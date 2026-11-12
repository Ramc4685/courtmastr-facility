"""pos tables (docs/architecture/data-model-money.md section 2). A completed sale is an invoice, charges and
payments in billing; pos keeps the cart, the tender legs, the discount breakdown and the stock and equipment
side effects. Deviations from the data model are listed in README.md (stock transfers, the negative-stock and
network settings, tender_kind and cash_refunded_minor snapshots, no package lines yet)."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Index, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, WallTime, enum_check, enum_column, tenant_args, tfk


def _values(*values: str) -> type[StrEnum]:
    return StrEnum("Vocabulary", {value.upper(): value for value in values})


DrawerStatus = _values("open", "closed")
MovementKind = _values("adjustment", "set", "sale", "return", "transfer_out", "transfer_in")
MovementReason = _values("other", "discrepancy", "new_stock", "sale", "return", "transfer")
SaleStatus = _values("draft", "completed", "abandoned")
ReturnState = _values("none", "partial", "full")
LineKind = _values("product", "equipment", "package")
DiscountSource = _values("preset", "custom", "coupon", "product_default")
DiscountScope = _values("sale", "lines")
TenderLeg = _values("payment", "account_credit", "pay_later")
TenderStatus = _values("pending", "captured", "failed", "removed")
RefundMode = _values("original_tenders", "cash", "external", "account_credit")
ReceiptChannel = _values("print", "email")
DeliveryStatus = _values("queued", "sent", "failed")
LoanStatus = _values("open", "returned", "lost")
ReturnCondition = _values("good", "damaged")


def _money(**kwargs) -> Mapped[int]:
    return mapped_column(BigInteger, **kwargs)


def _zero() -> Mapped[int]:
    return mapped_column(BigInteger, server_default=text("0"))


def _true() -> Mapped[bool]:
    return mapped_column(server_default=text("true"))


def _false() -> Mapped[bool]:
    return mapped_column(server_default=text("false"))


def _sort() -> Mapped[int]:
    return mapped_column(server_default=text("0"))


# --- 2.1 registers and settings ----------------------------------------------------------------------------


class Register(TenantOwned, Timestamps, Base):
    __tablename__ = "register"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", "name", name="uq_register_name"),
    )

    location_id: Mapped[UUID]
    name: Mapped[str]
    is_favorites_enabled: Mapped[bool] = _false()
    is_active: Mapped[bool] = _true()


class RegisterFavorite(TenantOwned, Timestamps, Base):
    __tablename__ = "register_favorite"
    __table_args__ = tenant_args(
        *tfk("register_id", "register", ondelete="CASCADE", index=False),
        *tfk("product_id", "product"),
        UniqueConstraint("tenant_id", "register_id", "product_id", name="uq_register_favorite"),
    )

    register_id: Mapped[UUID]
    product_id: Mapped[UUID]
    sort_order: Mapped[int] = _sort()


class DrawerSession(TenantOwned, Timestamps, Base):
    __tablename__ = "drawer_session"
    __table_args__ = tenant_args(
        *tfk("register_id", "register"),
        *tfk("location_id", "location"),
        *tfk("opened_by_staff_user_id", "staff_user"),
        *tfk("closed_by_staff_user_id", "staff_user"),
        *tfk("reconciled_by_staff_user_id", "staff_user"),
        enum_check("status", DrawerStatus),
        CheckConstraint("reconciled_at IS NULL OR status = 'closed'", name="reconciled"),
        Index(
            "uq_drawer_session_open", "tenant_id", "register_id", unique=True, postgresql_where=text("status = 'open'")
        ),
        CheckConstraint(
            "(status = 'closed') = (closed_at IS NOT NULL AND expected_cash_minor IS NOT NULL "
            "AND counted_cash_minor IS NOT NULL)",
            name="closed",
        ),
        CheckConstraint("opening_float_minor >= 0 AND COALESCE(counted_cash_minor, 0) >= 0", name="amounts"),
    )

    register_id: Mapped[UUID]
    location_id: Mapped[UUID]
    status: Mapped[str] = enum_column(server_default=text("'open'"))
    opened_by_staff_user_id: Mapped[UUID]
    opened_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    opening_float_minor: Mapped[int] = _zero()
    closed_by_staff_user_id: Mapped[UUID | None]
    closed_at: Mapped[datetime | None]
    expected_cash_minor: Mapped[int | None] = mapped_column(BigInteger)
    counted_cash_minor: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None]
    reconciled_at: Mapped[datetime | None]  # a manager accepted the variance (closed sessions only)
    reconciled_by_staff_user_id: Mapped[UUID | None]
    reconcile_note: Mapped[str | None]


class PosSettings(TenantOwned, Timestamps, Base):
    """The tenant row (location_id null) plus optional location overrides, like billing_settings."""

    __tablename__ = "pos_settings"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        Index("uq_pos_settings_location", "tenant_id", "location_id", unique=True, postgresql_nulls_not_distinct=True),
    )

    location_id: Mapped[UUID | None]
    is_email_receipt_enabled: Mapped[bool] = _true()
    is_auto_print_receipt: Mapped[bool] = _false()
    is_drawer_session_required: Mapped[bool] = _false()
    low_stock_alert_email: Mapped[str | None] = mapped_column(CITEXT)
    receipt_footer: Mapped[str | None]  # POS-14: blank falls back to billing's receipt_footer
    # Ours (README): stock may only go below zero where this is on; the register is usable only from these
    # networks when the list is not empty.
    is_negative_stock_allowed: Mapped[bool] = _false()
    allowed_networks: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), info={"audit": "value"}
    )


class PosLowStockDigest(TenantOwned, Timestamps, Base):
    """One row per location per local day the low-stock digest was emailed (POS-22): the job's idempotency key."""

    __tablename__ = "pos_low_stock_digest"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", "local_on", name="uq_pos_low_stock_digest_day"),
    )

    location_id: Mapped[UUID]
    local_on: Mapped[date]
    sent_to: Mapped[str] = mapped_column(CITEXT)
    item_count: Mapped[int]


