"""Collections and past-due enforcement (BIL-20, BIL-22, PAY-07; Phase 9 chip D).

Collections tags are a tenant list; a client in collections has one profile row carrying its current tag.
The report lists the clients in collections with what they owe. While `is_portal_blocked_when_past_due` is
on at an invoice's location, a payer with that invoice past due cannot buy or book in the portal (checked on
the server for every portal request, `PORTAL_PURCHASE_ROUTES`); paying and managing their own records stay
open. Memberships reads `unpaid_past_due` and `still_owing` to suspend for non-payment (MEM-14) without
importing billing's tables.
"""

from datetime import date
from uuid import UUID

from fastapi import Request
from sqlalchemy import Integer, cast, func, select, tuple_
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize
from app.core.auth.deps import add_client_guard
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import clients, platform
from app.modules.billing import catalogue
from app.modules.billing.models import (
    BillingSettings,
    Charge,
    ClientCollectionsProfile,
    CollectionsTag,
    Invoice,
    PaymentMethod,
)

_READ, _MANAGE, _TAGS = "billing.collections.read", "billing.collections.manage", "billing.collections_tag.manage"
_OWED = ("open", "partially_paid", "payment_pending")
_PAST_DUE = (
    Invoice.past_due_since_on.is_not(None),
    Invoice.balance_minor > 0,
    Invoice.status.in_(("open", "partially_paid")),
)


# --- tags --------------------------------------------------------------------------------------------------


def list_tags(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _READ)
    return paginate(
        session, select(CollectionsTag), query, id_column=CollectionsTag.id, sort_fields={"name": CollectionsTag.name},
        default_sort="name", filter_fields={"is_active": CollectionsTag.is_active}, search=(CollectionsTag.name,),
    )  # fmt: skip


def create_tag(session: Session, principal: Principal, data: dict) -> CollectionsTag:
    authorize(principal, _TAGS)
    tag = CollectionsTag(**data)
    session.add(tag)
    changes = audit.diff(tag)  # before the flush: diff reads the pending state
    session.flush()
    audit.record(session, _TAGS, tag, changes=changes)
    return tag


def update_tag(session: Session, principal: Principal, tag_id: UUID, data: dict) -> CollectionsTag:
    authorize(principal, _TAGS)
    tag = session.get(CollectionsTag, tag_id, with_for_update=True)
    if tag is None:
        raise NotFound()
    for key, value in data.items():
        setattr(tag, key, value)
    audit.record(session, _TAGS, tag, changes=audit.diff(tag))
    session.flush()
    return tag


# --- the client's collections profile ----------------------------------------------------------------------


def _profile(session: Session, client_id: UUID, *, lock: bool = False) -> ClientCollectionsProfile | None:
    stmt = select(ClientCollectionsProfile).where(ClientCollectionsProfile.client_id == client_id)
    return session.scalar(stmt.with_for_update() if lock else stmt)


def get_profile(session: Session, principal: Principal, client_id: UUID) -> ClientCollectionsProfile:
    authorize(principal, _READ)
    clients.service.get(session, client_id)
    profile = _profile(session, client_id)
    if profile is None:
        raise NotFound("This client is not in collections.", code="not-in-collections")
    return profile


def put_profile(session: Session, principal: Principal, client_id: UUID, data: dict) -> ClientCollectionsProfile:
    """Place a client in collections, or change their tag, date or notes. Gated at the client's home location.
    A tag no longer in use cannot be newly given, but a profile already carrying it keeps it."""
    client = clients.service.get(session, client_id)
    authorize(principal, _MANAGE, location_id=client.home_location_id)
    tag = session.get(CollectionsTag, data["collections_tag_id"])
    if tag is None:
        raise ValidationFailed("Unknown collections tag.", pointer="/collections_tag_id")
    profile = _profile(session, client_id, lock=True)
    if not tag.is_active and (profile is None or profile.collections_tag_id != tag.id):
        raise ValidationFailed("This tag is no longer used.", pointer="/collections_tag_id")
    placed_on = data.get("placed_on") or (profile and profile.placed_on)
    placed_on = placed_on or platform.service.location_today(session, client.home_location_id)
    if profile is None:
        profile = ClientCollectionsProfile(client_id=client_id)
        session.add(profile)
    profile.collections_tag_id, profile.placed_on, profile.notes = tag.id, placed_on, data.get("notes")
    profile.updated_by_staff_user_id = principal.staff_user_id
    changes = audit.diff(profile)
    session.flush()
    audit.record(session, _MANAGE, profile, location_id=client.home_location_id, changes=changes)
    return profile


