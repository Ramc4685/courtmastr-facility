"""POS report data (POS-16 history, the POS rows of the reporting catalogue): sales grouped by employee,
category, coupon, supplier, brand, product or register; the daily register; reorder; returns.

Gate: `reporting.pos.run` (registered by reporting), with location scope, the same key as the report centre's POS
reports (owner decisions 2026-11-13, question 14). Date ranges are local dates at the location (or the tenant's default zone
when no location is given), turned into UTC bounds: completed_at is stored in UTC.
"""

from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import Principal, authorize
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.modules import platform
from app.modules.pos.models import (
    DrawerSession,
    PosReturn,
    PosReturnLine,
    PosSale,
    PosSaleDiscount,
    PosSaleLine,
    PosSaleTender,
    Product,
    ProductBrand,
    ProductCategory,
    ProductStock,
    ProductSupplier,
    Register,
)
from app.modules.pos.service import check_location

_READ = "reporting.pos.run"  # owner decisions 2026-11-13, question 14
GROUPS = ("employee", "category", "coupon", "supplier", "brand", "product", "register")
_MAX_DAYS = 366


def _bounds(session: Session, principal: Principal, location_id: UUID | None, from_on: date, to_on: date):
    if to_on < from_on or (to_on - from_on).days > _MAX_DAYS:
        raise ValidationFailed("Choose a range of up to a year, ending after it starts.", pointer="/to_on")
    if location_id is not None:
        check_location(session, principal, location_id, pointer="/location_id")
        zone = platform.service.get_location(session, principal, location_id).time_zone
    else:
        zone = platform.service.get_tenant(session).default_time_zone
    tz = ZoneInfo(zone)
    start = datetime.combine(from_on, time(), tz)
    end = datetime.combine(to_on + timedelta(days=1), time(), tz)
    return start, end


def _scoped(stmt, principal: Principal, column, location_id: UUID | None):
    if location_id is not None:
        authorize(principal, _READ, location_id=location_id)
        return stmt.where(column == location_id)
    authorize(principal, _READ)
    if principal.kind != "system" and principal.location_ids is not None:
        stmt = stmt.where(column.in_(principal.location_ids))
    return stmt


def _staff_names(session: Session, principal: Principal, ids) -> dict:
    names = {}
    for staff_user_id in ids:
        try:
            user = platform.staff.get_staff_user(session, principal, staff_user_id, permission=_READ)
            names[staff_user_id] = f"{user.first_name} {user.last_name}".strip()
        except (NotFound, PermissionDenied):
            names[staff_user_id] = None
    return names


