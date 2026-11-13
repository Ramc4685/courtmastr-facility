"""Direct registration links (SCH-16) and shared bookings (SCH-17, SSP-09).

A session's `direct_link_token` exists from creation but resolves only while `is_direct_link_active` is on. The
link is reusable and may be forwarded (one link goes to many clients); revoking rotates the token, so every copy
sent before stops working. The token rides in the URL fragment of the web page and reaches the API only in a POST
body. Booking from the link is the portal's ordinary enrolment, which already accepts unlisted sessions.

A shared booking is one booking with several clients on it, each with their own attendance. The booking's client
is the organiser: participants must be their active relatives, and the organiser is listed too once the booking is
shared. Nothing here moves package credits: a package pays for the booking through the packages context's own
calls, so a couple sharing one capacity-1 session spends one credit.
"""

import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as Db

from app.core import audit, clock, events
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules import clients, platform
from app.modules.scheduling import events as ev
from app.modules.scheduling import service
from app.modules.scheduling.models import Booking, BookingParticipant, Session

LINK = "scheduling.registration_link.create"
ENROLL, UNENROLL = "scheduling.enrollment.create", "scheduling.enrollment.cancel"
MARK, MARK_EXCEPTION = "scheduling.attendance.mark", "scheduling.attendance.mark_exception"
PAGE = "/direct-link"  # the web page; the token follows in the fragment, never the query string


# --- direct registration links (SCH-16) --------------------------------------------------------------------


def _link_seat(session: Db, principal: Principal, session_id: UUID) -> tuple[Session, Booking]:
    seat = service._load(session, principal, Session, session_id, lock=True)
    booking = session.get_one(Booking, seat.booking_id)
    service._authorize(
        session, principal, LINK, seat.location_id, service._resource_ids(session, booking), booking.reservation_type_id
    )
    return seat, booking


def _link_view(seat: Session) -> dict:
    return {
        "session_id": seat.id, "is_active": seat.is_direct_link_active, "token": seat.direct_link_token,
        "path": f"{PAGE}#token={seat.direct_link_token}",
    }  # fmt: skip


def _link_changed(session: Db, seat: Session, was: bool) -> None:
    audit.record(session, LINK, seat, location_id=seat.location_id, changes={"is_direct_link_active": [was, not was]})
    events.publish(
        session, ev.DirectLinkChanged(session_id=seat.id, location_id=seat.location_id, is_active=not was), seat.id
    )
    session.flush()


def create_link(session: Db, principal: Principal, session_id: UUID) -> dict:
    """Turn the session's link on, or return it when it already is (a repeat changes nothing)."""
    seat, booking = _link_seat(session, principal, session_id)
    if booking.status == "cancelled":
        raise Conflict("A cancelled session cannot be shared.", code="invalid-state-transition")
    if not seat.is_direct_link_active:
        seat.is_direct_link_active = True
        _link_changed(session, seat, False)
    return _link_view(seat)


def revoke_link(session: Db, principal: Principal, session_id: UUID) -> None:
    """Stop the link: the token is replaced, so copies already sent no longer resolve. Idempotent."""
    seat, _ = _link_seat(session, principal, session_id)
    if seat.is_direct_link_active:
        seat.is_direct_link_active = False
        seat.direct_link_token = secrets.token_urlsafe(16)
        _link_changed(session, seat, True)


def resolve_link(session: Db, token: str) -> dict:
    """Public: the session an active link names, while it is still ahead. Only what the booking page shows."""
    seat = session.scalar(select(Session).where(Session.direct_link_token == token, Session.is_direct_link_active))
    booking = session.get(Booking, seat.booking_id) if seat is not None else None
    if seat is None or booking is None or booking.status != "confirmed" or booking.ends_at <= clock.now():
        raise NotFound("This link is not valid any more.", code="link-invalid")
    return {
        "session_id": seat.id, "title": booking.public_title or booking.title or "Session",
        "starts_at": booking.starts_at, "ends_at": booking.ends_at,
        "location_name": platform.service.location_name(session, seat.location_id),
        "time_zone": platform.service.location_time_zone(session, seat.location_id),
        "spots_left": max(seat.capacity - seat.booked_count, 0),
    }  # fmt: skip


# --- shared bookings (SCH-17, SSP-09) ----------------------------------------------------------------------


def _shareable(session: Db, principal: Principal, booking_id: UUID, key: str) -> Booking:
    booking = service._own(session, principal, booking_id, key)
    if booking.kind == "block":
        raise Conflict("A time block has no clients.", code="invalid-state-transition")
    return booking


def _participants(session: Db, booking_id: UUID) -> list[BookingParticipant]:
    stmt = select(BookingParticipant).where(BookingParticipant.booking_id == booking_id)
    return list(session.scalars(stmt.order_by(BookingParticipant.created_at, BookingParticipant.id)))


