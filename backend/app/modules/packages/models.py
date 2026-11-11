"""packages tables (docs/architecture/data-model-people.md section 4, the schema of record).

Deviations, recorded in the module README. `reservation_type_id` is a composite FK to scheduling's
`reservation_type` (added at integration, revision 0401). `coupon_id` is
not created (billing coupons are build module 8). Post-billed packages (PKG-11, P2) are not modelled, as the data
model says.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import DATERANGE, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk

_Pct = Numeric(5, 2)
_FLAG = {"audit": "flag"}


class PlanKind(StrEnum):
    STANDARD = "standard"
    RECURRING = "recurring"


class SessionMode(StrEnum):
    SINGLE = "single"
    FIXED = "fixed"
    RANGE = "range"
    UNLIMITED = "unlimited"


class PricingCategory(StrEnum):
    PAID = "paid"
    FREE = "free"


class FeeBasis(StrEnum):
    PER_SESSION = "per_session"
    PER_PACKAGE = "per_package"


class StartRule(StrEnum):
    SALE_DATE = "sale_date"
    FIXED_DATE = "fixed_date"


class Unit(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class RenewalTarget(StrEnum):
    SAME_TERMS = "same_terms"
    PLAN = "plan"


class PlanShareMode(StrEnum):
    NONE = "none"
    ALL_RELATED = "all_related"


class PlanInvoiceMode(StrEnum):
    ASK = "ask"
    SINGLE = "single"
    PER_PERIOD = "per_period"
    DEFERRED = "deferred"


class OnlineSaleMode(StrEnum):
    OFF = "off"
    BALANCE_ALLOWED = "balance_allowed"
    PAID_IN_FULL = "paid_in_full"


class SeriesInvoiceMode(StrEnum):
    SINGLE = "single"
    PER_PERIOD = "per_period"
    DEFERRED = "deferred"


class SeriesStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PackageInvoiceMode(StrEnum):
    SINGLE = "single"
    DEFERRED = "deferred"
    NONE = "none"


class PackageShareMode(StrEnum):
    NONE = "none"
    ALL_RELATED = "all_related"
    EXPLICIT = "explicit"


class DisabledBy(StrEnum):
    STAFF = "staff"
    CLIENT = "client"


class SalesChannel(StrEnum):
    STAFF = "staff"
    PORTAL = "portal"
    MOBILE = "mobile"
    POS = "pos"
    API = "api"
    RENEWAL = "renewal"
    MEMBERSHIP_ADDON = "membership_addon"
    IMPORT = "import"


class PackageStatus(StrEnum):
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    EXPIRED = "expired"
    REMOVED = "removed"


class RemovalMode(StrEnum):
    BILLING_REVERSED = "billing_reversed"
    BILLING_KEPT = "billing_kept"


class EntryType(StrEnum):
    GRANT = "grant"
    RESERVE = "reserve"
    RELEASE = "release"
    CONSUME = "consume"
    RESTORE = "restore"
    FORFEIT = "forfeit"
    ADJUST = "adjust"


class EntryReason(StrEnum):
    PURCHASE = "purchase"
    ADDON = "addon"
    RENEWAL = "renewal"
    BOOKING = "booking"
    CANCELLATION_EARLY = "cancellation_early"
    CANCELLATION_LATE = "cancellation_late"
    ATTENDANCE = "attendance"
    NO_SHOW = "no_show"
    EXPIRY = "expiry"
    REMOVAL = "removal"
    STAFF_ADJUSTMENT = "staff_adjustment"
    MERGE = "merge"


class SourceType(StrEnum):
    ENROLLMENT = "enrollment"
    BOOKING = "booking"


class ActorType(StrEnum):
    STAFF = "staff"
    CLIENT = "client"
    SYSTEM = "system"


class ShareOrigin(StrEnum):
    MANUAL = "manual"
    PLAN_PRESET = "plan_preset"
    CARRIED_FROM_PREVIOUS = "carried_from_previous"


class PackagePlan(TenantOwned, Timestamps, Base):
    __tablename__ = "package_plan"
    __table_args__ = tenant_args(
        *tfk("renews_as_plan_id", "package_plan"),
        *tfk("revenue_category_id", "revenue_category"),
        enum_check("kind", PlanKind),
        enum_check("session_mode", SessionMode),
        enum_check("pricing_category", PricingCategory),
        enum_check("fee_basis", FeeBasis),
        enum_check("start_rule", StartRule),
        enum_check("validity_unit", Unit),
        enum_check("auto_renew_lead_unit", Unit),
        enum_check("renewal_target", RenewalTarget),
        enum_check("share_mode", PlanShareMode),
        enum_check("recurrence_unit", Unit),
        enum_check("default_invoice_mode", PlanInvoiceMode),
        enum_check("online_sale_mode", OnlineSaleMode),
        CheckConstraint(
            "(session_mode = 'fixed') = (session_count IS NOT NULL) AND (session_mode = 'range') = "
            "(min_session_count IS NOT NULL AND max_session_count IS NOT NULL) AND (session_count IS NULL OR "
            "session_count >= 1) AND (min_session_count IS NULL OR (min_session_count >= 1 AND max_session_count "
            ">= min_session_count))",
            name="sessions",
        ),
        CheckConstraint(
            "(pricing_category = 'free' AND fee_minor IS NULL AND fee_basis IS NULL) OR (pricing_category = 'paid' "
            "AND fee_minor >= 0 AND fee_basis IS NOT NULL AND revenue_category_id IS NOT NULL)",
            name="pricing",
        ),
        CheckConstraint(
            "session_mode <> 'single' OR fee_basis IS NULL OR fee_basis = 'per_session'", name="single_basis"
        ),
        CheckConstraint(
            "(kind = 'recurring') = (recurrence_unit IS NOT NULL AND recurrence_interval_count >= 1 AND "
            "recurrence_occurrences_count >= 1) AND (kind <> 'recurring' OR session_mode <> 'range')",
            name="recurrence",
        ),
        CheckConstraint("(renewal_target = 'plan') = (renews_as_plan_id IS NOT NULL)", name="renewal"),
        CheckConstraint("(start_rule = 'fixed_date') = (fixed_start_on IS NOT NULL)", name="start"),
        CheckConstraint("(validity_count IS NULL) = (validity_unit IS NULL) AND validity_count >= 1", name="validity"),
        CheckConstraint(
            "(auto_renew_lead_count IS NULL) = (auto_renew_lead_unit IS NULL) AND auto_renew_lead_count >= 0",
            name="auto_renew_lead",
        ),
        CheckConstraint("renewal_threshold_count >= 0", name="renewal_threshold_count"),
        CheckConstraint("num_nonnulls(discount_pct, discount_minor) <= 1", name="discount"),
        CheckConstraint("discount_pct BETWEEN 0 AND 100 AND discount_minor >= 0", name="discount_range"),
        *tfk("reservation_type_id", "reservation_type", index=False),
        Index("ix_package_plan_reservation_type", "tenant_id", "reservation_type_id", "is_active"),
        Index("ix_package_plan_online", "tenant_id", postgresql_where=text("online_sale_mode <> 'off' AND is_active")),
    )

    kind: Mapped[str] = enum_column(server_default=text("'standard'"))
    reservation_type_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    invoice_description: Mapped[str | None]
    internal_remarks: Mapped[str | None]
    session_mode: Mapped[str] = enum_column()
    session_count: Mapped[int | None]
    min_session_count: Mapped[int | None]
    max_session_count: Mapped[int | None]
    pricing_category: Mapped[str] = enum_column(server_default=text("'paid'"))
    is_complimentary: Mapped[bool] = mapped_column(server_default=text("false"))
    fee_minor: Mapped[int | None]
    fee_basis: Mapped[str | None] = enum_column()
    start_rule: Mapped[str] = enum_column(server_default=text("'sale_date'"))
    fixed_start_on: Mapped[date | None]
    validity_count: Mapped[int | None]
    validity_unit: Mapped[str | None] = enum_column()
    allows_booking_after_expiry: Mapped[bool] = mapped_column(server_default=text("false"))
    auto_renew_lead_count: Mapped[int | None]
    auto_renew_lead_unit: Mapped[str | None] = enum_column()
    renewal_target: Mapped[str] = enum_column(server_default=text("'same_terms'"))
    renews_as_plan_id: Mapped[UUID | None]
    renewal_threshold_count: Mapped[int | None]
    is_auto_renew_on_threshold: Mapped[bool] = mapped_column(server_default=text("false"))
    share_mode: Mapped[str] = enum_column(server_default=text("'none'"))
    recurrence_unit: Mapped[str | None] = enum_column()
    recurrence_interval_count: Mapped[int | None]
    recurrence_occurrences_count: Mapped[int | None]
    is_series_auto_renew: Mapped[bool] = mapped_column(server_default=text("false"))
    default_invoice_mode: Mapped[str] = enum_column(server_default=text("'ask'"))
    is_autopay_default: Mapped[bool] = mapped_column(server_default=text("false"))
    online_sale_mode: Mapped[str] = enum_column(server_default=text("'off'"))
    is_members_only_online: Mapped[bool] = mapped_column(server_default=text("false"))
    is_members_only_at_desk: Mapped[bool] = mapped_column(server_default=text("false"))
    discount_pct: Mapped[Decimal | None] = mapped_column(_Pct)
    discount_minor: Mapped[int | None]
    revenue_category_id: Mapped[UUID | None]
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    version: Mapped[int] = mapped_column(server_default=text("1"))


class PackageSeries(TenantOwned, Timestamps, Base):
    """One sold recurring plan: each period's package is materialised by the daily job, not pre-created."""

    __tablename__ = "package_series"
    __table_args__ = tenant_args(
        *tfk("owner_client_id", "client"),
        *tfk("package_plan_id", "package_plan"),
        *tfk("location_id", "location"),
        enum_check("invoice_mode", SeriesInvoiceMode),
        enum_check("status", SeriesStatus),
        CheckConstraint("occurrences_generated_count <= occurrences_total_count", name="occurrences"),
        Index("ix_package_series_due", "tenant_id", "next_period_start_on", postgresql_where=text("status = 'active'")),
    )

    owner_client_id: Mapped[UUID]
    package_plan_id: Mapped[UUID]
    location_id: Mapped[UUID]
    occurrences_total_count: Mapped[int]
    occurrences_generated_count: Mapped[int] = mapped_column(server_default=text("0"))
    next_period_start_on: Mapped[date | None]
    invoice_mode: Mapped[str] = enum_column()
    is_auto_renew: Mapped[bool] = mapped_column(server_default=text("false"))
    status: Mapped[str] = enum_column(server_default=text("'active'"))


