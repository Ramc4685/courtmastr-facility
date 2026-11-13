"""programs service, session targets: enrolment into one or several sessions, attendance, the session waitlist
and the roster message. Group targets live in `groups`; the shared endpoints dispatch on the row's target.

Seats are counted by `scheduling.reserve_seat` under the session row lock; this context owns who sits in
them. A session that does not allow free booking needs a package or `scheduling.enrollment.free_book`.
"""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session as Db

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.modules import clients, packages, platform, scheduling
from app.modules.programs import events as ev
from app.modules.programs import groups
from app.modules.programs.models import Attendance, Enrollment, WaitlistEntry
from app.ports import notifications

READ = "scheduling.booking.read"
ENROLL, CANCEL, FREE = (f"scheduling.enrollment.{verb}" for verb in ("create", "cancel", "free_book"))
ROSTER_MESSAGE = "engagement.message.send_direct"  # engagement owns the key; programs may not import it
MARK, MARK_EXCEPTION, WAITLIST = (
    "scheduling.attendance.mark",
    "scheduling.attendance.mark_exception",
    "scheduling.waitlist.manage",
)
PROMOTION_CUTOFF = timedelta(minutes=60)  # no auto-promotion this close to the start (ADR 0004 section 8)
OFFER_WINDOW = timedelta(hours=2)  # an open offer lapses back to waiting after this, or at the start
CONSTRAINT_CODES["uq_enrollment_session_client"] = "already-enrolled"
notifications.register_template("programs.roster_message", subject="$subject", body="$body")
notifications.register_template(
    "programs.waitlist_offer",
    subject="A place is free: $title",
    body="$first_name, a place opened up in $title on $starts_at. The first to claim it in the portal gets it.",
)
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


GROUP_KEY = {READ: groups.READ, ENROLL: groups.ENROLL, CANCEL: groups.CANCEL, WAITLIST: groups.WAITLIST}


def _load(session: Db, principal: Principal, model, row_id: UUID, key: str):
    """An enrolment or waitlist entry, gated by its target: the session's reach or the group's."""
    row = session.get(model, row_id)
    if row is None:
        raise NotFound()
    if row.program_group_id is not None:
        groups.load(session, principal, row.program_group_id, GROUP_KEY[key])
    else:
        _seat(session, principal, row.session_id, key)
    return row


def _authorize_any(principal: Principal, *keys: str) -> None:
    """List reads span both targets: either key suffices (each row's reach is checked again on detail)."""
    for key in keys[:-1]:
        if principal.has(key):
            return authorize(principal, key)
    authorize(principal, keys[-1])


# --- enrolment ---------------------------------------------------------------------------------------------


def _credit(row: Enrollment) -> dict:
    return {"source_type": "enrollment", "source_id": row.id}


def _hold_credit(session: Db, seat: dict, row: Enrollment, client_package_id: UUID) -> None:
    """Hold one credit of the package for this place (PKG-12). The session's own day at its location decides
    whether the package is in date; packages refuses with 409 package-exhausted, -wrong-type, -out-of-range..."""
    zone = ZoneInfo(platform.service.location_time_zone(session, seat["location_id"]))
    try:
        packages.service.reserve_credit(
            session, client_package_id=client_package_id, client_id=row.client_id, **_credit(row),
            session_on=seat["starts_at"].astimezone(zone).date(), reservation_type_id=seat["reservation_type_id"],
        )  # fmt: skip
    except NotFound:
        raise ValidationFailed("Unknown package.", pointer="/client_package_id") from None


def _enroll(
    session: Db,
    seat: dict,
    client_id: UUID,
    channel: str,
    client_package_id: UUID | None = None,
    *,
    principal: Principal | None = None,
) -> Enrollment:
    """Internal: seat first (row lock, capacity-full), then the roster row and, when a package pays, its held
    credit, all in the caller's transaction. Every path into a seat meets the free-booking gate here: no
    package on a session that does not allow free booking needs `free_book` at its location, and the
    automatic path (`principal` None) never has it."""
    if client_package_id is None and not seat["allows_free_booking"]:
        if principal is None:
            raise PermissionDenied(
                "This session needs a package; registering without one requires an override.", required=FREE
            )
        authorize(principal, FREE, location_id=seat["location_id"])
    scheduling.service.reserve_seat(session, seat["id"])
    row = Enrollment(
        location_id=seat["location_id"], client_id=client_id, session_id=seat["id"], status="enrolled",
        pricing="entitlement" if client_package_id else "free", channel=channel, enrolled_at=clock.now(),
    )  # fmt: skip
    session.add(row)
    session.flush()  # uq_enrollment_session_client answers a second enrolment with already-enrolled
    if client_package_id:
        _hold_credit(session, seat, row, client_package_id)
    events.publish(
        session, ev.EnrollmentCreated(enrollment_id=row.id, session_id=seat["id"], client_id=client_id), row.id
    )
    return row


