"""Activity: note subjects, notes (CLI-09), tasks (CLI-10), alerts (CLI-20) and the profile timeline (CLI-11).

Staff only; none of this reaches the portal. Own reach: notes and alerts follow the client's own predicate
(service.load); tasks are own when the caller is the assignee (rbac-matrix 3.2).
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.audit import AuditEvent
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import platform
from app.modules.clients import service
from app.modules.clients.models import Client, ClientAlert, ClientNote, ClientTask, NoteSubject
from app.ports import notifications

notifications.register_template(
    "clients.task_reminder",
    subject="$app: task due $due",
    body="Hello,\n\nA client task assigned to you is due $due: $subject (client: $client).\n\n$url",
)


# --- note subjects -------------------------------------------------------------------------------------------


def list_note_subjects(session: Session, principal: Principal) -> list[NoteSubject]:
    authorize(principal, "clients.activity.read")
    return list(session.scalars(select(NoteSubject).order_by(func.lower(NoteSubject.label))))


def create_note_subject(session: Session, principal: Principal, data: dict) -> NoteSubject:
    authorize(principal, "clients.config.manage")
    row = NoteSubject(**data)
    session.add(row)
    session.flush()
    audit.record(session, "clients.config.manage", row, changes={"label": [None, row.label]})
    return row


def update_note_subject(session: Session, principal: Principal, subject_id: UUID, data: dict) -> NoteSubject:
    authorize(principal, "clients.config.manage")
    row = session.get(NoteSubject, subject_id) or service._not_found()
    for key, value in data.items():
        if value is None:
            raise ValidationFailed(f"{key} cannot be null.", pointer=f"/{key}")
        setattr(row, key, value)
    audit.record(session, "clients.config.manage", row, changes=audit.diff(row))
    session.flush()
    return row


def delete_note_subject(session: Session, principal: Principal, subject_id: UUID) -> None:
    authorize(principal, "clients.config.manage")
    row = session.get(NoteSubject, subject_id) or service._not_found()
    used = session.scalar(select(func.count()).where(ClientNote.note_subject_id == row.id)) or session.scalar(
        select(func.count()).where(ClientTask.note_subject_id == row.id)
    )
    if used:
        raise Conflict("This subject is in use; deactivate it instead.", code="in-use")
    audit.record(session, "clients.config.manage", row, changes={"deleted": True})
    session.delete(row)
    session.flush()


def _check_subject(session: Session, data: dict, current: tuple | None = None) -> None:
    """Exactly one of note_subject_id (an active list entry) or subject_text."""
    subject_id = data.get("note_subject_id", current[0] if current else None)
    text = data.get("subject_text", current[1] if current else None)
    if (subject_id is None) == (text is None):
        raise ValidationFailed("Give either a subject from the list or a subject text.", pointer="/note_subject_id")
    if "note_subject_id" in data and subject_id is not None:
        row = session.get(NoteSubject, subject_id)
        if row is None or not row.is_active:
            raise ValidationFailed("Unknown subject.", pointer="/note_subject_id")


def _check_staff(session: Session, staff_user_id: UUID | None, pointer: str) -> None:
    if staff_user_id is not None and not platform.service.staff_user_exists(session, staff_user_id):
        raise ValidationFailed("Unknown staff user.", pointer=pointer)


# --- notes ---------------------------------------------------------------------------------------------------


def list_notes(session: Session, principal: Principal, client_id: UUID, query: ListQuery) -> dict:
    client = service.load(session, principal, client_id, "clients.activity.read")
    return paginate(
        session, select(ClientNote).where(ClientNote.client_id == client.id), query, id_column=ClientNote.id,
        sort_fields={"occurred_at": ClientNote.occurred_at}, default_sort="-occurred_at",
        filter_fields={"kind": ClientNote.kind, "staff_user_id": ClientNote.staff_user_id},
        search=(ClientNote.subject_text, ClientNote.body),
    )  # fmt: skip


def create_note(session: Session, principal: Principal, client_id: UUID, data: dict) -> ClientNote:
    client = service.load(session, principal, client_id, "clients.activity.write")
    _check_subject(session, data)
    _check_staff(session, data.get("staff_user_id"), "/staff_user_id")
    if data.get("location_id") and not platform.service.location_exists(session, data["location_id"]):
        raise ValidationFailed("Unknown location.", pointer="/location_id")
    if principal.staff_user_id is None and data.get("staff_user_id") is None:
        raise ValidationFailed("Say which staff user performed this.", pointer="/staff_user_id")
    row = ClientNote(
        client_id=client.id, **{k: v for k, v in data.items() if v is not None and k != "staff_user_id"},
        staff_user_id=data.get("staff_user_id") or principal.staff_user_id,
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(
        session, "clients.activity.write", row, location_id=row.location_id, changes={"kind": [None, row.kind]}
    )
    return row


def _note(session: Session, principal: Principal, note_id: UUID, key: str) -> ClientNote:
    row = session.get(ClientNote, note_id)
    if row is None:
        raise NotFound()
    service.load(session, principal, row.client_id, key)
    return row


def update_note(session: Session, principal: Principal, note_id: UUID, data: dict) -> ClientNote:
    row = _note(session, principal, note_id, "clients.activity.write")
    if "note_subject_id" in data or "subject_text" in data:
        _check_subject(session, data, (row.note_subject_id, row.subject_text))
    for key, value in data.items():
        if value is None and key in ("kind", "occurred_at"):
            raise ValidationFailed(f"{key} cannot be null.", pointer=f"/{key}")
        setattr(row, key, value)
    audit.record(session, "clients.activity.write", row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def delete_note(session: Session, principal: Principal, note_id: UUID) -> None:
    authorize(principal, "clients.activity.delete")
    row = _note(session, principal, note_id, "clients.activity.read")
    audit.record(session, "clients.activity.delete", row, location_id=row.location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()


# --- tasks ---------------------------------------------------------------------------------------------------


def _task_reach(principal: Principal):
    authorize(principal, "clients.task.manage")
    if principal.kind == "system" or principal.permissions.get("clients.task.manage") == "all":
        return None
    return ClientTask.assignee_staff_user_id == principal.staff_user_id


def list_tasks(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Filters: client_id, assignee_staff_user_id, status; `overdue=true` for open tasks past their due date."""
    clause = _task_reach(principal)
    filters = dict(query.filters)
    overdue = filters.pop("overdue", None)
    stmt = select(ClientTask)
    if clause is not None:
        stmt = stmt.where(clause)
    if overdue == "true":
        stmt = stmt.where(ClientTask.status.in_(("open", "in_progress")), ClientTask.due_on < clock.now().date())
    return paginate(
        session, stmt, ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters),
        id_column=ClientTask.id, sort_fields={"created_at": ClientTask.created_at}, default_sort="-created_at",
        filter_fields={
            "client_id": ClientTask.client_id, "assignee_staff_user_id": ClientTask.assignee_staff_user_id,
            "status": ClientTask.status,
        },
        search=(ClientTask.subject_text, ClientTask.body),
    )  # fmt: skip