# --- 2.2 products and stock --------------------------------------------------------------------------------


class ProductCategory(TenantOwned, Timestamps, Base):
    __tablename__ = "product_category"
    __table_args__ = tenant_args(
        *tfk("parent_id", "product_category"),
        *tfk("revenue_category_id", "revenue_category"),
        Index(
            "uq_product_category_name", "tenant_id", "parent_id", "name", unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("parent_id <> id", name="not_self"),
    )  # fmt: skip

    parent_id: Mapped[UUID | None]
    name: Mapped[str]
    revenue_category_id: Mapped[UUID | None]
    sort_order: Mapped[int] = _sort()
    is_active: Mapped[bool] = _true()


class ProductCategoryTax(TenantOwned, Timestamps, Base):
    __tablename__ = "product_category_tax"
    __table_args__ = tenant_args(
        *tfk("product_category_id", "product_category", ondelete="CASCADE", index=False),
        *tfk("tax_id", "tax"),
        UniqueConstraint("tenant_id", "product_category_id", "tax_id", name="uq_product_category_tax"),
    )

    product_category_id: Mapped[UUID]
    tax_id: Mapped[UUID]


class ProductBrand(TenantOwned, Timestamps, Base):
    __tablename__ = "product_brand"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "name", name="uq_product_brand_name"))

    name: Mapped[str]
    is_active: Mapped[bool] = _true()


class ProductSupplier(TenantOwned, Timestamps, Base):
    __tablename__ = "product_supplier"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "name", name="uq_product_supplier_name"))

    name: Mapped[str]
    contact_name: Mapped[str | None]
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None]
    address: Mapped[str | None]
    account_reference: Mapped[str | None]
    notes: Mapped[str | None]
    is_active: Mapped[bool] = _true()


