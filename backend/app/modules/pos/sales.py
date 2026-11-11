"""The register (POS-07 to POS-13): draft carts, lines, discounts, tender legs, completion and receipts.

A sale is a draft cart until completion. Each tender leg is captured as it is taken: a `payment` leg is a
billing payment, unallocated until completion (so a declined card never undoes a taken cash leg); an
`account_credit` leg is checked against the client's credit and spent at completion; `pay_later` leaves the
invoice open. Completion is one transaction: the line charges (origin `pos`/`pos_sale_line`), the invoice,
the allocations, the coupon redemption, the stock movements and the equipment loans.

A walk-in sale has no client (owner decision 7): billing then records the invoice, charges and payments with
a null client, which it permits for origin `pos` only. Tenders that need a person, equipment rentals and
capped coupons require a client.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from html import escape
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, packages, platform
from app.modules.pos import catalogue, equipment, inventory
from app.modules.pos.domain.pricing import Discount, apply_discounts, round_half_up
from app.modules.pos.events import SaleCompleted
from app.modules.pos.models import (
    DiscountPreset,
    EquipmentItem,
    PosReceiptDelivery,
    PosReturn,
    PosReturnLine,
    PosSale,
    PosSaleDiscount,
    PosSaleDiscountLine,
    PosSaleLine,
    PosSaleTender,
    Product,
    Register,
)
from app.modules.pos.service import (
    check_network,
    get_row,
    open_drawer,
    product_revenue_category,
    product_tax_ids,
    settings_for,
)
from app.ports import notifications

_CREATE = "pos.sale.create"
CONSTRAINT_CODES["ix_pos_sale_draft"] = "draft-sale-exists"
CONSTRAINT_CODES["uq_drawer_session_open"] = "drawer-already-open"
CONSTRAINT_CODES["ck_equipment_item_on_loan"] = "equipment-unavailable"
CONSTRAINT_CODES["ck_pos_sale_line_returned"] = "return-exceeds-sold"
# Kinds a cashier can take at the register. Bank debit settles days later, which a till cannot wait for.
PROCESSED_KINDS = ("card", "bank_debit")  # the provider moves the money; every other register kind is record-only
# Each tender moves money its own way, so each needs the billing key for that move (a payment leg otherwise).
_TENDER_KEYS = {"account_credit": "billing.credit.apply", "pay_later": "billing.invoice.create"}
_REGISTER_KINDS = ("card", "cash", "cheque", "gift_card", "bank_transfer", "external", "other")
COUPON_SEQ = 1_000_000  # the coupon applies last

notifications.register_template(
    "pos.receipt",
    subject="Your receipt from $location_name ($number)",
    body="$location_name\n$location_contact\n\nReceipt $number, $completed_at\n\n$lines\n\n$totals\n\n$tenders\n\n$footer\n",
)


# --- reads -------------------------------------------------------------------------------------------------


def draft_for_register(session: Session, register_id: UUID) -> PosSale | None:
    return session.execute(
        select(PosSale).where(PosSale.register_id == register_id, PosSale.status == "draft")
    ).scalar_one_or_none()


def _lines(session: Session, sale_id: UUID) -> list[PosSaleLine]:
    return list(
        session.scalars(select(PosSaleLine).where(PosSaleLine.pos_sale_id == sale_id).order_by(PosSaleLine.line_no))
    )


def _tenders(session: Session, sale_id: UUID) -> list[PosSaleTender]:
    return list(
        session.scalars(select(PosSaleTender).where(PosSaleTender.pos_sale_id == sale_id).order_by(PosSaleTender.seq))
    )


def _discounts(session: Session, sale_id: UUID) -> list[PosSaleDiscount]:
    return list(
        session.scalars(
            select(PosSaleDiscount).where(PosSaleDiscount.pos_sale_id == sale_id).order_by(PosSaleDiscount.seq)
        )
    )


def _columns(row) -> dict:
    return {c.key: getattr(row, c.key) for c in type(row).__table__.columns}


def captured_minor(tenders: list[PosSaleTender]) -> int:
    return sum(t.amount_minor for t in tenders if t.status == "captured")


def sale_detail(session: Session, sale: PosSale) -> dict:
    tenders = _tenders(session, sale.id)
    shares = session.execute(
        select(PosSaleDiscountLine)
        .join(PosSaleDiscount, PosSaleDiscount.id == PosSaleDiscountLine.pos_sale_discount_id)
        .where(PosSaleDiscount.pos_sale_id == sale.id)
    ).scalars()
    by_discount: dict[UUID, list] = {}
    for share in shares:
        by_discount.setdefault(share.pos_sale_discount_id, []).append(
            {"pos_sale_line_id": share.pos_sale_line_id, "amount_minor": share.amount_minor}
        )
    returns = []
    for row in session.scalars(
        select(PosReturn).where(PosReturn.pos_sale_id == sale.id).order_by(PosReturn.processed_at)
    ):
        lines = session.scalars(select(PosReturnLine).where(PosReturnLine.pos_return_id == row.id)).all()
        returns.append({**_columns(row), "lines": [_columns(line) for line in lines]})
    paid = captured_minor(tenders)
    client_name = None
    if sale.client_id:
        client_name = clients.service.display_name(clients.service.get(session, sale.client_id))
    return {
        **_columns(sale), "client_name": client_name,
        "lines": [_columns(line) for line in _lines(session, sale.id)],
        "discounts": [
            {**_columns(d), "lines": by_discount.get(d.id, []),
             "line_ids": [share["pos_sale_line_id"] for share in by_discount.get(d.id, [])]}
            for d in _discounts(session, sale.id)
        ],
        "tenders": [{**_columns(t), "next_action": None} for t in tenders], "returns": returns, "tendered_minor": paid,
        "remaining_minor": sale.total_minor - paid,
    }  # fmt: skip


def _sale(session: Session, principal: Principal, sale_id: UUID, *, key: str = "pos.sale.read", lock: bool = False):
    sale = get_row(session, PosSale, sale_id, lock=lock)
    authorize(principal, key, location_id=sale.location_id)
    return sale


def get_sale(session: Session, principal: Principal, sale_id: UUID) -> dict:
    return sale_detail(session, _sale(session, principal, sale_id))


def list_sales(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Transaction history (POS-16): search by client or invoice number."""
    authorize(principal, "pos.sale.read")
    return paginate(
        session, scope_query(select(PosSale), principal, PosSale.location_id), query, id_column=PosSale.id,
        sort_fields={"created_at": PosSale.created_at}, default_sort="-created_at",
        filter_fields={
            "location_id": PosSale.location_id, "register_id": PosSale.register_id, "client_id": PosSale.client_id,
            "cashier_staff_user_id": PosSale.cashier_staff_user_id, "status": PosSale.status,
            "return_state": PosSale.return_state, "invoice_number": PosSale.invoice_number,
            "completed_at": PosSale.completed_at, "drawer_session_id": PosSale.drawer_session_id,
        },
    )  # fmt: skip


