"""access kiosk: the reservation page after a self check-in, booking from it, and auto-book (CHK-05, CHK-06; owner
decisions 2026-11-13, question 15).

Internal functions for the kiosk router (device cookie, no principal). An admitted check-in is handed a visit token
(stored hashed, `kiosk_visit`): every action on the visit spends it and gets a fresh one, it dies at its screens'
timeouts, and it ends when the kiosk goes back to its start screen or takes the next check-in. Booking goes through
programs' kiosk functions, which apply the portal's rules unchanged, and the past-due lockout applies as it does
online. Spending a package credit needs identification by possession, a card or the app's code; charging the card
on file needs a signed card payload (`signed_card`); a visit found by name books only free sessions, when the
location allows even that. Refusals that would reveal the
client's standing answer only "see staff"."""

import secrets
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import tokens
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.core.pagination import ListQuery
from app.modules import billing, clients, memberships, packages, platform, programs
from app.modules.access import events as ev
from app.modules.access import service
from app.modules.access.models import CheckIn, CheckInAttendance, KioskDevice, KioskVisit

VISIT_GRACE = timedelta(seconds=5)  # the network round trips on top of the screens' own timeouts


def _by_possession(row: CheckIn) -> bool:
    return row.identified_by in ("credential", "signed_card")


def _by_signed_card(row: CheckIn) -> bool:
    """Charging a card on file needs more than possession: a verified app QR or wallet-pass payload, never a
    typed or looked-up number (security review 2026-11-13)."""
    return row.identified_by == "signed_card"


def end_visits(session: Session, device: KioskDevice) -> None:
    """The kiosk is back at its start screen: every visit token it holds stops working."""
    session.execute(delete(KioskVisit).where(KioskVisit.kiosk_device_id == device.id))


def _issue(session: Session, device: KioskDevice, row: CheckIn, config: dict) -> str:
    """A fresh visit token, alive for the result screen and then the reservation or package page."""
    raw = secrets.token_urlsafe(24)
    page = max(config["reservation_timeout_seconds"], config["package_timeout_seconds"])
    ttl = timedelta(seconds=config["confirmation_timeout_seconds"] + page)
    session.add(KioskVisit(
        kiosk_device_id=device.id, check_in_id=row.id, token_hash=tokens.digest(raw),
        expires_at=clock.now() + ttl + VISIT_GRACE,
    ))  # fmt: skip
    return raw


def visit(session: Session, device: KioskDevice, check_in_id: UUID, token: str, *, spend: bool = True) -> CheckIn:
    """Spend the visit token this device holds for this admitted, open check-in; anything else is 404. A refused
    action rolls back with its transaction, so the token stays good for another choice until it expires. A read
    (`spend` False) checks the token without spending it."""
    held = session.scalar(select(KioskVisit).where(KioskVisit.token_hash == tokens.digest(token)))
    if (
        held is None or held.kiosk_device_id != device.id or held.check_in_id != check_in_id
        or held.expires_at < clock.now()
    ):  # fmt: skip
        raise NotFound()
    if spend:
        session.delete(held)
    row = session.get_one(CheckIn, check_in_id)
    if row.result == "denied" or row.checked_out_at is not None:
        raise NotFound()
    return row


def see_staff() -> Conflict:
    return Conflict("Please see the front desk.", code="see-staff")


def _until(config: dict):
    return clock.now() + timedelta(minutes=config["visible_range_minutes"])


def _may_book(session: Session, row: CheckIn, config: dict) -> bool:
    if not _by_possession(row) and not config["is_name_search_booking_allowed"]:
        return False
    return not billing.collections.is_portal_locked(session, [row.client_id])


def _sessions(session: Session, row: CheckIn, config: dict) -> list[dict]:
    listed = programs.selfservice.kiosk_sessions(
        session, row.client_id, row.location_id, _until(config), free_only=not _by_possession(row)
    )
    if not _may_book(session, row, config):
        for seat in listed:
            seat["is_bookable"] = False
    return listed


