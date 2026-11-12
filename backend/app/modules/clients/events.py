"""Events the clients context emits. Thin payloads: ids and the transition, no PII (overview 3.11)."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class ClientCreated(Event):
    aggregate_type: ClassVar[str] = "client"
    type: Literal["clients.client.created"] = "clients.client.created"
    client_id: UUID
    source: Literal["import"] | None = None  # set for a client created by a CSV import (automations skip it)
    import_job_id: UUID | None = None


class ClientUpdated(Event):
    aggregate_type: ClassVar[str] = "client"
    type: Literal["clients.client.updated"] = "clients.client.updated"
    client_id: UUID


class ClientDisabled(Event):
    aggregate_type: ClassVar[str] = "client"
    type: Literal["clients.client.disabled"] = "clients.client.disabled"
    client_id: UUID


class ClientMerged(Event):
    """Consumers re-point anything they hold by client id that the synchronous merge handlers did not cover."""

    aggregate_type: ClassVar[str] = "client"
    type: Literal["clients.client.merged"] = "clients.client.merged"
    client_id: UUID  # the merged (losing) record
    survivor_client_id: UUID


class RelationshipChanged(Event):
    aggregate_type: ClassVar[str] = "client_relationship"
    type: Literal["clients.relationship.changed"] = "clients.relationship.changed"
    relationship_id: UUID
    status: str