def sales_report(
    session: Session, principal: Principal, *, group_by: str, from_on: date, to_on: date, location_id: UUID | None
) -> dict:
    """Completed sales in the range, one row per group: sale count, units, gross, discount, net, tax, total.
    The coupon grouping is per sale (the coupon's own discount); the others are per line."""
    if group_by not in GROUPS:
        raise ValidationFailed(f"Group by one of: {', '.join(GROUPS)}.", pointer="/group_by")
    start, end = _bounds(session, principal, location_id, from_on, to_on)
    window = (PosSale.status == "completed", PosSale.completed_at >= start, PosSale.completed_at < end)
    if group_by == "coupon":
        stmt = (
            select(
                PosSale.coupon_code.label("key"), func.count(PosSale.id.distinct()).label("sale_count"),
                func.sum(PosSaleDiscount.applied_minor).label("coupon_discount_minor"),
                func.sum(PosSale.total_minor).label("total_minor"),
            )
            .join(PosSaleDiscount, (PosSaleDiscount.pos_sale_id == PosSale.id) & (PosSaleDiscount.source == "coupon"))
            .where(*window)
            .group_by(PosSale.coupon_code)
            .order_by(PosSale.coupon_code)
        )  # fmt: skip
        rows = session.execute(_scoped(stmt, principal, PosSale.location_id, location_id)).all()
        data = [{"key": r.key, "label": str(r.key).upper(), "sale_count": r.sale_count,
                 "coupon_discount_minor": int(r.coupon_discount_minor or 0), "total_minor": int(r.total_minor or 0)}
                for r in rows]  # fmt: skip
        return {"group_by": group_by, "from_on": from_on, "to_on": to_on, "location_id": location_id, "data": data}

    key = {
        "employee": PosSale.cashier_staff_user_id, "register": PosSale.register_id,
        "category": Product.product_category_id, "supplier": Product.product_supplier_id,
        "brand": Product.product_brand_id, "product": PosSaleLine.product_id,
    }[group_by]  # fmt: skip
    stmt = (
        select(
            key.label("key"), func.count(PosSale.id.distinct()).label("sale_count"),
            func.sum(PosSaleLine.quantity).label("quantity"),
            func.sum(PosSaleLine.quantity * PosSaleLine.unit_price_minor).label("gross_minor"),
            func.sum(PosSaleLine.discount_minor).label("discount_minor"), func.sum(PosSaleLine.net_minor).label("net_minor"),
            func.sum(PosSaleLine.tax_minor).label("tax_minor"), func.sum(PosSaleLine.total_minor).label("total_minor"),
            func.sum(PosSaleLine.returned_quantity).label("returned_quantity"),
        )
        .join(PosSale, PosSale.id == PosSaleLine.pos_sale_id)
        .outerjoin(Product, Product.id == PosSaleLine.product_id)
        .where(*window)
        .group_by(key)
    )  # fmt: skip
    if group_by in ("category", "supplier", "brand", "product"):
        stmt = stmt.where(PosSaleLine.line_kind == "product")
    rows = session.execute(_scoped(stmt, principal, PosSale.location_id, location_id)).all()
    labels = _labels(session, principal, group_by, [r.key for r in rows if r.key is not None])
    data = [
        {"key": r.key, "label": labels.get(r.key) if r.key else "(none)", "sale_count": r.sale_count,
         **{f: int(getattr(r, f) or 0) for f in ("quantity", "gross_minor", "discount_minor", "net_minor", "tax_minor",
                                                 "total_minor", "returned_quantity")}}
        for r in rows
    ]  # fmt: skip
    data.sort(key=lambda row: -row["total_minor"])
    return {"group_by": group_by, "from_on": from_on, "to_on": to_on, "location_id": location_id, "data": data}


def _labels(session: Session, principal: Principal, group_by: str, ids: list) -> dict:
    if group_by == "employee":
        return _staff_names(session, principal, ids)
    model = {"register": Register, "category": ProductCategory, "supplier": ProductSupplier, "brand": ProductBrand,
             "product": Product}[group_by]  # fmt: skip
    return dict(session.execute(select(model.id, model.name).where(model.id.in_(ids))).all()) if ids else {}


def daily_register(session: Session, principal: Principal, *, location_id: UUID, on: date) -> dict:
    """One local day at a location, per register: sales, tenders by kind, refunds, and the drawer sessions
    opened that day with their counts and variance."""
    start, end = _bounds(session, principal, location_id, on, on)
    authorize(principal, _READ, location_id=location_id)
    registers = session.scalars(select(Register).where(Register.location_id == location_id).order_by(Register.name))
    out = []
    for register in registers:
        sales = session.execute(
            select(func.count(PosSale.id), func.coalesce(func.sum(PosSale.total_minor), 0),
                   func.coalesce(func.sum(PosSale.tax_minor), 0), func.coalesce(func.sum(PosSale.discount_minor), 0))
            .where(PosSale.register_id == register.id, PosSale.status == "completed",
                   PosSale.completed_at >= start, PosSale.completed_at < end)
        ).one()  # fmt: skip
        tenders = session.execute(
            select(PosSaleTender.tender, PosSaleTender.tender_kind, func.sum(PosSaleTender.amount_minor))
            .join(PosSale, PosSale.id == PosSaleTender.pos_sale_id)
            .where(PosSale.register_id == register.id, PosSale.status == "completed", PosSaleTender.status == "captured",
                   PosSale.completed_at >= start, PosSale.completed_at < end)
            .group_by(PosSaleTender.tender, PosSaleTender.tender_kind)
            .order_by(PosSaleTender.tender, PosSaleTender.tender_kind)
        ).all()  # fmt: skip
        refunds = session.execute(
            select(func.count(PosReturn.id), func.coalesce(func.sum(PosReturn.amount_minor), 0),
                   func.coalesce(func.sum(PosReturn.refunded_minor), 0),
                   func.coalesce(func.sum(PosReturn.cash_refunded_minor), 0))
            .where(PosReturn.register_id == register.id, PosReturn.processed_at >= start, PosReturn.processed_at < end)
        ).one()  # fmt: skip
        drawers = session.scalars(
            select(DrawerSession).where(DrawerSession.register_id == register.id, DrawerSession.opened_at >= start,
                                        DrawerSession.opened_at < end).order_by(DrawerSession.opened_at)
        ).all()  # fmt: skip
        out.append({
            "register_id": register.id, "register_name": register.name, "sale_count": sales[0],
            "total_minor": int(sales[1]), "tax_minor": int(sales[2]), "discount_minor": int(sales[3]),
            "tenders": [{"tender": t, "tender_kind": k, "amount_minor": int(a)} for t, k, a in tenders],
            "return_count": refunds[0], "returned_minor": int(refunds[1]), "refunded_minor": int(refunds[2]),
            "cash_refunded_minor": int(refunds[3]),
            "drawer_sessions": [
                {"id": d.id, "status": d.status, "opened_at": d.opened_at, "closed_at": d.closed_at,
                 "opening_float_minor": d.opening_float_minor, "expected_cash_minor": d.expected_cash_minor,
                 "counted_cash_minor": d.counted_cash_minor,
                 "variance_minor": None if d.counted_cash_minor is None else d.counted_cash_minor - d.expected_cash_minor}
                for d in drawers
            ],
        })  # fmt: skip
    return {"location_id": location_id, "on": on, "registers": out}


