"""Scheduling's side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2).
Bookings move to the survivor on a merge. Erasure keeps past bookings (the calendar's history) without their
notes and is blocked while the client still has a booking ahead: staff cancel or reassign it first. Shared-booking
participant rows move on a merge (a duplicate on the same booking folds into the survivor's) and stay on erasure as
attendance history, like the bookings they belong to."""

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.modules import clients, platform
from app.modules.scheduling.models import Booking, BookingParticipant


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    session.execute(update(Booking).where(Booking.client_id == loser_id).values(client_id=survivor_id))
    p = BookingParticipant
    both = select(p.booking_id).where(p.client_id == survivor_id)
    session.execute(delete(p).where(p.client_id == loser_id, p.booking_id.in_(both)))
    session.execute(update(p).where(p.client_id == loser_id).values(client_id=survivor_id))


def _export(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(select(Booking).where(Booking.client_id == client_id).order_by(Booking.starts_at))
    return {"bookings": [
        {"booking_number": r.booking_number, "title": r.title, "starts_at": r.starts_at.isoformat(),
         "ends_at": r.ends_at.isoformat(), "status": r.status}
        for r in rows
    ], "shared_bookings": [
        {"booking_id": str(r.booking_id), "attendance": r.attendance}
        for r in session.scalars(select(BookingParticipant).where(BookingParticipant.client_id == client_id))
    ]}  # fmt: skip


def _erase_precheck(session: Session, client_id: UUID) -> list[dict]:
    ahead = select(Booking.id).where(
        Booking.client_id == client_id, Booking.status != "cancelled", Booking.ends_at > clock.now()
    )
    if session.scalar(ahead.limit(1)):
        return [{"code": "upcoming-booking", "detail": "The client still has a booking ahead."}]
    return []


def _erase(session: Session, client_id: UUID) -> dict:
    kept = session.execute(
        update(Booking).where(Booking.client_id == client_id).values(notes=None, cancel_reason=None)
    ).rowcount
    return {"retained_bookings": kept}


_TABLES = ("booking", "booking_participant")
clients.merge.register_merge_handler("scheduling", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler(
    "scheduling", tables=_TABLES, export=_export, erase=_erase, precheck=_erase_precheck
)
