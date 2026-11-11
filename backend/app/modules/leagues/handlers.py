"""Subscribers of the leagues context. Each runs as a tenant actor, once per event, and is idempotent: a game
moved or cancelled on the calendar follows its booking."""

from uuid import UUID

from app.core.events import handles
from app.modules.leagues import service


@handles("scheduling.booking.rescheduled")
def follow_rescheduled_game(session, payload: dict) -> None:
    if payload.get("source_context") == "leagues":
        service.on_booking_rescheduled(session, UUID(payload["booking_id"]))


@handles("scheduling.booking.cancelled")
def follow_cancelled_game(session, payload: dict) -> None:
    if payload.get("source_context") == "leagues":
        service.on_booking_cancelled(session, UUID(payload["booking_id"]))
