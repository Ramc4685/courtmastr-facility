"""Events the platform context emits. Thin payloads: ids and the transition, no PII (overview 3.11)."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class TenantCreated(Event):
    aggregate_type: ClassVar[str] = "tenant"
    type: Literal["platform.tenant.created"] = "platform.tenant.created"
    tenant_id: UUID


class LocationCreated(Event):
    aggregate_type: ClassVar[str] = "location"
    type: Literal["platform.location.created"] = "platform.location.created"
    location_id: UUID


class StaffUserInvited(Event):
    aggregate_type: ClassVar[str] = "staff_user"
    type: Literal["platform.staff_user.invited"] = "platform.staff_user.invited"
    staff_user_id: UUID
    role_id: UUID


class StaffUserDeactivated(Event):
    aggregate_type: ClassVar[str] = "staff_user"
    type: Literal["platform.staff_user.deactivated"] = "platform.staff_user.deactivated"
    staff_user_id: UUID


class IdentityLocked(Event):
    aggregate_type: ClassVar[str] = "identity"
    type: Literal["platform.identity.locked"] = "platform.identity.locked"
    identity_id: UUID
