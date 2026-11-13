"""security-baseline V7 and 2.3: logs carry ids, never PII, secrets or card numbers, whatever a caller passes."""

import io
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import api
from app.core.db.platform import platform_engine
from app.core.db.session import app_engine
from app.core.logging import JsonFormatter

EMAIL, PHONE, PAN, DOB = "jane.doe@example.com", "2175550123", "4111 1111 1111 1111", "2014-03-09"
CORPUS = {
    "email": EMAIL, "contact_email": EMAIL, "phone": PHONE, "mobile_phone": PHONE, "first_name": "Jane",
    "last_name": "Doe", "display_name": "Jane Doe", "date_of_birth": DOB, "dob": DOB, "address_line1": "1 Main St",
    "password": "hunter2hunter2", "access_token": "fha_secret", "client_secret": "s3cr3t", "Authorization": "Bearer x",
    "cookie": "fh_session=abc", "card_number": PAN, "signature_png": "data:image/png;base64,AAAA",
}  # fmt: skip
LEAKS = (EMAIL, PHONE, PAN, "4111111111111111", DOB, "Jane", "1 Main St", "hunter2", "fha_secret", "s3cr3t",
         "Bearer x", "abc", "AAAA")  # fmt: skip


def _capture(logger_name: str) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger, stream


def _assert_clean(output: str) -> None:
    for leak in LEAKS:
        assert leak not in output, leak


def test_deny_listed_keys_are_masked_at_any_depth():
    logger, stream = _capture("test.redaction.keys")
    logger.info("event", extra={"tenant_id": "t-1", **CORPUS, "nested": {"list": [CORPUS], "inner": CORPUS}})
    entry = json.loads(stream.getvalue())
    _assert_clean(stream.getvalue())
    assert entry["tenant_id"] == "t-1"  # ids stay: they are what logs are for
    assert entry["email"] == "[redacted]" and entry["nested"]["list"][0]["password"] == "[redacted]"


def test_messages_and_values_are_scrubbed_of_emails_digit_runs_and_card_numbers():
    logger, stream = _capture("test.redaction.messages")
    logger.info("sent to %s / %s / card %s", EMAIL, PHONE, PAN, extra={"detail": f"from {EMAIL} card {PAN}"})
    logger.info("card 4111-1111-1111-1111 and 5555555555554444")
    _assert_clean(stream.getvalue())
    assert "5555555555554444" not in stream.getvalue()
    assert "sent to" in stream.getvalue()


def test_exception_text_is_scrubbed():
    logger, stream = _capture("test.redaction.exc")
    try:
        raise ValueError(f"bad row for {EMAIL}, card {PAN}")
    except ValueError:
        logger.exception("failed")
    _assert_clean(stream.getvalue())
    assert "ValueError" in stream.getvalue()


def test_engines_hide_bound_parameters():
    assert app_engine().hide_parameters and platform_engine().hide_parameters


def test_a_database_error_that_becomes_a_500_logs_no_values():
    """The bound value never reaches the log (hide_parameters), and Postgres's own echo of it in the error
    text (`invalid input syntax ... "jane.doe@example.com"`) is scrubbed by the formatter."""
    app = FastAPI()
    api.install(app)

    @app.get("/boom")
    def boom():
        with app_engine().connect() as conn:
            conn.execute(text("SELECT CAST(:v AS int), :p, :d"), {"v": EMAIL, "p": PHONE, "d": PAN})

    _, stream = _capture("app.request")
    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500 and response.json()["code"] == "internal-error"
    output = stream.getvalue()
    assert "unhandled error" in output and "DataError" in output
    assert "parameters hidden" in output  # hide_parameters, not only the formatter, kept the values out
    _assert_clean(output)
