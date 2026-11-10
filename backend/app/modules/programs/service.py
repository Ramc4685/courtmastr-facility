"""programs service, session slice: enrolment into a single session, attendance and the session waitlist.

Seats are counted by `scheduling.reserve_seat` under the session row lock; this context owns who sits in
them. Only `pricing = free` exists until packages (build module 5) and fees (build module 6) arrive: a
session that does not allow free booking needs `scheduling.enrollment.free_book`.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import clients, scheduling
from app.modules.programs import events as ev
from app.modules.programs.models import Attendance, Enrollment, WaitlistEntry
from app.ports import notifications

READ = "scheduling.booking.read"
ENROLL, CANCEL, FREE = (f"scheduling.enrollment.{verb}" for verb in ("create", "cancel", "free_book"))
MARK, MARK_EXCEPTION, WAITLIST = (
    "scheduling.attendance.mark",
    "scheduling.attendance.mark_exception",
    "scheduling.waitlist.manage",
)
PROMOTION_CUTOFF = timedelta(minutes=60)  # no auto-promotion this close to the start (ADR 0004 section 8)
CONSTRAINT_CODES["uq_enrollment_session_client"] = "already-enrolled"
notifications.register_template(
    "programs.waitlist_promoted",
    subject="A place opened up: $title",
    body="Good news, $first_name. A place opened up in $title on $starts_at and you are now booked in.",
)


def _seat(session: Db, principal: Principal, session_id: UUID, key: str) -> dict:
    """The session, gated: location containment and `own` reach are scheduling's to judge."""
    seat = scheduling.service.get_session(session, session_id)
    scheduling.service.authorize_reach(session, principal, key, seat["booking_id"])
    return seat


def _load(session: Db, principal: Principal, model, row_id: UUID, key: str):
    row = session.get(model, row_id)
    if row is None:
        raise NotFound()
    _seat(session, principal, row.session_id, key)
    return row


# --- enrolment ---------------------------------------------------------------------------------------------


def _enroll(session: Db, seat: dict, client_id: UUID, channel: str) -> Enrollment:
    """Internal: seat first (row lock, capacity-full), then the roster row, in the caller's transaction."""
    scheduling.service.reserve_seat(session, seat["id"])
    row = Enrollment(
        location_id=seat["location_id"], client_id=client_id, session_id=seat["id"], status="enrolled",
        pricing="free", channel=channel, enrolled_at=clock.now(),
    )  # fmt: skip
    session.add(row)
    session.flush()  # uq_enrollment_session_client answers a second enrolment with already-enrolled
    events.publish(
        session, ev.EnrollmentCreated(enrollment_id=row.id, session_id=seat["id"], client_id=client_id), row.id
    )
    return row


def create_enrollment(session: Db, principal: Principal, data: dict) -> Enrollment:
    """Register a client into a single session (CLS-01, CLS-05). Errors: capacity-full, already-enrolled."""
    seat = _seat(session, principal, data["session_id"], ENROLL)
    if not seat["allows_free_booking"] and not principal.has(FREE):
        raise PermissionDenied(
            "This session needs a package; registering without one requires an override.", required=FREE
        )
    clients.service.require_active(session, data["client_id"])
    row = _enroll(session, seat, data["client_id"], "staff")
    audit.record(session, ENROLL, row, location_id=row.location_id, changes={"session_id": [None, str(row.session_id)]})
    return row


def list_enrollments(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, READ)
    return paginate(
        session, scope_query(select(Enrollment), principal, Enrollment.location_id), query, id_column=Enrollment.id,
        sort_fields={"enrolled_at": Enrollment.created_at}, default_sort="enrolled_at",
        filter_fields={
            "location_id": Enrollment.location_id, "session_id": Enrollment.session_id,
            "client_id": Enrollment.client_id, "status": Enrollment.status,
        },
    )  # fmt: skip


def get_enrollment(session: Db, principal: Principal, enrollment_id: UUID) -> Enrollment:
    return _load(session, principal, Enrollment, enrollment_id, READ)


def _cancel(session: Db, row: Enrollment, kind: str, reason: str | None = None) -> None:
    row.status, row.cancelled_at, row.cancel_kind, row.cancel_reason = "cancelled", clock.now(), kind, reason
    scheduling.service.release_seat(session, row.session_id)
    events.publish(
        session,
        ev.EnrollmentCancelled(
            enrollment_id=row.id, session_id=row.session_id, client_id=row.client_id, cancel_kind=kind
        ),
        row.id,
    )
    session.flush()


