"""rentals tables (docs/architecture/data-model-core.md section 5). `locker_lease` is not built: its `locker`
and `locker_term` tables in resources do not exist yet (see README)."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Numeric, SmallInteger, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, WallTime, enum_check, enum_column, tenant_args, tfk


class Access(StrEnum):
    STAFF_ONLY = "staff_only"
    SELF_SERVICE = "self_service"


class Eligibility(StrEnum):
    EVERYONE = "everyone"
    ACTIVE_MEMBERS = "active_members"
    PAID_UP_MEMBERS = "paid_up_members"


class PaymentMode(StrEnum):
    PAY_IN_FULL = "pay_in_full"
    PAY_LATER = "pay_later"


class Basis(StrEnum):
    PER_HOUR = "per_hour"
    PER_OCCURRENCE = "per_occurrence"
    FLAT = "flat"


class MultiResourceMode(StrEnum):
    ONCE = "once"
    PER_RESOURCE = "per_resource"


class LineGrouping(StrEnum):
    COMBINED = "combined"
    PER_RESOURCE = "per_resource"
    PER_OCCURRENCE = "per_occurrence"
    PER_RESOURCE_OCCURRENCE = "per_resource_occurrence"


class RuleKind(StrEnum):
    RATE = "rate"
    DISCOUNT = "discount"


class ChargeState(StrEnum):
    UNBILLED = "unbilled"
    NO_CHARGE = "no_charge"
    BILLED = "billed"
    PLAN_COVERED = "plan_covered"


class BookedVia(StrEnum):
    STAFF = "staff"
    PORTAL = "portal"
    MOBILE = "mobile"
    API = "api"


class Routing(StrEnum):
    NEW_SINGLE = "new_single"
    NEW_PER_LINE = "new_per_line"
    DATE_BASED = "date_based"
    EXISTING_OPEN = "existing_open"
    CART = "cart"


class RoutingPeriod(StrEnum):
    WEEK = "week"
    MONTH = "month"


class PlanModel(StrEnum):
    PER_HOUR = "per_hour"
    PER_OCCURRENCE = "per_occurrence"


class PlanStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class StartMode(StrEnum):
    SALE_DATE = "sale_date"
    FIXED_DATE = "fixed_date"


class PurchaseStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SoldVia(StrEnum):
    STAFF = "staff"
    PORTAL = "portal"
    MOBILE = "mobile"


class CancelMode(StrEnum):
    REVERSE_BILLING = "reverse_billing"
    KEEP_BILLING = "keep_billing"


class EntryType(StrEnum):
    GRANT = "grant"
    DEBIT = "debit"
    CREDIT = "credit"
    EXPIRE = "expire"
    ADJUST = "adjust"


def _small(default: int) -> Mapped[int]:
    return mapped_column(SmallInteger, server_default=text(str(default)))


class RentalType(TenantOwned, Timestamps, Base):
    """What is rented and how it may be sold online (RNT-01, RNT-05, RNT-07). `deposit_pct`,
    `cancel_cutoff_hours` and `late_cancel_fee_pct` are our own design: no public source describes rental
    deposits or cancellation policies (discovery unknowns item 9)."""

    __tablename__ = "rental_type"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("revenue_category_id", "revenue_category"),
        ForeignKeyConstraint(  # rental_rate points back at rental_type: created after both tables
            ["tenant_id", "online_rental_rate_id"], ["rental_rate.tenant_id", "rental_rate.id"],
            ondelete="RESTRICT", use_alter=True,
        ),
        enum_check("access", Access),
        enum_check("eligibility", Eligibility),
        enum_check("online_payment_mode", PaymentMode),
        Index(
            "uq_rental_type_name", "tenant_id", "location_id", "name", unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint("access = 'staff_only' OR online_rental_rate_id IS NOT NULL", name="online_rate"),
        CheckConstraint(
            "min_length_min > 0 AND (max_length_min IS NULL OR max_length_min >= min_length_min) "
            "AND (default_length_min IS NULL OR default_length_min >= min_length_min)",
            name="lengths",
        ),
        CheckConstraint("buffer_before_min BETWEEN 0 AND 240 AND buffer_after_min BETWEEN 0 AND 240", name="buffers"),
        CheckConstraint("color IS NULL OR color ~ '^#[0-9a-f]{6}$'", name="color"),
        CheckConstraint("slot_granularity_min IN (15, 30, 60)", name="granularity"),
        CheckConstraint("min_lead_min >= 0", name="lead"),
        CheckConstraint("deposit_pct IS NULL OR (deposit_pct > 0 AND deposit_pct <= 100)", name="deposit"),
        CheckConstraint(
            "(cancel_cutoff_hours IS NULL OR cancel_cutoff_hours > 0) AND (late_cancel_fee_pct IS NULL OR "
            "(cancel_cutoff_hours IS NOT NULL AND late_cancel_fee_pct > 0 AND late_cancel_fee_pct <= 100))",
            name="cancel_policy",
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    revenue_category_id: Mapped[UUID]
    color: Mapped[str | None] = mapped_column(info={"audit": "value"})
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    buffer_before_min: Mapped[int] = _small(0)
    buffer_after_min: Mapped[int] = _small(0)
    access: Mapped[str] = enum_column(server_default=text("'staff_only'"))
    online_rental_rate_id: Mapped[UUID | None]
    eligibility: Mapped[str] = enum_column(server_default=text("'everyone'"))
    online_payment_mode: Mapped[str] = enum_column(server_default=text("'pay_in_full'"))
    min_lead_min: Mapped[int] = mapped_column(server_default=text("0"))
    default_length_min: Mapped[int | None]
    min_length_min: Mapped[int] = mapped_column(server_default=text("60"))
    max_length_min: Mapped[int | None]
    slot_granularity_min: Mapped[int] = _small(60)
    online_description: Mapped[str | None]
    deposit_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), info={"audit": "value"})
    cancel_cutoff_hours: Mapped[int | None] = mapped_column(info={"audit": "value"})
    late_cancel_fee_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), info={"audit": "value"})
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class RentalTypeResource(TenantOwned, Timestamps, Base):
    """Resources a type may be booked on; online search offers exactly these rows."""

    __tablename__ = "rental_type_resource"
    __table_args__ = tenant_args(
        *tfk("rental_type_id", "rental_type", ondelete="CASCADE", index=False),
        *tfk("resource_id", "resource"),
        UniqueConstraint("tenant_id", "rental_type_id", "resource_id", name="uq_rental_type_resource"),
    )

    rental_type_id: Mapped[UUID]
    resource_id: Mapped[UUID]


class RentalRate(TenantOwned, Timestamps, Base):
    __tablename__ = "rental_rate"
    __table_args__ = tenant_args(
        *tfk("rental_type_id", "rental_type", index=False),
        enum_check("basis", Basis),
        enum_check("multi_resource_mode", MultiResourceMode),
        enum_check("line_grouping", LineGrouping),
        Index(
            "uq_rental_rate_name", "tenant_id", "rental_type_id", "name", unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint(
            "amount_minor >= 0 AND (member_amount_minor IS NULL OR member_amount_minor >= 0)", name="amounts"
        ),
    )  # fmt: skip

    rental_type_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    internal_note: Mapped[str | None]
    amount_minor: Mapped[int] = mapped_column(info={"audit": "value"})
    member_amount_minor: Mapped[int | None] = mapped_column(info={"audit": "value"})
    basis: Mapped[str] = enum_column()
    multi_resource_mode: Mapped[str] = enum_column(server_default=text("'per_resource'"))
    line_grouping: Mapped[str] = enum_column(server_default=text("'combined'"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class RentalRateTax(TenantOwned, Timestamps, Base):
    """Default taxes of a rate. Deviation: references billing `tax`, not `tax_rate` (a dated rate row would
    stop applying when the rate changes); the rate in force is billing's to pick."""

    __tablename__ = "rental_rate_tax"
    __table_args__ = tenant_args(
        *tfk("rental_rate_id", "rental_rate", ondelete="CASCADE", index=False),
        *tfk("tax_id", "tax"),
        UniqueConstraint("tenant_id", "rental_rate_id", "tax_id", name="uq_rental_rate_tax"),
    )

    rental_rate_id: Mapped[UUID]
    tax_id: Mapped[UUID]


