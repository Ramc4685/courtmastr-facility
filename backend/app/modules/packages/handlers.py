"""Events packages consumes (overview section 2). Handlers re-read current state and are idempotent.

The three `scheduling.booking.*` subscriptions are the narrow interface packages needs from the calendar engine,
which is built in another lane. Expected payloads (ids as strings):

- `scheduling.booking.created`: `booking_id`, `client_id`, and, when a package pays, `client_package_id`;
  optional `starts_on` (location-local date of the session) and `reservation_type_id`.
- `scheduling.booking.cancelled`: `booking_id`, optional `is_late` (inside the late-cancel window).
- `scheduling.booking.completed`: `booking_id`, `outcome` = `attended` or `no_show`.

A context above packages (programs, the portal checkout) may call `service.reserve_credit` and
`service.settle_credit` directly instead and get the refusal synchronously.
"""

from uuid import UUID

from app.core.events import handles
from app.modules.packages import service


@handles("scheduling.booking.created")
def on_booking_created(session, payload: dict) -> None:
    service.booking_created(session, payload)


@handles("scheduling.booking.cancelled")
def on_booking_cancelled(session, payload: dict) -> None:
    outcome = "late_cancel" if payload.get("is_late") else "early_cancel"
    service.settle_credit(session, source_type="booking", source_id=UUID(payload["booking_id"]), outcome=outcome)


@handles("scheduling.booking.completed")
def on_booking_completed(session, payload: dict) -> None:
    outcome = "no_show" if payload.get("outcome") == "no_show" else "attended"
    service.settle_credit(session, source_type="booking", source_id=UUID(payload["booking_id"]), outcome=outcome)


@handles("memberships.contract.activated")
def on_contract_activated(session, payload: dict) -> None:
    service.grant_contract_addons(session, UUID(payload["contract_id"]))


@handles("memberships.contract.cancelled")
def on_contract_cancelled(session, payload: dict) -> None:
    if payload.get("cancel_packages"):
        service.remove_contract_addons(session, UUID(payload["contract_id"]))
