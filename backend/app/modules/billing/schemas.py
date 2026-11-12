"""Request and response models for the billing API (docs/api/openapi-money.yaml, tag billing). Kernel slice."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import EmailStr, Field, StringConstraints, computed_field

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)
from app.ports import payment_provider

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
    exclude_tax_ids: Annotated[list[UUID], Field(max_length=20)] = []
    service_starts_on: date | None = None
    service_ends_on: date | None = None
    coupon_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = None


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
    adjusts_charge_id: UUID | None
    coupon_id: UUID | None
    internal_remarks: str | None
    service_starts_on: date | None
    service_ends_on: date | None
    created_by_staff_user_id: UUID | None
    reason: str | None
    created_at: datetime


class InvoiceCreate(In):
    charge_ids: Annotated[list[UUID], Field(min_length=1, max_length=200)]
    bill_to_client_id: UUID | None = None
    due_on: date | None = None
    is_autopay: bool = False
    comments: Text | None = None


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
    is_autopay: bool
    past_due_since_on: date | None
    dunning_state: Literal["none", "retrying", "awaiting_method", "exhausted"]
    attempt_count: int
    next_attempt_on: date | None
    comments: str | None
    organization_name: str | None
    void_reason: str | None
    version: int
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
    payment_method_id: UUID | None = None  # a stored method of this payer, instead of method_token
    tender_type_id: UUID | None = None  # a tenant-labelled record-only tender of the given kind
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
    refund_batch_id: UUID | None
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
    # Present only on the response that created a `requires_action` payment: the payer's browser needs it
    # to authenticate with the processor. Never stored.
    client_secret: str | None = None


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


# === build module 8 ========================================================================================

Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Rate = Annotated[Decimal, Field(ge=0, lt=1, decimal_places=6)]
Quantity = Annotated[Decimal, Field(gt=0, le=100000, decimal_places=3)]
Days = Annotated[list[Annotated[int, Field(ge=-365, le=365)]], Field(max_length=12)]


class ReasonRequest(In):
    reason: Text


# --- catalogue ---------------------------------------------------------------------------------------------


class RevenueCategoryCreate(In):
    code: Code
    label: Text
    remarks: Text | None = None
    parent_id: UUID | None = None
    tax_ids: Annotated[list[UUID], Field(max_length=20)] = []


class RevenueCategoryUpdate(In):
    label: Text | None = None
    remarks: Text | None = None
    parent_id: UUID | None = None
    is_active: bool | None = None
    tax_ids: Annotated[list[UUID], Field(max_length=20)] | None = None


class RevenueCategoryDetail(RevenueCategoryOut):
    remarks: str | None
    tax_ids: list[UUID]


class TaxRateOut(Out):
    id: UUID
    rate: Decimal
    effective_from_on: date


class TaxOut(Out):
    id: UUID
    code: str
    label: str
    remarks: str | None
    is_active: bool
    deactivated_on: date | None


class TaxDetail(TaxOut):
    rates: list[TaxRateOut]


class TaxRateIn(In):
    rate: Rate
    effective_from_on: date


class TaxCreate(TaxRateIn):
    code: Code
    label: Text
    remarks: Text | None = None


class TaxUpdate(In):
    label: Text | None = None
    remarks: Text | None = None
    is_active: bool | None = None
    deactivated_on: date | None = None


class TaxRateUpdate(In):
    rate: Rate | None = None
    effective_from_on: date | None = None


class TenderTypeOut(Out):
    id: UUID
    kind: TenderKind
    label: str
    is_processed: bool
    is_optional: bool
    is_enabled: bool
    sort_order: int


class TenderTypeCreate(In):
    kind: Literal["external", "other"]
    label: Text
    sort_order: Annotated[int, Field(ge=0, le=1000)] = 100


class TenderTypeUpdate(In):
    label: Text | None = None
    is_enabled: bool | None = None
    sort_order: Annotated[int, Field(ge=0, le=1000)] | None = None


class BillingSettingsIn(In):
    is_membership_autopay_default_staff: bool = False
    is_membership_autopay_default_portal: bool = True
    save_card_default: Literal["never", "ask", "always"] = "ask"
    card_expiry_notice_days: Days = [60, 30]
    card_expiry_notice_scope: Literal["all_methods", "autopay_methods"] = "autopay_methods"
    decline_notice_scope: Literal["off", "all_payments", "autopay_payments"] = "all_payments"
    decline_alert_email: EmailStr | None = None
    decline_alert_mode: Literal["per_event", "daily_digest"] = "per_event"
    autopay_retry_offset_days: Days = [3, 5, 7]
    due_reminder_offset_days: Days = [-3]
    is_portal_blocked_when_past_due: bool = False
    invoice_email_subject: Text = "Invoice {invoice_number}"
    invoice_footer: Text | None = None
    receipt_footer: Text | None = None
    statement_email_subject: Text | None = None
    statement_email_body: Annotated[str, StringConstraints(max_length=4000)] | None = None
    statement_footer: Text | None = None
    is_program_description_on_invoice: bool = False
    program_description_source: Literal["group", "subgroup"] = "group"
    bill_to_fields: list[Literal["name", "organization", "address", "email", "phone"]] = ["name", "address"]
    package_invoice_sessions: Literal["all", "attended", "none"] = "all"


class BillingSettingsOut(BillingSettingsIn, Out):
    model_config = {"from_attributes": True, "extra": "ignore"}
    id: UUID
    location_id: UUID | None


class PeriodLock(In):
    locked_through_on: date | None


class PeriodLockOut(Out):
    locked_through_on: date | None


class CouponCreate(In):
    name: Text
    code: Code
    starts_at: datetime
    ends_at: datetime | None = None
    discount_pct: Annotated[Decimal, Field(gt=0, le=100, decimal_places=2)] | None = None
    discount_minor: PositiveMinor | None = None
    limit_per_client: Annotated[int, Field(ge=1, le=100000)] | None = None
    is_portal_enabled: bool = False
    is_active: bool = True


class CouponUpdate(In):
    name: Text | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    discount_pct: Annotated[Decimal, Field(gt=0, le=100, decimal_places=2)] | None = None
    discount_minor: PositiveMinor | None = None
    limit_per_client: Annotated[int, Field(ge=1, le=100000)] | None = None
    is_portal_enabled: bool | None = None
    is_active: bool | None = None


class CouponOut(Out):
    id: UUID
    name: str
    code: str
    starts_at: datetime
    ends_at: datetime | None
    discount_pct: Decimal | None
    discount_minor: int | None
    limit_per_client: int | None
    is_portal_enabled: bool
    is_active: bool


class CouponValidateRequest(In):
    code: Code
    subtotal_minor: Minor
    redeemer_client_id: UUID | None = None
    channel: Literal["staff", "pos", "portal"] = "staff"


class CouponQuote(Out):
    coupon_id: UUID
    is_valid: bool
    invalid_reason: str | None
    discount_minor: int


class CouponRedemptionOut(Out):
    id: UUID
    coupon_id: UUID
    redeemer_client_id: UUID | None
    redemption_key: str
    invoice_id: UUID | None
    discount_minor: int
    redeemed_at: datetime
    released_at: datetime | None


# --- items and invoices ------------------------------------------------------------------------------------


class ChargePreviewRequest(In):
    location_id: UUID
    unit_price_minor: Minor
    quantity: Quantity = Decimal(1)
    discount_minor: Minor = 0
    revenue_category_id: UUID | None = None
    revenue_on: date | None = None
    exclude_tax_ids: Annotated[list[UUID], Field(max_length=20)] = []


class ChargeTaxLine(Out):
    tax_id: UUID
    rate: Decimal
    amount_minor: int
    is_excluded: bool


class ChargePreview(Out):
    net_minor: int
    tax_minor: int
    total_minor: int
    taxes: list[ChargeTaxLine]


class ChargeDetail(ChargeOut):
    taxes: list[ChargeTaxLine]


class ChargeUpdate(In):
    """Text and service-period fields update in place. A money field replaces the item with an adjustment
    and needs `reason`."""

    description: Text | None = None
    additional_description: Text | None = None
    internal_remarks: Text | None = None
    service_starts_on: date | None = None
    service_ends_on: date | None = None
    quantity: Quantity | None = None
    unit_price_minor: Minor | None = None
    discount_minor: Minor | None = None
    exclude_tax_ids: Annotated[list[UUID], Field(max_length=20)] | None = None
    reason: Text | None = None


class InvoiceUpdate(In):
    invoice_on: date | None = None
    due_on: date | None = None
    is_autopay: bool | None = None
    comments: Text | None = None
    organization_name: Text | None = None
    version: int | None = None


class InvoiceChargesAdd(In):
    charge_ids: Annotated[list[UUID], Field(min_length=1, max_length=200)]


class InvoiceChargeMove(In):
    target_invoice_id: UUID


class InvoiceVoidRequest(In):
    reason: Text
    release_allocations: bool = False


class InvoiceReassign(In):
    bill_to_client_id: UUID


class MarkPaidRequest(In):
    external_reference: Text | None = None
    memo: Text | None = None


class InstalmentIn(In):
    due_on: date
    amount_minor: Minor


class InstalmentOut(Out):
    id: UUID
    seq: int
    due_on: date
    amount_minor: int
    covered_minor: int


class ScheduleReplace(In):
    instalments: Annotated[list[InstalmentIn], Field(min_length=1, max_length=120)]


class ScheduleGenerate(In):
    start_on: date
    every: Annotated[int, Field(ge=1, le=365)] = 1
    unit: Literal["day", "week", "half_month", "month", "year"] = "month"
    count: Annotated[int, Field(ge=1, le=120)]


class ScheduleOut(Out):
    invoice_id: UUID
    total_minor: int
    instalments: list[InstalmentOut]


class DocumentSendRequest(In):
    channel: Literal["email", "print", "download"] = "email"
    to_email: EmailStr | None = None


class DeliveryOut(Out):
    id: UUID
    document_kind: Literal["invoice", "receipt", "statement"]
    invoice_id: UUID | None
    payment_id: UUID | None
    client_id: UUID | None
    channel: Literal["email", "print", "download"]
    to_email: str | None
    status: Literal["queued", "sent", "failed"]
    created_at: datetime


class DocumentLine(Out):
    description: str
    additional_description: str | None = None
    quantity: Decimal
    unit_price_minor: int
    discount_minor: int
    net_minor: int
    tax_minor: int
    total_minor: int


class DocumentInstalment(Out):
    due_on: date
    amount_minor: int
    covered_minor: int


class InvoiceDocument(Out):
    invoice_id: UUID
    number: int
    status: str
    invoice_on: date
    due_on: date
    bill_to_client_id: UUID | None
    bill_to_name: str | None
    organization_name: str | None
    comments: str | None
    currency: str
    total_minor: int
    balance_minor: int
    paid_minor: int
    footer: str | None
    lines: list[DocumentLine]
    instalments: list[DocumentInstalment]


class BulkInvoiceRequest(In):
    """`action` is fixed to creating invoices: one per client. Give charge_ids, or a location."""

    action: Literal["create_invoices"] = "create_invoices"
    charge_ids: Annotated[list[UUID], Field(max_length=1000)] | None = None
    location_id: UUID | None = None
    only_mine: bool = False
    due_on: date | None = None
    is_autopay: bool = False
    is_dry_run: bool = False


class BulkInvoiceItem(Out):
    client_id: UUID | None
    location_id: UUID | None
    charge_ids: list[UUID]
    total_minor: int
    invoice_id: UUID | None
    status: Literal["pending", "done", "failed", "skipped"]
    error_code: str | None


class BulkInvoiceResult(Out):
    is_dry_run: bool
    items: list[BulkInvoiceItem]


class HistoryOut(Out):
    id: UUID
    occurred_at: datetime
    actor_type: str
    actor_label: str
    location_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID
    changes: dict
    reason: str | None


class NoticeOut(Out):
    id: UUID
    kind: str
    subject_type: str
    subject_id: UUID
    dedupe_key: str
    client_id: UUID | None
    location_id: UUID | None
    sent_at: datetime


class AgeingRow(Out):
    client_id: UUID | None
    current: int
    days_1_30: int
    days_31_60: int
    days_61_90: int
    days_over_90: int
    total_minor: int


class AgeingTotals(Out):
    current: int
    days_1_30: int
    days_31_60: int
    days_61_90: int
    days_over_90: int
    total_minor: int


class AgeingReport(Out):
    as_of: date
    currency: str
    rows: list[AgeingRow]
    totals: AgeingTotals


# --- payments, credit, receipts, statements ----------------------------------------------------------------


class ReceiptLine(Out):
    description: str
    invoice_id: UUID | None
    amount_minor: int


class ReceiptOut(Out):
    payment_id: UUID
    receipt_number: int
    status: str
    client_id: UUID | None
    tender_kind: str
    currency: str
    received_at: datetime
    received_minor: int
    applied_minor: int
    refunded_minor: int
    unapplied_minor: int
    card_brand: str | None
    card_last4: str | None
    footer: str | None
    lines: list[ReceiptLine]


class BillingSummary(Out):
    client_id: UUID
    currency: str
    credit_minor: int
    open_balance_minor: int
    past_due_minor: int
    oldest_past_due_on: date | None
    uninvoiced_minor: int


class AccountCredit(Out):
    client_id: UUID
    currency: str
    credit_minor: int
    payments: list[PaymentOut]


class CreditApplyRequest(AllocationsCreate):
    pass


class CreditApplied(Out):
    client_id: UUID
    applied_minor: int
    credit_minor: int


class CreditRefundRequest(In):
    amount_minor: PositiveMinor
    reason: Text


class StatementOut(Out):
    client_id: UUID
    from_on: date
    to_on: date
    date_basis: Literal["invoice_date", "due_date"]
    currency: str
    invoices: list[InvoiceOut]
    payments: list[PaymentOut]
    refunds: list[RefundOut]
    invoiced_minor: int
    paid_minor: int
    refunded_minor: int
    balance_due_minor: int
    credit_minor: int


class StatementSend(In):
    from_on: date
    to_on: date
    date_basis: Literal["invoice_date", "due_date"] = "invoice_date"
    to_email: EmailStr | None = None


# --- stored methods, autopay, processor --------------------------------------------------------------------

MethodToken = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class PaymentMethodOut(Out):
    """Display data only. The provider reference is never serialised."""

    id: UUID
    client_id: UUID
    kind: Literal["card", "bank_account"]
    brand: str | None
    last4: str
    exp_month: int | None
    exp_year: int | None
    funding: str | None
    wallet: str | None
    is_autopay: bool
    status: Literal["pending_verification", "active", "suspended", "removed"]
    created_at: datetime


class PaymentMethodAttach(In):
    method_token: MethodToken
    is_autopay: bool | None = None


class PaymentMethodUpdate(In):
    is_autopay: bool


class SetupIntentRequest(In):
    kinds: Annotated[list[Literal["card", "bank_account"]], Field(min_length=1, max_length=2)] = ["card"]


class BrowserKeys(Out):
    """Stripe.js needs these to tokenise a card on the tenant's connected account; both null for the fake."""

    publishable_key: str | None = None
    account_ref: str | None = None


