"""Notification port. Contexts call send(); the adapter is wired by configuration in app.bootstrap.

This is the thin slice that ships ahead of the engagement module (overview section 6 item 4): no consent
gate, no preferences, no delivery log. Engagement replaces the adapter, not the callers.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from string import Template
from typing import Any, Protocol

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationTemplate:
    """Plain-text email template with $name placeholders (string.Template: substitution only, no logic)."""

    subject: str
    body: str

    def render(self, data: Mapping[str, Any]) -> tuple[str, str]:
        return Template(self.subject).substitute(data), Template(self.body).substitute(data)


class Notifier(Protocol):
    def deliver(self, session: Session, to: str, subject: str, body: str) -> None: ...


TEMPLATES: dict[str, NotificationTemplate] = {}
_notifier: Notifier | None = None


def register_template(key: str, *, subject: str, body: str) -> None:
    """Called at import time by the context that owns the message; keys are `<context>.<what>`."""
    if key in TEMPLATES:
        raise ValueError(f"notification template {key} is already registered")
    TEMPLATES[key] = NotificationTemplate(subject, body)


def configure(notifier: Notifier) -> None:
    global _notifier
    _notifier = notifier


def send(session: Session, template_key: str, to: str, data: Mapping[str, Any]) -> None:
    """Notify one address. Goes out only if the caller's transaction commits. An unknown key or a missing
    placeholder is a programming error and raises here, in the request, not later in delivery."""
    subject, body = TEMPLATES[template_key].render(data)
    assert _notifier is not None, "no notification adapter configured"
    _notifier.deliver(session, to, subject, body)
