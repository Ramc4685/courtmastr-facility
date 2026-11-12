"""programs tables (docs/architecture/data-model-programs.md 1.2 to 1.12). Build module 6 added groups, fees,
registration config, checkout and the session booking policy; forms, classifiers and roster invites (P1) are
not built, and no column here is renamed when they arrive."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Index, SmallInteger, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk


class EnrollmentStatus(StrEnum):
    PENDING = "pending"
    ENROLLED = "enrolled"
    CANCELLED = "cancelled"


class Pricing(StrEnum):
    FEE = "fee"
    ENTITLEMENT = "entitlement"
    FREE = "free"


class Channel(StrEnum):
    STAFF = "staff"
    PORTAL = "portal"
    MOBILE = "mobile"
    PUBLIC_LINK = "public_link"
    KIOSK = "kiosk"
    API = "api"
    WAITLIST = "waitlist"
    ROSTER_INVITE = "roster_invite"


class CancelKind(StrEnum):
    EARLY = "early"
    LATE = "late"
    STAFF_REMOVED = "staff_removed"
    SESSION_CANCELLED = "session_cancelled"
    HOLD_EXPIRED = "hold_expired"
    DEMOTED_TO_WAITLIST = "demoted_to_waitlist"
    PAYMENT_REFUNDED = "payment_refunded"
    CLIENT_MERGED = "client_merged"


class BookedScope(StrEnum):
    SINGLE = "single"
    ALL_LINKED = "all_linked"
    CUSTOM = "custom"


class BillingDisposition(StrEnum):
    REVERSED = "reversed"
    KEPT = "kept"
    NONE = "none"


class ActorType(StrEnum):
    STAFF = "staff"
    CLIENT = "client"
    SYSTEM = "system"


class TargetKind(StrEnum):
    GROUP = "group"
    SESSION = "session"


class GroupKind(StrEnum):
    PROGRAM = "program"
    CAMP = "camp"
    CLINIC = "clinic"
    CLASS_SERIES = "class_series"
    COMPETITION = "competition"
    TEAM = "team"
    OTHER = "other"


class GroupStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class GroupWaitlistMode(StrEnum):
    DISABLED = "disabled"
    MANUAL = "manual"
    AUTO_PROMOTE = "auto_promote"


class FeeKind(StrEnum):
    INDIVIDUAL = "individual"
    JOIN_SUBGROUP = "join_subgroup"
    NEW_SUBGROUP = "new_subgroup"


class PaymentRequirement(StrEnum):
    PAY_LATER_ALLOWED = "pay_later_allowed"
    IMMEDIATE_CARD_PAYMENT = "immediate_card_payment"
    CARD_REQUIRED_CHARGE_OPTIONAL = "card_required_charge_optional"
    CARD_REQUIRED_NO_CHARGE = "card_required_no_charge"


class CheckoutChannel(StrEnum):
    STAFF = "staff"
    PORTAL = "portal"
    PUBLIC_LINK = "public_link"
    MOBILE = "mobile"
    API = "api"


class CheckoutStatus(StrEnum):
    OPEN = "open"
    AWAITING_PAYMENT = "awaiting_payment"
    COMPLETED = "completed"
    EXPIRED = "expired"
    ABANDONED = "abandoned"


class ListingMode(StrEnum):
    BOOKABLE = "bookable"
    LIST_ONLY = "list_only"
    UNLISTED = "unlisted"
    HIDDEN = "hidden"


class PolicyWaitlistMode(StrEnum):
    DISABLED = "disabled"
    AUTO_PROMOTE = "auto_promote"
    OPEN_OFFER = "open_offer"


class AttendanceStatus(StrEnum):
    ATTENDED = "attended"
    NO_SHOW = "no_show"
    EXCUSED = "excused"


class AttendanceSource(StrEnum):
    STAFF = "staff"
    CHECK_IN = "check_in"
    KIOSK = "kiosk"
    VIDEO_JOIN = "video_join"
    API = "api"


class WaitlistStatus(StrEnum):
    WAITING = "waiting"
    OFFERED = "offered"
    PROMOTED = "promoted"
    EXPIRED = "expired"
    REMOVED = "removed"


class WaitlistMode(StrEnum):
    MANUAL = "manual"
    AUTO_PROMOTE = "auto_promote"
    OPEN_OFFER = "open_offer"


class Enrollment(TenantOwned, Timestamps, Base):
    """A client's place in a session: the roster row. The seat itself is counted by scheduling."""

    __tablename__ = "enrollment"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("client_id", "client", index=False),
        *tfk("session_id", "session", index=False),
        *tfk("program_group_id", "program_group", index=False),
        *tfk("program_fee_id", "program_fee"),
        *tfk("charge_id", "charge"),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("payer_client_id", "client"),
        *tfk("checkout_id", "registration_checkout"),
        enum_check("status", EnrollmentStatus),
        enum_check("pricing", Pricing),
        enum_check("channel", Channel),
        enum_check("cancel_kind", CancelKind),
        enum_check("target_kind", TargetKind),
        enum_check("booked_scope", BookedScope),
        enum_check("billing_disposition", BillingDisposition),
        enum_check("cancelled_by_actor_type", ActorType),
        CheckConstraint(
            "(target_kind = 'group' AND program_group_id IS NOT NULL AND session_id IS NULL)"
            " OR (target_kind = 'session' AND session_id IS NOT NULL AND program_group_id IS NULL)",
            name="target",
        ),
        CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="cancel"),
        CheckConstraint("status <> 'pending' OR hold_expires_at IS NOT NULL", name="hold"),
        Index(
            "uq_enrollment_session_client", "tenant_id", "session_id", "client_id", unique=True,
            postgresql_where=text("status IN ('pending', 'enrolled') AND target_kind = 'session'"),
        ),
        Index(
            "uq_enrollment_group_client", "tenant_id", "program_group_id", "client_id", unique=True,
            postgresql_where=text("status IN ('pending', 'enrolled') AND target_kind = 'group'"),
        ),
        Index("ix_enrollment_client", "tenant_id", "client_id", "status", "id"),
        Index("ix_enrollment_session_roster", "tenant_id", "session_id", "status", "id"),
        Index("ix_enrollment_group_roster", "tenant_id", "program_group_id", "status", "id"),
        Index("ix_enrollment_hold_expiry", "hold_expires_at", postgresql_where=text("status = 'pending'")),
        Index("ix_enrollment_batch", "tenant_id", "batch_id", postgresql_where=text("batch_id IS NOT NULL")),
    )  # fmt: skip

    location_id: Mapped[UUID]
    client_id: Mapped[UUID]
    target_kind: Mapped[str] = enum_column(server_default=text("'session'"))
    session_id: Mapped[UUID | None]
    program_group_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'enrolled'"))
    pricing: Mapped[str] = enum_column()
    program_fee_id: Mapped[UUID | None]
    charge_id: Mapped[UUID | None]
    revenue_category_id: Mapped[UUID | None]
    payer_client_id: Mapped[UUID | None]
    checkout_id: Mapped[UUID | None]
    batch_id: Mapped[UUID | None]
    booked_scope: Mapped[str] = enum_column(server_default=text("'single'"))
    channel: Mapped[str] = enum_column()
    registrant_comment: Mapped[str | None]
    hold_expires_at: Mapped[datetime | None]
    enrolled_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancel_kind: Mapped[str | None] = enum_column()
    cancel_reason: Mapped[str | None]
    billing_disposition: Mapped[str | None] = enum_column()
    cancelled_by_actor_type: Mapped[str | None] = enum_column()