class SetupIntentOut(BrowserKeys):
    provider: str
    client_secret: str


class BankVerifyRequest(In):
    amounts: Annotated[list[Annotated[int, Field(ge=1, le=99)]], Field(min_length=2, max_length=2)]


class AutopayRunStart(In):
    location_id: UUID
    business_on: date | None = None
    is_dry_run: bool = False


class AutopayRunOut(Out):
    id: UUID
    location_id: UUID
    business_on: date
    status: Literal["running", "completed", "completed_with_errors"]
    selected_count: int
    succeeded_count: int
    failed_count: int
    collected_minor: int
    started_at: datetime
    finished_at: datetime | None


class AutopayPreviewRow(Out):
    invoice_id: UUID
    number: int
    bill_to_client_id: UUID | None
    due_minor: int
    credit_minor: int
    has_payment_method: bool


class AutopayRunResult(Out):
    """`run` for a real run, `preview` for a dry run."""

    run: AutopayRunOut | None = None
    preview: list[AutopayPreviewRow] | None = None


class AutopayAttemptOut(Out):
    id: UUID
    autopay_run_id: UUID
    invoice_id: UUID
    attempt_no: int
    amount_minor: int
    credit_applied_minor: int
    payment_method_id: UUID | None
    payment_id: UUID | None
    status: Literal["pending", "succeeded", "processing", "failed", "skipped"]
    failure_category: str | None
    failure_message: str | None
    error_cleared_at: datetime | None
    created_at: datetime