class Product(TenantOwned, Timestamps, Base):
    __tablename__ = "product"
    __table_args__ = tenant_args(
        *tfk("product_category_id", "product_category"),
        *tfk("product_brand_id", "product_brand"),
        *tfk("product_supplier_id", "product_supplier"),
        *tfk("revenue_category_id", "revenue_category"),
        UniqueConstraint("tenant_id", "product_code", name="uq_product_code"),
        Index("uq_product_sku", "tenant_id", "sku", unique=True, postgresql_where=text("sku IS NOT NULL")),
        Index("ix_product_search", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        CheckConstraint("unit_price_minor >= 0 AND COALESCE(cost_minor, 0) >= 0", name="amounts"),
        CheckConstraint("units_per_sale >= 1", name="units_per_sale"),
        CheckConstraint("default_discount_pct IS NULL OR default_discount_pct BETWEEN 0 AND 100", name="discount"),
        CheckConstraint("reorder_level IS NULL OR reorder_level >= 0", name="reorder_level"),
    )

    product_category_id: Mapped[UUID]
    product_brand_id: Mapped[UUID | None]
    product_supplier_id: Mapped[UUID | None]
    name: Mapped[str]
    product_code: Mapped[str] = mapped_column(CITEXT, info={"audit": "value"})
    sku: Mapped[str | None] = mapped_column(CITEXT, info={"audit": "value"})
    description: Mapped[str | None]
    unit_price_minor: Mapped[int] = _money(info={"audit": "value"})
    cost_minor: Mapped[int | None] = mapped_column(BigInteger, info={"audit": "value"})
    units_per_sale: Mapped[int] = mapped_column(server_default=text("1"))
    default_discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    reorder_level: Mapped[int | None]
    revenue_category_id: Mapped[UUID | None]
    is_tax_inherited: Mapped[bool] = _true()
    is_stock_tracked: Mapped[bool] = _true()
    is_active: Mapped[bool] = _true()


class ProductTax(TenantOwned, Timestamps, Base):
    __tablename__ = "product_tax"
    __table_args__ = tenant_args(
        *tfk("product_id", "product", ondelete="CASCADE", index=False),
        *tfk("tax_id", "tax"),
        UniqueConstraint("tenant_id", "product_id", "tax_id", name="uq_product_tax"),
    )

    product_id: Mapped[UUID]
    tax_id: Mapped[UUID]


class ProductStock(TenantOwned, Timestamps, Base):
    __tablename__ = "product_stock"
    __table_args__ = tenant_args(
        *tfk("product_id", "product", index=False),
        *tfk("location_id", "location"),
        UniqueConstraint("tenant_id", "product_id", "location_id", name="uq_product_stock"),
    )

    product_id: Mapped[UUID]
    location_id: Mapped[UUID]
    on_hand_count: Mapped[int] = mapped_column(server_default=text("0"))
    low_stock_notified_at: Mapped[datetime | None]


class StockMovement(TenantOwned, Base):
    """Append-only. Written with product_stock under SELECT ... FOR UPDATE on the stock row."""

    __tablename__ = "stock_movement"
    __table_args__ = tenant_args(
        *tfk("product_id", "product", index=False),
        *tfk("location_id", "location"),
        *tfk("pos_sale_line_id", "pos_sale_line", index=False),
        *tfk("pos_return_line_id", "pos_return_line", index=False),
        *tfk("created_by_staff_user_id", "staff_user"),
        enum_check("kind", MovementKind),
        enum_check("reason", MovementReason),
        CheckConstraint("(kind = 'set') = (set_to_count IS NOT NULL)", name="set"),
        CheckConstraint("(kind IN ('transfer_out', 'transfer_in')) = (transfer_id IS NOT NULL)", name="transfer"),
        Index(
            "uq_stock_movement_sale_line", "tenant_id", "pos_sale_line_id", unique=True,
            postgresql_where=text("kind = 'sale'"),
        ),
        Index(
            "uq_stock_movement_return_line", "tenant_id", "pos_return_line_id", unique=True,
            postgresql_where=text("kind = 'return'"),
        ),
        Index("ix_stock_movement_product", "tenant_id", "product_id", "location_id", "id"),
    )  # fmt: skip

    product_id: Mapped[UUID]
    location_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    quantity_delta: Mapped[int] = mapped_column(info={"audit": "value"})
    set_to_count: Mapped[int | None]
    resulting_count: Mapped[int]
    reason: Mapped[str] = enum_column()
    effective_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    comment: Mapped[str | None]
    transfer_id: Mapped[UUID | None]  # pairs the two rows of a transfer; not an FK
    pos_sale_line_id: Mapped[UUID | None]
    pos_return_line_id: Mapped[UUID | None]
    created_by_staff_user_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), sort_order=98)


