"""resources tables (docs/architecture/data-model-core.md section 3). Lockers (3, RES-07..09) are not built."""

from datetime import date
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, SmallInteger, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, WallTime, enum_check, enum_column, tenant_args, tfk


class ResourceKind(StrEnum):
    VENUE = "venue"
    TRAINER = "trainer"
    VIRTUAL_ROOM = "virtual_room"


class ResourceStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ResourceGroup(TenantOwned, Timestamps, Base):
    """A calendar header and multi-select convenience; nothing is booked on it (RES-04)."""

    __tablename__ = "resource_group"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        Index(
            "uq_resource_group_name", "tenant_id", "location_id", "name", unique=True,
            postgresql_where=text("is_active"),
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    name: Mapped[str]
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Resource(TenantOwned, Timestamps, Base):
    """Venues, sub-venues, trainers and virtual rooms share one table so one exclusion constraint covers all."""

    __tablename__ = "resource"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("resource_group_id", "resource_group", index=False),
        *tfk("parent_id", "resource"),
        enum_check("kind", ResourceKind),
        enum_check("status", ResourceStatus),
        CheckConstraint("(kind = 'virtual_room') = (external_ref IS NOT NULL)", name="external_ref"),
        CheckConstraint("parent_id <> id", name="not_own_parent"),
        CheckConstraint("kind = 'venue' OR parent_id IS NULL", name="trainer_flat"),
        CheckConstraint("btrim(name) <> ''", name="name"),
        Index(
            "uq_resource_name", "tenant_id", "location_id", "parent_id", "name", unique=True,
            postgresql_where=text("status = 'active'"), postgresql_nulls_not_distinct=True,
        ),
        Index("ix_resource_group_order", "tenant_id", "location_id", "resource_group_id", "sort_order"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    resource_group_id: Mapped[UUID]
    parent_id: Mapped[UUID | None]
    kind: Mapped[str] = enum_column()
    external_ref: Mapped[str | None]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    public_name: Mapped[str | None]
    description: Mapped[str | None]
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_online_bookable: Mapped[bool] = mapped_column(server_default=text("true"))
    counts_toward_plan: Mapped[bool] = mapped_column(server_default=text("true"))
    status: Mapped[str] = enum_column(server_default=text("'active'"))


class ResourceLink(TenantOwned, Timestamps, Base):
    """Standing rule: booking `from` also holds `to` (RES-05). Directional; copied onto the booking."""

    __tablename__ = "resource_link"
    __table_args__ = tenant_args(
        *tfk("from_resource_id", "resource", ondelete="CASCADE", index=False),
        *tfk("to_resource_id", "resource", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "from_resource_id", "to_resource_id", name="uq_resource_link"),
        CheckConstraint("from_resource_id <> to_resource_id", name="distinct"),
    )

    from_resource_id: Mapped[UUID]
    to_resource_id: Mapped[UUID]


class AvailabilityWindow(TenantOwned, Timestamps, Base):
    """When a resource offers bookable time: a weekly rule over a date span, in local wall time (SCH-18)."""

    __tablename__ = "availability_window"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("resource_id", "resource", ondelete="CASCADE", index=False),
        CheckConstraint("end_time > start_time", name="times"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="dates"),
        CheckConstraint("weekdays <@ ARRAY[1,2,3,4,5,6,7]::smallint[] AND cardinality(weekdays) > 0", name="weekdays"),
        CheckConstraint("interval_weeks BETWEEN 1 AND 8", name="interval"),
        Index("ix_availability_window_resource", "tenant_id", "resource_id", "starts_on"),
    )

    location_id: Mapped[UUID]
    resource_id: Mapped[UUID]
    starts_on: Mapped[date]
    ends_on: Mapped[date | None]
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    interval_weeks: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    start_time: Mapped[str] = mapped_column(WallTime)
    end_time: Mapped[str] = mapped_column(WallTime)
    note: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