class ProviderAccountOut(Out):
    id: UUID
    provider: Literal["stripe", "fake"]
    provider_account_ref: str
    status: Literal["pending", "restricted", "active", "disabled"]
    has_card: bool
    has_bank_debit: bool
    is_payouts_enabled: bool
    requirements_due: list[str] | None
    connected_at: datetime | None
    disabled_at: datetime | None

    @computed_field
    @property
    def publishable_key(self) -> str | None:
        """For Stripe.js on staff screens; null for the fake."""
        return payment_provider.browser_keys(self.provider, self.provider_account_ref)["publishable_key"]


class ProviderConnect(In):
    provider: Literal["stripe", "fake"]


class OnboardingLink(Out):
    url: str


class WebhookAck(Out):
    result: Literal["accepted", "duplicate", "ignored"]


# --- public pay link and portal: surface-specific bodies, only what the caller may set (baseline 17.1) -----

LinkToken = Annotated[str, StringConstraints(min_length=20, max_length=200)]


class InvoiceLinkLookup(In):
    token: LinkToken


class InvoiceLinkPayment(In):
    token: LinkToken
    method_token: MethodToken


class LinkInvoice(BrowserKeys):
    number: int
    status: str
    invoice_on: date
    due_on: date
    bill_to_name: str | None
    currency: str
    total_minor: int
    balance_minor: int
    lines: list[DocumentLine]
    provider: Literal["stripe", "fake"] | None  # which card entry the pay page shows; None: cannot take cards