# --- 2.3 sales ---------------------------------------------------------------------------------------------


class DiscountPreset(TenantOwned, Timestamps, Base):
    __tablename__ = "discount_preset"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "name", name="uq_discount_preset_name"),
        CheckConstraint(
            "num_nonnulls(discount_pct, discount_minor) = 1 AND COALESCE(discount_pct, 1) BETWEEN 0.01 AND 100 "
            "AND COALESCE(discount_minor, 1) > 0",
            name="value",
        ),
    )

    name: Mapped[str]
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount_minor: Mapped[int | None] = mapped_column(BigInteger)
    sort_order: Mapped[int] = _sort()
    is_active: Mapped[bool] = _true()


class PosSale(TenantOwned, Timestamps, Base):
    __tablename__ = "pos_sale"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("register_id", "register", index=False),
        *tfk("drawer_session_id", "drawer_session"),
        *tfk("cashier_staff_user_id", "staff_user"),
        *tfk("client_id", "client", index=False),
        *tfk("invoice_id", "invoice", index=False),
        enum_check("status", SaleStatus),
        enum_check("return_state", ReturnState),
        Index("uq_pos_sale_invoice", "tenant_id", "invoice_id", unique=True, postgresql_where=text("invoice_id IS NOT NULL")),
        Index("ix_pos_sale_draft", "tenant_id", "register_id", unique=True, postgresql_where=text("status = 'draft'")),
        Index(
            "ix_pos_sale_completed", "tenant_id", "location_id", text("completed_at DESC"), text("id DESC"),
            postgresql_where=text("status = 'completed'"),
        ),
        Index("ix_pos_sale_client", "tenant_id", "client_id", text("completed_at DESC")),
        CheckConstraint("total_minor = subtotal_minor - discount_minor + tax_minor", name="total"),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL AND invoice_id IS NOT NULL)", name="completed"
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    register_id: Mapped[UUID]
    drawer_session_id: Mapped[UUID | None]
    cashier_staff_user_id: Mapped[UUID]
    client_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'draft'"))
    return_state: Mapped[str] = enum_column(server_default=text("'none'"))
    invoice_id: Mapped[UUID | None]
    invoice_number: Mapped[int | None]  # snapshot: the transaction search key, without reading billing tables
    coupon_code: Mapped[str | None] = mapped_column(CITEXT, info={"audit": "value"})
    note: Mapped[str | None]
    subtotal_minor: Mapped[int] = _zero()
    discount_minor: Mapped[int] = _zero()
    tax_minor: Mapped[int] = _zero()
    total_minor: Mapped[int] = _zero()
    completed_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(server_default=text("1"))


