"""Request and response models for the memberships API (docs/api/openapi-people.yaml, tag memberships)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Minor = Annotated[int, Field(ge=0, le=10**12)]
Order = Annotated[int, Field(ge=0, le=10_000)]  # sort_order: bounded so it never overflows the INTEGER column
Pct = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
Count = Annotated[int, Field(ge=1, le=1000)]
Unit = Literal["day", "week", "month", "year"]
Tail = Literal["extend_last", "drop_last", "prorate_last"]
TenderKind = Literal["card", "bank_debit", "cash", "cheque", "bank_transfer", "gift_card", "external", "other"]
Status = Literal["upcoming", "active", "frozen", "suspended", "expired", "cancelled"]


class MembershipTypeCreate(In):
    name: Name
    revenue_category_id: UUID
    sort_order: Order = 0
    is_active: bool = True


class MembershipTypeUpdate(In):
    name: Name | None = None
    revenue_category_id: UUID | None = None
    sort_order: Order | None = None
    is_active: bool | None = None


class MembershipTypeOut(Out):
    id: UUID
    name: str
    revenue_category_id: UUID
    sort_order: int
    is_active: bool


class PlanAddonIn(In):
    """A bundled package plan, or a pre-defined billing item billed with the dues (MEM-04)."""

    addon_kind: Literal["package_plan", "catalog_item"] = "package_plan"
    package_plan_id: UUID | None = None
    catalog_item_id: UUID | None = None
    quantity: Count = 1

    @model_validator(mode="after")
    def _one_target(self):
        if (self.package_plan_id is None) != (self.addon_kind == "catalog_item") or (self.catalog_item_id is None) != (
            self.addon_kind == "package_plan"
        ):
            raise ValueError("Name the package plan or the catalogue item the add-on kind says, and only that.")
        return self


class PlanAddonsReplace(In):
    addons: list[PlanAddonIn] = Field(max_length=20)


class PlanAddonOut(Out):
    id: UUID
    addon_kind: str
    package_plan_id: UUID | None
    catalog_item_id: UUID | None
    quantity: int
    sort_order: int


class _PlanFields(In):
    invoice_description: Annotated[str, StringConstraints(max_length=100)] | None = None
    fixed_start_on: date | None = None
    billing_interval_unit: Unit = "month"
    billing_interval_count: Count = 1
    auto_renew_lead_count: Annotated[int, Field(ge=0, le=1000)] | None = None
    auto_renew_lead_unit: Unit | None = None
    renewal_target: Literal["same_terms", "plan"] = "same_terms"
    renews_as_plan_id: UUID | None = None
    max_visits_count: Count | None = None
    initiation_fee_minor: Minor = 0
    payment_due_day: Annotated[int, Field(ge=1, le=31)] | None = None
    discount_pct: Pct | None = None
    discount_minor: Minor | None = None
    revenue_category_id: UUID | None = None
    default_invoice_mode: Literal["ask", "per_period", "single"] = "ask"
    is_autopay_default: bool | None = None  # BIL-17: null follows the billing setting for the channel
    is_sold_online: bool = False
    proration_mode: Literal["none", "to_month_start", "seller_choice"] = "none"
    proration_tail: Tail | None = None
    sort_order: Order = 0
    is_active: bool = True


class MembershipPlanCreate(_PlanFields):
    membership_type_id: UUID
    name: Name
    billing_occurrences_count: Count
    term_fee_minor: Minor


class MembershipPlanUpdate(In):
    membership_type_id: UUID | None = None
    name: Name | None = None
    invoice_description: Annotated[str, StringConstraints(max_length=100)] | None = None
    fixed_start_on: date | None = None
    billing_interval_unit: Unit | None = None
    billing_interval_count: Count | None = None
    billing_occurrences_count: Count | None = None
    auto_renew_lead_count: Annotated[int, Field(ge=0, le=1000)] | None = None
    auto_renew_lead_unit: Unit | None = None
    renewal_target: Literal["same_terms", "plan"] | None = None
    renews_as_plan_id: UUID | None = None
    max_visits_count: Count | None = None
    initiation_fee_minor: Minor | None = None
    term_fee_minor: Minor | None = None
    payment_due_day: Annotated[int, Field(ge=1, le=31)] | None = None
    discount_pct: Pct | None = None
    discount_minor: Minor | None = None
    revenue_category_id: UUID | None = None
    default_invoice_mode: Literal["ask", "per_period", "single"] | None = None
    is_autopay_default: bool | None = None
    is_sold_online: bool | None = None
    proration_mode: Literal["none", "to_month_start", "seller_choice"] | None = None
    proration_tail: Tail | None = None
    sort_order: Order | None = None
    is_active: bool | None = None


class MembershipPlanOut(Out):
    id: UUID
    membership_type_id: UUID
    name: str
    invoice_description: str | None
    fixed_start_on: date | None
    billing_interval_unit: str
    billing_interval_count: int
    billing_occurrences_count: int
    auto_renew_lead_count: int | None
    auto_renew_lead_unit: str | None
    renewal_target: str
    renews_as_plan_id: UUID | None
    max_visits_count: int | None
    initiation_fee_minor: int
    term_fee_minor: int
    payment_due_day: int | None
    discount_pct: Decimal | None
    discount_minor: int | None
    revenue_category_id: UUID | None
    default_invoice_mode: str
    is_autopay_default: bool | None
    is_sold_online: bool
    proration_mode: str
    proration_tail: str | None
    sort_order: int
    is_active: bool
    version: int
    addons: list[PlanAddonOut]


class MembershipSettingsUpdate(In):
    is_remark_required_on_freeze: bool | None = None
    is_remark_required_on_suspend: bool | None = None
    is_remark_required_on_cancel: bool | None = None
    payment_method_capture: Literal["hidden", "optional", "required"] | None = None
    online_card_save_mode: Literal["always", "when_nothing_due", "ask"] | None = None
    billing_lead_days: Annotated[int, Field(ge=0, le=60)] | None = None
    is_daily_visit_limit_enabled: bool | None = None
    freeze_resume_invoice_mode: Literal["per_period", "single", "deferred"] | None = None
    is_addon_package_cancelled_with_contract: bool | None = None


class MembershipSettingsOut(Out):
    is_remark_required_on_freeze: bool
    is_remark_required_on_suspend: bool
    is_remark_required_on_cancel: bool
    payment_method_capture: str
    online_card_save_mode: str
    billing_lead_days: int
    is_daily_visit_limit_enabled: bool
    freeze_resume_invoice_mode: str
    is_addon_package_cancelled_with_contract: bool


class CustomizeTerms(In):
    """Per-sale changes to the plan's terms; needs memberships.contract.customize_terms."""

    term_fee_minor: Minor | None = None
    initiation_fee_minor: Minor | None = None
    discount_pct: Pct | None = None
    discount_minor: Minor | None = None
    end_on: date | None = None
    billing_occurrences_count: Count | None = None
    max_visits_count: Count | None = None


