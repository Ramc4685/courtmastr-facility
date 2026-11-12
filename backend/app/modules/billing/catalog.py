"""Pre-defined items (BIL-14): the catalogue of reusable fees, selling one to a client, and the renewal job.

A sale freezes the item's terms (after per-sale overrides) into `catalog_item_sale.terms` and expands at once
into one charge per occurrence, each through `service.post_charge` with the origin (billing,
catalog_item_sale, sale id, occurrence index), so a retried sale or job never bills twice. Renewals are
created by `renew_due` one term at a time, never expanded up front.

Staff commands take a principal and check both gates. `addon_terms` is internal (ADR 0009 section 9):
memberships calls it while it sells a plan with item add-ons (MEM-04).
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.core.jobs import tenant_actor
from app.core.pagination import ListQuery, paginate
from app.modules import platform
from app.modules.billing import service
from app.modules.billing.domain import recurrence
from app.modules.billing.events import CatalogItemSaleEnded, CatalogItemSaleRenewed, CatalogItemSold
from app.modules.billing.models import CatalogItem, CatalogItemSale, Charge, RevenueCategory

_MANAGE = "billing.item.manage"
_SOURCE = ("billing", "catalog_item_sale")
_DAY = timedelta(days=1)
# What a sale snapshots from its item: the pricing and recurrence columns (data-model-money 1.1).
_TERMS = (
    "kind", "description", "additional_description", "internal_remarks", "length_count", "length_unit",
    "recurrence_unit", "recurrence_every", "recurrence_count", "fee_minor", "discount_pct", "discount_minor",
    "invoice_option", "is_autopay", "renew_lead_days", "revenue_category_id",
)  # fmt: skip
_PRICE = ("fee_minor", "discount_pct", "discount_minor")


def _in_scope(principal: Principal, location_id: UUID) -> None:
    """Outside the caller's locations is 404, also for reads that need no key."""
    if principal.kind != "system" and principal.location_ids is not None and location_id not in principal.location_ids:
        raise NotFound()


# --- the catalogue ------------------------------------------------------------------------------------------


def _check_item(session: Session, item: CatalogItem) -> None:
    """Readable 422s for what the table's checks would refuse anyway."""
    recurring = (item.recurrence_unit, item.recurrence_every, item.recurrence_count)
    if item.kind == "recurring" and None in recurring:
        raise ValidationFailed("A recurring item needs a unit, an interval and a count.", pointer="/recurrence_count")
    if item.kind == "one_off" and any(v is not None for v in recurring):
        raise ValidationFailed("A one-off item does not recur.", pointer="/recurrence_unit")
    if item.kind == "recurring" and item.length_count is not None:
        raise ValidationFailed("A recurring item's length is its recurrence.", pointer="/length_count")
    if (item.length_count is None) != (item.length_unit is None):
        raise ValidationFailed("Give both a length and its unit, or neither.", pointer="/length_unit")
    if item.start_mode == "fixed_date" and item.starts_on is None:
        raise ValidationFailed("A fixed start needs a start date.", pointer="/starts_on")
    if item.discount_pct is not None and item.discount_minor is not None:
        raise ValidationFailed("Give a percentage or an amount off, not both.", pointer="/discount_minor")
    if (item.discount_minor or 0) > item.fee_minor:
        raise ValidationFailed("The discount cannot exceed the fee.", pointer="/discount_minor")
    if item.renews_as_catalog_item_id is not None:
        if not item.is_auto_renew:
            raise ValidationFailed(
                "Only an auto-renewing item renews as another.", pointer="/renews_as_catalog_item_id"
            )
        target = service._get(
            session, CatalogItem, item.renews_as_catalog_item_id, pointer="/renews_as_catalog_item_id"
        )
        if target.location_id != item.location_id:
            raise ValidationFailed("An item renews as one at its own location.", pointer="/renews_as_catalog_item_id")
    service._get(session, RevenueCategory, item.revenue_category_id, pointer="/revenue_category_id")


