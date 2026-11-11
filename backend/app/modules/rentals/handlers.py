"""Subscribers of the rentals context. Each runs as a tenant actor, once per event, and is idempotent."""

from uuid import UUID

from app.core.events import handles
from app.modules.rentals import service


@handles("scheduling.booking.cancelled")
def settle_cancelled_rental(session, payload: dict) -> None:
    """A rental cancelled on the calendar, or a checkout hold that ran out, settles its money."""
    if payload.get("source_context") == "rentals":
        service.on_booking_cancelled(session, UUID(payload["booking_id"]))


@handles("scheduling.booking.rescheduled")
def follow_rescheduled_rental(session, payload: dict) -> None:
    if payload.get("source_context") == "rentals":
        service.on_booking_rescheduled(session, UUID(payload["booking_id"]))


@handles("billing.invoice.paid")
def confirm_paid_checkout(session, payload: dict) -> None:
    service.on_invoice_paid(session, UUID(payload["invoice_id"]))