class Attendance(TenantOwned, Timestamps, Base):
    """Attendance mark for one participant at one session; a missing row means scheduled, not yet marked."""

    __tablename__ = "attendance"
    __table_args__ = tenant_args(
        *tfk("enrollment_id", "enrollment", ondelete="CASCADE", index=False),
        *tfk("session_id", "session", index=False),
        *tfk("client_id", "client", index=False),
        *tfk("marked_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "enrollment_id", "session_id", name="uq_attendance_enrollment_session"),
        enum_check("status", AttendanceStatus),
        enum_check("source", AttendanceSource),
        Index("ix_attendance_session", "tenant_id", "session_id", "status"),
        Index("ix_attendance_client", "tenant_id", "client_id", "marked_at"),
    )

    enrollment_id: Mapped[UUID]
    session_id: Mapped[UUID]
    client_id: Mapped[UUID]
    status: Mapped[str] = enum_column()
    source: Mapped[str] = enum_column(server_default=text("'staff'"))
    marked_at: Mapped[datetime] = mapped_column(server_default=func.now())
    marked_by_staff_user_id: Mapped[UUID | None]


class WaitlistEntry(TenantOwned, Timestamps, Base):
    """FIFO queue for a full session. A waiting client holds no seat, no credit and no charge."""

    __tablename__ = "waitlist_entry"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("client_id", "client"),
        *tfk("session_id", "session", index=False),
        *tfk("promoted_enrollment_id", "enrollment"),
        *tfk("program_group_id", "program_group", index=False),
        *tfk("program_fee_id", "program_fee"),
        *tfk("payer_client_id", "client"),
        enum_check("status", WaitlistStatus),
        enum_check("mode", WaitlistMode),
        enum_check("channel", Channel),
        enum_check("target_kind", TargetKind),
        CheckConstraint(
            "(target_kind = 'group' AND program_group_id IS NOT NULL AND session_id IS NULL)"
            " OR (target_kind = 'session' AND session_id IS NOT NULL AND program_group_id IS NULL)",
            name="target",
        ),
        Index(
            "uq_waitlist_entry_session_client", "tenant_id", "session_id", "client_id", unique=True,
            postgresql_where=text("status IN ('waiting', 'offered')"),
        ),
        Index(
            "uq_waitlist_entry_group_client", "tenant_id", "program_group_id", "client_id", unique=True,
            postgresql_where=text("status IN ('waiting', 'offered')"),
        ),
        Index("ix_waitlist_entry_session_queue", "tenant_id", "session_id", "status", "queued_at", "id"),
        Index("ix_waitlist_entry_group_queue", "tenant_id", "program_group_id", "status", "queued_at", "id"),
        Index("ix_waitlist_entry_offer_expiry", "offer_expires_at", postgresql_where=text("status = 'offered'")),
    )  # fmt: skip

    location_id: Mapped[UUID]
    client_id: Mapped[UUID]
    target_kind: Mapped[str] = enum_column(server_default=text("'session'"))
    session_id: Mapped[UUID | None]
    program_group_id: Mapped[UUID | None]
    program_fee_id: Mapped[UUID | None]
    payer_client_id: Mapped[UUID | None]
    offered_at: Mapped[datetime | None]
    offer_expires_at: Mapped[datetime | None]
    status: Mapped[str] = enum_column(server_default=text("'waiting'"))
    mode: Mapped[str] = enum_column()
    queued_at: Mapped[datetime] = mapped_column(server_default=func.now())
    channel: Mapped[str] = enum_column()
    promoted_enrollment_id: Mapped[UUID | None]
    removed_reason: Mapped[str | None]


