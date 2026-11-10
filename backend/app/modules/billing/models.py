"""billing tables (docs/architecture/data-model-money.md section 1, ADR 0003). Kernel slice: what it takes to
post a taxed charge, invoice it, take and allocate a payment, refund and reverse. Build module 8 adds the
remaining tables and the columns that point at them (coupon_id, payment_method_id); nothing here is renamed."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CHAR, BigInteger, CheckConstraint, Index, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.audit import ActorType
from app.core.db import Base, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk


def _values(*values: str) -> type[StrEnum]:
    return StrEnum("Vocabulary", {value.upper(): value for value in values})


ChargeKind = _values("standard", "adjustment", "reversal", "surcharge")
ChargeStatus = _values("active", "reversed", "voided")
InvoiceOrigin = _values("staff", "portal", "pos", "kiosk", "api", "system")
InvoiceStatus = _values("open", "payment_pending", "partially_paid", "paid", "voided")
DunningState = _values("none", "retrying", "awaiting_method", "exhausted")
TenderKind = _values("card", "bank_debit", "cash", "cheque", "bank_transfer", "gift_card", "external", "other")
PaymentStatus = _values(
    "initiated", "requires_action", "processing", "succeeded", "failed", "unknown", "cancelled", "disputed",
    "charged_back", "voided",
)  # fmt: skip
PaymentOrigin = _values("staff", "portal", "pos", "kiosk", "autopay", "api")
AllocationStatus = _values("provisional", "applied", "released")
ReleaseReason = _values(
    "unapplied", "charge_reversed", "charge_adjusted", "payment_voided", "payment_failed", "dispute_opened",
    "invoice_voided",
)  # fmt: skip
RefundMethod = _values("original", "external")
RefundStatus = _values("pending", "succeeded", "failed", "cancelled")
LedgerKind = _values(
    "charge_posted", "payment_settled", "allocation_applied", "allocation_released", "refund_succeeded",
    "refund_returned", "payment_voided", "dispute_opened", "dispute_won", "dispute_lost", "correction",
)  # fmt: skip
LedgerSource = _values("charge", "payment", "payment_allocation", "refund", "dispute")
LedgerAccount = _values("receivable", "revenue", "tax_payable", "funds_received", "client_credit", "disputed_funds")
Provider = _values("stripe", "fake")
ProviderAccountStatus = _values("pending", "restricted", "active", "disabled")


def _money(**kwargs) -> Mapped[int]:
    return mapped_column(BigInteger, **kwargs)


def _false() -> Mapped[bool]:
    return mapped_column(server_default=text("false"))


# --- 1.1 catalogue and configuration ---------------------------------------------------------------------


class RevenueCategory(TenantOwned, Timestamps, Base):
    __tablename__ = "revenue_category"
    __table_args__ = tenant_args(
        *tfk("parent_id", "revenue_category"),
        UniqueConstraint("tenant_id", "code", name="uq_revenue_category_code"),
        Index(
            "uq_revenue_category_system_key", "tenant_id", "system_key", unique=True,
            postgresql_where=text("system_key IS NOT NULL"),
        ),
        CheckConstraint("parent_id <> id", name="not_self"),
    )  # fmt: skip

    code: Mapped[str] = mapped_column(CITEXT)
    label: Mapped[str]
    remarks: Mapped[str | None]
    parent_id: Mapped[UUID | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    system_key: Mapped[str | None] = mapped_column(info={"audit": "value"})


class Tax(TenantOwned, Timestamps, Base):
    __tablename__ = "tax"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "code", name="uq_tax_code"),
        CheckConstraint("is_active OR deactivated_on IS NOT NULL", name="deactivated"),
    )

    code: Mapped[str] = mapped_column(CITEXT)
    label: Mapped[str]
    remarks: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    deactivated_on: Mapped[date | None]


class TaxRate(TenantOwned, Timestamps, Base):
    __tablename__ = "tax_rate"
    __table_args__ = tenant_args(
        *tfk("tax_id", "tax", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "tax_id", "effective_from_on", name="uq_tax_rate_tax_id_effective_from_on"),
        CheckConstraint("rate >= 0 AND rate < 1", name="rate"),
    )

    tax_id: Mapped[UUID]
    rate: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    effective_from_on: Mapped[date]


class RevenueCategoryTax(TenantOwned, Timestamps, Base):
    __tablename__ = "revenue_category_tax"
    __table_args__ = tenant_args(
        *tfk("revenue_category_id", "revenue_category", ondelete="CASCADE", index=False),
        *tfk("tax_id", "tax"),
        UniqueConstraint("tenant_id", "revenue_category_id", "tax_id", name="uq_revenue_category_tax"),
    )

    revenue_category_id: Mapped[UUID]
    tax_id: Mapped[UUID]


class TenderType(TenantOwned, Timestamps, Base):
    """How money can be received (PAY-02). Seeded per tenant on first use; account credit is not a tender."""

    __tablename__ = "tender_type"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "label", name="uq_tender_type_label"),
        Index(
            "uq_tender_type_kind_single", "tenant_id", "kind", unique=True,
            postgresql_where=text("kind NOT IN ('external', 'other')"),
        ),
        enum_check("kind", TenderKind),
        CheckConstraint("is_processed = (kind IN ('card', 'bank_debit'))", name="processed"),
    )  # fmt: skip

    kind: Mapped[str] = enum_column()
    label: Mapped[str]
    is_processed: Mapped[bool]
    is_optional: Mapped[bool] = mapped_column(server_default=text("true"))
    is_enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class ProviderAccount(TenantOwned, Timestamps, Base):
    """The tenant's account at a payment provider (PAY-11). One per tenant in v1."""

    __tablename__ = "provider_account"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        UniqueConstraint("tenant_id", "provider", "provider_account_ref", name="uq_provider_account_ref"),
        Index(
            "uq_provider_account_scope", "tenant_id", "location_id", unique=True,
            postgresql_where=text("status <> 'disabled'"), postgresql_nulls_not_distinct=True,
        ),
        enum_check("provider", Provider),
        enum_check("status", ProviderAccountStatus),
    )  # fmt: skip

    location_id: Mapped[UUID | None]
    provider: Mapped[str] = enum_column()
    provider_account_ref: Mapped[str] = mapped_column(info={"audit": "value"})
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    has_card: Mapped[bool] = _false()
    has_bank_debit: Mapped[bool] = _false()
    has_wallets: Mapped[bool] = _false()
    is_payouts_enabled: Mapped[bool] = _false()
    requirements_due: Mapped[Any | None] = mapped_column(JSONB)
    connected_at: Mapped[datetime | None]
    disabled_at: Mapped[datetime | None]


