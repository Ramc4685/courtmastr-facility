"""Notification adapters: a no-op and plain-text email through the existing email port."""

from sqlalchemy.orm import Session

from app.ports.email import EmailMessage, send_after_commit


class NoopNotifier:
    def deliver(self, session: Session, to: str, subject: str, body: str) -> None:
        pass


class EmailNotifier:
    def deliver(self, session: Session, to: str, subject: str, body: str) -> None:
        send_after_commit(session, EmailMessage(to, subject, body))