def create_task(session: Session, principal: Principal, data: dict) -> ClientTask:
    _task_reach(principal)
    try:
        client = service.load(session, principal, data["client_id"], "clients.activity.write")
    except NotFound:
        raise ValidationFailed("Unknown client.", pointer="/client_id") from None
    service._require_live(client)
    _check_subject(session, data)
    assignee = data.get("assignee_staff_user_id") or principal.staff_user_id
    if assignee is None:
        raise ValidationFailed("Choose an assignee.", pointer="/assignee_staff_user_id")
    _check_staff(session, assignee, "/assignee_staff_user_id")
    if principal.permissions.get("clients.task.manage") == "own" and assignee != principal.staff_user_id:
        raise ValidationFailed("You can only assign tasks to yourself.", pointer="/assignee_staff_user_id")
    row = ClientTask(**{k: v for k, v in data.items() if v is not None} | {"assignee_staff_user_id": assignee})
    session.add(row)
    session.flush()
    audit.record(session, "clients.task.manage", row, changes={"status": [None, "open"]})
    return row


def update_task(session: Session, principal: Principal, task_id: UUID, data: dict) -> ClientTask:
    clause = _task_reach(principal)
    row = session.get(ClientTask, task_id)
    if row is None or (clause is not None and row.assignee_staff_user_id != principal.staff_user_id):
        raise NotFound()
    if "note_subject_id" in data or "subject_text" in data:
        _check_subject(session, data, (row.note_subject_id, row.subject_text))
    if "assignee_staff_user_id" in data:
        if data["assignee_staff_user_id"] is None:
            raise ValidationFailed("assignee cannot be null.", pointer="/assignee_staff_user_id")
        _check_staff(session, data["assignee_staff_user_id"], "/assignee_staff_user_id")
        if clause is not None and data["assignee_staff_user_id"] != principal.staff_user_id:
            raise ValidationFailed("You can only assign tasks to yourself.", pointer="/assignee_staff_user_id")
    status = data.pop("status", None)
    for key, value in data.items():
        setattr(row, key, value)
    if status is not None and status != row.status:
        row.status = status
        done = status == "done"
        row.completed_at = clock.now() if done else None
        row.completed_by_staff_user_id = principal.staff_user_id if done else None
    audit.record(session, "clients.task.manage", row, changes=audit.diff(row))
    session.flush()
    return row


