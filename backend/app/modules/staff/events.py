"""Events the staff context emits (overview section 2). Thin payloads: ids and the transition."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class TrainerCreated(Event):
    aggregate_type: ClassVar[str] = "staff_payee"
    type: Literal["staff.trainer.created"] = "staff.trainer.created"
    staff_payee_id: UUID
    resource_id: UUID
    location_id: UUID


class TimeEntryClosed(Event):
    aggregate_type: ClassVar[str] = "time_entry"
    type: Literal["staff.time_entry.closed"] = "staff.time_entry.closed"
    time_entry_id: UUID
    staff_user_id: UUID
    location_id: UUID


class PayrollRunFinalized(Event):
    aggregate_type: ClassVar[str] = "payroll_run"
    type: Literal["staff.payroll_run.finalized"] = "staff.payroll_run.finalized"
    payroll_run_id: UUID
