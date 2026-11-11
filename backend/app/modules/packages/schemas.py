"""Request and response models for the packages API (docs/api/openapi-people.yaml, tag packages)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Minor = Annotated[int, Field(ge=0, le=10**12)]
Pct = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
Count = Annotated[int, Field(ge=1, le=10000)]
Lead = Annotated[int, Field(ge=0, le=1000)]
Unit = Literal["day", "week", "month", "year"]
TenderKind = Literal["card", "bank_debit", "cash", "cheque", "bank_transfer", "gift_card", "external", "other"]
Status = Literal["active", "exhausted", "expired", "removed"]


class PackagePlanCreate(In):
    kind: Literal["standard", "recurring"] = "standard"
    reservation_type_id: UUID
    name: Name
    invoice_description: Note | None = None
    internal_remarks: Note | None = None
    session_mode: Literal["single", "fixed", "range", "unlimited"]
    session_count: Count | None = None
    min_session_count: Count | None = None
    max_session_count: Count | None = None
    pricing_category: Literal["paid", "free"] = "paid"
    is_complimentary: bool = False
    fee_minor: Minor | None = None
    fee_basis: Literal["per_session", "per_package"] | None = None
    start_rule: Literal["sale_date", "fixed_date"] = "sale_date"
    fixed_start_on: date | None = None
    validity_count: Count | None = None
    validity_unit: Unit | None = None
    allows_booking_after_expiry: bool = False
    auto_renew_lead_count: Lead | None = None
    auto_renew_lead_unit: Unit | None = None
    renewal_target: Literal["same_terms", "plan"] = "same_terms"
    renews_as_plan_id: UUID | None = None
    renewal_threshold_count: Lead | None = None
    is_auto_renew_on_threshold: bool = False
    share_mode: Literal["none", "all_related"] = "none"
    recurrence_unit: Unit | None = None
    recurrence_interval_count: Count | None = None
    recurrence_occurrences_count: Count | None = None
    is_series_auto_renew: bool = False
    default_invoice_mode: Literal["ask", "single", "per_period", "deferred"] = "ask"
    is_autopay_default: bool = False
    online_sale_mode: Literal["off", "balance_allowed", "paid_in_full"] = "off"
    is_members_only_online: bool = False
    is_members_only_at_desk: bool = False
    discount_pct: Pct | None = None
    discount_minor: Minor | None = None
    revenue_category_id: UUID | None = None
    sort_order: int = 0
    is_active: bool = True


class PackagePlanUpdate(In):
    name: Name | None = None
    invoice_description: Note | None = None
    internal_remarks: Note | None = None
    session_mode: Literal["single", "fixed", "range", "unlimited"] | None = None
    session_count: Count | None = None
    min_session_count: Count | None = None
    max_session_count: Count | None = None
    pricing_category: Literal["paid", "free"] | None = None
    is_complimentary: bool | None = None
    fee_minor: Minor | None = None
    fee_basis: Literal["per_session", "per_package"] | None = None
    start_rule: Literal["sale_date", "fixed_date"] | None = None
    fixed_start_on: date | None = None
    validity_count: Count | None = None
    validity_unit: Unit | None = None
    allows_booking_after_expiry: bool | None = None
    auto_renew_lead_count: Lead | None = None
    auto_renew_lead_unit: Unit | None = None
    renewal_target: Literal["same_terms", "plan"] | None = None
    renews_as_plan_id: UUID | None = None
    renewal_threshold_count: Lead | None = None
    is_auto_renew_on_threshold: bool | None = None
    share_mode: Literal["none", "all_related"] | None = None
    recurrence_unit: Unit | None = None
    recurrence_interval_count: Count | None = None
    recurrence_occurrences_count: Count | None = None
    is_series_auto_renew: bool | None = None
    default_invoice_mode: Literal["ask", "single", "per_period", "deferred"] | None = None
    is_autopay_default: bool | None = None
    online_sale_mode: Literal["off", "balance_allowed", "paid_in_full"] | None = None
    is_members_only_online: bool | None = None
    is_members_only_at_desk: bool | None = None
    discount_pct: Pct | None = None
    discount_minor: Minor | None = None
    revenue_category_id: UUID | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class PackagePlanOut(Out):
    id: UUID
    kind: str
    reservation_type_id: UUID
    name: str
    invoice_description: str | None
    internal_remarks: str | None
    session_mode: str
    session_count: int | None
    min_session_count: int | None
    max_session_count: int | None
    pricing_category: str
    is_complimentary: bool
    fee_minor: int | None
    fee_basis: str | None
    start_rule: str
    fixed_start_on: date | None
    validity_count: int | None
    validity_unit: str | None
    allows_booking_after_expiry: bool
    auto_renew_lead_count: int | None
    auto_renew_lead_unit: str | None
    renewal_target: str
    renews_as_plan_id: UUID | None
    renewal_threshold_count: int | None
    is_auto_renew_on_threshold: bool
    share_mode: str
    recurrence_unit: str | None
    recurrence_interval_count: int | None
    recurrence_occurrences_count: int | None
    is_series_auto_renew: bool
    default_invoice_mode: str
    is_autopay_default: bool
    online_sale_mode: str
    is_members_only_online: bool
    is_members_only_at_desk: bool
    discount_pct: Decimal | None
    discount_minor: int | None
    revenue_category_id: UUID | None
    sort_order: int
    is_active: bool
    version: int


class PortalPackagePlanOut(Out):
    id: UUID
    kind: str
    reservation_type_id: UUID
    name: str
    invoice_description: str | None
    session_mode: str
    session_count: int | None
    min_session_count: int | None
    max_session_count: int | None
    pricing_category: str
    fee_minor: int | None
    fee_basis: str | None
    validity_count: int | None
    validity_unit: str | None
    recurrence_unit: str | None
    recurrence_interval_count: int | None
    recurrence_occurrences_count: int | None
    online_sale_mode: str
    is_members_only_online: bool
    is_purchasable: bool
    discount_pct: Decimal | None
    discount_minor: int | None


class PackageSettingsUpdate(In):
    is_late_cancel_charged: bool | None = None
    is_no_show_charged: bool | None = None
    is_account_credit_applied_by_default: bool | None = None
    expiry_notice_days: Annotated[int, Field(ge=0, le=365)] | None = None


class PackageSettingsOut(Out):
    is_late_cancel_charged: bool
    is_no_show_charged: bool
    is_account_credit_applied_by_default: bool
    expiry_notice_days: int


class SalePayment(In):
    amount_minor: Annotated[int, Field(gt=0, le=10**12)]
    tender_kind: TenderKind
    # An opaque provider reference from the provider's hosted fields. Card and bank numbers never reach us.
    method_token: Annotated[str, StringConstraints(max_length=200)] | None = None
    external_reference: Annotated[str, StringConstraints(max_length=500)] | None = None
    memo: Annotated[str, StringConstraints(max_length=500)] | None = None


class PackageQuote(In):
    client_id: UUID
    location_id: UUID
    package_plan_id: UUID
    quantity: Count | None = None  # sessions, for a plan sold in a min/max range
    start_on: date | None = None


class PackageGrant(PackageQuote):
    internal_remarks: Note | None = None


class PackageSell(PackageGrant):
    invoice_mode: Literal["single", "per_period", "deferred"] | None = None
    sold_by_staff_user_id: UUID | None = None
    payment: SalePayment | None = None


class PortalPackageBuy(In):
    package_plan_id: UUID
    location_id: UUID
    client_id: UUID | None = None  # who the package is for; default: the signed-in client
    quantity: Count | None = None
    tender_kind: Literal["card", "bank_debit"] = "card"
    method_token: Annotated[str, StringConstraints(max_length=200)] | None = None


class PackageQuoteOut(Out):
    name: str
    is_unlimited: bool
    sessions_granted_count: int
    price_minor: int
    unit_price_minor: int | None
    valid_from_on: date
    valid_until_on: date | None
    occurrences_count: int | None
    is_member_required: bool
    is_member: bool
    requirements: list[dict[str, Any]]


class PortalPackageOut(Out):
    """What a member sees: balances and dates, no internal remarks or staff attribution."""

    id: UUID
    owner_client_id: UUID
    location_id: UUID
    package_plan_id: UUID | None
    package_series_id: UUID | None
    reservation_type_id: UUID
    name: str
    is_unlimited: bool
    sessions_granted_count: int
    sessions_reserved_count: int
    sessions_consumed_count: int
    sessions_forfeited_count: int
    sessions_available_count: int | None
    valid_from_on: date
    valid_until_on: date | None
    allows_booking_after_expiry: bool
    price_minor: int
    is_auto_renew: bool
    renew_on: date | None
    is_renewal_due: bool
    share_count: int
    status: Status


class PackageOut(PortalPackageOut):
    series_sequence_number: int | None
    invoice_description: str | None
    internal_remarks: str | None
    fee_basis: str | None
    unit_price_minor: int | None
    is_complimentary: bool
    revenue_category_id: UUID | None
    invoice_mode: str
    charge_id: UUID | None
    is_autopay: bool
    share_mode: str
    auto_renew_lead_count: int | None
    auto_renew_lead_unit: str | None
    renewal_target: str
    renews_as_plan_id: UUID | None
    renewal_threshold_count: int | None
    is_auto_renew_on_threshold: bool
    renewal_flagged_at: datetime | None
    auto_renew_disabled_by: str | None
    previous_package_id: UUID | None
    source_contract_id: UUID | None
    sold_by_staff_user_id: UUID | None
    sales_channel: str
    client_document_id: UUID | None
    removed_at: datetime | None
    removal_mode: str | None
    version: int
    created_at: datetime


class PackageSaleOut(PackageOut):
    invoice_id: UUID | None
    payment_id: UUID | None
    payment_status: str | None


class PortalPackageSaleOut(PortalPackageOut):
    invoice_id: UUID | None
    payment_id: UUID | None
    payment_status: str | None


class PackageUpdate(In):
    valid_until_on: date | None = None
    allows_booking_after_expiry: bool | None = None
    internal_remarks: Note | None = None
    is_auto_renew: bool | None = None
    auto_renew_lead_count: Lead | None = None
    auto_renew_lead_unit: Unit | None = None
    renews_as_plan_id: UUID | None = None
    renewal_threshold_count: Lead | None = None
    is_auto_renew_on_threshold: bool | None = None


class CreditAdjust(In):
    delta: Annotated[int, Field(ge=-10000, le=10000)]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class CreditLedgerEntryOut(Out):
    id: UUID
    client_package_id: UUID
    client_id: UUID
    entry_type: Literal["grant", "reserve", "release", "consume", "restore", "forfeit", "adjust"]
    granted_delta: int
    reserved_delta: int
    consumed_delta: int
    forfeited_delta: int
    reason: str
    source_type: str | None
    source_id: UUID | None
    actor_type: str
    actor_id: UUID | None
    note: str | None
    occurred_at: datetime


class PortalCreditLedgerEntryOut(Out):
    """The portal view of a credit movement: no staff note, actor, source or client id (P-11)."""

    id: UUID
    client_package_id: UUID
    entry_type: Literal["grant", "reserve", "release", "consume", "restore", "forfeit", "adjust"]
    granted_delta: int
    reserved_delta: int
    consumed_delta: int
    forfeited_delta: int
    reason: str
    occurred_at: datetime


class ShareIn(In):
    client_id: UUID


class PackageShareOut(Out):
    id: UUID
    client_package_id: UUID
    client_id: UUID
    origin: str
    added_by_staff_user_id: UUID | None
    revoked_at: datetime | None
    created_at: datetime


class RemovalQuoteOut(Out):
    sessions_consumed_count: int
    open_reservations_count: int
    sessions_forfeited_on_removal_count: int
    charge_id: UUID | None
    charge_total_minor: int
    paid_minor: int
    can_reverse_billing: bool


class PackageRemove(In):
    removal_mode: Literal["billing_reversed", "billing_kept"]


class PortalPackageSeriesOut(Out):
    id: UUID
    package_plan_id: UUID
    occurrences_total_count: int
    occurrences_generated_count: int
    next_period_start_on: date | None
    is_auto_renew: bool
    status: Literal["active", "completed", "cancelled"]


class PackageSeriesOut(Out):
    id: UUID
    owner_client_id: UUID
    package_plan_id: UUID
    location_id: UUID
    occurrences_total_count: int
    occurrences_generated_count: int
    next_period_start_on: date | None
    invoice_mode: str
    is_auto_renew: bool
    status: Literal["active", "completed", "cancelled"]
    created_at: datetime