def create_enrollment(session: Db, principal: Principal, data: dict) -> Enrollment:
    """Register a client into a single session (CLS-01, CLS-05) or a group node (REG-07).
    Errors: capacity-full, already-enrolled."""
    if data.get("program_group_id"):
        return groups.create_enrollment(session, principal, data)["enrollment"]
    seat = _seat(session, principal, data["session_id"], ENROLL)
    clients.service.require_active(session, data["client_id"])
    row = _enroll(session, seat, data["client_id"], "staff", data.get("client_package_id"), principal=principal)
    audit.record(session, ENROLL, row, location_id=row.location_id, changes={"session_id": [None, str(row.session_id)]})
    return row


def list_enrollments(session: Db, principal: Principal, query: ListQuery) -> dict:
    _authorize_any(principal, READ, groups.READ)
    e, kinds = Enrollment, []
    for key, kind in ((READ, "session"), (groups.READ, "group")):
        reach = principal.permissions.get(key) if principal.kind == "staff" else "all"
        if not reach:
            continue  # each target kind needs its own read key
        clause = e.target_kind == kind
        if reach == "own" and kind == "session":
            mine = platform.service.linked_resource_id(session, principal.staff_user_id)
            sessions = scheduling.service.sessions_with_resource(mine, select(e.session_id)) if mine else None
            clause &= e.session_id.in_(sessions) if sessions is not None else false()
        elif reach == "own":
            clause &= e.program_group_id.in_(groups.reached_groups(session, principal))
        kinds.append(clause)
    stmt = select(e).where(or_(*kinds))
    return paginate(
        session, scope_query(stmt, principal, Enrollment.location_id), query, id_column=Enrollment.id,
        sort_fields={"enrolled_at": Enrollment.created_at}, default_sort="enrolled_at",
        filter_fields={
            "location_id": Enrollment.location_id, "session_id": Enrollment.session_id,
            "client_id": Enrollment.client_id, "status": Enrollment.status,
            "program_group_id": Enrollment.program_group_id, "batch_id": Enrollment.batch_id,
        },
    )  # fmt: skip


def get_enrollment(session: Db, principal: Principal, enrollment_id: UUID) -> Enrollment:
    return _load(session, principal, Enrollment, enrollment_id, READ)


def _cancel(session: Db, row: Enrollment, kind: str, reason: str | None = None) -> None:
    row.status, row.cancelled_at, row.cancel_kind, row.cancel_reason = "cancelled", clock.now(), kind, reason
    scheduling.service.release_seat(session, row.session_id)
    # A held credit goes back, or is kept on a late cancel when the package settings say so. No-op without one.
    packages.service.settle_credit(session, **_credit(row), outcome="late_cancel" if kind == "late" else "early_cancel")
    events.publish(
        session,
        ev.EnrollmentCancelled(
            enrollment_id=row.id, session_id=row.session_id, client_id=row.client_id, cancel_kind=kind
        ),
        row.id,
    )
    session.flush()


def cancel_enrollment(session: Db, principal: Principal, enrollment_id: UUID, data: dict) -> Enrollment:
    """Remove a participant (CLS-03, REG-07). A freed seat goes to the head of the waitlist in this transaction.
    `scope: batch` cancels every live enrolment booked with this one (CLS-02)."""
    row = _load(session, principal, Enrollment, enrollment_id, CANCEL)
    if row.program_group_id is not None:
        return groups.cancel_enrollment(session, principal, row, data)
    rows = [row]
    if data.get("scope") == "batch" and row.batch_id is not None:
        rows = session.scalars(
            select(Enrollment).where(Enrollment.batch_id == row.batch_id, Enrollment.status == "enrolled")
        ).all()
    for each in rows:
        if each is not row:
            _seat(session, principal, each.session_id, CANCEL)
        if each.status == "cancelled":
            continue
        _cancel(session, each, data.get("cancel_kind") or "staff_removed", data.get("reason"))
        each.cancelled_by_actor_type = "staff"
        audit.record(
            session, CANCEL, each, location_id=each.location_id,
            changes={"status": ["enrolled", "cancelled"], "cancel_kind": [None, each.cancel_kind]},
        )  # fmt: skip
        promote_waitlist(session, each.session_id)
    return row


