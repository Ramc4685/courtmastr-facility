"""integrations tables (data-model-programs.md section 5; api_key from section 5.1 and ADR 0012 section 1)."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Index, Text, UniqueConstraint, Uuid, text
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