# --- the cart ----------------------------------------------------------------------------------------------


def _draft(session: Session, principal: Principal, sale_id: UUID, client_ip: str | None) -> PosSale:
    sale = _sale(session, principal, sale_id, key=_CREATE, lock=True)
    if sale.status != "draft":
        raise Conflict("This sale is no longer open.")
    check_network(session, sale.location_id, client_ip)
    return sale


def create_sale(session: Session, principal: Principal, data: dict, client_ip: str | None) -> dict:
    register = get_row(session, Register, data["register_id"], pointer="/register_id")
    authorize(principal, _CREATE, location_id=register.location_id)
    if not register.is_active:
        raise Conflict("This register is not active.", code="register-inactive")
    check_network(session, register.location_id, client_ip)
    drawer = open_drawer(session, register.id)
    if drawer is None and settings_for(session, register.location_id).is_drawer_session_required:
        raise Conflict("Open the cash drawer before the first sale.", code="drawer-session-required")
    if draft_for_register(session, register.id) is not None:
        raise Conflict("This register already has a sale in progress.", code="draft-sale-exists")
    if data.get("client_id"):
        _attach_client(session, principal, data["client_id"])
    sale = PosSale(
        location_id=register.location_id, register_id=register.id, drawer_session_id=drawer.id if drawer else None,
        cashier_staff_user_id=principal.staff_user_id, client_id=data.get("client_id"), note=data.get("note"),
    )  # fmt: skip
    session.add(sale)
    session.flush()
    audit.record(session, _CREATE, sale, location_id=sale.location_id, changes={"status": [None, "draft"]})
    return sale_detail(session, sale)


def _attach_client(session: Session, principal: Principal, client_id: UUID) -> None:
    """A client the cashier may read (own reach included), and active. Out of reach reads as unknown."""
    try:
        clients.service.load(session, principal, client_id, "clients.client.read")
    except NotFound:
        raise ValidationFailed("Unknown or disabled client.", pointer="/client_id") from None
    clients.service.require_active(session, client_id)


def update_sale(session: Session, principal: Principal, sale_id: UUID, data: dict, client_ip: str | None) -> dict:
    """Attach or detach the client (POS-08), edit the note. `version` guards a cart handed between devices."""
    sale = _draft(session, principal, sale_id, client_ip)
    if data.get("version") is not None and data["version"] != sale.version:
        raise Conflict("The sale changed on another device; reload it.", code="version-conflict")
    if "client_id" in data and data["client_id"] != sale.client_id:
        if any(t.status == "captured" for t in _tenders(session, sale.id)):
            raise Conflict("Remove the payments taken before changing the client.", code="captured-tenders-exist")
        if data["client_id"] is None:
            if any(line.line_kind == "equipment" for line in _lines(session, sale.id)):
                raise ValidationFailed("Equipment rentals need a client.", pointer="/client_id", code="client-required")
        else:
            _attach_client(session, principal, data["client_id"])
        sale.client_id = data["client_id"]
    if "note" in data:
        sale.note = data["note"]
    audit.record(session, _CREATE, sale, location_id=sale.location_id, changes=audit.diff(sale))
    recompute(session, sale)
    return sale_detail(session, sale)


def _find_product(session: Session, data: dict) -> Product:
    if data.get("product_id"):
        product = get_row(session, Product, data["product_id"], pointer="/product_id")
    else:
        code = data["sku"].strip()
        product = session.execute(select(Product).where(Product.sku == code)).scalar_one_or_none()
        product = product or session.execute(select(Product).where(Product.product_code == code)).scalar_one_or_none()
        if product is None:
            raise ValidationFailed("No product has this code.", pointer="/sku", code="product-not-found")
    if not product.is_active:
        raise ValidationFailed("This product is not for sale.", pointer="/product_id", code="product-inactive")
    return product


def _check_stock(session: Session, sale: PosSale, product: Product, extra: int) -> None:
    """Early warning while ringing up; completion re-checks under the stock row lock."""
    if not product.is_stock_tracked or settings_for(session, sale.location_id).is_negative_stock_allowed:
        return
    in_cart = session.scalar(
        select(func.coalesce(func.sum(PosSaleLine.quantity), 0)).where(
            PosSaleLine.pos_sale_id == sale.id, PosSaleLine.product_id == product.id
        )
    )
    have = inventory.on_hand(session, product.id, sale.location_id)
    if (in_cart + extra) * product.units_per_sale > have:
        raise Conflict(f"Not enough stock of {product.name}: {have} on hand.", code="insufficient-stock")


