"""rentals service (build module 3): rental types and rates, quoting, rental bookings and their charges,
cancellation settlement, online booking with a checkout hold, and prepaid rental plans.

Rentals never writes holds: occurrences are made by scheduling's internal `template_for` + `book` (or
`create_booking` for one portal checkout) with source ('rentals', 'rental_booking', id). The hook registered in
scheduling.service.HOOKS writes the rental_booking row inside each occurrence's savepoint, so occurrences the
worker generates (series above 50) and extension passes get one too. Money goes through billing's internal
functions only: post_charge (idempotent by source), reverse, create_invoice_for_charges, attach_charges and
take_payment.
"""

import base64
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session as Db

from app.core import audit, clock, dates, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, DomainError, NotFound, PermissionDenied, ValidationFailed
from app.core.ids import new_id
from app.core.jobs import tenant_actor
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, memberships, platform, resources, scheduling
from app.modules.rentals import events as ev
from app.modules.rentals.domain import pricing
from app.modules.rentals.models import (
    LockerLease,
    RentalBooking,
    RentalBookingCharge,
    RentalBookingChargeItem,
    RentalParty,
    RentalPlan,
    RentalPlanLedgerEntry,
    RentalPlanPurchase,
    RentalPlanShare,
    RentalPortalSetting,
    RentalRate,
    RentalRateRule,
    RentalRateTax,
    RentalType,
    RentalTypeRentalPlan,
    RentalTypeResource,
)

READ = "scheduling.booking.read"
CREATE, UPDATE, CANCEL, OVERRIDE_RATE = (
    f"rentals.booking.{verb}" for verb in ("create", "update", "cancel", "override_rate")
)
TYPES, PLANS, SELL, REMOVE = (
    "rentals.rental_type.manage",
    "rentals.rental_plan.manage",
    "rentals.rental_plan.sell",
    "rentals.rental_plan.remove",
)
PUBLISH = "rentals.public_listing.publish"
SHARE, LOCKER_RENT = "rentals.rental_plan.share", "rentals.locker_rental.manage"
PORTAL_SETTINGS = "rentals.portal_setting.manage"
OVERRIDE_MINOR = "rentals.booking.override_minor"
SOURCE = ("rentals", "rental_booking")
CONSTRAINT_CODES["uq_rental_type_name"] = "already-exists"
CONSTRAINT_CODES["uq_rental_rate_name"] = "already-exists"
CONSTRAINT_CODES["uq_rental_plan_name"] = "already-exists"
CONSTRAINT_CODES["uq_locker_lease_open"] = "locker-already-rented"
CONSTRAINT_CODES["uq_rental_plan_purchase_successor"] = "plan-already-renewed"
CONSTRAINT_CODES["uq_locker_lease_successor"] = "lease-already-renewed"


# --- shared helpers ----------------------------------------------------------------------------------------


def _zone(session: Db, location_id: UUID) -> ZoneInfo:
    return ZoneInfo(platform.service.location_time_zone(session, location_id))


def _location(session: Db, principal: Principal, location_id: UUID) -> UUID:
    try:
        return platform.service.get_location(session, principal, location_id).id
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None


def _scoped(session: Db, principal: Principal, model, row_id: UUID, key: str | None, *, lock: bool = False):
    """A location-owned row, gated: missing or outside the caller's locations is 404."""
    stmt = select(model).where(model.id == row_id)
    row = session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    if row is None:
        raise NotFound()
    _gate(principal, key, row.location_id)
    return row


def _gate(principal: Principal, key: str | None, location_id: UUID) -> None:
    """`key` None is an `authenticated` read: location containment only (outside it is 404)."""
    if key is not None:
        authorize(principal, key, location_id=location_id)
    elif (
        principal.kind != "system" and principal.location_ids is not None and location_id not in principal.location_ids
    ):
        raise NotFound()


def _apply(row, data: dict, fields) -> dict:
    """Set the given fields; return the audit diff of the ones that changed."""
    changes = {}
    for name in fields:
        if name in data and getattr(row, name) != data[name]:
            changes[name] = [_plain(getattr(row, name)), _plain(data[name])]
            setattr(row, name, data[name])
    return changes


def _plain(value):
    return str(value) if isinstance(value, UUID | Decimal | date) else value


def _columns(row) -> dict:
    return {c.key: getattr(row, c.key) for c in type(row).__table__.columns if c.key != "tenant_id"}


# --- rental types ------------------------------------------------------------------------------------------

_TYPE_FIELDS = (
    "name", "revenue_category_id", "color", "sort_order", "buffer_before_min", "buffer_after_min", "access",
    "online_rental_rate_id", "eligibility", "online_payment_mode", "min_lead_min", "default_length_min",
    "min_length_min", "max_length_min", "slot_granularity_min", "online_description", "deposit_pct",
    "cancel_cutoff_hours", "late_cancel_fee_pct", "is_active",
)  # fmt: skip


def _type_view(session: Db, row: RentalType) -> dict:
    resource_ids = session.scalars(
        select(RentalTypeResource.resource_id).where(RentalTypeResource.rental_type_id == row.id)
    ).all()
    plan_ids = session.scalars(
        select(RentalTypeRentalPlan.rental_plan_id).where(RentalTypeRentalPlan.rental_type_id == row.id)
    ).all()
    return _columns(row) | {"resource_ids": list(resource_ids), "rental_plan_ids": list(plan_ids)}


def list_types(session: Db, principal: Principal, query: ListQuery) -> dict:
    page = paginate(
        session, scope_query(select(RentalType), principal, RentalType.location_id), query, id_column=RentalType.id,
        sort_fields={"name": RentalType.name, "sort_order": RentalType.sort_order}, default_sort="sort_order,name",
        filter_fields={"location_id": RentalType.location_id, "is_active": RentalType.is_active, "access": RentalType.access},
        search=(RentalType.name,),
    )  # fmt: skip
    return page | {"data": [_type_view(session, row) for row in page["data"]]}


def get_type(session: Db, principal: Principal, type_id: UUID) -> dict:
    return _type_view(session, _scoped(session, principal, RentalType, type_id, None))


def _set_type_links(session: Db, row: RentalType, data: dict) -> dict:
    changes = {}
    if data.get("resource_ids") is not None:
        ids = list(dict.fromkeys(data["resource_ids"]))
        found = {r.id: r for r in resources.service.get_many(session, ids)}
        for index, resource_id in enumerate(ids):
            resource = found.get(resource_id)
            if resource is None or resource.location_id != row.location_id:
                raise ValidationFailed("Unknown resource at this location.", pointer=f"/resource_ids/{index}")
        session.execute(delete(RentalTypeResource).where(RentalTypeResource.rental_type_id == row.id))
        session.add_all(RentalTypeResource(rental_type_id=row.id, resource_id=r) for r in ids)
        changes["resource_ids"] = [None, len(ids)]
    if data.get("rental_plan_ids") is not None:
        ids = list(dict.fromkeys(data["rental_plan_ids"]))
        for index, plan_id in enumerate(ids):
            plan = session.get(RentalPlan, plan_id)
            if plan is None or plan.location_id != row.location_id:
                raise ValidationFailed("Unknown rental plan at this location.", pointer=f"/rental_plan_ids/{index}")
        session.execute(delete(RentalTypeRentalPlan).where(RentalTypeRentalPlan.rental_type_id == row.id))
        session.add_all(RentalTypeRentalPlan(rental_type_id=row.id, rental_plan_id=p) for p in ids)
        changes["rental_plan_ids"] = [None, len(ids)]
    session.flush()
    return changes


def _check_type(session: Db, row: RentalType) -> None:
    if row.online_rental_rate_id is not None:
        rate = session.get(RentalRate, row.online_rental_rate_id)
        if rate is None or rate.rental_type_id != row.id or not rate.is_active:
            raise ValidationFailed(
                "The online rate must be an active rate of this type.", pointer="/online_rental_rate_id"
            )
    if row.access == "self_service":
        if row.online_rental_rate_id is None:
            raise ValidationFailed("Online booking needs an online rate.", pointer="/online_rental_rate_id")
        if not session.scalar(
            select(RentalTypeResource.id).where(RentalTypeResource.rental_type_id == row.id).limit(1)
        ):
            raise ValidationFailed("Online booking needs at least one resource.", pointer="/resource_ids")


def create_type(session: Db, principal: Principal, data: dict) -> dict:
    """RNT-01. A new type is staff-only until it has a rate: `access = self_service` is refused on create."""
    location_id = _location(session, principal, data["location_id"])
    authorize(principal, TYPES, location_id=location_id)
    if data.get("access") == "self_service" or data.get("online_rental_rate_id"):
        raise ValidationFailed("Add a rate before opening the type for online booking.", pointer="/access")
    row = RentalType(location_id=location_id)
    _apply(row, {k: v for k, v in data.items() if v is not None}, _TYPE_FIELDS)
    session.add(row)
    session.flush()
    _set_type_links(session, row, data)
    audit.record(session, TYPES, row, location_id=location_id, changes={"name": [None, row.name]})
    return _type_view(session, row)


def update_type(session: Db, principal: Principal, type_id: UUID, data: dict) -> dict:
    row = _scoped(session, principal, RentalType, type_id, TYPES, lock=True)
    changes = _apply(row, data, _TYPE_FIELDS)
    session.flush()
    changes |= _set_type_links(session, row, data)
    _check_type(session, row)
    if changes:
        audit.record(session, TYPES, row, location_id=row.location_id, changes=changes)
    return _type_view(session, row)


def _type_for(
    session: Db, type_id: UUID, location_id: UUID | None = None, pointer: str = "/rental_type_id"
) -> RentalType:
    row = session.get(RentalType, type_id)
    if row is None or not row.is_active or (location_id is not None and row.location_id != location_id):
        raise ValidationFailed("Unknown or inactive rental type at this location.", pointer=pointer)
    return row


def _type_resources(session: Db, type_id: UUID) -> set[UUID]:
    return set(
        session.scalars(select(RentalTypeResource.resource_id).where(RentalTypeResource.rental_type_id == type_id))
    )


# --- rates -------------------------------------------------------------------------------------------------

_RATE_FIELDS = (
    "name", "internal_note", "amount_minor", "member_amount_minor", "basis", "multi_resource_mode", "line_grouping",
    "sort_order", "is_active",
)  # fmt: skip
_RULE_FIELDS = (
    "kind", "name", "sort_order", "start_time", "end_time", "starts_on", "ends_on", "weekdays", "membership_type_id",
    "amount_minor", "discount_pct", "discount_minor",
)  # fmt: skip


def _rate_view(session: Db, row: RentalRate) -> dict:
    rules = session.scalars(
        select(RentalRateRule)
        .where(RentalRateRule.rental_rate_id == row.id)
        .order_by(RentalRateRule.sort_order, RentalRateRule.id)
    ).all()
    taxes = session.scalars(select(RentalRateTax.tax_id).where(RentalRateTax.rental_rate_id == row.id)).all()
    return _columns(row) | {"rules": [_columns(r) for r in rules], "tax_ids": list(taxes)}


def _rate(
    session: Db, principal: Principal, rate_id: UUID, key: str | None, *, lock: bool = False
) -> tuple[RentalRate, RentalType]:
    stmt = select(RentalRate).where(RentalRate.id == rate_id)
    rate = session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    if rate is None:
        raise NotFound()
    rtype = session.get(RentalType, rate.rental_type_id)
    _gate(principal, key, rtype.location_id)
    return rate, rtype


def list_rates(session: Db, principal: Principal, type_id: UUID, query: ListQuery) -> dict:
    rtype = _scoped(session, principal, RentalType, type_id, None)
    page = paginate(
        session, select(RentalRate).where(RentalRate.rental_type_id == rtype.id), query, id_column=RentalRate.id,
        sort_fields={"sort_order": RentalRate.sort_order, "name": RentalRate.name}, default_sort="sort_order,name",
        filter_fields={"is_active": RentalRate.is_active, "basis": RentalRate.basis},
    )  # fmt: skip
    return page | {"data": [_rate_view(session, row) for row in page["data"]]}


def get_rate(session: Db, principal: Principal, rate_id: UUID) -> dict:
    return _rate_view(session, _rate(session, principal, rate_id, None)[0])


def _set_rate_parts(session: Db, rate: RentalRate, data: dict) -> dict:
    changes = {}
    if data.get("rules") is not None:
        session.execute(delete(RentalRateRule).where(RentalRateRule.rental_rate_id == rate.id))
        for index, rule in enumerate(data["rules"]):
            if rule["kind"] == "rate" and rule.get("amount_minor") is None:
                raise ValidationFailed("A rate rule sets an amount.", pointer=f"/rules/{index}/amount_minor")
            if rule["kind"] == "discount" and (rule.get("discount_pct") is None) == (
                rule.get("discount_minor") is None
            ):
                raise ValidationFailed(
                    "A discount is a percentage or an amount.", pointer=f"/rules/{index}/discount_pct"
                )
            if (rule.get("start_time") is None) != (rule.get("end_time") is None):
                raise ValidationFailed("A time band has a start and an end.", pointer=f"/rules/{index}/end_time")
            session.add(
                RentalRateRule(
                    rental_rate_id=rate.id, **{k: rule.get(k) for k in _RULE_FIELDS} | {"name": rule.get("name") or ""}
                )
            )
        changes["rules"] = [None, len(data["rules"])]
    if data.get("tax_ids") is not None:
        session.execute(delete(RentalRateTax).where(RentalRateTax.rental_rate_id == rate.id))
        session.add_all(RentalRateTax(rental_rate_id=rate.id, tax_id=t) for t in dict.fromkeys(data["tax_ids"]))
        changes["tax_ids"] = [None, [str(t) for t in data["tax_ids"]]]
    session.flush()
    return changes


