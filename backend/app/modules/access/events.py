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


class CheckedOut(_CheckInEvent):
    type: Literal["access.check_in.checked_out"] = "access.check_in.checked_out"


class CheckInSessionBooked(_CheckInEvent):
    type: Literal["access.check_in.session_booked"] = "access.check_in.session_booked"
    enrollment_id: UUID
    session_id: UUID


class CheckInStationChanged(Event):
    aggregate_type: ClassVar[str] = "check_in_station"
    type: Literal["access.check_in_station.changed"] = "access.check_in_station.changed"
    check_in_station_id: UUID
    location_id: UUID


class IdCardTemplateChanged(Event):
    aggregate_type: ClassVar[str] = "id_card_template"
    type: Literal["access.id_card_template.changed"] = "access.id_card_template.changed"
    id_card_template_id: UUID


class CredentialAssigned(Event):
    aggregate_type: ClassVar[str] = "credential"
    type: Literal["access.credential.assigned"] = "access.credential.assigned"
    credential_id: UUID
    client_id: UUID
    kind: str


class ClientAccessModeChanged(Event):
    aggregate_type: ClassVar[str] = "client_access"
    type: Literal["access.client_access.changed"] = "access.client_access.changed"
    client_id: UUID
    access_mode: str