# --- 1.2 receivables ---------------------------------------------------------------------------------------


class Invoice(TenantOwned, Timestamps, Base):
    """Grouping and collection document for one payer. Totals are projections of its charges."""

    __tablename__ = "invoice"
    __table_args__ = tenant_args(
        *tfk("bill_to_client_id", "client", index=False),
        *tfk("location_id", "location"),
        *tfk("created_by_staff_user_id", "staff_user"),
        *tfk("voided_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "number", name="uq_invoice_number"),
        enum_check("origin", InvoiceOrigin),
        enum_check("status", InvoiceStatus),
        enum_check("dunning_state", DunningState),
        CheckConstraint("bill_to_client_id IS NOT NULL OR origin = 'pos'", name="bill_to"),
        CheckConstraint("due_on >= invoice_on", name="due"),
        Index(
            "ix_invoice_payable", "tenant_id", "bill_to_client_id", "due_on", "id",
            postgresql_where=text("status IN ('open', 'payment_pending', 'partially_paid')"),
        ),
        Index("ix_invoice_bill_to_client_id", "tenant_id", "bill_to_client_id", text("invoice_on DESC"), text("id DESC")),
    )  # fmt: skip

    number: Mapped[int] = _money()
    bill_to_client_id: Mapped[UUID | None]
    location_id: Mapped[UUID]
    origin: Mapped[str] = enum_column()
    invoice_on: Mapped[date]
    due_on: Mapped[date]
    is_autopay: Mapped[bool] = _false()
    status: Mapped[str] = enum_column(server_default=text("'open'"))
    total_minor: Mapped[int] = _money(server_default=text("0"))
    balance_minor: Mapped[int] = _money(server_default=text("0"))
    past_due_since_on: Mapped[date | None]
    dunning_state: Mapped[str] = enum_column(server_default=text("'none'"))
    attempt_count: Mapped[int] = mapped_column(server_default=text("0"))
    next_attempt_on: Mapped[date | None]
    comments: Mapped[str | None]
    organization_name: Mapped[str | None]
    created_by_staff_user_id: Mapped[UUID | None]
    voided_at: Mapped[datetime | None]
    voided_by_staff_user_id: Mapped[UUID | None]
    void_reason: Mapped[str | None]
    version: Mapped[int] = mapped_column(server_default=text("1"))


class Charge(TenantOwned, Timestamps, Base):
    """Atomic receivable. Money columns never change once inserted (ADR 0003 section 3)."""

    __tablename__ = "charge"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("location_id", "location"),
        *tfk("invoice_id", "invoice"),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("reverses_charge_id", "charge", index=False),
        *tfk("adjusts_charge_id", "charge"),
        *tfk("voided_by_staff_user_id", "staff_user"),
        *tfk("created_by_staff_user_id", "staff_user"),
        enum_check("kind", ChargeKind),
        enum_check("status", ChargeStatus),
        Index(
            "uq_charge_reverses_charge_id", "tenant_id", "reverses_charge_id", unique=True,
            postgresql_where=text("reverses_charge_id IS NOT NULL"),
        ),
        Index(
            "uq_charge_origin", "tenant_id", "source_context", "source_type", "source_id", "source_line_no",
            unique=True, postgresql_where=text("kind = 'standard'"),
        ),
        CheckConstraint("client_id IS NOT NULL OR source_context = 'pos'", name="client"),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint("kind IN ('adjustment', 'reversal') OR net_minor >= 0", name="sign"),
        CheckConstraint(
            "(kind = 'reversal') = (reverses_charge_id IS NOT NULL) AND "
            "(kind = 'adjustment') = (adjusts_charge_id IS NOT NULL)",
            name="link",
        ),
        CheckConstraint("total_minor = net_minor + tax_minor", name="total"),
        CheckConstraint(
            "applied_minor BETWEEN LEAST(total_minor, 0) AND GREATEST(total_minor, 0)", name="applied"
        ),
        CheckConstraint("service_ends_on IS NULL OR service_ends_on >= service_starts_on", name="service_period"),
        CheckConstraint("(kind <> 'reversal' AND status <> 'voided') OR reason IS NOT NULL", name="reason"),
        Index("ix_charge_client_id", "tenant_id", "client_id", text("bill_on DESC"), text("id DESC")),
        Index(
            "ix_charge_uninvoiced", "tenant_id", "location_id", "id",
            postgresql_where=text("invoice_id IS NULL AND status = 'active'"),
        ),
        Index(
            "ix_charge_uninvoiced_creator", "tenant_id", "created_by_staff_user_id", "id",
            postgresql_where=text("invoice_id IS NULL AND status = 'active'"),
        ),
        Index("ix_charge_source", "tenant_id", "source_context", "source_type", "source_id"),
        Index("ix_charge_revenue_on", "tenant_id", "revenue_on", "revenue_category_id"),
        Index(
            "ix_charge_open", "tenant_id", "client_id", "bill_on", "id",
            postgresql_where=text("status = 'active' AND applied_minor < total_minor"),
        ),
    )  # fmt: skip

    client_id: Mapped[UUID | None]
    location_id: Mapped[UUID]
    invoice_id: Mapped[UUID | None]
    kind: Mapped[str] = enum_column(server_default=text("'standard'"))
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    source_context: Mapped[str] = mapped_column(info={"audit": "value"})
    source_type: Mapped[str] = mapped_column(info={"audit": "value"})
    source_id: Mapped[UUID]
    source_line_no: Mapped[int] = mapped_column(server_default=text("0"))
    description: Mapped[str]
    additional_description: Mapped[str | None]
    internal_remarks: Mapped[str | None]
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), server_default=text("1"))
    unit_price_minor: Mapped[int] = _money()
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount_minor: Mapped[int] = _money(server_default=text("0"))
    net_minor: Mapped[int] = _money()
    tax_minor: Mapped[int] = _money(server_default=text("0"))
    total_minor: Mapped[int] = _money()
    applied_minor: Mapped[int] = _money(server_default=text("0"))
    bill_on: Mapped[date]
    revenue_on: Mapped[date]
    service_starts_on: Mapped[date | None]
    service_ends_on: Mapped[date | None]
    revenue_category_id: Mapped[UUID]
    reverses_charge_id: Mapped[UUID | None]
    adjusts_charge_id: Mapped[UUID | None]
    reason: Mapped[str | None]
    reversed_at: Mapped[datetime | None]
    voided_at: Mapped[datetime | None]
    voided_by_staff_user_id: Mapped[UUID | None]
    created_by_staff_user_id: Mapped[UUID | None]


