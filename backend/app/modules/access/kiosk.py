"""access kiosk: the reservation page after a self check-in, booking from it, and auto-book (CHK-05, CHK-06; owner
decisions 2026-11-13, question 15).

Internal functions for the kiosk router (device cookie, no principal). The kiosk acts for the client of one of its
own admitted check-ins for `KIOSK_VISIT` after it; the check-in id never leaves that device's session. Booking goes
through programs' kiosk functions, which apply the portal's rules unchanged, and the past-due lockout applies as
it does online. Refusals that would reveal the client's standing answer only "see staff"."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.errors import Conflict, DomainError, NotFound
from app.modules import billing, clients, programs
from app.modules.access import events as ev
from app.modules.access import service
from app.modules.access.models import CheckIn, CheckInAttendance, KioskDevice

KIOSK_VISIT = timedelta(minutes=10)  # how long after a self check-in the kiosk may still act for that client


def visit(session: Session, device: KioskDevice, check_in_id: UUID) -> CheckIn:
    """An admitted, open check-in this device took in the last ten minutes; anything else is 404."""
    row = session.get(CheckIn, check_in_id)
    if (
        row is None or row.kiosk_device_id != device.id or row.result == "denied" or row.checked_out_at is not None
        or row.checked_in_at < clock.now() - KIOSK_VISIT
    ):  # fmt: skip
        raise NotFound()
    return row


def see_staff() -> Conflict:
    return Conflict("Please see the front desk.", code="see-staff")


def _until(config: dict):
    return clock.now() + timedelta(minutes=config["visible_range_minutes"])


def _sessions(session: Session, row: CheckIn, config: dict) -> list[dict]:
    listed = programs.selfservice.kiosk_sessions(session, row.client_id, row.location_id, _until(config))
    if billing.collections.is_portal_locked(session, [row.client_id]):
        for seat in listed:
            seat["is_bookable"] = False
    return listed


def _book(session: Session, row: CheckIn, session_id: UUID, config: dict) -> None:
    """Enrol through programs' kiosk rules, then mark the place attended when it starts inside the kiosk's
    check-in window (the same window the check-in itself marks)."""
    if billing.collections.is_portal_locked(session, [row.client_id]):
        raise see_staff()
    enrollment = programs.selfservice.kiosk_enroll(session, row.client_id, row.location_id, session_id, _until(config))
    marked = programs.service.mark_attended_by_check_in(
        session, client_id=row.client_id, location_id=row.location_id, at=clock.now(),
        early=timedelta(minutes=config["late_window_minutes"]), late=timedelta(minutes=config["early_window_minutes"]),
        source="kiosk", session_id=session_id,
    )  # fmt: skip
    for enrollment_id, marked_session_id in marked:
        session.add(CheckInAttendance(
            check_in_id=row.id, target_id=enrollment_id, session_id=marked_session_id, was_auto_booked=True
        ))  # fmt: skip
    audit.record(
        session,
        service.CREATE,
        row,
        location_id=row.location_id,
        changes={"booked_session_id": [None, str(session_id)]},
    )
    events.publish(session, ev.CheckInSessionBooked(
        check_in_id=row.id, client_id=row.client_id, location_id=row.location_id, enrollment_id=enrollment.id,
        session_id=session_id,
    ), row.id)  # fmt: skip
    session.flush()


def result(session: Session, row: CheckIn, config: dict, sessions: list[dict]) -> dict:
    """The kiosk's view of a visit: first name, the alerts the location shows, places marked, the reservation
    page. Never amounts, reasons or plan names."""
    admitted = row.result != "denied"
    shown = set(config["displayed_alert_codes"]) if admitted else set()
    return {
        "check_in_id": row.id, "status": "admitted" if admitted else "see_staff",
        "first_name": clients.service.get(session, row.client_id).first_name,
        "displayed_alert_codes": [c for c in row.alert_codes if c in shown],
        "attended": service.check_in_view(session, row)["attended"], "welcome_message": config["welcome_message"],
        "sessions": sessions if admitted else [],
    }  # fmt: skip


def check_in(session: Session, device: KioskDevice, data: dict) -> dict:
    """Self check-in, then the reservation page. With auto-book on and no place already held in the window, the
    earliest bookable session is booked; auto-book is best effort and never undoes the check-in."""
    row = session.get_one(CheckIn, service.kiosk_check_in(session, device, data)["check_in_id"])
    config = service.settings_view(session, device.location_id)
    if row.result == "denied":
        return result(session, row, config, [])
    listed = _sessions(session, row, config)
    marked = service.check_in_view(session, row)["attended"]
    held = any(a["target_type"] == "enrollment" for a in marked) or any(s["is_booked"] for s in listed)
    pick = next((s for s in listed if s["is_bookable"]), None)
    if config["is_auto_book"] and pick and not held:
        try:
            with session.begin_nested():
                _book(session, row, pick["target_id"], config)
        except DomainError:
            pass  # a refusal leaves the client checked in with the page to choose from
        else:
            listed = _sessions(session, row, config)
    return result(session, row, config, listed)


def attend(session: Session, device: KioskDevice, check_in_id: UUID, data: dict) -> dict:
    """Book a session from the reservation page (createKioskAttendance)."""
    row = visit(session, device, check_in_id)
    config = service.settings_view(session, device.location_id)
    _book(session, row, data["target_id"], config)
    return result(session, row, config, _sessions(session, row, config))
