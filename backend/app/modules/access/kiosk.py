"""access kiosk: the reservation page after a self check-in, booking from it, and auto-book (CHK-05, CHK-06; owner
decisions 2026-11-13, question 15).

Internal functions for the kiosk router (device cookie, no principal). An admitted check-in is handed a visit token
(stored hashed, `kiosk_visit`): every action on the visit spends it and gets a fresh one, it dies at its screens'
timeouts, and it ends when the kiosk goes back to its start screen or takes the next check-in. Booking goes through
programs' kiosk functions, which apply the portal's rules unchanged, and the past-due lockout applies to the
visitor's household (the visitor and every client one acting relationship away), as the portal guard does online.
Spending anything (a package credit) needs identification by possession (a verified app-card QR or an active wallet
pass); a static card, fob or member number, or a visit found by name, books only free sessions, when the location
allows even that. Refusals that would reveal the client's standing answer only "see staff"."""

import secrets
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import tokens
from app.core.errors import Conflict, DomainError, NotFound
from app.modules import billing, clients, programs
from app.modules.access import events as ev
from app.modules.access import service
from app.modules.access.models import CheckIn, CheckInAttendance, KioskDevice, KioskVisit

VISIT_GRACE = timedelta(seconds=5)  # the network round trips on top of the screens' own timeouts


def _by_possession(row: CheckIn) -> bool:
    return row.identified_by == "credential"


def end_visits(session: Session, device: KioskDevice) -> None:
    """The kiosk is back at its start screen: every visit token it holds stops working."""
    session.execute(delete(KioskVisit).where(KioskVisit.kiosk_device_id == device.id))


def _issue(session: Session, device: KioskDevice, row: CheckIn, config: dict) -> str:
    """A fresh visit token, alive for the result screen and then the reservation page."""
    raw = secrets.token_urlsafe(24)
    ttl = timedelta(seconds=config["confirmation_timeout_seconds"] + config["reservation_timeout_seconds"])
    session.add(KioskVisit(
        kiosk_device_id=device.id, check_in_id=row.id, token_hash=tokens.digest(raw),
        expires_at=clock.now() + ttl + VISIT_GRACE,
    ))  # fmt: skip
    return raw


def visit(session: Session, device: KioskDevice, check_in_id: UUID, token: str) -> CheckIn:
    """Spend the visit token this device holds for this admitted, open check-in; anything else is 404. A refused
    action rolls back with its transaction, so the token stays good for another choice until it expires."""
    # One statement, so two concurrent taps cannot both spend it: the second waits on the row lock, then matches none.
    spent = session.scalar(
        delete(KioskVisit)
        .where(
            KioskVisit.token_hash == tokens.digest(token), KioskVisit.kiosk_device_id == device.id,
            KioskVisit.check_in_id == check_in_id, KioskVisit.expires_at >= clock.now(),
        )
        .returning(KioskVisit.id)
    )  # fmt: skip
    if spent is None:
        raise NotFound()
    row = session.get_one(CheckIn, check_in_id)
    if row.result == "denied" or row.checked_out_at is not None:
        raise NotFound()
    return row


# A booking from the page is an enrolment, audited as the desk audits one, never a second check-in.
ENROLL = "scheduling.enrollment.create"


def see_staff() -> Conflict:
    return Conflict("Please see the front desk.", code="see-staff")


def _until(config: dict):
    return clock.now() + timedelta(minutes=config["visible_range_minutes"])


def _may_book(session: Session, row: CheckIn, config: dict) -> bool:
    if not _by_possession(row) and not config["is_name_search_booking_allowed"]:
        return False
    # The household, as the portal guard checks an identity's clients: a child billed to a past-due parent is locked.
    return not billing.collections.is_portal_locked(session, clients.households.household_ids(session, row.client_id))


def _sessions(session: Session, row: CheckIn, config: dict, *, free_only: bool | None = None) -> list[dict]:
    """The reservation page; `free_only` defaults to the visit's rule (not identified by possession)."""
    free_only = not _by_possession(row) if free_only is None else free_only
    listed = programs.selfservice.kiosk_sessions(
        session, row.client_id, row.location_id, _until(config), free_only=free_only
    )
    if not _may_book(session, row, config):
        for seat in listed:
            seat["is_bookable"] = False
    return listed


