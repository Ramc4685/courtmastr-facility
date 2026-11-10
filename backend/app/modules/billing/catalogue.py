"""Billing configuration: revenue categories, taxes and dated rates, tender types, billing settings, coupons.

Staff commands take a principal and authorize it. `settings_for`, `quote_coupon`, `redeem_coupon` and
`release_coupon` are internal (ADR 0009 section 9): selling contexts call them inside their own use case.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.modules import platform
from app.modules.billing import service
from app.modules.billing.domain.money import round_half_up
from app.modules.billing.domain.schedule import split_by_weight
from app.modules.billing.models import (
    BillingSettings,
    Charge,
    ChargeTax,
    Coupon,
    CouponRedemption,
    RevenueCategory,
    RevenueCategoryTax,
    Tax,
    TaxRate,
    TenderType,
)

# --- revenue categories (BIL-13) ---------------------------------------------------------------------------


def _category_detail(session: Session, category: RevenueCategory) -> dict:
    tax_ids = session.scalars(
        select(RevenueCategoryTax.tax_id).where(RevenueCategoryTax.revenue_category_id == category.id)
    ).all()
    return {**{c.key: getattr(category, c.key) for c in RevenueCategory.__table__.columns}, "tax_ids": tax_ids}


def _set_category_taxes(session: Session, category: RevenueCategory, tax_ids: list[UUID]) -> None:
    for tax_id in tax_ids:
        service._get(session, Tax, tax_id, pointer="/tax_ids")
    session.execute(delete(RevenueCategoryTax).where(RevenueCategoryTax.revenue_category_id == category.id))
    session.add_all(RevenueCategoryTax(revenue_category_id=category.id, tax_id=tax_id) for tax_id in set(tax_ids))


def _check_parent(session: Session, category_id: UUID | None, parent_id: UUID | None) -> None:
    """The tree is an adjacency list: walk up from the new parent and refuse a loop."""
    seen = {category_id}
    while parent_id is not None:
        if parent_id in seen:
            raise ValidationFailed("A category cannot sit under itself.", pointer="/parent_id")
        seen.add(parent_id)
        parent_id = service._get(session, RevenueCategory, parent_id, pointer="/parent_id").parent_id


def get_revenue_category(session: Session, principal: Principal, category_id: UUID) -> dict:
    return _category_detail(session, service._get(session, RevenueCategory, category_id))


def create_revenue_category(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, "billing.revenue_category.manage")
    tax_ids = data.pop("tax_ids", None) or []
    _check_parent(session, None, data.get("parent_id"))
    if session.scalar(select(RevenueCategory.id).where(RevenueCategory.code == data["code"])):
        raise Conflict("A revenue category with this code already exists.", code="already-exists")
    category = RevenueCategory(**data)
    session.add(category)
    session.flush()
    _set_category_taxes(session, category, tax_ids)
    audit.record(session, "billing.revenue_category.manage", category, changes={"code": [None, category.code]})
    session.flush()
    return _category_detail(session, category)


def update_revenue_category(session: Session, principal: Principal, category_id: UUID, data: dict) -> dict:
    authorize(principal, "billing.revenue_category.manage")
    category = service._lock(session, RevenueCategory, category_id)
    tax_ids = data.pop("tax_ids", None)
    if "parent_id" in data:
        _check_parent(session, category.id, data["parent_id"])
    if category.system_key and data.get("is_active") is False:
        raise Conflict("A built-in category cannot be deactivated.", code="system-row")
    for key, value in data.items():
        setattr(category, key, value)
    changes = audit.diff(category)
    if tax_ids is not None:
        _set_category_taxes(session, category, tax_ids)
        changes["tax_ids"] = True
    audit.record(session, "billing.revenue_category.manage", category, changes=changes)
    session.flush()
    return _category_detail(session, category)


# --- taxes and dated rates (BIL-12) ------------------------------------------------------------------------


def _tax_detail(session: Session, tax: Tax) -> dict:
    rates = session.scalars(select(TaxRate).where(TaxRate.tax_id == tax.id).order_by(TaxRate.effective_from_on)).all()
    return {**{c.key: getattr(tax, c.key) for c in Tax.__table__.columns}, "rates": rates}


def list_taxes(session: Session, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, select(Tax), query, id_column=Tax.id, sort_fields={"code": Tax.code}, default_sort="code",
        filter_fields={"is_active": Tax.is_active}, search=(Tax.code, Tax.label),
    )  # fmt: skip


def get_tax(session: Session, principal: Principal, tax_id: UUID) -> dict:
    return _tax_detail(session, service._get(session, Tax, tax_id))


def create_tax(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, "billing.tax.manage")
    if session.scalar(select(Tax.id).where(Tax.code == data["code"])):
        raise Conflict("A tax with this code already exists.", code="already-exists")
    tax = service.create_tax(
        session, code=data["code"], label=data["label"], rate=data["rate"], effective_from_on=data["effective_from_on"]
    )
    tax.remarks = data.get("remarks")
    session.flush()
    return _tax_detail(session, tax)


def update_tax(session: Session, principal: Principal, tax_id: UUID, data: dict) -> dict:
    """Label, remarks and the date it stops applying. Deactivating never touches posted charges: it only
    stops the tax being added to charges whose revenue date is on or after `deactivated_on`."""
    authorize(principal, "billing.tax.manage")
    tax = service._lock(session, Tax, tax_id)
    for key in ("label", "remarks"):
        if key in data:
            setattr(tax, key, data[key])
    if "is_active" in data:
        tax.is_active = data["is_active"]
        today = clock.now().date()
        tax.deactivated_on = None if tax.is_active else (data.get("deactivated_on") or today)
    audit.record(session, "billing.tax.manage", tax, changes=audit.diff(tax))
    session.flush()
    return _tax_detail(session, tax)


def _rate_in_use(session: Session, rate: TaxRate) -> bool:
    """A rate is frozen once a charge could have used it: any charge taxed by this tax at this rate's dates."""
    later = session.scalar(
        select(func.min(TaxRate.effective_from_on)).where(
            TaxRate.tax_id == rate.tax_id, TaxRate.effective_from_on > rate.effective_from_on
        )
    )
    stmt = (
        select(func.count())
        .select_from(ChargeTax)
        .join(Charge, Charge.id == ChargeTax.charge_id)
        .where(ChargeTax.tax_id == rate.tax_id, Charge.revenue_on >= rate.effective_from_on)
    )
    if later is not None:
        stmt = stmt.where(Charge.revenue_on < later)
    return bool(session.scalar(stmt))


