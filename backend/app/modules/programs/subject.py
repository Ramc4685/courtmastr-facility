"""Programs' side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). Where
both records hold a place in the same session or program group the merged record's place is cancelled
(`client_merged`, billing untouched) and its seat or place released; everything else, payer references
included, moves to the survivor. Erasure keeps enrolments and attendance marks (history and money) without
their free text and takes the client off every waitlist."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.programs import groups, service
from app.modules.programs.models import Attendance, Enrollment, RegistrationCheckout, WaitlistEntry

_LIVE = ("pending", "enrolled")
_QUEUED = ("waiting", "offered")


def _target(row) -> tuple[str, UUID]:
    return ("group", row.program_group_id) if row.program_group_id else ("session", row.session_id)


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    e, w = Enrollment, WaitlistEntry
    held = {_target(r) for r in session.scalars(select(e).where(e.client_id == survivor_id, e.status.in_(_LIVE)))}
    for row in session.scalars(select(e).where(e.client_id == loser_id, e.status.in_(_LIVE))).all():
        if _target(row) in held:
            if row.program_group_id:
                groups.cancel(session, None, row, kind="client_merged", disposition="none", reason=None, actor="system")
            else:
                service._cancel(session, row, "client_merged")
    queued = {_target(r) for r in session.scalars(select(w).where(w.client_id == survivor_id, w.status.in_(_QUEUED)))}
    for row in session.scalars(select(w).where(w.client_id == loser_id, w.status.in_(_QUEUED))).all():
        if _target(row) in held or _target(row) in queued:
            row.status, row.removed_reason = "removed", "client_merged"
    session.flush()
    for model in (Enrollment, Attendance, WaitlistEntry):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))
    for model in (Enrollment, WaitlistEntry, RegistrationCheckout):
        session.execute(update(model).where(model.payer_client_id == loser_id).values(payer_client_id=survivor_id))


def _export(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(select(Enrollment).where(Enrollment.client_id == client_id))
    marks = session.scalars(select(Attendance).where(Attendance.client_id == client_id))
    queue = session.scalars(select(WaitlistEntry).where(WaitlistEntry.client_id == client_id))
    return {
        "enrollments": [
            {"session_id": r.session_id and str(r.session_id), "program_group_id": r.program_group_id and str(r.program_group_id),
             "status": r.status, "enrolled_at": r.enrolled_at and r.enrolled_at.isoformat(),
             "registrant_comment": r.registrant_comment}
            for r in rows
        ],
        "attendance": [{"session_id": str(r.session_id), "status": r.status} for r in marks],
        "waitlist": [
            {"session_id": r.session_id and str(r.session_id), "program_group_id": r.program_group_id and str(r.program_group_id),
             "status": r.status, "queued_at": r.queued_at.isoformat()}
            for r in queue
        ],
    }  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    kept = session.execute(
        update(Enrollment).where(Enrollment.client_id == client_id).values(cancel_reason=None, registrant_comment=None)
    ).rowcount
    w = WaitlistEntry
    left = session.execute(
        update(w).where(w.client_id == client_id, w.status.in_(_QUEUED)).values(status="removed", removed_reason="erased")
    ).rowcount  # fmt: skip
    session.execute(
        update(RegistrationCheckout).where(RegistrationCheckout.payer_client_id == client_id).values(comment=None)
    )
    return {"retained_enrollments": kept, "removed_waitlist_entries": left}


_TABLES = ("enrollment", "attendance", "waitlist_entry", "registration_checkout")
clients.merge.register_merge_handler("programs", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("programs", tables=_TABLES, export=_export, erase=_erase)