def reorder_report(session: Session, principal: Principal, *, location_id: UUID) -> dict:
    """Stock-tracked active products at or below their reorder level at the location, by supplier."""
    check_location(session, principal, location_id, pointer="/location_id")
    authorize(principal, _READ, location_id=location_id)
    on_hand = func.coalesce(ProductStock.on_hand_count, 0)
    rows = session.execute(
        select(Product, on_hand.label("on_hand"), ProductSupplier.name.label("supplier_name"))
        .outerjoin(ProductStock, (ProductStock.product_id == Product.id) & (ProductStock.location_id == location_id))
        .outerjoin(ProductSupplier, ProductSupplier.id == Product.product_supplier_id)
        .where(Product.is_active, Product.is_stock_tracked, Product.reorder_level.is_not(None),
               on_hand <= Product.reorder_level)
        .order_by(ProductSupplier.name.nulls_last(), Product.name)
    ).all()  # fmt: skip
    return {"location_id": location_id, "data": [
        {"product_id": p.id, "name": p.name, "product_code": p.product_code, "sku": p.sku,
         "product_supplier_id": p.product_supplier_id, "supplier_name": supplier, "on_hand_count": int(count),
         "reorder_level": p.reorder_level, "cost_minor": p.cost_minor}
        for p, count, supplier in rows
    ]}  # fmt: skip


def returns_report(
    session: Session, principal: Principal, *, from_on: date, to_on: date, location_id: UUID | None
) -> dict:
    start, end = _bounds(session, principal, location_id, from_on, to_on)
    stmt = (
        select(PosReturn, PosSale.invoice_number, func.coalesce(func.sum(PosReturnLine.quantity), 0))
        .join(PosSale, PosSale.id == PosReturn.pos_sale_id)
        .outerjoin(PosReturnLine, PosReturnLine.pos_return_id == PosReturn.id)
        .where(PosReturn.processed_at >= start, PosReturn.processed_at < end)
        .group_by(PosReturn.id, PosSale.invoice_number)
        .order_by(PosReturn.processed_at.desc())
    )  # fmt: skip
    rows = session.execute(_scoped(stmt, principal, PosReturn.location_id, location_id)).all()
    names = _staff_names(session, principal, {r.processed_by_staff_user_id for r, _, _ in rows})
    return {"from_on": from_on, "to_on": to_on, "location_id": location_id, "data": [
        {"pos_return_id": r.id, "pos_sale_id": r.pos_sale_id, "invoice_number": number, "processed_at": r.processed_at,
         "processed_by": names.get(r.processed_by_staff_user_id), "refund_mode": r.refund_mode,
         "quantity": int(quantity), "amount_minor": r.amount_minor, "refunded_minor": r.refunded_minor,
         "cash_refunded_minor": r.cash_refunded_minor, "reason": r.reason}
        for r, number, quantity in rows
    ]}  # fmt: skip