class RentalRateRule(TenantOwned, Timestamps, Base):
    """Conditional price changes on a rate. `membership_type_id` gets its FK from the memberships migration."""

    __tablename__ = "rental_rate_rule"
    __table_args__ = tenant_args(
        *tfk("rental_rate_id", "rental_rate", ondelete="CASCADE", index=False),
        enum_check("kind", RuleKind),
        CheckConstraint(
            "(kind = 'rate' AND amount_minor >= 0 AND discount_pct IS NULL AND discount_minor IS NULL) OR "
            "(kind = 'discount' AND amount_minor IS NULL AND num_nonnulls(discount_pct, discount_minor) = 1 "
            "AND (discount_pct IS NULL OR (discount_pct > 0 AND discount_pct <= 100)) "
            "AND (discount_minor IS NULL OR discount_minor > 0))",
            name="value",
        ),
        CheckConstraint(
            "(start_time IS NULL) = (end_time IS NULL) AND (start_time IS NULL OR end_time > start_time)", name="band"
        ),
        CheckConstraint("starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on", name="dates"),
        Index("ix_rental_rate_rule_order", "tenant_id", "rental_rate_id", "sort_order"),
    )  # fmt: skip

    rental_rate_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    name: Mapped[str] = mapped_column(server_default=text("''"), info={"audit": "value"})
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    start_time: Mapped[str | None] = mapped_column(WallTime)
    end_time: Mapped[str | None] = mapped_column(WallTime)
    starts_on: Mapped[date | None]
    ends_on: Mapped[date | None]
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    membership_type_id: Mapped[UUID | None]
    amount_minor: Mapped[int | None] = mapped_column(info={"audit": "value"})
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), info={"audit": "value"})
    discount_minor: Mapped[int | None] = mapped_column(info={"audit": "value"})


