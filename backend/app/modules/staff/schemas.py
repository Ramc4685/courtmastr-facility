"""Request and response models for the staff API (docs/api/openapi-money.yaml, tag staff)."""

from datetime import date, datetime
from decimal import Decimal
from ipaddress import IPv4Network, IPv6Network
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import In, Out, Page  # noqa: F401

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Note = Annotated[str, StringConstraints(max_length=2000)]
Minor = Annotated[int, Field(ge=0, le=10**10)]
Pct = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Basis = Literal["invoiced", "paid"]
Section = Literal["sessions", "commissions", "hourly"]


# --- payees ------------------------------------------------------------------------------------------------


class StaffPayeeOut(Out):
    id: UUID
    kind: Literal["trainer", "salesperson"]
    display_name: str
    location_id: UUID
    resource_id: UUID | None
    staff_user_id: UUID | None
    is_booking_alert_enabled: bool
    is_reminder_copy_enabled: bool
    is_active: bool
    tax_form_on_file_on: date | None = None


class StaffPayeeCreate(In):
    kind: Literal["trainer", "salesperson"]
    display_name: Name
    location_id: UUID
    staff_user_id: UUID | None = None
    resource_id: UUID | None = Field(None, description="Adopt an existing trainer resource instead of creating one")
    resource_group_id: UUID | None = Field(None, description="Schedule group for a new trainer column")
    is_booking_alert_enabled: bool = False
    is_reminder_copy_enabled: bool = False


class StaffPayeeUpdate(In):
    display_name: Name | None = None
    staff_user_id: UUID | None = None
    is_booking_alert_enabled: bool | None = None
    is_reminder_copy_enabled: bool | None = None
    is_active: bool | None = None


class PayRateOut(Out):
    id: UUID
    staff_payee_id: UUID
    reservation_type_id: UUID | None
    membership_type_id: UUID | None
    pay_basis: Literal["per_attendee", "per_session"]
    rate_60_minor: int
    rate_45_minor: int
    rate_30_minor: int
    comp_session_rate_minor: int
    session_commission_pct: Decimal
    program_instruction_rate_minor: int | None
    non_training_rate_minor: int | None
    floor_rate_minor: int | None


class PayRateWrite(In):
    pay_basis: Literal["per_attendee", "per_session"]
    rate_60_minor: Minor = 0
    rate_45_minor: Minor = 0
    rate_30_minor: Minor = 0
    comp_session_rate_minor: Minor = 0
    session_commission_pct: Pct = Decimal(0)
    program_instruction_rate_minor: Minor | None = None
    non_training_rate_minor: Minor | None = None
    floor_rate_minor: Minor | None = None


class BonusRuleIn(In):
    """`trained_hours` needs threshold_minutes; `off_hours` needs from_minute, to_minute (minutes after local
    midnight, up to 1440) and weekdays (0 = Monday). amount_minor is a flat bonus, or per hour for off hours."""

    kind: Literal["trained_hours", "off_hours"]
    amount_minor: Minor
    threshold_minutes: Annotated[int, Field(gt=0, le=100_000)] | None = None
    from_minute: Annotated[int, Field(ge=0, le=1439)] | None = None
    to_minute: Annotated[int, Field(ge=1, le=1440)] | None = None
    weekdays: Annotated[list[Annotated[int, Field(ge=0, le=6)]], Field(min_length=1, max_length=7)] | None = None

    @model_validator(mode="after")
    def _shape(self):
        window = (self.from_minute, self.to_minute, self.weekdays)
        if self.kind == "trained_hours":
            if self.threshold_minutes is None or any(v is not None for v in window):
                raise ValueError("A trained-hours bonus needs threshold_minutes and no window.")
        elif self.threshold_minutes is not None or any(v is None for v in window) or self.to_minute <= self.from_minute:
            raise ValueError("An off-hours bonus needs weekdays and a window that ends after it starts.")
        if self.weekdays is not None:
            self.weekdays = sorted(set(self.weekdays))
        return self


