"""Request and response models of the programs session slice (docs/api/openapi-programs.yaml)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401

Reason = Annotated[str, StringConstraints(max_length=500)]


class EnrollmentCreate(In):
    session_id: UUID
    client_id: UUID
    client_package_id: UUID | None = None  # the package that pays for the place (pricing becomes `entitlement`)


class EnrollmentCancel(In):
    cancel_kind: Literal["early", "late", "staff_removed"] = "staff_removed"
    reason: Reason | None = None


class EnrollmentOut(Out):
    id: UUID
    location_id: UUID
    client_id: UUID
    target_kind: str
    session_id: UUID | None
    status: Literal["pending", "enrolled", "cancelled"]
    pricing: str
    channel: str
    enrolled_at: datetime | None
    cancelled_at: datetime | None
    cancel_kind: str | None


class Participant(Out):
    enrollment_id: UUID
    client_id: UUID
    client_name: str
    enrolled_at: datetime | None
    channel: str
    attendance: Literal["scheduled", "attended", "no_show", "excused"]


class Roster(Out):
    session_id: UUID
    capacity: int
    booked_count: int
    waiting_count: int
    participants: list[Participant]


class Mark(In):
    enrollment_id: UUID
    status: Literal["attended", "no_show", "excused"]


class AttendancePut(In):
    marks: Annotated[list[Mark], Field(min_length=1, max_length=500)]


class WaitlistCreate(In):
    session_id: UUID
    client_id: UUID
    mode: Literal["manual", "auto_promote"] = "auto_promote"


class WaitlistOut(Out):
    id: UUID
    location_id: UUID
    client_id: UUID
    session_id: UUID | None
    status: Literal["waiting", "offered", "promoted", "expired", "removed"]
    mode: str
    queued_at: datetime
    position: int | None
    promoted_enrollment_id: UUID | None
