"""Programs' side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). Where
both records hold a place in the same session or program group the merged record's place is cancelled
(`client_merged`, billing untouched) and its seat or place released; everything else, payer references
included, moves to the survivor. Erasure keeps enrolments and attendance marks (history and money) without
their free text and takes the client off every waitlist."""

from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.programs import forms, groups, service
from app.modules.programs.models import (
    Attendance,
    Enrollment,
    FormAnswer,
    FormSubmission,
    FormVersion,
    RegistrationCheckout,
    WaitlistEntry,
)

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
    for column in ("account_client_id", "registrant_client_id"):
        col = getattr(FormSubmission, column)
        session.execute(update(FormSubmission).where(col == loser_id).values({column: survivor_id}))


def _submissions(client_id: UUID):
    f = FormSubmission
    return select(f).where(or_(f.account_client_id == client_id, f.registrant_client_id == client_id))


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
        "form_submissions": [_submission_export(session, r) for r in session.scalars(_submissions(client_id))],
        "waitlist": [
            {"session_id": r.session_id and str(r.session_id), "program_group_id": r.program_group_id and str(r.program_group_id),
             "status": r.status, "queued_at": r.queued_at.isoformat()}
            for r in queue
        ],
    }  # fmt: skip


def _submission_export(session: Session, r: FormSubmission) -> dict:
    schema = session.get(FormVersion, r.form_version_id).schema
    answers = session.scalars(select(FormAnswer).where(FormAnswer.form_submission_id == r.id).order_by(FormAnswer.id))
    return {
        "form_id": str(r.form_id), "confirmation_no": r.confirmation_no, "status": r.status,
        "contact_name": r.contact_name, "contact_email": r.contact_email, "contact_phone": r.contact_phone,
        "submitted_at": r.submitted_at.isoformat(),
        "answers": [{"item_key": a.item_key, "label": forms._label(schema, a.item_key, a.choice_key),
                     "text_value": a.text_value, "quantity": a.quantity} for a in answers],
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
    # Form registrations keep their money and counts; the contact details and typed answers go.
    ids = [r.id for r in session.scalars(_submissions(client_id))]
    if ids:
        session.execute(
            update(FormSubmission).where(FormSubmission.id.in_(ids))
            .values(contact_name="Erased", contact_email=forms.ERASED_EMAIL, contact_phone=None)
        )  # fmt: skip
        session.execute(update(FormAnswer).where(FormAnswer.form_submission_id.in_(ids)).values(text_value=None))
    return {"retained_enrollments": kept, "removed_waitlist_entries": left, "erased_form_submissions": len(ids)}


_TABLES = ("enrollment", "attendance", "waitlist_entry", "registration_checkout", "form_submission")
clients.merge.register_merge_handler("programs", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("programs", tables=_TABLES, export=_export, erase=_erase)
# Anonymous public-link registrations have no client to request against: they age out instead (README).
platform.retention.register_purge("programs_anonymous_form_submissions", forms.purge_anonymous)