def create_rate(session: Db, principal: Principal, type_id: UUID, data: dict) -> dict:
    """RNT-02. Rules and taxes come with the rate; `24:00` closes a band at midnight."""
    rtype = _scoped(session, principal, RentalType, type_id, TYPES)
    for name in ("name", "amount_minor", "basis"):
        if data.get(name) is None:
            raise ValidationFailed(f"{name} is required.", pointer=f"/{name}")
    rate = RentalRate(rental_type_id=rtype.id)
    _apply(rate, {k: v for k, v in data.items() if v is not None}, _RATE_FIELDS)
    session.add(rate)
    session.flush()
    _set_rate_parts(session, rate, data)
    audit.record(
        session, TYPES, rate, location_id=rtype.location_id,
        changes={"name": [None, rate.name], "amount_minor": [None, rate.amount_minor]},
    )  # fmt: skip
    return _rate_view(session, rate)


def update_rate(session: Db, principal: Principal, rate_id: UUID, data: dict) -> dict:
    """Changes apply to future quotes only: posted charges keep their snapshot."""
    rate, rtype = _rate(session, principal, rate_id, TYPES, lock=True)
    changes = _apply(rate, data, _RATE_FIELDS)
    session.flush()
    changes |= _set_rate_parts(session, rate, data)
    if not rate.is_active and rtype.online_rental_rate_id == rate.id:
        raise ValidationFailed("This is the type's online rate: choose another one first.", pointer="/is_active")
    if changes:
        audit.record(session, TYPES, rate, location_id=rtype.location_id, changes=changes)
    return _rate_view(session, rate)


# --- pricing glue ------------------------------------------------------------------------------------------


def _wall(value: str | None) -> time | None:
    if value is None or value.startswith("24"):
        return None
    hours, minutes = value[:5].split(":")
    return time(int(hours), int(minutes))


def _rate_input(session: Db, rate: RentalRate) -> pricing.Rate:
    rules = session.scalars(select(RentalRateRule).where(RentalRateRule.rental_rate_id == rate.id)).all()
    return pricing.Rate(
        id=rate.id, name=rate.name, amount_minor=rate.amount_minor, basis=rate.basis,
        member_amount_minor=rate.member_amount_minor, multi_resource_mode=rate.multi_resource_mode,
        line_grouping=rate.line_grouping,
        rules=tuple(
            pricing.Rule(
                id=r.id, kind=r.kind, name=r.name, sort_order=r.sort_order,
                start_time=_wall(r.start_time) if r.start_time else None, end_time=_wall(r.end_time),
                starts_on=r.starts_on, ends_on=r.ends_on, weekdays=tuple(r.weekdays) if r.weekdays else None,
                membership_type_id=r.membership_type_id, amount_minor=r.amount_minor, discount_pct=r.discount_pct,
                discount_minor=r.discount_minor,
            )
            for r in rules
        ),
    )  # fmt: skip


class _Priced:
    """A charge decision priced: the lines, the taxes they will carry and what billing gets told."""

    def __init__(
        self, session: Db, rtype: RentalType, decision: dict, occurrences: list[pricing.Occurrence], on: date,
        client_id: UUID | None,
    ):  # fmt: skip
        custom = decision.get("custom_rate")
        if custom:
            self.rate = pricing.Rate(
                id=None, name=custom["description"], amount_minor=custom["unit_amount_minor"], basis=custom["basis"],
                multi_resource_mode="once",
            )  # fmt: skip
            selected = custom.get("tax_ids")
        else:
            if decision.get("rental_rate_id") is None:
                raise ValidationFailed("Choose a rate or key a custom price.", pointer="/charge/rental_rate_id")
            row = session.get(RentalRate, decision["rental_rate_id"])
            if row is None or row.rental_type_id != rtype.id or not row.is_active:
                raise ValidationFailed(
                    "The rate does not belong to this rental type.", pointer="/charge/rental_rate_id",
                    code="rate-not-applicable",
                )  # fmt: skip
            self.rate = _rate_input(session, row)
            selected = session.scalars(select(RentalRateTax.tax_id).where(RentalRateTax.rental_rate_id == row.id)).all()
        if decision.get("tax_ids") is not None:
            selected = decision["tax_ids"]
        self.lines = _price_for(session, self.rate, occurrences, client_id, decision.get("line_grouping"))
        try:
            pricing.apply_discount(self.lines, decision.get("discount_minor") or 0)
        except ValueError:
            raise ValidationFailed("The discount exceeds the total.", pointer="/charge/discount_minor") from None
        category = billing.service.category_taxes(session, rtype.revenue_category_id, on)
        chosen = set(selected or ())
        self.exclude = [tax_id for tax_id, _ in category if tax_id not in chosen]
        self.tax_rates = [rate for tax_id, rate in category if tax_id in chosen]

    def quote(self, currency: str, deposit_pct: Decimal | None = None) -> dict:
        lines = [
            {
                "description": line.description, "rental_rate_id": line.rental_rate_id, "basis": line.basis,
                "quantity": line.quantity, "unit_amount_minor": line.unit_amount_minor,
                "discount_minor": line.discount_minor, "amount_minor": line.amount_minor,
                "tax_minor": pricing.tax_of(line.amount_minor, self.tax_rates), "resource_id": line.resource_id,
                "occurrence_index": line.occurrence_index, "applied_rule_id": line.applied_rule_id,
                "is_member_price": line.is_member_price,
            }
            for line in self.lines
        ]  # fmt: skip
        subtotal = sum(line["amount_minor"] for line in lines)
        tax = sum(line["tax_minor"] for line in lines)
        return {
            "lines": lines, "subtotal_minor": subtotal, "discount_minor": sum(line["discount_minor"] for line in lines),
            "tax_minor": tax, "total_minor": subtotal + tax, "deposit_minor": pricing.deposit_of(subtotal + tax, deposit_pct),
            "currency": currency,
        }  # fmt: skip


def _member_pricing(session: Db, client_id: UUID | None, on: date) -> tuple[bool, frozenset]:
    """Whether the payer pays member prices on a local date, and under which membership type: memberships'
    `member_on`, the date-aware form of the owner-decision-13 definition (an active contract, owned or shared, at
    any location, overdue or used up; never suspended or frozen on that date). It covers a past date a since-ended
    contract covered and an auto-renewing contract past its end date."""
    if client_id is None:
        return False, frozenset()
    found = memberships.service.member_on(session, client_id, on)
    return (True, frozenset({found["membership_type_id"]})) if found else (False, frozenset())


def _price_for(
    session: Db,
    rate: pricing.Rate,
    occurrences: list[pricing.Occurrence],
    client_id: UUID | None,
    grouping: str | None = None,
    status: dict[date, tuple[bool, frozenset]] | None = None,
) -> list[pricing.Line]:
    """The rental price for quote and charge alike: each occurrence at the payer's member status on its own
    local date (a recurring rental that outlives a membership pays the guest price after it). `flat` is one
    charge for the whole request, priced on the first date. `status` caches the payer's member status by date
    across calls in one request (open times price every slot of a day)."""
    groups: dict[tuple, list[pricing.Occurrence]] = {}
    status = {} if status is None else status
    first = min(occurrences, key=lambda o: o.index).starts_at.date()
    for occurrence in occurrences:
        on = first if rate.basis == "flat" else occurrence.starts_at.date()
        if on not in status:
            status[on] = _member_pricing(session, client_id, on)
        groups.setdefault(status[on], []).append(occurrence)
    lines = [
        line
        for (is_member, types), group in groups.items()
        for line in pricing.price(rate, group, is_member=is_member, member_types=types, grouping=grouping)
    ]
    return sorted(
        lines, key=lambda line: (line.occurrence_index or 0, str(line.resource_id or ""), -line.unit_amount_minor)
    )


def _currency(session: Db) -> str:
    return platform.service.get_tenant(session).currency


def _priced_resources(type_resources: set[UUID], resource_ids: list[UUID]) -> tuple[UUID, ...]:
    """What a rate counts: the type's own resources among the booked ones (linked lights, say, are not)."""
    chosen = [r for r in resource_ids if not type_resources or r in type_resources]
    return tuple(chosen or resource_ids[:1])


# --- rental bookings: hook, views ---------------------------------------------------------------------------


def _on_booking(session: Db, booking, data: dict) -> None:
    """scheduling.service.HOOKS['rentals']: the rental row of a new occurrence, in its savepoint."""
    row = RentalBooking(
        id=booking.source_id, location_id=booking.location_id, booking_id=booking.id,
        rental_type_id=UUID(data["rental_type_id"]), charge_state=data.get("charge_state") or "unbilled",
        booked_via=data["booked_via"], starts_at=booking.starts_at, ends_at=booking.ends_at,
        minor_override_reason=data.get("minor_override_reason"),
    )  # fmt: skip
    session.add(row)
    session.flush()
    session.add_all(
        RentalParty(rental_booking_id=row.id, client_id=UUID(p["client_id"]), is_charged=p["is_charged"])
        for p in data.get("parties") or ()
    )
    session.flush()
    events.publish(
        session, ev.RentalBooked(rental_booking_id=row.id, booking_id=booking.id, location_id=row.location_id), row.id
    )


scheduling.service.HOOKS["rentals"] = _on_booking


def _views(session: Db, rows: list[RentalBooking]) -> list[dict]:
    if not rows:
        return []
    ids = [row.id for row in rows]
    bookings = scheduling.service.booking_views(session, [row.booking_id for row in rows])
    parties = defaultdict(list)
    for party in session.scalars(select(RentalParty).where(RentalParty.rental_booking_id.in_(ids))):
        parties[party.rental_booking_id].append({"client_id": party.client_id, "is_charged": party.is_charged})
    amounts, charges = defaultdict(int), defaultdict(list)
    for booking_id, amount, charge_id in session.execute(
        select(
            RentalBookingChargeItem.rental_booking_id,
            RentalBookingChargeItem.amount_minor,
            RentalBookingCharge.charge_id,
        )
        .join(RentalBookingCharge, RentalBookingCharge.id == RentalBookingChargeItem.rental_booking_charge_id)
        .where(RentalBookingChargeItem.rental_booking_id.in_(ids), RentalBookingChargeItem.reversed_at.is_(None))
    ):
        amounts[booking_id] += amount
        charges[booking_id].append(charge_id)
    states = billing.service.charge_states(session, [c for cs in charges.values() for c in cs])
    views = []
    for row in rows:
        booking = bookings[row.booking_id]
        invoices = list(dict.fromkeys(states[c]["invoice_id"] for c in charges[row.id] if states[c]["invoice_id"]))
        views.append(
            {
                "id": row.id, "location_id": row.location_id, "booking_id": row.booking_id,
                "booking_number": booking["booking_number"], "booking_series_id": booking["booking_series_id"],
                "rental_type_id": row.rental_type_id, "client_id": booking["client_id"], "parties": parties[row.id],
                "resources": booking["resources"], "starts_at": booking["starts_at"], "ends_at": booking["ends_at"],
                "status": booking["status"], "expires_at": booking["expires_at"], "charge_state": row.charge_state,
                "booked_via": row.booked_via, "cancelled_at": row.cancelled_at,
                "amount_minor": amounts[row.id] if row.id in amounts else None, "charge_ids": list(dict.fromkeys(charges[row.id])),
                "invoice_ids": invoices, "is_on_public_schedule": row.is_on_public_schedule, "title": booking["title"],
                "version": booking["version"], "minor_override_reason": row.minor_override_reason,
            }
        )  # fmt: skip
    return views


def _view(session: Db, row: RentalBooking) -> dict:
    return _views(session, [row])[0]


def list_rentals(session: Db, principal: Principal, query: ListQuery) -> dict:
    """RNT-03/RNT-08. Booking-side filters (client_id, status, booking_series_id, resource_id) are matched in
    scheduling; the rest on the rental row. `charge_state=unbilled` is the unbilled-occurrence queue."""
    authorize(principal, READ)
    filters = dict(query.filters)
    booking_side = {
        k: filters.pop(k) for k in ("client_id", "status", "booking_series_id", "resource_id") if k in filters
    }
    stmt = scope_query(select(RentalBooking), principal, RentalBooking.location_id)
    if booking_side:
        try:
            ids = scheduling.service.booking_ids(
                client_id=UUID(booking_side["client_id"]) if "client_id" in booking_side else None,
                status=booking_side.get("status"),
                series_id=UUID(booking_side["booking_series_id"]) if "booking_series_id" in booking_side else None,
                resource_id=UUID(booking_side["resource_id"]) if "resource_id" in booking_side else None,
            )
        except ValueError:
            raise ValidationFailed("Invalid id filter.", pointer="/client_id") from None
        stmt = stmt.where(RentalBooking.booking_id.in_(ids))
    query = ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters)
    page = paginate(
        session, stmt, query, id_column=RentalBooking.id, sort_fields={"starts_at": RentalBooking.starts_at},
        default_sort="starts_at",
        filter_fields={
            "location_id": RentalBooking.location_id, "rental_type_id": RentalBooking.rental_type_id,
            "charge_state": RentalBooking.charge_state, "starts_at": RentalBooking.starts_at,
            "booked_via": RentalBooking.booked_via,
        },
    )  # fmt: skip
    return page | {"data": _views(session, page["data"])}


def _rental(session: Db, principal: Principal, rental_id: UUID, key: str, *, lock: bool = False) -> RentalBooking:
    return _scoped(session, principal, RentalBooking, rental_id, key, lock=lock)


def get_rental(session: Db, principal: Principal, rental_id: UUID) -> dict:
    return _view(session, _rental(session, principal, rental_id, READ))


# --- charges: posting, routing, plans ----------------------------------------------------------------------


def _occurrence_inputs(session: Db, rows: list[RentalBooking], type_resources: set[UUID]) -> list[pricing.Occurrence]:
    bookings = scheduling.service.booking_views(session, [row.booking_id for row in rows])
    zone = _zone(session, rows[0].location_id)
    return [
        pricing.Occurrence(
            index, row.starts_at.astimezone(zone), row.ends_at.astimezone(zone),
            _priced_resources(type_resources, [r["resource_id"] for r in bookings[row.booking_id]["resources"]]),
        )
        for index, row in enumerate(rows)
    ]  # fmt: skip


