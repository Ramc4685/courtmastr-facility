"""Email port. Modules call send_after_commit(); the adapter is wired by configuration in app.bootstrap."""

import logging
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> None: ...


_provider: EmailProvider | None = None


def configure(provider: EmailProvider) -> None:
    global _provider
    _provider = provider


def _deliver(message: EmailMessage) -> bool:
    """Hand the message to the adapter now; True once it accepted it. Used after commit only."""
    try:
        assert _provider is not None, "no email adapter configured"
        _provider.send(message)
        return True
    except Exception:
        # The transaction is already committed; a lost email is recoverable (the user asks again).
        log.exception("email delivery failed")
        return False


def send_after_commit(session: Session, message: EmailMessage) -> None:
    """Queue a message that goes out only if the transaction commits, and off the request's critical path
    (so response time does not reveal whether an address exists)."""
    session.info.setdefault("after_commit", []).append(lambda: _deliver(message))


def send_after_commit_then(session: Session, message: EmailMessage, on_sent) -> None:
    """send_after_commit, then `on_sent()` once the adapter accepted the message (a caller that must know it was
    handed off, and retries otherwise: door codes)."""
    session.info.setdefault("after_commit", []).append(lambda: _deliver(message) and on_sent())