class RentalBooking(TenantOwned, Timestamps, Base):
    """Rentals' row for each booking of kind 'rental': the charge decision of one occurrence."""

    __tablename__ = "rental_booking"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("booking_id", "booking", index=False),
        *tfk("rental_type_id", "rental_type", index=False),
        UniqueConstraint("tenant_id", "booking_id", name="uq_rental_booking_booking"),
        enum_check("charge_state", ChargeState),
        enum_check("booked_via", BookedVia),
        Index(
            "ix_rental_booking_unbilled", "tenant_id", "location_id", "starts_at",
            postgresql_where=text("charge_state = 'unbilled' AND cancelled_at IS NULL"),
        ),
        Index("ix_rental_booking_type", "tenant_id", "rental_type_id", "starts_at"),
        Index("ix_rental_booking_location", "tenant_id", "location_id", "starts_at", "id"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    booking_id: Mapped[UUID]
    rental_type_id: Mapped[UUID]
    charge_state: Mapped[str] = enum_column(server_default=text("'unbilled'"))
    booked_via: Mapped[str] = enum_column()
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    cancelled_at: Mapped[datetime | None]
    is_on_public_schedule: Mapped[bool] = mapped_column(server_default=text("false"))


class RentalParty(TenantOwned, Timestamps, Base):
    __tablename__ = "rental_party"
    __table_args__ = tenant_args(
        *tfk("rental_booking_id", "rental_booking", ondelete="CASCADE", index=False),
        *tfk("client_id", "client"),
        UniqueConstraint("tenant_id", "rental_booking_id", "client_id", name="uq_rental_party"),
    )

    rental_booking_id: Mapped[UUID]
    client_id: Mapped[UUID]
    is_charged: Mapped[bool] = mapped_column(server_default=text("false"))


class RentalBookingCharge(TenantOwned, Timestamps, Base):
    """One priced line handed to billing, covering one or many occurrences; `charge_id` is never null."""

    __tablename__ = "rental_booking_charge"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("client_id", "client", index=False),
        *tfk("rental_rate_id", "rental_rate"),
        *tfk("charge_id", "charge", index=False),
        UniqueConstraint("tenant_id", "charge_id", name="uq_rental_booking_charge_charge"),
        enum_check("basis", Basis),
        enum_check("invoice_routing", Routing),
        enum_check("routing_period", RoutingPeriod),
        CheckConstraint(
            "unit_amount_minor >= 0 AND discount_minor >= 0 AND amount_minor >= 0", name="amounts"
        ),
        CheckConstraint("(invoice_routing = 'date_based') = (routing_period IS NOT NULL)", name="period"),
        Index("ix_rental_booking_charge_client", "tenant_id", "client_id", "id"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    client_id: Mapped[UUID]
    rental_rate_id: Mapped[UUID | None]
    description: Mapped[str]
    basis: Mapped[str] = enum_column()
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), info={"audit": "value"})
    unit_amount_minor: Mapped[int] = mapped_column(info={"audit": "value"})
    discount_minor: Mapped[int] = mapped_column(server_default=text("0"), info={"audit": "value"})
    amount_minor: Mapped[int] = mapped_column(info={"audit": "value"})
    revenue_on: Mapped[date]
    invoice_routing: Mapped[str] = enum_column()
    routing_period: Mapped[str | None] = enum_column()
    charge_id: Mapped[UUID]
    reversed_at: Mapped[datetime | None]


