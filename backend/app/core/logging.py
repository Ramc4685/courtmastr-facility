"""Structured JSON logs with trace_id; no PII (overview 3.17, security-baseline 2.3 and V7).

Every entry passes the redaction below, so a careless `extra=` or an exception that quotes a row cannot leak:
keys on the deny-list are masked at any depth, and every string (message, values, exception text) loses
emails, card numbers and long digit runs. **[test]** `tests/test_log_redaction.py`."""

import json
import logging
import re
import sys
import time
from typing import Any

from app.core import context

_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

# security-baseline 2.3. Matched as substrings of the lower-cased key ("x-api-key", "refreshTokens", "apikey"),
# so plurals and run-together names are caught; fail closed ("idempotency_key", "filename" go too).
_DENY_PARTS = (
    "password", "passwd", "passcode", "token", "secret", "authorization", "cookie", "email", "phone", "mobile",
    "birth", "name", "address", "signature", "card", "iban", "credential", "body", "medical", "key",
)  # fmt: skip
# Too short for a substring ("company", "shipping", "span"): matched as a whole word of the key instead.
_DENY_WORDS = {"pin", "pins", "pan", "pans", "dob", "cvc", "cvv", "ssn"}
_WORDS = re.compile(r"[A-Z]?[a-z0-9]{1,64}|[A-Z]{1,64}(?![a-z])")
_SPACE = re.compile(r"(\s+)")
# Kept whole before the digit scrub: a UUID (ids are what logs are for), and an ISO date with an optional time.
# A card cannot hide in a date: none starts with 19 or 20.
_KEEP = re.compile(
    r"(?<![0-9A-Fa-f-])([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"|(?:19|20)\d\d-[01]\d-[0-3]\d(?:[T ][0-2]\d:[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?(?:Z|[+-][0-2]\d:?[0-5]\d)?)?)"
    r"(?![0-9A-Fa-f-])"
)
_PG_DETAIL = re.compile(r"^[ \t]*(DETAIL|CONTEXT):[^\n]*", re.M)  # Postgres echoes the row: "Failing row contains"
# Fail closed and linear: any run of digits joined by whitespace, dashes, dots, slashes or underscores that holds
# 9 or more digits is masked, Luhn or not
# (phones, account and card numbers however grouped; a date and time may go too). No address regex: every
# whitespace-delimited token holding an @ is masked whole, however malformed.
_DIGIT_RUN = re.compile(r"\d[\d\s./_-]*")  # one greedy class: never backtracks
_STATIC = {"method", "status", "duration_ms"}  # written by our own code from fixed values: kept as they are
REDACTED, TRUNCATED = "[redacted]", "...[truncated]"
MAX_CHARS, MAX_DEPTH, MAX_ITEMS = 2048, 6, 100
MAX_EXC_CHARS = 16_384  # a traceback is our own text and needs its frames; still capped
_LOOKAHEAD = 256  # the scrub sees this far past the cut, so a value straddling it is masked whole first


def _denied(key: Any) -> bool:
    key = str(key)[:MAX_CHARS]
    lowered = key.lower()
    return any(part in lowered for part in _DENY_PARTS) or any(
        word.lower() in _DENY_WORDS for word in _WORDS.findall(key)
    )


def _mask_digits(match: re.Match) -> str:
    run = match.group()
    body = run.rstrip(" \t\r\n\f\v./_-")
    return "[digits]" + run[len(body) :] if sum(c.isdigit() for c in body) >= 9 else run


def scrub(value: str, limit: int = MAX_CHARS) -> str:
    cut = len(value) > limit
    value = value[: limit + _LOOKAHEAD]
    if "DETAIL:" in value or "CONTEXT:" in value:
        value = _PG_DETAIL.sub(r"\1: [dropped]", value)
    if "@" in value:
        value = "".join("[email]" if "@" in token else token for token in _SPACE.split(value))
    # split() with one group alternates free text (even indexes) and kept UUIDs and dates (odd indexes)
    parts = _KEEP.split(value)
    value = "".join(p if i % 2 else _DIGIT_RUN.sub(_mask_digits, p) for i, p in enumerate(parts))
    if not cut:
        return value
    # Drop the token touching the cut, and any digits or separators before it: half a value is still a value.
    kept = value[:limit].rsplit(maxsplit=1)
    return (kept[0] if len(kept) == 2 else "").rstrip("0123456789 +-.@") + TRUNCATED


def redact(value: Any, depth: int = 0) -> Any:
    if isinstance(value, (dict, list, tuple, set)) and depth >= MAX_DEPTH:
        return TRUNCATED
    if isinstance(value, dict):
        items = list(value.items())
        out = {scrub(str(k)): REDACTED if _denied(k) else redact(v, depth + 1) for k, v in items[:MAX_ITEMS]}
        return out | ({TRUNCATED: len(items) - MAX_ITEMS} if len(items) > MAX_ITEMS else {})
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        return [redact(v, depth + 1) for v in items[:MAX_ITEMS]] + ([TRUNCATED] if len(items) > MAX_ITEMS else [])
    if isinstance(value, str):
        return scrub(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return scrub(str(value))  # UUIDs, dates, objects: as their text, scrubbed like any other


class JsonFormatter(logging.Formatter):
    converter = time.gmtime  # logs are UTC, like everything else

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": context.request_id.get(),
        }
        try:
            entry["msg"] = scrub(record.getMessage())
            extra = {k: v for k, v in record.__dict__.items() if k not in _STANDARD}
            entry.update(redact({k: v for k, v in extra.items() if k not in _STATIC}))
            entry.update({k: extra[k] for k in _STATIC.intersection(extra)})
            if record.exc_info:
                entry["exc"] = scrub(self.formatException(record.exc_info), MAX_EXC_CHARS)
            return json.dumps(entry, default=str)
        except Exception:  # never fall back to Handler.handleError, which prints the raw msg and args
            return json.dumps(entry | {"msg": "[log record could not be formatted]"}, default=str)


# Loggers that bring their own handlers (uvicorn's dictConfig gives `uvicorn` a plain one with propagate False;
# Dramatiq's worker logs print actor arguments): taken over so every line goes through the formatter above.
_TAKEN_OVER = ("uvicorn", "uvicorn.error", "uvicorn.access", "dramatiq")


def configure(level: int = logging.INFO) -> None:
    logging.raiseExceptions = False
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for name in _TAKEN_OVER:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by the request log in app.core.api