def add_tax_rate(session: Session, principal: Principal, tax_id: UUID, data: dict) -> dict:
    authorize(principal, "billing.tax.manage")
    tax = service._lock(session, Tax, tax_id)
    taken = session.scalar(
        select(TaxRate.id).where(TaxRate.tax_id == tax.id, TaxRate.effective_from_on == data["effective_from_on"])
    )
    if taken:
        raise Conflict("This tax already has a rate starting on that date.", code="already-exists")
    session.add(TaxRate(tax_id=tax.id, **data))
    audit.record(
        session, "billing.tax.manage", tax,
        changes={"rate": [None, str(data["rate"])], "effective_from_on": [None, str(data["effective_from_on"])]},
    )  # fmt: skip
    session.flush()
    return _tax_detail(session, tax)


def _editable_rate(session: Session, tax_id: UUID, rate_id: UUID) -> tuple[Tax, TaxRate]:
    tax = service._lock(session, Tax, tax_id)
    rate = service._get(session, TaxRate, rate_id)
    if rate.tax_id != tax.id:
        raise NotFound()
    if _rate_in_use(session, rate):
        raise Conflict("Charges were already taxed at this rate; add a new dated rate instead.", code="tax-rate-in-use")
    return tax, rate


def update_tax_rate(session: Session, principal: Principal, tax_id: UUID, rate_id: UUID, data: dict) -> dict:
    authorize(principal, "billing.tax.manage")
    tax, rate = _editable_rate(session, tax_id, rate_id)
    for key, value in data.items():
        setattr(rate, key, value)
    audit.record(session, "billing.tax.manage", tax, changes={"rate": [None, str(rate.rate)]})
    session.flush()
    return _tax_detail(session, tax)