class ClientPackage(TenantOwned, Timestamps, Base):
    """A sold package: snapshot of terms, validity and the cached balance of its credit ledger."""

    __tablename__ = "client_package"
    __table_args__ = tenant_args(
        *tfk("owner_client_id", "client", index=False),
        *tfk("location_id", "location", index=False),
        *tfk("package_plan_id", "package_plan"),
        *tfk("package_series_id", "package_series", index=False),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("charge_id", "charge"),
        *tfk("renews_as_plan_id", "package_plan"),
        *tfk("previous_package_id", "client_package", index=False),
        *tfk("source_contract_id", "membership_contract", index=False),
        *tfk("source_contract_addon_id", "membership_contract_addon", index=False),
        *tfk("sold_by_staff_user_id", "staff_user"),
        *tfk("client_document_id", "client_document"),
        *tfk("removed_by_staff_user_id", "staff_user"),
        enum_check("fee_basis", FeeBasis),
        enum_check("invoice_mode", PackageInvoiceMode),
        enum_check("share_mode", PackageShareMode),
        enum_check("auto_renew_lead_unit", Unit),
        enum_check("renewal_target", RenewalTarget),
        enum_check("auto_renew_disabled_by", DisabledBy),
        enum_check("sales_channel", SalesChannel),
        enum_check("status", PackageStatus),
        enum_check("removal_mode", RemovalMode),
        UniqueConstraint("tenant_id", "package_series_id", "series_sequence_number"),
        # Mapped to problem code `package-exhausted`: the last line of defence behind the row lock.
        CheckConstraint(
            "sessions_reserved_count >= 0 AND sessions_consumed_count >= 0 AND sessions_forfeited_count >= 0 AND "
            "(is_unlimited OR sessions_granted_count - sessions_reserved_count - sessions_consumed_count - "
            "sessions_forfeited_count >= 0)",
            name="balance",
        ),
        CheckConstraint("NOT isempty(valid_during) AND lower(valid_during) IS NOT NULL", name="valid"),
        CheckConstraint("(status = 'removed') = (removed_at IS NOT NULL)", name="removed"),
        CheckConstraint("price_minor >= 0", name="price_minor"),
        CheckConstraint("(renewal_target = 'plan') = (renews_as_plan_id IS NOT NULL)", name="renewal"),
        *tfk("reservation_type_id", "reservation_type", index=False),
        Index("ix_client_package_owner", "tenant_id", "owner_client_id", "status", "id"),
        Index(
            "ix_client_package_spendable", "tenant_id", "owner_client_id", "reservation_type_id",
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_client_package_expiry_due", "tenant_id", text("upper(valid_during)"),
            postgresql_where=text("status IN ('active', 'exhausted')"),
        ),
        Index(
            "ix_client_package_renew_due", "tenant_id", "renew_on",
            postgresql_where=text("is_auto_renew AND status IN ('active', 'exhausted')"),
        ),
        Index(
            "ix_client_package_contract", "tenant_id", "source_contract_id",
            postgresql_where=text("source_contract_id IS NOT NULL"),
        ),
        Index("ix_client_package_location", "tenant_id", "location_id", "id"),
        Index(
            "uq_client_package_previous", "tenant_id", "previous_package_id", unique=True,
            postgresql_where=text("previous_package_id IS NOT NULL"),
        ),
        Index(
            "uq_client_package_contract_addon", "tenant_id", "source_contract_addon_id", unique=True,
            postgresql_where=text("source_contract_addon_id IS NOT NULL"),
        ),
    )  # fmt: skip

    owner_client_id: Mapped[UUID]
    location_id: Mapped[UUID]
    package_plan_id: Mapped[UUID | None]
    package_series_id: Mapped[UUID | None]
    series_sequence_number: Mapped[int | None]
    reservation_type_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    invoice_description: Mapped[str | None]
    internal_remarks: Mapped[str | None]
    is_unlimited: Mapped[bool] = mapped_column(server_default=text("false"))
    sessions_granted_count: Mapped[int] = mapped_column(server_default=text("0"))
    sessions_reserved_count: Mapped[int] = mapped_column(server_default=text("0"))
    sessions_consumed_count: Mapped[int] = mapped_column(server_default=text("0"))
    sessions_forfeited_count: Mapped[int] = mapped_column(server_default=text("0"))
    valid_during: Mapped[Range[date]] = mapped_column(DATERANGE)
    allows_booking_after_expiry: Mapped[bool] = mapped_column(server_default=text("false"))
    price_minor: Mapped[int] = mapped_column(server_default=text("0"))
    fee_basis: Mapped[str | None] = enum_column()
    unit_price_minor: Mapped[int | None]
    is_complimentary: Mapped[bool] = mapped_column(server_default=text("false"))
    revenue_category_id: Mapped[UUID | None]
    invoice_mode: Mapped[str] = enum_column(server_default=text("'single'"))
    charge_id: Mapped[UUID | None]
    is_autopay: Mapped[bool] = mapped_column(server_default=text("false"))
    share_mode: Mapped[str] = enum_column(server_default=text("'none'"))
    is_auto_renew: Mapped[bool] = mapped_column(server_default=text("false"))
    auto_renew_lead_count: Mapped[int | None]
    auto_renew_lead_unit: Mapped[str | None] = enum_column()
    renew_on: Mapped[date | None]
    renewal_target: Mapped[str] = enum_column(server_default=text("'same_terms'"))
    renews_as_plan_id: Mapped[UUID | None]
    renewal_threshold_count: Mapped[int | None]
    is_auto_renew_on_threshold: Mapped[bool] = mapped_column(server_default=text("false"))
    renewal_flagged_at: Mapped[datetime | None]
    auto_renew_disabled_by: Mapped[str | None] = enum_column()
    previous_package_id: Mapped[UUID | None]
    source_contract_id: Mapped[UUID | None]
    source_contract_addon_id: Mapped[UUID | None]
    sold_by_staff_user_id: Mapped[UUID | None]
    sales_channel: Mapped[str] = enum_column(server_default=text("'staff'"))
    client_document_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    removed_at: Mapped[datetime | None]
    removal_mode: Mapped[str | None] = enum_column()
    removed_by_staff_user_id: Mapped[UUID | None]
    version: Mapped[int] = mapped_column(server_default=text("1"))