class BonusRuleOut(Out):
    id: UUID
    kind: Literal["trained_hours", "off_hours"]
    amount_minor: int
    threshold_minutes: int | None
    from_minute: int | None
    to_minute: int | None
    weekdays: list[int] | None


class BonusRulesPut(In):
    rules: Annotated[list[BonusRuleIn], Field(max_length=50)]


class BonusRuleSet(Out):
    staff_payee_id: UUID
    rules: list[BonusRuleOut]


class CommissionRuleIn(In):
    applies_to: Literal["package_sale", "session_completion", "membership_sale"]
    reservation_type_id: UUID | None = None
    membership_type_id: UUID | None = None
    commission_pct: Pct = Decimal(0)
    flat_minor: Minor = 0
    is_first_invoice_only: bool = False


class CommissionRuleOut(Out):
    id: UUID
    applies_to: str
    reservation_type_id: UUID | None
    membership_type_id: UUID | None
    commission_pct: Decimal
    flat_minor: int
    is_first_invoice_only: bool


class CommissionRulesPut(In):
    rules: Annotated[list[CommissionRuleIn], Field(max_length=200)]


class CommissionRuleSet(Out):
    staff_payee_id: UUID
    rules: list[CommissionRuleOut]


# --- job classifications, hourly rates, settings -----------------------------------------------------------


class JobClassificationOut(Out):
    id: UUID
    name: str
    is_active: bool


class JobClassificationCreate(In):
    name: Name


class JobClassificationUpdate(In):
    name: Name | None = None
    is_active: bool | None = None


class StaffHourlyRateOut(Out):
    id: UUID
    staff_user_id: UUID
    job_classification_id: UUID
    rate_minor: int
    effective_from_on: date


class StaffHourlyRateCreate(In):
    job_classification_id: UUID
    rate_minor: Minor
    effective_from_on: date


class StaffSettingsOut(Out):
    location_id: UUID | None
    is_override: bool
    is_time_clock_network_restricted: bool
    time_clock_networks: list[str]
    default_commission_basis: Basis
    pay_period: Literal["weekly", "biweekly", "semi_monthly", "monthly"]
    pay_period_anchor_on: date | None


class StaffSettingsWrite(In):
    is_time_clock_network_restricted: bool = False
    time_clock_networks: Annotated[list[IPv4Network | IPv6Network], Field(max_length=50)] = []
    default_commission_basis: Basis = "paid"
    pay_period: Literal["weekly", "biweekly", "semi_monthly", "monthly"] = "biweekly"
    pay_period_anchor_on: date | None = None


# --- time clock --------------------------------------------------------------------------------------------


class TimeEntryOut(Out):
    id: UUID
    staff_user_id: UUID
    location_id: UUID
    job_classification_id: UUID
    clock_in_at: datetime
    clock_out_at: datetime | None
    duration_minutes: int | None
    source: Literal["self", "manager"]
    edited_by_staff_user_id: UUID | None
    edit_reason: str | None
    voided_at: datetime | None


class TimeClockState(Out):
    open_entry: TimeEntryOut | None
    job_classifications: list[JobClassificationOut]
    is_network_allowed: bool


class ClockIn(In):
    location_id: UUID
    job_classification_id: UUID
    password: Password


class ClockOut(In):
    password: Password


class TimeEntryCreate(In):
    staff_user_id: UUID
    location_id: UUID
    job_classification_id: UUID
    clock_in_at: datetime
    clock_out_at: datetime
    edit_reason: Reason


class TimeEntryUpdate(In):
    job_classification_id: UUID | None = None
    clock_in_at: datetime | None = None
    clock_out_at: datetime | None = None
    edit_reason: Reason


class TimeEntryVoid(In):
    edit_reason: Reason


