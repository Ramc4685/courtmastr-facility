"""Programs' side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). Where
both records hold a place in the same session the merged record's place is cancelled (`client_merged`) and
its seat released; everything else moves to the survivor. Erasure keeps enrolments and attendance marks
(session history) and takes the client off every waitlist."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.programs import service
from app.modules.programs.models import Attendance, Enrollment, WaitlistEntry

_LIVE = ("pending", "enrolled")
_QUEUED = ("waiting", "offered")


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    e, w = Enrollment, WaitlistEntry
    held = set(session.scalars(select(e.session_id).where(e.client_id == survivor_id, e.status.in_(_LIVE))))
    for row in session.scalars(select(e).where(e.client_id == loser_id, e.status.in_(_LIVE))).all():
        if row.session_id in held:
            service._cancel(session, row, "client_merged")
    queued = set(session.scalars(select(w.session_id).where(w.client_id == survivor_id, w.status.in_(_QUEUED))))
    for row in session.scalars(select(w).where(w.client_id == loser_id, w.status.in_(_QUEUED))).all():
        if row.session_id in held or row.session_id in queued:
            row.status, row.removed_reason = "removed", "client_merged"
    session.flush()
    for model in (Enrollment, Attendance, WaitlistEntry):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))


def _export(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(select(Enrollment).where(Enrollment.client_id == client_id))
    marks = session.scalars(select(Attendance).where(Attendance.client_id == client_id))
    return {
        "enrollments": [
            {"session_id": str(r.session_id), "status": r.status, "enrolled_at": r.enrolled_at.isoformat()}
            for r in rows
        ],
        "attendance": [{"session_id": str(r.session_id), "status": r.status} for r in marks],
    }  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    kept = session.execute(
        update(Enrollment).where(Enrollment.client_id == client_id).values(cancel_reason=None)
    ).rowcount
    w = WaitlistEntry
    left = session.execute(
        update(w).where(w.client_id == client_id, w.status.in_(_QUEUED)).values(status="removed", removed_reason="erased")
    ).rowcount  # fmt: skip
    return {"retained_enrollments": kept, "removed_waitlist_entries": left}


_TABLES = ("enrollment", "attendance", "waitlist_entry")
clients.merge.register_merge_handler("programs", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("programs", tables=_TABLES, export=_export, erase=_erase)
