"""scheduling service: the calendar engine (ADR 0004).

The Postgres exclusion constraint on `resource_hold` is the arbiter of every conflict; the pre-check here only
builds the friendly `conflicts[]`. Staff commands take a principal and authorize it. The functions under
"internal" are what rentals, programs, leagues and staff call: no principal, no permission check.
"""

import secrets
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as Db

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, authorize_tenant_wide, scope_query, system_principal
from app.core.auth.tokens import digest
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.modules import clients, platform, resources
from app.modules.scheduling import events as ev
from app.modules.scheduling.domain import recurrence as rec
from app.modules.scheduling.domain import slots
from app.modules.scheduling.models import (
    Blackout,
    Booking,
    BookingResource,
    BookingSeries,
    BookingSeriesRule,
    BookingSeriesRun,
    ReservationCategory,
    ReservationType,
    ReservationTypeGrant,
    ResourceHold,
    SchedulingSettings,
    Session,
)

READ, CREATE, UPDATE, DELETE = (f"scheduling.booking.{verb}" for verb in ("read", "create", "update", "delete"))
UPDATE_SERIES, DELETE_SERIES = "scheduling.booking.update_series", "scheduling.booking.delete_series"
OVERRIDE, BLOCK = "scheduling.booking.override_policy", "scheduling.block.manage"
SESSION, CAPACITY = "scheduling.session.manage", "scheduling.session.change_capacity"
FREE_BOOK = "scheduling.enrollment.free_book"
TYPES, LOCATION = "scheduling.reservation_type.manage", "platform.location.update"
GRANTS = "scheduling.reservation_type.grant"
OUTSIDE_HOURS = "outside-opening-hours"
SYNC_LIMIT = 50  # occurrences per transaction: stays under Postgres's 64 cached subtransactions (ADR 0004)
MAX_CALENDAR_DAYS = 42
OVERLAP = "ex_resource_hold_overlap"
CONSTRAINT_CODES[OVERLAP] = "booking-conflict"
CONSTRAINT_CODES["ck_session_booked_within_capacity"] = "capacity-full"
CONSTRAINT_CODES["fk_session_slot_offer_id_slot_offer"] = "slot-offer-in-use"  # a window whose offer has taken slots


# --- shared helpers ----------------------------------------------------------------------------------------


def _zone(session: Db, location_id: UUID) -> ZoneInfo:
    cache = session.info.setdefault("zones", {})
    if location_id not in cache:
        cache[location_id] = ZoneInfo(platform.service.location_time_zone(session, location_id))
    return cache[location_id]


def _location(session: Db, principal: Principal, location_id: UUID, pointer: str = "/location_id") -> UUID:
    try:
        return platform.service.get_location(session, principal, location_id).id
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer=pointer) from None


def _load(session: Db, principal: Principal, model, row_id: UUID, *, lock: bool = False):
    """A location-owned row; missing or outside the caller's locations is 404."""
    stmt = select(model).where(model.id == row_id)
    row = session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    everywhere = principal.kind == "system" or principal.location_ids is None
    if row is None or not (everywhere or row.location_id in principal.location_ids):
        raise NotFound()
    return row


def _authorize(
    session: Db, principal: Principal, key: str, location_id: UUID, resource_ids, reservation_type_id=None
) -> None:
    """The service gate plus `own` reach (a coach writes only bookings that include their own resource) plus
    the reservation type's staff grants (SCH-05). Every staff booking write meets here."""
    authorize(principal, key, location_id=location_id)
    if principal.kind == "staff" and principal.permissions.get(key) == "own":
        mine = platform.service.linked_resource_id(session, principal.staff_user_id)
        if mine is None or mine not in set(resource_ids):
            raise PermissionDenied("You can change your own calendar only.", required=key)
    _check_grant(session, principal, key, reservation_type_id)


def _check_grant(session: Db, principal: Principal, key: str, reservation_type_id) -> None:
    if reservation_type_id is not None and reservation_type_id in _denied_types(session, principal):
        raise PermissionDenied("You are not allowed to book this reservation type.", required=key)


def _denied_types(session: Db, principal: Principal) -> set[UUID]:
    """Restricted reservation types (they have grant rows) that the caller is not granted. Owners, system jobs
    and API keys are never restricted: grants are per staff user."""
    if principal.kind != "staff" or principal.is_owner:
        return set()
    cache = session.info.setdefault("denied_types", {})
    if principal.staff_user_id not in cache:
        rows = session.execute(select(ReservationTypeGrant.reservation_type_id, ReservationTypeGrant.staff_user_id))
        restricted, granted = set(), set()
        for type_id, user_id in rows:
            restricted.add(type_id)
            if user_id == principal.staff_user_id:
                granted.add(type_id)
        cache[principal.staff_user_id] = restricted - granted
    return cache[principal.staff_user_id]


def _apply(row, data: dict) -> None:
    for key, value in data.items():
        setattr(row, key, value)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _check_span(starts_at: datetime, ends_at: datetime) -> None:
    for name, value in (("starts_at", starts_at), ("ends_at", ends_at)):
        if value.tzinfo is None or value.second or value.microsecond:
            raise ValidationFailed("Times are whole minutes with a UTC offset.", pointer=f"/{name}")
    if ends_at <= starts_at:
        raise ValidationFailed("ends_at must be after starts_at.", pointer="/ends_at")


# --- settings ----------------------------------------------------------------------------------------------


def settings_for(session: Db, location_id: UUID | None) -> SchedulingSettings:
    """Internal. The location's row, else the tenant default, which is created on first use."""
    rows = {
        row.location_id: row
        for row in session.scalars(
            select(SchedulingSettings).where(
                SchedulingSettings.location_id.is_(None) | (SchedulingSettings.location_id == location_id)
            )
        )
    }
    if location_id in rows:
        return rows[location_id]
    if None not in rows:
        session.execute(
            pg_insert(SchedulingSettings)
            .values(id=new_id(), tenant_id=session.info["tenant_id"])
            .on_conflict_do_nothing()
        )
        rows[None] = session.execute(
            select(SchedulingSettings).where(SchedulingSettings.location_id.is_(None))
        ).scalar_one()
    return rows[None]


def get_settings(session: Db, principal: Principal, location_id: UUID | None) -> SchedulingSettings:
    if location_id:
        _location(session, principal, location_id)
    return settings_for(session, location_id)


def update_settings(session: Db, principal: Principal, location_id: UUID | None, data: dict) -> SchedulingSettings:
    if location_id:
        _location(session, principal, location_id)
        authorize(principal, LOCATION, location_id=location_id)
    else:
        authorize_tenant_wide(principal, LOCATION)  # the tenant default governs every location (S-04)
    row = settings_for(session, location_id)
    if row.location_id != location_id:  # first override for this location: start from the tenant default
        inherited = {
            c.key: getattr(row, c.key)
            for c in SchedulingSettings.__table__.columns
            if c.key.endswith("_min") or c.key in ("drag_drop_default", "max_series_occurrences")
        }
        row = SchedulingSettings(**inherited, location_id=location_id)
        session.add(row)
    _apply(row, data)
    session.flush()
    audit.record(session, LOCATION, row, location_id=location_id, changes={key: True for key in data})
    return row


# --- reservation categories and types ----------------------------------------------------------------------


def list_categories(session: Db, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, scope_query(select(ReservationCategory), principal, ReservationCategory.location_id), query,
        id_column=ReservationCategory.id,
        sort_fields={"sort_order": ReservationCategory.sort_order, "name": ReservationCategory.name},
        default_sort="sort_order,name",
        filter_fields={"location_id": ReservationCategory.location_id, "is_active": ReservationCategory.is_active},
    )  # fmt: skip


def _check_category(session: Db, location_id: UUID, category_id: UUID | None, pointer: str, *, top_only: bool) -> None:
    if category_id is None:
        return
    parent = session.get(ReservationCategory, category_id)
    if parent is None or parent.location_id != location_id or (top_only and parent.parent_id is not None):
        raise ValidationFailed("Unknown category at this location.", pointer=pointer)


def create_category(session: Db, principal: Principal, data: dict) -> ReservationCategory:
    _location(session, principal, data["location_id"])
    authorize(principal, TYPES)
    _check_category(session, data["location_id"], data.get("parent_id"), "/parent_id", top_only=True)
    row = ReservationCategory(**data)
    session.add(row)
    session.flush()
    audit.record(session, TYPES, row, location_id=row.location_id, changes={"name": True})
    return row