def _check_equipment(session: Session, sale: PosSale, item: EquipmentItem, extra: int) -> None:
    in_cart = session.scalar(
        select(func.coalesce(func.sum(PosSaleLine.quantity), 0)).where(
            PosSaleLine.pos_sale_id == sale.id, PosSaleLine.equipment_item_id == item.id
        )
    )
    if in_cart + extra > item.unit_count - item.on_loan_count:
        raise Conflict(
            f"Only {item.unit_count - item.on_loan_count} of {item.name} available.", code="equipment-unavailable"
        )


def add_line(session: Session, principal: Principal, sale_id: UUID, data: dict, client_ip: str | None) -> dict:
    """Add a product by id or scan (SKU, then product ID) or an equipment item. Scanning the same product again
    adds a unit to its line unless that line's price was overridden."""
    sale = _draft(session, principal, sale_id, client_ip)
    targets = [k for k in ("product_id", "sku", "equipment_item_id", "package_plan_id") if data.get(k)]
    if len(targets) != 1:
        raise ValidationFailed(
            "Give exactly one of product_id, sku, equipment_item_id or package_plan_id.", pointer="/product_id"
        )
    quantity = data.get("quantity") or 1
    lines = _lines(session, sale.id)
    if targets[0] == "package_plan_id":
        authorize(principal, "packages.package.sell", location_id=sale.location_id)
        if sale.client_id is None:
            raise ValidationFailed("Packages need a client.", pointer="/client_id", code="client-required")
        if quantity != 1:
            raise ValidationFailed("Add a package once per line.", pointer="/quantity")
        offer = packages.service.offer(session, data["package_plan_id"], sale.location_id)
        line = PosSaleLine(
            line_kind="package", package_plan_id=offer["package_plan_id"], description=offer["name"],
            list_unit_price_minor=offer["price_minor"], unit_price_minor=offer["price_minor"],
            revenue_category_id=offer["revenue_category_id"] or billing.service.default_revenue_category(session).id,
        )  # fmt: skip
    elif targets[0] == "equipment_item_id":
        authorize(principal, "pos.equipment.rent", location_id=sale.location_id)
        item = get_row(session, EquipmentItem, data["equipment_item_id"], pointer="/equipment_item_id")
        if not item.is_active or item.location_id != sale.location_id:
            raise ValidationFailed("This equipment is not rented here.", pointer="/equipment_item_id")
        if sale.client_id is None:
            raise ValidationFailed("Equipment rentals need a client.", pointer="/client_id", code="client-required")
        _check_equipment(session, sale, item, quantity)
        line = PosSaleLine(
            line_kind="equipment", equipment_item_id=item.id, description=f"Rental: {item.name}",
            list_unit_price_minor=item.rental_fee_minor, unit_price_minor=item.rental_fee_minor,
            revenue_category_id=catalogue.equipment_revenue_category(session, item)
            or billing.service.default_revenue_category(session).id,
        )  # fmt: skip
    else:
        product = _find_product(session, data)
        _check_stock(session, sale, product, quantity)
        same = next(
            (
                other
                for other in lines
                if other.product_id == product.id and other.price_overridden_by_staff_user_id is None
            ),
            None,
        )
        if same is not None:
            same.quantity += quantity
            recompute(session, sale)
            return sale_detail(session, sale)
        line = PosSaleLine(
            line_kind="product", product_id=product.id, description=product.name,
            list_unit_price_minor=product.unit_price_minor, unit_price_minor=product.unit_price_minor,
            revenue_category_id=product_revenue_category(session, product),
        )  # fmt: skip
    line.pos_sale_id, line.quantity = sale.id, quantity
    line.line_no = max((other.line_no for other in lines), default=0) + 1
    line.net_minor = line.total_minor = 0
    session.add(line)
    session.flush()
    recompute(session, sale)
    return sale_detail(session, sale)


def _own_line(session: Session, sale: PosSale, line_id: UUID) -> PosSaleLine:
    line = get_row(session, PosSaleLine, line_id)
    if line.pos_sale_id != sale.id:
        raise NotFound()
    return line


def update_line(
    session: Session, principal: Principal, sale_id: UUID, line_id: UUID, data: dict, client_ip: str | None
) -> dict:
    """Quantity needs only pos.sale.create; a price that differs from the list needs pos.sale.override_price
    (POS-09), and the receipt itemises the difference as a discount."""
    sale = _draft(session, principal, sale_id, client_ip)
    line = _own_line(session, sale, line_id)
    if line.line_kind == "package":
        raise ValidationFailed("A package line cannot be changed; remove it and add it again.", pointer="/quantity")
    if data.get("unit_price_minor") is not None:
        price = data["unit_price_minor"]
        if price != line.list_unit_price_minor:
            authorize(principal, "pos.sale.override_price", location_id=sale.location_id)
            line.price_overridden_by_staff_user_id = principal.staff_user_id
        else:
            line.price_overridden_by_staff_user_id = None
        line.unit_price_minor = price
    if data.get("quantity") is not None and data["quantity"] != line.quantity:
        extra = data["quantity"] - line.quantity
        if extra > 0 and line.product_id:
            _check_stock(session, sale, session.get(Product, line.product_id), extra)
        if extra > 0 and line.equipment_item_id:
            _check_equipment(session, sale, session.get(EquipmentItem, line.equipment_item_id), extra)
        line.quantity = data["quantity"]
    audit.record(session, _CREATE, sale, location_id=sale.location_id,
                 changes={f"line_{line.line_no}": audit.diff(line)})  # fmt: skip
    recompute(session, sale)
    return sale_detail(session, sale)


def remove_line(session: Session, principal: Principal, sale_id: UUID, line_id: UUID, client_ip: str | None) -> None:
    sale = _draft(session, principal, sale_id, client_ip)
    session.delete(_own_line(session, sale, line_id))
    session.flush()
    recompute(session, sale)