class PosSaleLine(TenantOwned, Timestamps, Base):
    __tablename__ = "pos_sale_line"
    __table_args__ = tenant_args(
        *tfk("pos_sale_id", "pos_sale", ondelete="CASCADE", index=False),
        *tfk("product_id", "product"),
        *tfk("equipment_item_id", "equipment_item"),
        *tfk("price_overridden_by_staff_user_id", "staff_user"),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("charge_id", "charge"),
        enum_check("line_kind", LineKind),
        UniqueConstraint("tenant_id", "pos_sale_id", "line_no", name="uq_pos_sale_line_no"),
        *tfk("package_plan_id", "package_plan"),
        CheckConstraint(
            "(line_kind = 'product') = (product_id IS NOT NULL) AND (line_kind = 'equipment') = "
            "(equipment_item_id IS NOT NULL) AND (line_kind = 'package') = (package_plan_id IS NOT NULL)",
            name="target",
        ),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint("returned_quantity BETWEEN 0 AND quantity", name="returned"),
        CheckConstraint(
            "(price_overridden_by_staff_user_id IS NOT NULL) = (unit_price_minor <> list_unit_price_minor)",
            name="override",
        ),
    )  # fmt: skip

    pos_sale_id: Mapped[UUID]
    line_no: Mapped[int]
    line_kind: Mapped[str] = enum_column()
    product_id: Mapped[UUID | None]
    equipment_item_id: Mapped[UUID | None]
    package_plan_id: Mapped[UUID | None]  # POS-19: packages.sell runs at completion
    fulfilment_id: Mapped[UUID | None]  # what completion created: client_package.id for a package line (not an FK)
    description: Mapped[str]
    quantity: Mapped[int] = mapped_column(server_default=text("1"), info={"audit": "value"})
    list_unit_price_minor: Mapped[int] = _money()
    unit_price_minor: Mapped[int] = _money(info={"audit": "value"})
    price_overridden_by_staff_user_id: Mapped[UUID | None]
    discount_minor: Mapped[int] = _zero()
    net_minor: Mapped[int] = _money()
    tax_minor: Mapped[int] = _zero()
    total_minor: Mapped[int] = _money()
    revenue_category_id: Mapped[UUID]
    charge_id: Mapped[UUID | None]
    returned_quantity: Mapped[int] = mapped_column(server_default=text("0"))


class PosSaleDiscount(TenantOwned, Timestamps, Base):
    __tablename__ = "pos_sale_discount"
    __table_args__ = tenant_args(
        *tfk("pos_sale_id", "pos_sale", ondelete="CASCADE", index=False),
        *tfk("discount_preset_id", "discount_preset"),
        *tfk("coupon_id", "coupon"),
        enum_check("source", DiscountSource),
        enum_check("scope", DiscountScope),
        Index(
            "uq_pos_sale_discount_coupon", "tenant_id", "pos_sale_id", unique=True,
            postgresql_where=text("source = 'coupon'"),
        ),
        CheckConstraint("num_nonnulls(discount_pct, discount_minor) = 1", name="value"),
    )  # fmt: skip

    pos_sale_id: Mapped[UUID]
    source: Mapped[str] = enum_column()
    discount_preset_id: Mapped[UUID | None]
    coupon_id: Mapped[UUID | None]
    label: Mapped[str]
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount_minor: Mapped[int | None] = mapped_column(BigInteger)
    scope: Mapped[str] = enum_column()
    applied_minor: Mapped[int] = _zero()
    seq: Mapped[int]


class PosSaleDiscountLine(TenantOwned, Timestamps, Base):
    __tablename__ = "pos_sale_discount_line"
    __table_args__ = tenant_args(
        *tfk("pos_sale_discount_id", "pos_sale_discount", ondelete="CASCADE", index=False),
        *tfk("pos_sale_line_id", "pos_sale_line", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "pos_sale_discount_id", "pos_sale_line_id", name="uq_pos_sale_discount_line"),
    )

    pos_sale_discount_id: Mapped[UUID]
    pos_sale_line_id: Mapped[UUID]
    amount_minor: Mapped[int] = _zero()