def _book(session: Session, row: CheckIn, session_id: UUID, config: dict, *, free_only: bool | None = None) -> None:
    """Enrol through programs' kiosk rules, then mark the place attended when it starts inside the kiosk's
    check-in window (the same window the check-in itself marks). Found by name: free sessions only, and any
    refusal is see-staff, so a name alone learns nothing about the client."""
    if not _may_book(session, row, config):
        raise see_staff()
    free_only = not _by_possession(row) if free_only is None else free_only
    try:
        with session.begin_nested():  # a refusal undoes the seat it reserved, so "already enrolled" can go on
            enrollment = programs.selfservice.kiosk_enroll(
                session, row.client_id, row.location_id, session_id, _until(config), free_only=free_only
            )
    except DomainError as exc:
        if exc.code == "already-enrolled":
            enrollment = None  # the place is held already (or pending, or just taken on another kiosk): check in to it
        elif _by_possession(row) or exc.status >= 500:
            raise
        else:
            raise see_staff() from None
    marked = programs.service.mark_attended_by_check_in(
        session, client_id=row.client_id, location_id=row.location_id, at=clock.now(),
        early=timedelta(minutes=config["late_window_minutes"]), late=timedelta(minutes=config["early_window_minutes"]),
        source="kiosk", session_id=session_id,
    )  # fmt: skip
    for enrollment_id, marked_session_id in marked:
        session.add(CheckInAttendance(
            check_in_id=row.id, target_id=enrollment_id, session_id=marked_session_id,
            was_auto_booked=enrollment is not None,
        ))  # fmt: skip
    if enrollment is None:
        session.flush()
        return
    audit.record(
        session,
        ENROLL,
        row,
        location_id=row.location_id,
        changes={"booked_session_id": [None, str(session_id)]},
    )
    events.publish(session, ev.CheckInSessionBooked(
        check_in_id=row.id, client_id=row.client_id, location_id=row.location_id, enrollment_id=enrollment.id,
        session_id=session_id,
    ), row.id)  # fmt: skip
    session.flush()


def result(session: Session, row: CheckIn, config: dict, sessions: list[dict], token: str | None = None) -> dict:
    """The kiosk's view of a visit: first name, the alerts the location shows, places marked, the reservation
    page and the visit token for the next action. Never amounts, reasons or plan names; found by name, not even
    which sessions the client already holds."""
    admitted = row.result != "denied"
    shown = set(config["displayed_alert_codes"]) if admitted else set()
    if not _by_possession(row):
        sessions = [{**seat, "is_booked": False} for seat in sessions]
    return {
        "check_in_id": row.id, "status": "admitted" if admitted else "see_staff",
        "first_name": clients.service.get(session, row.client_id).first_name,
        "displayed_alert_codes": [c for c in row.alert_codes if c in shown],
        "attended": service.check_in_view(session, row)["attended"], "welcome_message": config["welcome_message"],
        "sessions": sessions if admitted else [], "visit_token": token if admitted else None,
    }  # fmt: skip


def check_in(session: Session, device: KioskDevice, data: dict) -> dict:
    """Self check-in, then the reservation page. With auto-book on and no place already held in the window, the
    earliest bookable session that consumes nothing (free booking) is booked, whatever the identification: a
    package credit or a charge is spent only when the person picks the session on screen. Auto-book is best effort
    and never undoes the check-in. Any visit the kiosk still held ends here."""
    end_visits(session, device)
    row = session.get_one(CheckIn, service.kiosk_check_in(session, device, data)["check_in_id"])
    config = service.settings_view(session, device.location_id)
    if row.result == "denied":
        return result(session, row, config, [])
    listed = _sessions(session, row, config)
    marked = service.check_in_view(session, row)["attended"]
    held = any(a["target_type"] == "enrollment" for a in marked) or any(s["is_booked"] for s in listed)
    free = _sessions(session, row, config, free_only=True) if config["is_auto_book"] and not held else []
    pick = next((s for s in free if s["is_bookable"]), None)
    if pick:
        try:
            with session.begin_nested():
                _book(session, row, pick["target_id"], config, free_only=True)
        except DomainError:
            pass  # a refusal leaves the client checked in with the page to choose from
        else:
            listed = _sessions(session, row, config)
    return result(session, row, config, listed, _issue(session, device, row, config))


def attend(session: Session, device: KioskDevice, check_in_id: UUID, data: dict) -> dict:
    """Book a session from the reservation page (createKioskAttendance), spending the visit token."""
    row = visit(session, device, check_in_id, data["visit_token"])
    config = service.settings_view(session, device.location_id)
    _book(session, row, data["target_id"], config)
    return result(session, row, config, _sessions(session, row, config), _issue(session, device, row, config))