def add_discount(session: Session, principal: Principal, sale_id: UUID, data: dict, client_ip: str | None) -> dict:
    """A preset, custom or coupon discount on the sale or on ticked lines (POS-10, POS-11)."""
    sale = _draft(session, principal, sale_id, client_ip)
    authorize(principal, "billing.discount.apply_preset", location_id=sale.location_id)
    source, scope = data["source"], data.get("scope", "sale")
    lines = _lines(session, sale.id)
    targets = lines
    if scope == "lines":
        ids = set(data.get("line_ids") or [])
        targets = [line for line in lines if line.id in ids]
        if not ids or len(targets) != len(ids):
            raise ValidationFailed("Tick the lines of this sale to discount.", pointer="/line_ids")
    base = sum(line.net_minor for line in targets)
    row = PosSaleDiscount(pos_sale_id=sale.id, source=source, scope=scope)
    if source == "preset":
        preset = get_row(session, DiscountPreset, data.get("discount_preset_id"), pointer="/discount_preset_id")
        if not preset.is_active:
            raise ValidationFailed("This preset is not active.", pointer="/discount_preset_id")
        row.discount_preset_id, row.label = preset.id, preset.name
        row.discount_pct, row.discount_minor = preset.discount_pct, preset.discount_minor
    elif source == "custom":
        authorize(principal, "billing.discount.apply_custom", location_id=sale.location_id)
        if (data.get("discount_pct") is None) == (data.get("discount_minor") is None):
            raise ValidationFailed("Give a percentage or an amount, not both.", pointer="/discount_pct")
        row.label, row.discount_pct, row.discount_minor = (
            "Custom discount",
            data.get("discount_pct"),
            data.get("discount_minor"),
        )
    else:
        code = (data.get("coupon_code") or "").strip()
        if not code:
            raise ValidationFailed("Enter the coupon code.", pointer="/coupon_code")
        if sale.coupon_code:
            raise Conflict("This sale already has a coupon.", code="coupon-already-applied")
        quote = billing.catalogue.quote_coupon(
            session, code, subtotal_minor=sale.subtotal_minor - sale.discount_minor, redeemer_client_id=sale.client_id
        )
        if not quote["is_valid"]:
            reason = quote["invalid_reason"]
            raise ValidationFailed(
                f"This coupon cannot be used ({reason.replace('_', ' ')}).", pointer="/coupon_code",
                code=f"coupon-{reason.replace('_', '-')}",
            )  # fmt: skip
        sale.coupon_code, row.scope, row.coupon_id = code, "sale", quote["coupon_id"]
        row.label, row.discount_minor = f"Coupon {code.upper()}", quote["discount_minor"]
        targets = lines
    if row.discount_minor is not None and source != "coupon" and row.discount_minor > base:
        raise ValidationFailed("The discount is larger than what it applies to.", pointer="/discount_minor",
                               code="discount-exceeds-total")  # fmt: skip
    existing = _discounts(session, sale.id)
    row.seq = COUPON_SEQ if source == "coupon" else max((d.seq for d in existing if d.seq < COUPON_SEQ), default=0) + 1
    session.add(row)
    session.flush()
    session.add_all(PosSaleDiscountLine(pos_sale_discount_id=row.id, pos_sale_line_id=line.id) for line in targets)
    session.flush()
    audit.record(session, "billing.discount.apply_custom" if source == "custom" else "billing.discount.apply_preset",
                 sale, location_id=sale.location_id, changes={"discount": [None, row.label]})  # fmt: skip
    recompute(session, sale)
    return sale_detail(session, sale)


def remove_discount(
    session: Session, principal: Principal, sale_id: UUID, discount_id: UUID, client_ip: str | None
) -> None:
    sale = _draft(session, principal, sale_id, client_ip)
    row = get_row(session, PosSaleDiscount, discount_id)
    if row.pos_sale_id != sale.id:
        raise NotFound()
    if row.source == "product_default":
        raise Conflict("A product's own discount follows the product; override the price instead.")
    if row.source == "coupon":
        sale.coupon_code = None
    session.delete(row)
    session.flush()
    audit.record(session, _CREATE, sale, location_id=sale.location_id, changes={"discount": [row.label, None]})
    recompute(session, sale)


def _line_taxes(session: Session, line: PosSaleLine, on) -> list[tuple[UUID, Decimal]]:
    tax_ids = product_tax_ids(session, session.get(Product, line.product_id)) if line.product_id else None
    return billing.service.taxes_in_force(session, on, revenue_category_id=line.revenue_category_id, tax_ids=tax_ids)


