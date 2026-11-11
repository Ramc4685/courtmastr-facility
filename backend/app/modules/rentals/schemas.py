"""Request and response models of the rentals context (docs/api/openapi-core.yaml, tag rentals)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401
from app.modules.scheduling.schemas import (
    Buffer,
    Color,
    OccurrenceResult,
    OnConflict,
    RecurrenceRule,
    Resources,
    SeriesScope,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Text = Annotated[str, StringConstraints(max_length=4000)]
Money = Annotated[int, Field(ge=0, le=100_000_000)]
Pct = Annotated[Decimal, Field(gt=0, le=100, decimal_places=2)]
Wall24 = Annotated[str, StringConstraints(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")]
Basis = Literal["per_hour", "per_occurrence", "flat"]
Grouping = Literal["combined", "per_resource", "per_occurrence", "per_resource_occurrence"]
RoutingKind = Literal["new_single", "new_per_line", "date_based", "existing_open", "cart"]
ChargeStateKind = Literal["unbilled", "no_charge", "billed", "plan_covered"]


# --- types --------------------------------------------------------------------------------------------------


class _TypeFields(In):
    name: Name | None = None
    revenue_category_id: UUID | None = None
    color: Color | None = None
    sort_order: int | None = None
    buffer_before_min: Buffer | None = None
    buffer_after_min: Buffer | None = None
    access: Literal["staff_only", "self_service"] | None = None
    online_rental_rate_id: UUID | None = None
    eligibility: Literal["everyone", "active_members", "paid_up_members"] | None = None
    online_payment_mode: Literal["pay_in_full", "pay_later"] | None = None
    min_lead_min: Annotated[int, Field(ge=0, le=525_600)] | None = None
    default_length_min: Annotated[int, Field(ge=15, le=1440)] | None = None
    min_length_min: Annotated[int, Field(ge=15, le=1440)] | None = None
    max_length_min: Annotated[int, Field(ge=15, le=1440)] | None = None
    slot_granularity_min: Literal[15, 30, 60] | None = None
    online_description: Text | None = None
    deposit_pct: Pct | None = None
    cancel_cutoff_hours: Annotated[int, Field(ge=1, le=8760)] | None = None
    late_cancel_fee_pct: Pct | None = None
    is_active: bool | None = None
    resource_ids: Annotated[list[UUID], Field(max_length=200)] | None = None
    rental_plan_ids: Annotated[list[UUID], Field(max_length=200)] | None = None


class RentalTypeCreate(_TypeFields):
    location_id: UUID
    name: Name
    revenue_category_id: UUID


class RentalTypeUpdate(_TypeFields):
    """`access = self_service` requires online_rental_rate_id and at least one resource (422)."""


class RentalTypeOut(Out):
    id: UUID
    location_id: UUID
    name: str
    revenue_category_id: UUID
    color: str | None
    sort_order: int
    buffer_before_min: int
    buffer_after_min: int
    access: str
    online_rental_rate_id: UUID | None
    eligibility: str
    online_payment_mode: str
    min_lead_min: int
    default_length_min: int | None
    min_length_min: int
    max_length_min: int | None
    slot_granularity_min: int
    online_description: str | None
    deposit_pct: Decimal | None
    cancel_cutoff_hours: int | None
    late_cancel_fee_pct: Decimal | None
    is_active: bool
    resource_ids: list[UUID] = []
    rental_plan_ids: list[UUID] = []


# --- rates --------------------------------------------------------------------------------------------------


class RateRule(In):
    kind: Literal["rate", "discount"]
    name: Annotated[str, StringConstraints(max_length=120)] | None = None
    sort_order: int = 0
    start_time: Wall24 | None = None
    end_time: Wall24 | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    weekdays: Annotated[list[Annotated[int, Field(ge=1, le=7)]], Field(min_length=1, max_length=7)] | None = None
    membership_type_id: UUID | None = None
    amount_minor: Money | None = None
    discount_pct: Pct | None = None
    discount_minor: Annotated[int, Field(gt=0, le=100_000_000)] | None = None


class RateRuleOut(Out):
    id: UUID
    kind: str
    name: str
    sort_order: int
    start_time: str | None
    end_time: str | None
    starts_on: date | None
    ends_on: date | None
    weekdays: list[int] | None
    membership_type_id: UUID | None
    amount_minor: int | None
    discount_pct: Decimal | None
    discount_minor: int | None


class RentalRateWrite(In):
    """Create requires name, amount_minor, basis. `rules` and `tax_ids` are replaced as whole sets."""

    name: Name | None = None
    internal_note: Text | None = None
    amount_minor: Money | None = None
    member_amount_minor: Money | None = None
    basis: Basis | None = None
    multi_resource_mode: Literal["once", "per_resource"] | None = None
    line_grouping: Grouping | None = None
    tax_ids: Annotated[list[UUID], Field(max_length=10)] | None = None
    rules: Annotated[list[RateRule], Field(max_length=50)] | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class RentalRateOut(Out):
    id: UUID
    rental_type_id: UUID
    name: str
    internal_note: str | None
    amount_minor: int
    member_amount_minor: int | None
    basis: str
    multi_resource_mode: str
    line_grouping: str
    tax_ids: list[UUID] = []
    rules: list[RateRuleOut] = []
    sort_order: int
    is_active: bool


# --- quotes, rentals ----------------------------------------------------------------------------------------


class CustomRate(In):
    """Needs rentals.booking.override_rate."""

    description: Name
    unit_amount_minor: Money
    basis: Basis
    tax_ids: Annotated[list[UUID], Field(max_length=10)] | None = None


class ChargeDecision(In):
    """bill needs rental_rate_id or custom_rate; plan needs rental_plan_purchase_id. Maps to charge_state."""

    decision: Literal["bill", "unbilled", "no_charge", "plan"]
    rental_rate_id: UUID | None = None
    custom_rate: CustomRate | None = None
    line_grouping: Literal["combined", "per_occurrence"] | None = None
    discount_minor: Money = 0
    tax_ids: Annotated[list[UUID], Field(max_length=10)] | None = None
    rental_plan_purchase_id: UUID | None = None
    invoice_routing: RoutingKind = "new_single"
    routing_period: Literal["week", "month"] | None = None
    existing_invoice_id: UUID | None = None
    revenue_on: date | None = None


class PartyInput(In):
    client_id: UUID
    is_charged: bool = False


class RentalCreate(In):
    location_id: UUID
    rental_type_id: UUID
    client_id: UUID
    parties: Annotated[list[PartyInput], Field(max_length=10)] = []
    resources: Resources
    starts_at: datetime
    ends_at: datetime
    title: Annotated[str, StringConstraints(max_length=200)] | None = None
    notes: Text | None = None
    buffer_before_min: Buffer | None = None
    buffer_after_min: Buffer | None = None
    recurrence: RecurrenceRule | None = None
    charge: ChargeDecision
    on_conflict: OnConflict = "abort"
    override_policy: bool = False


class QuoteLine(Out):
    description: str
    rental_rate_id: UUID | None
    basis: str
    quantity: Decimal
    unit_amount_minor: int
    discount_minor: int
    amount_minor: int
    tax_minor: int
    resource_id: UUID | None
    occurrence_index: int | None
    applied_rule_id: UUID | None
    is_member_price: bool


class Quote(Out):
    """Output of the deterministic pricing function; identical inputs give identical lines (RNT-02)."""

    lines: list[QuoteLine]
    subtotal_minor: int
    discount_minor: int
    tax_minor: int
    total_minor: int
    deposit_minor: int
    currency: str


class RentalPreview(Out):
    occurrences: list[OccurrenceResult]
    requested_count: int
    conflict_count: int
    quote: Quote | None


class PartyOut(Out):
    client_id: UUID
    is_charged: bool


class RentalResourceOut(Out):
    resource_id: UUID
    role: str


class RentalOut(Out):
    """One rental occurrence (rental_booking 1:1 booking). Status, times and version come from the booking."""

    id: UUID
    location_id: UUID
    booking_id: UUID
    booking_number: int
    booking_series_id: UUID | None
    rental_type_id: UUID
    client_id: UUID
    parties: list[PartyOut]
    resources: list[RentalResourceOut]
    starts_at: datetime
    ends_at: datetime
    status: str
    expires_at: datetime | None
    charge_state: str
    booked_via: str
    cancelled_at: datetime | None
    amount_minor: int | None
    charge_ids: list[UUID]
    invoice_ids: list[UUID]
    is_on_public_schedule: bool
    title: str
    version: int


class RentalCreated(Out):
    rental: RentalOut | None
    booking_series_id: UUID | None
    created_count: int
    conflict_count: int
    results: list[OccurrenceResult] = []
    quote: Quote | None = None
    invoice_ids: list[UUID] = []
    status_url: str | None = None


class BillSelected(In):
    """Price any set of unbilled occurrences of one payer and route the lines (RNT-04)."""

    rental_ids: Annotated[list[UUID], Field(min_length=1, max_length=500)]
    charge: ChargeDecision
    preview: bool = False


class Billed(Out):
    quote: Quote
    rentals: list[RentalOut]
    invoice_ids: list[UUID]


class Extension(In):
    """Add more occurrences to the rental's series (RNT-04): same type, client and resources unless given."""

    start_on: date
    start_time: Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
    end_time: Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
    end_day_offset: Annotated[int, Field(ge=0, le=6)] = 0
    rule: RecurrenceRule
    resources: Resources | None = None
    on_conflict: OnConflict = "abort"
    preview: bool = False


