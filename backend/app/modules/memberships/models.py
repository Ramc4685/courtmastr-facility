"""memberships tables (docs/architecture/data-model-people.md section 3, the schema of record).

Deviations, recorded in the module README. `coupon_id` and `payment_method_id` are not created (their tables exist
in billing; the columns are left out on purpose). `catalog_item_id` is on the add-on and period tables, so an add-on
is a package plan or a catalog item. `membership_visit.check_in_id` has no foreign key (the `access` context owns
`check_in`).
Added: `membership_contract.end_on_before_cancel` (what undo-cancel restores) and, on `billing_schedule_period`,
`charge_sequence` (the billing origin line of the next charge after a reversal), `pre_freeze` (the dates a freeze
replaced, so editing or removing it is exact) and `cancelled_reason`. The exclusion constraints live in the
migration (Alembic cannot generate them).
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Numeric, SmallInteger, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import DATERANGE, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JsonDict, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk

LIVE = ("upcoming", "active", "frozen", "suspended")
_ONE_DISCOUNT = "num_nonnulls(discount_pct, discount_minor) <= 1"
_Pct = Numeric(5, 2)


class IntervalUnit(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class RenewalTarget(StrEnum):
    SAME_TERMS = "same_terms"
    PLAN = "plan"


class PlanInvoiceMode(StrEnum):
    ASK = "ask"
    PER_PERIOD = "per_period"
    SINGLE = "single"


class ProrationMode(StrEnum):
    NONE = "none"
    TO_MONTH_START = "to_month_start"
    SELLER_CHOICE = "seller_choice"


class ProrationTail(StrEnum):
    EXTEND_LAST = "extend_last"
    DROP_LAST = "drop_last"
    PRORATE_LAST = "prorate_last"


class AddonKind(StrEnum):
    PACKAGE_PLAN = "package_plan"
    CATALOG_ITEM = "catalog_item"


class PaymentCapture(StrEnum):
    HIDDEN = "hidden"
    OPTIONAL = "optional"
    REQUIRED = "required"


class CardSaveMode(StrEnum):
    ALWAYS = "always"
    WHEN_NOTHING_DUE = "when_nothing_due"
    ASK = "ask"


class ResumeInvoiceMode(StrEnum):
    PER_PERIOD = "per_period"
    SINGLE = "single"
    DEFERRED = "deferred"


class InvoiceMode(StrEnum):
    PER_PERIOD = "per_period"
    SINGLE = "single"
    DEFERRED = "deferred"
    NONE = "none"


class DisabledBy(StrEnum):
    STAFF = "staff"
    CLIENT = "client"
    FREEZE = "freeze"


class SalesChannel(StrEnum):
    STAFF = "staff"
    PORTAL = "portal"
    MOBILE = "mobile"
    POS = "pos"
    API = "api"
    RENEWAL = "renewal"
    IMPORT = "import"


class ContractStatus(StrEnum):
    UPCOMING = "upcoming"
    ACTIVE = "active"
    FROZEN = "frozen"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class CancelReason(StrEnum):
    VOLUNTARY = "voluntary"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    ADMINISTRATIVE_ERROR = "administrative_error"
    OTHER = "other"


class PeriodKind(StrEnum):
    DUES = "dues"
    INITIATION = "initiation"
    SUSPENSION_FEE = "suspension_fee"
    ADDON_ITEM = "addon_item"


class PeriodStatus(StrEnum):
    SCHEDULED = "scheduled"
    BILLED = "billed"
    WITHHELD = "withheld"
    CANCELLED = "cancelled"


class PeriodCancelledReason(StrEnum):
    CONTRACT_CANCELLED = "contract_cancelled"
    SUSPENSION_ENDED = "suspension_ended"


class ShareOrigin(StrEnum):
    MANUAL = "manual"
    CARRIED_FROM_PREVIOUS = "carried_from_previous"


class MembershipType(TenantOwned, Timestamps, Base):
    __tablename__ = "membership_type"
    __table_args__ = tenant_args(
        *tfk("revenue_category_id", "revenue_category"),
        Index("uq_membership_type_name", "tenant_id", text("lower(name)"), unique=True),
    )

    name: Mapped[str] = mapped_column(info={"audit": "value"})
    revenue_category_id: Mapped[UUID]
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class MembershipPlan(TenantOwned, Timestamps, Base):
    __tablename__ = "membership_plan"
    __table_args__ = tenant_args(
        *tfk("membership_type_id", "membership_type", index=False),
        *tfk("renews_as_plan_id", "membership_plan"),
        *tfk("revenue_category_id", "revenue_category"),
        enum_check("billing_interval_unit", IntervalUnit),
        enum_check("auto_renew_lead_unit", IntervalUnit),
        enum_check("renewal_target", RenewalTarget),
        enum_check("default_invoice_mode", PlanInvoiceMode),
        enum_check("proration_mode", ProrationMode),
        enum_check("proration_tail", ProrationTail),
        CheckConstraint("billing_interval_count >= 1", name="billing_interval_count"),
        CheckConstraint("billing_occurrences_count >= 1", name="billing_occurrences_count"),
        CheckConstraint(
            "(auto_renew_lead_count IS NULL) = (auto_renew_lead_unit IS NULL) AND auto_renew_lead_count >= 0",
            name="auto_renew_lead",
        ),
        CheckConstraint("(renewal_target = 'plan') = (renews_as_plan_id IS NOT NULL)", name="renewal"),
        CheckConstraint("max_visits_count >= 1", name="max_visits_count"),
        CheckConstraint("initiation_fee_minor >= 0", name="initiation_fee_minor"),
        CheckConstraint("term_fee_minor >= 0", name="term_fee_minor"),
        CheckConstraint("payment_due_day BETWEEN 1 AND 31", name="payment_due_day"),
        CheckConstraint(_ONE_DISCOUNT, name="discount"),
        CheckConstraint("discount_pct BETWEEN 0 AND 100 AND discount_minor >= 0", name="discount_range"),
        CheckConstraint("(proration_mode = 'to_month_start') = (proration_tail IS NOT NULL)", name="proration"),
        Index("ix_membership_plan_type", "tenant_id", "membership_type_id", "sort_order"),
        Index("ix_membership_plan_online", "tenant_id", postgresql_where=text("is_sold_online AND is_active")),
    )

    membership_type_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    invoice_description: Mapped[str | None] = mapped_column(String(100))
    fixed_start_on: Mapped[date | None]
    billing_interval_unit: Mapped[str] = enum_column(server_default=text("'month'"))
    billing_interval_count: Mapped[int] = mapped_column(server_default=text("1"))
    billing_occurrences_count: Mapped[int]
    auto_renew_lead_count: Mapped[int | None]
    auto_renew_lead_unit: Mapped[str | None] = enum_column()
    renewal_target: Mapped[str] = enum_column(server_default=text("'same_terms'"))
    renews_as_plan_id: Mapped[UUID | None]
    max_visits_count: Mapped[int | None]
    initiation_fee_minor: Mapped[int] = mapped_column(server_default=text("0"))
    term_fee_minor: Mapped[int]
    payment_due_day: Mapped[int | None] = mapped_column(SmallInteger)
    discount_pct: Mapped[Decimal | None] = mapped_column(_Pct)
    discount_minor: Mapped[int | None]
    revenue_category_id: Mapped[UUID | None]
    default_invoice_mode: Mapped[str] = enum_column(server_default=text("'ask'"))
    is_autopay_default: Mapped[bool | None]  # BIL-17: null follows the billing setting for the sales channel
    is_sold_online: Mapped[bool] = mapped_column(server_default=text("false"))
    proration_mode: Mapped[str] = enum_column(server_default=text("'none'"))
    proration_tail: Mapped[str | None] = enum_column()
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    version: Mapped[int] = mapped_column(server_default=text("1"))


class MembershipPlanAddon(TenantOwned, Timestamps, Base):
    __tablename__ = "membership_plan_addon"
    __table_args__ = tenant_args(
        *tfk("membership_plan_id", "membership_plan", ondelete="CASCADE"),
        *tfk("package_plan_id", "package_plan"),
        enum_check("addon_kind", AddonKind),
        *tfk("catalog_item_id", "catalog_item"),
        CheckConstraint(
            "(addon_kind = 'package_plan') = (package_plan_id IS NOT NULL) "
            "AND (addon_kind = 'catalog_item') = (catalog_item_id IS NOT NULL)",
            name="target",
        ),
        CheckConstraint("quantity >= 1", name="quantity"),
    )

    membership_plan_id: Mapped[UUID]
    addon_kind: Mapped[str] = enum_column()
    package_plan_id: Mapped[UUID | None]
    catalog_item_id: Mapped[UUID | None]
    quantity: Mapped[int] = mapped_column(server_default=text("1"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class MembershipSettings(TenantOwned, Timestamps, Base):
    __tablename__ = "membership_settings"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", name="uq_membership_settings_tenant"),
        enum_check("payment_method_capture", PaymentCapture),
        enum_check("online_card_save_mode", CardSaveMode),
        enum_check("freeze_resume_invoice_mode", ResumeInvoiceMode),
        CheckConstraint("billing_lead_days BETWEEN 0 AND 60", name="billing_lead_days"),
    )

    is_remark_required_on_freeze: Mapped[bool] = mapped_column(server_default=text("false"))
    is_remark_required_on_suspend: Mapped[bool] = mapped_column(server_default=text("false"))
    is_remark_required_on_cancel: Mapped[bool] = mapped_column(server_default=text("false"))
    payment_method_capture: Mapped[str] = enum_column(server_default=text("'optional'"))
    online_card_save_mode: Mapped[str] = enum_column(server_default=text("'ask'"))
    billing_lead_days: Mapped[int] = mapped_column(server_default=text("0"))
    is_daily_visit_limit_enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    freeze_resume_invoice_mode: Mapped[str] = enum_column(server_default=text("'per_period'"))
    is_addon_package_cancelled_with_contract: Mapped[bool] = mapped_column(server_default=text("true"))


class MembershipContract(TenantOwned, Timestamps, Base):
    """One sold term for one owning (billed) client; a renewal is a new row linked by previous_contract_id."""

    __tablename__ = "membership_contract"
    __table_args__ = tenant_args(
        *tfk("owner_client_id", "client", index=False),
        *tfk("location_id", "location", index=False),
        *tfk("membership_plan_id", "membership_plan"),
        *tfk("membership_type_id", "membership_type", index=False),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("renews_as_plan_id", "membership_plan"),
        *tfk("previous_contract_id", "membership_contract", index=False),
        *tfk("sold_by_staff_user_id", "staff_user"),
        *tfk("referred_by_client_id", "client"),
        *tfk("client_document_id", "client_document"),
        *tfk("cancelled_by_staff_user_id", "staff_user"),
        enum_check("billing_interval_unit", IntervalUnit),
        enum_check("invoice_mode", InvoiceMode),
        enum_check("proration_tail", ProrationTail),
        enum_check("auto_renew_lead_unit", IntervalUnit),
        enum_check("renewal_target", RenewalTarget),
        enum_check("auto_renew_disabled_by", DisabledBy),
        enum_check("sales_channel", SalesChannel),
        enum_check("status", ContractStatus),
        enum_check("cancel_reason", CancelReason),
        CheckConstraint("end_on >= start_on", name="term"),
        CheckConstraint("term_fee_minor >= 0 AND initiation_fee_minor >= 0", name="fees"),
        CheckConstraint(_ONE_DISCOUNT, name="discount"),
        CheckConstraint("num_nonnulls(renewal_discount_pct, renewal_discount_minor) <= 1", name="renewal_discount"),
        CheckConstraint("visits_used_count >= 0", name="visits"),
        CheckConstraint("(status = 'cancelled') = (cancelled_on IS NOT NULL)", name="cancelled_on"),
        CheckConstraint("(renewal_target = 'plan') = (renews_as_plan_id IS NOT NULL)", name="renewal"),
        Index("ix_membership_contract_owner", "tenant_id", "owner_client_id", text("start_on DESC")),
        Index("ix_membership_contract_status", "tenant_id", "status", "end_on"),
        Index("ix_membership_contract_location", "tenant_id", "location_id", "status", "id"),
        Index("ix_membership_contract_type", "tenant_id", "membership_type_id", "status"),
        Index(
            "ix_membership_contract_renew_due", "tenant_id", "renew_on",
            postgresql_where=text("is_auto_renew AND status IN ('active', 'frozen', 'suspended')"),
        ),
        Index("ix_membership_contract_start_due", "tenant_id", "start_on", postgresql_where=text("status = 'upcoming'")),
        Index(
            "ix_membership_contract_end_due", "tenant_id", "end_on",
            postgresql_where=text("status IN ('active', 'suspended')"),
        ),
        # A contract is renewed at most once: a double-clicked renew or a retried job cannot make two successors.
        Index(
            "uq_membership_contract_previous", "tenant_id", "previous_contract_id", unique=True,
            postgresql_where=text("previous_contract_id IS NOT NULL"),
        ),
    )  # fmt: skip

    owner_client_id: Mapped[UUID]
    location_id: Mapped[UUID]
    membership_plan_id: Mapped[UUID | None]
    membership_type_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    invoice_description: Mapped[str | None] = mapped_column(String(100))
    revenue_category_id: Mapped[UUID]
    start_on: Mapped[date]
    end_on: Mapped[date]
    original_end_on: Mapped[date]
    billing_interval_unit: Mapped[str] = enum_column()
    billing_interval_count: Mapped[int]
    billing_occurrences_count: Mapped[int]
    term_fee_minor: Mapped[int]
    initiation_fee_minor: Mapped[int] = mapped_column(server_default=text("0"))
    discount_pct: Mapped[Decimal | None] = mapped_column(_Pct)
    discount_minor: Mapped[int | None]
    payment_due_day: Mapped[int | None] = mapped_column(SmallInteger)
    revenue_on: Mapped[date | None]
    max_visits_count: Mapped[int | None]
    visits_used_count: Mapped[int] = mapped_column(server_default=text("0"))
    is_autopay: Mapped[bool] = mapped_column(server_default=text("false"))
    invoice_mode: Mapped[str] = enum_column()
    is_prorated: Mapped[bool] = mapped_column(server_default=text("false"))
    proration_tail: Mapped[str | None] = enum_column()
    is_auto_renew: Mapped[bool] = mapped_column(server_default=text("false"))
    auto_renew_lead_count: Mapped[int | None]
    auto_renew_lead_unit: Mapped[str | None] = enum_column()
    renew_on: Mapped[date | None]
    renewal_target: Mapped[str] = enum_column(server_default=text("'same_terms'"))
    renews_as_plan_id: Mapped[UUID | None]
    renewal_discount_pct: Mapped[Decimal | None] = mapped_column(_Pct)
    renewal_discount_minor: Mapped[int | None]
    renewal_description: Mapped[str | None]
    renewal_remark: Mapped[str | None]
    auto_renew_disabled_by: Mapped[str | None] = enum_column()
    auto_renew_disabled_at: Mapped[datetime | None]
    previous_contract_id: Mapped[UUID | None]
    sold_by_staff_user_id: Mapped[UUID | None]
    referred_by_client_id: Mapped[UUID | None]
    sales_channel: Mapped[str] = enum_column(server_default=text("'staff'"))
    internal_notes: Mapped[str | None]
    client_document_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column()
    activated_at: Mapped[datetime | None]
    cancelled_on: Mapped[date | None]
    cancel_reason: Mapped[str | None] = enum_column()
    cancel_remarks: Mapped[str | None]
    cancelled_by_staff_user_id: Mapped[UUID | None]
    cancelled_at: Mapped[datetime | None]
    end_on_before_cancel: Mapped[date | None]
    version: Mapped[int] = mapped_column(server_default=text("1"))


class MembershipContractAddon(TenantOwned, Timestamps, Base):
    __tablename__ = "membership_contract_addon"
    __table_args__ = tenant_args(
        *tfk("membership_contract_id", "membership_contract", ondelete="CASCADE"),
        *tfk("package_plan_id", "package_plan"),
        enum_check("addon_kind", AddonKind),
        *tfk("catalog_item_id", "catalog_item"),
        CheckConstraint(
            "(addon_kind = 'package_plan') = (package_plan_id IS NOT NULL) "
            "AND (addon_kind = 'catalog_item') = (catalog_item_id IS NOT NULL)",
            name="target",
        ),
        CheckConstraint("quantity >= 1", name="quantity"),
    )

    membership_contract_id: Mapped[UUID]
    addon_kind: Mapped[str] = enum_column()
    package_plan_id: Mapped[UUID | None]
    catalog_item_id: Mapped[UUID | None]
    quantity: Mapped[int] = mapped_column(server_default=text("1"))


class BillingSchedulePeriod(TenantOwned, Timestamps, Base):
    """The pre-generated receivable schedule of a contract. A row becomes a charge only through billing."""

    __tablename__ = "billing_schedule_period"
    __table_args__ = tenant_args(
        *tfk("membership_contract_id", "membership_contract", ondelete="CASCADE", index=False),
        *tfk("suspension_id", "membership_suspension"),
        *tfk("charge_id", "charge", index=False),
        *tfk("withheld_by_freeze_id", "membership_freeze"),
        *tfk("catalog_item_id", "catalog_item"),
        CheckConstraint("(kind = 'addon_item') = (catalog_item_id IS NOT NULL)", name="addon_item"),
        enum_check("kind", PeriodKind),
        enum_check("status", PeriodStatus),
        enum_check("cancelled_reason", PeriodCancelledReason),
        UniqueConstraint("tenant_id", "membership_contract_id", "kind", "sequence_number"),
        CheckConstraint("(kind = 'dues') <= (service_during IS NOT NULL)", name="service_during"),
        CheckConstraint("amount_minor >= 0", name="amount_minor"),
        CheckConstraint("status <> 'billed' OR charge_id IS NOT NULL", name="charge"),
        CheckConstraint("(status = 'withheld') = (withheld_by_freeze_id IS NOT NULL)", name="withheld"),
        Index(
            "uq_billing_schedule_period_charge", "tenant_id", "charge_id", unique=True,
            postgresql_where=text("charge_id IS NOT NULL"),
        ),
        Index(
            "ix_billing_schedule_period_bill_due", "tenant_id", "bill_on", postgresql_where=text("status = 'scheduled'")
        ),
        Index("ix_billing_schedule_period_contract", "tenant_id", "membership_contract_id", "due_on"),
        Index("ix_billing_schedule_period_revenue", "tenant_id", "revenue_on"),
    )  # fmt: skip

    membership_contract_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    sequence_number: Mapped[int]
    service_during: Mapped[Range[date] | None] = mapped_column(DATERANGE)
    due_on: Mapped[date]
    bill_on: Mapped[date]
    revenue_on: Mapped[date]
    list_amount_minor: Mapped[int]
    amount_minor: Mapped[int]
    is_prorated: Mapped[bool] = mapped_column(server_default=text("false"))
    description: Mapped[str] = mapped_column(info={"audit": "value"})
    suspension_id: Mapped[UUID | None]
    catalog_item_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'scheduled'"))
    charge_id: Mapped[UUID | None]
    charge_sequence: Mapped[int] = mapped_column(server_default=text("0"))
    billed_at: Mapped[datetime | None]
    withheld_by_freeze_id: Mapped[UUID | None]
    pre_freeze: Mapped[dict | None] = mapped_column(JsonDict)
    cancelled_reason: Mapped[str | None] = enum_column()


class MembershipFreeze(TenantOwned, Timestamps, Base):
    __tablename__ = "membership_freeze"
    __table_args__ = tenant_args(
        *tfk("membership_contract_id", "membership_contract", ondelete="CASCADE"),
        *tfk("created_by_staff_user_id", "staff_user"),
        *tfk("removed_by_staff_user_id", "staff_user"),
        enum_check("resume_invoice_mode", ResumeInvoiceMode),
        CheckConstraint("NOT isempty(during) AND lower(during) IS NOT NULL", name="during"),
        Index(
            "ix_membership_freeze_end_due", "tenant_id", text("upper(during)"),
            postgresql_where=text("removed_at IS NULL"),
        ),
    )  # fmt: skip

    membership_contract_id: Mapped[UUID]
    during: Mapped[Range[date]] = mapped_column(DATERANGE)
    remarks: Mapped[str | None]
    extended_days_count: Mapped[int] = mapped_column(server_default=text("0"))
    resume_invoice_mode: Mapped[str | None] = enum_column()
    created_by_staff_user_id: Mapped[UUID | None]
    removed_at: Mapped[datetime | None]
    removed_by_staff_user_id: Mapped[UUID | None]
    removal_remarks: Mapped[str | None]


class MembershipSuspension(TenantOwned, Timestamps, Base):
    __tablename__ = "membership_suspension"
    __table_args__ = tenant_args(
        *tfk("membership_contract_id", "membership_contract", ondelete="CASCADE"),
        *tfk("created_by_staff_user_id", "staff_user"),
        *tfk("removed_by_staff_user_id", "staff_user"),
        CheckConstraint("NOT isempty(during) AND lower(during) IS NOT NULL", name="during"),
        CheckConstraint("fee_minor > 0", name="fee_minor"),
        *tfk("past_due_invoice_id", "invoice", index=False),
        # MEM-14: one automatic suspension per contract and unpaid invoice, ever, so a sweep that runs again (or
        # one that runs after staff lifted it by hand) never suspends twice for the same invoice.
        Index(
            "uq_membership_suspension_past_due", "tenant_id", "membership_contract_id", "past_due_invoice_id",
            unique=True, postgresql_where=text("past_due_invoice_id IS NOT NULL"),
        ),
        Index(  # invoice_settled looks suspensions up by invoice alone
            "ix_membership_suspension_past_due_invoice", "tenant_id", "past_due_invoice_id",
            postgresql_where=text("past_due_invoice_id IS NOT NULL"),
        ),
    )  # fmt: skip

    membership_contract_id: Mapped[UUID]
    during: Mapped[Range[date]] = mapped_column(DATERANGE)
    past_due_invoice_id: Mapped[UUID | None]  # set when billing's non-payment rule suspended it (MEM-14)
    fee_minor: Mapped[int | None]
    remarks: Mapped[str | None]
    created_by_staff_user_id: Mapped[UUID | None]
    removed_at: Mapped[datetime | None]
    removed_by_staff_user_id: Mapped[UUID | None]
    removal_remarks: Mapped[str | None]


class MembershipShare(TenantOwned, Timestamps, Base):
    __tablename__ = "membership_share"
    __table_args__ = tenant_args(
        *tfk("membership_contract_id", "membership_contract", ondelete="CASCADE"),
        *tfk("client_id", "client", index=False),
        *tfk("added_by_staff_user_id", "staff_user"),
        *tfk("revoked_by_staff_user_id", "staff_user"),
        enum_check("origin", ShareOrigin),
        Index(
            "uq_membership_share_active", "tenant_id", "membership_contract_id", "client_id", unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_membership_share_client", "tenant_id", "client_id", postgresql_where=text("revoked_at IS NULL")),
    )  # fmt: skip

    membership_contract_id: Mapped[UUID]
    client_id: Mapped[UUID]
    origin: Mapped[str] = enum_column(server_default=text("'manual'"))
    added_by_staff_user_id: Mapped[UUID | None]
    revoked_at: Mapped[datetime | None]
    revoked_by_staff_user_id: Mapped[UUID | None]


class MembershipVisit(TenantOwned, Timestamps, Base):
    """A check-in counted against a contract (MEM-20), written by service.record_visit for `access`."""

    __tablename__ = "membership_visit"
    __table_args__ = tenant_args(
        *tfk("membership_contract_id", "membership_contract", index=False),
        *tfk("client_id", "client"),
        *tfk("location_id", "location"),
        UniqueConstraint("tenant_id", "check_in_id", name="uq_membership_visit_check_in"),
        Index("ix_membership_visit_contract_day", "tenant_id", "membership_contract_id", "local_on"),
    )

    membership_contract_id: Mapped[UUID]
    client_id: Mapped[UUID]
    check_in_id: Mapped[UUID]
    location_id: Mapped[UUID]
    visited_at: Mapped[datetime]
    local_on: Mapped[date]
    is_counted: Mapped[bool] = mapped_column(server_default=text("true"))