def list_items(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Configuration read: any signed-in staff user, limited to their locations."""
    stmt = scope_query(select(CatalogItem), principal, CatalogItem.location_id)
    return paginate(
        session, stmt, query, id_column=CatalogItem.id,
        sort_fields={"description": CatalogItem.description, "created_at": CatalogItem.created_at},
        default_sort="description",
        filter_fields={"location_id": CatalogItem.location_id, "kind": CatalogItem.kind, "is_active": CatalogItem.is_active},
        search=(CatalogItem.description,),
    )  # fmt: skip


def get_item(session: Session, principal: Principal, item_id: UUID) -> CatalogItem:
    item = service._get(session, CatalogItem, item_id)
    _in_scope(principal, item.location_id)
    return item


def create_item(session: Session, principal: Principal, data: dict) -> CatalogItem:
    authorize(principal, _MANAGE)
    service._location_in_scope(session, principal, data["location_id"])
    item = CatalogItem(**data)
    _check_item(session, item)
    session.add(item)
    session.flush()
    audit.record(
        session, _MANAGE, item, location_id=item.location_id,
        changes={"kind": [None, item.kind], "fee_minor": [None, item.fee_minor]},
    )  # fmt: skip
    return item


def update_item(session: Session, principal: Principal, item_id: UUID, data: dict) -> CatalogItem:
    """Edits apply to later sales only: a sale keeps the terms it froze."""
    authorize(principal, _MANAGE)
    item = service._lock(session, CatalogItem, item_id)
    _in_scope(principal, item.location_id)
    if "location_id" in data and data["location_id"] != item.location_id:
        service._location_in_scope(session, principal, data["location_id"])
    for key, value in data.items():
        setattr(item, key, value)
    _check_item(session, item)
    audit.record(session, _MANAGE, item, location_id=item.location_id, changes=audit.diff(item))
    session.flush()
    return item


# --- selling (internal core shared by the desk and the renewal job) ----------------------------------------


def _terms(item: CatalogItem, overrides: dict | None = None) -> dict:
    terms = {key: getattr(item, key) for key in _TERMS} | (overrides or {})
    terms["discount_pct"] = None if terms["discount_pct"] is None else str(terms["discount_pct"])
    terms["revenue_category_id"] = str(terms["revenue_category_id"])
    terms["excluded_tax_ids"] = [str(tax_id) for tax_id in terms.get("excluded_tax_ids") or ()]
    return terms


def _periods(terms: dict, starts_on: date) -> list[tuple[date, date | None]]:
    keys = ("length_count", "length_unit", "recurrence_unit", "recurrence_every", "recurrence_count")
    return recurrence.occurrences(starts_on, kind=terms["kind"], **{key: terms[key] for key in keys})


def _describe(terms: dict, first: date, last: date | None) -> str:
    if terms["kind"] == "one_off":
        return terms["description"]
    return f"{terms['description']}: {first.isoformat()} to {last.isoformat()}"


def _create_sale(
    session: Session,
    item: CatalogItem,
    *,
    client_id: UUID,
    terms: dict,
    starts_on: date,
    is_auto_renew: bool,
    renews_as_catalog_item_id: UUID | None,
    previous_sale_id: UUID | None = None,
) -> CatalogItemSale:
    """Write the sale, post one charge per occurrence and invoice them as the terms say."""
    today = platform.service.location_today(session, item.location_id)
    periods = _periods(terms, starts_on)
    ends_on = recurrence.term_end(periods)
    is_auto_renew = is_auto_renew and ends_on is not None
    sale = CatalogItemSale(
        catalog_item_id=item.id, client_id=client_id, location_id=item.location_id, terms=terms, sold_on=today,
        starts_on=starts_on, ends_on=ends_on, is_auto_renew=is_auto_renew,
        renew_on=recurrence.renew_on(ends_on, terms["renew_lead_days"]) if is_auto_renew else None,
        renews_as_catalog_item_id=renews_as_catalog_item_id if is_auto_renew else None,
        previous_sale_id=previous_sale_id, sold_by_staff_user_id=service._staff_id(session),
    )  # fmt: skip
    session.add(sale)
    session.flush()
    discount = recurrence.discount(
        terms["fee_minor"], terms["discount_pct"] and Decimal(terms["discount_pct"]), terms["discount_minor"]
    )
    charges = [
        service.post_charge(
            session,
            client_id=client_id,
            location_id=item.location_id,
            description=_describe(terms, first, last),
            unit_price_minor=terms["fee_minor"],
            discount_minor=discount,
            source_context=_SOURCE[0],
            source_type=_SOURCE[1],
            source_id=sale.id,
            source_line_no=index,
            revenue_category_id=UUID(terms["revenue_category_id"]),
            revenue_on=max(first, today),
            exclude_tax_ids=[UUID(tax_id) for tax_id in terms["excluded_tax_ids"]],
            additional_description=terms["additional_description"],
            internal_remarks=terms["internal_remarks"],
            service_starts_on=first,
            service_ends_on=last,
        )  # fmt: skip
        for index, (first, last) in enumerate(periods)
    ]
    billable = [(charge, first) for charge, (first, _) in zip(charges, periods, strict=True) if charge.total_minor > 0]
    invoice = {"origin": "system" if previous_sale_id else "staff", "is_autopay": terms["is_autopay"]}
    if billable and terms["invoice_option"] == "single_invoice":
        service.create_invoice_for_charges(
            session, [charge.id for charge, _ in billable], due_on=max(starts_on, today), **invoice
        )
    elif terms["invoice_option"] == "invoice_per_occurrence":
        for charge, first in billable:
            service.create_invoice_for_charges(session, [charge.id], due_on=max(first, today), **invoice)
    return sale


def sell(
    session: Session,
    item_id: UUID,
    *,
    client_id: UUID,
    starts_on: date | None = None,
    overrides: dict | None = None,
    is_auto_renew: bool | None = None,
) -> CatalogItemSale:
    """Sell an active item to a client (internal: the caller authorized it, price overrides included)."""
    item = service._get(session, CatalogItem, item_id)
    if not item.is_active:
        raise ValidationFailed("This item is no longer sold.", pointer="/catalog_item_id")
    terms = _terms(item, overrides)
    if terms["discount_pct"] is not None and terms["discount_minor"] is not None:
        raise ValidationFailed("Give a percentage or an amount off, not both.", pointer="/discount_minor")
    start = item.starts_on if item.start_mode == "fixed_date" else starts_on
    start = start or platform.service.location_today(session, item.location_id)
    sale = _create_sale(
        session, item, client_id=client_id, terms=terms, starts_on=start,
        is_auto_renew=item.is_auto_renew if is_auto_renew is None else is_auto_renew,
        renews_as_catalog_item_id=item.renews_as_catalog_item_id,
    )  # fmt: skip
    audit.record(
        session, "billing.charge.create", sale, location_id=sale.location_id,
        changes={"catalog_item_id": [None, str(item.id)], "fee_minor": [None, terms["fee_minor"]]},
    )  # fmt: skip
    events.publish(session, CatalogItemSold(**_ref(sale)), sale.id)
    session.flush()
    return sale


def _ref(sale: CatalogItemSale) -> dict:
    return {"catalog_item_sale_id": sale.id, "catalog_item_id": sale.catalog_item_id, "client_id": sale.client_id}


def _charges(session: Session, sale_id: UUID) -> list[Charge]:
    stmt = select(Charge).where(
        Charge.source_context == _SOURCE[0], Charge.source_type == _SOURCE[1], Charge.source_id == sale_id,
        Charge.kind == "standard",
    )  # fmt: skip
    return list(session.scalars(stmt.order_by(Charge.source_line_no)))


def sale_view(session: Session, sale: CatalogItemSale) -> dict:
    charges = _charges(session, sale.id)
    return {c.key: getattr(sale, c.key) for c in CatalogItemSale.__table__.columns} | {
        "charge_ids": [charge.id for charge in charges],
        "invoice_ids": list(dict.fromkeys(charge.invoice_id for charge in charges if charge.invoice_id)),
    }  # fmt: skip


def sell_item(session: Session, principal: Principal, item_id: UUID, data: dict) -> dict:
    """The desk sale (BIL-14). A fee or discount other than the item's needs billing.charge.override_price."""
    item = service._get(session, CatalogItem, item_id)
    authorize(principal, "billing.charge.create", location_id=item.location_id)
    overrides = {key: data[key] for key in _PRICE if key in data}
    if overrides.get("discount_pct") is not None:
        overrides.setdefault("discount_minor", None)
    elif overrides.get("discount_minor") is not None:
        overrides["discount_pct"] = None
    if any(overrides[key] != getattr(item, key) for key in overrides):
        authorize(principal, "billing.charge.override_price", location_id=item.location_id)
    for key in ("invoice_option", "is_autopay"):
        if data.get(key) is not None:
            overrides[key] = data[key]
    overrides["excluded_tax_ids"] = data.get("excluded_tax_ids") or []
    sale = sell(
        session, item.id, client_id=data["client_id"], starts_on=data.get("starts_on"), overrides=overrides,
        is_auto_renew=data.get("is_auto_renew"),
    )  # fmt: skip
    return sale_view(session, sale)


def list_sales(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "billing.charge.read")
    page = paginate(
        session, select(CatalogItemSale), query, id_column=CatalogItemSale.id,
        sort_fields={"starts_on": CatalogItemSale.starts_on, "created_at": CatalogItemSale.created_at},
        default_sort="-starts_on",
        filter_fields={
            "client_id": CatalogItemSale.client_id, "catalog_item_id": CatalogItemSale.catalog_item_id,
            "status": CatalogItemSale.status, "location_id": CatalogItemSale.location_id,
        },
    )  # fmt: skip
    return page | {"data": [sale_view(session, sale) for sale in page["data"]]}


def _end(session: Session, sale: CatalogItemSale, status: str, *, reason: str | None = None) -> None:
    previous = sale.status
    sale.status = status
    audit.record(
        session, "billing.charge.reverse" if status == "cancelled" else "billing.catalog_item_sale.end", sale,
        location_id=sale.location_id, reason=reason, changes={"status": [previous, status]},
    )  # fmt: skip
    events.publish(session, CatalogItemSaleEnded(**_ref(sale), status=status), sale.id)


def cancel_sale(session: Session, principal: Principal, sale_id: UUID, data: dict) -> dict:
    """Stop a sale: every occurrence that has not started yet is reversed (money applied to it becomes the
    payer's account credit), and it does not renew. Occurrences already under way stay billed."""
    sale = service._lock(session, CatalogItemSale, sale_id)
    authorize(principal, "billing.charge.reverse", location_id=sale.location_id)
    if sale.status != "active":
        raise Conflict("Only an active sale can be cancelled.")
    today = platform.service.location_today(session, sale.location_id)
    for charge in _charges(session, sale.id):
        if charge.status == "active" and charge.service_starts_on > today:
            service.reverse(session, charge.id, reason=data["reason"])
    _end(session, sale, "cancelled", reason=data["reason"])
    session.flush()
    return sale_view(session, sale)


# --- the renewal job ----------------------------------------------------------------------------------------


def renew(session: Session, sale: CatalogItemSale) -> CatalogItemSale | None:
    """Create the successor term once (`uq_catalog_item_sale_previous`). Renewing "as" a named item takes that
    item's current price and settings; otherwise the sale's own frozen terms repeat. An inactive target ends
    the sale instead."""
    existing = session.scalar(select(CatalogItemSale).where(CatalogItemSale.previous_sale_id == sale.id))
    if existing is not None:
        return existing
    target = session.get(CatalogItem, sale.renews_as_catalog_item_id or sale.catalog_item_id)
    if sale.renews_as_catalog_item_id is not None:
        if not target.is_active:
            _end(session, sale, "ended")
            return None
        terms, auto, renews_as = _terms(target), target.is_auto_renew, target.renews_as_catalog_item_id
    else:
        terms, auto, renews_as = sale.terms, True, None
    successor = _create_sale(
        session, target, client_id=sale.client_id, terms=terms, starts_on=sale.ends_on + _DAY,
        is_auto_renew=auto, renews_as_catalog_item_id=renews_as, previous_sale_id=sale.id,
    )  # fmt: skip
    sale.status = "renewed"
    audit.record(
        session, "billing.catalog_item_sale.renew", sale, location_id=sale.location_id,
        changes={"status": ["active", "renewed"], "successor": [None, str(successor.id)]},
    )  # fmt: skip
    events.publish(session, CatalogItemSaleRenewed(**_ref(sale), successor_sale_id=successor.id), sale.id)
    session.flush()
    return successor


def renew_due(session: Session) -> dict:
    """Renew every auto-renewing sale whose renewal day has come at its location, and end the sales whose term
    is over. Idempotent: a renewed or ended sale is no longer a candidate, and a successor exists only once.
    A sale that cannot renew (the client was disabled, the period is locked) is skipped and retried next run."""
    horizon = clock.now().date() + _DAY  # no location's today is later than UTC's tomorrow
    renewed = ended = failed = 0
    due = select(CatalogItemSale).where(
        CatalogItemSale.status == "active", CatalogItemSale.is_auto_renew, CatalogItemSale.renew_on <= horizon
    )
    for sale in session.scalars(
        due.order_by(CatalogItemSale.renew_on, CatalogItemSale.id).with_for_update(skip_locked=True)
    ):
        if sale.renew_on > platform.service.location_today(session, sale.location_id):
            continue
        try:
            with session.begin_nested():
                renewed += renew(session, sale) is not None
        except DomainError:
            failed += 1
    over = select(CatalogItemSale).where(
        CatalogItemSale.status == "active", CatalogItemSale.ends_on < horizon, CatalogItemSale.is_auto_renew.is_(False)
    )
    for sale in session.scalars(over.with_for_update(skip_locked=True)):
        if sale.ends_on < platform.service.location_today(session, sale.location_id):
            _end(session, sale, "ended")
            ended += 1
    session.flush()
    return {"renewed": renewed, "ended": ended, "failed": failed}


@tenant_actor
def renew_catalog_item_sales(session: Session) -> dict:
    """The hourly clock's message (app/scheduler.py); the work is renew_due."""
    return renew_due(session)


# --- membership add-ons (MEM-04), internal ----------------------------------------------------------------


def addon_terms(session: Session, item_id: UUID, *, location_id: UUID, pointer: str = "/addons") -> dict:
    """What one unit of an item add-on costs on a membership sold at `location_id`: the per-occurrence net
    after the item's discount, its revenue category, and whether it recurs (billed with every dues period)
    or not (billed once, with the first)."""
    item = service._get(session, CatalogItem, item_id, pointer=pointer)
    if not item.is_active or item.location_id != location_id:
        raise ValidationFailed("This item is not sold at this location.", pointer=pointer)
    net = item.fee_minor - recurrence.discount(item.fee_minor, item.discount_pct, item.discount_minor)
    return {
        "catalog_item_id": item.id, "description": item.description, "amount_minor": net,
        "is_recurring": item.kind == "recurring", "revenue_category_id": item.revenue_category_id,
    }  # fmt: skip


def item_exists(session: Session, item_id: UUID) -> bool:
    return session.get(CatalogItem, item_id) is not None


def revenue_category_of(session: Session, item_id: UUID) -> UUID:
    """Where an item add-on's revenue goes, read when its schedule row is billed (the item may be inactive by then)."""
    return service._get(session, CatalogItem, item_id).revenue_category_id