class CreditLedgerEntry(TenantOwned, Base):
    """Append-only: every movement of session credits. The counters on client_package cache these sums."""

    __tablename__ = "credit_ledger_entry"
    __table_args__ = tenant_args(
        *tfk("client_package_id", "client_package", index=False),
        *tfk("client_id", "client"),
        enum_check("entry_type", EntryType),
        enum_check("reason", EntryReason),
        enum_check("source_type", SourceType),
        enum_check("actor_type", ActorType),
        CheckConstraint("(source_type IS NULL) = (source_id IS NULL)", name="source"),
        CheckConstraint(
            "CASE entry_type "
            "WHEN 'grant' THEN granted_delta > 0 AND reserved_delta = 0 AND consumed_delta = 0 AND forfeited_delta = 0 "
            "WHEN 'reserve' THEN granted_delta = 0 AND reserved_delta = 1 AND consumed_delta = 0 AND forfeited_delta = 0 "
            "WHEN 'release' THEN granted_delta = 0 AND reserved_delta = -1 AND consumed_delta = 0 AND forfeited_delta = 0 "
            "WHEN 'consume' THEN granted_delta = 0 AND reserved_delta = -1 AND consumed_delta = 1 AND forfeited_delta = 0 "
            "WHEN 'restore' THEN granted_delta = 0 AND reserved_delta = 0 AND consumed_delta = -1 AND forfeited_delta = 0 "
            "WHEN 'forfeit' THEN granted_delta = 0 AND reserved_delta = 0 AND consumed_delta = 0 AND forfeited_delta > 0 "
            "ELSE granted_delta <> 0 AND reserved_delta = 0 AND consumed_delta = 0 AND forfeited_delta = 0 END",
            name="shape",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_credit_ledger_entry_key"),
        Index("ix_credit_ledger_entry_package", "tenant_id", "client_package_id", "occurred_at"),
        Index(
            "ix_credit_ledger_entry_source", "tenant_id", "source_type", "source_id",
            postgresql_where=text("source_id IS NOT NULL"),
        ),
    )  # fmt: skip

    client_package_id: Mapped[UUID]
    client_id: Mapped[UUID]
    entry_type: Mapped[str] = enum_column()
    granted_delta: Mapped[int] = mapped_column(server_default=text("0"))
    reserved_delta: Mapped[int] = mapped_column(server_default=text("0"))
    consumed_delta: Mapped[int] = mapped_column(server_default=text("0"))
    forfeited_delta: Mapped[int] = mapped_column(server_default=text("0"))
    reason: Mapped[str] = enum_column()
    source_type: Mapped[str | None] = enum_column()
    source_id: Mapped[UUID | None]
    idempotency_key: Mapped[str] = mapped_column(info={"audit": "value"})
    actor_type: Mapped[str] = enum_column()
    actor_id: Mapped[UUID | None]
    note: Mapped[str | None] = mapped_column(info=_FLAG)
    occurred_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class PackageShare(TenantOwned, Timestamps, Base):
    __tablename__ = "package_share"
    __table_args__ = tenant_args(
        *tfk("client_package_id", "client_package", ondelete="CASCADE"),
        *tfk("client_id", "client", index=False),
        *tfk("added_by_staff_user_id", "staff_user"),
        enum_check("origin", ShareOrigin),
        Index(
            "uq_package_share_active", "tenant_id", "client_package_id", "client_id", unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_package_share_client", "tenant_id", "client_id", postgresql_where=text("revoked_at IS NULL")),
    )  # fmt: skip

    client_package_id: Mapped[UUID]
    client_id: Mapped[UUID]
    origin: Mapped[str] = enum_column(server_default=text("'manual'"))
    added_by_staff_user_id: Mapped[UUID | None]
    revoked_at: Mapped[datetime | None]


class PackageSettings(TenantOwned, Timestamps, Base):
    __tablename__ = "package_settings"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", name="uq_package_settings_tenant"),
        CheckConstraint("expiry_notice_days BETWEEN 0 AND 365", name="expiry_notice_days"),
    )

    is_late_cancel_charged: Mapped[bool] = mapped_column(server_default=text("true"))
    is_no_show_charged: Mapped[bool] = mapped_column(server_default=text("true"))
    is_account_credit_applied_by_default: Mapped[bool] = mapped_column(server_default=text("true"))
    expiry_notice_days: Mapped[int] = mapped_column(server_default=text("7"))