def _route(session: Db, decision: dict, posted: list[tuple[RentalBookingCharge, date]], client_id: UUID) -> list[UUID]:
    """Group posted lines into invoices (RNT-04 routing). `cart` leaves them uninvoiced for checkout."""
    routing = decision.get("invoice_routing") or "new_single"
    ids = [rbc.charge_id for rbc, _ in posted]
    if routing == "cart" or not ids:
        return []
    if routing == "existing_open":
        if not decision.get("existing_invoice_id"):
            raise ValidationFailed("Choose the open invoice.", pointer="/charge/existing_invoice_id")
        return [billing.service.attach_charges(session, decision["existing_invoice_id"], ids).id]
    if routing == "new_per_line":
        groups = [[charge_id] for charge_id in ids]
    elif routing == "date_based":
        period = decision.get("routing_period")
        if period is None:
            raise ValidationFailed("Date-based routing needs a period.", pointer="/charge/routing_period")
        by_period = defaultdict(list)
        for rbc, day in posted:
            key = day.isocalendar()[:2] if period == "week" else (day.year, day.month)
            by_period[key].append(rbc.charge_id)
        groups = [by_period[key] for key in sorted(by_period)]
    else:
        groups = [ids]
    return [
        billing.service.create_invoice_for_charges(session, group, bill_to_client_id=client_id).id for group in groups
    ]


def _post_lines(
    session: Db, priced: _Priced, rows: list[RentalBooking], rtype: RentalType, client_id: UUID, decision: dict
) -> list[tuple[RentalBookingCharge, date]]:
    """One rental_booking_charge and one billing charge per line, with the occurrence shares as items."""
    zone = _zone(session, rtype.location_id)
    routing = decision.get("invoice_routing") or "new_single"
    posted = []
    for line in priced.lines:
        first = rows[line.items[0][0]] if line.items else rows[0]
        day = first.starts_at.astimezone(zone).date()
        rbc = RentalBookingCharge(
            id=new_id(), location_id=rtype.location_id, client_id=client_id, rental_rate_id=line.rental_rate_id,
            description=line.description, basis=line.basis, quantity=line.quantity,
            unit_amount_minor=line.unit_amount_minor, discount_minor=line.discount_minor, amount_minor=line.amount_minor,
            revenue_on=decision.get("revenue_on") or day, invoice_routing=routing,
            routing_period=decision.get("routing_period") if routing == "date_based" else None,
        )  # fmt: skip
        charge = billing.service.post_charge(
            session, client_id=client_id, location_id=rtype.location_id, description=f"{rtype.name}: {line.description}",
            unit_price_minor=line.unit_amount_minor, quantity=line.quantity, discount_minor=line.discount_minor,
            source_context="rentals", source_type="rental_booking_charge", source_id=rbc.id,
            revenue_category_id=rtype.revenue_category_id, revenue_on=rbc.revenue_on, exclude_tax_ids=priced.exclude,
            service_starts_on=day,
        )  # fmt: skip
        rbc.charge_id = charge.id
        session.add(rbc)
        session.flush()
        session.add_all(
            RentalBookingChargeItem(
                rental_booking_charge_id=rbc.id,
                rental_booking_id=rows[index].id,
                resource_id=resource,
                amount_minor=share,
            )
            for index, resource, share in line.items
        )
        posted.append((rbc, day))
    for row in rows:
        row.charge_state = "billed"
    session.flush()
    return posted


def _plan_need(rows: list[RentalBooking], model: str) -> Decimal:
    if model == "per_occurrence":
        return Decimal(len(rows))
    return sum((Decimal(int((r.ends_at - r.starts_at).total_seconds())) / 3600 for r in rows), Decimal(0)).quantize(
        pricing.CENT
    )


def _purchase_for(session: Db, purchase_id: UUID, client_id: UUID, rtype: RentalType, rows: list[RentalBooking]):
    purchase = session.execute(
        select(RentalPlanPurchase).where(RentalPlanPurchase.id == purchase_id).with_for_update()
    ).scalar_one_or_none()
    pointer = "/charge/rental_plan_purchase_id"
    plan = purchase and session.get(RentalPlan, purchase.rental_plan_id)
    if (
        purchase is None
        or purchase.location_id != rtype.location_id
        or (
            purchase.client_id != client_id
            and not (plan.is_shareable and client_id in _shared_with(session, purchase.id))
            and not _guardian_spends_players_plan(session, purchase.client_id, client_id, rows, rtype)
        )  # a plan made unshareable later ignores its old share rows
    ):
        raise ValidationFailed("Unknown plan for this client.", pointer=pointer)
    # hook: share-holder waiver gate. claude/owner-decisions-1 gates share-holders on the plan's waiver; once both
    # branches merge, a holder spending someone else's plan (a share or a guardian) must pass it here too.
    allowed = set(
        session.scalars(
            select(RentalTypeRentalPlan.rental_plan_id).where(RentalTypeRentalPlan.rental_type_id == rtype.id)
        )
    )
    if (plan.id not in allowed) if allowed else (plan.rental_type_id != rtype.id):
        raise ValidationFailed(
            "This plan does not cover this rental type.", pointer=pointer, code="plan-not-applicable"
        )
    zone = _zone(session, rtype.location_id)
    days = [r.starts_at.astimezone(zone).date() for r in rows]
    if (
        purchase.status not in ("pending", "active")
        or min(days) < purchase.starts_on
        or (purchase.expires_on is not None and max(days) > purchase.expires_on)
    ):
        raise Conflict("The plan is not valid on these dates.", code="plan-not-valid")
    return purchase


def _guardian_spends_players_plan(
    session: Db, owner: UUID, holder: UUID, rows: list[RentalBooking], rtype: RentalType
) -> bool:
    """A plan bought in a child's name: the child never holds a rental (the minors rule), so a guardian holding the
    rental may spend it, but only while the owner is a minor (on the first date; an unknown birth date is not, so
    this fails closed) and only on occurrences the child plays, every one of them."""
    first = min(r.starts_at for r in rows).astimezone(_zone(session, rtype.location_id)).date()
    if not _is_minor(session, owner, first) or holder not in clients.households.guardian_ids(session, owner):
        return False
    played = select(RentalParty.rental_booking_id).where(
        RentalParty.rental_booking_id.in_([r.id for r in rows]), RentalParty.client_id == owner
    )
    return set(session.scalars(played)) == {r.id for r in rows}


def _cover(session: Db, purchase_id: UUID, client_id: UUID, rtype: RentalType, rows: list[RentalBooking]) -> Decimal:
    """Plan coverage (RNT-09): all or nothing. The balance must cover every occurrence (full-coverage rule)."""
    purchase = _purchase_for(session, purchase_id, client_id, rtype, rows)
    need = _plan_need(rows, purchase.model)
    if purchase.balance is not None and purchase.balance < need:
        raise Conflict(
            "The plan balance does not cover the whole booking.", code="insufficient-plan-balance",
            balance=str(purchase.balance), required=str(need),
        )  # fmt: skip
    for row in rows:
        quantity = _plan_need([row], purchase.model)
        if purchase.balance is not None:
            purchase.balance -= quantity
        session.add(
            RentalPlanLedgerEntry(
                rental_plan_purchase_id=purchase.id,
                entry_type="debit",
                quantity=-quantity,
                balance_after=purchase.balance,
                rental_booking_id=row.id,
                used_by_client_id=client_id,
            )  # fmt: skip
        )
        row.charge_state = "plan_covered"
    session.flush()
    return need


def _decide(
    session: Db, rtype: RentalType, client_id: UUID, rows: list[RentalBooking], decision: dict
) -> tuple[dict | None, list[UUID]]:
    """Apply a charge decision to occurrences: bill, leave unbilled, no charge, or cover from a plan."""
    kind = decision["decision"]
    rows = sorted(rows, key=lambda r: r.starts_at)
    if kind in ("unbilled", "no_charge"):
        for row in rows:
            row.charge_state = kind
        session.flush()
        return None, []
    if kind == "plan":
        if not decision.get("rental_plan_purchase_id"):
            raise ValidationFailed("Choose the plan.", pointer="/charge/rental_plan_purchase_id")
        _cover(session, decision["rental_plan_purchase_id"], client_id, rtype, rows)
        return None, []
    priced = _price_rows(session, rtype, decision, rows, client_id)
    posted = _post_lines(session, priced, rows, rtype, client_id, decision)
    return priced.quote(_currency(session), rtype.deposit_pct), _route(session, decision, posted, client_id)


def _price_rows(session: Db, rtype: RentalType, decision: dict, rows: list[RentalBooking], client_id: UUID) -> _Priced:
    occurrences = _occurrence_inputs(session, rows, _type_resources(session, rtype.id))
    return _Priced(session, rtype, decision, occurrences, occurrences[0].starts_at.date(), client_id)


def _check_override(principal: Principal, decision: dict, location_id: UUID) -> None:
    if decision.get("custom_rate") or decision.get("discount_minor"):
        authorize(principal, OVERRIDE_RATE, location_id=location_id)


# --- staff commands: create, preview, bill selected, extend ----------------------------------------------


def _is_minor(session: Db, client_id: UUID, on: date, *, unknown_is_minor: bool = False) -> bool:
    """The one minor lookup for rentals: under the tenant's minor age (`platform.service.minor_age`, which Phase 13
    consolidates households' `age_of_majority` into) on the rental's local date. An unknown birth date counts as
    an adult at the desk (`clients.service.is_minor`, ADR 0002 section 5) but as a minor online
    (`unknown_is_minor`), where nobody is there to look."""
    client = clients.service.get(session, client_id)
    if client.birth_on is None:
        return unknown_is_minor
    return clients.service.is_minor(client, on, platform.service.minor_age(session))


def _check_minors(
    session: Db, holder: UUID, parties, on: date, pointer: str = "/parties", *, online: bool = False
) -> None:
    """The minors rule (pilot): a minor never holds a rental; a minor may play (an uncharged party) only on a
    rental held, and so paid, by one of their guardians (`clients.households.guardian_ids`: a guardianship
    relationship, never a delegate's acting rights). Online the holder needs a birth date on file."""
    if online and clients.service.get(session, holder).birth_on is None:
        raise ValidationFailed(
            "Add your birth date to your profile before booking a court online.",
            pointer="/client_id", code="birth-date-required",
        )  # fmt: skip
    if _is_minor(session, holder, on):
        raise ValidationFailed(
            "A child cannot hold a court booking. Book it in a parent's name and add the child as a player.",
            pointer="/client_id", code="minor-cannot-hold-rental",
        )  # fmt: skip
    for index, party in enumerate(parties):
        if _is_minor(session, party["client_id"], on, unknown_is_minor=online) and (
            party.get("is_charged") or holder not in clients.households.guardian_ids(session, party["client_id"])
        ):
            raise ValidationFailed(
                "A child can play only on a booking held and paid by their parent or guardian.",
                pointer=f"{pointer}/{index}", code="minor-needs-guardian",
            )  # fmt: skip


def _parties(session: Db, data: dict) -> list[dict]:
    seen, parties = {data["client_id"]}, []
    for index, party in enumerate(data.get("parties") or ()):
        if party["client_id"] in seen:
            continue
        clients.service.require_active(session, party["client_id"], pointer=f"/parties/{index}/client_id")
        seen.add(party["client_id"])
        parties.append({"client_id": str(party["client_id"]), "is_charged": party["is_charged"]})
    return parties


def _check_type_resources(session: Db, rental_type_id: UUID, resources: list[dict]) -> None:
    allowed = _type_resources(session, rental_type_id)
    for index, resource in enumerate(resources):
        if allowed and resource["resource_id"] not in allowed:
            raise ValidationFailed(
                "This resource is not offered for this rental type.", pointer=f"/resources/{index}/resource_id",
                code="resource-not-allowed",
            )  # fmt: skip


def _rental_template(session: Db, principal: Principal, data: dict) -> tuple[RentalType, dict]:
    location_id = _location(session, principal, data["location_id"])
    authorize(principal, CREATE, location_id=location_id)
    rtype = _type_for(session, data["rental_type_id"], location_id)
    _check_type_resources(session, rtype.id, data["resources"])
    if data.get("override_policy"):
        authorize(principal, scheduling.service.OVERRIDE, location_id=location_id)
    _check_override(principal, data["charge"], location_id)
    clients.service.require_active(session, data["client_id"])
    reason = data.get("minor_override_reason")
    if reason:
        authorize(principal, OVERRIDE_MINOR, location_id=location_id)
    else:
        on = data["starts_at"].astimezone(_zone(session, location_id)).date()
        _check_minors(session, data["client_id"], data.get("parties") or (), on)
    template = scheduling.service.template_for(
        session, location_id,
        {
            "kind": "rental", "resources": data["resources"], "title": data.get("title") or rtype.name,
            "notes": data.get("notes"),
            "buffer_before_min": rtype.buffer_before_min if data.get("buffer_before_min") is None else data["buffer_before_min"],
            "buffer_after_min": rtype.buffer_after_min if data.get("buffer_after_min") is None else data["buffer_after_min"],
            "override_policy": data.get("override_policy"),
        },
        principal.staff_user_id,
    )  # fmt: skip
    state = "no_charge" if data["charge"]["decision"] == "no_charge" else "unbilled"
    template["client_id"] = str(data["client_id"])
    template["source"] = {
        "context": "rentals", "type": "rental_booking",
        "data": {"rental_type_id": str(rtype.id), "booked_via": "staff", "charge_state": state, "parties": _parties(session, data),
                 "minor_override_reason": reason},
    }  # fmt: skip
    return rtype, template


def preview_rental(session: Db, principal: Principal, data: dict) -> dict:
    """Dry run of a create: each occurrence with what it would meet, and the quote of the bookable ones."""
    rtype, template = _rental_template(session, principal, data)
    result = scheduling.service.book(session, template, data, principal.staff_user_id, preview=True)
    quote = None
    if data["charge"]["decision"] == "bill":
        allowed, zone = _type_resources(session, rtype.id), _zone(session, rtype.location_id)
        resources = _priced_resources(allowed, [UUID(r) for r, _ in template["resources"]])
        occurrences = [
            pricing.Occurrence(
                o["index"], datetime.fromisoformat(o["starts_at"].replace("Z", "+00:00")).astimezone(zone),
                datetime.fromisoformat(o["ends_at"].replace("Z", "+00:00")).astimezone(zone), resources,
            )
            for o in result["occurrences"]
            if o["status"] == "ok"
        ]  # fmt: skip
        if occurrences:
            quote = _Priced(
                session, rtype, data["charge"], occurrences, occurrences[0].starts_at.date(), data["client_id"]
            ).quote(_currency(session), rtype.deposit_pct)
    return {
        "occurrences": result["occurrences"], "requested_count": result["requested_count"],
        "conflict_count": result["conflict_count"], "quote": quote, "birth_on_unknown": _birth_on_unknown(session, data),
    }  # fmt: skip


