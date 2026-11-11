"""Webhook event catalogue (ADR 0007 section 6, security-baseline 17.4): every subscribable event type with the
read permission a subscriber must hold and how to find the event's location for location-scoped subscribers.

An event type missing here is never delivered (operational events such as identity.locked stay internal). A
type without a locator reaches tenant-wide subscribers only: a location-limited creator cannot be shown it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.auth import system_principal

TEST_EVENT = "integrations.webhook.tested"


@dataclass(frozen=True)
class EventType:
    type: str
    permission: str | None  # None: configuration data any staff user may read (rbac-matrix section 1)
    description: str
    locate: Callable[[Session, dict], UUID | None] | None = None

    @property
    def context(self) -> str:
        return self.type.split(".", 1)[0]


def _location(_session: Session, payload: dict) -> UUID:
    return UUID(payload["location_id"])


def _client(session: Session, payload: dict) -> UUID:
    from app.modules import clients

    return clients.service.get(session, UUID(payload["client_id"])).home_location_id


def _billing(kind: str) -> Callable[[Session, dict], UUID]:
    def locate(session: Session, payload: dict) -> UUID:
        from app.modules import billing

        getter = billing.service.get_invoice if kind == "invoice" else billing.service.get_payment
        return getter(session, system_principal("webhooks"), UUID(payload[f"{kind}_id"]))["location_id"]

    return locate


CATALOGUE: dict[str, EventType] = {
    e.type: e
    for e in (
        EventType("platform.location.created", None, "A location was added.", _location),
        EventType("platform.staff_user.invited", "platform.staff_user.read", "A staff user was invited."),
        EventType("platform.staff_user.deactivated", "platform.staff_user.read", "A staff user was deactivated."),
        EventType("clients.client.created", "clients.client.read", "A client was created.", _client),
        EventType("billing.charge.created", "billing.charge.read", "A billing item was posted."),
        EventType("billing.charge.reversed", "billing.charge.read", "A billing item was reversed."),
        EventType("billing.invoice.issued", "billing.invoice.read", "An invoice was issued.", _billing("invoice")),
        EventType("billing.invoice.paid", "billing.invoice.read", "An invoice was paid in full.", _billing("invoice")),
        EventType(
            "billing.payment.processing", "billing.payment.read", "A payment is processing.", _billing("payment")
        ),
        EventType("billing.payment.succeeded", "billing.payment.read", "A payment succeeded.", _billing("payment")),
        EventType("billing.payment.failed", "billing.payment.read", "A payment failed.", _billing("payment")),
        EventType("billing.payment.refunded", "billing.payment.read", "A payment was refunded.", _billing("payment")),
    )
}