def delete_profile(session: Session, principal: Principal, client_id: UUID) -> None:
    """Take a client out of collections."""
    client = clients.service.get(session, client_id)
    authorize(principal, _MANAGE, location_id=client.home_location_id)
    profile = _profile(session, client_id, lock=True)
    if profile is None:
        raise NotFound("This client is not in collections.", code="not-in-collections")
    audit.record(
        session, _MANAGE, profile, location_id=client.home_location_id,
        changes={"collections_tag_id": [str(profile.collections_tag_id), None]},
    )  # fmt: skip
    session.delete(profile)
    session.flush()


def _owed(session: Session, client_ids: list[UUID]) -> dict[UUID | None, dict]:
    """What each payer owes now: open balance, the past-due part and the oldest past-due date."""
    past_due = Invoice.past_due_since_on.is_not(None)
    rows = session.execute(
        select(
            Invoice.bill_to_client_id,
            func.coalesce(func.sum(Invoice.balance_minor), 0),
            func.coalesce(func.sum(Invoice.balance_minor).filter(past_due), 0),
            func.min(Invoice.due_on).filter(past_due),
        )
        .where(Invoice.bill_to_client_id.in_(client_ids), Invoice.status.in_(_OWED), Invoice.balance_minor > 0)
        .group_by(Invoice.bill_to_client_id)
    ).all()
    return {row[0]: {"balance_minor": row[1], "past_due_minor": row[2], "oldest_past_due_on": row[3]} for row in rows}


def report(session: Session, principal: Principal, query: ListQuery) -> dict:
    """The collections report (BIL-20): every client in collections, with tag and what they owe. Filter
    `collections_tag_id`; sort `placed_on` (default, oldest first)."""
    authorize(principal, _READ)
    page = paginate(
        session, select(ClientCollectionsProfile), query, id_column=ClientCollectionsProfile.id,
        sort_fields={"placed_on": ClientCollectionsProfile.placed_on}, default_sort="placed_on",
        filter_fields={"collections_tag_id": ClientCollectionsProfile.collections_tag_id},
    )  # fmt: skip
    profiles = page["data"]
    owed = _owed(session, [p.client_id for p in profiles])
    tags = dict(session.execute(select(CollectionsTag.id, CollectionsTag.name).where(
        CollectionsTag.id.in_({p.collections_tag_id for p in profiles}))).all())  # fmt: skip
    nothing = {"balance_minor": 0, "past_due_minor": 0, "oldest_past_due_on": None}
    rows = []
    for profile in profiles:
        client = clients.service.get(session, profile.client_id)
        rows.append({
            "client_id": profile.client_id, "client_name": clients.service.display_name(client),
            "collections_tag_id": profile.collections_tag_id, "collections_tag_name": tags[profile.collections_tag_id],
            "placed_on": profile.placed_on, "notes": profile.notes, **owed.get(profile.client_id, nothing),
        })  # fmt: skip
    return {"data": rows, "page": page["page"]}


# --- expiring cards (PAY-07) -------------------------------------------------------------------------------


def expiring_cards(session: Session, principal: Principal, through: str | None, query: ListQuery) -> dict:
    """Active stored cards that expire through `through` (YYYY-MM, default: next month), with their holder.
    Already-expired cards are included: they will decline. Sorted by expiry, soonest first."""
    authorize(principal, "billing.payment_method.read")
    # shortcut: the month is read in UTC; a card network expires a card at month end, so a day either way is moot.
    today = clock.now().date()
    if through:
        try:
            year, month = (int(part) for part in through.split("-"))
            if not 1 <= month <= 12:
                raise ValueError
        except ValueError:
            raise ValidationFailed("Use YYYY-MM.", pointer="/through") from None
    else:
        year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    stmt = select(PaymentMethod).where(
        PaymentMethod.kind == "card", PaymentMethod.status == "active",
        tuple_(PaymentMethod.exp_year, PaymentMethod.exp_month) <= (year, month),
    )  # fmt: skip
    page = paginate(
        session, stmt, query, id_column=PaymentMethod.id,
        sort_fields={"expiry": cast(PaymentMethod.exp_year, Integer) * 100 + PaymentMethod.exp_month}, default_sort="expiry",
        filter_fields={"is_autopay": PaymentMethod.is_autopay, "client_id": PaymentMethod.client_id},
    )  # fmt: skip
    rows = []
    for card in page["data"]:
        holder = clients.service.get(session, card.client_id)
        rows.append({
            "id": card.id, "client_id": card.client_id, "client_name": clients.service.display_name(holder),
            "brand": card.brand, "last4": card.last4, "exp_month": card.exp_month, "exp_year": card.exp_year,
            "is_autopay": card.is_autopay, "is_expired": (card.exp_year, card.exp_month) < (today.year, today.month),
        })  # fmt: skip
    return {"data": rows, "page": page["page"]}