class ChargeTax(TenantOwned, Timestamps, Base):
    """Tax snapshot per charge per tax. Later rate or mapping changes never alter a posted charge."""

    __tablename__ = "charge_tax"
    __table_args__ = tenant_args(
        *tfk("charge_id", "charge", ondelete="CASCADE", index=False),
        *tfk("tax_id", "tax"),
        UniqueConstraint("tenant_id", "charge_id", "tax_id", name="uq_charge_tax"),
    )

    charge_id: Mapped[UUID]
    tax_id: Mapped[UUID]
    rate: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    amount_minor: Mapped[int] = _money()
    is_excluded: Mapped[bool] = _false()


# --- 1.3 money in and out ----------------------------------------------------------------------------------


class Payment(TenantOwned, Timestamps, Base):
    """Money received from one payer in one tender. Its unallocated remainder is the client's account credit."""

    __tablename__ = "payment"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("location_id", "location", index=False),
        *tfk("tender_type_id", "tender_type"),
        *tfk("provider_account_id", "provider_account"),
        *tfk("taken_by_staff_user_id", "staff_user"),
        *tfk("voided_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "receipt_number", name="uq_payment_receipt_number"),
        Index(
            "uq_payment_provider_ref", "tenant_id", "provider_account_id", "provider_payment_ref", unique=True,
            postgresql_where=text("provider_payment_ref IS NOT NULL"),
        ),
        enum_check("tender_kind", TenderKind),
        enum_check("status", PaymentStatus),
        enum_check("origin", PaymentOrigin),
        CheckConstraint("amount_minor > 0", name="amount"),
        CheckConstraint("client_id IS NOT NULL OR origin = 'pos'", name="client"),
        CheckConstraint(
            "(provider_account_id IS NOT NULL) = (tender_kind IN ('card', 'bank_debit'))", name="provider"
        ),
        CheckConstraint(
            "unapplied_minor >= 0 AND refunded_minor BETWEEN 0 AND amount_minor", name="remainder"
        ),
        CheckConstraint(
            "status <> 'voided' OR (void_reason IS NOT NULL AND provider_account_id IS NULL)", name="void"
        ),
        Index("ix_payment_client_id", "tenant_id", "client_id", text("received_at DESC"), text("id DESC")),
        Index(
            "ix_payment_credit", "tenant_id", "client_id", "received_at",
            postgresql_where=text("status = 'succeeded' AND unapplied_minor > 0"),
        ),
        Index(
            "ix_payment_unsettled", "tenant_id", "status", "received_at",
            postgresql_where=text("status IN ('initiated', 'unknown', 'requires_action', 'processing')"),
        ),
        Index("ix_payment_location_id", "tenant_id", "location_id", "received_at"),
    )  # fmt: skip

    receipt_number: Mapped[int] = _money()
    client_id: Mapped[UUID | None]
    location_id: Mapped[UUID]
    tender_type_id: Mapped[UUID]
    tender_kind: Mapped[str] = enum_column()
    amount_minor: Mapped[int] = _money()
    currency: Mapped[str] = mapped_column(CHAR(3), info={"audit": "value"})
    status: Mapped[str] = enum_column(server_default=text("'initiated'"))
    origin: Mapped[str] = enum_column()
    provider_account_id: Mapped[UUID | None]
    provider_payment_ref: Mapped[str | None] = mapped_column(info={"audit": "value"})
    card_brand: Mapped[str | None]
    card_last4: Mapped[str | None]
    card_funding: Mapped[str | None]
    wallet: Mapped[str | None]
    external_reference: Mapped[str | None]
    memo: Mapped[str | None]
    received_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    settled_at: Mapped[datetime | None]
    failure_category: Mapped[str | None] = mapped_column(info={"audit": "value"})
    failure_message: Mapped[str | None]
    unapplied_minor: Mapped[int] = _money(server_default=text("0"))
    refunded_minor: Mapped[int] = _money(server_default=text("0"))
    taken_by_staff_user_id: Mapped[UUID | None]
    voided_at: Mapped[datetime | None]
    voided_by_staff_user_id: Mapped[UUID | None]
    void_reason: Mapped[str | None]