class TimeSummaryRow(Out):
    staff_user_id: UUID
    display_name: str
    job_classification_id: UUID
    location_id: UUID
    entry_count: int
    minutes: int
    pay_minor: int | None


# --- shifts ------------------------------------------------------------------------------------------------


class ShiftOut(Out):
    id: UUID
    staff_user_id: UUID
    location_id: UUID
    job_classification_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    status: Literal["draft", "published", "cancelled"]
    note: str | None


class MyShiftOut(Out):
    """A published shift as its assignee sees it: no manager note."""

    id: UUID
    location_id: UUID
    job_classification_id: UUID | None
    starts_at: datetime
    ends_at: datetime


class ShiftCreate(In):
    staff_user_id: UUID
    location_id: UUID
    job_classification_id: UUID | None = None
    starts_at: datetime
    ends_at: datetime
    note: Note | None = None


class ShiftUpdate(In):
    staff_user_id: UUID | None = None
    job_classification_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    note: Note | None = None


class ShiftPublish(In):
    shift_ids: Annotated[list[UUID], Field(max_length=500)] = []
    location_id: UUID | None = None
    starts_from: datetime | None = None
    starts_to: datetime | None = None


class ShiftPublishResult(Out):
    published_count: int


class ShiftCopy(In):
    location_id: UUID
    from_starts_on: date = Field(description="First local date of the seven days to copy")
    to_starts_on: date = Field(description="First local date of the seven days to copy onto")


class ShiftCopyResult(Out):
    copied_count: int
    skipped_count: int


class ShiftVarianceOut(Out):
    shift_id: UUID
    staff_user_id: UUID
    location_id: UUID
    display_name: str
    starts_at: datetime
    ends_at: datetime
    state: Literal["upcoming", "no_show", "short", "met"]
    scheduled_minutes: int
    worked_minutes: int
    variance_minutes: int
    first_in_at: datetime | None
    last_out_at: datetime | None


# --- instructors -------------------------------------------------------------------------------------------


class TrainerSessionOut(Out):
    booking_id: UUID
    session_id: UUID
    location_id: UUID
    reservation_type_id: UUID | None
    title: str
    starts_at: datetime
    ends_at: datetime
    status: str
    capacity: int
    booked_count: int


class InstructorAssign(In):
    staff_payee_id: UUID | None = Field(None, description="The trainer to teach the session; null removes them")


class SessionInstructorOut(Out):
    session_id: UUID
    booking_id: UUID
    staff_payee_id: UUID | None
    resource_ids: list[UUID]


# --- payroll -----------------------------------------------------------------------------------------------


class PayrollRunCreate(In):
    location_id: UUID | None = None
    period_starts_on: date
    period_ends_on: date
    commission_basis: Basis | None = None
    includes: Annotated[list[Section], Field(min_length=1, max_length=3)] = ["sessions", "commissions", "hourly"]
    scope_staff_payee_id: UUID | None = None


class PayrollRunOut(Out):
    id: UUID
    location_id: UUID | None
    period_starts_on: date
    period_ends_on: date
    commission_basis: Basis
    includes: list[str]
    scope_staff_payee_id: UUID | None
    status: Literal["draft", "calculating", "calculated", "finalized", "voided"]
    calculated_at: datetime | None
    finalized_at: datetime | None
    finalized_by_staff_user_id: UUID | None
    requested_by_staff_user_id: UUID
    total_minor: int
    statement_count: int
    created_at: datetime


class PayStatementLineOut(Out):
    id: UUID
    kind: str
    occurred_on: date
    source_type: str
    source_id: UUID
    reservation_type_id: UUID | None
    description: str
    quantity: Decimal
    rate_minor: int | None
    commission_pct: Decimal | None
    base_minor: int | None
    amount_minor: int
    was_paid_before: bool


class PayStatementOut(Out):
    id: UUID
    payroll_run_id: UUID
    staff_payee_id: UUID | None
    staff_user_id: UUID | None
    display_name: str
    session_pay_minor: int
    commission_minor: int
    bonus_minor: int
    hourly_pay_minor: int
    additional_income_minor: int
    additional_income_note: str | None
    total_minor: int


