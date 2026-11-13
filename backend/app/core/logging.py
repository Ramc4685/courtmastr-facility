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

# security-baseline 2.3, matched against each word of a key ("contact_email", "accessToken" -> email, token).
_DENY = {
    "password", "passwd", "passcode", "pin", "token", "secret", "authorization", "cookie", "email", "emails",
    "phone", "mobile", "dob", "birth", "name", "address", "signature", "card", "pan", "cvc", "cvv", "iban",
    "ssn", "credential", "body", "medical",
}  # fmt: skip
_WORDS = re.compile(r"[A-Z]?[a-z0-9]{1,64}|[A-Z]{1,64}(?![a-z])")
_SPACE = re.compile(r"(\s+)")
# Fail closed and linear: any run of digits joined by spaces or dashes that holds 9 or more digits is masked
# (phones, account and card numbers however grouped; a date and time may go too). No address regex: every
# whitespace-delimited token holding an @ is masked whole, however malformed.
_DIGIT_RUN = re.compile(r"\d[\d -]*\d")
_STATIC = {"method", "status", "duration_ms"}  # written by our own code from fixed values: kept as they are
REDACTED, TRUNCATED = "[redacted]", "...[truncated]"
MAX_CHARS, MAX_DEPTH, MAX_ITEMS = 2048, 6, 100
MAX_EXC_CHARS = 16_384  # a traceback is our own text and needs its frames; still capped
_LOOKAHEAD = 256  # the scrub sees this far past the cut, so a value straddling it is masked whole first


def _denied(key: str) -> bool:
    return any(word.lower() in _DENY for word in _WORDS.findall(str(key)[:MAX_CHARS]))


def _mask_digits(match: re.Match) -> str:
    run = match.group()
    return "[digits]" if sum(c.isdigit() for c in run) >= 9 else run


def scrub(value: str, limit: int = MAX_CHARS) -> str:
    cut = len(value) > limit
    value = value[: limit + _LOOKAHEAD]
    if "@" in value:
        value = "".join("[email]" if "@" in token else token for token in _SPACE.split(value))
    value = _DIGIT_RUN.sub(_mask_digits, value)
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
        out = {k: REDACTED if _denied(k) else redact(v, depth + 1) for k, v in items[:MAX_ITEMS]}
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
            "msg": scrub(record.getMessage()),
            "trace_id": context.request_id.get(),
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in _STANDARD}
        entry.update(redact({k: v for k, v in extra.items() if k not in _STATIC}))
        entry.update({k: extra[k] for k in _STATIC.intersection(extra)})
        if record.exc_info:
            entry["exc"] = scrub(self.formatException(record.exc_info), MAX_EXC_CHARS)
        return json.dumps(entry, default=str)


def configure(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by the request log in app.core.api
