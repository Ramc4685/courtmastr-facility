"""programs tables, session-target subset (docs/architecture/data-model-programs.md 1.9 to 1.11). Columns
for groups, fees, packages, checkout and forms arrive with build module 6; names and vocabularies are final."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, func, text
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
        enum_check("status", EnrollmentStatus),
        enum_check("pricing", Pricing),
        enum_check("channel", Channel),
        enum_check("cancel_kind", CancelKind),
        CheckConstraint("target_kind = 'session' AND session_id IS NOT NULL", name="target"),
        CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="cancel"),
        Index(
            "uq_enrollment_session_client", "tenant_id", "session_id", "client_id", unique=True,
            postgresql_where=text("status IN ('pending', 'enrolled') AND target_kind = 'session'"),
        ),
        Index("ix_enrollment_client", "tenant_id", "client_id", "status", "id"),
        Index("ix_enrollment_session_roster", "tenant_id", "session_id", "status", "id"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    client_id: Mapped[UUID]
    target_kind: Mapped[str] = enum_column(server_default=text("'session'"))
    session_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'enrolled'"))
    pricing: Mapped[str] = enum_column()
    channel: Mapped[str] = enum_column()
    enrolled_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancel_kind: Mapped[str | None] = enum_column()
    cancel_reason: Mapped[str | None]


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
        enum_check("status", WaitlistStatus),
        enum_check("mode", WaitlistMode),
        enum_check("channel", Channel),
        CheckConstraint("target_kind = 'session' AND session_id IS NOT NULL", name="target"),
        Index(
            "uq_waitlist_entry_session_client", "tenant_id", "session_id", "client_id", unique=True,
            postgresql_where=text("status IN ('waiting', 'offered')"),
        ),
        Index("ix_waitlist_entry_session_queue", "tenant_id", "session_id", "status", "queued_at", "id"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    client_id: Mapped[UUID]
    target_kind: Mapped[str] = enum_column(server_default=text("'session'"))
    session_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'waiting'"))
    mode: Mapped[str] = enum_column()
    queued_at: Mapped[datetime] = mapped_column(server_default=func.now())
    channel: Mapped[str] = enum_column()
    promoted_enrollment_id: Mapped[UUID | None]
    removed_reason: Mapped[str | None]
