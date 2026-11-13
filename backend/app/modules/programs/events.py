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


# Program-group targets share the event types above; the payload carries program_group_id instead of session_id
# (data-model-programs 2.x "Emits": target ids per target kind). Consumers read payload keys, not classes.
class _GroupEnrollmentEvent(Event):
    aggregate_type: ClassVar[str] = "enrollment"
    enrollment_id: UUID
    program_group_id: UUID
    client_id: UUID
    location_id: UUID


class GroupEnrollmentCreated(_GroupEnrollmentEvent):
    type: Literal["programs.enrollment.created"] = "programs.enrollment.created"


class GroupEnrollmentCancelled(_GroupEnrollmentEvent):
    type: Literal["programs.enrollment.cancelled"] = "programs.enrollment.cancelled"
    cancel_kind: str


class GroupWaitlistPromoted(Event):
    aggregate_type: ClassVar[str] = "waitlist_entry"
    type: Literal["programs.waitlist.promoted"] = "programs.waitlist.promoted"
    enrollment_id: UUID
    program_group_id: UUID
    client_id: UUID
    waitlist_entry_id: UUID


class GroupCompleted(Event):
    aggregate_type: ClassVar[str] = "program_group"
    type: Literal["programs.group.completed"] = "programs.group.completed"
    program_group_id: UUID
    location_id: UUID


class EnrollmentMoved(Event):
    aggregate_type: ClassVar[str] = "enrollment"
    type: Literal["programs.enrollment.moved"] = "programs.enrollment.moved"
    enrollment_id: UUID
    from_program_group_id: UUID
    program_group_id: UUID
    client_id: UUID
    location_id: UUID


class FormSubmitted(Event):
    aggregate_type: ClassVar[str] = "form_submission"
    type: Literal["programs.form.submitted"] = "programs.form.submitted"
    form_submission_id: UUID
    form_id: UUID
    location_id: UUID
    status: str
