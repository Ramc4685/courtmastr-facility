"""billing tables (docs/architecture/data-model-money.md section 1, ADR 0003). Kernel slice: what it takes to
post a taxed charge, invoice it, take and allocate a payment, refund and reverse. Build module 8 adds the
remaining tables and the columns that point at them (coupon_id, payment_method_id); nothing here is renamed."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
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
DisputeStatus = _values("open", "won", "lost")
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
        Index(
            "ix_invoice_autopay_due", "tenant_id", "location_id", "due_on",
            postgresql_where=text("is_autopay AND balance_minor > 0 AND status <> 'voided'"),
        ),
        Index(
            "ix_invoice_past_due", "tenant_id", "location_id", "past_due_since_on",
            postgresql_where=text("past_due_since_on IS NOT NULL"),
        ),
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
        *tfk("coupon_id", "coupon"),
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
    coupon_id: Mapped[UUID | None]
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
        *tfk("payment_method_id", "payment_method"),
        UniqueConstraint("tenant_id", "receipt_number", name="uq_payment_receipt_number"),
        Index(
            "uq_payment_idempotency_key", "tenant_id", "idempotency_key", unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
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
    payment_method_id: Mapped[UUID | None]
    # Not in the data model: the caller's key, so the row inserted before the provider call (ADR 0003
    # section 8) can be found again by a retry or the reconciliation sweep.
    idempotency_key: Mapped[str | None] = mapped_column(info={"audit": "never"})
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


class Dispute(TenantOwned, Timestamps, Base):
    """A chargeback or a bank-debit return after settlement (PAY-17, ADR 0003 section 9). Mirrors the processor:
    created and moved only by webhooks.apply_event through service.sync_dispute."""

    __tablename__ = "dispute"
    __table_args__ = tenant_args(
        *tfk("payment_id", "payment"),
        UniqueConstraint("tenant_id", "provider_dispute_ref", name="uq_dispute_provider_ref"),
        enum_check("status", DisputeStatus),
        CheckConstraint("amount_minor > 0", name="amount"),
    )  # fmt: skip

    payment_id: Mapped[UUID]
    provider_dispute_ref: Mapped[str] = mapped_column(info={"audit": "value"})
    amount_minor: Mapped[int] = _money()
    currency: Mapped[str] = mapped_column(CHAR(3), info={"audit": "value"})
    reason_code: Mapped[str | None] = mapped_column(info={"audit": "value"})
    status: Mapped[str] = enum_column(server_default=text("'open'"))
    opened_at: Mapped[datetime]
    evidence_due_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]


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


# --- build module 8: settings, coupons, schedules, stored methods, autopay, notices, delivery ---------------

MethodKind = _values("card", "bank_account")
MethodStatus = _values("pending_verification", "active", "suspended", "removed")
AutopayRunStatus = _values("running", "completed", "completed_with_errors")
AutopayAttemptStatus = _values("pending", "succeeded", "processing", "failed", "skipped")
NoticeKind = _values(
    "due_reminder", "past_due_reminder", "final_notice", "payment_declined", "authentication_required",
    "method_expiring", "staff_decline_alert", "staff_decline_digest",
)  # fmt: skip
NoticeSubject = _values("invoice", "payment", "payment_method", "location")
DocumentKind = _values("invoice", "receipt", "statement")
DeliveryChannel = _values("email", "print", "download")
DeliveryStatus = _values("queued", "sent", "failed")


def _ints(default: str) -> Mapped[list[int]]:
    return mapped_column(ARRAY(Integer), server_default=text(f"'{default}'"))


class BillingSettings(TenantOwned, Timestamps, Base):
    """Billing preferences (BIL-16): the tenant row (location_id null) plus optional location overrides."""

    __tablename__ = "billing_settings"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        Index(
            "uq_billing_settings_location", "tenant_id", "location_id", unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("save_card_default IN ('never', 'ask', 'always')", name="save_card_default"),
        CheckConstraint(
            "card_expiry_notice_scope IN ('all_methods', 'autopay_methods')", name="card_expiry_notice_scope"
        ),
        CheckConstraint(
            "decline_notice_scope IN ('off', 'all_payments', 'autopay_payments')", name="decline_notice_scope"
        ),
        CheckConstraint("decline_alert_mode IN ('per_event', 'daily_digest')", name="decline_alert_mode"),
        CheckConstraint("program_description_source IN ('group', 'subgroup')", name="program_description_source"),
        CheckConstraint("package_invoice_sessions IN ('all', 'attended', 'none')", name="package_invoice_sessions"),
    )  # fmt: skip

    location_id: Mapped[UUID | None]
    is_membership_autopay_default_staff: Mapped[bool] = _false()
    is_membership_autopay_default_portal: Mapped[bool] = mapped_column(server_default=text("true"))
    save_card_default: Mapped[str] = enum_column(server_default=text("'ask'"))
    card_expiry_notice_days: Mapped[list[int]] = _ints("{60,30}")
    card_expiry_notice_scope: Mapped[str] = enum_column(server_default=text("'autopay_methods'"))
    decline_notice_scope: Mapped[str] = enum_column(server_default=text("'all_payments'"))
    decline_alert_email: Mapped[str | None] = mapped_column(CITEXT)
    decline_alert_mode: Mapped[str] = enum_column(server_default=text("'per_event'"))
    autopay_retry_offset_days: Mapped[list[int]] = _ints("{3,5,7}")
    due_reminder_offset_days: Mapped[list[int]] = _ints("{-3}")
    is_portal_blocked_when_past_due: Mapped[bool] = _false()
    invoice_email_subject: Mapped[str] = mapped_column(server_default=text("'Invoice {invoice_number}'"))
    invoice_footer: Mapped[str | None]
    receipt_footer: Mapped[str | None]
    statement_email_subject: Mapped[str | None]
    statement_email_body: Mapped[str | None]
    statement_footer: Mapped[str | None]
    is_program_description_on_invoice: Mapped[bool] = _false()
    program_description_source: Mapped[str] = enum_column(server_default=text("'group'"))
    bill_to_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{name,address}'"))
    package_invoice_sessions: Mapped[str] = enum_column(server_default=text("'all'"))


class Coupon(TenantOwned, Timestamps, Base):
    __tablename__ = "coupon"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "code", name="uq_coupon_code"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="window"),
        CheckConstraint(
            "num_nonnulls(discount_pct, discount_minor) = 1 AND COALESCE(discount_pct, 1) > 0 "
            "AND COALESCE(discount_pct, 1) <= 100 AND COALESCE(discount_minor, 1) > 0",
            name="discount",
        ),
    )

    name: Mapped[str]
    code: Mapped[str] = mapped_column(CITEXT, info={"audit": "value"})
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime | None]
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount_minor: Mapped[int | None] = mapped_column(BigInteger)
    limit_per_client: Mapped[int | None]
    is_portal_enabled: Mapped[bool] = _false()
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class CouponRedemption(TenantOwned, Timestamps, Base):
    __tablename__ = "coupon_redemption"
    __table_args__ = tenant_args(
        *tfk("coupon_id", "coupon", index=False),
        *tfk("redeemer_client_id", "client"),
        *tfk("invoice_id", "invoice"),
        UniqueConstraint("tenant_id", "coupon_id", "redemption_key", name="uq_coupon_redemption_key"),
    )

    coupon_id: Mapped[UUID]
    redeemer_client_id: Mapped[UUID | None]
    redemption_key: Mapped[str] = mapped_column(info={"audit": "value"})
    invoice_id: Mapped[UUID | None]
    discount_minor: Mapped[int] = _money()
    redeemed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    released_at: Mapped[datetime | None]


class PaymentSchedule(TenantOwned, Timestamps, Base):
    """One instalment of an invoice (BIL-06): a due-date plan, not an allocation target."""

    __tablename__ = "payment_schedule"
    __table_args__ = tenant_args(
        *tfk("invoice_id", "invoice", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "invoice_id", "seq", name="uq_payment_schedule_seq"),
        CheckConstraint("amount_minor >= 0", name="amount"),
        CheckConstraint("covered_minor BETWEEN 0 AND amount_minor", name="covered"),
        Index("ix_payment_schedule_due", "tenant_id", "due_on", postgresql_where=text("covered_minor < amount_minor")),
    )

    invoice_id: Mapped[UUID]
    seq: Mapped[int]
    due_on: Mapped[date]
    amount_minor: Mapped[int] = _money()
    covered_minor: Mapped[int] = _money(server_default=text("0"))


class ProviderCustomer(TenantOwned, Timestamps, Base):
    __tablename__ = "provider_customer"
    __table_args__ = tenant_args(
        *tfk("client_id", "client"),
        *tfk("provider_account_id", "provider_account", index=False),
        UniqueConstraint("tenant_id", "provider_account_id", "client_id", name="uq_provider_customer"),
    )

    client_id: Mapped[UUID]
    provider_account_id: Mapped[UUID]
    provider_customer_ref: Mapped[str] = mapped_column(info={"audit": "value"})


class PaymentMethod(TenantOwned, Timestamps, Base):
    """Stored card or bank account (PAY-06): provider references and display data only, never numbers."""

    __tablename__ = "payment_method"
    __table_args__ = tenant_args(
        *tfk("client_id", "client"),
        *tfk("provider_account_id", "provider_account", index=False),
        UniqueConstraint("tenant_id", "provider_account_id", "provider_method_ref", name="uq_payment_method_ref"),
        enum_check("kind", MethodKind),
        enum_check("status", MethodStatus),
        CheckConstraint(
            "(kind = 'card') = (exp_month IS NOT NULL AND exp_year IS NOT NULL) "
            "AND (exp_month IS NULL OR exp_month BETWEEN 1 AND 12)",
            name="expiry",
        ),
        Index(
            "uq_payment_method_autopay", "tenant_id", "client_id", unique=True,
            postgresql_where=text("is_autopay AND status = 'active'"),
        ),
        Index(
            "ix_payment_method_expiry", "tenant_id", "exp_year", "exp_month",
            postgresql_where=text("kind = 'card' AND status = 'active'"),
        ),
    )  # fmt: skip

    client_id: Mapped[UUID]
    provider_account_id: Mapped[UUID]
    provider_method_ref: Mapped[str] = mapped_column(info={"audit": "never"})
    kind: Mapped[str] = enum_column()
    brand: Mapped[str | None] = mapped_column(info={"audit": "value"})
    last4: Mapped[str] = mapped_column(info={"audit": "value"})
    exp_month: Mapped[int | None] = mapped_column(SmallInteger)
    exp_year: Mapped[int | None] = mapped_column(SmallInteger)
    funding: Mapped[str | None] = mapped_column(info={"audit": "value"})
    wallet: Mapped[str | None] = mapped_column(info={"audit": "value"})
    is_autopay: Mapped[bool] = mapped_column(server_default=text("true"))
    status: Mapped[str] = enum_column()
    verified_at: Mapped[datetime | None]
    suspended_on: Mapped[date | None]
    mandate_ref: Mapped[str | None] = mapped_column(info={"audit": "never"})
    removed_at: Mapped[datetime | None]


class AutopayRun(TenantOwned, Timestamps, Base):
    __tablename__ = "autopay_run"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", "business_on", name="uq_autopay_run"),
        enum_check("status", AutopayRunStatus),
    )

    location_id: Mapped[UUID]
    business_on: Mapped[date]
    status: Mapped[str] = enum_column(server_default=text("'running'"))
    selected_count: Mapped[int] = mapped_column(server_default=text("0"))
    succeeded_count: Mapped[int] = mapped_column(server_default=text("0"))
    failed_count: Mapped[int] = mapped_column(server_default=text("0"))
    collected_minor: Mapped[int] = _money(server_default=text("0"))
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    finished_at: Mapped[datetime | None]


class AutopayAttempt(TenantOwned, Timestamps, Base):
    __tablename__ = "autopay_attempt"
    __table_args__ = tenant_args(
        *tfk("autopay_run_id", "autopay_run"),
        *tfk("invoice_id", "invoice", index=False),
        *tfk("payment_method_id", "payment_method"),
        *tfk("payment_id", "payment", index=False),
        *tfk("error_cleared_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "invoice_id", "attempt_no", name="uq_autopay_attempt"),
        Index(
            "uq_autopay_attempt_payment", "tenant_id", "payment_id", unique=True,
            postgresql_where=text("payment_id IS NOT NULL"),
        ),
        Index(
            "ix_autopay_attempt_errors", "tenant_id", text("created_at DESC"),
            postgresql_where=text("status = 'failed' AND error_cleared_at IS NULL"),
        ),
        enum_check("status", AutopayAttemptStatus),
    )  # fmt: skip

    autopay_run_id: Mapped[UUID]
    invoice_id: Mapped[UUID]
    attempt_no: Mapped[int]
    amount_minor: Mapped[int] = _money()
    credit_applied_minor: Mapped[int] = _money(server_default=text("0"))
    payment_method_id: Mapped[UUID | None]
    payment_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    failure_category: Mapped[str | None] = mapped_column(info={"audit": "value"})
    failure_message: Mapped[str | None]
    error_cleared_at: Mapped[datetime | None]
    error_cleared_by_staff_user_id: Mapped[UUID | None]


class BillingNotice(TenantOwned, Base):
    """Dedupe log of billing-triggered notices. Append-only: insert first, send only if the insert won."""

    __tablename__ = "billing_notice"
    __table_args__ = tenant_args(
        *tfk("client_id", "client"),
        *tfk("location_id", "location"),
        UniqueConstraint("tenant_id", "kind", "subject_type", "subject_id", "dedupe_key", name="uq_billing_notice"),
        enum_check("kind", NoticeKind),
        enum_check("subject_type", NoticeSubject),
    )

    kind: Mapped[str] = enum_column()
    subject_type: Mapped[str] = enum_column()
    subject_id: Mapped[UUID]
    dedupe_key: Mapped[str] = mapped_column(info={"audit": "value"})
    client_id: Mapped[UUID | None]
    location_id: Mapped[UUID | None]
    sent_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class BillingDocumentDelivery(TenantOwned, Timestamps, Base):
    """One sending of an invoice, receipt or statement (BIL-10, BIL-11, PAY-03)."""

    __tablename__ = "billing_document_delivery"
    __table_args__ = tenant_args(
        *tfk("invoice_id", "invoice"),
        *tfk("payment_id", "payment"),
        *tfk("client_id", "client"),
        *tfk("requested_by_staff_user_id", "staff_user"),
        enum_check("document_kind", DocumentKind),
        enum_check("channel", DeliveryChannel),
        enum_check("status", DeliveryStatus),
        CheckConstraint(
            "(document_kind = 'invoice') = (invoice_id IS NOT NULL) AND "
            "(document_kind = 'receipt') = (payment_id IS NOT NULL) AND "
            "(document_kind <> 'statement' OR client_id IS NOT NULL)",
            name="subject",
        ),
        CheckConstraint("channel <> 'email' OR to_email IS NOT NULL", name="to_email"),
    )

    document_kind: Mapped[str] = enum_column()
    invoice_id: Mapped[UUID | None]
    payment_id: Mapped[UUID | None]
    client_id: Mapped[UUID | None]
    channel: Mapped[str] = enum_column()
    to_email: Mapped[str | None] = mapped_column(CITEXT)
    status: Mapped[str] = enum_column(server_default=text("'queued'"))
    failure_message: Mapped[str | None]
    requested_by_staff_user_id: Mapped[UUID | None]


class InvoicePayLink(TenantOwned, Timestamps, Base):
    """The emailed pay link of an invoice (security-baseline 17.2): only the token's hash is stored, it
    expires, and the payment it produces consumes it."""

    __tablename__ = "invoice_pay_link"
    __table_args__ = tenant_args(
        *tfk("invoice_id", "invoice"),
        *tfk("payment_id", "payment"),
        UniqueConstraint("tenant_id", "token_hash", name="uq_invoice_pay_link_token_hash"),
    )

    invoice_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    payment_id: Mapped[UUID | None]


# --- pre-defined items (BIL-14, data-model-money 1.1) ------------------------------------------------------

CatalogItemKind = _values("one_off", "recurring")
CatalogUnit = _values("day", "week", "month", "year")
CatalogStartMode = _values("sale_date", "fixed_date")
CatalogInvoiceOption = _values("single_invoice", "invoice_per_occurrence", "leave_uninvoiced")
CatalogSaleStatus = _values("active", "renewed", "ended", "cancelled")


class CatalogItem(TenantOwned, Timestamps, Base):
    """A reusable fee definition, one-off or recurring, sold to clients as a `catalog_item_sale`."""

    __tablename__ = "catalog_item"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("renews_as_catalog_item_id", "catalog_item"),
        enum_check("kind", CatalogItemKind),
        enum_check("start_mode", CatalogStartMode),
        enum_check("length_unit", CatalogUnit),
        enum_check("recurrence_unit", CatalogUnit),
        enum_check("invoice_option", CatalogInvoiceOption),
        CheckConstraint(
            "(kind = 'recurring') = (num_nonnulls(recurrence_unit, recurrence_every, recurrence_count) = 3) "
            "AND num_nonnulls(recurrence_unit, recurrence_every, recurrence_count) IN (0, 3)",
            name="recurrence",
        ),
        CheckConstraint("recurrence_every IS NULL OR recurrence_every >= 1", name="every"),
        CheckConstraint("recurrence_count IS NULL OR recurrence_count BETWEEN 1 AND 366", name="count"),
        CheckConstraint(
            "kind = 'one_off' OR length_count IS NULL", name="length_one_off"
        ),
        CheckConstraint("(length_count IS NULL) = (length_unit IS NULL) AND COALESCE(length_count, 1) >= 1", name="length"),
        CheckConstraint("start_mode <> 'fixed_date' OR starts_on IS NOT NULL", name="start"),
        CheckConstraint("fee_minor >= 0", name="fee"),
        CheckConstraint(
            "num_nonnulls(discount_pct, discount_minor) <= 1 AND COALESCE(discount_pct, 0) BETWEEN 0 AND 100 "
            "AND COALESCE(discount_minor, 0) >= 0",
            name="discount",
        ),
        CheckConstraint("renew_lead_days BETWEEN 0 AND 366", name="renew_lead_days"),
        CheckConstraint("renews_as_catalog_item_id IS NULL OR is_auto_renew", name="renews_as"),
        Index("ix_catalog_item_location", "tenant_id", "location_id", "is_active", "description"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    description: Mapped[str]
    additional_description: Mapped[str | None]
    internal_remarks: Mapped[str | None]
    start_mode: Mapped[str] = enum_column(server_default=text("'sale_date'"))
    starts_on: Mapped[date | None]
    length_count: Mapped[int | None]
    length_unit: Mapped[str | None] = enum_column()
    recurrence_unit: Mapped[str | None] = enum_column()
    recurrence_every: Mapped[int | None]
    recurrence_count: Mapped[int | None]
    fee_minor: Mapped[int] = _money()
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount_minor: Mapped[int | None] = mapped_column(BigInteger)
    invoice_option: Mapped[str] = enum_column(server_default=text("'single_invoice'"))
    is_autopay: Mapped[bool] = _false()
    is_auto_renew: Mapped[bool] = _false()
    renew_lead_days: Mapped[int] = mapped_column(server_default=text("0"))
    renews_as_catalog_item_id: Mapped[UUID | None]
    revenue_category_id: Mapped[UUID]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class CatalogItemSale(TenantOwned, Timestamps, Base):
    """One sale of an item to a client: the `source` of the charges it expands into, and the row the renewal
    job advances. `previous_sale_id` is unique, so a renewal is created once however often the job runs."""

    __tablename__ = "catalog_item_sale"
    __table_args__ = tenant_args(
        *tfk("catalog_item_id", "catalog_item"),
        *tfk("client_id", "client"),
        *tfk("location_id", "location"),
        *tfk("renews_as_catalog_item_id", "catalog_item"),
        *tfk("previous_sale_id", "catalog_item_sale", index=False),
        *tfk("sold_by_staff_user_id", "staff_user"),
        enum_check("status", CatalogSaleStatus),
        UniqueConstraint("tenant_id", "previous_sale_id", name="uq_catalog_item_sale_previous"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="term"),
        CheckConstraint("NOT is_auto_renew OR renew_on IS NOT NULL", name="renew_on"),
        Index(
            "ix_catalog_item_sale_renew_due", "tenant_id", "renew_on",
            postgresql_where=text("status = 'active' AND is_auto_renew"),
        ),
        Index("ix_catalog_item_sale_ends", "tenant_id", "ends_on", postgresql_where=text("status = 'active'")),
    )  # fmt: skip

    catalog_item_id: Mapped[UUID]
    client_id: Mapped[UUID]
    location_id: Mapped[UUID]
    terms: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sold_on: Mapped[date]
    starts_on: Mapped[date]
    ends_on: Mapped[date | None]
    is_auto_renew: Mapped[bool] = _false()
    renew_on: Mapped[date | None]
    renews_as_catalog_item_id: Mapped[UUID | None]
    previous_sale_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    sold_by_staff_user_id: Mapped[UUID | None]