class RentalBookingChargeItem(TenantOwned, Timestamps, Base):
    """Which occurrence (and resource) a line covers, and its largest-remainder share of the line."""

    __tablename__ = "rental_booking_charge_item"
    __table_args__ = tenant_args(
        *tfk("rental_booking_charge_id", "rental_booking_charge", ondelete="CASCADE", index=False),
        *tfk("rental_booking_id", "rental_booking", index=False),
        *tfk("resource_id", "resource"),
        Index(
            "uq_rental_booking_charge_item", "tenant_id", "rental_booking_charge_id", "rental_booking_id",
            "resource_id", unique=True, postgresql_nulls_not_distinct=True,
        ),
        Index("ix_rental_booking_charge_item_booking", "tenant_id", "rental_booking_id"),
        CheckConstraint("amount_minor >= 0", name="amount"),
    )  # fmt: skip

    rental_booking_charge_id: Mapped[UUID]
    rental_booking_id: Mapped[UUID]
    resource_id: Mapped[UUID | None]
    amount_minor: Mapped[int] = mapped_column(info={"audit": "value"})
    reversed_at: Mapped[datetime | None]


class RentalPlan(TenantOwned, Timestamps, Base):
    """A prepaid rental balance offered for sale (RNT-09)."""

    __tablename__ = "rental_plan"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("rental_type_id", "rental_type"),
        *tfk("revenue_category_id", "revenue_category"),
        enum_check("model", PlanModel),
        enum_check("start_mode", StartMode),
        enum_check("default_invoice_routing", Routing),
        enum_check("status", PlanStatus),
        Index(
            "uq_rental_plan_name", "tenant_id", "location_id", "name", unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint("is_unlimited = (quantity IS NULL) AND (quantity IS NULL OR quantity > 0)", name="quantity"),
        CheckConstraint("is_flat_rate OR NOT is_unlimited", name="unit_price"),
        CheckConstraint("price_minor >= 0 AND (member_price_minor IS NULL OR member_price_minor >= 0)", name="price"),
        CheckConstraint("(start_mode = 'fixed_date') = (fixed_starts_on IS NOT NULL)", name="start"),
        CheckConstraint("num_nonnulls(validity_days, fixed_expires_on) <= 1", name="expiry"),
        CheckConstraint("validity_days IS NULL OR validity_days > 0", name="validity"),
        CheckConstraint("NOT is_auto_renew OR validity_days IS NOT NULL", name="renew"),
        CheckConstraint("default_invoice_routing NOT IN ('date_based', 'existing_open')", name="routing"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    rental_type_id: Mapped[UUID]
    model: Mapped[str] = enum_column()
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), info={"audit": "value"})
    is_unlimited: Mapped[bool] = mapped_column(server_default=text("false"))
    price_minor: Mapped[int] = mapped_column(info={"audit": "value"})
    member_price_minor: Mapped[int | None] = mapped_column(info={"audit": "value"})
    is_flat_rate: Mapped[bool] = mapped_column(server_default=text("true"))
    revenue_category_id: Mapped[UUID]
    internal_description: Mapped[str | None]
    client_description: Mapped[str | None]
    is_members_only: Mapped[bool] = mapped_column(server_default=text("false"))
    is_sold_online: Mapped[bool] = mapped_column(server_default=text("false"))
    start_mode: Mapped[str] = enum_column(server_default=text("'sale_date'"))
    fixed_starts_on: Mapped[date | None]
    validity_days: Mapped[int | None]
    fixed_expires_on: Mapped[date | None]
    is_auto_renew: Mapped[bool] = mapped_column(server_default=text("false"))
    is_autopay_default: Mapped[bool] = mapped_column(server_default=text("false"))
    default_invoice_routing: Mapped[str] = enum_column(server_default=text("'new_single'"))
    is_shareable: Mapped[bool] = mapped_column(server_default=text("false"))
    status: Mapped[str] = enum_column(server_default=text("'active'"))


