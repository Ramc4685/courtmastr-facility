"""scheduling tables (docs/architecture/data-model-core.md section 4), plus `reservation_type_grant` (SCH-05,
README assumption 11)."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, SmallInteger, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JsonDict, TenantOwned, Timestamps, WallTime, enum_check, enum_column, tenant_args, tfk


class BookingKind(StrEnum):
    SESSION = "session"
    RENTAL = "rental"
    BLOCK = "block"
    GAME = "game"


class BlockKind(StrEnum):
    FLOOR_SHIFT = "floor_shift"
    INSTRUCTION = "instruction"
    UNPAID = "unpaid"
    UNAVAILABLE = "unavailable"


class BookingStatus(StrEnum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class CancelReason(StrEnum):
    STAFF = "staff"
    CLIENT = "client"
    HOLD_EXPIRED = "hold_expired"
    PAYMENT_FAILED = "payment_failed"
    SERIES_EDIT = "series_edit"
    OTHER = "other"


class CreatedVia(StrEnum):
    STAFF = "staff"
    PORTAL = "portal"
    MOBILE = "mobile"
    API = "api"
    SYSTEM = "system"


class Pattern(StrEnum):
    SINGLE = "single"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY_BY_DATE = "monthly_by_date"
    MONTHLY_BY_WEEKDAY = "monthly_by_weekday"
    YEARLY = "yearly"


class RangeType(StrEnum):
    COUNT = "count"
    UNTIL = "until"


class RuleStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class RunKind(StrEnum):
    GENERATE = "generate"
    EDIT = "edit"
    CANCEL = "cancel"
    PREVIEW = "preview"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class HoldOrigin(StrEnum):
    BOOKED = "booked"
    LINKED = "linked"
    DESCENDANT = "descendant"


class DragDropDefault(StrEnum):
    ASK = "ask"
    RESCHEDULE = "reschedule"
    MOVE_ENROLLMENT = "move_enrollment"


class Attendance(StrEnum):
    SCHEDULED = "scheduled"
    ATTENDED = "attended"
    NO_SHOW = "no_show"


class BlackoutScope(StrEnum):
    ALL = "all"
    ONLINE_ONLY = "online_only"


def _int(default: int) -> Mapped[int]:
    return mapped_column(server_default=text(str(default)))


def _small(default: int) -> Mapped[int]:
    return mapped_column(SmallInteger, server_default=text(str(default)))


def _flag(default: bool) -> Mapped[bool]:
    return mapped_column(server_default=text("true" if default else "false"))


_BUFFERS = "buffer_before_min BETWEEN 0 AND 240 AND buffer_after_min BETWEEN 0 AND 240"


class SchedulingSettings(TenantOwned, Timestamps, Base):
    """One tenant-default row (location_id NULL); a location row overrides it whole."""

    __tablename__ = "scheduling_settings"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        Index("uq_scheduling_settings", "tenant_id", "location_id", unique=True, postgresql_nulls_not_distinct=True),
        CheckConstraint(
            "default_buffer_before_min BETWEEN 0 AND 240 AND default_buffer_after_min BETWEEN 0 AND 240",
            name="buffers",
        ),
        CheckConstraint("calendar_slot_min IN (5, 10, 15, 20, 30, 60)", name="calendar_slot"),
        CheckConstraint("checkout_hold_min BETWEEN 5 AND 30", name="checkout_hold"),
        CheckConstraint("max_series_occurrences BETWEEN 1 AND 2000", name="max_series"),
        enum_check("drag_drop_default", DragDropDefault),
    )

    location_id: Mapped[UUID | None]
    default_buffer_before_min: Mapped[int] = _small(0)
    default_buffer_after_min: Mapped[int] = _small(0)
    drag_drop_default: Mapped[str] = enum_column(server_default=text("'ask'"))
    calendar_slot_min: Mapped[int] = _small(15)
    checkout_hold_min: Mapped[int] = _small(10)
    max_series_occurrences: Mapped[int] = _int(2000)


class ReservationCategory(TenantOwned, Timestamps, Base):
    __tablename__ = "reservation_category"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("parent_id", "reservation_category"),
        Index(
            "uq_reservation_category_name", "tenant_id", "location_id", "parent_id", "name", unique=True,
            postgresql_where=text("is_active"), postgresql_nulls_not_distinct=True,
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    parent_id: Mapped[UUID | None]
    name: Mapped[str]
    sort_order: Mapped[int] = _int(0)
    is_active: Mapped[bool] = _flag(True)


class ReservationType(TenantOwned, Timestamps, Base):
    """The activity master. Every default is copied onto the booking or session at creation (CLS-04, SCH-14)."""

    __tablename__ = "reservation_type"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("reservation_category_id", "reservation_category"),
        Index(
            "uq_reservation_type_name", "tenant_id", "location_id", "name", unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_reservation_type_order", "tenant_id", "location_id", "sort_order"),
        CheckConstraint("default_capacity >= 0", name="capacity"),
        CheckConstraint("default_duration_min IS NULL OR default_duration_min > 0", name="duration"),
        CheckConstraint(_BUFFERS, name="buffers"),
        CheckConstraint("color ~ '^#[0-9a-f]{6}$'", name="color"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    is_schedulable: Mapped[bool] = _flag(True)
    is_sellable: Mapped[bool] = _flag(True)
    revenue_category_id: Mapped[UUID | None]
    reservation_category_id: Mapped[UUID | None]
    default_capacity: Mapped[int] = _int(1)
    default_duration_min: Mapped[int | None]
    default_allows_free_booking: Mapped[bool] = _flag(False)
    color: Mapped[str | None] = mapped_column(info={"audit": "value"})
    uses_default_buffer: Mapped[bool] = _flag(True)
    buffer_before_min: Mapped[int] = _small(0)
    buffer_after_min: Mapped[int] = _small(0)
    is_self_bookable_default: Mapped[bool] = _flag(True)
    sort_order: Mapped[int] = _int(0)
    is_active: Mapped[bool] = _flag(True)


class BookingSeries(TenantOwned, Timestamps, Base):
    """A linked set of occurrences, not a rule owner (ADR 0004 section 6)."""

    __tablename__ = "booking_series"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("created_by_staff_user_id", "staff_user"),
        enum_check("kind", BookingKind),
    )

    location_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    label: Mapped[str | None]
    created_by_staff_user_id: Mapped[UUID | None]
    occurrence_count: Mapped[int] = _int(0)


class BookingSeriesRule(TenantOwned, Timestamps, Base):
    """One generation pass; a series built by stacking patterns has several (SCH-09, SCH-10)."""

    __tablename__ = "booking_series_rule"
    __table_args__ = tenant_args(
        *tfk("booking_series_id", "booking_series", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "booking_series_id", "sequence", name="uq_booking_series_rule"),
        enum_check("pattern", Pattern),
        enum_check("range_type", RangeType),
        enum_check("status", RuleStatus),
        CheckConstraint(
            "(range_type = 'count' AND occurrence_limit > 0 AND until_on IS NULL) OR "
            "(range_type = 'until' AND until_on >= start_on AND occurrence_limit IS NULL)",
            name="range",
        ),
        CheckConstraint("end_day_offset > 0 OR end_time > start_time", name="span"),
        CheckConstraint("end_day_offset BETWEEN 0 AND 6", name="end_day_offset"),
        CheckConstraint("pattern <> 'weekly' OR cardinality(weekdays) > 0", name="weekly"),
        CheckConstraint("interval_count >= 1", name="interval"),
    )

    booking_series_id: Mapped[UUID]
    sequence: Mapped[int]
    pattern: Mapped[str] = enum_column()
    interval_count: Mapped[int] = _small(1)
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    month_week: Mapped[int | None] = mapped_column(SmallInteger)
    start_on: Mapped[date]
    start_time: Mapped[str] = mapped_column(WallTime)
    end_time: Mapped[str] = mapped_column(WallTime)
    end_day_offset: Mapped[int] = _small(0)
    range_type: Mapped[str] = enum_column()
    occurrence_limit: Mapped[int | None]
    until_on: Mapped[date | None]
    template: Mapped[dict] = mapped_column(JsonDict)
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    requested_count: Mapped[int] = _int(0)
    created_count: Mapped[int] = _int(0)
    conflict_count: Mapped[int] = _int(0)
    results: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class BookingSeriesRun(TenantOwned, Timestamps, Base):
    """One asynchronous series command; the resource behind status_url."""

    __tablename__ = "booking_series_run"
    __table_args__ = tenant_args(
        *tfk("booking_series_id", "booking_series", ondelete="CASCADE"),
        *tfk("booking_series_rule_id", "booking_series_rule", ondelete="CASCADE"),
        *tfk("requested_by_staff_user_id", "staff_user"),
        enum_check("kind", RunKind),
        enum_check("status", RunStatus),
    )

    booking_series_id: Mapped[UUID]
    booking_series_rule_id: Mapped[UUID | None]
    kind: Mapped[str] = enum_column()
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    command: Mapped[dict] = mapped_column(JsonDict)
    requested_count: Mapped[int] = _int(0)
    ok_count: Mapped[int] = _int(0)
    conflict_count: Mapped[int] = _int(0)
    results: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    requested_by_staff_user_id: Mapped[UUID | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class Booking(TenantOwned, Timestamps, Base):
    """One calendar occurrence of anything that occupies resources. Cancel is a status, never a delete."""

    __tablename__ = "booking"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("booking_series_id", "booking_series", index=False),
        *tfk("booking_series_rule_id", "booking_series_rule", index=False),
        *tfk("reservation_type_id", "reservation_type", index=False),
        *tfk("client_id", "client", index=False),
        *tfk("created_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "booking_number", name="uq_booking_number"),
        CheckConstraint("ends_at > starts_at", name="span"),
        CheckConstraint("duration_min > 0", name="duration"),
        CheckConstraint("booking_series_rule_id IS NULL OR occurrence_index IS NOT NULL", name="occurrence"),
        enum_check("kind", BookingKind),
        enum_check("status", BookingStatus),
        enum_check("block_kind", BlockKind),
        enum_check("cancel_reason", CancelReason),
        enum_check("created_via", CreatedVia),
        CheckConstraint("(kind = 'block') = (block_kind IS NOT NULL)", name="block"),
        CheckConstraint("kind = 'session' OR reservation_type_id IS NULL", name="type_only_on_session"),
        CheckConstraint("(status = 'tentative') = (expires_at IS NOT NULL)", name="tentative"),
        CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="cancelled"),
        CheckConstraint("(source_context IS NULL) = (source_id IS NULL)", name="source"),
        CheckConstraint(_BUFFERS, name="buffers"),
        Index(
            "uq_booking_series_rule_occurrence", "tenant_id", "booking_series_rule_id", "occurrence_index",
            unique=True, postgresql_where=text("booking_series_rule_id IS NOT NULL"),
        ),
        Index(
            "ix_booking_span", "tenant_id", "location_id", text("tstzrange(starts_at, ends_at, '[)')"),
            postgresql_using="gist", postgresql_where=text("status <> 'cancelled'"),
        ),
        Index("ix_booking_location_day", "tenant_id", "location_id", "occurrence_on", "id"),
        Index(
            "ix_booking_series", "tenant_id", "booking_series_id", "starts_at",
            postgresql_where=text("booking_series_id IS NOT NULL"),
        ),
        Index("ix_booking_client", "tenant_id", "client_id", "starts_at", postgresql_where=text("client_id IS NOT NULL")),
        Index(
            "ix_booking_source", "tenant_id", "source_context", "source_type", "source_id",
            postgresql_where=text("source_id IS NOT NULL"),
        ),
        Index(
            "ix_booking_type", "tenant_id", "reservation_type_id", "starts_at",
            postgresql_where=text("reservation_type_id IS NOT NULL"),
        ),
        Index("ix_booking_expiring", "expires_at", postgresql_where=text("status = 'tentative'")),
    )  # fmt: skip

    location_id: Mapped[UUID]
    booking_number: Mapped[int]
    booking_series_id: Mapped[UUID | None]
    booking_series_rule_id: Mapped[UUID | None]
    occurrence_index: Mapped[int | None]
    occurrence_on: Mapped[date]
    local_start_time: Mapped[str] = mapped_column(WallTime)
    duration_min: Mapped[int]
    kind: Mapped[str] = enum_column()
    block_kind: Mapped[str | None] = enum_column()
    reservation_type_id: Mapped[UUID | None]
    client_id: Mapped[UUID | None]
    title: Mapped[str] = mapped_column(server_default=text("''"))
    public_title: Mapped[str | None]
    notes: Mapped[str | None]
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    buffer_before_min: Mapped[int] = _small(0)
    buffer_after_min: Mapped[int] = _small(0)
    status: Mapped[str] = enum_column(server_default=text("'confirmed'"))
    expires_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None] = enum_column()
    created_via: Mapped[str] = enum_column()
    created_by_staff_user_id: Mapped[UUID | None]
    source_context: Mapped[str | None] = mapped_column(info={"audit": "value"})
    source_type: Mapped[str | None] = mapped_column(info={"audit": "value"})
    source_id: Mapped[UUID | None]
    version: Mapped[int] = _int(1)


class BookingParticipant(TenantOwned, Timestamps, Base):
    """SCH-17, SSP-09: one client on a shared booking (a couple, a team, invitees), with their own attendance.
    The booking's client is the organiser and pays; participants never move package credits here."""

    __tablename__ = "booking_participant"
    __table_args__ = tenant_args(
        *tfk("booking_id", "booking", ondelete="CASCADE", index=False),
        *tfk("location_id", "location", index=False),
        *tfk("client_id", "client", index=False),
        *tfk("added_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "booking_id", "client_id", name="uq_booking_participant"),
        enum_check("attendance", Attendance),
        Index("ix_booking_participant_client", "tenant_id", "client_id"),
    )

    booking_id: Mapped[UUID]
    location_id: Mapped[UUID]
    client_id: Mapped[UUID]
    attendance: Mapped[str] = enum_column(server_default=text("'scheduled'"))
    attendance_marked_at: Mapped[datetime | None]
    added_by_staff_user_id: Mapped[UUID | None]


class BookingResource(TenantOwned, Timestamps, Base):
    """The resources a booking was made on, as chosen. Survives cancellation (holds do not)."""

    __tablename__ = "booking_resource"
    __table_args__ = tenant_args(
        *tfk("booking_id", "booking", ondelete="CASCADE", index=False),
        *tfk("resource_id", "resource"),
        UniqueConstraint("tenant_id", "booking_id", "resource_id", name="uq_booking_resource"),
        Index(
            "uq_booking_resource_primary", "tenant_id", "booking_id", unique=True,
            postgresql_where=text("role = 'primary'"),
        ),
        CheckConstraint("role IN ('primary', 'additional')", name="role"),
    )  # fmt: skip

    booking_id: Mapped[UUID]
    resource_id: Mapped[UUID]
    role: Mapped[str] = enum_column(server_default=text("'additional'"))
    sort_order: Mapped[int] = _int(0)


class ResourceHold(TenantOwned, Timestamps, Base):
    """The constrained rows: one occupied interval on one resource. Written only by scheduling.service."""

    __tablename__ = "resource_hold"
    __table_args__ = tenant_args(
        *tfk("resource_id", "resource", index=False),
        *tfk("booking_id", "booking", ondelete="CASCADE", index=False),
        *tfk("source_resource_id", "resource"),
        UniqueConstraint("tenant_id", "booking_id", "resource_id", name="uq_resource_hold_booking_resource"),
        enum_check("origin", HoldOrigin),
        CheckConstraint(
            "NOT isempty(during) AND lower_inc(during) AND NOT upper_inc(during) "
            "AND NOT lower_inf(during) AND NOT upper_inf(during)",
            name="during",
        ),
        # Not deferrable: a reschedule deletes and re-inserts, one savepoint per occurrence (ADR 0004 section 1).
        ExcludeConstraint(
            ("tenant_id", "="), ("resource_id", "="), ("during", "&&"), name="ex_resource_hold_overlap", using="gist"
        ),
        Index("ix_resource_hold_expires_at", "expires_at", postgresql_where=text("expires_at IS NOT NULL")),
    )

    resource_id: Mapped[UUID]
    booking_id: Mapped[UUID]
    during: Mapped[Any] = mapped_column(TSTZRANGE)
    origin: Mapped[str] = enum_column()
    source_resource_id: Mapped[UUID]
    expires_at: Mapped[datetime | None]


class Blackout(TenantOwned, Timestamps, Base):
    """Dated closure of a location. A rule row checked by the service, not a hold (ADR 0004 section 7)."""

    __tablename__ = "blackout"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        enum_check("scope", BlackoutScope),
        CheckConstraint("NOT isempty(during)", name="during"),
        Index("ix_blackout_span", "tenant_id", "location_id", "during", postgresql_using="gist"),
    )

    location_id: Mapped[UUID]
    name: Mapped[str]
    during: Mapped[Any] = mapped_column(TSTZRANGE)
    scope: Mapped[str] = enum_column(server_default=text("'all'"))
    note: Mapped[str | None]


