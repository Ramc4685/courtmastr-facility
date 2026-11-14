"""Events access consumes. A disabled client's wallet passes are revoked (CHK-13). A booking created, moved or
cancelled, or a session cancelled, re-syncs its door codes at once (CHK-16; a checkout hold confirmed without an
event is caught by the minute tick); a new participant gets their own code; an enrolment cancelled or moved and a
payment failed, refunded, voided or disputed re-check the client's codes. The door re-checks all of it anyway. All idempotent: revoking
twice finds nothing active, a synced code is left alone, a repeated email is the only duplicate (accepted)."""

from uuid import UUID

from app.core.errors import NotFound
from app.core.events import handles
from app.modules import scheduling
from app.modules.access import building, service


@handles("clients.client.disabled")
def on_client_disabled(session, payload: dict) -> None:
    service.revoke_wallet_passes_of(session, UUID(payload["client_id"]))


@handles("clients.client.age_confirmed")
def on_age_confirmed(session, payload: dict) -> None:
    building.issue_held_codes(session, UUID(payload["client_id"]))


@handles("clients.client.updated")
def on_client_updated(session, payload: dict) -> None:
    """A changed birth date unconfirms the person and fires nothing else: their active codes are re-checked now
    (the door and the minute tick re-check too)."""
    building.resync_client_codes(session, UUID(payload["client_id"]))


@handles("clients.client.merged")
def on_client_merged(session, payload: dict) -> None:
    """A merge may unconfirm the survivor (clients README) and fires no reverse event."""
    building.resync_client_codes(session, UUID(payload["survivor_client_id"]))


@handles("scheduling.booking.created")
def on_booking_created(session, payload: dict) -> None:
    building.sync_booking_code(session, UUID(payload["booking_id"]))


@handles("scheduling.booking.rescheduled")
def on_booking_rescheduled(session, payload: dict) -> None:
    building.sync_booking_code(session, UUID(payload["booking_id"]))


@handles("scheduling.booking.cancelled")
def on_booking_cancelled(session, payload: dict) -> None:
    building.sync_booking_code(session, UUID(payload["booking_id"]))


@handles("scheduling.session.cancelled")
def on_session_cancelled(session, payload: dict) -> None:
    building.sync_booking_code(session, UUID(payload["booking_id"]))


def _sync_seat(session, payload: dict) -> None:
    """A new participant of a session that already has codes gets their own (a whole-group enrollment is caught
    by the minute tick, which syncs every booking inside the horizon)."""
    if "session_id" not in payload:
        return
    try:
        seat = scheduling.service.get_session(session, UUID(payload["session_id"]))
    except NotFound:
        return
    building.sync_booking_code(session, seat["booking_id"])


@handles("programs.enrollment.created")
def on_enrolled(session, payload: dict) -> None:
    _sync_seat(session, payload)


@handles("programs.waitlist.promoted")
def on_promoted(session, payload: dict) -> None:
    _sync_seat(session, payload)  # not on_enrolled: a @handles function is its actor, called with a tenant id


@handles("programs.enrollment.cancelled")
def on_enrollment_ended(session, payload: dict) -> None:
    """Cancelled or withdrawn (session or whole group): the client's codes are re-checked at once."""
    building.recheck_client_codes(session, UUID(payload["client_id"]))


@handles("programs.enrollment.moved")
def on_enrollment_moved(session, payload: dict) -> None:
    building.recheck_client_codes(session, UUID(payload["client_id"]))


def _money_back(session, payload: dict) -> None:
    """A holder the check-in evaluation now refuses (paid entry) loses their codes."""
    if payload.get("client_id"):
        building.recheck_client_codes(session, UUID(payload["client_id"]))


@handles("billing.payment.failed")
def on_payment_changed(session, payload: dict) -> None:
    _money_back(session, payload)


@handles("billing.payment.refunded")
def on_payment_refunded(session, payload: dict) -> None:
    _money_back(session, payload)


@handles("billing.payment.voided")
def on_payment_voided(session, payload: dict) -> None:
    _money_back(session, payload)


@handles("billing.payment.disputed")
def on_payment_disputed(session, payload: dict) -> None:
    _money_back(session, payload)