class PosSaleTender(TenantOwned, Timestamps, Base):
    __tablename__ = "pos_sale_tender"
    __table_args__ = tenant_args(
        *tfk("pos_sale_id", "pos_sale", ondelete="CASCADE", index=False),
        *tfk("tender_type_id", "tender_type"),
        *tfk("payment_method_id", "payment_method"),
        *tfk("payment_id", "payment"),
        enum_check("tender", TenderLeg),
        enum_check("status", TenderStatus),
        UniqueConstraint("tenant_id", "pos_sale_id", "seq", name="uq_pos_sale_tender_seq"),
        CheckConstraint(
            "(tender = 'payment') = (tender_kind IS NOT NULL) AND (tender = 'payment' OR payment_id IS NULL)",
            name="shape",
        ),
        CheckConstraint("amount_minor > 0", name="amount"),
    )

    pos_sale_id: Mapped[UUID]
    seq: Mapped[int]
    tender: Mapped[str] = enum_column()
    tender_kind: Mapped[str | None] = enum_column()  # snapshot of billing's tender kind (cash counts the drawer)
    tender_type_id: Mapped[UUID | None]
    payment_method_id: Mapped[UUID | None]
    amount_minor: Mapped[int] = _money(info={"audit": "value"})
    payment_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'pending'"))


class PosReturn(TenantOwned, Timestamps, Base):
    __tablename__ = "pos_return"
    __table_args__ = tenant_args(
        *tfk("pos_sale_id", "pos_sale"),
        *tfk("location_id", "location"),
        *tfk("register_id", "register"),
        *tfk("drawer_session_id", "drawer_session"),
        *tfk("processed_by_staff_user_id", "staff_user"),
        enum_check("refund_mode", RefundMode),
        CheckConstraint("amount_minor >= 0 AND refunded_minor >= 0 AND cash_refunded_minor >= 0", name="amounts"),
    )

    pos_sale_id: Mapped[UUID]
    location_id: Mapped[UUID]
    register_id: Mapped[UUID | None]
    drawer_session_id: Mapped[UUID | None]
    refund_mode: Mapped[str] = enum_column()
    amount_minor: Mapped[int] = _money(info={"audit": "value"})
    refunded_minor: Mapped[int] = _zero()  # money that left; the rest of amount_minor stayed as account credit
    cash_refunded_minor: Mapped[int] = _zero()  # of which handed back from the drawer
    refund_batch_id: Mapped[UUID | None]
    reason: Mapped[str | None]
    processed_by_staff_user_id: Mapped[UUID]
    processed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class PosReturnLine(TenantOwned, Timestamps, Base):
    __tablename__ = "pos_return_line"
    __table_args__ = tenant_args(
        *tfk("pos_return_id", "pos_return", ondelete="CASCADE", index=False),
        *tfk("pos_sale_line_id", "pos_sale_line"),
        *tfk("adjustment_charge_id", "charge"),
        CheckConstraint("quantity > 0", name="quantity"),
    )

    pos_return_id: Mapped[UUID]
    pos_sale_line_id: Mapped[UUID]
    quantity: Mapped[int] = mapped_column(info={"audit": "value"})
    amount_minor: Mapped[int] = _money()
    is_restocked: Mapped[bool] = _true()
    adjustment_charge_id: Mapped[UUID | None]


class PosReceiptDelivery(TenantOwned, Timestamps, Base):
    __tablename__ = "pos_receipt_delivery"
    __table_args__ = tenant_args(
        *tfk("pos_sale_id", "pos_sale"),
        *tfk("pos_return_id", "pos_return"),
        *tfk("sent_by_staff_user_id", "staff_user"),
        enum_check("channel", ReceiptChannel),
        enum_check("status", DeliveryStatus),
        CheckConstraint("channel = 'print' OR to_email IS NOT NULL", name="email"),
    )

    pos_sale_id: Mapped[UUID]
    pos_return_id: Mapped[UUID | None]
    channel: Mapped[str] = enum_column()
    to_email: Mapped[str | None] = mapped_column(CITEXT)
    status: Mapped[str] = enum_column(server_default=text("'queued'"))
    message_id: Mapped[UUID | None]
    sent_by_staff_user_id: Mapped[UUID | None]