def recompute(session: Session, sale: PosSale) -> None:
    """Re-price the cart: product default discounts, then manual discounts in entry order, then the coupon
    (re-quoted on what is left), then tax per line at today's rates. Bumps the version."""
    lines = _lines(session, sale.id)
    session.execute(
        delete(PosSaleDiscount).where(
            PosSaleDiscount.pos_sale_id == sale.id, PosSaleDiscount.source == "product_default"
        )
    )
    for line in lines:
        product = session.get(Product, line.product_id) if line.product_id else None
        if product is not None and product.default_discount_pct:
            row = PosSaleDiscount(
                pos_sale_id=sale.id, source="product_default", scope="lines", label=f"{product.name} discount",
                discount_pct=product.default_discount_pct, seq=-line.line_no,
            )  # fmt: skip
            session.add(row)
            session.flush()
            session.add(PosSaleDiscountLine(pos_sale_discount_id=row.id, pos_sale_line_id=line.id))
    session.flush()
    discounts = _discounts(session, sale.id)
    shares = {
        (row.pos_sale_discount_id, row.pos_sale_line_id): row
        for row in session.scalars(
            select(PosSaleDiscountLine).where(PosSaleDiscountLine.pos_sale_discount_id.in_([d.id for d in discounts]))
        )
    }
    # A package's price is its plan's (packages bills it): cart discounts and coupons skip those lines.
    line_ids = [line.id for line in lines if line.line_kind != "package"]

    def targets(discount: PosSaleDiscount) -> tuple[UUID, ...]:
        if discount.scope == "sale":
            return tuple(line_ids)
        return tuple(line_id for line_id in line_ids if (discount.id, line_id) in shares)

    gross = {line.id: line.quantity * line.unit_price_minor for line in lines}
    manual = [d for d in discounts if d.source != "coupon"]
    applied = apply_discounts(gross, [Discount(d.id, d.discount_pct, d.discount_minor, targets(d)) for d in manual])
    coupon = next((d for d in discounts if d.source == "coupon"), None)
    if coupon is not None:
        quote = billing.catalogue.quote_coupon(
            session, sale.coupon_code, subtotal_minor=sum(applied.nets[line_id] for line_id in line_ids),
            redeemer_client_id=sale.client_id,
        )  # fmt: skip
        coupon.discount_minor = quote["discount_minor"]
        more = apply_discounts(
            applied.nets, [Discount(coupon.id, minor=coupon.discount_minor, line_keys=targets(coupon))]
        )
        applied.applied.update(more.applied)
        applied.shares.update(more.shares)
        applied.nets = more.nets
    for discount in discounts:
        discount.applied_minor = applied.applied.get(discount.id, 0)
        for line_id in targets(discount):
            amount = applied.shares.get((discount.id, line_id), 0)
            row = shares.get((discount.id, line_id))
            if row is None:
                session.add(
                    PosSaleDiscountLine(pos_sale_discount_id=discount.id, pos_sale_line_id=line_id, amount_minor=amount)
                )
            else:
                row.amount_minor = amount
    today = platform.service.location_today(session, sale.location_id)
    for line in lines:
        line.net_minor = applied.nets[line.id]
        line.discount_minor = gross[line.id] - line.net_minor
        line.tax_minor = sum(
            round_half_up(Decimal(line.net_minor) * rate) for _, rate in _line_taxes(session, line, today)
        )
        line.total_minor = line.net_minor + line.tax_minor
    sale.subtotal_minor = sum(gross.values())
    sale.discount_minor = sum(line.discount_minor for line in lines)
    sale.tax_minor = sum(line.tax_minor for line in lines)
    sale.total_minor = sale.subtotal_minor - sale.discount_minor + sale.tax_minor
    sale.version += 1
    session.flush()


# --- tenders (POS-12) --------------------------------------------------------------------------------------


def add_tender(
    session: Session, principal: Principal, sale_id: UUID, data: dict, idempotency_key: str, client_ip: str | None
) -> dict:
    """Capture one leg. A declined card is `402 payment-declined` and leaves earlier legs captured; the leg
    is kept as `failed`. The same Idempotency-Key always resolves to the same payment."""
    sale = _draft(session, principal, sale_id, client_ip)
    tenders = _tenders(session, sale.id)
    key = f"pos:{sale.id}:{principal.staff_user_id}:{idempotency_key}"
    payment = billing.service.find_payment(session, key)
    if payment is not None:
        leg = next((t for t in tenders if t.payment_id == payment.id), None)
        if leg is not None:
            if payment.status in ("unknown", "initiated"):
                payment = billing.service.confirm_payment(session, payment.id)
                _settle_leg(session, sale, leg, payment)
            return sale_detail(session, sale)
    tender, amount = data["tender"], data["amount_minor"]
    authorize(principal, _TENDER_KEYS.get(tender, "billing.payment.take"), location_id=sale.location_id)
    remaining = sale.total_minor - captured_minor(tenders)
    if amount > remaining:
        raise ValidationFailed(
            f"Only {remaining} is left to pay.", pointer="/amount_minor", code="tender-exceeds-remaining"
        )
    needs_client = tender in ("account_credit", "pay_later") or data.get("payment_method_id")
    if needs_client and sale.client_id is None:
        raise ValidationFailed(
            "Attach a client to use this payment option.", pointer="/client_id", code="client-required"
        )
    leg = PosSaleTender(
        pos_sale_id=sale.id, seq=max((t.seq for t in tenders), default=0) + 1, tender=tender, amount_minor=amount,
        payment_method_id=data.get("payment_method_id"), tender_type_id=data.get("tender_type_id"),
    )  # fmt: skip
    if tender == "pay_later":
        if any(t.tender == "pay_later" and t.status == "captured" for t in tenders):
            raise ValidationFailed("Pay later is already on this sale.", pointer="/tender")
        leg.status = "captured"
    elif tender == "account_credit":
        if amount > _credit_available(session, sale, tenders):
            raise ValidationFailed("Not enough credit on account.", pointer="/amount_minor", code="insufficient-credit")
        leg.status = "captured"
    else:
        leg.tender_kind = _tender_kind(session, principal, data)
        payment = billing.service.take_payment(
            session, client_id=sale.client_id, location_id=sale.location_id, amount_minor=amount,
            tender_kind=leg.tender_kind, idempotency_key=key, method_token=data.get("provider_confirmation_token"),
            payment_method_id=data.get("payment_method_id"), tender_type_id=data.get("tender_type_id"), origin="pos",
            external_reference=data.get("external_reference"), memo=f"POS sale {sale.id}",
        )  # fmt: skip
        leg.payment_id, leg.tender_type_id = payment.id, payment.tender_type_id
    session.add(leg)
    session.flush()
    audit.record(session, _CREATE, sale, location_id=sale.location_id,
                 changes={f"tender_{leg.seq}": [None, {"tender": tender, "amount_minor": amount}]})  # fmt: skip
    if leg.payment_id is not None:
        _settle_leg(session, sale, leg, payment)
    return sale_detail(session, sale)