class SalePayment(In):
    amount_minor: Annotated[int, Field(gt=0, le=10**12)]
    tender_kind: TenderKind
    # An opaque provider reference from the provider's hosted fields. Card and bank numbers never reach us.
    method_token: Annotated[str, StringConstraints(max_length=200)] | None = None
    external_reference: Annotated[str, StringConstraints(max_length=500)] | None = None
    memo: Annotated[str, StringConstraints(max_length=500)] | None = None


class ContractQuote(In):
    client_id: UUID
    location_id: UUID
    membership_plan_id: UUID
    start_on: date | None = None
    proration_tail: Tail | None = None  # the seller's choice when the plan leaves proration to the sale
    invoice_mode: Literal["per_period", "single", "deferred"] | None = None
    is_autopay: bool | None = None
    is_auto_renew: bool | None = None
    customize: CustomizeTerms | None = None
    # This sale's add-ons instead of the plan's (MEM-04); a list other than the plan's needs customize_terms.
    addons: list[PlanAddonIn] | None = Field(default=None, max_length=20)


class ContractSell(ContractQuote):
    sold_by_staff_user_id: UUID | None = None
    referred_by_client_id: UUID | None = None
    internal_notes: Note | None = None
    share_client_ids: list[UUID] = Field(default_factory=list, max_length=20)
    payment: SalePayment | None = None


class PortalContractBuy(In):
    membership_plan_id: UUID
    location_id: UUID
    client_id: UUID | None = None  # who the membership is for; default: the signed-in client
    start_on: date | None = None
    proration_tail: Tail | None = None
    is_autopay: bool | None = None
    is_auto_renew: bool | None = None
    tender_kind: Literal["card", "bank_debit"] = "card"
    method_token: Annotated[str, StringConstraints(max_length=200)] | None = None
    payment_method_id: UUID | None = None  # one of the payer's stored methods, instead of a new token
    save_method: bool | None = None  # MEM-05: the buyer's answer when the card-save mode is `ask`
    terms_version_id: Annotated[str, StringConstraints(max_length=64)] | None = None  # the portal terms shown (SSP-14)
    coupon_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = (
        None  # SSP-11
    )


class PublicPlanOut(Out):
    id: UUID
    membership_type_id: UUID
    name: str
    invoice_description: str | None
    fixed_start_on: date | None
    billing_interval_unit: str
    billing_interval_count: int
    billing_occurrences_count: int
    initiation_fee_minor: int
    term_fee_minor: int
    discount_pct: Decimal | None
    discount_minor: int | None
    max_visits_count: int | None
    proration_mode: str