def update_category(session: Db, principal: Principal, category_id: UUID, data: dict) -> ReservationCategory:
    row = _load(session, principal, ReservationCategory, category_id)
    authorize(principal, TYPES)
    _apply(row, data)
    audit.record(session, TYPES, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def list_types(session: Db, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, scope_query(select(ReservationType), principal, ReservationType.location_id), query,
        id_column=ReservationType.id,
        sort_fields={"sort_order": ReservationType.sort_order, "name": ReservationType.name},
        default_sort="sort_order,name",
        filter_fields={
            "location_id": ReservationType.location_id, "is_active": ReservationType.is_active,
            "is_schedulable": ReservationType.is_schedulable,
            "reservation_category_id": ReservationType.reservation_category_id,
        },
        search=(ReservationType.name,),
    )  # fmt: skip


def get_type(session: Db, principal: Principal, type_id: UUID) -> ReservationType:
    return _load(session, principal, ReservationType, type_id)


def create_type(session: Db, principal: Principal, data: dict) -> ReservationType:
    _location(session, principal, data["location_id"])
    authorize(principal, TYPES)
    # a seat inherits this default, so setting it is the free_book decision itself (backlog 28)
    _check_free_flag(principal, data["location_id"], data.get("default_allows_free_booking"), False)
    _check_category(
        session, data["location_id"], data.get("reservation_category_id"), "/reservation_category_id", top_only=False
    )
    row = ReservationType(**data)
    session.add(row)
    session.flush()
    audit.record(session, TYPES, row, location_id=row.location_id, changes={"name": [None, row.name]})
    return row


def update_type(session: Db, principal: Principal, type_id: UUID, data: dict) -> ReservationType:
    """Edits change only what is created afterwards: existing bookings and sessions keep their copies."""
    row = _load(session, principal, ReservationType, type_id)
    authorize(principal, TYPES)
    _check_free_flag(
        principal, row.location_id, data.get("default_allows_free_booking"), row.default_allows_free_booking
    )
    if "reservation_category_id" in data:
        _check_category(
            session, row.location_id, data["reservation_category_id"], "/reservation_category_id", top_only=False
        )
    _apply(row, data)
    audit.record(session, TYPES, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


# --- blackouts ---------------------------------------------------------------------------------------------


def _blackout_view(row: Blackout, overlapping: list | None = None) -> dict:
    view = {
        "id": row.id, "location_id": row.location_id, "name": row.name, "starts_at": row.during.lower,
        "ends_at": row.during.upper, "scope": row.scope, "note": row.note,
    }  # fmt: skip
    return view if overlapping is None else view | {"overlapping_bookings": overlapping}


def _overlapping_bookings(session: Db, row: Blackout) -> list[dict]:
    """Bookings a closure covers: listed so staff cancel them deliberately; nothing is cancelled here."""
    found = session.execute(
        select(Booking.id, Booking.booking_number, Booking.title, Booking.starts_at, Booking.ends_at)
        .where(
            Booking.location_id == row.location_id, Booking.status != "cancelled", Booking.kind != "block",
            Booking.starts_at < row.during.upper, Booking.ends_at > row.during.lower,
        )
        .order_by(Booking.starts_at, Booking.id)
        .limit(500)
    )  # fmt: skip
    return [dict(r._mapping) for r in found]


def list_blackouts(
    session: Db, principal: Principal, location_id: UUID, start: datetime | None, end: datetime | None
) -> list[dict]:
    _location(session, principal, location_id)
    return [_blackout_view(row) for row in blackouts_between(session, location_id, start, end)]


def blackouts_between(
    session: Db, location_id: UUID, start: datetime | None, end: datetime | None, scope: str | None = None
) -> list[Blackout]:
    """Internal. Closures overlapping [start, end); either bound may be open."""
    stmt = select(Blackout).where(Blackout.location_id == location_id)
    if start or end:
        stmt = stmt.where(Blackout.during.overlaps(Range(start, end, bounds="[)")))
    if scope:
        stmt = stmt.where(Blackout.scope == scope)
    return list(session.scalars(stmt.order_by(func.lower(Blackout.during), Blackout.id)))


def create_blackout(session: Db, principal: Principal, data: dict) -> dict:
    _location(session, principal, data["location_id"])
    authorize(principal, LOCATION, location_id=data["location_id"])
    _check_span(data["starts_at"], data["ends_at"])
    row = Blackout(
        location_id=data["location_id"], name=data["name"], scope=data["scope"], note=data.get("note"),
        during=Range(data["starts_at"], data["ends_at"], bounds="[)"),
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(session, LOCATION, row, location_id=row.location_id, changes={"scope": [None, row.scope]})
    return _blackout_view(row, _overlapping_bookings(session, row))


def update_blackout(session: Db, principal: Principal, blackout_id: UUID, data: dict) -> dict:
    row = _load(session, principal, Blackout, blackout_id)
    authorize(principal, LOCATION, location_id=row.location_id)
    starts_at, ends_at = data.pop("starts_at", None) or row.during.lower, data.pop("ends_at", None) or row.during.upper
    _check_span(starts_at, ends_at)
    _apply(row, data | {"during": Range(starts_at, ends_at, bounds="[)")})
    audit.record(
        session, LOCATION, row, location_id=row.location_id, changes={key: True for key in data} | {"during": True}
    )
    session.flush()
    return _blackout_view(row, _overlapping_bookings(session, row))


def delete_blackout(session: Db, principal: Principal, blackout_id: UUID) -> None:
    row = _load(session, principal, Blackout, blackout_id)
    authorize(principal, LOCATION, location_id=row.location_id)
    audit.record(session, LOCATION, row, location_id=row.location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()


def _check_blackout(session: Db, location_id: UUID, starts_at: datetime, ends_at: datetime) -> None:
    closed = blackouts_between(session, location_id, starts_at, ends_at, scope="all")
    if closed:
        raise Conflict(
            f"The location is closed then: {closed[0].name}.", code="resource-blacked-out",
            blackout={"id": str(closed[0].id), "name": closed[0].name},
        )  # fmt: skip


# --- holds: the only code that writes resource_hold --------------------------------------------------------


def _padded(booking: Booking) -> Range:
    return Range(
        booking.starts_at - timedelta(minutes=booking.buffer_before_min),
        booking.ends_at + timedelta(minutes=booking.buffer_after_min),
        bounds="[)",
    )


def _booked(session: Db, booking_ids) -> dict[UUID, list[BookingResource]]:
    grouped: dict[UUID, list[BookingResource]] = {booking_id: [] for booking_id in booking_ids}
    rows = session.scalars(
        select(BookingResource)
        .where(BookingResource.booking_id.in_(list(grouped)))
        .order_by(BookingResource.sort_order, BookingResource.id)
    )
    for row in rows:
        grouped[row.booking_id].append(row)
    return grouped


def hold_plan(session: Db, rows: list[tuple[UUID, str]]) -> list[tuple[UUID, str, UUID]]:
    """(resource_id, origin, source_resource_id) for a booking's resources: self plus every descendant of the
    primary (`booked`) and of each additional resource (`linked`), de-duplicated with precedence booked,
    linked, descendant. No ancestor rows: siblings must stay bookable side by side (ADR 0004 section 3)."""
    tree = resources.service.descendants(session, [resource_id for resource_id, _ in rows])
    plan: dict[UUID, tuple[str, UUID]] = {}
    for role in ("primary", "additional"):
        for resource_id, row_role in rows:
            if row_role == role:
                plan.setdefault(resource_id, ("booked" if role == "primary" else "linked", resource_id))
    for resource_id, _ in rows:
        for child in tree[resource_id]:
            plan.setdefault(child, ("descendant", resource_id))
    # Ordered by resource so two multi-resource bookings take their index locks in the same order.
    return sorted((resource_id, origin, source) for resource_id, (origin, source) in plan.items())


def find_conflicts(session: Db, resource_ids, during: Range, exclude=()) -> list[dict]:
    """Internal. Holds overlapping a padded range on any of the resources, each naming its booking."""
    rows = session.execute(
        select(
            ResourceHold.resource_id, ResourceHold.during, Booking.id, Booking.booking_number, Booking.title,
            Booking.kind, Booking.starts_at, Booking.ends_at, Booking.status, Booking.expires_at,
        )
        .join(Booking, Booking.id == ResourceHold.booking_id)
        .where(
            ResourceHold.resource_id.in_(list(resource_ids)), ResourceHold.during.overlaps(during),
            ResourceHold.booking_id.not_in(list(exclude) or [new_id()]),
        )
        .order_by(func.lower(ResourceHold.during), ResourceHold.resource_id)
    ).all()  # fmt: skip
    names = {r.id: r.name for r in resources.service.get_many(session, {row.resource_id for row in rows})}
    return [
        {
            "resource_id": str(row.resource_id), "resource_name": names.get(row.resource_id),
            "booking_id": str(row.id), "booking_number": row.booking_number, "title": row.title, "kind": row.kind,
            "starts_at": _iso(row.starts_at), "ends_at": _iso(row.ends_at),
            "held_from": _iso(row.during.lower), "held_until": _iso(row.during.upper),
            "is_expired_hold": row.status == "tentative" and row.expires_at <= clock.now(),
        }
        for row in rows
    ]  # fmt: skip


def _conflict(found: list[dict]) -> Conflict:
    if not found:  # the rival transaction is gone again; the caller may simply retry
        return Conflict("That time was taken a moment ago. Try again.", code="booking-conflict", conflicts=[])
    first = found[0]
    label = f"booking #{first['booking_number']}" + (f" ({first['title']})" if first["title"] else "")
    return Conflict(
        f"{first['resource_name']} is already held by {label} from {first['starts_at']} to {first['ends_at']}.",
        code="booking-conflict", conflicts=found,
    )  # fmt: skip


def _blocking(session: Db, resource_ids, during: Range, booking_id: UUID) -> list[dict]:
    """Conflicts, after reaping checkout holds that have already expired (ADR 0004 section 9 item 4)."""
    found = find_conflicts(session, resource_ids, during, exclude=[booking_id])
    expired = {UUID(c["booking_id"]) for c in found if c["is_expired_hold"]}
    if expired:
        for rival in session.scalars(select(Booking).where(Booking.id.in_(expired)).with_for_update(skip_locked=True)):
            _expire(session, rival)
        found = find_conflicts(session, resource_ids, during, exclude=[booking_id])
    return found


def _write_holds(session: Db, booking: Booking) -> None:
    rows = [(row.resource_id, row.role) for row in _booked(session, [booking.id])[booking.id]]
    plan, during = hold_plan(session, rows), _padded(booking)
    resource_ids = [resource_id for resource_id, _, _ in plan]
    found = _blocking(session, resource_ids, during, booking.id)
    if found:
        raise _conflict(found)
    try:
        with session.begin_nested():
            session.execute(
                insert(ResourceHold),
                [
                    {
                        "id": new_id(), "tenant_id": session.info["tenant_id"], "resource_id": resource_id,
                        "booking_id": booking.id, "during": during, "origin": origin,
                        "source_resource_id": source, "expires_at": booking.expires_at,
                    }
                    for resource_id, origin, source in plan
                ],
            )  # fmt: skip
    except IntegrityError as exc:  # lost a race: the constraint, not the pre-check, is the arbiter
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != OVERLAP:
            raise
        raise _conflict(find_conflicts(session, resource_ids, during, exclude=[booking.id])) from None


def _release_holds(session: Db, booking_ids) -> None:
    session.execute(delete(ResourceHold).where(ResourceHold.booking_id.in_(list(booking_ids))))


def _resolve_resources(
    session: Db, location_id: UUID, resource_ids: list[UUID], include_linked: bool
) -> list[tuple[UUID, str]]:
    """Validated (resource_id, role) rows, primary first; standing links are appended as additional."""
    ordered = list(dict.fromkeys(resource_ids))
    if include_linked:
        ordered += [r for r in resources.service.linked_ids(session, ordered) if r not in ordered]
    found = {r.id: r for r in resources.service.get_many(session, ordered)}
    for index, resource_id in enumerate(ordered):
        row = found.get(resource_id)
        if row is None or row.location_id != location_id or row.status != "active":
            if resource_id in resource_ids:
                raise ValidationFailed("Unknown resource at this location.", pointer=f"/resources/{index}/resource_id")
            ordered = [r for r in ordered if r != resource_id]  # a stale standing link is dropped silently
    return [(resource_id, "primary" if index == 0 else "additional") for index, resource_id in enumerate(ordered)]


def _set_resources(session: Db, booking: Booking, rows: list[tuple[UUID, str]]) -> None:
    session.execute(delete(BookingResource).where(BookingResource.booking_id == booking.id))
    session.add_all(
        BookingResource(booking_id=booking.id, resource_id=resource_id, role=role, sort_order=index)
        for index, (resource_id, role) in enumerate(rows)
    )
    session.flush()


def _on_tree_changed(session: Db, resource) -> None:
    """A node gained or changed its parent: drop what it inherited from old ancestors and back-fill the holds
    of every future booking on its new ancestors, or fail as a whole (ADR 0004 section 3)."""
    now = clock.now()
    subtree = [resource.id, *resources.service.descendants(session, [resource.id])[resource.id]]
    session.execute(
        delete(ResourceHold).where(
            ResourceHold.resource_id.in_(subtree), ResourceHold.origin == "descendant",
            ResourceHold.source_resource_id.not_in(subtree), func.upper(ResourceHold.during) > now,
        )
    )  # fmt: skip
    if resource.parent_id is None:
        return
    inherited = session.scalars(
        select(ResourceHold).where(
            ResourceHold.resource_id == resource.parent_id, func.upper(ResourceHold.during) > now
        )
    ).all()
    rows = [
        {
            "id": new_id(), "tenant_id": session.info["tenant_id"], "resource_id": node, "booking_id": hold.booking_id,
            "during": hold.during, "origin": "descendant", "source_resource_id": hold.source_resource_id,
            "expires_at": hold.expires_at,
        }
        for hold in inherited
        for node in sorted(subtree)
    ]  # fmt: skip
    if not rows:
        return
    try:
        with session.begin_nested():
            session.execute(
                pg_insert(ResourceHold).on_conflict_do_nothing(constraint="uq_resource_hold_booking_resource"), rows
            )
    except IntegrityError as exc:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != OVERLAP:
            raise
        found = [
            c for hold in inherited for c in find_conflicts(session, subtree, hold.during, exclude=[hold.booking_id])
        ]
        raise _conflict(found) from None


def _on_archiving(session: Db, resource) -> None:
    booked = session.scalar(
        select(func.count()).where(
            ResourceHold.resource_id == resource.id, ResourceHold.origin != "descendant",
            func.upper(ResourceHold.during) > clock.now(),
        )
    )  # fmt: skip
    if booked:
        raise Conflict(f"{resource.name} still has {booked} future bookings.", code="resource-has-future-bookings")


resources.service.HOOKS["tree_changed"].append(_on_tree_changed)
resources.service.HOOKS["archiving"].append(_on_archiving)


# --- internal: bookings (the cross-context interface, ADR 0009 section 9) ----------------------------------


def _reservation_type(session: Db, location_id: UUID, kind: str, type_id: UUID | None) -> ReservationType | None:
    if type_id is None:
        return None
    row = session.get(ReservationType, type_id)
    if kind != "session" or row is None or row.location_id != location_id or not (row.is_active and row.is_schedulable):
        raise ValidationFailed("Unknown or unschedulable reservation type.", pointer="/reservation_type_id")
    return row


def _buffers(session: Db, location_id: UUID, rtype: ReservationType | None, before: int | None, after: int | None):
    """Copied onto the booking at creation and never re-read (SCH-14): explicit, else the type, else settings."""
    if rtype is not None and not rtype.uses_default_buffer:
        defaults = (rtype.buffer_before_min, rtype.buffer_after_min)
    elif before is None or after is None:
        row = settings_for(session, location_id)
        defaults = (row.default_buffer_before_min, row.default_buffer_after_min)
    else:
        defaults = (0, 0)
    return (defaults[0] if before is None else before), (defaults[1] if after is None else after)


def _event_fields(booking: Booking) -> dict:
    return {
        "booking_id": booking.id, "location_id": booking.location_id, "kind": booking.kind,
        "block_kind": booking.block_kind, "source_context": booking.source_context,
        "source_type": booking.source_type, "source_id": booking.source_id,
    }  # fmt: skip


def create_booking(
    session: Db, *, location_id: UUID, kind: str, starts_at: datetime, ends_at: datetime, resource_ids: list[UUID],
    include_linked: bool = True, reservation_type_id: UUID | None = None, client_id: UUID | None = None,
    title: str = "", public_title: str | None = None, notes: str | None = None,
    buffer_before_min: int | None = None, buffer_after_min: int | None = None, block_kind: str | None = None,
    session_input: dict | None = None, source: tuple[str, str, UUID] | None = None, created_via: str = "system",
    created_by_staff_user_id: UUID | None = None, hold_minutes: int | None = None, override_policy: bool = False,
    series: tuple[UUID, UUID, int] | None = None, local: tuple[date, str, int] | None = None,
    slot: tuple[UUID, datetime] | None = None,
) -> Booking:  # fmt: skip
    """Write one occurrence with its holds, atomically across its resources. Raises Conflict
    `booking-conflict` (naming the conflicting bookings) or `resource-blacked-out`. `hold_minutes` makes it a
    tentative checkout hold. `local` is (date, wall time, nominal minutes) when a series supplies them."""
    _check_span(starts_at, ends_at)
    rows = _resolve_resources(session, location_id, resource_ids, include_linked)
    rtype = _reservation_type(session, location_id, kind, reservation_type_id)
    before, after = _buffers(session, location_id, rtype, buffer_before_min, buffer_after_min)
    if kind != "block" and not override_policy:
        _check_blackout(session, location_id, starts_at, ends_at)
    if client_id is not None:
        clients.service.require_active(session, client_id)
    if local is None:
        day, wall = rec.local_parts(starts_at, _zone(session, location_id))
        local = (day, wall.strftime("%H:%M"), int((ends_at - starts_at).total_seconds() // 60))
    series_id, rule_id, index = series or (None, None, None)
    context, source_type, source_id = source or (None, None, None)
    booking = Booking(
        location_id=location_id, booking_number=platform.service.next_number(session, "booking_number"),
        booking_series_id=series_id, booking_series_rule_id=rule_id, occurrence_index=index,
        occurrence_on=local[0], local_start_time=local[1], duration_min=local[2], kind=kind, block_kind=block_kind,
        reservation_type_id=reservation_type_id, client_id=client_id, title=title or "", public_title=public_title,
        notes=notes, starts_at=starts_at, ends_at=ends_at, buffer_before_min=before, buffer_after_min=after,
        status="tentative" if hold_minutes else "confirmed",
        expires_at=clock.now() + timedelta(minutes=hold_minutes) if hold_minutes else None,
        created_via=created_via, created_by_staff_user_id=created_by_staff_user_id, source_context=context,
        source_type=source_type, source_id=source_id, version=1,
    )  # fmt: skip
    session.add(booking)
    session.flush()
    _set_resources(session, booking, rows)
    _write_holds(session, booking)
    events.publish(session, ev.BookingCreated(**_event_fields(booking)), booking.id)
    if kind == "session":
        given = session_input or {}
        seat = Session(
            location_id=location_id, booking_id=booking.id,
            capacity=_default(given.get("capacity"), rtype.default_capacity if rtype else 0),
            is_self_bookable=_default(given.get("is_self_bookable"), rtype.is_self_bookable_default if rtype else False),
            allows_free_booking=_default(given.get("allows_free_booking"), rtype.default_allows_free_booking if rtype else False),
            direct_link_token=secrets.token_urlsafe(16), slot_offer_id=slot[0] if slot else None,
            slot_starts_at=slot[1] if slot else None,
        )  # fmt: skip
        session.add(seat)
        session.flush()
        events.publish(
            session, ev.SessionCreated(session_id=seat.id, booking_id=booking.id, location_id=location_id), seat.id
        )
    return booking


def _default(value, fallback):
    return fallback if value is None else value


def get_booking(session: Db, booking_id: UUID) -> Booking:
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise NotFound()
    return booking


def reschedule_booking(
    session: Db, booking: Booking, *, starts_at: datetime, ends_at: datetime, resource_ids: list[UUID] | None = None,
    override_policy: bool = False, local: tuple[date, str, int] | None = None,
) -> Booking:  # fmt: skip
    """Move, resize or re-resource one occurrence: its holds are deleted and re-derived in this transaction,
    so the booking never collides with its own old range and a clash names the rival."""
    if booking.status == "cancelled":
        raise Conflict("A cancelled booking cannot be moved.")
    _check_span(starts_at, ends_at)
    if booking.kind != "block" and not override_policy:
        _check_blackout(session, booking.location_id, starts_at, ends_at)
    if local is None:
        day, wall = rec.local_parts(starts_at, _zone(session, booking.location_id))
        local = (day, wall.strftime("%H:%M"), int((ends_at - starts_at).total_seconds() // 60))
    _release_holds(session, [booking.id])
    if resource_ids is not None:
        _set_resources(session, booking, _resolve_resources(session, booking.location_id, resource_ids, False))
    booking.starts_at, booking.ends_at = starts_at, ends_at
    booking.occurrence_on, booking.local_start_time, booking.duration_min = local
    booking.version += 1
    session.flush()
    _write_holds(session, booking)
    events.publish(session, ev.BookingRescheduled(**_event_fields(booking)), booking.id)
    return booking


def cancel_booking(session: Db, booking: Booking, *, reason: str = "staff") -> Booking:
    """Soft cancel: the status changes, the holds are deleted, the row and its resources stay. Idempotent."""
    if booking.status == "cancelled":
        return booking
    booking.status, booking.cancelled_at, booking.cancel_reason, booking.expires_at = (
        "cancelled",
        clock.now(),
        reason,
        None,
    )
    booking.version += 1
    _release_holds(session, [booking.id])
    if booking.booking_series_id:
        _count(session, booking.booking_series_id, -1)
    events.publish(session, ev.BookingCancelled(**_event_fields(booking), cancel_reason=reason), booking.id)
    seat = session.scalar(select(Session).where(Session.booking_id == booking.id))
    if seat is not None:
        seat.slot_offer_id = seat.slot_starts_at = None  # uq_session_slot: a cancelled slot can be taken again
        events.publish(
            session,
            ev.SessionCancelled(session_id=seat.id, booking_id=booking.id, location_id=booking.location_id),
            seat.id,
        )
    session.flush()
    return booking


def _count(session: Db, series_id: UUID, delta: int) -> None:
    """Move a series' live-occurrence counter in SQL: two passes of one series may run at the same time."""
    session.execute(
        BookingSeries.__table__.update()
        .where(BookingSeries.id == series_id)
        .values(occurrence_count=func.greatest(BookingSeries.occurrence_count + delta, 0))
    )


def confirm_booking(session: Db, booking_id: UUID) -> Booking:
    """Turn a checkout hold into a confirmed booking. The row lock keeps the reaper away while a payment is
    in flight (it reads with SKIP LOCKED). Raises Conflict `hold-expired` when the clock ran out."""
    booking = session.execute(select(Booking).where(Booking.id == booking_id).with_for_update()).scalar_one_or_none()
    if booking is None:
        raise NotFound()
    if booking.status == "confirmed":
        return booking
    if booking.status != "tentative" or booking.expires_at <= clock.now():
        raise Conflict("The hold on this time has expired.", code="hold-expired")
    booking.status, booking.expires_at = "confirmed", None
    session.execute(
        ResourceHold.__table__.update().where(ResourceHold.booking_id == booking.id).values(expires_at=None)
    )
    session.flush()
    return booking


def _expire(session: Db, booking: Booking) -> None:
    if booking.status == "tentative" and booking.expires_at <= clock.now():
        cancel_booking(session, booking, reason="hold_expired")
        events.publish(session, ev.HoldExpired(**_event_fields(booking)), booking.id)


def expire_holds(session: Db) -> int:
    """Release every checkout hold whose clock ran out. Called by the reaper job; inserts also reap inline."""
    due = session.scalars(
        select(Booking)
        .where(Booking.status == "tentative", Booking.expires_at <= clock.now())
        .with_for_update(skip_locked=True)
    ).all()
    for booking in due:
        _expire(session, booking)
    return len(due)


# --- internal: seats (the session side of CLS; programs owns enrolments) -----------------------------------


def _seat(session: Db, session_id: UUID) -> Session:
    seat = session.execute(
        select(Session).where(Session.id == session_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if seat is None:
        raise NotFound()
    return seat


def reserve_seat(session: Db, session_id: UUID, n: int = 1) -> Session:
    """Take n seats under the session row lock. Raises Conflict `capacity-full` or `session-not-bookable`."""
    seat = _seat(session, session_id)
    if session.get(Booking, seat.booking_id).status != "confirmed":
        raise Conflict("This session is not open for booking.", code="session-not-bookable")
    if seat.booked_count + n > seat.capacity:
        raise Conflict("The session is full.", code="capacity-full", capacity=seat.capacity)
    seat.booked_count += n
    session.flush()
    return seat


def release_seat(session: Db, session_id: UUID, n: int = 1) -> Session:
    """Give seats back. When the last seat of a slot-offer session goes, the session is cancelled so the time
    returns to the window (data model 4.3, step 4)."""
    seat = _seat(session, session_id)
    seat.booked_count = max(seat.booked_count - n, 0)
    session.flush()
    if seat.slot_offer_id is not None and seat.booked_count == 0:
        cancel_booking(session, session.get(Booking, seat.booking_id), reason="other")
    return seat


def set_capacity(session: Db, session_ids: list[UUID], capacity: int) -> list[dict]:
    """Per-session result: `ok`, or `capacity-below-booked` when seats already taken exceed the new size."""
    results = []
    for session_id in sorted(set(session_ids)):  # one lock order for concurrent bulk changes
        seat = _seat(session, session_id)
        if capacity < seat.booked_count:
            results.append(
                {
                    "session_id": seat.id,
                    "status": "capacity-below-booked",
                    "capacity": seat.capacity,
                    "booked_count": seat.booked_count,
                }
            )
            continue
        old, seat.capacity = seat.capacity, capacity
        if old != capacity:
            events.publish(
                session,
                ev.SessionCapacityChanged(
                    session_id=seat.id, booking_id=seat.booking_id, location_id=seat.location_id,
                    old_capacity=old, new_capacity=capacity,
                ),
                seat.id,
            )  # fmt: skip
        results.append({"session_id": seat.id, "status": "ok", "capacity": capacity, "booked_count": seat.booked_count})
    session.flush()
    return results


def has_live_link(session: Db, session_id: UUID, token: str | None) -> bool:
    """Internal (programs' portal enrolment): whether the token is this session's active direct link (SCH-16).
    Only the token's digest is stored."""
    if not token:
        return False
    s = Session
    stmt = select(s.id).where(s.id == session_id, s.direct_link_token == digest(token), s.is_direct_link_active)
    return session.scalar(stmt) is not None


def get_session(session: Db, session_id: UUID) -> dict:
    """Internal read for programs: the seat row with its booking's times and status."""
    seat = session.get(Session, session_id)
    if seat is None:
        raise NotFound()
    return _session_views(session, [seat])[0]


def get_sessions(session: Db, session_ids) -> dict[UUID, dict]:
    """Internal (integrations' member feed): get_session for many ids in one read; unknown ids are left out."""
    seats = session.scalars(select(Session).where(Session.id.in_(list(session_ids)))).all() if session_ids else []
    return {view["id"]: view for view in _session_views(session, list(seats))}


# --- views -------------------------------------------------------------------------------------------------


def _fill(capacity: int, booked: int) -> str:
    return "empty" if booked == 0 else "full" if booked >= capacity else "partial"


def _session_view(seat: Session) -> dict:
    return {
        "id": seat.id, "location_id": seat.location_id, "booking_id": seat.booking_id, "capacity": seat.capacity,
        "booked_count": seat.booked_count, "fill": _fill(seat.capacity, seat.booked_count),
        "is_self_bookable": seat.is_self_bookable, "allows_free_booking": seat.allows_free_booking,
        "is_direct_link_active": seat.is_direct_link_active,
    }  # fmt: skip


def _session_views(session: Db, seats: list[Session]) -> list[dict]:
    bookings = {b.id: b for b in session.scalars(select(Booking).where(Booking.id.in_([s.booking_id for s in seats])))}
    return [
        _session_view(seat)
        | {
            key: getattr(bookings[seat.booking_id], key)
            for key in (
                "starts_at",
                "ends_at",
                "title",
                "public_title",
                "reservation_type_id",
                "status",
                "booking_series_id",
            )
        }
        for seat in seats
    ]


def _views(session: Db, bookings: list[Booking]) -> list[dict]:
    ids = [booking.id for booking in bookings]
    booked = _booked(session, ids)
    seats = {s.booking_id: s for s in session.scalars(select(Session).where(Session.booking_id.in_(ids)))}
    return [
        {c.key: getattr(booking, c.key) for c in Booking.__table__.columns}
        | {
            "resources": [{"resource_id": r.resource_id, "role": r.role} for r in booked[booking.id]],
            "session": _session_view(seats[booking.id]) if booking.id in seats else None,
        }
        for booking in bookings
    ]


def _view(session: Db, booking: Booking) -> dict:
    return _views(session, [booking])[0]


# --- staff commands: single bookings -----------------------------------------------------------------------


def booking_views(session: Db, booking_ids) -> dict[UUID, dict]:
    """Internal: booking views (with resources) by id, for an owning context's read model (rentals)."""
    ids = list(booking_ids)
    bookings = session.scalars(select(Booking).where(Booking.id.in_(ids))).all() if ids else []
    return {view["id"]: view for view in _views(session, bookings)}


def booking_ids(
    *,
    client_id=None,
    client_ids=None,
    status=None,
    series_id=None,
    resource_id=None,
    starts_from=None,
    starts_to=None,
    location_id=None,
):
    """Internal: a SELECT of booking ids matching booking-side filters, for an owner's list query."""
    stmt = select(Booking.id)
    if location_id is not None:
        stmt = stmt.where(Booking.location_id == location_id)
    if starts_from is not None:
        stmt = stmt.where(Booking.starts_at >= starts_from)
    if starts_to is not None:
        stmt = stmt.where(Booking.starts_at < starts_to)
    if client_id is not None:
        stmt = stmt.where(Booking.client_id == client_id)
    if client_ids is not None:
        stmt = stmt.where(Booking.client_id.in_(list(client_ids)))
    if status is not None:
        stmt = stmt.where(Booking.status == status)
    if series_id is not None:
        stmt = stmt.where(Booking.booking_series_id == series_id)
    if resource_id is not None:
        stmt = stmt.where(
            Booking.id.in_(select(BookingResource.booking_id).where(BookingResource.resource_id == resource_id))
        )
    return stmt


def sessions_with_resource(resource_id: UUID, session_ids):
    """Internal: a SELECT of the session ids (out of `session_ids`, a SELECT) whose booking uses the resource; the
    `own` reach of a coach over another context's records that hang off sessions (programs)."""
    return (
        select(Session.id)
        .join(BookingResource, BookingResource.booking_id == Session.booking_id)
        .where(Session.id.in_(session_ids), BookingResource.resource_id == resource_id)
    )


def series_sessions(session: Db, series_id: UUID, starts_from) -> list[UUID]:
    """Internal: the confirmed session ids of a series starting at or after `starts_from`, earliest first
    (programs' multi-session enrolment, CLS-02)."""
    return list(
        session.scalars(
            select(Session.id)
            .join(Booking, Booking.id == Session.booking_id)
            .where(
                Booking.booking_series_id == series_id, Booking.status == "confirmed", Booking.starts_at >= starts_from
            )
            .order_by(Booking.starts_at, Session.id)
        )
    )


def reservation_type_location(session: Db, reservation_type_id: UUID) -> UUID | None:
    """Internal (packages, wired in bootstrap): the location a reservation type belongs to, or None."""
    return session.scalar(select(ReservationType.location_id).where(ReservationType.id == reservation_type_id))


def check_location_archive(session: Db, location_id: UUID) -> None:
    """Internal, registered with platform: a location with a confirmed booking or a live checkout hold still to
    start is not archived. Blocks do not count."""
    now = clock.now()
    live = or_(Booking.status == "confirmed", and_(Booking.status == "tentative", Booking.expires_at > now))
    ahead = select(Booking.id).where(  # a closure block is not a customer's booking, so it never refuses
        Booking.location_id == location_id, Booking.kind != "block", Booking.starts_at > now, live
    )
    if session.scalar(ahead.limit(1)) is not None:
        raise Conflict(
            "This location has bookings still to come. Cancel or move them first.",
            code="location-has-future-bookings",
        )


def type_location(session: Db, type_id: UUID) -> UUID:
    """Internal: the location a reservation type belongs to, or NotFound (programs' booking policy overrides)."""
    row = session.get(ReservationType, type_id)
    if row is None:
        raise NotFound()
    return row.location_id


def session_window(
    session: Db, starts_from, starts_before, *, location_id=None, reservation_type_id=None, resource_id=None,
    limit: int = 500,
) -> list[dict]:  # fmt: skip
    """Internal: confirmed, self-bookable sessions starting in [starts_from, starts_before), earliest first, as
    session views (programs' portal listing, CLS-09). Capped at `limit`."""
    stmt = (
        select(Session)
        .join(Booking, Booking.id == Session.booking_id)
        .where(
            Booking.status == "confirmed", Session.is_self_bookable, Booking.starts_at >= starts_from,
            Booking.starts_at < starts_before,
        )
        .order_by(Booking.starts_at, Session.id)
        .limit(limit)
    )  # fmt: skip
    if location_id is not None:
        stmt = stmt.where(Session.location_id == location_id)
    if reservation_type_id is not None:
        stmt = stmt.where(Booking.reservation_type_id == reservation_type_id)
    if resource_id is not None:
        stmt = stmt.where(
            Booking.id.in_(select(BookingResource.booking_id).where(BookingResource.resource_id == resource_id))
        )
    seats = list(session.scalars(stmt))
    return _session_views(session, seats) if seats else []


def series_scope(session: Db, series_id: UUID, scope: dict) -> list[Booking]:
    """Internal: the live, locked occurrences a series scope names (rentals' cancel over a scope)."""
    return _scope(session, session.get(BookingSeries, series_id), scope)


def _key(kind: str, key: str) -> str:
    return BLOCK if kind == "block" else key


def _type_id(template: dict) -> UUID | None:
    return UUID(template["reservation_type_id"]) if template.get("reservation_type_id") else None


def _resource_ids(session: Db, booking: Booking) -> list[UUID]:
    return [row.resource_id for row in _booked(session, [booking.id])[booking.id]]


def _own(session: Db, principal: Principal, booking_id: UUID, key: str, *, lock: bool = True) -> Booking:
    """Load + authorize for a write on one booking."""
    booking = _load(session, principal, Booking, booking_id, lock=lock)
    _authorize(
        session, principal, _key(booking.kind, key), booking.location_id, _resource_ids(session, booking),
        booking.reservation_type_id,
    )  # fmt: skip
    return booking


def _check_version(booking: Booking, version: int) -> None:
    if booking.version != version:
        raise Conflict(
            "This booking was changed by someone else. Reload and try again.",
            code="version-conflict",
            version=booking.version,
        )


def list_bookings(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, READ)
    page = paginate(
        session, scope_query(select(Booking), principal, Booking.location_id), query, id_column=Booking.id,
        sort_fields={"occurrence_on": Booking.occurrence_on, "starts_at": Booking.starts_at, "booking_number": Booking.booking_number},
        default_sort="occurrence_on,starts_at",
        filter_fields={
            "location_id": Booking.location_id, "kind": Booking.kind, "status": Booking.status,
            "booking_series_id": Booking.booking_series_id, "reservation_type_id": Booking.reservation_type_id,
            "client_id": Booking.client_id, "occurrence_on": Booking.occurrence_on, "starts_at": Booking.starts_at,
            "booking_number": Booking.booking_number,
        },
        search=(Booking.title,),
    )  # fmt: skip
    return page | {"data": _views(session, page["data"])}


def get_booking_view(session: Db, principal: Principal, booking_id: UUID) -> dict:
    booking = _load(session, principal, Booking, booking_id)
    authorize(principal, READ, location_id=booking.location_id)
    return _view(session, booking)


def _check_free_flag(principal: Principal, location_id: UUID, wanted: bool | None, current: bool) -> None:
    """`allows_free_booking` lets anyone register without a package, so turning it on is a `free_book`
    decision wherever it is set (S-02)."""
    if wanted and not current:
        authorize(principal, FREE_BOOK, location_id=location_id)


def _template(session: Db, principal: Principal, data: dict) -> dict:
    """Validate a staff create and resolve everything an occurrence copies, once."""
    location_id = _location(session, principal, data["location_id"])
    template = template_for(session, location_id, data, principal.staff_user_id)
    _authorize(
        session, principal, _key(template["kind"], CREATE), location_id, [UUID(r) for r, _ in template["resources"]],
        _type_id(template),
    )  # fmt: skip
    if data.get("override_policy"):
        authorize(principal, OVERRIDE, location_id=location_id)
    _check_free_flag(principal, location_id, (data.get("session") or {}).get("allows_free_booking"), False)
    return template


def template_for(session: Db, location_id: UUID, data: dict, staff_user_id: UUID | None) -> dict:
    """Internal: validate a create (no permission check) and resolve what each occurrence copies. An owning
    context adds `client_id` and `source` = {context, type, data}; each occurrence then gets a fresh source id
    and the owner's HOOKS[context] runs in the occurrence's savepoint (rentals writes its rental_booking)."""
    kind = data["kind"]
    ordered = sorted(data["resources"], key=lambda r: r.get("role") != "primary")  # stable: primary first
    if sum(r.get("role") == "primary" for r in ordered) > 1:
        raise ValidationFailed("A booking has one primary resource.", pointer="/resources")
    rows = _resolve_resources(
        session, location_id, [r["resource_id"] for r in ordered], data.get("include_linked_resources", True)
    )
    if (kind == "block") != (data.get("block_kind") is not None):
        raise ValidationFailed("block_kind is required for, and only for, a time block.", pointer="/block_kind")
    if kind == "block" and (data.get("reservation_type_id") or data.get("session")):
        raise ValidationFailed("A time block has no reservation type or seats.", pointer="/reservation_type_id")
    rtype = _reservation_type(session, location_id, kind, data.get("reservation_type_id"))
    before, after = _buffers(session, location_id, rtype, data.get("buffer_before_min"), data.get("buffer_after_min"))
    return {
        "location_id": str(location_id), "kind": kind, "block_kind": data.get("block_kind"),
        "reservation_type_id": str(rtype.id) if rtype else None, "title": data.get("title") or (rtype.name if rtype else ""),
        "public_title": data.get("public_title"), "notes": data.get("notes"), "buffer_before_min": before,
        "buffer_after_min": after, "resources": [[str(resource_id), role] for resource_id, role in rows],
        "session": data.get("session"), "override_policy": bool(data.get("override_policy")),
        "created_by_staff_user_id": str(staff_user_id) if staff_user_id else None,
    }  # fmt: skip


HOOKS: dict = {}  # source context -> fn(session, booking, source data); registered by the owner at import


def _from_template(session: Db, template: dict, starts_at: datetime, ends_at: datetime, **extra) -> Booking:
    source = template.get("source")
    booking = create_booking(
        session, location_id=UUID(template["location_id"]), kind=template["kind"], starts_at=starts_at, ends_at=ends_at,
        resource_ids=[UUID(resource_id) for resource_id, _ in template["resources"]], include_linked=False,
        reservation_type_id=UUID(template["reservation_type_id"]) if template["reservation_type_id"] else None,
        title=template["title"], public_title=template["public_title"], notes=template["notes"],
        buffer_before_min=template["buffer_before_min"], buffer_after_min=template["buffer_after_min"],
        block_kind=template["block_kind"], session_input=template["session"], created_via="staff",
        created_by_staff_user_id=UUID(template["created_by_staff_user_id"]) if template["created_by_staff_user_id"] else None,
        override_policy=template["override_policy"],
        client_id=UUID(template["client_id"]) if template.get("client_id") else None,
        source=(source["context"], source["type"], new_id()) if source else None, **extra,
    )  # fmt: skip
    if source:
        HOOKS[source["context"]](session, booking, source["data"])
    return booking


def create_booking_command(session: Db, principal: Principal, data: dict, *, preview: bool = False) -> dict:
    """Staff create of a session or time block, single or recurring (SCH-07, SCH-08, SCH-09). Occurrences
    outside the facility hours are booked and reported in `warnings` (owner decision, question 19)."""
    template = _template(session, principal, data)
    return book(
        session, template, data, principal.staff_user_id, preview=preview, audit_key=_key(template["kind"], CREATE),
        warn_hours=True,
    )  # fmt: skip


def book(
    session: Db, template: dict, data: dict, staff_user_id: UUID | None, *, preview: bool = False,
    audit_key: str | None = None, warn_hours: bool = False,
) -> dict:  # fmt: skip
    """Internal: write a single booking or start a series from a validated template. Above SYNC_LIMIT
    occurrences the pass is handed to the worker (`status_url` set, `booking` None)."""
    location_id, zone = UUID(template["location_id"]), _zone(session, UUID(template["location_id"]))
    _check_span(data["starts_at"], data["ends_at"])
    rule = data.get("recurrence") or {"pattern": "single", "range_type": "count", "occurrence_limit": 1}
    if rule["pattern"] == "single":
        occurrences = [(0, rec.local_parts(data["starts_at"], zone)[0], data["starts_at"], data["ends_at"])]
        warnings = hours_warnings(session, location_id, occurrences) if warn_hours else []
        if preview:
            return _preview(_probe(session, template, occurrences)) | {"warnings": warnings}
        booking = _from_template(session, template, data["starts_at"], data["ends_at"])
        if audit_key:
            audit.record(session, audit_key, booking, location_id=location_id, changes={"kind": [None, booking.kind]})
        return {
            "booking": _view(session, booking),
            "booking_series_id": None,
            "created_count": 1,
            "conflict_count": 0,
            "results": [],
            "status_url": None,
            "warnings": warnings,
        }

    day, start = rec.local_parts(data["starts_at"], zone)
    end_day, end = rec.local_parts(data["ends_at"], zone)
    row = BookingSeriesRule(
        sequence=1, pattern=rule["pattern"], interval_count=rule.get("interval_count") or 1,
        weekdays=rule.get("weekdays") or ([day.isoweekday()] if rule["pattern"] == "weekly" else None),
        month_week=rule.get("month_week"), start_on=day, start_time=start.strftime("%H:%M"),
        end_time=end.strftime("%H:%M"), end_day_offset=(end_day - day).days, range_type=rule["range_type"],
        occurrence_limit=rule.get("occurrence_limit") if rule["range_type"] == "count" else None,
        until_on=rule.get("until_on") if rule["range_type"] == "until" else None, template=template,
    )  # fmt: skip
    occurrences = _occurrences(session, row, location_id)
    warnings = hours_warnings(session, location_id, occurrences) if warn_hours else []
    if preview:
        return _preview(_probe(session, template, occurrences)) | {"warnings": warnings}
    series = BookingSeries(
        location_id=location_id, kind=template["kind"], label=data.get("series_label"),
        created_by_staff_user_id=staff_user_id,
    )  # fmt: skip
    session.add(series)
    session.flush()
    row.booking_series_id, row.requested_count = series.id, len(occurrences)
    session.add(row)
    session.flush()
    if audit_key:
        audit.record(
            session, audit_key, series, location_id=location_id,
            changes={"pattern": [None, row.pattern], "requested_count": [None, len(occurrences)]},
        )  # fmt: skip
    result = _start_pass(session, staff_user_id, series, row, occurrences, data.get("on_conflict") or "abort")
    return result | {"warnings": warnings}


def hours_warnings(session: Db, location_id: UUID, occurrences) -> list[dict]:
    """Staff may book outside the facility hours (ADR 0004 section 7); they get a dismissible warning instead.
    `occurrences` are (index, local date, starts_at, ends_at). A weekday with no hours row is open."""
    zone = _zone(session, location_id)
    hours = {
        d.weekday: d
        for d in platform.service.get_facility_hours(session, system_principal("scheduling.hours"), location_id)["days"]
    }

    def span(day: date) -> tuple[datetime, datetime] | None:
        hour = hours.get(day.isoweekday())
        if hour is None:
            return _between(day, "00:00", "24:00", zone)
        if hour.is_closed or not (hour.opens_time and hour.closes_time):
            return None
        return _between(day, hour.opens_time, hour.closes_time, zone)

    outside = []
    for _, _, starts_at, ends_at in occurrences:
        first = day = starts_at.astimezone(zone).date()
        cursor = starts_at  # a booking across midnight is inside when each day's hours meet the next one's
        while (open_ := span(day)) is not None and open_[0] <= cursor < open_[1] and ends_at > open_[1]:
            cursor, day = open_[1], day + timedelta(days=1)
        if open_ is None or not (open_[0] <= cursor and ends_at <= open_[1]):
            outside.append(first)
    if not outside:
        return []
    detail = (
        f"Outside opening hours on {outside[0].isoformat()}."
        if len(outside) == 1
        else f"{len(outside)} occurrences are outside opening hours."
    )
    return [{"code": OUTSIDE_HOURS, "detail": detail, "count": len(outside)}]


def _between(day: date, opens: str, closes: str, zone: ZoneInfo) -> tuple[datetime, datetime]:
    (open_time, _), (close_time, extra) = rec.parse_wall(opens), rec.parse_wall(closes)
    return rec.localize(day, open_time, zone), rec.localize(day + timedelta(days=extra), close_time, zone)


# --- series ------------------------------------------------------------------------------------------------


def _occurrences(session: Db, rule: BookingSeriesRule, location_id: UUID) -> list[tuple[int, date, datetime, datetime]]:
    """(index, local date, starts_at, ends_at) of one pass, each localised on its own (DST-safe)."""
    limit = settings_for(session, location_id).max_series_occurrences
    start, _ = rec.parse_wall(rule.start_time)
    end, extra = rec.parse_wall(rule.end_time)
    duration = rec.nominal_minutes(start, end, rule.end_day_offset + extra)
    if duration <= 0:
        raise ValidationFailed("The end must be after the start.", pointer="/ends_at")
    try:
        days = rec.expand(
            rec.Rule(
                rule.pattern, rule.start_on, rule.interval_count, tuple(rule.weekdays or ()), rule.month_week,
                rule.range_type, rule.occurrence_limit, rule.until_on,
            ),
            limit,
        )  # fmt: skip
    except rec.RuleError as exc:
        raise ValidationFailed(str(exc), pointer="/recurrence", code=exc.code) from None
    zone = _zone(session, location_id)
    return [(index, day, *rec.span(day, start, duration, zone)) for index, day in enumerate(days)]


def _result(
    index: int, day: date, starts_at: datetime, ends_at: datetime, status: str, conflicts=(), booking_id=None
) -> dict:
    return {
        "index": index, "local_start": day.isoformat(), "starts_at": _iso(starts_at), "ends_at": _iso(ends_at),
        "status": status, "booking_id": str(booking_id) if booking_id else None, "conflicts": list(conflicts),
    }  # fmt: skip


def _probe(session: Db, template: dict, occurrences) -> list[dict]:
    """Dry run: what each occurrence would meet, without writing (SCH-09 preview). Besides existing holds
    and closures it flags occurrences of the same pass that overlap each other."""
    location_id = UUID(template["location_id"])
    plan = [
        r for r, _, _ in hold_plan(session, [(UUID(resource_id), role) for resource_id, role in template["resources"]])
    ]
    before, after = timedelta(minutes=template["buffer_before_min"]), timedelta(minutes=template["buffer_after_min"])
    results, previous_end = [], None
    for index, day, starts_at, ends_at in occurrences:
        status, found = "ok", []
        if (
            template["kind"] != "block"
            and not template["override_policy"]
            and blackouts_between(session, location_id, starts_at, ends_at, "all")
        ):
            status = "blackout"
        else:
            found = [
                c
                for c in find_conflicts(session, plan, Range(starts_at - before, ends_at + after, bounds="[)"))
                if not c["is_expired_hold"]
            ]
            if found or (previous_end is not None and starts_at - before < previous_end):
                status = "conflict"
        if status == "ok":
            previous_end = ends_at + after
        results.append(_result(index, day, starts_at, ends_at, status, found))
    return results


def _preview(results: list[dict]) -> dict:
    return {
        "requested_count": len(results), "ok_count": sum(r["status"] == "ok" for r in results),
        "conflict_count": sum(r["status"] != "ok" for r in results), "occurrences": results, "status_url": None,
    }  # fmt: skip


def _generate(
    session: Db, series: BookingSeries, rule: BookingSeriesRule, occurrences
) -> tuple[list[Booking], list[dict]]:
    """Create occurrences, one savepoint each, so a clash is attributed to its occurrence. Returns the
    bookings made and the results of those that were not. Idempotent on (rule, occurrence index)."""
    start, _ = rec.parse_wall(rule.start_time)
    end, extra = rec.parse_wall(rule.end_time)
    duration = rec.nominal_minutes(start, end, rule.end_day_offset + extra)
    done = set(session.scalars(select(Booking.occurrence_index).where(Booking.booking_series_rule_id == rule.id)))
    created, skipped = [], []
    for index, day, starts_at, ends_at in occurrences:
        if index in done:
            continue
        try:
            with session.begin_nested():
                created.append(
                    _from_template(
                        session, rule.template, starts_at, ends_at, series=(series.id, rule.id, index),
                        local=(day, rule.start_time, duration),
                    )
                )  # fmt: skip
        except Conflict as exc:
            if exc.code not in ("booking-conflict", "resource-blacked-out"):
                raise
            status = "conflict" if exc.code == "booking-conflict" else "blackout"
            skipped.append(_result(index, day, starts_at, ends_at, status, exc.extra.get("conflicts", ())))
    _count(session, series.id, len(created))
    rule.created_count += len(created)
    rule.conflict_count += len(skipped)
    session.flush()
    return created, skipped


def _clashes(results: list[dict]) -> list[dict]:
    return [r for r in results if r["status"] == "conflict"]


def _start_pass(
    session: Db,
    staff_user_id: UUID | None,
    series: BookingSeries,
    rule: BookingSeriesRule,
    occurrences,
    on_conflict: str,
) -> dict:
    """Run a generation pass now (up to SYNC_LIMIT occurrences) or hand it to the worker."""
    base = {
        "booking": None,
        "booking_series_id": series.id,
        "created_count": 0,
        "conflict_count": 0,
        "results": [],
        "status_url": None,
    }
    if len(occurrences) > SYNC_LIMIT:
        run = BookingSeriesRun(
            booking_series_id=series.id, booking_series_rule_id=rule.id, kind="generate", requested_count=len(occurrences),
            command={"on_conflict": on_conflict, "next_index": 0}, requested_by_staff_user_id=staff_user_id,
        )  # fmt: skip
        session.add(run)
        session.flush()
        tenant_id, run_id = str(session.info["tenant_id"]), str(run.id)

        def enqueue() -> None:
            from app.modules.scheduling.jobs import generate_series

            generate_series.send(tenant_id, run_id)

        session.info.setdefault("after_commit", []).append(enqueue)
        return base | {"status_url": f"/api/v1/booking-series/{series.id}/runs/{run.id}"}
    rule.status, rule.started_at = "generating", clock.now()
    created, skipped = _generate(session, series, rule, occurrences)
    if (on_conflict == "abort" and _clashes(skipped)) or not created:
        found = [c for r in skipped for c in r["conflicts"]]
        error = (
            _conflict(found)
            if found
            else Conflict("No occurrence could be booked.", code="booking-conflict", conflicts=[])
        )
        error.extra["results"] = skipped
        raise error  # the request transaction rolls back: nothing of the pass is kept
    rule.status, rule.finished_at, rule.results = "completed", clock.now(), skipped
    events.publish(
        session,
        ev.SeriesGenerated(
            booking_series_id=series.id,
            booking_series_rule_id=rule.id,
            created_count=len(created),
            conflict_count=len(skipped),
        ),
        series.id,
    )
    session.flush()
    return base | {
        "booking": _view(session, created[0]),
        "created_count": len(created),
        "conflict_count": len(skipped),
        "results": skipped,
    }


def run_generation_chunk(session: Db, run_id: UUID) -> bool:
    """One worker step of a long pass: at most SYNC_LIMIT occurrences, committed by the caller. Returns True
    while there is more to do. Safe to redeliver and to resume after a crash: progress lives in the run row
    and the unique (rule, occurrence index) refuses a second copy."""
    run = session.execute(
        select(BookingSeriesRun).where(BookingSeriesRun.id == run_id).with_for_update()
    ).scalar_one_or_none()
    if run is None or run.status in ("completed", "failed"):
        return False
    rule = session.get(BookingSeriesRule, run.booking_series_rule_id)
    series = session.get(BookingSeries, run.booking_series_id)
    occurrences = _occurrences(session, rule, series.location_id)
    skip = run.command["on_conflict"] == "skip"

    def finish(failed: bool, results: list[dict]) -> bool:
        now = clock.now()
        run.status, run.finished_at, run.results = ("failed" if failed else "completed"), now, results
        run.conflict_count = len(results)
        rule.status, rule.finished_at, rule.results = run.status, now, results
        events.publish(
            session,
            ev.SeriesGenerated(
                booking_series_id=series.id,
                booking_series_rule_id=rule.id,
                created_count=run.ok_count,
                conflict_count=len(results),
            ),
            series.id,
        )
        session.flush()
        return False

    if run.status == "pending":
        run.status, run.started_at, rule.status, rule.started_at = "running", clock.now(), "generating", clock.now()
        if not skip and (found := _clashes(_probe(session, rule.template, occurrences))):
            return finish(True, found)  # abort mode writes nothing when the set-based pre-check finds a clash
    start = run.command["next_index"]
    chunk = occurrences[start : start + SYNC_LIMIT]
    created, skipped = _generate(session, series, rule, chunk)
    if _clashes(skipped) and not skip:  # lost a race after the pre-check: undo the whole pass
        session.execute(delete(Booking).where(Booking.booking_series_rule_id == rule.id))
        _count(session, series.id, -rule.created_count)
        rule.created_count, run.ok_count = 0, 0
        return finish(True, skipped)
    run.ok_count += len(created)
    run.command = run.command | {"next_index": start + len(chunk)}
    results = [*run.results, *skipped]
    if start + len(chunk) >= len(occurrences):
        return finish(False, results)
    run.results, run.conflict_count = results, len(results)
    session.flush()
    return True


def _series(session: Db, principal: Principal, series_id: UUID, key: str, *, lock: bool = False) -> BookingSeries:
    series = _load(session, principal, BookingSeries, series_id, lock=lock)
    authorize(principal, key, location_id=series.location_id)
    return series


def _rule_view(rule: BookingSeriesRule) -> dict:
    view = {c.key: getattr(rule, c.key) for c in BookingSeriesRule.__table__.columns if c.key != "template"}
    return view | {
        "rule": {
            "pattern": rule.pattern, "interval_count": rule.interval_count, "weekdays": rule.weekdays,
            "month_week": rule.month_week, "range_type": rule.range_type, "occurrence_limit": rule.occurrence_limit,
            "until_on": rule.until_on,
        }
    }  # fmt: skip


def get_series(session: Db, principal: Principal, series_id: UUID) -> dict:
    series = _series(session, principal, series_id, READ)
    rules = session.scalars(
        select(BookingSeriesRule)
        .where(BookingSeriesRule.booking_series_id == series.id)
        .order_by(BookingSeriesRule.sequence)
    )
    return {c.key: getattr(series, c.key) for c in BookingSeries.__table__.columns} | {
        "rules": [_rule_view(r) for r in rules]
    }


def get_series_rule(session: Db, principal: Principal, series_id: UUID, rule_id: UUID) -> dict:
    series = _series(session, principal, series_id, READ)
    rule = session.get(BookingSeriesRule, rule_id)
    if rule is None or rule.booking_series_id != series.id:
        raise NotFound()
    return _rule_view(rule)


def get_series_run(session: Db, principal: Principal, series_id: UUID, run_id: UUID) -> BookingSeriesRun:
    series = _series(session, principal, series_id, READ)
    run = session.get(BookingSeriesRun, run_id)
    if run is None or run.booking_series_id != series.id:
        raise NotFound()
    return run


def add_series_rule(session: Db, principal: Principal, series_id: UUID, data: dict) -> dict:
    """Stack another pass onto a series ("add occurrences", SCH-09): same attributes, new pattern."""
    series = _series(session, principal, series_id, UPDATE_SERIES, lock=True)
    return add_rule(session, series.id, data, principal.staff_user_id, principal=principal)


def add_rule(
    session: Db, series_id: UUID, data: dict, staff_user_id: UUID | None, *, principal: Principal | None = None,
    key: str = UPDATE_SERIES, template_rule: BookingSeriesRule | None = None, extra_changes: dict | None = None,
    sync_only: bool = False,
) -> dict:  # fmt: skip
    """Internal (no gate unless `principal` is given; `key` gates and audits): add a pass to a series, copying
    its first template (or `template_rule`'s), so an owner's source hook runs for the new occurrences too (rentals RNT-04 "add
    more"). The copy never carries the policy override or the original creator over (S-03)."""
    series = session.execute(select(BookingSeries).where(BookingSeries.id == series_id).with_for_update()).scalar_one()
    rules = session.scalars(
        select(BookingSeriesRule)
        .where(BookingSeriesRule.booking_series_id == series.id)
        .order_by(BookingSeriesRule.sequence)
    ).all()
    template = dict((template_rule or rules[0]).template)
    if data.get("resources"):
        ordered = sorted(data["resources"], key=lambda r: r.get("role") != "primary")
        rows = _resolve_resources(session, series.location_id, [r["resource_id"] for r in ordered], False)
        template["resources"] = [[str(resource_id), role] for resource_id, role in rows]
    if principal is not None:
        _authorize(
            session, principal, key, series.location_id, [UUID(r) for r, _ in template["resources"]], _type_id(template)
        )
    override = bool(data.get("override_policy")) and principal is not None
    if override:
        authorize(principal, OVERRIDE, location_id=series.location_id)
    template["override_policy"] = override
    template["created_by_staff_user_id"] = str(staff_user_id) if staff_user_id else None
    rule = data["rule"]
    row = BookingSeriesRule(
        booking_series_id=series.id, sequence=rules[-1].sequence + 1, pattern=rule["pattern"],
        interval_count=rule.get("interval_count") or 1,
        weekdays=rule.get("weekdays") or ([data["start_on"].isoweekday()] if rule["pattern"] == "weekly" else None),
        month_week=rule.get("month_week"), start_on=data["start_on"], start_time=data["start_time"],
        end_time=data["end_time"], end_day_offset=data.get("end_day_offset") or 0, range_type=rule["range_type"],
        occurrence_limit=rule.get("occurrence_limit") if rule["range_type"] == "count" else None,
        until_on=rule.get("until_on") if rule["range_type"] == "until" else None, template=template,
    )  # fmt: skip
    occurrences = _occurrences(session, row, series.location_id)
    if sync_only and len(occurrences) > SYNC_LIMIT:
        raise ValidationFailed(
            f"A pattern change books at most {SYNC_LIMIT} occurrences; add a further pass for the rest.",
            pointer="/rule/occurrence_limit",
        )
    if data.get("preview"):
        return {"preview": _preview(_probe(session, template, occurrences))}
    row.requested_count = len(occurrences)
    session.add(row)
    session.flush()
    audit.record(
        session, key, series, location_id=series.location_id,
        changes={"rule_added": [None, row.sequence]} | (extra_changes or {}),
    )  # fmt: skip
    return _start_pass(session, staff_user_id, series, row, occurrences, data.get("on_conflict") or "abort")


def change_series_rule(session: Db, principal: Principal, series_id: UUID, rule_id: UUID, data: dict) -> dict:
    """Change an existing pass's pattern (SCH-09): its live occurrences from `start_on` are cancelled and a new
    pass with the new pattern and the old pass's attributes is added, in one command (ADR 0004 section 6).
    `preview` runs both in a savepoint and rolls back, so the new pass is probed without the old holds."""
    series = _series(session, principal, series_id, UPDATE_SERIES, lock=True)
    rule = session.get(BookingSeriesRule, rule_id)
    if rule is None or rule.booking_series_id != series.id:
        raise NotFound()
    if data["start_on"] < platform.service.location_today(session, series.location_id):
        raise ValidationFailed("A pattern change starts today or later.", pointer="/start_on")
    targets = list(
        session.scalars(
            select(Booking)
            .where(
                Booking.booking_series_rule_id == rule.id,
                Booking.status != "cancelled",
                Booking.occurrence_on >= data["start_on"],
            )
            .order_by(Booking.starts_at, Booking.id)
            .with_for_update()
        )
    )
    booked = _booked(session, [b.id for b in targets])
    for booking in targets:  # the old occurrences are cancelled, so the caller needs the delete key too
        for key in (UPDATE_SERIES, DELETE_SERIES):
            _authorize(
                session, principal, key, series.location_id, [r.resource_id for r in booked[booking.id]],
                booking.reservation_type_id,
            )  # fmt: skip
    outer = session.begin_nested()
    try:
        for booking in targets:
            cancel_booking(session, booking, reason="series_edit")
        result = add_rule(
            session, series.id, data, principal.staff_user_id, principal=principal, template_rule=rule,
            extra_changes={"rule_replaced": [None, rule.sequence], "cancelled_count": [None, len(targets)]},
            sync_only=True,
        )  # fmt: skip
    except BaseException:
        outer.rollback()
        raise
    outer.rollback() if data.get("preview") else outer.commit()
    return result | {"cancelled_count": len(targets)}


def _scope(session: Db, series: BookingSeries, scope: dict) -> list[Booking]:
    """Resolve a series scope (this, following, all, selected, date_range) to its live occurrences, locked."""
    stmt = select(Booking).where(Booking.booking_series_id == series.id, Booking.status != "cancelled")
    mode = scope["mode"]
    if mode in ("this", "following"):
        anchor = session.get(Booking, scope.get("anchor_booking_id")) if scope.get("anchor_booking_id") else None
        if anchor is None or anchor.booking_series_id != series.id:
            raise ValidationFailed(
                "anchor_booking_id must be an occurrence of this series.", pointer="/scope/anchor_booking_id"
            )
        stmt = (
            stmt.where(Booking.id == anchor.id) if mode == "this" else stmt.where(Booking.starts_at >= anchor.starts_at)
        )
    elif mode == "selected":
        stmt = stmt.where(Booking.id.in_(scope.get("booking_ids") or []))
    elif mode == "date_range":
        if scope.get("from_on"):
            stmt = stmt.where(Booking.occurrence_on >= scope["from_on"])
        if scope.get("to_on"):
            stmt = stmt.where(Booking.occurrence_on <= scope["to_on"])
    return list(session.scalars(stmt.order_by(Booking.starts_at, Booking.id).with_for_update()))


_TIMING = ("start_time", "duration_min", "shift_days", "buffer_before_min", "buffer_after_min", "resources")


def edit_series(session: Db, principal: Principal, series_id: UUID, data: dict) -> dict:
    """Mass edit (SCH-10): a sparse patch over a scope. Times are local wall time, so a shifted series keeps
    its wall time across DST. Every selected occurrence gives up its holds first and takes its new ones in
    its own savepoint, so a clash is attributed to its occurrence and never to a neighbour's old range.
    `preview` runs the real command and rolls it back."""
    series = _series(session, principal, series_id, UPDATE_SERIES, lock=True)
    targets, patch = _scope(session, series, data["scope"]), dict(data["patch"])
    skip, preview = data.get("on_conflict") == "skip", bool(data.get("preview"))
    outer = session.begin_nested()
    try:
        results = _apply_patch(session, principal, series, targets, patch, skip)
        failed = [r for r in results if r["status"] != "ok"]
        if not preview:
            audit.record(
                session,
                UPDATE_SERIES,
                series,
                location_id=series.location_id,
                changes={"fields": sorted(patch), "affected_count": [None, len(results) - len(failed)]},
            )
    except BaseException:
        outer.rollback()
        raise
    outer.rollback() if preview else outer.commit()
    return {
        "booking_series_id": series.id, "affected_count": len(results) - len(failed), "conflict_count": len(failed),
        "results": results if preview else failed,
    }  # fmt: skip


def _apply_patch(
    session: Db, principal: Principal, series: BookingSeries, targets: list[Booking], patch: dict, skip: bool
) -> list[dict]:
    zone = _zone(session, series.location_id)
    seats_patch = patch.pop("session", None) or {}
    resource_rows = None
    if patch.get("resources"):
        ordered = sorted(patch["resources"], key=lambda r: r.get("role") != "primary")
        resource_rows = _resolve_resources(session, series.location_id, [r["resource_id"] for r in ordered], False)
    if "reservation_type_id" in patch:
        _reservation_type(session, series.location_id, series.kind, patch["reservation_type_id"])
        _check_grant(session, principal, UPDATE_SERIES, patch["reservation_type_id"])
    if seats_patch.get("capacity") is not None:
        authorize(principal, CAPACITY, location_id=series.location_id)
    booked = _booked(session, [b.id for b in targets])
    for booking in targets:
        _authorize(
            session, principal, UPDATE_SERIES, series.location_id, [r.resource_id for r in booked[booking.id]],
            booking.reservation_type_id,
        )  # fmt: skip
    timing = any(patch.get(key) is not None for key in _TIMING)
    if timing:
        _release_holds(session, [b.id for b in targets])
        session.flush()
    seats = {
        s.booking_id: s for s in session.scalars(select(Session).where(Session.booking_id.in_([b.id for b in targets])))
    }
    _check_free_flag(
        principal, series.location_id, seats_patch.get("allows_free_booking"),
        all(seat.allows_free_booking for seat in seats.values()),
    )  # fmt: skip
    results = []
    for booking in targets:
        status, found = "ok", []
        old = {
            key: getattr(booking, key)
            for key in (
                "occurrence_on",
                "local_start_time",
                "duration_min",
                "starts_at",
                "ends_at",
                "buffer_before_min",
                "buffer_after_min",
            )
        }
        old_rows = [(r.resource_id, r.role) for r in booked[booking.id]]
        for key in ("title", "public_title", "notes", "reservation_type_id"):
            if key in patch:
                setattr(booking, key, patch[key] if key != "title" else patch[key] or "")
        if timing:
            day = booking.occurrence_on + timedelta(days=patch.get("shift_days") or 0)
            wall = patch.get("start_time") or booking.local_start_time
            duration = patch.get("duration_min") or booking.duration_min
            starts_at, ends_at = rec.span(day, rec.parse_wall(wall)[0], duration, zone)
            _apply(
                booking,
                {
                    "occurrence_on": day,
                    "local_start_time": wall[:5],
                    "duration_min": duration,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                },
            )
            for key in ("buffer_before_min", "buffer_after_min"):
                if patch.get(key) is not None:
                    setattr(booking, key, patch[key])
            try:
                with session.begin_nested():
                    if booking.kind != "block":
                        _check_blackout(session, series.location_id, starts_at, ends_at)
                    if resource_rows is not None:
                        _set_resources(session, booking, resource_rows)
                    session.flush()
                    _write_holds(session, booking)
            except Conflict as exc:
                if exc.code not in ("booking-conflict", "resource-blacked-out") or not skip:
                    raise  # abort mode: the caller rolls the whole edit back
                status, found = (
                    ("conflict" if exc.code == "booking-conflict" else "blackout"),
                    exc.extra.get("conflicts", []),
                )
                _apply(booking, old)  # this occurrence stays where it was; a clash here aborts the edit
                _set_resources(session, booking, old_rows)
                _write_holds(session, booking)
            else:
                booking.version += 1
                events.publish(session, ev.BookingRescheduled(**_event_fields(booking)), booking.id)
        seat = seats.get(booking.id)
        if seat is not None and status == "ok":
            for key in ("is_self_bookable", "allows_free_booking"):
                if seats_patch.get(key) is not None:
                    setattr(seat, key, seats_patch[key])
            if seats_patch.get("capacity") is not None:
                status = set_capacity(session, [seat.id], seats_patch["capacity"])[0]["status"]
        results.append(
            _result(
                booking.occurrence_index or 0,
                booking.occurrence_on,
                booking.starts_at,
                booking.ends_at,
                status,
                found,
                booking.id,
            )
        )
    session.flush()
    return results


def cancel_series(session: Db, principal: Principal, series_id: UUID, data: dict) -> dict:
    """Scoped soft cancel (SCH-11): one cancellation event per occurrence so owners can react."""
    series = _series(session, principal, series_id, DELETE_SERIES, lock=True)
    targets = _scope(session, series, data["scope"])
    for type_id in {b.reservation_type_id for b in targets}:
        _check_grant(session, principal, DELETE_SERIES, type_id)
    if not data.get("preview"):
        for booking in targets:
            cancel_booking(session, booking, reason=data.get("reason") or "staff")
        audit.record(
            session,
            DELETE_SERIES,
            series,
            location_id=series.location_id,
            changes={"cancelled_count": [None, len(targets)]},
            reason=data.get("note"),
        )
    return {
        "booking_series_id": series.id, "affected_count": len(targets), "conflict_count": 0,
        "results": [_result(b.occurrence_index or 0, b.occurrence_on, b.starts_at, b.ends_at, "ok", (), b.id) for b in targets] if data.get("preview") else [],
    }  # fmt: skip


def update_booking_command(session: Db, principal: Principal, booking_id: UUID, data: dict) -> dict:
    """Sparse patch of non-time fields. A buffer change rewrites the holds and may conflict (SCH-14)."""
    booking = _own(session, principal, booking_id, UPDATE)
    _check_version(booking, data.pop("version"))
    if booking.status == "cancelled":
        raise Conflict("A cancelled booking cannot be edited.")
    if "reservation_type_id" in data:
        _reservation_type(session, booking.location_id, booking.kind, data["reservation_type_id"])
        _check_grant(session, principal, UPDATE, data["reservation_type_id"])
    if "block_kind" in data and booking.kind != "block":
        raise ValidationFailed("Only a time block has a block kind.", pointer="/block_kind")
    rebuffer = any(
        key in data and data[key] != getattr(booking, key) for key in ("buffer_before_min", "buffer_after_min")
    )
    _apply(booking, {key: ("" if key == "title" and value is None else value) for key, value in data.items()})
    booking.version += 1
    audit.record(
        session, _key(booking.kind, UPDATE), booking, location_id=booking.location_id, changes=audit.diff(booking)
    )
    session.flush()
    if rebuffer:
        _release_holds(session, [booking.id])
        _write_holds(session, booking)
    return _view(session, booking)


def reschedule_command(session: Db, principal: Principal, booking_id: UUID, data: dict) -> dict:
    """Drag-and-drop and form time changes (SCH-12). A stale `version` is 409 version-conflict."""
    booking = _own(session, principal, booking_id, UPDATE)
    _check_version(booking, data["version"])
    resource_ids = None
    if data.get("resources"):
        ordered = sorted(data["resources"], key=lambda r: r.get("role") != "primary")
        resource_ids = [r["resource_id"] for r in ordered]
        _authorize(session, principal, _key(booking.kind, UPDATE), booking.location_id, resource_ids)
    if data.get("override_policy"):
        authorize(principal, OVERRIDE, location_id=booking.location_id)
    before = (booking.starts_at, booking.ends_at)
    reschedule_booking(
        session,
        booking,
        starts_at=data["starts_at"],
        ends_at=data["ends_at"],
        resource_ids=resource_ids,
        override_policy=bool(data.get("override_policy")),
    )
    audit.record(
        session, _key(booking.kind, UPDATE), booking, location_id=booking.location_id,
        changes={"starts_at": [_iso(before[0]), _iso(booking.starts_at)], "ends_at": [_iso(before[1]), _iso(booking.ends_at)]},
    )  # fmt: skip
    span = [(0, booking.occurrence_on, booking.starts_at, booking.ends_at)]
    return _view(session, booking) | {"warnings": hours_warnings(session, booking.location_id, span)}


def cancel_command(session: Db, principal: Principal, booking_id: UUID, data: dict) -> dict:
    booking = _own(session, principal, booking_id, DELETE)
    _check_version(booking, data["version"])
    if booking.status != "cancelled":
        cancel_booking(session, booking, reason=data.get("reason") or "staff")
        audit.record(
            session,
            _key(booking.kind, DELETE),
            booking,
            location_id=booking.location_id,
            changes={"status": ["confirmed", "cancelled"]},
            reason=data.get("note"),
        )
    return _view(session, booking)


# --- staff commands: sessions ------------------------------------------------------------------------------


def list_sessions(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, READ)
    stmt = select(Session).join(Booking, Booking.id == Session.booking_id)
    page = paginate(
        session, scope_query(stmt, principal, Session.location_id), query, id_column=Session.id,
        sort_fields={"starts_at": Booking.starts_at}, default_sort="starts_at",
        filter_fields={
            "location_id": Session.location_id, "starts_at": Booking.starts_at, "status": Booking.status,
            "reservation_type_id": Booking.reservation_type_id, "booking_series_id": Booking.booking_series_id,
            "is_self_bookable": Session.is_self_bookable,
        },
    )  # fmt: skip
    return page | {"data": _session_views(session, page["data"])}


def get_session_view(session: Db, principal: Principal, session_id: UUID) -> dict:
    seat = _load(session, principal, Session, session_id)
    authorize(principal, READ, location_id=seat.location_id)
    return _session_views(session, [seat])[0]


def update_session(session: Db, principal: Principal, session_id: UUID, data: dict) -> dict:
    seat = _load(session, principal, Session, session_id, lock=True)
    booking = session.get(Booking, seat.booking_id)
    _authorize(
        session, principal, SESSION, seat.location_id, _resource_ids(session, booking), booking.reservation_type_id
    )
    _check_free_flag(principal, seat.location_id, data.get("allows_free_booking"), seat.allows_free_booking)
    _apply(seat, data)
    audit.record(session, SESSION, seat, location_id=seat.location_id, changes=audit.diff(seat))
    session.flush()
    return _session_views(session, [seat])[0]


def reservation_type_exists(session: Db, reservation_type_id: UUID) -> bool:
    """Internal: an active reservation type of the tenant (programs passes it on to engagement's favourites)."""
    found = select(ReservationType.id).where(ReservationType.id == reservation_type_id, ReservationType.is_active)
    return session.scalar(found) is not None


def change_capacity(session: Db, principal: Principal, session_ids: list[UUID], capacity: int) -> dict:
    """Single or bulk class-size change (CLS-04). A session with more seats taken than the new size is
    reported as capacity-below-booked and left alone."""
    seats = [_load(session, principal, Session, session_id) for session_id in dict.fromkeys(session_ids)]
    for location_id in {seat.location_id for seat in seats}:
        authorize(principal, CAPACITY, location_id=location_id)
    for seat in seats:
        _check_grant(session, principal, CAPACITY, session.get(Booking, seat.booking_id).reservation_type_id)
    results = set_capacity(session, [seat.id for seat in seats], capacity)
    for seat, result in zip(sorted(seats, key=lambda s: s.id), results, strict=True):
        if result["status"] == "ok":
            audit.record(session, CAPACITY, seat, location_id=seat.location_id, changes={"capacity": [None, capacity]})
    return {"results": results, "changed_count": sum(r["status"] == "ok" for r in results)}


# --- reads: calendar and availability ----------------------------------------------------------------------


def _window(start: datetime, end: datetime) -> None:
    # The extra hour lets a 42-local-day month grid span a clock change (it is then 42 days and 1 hour of UTC).
    widest = timedelta(days=MAX_CALENDAR_DAYS, hours=1)
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > widest:
        raise ValidationFailed(
            f"Send from < to with UTC offsets, at most {MAX_CALENDAR_DAYS} days apart.", pointer="/to"
        )


def _columns(session: Db, location_id: UUID, group_id: UUID | None, resource_ids: list[UUID] | None):
    return resources.service.in_location(session, location_id, group_id=group_id, ids=resource_ids)


def get_calendar(
    session: Db, principal: Principal, location_id: UUID, start: datetime, end: datetime, *,
    resource_group_id: UUID | None = None, resource_ids: list[UUID] | None = None, kinds: list[str] | None = None,
    reservation_type_ids: list[UUID] | None = None,
) -> dict:  # fmt: skip
    """Day, week, month and resource views from one range query over the hold index (SCH-01): one tile per
    (booking, resource column), `descendant` tiles being the greyed "held" rendering on sub-venues."""
    _location(session, principal, location_id)
    authorize(principal, READ, location_id=location_id)
    _window(start, end)
    columns = _columns(session, location_id, resource_group_id, resource_ids)
    stmt = (
        select(
            ResourceHold.resource_id,
            BookingResource.role,
            Booking,
            Session.capacity,
            Session.booked_count,
            ReservationType.color,
        )
        .join(Booking, Booking.id == ResourceHold.booking_id)
        .outerjoin(
            BookingResource,
            (BookingResource.booking_id == Booking.id) & (BookingResource.resource_id == ResourceHold.resource_id),
        )
        .outerjoin(Session, Session.booking_id == Booking.id)
        .outerjoin(ReservationType, ReservationType.id == Booking.reservation_type_id)
        .where(
            ResourceHold.resource_id.in_([c.id for c in columns]),
            ResourceHold.during.overlaps(Range(start, end, bounds="[)")),
        )
        .order_by(Booking.starts_at, Booking.id, ResourceHold.resource_id)
    )
    if kinds:
        stmt = stmt.where(Booking.kind.in_(kinds))
    if reservation_type_ids:
        stmt = stmt.where(Booking.reservation_type_id.in_(reservation_type_ids))
    can_edit, denied = principal.has(UPDATE), _denied_types(session, principal)
    mine = (
        platform.service.linked_resource_id(session, principal.staff_user_id)
        if principal.permissions.get(UPDATE) == "own"
        else None
    )
    rows = session.execute(stmt).all()
    own_bookings = {row.Booking.id for row in rows if row.resource_id == mine}
    entries = [
        {
            "booking_id": b.id, "booking_number": b.booking_number, "kind": b.kind, "block_kind": b.block_kind,
            "title": b.title, "starts_at": b.starts_at, "ends_at": b.ends_at, "buffer_before_min": b.buffer_before_min,
            "buffer_after_min": b.buffer_after_min, "status": b.status, "resource_id": row.resource_id,
            "resource_role": row.role or "descendant", "color": row.color, "reservation_type_id": b.reservation_type_id,
            "client_id": b.client_id, "booking_series_id": b.booking_series_id, "capacity": row.capacity,
            "booked_count": row.booked_count,
            "fill": _fill(row.capacity, row.booked_count) if row.capacity is not None else None,
            "version": b.version,
            "can_edit": can_edit and b.reservation_type_id not in denied
            and (principal.permissions.get(UPDATE) != "own" or b.id in own_bookings),
        }
        for row in rows
        for b in [row.Booking]
    ]  # fmt: skip
    types = session.scalars(
        select(ReservationType)
        .where(ReservationType.location_id == location_id, ReservationType.is_active)
        .order_by(ReservationType.sort_order, ReservationType.name)
    )
    settings = settings_for(session, location_id)
    opened = _open_ranges(session, location_id, [c.id for c in columns], start, end)
    return {
        "location_id": location_id, "time_zone": _zone(session, location_id).key, "from": start, "to": end,
        "calendar_slot_min": settings.calendar_slot_min, "drag_drop_default": settings.drag_drop_default,
        "resource_hours": [
            {"resource_id": rid, "open": [{"starts_at": s, "ends_at": e} for s, e in ranges]}
            for rid, (has_windows, ranges) in opened.items()
            if has_windows
        ],
        "facility_hours": platform.service.get_facility_hours(session, principal, location_id)["days"],
        "resources": columns, "entries": entries,
        "blackouts": [_blackout_view(row) for row in blackouts_between(session, location_id, start, end)],
        "legend": {
            "reservation_types": [{"reservation_type_id": t.id, "name": t.name, "color": t.color} for t in types],
            "fill_states": ["empty", "partial", "full"],
        },
    }  # fmt: skip


def get_availability(
    session: Db, principal: Principal, location_id: UUID, start: datetime, end: datetime, *,
    resource_ids: list[UUID] | None = None, min_free_min: int = 15,
) -> dict:  # fmt: skip
    """Free time per resource (SCH-18): its availability windows, or the facility hours when it has none,
    minus its holds (which already include buffers, linked and parent or child bookings) and closures."""
    _location(session, principal, location_id)
    authorize(principal, READ, location_id=location_id)
    _window(start, end)
    if resource_ids and len(resource_ids) > 50:
        raise ValidationFailed("At most 50 resources.", pointer="/resource_id[in]")
    return free_ranges(session, location_id, start, end, resource_ids=resource_ids, min_free_min=min_free_min)


def _days(start: datetime, end: datetime, zone: ZoneInfo) -> list[date]:
    first, last = start.astimezone(zone).date() - timedelta(days=1), end.astimezone(zone).date()
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _window_ranges(day: date, window, zone: ZoneInfo) -> tuple[datetime, datetime] | None:
    if not slots.window_fires_on(day, window.starts_on, window.ends_on, window.weekdays, window.interval_weeks):
        return None
    return _between(day, window.start_time, window.end_time, zone)


def _open_ranges(session: Db, location_id: UUID, ids: list[UUID], start: datetime, end: datetime) -> dict:
    """resource id -> (has windows, open ranges clipped to [start, end)): its availability windows, else the
    facility hours (a weekday without hours is open all day)."""
    zone = _zone(session, location_id)
    days = _days(start, end, zone)
    windows = resources.service.windows_for(session, ids)
    principal = system_principal("scheduling.free_ranges")
    hours = {d.weekday: d for d in platform.service.get_facility_hours(session, principal, location_id)["days"]}
    result = {}
    for resource_id in ids:
        open_, rules = [], windows.get(resource_id)
        for day in days:
            if rules:
                open_ += [r for w in rules if (r := _window_ranges(day, w, zone))]
            elif (hour := hours.get(day.isoweekday())) is None:
                open_.append(_between(day, "00:00", "24:00", zone))
            elif not hour.is_closed and hour.opens_time and hour.closes_time:
                open_.append(_between(day, hour.opens_time, hour.closes_time, zone))
        clipped = sorted((max(s, start), min(e, end)) for s, e in open_ if e > start and s < end)
        result[resource_id] = (bool(rules), clipped)
    return result


def free_ranges(
    session: Db, location_id: UUID, start: datetime, end: datetime, *, resource_ids: list[UUID] | None = None,
    min_free_min: int = 15,
) -> dict:  # fmt: skip
    """Internal (no gate): the free time of get_availability, also used by rentals' online search. Every
    closure counts; holds of checkouts whose clock ran out do not count as busy."""
    columns, zone = _columns(session, location_id, None, resource_ids), _zone(session, location_id)
    ids = [c.id for c in columns]
    opened = _open_ranges(session, location_id, ids, start, end)
    busy: dict[UUID, list] = {resource_id: [] for resource_id in ids}
    held = session.execute(
        select(ResourceHold.resource_id, ResourceHold.during).where(
            ResourceHold.resource_id.in_(ids),
            ResourceHold.during.overlaps(Range(start, end, bounds="[)")),
            (ResourceHold.expires_at.is_(None)) | (ResourceHold.expires_at > clock.now()),
        )
    )
    for resource_id, during in held:
        busy[resource_id].append((during.lower, during.upper))
    closed = [(b.during.lower, b.during.upper) for b in blackouts_between(session, location_id, start, end)]
    result = []
    for column in columns:
        free = slots.subtract(opened[column.id][1], busy[column.id] + closed, min_free_min)
        result.append({"resource_id": column.id, "free": [{"starts_at": s, "ends_at": e} for s, e in free]})
    return {"location_id": location_id, "time_zone": zone.key, "from": start, "to": end, "resources": result}


# --- internal: what programs needs to gate and read a session ----------------------------------------------


def authorize_reach(session: Db, principal: Principal, key: str, booking_id: UUID) -> Booking:
    """Service gate for an action on a booking owned by another context's use case (enrolment, attendance):
    location containment, `own` reach against the booking's resources, and the type's staff grants (portal and
    system callers are exempt). Returns the booking."""
    booking = get_booking(session, booking_id)
    everywhere = principal.kind == "system" or principal.location_ids is None
    if not (everywhere or booking.location_id in principal.location_ids):
        raise NotFound()
    _authorize(
        session, principal, key, booking.location_id, _resource_ids(session, booking), booking.reservation_type_id
    )
    return booking


def client_bookings_starting(
    session: Db, *, client_id: UUID, location_id: UUID, start: datetime, end: datetime
) -> list[UUID]:
    """Internal (access, owner question 22): the client's confirmed court bookings and rentals at the location
    starting from `start` to `end`, which a check-in marks as arrived."""
    return list(session.scalars(select(Booking.id).where(
        Booking.client_id == client_id, Booking.location_id == location_id, Booking.status == "confirmed",
        Booking.kind.in_(("session", "rental")), Booking.starts_at >= start, Booking.starts_at <= end,
    ).order_by(Booking.starts_at)))  # fmt: skip


# --- series merge (SCH-21) ---------------------------------------------------------------------------------


def merge_series(session: Db, principal: Principal, booking_id: UUID, data: dict) -> dict:
    """Join another booking, or the whole series it belongs to, into this booking's series, so the two are
    mass-edited, cancelled and billed as one linked set. Times and holds do not change. Same location, kind and
    client only; this booking gets a series of its own first when it has none. The other series' passes move
    with their occurrences (renumbered after this series' passes) and the emptied series row goes."""
    number = data["booking_number"]
    other_id = session.scalar(select(Booking.id).where(Booking.booking_number == number))
    # Every lock first, in one order (series ids, then booking ids), so opposite merges cannot deadlock.
    pair = [booking_id] if other_id is None else sorted({booking_id, other_id})
    seen = dict(session.execute(select(Booking.id, Booking.booking_series_id).where(Booking.id.in_(pair))).all())
    series_ids = sorted({sid for sid in seen.values() if sid})
    if series_ids:
        stmt = select(BookingSeries.id).where(BookingSeries.id.in_(series_ids)).order_by(BookingSeries.id)
        session.execute(stmt.with_for_update())
    rows = select(Booking.id).where(Booking.id.in_(pair) | Booking.booking_series_id.in_(series_ids))
    session.execute(rows.order_by(Booking.id).with_for_update())
    booking = _own(session, principal, booking_id, UPDATE_SERIES)
    other = session.get(Booking, other_id) if other_id is not None else None
    if other is None or not (
        principal.kind == "system" or principal.location_ids is None or other.location_id in principal.location_ids
    ):
        raise ValidationFailed("No booking has that number.", pointer="/booking_number")
    _authorize(
        session, principal, UPDATE_SERIES, other.location_id, _resource_ids(session, other), other.reservation_type_id
    )
    if other.id == booking.id or (booking.booking_series_id and other.booking_series_id == booking.booking_series_id):
        raise Conflict("These bookings are already linked.", code="already-linked")
    if (other.location_id, other.kind, other.client_id) != (booking.location_id, booking.kind, booking.client_id):
        raise Conflict("Only bookings of the same location, kind and client can be linked.", code="merge-mismatch")
    if booking.kind == "block" or "cancelled" in (booking.status, other.status):
        raise Conflict("Only live reservations can be linked.", code="invalid-state-transition")
    if {booking.id: booking.booking_series_id, other.id: other.booking_series_id} != seen:
        raise Conflict("The bookings changed while linking; try again.", code="invalid-state-transition")
    series = {sid for sid in (booking.booking_series_id, other.booking_series_id) if sid}
    busy = select(BookingSeriesRun.id).where(
        BookingSeriesRun.booking_series_id.in_(series), BookingSeriesRun.status.in_(("pending", "running"))
    )
    if series and session.scalar(busy.limit(1)):
        raise Conflict("A series change is still running; link the bookings once it finishes.",
                       code="series-run-in-progress")  # fmt: skip
    target = (
        session.get(BookingSeries, booking.booking_series_id, with_for_update=True)
        if booking.booking_series_id
        else None
    )
    if target is None:
        target = BookingSeries(
            location_id=booking.location_id, kind=booking.kind, label=booking.title or None,
            created_by_staff_user_id=principal.staff_user_id if principal.kind == "staff" else None,
            occurrence_count=1,
        )  # fmt: skip
        session.add(target)
        session.flush()
        booking.booking_series_id, booking.version = target.id, booking.version + 1
        audit.record(session, UPDATE_SERIES, booking, location_id=booking.location_id,
                     changes={"booking_series_id": [None, str(target.id)]})  # fmt: skip
    source_id = other.booking_series_id
    if source_id is None:
        moved_rows = [other]
    else:
        stmt = select(Booking).where(Booking.booking_series_id == source_id).order_by(Booking.id).with_for_update()
        moved_rows = list(session.scalars(stmt))
        offset = session.scalar(
            select(func.coalesce(func.max(BookingSeriesRule.sequence), 0)).where(
                BookingSeriesRule.booking_series_id == target.id
            )
        )
        rules = BookingSeriesRule.__table__
        # Two steps so the unique (series, sequence) never sees a transient duplicate.
        session.execute(rules.update().where(rules.c.booking_series_id == source_id).values(sequence=-rules.c.sequence))
        session.execute(
            rules.update().where(rules.c.booking_series_id == source_id)
            .values(booking_series_id=target.id, sequence=offset - rules.c.sequence)
        )  # fmt: skip
        session.execute(
            BookingSeriesRun.__table__.update().where(BookingSeriesRun.booking_series_id == source_id)
            .values(booking_series_id=target.id)
        )  # fmt: skip
    moved = [row.id for row in moved_rows]
    live = sum(row.status != "cancelled" for row in moved_rows)
    for row in moved_rows:
        changes = {"booking_series_id": [str(row.booking_series_id) if row.booking_series_id else None, str(target.id)]}
        row.booking_series_id, row.version = target.id, row.version + 1
        audit.record(session, UPDATE_SERIES, row, location_id=row.location_id, changes=changes)
    session.flush()
    _count(session, target.id, live)
    if source_id is not None:
        source = session.get(BookingSeries, source_id)
        audit.record(
            session, UPDATE_SERIES, source, location_id=source.location_id, changes={"merged_into": str(target.id)}
        )
        session.delete(source)
    audit.record(
        session, UPDATE_SERIES, target, location_id=target.location_id,
        changes={"merged_booking_numbers": [number], "merged_count": len(moved)},
    )  # fmt: skip
    events.publish(
        session, ev.SeriesMerged(booking_series_id=target.id, location_id=target.location_id, merged_booking_count=len(moved)),
        target.id,
    )  # fmt: skip
    session.flush()
    session.expire_all()
    return get_series(session, principal, target.id)