def _birth_on_unknown(session: Db, data: dict) -> list[UUID]:
    """The holder and players with no birth date: the desk keeps ADR 0002 section 5 (unknown counts as an adult)
    but is told, so staff can check before booking."""
    ids = [data["client_id"], *(p["client_id"] for p in data.get("parties") or [])]
    return [i for i in ids if clients.service.get(session, i).birth_on is None]


def create_rental(session: Db, principal: Principal, data: dict) -> dict:
    """Book a rental (RNT-03, single or recurring) and apply its charge decision (RNT-04). Above 50
    occurrences the worker generates them unbilled; only `unbilled` and `no_charge` are accepted then."""
    rtype, template = _rental_template(session, principal, data)
    result = scheduling.service.book(session, template, data, principal.staff_user_id)
    decision = data["charge"]
    if result["status_url"]:
        if decision["decision"] not in ("unbilled", "no_charge"):
            raise ValidationFailed(
                "Series above 50 occurrences are booked unbilled; bill them from the unbilled queue once generated.",
                pointer="/charge/decision", code="series-billed-later",
            )  # fmt: skip
        return result | {"rental": None, "quote": None, "invoice_ids": []}
    booking_ids = (
        [result["booking"]["id"]]
        if result["booking_series_id"] is None
        else scheduling.service.booking_ids(series_id=result["booking_series_id"])
    )
    rows = session.scalars(select(RentalBooking).where(RentalBooking.booking_id.in_(booking_ids))).all()
    quote, invoice_ids = _decide(session, rtype, data["client_id"], rows, decision)
    flag = {"minor_override_reason": True} if data.get("minor_override_reason") else {}  # free text: flag only
    for row in rows:
        audit.record(
            session, CREATE, row, location_id=row.location_id,
            changes={"charge_state": [None, row.charge_state], "rental_type_id": [None, str(row.rental_type_id)]} | flag,
        )  # fmt: skip
    first = min(rows, key=lambda r: r.starts_at)
    return result | {
        "rental": _view(session, first), "quote": quote, "invoice_ids": invoice_ids,
        "birth_on_unknown": _birth_on_unknown(session, data),
    }  # fmt: skip


def bill_selected(session: Db, principal: Principal, data: dict) -> dict:
    """Price any set of unbilled occurrences of one payer and type, then route the lines (RNT-04)."""
    rows = session.scalars(
        select(RentalBooking).where(RentalBooking.id.in_(data["rental_ids"])).with_for_update()
    ).all()
    if len(rows) != len(set(data["rental_ids"])):
        raise ValidationFailed("Unknown rental.", pointer="/rental_ids")
    for row in rows:
        authorize(principal, UPDATE, location_id=row.location_id)
    bookings = scheduling.service.booking_views(session, [row.booking_id for row in rows])
    if len({row.location_id for row in rows}) > 1 or len({row.rental_type_id for row in rows}) > 1:
        raise ValidationFailed("Bill one location and rental type at a time.", pointer="/rental_ids")
    payers = {bookings[row.booking_id]["client_id"] for row in rows}
    if len(payers) > 1:
        raise ValidationFailed("Bill one client at a time.", pointer="/rental_ids", code="payer-mismatch")
    if any(row.charge_state != "unbilled" or row.cancelled_at for row in rows):
        raise Conflict("Only unbilled, live occurrences can be billed.", code="rental-not-unbilled")
    decision = data["charge"]
    if decision["decision"] == "unbilled":
        raise ValidationFailed("Choose bill, no charge or plan.", pointer="/charge/decision")
    rtype, client_id = session.get(RentalType, rows[0].rental_type_id), payers.pop()
    _check_override(principal, decision, rtype.location_id)
    if data.get("preview"):
        if decision["decision"] != "bill":
            raise ValidationFailed("Only a bill decision has a quote.", pointer="/charge/decision")
        quote = _price_rows(session, rtype, decision, sorted(rows, key=lambda r: r.starts_at), client_id).quote(
            _currency(session), rtype.deposit_pct
        )
        return {"quote": quote, "rentals": _views(session, rows), "invoice_ids": []}
    quote, invoice_ids = _decide(session, rtype, client_id, rows, decision)
    for row in rows:
        audit.record(
            session, UPDATE, row, location_id=row.location_id, changes={"charge_state": ["unbilled", row.charge_state]}
        )
    empty = {"lines": [], "subtotal_minor": 0, "discount_minor": 0, "tax_minor": 0, "total_minor": 0, "deposit_minor": 0, "currency": _currency(session)}  # fmt: skip
    return {"quote": quote or empty, "rentals": _views(session, rows), "invoice_ids": invoice_ids}


def extend_rental(session: Db, principal: Principal, rental_id: UUID, data: dict) -> dict:
    """Add more occurrences to a recurring rental (RNT-04). They copy the series template, so they arrive
    unbilled (or no-charge) and are billed from the unbilled queue."""
    row = _rental(session, principal, rental_id, UPDATE)
    booking = scheduling.service.booking_views(session, [row.booking_id])[row.booking_id]
    if booking["booking_series_id"] is None:
        raise ValidationFailed(
            "Only a recurring rental can be extended; book a new rental instead.", pointer="/rule", code="not-a-series"
        )
    _check_type_resources(session, row.rental_type_id, data.get("resources") or ())
    # The minors rule again for the new dates: an override is never inherited from the original booking.
    reason = data.pop("minor_override_reason", None)
    if reason:
        authorize(principal, OVERRIDE_MINOR, location_id=row.location_id)
    else:  # the new occurrences copy the series' players, so they are checked again too
        players = session.scalars(select(RentalParty).where(RentalParty.rental_booking_id == row.id))
        parties = [{"client_id": p.client_id, "is_charged": p.is_charged} for p in players]
        _check_minors(session, booking["client_id"], parties, data["start_on"])
    result = scheduling.service.add_rule(
        session,
        booking["booking_series_id"],
        data,
        principal.staff_user_id,
        principal=principal,
        key=UPDATE,
        source_data={"minor_override_reason": reason},
        extra_changes={"minor_override_reason": True} if reason else None,  # free text: flag only
    )
    if data.get("preview"):
        return {"booking_series_id": booking["booking_series_id"], "created_count": 0, "conflict_count": 0} | result
    events.publish(
        session,
        ev.RentalExtended(booking_series_id=booking["booking_series_id"], location_id=row.location_id),
        booking["booking_series_id"],
    )
    return result


def set_public_schedule(session: Db, principal: Principal, rental_id: UUID, flag: bool) -> dict:
    row = _rental(session, principal, rental_id, PUBLISH, lock=True)
    if row.is_on_public_schedule != flag:
        audit.record(
            session, PUBLISH, row, location_id=row.location_id, changes={"is_on_public_schedule": [not flag, flag]}
        )
        row.is_on_public_schedule = flag
        session.flush()
    return _view(session, row)


# --- cancellation settlement --------------------------------------------------------------------------------


def _settle(session: Db, row: RentalBooking, *, keep_charge: bool = False) -> dict:
    """Idempotent money side of a cancelled occurrence (also run by the scheduling.booking.cancelled handler,
    so a calendar cancel or an expired checkout hold settles too). A line covering only this occurrence is
    reversed; a line shared with live occurrences is reversed and its remainder re-posted as one adjusted
    line (quantity 1, the remaining shares) on the same invoice when it is still open. Money already paid
    becomes account credit (billing.reverse). Plan-covered occurrences get their balance back."""
    out = {"reversed_minor": 0, "reposted_minor": 0, "plan_quantity_returned": Decimal(0)}
    if row.cancelled_at is not None:
        return out
    row.cancelled_at = clock.now()
    session.flush()
    if not keep_charge:
        lines = (
            session.scalars(
                select(RentalBookingCharge)
                .join(
                    RentalBookingChargeItem, RentalBookingChargeItem.rental_booking_charge_id == RentalBookingCharge.id
                )
                .where(RentalBookingChargeItem.rental_booking_id == row.id, RentalBookingCharge.reversed_at.is_(None))
                .with_for_update(of=RentalBookingCharge)
            )
            .unique()
            .all()
        )
        for rbc in lines:
            out["reversed_minor"] += rbc.amount_minor
            out["reposted_minor"] += _reverse_line(session, rbc)
    out["plan_quantity_returned"] = _credit_plan(session, row)
    events.publish(
        session,
        ev.RentalCancelled(rental_booking_id=row.id, booking_id=row.booking_id, location_id=row.location_id),
        row.id,
    )
    return out


def _reverse_line(session: Db, rbc: RentalBookingCharge) -> int:
    items = session.scalars(
        select(RentalBookingChargeItem).where(
            RentalBookingChargeItem.rental_booking_charge_id == rbc.id, RentalBookingChargeItem.reversed_at.is_(None)
        )
    ).all()
    live = {
        r.id
        for r in session.scalars(
            select(RentalBooking).where(
                RentalBooking.id.in_([i.rental_booking_id for i in items]), RentalBooking.cancelled_at.is_(None)
            )
        )
    }
    state = billing.service.charge_states(session, [rbc.charge_id])[rbc.charge_id]
    now = clock.now()
    if state["status"] == "active":
        billing.service.reverse(session, rbc.charge_id, reason="Rental cancelled")
    rbc.reversed_at = now
    for item in items:
        item.reversed_at = now
    remaining = [i for i in items if i.rental_booking_id in live]
    amount = sum(i.amount_minor for i in remaining)
    if not remaining:
        session.flush()
        return 0
    adjusted = RentalBookingCharge(
        id=new_id(), location_id=rbc.location_id, client_id=rbc.client_id, rental_rate_id=rbc.rental_rate_id,
        description=f"{rbc.description} (adjusted)", basis=rbc.basis, quantity=Decimal(1), unit_amount_minor=amount,
        discount_minor=0, amount_minor=amount, revenue_on=rbc.revenue_on, invoice_routing=rbc.invoice_routing,
        routing_period=rbc.routing_period,
    )  # fmt: skip
    original = billing.service.charge_states(session, [rbc.charge_id])[rbc.charge_id]
    excluded = billing.service.excluded_tax_ids(session, rbc.charge_id)  # keep the line's tax choice
    rental = session.get(RentalBooking, remaining[0].rental_booking_id)
    rtype = session.get(RentalType, rental.rental_type_id)
    charge = billing.service.post_charge(
        session, client_id=rbc.client_id, location_id=rbc.location_id, description=f"{rtype.name}: {adjusted.description}",
        unit_price_minor=amount, source_context="rentals", source_type="rental_booking_charge", source_id=adjusted.id,
        revenue_category_id=rtype.revenue_category_id, revenue_on=rbc.revenue_on, exclude_tax_ids=excluded,
    )  # fmt: skip
    adjusted.charge_id = charge.id
    session.add(adjusted)
    session.flush()
    session.add_all(
        RentalBookingChargeItem(
            rental_booking_charge_id=adjusted.id, rental_booking_id=i.rental_booking_id, resource_id=i.resource_id,
            amount_minor=i.amount_minor,
        )
        for i in remaining
    )  # fmt: skip
    session.flush()
    if original["invoice_id"]:
        if original["invoice_status"] in ("open", "partially_paid"):
            billing.service.attach_charges(session, original["invoice_id"], [charge.id])
        else:
            billing.service.create_invoice_for_charges(session, [charge.id], bill_to_client_id=rbc.client_id)
    return amount


def _credit_plan(session: Db, row: RentalBooking) -> Decimal:
    debit = session.scalar(
        select(RentalPlanLedgerEntry).where(
            RentalPlanLedgerEntry.rental_booking_id == row.id, RentalPlanLedgerEntry.entry_type == "debit"
        )
    )
    if debit is None:
        return Decimal(0)
    purchase = session.execute(
        select(RentalPlanPurchase).where(RentalPlanPurchase.id == debit.rental_plan_purchase_id).with_for_update()
    ).scalar_one()
    if purchase.status not in ("pending", "active"):
        return Decimal(0)
    quantity = -debit.quantity
    if purchase.balance is not None:
        purchase.balance += quantity
    session.add(
        RentalPlanLedgerEntry(
            rental_plan_purchase_id=purchase.id,
            entry_type="credit",
            quantity=quantity,
            balance_after=purchase.balance,
            rental_booking_id=row.id,
            used_by_client_id=debit.used_by_client_id,
            note="Rental cancelled",
        )  # fmt: skip
    )
    session.flush()
    return quantity


def _late_fee(session: Db, row: RentalBooking, rtype: RentalType, client_id: UUID) -> int:
    """Own design (no public source): inside the type's cut-off, a percentage of the occurrence's charged
    share is billed as a late-cancellation fee on its own invoice. Idempotent per occurrence."""
    if rtype.late_cancel_fee_pct is None or row.starts_at - clock.now() >= timedelta(hours=rtype.cancel_cutoff_hours):
        return 0
    base = session.scalar(
        select(func.coalesce(func.sum(RentalBookingChargeItem.amount_minor), 0)).where(
            RentalBookingChargeItem.rental_booking_id == row.id
        )
    )
    reposted = session.scalar(
        select(func.coalesce(func.sum(RentalBookingChargeItem.amount_minor), 0)).where(
            RentalBookingChargeItem.rental_booking_id == row.id, RentalBookingChargeItem.reversed_at.is_(None)
        )
    )
    base = base - reposted  # items are copied on re-post: count each share once
    fee = pricing.half_up(Decimal(base) * rtype.late_cancel_fee_pct / 100)
    if fee <= 0:
        return 0
    charge = billing.service.post_charge(
        session, client_id=client_id, location_id=row.location_id, description=f"Late cancellation: {rtype.name}",
        unit_price_minor=fee, source_context="rentals", source_type="rental_booking_late_fee", source_id=row.id,
        revenue_category_id=rtype.revenue_category_id,
    )  # fmt: skip
    if billing.service.charge_states(session, [charge.id])[charge.id]["invoice_id"] is None:
        billing.service.create_invoice_for_charges(session, [charge.id], bill_to_client_id=client_id)
    return fee


