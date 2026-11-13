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
from app.core.pan import mask_card_numbers

_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

# security-baseline 2.3, matched against each word of a key ("contact_email", "accessToken" -> email, token).
_DENY = {
    "password", "passwd", "passcode", "pin", "token", "secret", "authorization", "cookie", "email", "emails",
    "phone", "mobile", "dob", "birth", "name", "address", "signature", "card", "pan", "cvc", "cvv", "iban",
    "ssn", "credential", "body", "medical",
}  # fmt: skip
_WORDS = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DIGITS = re.compile(r"\d{9,}")  # phone numbers, account and card numbers typed without separators
REDACTED = "[redacted]"


def _denied(key: str) -> bool:
    return any(word.lower() in _DENY for word in _WORDS.findall(str(key)))


def scrub(value: str) -> str:
    return _DIGITS.sub("[digits]", mask_card_numbers(_EMAIL.sub("[email]", value)))


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED if _denied(k) else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(v) for v in value]
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
        entry.update(redact({k: v for k, v in record.__dict__.items() if k not in _STANDARD}))
        if record.exc_info:
            entry["exc"] = scrub(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


def configure(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by the request log in app.core.api
