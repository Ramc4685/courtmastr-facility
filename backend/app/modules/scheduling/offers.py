"""Slot offers (SCH-07 "split into slots", SCH-18 trainer slots) and per-staff reservation type grants (SCH-05).

A slot offer sells an availability window as fixed-length slots. Slots are derived at query time; a slot becomes
a `booking` plus `session` (with `slot_offer_id`, `slot_starts_at`) only when it is taken, through
`service.create_booking`, so holds are still written by `service` alone and the exclusion constraint decides.
"""

import secrets
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as Db

from app.core import audit, events
from app.core.auth import Principal, authorize, scope_query
from app.core.clock import now
from app.core.errors import ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import resources
from app.modules.scheduling import events as ev
from app.modules.scheduling import service
from app.modules.scheduling.models import (
    Booking,
    ReservationType,
    ReservationTypeGrant,
    ResourceHold,
    Session,
    SlotOffer,
    SlotOfferResource,
)

_FIELDS = ("reservation_type_id", "slot_min", "capacity", "title", "public_title", "is_self_bookable",
           "allows_free_booking", "is_active")  # fmt: skip


# --- reservation type grants (SCH-05) ----------------------------------------------------------------------


def get_grants(session: Db, principal: Principal, type_id: UUID) -> dict:
    rtype = service.get_type(session, principal, type_id)
    authorize(principal, service.GRANTS)
    return _grants_view(session, rtype.id)


def _grants_view(session: Db, type_id: UUID) -> dict:
    ids = session.scalars(
        select(ReservationTypeGrant.staff_user_id)
        .where(ReservationTypeGrant.reservation_type_id == type_id)
        .order_by(ReservationTypeGrant.staff_user_id)
    ).all()
    return {"reservation_type_id": type_id, "is_restricted": bool(ids), "staff_user_ids": list(ids)}


def replace_grants(session: Db, principal: Principal, type_id: UUID, staff_user_ids: list[UUID]) -> dict:
    """Restrict who may book a type to these staff users; an empty list opens it to everyone again."""
    rtype = service.get_type(session, principal, type_id)
    authorize(principal, service.GRANTS)
    before = len(_grants_view(session, rtype.id)["staff_user_ids"])
    wanted = sorted(set(staff_user_ids))
    session.execute(delete(ReservationTypeGrant).where(ReservationTypeGrant.reservation_type_id == rtype.id))
    session.add_all(ReservationTypeGrant(reservation_type_id=rtype.id, staff_user_id=u) for u in wanted)
    session.flush()  # fk_reservation_type_grant_staff_user_id_staff_user: an unknown user is 422
    session.info.pop("denied_types", None)
    audit.record(
        session, service.GRANTS, rtype, location_id=rtype.location_id,
        changes={"granted_staff_count": [before, len(wanted)]},
    )  # fmt: skip
    events.publish(
        session, ev.ReservationTypeGrantsReplaced(reservation_type_id=rtype.id, staff_user_count=len(wanted)), rtype.id
    )
    return _grants_view(session, rtype.id)


# --- slot offers -------------------------------------------------------------------------------------------


def _extras(session: Db, offer_ids) -> dict[UUID, list[UUID]]:
    found: dict[UUID, list[UUID]] = {offer_id: [] for offer_id in offer_ids}
    rows = session.execute(
        select(SlotOfferResource.slot_offer_id, SlotOfferResource.resource_id)
        .where(SlotOfferResource.slot_offer_id.in_(list(found)))
        .order_by(SlotOfferResource.resource_id)
    )
    for offer_id, resource_id in rows:
        found[offer_id].append(resource_id)
    return found


def _views(session: Db, offers: list[SlotOffer]) -> list[dict]:
    extras = _extras(session, [o.id for o in offers])
    windows = {
        o.availability_window_id: resources.service.get_window(session, o.availability_window_id) for o in offers
    }
    return [
        {c: getattr(o, c) for c in ("id", "location_id", "availability_window_id", *_FIELDS)}
        | {"resource_id": windows[o.availability_window_id].resource_id, "additional_resource_ids": extras[o.id]}
        for o in offers
    ]


