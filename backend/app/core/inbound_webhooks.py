"""Inbound provider webhooks: the two global tables and the fh_platform access they need.

A webhook arrives with no tenant in the request, so it is stored and routed here, outside row-level
security, and the owning context then processes it inside the tenant (ADR 0003 section 8). Both tables are
on the global allow-list of overview 3.1. `integrations` owns them once it is built; billing needs them first.
"""

import json
import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import ForeignKey, Index, PrimaryKeyConstraint, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core import clock
from app.core.db.base import Base
from app.core.db.platform import platform_engine
from app.core.ids import new_id
from app.core.settings import get_settings

log = logging.getLogger("app.inbound_webhooks")


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


# A failed event is retried by billing's sweep until it has this many attempts, then left `failed` for an
# operator. Kept here so the purge below never empties an event the sweep would still retry.
RETRY_ATTEMPTS = 5


def finish(row_id: UUID, error: str | None = None) -> None:
    with platform_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE inbound_webhook_event SET status = :s, error = :e, attempt_count = attempt_count + 1, "
                "processed_at = now() WHERE id = :id"
            ),
            {"s": "failed" if error else "processed", "e": error, "id": row_id},
        )


def stale(tenant_id: UUID, before: datetime, max_attempts: int) -> list[UUID]:
    """One tenant's events that were stored but not processed before `before` (never enqueued, or failed
    fewer than `max_attempts` times), oldest first and at most 100 per sweep: the work list of billing's retry
    sweep."""
    with platform_engine().connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT id FROM inbound_webhook_event WHERE tenant_id = :t AND received_at < :b AND "
                    "(status = 'received' OR (status = 'failed' AND attempt_count < :m)) ORDER BY received_at LIMIT 100"
                ),
                {"t": tenant_id, "b": before, "m": max_attempts},
            ).scalars()
        )


def purge_payloads() -> int:
    """Retention (security-baseline 2.3): every event last touched more than `retention.inbound_payload_days` ago
    loses its payload and error text (where personal data sits), whatever its status, attempt count or tenant's
    state, at most `retention.batch_rows` per call. An unfinished one (received, or failed under the cap) is made
    terminal in the same statement: `failed` with `attempt_count` at `RETRY_ATTEMPTS`, which `stale()` never
    returns, so the retry sweep can never pick up an emptied event. Nothing new is written about the event. The row
    stays so a late redelivery is still a duplicate. Idempotent. Run hourly by the clock (app.scheduler.tick_hour)
    as fh_platform: the table is global, and ignored events have no tenant."""
    cfg = get_settings().retention
    before = clock.now() - timedelta(days=cfg.inbound_payload_days)
    with platform_engine().begin() as conn:
        # shortcut: no index covers processed rows by age, so each run scans them; add a partial index on
        # COALESCE(processed_at, received_at) WHERE payload <> '{}' when this shows up in the slow-query log.
        unfinished = (
            conn.execute(
                text(
                    "WITH due AS (SELECT id, (status = 'received' OR (status = 'failed' AND attempt_count < :cap)) "
                    "AS unfinished FROM inbound_webhook_event WHERE "
                    "(payload <> '{}'::jsonb OR error IS NOT NULL OR status = 'received' "
                    "OR (status = 'failed' AND attempt_count < :cap)) "
                    "AND COALESCE(processed_at, received_at) < :before LIMIT :n FOR UPDATE SKIP LOCKED) "
                    "UPDATE inbound_webhook_event e SET payload = '{}'::jsonb, error = NULL, "
                    "status = CASE WHEN e.status = 'received' THEN 'failed' ELSE e.status END, "
                    "attempt_count = CASE WHEN due.unfinished THEN GREATEST(e.attempt_count, :cap) "
                    "ELSE e.attempt_count END "
                    "FROM due WHERE e.id = due.id RETURNING due.unfinished"
                ),
                {"before": before, "n": cfg.batch_rows, "cap": RETRY_ATTEMPTS},
            )
            .scalars()
            .all()
        )
    if made := sum(unfinished):  # never processed: an operator should know these were given up on
        log.warning("retention made %d unfinished inbound webhook events terminal", made)
    return len(unfinished)


def get(row_id: UUID):
    with platform_engine().connect() as conn:
        return conn.execute(
            text("SELECT provider, event_type, payload, status FROM inbound_webhook_event WHERE id = :id"),
            {"id": row_id},
        ).first()