def create_enrollment_batch(session: Db, principal: Principal, data: dict) -> dict:
    """Register a client into several occurrences of a series in one transaction (CLS-02): `all_linked` takes the
    anchor and every later confirmed occurrence, `custom` the listed ones. A full or ineligible occurrence is
    skipped with its problem code; a forbidden or malformed request still fails as a whole."""
    anchor = _seat(session, principal, data["session_id"], ENROLL)
    clients.service.require_active(session, data["client_id"])
    linked = [anchor["id"]]
    if anchor["booking_series_id"] is not None:
        linked = scheduling.service.series_sessions(session, anchor["booking_series_id"], anchor["starts_at"])
    targets = linked
    if data["booked_scope"] == "custom":
        targets = data.get("session_ids") or []
        if not targets:
            raise ValidationFailed("Choose the sessions to book.", pointer="/session_ids")
        for index, session_id in enumerate(targets):
            if session_id not in linked:
                raise ValidationFailed("Not a later session of this series.", pointer=f"/session_ids/{index}")
    package_id = data.get("client_package_id")
    batch_id, enrolled, skipped = new_id(), [], []
    for session_id in dict.fromkeys(targets):
        seat = _seat(session, principal, session_id, ENROLL)
        try:
            with session.begin_nested():
                row = _enroll(session, seat, data["client_id"], "staff", package_id, principal=principal)
        except Conflict as exc:
            skipped.append({"session_id": session_id, "code": exc.code})
            continue
        row.batch_id, row.booked_scope = batch_id, data["booked_scope"]
        audit.record(session, ENROLL, row, location_id=row.location_id, changes={"session_id": [None, str(session_id)]})
        enrolled.append(row)
    session.flush()
    return {"batch_id": batch_id, "enrolled": enrolled, "skipped": skipped}


def rebook_enrollment(session: Db, principal: Principal, enrollment_id: UUID, data: dict) -> Enrollment:
    """Early-cancel a session place and register the same client into another session in one transaction (CLS-03).
    The credit returns and is held again, on the same package unless another is named."""
    row = _load(session, principal, Enrollment, enrollment_id, CANCEL)
    if row.session_id is None or row.status != "enrolled":
        raise Conflict("Only a live session place can be rebooked.", code="invalid-state-transition")
    target = _seat(session, principal, data["session_id"], ENROLL)
    package_id = data.get("client_package_id") or packages.service.package_for(session, **_credit(row))
    _cancel(session, row, "early", "rebooked")
    row.cancelled_by_actor_type = "staff"
    audit.record(session, CANCEL, row, location_id=row.location_id, changes={"status": ["enrolled", "cancelled"]})
    new = _enroll(session, target, row.client_id, "staff", package_id, principal=principal)
    audit.record(session, ENROLL, new, location_id=new.location_id, changes={"session_id": [None, str(new.session_id)]})
    promote_waitlist(session, row.session_id)
    return new


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


def _settle_credit(session: Db, seat: dict, row: Enrollment, status: str) -> None:
    """Move the place's package credit to match its attendance mark: attended consumes it, a no-show consumes
    or returns it per the package settings, excused returns it. A corrected mark first undoes the previous
    outcome and holds the credit again on the same package, so marks can be changed any number of times."""
    packages.service.restore_credit(session, **_credit(row))
    if status == "excused":
        packages.service.settle_credit(session, **_credit(row), outcome="early_cancel")
        return
    package_id = packages.service.package_for(session, **_credit(row))
    if package_id is not None:
        _hold_credit(session, seat, row, package_id)  # a no-op while the credit is still held
        packages.service.settle_credit(session, **_credit(row), outcome=status)


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
            if row.pricing == "entitlement":
                _settle_credit(session, seat, row, mark["status"])
            if mark["status"] == "attended":
                events.publish(
                    session,
                    ev.EnrollmentAttended(enrollment_id=row.id, session_id=session_id, client_id=row.client_id),
                    row.id,
                )
    return get_roster(session, principal, session_id)


# --- waitlist ----------------------------------------------------------------------------------------------


def list_waitlist(
    session: Db, principal: Principal, session_id: UUID | None = None, program_group_id: UUID | None = None
) -> list[dict]:
    """The waiting queue of one session or one group node, FIFO, with positions."""
    if program_group_id is not None:
        rows = groups.list_waitlist(session, principal, program_group_id)
        return [_entry_view(row, position) for position, row in enumerate(rows, start=1)]
    if session_id is None:
        raise ValidationFailed("Name a session or a program group.", pointer="/session_id")
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
    """Queue a client for a full session (CLS-06) or group node (REG-09).
    Errors: session-has-space, already-enrolled, already-waitlisted."""
    if data.get("program_group_id"):
        entry = groups.create_waitlist_entry(session, principal, data)
        return _entry_view(entry, len(groups.queue(session, entry.program_group_id)))
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