# --- 2.5 equipment -----------------------------------------------------------------------------------------


class EquipmentCategory(TenantOwned, Timestamps, Base):
    __tablename__ = "equipment_category"
    __table_args__ = tenant_args(
        *tfk("revenue_category_id", "revenue_category"),
        UniqueConstraint("tenant_id", "name", name="uq_equipment_category_name"),
    )

    name: Mapped[str]
    revenue_category_id: Mapped[UUID | None]
    sort_order: Mapped[int] = _sort()
    is_active: Mapped[bool] = _true()


class EquipmentItem(TenantOwned, Timestamps, Base):
    __tablename__ = "equipment_item"
    __table_args__ = tenant_args(
        *tfk("equipment_category_id", "equipment_category"),
        *tfk("location_id", "location"),
        *tfk("revenue_category_id", "revenue_category"),
        UniqueConstraint("tenant_id", "asset_code", name="uq_equipment_item_asset_code"),
        CheckConstraint("on_loan_count BETWEEN 0 AND unit_count", name="on_loan"),
        CheckConstraint("unit_count >= 1 AND rental_days >= 0", name="counts"),
        CheckConstraint("rental_fee_minor >= 0 AND late_fee_minor >= 0 AND replacement_fee_minor >= 0", name="fees"),
    )

    equipment_category_id: Mapped[UUID]
    location_id: Mapped[UUID]
    name: Mapped[str]
    asset_code: Mapped[str] = mapped_column(CITEXT, info={"audit": "value"})
    description: Mapped[str | None]
    rental_fee_minor: Mapped[int] = _zero()
    rental_days: Mapped[int] = mapped_column(server_default=text("0"))
    return_time: Mapped[str | None] = mapped_column(WallTime)
    late_fee_minor: Mapped[int] = _zero()
    replacement_fee_minor: Mapped[int] = _zero()
    revenue_category_id: Mapped[UUID | None]
    unit_count: Mapped[int] = mapped_column(server_default=text("1"))
    on_loan_count: Mapped[int] = mapped_column(server_default=text("0"))
    sort_order: Mapped[int] = _sort()
    is_active: Mapped[bool] = _true()


class EquipmentLoan(TenantOwned, Timestamps, Base):
    __tablename__ = "equipment_loan"
    __table_args__ = tenant_args(
        *tfk("equipment_item_id", "equipment_item"),
        *tfk("client_id", "client"),
        *tfk("location_id", "location", index=False),
        *tfk("pos_sale_line_id", "pos_sale_line", index=False),
        *tfk("returned_by_staff_user_id", "staff_user"),
        *tfk("late_fee_charge_id", "charge"),
        *tfk("replacement_fee_charge_id", "charge"),
        enum_check("status", LoanStatus),
        CheckConstraint("return_condition IN ('good', 'damaged')", name="return_condition"),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint("(status = 'open') = (returned_at IS NULL)", name="returned"),
        Index(
            "uq_equipment_loan_sale_line", "tenant_id", "pos_sale_line_id", unique=True,
            postgresql_where=text("pos_sale_line_id IS NOT NULL"),
        ),
        Index("ix_equipment_loan_open", "tenant_id", "location_id", "due_at", postgresql_where=text("status = 'open'")),
    )  # fmt: skip

    equipment_item_id: Mapped[UUID]
    client_id: Mapped[UUID]
    location_id: Mapped[UUID]
    pos_sale_line_id: Mapped[UUID | None]
    quantity: Mapped[int] = mapped_column(server_default=text("1"))
    checked_out_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    due_at: Mapped[datetime]
    status: Mapped[str] = enum_column(server_default=text("'open'"))
    returned_at: Mapped[datetime | None]
    returned_by_staff_user_id: Mapped[UUID | None]
    return_condition: Mapped[str | None] = enum_column()
    late_fee_charge_id: Mapped[UUID | None]
    replacement_fee_charge_id: Mapped[UUID | None]
    note: Mapped[str | None]