class PayStatementUpdate(In):
    additional_income_minor: Annotated[int, Field(ge=-(10**10), le=10**10)]
    additional_income_note: Annotated[str, StringConstraints(max_length=500)] | None = None


class PayrollExport(Out):
    filename: str
    content_type: str
    content: str


# --- coach revenue share (independent coaches) -------------------------------------------------------------------

EngagementKind = Literal["employee", "independent"]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class CoachEngagementOut(Out):
    id: UUID
    staff_payee_id: UUID
    engagement: EngagementKind
    effective_from_on: date


class CoachEngagementWrite(In):
    engagement: EngagementKind = Field(description="employee: a staff coach on payroll; independent: revenue share")
    effective_from_on: date


class CoachTaxFormWrite(In):
    tax_form_on_file_on: date | None = Field(
        description="When a tax form (for example a W-9) was received; null when none is on file. Never a tax id."
    )


class CoachShareRuleOut(Out):
    id: UUID
    staff_payee_id: UUID | None
    reservation_type_id: UUID | None
    effective_from_on: date
    coach_share_pct: Decimal
    court_fee_minor: int
    court_fee_basis: Literal["session", "hour"]
    court_fee_applies: Literal["before_split", "after_split"]


class CoachShareRuleWrite(In):
    staff_payee_id: UUID | None = Field(None, description="One coach; null for every independent coach")
    reservation_type_id: UUID | None = Field(None, description="One lesson or program type; null for all")
    effective_from_on: date
    coach_share_pct: Pct
    court_fee_minor: Minor = 0
    court_fee_basis: Literal["session", "hour"] = "session"
    court_fee_applies: Literal["before_split", "after_split"] = "before_split"


class CoachEarningOut(Out):
    id: UUID
    location_id: UUID
    staff_payee_id: UUID
    kind: Literal["lesson", "reversal", "adjustment"]
    earned_on: date
    source_type: Literal["enrollment", "booking"] | None
    source_id: UUID | None
    reservation_type_id: UUID | None
    description: str
    gross_minor: int
    facility_share_minor: int
    coach_share_minor: int
    coach_share_pct: Decimal | None = Field(description="Null unless you may read share rules")
    court_fee_minor: int | None = Field(description="Null unless you may read share rules")
    reverses_coach_earning_id: UUID | None
    reason: str | None
    coach_payout_id: UUID | None
    created_at: datetime


class CoachPayoutOut(Out):
    id: UUID
    location_id: UUID
    staff_payee_id: UUID
    coach_name: str
    period_starts_on: date
    period_ends_on: date
    status: Literal["draft", "approved", "paid"]
    line_count: int
    gross_minor: int
    facility_share_minor: int
    coach_share_minor: int
    adjustment_minor: int
    approved_at: datetime | None
    paid_at: datetime | None
    paid_on: date | None
    payment_method: Literal["bank_transfer", "cheque", "other"] | None
    payment_reference: str | None
    tax_form_on_file_on: date | None
    notice: str = Field(description="The software moves no money; this is a record of what is owed and paid")


class CoachPayoutList(Out):
    data: list[CoachPayoutOut]


class CoachPayoutCreate(In):
    location_id: UUID
    period_starts_on: date
    period_ends_on: date
    staff_payee_id: UUID | None = Field(None, description="One coach; omit for every independent coach here")


class CoachAdjustmentCreate(In):
    amount_minor: Annotated[int, Field(ge=-(10**10), le=10**10, description="Positive raises the coach's share")]
    reason: Reason


class CoachPayoutPaid(In):
    paid_on: date
    payment_method: Literal["bank_transfer", "cheque", "other"]
    payment_reference: Reference | None = Field(None, description="Transfer or cheque reference, staff-typed")
