"""integrations tables (data-model-programs.md section 5; api_key from section 5.1 and ADR 0012 section 1)."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JsonDict, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk


class ApiKeyStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class EndpointStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class DeliveryStatus(StrEnum):
    PENDING = "pending"  # due at next_attempt_at (first attempt or a retry)
    DELIVERED = "delivered"
    FAILED = "failed"  # every attempt used, or a permanent refusal
    ABANDONED = "abandoned"  # the endpoint was disabled or paused before it went out


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class Provider(StrEnum):
    QUICKBOOKS_ONLINE = "quickbooks_online"
    ACCOUNTING_FILE = "accounting_file"  # ours: the daily journal as a JSON file (no external account)
    ZOOM = "zoom"
    GOOGLE_ANALYTICS = "google_analytics"  # INT-13: no credentials, only a public measurement id


class ExportStatus(StrEnum):
    PENDING = "pending"
    POSTED = "posted"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    SKIPPED = "skipped"


class CommandOutcome(StrEnum):
    OK = "ok"
    SIMULATED_FAILURE = "simulated_failure"


class ApiKey(TenantOwned, Timestamps, Base):
    """A machine credential: `fhk_<tenant>_<secret>`, stored as SHA-256. Its effective grants are recomputed on
    every request as scopes intersected with the creator's current grants (rbac-matrix section 11)."""

    __tablename__ = "api_key"
    __table_args__ = tenant_args(
        enum_check("status", ApiKeyStatus),
        *tfk("created_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "key_prefix"),
        Index("ix_api_key_previous_key_prefix", "tenant_id", "previous_key_prefix"),
    )

    name: Mapped[str]
    key_prefix: Mapped[str] = mapped_column(info={"audit": "value"})  # first 12 secret characters: lookup only
    secret_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    previous_key_prefix: Mapped[str | None] = mapped_column(info={"audit": "never"})
    previous_secret_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    previous_valid_until: Mapped[datetime | None]
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), info={"audit": "value"})
    location_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(Uuid), info={"audit": "value"})
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    expires_at: Mapped[datetime | None]
    last_used_at: Mapped[datetime | None]
    rotated_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    created_by_staff_user_id: Mapped[UUID]


class WebhookEndpoint(TenantOwned, Timestamps, Base):
    __tablename__ = "webhook_endpoint"
    __table_args__ = tenant_args(
        enum_check("status", EndpointStatus),
        *tfk("created_by_staff_user_id", "staff_user"),
        Index("ix_webhook_endpoint_active", "tenant_id", postgresql_where=text("status = 'active'")),
    )

    url: Mapped[str] = mapped_column(info={"audit": "value"})
    description: Mapped[str | None]
    event_types: Mapped[list[str]] = mapped_column(ARRAY(Text), info={"audit": "value"})  # concrete, never '*'
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    secret_ciphertext: Mapped[str] = mapped_column(info={"audit": "never"})
    previous_secret_ciphertext: Mapped[str | None] = mapped_column(info={"audit": "never"})
    previous_secret_expires_at: Mapped[datetime | None]
    failure_count: Mapped[int] = mapped_column(server_default=text("0"))  # consecutive failed deliveries
    last_success_at: Mapped[datetime | None]
    disabled_at: Mapped[datetime | None]
    disabled_reason: Mapped[str | None] = mapped_column(info={"audit": "value"})
    created_by_staff_user_id: Mapped[UUID]


class WebhookDelivery(TenantOwned, Timestamps, Base):
    __tablename__ = "webhook_delivery"
    __table_args__ = tenant_args(
        enum_check("status", DeliveryStatus),
        *tfk("webhook_endpoint_id", "webhook_endpoint", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "webhook_endpoint_id", "event_id", name="uq_webhook_delivery_endpoint_event"),
        Index("ix_webhook_delivery_due", "tenant_id", "next_attempt_at", postgresql_where=text("status = 'pending'")),
    )

    webhook_endpoint_id: Mapped[UUID]
    event_id: Mapped[UUID]  # outbox_event.id; not an FK, outbox rows are purged
    event_type: Mapped[str] = mapped_column(info={"audit": "value"})
    payload: Mapped[dict] = mapped_column(JsonDict)
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    attempt_count: Mapped[int] = mapped_column(server_default=text("0"))
    next_attempt_at: Mapped[datetime | None]
    last_response_status: Mapped[int | None]
    last_error: Mapped[str | None]
    last_duration_ms: Mapped[int | None]
    delivered_at: Mapped[datetime | None]


class ExternalConnection(TenantOwned, Timestamps, Base):
    __tablename__ = "external_connection"
    __table_args__ = tenant_args(
        enum_check("status", ConnectionStatus),
        enum_check("provider", Provider),
        *tfk("location_id", "location"),
        *tfk("connected_by_staff_user_id", "staff_user"),
        UniqueConstraint(
            "tenant_id", "provider", "location_id", name="uq_external_connection", postgresql_nulls_not_distinct=True
        ),
    )

    location_id: Mapped[UUID | None]  # null = tenant-wide
    provider: Mapped[str] = enum_column()
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    external_account_id: Mapped[str | None]
    external_account_name: Mapped[str | None]
    credentials_ciphertext: Mapped[str | None] = mapped_column(info={"audit": "never"})
    settings: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    connected_by_staff_user_id: Mapped[UUID | None]
    connected_at: Mapped[datetime | None]
    last_sync_at: Mapped[datetime | None]
    last_error: Mapped[str | None]
    last_error_at: Mapped[datetime | None]
    failure_count: Mapped[int] = mapped_column(server_default=text("0"))