def _tender_kind(session: Session, principal: Principal, data: dict) -> str:
    """A payment leg names an enabled tender type; a stored payment method alone means its card."""
    if data.get("tender_type_id") is None:
        if data.get("payment_method_id") is None:
            raise ValidationFailed("Choose how the payment is made.", pointer="/tender_type_id")
        return "card"
    tender_type = next(
        (t for t in billing.catalogue.list_tender_types(session, principal) if t.id == data["tender_type_id"]), None
    )
    if tender_type is None or not tender_type.is_enabled or tender_type.kind not in _REGISTER_KINDS:
        raise ValidationFailed("This payment method is not taken at the register.", pointer="/tender_type_id",
                               code="tender-unavailable")  # fmt: skip
    return tender_type.kind


def _settle_leg(session: Session, sale: PosSale, leg: PosSaleTender, payment) -> None:
    if payment.status == "succeeded":
        leg.status = "captured"
        session.flush()
        return
    if payment.status in ("unknown", "initiated", "processing"):
        leg.status = "pending"
        session.flush()
        raise DomainError("The card processor did not answer; retry with the same Idempotency-Key.", status=503,
                          code="provider-unavailable", persist=True)  # fmt: skip
    if payment.status == "requires_action":
        billing.service.cancel_payment(session, payment.id)
    leg.status = "failed"
    session.flush()
    raise DomainError(payment.failure_message or "The payment was declined.", status=402, code="payment-declined",
                      persist=True, pos_sale_id=str(sale.id))  # fmt: skip


def _credit_available(session: Session, sale: PosSale, tenders: list[PosSaleTender]) -> int:
    """The client's account credit, less what this sale has already claimed: its own captured payment legs
    are unapplied until completion (so they show as credit) and its earlier credit legs are spoken for."""
    claimed = sum(
        t.amount_minor for t in tenders if t.status == "captured" and t.tender in ("payment", "account_credit")
    )
    return billing.service.credit_balance(session, sale.client_id) - claimed


def remove_tender(
    session: Session, principal: Principal, sale_id: UUID, tender_id: UUID, client_ip: str | None
) -> dict:
    """Take a leg back before completion (ours: the cart needs a way out of a captured leg). Money taken is
    returned through billing: a record-only payment is voided, a card payment refunded in full; each checks
    its own billing permission."""
    sale = _draft(session, principal, sale_id, client_ip)
    leg = get_row(session, PosSaleTender, tender_id, lock=True)
    if leg.pos_sale_id != sale.id:
        raise NotFound()
    if leg.status == "removed":
        return sale_detail(session, sale)
    if leg.status == "captured" and leg.payment_id is not None:
        reason = f"Removed from POS sale {sale.id}"
        if leg.tender_kind not in PROCESSED_KINDS:
            authorize(principal, "billing.payment.void", location_id=sale.location_id)
            billing.service.void_payment(session, leg.payment_id, reason=reason)
        else:
            authorize(principal, "billing.refund.create", location_id=sale.location_id)
            refund = billing.service.refund(session, leg.payment_id, amount_minor=leg.amount_minor, reason=reason,
                                            idempotency_key=f"pos:tender-remove:{leg.id}")  # fmt: skip
            if refund.status in ("failed", "cancelled"):
                raise DomainError("The card refund did not go through; try again.", status=502,
                                  code="refund-failed", persist=True)  # fmt: skip
    elif leg.status == "pending":
        raise Conflict("Resolve this payment first: retry it with the same Idempotency-Key.")
    leg.status = "removed"
    audit.record(session, _CREATE, sale, location_id=sale.location_id,
                 changes={f"tender_{leg.seq}": ["captured", "removed"]})  # fmt: skip
    session.flush()
    return sale_detail(session, sale)


# --- completion --------------------------------------------------------------------------------------------