def delete_tax_rate(session: Session, principal: Principal, tax_id: UUID, rate_id: UUID) -> None:
    authorize(principal, "billing.tax.manage")
    tax, rate = _editable_rate(session, tax_id, rate_id)
    if session.scalar(select(func.count()).select_from(TaxRate).where(TaxRate.tax_id == tax.id)) == 1:
        raise Conflict("A tax keeps at least one rate; deactivate the tax instead.", code="last-tax-rate")
    session.delete(rate)
    audit.record(session, "billing.tax.manage", tax, changes={"rate_removed": [str(rate.rate), None]})
    session.flush()


# --- tender types (PAY-02) ---------------------------------------------------------------------------------


def list_tender_types(session: Session, principal: Principal) -> list[TenderType]:
    service.ensure_defaults(session)
    return list(session.scalars(select(TenderType).order_by(TenderType.sort_order, TenderType.label)))


def create_tender_type(session: Session, principal: Principal, data: dict) -> TenderType:
    """A tenant-labelled record-only tender ("PayPal", "Venmo"). Built-in kinds exist once and are seeded."""
    authorize(principal, "billing.settings.manage")
    service.ensure_defaults(session)
    if session.scalar(select(TenderType.id).where(TenderType.label == data["label"])):
        raise Conflict("A payment method with this label already exists.", code="already-exists")
    tender = TenderType(**data, is_processed=False, is_optional=True)
    session.add(tender)
    session.flush()
    audit.record(session, "billing.settings.manage", tender, changes={"label": [None, tender.label]})
    return tender


def update_tender_type(session: Session, principal: Principal, tender_id: UUID, data: dict) -> TenderType:
    authorize(principal, "billing.settings.manage")
    tender = service._lock(session, TenderType, tender_id)
    if data.get("is_enabled") is False and not tender.is_optional:
        raise Conflict("Card, bank debit and cash cannot be hidden.", code="tender-required")
    for key, value in data.items():
        setattr(tender, key, value)
    audit.record(session, "billing.settings.manage", tender, changes=audit.diff(tender))
    session.flush()
    return tender


# --- billing settings (BIL-16) -----------------------------------------------------------------------------