def _promote(session: Db, seat: dict, entry: WaitlistEntry, principal: Principal | None = None) -> Enrollment:
    row = _enroll(session, seat, entry.client_id, "waitlist", principal=principal)
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
    if seat["allows_free_booking"]:  # an auto entry carries no package: it waits for staff with free_book (S-01)
        promoted = _auto_promote(session, seat)
    offer_open_seats(session, session_id)
    return promoted


def _auto_promote(session: Db, seat: dict) -> int:
    promoted, session_id = 0, seat["id"]
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
    if entry.program_group_id is not None:
        return _entry_view(groups.promote_entry(session, principal, entry))
    if entry.status not in ("waiting", "offered"):
        raise Conflict("This entry is no longer waiting.")
    _promote(session, scheduling.service.get_session(session, entry.session_id), entry, principal)
    audit.record(session, WAITLIST, entry, location_id=entry.location_id, changes={"status": ["waiting", "promoted"]})
    return _entry_view(entry)


def remove_waitlist_entry(session: Db, principal: Principal, entry_id: UUID) -> None:
    entry = _load(session, principal, WaitlistEntry, entry_id, WAITLIST)
    if entry.program_group_id is not None:
        return groups.remove_entry(session, principal, entry)
    if entry.status in ("waiting", "offered"):
        was, entry.status, entry.removed_reason = entry.status, "removed", "staff"
        audit.record(session, WAITLIST, entry, location_id=entry.location_id, changes={"status": [was, "removed"]})
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


# --- internal: payroll facts (staff, STF-09) ---------------------------------------------------------------------


def attended_enrollments(session: Db, session_ids) -> dict[UUID, list[UUID]]:
    """Enrolments marked attended per session: the attendees a trainer is paid for, each with the package credit
    its enrolment spent (staff payroll, STF-02, STF-10)."""
    ids = list(session_ids)
    rows = session.execute(
        select(Attendance.session_id, Attendance.enrollment_id)
        .where(Attendance.session_id.in_(ids), Attendance.status == "attended")
    ).all() if ids else []  # fmt: skip
    found: dict[UUID, list[UUID]] = {}
    for session_id, enrollment_id in rows:
        found.setdefault(session_id, []).append(enrollment_id)
    return found


# --- roster message (CLS-03) -------------------------------------------------------------------------------


def send_roster_message(session: Db, principal: Principal, session_id: UUID, data: dict) -> dict:
    """Email everyone registered in a session. Goes out through the notification port after commit; clients with
    no email address are skipped. Returns an already-finished job handle (the engagement module will queue)."""
    seat = _seat(session, principal, session_id, ROSTER_MESSAGE)
    statuses = data.get("statuses") or ["enrolled"]
    client_ids = session.scalars(
        select(Enrollment.client_id).where(Enrollment.session_id == session_id, Enrollment.status.in_(statuses))
    ).all()
    sent = 0
    for client_id in client_ids:
        client = clients.service.get(session, client_id)
        if client.primary_email:
            notifications.send(
                session, "programs.roster_message", client.primary_email,
                {"subject": data["subject"], "body": data["body_html"]},
            )  # fmt: skip
            sent += 1
    job_id = new_id()
    target = SimpleNamespace(__tablename__="session", id=session_id)  # the audited aggregate is scheduling's row
    audit.record(
        session,
        "programs.roster_message.send",
        target,
        location_id=seat["location_id"],
        changes={"recipients": [None, sent]},
    )
    return {"job_id": job_id, "status": "succeeded", "resource_url": None}


# --- open offers (CLS-06 open_offer mode) -----------------------------------------------------------------------


def offer_open_seats(session: Db, session_id: UUID) -> int:
    """Internal. While a session has free seats, every waiting `open_offer` entry is offered at once; the first
    valid claim under the seat lock wins and the others go back to waiting (claim_offer)."""
    seat = scheduling.service.get_session(session, session_id)
    if seat["status"] != "confirmed" or seat["booked_count"] >= seat["capacity"]:
        return 0
    now = clock.now()
    expires = min(now + OFFER_WINDOW, seat["starts_at"])
    if expires <= now:
        return 0
    entries = session.scalars(
        select(WaitlistEntry)
        .where(
            WaitlistEntry.session_id == session_id, WaitlistEntry.status == "waiting",
            WaitlistEntry.mode == "open_offer",
        )
        .order_by(WaitlistEntry.queued_at, WaitlistEntry.id)
        .with_for_update(skip_locked=True)
    ).all()  # fmt: skip
    for entry in entries:
        entry.status, entry.offered_at, entry.offer_expires_at = "offered", now, expires
        client = clients.service.get(session, entry.client_id)
        if client.primary_email:
            notifications.send(
                session, "programs.waitlist_offer", client.primary_email,
                {"first_name": client.first_name, "title": seat["title"] or "your session",
                 "starts_at": seat["starts_at"].isoformat()},
            )  # fmt: skip
    session.flush()
    return len(entries)