def _views(session: Db, booking: Booking) -> list[dict]:
    rows = _participants(session, booking.id)
    names = clients.service.display_names(session, [row.client_id for row in rows])
    return [
        {c.key: getattr(row, c.key) for c in BookingParticipant.__table__.columns}
        | {"client_name": names.get(row.client_id), "is_organiser": row.client_id == booking.client_id}
        for row in rows
    ]


def list_participants(session: Db, principal: Principal, booking_id: UUID) -> list[dict]:
    booking = service._load(session, principal, Booking, booking_id)
    authorize(principal, service.READ, location_id=booking.location_id)
    return _views(session, booking)


def _related(session: Db, organiser_id: UUID) -> set[UUID]:
    return {
        rel.to_client_id if rel.from_client_id == organiser_id else rel.from_client_id
        for rel in clients.households.relationships_of(session, organiser_id, live_only=True)
        if rel.status == "active"
    }


def _insert(session: Db, booking: Booking, client_id: UUID, staff_user_id: UUID | None) -> BookingParticipant:
    row = BookingParticipant(
        booking_id=booking.id,
        location_id=booking.location_id,
        client_id=client_id,
        added_by_staff_user_id=staff_user_id,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        raise Conflict("This client is already on the booking.", code="already-enrolled") from None
    return row


def _event(row: BookingParticipant) -> dict:
    return {
        "participant_id": row.id, "booking_id": row.booking_id, "location_id": row.location_id,
        "client_id": row.client_id, "attendance": row.attendance,
    }  # fmt: skip


def add_participant(session: Db, principal: Principal, booking_id: UUID, client_id: UUID) -> list[dict]:
    """Share the booking with one more client. With an organiser, the client must be their active relative (a
    spouse, a player of the coach's team); the organiser is listed too once the booking is shared."""
    booking = _shareable(session, principal, booking_id, ENROLL)
    if booking.status == "cancelled":
        raise Conflict("A cancelled booking cannot be shared.", code="invalid-state-transition")
    clients.service.require_active(session, client_id)
    organiser = booking.client_id
    if organiser is not None and client_id != organiser and client_id not in _related(session, organiser):
        raise ValidationFailed("Only the organiser's related clients can share this booking.", pointer="/client_id")
    staff_user_id = principal.staff_user_id if principal.kind == "staff" else None
    on_booking = {row.client_id for row in _participants(session, booking.id)}
    if organiser is not None and organiser not in on_booking and client_id != organiser:
        _insert(session, booking, organiser, staff_user_id)
    row = _insert(session, booking, client_id, staff_user_id)
    audit.record(session, ENROLL, row, location_id=booking.location_id, changes={"booking_id": [None, str(booking.id)]})
    events.publish(session, ev.ParticipantAdded(**_event(row)), row.id)
    return _views(session, booking)


def _participant(session: Db, booking: Booking, participant_id: UUID) -> BookingParticipant:
    row = session.get(BookingParticipant, participant_id, with_for_update=True)
    if row is None or row.booking_id != booking.id:
        raise NotFound()
    return row


def remove_participant(session: Db, principal: Principal, booking_id: UUID, participant_id: UUID) -> None:
    booking = _shareable(session, principal, booking_id, UNENROLL)
    row = _participant(session, booking, participant_id)
    if row.client_id == booking.client_id:
        raise Conflict(
            "The organiser stays on the booking; cancel the booking instead.", code="invalid-state-transition"
        )
    audit.record(
        session, UNENROLL, row, location_id=booking.location_id, changes={"booking_id": [str(booking.id), None]}
    )
    events.publish(session, ev.ParticipantRemoved(**_event(row)), row.id)
    session.delete(row)
    session.flush()


def mark_attendance(session: Db, principal: Principal, booking_id: UUID, participant_id: UUID, attendance: str) -> dict:
    """One participant's own attendance. A no-show needs the exception key, as for enrolments."""
    booking = _shareable(session, principal, booking_id, MARK)
    if attendance == "no_show":
        authorize(principal, MARK_EXCEPTION, location_id=booking.location_id)
    if booking.status == "cancelled":
        raise Conflict("A cancelled booking takes no attendance.", code="invalid-state-transition")
    row = _participant(session, booking, participant_id)
    if row.attendance != attendance:
        changes = {"attendance": [row.attendance, attendance]}
        row.attendance, row.attendance_marked_at = attendance, None if attendance == "scheduled" else clock.now()
        audit.record(session, MARK, row, location_id=booking.location_id, changes=changes)
        events.publish(session, ev.ParticipantAttendanceMarked(**_event(row)), row.id)
        session.flush()
    return next(view for view in _views(session, booking) if view["id"] == row.id)
