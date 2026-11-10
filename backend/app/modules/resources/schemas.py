"""Request and response models for the resources API (docs/api/openapi-core.yaml, tag resources)."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Text_ = Annotated[str, StringConstraints(max_length=2000)]
Wall = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$|^24:00$")]
Weekdays = Annotated[list[Annotated[int, Field(ge=1, le=7)]], Field(min_length=1, max_length=7)]
Kind = Literal["venue", "trainer", "virtual_room"]


class ResourceGroupCreate(In):
    location_id: UUID
    name: Name
    sort_order: int = 0


class ResourceGroupUpdate(In):
    name: Name | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class ResourceGroupOut(Out):
    id: UUID
    location_id: UUID
    name: str
    sort_order: int
    is_active: bool


class ResourceCreate(In):
    location_id: UUID
    resource_group_id: UUID
    parent_id: UUID | None = None
    kind: Kind = "venue"
    external_ref: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    name: Name
    public_name: Name | None = None
    description: Text_ | None = None
    sort_order: int = 0
    is_online_bookable: bool = True
    counts_toward_plan: bool | None = None  # default: true for top-level rows, false for sub-venues
    staff_user_id: UUID | None = None  # trainer only: the staff user whose calendar this is


class ResourceUpdate(In):
    resource_group_id: UUID | None = None
    parent_id: UUID | None = None
    name: Name | None = None
    public_name: Name | None = None
    description: Text_ | None = None
    sort_order: int | None = None
    is_online_bookable: bool | None = None
    counts_toward_plan: bool | None = None


class ResourceOut(Out):
    id: UUID
    location_id: UUID
    resource_group_id: UUID
    parent_id: UUID | None
    kind: Kind
    name: str
    public_name: str | None
    description: str | None
    sort_order: int
    is_online_bookable: bool
    counts_toward_plan: bool
    status: Literal["active", "archived"]


class ResourceDetail(ResourceOut):
    linked_resource_ids: list[UUID]


class ResourceLinks(In):
    to_resource_ids: Annotated[list[UUID], Field(max_length=20)]


class WindowCreate(In):
    starts_on: date
    ends_on: date | None = None
    weekdays: Weekdays
    interval_weeks: Annotated[int, Field(ge=1, le=8)] = 1
    start_time: Wall
    end_time: Wall
    note: Text_ | None = None


class WindowUpdate(In):
    starts_on: date | None = None
    ends_on: date | None = None
    weekdays: Weekdays | None = None
    interval_weeks: Annotated[int, Field(ge=1, le=8)] | None = None
    start_time: Wall | None = None
    end_time: Wall | None = None
    note: Text_ | None = None
    is_active: bool | None = None


class WindowOut(Out):
    id: UUID
    location_id: UUID
    resource_id: UUID
    starts_on: date
    ends_on: date | None
    weekdays: list[int]
    interval_weeks: int
    start_time: str
    end_time: str
    note: str | None
    is_active: bool