class ProgramGroup(TenantOwned, Timestamps, Base):
    """A registerable container (program, camp, clinic, league) or a child node such as a team (REG-01, REG-02).
    `enrolled_count` counts live enrolments of this node and its descendants; the checks are the capacity guard."""

    __tablename__ = "program_group"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("parent_id", "program_group"),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("deleted_by_staff_user_id", "staff_user"),
        enum_check("kind", GroupKind),
        enum_check("status", GroupStatus),
        enum_check("waitlist_mode", GroupWaitlistMode),
        CheckConstraint("capacity IS NULL OR enrolled_count <= capacity", name="capacity"),
        CheckConstraint("max_children IS NULL OR child_count <= max_children", name="children"),
        CheckConstraint("enrolled_count >= 0 AND child_count >= 0", name="counts"),
        CheckConstraint("(parent_id IS NULL) = (depth = 0)", name="root"),
        CheckConstraint("depth BETWEEN 0 AND 5", name="depth"),
        CheckConstraint("ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on", name="span"),
        Index(
            "uq_program_group_sibling_name", "tenant_id", "parent_id", text("lower(name)"), unique=True,
            postgresql_where=text("parent_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("ix_program_group_list", "tenant_id", "location_id", "status", "id", postgresql_where=text("deleted_at IS NULL")),
        Index(
            "ix_program_group_auto_archive", "auto_archive_on",
            postgresql_where=text("status = 'active' AND auto_archive_on IS NOT NULL AND deleted_at IS NULL"),
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    parent_id: Mapped[UUID | None]
    depth: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    kind: Mapped[str] = enum_column(server_default=text("'program'"))
    name: Mapped[str]
    description: Mapped[str | None]
    child_label: Mapped[str] = mapped_column(server_default=text("'Team'"))
    revenue_category_id: Mapped[UUID | None]
    capacity: Mapped[int | None]
    max_children: Mapped[int | None]
    enrolled_count: Mapped[int] = mapped_column(server_default=text("0"))
    child_count: Mapped[int] = mapped_column(server_default=text("0"))
    price_minor: Mapped[int | None] = mapped_column(BigInteger)
    contact_name: Mapped[str | None]
    contact_email: Mapped[str | None]
    starts_on: Mapped[date | None]
    ends_on: Mapped[date | None]
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    auto_archive_on: Mapped[date | None]
    completed_at: Mapped[datetime | None]
    waitlist_mode: Mapped[str | None] = enum_column()
    deleted_at: Mapped[datetime | None]
    deleted_by_staff_user_id: Mapped[UUID | None]


class ProgramSession(TenantOwned, Timestamps, Base):
    """A scheduling session that belongs to a group node (camp day, clinic meeting). Group enrolment takes a seat
    in each linked session, so drop-ins and registrants share one counter (CLS-10)."""

    __tablename__ = "program_session"
    __table_args__ = tenant_args(
        *tfk("program_group_id", "program_group", ondelete="CASCADE", index=False),
        *tfk("session_id", "session", index=False),
        UniqueConstraint("tenant_id", "session_id", name="uq_program_session_session"),
        UniqueConstraint("tenant_id", "program_group_id", "sequence_no", name="uq_program_session_group_seq"),
    )

    program_group_id: Mapped[UUID]
    session_id: Mapped[UUID]
    sequence_no: Mapped[int]


class ProgramFee(TenantOwned, Timestamps, Base):
    """A fee: the location's staff catalogue (`program_group_id` null) or a group's own fees (REG-07, REG-10)."""

    __tablename__ = "program_fee"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("program_group_id", "program_group", ondelete="CASCADE"),
        *tfk("revenue_category_id", "revenue_category"),
        enum_check("fee_kind", FeeKind),
        CheckConstraint("amount_minor >= 0", name="amount"),
        CheckConstraint("deposit_minor IS NULL OR deposit_minor BETWEEN 0 AND amount_minor", name="deposit"),
    )

    location_id: Mapped[UUID]
    program_group_id: Mapped[UUID | None]
    fee_kind: Mapped[str] = enum_column(server_default=text("'individual'"))
    description: Mapped[str]
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    deposit_minor: Mapped[int | None] = mapped_column(BigInteger)
    revenue_category_id: Mapped[UUID | None]
    is_online: Mapped[bool] = mapped_column(server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class PaymentPlan(StrEnum):
    """How an online registration pays (REG-10, decision Q5): all now, a deposit now and the balance on a date,
    or a deposit now and the balance in equal instalments collected by autopay."""

    PAY_IN_FULL = "pay_in_full"
    DEPOSIT = "deposit"
    INSTALMENTS = "instalments"


class InstalmentUnit(StrEnum):
    WEEK = "week"
    HALF_MONTH = "half_month"
    MONTH = "month"


class RegistrationConfig(TenantOwned, Timestamps, Base):
    """Online registration and portal publication of one group node (REG-10, SSP-17)."""

    __tablename__ = "registration_config"
    __table_args__ = tenant_args(
        *tfk("program_group_id", "program_group", ondelete="CASCADE", index=False),
        enum_check("payment_requirement", PaymentRequirement),
        enum_check("payment_plan", PaymentPlan),
        enum_check("instalment_unit", InstalmentUnit),
        CheckConstraint("closes_on IS NULL OR opens_on IS NULL OR closes_on >= opens_on", name="window"),
        CheckConstraint(
            "payment_plan = 'pay_in_full' OR balance_due_on IS NOT NULL", name="balance_due_on"
        ),
        CheckConstraint(
            "(payment_plan = 'instalments') = (instalment_count IS NOT NULL AND instalment_unit IS NOT NULL)",
            name="instalments",
        ),
        CheckConstraint("instalment_count IS NULL OR instalment_count BETWEEN 2 AND 24", name="instalment_count"),
        UniqueConstraint("tenant_id", "program_group_id", name="uq_registration_config_program_group"),
        UniqueConstraint("tenant_id", "public_slug", name="uq_registration_config_public_slug"),
        Index("ix_registration_config_portal", "tenant_id", "is_portal_visible", postgresql_where=text("is_portal_visible")),
    )  # fmt: skip

    program_group_id: Mapped[UUID]
    is_enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    opens_on: Mapped[date | None]
    closes_on: Mapped[date | None]
    payment_requirement: Mapped[str] = enum_column(server_default=text("'immediate_card_payment'"))
    displays_openings: Mapped[bool] = mapped_column(server_default=text("false"))
    online_description: Mapped[str | None]
    closed_message: Mapped[str | None]
    confirmation_message: Mapped[str | None]
    public_slug: Mapped[str]
    is_portal_visible: Mapped[bool] = mapped_column(server_default=text("false"))
    portal_publish_name: Mapped[str | None]
    portal_published_at: Mapped[datetime | None]
    payment_plan: Mapped[str] = enum_column(server_default=text("'pay_in_full'"))
    balance_due_on: Mapped[date | None]
    instalment_count: Mapped[int | None] = mapped_column(SmallInteger)
    instalment_unit: Mapped[str | None] = enum_column(nullable=True)


class RegistrationCheckout(TenantOwned, Timestamps, Base):
    """One checkout attempt: the cart. Its lines are pending enrolments holding their places until expiry; the
    confirm step bills them to one payer on one invoice (REG-07, REG-12)."""

    __tablename__ = "registration_checkout"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("payer_client_id", "client"),
        *tfk("invoice_id", "invoice"),
        enum_check("channel", CheckoutChannel),
        enum_check("status", CheckoutStatus),
        Index(
            "ix_registration_checkout_expiry", "expires_at",
            postgresql_where=text("status IN ('open', 'awaiting_payment')"),
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    channel: Mapped[str] = enum_column()
    identity_id: Mapped[UUID | None]
    payer_client_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'open'"))
    invoice_id: Mapped[UUID | None]
    comment: Mapped[str | None]
    expires_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]


class SessionBookingPolicy(TenantOwned, Timestamps, Base):
    """Self-service rules for booking sessions: a location default row and per-reservation-type overrides whose
    null columns inherit (CLS-09, SSP-02, SSP-03)."""

    __tablename__ = "session_booking_policy"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("reservation_type_id", "reservation_type"),
        enum_check("listing_mode", ListingMode),
        enum_check("waitlist_mode", PolicyWaitlistMode),
        CheckConstraint("visible_range_days IS NULL OR visible_range_days BETWEEN 1 AND 730", name="range"),
        CheckConstraint("booking_cutoff_minutes IS NULL OR booking_cutoff_minutes >= 0", name="cutoff"),
        CheckConstraint("cancel_notice_minutes IS NULL OR cancel_notice_minutes >= 0", name="notice"),
        CheckConstraint(
            "reservation_type_id IS NOT NULL OR (listing_mode IS NOT NULL AND requires_active_membership IS NOT NULL"
            " AND visible_range_days IS NOT NULL AND hides_full_sessions IS NOT NULL AND booking_cutoff_minutes IS NOT NULL"
            " AND allows_self_cancel IS NOT NULL AND cancel_notice_minutes IS NOT NULL AND waitlist_mode IS NOT NULL)",
            name="default_complete",
        ),
        Index(
            "uq_session_booking_policy_location_type", "tenant_id", "location_id", "reservation_type_id",
            unique=True, postgresql_nulls_not_distinct=True,
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    reservation_type_id: Mapped[UUID | None]
    listing_mode: Mapped[str | None] = enum_column()
    requires_active_membership: Mapped[bool | None]
    visible_range_days: Mapped[int | None]
    hides_full_sessions: Mapped[bool | None]
    booking_cutoff_minutes: Mapped[int | None]
    allows_self_cancel: Mapped[bool | None]
    cancel_notice_minutes: Mapped[int | None]
    waitlist_mode: Mapped[str | None] = enum_column()