# --- past due: the portal lockout (BIL-22) and the reads memberships uses (MEM-14) ------------------------

# Portal POST routes that buy or book. While locked these are refused; every other portal route (paying,
# stored methods, profile, documents, cancelling and opting out) stays open. A test classifies every portal
# POST route as locked or open, so a new purchase route cannot slip past this list.
PORTAL_PURCHASE_ROUTES = frozenset({
    "/portal/client-packages", "/portal/coupon-quotes", "/portal/enrollments", "/portal/membership-contracts",
    "/portal/membership-contracts/quote", "/portal/registration-checkouts",
    "/portal/registration-checkouts/{checkout_id}/confirm", "/portal/registration-checkouts/{checkout_id}/items",
    "/portal/rentals", "/portal/rentals/{rental_id}/confirm", "/portal/waitlist-entries",
    "/portal/waitlist-entries/{waitlist_entry_id}/claim",
})  # fmt: skip


def is_portal_locked(session: Session, client_ids: list[UUID]) -> bool:
    """True when any of these clients is the payer of a past-due invoice at a location that blocks the portal."""
    if not client_ids:
        return False
    location_ids = session.scalars(
        select(Invoice.location_id).where(Invoice.bill_to_client_id.in_(client_ids), *_PAST_DUE).distinct()
    ).all()
    return any(catalogue.settings_for(session, loc).is_portal_blocked_when_past_due for loc in location_ids)


def _portal_guard(session: Session, principal: Principal, request: Request) -> None:
    if request.method != "POST" or principal.identity_id is None:
        return
    path = getattr(request.scope.get("route"), "path", "")
    at = path.find("/portal/")
    if at < 0 or path[at:] not in PORTAL_PURCHASE_ROUTES:
        return
    # Every client the identity may act for (direct access and one-hop relationships), as purchases accept.
    if is_portal_locked(session, clients.households.actable_client_ids(session, principal.identity_id)):
        raise PermissionDenied(
            "Your account has a past-due balance. Please pay it before booking or buying online.",
            code="portal-past-due",
        )  # fmt: skip


add_client_guard(_portal_guard)


def unpaid_past_due(session: Session, charge_ids: list[UUID], *, since_on_or_before: date) -> list[UUID]:
    """Internal (memberships, MEM-14): the invoices holding any of these charges that still owe and have been
    past due since the given date or earlier, oldest due first."""
    if not charge_ids:
        return []
    return list(session.scalars(
        select(Invoice.id).join(Charge, Charge.invoice_id == Invoice.id)
        .where(Charge.id.in_(charge_ids), *_PAST_DUE, Invoice.past_due_since_on <= since_on_or_before)
        .group_by(Invoice.id, Invoice.due_on).order_by(Invoice.due_on, Invoice.id)
    ))  # fmt: skip


def still_owing(session: Session, invoice_ids: list[UUID]) -> set[UUID]:
    """Internal (memberships, MEM-14): which of these invoices are still open with a balance (a payment, a
    reversal or a void clears one)."""
    if not invoice_ids:
        return set()
    stmt = select(Invoice.id).where(Invoice.id.in_(invoice_ids), Invoice.balance_minor > 0, Invoice.status.in_(_OWED))
    return set(session.scalars(stmt))


def is_suspension_rule_on(session: Session) -> bool:
    """Internal (memberships, MEM-14): whether any location suspends memberships for non-payment."""
    stmt = select(BillingSettings.id).where(BillingSettings.membership_suspend_after_days.is_not(None)).limit(1)
    return session.scalar(stmt) is not None
