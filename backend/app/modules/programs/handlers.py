"""Subscribers of the programs slice. Each runs as a tenant actor, once per event."""

from uuid import UUID

from app.core.events import handles
from app.modules.programs import service


@handles("scheduling.session.capacity_changed")
def promote_on_capacity_raise(session, payload: dict) -> None:
    if payload["new_capacity"] > payload["old_capacity"]:
        service.promote_waitlist(session, UUID(payload["session_id"]))


@handles("scheduling.session.cancelled")
def cancel_enrollments_of_cancelled_session(session, payload: dict) -> None:
    service.on_session_cancelled(session, UUID(payload["session_id"]))