class AccountingExport(TenantOwned, Timestamps, Base):
    """One journal entry per connection, location and business day: the idempotency anchor of the push."""

    __tablename__ = "accounting_export"
    __table_args__ = tenant_args(
        enum_check("status", ExportStatus),
        *tfk("external_connection_id", "external_connection", ondelete="CASCADE"),
        *tfk("location_id", "location"),
        UniqueConstraint(
            "tenant_id", "external_connection_id", "location_id", "business_on", name="uq_accounting_export_day"
        ),
    )

    external_connection_id: Mapped[UUID]
    location_id: Mapped[UUID]
    business_on: Mapped[date]
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    totals: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    external_id: Mapped[str | None] = mapped_column(info={"audit": "value"})
    doc_number: Mapped[str | None] = mapped_column(info={"audit": "value"})
    attempt_count: Mapped[int] = mapped_column(server_default=text("0"))
    last_attempt_at: Mapped[datetime | None]
    last_error: Mapped[str | None]
    posted_at: Mapped[datetime | None]


class AdapterCommandLog(TenantOwned, Base):
    """What a simulated adapter was asked to do. Append-only; never written by a real adapter."""

    __tablename__ = "adapter_command_log"
    __table_args__ = tenant_args(
        enum_check("outcome", CommandOutcome),
        *tfk("location_id", "location"),
        Index("ix_adapter_command_log_occurred_at", "tenant_id", "occurred_at"),
    )

    port: Mapped[str] = mapped_column(info={"audit": "value"})
    adapter: Mapped[str]
    location_id: Mapped[UUID | None]
    command: Mapped[str]
    arguments: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    outcome: Mapped[str] = enum_column(server_default=text("'ok'"))
    occurred_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class FeedKind(StrEnum):
    STAFF_SCHEDULE = "staff_schedule"  # the owner's readable bookings, optionally their published shifts
    TEAM_SCHEDULE = "team_schedule"  # one league team's games
    MEMBER_SCHEDULE = "member_schedule"  # a portal identity's enrolled sessions


class FeedStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class CalendarFeed(TenantOwned, Timestamps, Base):
    """A one-way iCalendar subscription (INT-08, SCH-19, STF-13, LGE-25, SSP-19). The URL token is a read-only
    capability: 256-bit, shown once, stored as SHA-256 with a lookup prefix; re-enabling mints a new one."""

    __tablename__ = "calendar_feed"
    __table_args__ = tenant_args(
        enum_check("kind", FeedKind),
        enum_check("status", FeedStatus),
        *tfk("owner_staff_user_id", "staff_user", ondelete="CASCADE"),
        *tfk("owner_identity_id", "identity", ondelete="CASCADE"),
        *tfk("location_id", "location", ondelete="CASCADE"),
        *tfk("competition_team_id", "competition_team", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "token_prefix"),
        CheckConstraint("num_nonnulls(owner_staff_user_id, owner_identity_id) = 1", name="owner"),
    )

    kind: Mapped[str] = enum_column()
    name: Mapped[str]
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    owner_staff_user_id: Mapped[UUID | None]
    owner_identity_id: Mapped[UUID | None]
    location_id: Mapped[UUID | None]  # staff feeds: only this location
    competition_team_id: Mapped[UUID | None]  # team feeds
    include_shifts: Mapped[bool] = mapped_column(server_default=text("false"))
    token_prefix: Mapped[str] = mapped_column(info={"audit": "never"})
    token_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    last_fetched_at: Mapped[datetime | None]


class PublicScheduleSetting(TenantOwned, Timestamps, Base):
    """What the anonymous embeddable schedule of one location shows (SCH-20). No row = not published."""

    __tablename__ = "public_schedule_setting"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "location_id"),
        CheckConstraint("days_ahead BETWEEN 1 AND 31", name="days_ahead"),
    )

    location_id: Mapped[UUID]
    is_enabled: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    days_ahead: Mapped[int] = mapped_column(server_default=text("7"), info={"audit": "value"})
    show_sessions: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    show_busy: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})


class MeetingProvider(StrEnum):
    MANUAL = "manual"  # a pasted link
    ZOOM = "zoom"  # created through the VideoMeeting port on the tenant's Zoom connection


class MeetingStatus(StrEnum):
    SCHEDULED = "scheduled"
    FAILED = "failed"


class VideoMeeting(TenantOwned, Timestamps, Base):
    """The online meeting of one session (INT-09, SSP-18, CLS-08). The join URL and passcode are sealed: members
    reach them only through the join route, which checks their place at click time."""

    __tablename__ = "video_meeting"
    __table_args__ = tenant_args(
        enum_check("provider", MeetingProvider),
        enum_check("status", MeetingStatus),
        *tfk("session_id", "session", ondelete="CASCADE", index=False),
        *tfk("location_id", "location", ondelete="CASCADE"),
        *tfk("external_connection_id", "external_connection"),  # connections are disconnected, never deleted
        UniqueConstraint("tenant_id", "session_id"),
        CheckConstraint("(provider = 'zoom') = (external_connection_id IS NOT NULL)", name="connection"),
    )

    session_id: Mapped[UUID]
    location_id: Mapped[UUID]
    provider: Mapped[str] = enum_column()
    status: Mapped[str] = enum_column(server_default=text("'scheduled'"))
    external_connection_id: Mapped[UUID | None]
    external_meeting_id: Mapped[str | None] = mapped_column(info={"audit": "value"})
    join_url_ciphertext: Mapped[str] = mapped_column(info={"audit": "never"})
    host_start_url_ciphertext: Mapped[str | None] = mapped_column(info={"audit": "never"})
    passcode_ciphertext: Mapped[str | None] = mapped_column(info={"audit": "never"})
    last_error: Mapped[str | None]