def cancel_enrollment(session: Db, principal: Principal, enrollment_id: UUID, data: dict) -> Enrollment:
    """Remove a participant (CLS-03). The freed seat goes to the head of the waitlist in this transaction."""
    row = _load(session, principal, Enrollment, enrollment_id, CANCEL)
    if row.status != "cancelled":
        _cancel(session, row, data.get("cancel_kind") or "staff_removed", data.get("reason"))
        audit.record(
            session,
            CANCEL,
            row,
            location_id=row.location_id,
            changes={"status": ["enrolled", "cancelled"], "cancel_kind": [None, row.cancel_kind]},
        )
        promote_waitlist(session, row.session_id)
    return row


# --- roster and attendance ---------------------------------------------------------------------------------


def get_roster(session: Db, principal: Principal, session_id: UUID) -> dict:
    seat = _seat(session, principal, session_id, READ)
    rows = session.execute(
        select(Enrollment, Attendance.status)
        .outerjoin(
            Attendance, (Attendance.enrollment_id == Enrollment.id) & (Attendance.session_id == Enrollment.session_id)
        )
        .where(Enrollment.session_id == session_id, Enrollment.status == "enrolled")
        .order_by(Enrollment.enrolled_at, Enrollment.id)
    ).all()
    waiting = session.scalar(
        select(func.count()).where(WaitlistEntry.session_id == session_id, WaitlistEntry.status == "waiting")
    )
    return {
        "session_id": session_id, "capacity": seat["capacity"], "booked_count": seat["booked_count"], "waiting_count": waiting,
        "participants": [
            {
                "enrollment_id": row.id, "client_id": row.client_id, "enrolled_at": row.enrolled_at, "channel": row.channel,
                "client_name": clients.service.display_name(clients.service.get(session, row.client_id)),
                "attendance": status or "scheduled",
            }
            for row, status in rows
        ],
    }  # fmt: skip


def put_attendance(session: Db, principal: Principal, session_id: UUID, marks: list[dict]) -> dict:
    """Mark attendance for participants (CLS-03). Idempotent per (enrolment, session); the first move to
    `attended` emits programs.enrollment.attended. `no_show` and `excused` need the exception permission."""
    seat = _seat(session, principal, session_id, MARK)
    if any(mark["status"] != "attended" for mark in marks):
        scheduling.service.authorize_reach(session, principal, MARK_EXCEPTION, seat["booking_id"])
    enrolled = {
        row.id: row
        for row in session.scalars(
            select(Enrollment).where(Enrollment.session_id == session_id, Enrollment.status == "enrolled")
        )
    }
    existing = {
        row.enrollment_id: row for row in session.scalars(select(Attendance).where(Attendance.session_id == session_id))
    }
    for index, mark in enumerate(marks):
        row = enrolled.get(mark["enrollment_id"])
        if row is None:
            raise ValidationFailed("Not a participant of this session.", pointer=f"/marks/{index}/enrollment_id")
        attendance = existing.get(row.id)
        was = attendance.status if attendance else None
        if attendance is None:
            attendance = existing[row.id] = Attendance(
                enrollment_id=row.id, session_id=session_id, client_id=row.client_id
            )
            session.add(attendance)
        attendance.status, attendance.marked_at, attendance.marked_by_staff_user_id = (
            mark["status"],
            clock.now(),
            principal.staff_user_id,
        )
        session.flush()
        if was != mark["status"]:
            audit.record(
                session, MARK, attendance, location_id=seat["location_id"], changes={"status": [was, mark["status"]]}
            )
            if mark["status"] == "attended":
                events.publish(
                    session,
                    ev.EnrollmentAttended(enrollment_id=row.id, session_id=session_id, client_id=row.client_id),
                    row.id,
                )
    return get_roster(session, principal, session_id)


# --- waitlist ----------------------------------------------------------------------------------------------


def list_waitlist(session: Db, principal: Principal, session_id: UUID) -> list[dict]:
    _seat(session, principal, session_id, WAITLIST)
    rows = session.scalars(
        select(WaitlistEntry)
        .where(WaitlistEntry.session_id == session_id, WaitlistEntry.status == "waiting")
        .order_by(WaitlistEntry.queued_at, WaitlistEntry.id)
    )
    return [_entry_view(row, position) for position, row in enumerate(rows, start=1)]


def _entry_view(row: WaitlistEntry, position: int | None = None) -> dict:
    return {c.key: getattr(row, c.key) for c in WaitlistEntry.__table__.columns} | {"position": position}


