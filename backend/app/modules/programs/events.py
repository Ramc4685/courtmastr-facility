"""Events the programs slice emits. Thin payloads: ids and the transition."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _EnrollmentEvent(Event):
    aggregate_type: ClassVar[str] = "enrollment"
    enrollment_id: UUID
    session_id: UUID
    client_id: UUID


class EnrollmentCreated(_EnrollmentEvent):
    type: Literal["programs.enrollment.created"] = "programs.enrollment.created"


class EnrollmentCancelled(_EnrollmentEvent):
    type: Literal["programs.enrollment.cancelled"] = "programs.enrollment.cancelled"
    cancel_kind: str


class EnrollmentAttended(_EnrollmentEvent):
    type: Literal["programs.enrollment.attended"] = "programs.enrollment.attended"


class WaitlistPromoted(_EnrollmentEvent):
    aggregate_type: ClassVar[str] = "waitlist_entry"
    type: Literal["programs.waitlist.promoted"] = "programs.waitlist.promoted"
    waitlist_entry_id: UUID
