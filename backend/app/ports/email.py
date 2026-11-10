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


def _deliver(message: EmailMessage) -> None:
    try:
        assert _provider is not None, "no email adapter configured"
        _provider.send(message)
    except Exception:
        # The transaction is already committed; a lost email is recoverable (the user asks again).
        log.exception("email delivery failed")


def send_after_commit(session: Session, message: EmailMessage) -> None:
    """Queue a message that goes out only if the transaction commits, and off the request's critical path
    (so response time does not reveal whether an address exists)."""
    session.info.setdefault("after_commit", []).append(lambda: _deliver(message))