def create_waitlist_entry(session: Db, principal: Principal, data: dict) -> dict:
    """Queue a client for a full session (CLS-06). Errors: session-has-space, already-enrolled, already-exists."""
    seat = _seat(session, principal, data["session_id"], WAITLIST)
    clients.service.require_active(session, data["client_id"])
    if seat["booked_count"] < seat["capacity"]:
        raise Conflict("The session still has space: register the client instead.", code="session-has-space")
    if session.scalar(
        select(Enrollment.id).where(
            Enrollment.session_id == seat["id"],
            Enrollment.client_id == data["client_id"],
            Enrollment.status == "enrolled",
        )
    ):
        raise Conflict("The client is already registered.", code="already-enrolled")
    row = WaitlistEntry(
        location_id=seat["location_id"], client_id=data["client_id"], session_id=seat["id"], mode=data["mode"],
        channel="staff", queued_at=clock.now(),
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(
        session, WAITLIST, row, location_id=row.location_id, changes={"session_id": [None, str(row.session_id)]}
    )
    position = session.scalar(
        select(func.count()).where(WaitlistEntry.session_id == seat["id"], WaitlistEntry.status == "waiting")
    )
    return _entry_view(row, position)


def _promote(session: Db, seat: dict, entry: WaitlistEntry) -> Enrollment:
    row = _enroll(session, seat, entry.client_id, "waitlist")
    entry.status, entry.promoted_enrollment_id = "promoted", row.id
    events.publish(
        session,
        ev.WaitlistPromoted(
            enrollment_id=row.id, session_id=seat["id"], client_id=entry.client_id, waitlist_entry_id=entry.id
        ),
        entry.id,
    )
    client = clients.service.get(session, entry.client_id)
    if client.primary_email:
        notifications.send(
            session, "programs.waitlist_promoted", client.primary_email,
            {"first_name": client.first_name, "title": seat["title"] or "your session", "starts_at": seat["starts_at"].isoformat()},
        )  # fmt: skip
    session.flush()
    return row


def promote_waitlist(session: Db, session_id: UUID) -> int:
    """Internal. Give free seats to the head of the queue, FIFO, under the session row lock that
    reserve_seat takes. Runs in the transaction that freed the seat or raised the capacity. Only
    `auto_promote` entries move by themselves, and not within the cut-off before the start."""
    seat = scheduling.service.get_session(session, session_id)
    if seat["status"] != "confirmed" or seat["starts_at"] - clock.now() < PROMOTION_CUTOFF:
        return 0
    promoted = 0
    queue = session.scalars(
        select(WaitlistEntry)
        .where(
            WaitlistEntry.session_id == session_id,
            WaitlistEntry.status == "waiting",
            WaitlistEntry.mode == "auto_promote",
        )
        .order_by(WaitlistEntry.queued_at, WaitlistEntry.id)
        .with_for_update(skip_locked=True)
    ).all()
    for entry in queue:
        try:
            with session.begin_nested():
                _promote(session, seat, entry)
        except Conflict as exc:
            if exc.code != "capacity-full":
                raise
            break
        promoted += 1
    return promoted


def promote_waitlist_entry(session: Db, principal: Principal, entry_id: UUID) -> dict:
    """Staff promotion of one entry, any mode, any time before the start. Errors: capacity-full."""
    entry = _load(session, principal, WaitlistEntry, entry_id, WAITLIST)
    if entry.status != "waiting":
        raise Conflict("This entry is no longer waiting.")
    _promote(session, scheduling.service.get_session(session, entry.session_id), entry)
    audit.record(session, WAITLIST, entry, location_id=entry.location_id, changes={"status": ["waiting", "promoted"]})
    return _entry_view(entry)


def remove_waitlist_entry(session: Db, principal: Principal, entry_id: UUID) -> None:
    entry = _load(session, principal, WaitlistEntry, entry_id, WAITLIST)
    if entry.status == "waiting":
        entry.status, entry.removed_reason = "removed", "staff"
        audit.record(
            session, WAITLIST, entry, location_id=entry.location_id, changes={"status": ["waiting", "removed"]}
        )
        session.flush()


def on_session_cancelled(session: Db, session_id: UUID) -> None:
    """Internal (event handler body): a cancelled session cancels its enrolments and closes its queue."""
    for row in session.scalars(
        select(Enrollment).where(Enrollment.session_id == session_id, Enrollment.status == "enrolled")
    ):
        _cancel(session, row, "session_cancelled")
    for entry in session.scalars(
        select(WaitlistEntry).where(WaitlistEntry.session_id == session_id, WaitlistEntry.status == "waiting")
    ):
        entry.status, entry.removed_reason = "expired", "session_cancelled"
    session.flush()
