"""Events the assessments context emits (overview section 2). Thin payload: ids only, never values (H data)."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class ResultRecorded(Event):
    aggregate_type: ClassVar[str] = "assessment_result"
    type: Literal["assessments.result.recorded"] = "assessments.result.recorded"
    assessment_result_id: UUID
    client_id: UUID