def complete_sale(session: Session, principal: Principal, sale_id: UUID, client_ip: str | None) -> dict:
    sale = _sale(session, principal, sale_id, key=_CREATE, lock=True)
    if sale.status == "completed":
        return sale_detail(session, sale)  # a replay, even with another key
    if sale.status != "draft":
        raise Conflict("This sale is no longer open.")
    check_network(session, sale.location_id, client_ip)
    lines = _lines(session, sale.id)
    if not lines:
        raise ValidationFailed("The cart is empty.", pointer="/lines")
    recompute(session, sale)
    tenders = [t for t in _tenders(session, sale.id) if t.status == "captured"]
    if any(t.status == "pending" for t in _tenders(session, sale.id)):
        raise Conflict("A payment is still being confirmed; retry it first.", code="tender-pending")
    if captured_minor(tenders) != sale.total_minor:
        raise Conflict(
            f"Payments ({captured_minor(tenders)}) do not match the total ({sale.total_minor}).",
            code="tender-total-mismatch",
        )
    if sale.client_id is None and any(line.line_kind != "product" for line in lines):
        raise ValidationFailed(
            "Equipment rentals and packages need a client.", pointer="/client_id", code="client-required"
        )

    for line in lines:  # before any write: this refusal commits (it issues the document to sign)
        if line.line_kind == "package":
            packages.service.require_documents(session, line.package_plan_id, sale.client_id, sale.location_id)

    coupon = next((d for d in _discounts(session, sale.id) if d.source == "coupon"), None)
    coupon_lines: set[UUID] = set()
    if coupon is not None and coupon.applied_minor:
        priced = [line for line in lines if line.line_kind != "package"]
        before = [line.net_minor + _share(session, coupon.id, line.id) for line in priced]
        coupon_id, parts = billing.catalogue.redeem_coupon(
            session, sale.coupon_code, redemption_key=f"pos:pos_sale:{sale.id}", line_nets=before,
            redeemer_client_id=sale.client_id,
        )  # fmt: skip
        if sum(parts) != coupon.applied_minor:
            raise Conflict("The coupon's value changed; review the sale.", code="coupon-changed")
        coupon_lines = {line.id for line, part in zip(priced, parts, strict=True) if part}

    charge_ids = []
    for line in lines:
        if line.line_kind == "package":
            # packages owns the sale: it checks members-only and required documents (409 document-required),
            # grants the credits and posts its own charge, left uninvoiced so it joins this sale's invoice.
            sold = packages.service.sell(
                session, client_id=sale.client_id, location_id=sale.location_id, package_plan_id=line.package_plan_id,
                channel="pos", invoice_mode="deferred", sold_by_staff_user_id=principal.staff_user_id,
            )  # fmt: skip
            charge = billing.service.get_charge(session, sold["package"].charge_id)
            if charge.total_minor != line.total_minor:
                raise Conflict("The package's price changed; remove it and add it again.", code="price-changed")
            line.charge_id, line.fulfilment_id = charge.id, sold["package"].id
            charge_ids.append(charge.id)
            continue
        product = session.get(Product, line.product_id) if line.product_id else None
        charge = billing.service.post_charge(
            session, client_id=sale.client_id, location_id=sale.location_id, description=line.description,
            unit_price_minor=line.unit_price_minor, quantity=line.quantity, discount_minor=line.discount_minor,
            revenue_category_id=line.revenue_category_id, source_context="pos", source_type="pos_sale_line",
            source_id=line.id, coupon_id=coupon.coupon_id if line.id in coupon_lines else None,
            tax_ids=product_tax_ids(session, product) if product else None,
        )  # fmt: skip
        line.charge_id = charge.id
        charge_ids.append(charge.id)
    invoice = billing.service.create_invoice_for_charges(
        session, charge_ids, bill_to_client_id=sale.client_id, origin="pos", comments=sale.note
    )
    for leg in tenders:
        if leg.tender == "payment":
            billing.service.allocate(session, leg.payment_id, invoice_id=invoice.id)
        elif leg.tender == "account_credit":
            spent = billing.service.spend_credit(session, sale.client_id, invoice_id=invoice.id, limit=leg.amount_minor)
            if spent != leg.amount_minor:
                raise Conflict("The credit on account is no longer enough.", code="insufficient-credit")

    for line in lines:
        if line.line_kind == "product":
            product = session.get(Product, line.product_id)
            if product.is_stock_tracked:
                inventory.move(
                    session, product, sale.location_id, kind="sale", reason="sale",
                    delta=-line.quantity * product.units_per_sale, pos_sale_line_id=line.id,
                    staff_user_id=principal.staff_user_id,
                )  # fmt: skip
        elif line.line_kind == "equipment":
            equipment.check_out(session, principal, sale, line)

    drawer = open_drawer(session, sale.register_id)
    sale.drawer_session_id = drawer.id if drawer else sale.drawer_session_id
    sale.status, sale.completed_at = "completed", clock.now()
    sale.invoice_id, sale.invoice_number = invoice.id, invoice.number
    audit.record(session, _CREATE, sale, location_id=sale.location_id,
                 changes={"status": ["draft", "completed"], "total_minor": [None, sale.total_minor]})  # fmt: skip
    events.publish(
        session, SaleCompleted(pos_sale_id=sale.id, client_id=sale.client_id, invoice_id=invoice.id), sale.id
    )
    session.flush()
    return sale_detail(session, sale)


def _share(session: Session, discount_id: UUID, line_id: UUID) -> int:
    return (
        session.scalar(
            select(PosSaleDiscountLine.amount_minor).where(
                PosSaleDiscountLine.pos_sale_discount_id == discount_id, PosSaleDiscountLine.pos_sale_line_id == line_id
            )
        )
        or 0
    )


def abandon_sale(session: Session, principal: Principal, sale_id: UUID, client_ip: str | None) -> PosSale:
    """Clear the cart. Refused while money is captured: remove those legs (or complete) first."""
    sale = _draft(session, principal, sale_id, client_ip)
    _abandon(session, sale)
    audit.record(session, _CREATE, sale, location_id=sale.location_id, changes={"status": ["draft", "abandoned"]})
    session.flush()
    return sale


def _abandon(session: Session, sale: PosSale) -> None:
    if any(t.status in ("captured", "pending") and t.tender == "payment" for t in _tenders(session, sale.id)):
        raise Conflict("Money was taken on this sale; remove those payments first.", code="captured-tenders-exist")
    sale.status = "abandoned"


def abandon_stale_drafts(session: Session, *, idle: timedelta = timedelta(hours=24)) -> int:
    """Mark drafts untouched for `idle` abandoned, skipping any with money taken. Internal, for a daily job:
    nothing schedules it yet (the kernel has no scheduler; billing_daily has the same gap)."""
    cutoff: datetime = clock.now() - idle
    count = 0
    for sale in session.scalars(
        select(PosSale).where(PosSale.status == "draft", PosSale.updated_at < cutoff).with_for_update(skip_locked=True)
    ):
        try:
            _abandon(session, sale)
        except Conflict:
            continue
        audit.record(session, _CREATE, sale, location_id=sale.location_id, changes={"status": ["draft", "abandoned"]})
        count += 1
    session.flush()
    return count


# --- receipts (POS-13, POS-14) -----------------------------------------------------------------------------


def receipt(session: Session, principal: Principal, sale_id: UUID, return_id: UUID | None = None) -> dict:
    sale = _sale(session, principal, sale_id)
    return build_receipt(session, principal, sale, return_id)