def open_task_count(session: Session, principal: Principal) -> dict:
    """The caller's own open and overdue tasks (the "My tasks" badge)."""
    authorize(principal, "clients.task.manage")
    today = clock.now().date()
    open_, overdue = session.execute(
        select(func.count(), func.count(case((ClientTask.due_on < today, 1)))).where(
            ClientTask.assignee_staff_user_id == principal.staff_user_id,
            ClientTask.status.in_(("open", "in_progress")),
        )
    ).one()
    return {"open_count": open_, "overdue_count": overdue}


def send_task_reminders(session: Session, on: date) -> int:
    """Email assignees about open tasks with a reminder due on or before `on`. Idempotent: reminder_sent_at.
    Internal; callable from a job. shortcut: no periodic scheduler exists yet, wire this into one when jobs land."""
    sent = 0
    settings = get_settings()
    for task in session.scalars(
        select(ClientTask).where(
            ClientTask.has_email_reminder,
            ClientTask.reminder_sent_at.is_(None),
            ClientTask.status.in_(("open", "in_progress")),
            ClientTask.due_on <= on,
        )  # fmt: skip
    ):
        staff_user = session.get(platform.models.StaffUser, task.assignee_staff_user_id)
        identity = session.get(platform.models.Identity, staff_user.identity_id)
        client = session.get(Client, task.client_id)
        subject = task.subject_text or session.get(NoteSubject, task.note_subject_id).label
        notifications.send(
            session, "clients.task_reminder", identity.email,
            {"app": settings.app.display_name, "due": str(task.due_on), "subject": subject,
             "client": service.display_name(client), "url": f"{settings.app.web_base_url}/clients/{client.id}"},
        )  # fmt: skip
        task.reminder_sent_at = clock.now()
        sent += 1
    session.flush()
    return sent


# --- alerts --------------------------------------------------------------------------------------------------


def list_alerts(session: Session, principal: Principal, client_id: UUID) -> list[ClientAlert]:
    client = service.load(session, principal, client_id, "clients.activity.read")
    return list(
        session.scalars(
            select(ClientAlert)
            .where(ClientAlert.client_id == client.id)
            .order_by(ClientAlert.is_active.desc(), ClientAlert.created_at.desc())
        )
    )


def _check_dates(starts_on, ends_on) -> None:
    if starts_on and ends_on and ends_on < starts_on:
        raise ValidationFailed("The end date is before the start date.", pointer="/ends_on")


def create_alert(session: Session, principal: Principal, client_id: UUID, data: dict) -> ClientAlert:
    client = service.load(session, principal, client_id, "clients.activity.write")
    service._require_live(client)
    if principal.staff_user_id is None:
        raise ValidationFailed("Only staff can add alerts.")
    _check_dates(data.get("starts_on"), data.get("ends_on"))
    row = ClientAlert(client_id=client.id, created_by_staff_user_id=principal.staff_user_id, **data)
    session.add(row)
    session.flush()
    audit.record(session, "clients.activity.write", row, location_id=client.home_location_id, changes={"alert": True})
    return row