def _window(session: Db, principal: Principal, window_id: UUID):
    window = resources.service.get_window(session, window_id)
    everywhere = principal.kind == "system" or principal.location_ids is None
    if window is None or not (everywhere or window.location_id in principal.location_ids):
        raise ValidationFailed("Unknown availability window.", pointer="/availability_window_id")
    return window


def _gate(session: Db, principal: Principal, key: str, offer: SlotOffer, window, extra_ids) -> None:
    """`own` reach passes when any listed resource is the caller's, so callers pass resources the offer already
    has (never only what the request adds): a coach cannot claim another trainer's window by listing theirs."""
    service._authorize(
        session, principal, key, offer.location_id, [window.resource_id, *extra_ids], offer.reservation_type_id
    )


def _set_extras(session: Db, offer: SlotOffer, window, extra_ids: list[UUID]) -> None:
    ids = [r for r in dict.fromkeys(extra_ids) if r != window.resource_id]
    rows = service._resolve_resources(session, offer.location_id, [window.resource_id, *ids], False)
    session.execute(delete(SlotOfferResource).where(SlotOfferResource.slot_offer_id == offer.id))
    session.add_all(SlotOfferResource(slot_offer_id=offer.id, resource_id=r) for r, _ in rows[1:])


def list_offers(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, service.READ)
    stmt = scope_query(select(SlotOffer), principal, SlotOffer.location_id)
    query = replace(query, filters=dict(query.filters))
    if (raw := query.filters.pop("resource_id", None)) is not None:
        try:
            resource_id = UUID(raw)
        except ValueError:
            raise ValidationFailed("Invalid value for resource_id", pointer="/resource_id") from None
        windows = resources.service.windows_for(session, [resource_id])
        stmt = stmt.where(SlotOffer.availability_window_id.in_([w.id for w in windows.get(resource_id, [])]))
    page = paginate(
        session, stmt, query, id_column=SlotOffer.id, sort_fields={"title": SlotOffer.title}, default_sort="title",
        filter_fields={
            "location_id": SlotOffer.location_id, "reservation_type_id": SlotOffer.reservation_type_id,
            "availability_window_id": SlotOffer.availability_window_id, "is_active": SlotOffer.is_active,
        },
    )  # fmt: skip
    return page | {"data": _views(session, page["data"])}


def create_offer(session: Db, principal: Principal, data: dict) -> dict:
    window = _window(session, principal, data["availability_window_id"])
    rtype = service._reservation_type(session, window.location_id, "session", data["reservation_type_id"])
    extras = data.get("additional_resource_ids") or []
    offer = SlotOffer(
        location_id=window.location_id, availability_window_id=window.id, reservation_type_id=rtype.id,
        slot_min=data["slot_min"], capacity=data.get("capacity") or 1, title=data.get("title") or rtype.name,
        public_title=data.get("public_title"), is_self_bookable=data.get("is_self_bookable", True),
        allows_free_booking=bool(data.get("allows_free_booking")), direct_link_token=secrets.token_urlsafe(16),
        is_active=data.get("is_active", True),
    )  # fmt: skip
    _gate(session, principal, service.SESSION, offer, window, [])  # a new offer is on the caller's own window
    service._check_free_flag(principal, offer.location_id, offer.allows_free_booking, False)
    session.add(offer)
    session.flush()
    _set_extras(session, offer, window, extras)
    session.flush()
    audit.record(
        session, service.SESSION, offer, location_id=offer.location_id, changes={"slot_min": [None, offer.slot_min]}
    )
    events.publish(
        session, ev.SlotOfferSaved(slot_offer_id=offer.id, location_id=offer.location_id, is_active=offer.is_active),
        offer.id,
    )  # fmt: skip
    return _views(session, [offer])[0]