class LinkPayment(Out):
    status: str
    amount_minor: int
    currency: str
    receipt_number: int
    client_secret: str | None = None


class PortalPaymentCreate(In):
    invoice_ids: Annotated[list[UUID], Field(min_length=1, max_length=50)]
    payment_method_id: UUID | None = None
    method_token: MethodToken | None = None
    use_account_credit: bool = False
    set_autopay: bool = False


# --- portal: what a client sees of their own money. No staff memos, collection state or void reasons. -------


class PortalInvoiceOut(Out):
    id: UUID
    number: int
    bill_to_client_id: UUID | None
    location_id: UUID
    invoice_on: date
    due_on: date
    status: Literal["open", "payment_pending", "partially_paid", "paid", "voided"]
    total_minor: int
    balance_minor: int
    is_autopay: bool
    past_due_since_on: date | None
    comments: str | None
    organization_name: str | None
    created_at: datetime


class PortalAllocationOut(Out):
    id: UUID
    charge_id: UUID
    amount_minor: int
    status: Literal["provisional", "applied", "released"]
    applied_at: datetime | None
    released_at: datetime | None


class PortalRefundOut(Out):
    id: UUID
    payment_id: UUID
    amount_minor: int
    currency: str
    method: Literal["original", "external"]
    status: Literal["pending", "succeeded", "failed", "cancelled"]
    refund_on: date
    created_at: datetime


class PortalPaymentOut(Out):
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
    received_at: datetime
    settled_at: datetime | None
    failure_category: str | None
    unapplied_minor: int
    refunded_minor: int


class PortalPaymentDetail(PortalPaymentOut):
    allocations: list[PortalAllocationOut]
    refunds: list[PortalRefundOut]


class PortalPayment(Out):
    credit_applied_minor: int
    payment: PortalPaymentDetail | None
    client_secret: str | None