class Extended(Out):
    booking_series_id: UUID
    created_count: int
    conflict_count: int
    results: list[OccurrenceResult] = []
    preview: dict | None = None
    status_url: str | None = None


class RentalCancel(In):
    """Unpaid charge shares are always reversed; paid money becomes account credit (`credit_account`) unless
    `keep_charge`. Plan-covered occurrences always get the balance back. Inside the type's cancellation window
    a late-cancel fee is posted unless `waive_late_fee` (needs rentals.booking.override_rate)."""

    scope: SeriesScope | None = None
    reason: Literal["staff", "client", "other"] = "staff"
    note: Annotated[str, StringConstraints(max_length=500)] | None = None
    charge_action: Literal["credit_account", "keep_charge"] = "credit_account"
    waive_late_fee: bool = False


class RentalCancelResult(Out):
    cancelled_count: int
    reversed_minor: int
    reposted_minor: int
    late_fee_minor: int
    plan_quantity_returned: Decimal
    rentals: list[RentalOut]


class PublicSchedule(In):
    is_on_public_schedule: bool


# --- online ------------------------------------------------------------------------------------------------


class PublicRentalType(Out):
    id: UUID
    location_id: UUID
    name: str
    online_description: str | None
    eligibility: str
    online_payment_mode: str
    min_lead_min: int
    default_length_min: int | None
    min_length_min: int
    max_length_min: int | None
    slot_granularity_min: int
    deposit_pct: Decimal | None
    cancel_cutoff_hours: int | None
    late_cancel_fee_pct: Decimal | None
    resources: list[dict]
    from_price_minor: int


