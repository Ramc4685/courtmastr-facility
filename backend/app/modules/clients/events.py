"""Events the clients context emits. Thin payloads: ids and the transition, no PII (overview 3.11)."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class ClientCreated(Event):
    aggregate_type: ClassVar[str] = "client"
    type: Literal["clients.client.created"] = "clients.client.created"
    client_id: UUID