def update_offer(session: Db, principal: Principal, offer_id: UUID, data: dict) -> dict:
    """Changing an offer changes only slots not yet taken; materialised sessions keep what they copied."""
    offer = service._load(session, principal, SlotOffer, offer_id, lock=True)
    window = resources.service.get_window(session, offer.availability_window_id)
    extras = data.pop("additional_resource_ids", None)
    _gate(session, principal, service.SESSION, offer, window, _extras(session, [offer.id])[offer.id])
    if extras is not None:
        _gate(session, principal, service.SESSION, offer, window, extras)
    if data.get("reservation_type_id"):
        service._reservation_type(session, offer.location_id, "session", data["reservation_type_id"])
        service._check_grant(session, principal, service.SESSION, data["reservation_type_id"])
    service._check_free_flag(principal, offer.location_id, data.get("allows_free_booking"), offer.allows_free_booking)
    for key, value in data.items():
        if value is not None or key == "public_title":
            setattr(offer, key, value)
    changes = audit.diff(offer) | ({"additional_resources": True} if extras is not None else {})
    if extras is not None:
        _set_extras(session, offer, window, extras)
    session.flush()
    audit.record(session, service.SESSION, offer, location_id=offer.location_id, changes=changes)
    events.publish(
        session, ev.SlotOfferSaved(slot_offer_id=offer.id, location_id=offer.location_id, is_active=offer.is_active),
        offer.id,
    )  # fmt: skip
    return _views(session, [offer])[0]


# --- derived slots -----------------------------------------------------------------------------------------


def _candidates(session: Db, offer: SlotOffer, window, start: datetime, end: datetime) -> list[datetime]:
    """Each window occurrence in [start, end) cut into slot_min steps from the window start (data model 4.3)."""
    zone, step = service._zone(session, offer.location_id), timedelta(minutes=offer.slot_min)
    found = []
    for day in service._days(start, end, zone):
        span = service._window_ranges(day, window, zone)
        if span is None:
            continue
        at = span[0]
        while at + step <= span[1]:
            if start <= at < end:
                found.append(at)
            at += step
    return found


def slots(session: Db, principal: Principal, offer_id: UUID, start: datetime | None, end: datetime | None) -> dict:
    """Derived slots of an offer: `free` (bookable now), `booked` (a session exists, seats left), `full`, or
    `unavailable` (a hold or a closure overlaps the slot plus the type's buffers)."""
    offer = service._load(session, principal, SlotOffer, offer_id)
    authorize(principal, service.READ, location_id=offer.location_id)
    start = start or now()
    end = end or start + timedelta(days=7)
    service._window(start, end)
    window = resources.service.get_window(session, offer.availability_window_id)
    rtype = session.get(ReservationType, offer.reservation_type_id)
    before, after = service._buffers(session, offer.location_id, rtype, None, None)
    rows = [(window.resource_id, "primary")] + [(r, "additional") for r in _extras(session, [offer.id])[offer.id]]
    held = [r for r, _, _ in service.hold_plan(session, rows)]
    pad_from, pad_to = start - timedelta(minutes=before), end + timedelta(minutes=after)
    taken = {
        seat.slot_starts_at: seat
        for seat in session.scalars(
            select(Session)
            .join(Booking, Booking.id == Session.booking_id)
            .where(Session.slot_offer_id == offer.id, Booking.status != "cancelled")
            .where(Session.slot_starts_at >= start, Session.slot_starts_at < end)
        )
    }
    busy = [
        (d.lower, d.upper)
        for d in session.scalars(
            select(ResourceHold.during).where(
                ResourceHold.resource_id.in_(held), ResourceHold.during.overlaps(Range(pad_from, pad_to, bounds="[)"))
            )
        )
    ]
    busy += [
        (b.during.lower, b.during.upper)
        for b in service.blackouts_between(session, offer.location_id, pad_from, pad_to)
    ]
    result = []
    for at in _candidates(session, offer, window, start, end):
        until, seat = at + timedelta(minutes=offer.slot_min), taken.get(at)
        lo, hi = at - timedelta(minutes=before), until + timedelta(minutes=after)
        if seat is not None:
            status = "full" if seat.booked_count >= seat.capacity else "booked"
        elif any(s < hi and e > lo for s, e in busy):
            status = "unavailable"
        else:
            status = "free"
        result.append({
            "starts_at": at, "ends_at": until, "status": status, "session_id": seat.id if seat else None,
            "booking_id": seat.booking_id if seat else None, "capacity": seat.capacity if seat else offer.capacity,
            "booked_count": seat.booked_count if seat else 0,
        })  # fmt: skip
    return {"slot_offer_id": offer.id, "slots": result}