def _book(session: Session, row: CheckIn, session_id: UUID, config: dict) -> None:
    """Enrol through programs' kiosk rules, then mark the place attended when it starts inside the kiosk's
    check-in window (the same window the check-in itself marks). Found by name: free sessions only, and any
    refusal is see-staff, so a name alone learns nothing about the client."""
    if not _may_book(session, row, config):
        raise see_staff()
    try:
        enrollment = programs.selfservice.kiosk_enroll(
            session, row.client_id, row.location_id, session_id, _until(config), free_only=not _by_possession(row)
        )
    except DomainError as exc:
        if _by_possession(row) or exc.status >= 500:
            raise
        raise see_staff() from None
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
    earliest bookable session is booked (free only when found by name); auto-book is best effort and never undoes
    the check-in. Any visit the kiosk still held ends here."""
    end_visits(session, device)
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
    return result(session, row, config, listed, _issue(session, device, row, config))


# --- package purchase (card on file only) ------------------------------------------------------------------------


def _buyer(session: Session, device: KioskDevice, check_in_id: UUID, token: str, *, spend: bool) -> CheckIn:
    """The visit's client may buy here only when the location allows it, the check-in was by a signed card payload
    (the app's QR or a wallet pass; not a typed barcode, fob, member number or name), they are not a minor and have
    a default card on file. Anything else is 404: the kiosk never offers what it would refuse."""
    row = visit(session, device, check_in_id, token, spend=spend)
    client = clients.service.get(session, row.client_id)
    today = platform.service.location_today(session, row.location_id)
    if (
        not service.settings_view(session, device.location_id)["is_package_purchase_enabled"]
        or not _by_signed_card(row)
        or clients.service.is_minor(client, today, platform.service.minor_age(session))
        or billing.methods.autopay_method(session, row.client_id) is None
    ):  # fmt: skip
        raise NotFound()
    return row


def _plans(session: Session, row: CheckIn) -> list[dict]:
    member = memberships.service.is_member(session, row.client_id)
    out = []
    # shortcut: first page of 50 published plans; page through them if a location ever publishes more
    for plan in packages.service.public_list_plans(session, ListQuery(limit=50))["data"]:
        try:
            offer = packages.service.offer(session, plan["id"], row.location_id)
        except DomainError:
            continue  # recurring, ranged or unpriced: not for a one-tap sale
        out.append({
            "package_plan_id": plan["id"], "name": offer["name"], "price_minor": offer["price_minor"],
            "is_purchasable": member or not plan["is_members_only_online"],
        })  # fmt: skip
    return out


def package_plans(session: Session, device: KioskDevice, check_in_id: UUID, token: str) -> list[dict]:
    """The package page: plans published for online sale that a till could sell (one-off, priced, no quantity
    to choose), at their public price, marked whether this client may buy them (members-only plans)."""
    return _plans(session, _buyer(session, device, check_in_id, token, spend=False))


def buy_package(session: Session, device: KioskDevice, data: dict, idempotency_key: str) -> dict:
    """Buy a package for the visit's client with their default card on file, through packages' sale and billing's
    secured checkout, as the portal does; no card is entered on the tablet. A plan not offered to the client
    (members-only included) is 422. Any other refusal (decline, an unsigned document, portal terms the kiosk cannot
    show, past due) is 409 see-staff and nothing is sold;
    a document the sale issued for signing is kept for the desk."""
    row = _buyer(session, device, data["check_in_id"], data["visit_token"], spend=True)
    if billing.collections.is_portal_locked(session, [row.client_id]):
        raise see_staff()
    if data["package_plan_id"] not in {p["package_plan_id"] for p in _plans(session, row) if p["is_purchasable"]}:
        raise ValidationFailed("This package is not sold here.", pointer="/package_plan_id")
    method = billing.methods.autopay_method(session, row.client_id)
    try:
        clients.terms.acknowledge(
            session,
            client_id=row.client_id,
            terms_version_id=None,
            sale_kind="package",
            subject_id=data["package_plan_id"],
        )
        sold = packages.service.sell(
            session, client_id=row.client_id, location_id=row.location_id, package_plan_id=data["package_plan_id"],
            channel="portal", online=True, invoice_mode="single",
        )  # fmt: skip
        billing.checkout.secure_online_checkout(
            session, client_id=row.client_id, location_id=row.location_id, total_minor=sold["package"].price_minor,
            invoice=sold["invoice"], idempotency_key=f"kiosk:{device.id}:{idempotency_key}",
            payment_method_id=method.id if method else None, must_pay_now=True,
        )  # fmt: skip
    except DomainError as exc:
        if exc.status >= 500:
            raise  # the processor did not answer: a retry with the same key replays, nothing is a decline yet
        raise Conflict("Please see the front desk.", code="see-staff", persist=exc.persist) from None
    audit.record(session, service.CREATE, row, location_id=row.location_id,
                 changes={"package_purchased": [None, str(sold["package"].id)]})  # fmt: skip
    session.flush()
    config = service.settings_view(session, device.location_id)
    return result(session, row, config, _sessions(session, row, config), _issue(session, device, row, config))


def attend(session: Session, device: KioskDevice, check_in_id: UUID, data: dict) -> dict:
    """Book a session from the reservation page (createKioskAttendance), spending the visit token."""
    row = visit(session, device, check_in_id, data["visit_token"])
    config = service.settings_view(session, device.location_id)
    _book(session, row, data["target_id"], config)
    return result(session, row, config, _sessions(session, row, config), _issue(session, device, row, config))