class Session(TenantOwned, Timestamps, Base):
    """Seat counter of a booking of kind session: its own row so reserve_seat has its own lock site."""

    __tablename__ = "session"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("booking_id", "booking", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "booking_id", name="uq_session_booking"),
        *tfk("slot_offer_id", "slot_offer", index=False),
        UniqueConstraint("tenant_id", "direct_link_token", name="uq_session_direct_link"),
        CheckConstraint("booked_count >= 0 AND booked_count <= capacity", name="booked_within_capacity"),
        CheckConstraint("capacity >= 0", name="capacity"),
        CheckConstraint("(slot_offer_id IS NULL) = (slot_starts_at IS NULL)", name="slot"),
        CheckConstraint(
            "(meeting_external_id IS NULL) = (meeting_provider IS NULL) AND (meeting_external_id IS NULL) = "
            "(meeting_join_url IS NULL) AND (meeting_external_id IS NULL) = (meeting_host_url IS NULL)",
            name="meeting",
        ),
        Index(
            "uq_session_slot", "tenant_id", "slot_offer_id", "slot_starts_at", unique=True,
            postgresql_where=text("slot_offer_id IS NOT NULL"),
        ),
        Index(
            "ix_session_self_bookable", "tenant_id", "location_id", "is_self_bookable",
            postgresql_where=text("is_self_bookable"),
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    booking_id: Mapped[UUID]
    capacity: Mapped[int]
    booked_count: Mapped[int] = _int(0)
    is_self_bookable: Mapped[bool]
    allows_free_booking: Mapped[bool] = _flag(False)
    direct_link_token: Mapped[str] = mapped_column(info={"audit": "never"})
    is_direct_link_active: Mapped[bool] = _flag(False)  # SCH-16: the token resolves only while this is on
    slot_offer_id: Mapped[UUID | None]
    slot_starts_at: Mapped[datetime | None]
    # CLS-08: a virtual session's meeting (ports.video_meeting). The links are credentials: never audited by value.
    meeting_provider: Mapped[str | None]
    meeting_external_id: Mapped[str | None] = mapped_column(info={"audit": "never"})
    meeting_join_url: Mapped[str | None] = mapped_column(info={"audit": "never"})
    meeting_host_url: Mapped[str | None] = mapped_column(info={"audit": "never"})


class ReservationTypeGrant(TenantOwned, Timestamps, Base):
    """SCH-05: a staff user allowed to book a reservation type. A type with no rows is open to every staff user
    holding the booking keys; a type with rows is restricted to them (README assumption 11)."""

    __tablename__ = "reservation_type_grant"
    __table_args__ = tenant_args(
        *tfk("reservation_type_id", "reservation_type", ondelete="CASCADE", index=False),
        *tfk("staff_user_id", "staff_user", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "reservation_type_id", "staff_user_id", name="uq_reservation_type_grant"),
    )

    reservation_type_id: Mapped[UUID]
    staff_user_id: Mapped[UUID]


class SlotOffer(TenantOwned, Timestamps, Base):
    """What is sold inside an availability window: fixed-length slots of a reservation type (SCH-07, SCH-18).
    Slots are derived at query time; a session row is materialised only when a slot is taken."""

    __tablename__ = "slot_offer"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("availability_window_id", "availability_window", ondelete="CASCADE"),
        *tfk("reservation_type_id", "reservation_type"),
        CheckConstraint("slot_min BETWEEN 5 AND 480 AND slot_min % 5 = 0", name="slot"),
        CheckConstraint("capacity >= 1", name="capacity"),
        UniqueConstraint("tenant_id", "direct_link_token", name="uq_slot_offer_direct_link"),
    )

    location_id: Mapped[UUID]
    availability_window_id: Mapped[UUID]
    reservation_type_id: Mapped[UUID]
    slot_min: Mapped[int] = mapped_column(SmallInteger)
    capacity: Mapped[int] = _int(1)
    title: Mapped[str]
    public_title: Mapped[str | None]
    is_self_bookable: Mapped[bool] = _flag(True)
    allows_free_booking: Mapped[bool] = _flag(False)
    direct_link_token: Mapped[str] = mapped_column(info={"audit": "never"})
    is_active: Mapped[bool] = _flag(True)


class SlotOfferResource(TenantOwned, Timestamps, Base):
    """An extra resource a booked slot also holds (the court that goes with the coach)."""

    __tablename__ = "slot_offer_resource"
    __table_args__ = tenant_args(
        *tfk("slot_offer_id", "slot_offer", ondelete="CASCADE", index=False),
        *tfk("resource_id", "resource"),
        UniqueConstraint("tenant_id", "slot_offer_id", "resource_id", name="uq_slot_offer_resource"),
    )

    slot_offer_id: Mapped[UUID]
    resource_id: Mapped[UUID]