def update_alert(session: Session, principal: Principal, alert_id: UUID, data: dict) -> ClientAlert:
    row = session.get(ClientAlert, alert_id)
    if row is None:
        raise NotFound()
    service.load(session, principal, row.client_id, "clients.activity.write")
    for key, value in data.items():
        if value is None and key not in ("starts_on", "ends_on"):
            raise ValidationFailed(f"{key} cannot be null.", pointer=f"/{key}")
        setattr(row, key, value)
    _check_dates(row.starts_on, row.ends_on)
    audit.record(session, "clients.activity.write", row, changes=audit.diff(row))
    session.flush()
    return row


def active_alerts(session: Session, client_id: UUID, where: str, on: date) -> list[ClientAlert]:
    """Internal, for check-in (`check_in`) and booking (`booking`) screens of other contexts: the client's
    alerts live on `on` that are set to show there."""
    column = {"profile": ClientAlert.shows_on_profile, "check_in": ClientAlert.shows_on_check_in,
              "booking": ClientAlert.shows_on_booking}[where]  # fmt: skip
    return list(
        session.scalars(
            select(ClientAlert)
            .where(
                ClientAlert.client_id == client_id,
                ClientAlert.is_active,
                column,
                or_(ClientAlert.starts_on.is_(None), ClientAlert.starts_on <= on),
                or_(ClientAlert.ends_on.is_(None), ClientAlert.ends_on >= on),
            )
            .order_by(ClientAlert.severity.desc(), ClientAlert.created_at)  # fmt: skip
        )
    )


# --- timeline ------------------------------------------------------------------------------------------------


def timeline(session: Session, principal: Principal, client_id: UUID, before: datetime | None, limit: int = 50) -> dict:
    """One newest-first stream of notes, tasks, alerts and audited changes to the client (CLI-11). Keyset on
    occurred_at via `before`. Audit rows show the action only, never the diff values."""
    client = service.load(session, principal, client_id, "clients.activity.read")
    before = before or datetime.max.replace(tzinfo=clock.now().tzinfo)
    entries = []
    for note in session.scalars(
        select(ClientNote)
        .where(ClientNote.client_id == client.id, ClientNote.occurred_at < before)
        .order_by(ClientNote.occurred_at.desc())
        .limit(limit)  # fmt: skip
    ):
        subject = note.subject_text or session.get(NoteSubject, note.note_subject_id).label
        entries.append({"occurred_at": note.occurred_at, "kind": "note", "id": note.id,
                        "title": f"{note.kind.title()}: {subject}", "detail": note.body,
                        "staff_user_id": note.staff_user_id})  # fmt: skip
    for task in session.scalars(
        select(ClientTask)
        .where(ClientTask.client_id == client.id, ClientTask.created_at < before)
        .order_by(ClientTask.created_at.desc())
        .limit(limit)  # fmt: skip
    ):
        subject = task.subject_text or session.get(NoteSubject, task.note_subject_id).label
        entries.append({"occurred_at": task.created_at, "kind": "task", "id": task.id,
                        "title": f"Task ({task.status.replace('_', ' ')}): {subject}", "detail": task.body,
                        "staff_user_id": task.assignee_staff_user_id})  # fmt: skip
    for alert in session.scalars(
        select(ClientAlert)
        .where(ClientAlert.client_id == client.id, ClientAlert.created_at < before)
        .order_by(ClientAlert.created_at.desc())
        .limit(limit)  # fmt: skip
    ):
        entries.append({"occurred_at": alert.created_at, "kind": "alert", "id": alert.id,
                        "title": f"Alert ({alert.severity})", "detail": alert.message,
                        "staff_user_id": alert.created_by_staff_user_id})  # fmt: skip
    for event in session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_type == "client", AuditEvent.entity_id == client.id, AuditEvent.occurred_at < before)
        .order_by(AuditEvent.occurred_at.desc())
        .limit(limit)  # fmt: skip
    ):
        entries.append({"occurred_at": event.occurred_at, "kind": "audit", "id": event.id, "title": event.action,
                        "detail": event.actor_label, "staff_user_id": None})  # fmt: skip
    entries.sort(key=lambda e: e["occurred_at"], reverse=True)
    page = entries[:limit]
    more = len(entries) > limit
    return {"data": page, "next_before": page[-1]["occurred_at"] if more and page else None}