def cancel_rental(session: Db, principal: Principal, rental_id: UUID, data: dict, *, via: str = "staff") -> dict:
    """Remove occurrences from the schedule and settle their money (RNT-11). The scope names occurrences of
    the same series; without one only this occurrence is cancelled."""
    row = _rental(session, principal, rental_id, CANCEL, lock=True)
    if data.get("waive_late_fee"):
        authorize(principal, OVERRIDE_RATE, location_id=row.location_id)
    return _cancel_many(session, row, data, actor_key=CANCEL)


def _cancel_many(session: Db, row: RentalBooking, data: dict, *, actor_key: str) -> dict:
    booking = scheduling.service.get_booking(session, row.booking_id)
    if data.get("scope") and booking.booking_series_id:
        bookings = scheduling.service.series_scope(session, booking.booking_series_id, data["scope"])
    else:
        bookings = [booking] if booking.status != "cancelled" else []
    rtype = session.get(RentalType, row.rental_type_id)
    rows = {
        r.booking_id: r
        for r in session.scalars(
            select(RentalBooking).where(RentalBooking.booking_id.in_([b.id for b in bookings])).with_for_update()
        )
    }
    totals = {"cancelled_count": 0, "reversed_minor": 0, "reposted_minor": 0, "late_fee_minor": 0, "plan_quantity_returned": Decimal(0)}  # fmt: skip
    keep = data.get("charge_action") == "keep_charge"
    for target in sorted(bookings, key=lambda b: b.starts_at):
        rental = rows.get(target.id)
        scheduling.service.cancel_booking(session, target, reason=data.get("reason") or "staff")
        if rental is None:
            continue
        settled = _settle(session, rental, keep_charge=keep)
        for key in ("reversed_minor", "reposted_minor", "plan_quantity_returned"):
            totals[key] += settled[key]
        if not data.get("waive_late_fee") and not keep:
            totals["late_fee_minor"] += _late_fee(session, rental, rtype, target.client_id)
        totals["cancelled_count"] += 1
        audit.record(
            session, actor_key, rental, location_id=rental.location_id, reason=data.get("note"),
            changes={"status": [None, "cancelled"], "charge_action": [None, data.get("charge_action") or "credit_account"]},
        )  # fmt: skip
    return totals | {"rentals": _views(session, list(rows.values()))}


def on_booking_cancelled(session: Db, booking_id: UUID) -> None:
    """Internal (handler body): a rental cancelled outside rentals (calendar, hold expiry) settles here."""
    row = session.scalar(select(RentalBooking).where(RentalBooking.booking_id == booking_id).with_for_update())
    if row is not None:
        _settle(session, row)


def on_booking_rescheduled(session: Db, booking_id: UUID) -> None:
    """Keep the copied times current. A moved rental is not re-priced: its charges stay as posted."""
    row = session.scalar(select(RentalBooking).where(RentalBooking.booking_id == booking_id))
    if row is not None:
        booking = scheduling.service.get_booking(session, booking_id)
        row.starts_at, row.ends_at = booking.starts_at, booking.ends_at
        session.flush()


def on_invoice_paid(session: Db, invoice_id: UUID) -> None:
    """A paid checkout invoice confirms the portal holds it covers (a late provider confirmation)."""
    for row in _rows_on_invoice(session, invoice_id):
        booking = scheduling.service.get_booking(session, row.booking_id)
        if booking.status == "tentative":
            try:
                scheduling.service.confirm_booking(session, booking.id)
            except Conflict:
                pass  # the hold ran out first: its cancellation reversed the charge into account credit


def _rows_on_invoice(session: Db, invoice_id: UUID) -> list[RentalBooking]:
    charge_ids = billing.service.invoice_charge_ids(session, invoice_id)
    if not charge_ids:
        return []
    return list(
        session.scalars(
            select(RentalBooking)
            .join(RentalBookingChargeItem, RentalBookingChargeItem.rental_booking_id == RentalBooking.id)
            .join(RentalBookingCharge, RentalBookingCharge.id == RentalBookingChargeItem.rental_booking_charge_id)
            .where(RentalBookingCharge.charge_id.in_(charge_ids))
            .distinct()
        )
    )


# --- online: public listing, availability, portal checkout ------------------------------------------------


# --- per-location portal defaults (SSP-04) --------------------------------------------------------------------

_PORTAL_FIELDS = ("is_online_enabled", "min_lead_min", "max_length_min", "horizon_days")
_PORTAL_DEFAULTS = {"is_online_enabled": True, "min_lead_min": None, "max_length_min": None, "horizon_days": None}


def _portal_setting(session: Db, location_id: UUID) -> dict:
    row = session.scalar(select(RentalPortalSetting).where(RentalPortalSetting.location_id == location_id))
    return {k: getattr(row, k) for k in _PORTAL_FIELDS} if row else dict(_PORTAL_DEFAULTS)


def get_portal_settings(session: Db, principal: Principal, location_id: UUID) -> dict:
    platform.service.get_location(session, principal, location_id)  # unknown or out of scope: 404
    authorize(principal, PORTAL_SETTINGS, location_id=location_id)
    return {"location_id": location_id} | _portal_setting(session, location_id)


def put_portal_settings(session: Db, principal: Principal, location_id: UUID, data: dict) -> dict:
    """Replace the location's online rental defaults. Each limit tightens every self-service type there."""
    platform.service.get_location(session, principal, location_id)
    authorize(principal, PORTAL_SETTINGS, location_id=location_id)
    row = session.scalar(
        select(RentalPortalSetting).where(RentalPortalSetting.location_id == location_id).with_for_update()
    )
    if row is None:
        row = RentalPortalSetting(location_id=location_id)
        session.add(row)
    for key in _PORTAL_FIELDS:
        setattr(row, key, data[key])
    changes = audit.diff(row)
    session.flush()
    audit.record(session, PORTAL_SETTINGS, row, location_id=location_id, changes=changes)
    return {"location_id": location_id} | _portal_setting(session, location_id)


def _limits(session: Db, rtype: RentalType) -> dict:
    """The online limits a type runs under: the stricter of the type's and its location's."""
    loc = _portal_setting(session, rtype.location_id)
    maxes = [m for m in (rtype.max_length_min, loc["max_length_min"]) if m]
    return {
        "min_lead_min": max(rtype.min_lead_min, loc["min_lead_min"] or 0),
        "max_length_min": min(maxes) if maxes else None,
        "horizon_days": loc["horizon_days"],
    }


def list_public_types(session: Db) -> list[dict]:
    """RNT-05/RNT-06: self-service types with their resources and the online rate's base price, at locations
    whose portal books rentals; the limits are the effective ones (type and location defaults)."""
    out = []
    for row in session.scalars(
        select(RentalType)
        .where(RentalType.is_active, RentalType.access == "self_service")
        .order_by(RentalType.sort_order, RentalType.name)
    ):
        if not _portal_setting(session, row.location_id)["is_online_enabled"]:
            continue
        rate = session.get(RentalRate, row.online_rental_rate_id)
        found = resources.service.get_many(session, _type_resources(session, row.id))
        out.append(
            {c: getattr(row, c) for c in (
                "id", "location_id", "name", "online_description", "eligibility", "online_payment_mode",
                "default_length_min", "min_length_min", "slot_granularity_min", "deposit_pct",
                "cancel_cutoff_hours", "late_cancel_fee_pct",
            )}
            | _limits(session, row)
            | {
                "resources": [{"id": r.id, "name": r.name} for r in sorted(found, key=lambda r: (r.sort_order, r.name)) if r.status == "active"],
                "from_price_minor": rate.amount_minor if rate else 0,
            }
        )  # fmt: skip
    return out


def _online_type(session: Db, type_id: UUID) -> RentalType:
    row = session.get(RentalType, type_id)
    if row is None or not row.is_active or row.access != "self_service":
        raise NotFound()
    if not _portal_setting(session, row.location_id)["is_online_enabled"]:
        raise NotFound()
    return row


