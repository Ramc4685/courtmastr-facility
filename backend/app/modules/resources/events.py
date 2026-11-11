"""Events the resources context emits. Thin payloads: ids and the transition (overview 3.11)."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _ResourceEvent(Event):
    aggregate_type: ClassVar[str] = "resource"
    resource_id: UUID
    location_id: UUID


class ResourceCreated(_ResourceEvent):
    type: Literal["resources.resource.created"] = "resources.resource.created"


class ResourceArchived(_ResourceEvent):
    type: Literal["resources.resource.archived"] = "resources.resource.archived"


class ResourceTreeChanged(_ResourceEvent):
    type: Literal["resources.resource.tree_changed"] = "resources.resource.tree_changed"
    parent_id: UUID | None
