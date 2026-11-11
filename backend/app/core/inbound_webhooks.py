"""Inbound provider webhooks: the two global tables and the fh_platform access they need.

A webhook arrives with no tenant in the request, so it is stored and routed here, outside row-level
security, and the owning context then processes it inside the tenant (ADR 0003 section 8). Both tables are
on the global allow-list of overview 3.1. `integrations` owns them once it is built; billing needs them first.
"""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Index, PrimaryKeyConstraint, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.platform import platform_engine
from app.core.ids import new_id


class ProviderAccountLookup(Base):
    """provider account -> tenant. Written by app.register_provider_account(); read only by fh_platform."""

    __tablename__ = "provider_account_lookup"
    __table_args__ = (PrimaryKeyConstraint("provider", "provider_account_ref"),)

    provider: Mapped[str]
    provider_account_ref: Mapped[str]
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class InboundWebhookEvent(Base):
    __tablename__ = "inbound_webhook_event"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_inbound_webhook_event_provider_event"),
        Index(
            "ix_inbound_webhook_event_work", "received_at", postgresql_where=text("status IN ('received', 'failed')")
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id, server_default=text("app.uuid_v7()"))
    provider: Mapped[str]
    provider_event_id: Mapped[str]
    provider_account_id: Mapped[str | None]
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    event_type: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(server_default=text("'received'"))
    attempt_count: Mapped[int] = mapped_column(server_default=text("0"))
    error: Mapped[str | None]
    received_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    processed_at: Mapped[datetime | None]


def record(provider: str, event_id: str, account_ref: str | None, event_type: str, payload: dict):
    """Store a verified event once. Returns (row id, tenant id or None) for a first delivery and None for a
    duplicate. An event whose account maps to no tenant is kept as `ignored`, never dropped."""
    with platform_engine().begin() as conn:
        tenant_id = conn.execute(
            text("SELECT tenant_id FROM provider_account_lookup WHERE provider = :p AND provider_account_ref = :a"),
            {"p": provider, "a": account_ref or ""},
        ).scalar()
        row_id = conn.execute(
            text(
                "INSERT INTO inbound_webhook_event (id, provider, provider_event_id, provider_account_id, tenant_id,"
                " event_type, payload, status) VALUES (:id, :p, :e, :a, :t, :k, CAST(:body AS jsonb), :s) "
                "ON CONFLICT (provider, provider_event_id) DO NOTHING RETURNING id"
            ),
            {
                "id": new_id(), "p": provider, "e": event_id, "a": account_ref, "t": tenant_id, "k": event_type,
                "body": json.dumps(payload), "s": "received" if tenant_id else "ignored",
            },
        ).scalar()  # fmt: skip
    return None if row_id is None else (row_id, tenant_id)


def finish(row_id: UUID, error: str | None = None) -> None:
    with platform_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE inbound_webhook_event SET status = :s, error = :e, attempt_count = attempt_count + 1, "
                "processed_at = now() WHERE id = :id"
            ),
            {"s": "failed" if error else "processed", "e": error, "id": row_id},
        )


def get(row_id: UUID):
    with platform_engine().connect() as conn:
        return conn.execute(
            text("SELECT provider, event_type, payload, status FROM inbound_webhook_event WHERE id = :id"),
            {"id": row_id},
        ).first()