def _check_online_slot(session: Db, rtype: RentalType, starts_at: datetime, ends_at: datetime) -> None:
    """Online rules: length within min/max, start on the granularity grid, lead time and booking horizon
    respected (the stricter of the type and the location defaults, SSP-04)."""
    zone = _zone(session, rtype.location_id)
    local = starts_at.astimezone(zone)
    minutes = int((ends_at - starts_at).total_seconds() // 60)
    limits = _limits(session, rtype)
    if minutes < rtype.min_length_min or (limits["max_length_min"] and minutes > limits["max_length_min"]):
        raise ValidationFailed("That length is not offered online.", pointer="/ends_at", code="length-not-allowed")
    if (local.hour * 60 + local.minute) % rtype.slot_granularity_min or starts_at.second:
        raise ValidationFailed("Start on the booking grid.", pointer="/starts_at", code="off-grid")
    if starts_at < clock.now() + timedelta(minutes=limits["min_lead_min"]):
        raise ValidationFailed("Too close to the start to book online.", pointer="/starts_at", code="lead-time")
    if limits["horizon_days"] and starts_at >= clock.now() + timedelta(days=limits["horizon_days"]):
        raise ValidationFailed("That is too far ahead to book online.", pointer="/starts_at", code="beyond-horizon")


def search_availability(
    session: Db,
    type_id: UUID,
    on: date,
    *,
    length_min: int | None = None,
    resource_id: UUID | None = None,
    client_id: UUID | None = None,
    from_time: time | None = None,
    to_time: time | None = None,
) -> list[dict]:
    """Advisory slots (RNT-06): free ranges of the type's resources on a local date, snapped to the grid,
    with room for the type's buffers, priced with the online rate for `client_id` (anonymous: the guest
    price) through the same `_price_for` as the charge. The hold insert at checkout decides. The whole day,
    or the slots starting in the local band [from_time, to_time), grouped by court then start."""
    if from_time and to_time and to_time <= from_time:
        raise ValidationFailed("The band must end after it starts.", pointer="/to_time")
    rtype = _online_type(session, type_id)
    limits = _limits(session, rtype)
    length = length_min or rtype.default_length_min or rtype.min_length_min
    if length < rtype.min_length_min or (limits["max_length_min"] and length > limits["max_length_min"]):
        raise ValidationFailed("That length is not offered online.", pointer="/length_min", code="length-not-allowed")
    allowed = _type_resources(session, rtype.id)
    ids = [resource_id] if resource_id else sorted(allowed)
    if resource_id and resource_id not in allowed:
        raise ValidationFailed("This resource is not offered for this rental type.", pointer="/resource_id")
    zone = _zone(session, rtype.location_id)
    start = datetime.combine(on, time(0), zone)
    end = datetime.combine(on + timedelta(days=1), time(0), zone)
    band_from = datetime.combine(on, from_time, zone) if from_time else start
    band_to = datetime.combine(on, to_time, zone) if to_time else end
    free = scheduling.service.free_ranges(session, rtype.location_id, start, end, resource_ids=ids)
    names = {r.id: r.name for r in resources.service.get_many(session, ids)}
    rate = _rate_input(session, session.get(RentalRate, rtype.online_rental_rate_id))
    before, after = timedelta(minutes=rtype.buffer_before_min), timedelta(minutes=rtype.buffer_after_min)
    earliest, step = (
        clock.now() + timedelta(minutes=limits["min_lead_min"]),
        timedelta(minutes=rtype.slot_granularity_min),
    )
    latest = clock.now() + timedelta(days=limits["horizon_days"]) if limits["horizon_days"] else None
    slots = []
    member_status: dict[date, tuple[bool, frozenset]] = {}  # one membership read per date, not per slot
    for column in free["resources"]:
        for gap in column["free"]:
            cursor = start
            while cursor < gap["starts_at"] + before:
                cursor += step
            while cursor + timedelta(minutes=length) + after <= gap["ends_at"]:
                if max(earliest, band_from) <= cursor < band_to and (latest is None or cursor < latest):
                    finish = cursor + timedelta(minutes=length)
                    occurrence = pricing.Occurrence(0, cursor, finish, (column["resource_id"],))
                    lines = _price_for(session, rate, [occurrence], client_id, status=member_status)
                    slots.append(
                        {
                            "starts_at": cursor, "ends_at": finish, "resource_id": column["resource_id"],
                            "resource_name": names.get(column["resource_id"], ""),
                            "price_minor": sum(line.amount_minor for line in lines),
                            "is_member_price": any(line.is_member_price for line in lines),
                        }
                    )  # fmt: skip
                cursor += step
    return sorted(slots, key=_slot_key)


def _slot_key(slot: dict) -> tuple:
    return slot["resource_name"], str(slot["resource_id"]), slot["starts_at"]


def slot_page(slots: list[dict], limit: int, cursor: str | None) -> dict:
    """Keyset page over the day's slots (court, then start), so nothing is ever cut off silently."""
    if cursor:
        try:  # anonymous input: exactly [court name, court id, aware start], else 400, never a 500
            name, rid, at = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            after = (name, str(UUID(rid)), datetime.fromisoformat(at))
            if not isinstance(name, str) or after[2].tzinfo is None:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise DomainError("Invalid cursor", status=400, code="bad-request") from None
        slots = [s for s in slots if _slot_key(s) > after]
    page, more = slots[:limit], len(slots) > limit
    last = _slot_key(page[-1]) if more else None
    next_cursor = (
        base64.urlsafe_b64encode(json.dumps([last[0], last[1], last[2].isoformat()]).encode()).decode()
        if last else None
    )  # fmt: skip
    return {"data": page, "page": {"next_cursor": next_cursor, "has_more": more}}


def _portal_client(session: Db, principal: Principal, client_id: UUID) -> UUID:
    if principal.kind != "client":
        raise PermissionDenied("Clients only")
    if client_id not in clients.service.client_ids_for_identity(session, principal.identity_id):
        raise NotFound()
    return client_id


def portal_availability(session: Db, principal: Principal, client_id: UUID, type_id: UUID, on: date, **kw) -> list:
    """The open times priced for the client who will hold the rental (member prices), as the checkout charges."""
    return search_availability(session, type_id, on, client_id=_portal_client(session, principal, client_id), **kw)


def _portal_rental(
    session: Db, principal: Principal, rental_id: UUID, *, lock: bool = False
) -> tuple[RentalBooking, object]:
    stmt = select(RentalBooking).where(RentalBooking.id == rental_id)
    row = session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    if row is None:
        raise NotFound()
    if principal.kind != "client":
        raise PermissionDenied("Clients only")
    booking = scheduling.service.get_booking(session, row.booking_id)
    if booking.client_id not in clients.service.client_ids_for_identity(session, principal.identity_id):
        raise NotFound()
    return row, booking


def list_portal_rentals(session: Db, principal: Principal, query: ListQuery) -> dict:
    """The signed-in client's own rentals (and those of clients they act for)."""
    if principal.kind != "client":
        raise PermissionDenied("Clients only")
    mine = clients.service.client_ids_for_identity(session, principal.identity_id)
    stmt = select(RentalBooking).where(RentalBooking.booking_id.in_(scheduling.service.booking_ids(client_ids=mine)))
    page = paginate(
        session, stmt, ListQuery(query.limit, query.cursor, query.sort, query.include_total, None, {}),
        id_column=RentalBooking.id, sort_fields={"starts_at": RentalBooking.starts_at}, default_sort="starts_at",
        filter_fields={},
    )  # fmt: skip
    return page | {"data": _views(session, page["data"])}


def _amount_due(quote: dict | None) -> int:
    if not quote:
        return 0
    return quote["deposit_minor"] or quote["total_minor"]


def create_portal_rental(session: Db, principal: Principal, data: dict) -> dict:
    """Online checkout (RNT-07): a tentative booking on a checkout hold, priced with the online rate and
    invoiced; payment confirms it. Pay-later types, free and plan-covered rentals are confirmed at once."""
    client_id = _portal_client(session, principal, data["client_id"])
    rtype = _online_type(session, data["rental_type_id"])
    # active_members and paid_up_members read the same: non-payment suspends a contract, so it is no longer active.
    # Membership is read on the rental's own date (`member_on`): a contract that ends before it does not pass, an
    # auto-renewing one does.
    rental_on = data["starts_at"].astimezone(_zone(session, rtype.location_id)).date()
    if rtype.eligibility != "everyone" and memberships.service.member_on(session, client_id, rental_on) is None:
        raise ValidationFailed(
            "Online booking of this rental is for members.", pointer="/rental_type_id", code="membership-required"
        )
    if data["resource_id"] not in _type_resources(session, rtype.id):
        raise ValidationFailed("This resource is not offered for this rental type.", pointer="/resource_id")
    _check_online_slot(session, rtype, data["starts_at"], data["ends_at"])
    clients.service.require_active(session, client_id)
    players = []
    for player in dict.fromkeys(data.get("player_client_ids") or ()):
        if player == client_id:
            continue
        if clients.households.can_act_for(session, principal.identity_id, player) is None:
            raise NotFound()
        clients.service.require_active(session, player, pointer="/player_client_ids")
        players.append({"client_id": player, "is_charged": False})
    _check_minors(session, client_id, players, rental_on, pointer="/player_client_ids", online=True)
    plan = data.get("rental_plan_purchase_id")
    hold = None
    if rtype.online_payment_mode == "pay_in_full" and not plan:
        hold = scheduling.service.settings_for(session, rtype.location_id).checkout_hold_min
    rental_id = new_id()
    booking = scheduling.service.create_booking(
        session, location_id=rtype.location_id, kind="rental", starts_at=data["starts_at"], ends_at=data["ends_at"],
        resource_ids=[data["resource_id"]], client_id=client_id, title=rtype.name,
        buffer_before_min=rtype.buffer_before_min, buffer_after_min=rtype.buffer_after_min,
        source=(*SOURCE, rental_id), created_via="portal", hold_minutes=hold,
    )  # fmt: skip
    parties = [{"client_id": str(p["client_id"]), "is_charged": False} for p in players]
    _on_booking(session, booking, {"rental_type_id": str(rtype.id), "booked_via": "portal", "parties": parties})
    row = session.get(RentalBooking, rental_id)
    if plan:
        decision = {"decision": "plan", "rental_plan_purchase_id": plan}
    else:
        decision = {"decision": "bill", "rental_rate_id": rtype.online_rental_rate_id, "invoice_routing": "new_single"}
    quote, invoice_ids = _decide(session, rtype, client_id, [row], decision)
    due = _amount_due(quote)
    if hold and due == 0:
        scheduling.service.confirm_booking(session, booking.id)
    audit.record(session, CREATE, row, location_id=row.location_id, changes={"booked_via": [None, "portal"]})
    return _checkout(
        session, row, booking, quote, invoice_ids[0] if invoice_ids else None, hold is not None and due > 0
    )


def _checkout(
    session: Db,
    row: RentalBooking,
    booking,
    quote: dict | None,
    invoice_id: UUID | None,
    required: bool,
    status: str | None = None,
) -> dict:
    empty = {"lines": [], "subtotal_minor": 0, "discount_minor": 0, "tax_minor": 0, "total_minor": 0, "deposit_minor": 0, "currency": _currency(session)}  # fmt: skip
    return {
        "rental": _view(session, row), "quote": quote or empty, "expires_at": booking.expires_at, "invoice_id": invoice_id,
        "payment_required": required, "amount_due_minor": _amount_due(quote) if required else 0, "payment_status": status,
        "entry_code_notice": clients.service.entry_code_notice(session, clients.service.get(session, booking.client_id), row.location_id),
    }  # fmt: skip


def _checkout_quote(session: Db, row: RentalBooking) -> tuple[dict, UUID | None]:
    lines = (
        session.scalars(
            select(RentalBookingCharge)
            .join(RentalBookingChargeItem, RentalBookingChargeItem.rental_booking_charge_id == RentalBookingCharge.id)
            .where(RentalBookingChargeItem.rental_booking_id == row.id, RentalBookingCharge.reversed_at.is_(None))
        )
        .unique()
        .all()
    )
    states = billing.service.charge_states(session, [rbc.charge_id for rbc in lines])
    total = sum(states[rbc.charge_id]["total_minor"] for rbc in lines)
    rtype = session.get(RentalType, row.rental_type_id)
    subtotal = sum(rbc.amount_minor for rbc in lines)
    quote = {
        "lines": [], "subtotal_minor": subtotal, "discount_minor": sum(rbc.discount_minor for rbc in lines),
        "tax_minor": total - subtotal, "total_minor": total, "deposit_minor": pricing.deposit_of(total, rtype.deposit_pct),
        "currency": _currency(session),
    }  # fmt: skip
    invoice_id = next(
        (states[rbc.charge_id]["invoice_id"] for rbc in lines if states[rbc.charge_id]["invoice_id"]), None
    )
    return quote, invoice_id


def confirm_portal_rental(session: Db, principal: Principal, rental_id: UUID, data: dict, idempotency_key: str) -> dict:
    """Pay the checkout (the deposit when the type asks one, else the total) with a new card token or a stored
    method of the client, through `billing.checkout.secure_online_checkout`, and confirm the hold. A decline
    rolls the payment back and leaves the hold to run out; `unknown` is a 503 to retry with the same key."""
    row, booking = _portal_rental(session, principal, rental_id, lock=True)
    quote, invoice_id = _checkout_quote(session, row)
    if booking.status == "confirmed":  # an idempotent replay of a paid confirm: already acknowledged
        return _checkout(session, row, booking, quote, invoice_id, False)
    if booking.status != "tentative" or booking.expires_at <= clock.now():
        raise Conflict("The hold on this time has expired.", code="hold-expired")
    clients.terms.acknowledge(session, client_id=booking.client_id, terms_version_id=data.get("terms_version_id"),
                              sale_kind="rental", subject_id=row.id)  # fmt: skip
    token, method_id = data.get("provider_payment_token"), data.get("payment_method_id")
    if bool(token) == bool(method_id):
        raise ValidationFailed("Give a new card token or a stored payment method, not both.",
                               pointer="/payment_method_id", code="payment-method-required")  # fmt: skip
    invoice = billing.service.get_invoice_row(session, invoice_id) if invoice_id else None
    payment = billing.checkout.secure_online_checkout(
        session, client_id=booking.client_id, location_id=row.location_id, total_minor=quote["total_minor"],
        invoice=invoice, idempotency_key=f"rental:{row.id}:{idempotency_key}", method_token=token,
        payment_method_id=method_id, amount_minor=_amount_due(quote), save_method=bool(data.get("save_method")),
    )  # fmt: skip
    booking = scheduling.service.confirm_booking(session, booking.id)
    audit.record(session, UPDATE, row, location_id=row.location_id, changes={"status": ["tentative", "confirmed"]})
    return _checkout(session, row, booking, quote, invoice_id, False, payment.status if payment else None)


def abandon_portal_rental(session: Db, principal: Principal, rental_id: UUID) -> None:
    """Give the held time back before paying. Idempotent."""
    row, booking = _portal_rental(session, principal, rental_id, lock=True)
    if booking.status != "tentative":
        if booking.status == "cancelled":
            return
        raise Conflict("This rental is already confirmed; cancel it instead.", code="rental-confirmed")
    scheduling.service.cancel_booking(session, booking, reason="client")
    _settle(session, row)
    audit.record(session, CANCEL, row, location_id=row.location_id, changes={"status": ["tentative", "cancelled"]})


def cancel_portal_rental(session: Db, principal: Principal, rental_id: UUID) -> dict:
    """Self-service cancellation of a confirmed rental: the late-cancel fee applies inside the cut-off."""
    row, booking = _portal_rental(session, principal, rental_id, lock=True)
    if booking.starts_at <= clock.now():
        raise Conflict("A rental that has started cannot be cancelled online.", code="rental-started")
    return _cancel_many(session, row, {"reason": "client", "charge_action": "credit_account"}, actor_key=CANCEL)


# --- rental plans ------------------------------------------------------------------------------------------

_PLAN_FIELDS = (
    "name", "rental_type_id", "model", "quantity", "is_unlimited", "price_minor", "member_price_minor", "is_flat_rate",
    "revenue_category_id", "internal_description", "client_description", "is_members_only", "is_sold_online",
    "start_mode", "fixed_starts_on", "validity_days", "fixed_expires_on", "default_invoice_routing", "is_shareable",
    "status", "is_auto_renew", "is_autopay_default",
)  # fmt: skip


def list_plans(session: Db, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, scope_query(select(RentalPlan), principal, RentalPlan.location_id), query, id_column=RentalPlan.id,
        sort_fields={"name": RentalPlan.name}, default_sort="name",
        filter_fields={"location_id": RentalPlan.location_id, "status": RentalPlan.status, "rental_type_id": RentalPlan.rental_type_id},
        search=(RentalPlan.name,),
    )  # fmt: skip


def get_plan(session: Db, principal: Principal, plan_id: UUID) -> RentalPlan:
    return _scoped(session, principal, RentalPlan, plan_id, None)


def _check_plan(session: Db, row: RentalPlan) -> None:
    _type_for(session, row.rental_type_id, row.location_id)
    if row.is_unlimited:
        row.quantity = None
    elif row.quantity is None:
        raise ValidationFailed("A limited plan has a quantity.", pointer="/quantity")


def create_plan(session: Db, principal: Principal, data: dict) -> RentalPlan:
    """RNT-09. An auto-renewing plan needs `validity_days` (ck_rental_plan_renew); autopay is billing's."""
    location_id = _location(session, principal, data["location_id"])
    authorize(principal, PLANS, location_id=location_id)
    row = RentalPlan(location_id=location_id)
    _apply(row, {k: v for k, v in data.items() if v is not None}, _PLAN_FIELDS)
    _check_plan(session, row)
    session.add(row)
    session.flush()
    audit.record(session, PLANS, row, location_id=location_id, changes={"name": [None, row.name]})
    return row


def update_plan(session: Db, principal: Principal, plan_id: UUID, data: dict) -> RentalPlan:
    """Changes apply to future sales; sold purchases keep their snapshot."""
    row = _scoped(session, principal, RentalPlan, plan_id, PLANS, lock=True)
    changes = _apply(row, data, _PLAN_FIELDS)
    _check_plan(session, row)
    session.flush()
    if changes:
        audit.record(session, PLANS, row, location_id=row.location_id, changes=changes)
    return row


def archive_plan(session: Db, principal: Principal, plan_id: UUID) -> None:
    row = _scoped(session, principal, RentalPlan, plan_id, PLANS, lock=True)
    if row.status != "archived":
        row.status = "archived"
        session.flush()
        audit.record(session, PLANS, row, location_id=row.location_id, changes={"status": ["active", "archived"]})


def _shared_with(session: Db, purchase_id: UUID) -> list[UUID]:
    """Clients a purchase is shared with now (RNT-10): evaluated at use time from live share rows."""
    return list(session.scalars(
        select(RentalPlanShare.client_id)
        .where(RentalPlanShare.rental_plan_purchase_id == purchase_id, RentalPlanShare.revoked_at.is_(None))
        .order_by(RentalPlanShare.client_id)
    ))  # fmt: skip


def _purchase_view(session: Db, row: RentalPlanPurchase) -> dict:
    invoice_id = None
    if row.charge_id:
        invoice_id = billing.service.charge_states(session, [row.charge_id])[row.charge_id]["invoice_id"]
    return _columns(row) | {"invoice_id": invoice_id, "shared_with_client_ids": _shared_with(session, row.id)}


def _is_member(session: Db, client_id: UUID, on: date) -> bool:
    """Members-only plans and member prices (RNT-09). A read through memberships' internal `is_member`, which
    overview section 2 lists in rentals' "May call" column (read-only) and the import contract allows."""
    return memberships.service.is_member(session, client_id, on)


def _sell(
    session: Db,
    plan: RentalPlan,
    client_id: UUID,
    *,
    via: str,
    staff_user_id: UUID | None = None,
    quantity_total: Decimal | None = None,
    invoice_routing: str | None = None,
    is_auto_renew: bool | None = None,
    is_autopay: bool | None = None,
    renewed_from: RentalPlanPurchase | None = None,
    starts_on: date | None = None,
) -> tuple[RentalPlanPurchase, object]:
    """The purchase, its charge (invoiced unless routed to the cart) and its grant. Internal: staff sale, portal
    purchase and auto-renewal share it, so the members-only rule and the price are decided in one place."""
    clients.service.require_active(session, client_id)
    today = platform.service.location_today(session, plan.location_id)
    member = _is_member(session, client_id, today)
    if plan.is_members_only and not member:
        raise ValidationFailed("This plan is for members only.", pointer="/rental_plan_id", code="membership-required")
    quantity = None if plan.is_unlimited else (quantity_total or plan.quantity)
    unit = plan.member_price_minor if member and plan.member_price_minor is not None else plan.price_minor
    price = unit if plan.is_flat_rate else pricing.half_up(Decimal(unit) * quantity)
    starts = starts_on or (plan.fixed_starts_on if plan.start_mode == "fixed_date" else today)
    expires = (None if renewed_from else plan.fixed_expires_on) or (
        starts + timedelta(days=plan.validity_days - 1) if plan.validity_days else None
    )
    if expires is not None and expires < today:
        raise ValidationFailed("This plan has already expired.", pointer="/rental_plan_id", code="plan-not-valid")
    row = RentalPlanPurchase(
        location_id=plan.location_id, rental_plan_id=plan.id, client_id=client_id,
        status="pending" if starts > today else "active", model=plan.model, quantity_total=quantity, balance=quantity,
        price_minor=price, sold_via=via, sold_by_staff_user_id=staff_user_id, starts_on=starts, expires_on=expires,
        is_auto_renew=plan.is_auto_renew if is_auto_renew is None else is_auto_renew and plan.validity_days is not None,
        is_autopay=plan.is_autopay_default if is_autopay is None else is_autopay,
        renewed_from_purchase_id=renewed_from and renewed_from.id,
    )  # fmt: skip
    session.add(row)
    session.flush()
    invoice = None
    if price > 0:
        charge = billing.service.post_charge(
            session, client_id=row.client_id, location_id=row.location_id, description=f"Rental plan: {plan.name}",
            unit_price_minor=price, source_context="rentals", source_type="rental_plan_purchase", source_id=row.id,
            revenue_category_id=plan.revenue_category_id, service_starts_on=starts, service_ends_on=expires,
        )  # fmt: skip
        row.charge_id = charge.id
        if (invoice_routing or plan.default_invoice_routing) != "cart":
            invoice = billing.service.create_invoice_for_charges(
                session, [charge.id], bill_to_client_id=row.client_id, is_autopay=row.is_autopay,
                origin="system" if renewed_from else ("portal" if via == "portal" else "staff"),
            )  # fmt: skip
    session.add(
        RentalPlanLedgerEntry(
            rental_plan_purchase_id=row.id,
            entry_type="grant",
            quantity=quantity or Decimal(0),
            balance_after=quantity,
            used_by_client_id=row.client_id,
            note="Renewed" if renewed_from else "Sold",
        )  # fmt: skip
    )
    session.flush()
    audit.record(session, SELL, row, location_id=row.location_id, changes={
        "price_minor": [None, price], "rental_plan_id": [None, str(plan.id)], "sold_via": [None, via],
        **({"renewed_from_purchase_id": [None, str(renewed_from.id)]} if renewed_from else {}),
    })  # fmt: skip
    events.publish(session, ev.RentalPlanSold(rental_plan_purchase_id=row.id, client_id=row.client_id), row.id)
    return row, invoice


def sell_plan(session: Db, principal: Principal, data: dict) -> dict:
    """Sell a plan at the desk (RNT-09). Members-only plans need a member; a member pays the member price."""
    plan = session.get(RentalPlan, data["rental_plan_id"])
    if plan is None or plan.status != "active":
        raise ValidationFailed("Unknown or archived plan.", pointer="/rental_plan_id")
    authorize(principal, SELL, location_id=plan.location_id)
    row, _ = _sell(
        session, plan, data["client_id"], via="staff", staff_user_id=principal.staff_user_id,
        quantity_total=data.get("quantity_total"), invoice_routing=data.get("invoice_routing"),
        is_auto_renew=data.get("is_auto_renew"), is_autopay=data.get("is_autopay"),
    )  # fmt: skip
    return _purchase_view(session, row)


def list_purchases(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, SELL)
    page = paginate(
        session, scope_query(select(RentalPlanPurchase), principal, RentalPlanPurchase.location_id), query,
        id_column=RentalPlanPurchase.id, sort_fields={"created_at": RentalPlanPurchase.created_at}, default_sort="-created_at",
        filter_fields={
            "location_id": RentalPlanPurchase.location_id, "client_id": RentalPlanPurchase.client_id,
            "status": RentalPlanPurchase.status, "rental_plan_id": RentalPlanPurchase.rental_plan_id,
        },
    )  # fmt: skip
    return page | {"data": [_purchase_view(session, row) for row in page["data"]]}


def get_purchase(session: Db, principal: Principal, purchase_id: UUID) -> dict:
    return _purchase_view(session, _scoped(session, principal, RentalPlanPurchase, purchase_id, SELL))


def list_ledger(session: Db, principal: Principal, purchase_id: UUID) -> list[RentalPlanLedgerEntry]:
    row = _scoped(session, principal, RentalPlanPurchase, purchase_id, SELL)
    return list(
        session.scalars(
            select(RentalPlanLedgerEntry)
            .where(RentalPlanLedgerEntry.rental_plan_purchase_id == row.id)
            .order_by(RentalPlanLedgerEntry.created_at, RentalPlanLedgerEntry.id)
        )
    )


def cancel_purchase(session: Db, principal: Principal, purchase_id: UUID, data: dict) -> dict:
    """Remove a plan (RNT-11): `reverse_billing` reverses its charge (paid money becomes account credit),
    `keep_billing` leaves it. The remaining balance expires. Rentals it already covered stay covered."""
    row = _scoped(session, principal, RentalPlanPurchase, purchase_id, REMOVE, lock=True)
    if row.status == "cancelled":
        return _purchase_view(session, row)
    if data["cancel_mode"] == "reverse_billing" and row.charge_id:
        if billing.service.charge_states(session, [row.charge_id])[row.charge_id]["status"] == "active":
            billing.service.reverse(session, row.charge_id, reason=data["reason"])
    was = row.status
    row.status, row.cancelled_at, row.cancel_mode = "cancelled", clock.now(), data["cancel_mode"]
    if row.balance:
        session.add(
            RentalPlanLedgerEntry(
                rental_plan_purchase_id=row.id,
                entry_type="expire",
                quantity=-row.balance,
                balance_after=Decimal(0),
                note="Plan removed",
            )  # fmt: skip
        )
        row.balance = Decimal(0)
    session.flush()
    audit.record(
        session, REMOVE, row, location_id=row.location_id, reason=data["reason"],
        changes={"status": [was, "cancelled"], "cancel_mode": [None, data["cancel_mode"]]},
    )  # fmt: skip
    return _purchase_view(session, row)


def update_purchase(session: Db, principal: Principal, purchase_id: UUID, data: dict) -> dict:
    """Turn auto-renew or autopay on or off for one purchase (RNT-09). Auto-renew needs a plan with a validity."""
    row = _scoped(session, principal, RentalPlanPurchase, purchase_id, SELL, lock=True)
    if row.status not in ("pending", "active"):
        raise Conflict("Only a live plan can change.", code="plan-not-valid")
    if data.get("is_auto_renew") and session.get(RentalPlan, row.rental_plan_id).validity_days is None:
        raise ValidationFailed("Only a plan with a validity can renew.", pointer="/is_auto_renew")
    changes = _apply(row, data, ("is_auto_renew", "is_autopay"))
    session.flush()
    if changes:
        audit.record(session, SELL, row, location_id=row.location_id, changes=changes)
    return _purchase_view(session, row)


# --- plan sharing (RNT-10, FAM-06) -------------------------------------------------------------------------


def _related_ids(session: Db, client_id: UUID) -> set[UUID]:
    """The client's live, active relatives (household relationships)."""
    return {
        rel.to_client_id if rel.from_client_id == client_id else rel.from_client_id
        for rel in clients.households.relationships_of(session, client_id, live_only=True)
        if rel.status == "active"
    }


def replace_shares(session: Db, principal: Principal, purchase_id: UUID, client_ids: list[UUID]) -> dict:
    """Share a plan's balance with related clients (RNT-10, FAM-06): the list replaces the live shares. Each
    sharer's bookings debit the one balance, and each debit records who used it."""
    row = _scoped(session, principal, RentalPlanPurchase, purchase_id, SHARE, lock=True)
    if client_ids and not session.get(RentalPlan, row.rental_plan_id).is_shareable:
        raise Conflict("This plan cannot be shared.", code="plan-not-shareable")
    if client_ids and row.status not in ("pending", "active"):
        raise Conflict("Only a live plan can be shared.", code="plan-not-valid")
    related = _related_ids(session, row.client_id)
    for index, client_id in enumerate(client_ids):
        if client_id not in related:
            raise ValidationFailed(
                "Share only with a related client.", pointer=f"/client_ids/{index}", code="client-not-related"
            )
        clients.service.require_active(session, client_id)
    live = {
        share.client_id: share
        for share in session.scalars(select(RentalPlanShare).where(
            RentalPlanShare.rental_plan_purchase_id == row.id, RentalPlanShare.revoked_at.is_(None)
        ))
    }  # fmt: skip
    for client_id, share in live.items():
        if client_id not in client_ids:
            share.revoked_at = clock.now()
    added = [cid for cid in dict.fromkeys(client_ids) if cid not in live]
    session.add_all(RentalPlanShare(rental_plan_purchase_id=row.id, client_id=cid) for cid in added)
    session.flush()
    removed = [cid for cid in live if cid not in client_ids]
    if added or removed:
        audit.record(session, SHARE, row, location_id=row.location_id,
                     changes={"shares_added": [str(c) for c in added], "shares_revoked": [str(c) for c in removed]})  # fmt: skip
    return _purchase_view(session, row)


# --- plan day-roll: activation, expiry, auto-renew (RNT-09) ------------------------------------------------


def _expire_purchase(session: Db, row: RentalPlanPurchase) -> None:
    if row.balance:
        session.add(RentalPlanLedgerEntry(
            rental_plan_purchase_id=row.id, entry_type="expire", quantity=-row.balance, balance_after=Decimal(0),
            note="Plan expired",
        ))  # fmt: skip
        row.balance = Decimal(0)
    row.status = "expired"
    audit.record(session, SELL, row, location_id=row.location_id, changes={"status": ["active", "expired"]})


def _renew_purchase(session: Db, row: RentalPlanPurchase, today: date) -> RentalPlanPurchase | None:
    """The successor of an expiring auto-renew purchase: a new term and a new charge, invoiced with the
    purchase's autopay flag so billing's autopay run collects it. Shares carry over while the plan is
    shareable. None when the plan was
    archived or the client no longer qualifies (members-only); the purchase then simply expires."""
    plan = session.get(RentalPlan, row.rental_plan_id)
    if plan.status != "active" or plan.validity_days is None:
        return None
    if session.scalar(select(RentalPlanPurchase.id).where(RentalPlanPurchase.renewed_from_purchase_id == row.id)):
        return None
    starts = max(row.expires_on + timedelta(days=1), today)
    try:
        with session.begin_nested():
            successor, _ = _sell(
                session, plan, row.client_id, via=row.sold_via, staff_user_id=row.sold_by_staff_user_id,
                quantity_total=row.quantity_total, invoice_routing="new_single", is_auto_renew=True,
                is_autopay=row.is_autopay, renewed_from=row, starts_on=starts,
            )  # fmt: skip
    except (ValidationFailed, Conflict, NotFound):
        return None
    if plan.is_shareable:
        session.add_all(RentalPlanShare(rental_plan_purchase_id=successor.id, client_id=cid)
                        for cid in _shared_with(session, row.id))  # fmt: skip
    session.flush()
    return successor


def run_plan_day(session: Db) -> dict:
    """Idempotent day-roll per location's today: a pending purchase whose start arrived becomes active; an
    active one past its expiry expires (the remaining balance with it) and, when it auto-renews, gets its
    successor. Spending never waits for this run: every debit checks the dates itself."""
    p = RentalPlanPurchase
    result, todays = {"activated": 0, "expired": 0, "renewed": 0}, {}
    for purchase_id in session.scalars(select(p.id).where(p.status.in_(("pending", "active"))).order_by(p.id)).all():
        row = session.execute(select(p).where(p.id == purchase_id).with_for_update()).scalar_one()
        today = todays.get(row.location_id) or todays.setdefault(
            row.location_id, platform.service.location_today(session, row.location_id)
        )
        if row.status == "pending" and row.starts_on <= today:
            row.status = "active"
            audit.record(session, SELL, row, location_id=row.location_id, changes={"status": ["pending", "active"]})
            result["activated"] += 1
        if row.status == "active" and row.expires_on is not None and row.expires_on < today:
            _expire_purchase(session, row)
            result["expired"] += 1
            if row.is_auto_renew and _renew_purchase(session, row, today):
                result["renewed"] += 1
        session.flush()
    return result


@tenant_actor
def run_rental_plan_day(session: Db) -> dict:
    """The queued form of run_plan_day, one message per tenant per hour (app/scheduler.py)."""
    return run_plan_day(session)


# --- portal plans (RNT-09, RNT-10) -------------------------------------------------------------------------


def _portal_subject(session: Db, principal: Principal, client_id: UUID | None, capability: str = "book") -> UUID:
    """The client a portal call acts for: given and actable, or the identity's own first client."""
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    if client_id is None:
        own = clients.service.client_ids_for_identity(session, principal.identity_id)
        if not own:
            raise NotFound()
        client_id = own[0]
    if clients.households.can_act_for(session, principal.identity_id, client_id, capability) is None:
        raise NotFound()
    return client_id


def portal_list_plans(session: Db, principal: Principal, client_id: UUID | None, query: ListQuery) -> dict:
    """Plans sold online, with the price this client would pay and whether they may buy it (members-only)."""
    subject = _portal_subject(session, principal, client_id, "buy")
    stmt = select(RentalPlan).where(RentalPlan.status == "active", RentalPlan.is_sold_online)
    page = paginate(
        session, stmt, query, id_column=RentalPlan.id, sort_fields={"name": RentalPlan.name}, default_sort="name",
        filter_fields={"location_id": RentalPlan.location_id, "rental_type_id": RentalPlan.rental_type_id},
    )  # fmt: skip
    data = []
    for plan in page["data"]:
        member = _is_member(session, subject, platform.service.location_today(session, plan.location_id))
        price = plan.member_price_minor if member and plan.member_price_minor is not None else plan.price_minor
        data.append(_columns(plan) | {"price_minor": price, "is_purchasable": member or not plan.is_members_only})
    return page | {"data": data}


def portal_list_purchases(session: Db, principal: Principal, client_id: UUID | None, query: ListQuery) -> dict:
    """Live plan balances the acting client owns or may draw on through a share."""
    subject = _portal_subject(session, principal, client_id)
    p = RentalPlanPurchase
    shared = select(RentalPlanShare.rental_plan_purchase_id).where(
        RentalPlanShare.client_id == subject, RentalPlanShare.revoked_at.is_(None)
    )
    stmt = select(p).where(or_(p.client_id == subject, p.id.in_(shared)), p.status.in_(("pending", "active")))
    page = paginate(session, stmt, query, id_column=p.id, sort_fields={"created_at": p.created_at},
                    default_sort="-created_at")  # fmt: skip
    names = {r.id: r.name for r in session.scalars(select(RentalPlan).where(
        RentalPlan.id.in_({row.rental_plan_id for row in page["data"]})))}  # fmt: skip
    return page | {"data": [
        _columns(row) | {"rental_plan_name": names.get(row.rental_plan_id), "is_owner": row.client_id == subject}
        for row in page["data"]
    ]}  # fmt: skip


def portal_buy_plan(session: Db, principal: Principal, data: dict, idempotency_key: str) -> dict:
    """Buy a plan online for oneself or a client one may buy for (RNT-09). The sale is invoiced at once and
    ends in billing's secure_online_checkout: when the payment does not go through, nothing is sold."""
    subject = _portal_subject(session, principal, data.get("client_id"), "buy")
    plan = session.get(RentalPlan, data["rental_plan_id"])
    if plan is None or plan.status != "active" or not plan.is_sold_online:
        raise ValidationFailed("This plan is not sold online.", pointer="/rental_plan_id")
    row, invoice = _sell(session, plan, subject, via="portal", invoice_routing="new_single")
    payment = billing.checkout.secure_online_checkout(
        session, client_id=subject, location_id=row.location_id, total_minor=row.price_minor, invoice=invoice,
        idempotency_key=f"rental-plan:{idempotency_key}", method_token=data.get("method_token"),
        payment_method_id=data.get("payment_method_id"), must_pay_now=True,
    )  # fmt: skip
    return _columns(row) | {"rental_plan_name": plan.name, "is_owner": True,
                            "payment_status": payment.status if payment else None}  # fmt: skip


def portal_disable_auto_renew(session: Db, principal: Principal, purchase_id: UUID) -> dict:
    """Click-to-cancel from the portal: the plan runs to its end and does not renew. One way."""
    row = session.execute(
        select(RentalPlanPurchase).where(RentalPlanPurchase.id == purchase_id).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise NotFound()
    _portal_subject(session, principal, row.client_id, "edit_profile")
    if row.is_auto_renew:
        row.is_auto_renew = False
        audit.record(session, SELL, row, location_id=row.location_id, changes={"is_auto_renew": [True, False]})
        session.flush()
    name = session.get(RentalPlan, row.rental_plan_id).name
    return _columns(row) | {"rental_plan_name": name, "is_owner": True}


# --- locker leases (RNT-17, RNT-18) ------------------------------------------------------------------------

_TERM_UNITS = {"week": "week", "month": "month", "year": "year"}


def _today_for(session: Db, cache: dict, location_id: UUID) -> date:
    if location_id not in cache:
        cache[location_id] = platform.service.location_today(session, location_id)
    return cache[location_id]


def _lease_state(row: LockerLease, today: date) -> str:
    if row.cleared_at is not None:
        return "cleared"
    return "expired" if row.ends_on < today else "rented"


def _lease_views(session: Db, rows: list[LockerLease]) -> list[dict]:
    labels = resources.service.locker_labels(session, {r.locker_id for r in rows})
    names = clients.service.display_names(session, list({r.client_id for r in rows})) if rows else {}
    todays: dict = {}
    return [
        _columns(r) | labels.get(r.locker_id, {}) | {
            "client_name": names.get(r.client_id), "state": _lease_state(r, _today_for(session, todays, r.location_id)),
        }
        for r in rows
    ]  # fmt: skip


def _locker_states(session: Db, locker_ids: list[UUID]) -> dict[UUID, dict]:
    """resources.service.HOOKS["locker_states"]: each locker's uncleared lease, if any."""
    rows = session.scalars(select(LockerLease).where(
        LockerLease.locker_id.in_(locker_ids), LockerLease.cleared_at.is_(None)
    )).all() if locker_ids else []  # fmt: skip
    return {
        view["locker_id"]: {key: view[key] for key in ("state", "client_id", "client_name", "ends_on")}
        | {"locker_lease_id": view["id"]}
        for view in _lease_views(session, list(rows))
    }


def _locker_retiring(session: Db, locker) -> None:
    """resources.service.HOOKS["locker_retiring"]: a rented locker stays in service until it is cleared."""
    if session.scalar(
        select(LockerLease.id).where(LockerLease.locker_id == locker.id, LockerLease.cleared_at.is_(None))
    ):
        raise Conflict("Clear the locker's lease first.", code="locker-leased")


resources.service.HOOKS["locker_states"].append(_locker_states)
resources.service.HOOKS["locker_retiring"].append(_locker_retiring)


def list_locker_leases(session: Db, principal: Principal, query: ListQuery) -> dict:
    """Filters: location_id, locker_id, client_id, ends_on (with [gte]/[lte]), is_open (true: not cleared)."""
    authorize(principal, LOCKER_RENT)
    stmt = scope_query(select(LockerLease), principal, LockerLease.location_id)
    is_open = query.filters.pop("is_open", None)
    if is_open is not None:
        stmt = stmt.where(
            LockerLease.cleared_at.is_(None) if is_open == "true" else LockerLease.cleared_at.is_not(None)
        )
    page = paginate(
        session, stmt, query, id_column=LockerLease.id,
        sort_fields={"ends_on": LockerLease.ends_on, "created_at": LockerLease.created_at}, default_sort="-created_at",
        filter_fields={
            "location_id": LockerLease.location_id, "locker_id": LockerLease.locker_id,
            "client_id": LockerLease.client_id, "ends_on": LockerLease.ends_on,
        },
    )  # fmt: skip
    return page | {"data": _lease_views(session, page["data"])}


def _lease_dates(
    session: Db, location_id: UUID, data: dict, starts_default: date
) -> tuple[date, date, int, UUID | None]:
    """(starts_on, ends_on, predefined fee, term id) for a lease of the given term kind."""
    kind = data["term_kind"]
    if kind == "term":
        term = data.get("locker_term_id") and resources.service.get_locker_term(session, data["locker_term_id"])
        if not term or term.location_id != location_id or not term.is_active:
            raise ValidationFailed("Unknown locker term at this location.", pointer="/locker_term_id")
        if term.ends_on < platform.service.location_today(session, location_id):
            raise Conflict("This term has already ended.", code="term-ended")
        return term.starts_on, term.ends_on, term.price_minor, term.id
    if data.get("locker_term_id"):
        raise ValidationFailed("A locker term goes with term_kind 'term'.", pointer="/locker_term_id")
    starts = data.get("starts_on") or starts_default
    if kind == "custom":
        if data.get("ends_on") is None or data["ends_on"] < starts:
            raise ValidationFailed("A custom lease needs an end on or after its start.", pointer="/ends_on")
        return starts, data["ends_on"], 0, None
    ends = starts if kind == "day" else dates.add_interval(starts, _TERM_UNITS[kind], 1) - timedelta(days=1)
    return starts, ends, 0, None


def _new_lease(
    session: Db,
    principal: Principal,
    locker,
    client_id: UUID,
    data: dict,
    *,
    starts_default: date,
    renewed_from: LockerLease | None = None,
) -> LockerLease:
    """One lease and, for a fee, one charge for the whole term (the owner's decision: a term is one charge;
    renewal is a new lease and a new charge, never a silent extension)."""
    if locker.status != "active" or not resources.service.locker_room_is_active(session, locker.locker_room_id):
        raise Conflict("This locker is not in service.", code="locker-unavailable")
    starts, ends, predefined, term_id = _lease_dates(session, locker.location_id, data, starts_default)
    if renewed_from and starts <= renewed_from.ends_on:  # the same dates would be charged twice
        raise Conflict("The renewal must start after the current lease ends.", code="lease-overlaps")
    fee = data.get("fee_minor")
    if fee is None:
        fee = predefined
    elif fee != predefined:  # a keyed fee is a price override (security rules: a price field needs its own key)
        authorize(principal, OVERRIDE_RATE, location_id=locker.location_id)
    lease = LockerLease(
        location_id=locker.location_id, locker_id=locker.id, client_id=client_id, term_kind=data["term_kind"],
        locker_term_id=term_id, starts_on=starts, ends_on=ends, fee_minor=fee, charge_state="no_charge",
        renewed_from_lease_id=renewed_from and renewed_from.id,
    )  # fmt: skip
    session.add(lease)
    session.flush()  # uq_locker_lease_open: one uncleared lease per locker (locker-already-rented)
    if fee > 0:
        charge = billing.service.post_charge(
            session, client_id=client_id, location_id=lease.location_id, description=f"Locker {locker.number}",
            unit_price_minor=fee, source_context="rentals", source_type="locker_lease", source_id=lease.id,
            revenue_category_id=billing.service.default_revenue_category(session).id,
            service_starts_on=starts, service_ends_on=ends,
        )  # fmt: skip
        lease.charge_id, lease.charge_state = charge.id, "billed"
        if data.get("invoice_routing", "new_single") != "cart":
            billing.service.create_invoice_for_charges(session, [charge.id], bill_to_client_id=client_id)
    audit.record(session, LOCKER_RENT, lease, location_id=lease.location_id, changes={
        "locker_id": [None, str(locker.id)], "term_kind": [None, lease.term_kind], "ends_on": [None, ends.isoformat()],
        "fee_minor": [None, fee], **({"renewed_from_lease_id": [None, str(renewed_from.id)]} if renewed_from else {}),
    })  # fmt: skip
    session.flush()
    return lease


def create_locker_lease(session: Db, principal: Principal, data: dict) -> dict:
    """Rent a locker to a client for a term (RNT-17). Errors: locker-already-rented, locker-unavailable,
    term-ended."""
    locker = resources.service.get_locker(session, principal, data["locker_id"], lock=True)
    authorize(principal, LOCKER_RENT, location_id=locker.location_id)
    clients.service.load(session, principal, data["client_id"], LOCKER_RENT)  # out of client reach is 404
    clients.service.require_active(session, data["client_id"])
    today = platform.service.location_today(session, locker.location_id)
    lease = _new_lease(session, principal, locker, data["client_id"], data, starts_default=today)
    return _lease_views(session, [lease])[0]


def _clear(session: Db, lease: LockerLease, source: str) -> None:
    lease.cleared_at, lease.clear_source = clock.now(), source
    audit.record(session, LOCKER_RENT, lease, location_id=lease.location_id, changes={"clear_source": [None, source]})


def clear_locker_lease(session: Db, principal: Principal, lease_id: UUID) -> dict:
    """The locker was handed back (RNT-18). Idempotent; the charge stays as it is."""
    lease = _scoped(session, principal, LockerLease, lease_id, LOCKER_RENT, lock=True)
    if lease.cleared_at is None:
        _clear(session, lease, "staff")
        session.flush()
    return _lease_views(session, [lease])[0]


def clear_expired_locker_leases(session: Db, principal: Principal, data: dict) -> dict:
    """Clear every lapsed lease at a location, or in one of its locker rooms (RNT-18). There is no automatic
    release: an expired locker may still hold someone's belongings, so staff run this when they have checked."""
    location_id = _location(session, principal, data["location_id"])
    authorize(principal, LOCKER_RENT, location_id=location_id)
    today = platform.service.location_today(session, location_id)
    stmt = select(LockerLease).where(
        LockerLease.location_id == location_id, LockerLease.cleared_at.is_(None), LockerLease.ends_on < today
    )
    if data.get("locker_room_id"):
        stmt = stmt.where(LockerLease.locker_id.in_(resources.service.lockers_in_room(session, data["locker_room_id"])))
    leases = session.scalars(stmt.order_by(LockerLease.id).with_for_update()).all()
    for lease in leases:
        _clear(session, lease, "bulk_expired")
    session.flush()
    return {"cleared_count": len(leases)}


def renew_locker_lease(session: Db, principal: Principal, lease_id: UUID, data: dict) -> dict:
    """Renew into a new term (RES-08): the current lease is closed as renewed and a new one starts the day
    after it ends, or today when it has lapsed (or on the named term's dates), with its own charge. Errors:
    lease-cleared, lease-overlaps (the new dates start on or before the old lease's end)."""
    old = _scoped(session, principal, LockerLease, lease_id, LOCKER_RENT, lock=True)
    if old.cleared_at is not None:
        raise Conflict("This lease was already cleared.", code="lease-cleared")
    locker = resources.service.get_locker(session, principal, old.locker_id, lock=True)
    clients.service.require_active(session, old.client_id)
    _clear(session, old, "renewed")
    session.flush()
    today = platform.service.location_today(session, locker.location_id)
    lease = _new_lease(session, principal, locker, old.client_id, data,
                       starts_default=max(old.ends_on + timedelta(days=1), today), renewed_from=old)  # fmt: skip
    return _lease_views(session, [lease])[0]