class QuotePeriodOut(Out):
    kind: str
    sequence_number: int
    starts_on: date | None
    ends_on: date | None
    due_on: date
    list_amount_minor: int
    amount_minor: int
    is_prorated: bool


class ContractQuoteOut(Out):
    start_on: date
    end_on: date
    is_prorated: bool
    proration_tail: str | None
    invoice_mode: str
    is_autopay: bool  # BIL-17: what the sale resolves when it does not say
    card_save_mode: str  # MEM-05: whether checkout keeps the card that pays now (the portal asks in `ask`)
    is_auto_renew: bool
    renew_on: date | None
    periods: list[QuotePeriodOut]
    total_minor: int
    due_now_minor: int
    requirements: list[dict[str, Any]]


class ContractOut(Out):
    id: UUID
    owner_client_id: UUID
    location_id: UUID
    membership_plan_id: UUID | None
    membership_type_id: UUID
    name: str
    invoice_description: str | None
    revenue_category_id: UUID
    start_on: date
    end_on: date
    original_end_on: date
    billing_interval_unit: str
    billing_interval_count: int
    billing_occurrences_count: int
    term_fee_minor: int
    initiation_fee_minor: int
    discount_pct: Decimal | None
    discount_minor: int | None
    payment_due_day: int | None
    revenue_on: date | None
    max_visits_count: int | None
    visits_used_count: int
    visits_remaining_count: int | None
    is_autopay: bool
    invoice_mode: str
    is_prorated: bool
    proration_tail: str | None
    is_auto_renew: bool
    auto_renew_lead_count: int | None
    auto_renew_lead_unit: str | None
    renew_on: date | None
    renewal_target: str
    renews_as_plan_id: UUID | None
    renewal_discount_pct: Decimal | None
    renewal_discount_minor: int | None
    renewal_description: str | None
    renewal_remark: str | None
    auto_renew_disabled_by: str | None
    auto_renew_disabled_at: datetime | None
    previous_contract_id: UUID | None
    successor_contract_id: UUID | None
    sold_by_staff_user_id: UUID | None
    referred_by_client_id: UUID | None
    sales_channel: str
    internal_notes: str | None
    client_document_id: UUID | None
    status: Status
    effective_status: Status
    activated_at: datetime | None
    cancelled_on: date | None
    cancel_reason: str | None
    cancel_remarks: str | None
    cancelled_at: datetime | None
    is_cancel_scheduled: bool
    covered_client_count: int
    version: int
    created_at: datetime


class PortalContractOut(Out):
    """What a member sees: no internal notes, remarks or staff attribution."""

    id: UUID
    owner_client_id: UUID
    location_id: UUID
    name: str
    start_on: date
    end_on: date
    term_fee_minor: int
    billing_interval_unit: str
    billing_interval_count: int
    max_visits_count: int | None
    visits_used_count: int
    visits_remaining_count: int | None
    is_autopay: bool
    is_auto_renew: bool
    renew_on: date | None
    status: Status
    effective_status: Status
    is_cancel_scheduled: bool


class ContractSaleOut(ContractOut):
    invoice_id: UUID | None
    payment_id: UUID | None
    payment_status: str | None


class PortalContractSaleOut(PortalContractOut):
    client_document_id: UUID | None
    invoice_id: UUID | None
    payment_id: UUID | None
    payment_status: str | None


class ContractUpdate(In):
    is_autopay: bool | None = None
    is_auto_renew: bool | None = None
    auto_renew_lead_count: Annotated[int, Field(ge=0, le=1000)] | None = None
    auto_renew_lead_unit: Unit | None = None
    renewal_target: Literal["same_terms", "plan"] | None = None
    renews_as_plan_id: UUID | None = None
    renewal_discount_pct: Pct | None = None
    renewal_discount_minor: Minor | None = None
    renewal_description: Annotated[str, StringConstraints(max_length=100)] | None = None
    renewal_remark: Note | None = None
    max_visits_count: Count | None = None
    internal_notes: Note | None = None
    referred_by_client_id: UUID | None = None
    revenue_on: date | None = None
    invoice_description: Annotated[str, StringConstraints(max_length=100)] | None = None


class AgreementIn(In):
    client_document_id: UUID


class SoldByIn(In):
    sold_by_staff_user_id: UUID | None


class PeriodOut(Out):
    id: UUID
    membership_contract_id: UUID
    kind: str
    sequence_number: int
    start_on: date | None
    end_on: date | None
    due_on: date
    bill_on: date
    revenue_on: date
    list_amount_minor: int
    amount_minor: int
    is_prorated: bool
    description: str
    suspension_id: UUID | None
    status: Literal["scheduled", "billed", "withheld", "cancelled"]
    charge_id: UUID | None
    billed_at: datetime | None
    withheld_by_freeze_id: UUID | None
    cancelled_reason: str | None


