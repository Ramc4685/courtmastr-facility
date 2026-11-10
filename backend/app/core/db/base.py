"""Declarative base, constraint naming and the mixins every tenant-owned table uses (overview 3.1 to 3.3)."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    String,
    Text,
    Time,
    TypeDecorator,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.core import clock
from app.core.ids import new_id

# Tables with no tenant_id by design (overview 3.1). The RLS meta-test fails for anything else without RLS.
GLOBAL_TABLES = {"tenant", "subscription_plan", "provider_account_lookup", "inbound_webhook_event"}


def _last_col(constraint, table) -> str:
    keys = getattr(constraint, "column_keys", None) or [c.name for c in constraint.columns]
    return keys[-1]


# Error mapping keys off these names, so they are part of the API contract (overview 3.13).
NAMING = {
    "last_col": _last_col,
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(last_col)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(last_col)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


# Python None is SQL NULL, never JSON 'null': a NOT NULL jsonb column then rejects an explicit null (422)
# instead of storing a value its response model cannot serialise.
JsonDict = JSONB(none_as_null=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {str: Text, datetime: DateTime(timezone=True), dict: JsonDict}


class TenantOwned:
    """id + tenant_id first. tenant_id is stamped from session.info by the before_flush hook below."""

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=new_id, server_default=text("app.uuid_v7()"), sort_order=-2
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id", ondelete="RESTRICT"), sort_order=-1)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=98)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=clock.now, sort_order=99)


def tenant_args(*items):
    """__table_args__ for a tenant-owned table: the UNIQUE (tenant_id, id) composite FKs point at."""
    return (UniqueConstraint("tenant_id", "id"), *items)


def tfk(column: str, table: str, *, ondelete: str = "RESTRICT", index: bool = True) -> tuple:
    """Composite FK (tenant_id, column) -> table (tenant_id, id), plus its (tenant_id, column) index."""
    fk = ForeignKeyConstraint(["tenant_id", column], [f"{table}.tenant_id", f"{table}.id"], ondelete=ondelete)
    return (fk, Index(None, "tenant_id", column)) if index else (fk,)


def enum_column(**kwargs) -> Mapped[str]:
    """A fixed-vocabulary text column: audited by value, unlike free text which is flag-only (ADR 0007)."""
    return mapped_column(Text, info={"audit": "value"}, **kwargs)


def enum_check(column: str, enum: type[StrEnum]) -> CheckConstraint:
    """text + named CHECK instead of a native enum (overview 3.2)."""
    values = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({values})", name=column)


class WallTime(TypeDecorator):
    """Postgres `time` read and written as 'HH:MM' text: location-local wall time, and 24:00 is legal."""

    impl = Time
    cache_ok = True

    def column_expression(self, column):
        return func.to_char(column, "HH24:MI", type_=String)


@event.listens_for(Session, "before_flush")
def _stamp_tenant(session: Session, _ctx, _instances) -> None:
    tenant_id = session.info.get("tenant_id")
    for obj in session.new:
        if isinstance(obj, TenantOwned):
            if obj.tenant_id is None:
                obj.tenant_id = tenant_id
            elif obj.tenant_id != tenant_id:
                raise RuntimeError(f"{type(obj).__name__} carries a tenant_id other than the session's")