def materialise_slot(
    session: Db, offer: SlotOffer, starts_at: datetime, *, created_via: str = "system",
    staff_user_id: UUID | None = None,
) -> Booking:  # fmt: skip
    """Internal (no gate): the session of one slot, created on first use. Two takers racing for the same slot
    queue on the offer row and the loser gets the winner's session. Programs enrols into it with
    `reserve_seat` (portal slot booking is a programs handover)."""
    return _materialise(session, offer, starts_at, created_via=created_via, staff_user_id=staff_user_id)[0]


def _materialise(
    session: Db, offer: SlotOffer, starts_at: datetime, *, created_via: str, staff_user_id: UUID | None
) -> tuple[Booking, bool]:
    """(the slot's booking, whether this call created it)."""
    window = resources.service.get_window(session, offer.availability_window_id)
    if not offer.is_active or starts_at not in _candidates(
        session, offer, window, starts_at, starts_at + timedelta(minutes=1)
    ):
        raise ValidationFailed("That time is not a slot of this offer.", pointer="/starts_at")
    # Takers of one offer queue here; without it the loser meets the hold overlap first (booking-conflict).
    session.execute(select(SlotOffer.id).where(SlotOffer.id == offer.id).with_for_update())
    existing = _slot_booking(session, offer.id, starts_at)
    if existing is not None:
        return existing, False
    try:
        with session.begin_nested():
            booking = service.create_booking(
                session, location_id=offer.location_id, kind="session", starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=offer.slot_min),
                resource_ids=[window.resource_id, *_extras(session, [offer.id])[offer.id]], include_linked=False,
                reservation_type_id=offer.reservation_type_id, title=offer.title, public_title=offer.public_title,
                session_input={"capacity": offer.capacity, "is_self_bookable": offer.is_self_bookable,
                               "allows_free_booking": offer.allows_free_booking},
                created_via=created_via, created_by_staff_user_id=staff_user_id, slot=(offer.id, starts_at),
            )  # fmt: skip
    except IntegrityError as exc:
        found = _slot_booking(session, offer.id, starts_at)
        if "uq_session_slot" not in str(exc.orig) or found is None:
            raise
        return found, False
    return booking, True


def _slot_booking(session: Db, offer_id: UUID, starts_at: datetime) -> Booking | None:
    return session.scalar(
        select(Booking)
        .join(Session, Session.booking_id == Booking.id)
        .where(Session.slot_offer_id == offer_id, Session.slot_starts_at == starts_at, Booking.status != "cancelled")
    )


def book_slot(session: Db, principal: Principal, offer_id: UUID, starts_at: datetime) -> dict:
    """Staff take a slot: its session is created (no seat yet) so clients can be registered into it."""
    offer = service._load(session, principal, SlotOffer, offer_id)
    window = resources.service.get_window(session, offer.availability_window_id)
    _gate(session, principal, service.CREATE, offer, window, _extras(session, [offer.id])[offer.id])
    booking, created = _materialise(
        session, offer, starts_at, created_via="staff", staff_user_id=principal.staff_user_id
    )
    if created:
        audit.record(
            session, service.CREATE, booking, location_id=offer.location_id, changes={"kind": [None, "session"]}
        )
    return service._view(session, booking)