class PaymentAllocation(TenantOwned, Timestamps, Base):
    """Part of a payment applied to one charge. A released row is never re-applied: re-applying inserts."""

    __tablename__ = "payment_allocation"
    __table_args__ = tenant_args(
        *tfk("payment_id", "payment"),
        *tfk("charge_id", "charge"),
        *tfk("created_by_staff_user_id", "staff_user"),
        enum_check("status", AllocationStatus),
        enum_check("release_reason", ReleaseReason),
        CheckConstraint("amount_minor > 0", name="amount"),
        CheckConstraint(
            "(status = 'released') = (released_at IS NOT NULL AND release_reason IS NOT NULL)", name="release"
        ),
        Index(
            "ix_payment_allocation_live", "tenant_id", "charge_id", postgresql_where=text("status <> 'released'")
        ),
        Index(
            "ix_payment_allocation_live_payment", "tenant_id", "payment_id",
            postgresql_where=text("status <> 'released'"),
        ),
    )  # fmt: skip

    payment_id: Mapped[UUID]
    charge_id: Mapped[UUID]
    amount_minor: Mapped[int] = _money()
    status: Mapped[str] = enum_column()
    applied_at: Mapped[datetime | None]
    released_at: Mapped[datetime | None]
    release_reason: Mapped[str | None] = enum_column()
    created_by_staff_user_id: Mapped[UUID | None]


