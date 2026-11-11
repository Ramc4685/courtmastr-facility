"""Outbox subscribers. The fan-out needs the outbox event id (it becomes the webhook event id receivers dedupe
on), which `@handles` does not pass, so it is one plain tenant actor registered for every catalogue type.
Idempotency comes from the unique (endpoint, event) key on webhook_delivery."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.events import SUBSCRIBERS, handles
from app.core.jobs import tenant_actor
from app.modules.integrations import service
from app.modules.integrations.catalogue import CATALOGUE


@tenant_actor(actor_name="integrations.webhook_fan_out")
def webhook_fan_out(session: Session, event_id: str, payload: dict) -> None:
    service.fan_out(session, UUID(event_id), payload)


for _event_type in CATALOGUE:
    SUBSCRIBERS[_event_type].append(webhook_fan_out)


@handles("platform.staff_user.deactivated")
def disable_endpoints_of_deactivated_creator(session: Session, payload: dict) -> None:
    service.reevaluate_creator(session, UUID(payload["staff_user_id"]))
