"""Events the access context emits (overview section 2). Ids and the transition only."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _CheckInEvent(Event):
    aggregate_type: ClassVar[str] = "check_in"
    check_in_id: UUID
    client_id: UUID
    location_id: UUID


class CheckInGranted(_CheckInEvent):
    type: Literal["access.check_in.granted"] = "access.check_in.granted"


class CheckInDenied(_CheckInEvent):
    type: Literal["access.check_in.denied"] = "access.check_in.denied"
    denial_reason: str


class CredentialAssigned(Event):
    aggregate_type: ClassVar[str] = "credential"
    type: Literal["access.credential.assigned"] = "access.credential.assigned"
    credential_id: UUID
    client_id: UUID
    kind: str