def _settings_row(session: Session, location_id: UUID | None, *, create: bool) -> BillingSettings | None:
    stmt = select(BillingSettings).where(
        BillingSettings.location_id.is_(None) if location_id is None else BillingSettings.location_id == location_id
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None and create:
        session.execute(
            pg_insert(BillingSettings)
            .values(id=new_id(), tenant_id=session.info["tenant_id"], location_id=location_id)
            .on_conflict_do_nothing()
        )
        row = session.execute(stmt).scalar_one()
    return row


def settings_for(session: Session, location_id: UUID | None = None) -> BillingSettings:
    """The settings in force at a location: its override row when one exists, else the tenant's row (created
    with the documented defaults on first read)."""
    override = _settings_row(session, location_id, create=False) if location_id else None
    return override or _settings_row(session, None, create=True)


def get_settings(session: Session, principal: Principal, location_id: UUID | None) -> BillingSettings:
    if location_id is not None:
        platform.service.get_location(session, principal, location_id)
    return settings_for(session, location_id)


def put_settings(session: Session, principal: Principal, location_id: UUID | None, data: dict) -> BillingSettings:
    """Replace the tenant's settings, or create or replace one location's override."""
    authorize(principal, "billing.settings.manage")
    if location_id is not None:
        platform.service.get_location(session, principal, location_id)
    if any(days < 1 for days in data.get("autopay_retry_offset_days", [])):
        raise ValidationFailed("Retry offsets are days after the first decline.", pointer="/autopay_retry_offset_days")
    row = _settings_row(session, location_id, create=True)
    for key, value in data.items():
        setattr(row, key, value)
    audit.record(session, "billing.settings.manage", row, location_id=location_id, changes=audit.diff(row))
    session.flush()
    return row


def delete_settings_override(session: Session, principal: Principal, location_id: UUID) -> None:
    authorize(principal, "billing.settings.manage")
    platform.service.get_location(session, principal, location_id)
    row = _settings_row(session, location_id, create=False)
    if row is None:
        raise NotFound()
    audit.record(session, "billing.settings.manage", row, location_id=location_id, changes={"override": [True, None]})
    session.delete(row)
    session.flush()


def get_period_lock(session: Session, principal: Principal) -> date | None:
    authorize(principal, "billing.settings.manage")
    return platform.service.get_tenant(session).billing_locked_through_on


def set_period_lock(session: Session, principal: Principal, locked_through_on: date | None) -> date | None:
    """Close the books through a date (ADR 0003 section 3): no posting may then be dated on or before it.
    Moving the lock back re-opens a period, so it is an audited settings change like any other."""
    authorize(principal, "billing.settings.manage")
    tenant = platform.service.get_tenant(session)
    was, tenant.billing_locked_through_on = tenant.billing_locked_through_on, locked_through_on
    audit.record(
        session, "billing.settings.manage", tenant,
        changes={"billing_locked_through_on": [str(was) if was else None, str(locked_through_on or "") or None]},
    )  # fmt: skip
    session.flush()
    return locked_through_on


# --- coupons (BIL-15) --------------------------------------------------------------------------------------


def list_coupons(session: Session, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, select(Coupon), query, id_column=Coupon.id, sort_fields={"code": Coupon.code, "name": Coupon.name},
        default_sort="code", filter_fields={"is_active": Coupon.is_active}, search=(Coupon.code, Coupon.name),
    )  # fmt: skip


def get_coupon(session: Session, principal: Principal, coupon_id: UUID) -> Coupon:
    return service._get(session, Coupon, coupon_id)


def _check_coupon(coupon: Coupon) -> None:
    if (coupon.discount_pct is None) == (coupon.discount_minor is None):
        raise ValidationFailed("Give a percentage or an amount, not both.", pointer="/discount_pct")
    if coupon.ends_at is not None and coupon.ends_at <= coupon.starts_at:
        raise ValidationFailed("The coupon must end after it starts.", pointer="/ends_at")


def create_coupon(session: Session, principal: Principal, data: dict) -> Coupon:
    authorize(principal, "billing.coupon.manage")
    if session.scalar(select(Coupon.id).where(Coupon.code == data["code"])):
        raise Conflict("A coupon with this code already exists.", code="already-exists")
    coupon = Coupon(**data)
    _check_coupon(coupon)
    session.add(coupon)
    session.flush()
    audit.record(session, "billing.coupon.manage", coupon, changes={"code": [None, coupon.code]})
    return coupon


def update_coupon(session: Session, principal: Principal, coupon_id: UUID, data: dict) -> Coupon:
    authorize(principal, "billing.coupon.manage")
    coupon = service._lock(session, Coupon, coupon_id)
    for key, value in data.items():
        setattr(coupon, key, value)
    _check_coupon(coupon)
    audit.record(session, "billing.coupon.manage", coupon, changes=audit.diff(coupon))
    session.flush()
    return coupon


def delete_coupon(session: Session, principal: Principal, coupon_id: UUID) -> None:
    """Only a coupon nobody used can be deleted; a used one is deactivated so its charges keep their link."""
    authorize(principal, "billing.coupon.manage")
    coupon = service._lock(session, Coupon, coupon_id)
    if session.scalar(
        select(func.count()).select_from(CouponRedemption).where(CouponRedemption.coupon_id == coupon.id)
    ):
        raise Conflict("This coupon has been used; deactivate it instead.", code="coupon-in-use")
    audit.record(session, "billing.coupon.manage", coupon, changes={"code": [coupon.code, None]})
    session.delete(coupon)
    session.flush()


def list_coupon_redemptions(session: Session, principal: Principal, coupon_id: UUID) -> list[CouponRedemption]:
    authorize(principal, "billing.coupon.manage")
    coupon = service._get(session, Coupon, coupon_id)
    return list(
        session.scalars(
            select(CouponRedemption)
            .where(CouponRedemption.coupon_id == coupon.id)
            .order_by(CouponRedemption.redeemed_at.desc())
            .limit(500)
        )
    )


def _used(session: Session, coupon: Coupon, client_id: UUID) -> int:
    return session.scalar(
        select(func.count())
        .select_from(CouponRedemption)
        .where(
            CouponRedemption.coupon_id == coupon.id,
            CouponRedemption.redeemer_client_id == client_id,
            CouponRedemption.released_at.is_(None),
        )
    )


def quote_coupon(
    session: Session,
    code: str,
    *,
    subtotal_minor: int,
    redeemer_client_id: UUID | None = None,
    channel: str = "staff",
    lock: bool = False,
) -> dict:
    """Would this code work, and for how much? Validation only: nothing is redeemed. The discount is taken
    off the sale's subtotal after manual discounts and before tax; a percentage is rounded half-up once and
    an amount is capped at the subtotal. The per-client cap counts the purchasing person."""
    stmt = select(Coupon).where(Coupon.code == code)
    coupon = session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    if coupon is None:
        raise ValidationFailed("Unknown coupon code.", pointer="/code", code="coupon-not-found")
    now, reason = clock.now(), None
    if not coupon.is_active:
        reason = "inactive"
    elif now < coupon.starts_at:
        reason = "not_started"
    elif coupon.ends_at is not None and now >= coupon.ends_at:
        reason = "expired"
    elif channel == "portal" and not coupon.is_portal_enabled:
        reason = "not_portal_enabled"
    elif coupon.limit_per_client is not None and redeemer_client_id is None:
        reason = "client_required"
    elif coupon.limit_per_client is not None and _used(session, coupon, redeemer_client_id) >= coupon.limit_per_client:
        reason = "limit_reached"
    if coupon.discount_pct is not None:
        discount = round_half_up(Decimal(subtotal_minor) * coupon.discount_pct / 100)
    else:
        discount = min(coupon.discount_minor, subtotal_minor)
    return {
        "coupon_id": coupon.id, "is_valid": reason is None, "invalid_reason": reason,
        "discount_minor": 0 if reason else max(discount, 0),
    }  # fmt: skip


def redeem_coupon(
    session: Session,
    code: str,
    *,
    redemption_key: str,
    line_nets: list[int],
    redeemer_client_id: UUID | None = None,
    channel: str = "staff",
    invoice_id: UUID | None = None,
) -> tuple[UUID, list[int]]:
    """Redeem a coupon for one sale and return (coupon_id, discount per line).

    `line_nets` are the sale's line amounts after manual discounts, before tax; the coupon's discount is
    shared over them by largest remainder, so the parts sum to it exactly. Idempotent by `redemption_key`
    ("<context>:<type>:<id>" of the sale): a retry returns the same split and counts once toward the cap.
    The coupon row is locked while the cap is counted, so two sales cannot both take the last use.
    """
    quote = quote_coupon(
        session, code, subtotal_minor=sum(line_nets), redeemer_client_id=redeemer_client_id, channel=channel, lock=True
    )
    existing = session.execute(
        select(CouponRedemption).where(
            CouponRedemption.coupon_id == quote["coupon_id"], CouponRedemption.redemption_key == redemption_key
        )
    ).scalar_one_or_none()
    if existing is not None and existing.released_at is None:
        return existing.coupon_id, split_by_weight(existing.discount_minor, line_nets)
    if not quote["is_valid"]:
        raise ValidationFailed(
            f"This coupon cannot be used ({quote['invalid_reason'].replace('_', ' ')}).", pointer="/coupon_code",
            code=f"coupon-{quote['invalid_reason'].replace('_', '-')}",
        )  # fmt: skip
    if existing is not None:  # redeemed, released, redeemed again: the key is reused, so revive the row
        existing.released_at, existing.discount_minor, existing.redeemed_at = None, quote["discount_minor"], clock.now()
    else:
        session.add(
            CouponRedemption(
                coupon_id=quote["coupon_id"],
                redeemer_client_id=redeemer_client_id,
                redemption_key=redemption_key,
                invoice_id=invoice_id,
                discount_minor=quote["discount_minor"],
                redeemed_at=clock.now(),
            )  # fmt: skip
        )
    session.flush()
    return quote["coupon_id"], split_by_weight(quote["discount_minor"], line_nets)


def release_coupon(session: Session, redemption_key: str) -> None:
    """The sale was abandoned, reversed or voided: its redemption no longer counts toward the cap."""
    for row in session.scalars(
        select(CouponRedemption).where(
            CouponRedemption.redemption_key == redemption_key, CouponRedemption.released_at.is_(None)
        )
    ):
        row.released_at = clock.now()
    session.flush()
