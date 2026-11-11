"""Events engagement consumes: reminders follow bookings and enrollments, automations follow their triggers,
and staff alert routes hear about promotions and declined payments. Handlers re-read state and are idempotent
(scheduled rows and messages carry dedupe keys)."""

from uuid import UUID

from app.core.errors import NotFound
from app.core.events import handles
from app.modules import billing, scheduling
from app.modules.engagement import service


def _booking_reminders(session, payload: dict) -> None:
    try:
        booking = scheduling.service.get_booking(session, UUID(payload["booking_id"]))
    except NotFound:
        return
    if booking.status != "confirmed" or booking.client_id is None:
        return
    service.schedule_reminders(session, subject_type="booking", subject_id=booking.id, client_id=booking.client_id,
                               location_id=booking.location_id, starts_at=booking.starts_at, title=booking.title)  # fmt: skip


@handles("scheduling.booking.created")
def on_booking_created(session, payload: dict) -> None:
    _booking_reminders(session, payload)


@handles("scheduling.booking.rescheduled")
def on_booking_rescheduled(session, payload: dict) -> None:
    _booking_reminders(session, payload)


@handles("scheduling.booking.cancelled")
def on_booking_cancelled(session, payload: dict) -> None:
    service.cancel_notifications(session, subject_type="booking", subject_id=UUID(payload["booking_id"]))


@handles("programs.enrollment.created")
def on_enrollment_created(session, payload: dict) -> None:
    if "session_id" not in payload:  # a whole-group enrollment has no single start to remind about
        service.on_trigger(session, "programs.enrollment.created", payload)
        return
    try:
        seat = scheduling.service.get_session(session, UUID(payload["session_id"]))
    except NotFound:
        return
    service.schedule_reminders(
        session, subject_type="enrollment", subject_id=UUID(payload["enrollment_id"]),
        client_id=UUID(payload["client_id"]), location_id=seat["location_id"], starts_at=seat["starts_at"],
        title=seat.get("public_title") or seat.get("title"),
    )  # fmt: skip
    service.on_trigger(session, "programs.enrollment.created", payload)


@handles("programs.enrollment.cancelled")
def on_enrollment_cancelled(session, payload: dict) -> None:
    service.cancel_notifications(session, subject_type="enrollment", subject_id=UUID(payload["enrollment_id"]))


@handles("programs.waitlist.promoted")
def on_waitlist_promoted(session, payload: dict) -> None:
    service.on_trigger(session, "programs.waitlist.promoted", payload)
    if "session_id" not in payload:  # a group waitlist promotion names no single session
        return
    try:
        seat = scheduling.service.get_session(session, UUID(payload["session_id"]))
    except NotFound:
        return
    service.alert_staff(session, seat["location_id"], "waitlist_promoted", "Waitlist place filled",
                        f"A waitlisted client was moved into {seat.get('title') or 'a session'}.",
                        dedupe=payload["waitlist_entry_id"])  # fmt: skip


@handles("clients.client.created")
def on_client_created(session, payload: dict) -> None:
    service.on_trigger(session, "clients.client.created", payload)


@handles("memberships.contract.activated")
def on_contract_activated(session, payload: dict) -> None:
    service.on_trigger(session, "memberships.contract.activated", payload)


@handles("memberships.contract.renewed")
def on_contract_renewed(session, payload: dict) -> None:
    service.on_trigger(session, "memberships.contract.renewed", payload)


@handles("billing.payment.failed")
def on_payment_failed(session, payload: dict) -> None:
    service.on_trigger(session, "billing.payment.failed", payload)
    payment = billing.service.get_payment(session, service.SYSTEM, UUID(payload["payment_id"]))
    if payment.get("location_id"):
        service.alert_staff(session, payment["location_id"], "payment_declined", "Payment declined",
                            "A card payment was declined. Open the client's billing to follow up.",
                            dedupe=payload["payment_id"])  # fmt: skip