class RentalTypeRentalPlan(TenantOwned, Timestamps, Base):
    """Optional allow-list: no rows for a type = plans whose home type it is; rows = exactly those plans."""

    __tablename__ = "rental_type_rental_plan"
    __table_args__ = tenant_args(
        *tfk("rental_type_id", "rental_type", ondelete="CASCADE", index=False),
        *tfk("rental_plan_id", "rental_plan", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "rental_type_id", "rental_plan_id", name="uq_rental_type_rental_plan"),
    )

    rental_type_id: Mapped[UUID]
    rental_plan_id: Mapped[UUID]


class RentalPlanPurchase(TenantOwned, Timestamps, Base):
    __tablename__ = "rental_plan_purchase"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("rental_plan_id", "rental_plan"),
        *tfk("client_id", "client", index=False),
        *tfk("charge_id", "charge"),
        *tfk("sold_by_staff_user_id", "staff_user"),
        *tfk("renewed_from_purchase_id", "rental_plan_purchase", index=False),
        enum_check("status", PurchaseStatus),
        enum_check("model", PlanModel),
        enum_check("sold_via", SoldVia),
        enum_check("cancel_mode", CancelMode),
        CheckConstraint("balance IS NULL OR balance >= 0", name="balance"),
        CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="cancel"),
        CheckConstraint("price_minor >= 0", name="price"),
        Index(
            "uq_rental_plan_purchase_successor", "tenant_id", "renewed_from_purchase_id", unique=True,
            postgresql_where=text("renewed_from_purchase_id IS NOT NULL"),
        ),
        Index("ix_rental_plan_purchase_client", "tenant_id", "client_id", "status"),
        Index(
            "ix_rental_plan_purchase_due", "tenant_id", "location_id", "expires_on",
            postgresql_where=text("status = 'active'"),
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    rental_plan_id: Mapped[UUID]
    client_id: Mapped[UUID]
    status: Mapped[str] = enum_column()
    model: Mapped[str] = enum_column()
    quantity_total: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), info={"audit": "value"})
    balance: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), info={"audit": "value"})
    price_minor: Mapped[int] = mapped_column(info={"audit": "value"})
    charge_id: Mapped[UUID | None]
    sold_via: Mapped[str] = enum_column()
    sold_by_staff_user_id: Mapped[UUID | None]
    starts_on: Mapped[date]
    expires_on: Mapped[date | None]
    is_auto_renew: Mapped[bool] = mapped_column(server_default=text("false"))
    renewed_from_purchase_id: Mapped[UUID | None]
    cancelled_at: Mapped[datetime | None]
    cancel_mode: Mapped[str | None] = enum_column()


class RentalPlanLedgerEntry(TenantOwned, Base):
    """Append-only balance history (SELECT, INSERT only; no updated_at)."""

    __tablename__ = "rental_plan_ledger_entry"
    __table_args__ = tenant_args(
        *tfk("rental_plan_purchase_id", "rental_plan_purchase", index=False),
        *tfk("rental_booking_id", "rental_booking", index=False),
        *tfk("used_by_client_id", "client"),
        enum_check("entry_type", EntryType),
        Index(
            "uq_rental_plan_ledger_entry_booking", "tenant_id", "rental_booking_id", "entry_type", unique=True,
            postgresql_where=text("rental_booking_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(entry_type IN ('grant', 'credit') AND quantity >= 0) OR (entry_type IN ('debit', 'expire') "
            "AND quantity <= 0) OR entry_type = 'adjust'",
            name="sign",
        ),
        Index("ix_rental_plan_ledger_entry_purchase", "tenant_id", "rental_plan_purchase_id", "id"),
    )  # fmt: skip

    rental_plan_purchase_id: Mapped[UUID]
    entry_type: Mapped[str] = enum_column()
    quantity: Mapped[Decimal] = mapped_column(Numeric(8, 2), info={"audit": "value"})
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), info={"audit": "value"})
    rental_booking_id: Mapped[UUID | None]
    used_by_client_id: Mapped[UUID | None]
    note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), sort_order=98)
