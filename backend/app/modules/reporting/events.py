"""Events the reporting context emits (overview section 2). Thin payload: ids only."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class ExportCompleted(Event):
    aggregate_type: ClassVar[str] = "export_job"
    type: Literal["reporting.export.completed"] = "reporting.export.completed"
    export_job_id: UUID
    requested_by_staff_user_id: UUID