class Refund(TenantOwned, Timestamps, Base):
    """Money returned against one payment: its unapplied remainder (PAY-05)."""

    __tablename__ = "refund"
    __table_args__ = tenant_args(
        *tfk("payment_id", "payment"),
        *tfk("client_id", "client"),
        *tfk("location_id", "location"),
        *tfk("issued_by_staff_user_id", "staff_user"),
        Index(
            "uq_refund_provider_ref", "tenant_id", "provider_refund_ref", unique=True,
            postgresql_where=text("provider_refund_ref IS NOT NULL"),
        ),
        enum_check("method", RefundMethod),
        enum_check("status", RefundStatus),
        CheckConstraint("amount_minor > 0", name="amount"),
        Index(
            "ix_refund_batch", "tenant_id", "refund_batch_id", postgresql_where=text("refund_batch_id IS NOT NULL")
        ),
        Index("ix_refund_pending", "tenant_id", "created_at", postgresql_where=text("status = 'pending'")),
    )  # fmt: skip

    payment_id: Mapped[UUID]
    client_id: Mapped[UUID | None]
    location_id: Mapped[UUID]
    amount_minor: Mapped[int] = _money()
    currency: Mapped[str] = mapped_column(CHAR(3), info={"audit": "value"})
    method: Mapped[str] = enum_column()
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    provider_refund_ref: Mapped[str | None] = mapped_column(info={"audit": "value"})
    refund_on: Mapped[date]
    reason: Mapped[str]
    comments: Mapped[str | None]
    refund_batch_id: Mapped[UUID | None]
    failure_message: Mapped[str | None]
    issued_by_staff_user_id: Mapped[UUID | None]


class LedgerTransaction(TenantOwned, Base):
    """Header of one balanced posting. Append-only; the unique key is the idempotency guard."""

    __tablename__ = "ledger_transaction"
    __table_args__ = tenant_args(
        *tfk("reverses_transaction_id", "ledger_transaction"),
        UniqueConstraint("tenant_id", "kind", "source_type", "source_id", name="uq_ledger_transaction_source"),
        enum_check("kind", LedgerKind),
        enum_check("source_type", LedgerSource),
        enum_check("actor_type", ActorType),
    )

    kind: Mapped[str] = enum_column()
    source_type: Mapped[str] = enum_column()
    source_id: Mapped[UUID]
    effective_on: Mapped[date]
    posted_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    reverses_transaction_id: Mapped[UUID | None]
    actor_type: Mapped[str] = enum_column()
    actor_id: Mapped[UUID | None]


class LedgerEntry(TenantOwned, Base):
    """One debit or credit line. Append-only: never updated, never deleted (the grants enforce it)."""

    __tablename__ = "ledger_entry"
    __table_args__ = tenant_args(
        *tfk("ledger_transaction_id", "ledger_transaction"),
        *tfk("location_id", "location", index=False),
        *tfk("client_id", "client", index=False),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("tax_id", "tax"),
        *tfk("charge_id", "charge"),
        *tfk("payment_id", "payment"),
        enum_check("account", LedgerAccount),
        CheckConstraint(
            "debit_minor >= 0 AND credit_minor >= 0 AND (debit_minor = 0) <> (credit_minor = 0)", name="one_side"
        ),
        CheckConstraint(
            "(account <> 'revenue' OR revenue_category_id IS NOT NULL) AND "
            "(account <> 'tax_payable' OR tax_id IS NOT NULL)",
            name="dimension",
        ),
        Index("ix_ledger_entry_account", "tenant_id", "account", "effective_on"),
        Index("ix_ledger_entry_client_id", "tenant_id", "client_id", "account"),
        Index("ix_ledger_entry_location_id", "tenant_id", "location_id", "effective_on"),
    )

    ledger_transaction_id: Mapped[UUID]
    account: Mapped[str] = enum_column()
    debit_minor: Mapped[int] = _money(server_default=text("0"))
    credit_minor: Mapped[int] = _money(server_default=text("0"))
    currency: Mapped[str] = mapped_column(CHAR(3))
    effective_on: Mapped[date]
    location_id: Mapped[UUID]
    client_id: Mapped[UUID | None]
    revenue_category_id: Mapped[UUID | None]
    tax_id: Mapped[UUID | None]
    charge_id: Mapped[UUID | None]
    payment_id: Mapped[UUID | None]