class PeriodUpdate(In):
    amount_minor: Minor | None = None
    due_on: date | None = None
    description: Name | None = None


class RepriceIn(In):
    term_fee_minor: Minor
    effective_on: date | None = None
    remarks: Note | None = None


class InvoicePeriodsIn(In):
    period_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=200)


class InvoicePeriodsOut(Out):
    invoice_id: UUID | None
    period_ids: list[UUID]


class FreezeIn(In):
    start_on: date | None = None
    end_on: date | None = None
    remarks: Note | None = None
    resume_invoice_mode: Literal["per_period", "single", "deferred"] | None = None


class SpanUpdate(In):
    end_on: date | None = None
    remarks: Note | None = None


class RemoveIn(In):
    removal_remarks: Note | None = None


class FreezeOut(Out):
    id: UUID
    membership_contract_id: UUID
    start_on: date
    end_on: date | None
    remarks: str | None
    extended_days_count: int
    resume_invoice_mode: str | None
    created_by_staff_user_id: UUID | None
    removed_at: datetime | None
    removal_remarks: str | None
    created_at: datetime


class SuspensionIn(In):
    start_on: date | None = None
    end_on: date | None = None
    fee_minor: Minor | None = None
    remarks: Note | None = None


class SuspensionOut(Out):
    id: UUID
    membership_contract_id: UUID
    start_on: date
    end_on: date | None
    fee_minor: int | None
    remarks: str | None
    created_by_staff_user_id: UUID | None
    past_due_invoice_id: UUID | None  # set when the non-payment rule suspended it (MEM-14)
    removed_at: datetime | None
    removal_remarks: str | None
    created_at: datetime


class RenewIn(In):
    renews_as_plan_id: UUID | None = None


class CancelQuoteIn(In):
    effective_on: date | None = None


class CancelQuoteOut(Out):
    effective_on: date
    is_full_reversal: bool
    periods_voided: list[UUID]
    periods_reversed: list[UUID]
    reversed_minor: int
    paid_on_reversed_minor: int
    current_period_id: UUID | None
    proposed_credit_minor: int
    max_credit_minor: int


class CancelIn(In):
    reason: Literal["voluntary", "upgrade", "downgrade", "administrative_error", "other"]
    effective_on: date | None = None
    remarks: Note | None = None
    credit_minor: Minor = 0
    is_refunded: bool = False
    cancel_bundled_packages: bool | None = None


class CancelRefundOut(Out):
    refund_id: UUID
    payment_id: UUID
    amount_minor: int
    status: str


class CancelOut(ContractOut):
    released_minor: int
    credit_minor: int
    refunds: list[CancelRefundOut]


class ShareIn(In):
    client_id: UUID


class MembershipShareOut(Out):
    id: UUID
    membership_contract_id: UUID
    client_id: UUID
    origin: str
    added_by_staff_user_id: UUID | None
    revoked_at: datetime | None
    created_at: datetime


class VisitOut(Out):
    id: UUID
    membership_contract_id: UUID
    client_id: UUID
    check_in_id: UUID
    location_id: UUID
    visited_at: datetime
    local_on: date
    is_counted: bool


class VisitAdjust(In):
    delta: Annotated[int, Field(ge=-1000, le=1000)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class StandingOut(Out):
    client_id: UUID
    is_member: bool
    status: Literal["active", "frozen", "suspended", "upcoming", "none"]
    reason: str | None
    contract_id: UUID | None
    via: Literal["owner", "share"] | None = None
    membership_name: str | None = None
    membership_type_id: UUID | None = None
    end_on: date | None = None
    max_visits_count: int | None = None
    visits_used_count: int | None = None
    visits_remaining_count: int | None = None


class UpcomingRenewalOut(Out):
    contract_id: UUID
    client_id: UUID
    location_id: UUID
    name: str
    end_on: date
    renew_on: date
    successor_contract_id: UUID | None
    next_name: str
    next_start_on: date
    next_term_fee_minor: int
    next_discount_pct: Decimal | None
    next_discount_minor: int | None


class ContractHistoryOut(Out):
    id: UUID
    occurred_at: datetime
    action: str
    actor_type: str
    actor_label: str
    changes: dict[str, Any]
    reason: str | None


class SystemAlertOut(Out):
    code: Literal["balance_due", "membership_expiring", "membership_expired", "waiver_missing"]
    severity: Literal["warning", "danger"]
    message: str
    on: date | None
    amount_minor: int | None
