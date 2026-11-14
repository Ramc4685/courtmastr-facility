"""staff tables (docs/architecture/data-model-money.md section 4).

Deviations, recorded in the module README: the time-clock network allow-list is a column on `staff_settings`
(no `location_network` table exists), and `pay_statement_line` carries no `client_id` (no client reference, so
payroll snapshots need no merge or erasure handler).
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Integer, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, INET, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk

_Pct = Numeric(5, 2)


class PayeeKind(StrEnum):
    TRAINER = "trainer"
    SALESPERSON = "salesperson"


class PayBasis(StrEnum):
    PER_ATTENDEE = "per_attendee"
    PER_SESSION = "per_session"


class CommissionTarget(StrEnum):
    PACKAGE_SALE = "package_sale"
    SESSION_COMPLETION = "session_completion"
    MEMBERSHIP_SALE = "membership_sale"


class CommissionBasis(StrEnum):
    INVOICED = "invoiced"
    PAID = "paid"


class PayPeriod(StrEnum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    SEMI_MONTHLY = "semi_monthly"
    MONTHLY = "monthly"


class BonusKind(StrEnum):
    TRAINED_HOURS = "trained_hours"
    OFF_HOURS = "off_hours"


class EntrySource(StrEnum):
    SELF = "self"
    MANAGER = "manager"


class ShiftStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    DRAFT = "draft"
    CALCULATING = "calculating"
    CALCULATED = "calculated"
    FINALIZED = "finalized"
    VOIDED = "voided"


class LineKind(StrEnum):
    SESSION = "session"
    COMP_SESSION = "comp_session"
    SESSION_COMMISSION = "session_commission"
    PROGRAM_INSTRUCTION = "program_instruction"
    NON_TRAINING = "non_training"
    FLOOR = "floor"
    TRAINED_HOURS_BONUS = "trained_hours_bonus"
    OFF_HOURS_BONUS = "off_hours_bonus"
    PACKAGE_SALE_COMMISSION = "package_sale_commission"
    MEMBERSHIP_SALE_COMMISSION = "membership_sale_commission"
    SESSION_COMPLETION_COMMISSION = "session_completion_commission"
    HOURLY = "hourly"


class StaffPayee(TenantOwned, Timestamps, Base):
    """One row for trainers and salespeople, so "sold by" resolves through one column (STF-01, STF-05)."""

    __tablename__ = "staff_payee"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("resource_id", "resource", index=False),
        *tfk("staff_user_id", "staff_user", index=False),
        enum_check("kind", PayeeKind),
        CheckConstraint("(kind = 'trainer') = (resource_id IS NOT NULL)", name="resource"),
        CheckConstraint("kind <> 'salesperson' OR staff_user_id IS NOT NULL", name="salesperson_user"),
        CheckConstraint("btrim(display_name) <> ''", name="display_name"),
        Index("uq_staff_payee_resource", "tenant_id", "resource_id", unique=True,
              postgresql_where=text("resource_id IS NOT NULL")),
        Index("uq_staff_payee_staff_user", "tenant_id", "staff_user_id", unique=True,
              postgresql_where=text("staff_user_id IS NOT NULL")),
    )  # fmt: skip

    kind: Mapped[str] = enum_column()
    display_name: Mapped[str] = mapped_column(info={"audit": "value"})
    location_id: Mapped[UUID]
    resource_id: Mapped[UUID | None]
    staff_user_id: Mapped[UUID | None]
    is_booking_alert_enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    is_reminder_copy_enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    # Compliance placeholder (coach share): the date a W-9 or similar form was received, null = none on file.
    # Never a tax identifier.
    tax_form_on_file_on: Mapped[date | None]


class PayRate(TenantOwned, Timestamps, Base):
    """Trainer session pay: one default row plus override rows for one reservation type or one membership type
    (STF-02, STF-03)."""

    __tablename__ = "pay_rate"
    __table_args__ = tenant_args(
        *tfk("staff_payee_id", "staff_payee", ondelete="CASCADE", index=False),
        *tfk("reservation_type_id", "reservation_type"),
        *tfk("membership_type_id", "membership_type"),
        enum_check("pay_basis", PayBasis),
        UniqueConstraint("tenant_id", "staff_payee_id", "reservation_type_id", "membership_type_id", name="uq_pay_rate",
                         postgresql_nulls_not_distinct=True),
        CheckConstraint("num_nonnulls(reservation_type_id, membership_type_id) <= 1", name="one_override"),
        CheckConstraint(
            "(reservation_type_id IS NULL AND membership_type_id IS NULL) OR (program_instruction_rate_minor IS NULL"
            " AND non_training_rate_minor IS NULL AND floor_rate_minor IS NULL)", name="flat_default",
        ),
        CheckConstraint(
            "rate_60_minor >= 0 AND rate_45_minor >= 0 AND rate_30_minor >= 0 AND comp_session_rate_minor >= 0"
            " AND session_commission_pct BETWEEN 0 AND 100", name="amounts",
        ),
    )  # fmt: skip

    staff_payee_id: Mapped[UUID]
    reservation_type_id: Mapped[UUID | None]
    membership_type_id: Mapped[UUID | None]
    pay_basis: Mapped[str] = enum_column()
    rate_60_minor: Mapped[int] = mapped_column(server_default=text("0"))
    rate_45_minor: Mapped[int] = mapped_column(server_default=text("0"))
    rate_30_minor: Mapped[int] = mapped_column(server_default=text("0"))
    comp_session_rate_minor: Mapped[int] = mapped_column(server_default=text("0"))
    session_commission_pct: Mapped[Decimal] = mapped_column(_Pct, server_default=text("0"))
    program_instruction_rate_minor: Mapped[int | None]
    non_training_rate_minor: Mapped[int | None]
    floor_rate_minor: Mapped[int | None]


class BonusRule(TenantOwned, Timestamps, Base):
    """A trainer's bonus (STF-04). `trained_hours`: a flat `amount_minor` once trained time in the pay period
    reaches `threshold_minutes`. `off_hours`: `amount_minor` extra per hour of session time inside the window
    (minutes after local midnight, `to_minute` up to 1440) on the listed weekdays (0 = Monday)."""

    __tablename__ = "bonus_rule"
    __table_args__ = tenant_args(
        *tfk("staff_payee_id", "staff_payee", ondelete="CASCADE"),
        enum_check("kind", BonusKind),
        CheckConstraint("amount_minor >= 0", name="amount"),
        CheckConstraint(
            "(kind = 'trained_hours' AND threshold_minutes > 0 AND from_minute IS NULL AND to_minute IS NULL"
            " AND weekdays IS NULL) OR (kind = 'off_hours' AND threshold_minutes IS NULL AND from_minute >= 0"
            " AND to_minute <= 1440 AND to_minute > from_minute AND cardinality(weekdays) > 0"
            " AND weekdays <@ ARRAY[0,1,2,3,4,5,6])", name="shape",
        ),
    )  # fmt: skip

    staff_payee_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    threshold_minutes: Mapped[int | None]
    from_minute: Mapped[int | None]
    to_minute: Mapped[int | None]
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    amount_minor: Mapped[int]


class CommissionRule(TenantOwned, Timestamps, Base):
    """Sales and session-completion commission for a payee, most specific row wins (STF-02, STF-05, STF-10)."""

    __tablename__ = "commission_rule"
    __table_args__ = tenant_args(
        *tfk("staff_payee_id", "staff_payee", ondelete="CASCADE", index=False),
        *tfk("reservation_type_id", "reservation_type"),
        *tfk("membership_type_id", "membership_type"),
        enum_check("applies_to", CommissionTarget),
        UniqueConstraint(
            "tenant_id", "staff_payee_id", "applies_to", "reservation_type_id", "membership_type_id",
            name="uq_commission_rule", postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "(membership_type_id IS NULL OR applies_to = 'membership_sale') AND "
            "(reservation_type_id IS NULL OR applies_to <> 'membership_sale') AND "
            "(NOT is_first_invoice_only OR applies_to = 'membership_sale')", name="target",
        ),
        CheckConstraint("commission_pct BETWEEN 0 AND 100 AND flat_minor >= 0", name="amounts"),
    )  # fmt: skip

    staff_payee_id: Mapped[UUID]
    applies_to: Mapped[str] = enum_column()
    reservation_type_id: Mapped[UUID | None]
    membership_type_id: Mapped[UUID | None]
    commission_pct: Mapped[Decimal] = mapped_column(_Pct, server_default=text("0"))
    flat_minor: Mapped[int] = mapped_column(server_default=text("0"))
    is_first_invoice_only: Mapped[bool] = mapped_column(server_default=text("false"))


class JobClassification(TenantOwned, Timestamps, Base):
    """What an employee clocks in as (front desk, coach, cleaning). Tenant-wide (STF-06)."""

    __tablename__ = "job_classification"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "name", name="uq_job_classification_name"),
        CheckConstraint("btrim(name) <> ''", name="name"),
    )

    name: Mapped[str] = mapped_column(info={"audit": "value"})
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class StaffHourlyRate(TenantOwned, Timestamps, Base):
    """Effective-dated hourly pay per user and classification; a user clocks in only where a rate exists."""

    __tablename__ = "staff_hourly_rate"
    __table_args__ = tenant_args(
        *tfk("staff_user_id", "staff_user", index=False),
        *tfk("job_classification_id", "job_classification"),
        UniqueConstraint(
            "tenant_id", "staff_user_id", "job_classification_id", "effective_from_on", name="uq_staff_hourly_rate"
        ),
        CheckConstraint("rate_minor >= 0", name="rate"),
    )

    staff_user_id: Mapped[UUID]
    job_classification_id: Mapped[UUID]
    rate_minor: Mapped[int]
    effective_from_on: Mapped[date]


class StaffSettings(TenantOwned, Timestamps, Base):
    """The tenant row (location_id null) and optional per-location overrides (STF-06, STF-09)."""

    __tablename__ = "staff_settings"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        enum_check("default_commission_basis", CommissionBasis),
        enum_check("pay_period", PayPeriod),
        UniqueConstraint("tenant_id", "location_id", name="uq_staff_settings", postgresql_nulls_not_distinct=True),
    )

    location_id: Mapped[UUID | None]
    is_time_clock_network_restricted: Mapped[bool] = mapped_column(server_default=text("false"))
    time_clock_networks: Mapped[list[Any]] = mapped_column(ARRAY(CIDR), server_default=text("'{}'"))
    default_commission_basis: Mapped[str] = enum_column(server_default=text("'paid'"))
    pay_period: Mapped[str] = enum_column(server_default=text("'biweekly'"))
    pay_period_anchor_on: Mapped[date | None]


class TimeEntry(TenantOwned, Timestamps, Base):
    """One worked interval. The exclusion constraint also allows one open entry per user (STF-07, STF-08)."""

    __tablename__ = "time_entry"
    __table_args__ = tenant_args(
        *tfk("staff_user_id", "staff_user", index=False),
        *tfk("location_id", "location", index=False),
        *tfk("job_classification_id", "job_classification"),
        *tfk("edited_by_staff_user_id", "staff_user"),
        enum_check("source", EntrySource),
        CheckConstraint("clock_out_at IS NULL OR clock_out_at > clock_in_at", name="order"),
        ExcludeConstraint(
            ("tenant_id", "="), ("staff_user_id", "="),
            (text("tstzrange(clock_in_at, COALESCE(clock_out_at, 'infinity'::timestamptz), '[)')"), "&&"),
            name="ex_time_entry_overlap", using="gist", where=text("voided_at IS NULL"),
        ),
        Index("ix_time_entry_open", "tenant_id", "staff_user_id",
              postgresql_where=text("clock_out_at IS NULL AND voided_at IS NULL")),
        Index("ix_time_entry_location", "tenant_id", "location_id", "clock_in_at"),
    )  # fmt: skip

    staff_user_id: Mapped[UUID]
    location_id: Mapped[UUID]
    job_classification_id: Mapped[UUID]
    clock_in_at: Mapped[datetime]
    clock_out_at: Mapped[datetime | None]
    source: Mapped[str] = enum_column(server_default=text("'self'"))
    source_ip: Mapped[Any | None] = mapped_column(INET, info={"audit": "flag"})
    edited_by_staff_user_id: Mapped[UUID | None]
    edit_reason: Mapped[str | None]
    voided_at: Mapped[datetime | None]


class Shift(TenantOwned, Timestamps, Base):
    """Planned work for one employee. Not a booking: shifts never write resource holds (STF-15)."""

    __tablename__ = "shift"
    __table_args__ = tenant_args(
        *tfk("staff_user_id", "staff_user", index=False),
        *tfk("location_id", "location", index=False),
        *tfk("job_classification_id", "job_classification"),
        enum_check("status", ShiftStatus),
        CheckConstraint("ends_at > starts_at", name="order"),
        ExcludeConstraint(
            ("tenant_id", "="), ("staff_user_id", "="), (text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            name="ex_shift_overlap", using="gist", where=text("status <> 'cancelled'"),
        ),
        Index("ix_shift_location", "tenant_id", "location_id", "starts_at"),
    )  # fmt: skip

    staff_user_id: Mapped[UUID]
    location_id: Mapped[UUID]
    job_classification_id: Mapped[UUID | None]
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    status: Mapped[str] = enum_column(server_default=text("'draft'"))
    note: Mapped[str | None]


class PayrollRun(TenantOwned, Timestamps, Base):
    """A computed, then frozen, pay report for a date range (STF-09, STF-10). The product never disburses."""

    __tablename__ = "payroll_run"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("scope_staff_payee_id", "staff_payee"),
        *tfk("finalized_by_staff_user_id", "staff_user"),
        *tfk("requested_by_staff_user_id", "staff_user"),
        enum_check("commission_basis", CommissionBasis),
        enum_check("status", RunStatus),
        CheckConstraint("period_ends_on >= period_starts_on", name="period"),
        CheckConstraint(
            "includes <@ ARRAY['sessions','commissions','hourly']::text[] AND cardinality(includes) > 0",
            name="includes",
        ),
    )

    location_id: Mapped[UUID | None]
    period_starts_on: Mapped[date]
    period_ends_on: Mapped[date]
    commission_basis: Mapped[str] = enum_column()
    includes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{sessions,commissions,hourly}'"), info={"audit": "value"}
    )
    scope_staff_payee_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'draft'"))
    calculated_at: Mapped[datetime | None]
    finalized_at: Mapped[datetime | None]
    finalized_by_staff_user_id: Mapped[UUID | None]
    requested_by_staff_user_id: Mapped[UUID]


class PayStatement(TenantOwned, Timestamps, Base):
    """One payee's or hourly employee's totals in a run; the lines are the evidence."""

    __tablename__ = "pay_statement"
    __table_args__ = tenant_args(
        *tfk("payroll_run_id", "payroll_run", ondelete="CASCADE", index=False),
        *tfk("staff_payee_id", "staff_payee"),
        *tfk("staff_user_id", "staff_user"),
        CheckConstraint("num_nonnulls(staff_payee_id, staff_user_id) >= 1", name="subject"),
        CheckConstraint(
            "total_minor = session_pay_minor + commission_minor + bonus_minor + hourly_pay_minor"
            " + additional_income_minor", name="total",
        ),
        Index("uq_pay_statement_payee", "tenant_id", "payroll_run_id", "staff_payee_id", unique=True,
              postgresql_where=text("staff_payee_id IS NOT NULL")),
        Index("uq_pay_statement_user", "tenant_id", "payroll_run_id", "staff_user_id", unique=True,
              postgresql_where=text("staff_payee_id IS NULL")),
    )  # fmt: skip

    payroll_run_id: Mapped[UUID]
    staff_payee_id: Mapped[UUID | None]
    staff_user_id: Mapped[UUID | None]
    display_name: Mapped[str]
    session_pay_minor: Mapped[int] = mapped_column(server_default=text("0"))
    commission_minor: Mapped[int] = mapped_column(server_default=text("0"))
    bonus_minor: Mapped[int] = mapped_column(server_default=text("0"))
    hourly_pay_minor: Mapped[int] = mapped_column(server_default=text("0"))
    additional_income_minor: Mapped[int] = mapped_column(server_default=text("0"))
    additional_income_note: Mapped[str | None]
    total_minor: Mapped[int] = mapped_column(server_default=text("0"))


class PayStatementLine(TenantOwned, Timestamps, Base):
    """A snapshot of one pay fact with the rate applied; rebuilt until the run is finalized."""

    __tablename__ = "pay_statement_line"
    __table_args__ = tenant_args(
        *tfk("pay_statement_id", "pay_statement", ondelete="CASCADE", index=False),
        *tfk("reservation_type_id", "reservation_type"),
        enum_check("kind", LineKind),
        Index("ix_pay_statement_line_source", "tenant_id", "kind", "source_type", "source_id"),
        Index("ix_pay_statement_line_statement", "tenant_id", "pay_statement_id", "occurred_on"),
    )

    pay_statement_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    occurred_on: Mapped[date]
    source_type: Mapped[str]
    source_id: Mapped[UUID]
    reservation_type_id: Mapped[UUID | None]
    description: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default=text("1"))
    rate_minor: Mapped[int | None]
    commission_pct: Mapped[Decimal | None] = mapped_column(_Pct)
    base_minor: Mapped[int | None]
    amount_minor: Mapped[int]
    was_paid_before: Mapped[bool] = mapped_column(server_default=text("false"))


# --- coach revenue share (independent coaches) -----------------------------------------------------------------


class Engagement(StrEnum):
    EMPLOYEE = "employee"  # a staff coach: paid through payroll
    INDEPENDENT = "independent"  # an independent coach: earns a share of lesson revenue, never on payroll


class CourtFeeBasis(StrEnum):
    SESSION = "session"
    HOUR = "hour"


class CourtFeeApplies(StrEnum):
    BEFORE_SPLIT = "before_split"  # the fee comes off the lesson price, then the rest is split
    AFTER_SPLIT = "after_split"  # the lesson price is split, then the fee comes off the coach's share


class EarningKind(StrEnum):
    LESSON = "lesson"
    REVERSAL = "reversal"
    ADJUSTMENT = "adjustment"


class EarningSource(StrEnum):
    ENROLLMENT = "enrollment"
    BOOKING = "booking"


class PayoutStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    PAID = "paid"


class PayoutMethod(StrEnum):
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    OTHER = "other"


class CoachEngagement(TenantOwned, Timestamps, Base):
    """How a trainer payee is engaged from a date on; the latest row on or before a day is in force, and no row
    means a staff coach (employee). Effective-dated so a change never rewrites a past payroll or earning."""

    __tablename__ = "coach_engagement"
    __table_args__ = tenant_args(
        *tfk("staff_payee_id", "staff_payee", index=False),
        enum_check("engagement", Engagement),
        UniqueConstraint("tenant_id", "staff_payee_id", "effective_from_on", name="uq_coach_engagement"),
    )

    staff_payee_id: Mapped[UUID]
    engagement: Mapped[str] = enum_column()
    effective_from_on: Mapped[date]


class CoachShareRule(TenantOwned, Timestamps, Base):
    """An independent coach's share of net lesson revenue. Most specific wins: coach and lesson type, coach, lesson
    type, then the tenant default (both null). Effective-dated; earnings snapshot what they used."""

    __tablename__ = "coach_share_rule"
    __table_args__ = tenant_args(
        *tfk("staff_payee_id", "staff_payee", index=False),
        *tfk("reservation_type_id", "reservation_type"),
        enum_check("court_fee_basis", CourtFeeBasis),
        enum_check("court_fee_applies", CourtFeeApplies),
        UniqueConstraint("tenant_id", "staff_payee_id", "reservation_type_id", "effective_from_on",
                         name="uq_coach_share_rule", postgresql_nulls_not_distinct=True),
        CheckConstraint("coach_share_pct BETWEEN 0 AND 100 AND court_fee_minor >= 0", name="amounts"),
    )  # fmt: skip

    staff_payee_id: Mapped[UUID | None]
    reservation_type_id: Mapped[UUID | None]
    effective_from_on: Mapped[date]
    coach_share_pct: Mapped[Decimal] = mapped_column(_Pct)
    court_fee_minor: Mapped[int] = mapped_column(server_default=text("0"))
    court_fee_basis: Mapped[str] = enum_column(server_default=text("'session'"))
    court_fee_applies: Mapped[str] = enum_column(server_default=text("'before_split'"))


class CoachEarning(TenantOwned, Base):
    """The immutable earnings ledger of independent coaches: one line per recognised lesson, a reversing line when
    the money goes back, and manual adjustments. Shares always sum to the gross. No client id and no client text:
    the description is "Lesson" (or "Adjustment"), because an immutable row could never be erased or exported."""

    __tablename__ = "coach_earning"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("staff_payee_id", "staff_payee", index=False),
        *tfk("reservation_type_id", "reservation_type"),
        *tfk("reverses_coach_earning_id", "coach_earning", index=False),
        *tfk("created_by_staff_user_id", "staff_user"),
        enum_check("kind", EarningKind),
        enum_check("source_type", EarningSource),
        CheckConstraint("gross_minor = facility_share_minor + coach_share_minor", name="split"),
        CheckConstraint("(kind = 'reversal') = (reverses_coach_earning_id IS NOT NULL)", name="reversal"),
        CheckConstraint("kind <> 'adjustment' OR (reason IS NOT NULL AND btrim(reason) <> '' AND gross_minor = 0)",
                        name="adjustment"),
        CheckConstraint("kind = 'adjustment' OR (source_type IS NOT NULL AND source_id IS NOT NULL)", name="source"),
        Index("uq_coach_earning_reversal", "tenant_id", "reverses_coach_earning_id", unique=True,
              postgresql_where=text("reverses_coach_earning_id IS NOT NULL")),
        Index("ix_coach_earning_payee", "tenant_id", "staff_payee_id", "earned_on", "id"),
        Index("ix_coach_earning_source", "tenant_id", "source_type", "source_id"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    staff_payee_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    earned_on: Mapped[date]
    source_type: Mapped[str | None] = enum_column()
    source_id: Mapped[UUID | None]
    reservation_type_id: Mapped[UUID | None]
    description: Mapped[str]
    gross_minor: Mapped[int]
    facility_share_minor: Mapped[int]
    coach_share_minor: Mapped[int]
    coach_share_pct: Mapped[Decimal | None] = mapped_column(_Pct)
    court_fee_minor: Mapped[int] = mapped_column(server_default=text("0"))
    reverses_coach_earning_id: Mapped[UUID | None]
    reason: Mapped[str | None]
    created_by_staff_user_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class CoachPayout(TenantOwned, Timestamps, Base):
    """A payout statement: what the facility owes one independent coach for gathered earning lines. A record only;
    the software moves no money (a Stripe Connect transfer can fill `payment_reference` later). Paid is final;
    corrections go on the next statement."""

    __tablename__ = "coach_payout"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("staff_payee_id", "staff_payee"),
        *tfk("created_by_staff_user_id", "staff_user"),
        *tfk("approved_by_staff_user_id", "staff_user"),
        *tfk("paid_by_staff_user_id", "staff_user"),
        enum_check("status", PayoutStatus),
        enum_check("payment_method", PayoutMethod),
        CheckConstraint("period_ends_on >= period_starts_on", name="period"),
        CheckConstraint("gross_minor = facility_share_minor + coach_share_minor", name="split"),
        CheckConstraint("status = 'draft' OR approved_at IS NOT NULL", name="approved"),
        CheckConstraint("(status = 'paid') = (paid_on IS NOT NULL AND payment_method IS NOT NULL)", name="paid"),
        Index("ix_coach_payout_location", "tenant_id", "location_id", "period_ends_on", "id"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    staff_payee_id: Mapped[UUID]
    period_starts_on: Mapped[date]
    period_ends_on: Mapped[date]
    status: Mapped[str] = enum_column(server_default=text("'draft'"))
    line_count: Mapped[int] = mapped_column(server_default=text("0"))
    gross_minor: Mapped[int] = mapped_column(server_default=text("0"))
    facility_share_minor: Mapped[int] = mapped_column(server_default=text("0"))
    coach_share_minor: Mapped[int] = mapped_column(server_default=text("0"))
    adjustment_minor: Mapped[int] = mapped_column(server_default=text("0"))
    created_by_staff_user_id: Mapped[UUID | None]
    approved_at: Mapped[datetime | None]
    approved_by_staff_user_id: Mapped[UUID | None]
    paid_at: Mapped[datetime | None]
    paid_by_staff_user_id: Mapped[UUID | None]
    paid_on: Mapped[date | None]
    payment_method: Mapped[str | None] = enum_column()
    payment_reference: Mapped[str | None]


class CoachPayoutLine(TenantOwned, Timestamps, Base):
    """An earning line gathered into a payout; an earning is on one payout at most."""

    __tablename__ = "coach_payout_line"
    __table_args__ = tenant_args(
        *tfk("coach_payout_id", "coach_payout", ondelete="CASCADE"),
        *tfk("coach_earning_id", "coach_earning", index=False),
        UniqueConstraint("tenant_id", "coach_earning_id", name="uq_coach_payout_line_earning"),
    )

    coach_payout_id: Mapped[UUID]
    coach_earning_id: Mapped[UUID]