def claim_offer(session: Db, entry: WaitlistEntry, client_package_id: UUID | None) -> Enrollment:
    """Internal (portal claim): take the offered seat under the session lock. A seat already gone is 409
    capacity-full and the entry goes back to waiting (the refusal commits that)."""
    if entry.status != "offered" or entry.offer_expires_at is None or entry.offer_expires_at <= clock.now():
        raise Conflict("There is no open offer to claim.", code="invalid-state-transition")
    seat = scheduling.service.get_session(session, entry.session_id)
    if client_package_id is None and not seat["allows_free_booking"]:
        raise Conflict("Choose a package to book this session with.", code="entitlement-not-eligible")
    try:
        with session.begin_nested():
            row = _enroll(session, seat, entry.client_id, "waitlist", client_package_id)
    except Conflict as exc:
        if exc.code != "capacity-full":
            raise
        entry.status, entry.offered_at, entry.offer_expires_at = "waiting", None, None
        session.flush()
        # persist: the entry going back to waiting must survive the refusal
        raise Conflict("Someone else claimed the place first.", code="capacity-full", persist=True) from None
    entry.status, entry.promoted_enrollment_id = "promoted", row.id
    events.publish(
        session,
        ev.WaitlistPromoted(
            enrollment_id=row.id, session_id=seat["id"], client_id=entry.client_id, waitlist_entry_id=entry.id
        ),
        entry.id,
    )
    session.flush()
    return row


def lapse_offers(session: Db) -> int:
    """Internal (every minute): offers nobody claimed in time go back to waiting."""
    rows = session.scalars(
        select(WaitlistEntry)
        .where(WaitlistEntry.status == "offered", WaitlistEntry.offer_expires_at <= clock.now())
        .with_for_update(skip_locked=True)
    ).all()
    for entry in rows:
        entry.status, entry.offered_at, entry.offer_expires_at = "waiting", None, None
    session.flush()
    return len(rows)


# --- check-in (access, build module 10) ---------------------------------------------------------------------


def mark_attended_by_check_in(
    session: Db, *, client_id: UUID, location_id: UUID, at, early: timedelta, late: timedelta,
    source: str = "check_in", staff_user_id: UUID | None = None, session_id: UUID | None = None,
) -> list[tuple[UUID, UUID]]:  # fmt: skip
    """Internal (access, CHK-01, CHK-05): mark attended the client's unmarked session places at the location
    whose session starts from `early` before to `late` after `at` (only `session_id` when given). Credits and
    events follow as for a staff mark. Returns (enrollment id, session id) per place marked."""
    rows = session.scalars(
        select(Enrollment)
        .outerjoin(Attendance, (Attendance.enrollment_id == Enrollment.id) & (Attendance.session_id == Enrollment.session_id))
        .where(
            Enrollment.client_id == client_id, Enrollment.location_id == location_id,
            Enrollment.status == "enrolled", Enrollment.target_kind == "session", Attendance.id.is_(None),
            *([Enrollment.session_id == session_id] if session_id else []),
        )
        .order_by(Enrollment.enrolled_at.desc())
        .limit(50)  # shortcut: newest 50 unmarked places; enough for one visit, revisit if rosters stay unmarked
    ).all()  # fmt: skip
    marked = []
    for row in rows:
        seat = scheduling.service.get_session(session, row.session_id)
        if seat["status"] != "confirmed" or not (at - early <= seat["starts_at"] <= at + late):
            continue
        mark = Attendance(
            enrollment_id=row.id, session_id=row.session_id, client_id=client_id, status="attended", source=source,
            marked_at=clock.now(), marked_by_staff_user_id=staff_user_id,
        )  # fmt: skip
        session.add(mark)
        session.flush()
        audit.record(session, MARK, mark, location_id=location_id, changes={"status": [None, "attended"]})
        if row.pricing == "entitlement":
            _settle_credit(session, seat, row, "attended")
        events.publish(
            session, ev.EnrollmentAttended(enrollment_id=row.id, session_id=row.session_id, client_id=client_id), row.id
        )
        marked.append((row.id, row.session_id))
    return marked
