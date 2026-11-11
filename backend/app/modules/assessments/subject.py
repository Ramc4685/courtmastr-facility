"""Assessments' side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). A merge
moves every entry to the survivor. Erasure deletes the client's entries: they are health data with no
retention duty (the audit rows keep that they existed, not the values)."""

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.assessments.models import AssessmentResult, AssessmentResultValue


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    for model in (AssessmentResult, AssessmentResultValue):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))


def _export(session: Session, client_id: UUID) -> dict:
    results = session.scalars(select(AssessmentResult).where(AssessmentResult.client_id == client_id))
    values = session.scalars(select(AssessmentResultValue).where(AssessmentResultValue.client_id == client_id))
    by_result: dict[UUID, list] = {}
    for v in values:
        by_result.setdefault(v.assessment_result_id, []).append(
            {"assessment_field_id": str(v.assessment_field_id), "value": str(v.value)})  # fmt: skip
    return {"assessment_results": [
        {"recorded_at": r.recorded_at.isoformat(), "note": r.note, "values": by_result.get(r.id, [])} for r in results
    ]}  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    session.execute(delete(AssessmentResultValue).where(AssessmentResultValue.client_id == client_id))
    gone = session.execute(delete(AssessmentResult).where(AssessmentResult.client_id == client_id)).rowcount
    return {"deleted_assessment_results": gone}


_TABLES = ("assessment_result", "assessment_result_value")
clients.merge.register_merge_handler("assessments", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("assessments", tables=_TABLES, export=_export, erase=_erase)
