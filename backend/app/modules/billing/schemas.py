"""Request and response models for the billing API (docs/api/openapi-money.yaml, tag billing). Kernel slice."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Minor = Annotated[int, Field(ge=0, le=10**12)]  # minor units of the tenant currency
PositiveMinor = Annotated[int, Field(gt=0, le=10**12)]
# Kernel: the built-in kinds. Tenant-labelled record-only tenders are picked by id once module 8 lists them.
TenderKind = Literal["card", "bank_debit", "cash", "cheque", "bank_transfer", "gift_card", "external", "other"]


class RevenueCategoryOut(Out):
    id: UUID
    code: str
    label: str
    parent_id: UUID | None
    is_active: bool
    system_key: str | None


class ChargeCreate(In):
    client_id: UUID
    location_id: UUID
    description: Text
    unit_price_minor: Minor
    quantity: Annotated[Decimal, Field(gt=0, le=100000, decimal_places=3)] = Decimal(1)
    discount_minor: Minor = 0
    revenue_category_id: UUID | None = None
    revenue_on: date | None = None
    additional_description: Text | None = None
    internal_remarks: Text | None = None


class ChargeReverseRequest(In):
    reason: Text
    revenue_on: date | None = None


class ChargeOut(Out):
    id: UUID
    client_id: UUID | None
    location_id: UUID
    invoice_id: UUID | None
    kind: Literal["standard", "adjustment", "reversal", "surcharge"]
    status: Literal["active", "reversed", "voided"]
    source_context: str
    source_type: str
    source_id: UUID
    description: str
    additional_description: str | None
    quantity: Decimal
    unit_price_minor: int
    discount_minor: int
    net_minor: int
    tax_minor: int
    total_minor: int
    applied_minor: int
    bill_on: date
    revenue_on: date
    revenue_category_id: UUID
    reverses_charge_id: UUID | None
    reason: str | None
    created_at: datetime


class InvoiceCreate(In):
    charge_ids: Annotated[list[UUID], Field(min_length=1, max_length=200)]
    bill_to_client_id: UUID | None = None
    due_on: date | None = None


class InvoiceOut(Out):
    id: UUID
    number: int
    bill_to_client_id: UUID | None
    location_id: UUID
    origin: Literal["staff", "portal", "pos", "kiosk", "api", "system"]
    invoice_on: date
    due_on: date
    status: Literal["open", "payment_pending", "partially_paid", "paid", "voided"]
    total_minor: int
    balance_minor: int
    created_at: datetime


class InvoiceDetail(InvoiceOut):
    charges: list[ChargeOut]


class AllocationIn(In):
    charge_id: UUID
    amount_minor: PositiveMinor


class AllocationsCreate(In):
    """Explicit amounts per item, or an invoice to cover oldest item first, or neither: the payer's open items."""

    invoice_id: UUID | None = None
    allocations: Annotated[list[AllocationIn], Field(max_length=200)] | None = None


class PaymentTake(AllocationsCreate):
    client_id: UUID
    location_id: UUID
    amount_minor: PositiveMinor
    tender_kind: TenderKind
    # An opaque provider reference from the provider's hosted fields. Card and bank numbers never reach us.
    method_token: Annotated[str, StringConstraints(max_length=200)] | None = None
    external_reference: Text | None = None
    memo: Text | None = None


class AllocationOut(Out):
    id: UUID
    charge_id: UUID
    amount_minor: int
    status: Literal["provisional", "applied", "released"]
    applied_at: datetime | None
    released_at: datetime | None
    release_reason: str | None


class RefundCreate(In):
    amount_minor: PositiveMinor
    reason: Text
    method: Literal["original", "external"] | None = None
    comments: Text | None = None


class RefundOut(Out):
    id: UUID
    payment_id: UUID
    amount_minor: int
    currency: str
    method: Literal["original", "external"]
    status: Literal["pending", "succeeded", "failed", "cancelled"]
    refund_on: date
    reason: str
    failure_message: str | None
    created_at: datetime


class PaymentOut(Out):
    id: UUID
    receipt_number: int
    client_id: UUID | None
    location_id: UUID
    tender_kind: TenderKind
    amount_minor: int
    currency: str
    status: Literal[
        "initiated", "requires_action", "processing", "succeeded", "failed", "unknown", "cancelled", "disputed",
        "charged_back", "voided",
    ]  # fmt: skip
    origin: Literal["staff", "portal", "pos", "kiosk", "autopay", "api"]
    external_reference: str | None
    memo: str | None
    received_at: datetime
    settled_at: datetime | None
    failure_category: str | None
    failure_message: str | None
    unapplied_minor: int
    refunded_minor: int


class PaymentDetail(PaymentOut):
    allocations: list[AllocationOut]
    refunds: list[RefundOut]


class LedgerEntryOut(Out):
    id: UUID
    ledger_transaction_id: UUID
    account: Literal["receivable", "revenue", "tax_payable", "funds_received", "client_credit", "disputed_funds"]
    debit_minor: int
    credit_minor: int
    currency: str
    effective_on: date
    location_id: UUID
    client_id: UUID | None
    revenue_category_id: UUID | None
    tax_id: UUID | None
    charge_id: UUID | None
    payment_id: UUID | None
