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


# --- lockers and padlocks (RES-07..09) ---------------------------------------------------------------------

Designation = Literal["male", "female", "all_gender", "unspecified"]
SizeLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
LockerNumber = Annotated[int, Field(ge=1, le=99999)]
SortOrder = Annotated[int, Field(ge=0, le=10_000)]  # bounded: an unbounded int overflows Postgres (500)
Combination = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
PadlockNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class LockerRoomCreate(In):
    location_id: UUID
    name: Name
    designation: Designation = "unspecified"
    sort_order: SortOrder = 0


class LockerRoomUpdate(In):
    name: Name | None = None
    designation: Designation | None = None
    sort_order: SortOrder | None = None
    is_active: bool | None = None


class LockerRoomOut(Out):
    id: UUID
    location_id: UUID
    name: str
    designation: str
    sort_order: int
    is_active: bool


class LockerBulkCreate(In):
    from_number: LockerNumber
    to_number: LockerNumber
    size_label: SizeLabel | None = None


class LockerBulkResult(Out):
    created_count: int
    skipped_count: int


class LockerUpdate(In):
    size_label: SizeLabel | None = None
    status: Literal["active", "out_of_service", "retired"] | None = None
    padlock_id: UUID | None = None


class LockerOut(Out):
    id: UUID
    location_id: UUID
    locker_room_id: UUID
    locker_room_name: str | None
    number: int
    size_label: str | None
    status: str
    padlock_id: UUID | None
    padlock_number: str | None
    state: Literal["available", "rented", "expired"]
    locker_lease_id: UUID | None
    client_id: UUID | None
    client_name: str | None
    ends_on: date | None


class LockerTermCreate(In):
    location_id: UUID
    name: Name
    starts_on: date
    ends_on: date
    price_minor: Annotated[int, Field(ge=0, le=100_000_000)] = 0
    sort_order: SortOrder = 0


class LockerTermUpdate(In):
    name: Name | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    price_minor: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    sort_order: SortOrder | None = None
    is_active: bool | None = None


class LockerTermOut(Out):
    id: UUID
    location_id: UUID
    name: str
    starts_on: date
    ends_on: date
    price_minor: int
    sort_order: int
    is_active: bool


class PadlockCreate(In):
    location_id: UUID
    number: PadlockNumber
    combination: Combination


class PadlockUpdate(In):
    number: PadlockNumber | None = None
    combination: Combination | None = None
    status: Literal["active", "disabled"] | None = None


class PadlockOut(Out):
    """Never carries the combination: that is `revealPadlockCombination`, under its own key."""

    id: UUID
    location_id: UUID
    number: str
    status: str


class PadlockCombinationOut(Out):
    padlock_id: UUID
    number: str
    combination: str
