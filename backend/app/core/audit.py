"""Append-only audit trail (overview 3.10, ADR 0007). Written by services in the same transaction as the change."""

import json
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Index, String, Text, inspect, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core import clock, context
from app.core.db.base import Base, JsonDict, TenantOwned, enum_check, enum_column, tenant_args, tfk
from app.core.settings import get_settings

# Retention class is a property of the action, not a tenant setting (ADR 0007 section 9).
_LONG_RETENTION = (
    "platform.role.",
    "platform.staff_user.assign_role",
    "platform.staff_user.override_permissions",
    "platform.support_access.",
    "platform.data_subject_request.",
    "billing.",
    "documents.",
)
_MAX_CHANGES_BYTES = 8192


class ActorType(StrEnum):
    STAFF = "staff"
    CLIENT = "client"
    API_KEY = "api_key"
    KIOSK = "kiosk"
    SYSTEM = "system"


class AuditEvent(TenantOwned, Base):
    __tablename__ = "audit_event"
    __table_args__ = tenant_args(
        enum_check("actor_type", ActorType),
        *tfk("location_id", "location"),
        Index("ix_audit_event_entity", "tenant_id", "entity_type", "entity_id", "id"),
        Index("ix_audit_event_actor", "tenant_id", "actor_id", "id"),
        Index("ix_audit_event_retention", "retain_until_on"),
    )

    occurred_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    actor_type: Mapped[str] = enum_column()
    actor_id: Mapped[UUID | None]
    actor_label: Mapped[str]
    on_behalf_of_client_id: Mapped[UUID | None]
    location_id: Mapped[UUID | None]
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[UUID]
    changes: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    reason: Mapped[str | None]
    request_id: Mapped[str | None]
    ip: Mapped[Any | None] = mapped_column(INET)
    auth_session_id: Mapped[UUID | None]
    impersonator_ref: Mapped[str | None]
    retain_until_on: Mapped[date]


def _plain(value: Any) -> Any:
    return value if value is None or isinstance(value, bool | int | float | str) else str(value)


def diff(obj: Any) -> dict[str, Any]:
    """{"field": [old, new]} from the ORM's dirty state; call it before flushing.

    Redaction is declared on the column (info={"audit": "value" | "flag" | "never"}). Undeclared text and
    JSON columns are flag-only, so names, emails and notes never enter the audit table as values.
    """
    state = inspect(obj)
    changes: dict[str, Any] = {}
    for attr in state.mapper.column_attrs:
        history = state.attrs[attr.key].history
        if not history.has_changes():
            continue
        column = attr.columns[0]
        mode = column.info.get("audit") or ("flag" if isinstance(column.type, Text | String | JSON) else "value")
        if mode == "never":
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        changes[attr.key] = True if mode == "flag" else [_plain(old), _plain(new)]
    return changes


def record(
    session: Session,
    action: str,
    entity: Any,
    *,
    changes: dict[str, Any] | None = None,
    location_id: UUID | None = None,
    reason: str | None = None,
    actor: Any = None,
) -> AuditEvent:
    """One event per aggregate touched. The actor comes from the session, so a service cannot forge one;
    `actor` is only for flows with no principal yet (sign-in)."""
    actor = actor or session.info.get("actor")
    if actor is None:
        raise RuntimeError(f"audit.record({action}) without an actor on the session")
    changes = changes or {}
    if len(json.dumps(changes, default=str)) > _MAX_CHANGES_BYTES:
        changes = dict.fromkeys(changes, True)
    cfg = get_settings().audit
    days = cfg.retention_days_long if action.startswith(_LONG_RETENTION) else cfg.retention_days
    event = AuditEvent(
        occurred_at=clock.now(),
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        location_id=location_id,
        action=action,
        entity_type=entity.__tablename__,
        entity_id=entity.id,
        changes=changes,
        reason=reason,
        request_id=context.request_id.get(),
        ip=context.client_ip.get(),
        auth_session_id=getattr(actor, "session_id", None),
        retain_until_on=clock.now().date() + timedelta(days=days),
    )
    session.add(event)
    return event
