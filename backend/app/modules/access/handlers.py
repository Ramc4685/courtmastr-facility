"""Events access consumes. A disabled client's wallet passes are revoked (CHK-13). A booking created, moved or
cancelled re-syncs its door code at once (CHK-16; a checkout hold confirmed without an event is caught by the
minute tick), and someone registering on a session that already has a code is sent it. All idempotent: revoking
twice finds nothing active, a synced code is left alone, a repeated email is the only duplicate (accepted)."""

from uuid import UUID

from app.core.errors import NotFound
from app.core.events import handles
from app.modules import scheduling
from app.modules.access import building, service


@handles("clients.client.disabled")
def on_client_disabled(session, payload: dict) -> None:
    service.revoke_wallet_passes_of(session, UUID(payload["client_id"]))


@handles("scheduling.booking.created")
def on_booking_created(session, payload: dict) -> None:
    building.sync_booking_code(session, UUID(payload["booking_id"]))


@handles("scheduling.booking.rescheduled")
def on_booking_rescheduled(session, payload: dict) -> None:
    building.sync_booking_code(session, UUID(payload["booking_id"]))


@handles("scheduling.booking.cancelled")
def on_booking_cancelled(session, payload: dict) -> None:
    building.sync_booking_code(session, UUID(payload["booking_id"]))


@handles("programs.enrollment.created")
def on_enrolled(session, payload: dict) -> None:
    if "session_id" not in payload:  # a whole-group enrollment: each session's code goes out at issue
        return
    try:
        seat = scheduling.service.get_session(session, UUID(payload["session_id"]))
    except NotFound:
        return
    building.on_enrolled(session, seat["booking_id"], UUID(payload["client_id"]))