def build_receipt(session: Session, principal: Principal, sale: PosSale, return_id: UUID | None) -> dict:
    """Rendered from the sale snapshot, so a re-send from history is identical to the original. Header from
    the location, footer from billing settings; price overrides and every discount are itemised."""
    if sale.status != "completed":
        raise Conflict("Only a completed sale has a receipt.")
    location = platform.service.get_location(session, principal, sale.location_id)
    detail = sale_detail(session, sale)
    returned = None
    if return_id is not None:
        returned = next((r for r in detail["returns"] if r["id"] == return_id), None)
        if returned is None:
            raise ValidationFailed("Unknown return for this sale.", pointer="/pos_return_id")
    labels = {t.id: t.label for t in billing.catalogue.list_tender_types(session, principal)}
    lines = [
        {
            "line_no": line["line_no"], "description": line["description"], "quantity": line["quantity"],
            "list_unit_price_minor": line["list_unit_price_minor"], "unit_price_minor": line["unit_price_minor"],
            "override_minor": (line["list_unit_price_minor"] - line["unit_price_minor"]) * line["quantity"],
            "discount_minor": line["discount_minor"], "tax_minor": line["tax_minor"], "total_minor": line["total_minor"],
            "returned_quantity": line["returned_quantity"],
        }
        for line in detail["lines"]
    ]  # fmt: skip
    tender_label = {"account_credit": "Account credit", "pay_later": "Pay later (invoice)"}
    address = ", ".join(p for p in (location.address_line1, location.address_line2, location.city, location.region,
                                    location.postal_code) if p)  # fmt: skip
    header = {
        "location_name": location.public_name or location.name, "address": address or None, "phone": location.phone,
        "website_url": location.website_url, "number": sale.invoice_number, "completed_at": sale.completed_at,
        "time_zone": location.time_zone, "client_name": detail["client_name"],
    }  # fmt: skip
    content = {
        "pos_sale_id": sale.id, "header": header, "lines": lines,
        "discounts": [{"label": d["label"], "applied_minor": d["applied_minor"]} for d in detail["discounts"]
                      if d["applied_minor"]],
        "tenders": [{"label": tender_label.get(t["tender"]) or labels.get(t["tender_type_id"], t["tender_kind"]),
                     "amount_minor": t["amount_minor"]} for t in detail["tenders"] if t["status"] == "captured"],
        "subtotal_minor": sale.subtotal_minor, "discount_minor": sale.discount_minor, "tax_minor": sale.tax_minor,
        "total_minor": sale.total_minor, "pos_return": returned,
        "footer": billing.catalogue.settings_for(session, sale.location_id).receipt_footer,
    }  # fmt: skip
    content["html"] = _receipt_html(content)
    return content


def _receipt_html(content: dict) -> str:
    """A self-contained fragment for printers and the email body; the web print page renders the same data."""
    data = _email_data(content)
    blocks = [data["location_name"], data["location_contact"], f"Receipt {data['number']}, {data['completed_at']}",
              data["lines"], data["totals"], data["tenders"], data["footer"]]  # fmt: skip
    return "".join(f"<p>{escape(block).replace(chr(10), '<br>')}</p>" for block in blocks if block)


def _money(minor: int) -> str:
    return f"{minor / 100:.2f}"  # shortcut: two-decimal currencies only, like billing's notices


def send_receipt(session: Session, principal: Principal, sale_id: UUID, data: dict) -> PosReceiptDelivery:
    """Print or email the receipt. The cashier of the sale needs only pos.sale.create; anyone else needs
    pos.receipt.resend. An email typed here is never written back to the client."""
    sale = _sale(session, principal, sale_id, key="pos.sale.read")
    if principal.staff_user_id != sale.cashier_staff_user_id or not principal.has(_CREATE):
        authorize(principal, "pos.receipt.resend", location_id=sale.location_id)
    content = build_receipt(session, principal, sale, data.get("pos_return_id"))
    channel = data["channel"]
    row = PosReceiptDelivery(pos_sale_id=sale.id, pos_return_id=data.get("pos_return_id"), channel=channel,
                             sent_by_staff_user_id=principal.staff_user_id, status="sent")  # fmt: skip
    if channel == "email":
        if not settings_for(session, sale.location_id).is_email_receipt_enabled:
            raise Conflict("Email receipts are turned off for this location.", code="email-receipt-disabled")
        row.to_email = data.get("to_email")
        if not row.to_email:
            raise ValidationFailed("Enter an email address.", pointer="/to_email")
        notifications.send(session, "pos.receipt", row.to_email, _email_data(content))
    session.add(row)
    session.flush()
    audit.record(session, "pos.receipt.resend", row, location_id=sale.location_id, changes={"channel": [None, channel]})
    return row


def _email_data(content: dict) -> dict:
    header = content["header"]
    lines = "\n".join(
        f"{line['quantity']} x {line['description']}  {_money(line['total_minor'])}" for line in content["lines"]
    )
    totals = (
        f"Subtotal {_money(content['subtotal_minor'])}\nDiscounts -{_money(content['discount_minor'])}\n"
        f"Tax {_money(content['tax_minor'])}\nTotal {_money(content['total_minor'])}"
    )
    tenders = "\n".join(f"{t['label']}  {_money(t['amount_minor'])}" for t in content["tenders"])
    contact = " | ".join(p for p in (header["address"], header["phone"], header["website_url"]) if p)
    local = header["completed_at"].astimezone(ZoneInfo(header["time_zone"]))
    return {
        "location_name": header["location_name"], "location_contact": contact, "number": header["number"],
        "completed_at": local.strftime("%Y-%m-%d %H:%M"), "lines": lines, "totals": totals,
        "tenders": tenders or "No payment taken", "footer": content["footer"] or "",
    }  # fmt: skip