class RentalSlot(Out):
    starts_at: datetime
    ends_at: datetime
    resource_id: UUID
    resource_name: str
    price_minor: int
    is_member_price: bool


class PortalRentalCreate(In):
    rental_type_id: UUID
    client_id: UUID
    resource_id: UUID
    starts_at: datetime
    ends_at: datetime
    rental_plan_purchase_id: UUID | None = None


class PortalRentalConfirm(In):
    """A PaymentProvider client token; never raw card data. Stored methods arrive with build module 8."""

    provider_payment_token: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class RentalCheckout(Out):
    rental: RentalOut
    quote: Quote
    expires_at: datetime | None
    invoice_id: UUID | None
    payment_required: bool
    amount_due_minor: int
    payment_status: str | None = None


# --- plans -------------------------------------------------------------------------------------------------


class _PlanFields(In):
    name: Name | None = None
    rental_type_id: UUID | None = None
    model: Literal["per_hour", "per_occurrence"] | None = None
    quantity: Annotated[Decimal, Field(gt=0, le=100000, decimal_places=2)] | None = None
    is_unlimited: bool | None = None
    price_minor: Money | None = None
    member_price_minor: Money | None = None
    is_flat_rate: bool | None = None
    revenue_category_id: UUID | None = None
    internal_description: Text | None = None
    client_description: Text | None = None
    is_members_only: bool | None = None
    is_sold_online: bool | None = None
    start_mode: Literal["sale_date", "fixed_date"] | None = None
    fixed_starts_on: date | None = None
    validity_days: Annotated[int, Field(ge=1, le=3660)] | None = None
    fixed_expires_on: date | None = None
    default_invoice_routing: Literal["new_single", "new_per_line", "cart"] | None = None
    is_shareable: bool | None = None


class RentalPlanCreate(_PlanFields):
    location_id: UUID
    name: Name
    rental_type_id: UUID
    model: Literal["per_hour", "per_occurrence"]
    price_minor: Money
    revenue_category_id: UUID


class RentalPlanUpdate(_PlanFields):
    status: Literal["active", "archived"] | None = None


class RentalPlanOut(Out):
    id: UUID
    location_id: UUID
    name: str
    rental_type_id: UUID
    model: str
    quantity: Decimal | None
    is_unlimited: bool
    price_minor: int
    member_price_minor: int | None
    is_flat_rate: bool
    revenue_category_id: UUID
    internal_description: str | None
    client_description: str | None
    is_members_only: bool
    is_sold_online: bool
    start_mode: str
    fixed_starts_on: date | None
    validity_days: int | None
    fixed_expires_on: date | None
    default_invoice_routing: str
    is_shareable: bool
    status: str


class PlanSale(In):
    rental_plan_id: UUID
    client_id: UUID
    quantity_total: Annotated[Decimal, Field(gt=0, le=100000, decimal_places=2)] | None = None
    invoice_routing: Literal["new_single", "cart"] | None = None


class PurchaseOut(Out):
    id: UUID
    location_id: UUID
    rental_plan_id: UUID
    client_id: UUID
    status: str
    model: str
    quantity_total: Decimal | None
    balance: Decimal | None
    price_minor: int
    charge_id: UUID | None
    sold_via: str
    starts_on: date
    expires_on: date | None
    cancelled_at: datetime | None
    cancel_mode: str | None
    invoice_id: UUID | None = None


class RentalPlanLedgerEntryOut(Out):
    id: UUID
    entry_type: str
    quantity: Decimal
    balance_after: Decimal | None
    rental_booking_id: UUID | None
    used_by_client_id: UUID | None
    note: str | None
    created_at: datetime


class PurchaseCancel(In):
    cancel_mode: Literal["reverse_billing", "keep_billing"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
