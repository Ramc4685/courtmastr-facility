"""Request and response models for the scheduling API (docs/api/openapi-core.yaml, tag scheduling)."""

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401
from app.modules.resources.schemas import ResourceOut

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Title = Annotated[str, StringConstraints(max_length=200)]
Notes = Annotated[str, StringConstraints(max_length=4000)]
Wall = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-f]{6}$")]
Buffer = Annotated[int, Field(ge=0, le=240, multiple_of=5)]
Capacity = Annotated[int, Field(ge=0, le=100000)]
Kind = Literal["session", "rental", "block", "game"]
BlockKind = Literal["floor_shift", "instruction", "unpaid", "unavailable"]
OnConflict = Literal["skip", "abort"]
Status = Literal["ok", "conflict", "blackout", "outside_hours", "skipped_by_rule", "capacity-below-booked"]


class SettingsUpdate(In):
    default_buffer_before_min: Buffer | None = None
    default_buffer_after_min: Buffer | None = None
    drag_drop_default: Literal["ask", "reschedule", "move_enrollment"] | None = None
    calendar_slot_min: Literal[5, 10, 15, 20, 30, 60] | None = None
    checkout_hold_min: Annotated[int, Field(ge=5, le=30)] | None = None
    max_series_occurrences: Annotated[int, Field(ge=1, le=2000)] | None = None


class SettingsOut(Out):
    location_id: UUID | None
    default_buffer_before_min: int
    default_buffer_after_min: int
    drag_drop_default: str
    calendar_slot_min: int
    checkout_hold_min: int
    max_series_occurrences: int


class CategoryCreate(In):
    location_id: UUID
    parent_id: UUID | None = None
    name: Name
    sort_order: int = 0


class CategoryUpdate(In):
    name: Name | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class CategoryOut(Out):
    id: UUID
    location_id: UUID
    parent_id: UUID | None
    name: str
    sort_order: int
    is_active: bool


class _TypeFields(In):
    is_schedulable: bool | None = None
    is_sellable: bool | None = None
    revenue_category_id: UUID | None = None
    reservation_category_id: UUID | None = None
    default_capacity: Capacity | None = None
    default_duration_min: Annotated[int, Field(ge=5, le=1440)] | None = None
    default_allows_free_booking: bool | None = None
    color: Color | None = None
    uses_default_buffer: bool | None = None
    buffer_before_min: Buffer | None = None
    buffer_after_min: Buffer | None = None
    is_self_bookable_default: bool | None = None
    sort_order: int | None = None


class TypeCreate(_TypeFields):
    location_id: UUID
    name: Name


class TypeUpdate(_TypeFields):
    name: Name | None = None
    is_active: bool | None = None


class TypeOut(Out):
    id: UUID
    location_id: UUID
    name: str
    is_schedulable: bool
    is_sellable: bool
    revenue_category_id: UUID | None
    reservation_category_id: UUID | None
    default_capacity: int
    default_duration_min: int | None
    default_allows_free_booking: bool
    color: str | None
    uses_default_buffer: bool
    buffer_before_min: int
    buffer_after_min: int
    is_self_bookable_default: bool
    sort_order: int
    is_active: bool


class BlackoutCreate(In):
    location_id: UUID
    name: Name
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    scope: Literal["all", "online_only"] = "all"
    note: Notes | None = None


class BlackoutUpdate(In):
    name: Name | None = None
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    scope: Literal["all", "online_only"] | None = None
    note: Notes | None = None


class BlackoutOut(Out):
    id: UUID
    location_id: UUID
    name: str
    starts_at: datetime
    ends_at: datetime
    scope: str
    note: str | None


class OverlappingBooking(Out):
    id: UUID
    booking_number: int
    title: str
    starts_at: datetime
    ends_at: datetime


class BlackoutSaved(BlackoutOut):
    overlapping_bookings: list[OverlappingBooking]


class ResourceInput(In):
    resource_id: UUID
    role: Literal["primary", "additional"] | None = None


Resources = Annotated[list[ResourceInput], Field(min_length=1, max_length=20)]


class SessionInput(In):
    capacity: Capacity | None = None
    is_self_bookable: bool | None = None
    allows_free_booking: bool | None = None


class RecurrenceRule(In):
    pattern: Literal["single", "daily", "weekly", "monthly_by_date", "monthly_by_weekday", "yearly"]
    interval_count: Annotated[int, Field(ge=1, le=52)] = 1
    weekdays: Annotated[list[Annotated[int, Field(ge=1, le=7)]], Field(max_length=7)] | None = None
    month_week: Literal[1, 2, 3, 4, 5, -1] | None = None
    range_type: Literal["count", "until"]
    occurrence_limit: Annotated[int, Field(ge=1, le=2000)] | None = None
    until_on: date | None = None


class BookingCreate(In):
    location_id: UUID
    kind: Literal["session", "block"]
    block_kind: BlockKind | None = None
    reservation_type_id: UUID | None = None
    title: Title | None = None
    public_title: Title | None = None
    notes: Notes | None = None
    buffer_before_min: Buffer | None = None
    buffer_after_min: Buffer | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    resources: Resources
    include_linked_resources: bool = True
    session: SessionInput | None = None
    recurrence: RecurrenceRule | None = None
    series_label: Title | None = None
    on_conflict: OnConflict = "abort"
    override_policy: bool = False


class BookingUpdate(In):
    title: Title | None = None
    public_title: Title | None = None
    notes: Notes | None = None
    buffer_before_min: Buffer | None = None
    buffer_after_min: Buffer | None = None
    reservation_type_id: UUID | None = None
    block_kind: BlockKind | None = None
    version: int


class BookingReschedule(In):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    resources: Resources | None = None
    version: int
    override_policy: bool = False


class BookingCancel(In):
    reason: Literal["staff", "client", "other"] = "staff"
    note: Notes | None = None
    version: int


class BookingResourceOut(Out):
    resource_id: UUID
    role: Literal["primary", "additional"]


class SessionBrief(Out):
    id: UUID
    capacity: int
    booked_count: int
    fill: Literal["empty", "partial", "full"]
    is_self_bookable: bool
    allows_free_booking: bool
    is_direct_link_active: bool = False


class SessionOut(SessionBrief):
    location_id: UUID
    booking_id: UUID
    starts_at: datetime
    ends_at: datetime
    title: str
    public_title: str | None
    reservation_type_id: UUID | None
    booking_series_id: UUID | None
    status: Literal["tentative", "confirmed", "cancelled"]


class SessionUpdate(In):
    is_self_bookable: bool | None = None
    allows_free_booking: bool | None = None


class CapacityChange(In):
    session_ids: Annotated[list[UUID], Field(min_length=1, max_length=2000)]
    capacity: Capacity


class CapacityResult(Out):
    session_id: UUID
    status: Literal["ok", "capacity-below-booked"]
    capacity: int
    booked_count: int


class CapacityChanged(Out):
    results: list[CapacityResult]
    changed_count: int


class HoursWarning(Out):
    """A dismissible notice: the booking was made, but outside the facility hours (owner decision, question 19)."""

    code: Literal["outside-opening-hours"]
    detail: str
    count: int


class BookingOut(Out):
    id: UUID
    location_id: UUID
    booking_number: int
    kind: Kind
    block_kind: BlockKind | None
    reservation_type_id: UUID | None
    client_id: UUID | None
    title: str
    public_title: str | None
    notes: str | None
    buffer_before_min: int
    buffer_after_min: int
    starts_at: datetime
    ends_at: datetime
    occurrence_on: date
    local_start_time: str
    duration_min: int
    status: Literal["tentative", "confirmed", "cancelled"]
    expires_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_via: str
    booking_series_id: UUID | None
    booking_series_rule_id: UUID | None
    source_context: str | None
    source_type: str | None
    source_id: UUID | None
    resources: list[BookingResourceOut]
    session: SessionBrief | None
    version: int
    created_at: datetime
    updated_at: datetime
    warnings: list[HoursWarning] = []


class OccurrenceResult(Out):
    index: int
    local_start: str
    starts_at: datetime
    ends_at: datetime
    status: Status
    booking_id: UUID | None = None
    conflicts: list[dict[str, Any]] = []


class BookingCreated(Out):
    """`booking` is the first occurrence; null while a long series is generated by the worker (status_url)."""

    booking: BookingOut | None
    booking_series_id: UUID | None
    created_count: int
    conflict_count: int
    results: list[OccurrenceResult]
    status_url: str | None = None
    warnings: list[HoursWarning] = []


class SeriesPreview(Out):
    requested_count: int
    ok_count: int
    conflict_count: int
    occurrences: list[OccurrenceResult]
    status_url: str | None = None
    warnings: list[HoursWarning] = []


class SeriesRuleOut(Out):
    id: UUID
    sequence: int
    rule: RecurrenceRule
    start_on: date
    start_time: str
    end_time: str
    end_day_offset: int
    status: Literal["pending", "generating", "completed", "failed"]
    requested_count: int
    created_count: int
    conflict_count: int
    results: list[OccurrenceResult]
    started_at: datetime | None
    finished_at: datetime | None


class SeriesOut(Out):
    id: UUID
    location_id: UUID
    kind: Kind
    label: str | None
    occurrence_count: int
    rules: list[SeriesRuleOut]


class SeriesRunOut(Out):
    id: UUID
    booking_series_id: UUID
    booking_series_rule_id: UUID | None
    kind: Literal["generate", "edit", "cancel", "preview"]
    status: Literal["pending", "running", "completed", "failed"]
    requested_count: int
    ok_count: int
    conflict_count: int
    results: list[OccurrenceResult]
    started_at: datetime | None
    finished_at: datetime | None


class SeriesRuleAdd(In):
    start_on: date
    start_time: Wall
    end_time: Wall
    end_day_offset: Annotated[int, Field(ge=0, le=6)] = 0
    rule: RecurrenceRule
    resources: Resources | None = None
    on_conflict: OnConflict = "abort"
    preview: bool = False
    override_policy: bool = False


class SeriesRuleAdded(BookingCreated):
    preview: SeriesPreview | None = None
    booking_series_id: UUID | None = None
    created_count: int = 0
    conflict_count: int = 0
    results: list[OccurrenceResult] = []
    booking: BookingOut | None = None


class SeriesRuleChange(In):
    """A new pattern for an existing pass, taking over from `start_on` (today or later)."""

    start_on: date
    start_time: Wall
    end_time: Wall
    end_day_offset: Annotated[int, Field(ge=0, le=6)] = 0
    rule: RecurrenceRule
    on_conflict: OnConflict = "abort"
    preview: bool = False
    override_policy: bool = False


class SeriesRuleChanged(SeriesRuleAdded):
    cancelled_count: int


class SeriesScope(In):
    mode: Literal["this", "following", "all", "selected", "date_range"]
    anchor_booking_id: UUID | None = None
    booking_ids: Annotated[list[UUID], Field(max_length=2000)] | None = None
    from_on: date | None = None
    to_on: date | None = None


class SeriesPatch(In):
    title: Title | None = None
    public_title: Title | None = None
    notes: Notes | None = None
    buffer_before_min: Buffer | None = None
    buffer_after_min: Buffer | None = None
    reservation_type_id: UUID | None = None
    start_time: Wall | None = None
    duration_min: Annotated[int, Field(ge=5, le=10080)] | None = None
    shift_days: Annotated[int, Field(ge=-366, le=366)] | None = None
    resources: Resources | None = None
    session: SessionInput | None = None


class SeriesEdit(In):
    scope: SeriesScope
    patch: SeriesPatch
    on_conflict: OnConflict = "abort"
    preview: bool = False


class SeriesCancel(In):
    scope: SeriesScope
    reason: Literal["staff", "client", "other"] | None = None
    note: Notes | None = None
    preview: bool = False


class SeriesCommandResult(Out):
    booking_series_id: UUID
    affected_count: int
    conflict_count: int
    results: list[OccurrenceResult]


class CalendarEntry(Out):
    booking_id: UUID
    booking_number: int
    kind: Kind
    block_kind: str | None
    title: str
    starts_at: datetime
    ends_at: datetime
    buffer_before_min: int
    buffer_after_min: int
    status: Literal["tentative", "confirmed"]
    resource_id: UUID
    resource_role: Literal["primary", "additional", "descendant"]
    color: str | None
    reservation_type_id: UUID | None
    client_id: UUID | None
    booking_series_id: UUID | None
    capacity: int | None
    booked_count: int | None
    fill: Literal["empty", "partial", "full"] | None
    version: int
    can_edit: bool


class HoursDay(Out):
    weekday: int
    opens_time: str | None
    closes_time: str | None
    is_closed: bool


class LegendType(Out):
    reservation_type_id: UUID
    name: str
    color: str | None


class Legend(Out):
    reservation_types: list[LegendType]
    fill_states: list[str]


class OpenRange(Out):
    starts_at: datetime
    ends_at: datetime


class ResourceHours(Out):
    """When a resource with availability windows (a trainer) is available; the rest of its column is shaded."""

    resource_id: UUID
    open: list[OpenRange]


class CalendarView(Out):
    location_id: UUID
    time_zone: str
    from_: datetime = Field(serialization_alias="from", validation_alias="from")
    to: datetime
    calendar_slot_min: int
    drag_drop_default: Literal["ask", "reschedule", "move_enrollment"]
    resource_hours: list[ResourceHours]
    facility_hours: list[HoursDay]
    resources: list[ResourceOut]
    entries: list[CalendarEntry]
    blackouts: list[BlackoutOut]
    legend: Legend


class FreeInterval(Out):
    starts_at: datetime
    ends_at: datetime


class ResourceFree(Out):
    resource_id: UUID
    free: list[FreeInterval]


class Availability(Out):
    location_id: UUID
    time_zone: str
    from_: datetime = Field(serialization_alias="from", validation_alias="from")
    to: datetime
    resources: list[ResourceFree]


class TypeGrants(Out):
    """Staff allowed to book a reservation type (SCH-05). Not restricted = every staff user with the keys."""

    reservation_type_id: UUID
    is_restricted: bool
    staff_user_ids: list[UUID]


class TypeGrantsReplace(In):
    staff_user_ids: Annotated[list[UUID], Field(max_length=500)]


SlotMinutes = Annotated[int, Field(ge=5, le=480, multiple_of=5)]
SlotCapacity = Annotated[int, Field(ge=1, le=1000)]
ExtraResources = Annotated[list[UUID], Field(max_length=10)]


class SlotOfferCreate(In):
    availability_window_id: UUID
    reservation_type_id: UUID
    slot_min: SlotMinutes
    capacity: SlotCapacity = 1
    title: Title | None = None
    public_title: Title | None = None
    is_self_bookable: bool = True
    allows_free_booking: bool = False
    additional_resource_ids: ExtraResources = []
    is_active: bool = True


class SlotOfferUpdate(In):
    reservation_type_id: UUID | None = None
    slot_min: SlotMinutes | None = None
    capacity: SlotCapacity | None = None
    title: Title | None = None
    public_title: Title | None = None
    is_self_bookable: bool | None = None
    allows_free_booking: bool | None = None
    additional_resource_ids: ExtraResources | None = None
    is_active: bool | None = None


class SlotOfferOut(Out):
    id: UUID
    location_id: UUID
    availability_window_id: UUID
    resource_id: UUID
    reservation_type_id: UUID
    slot_min: int
    capacity: int
    title: str
    public_title: str | None
    is_self_bookable: bool
    allows_free_booking: bool
    additional_resource_ids: list[UUID]
    is_active: bool


class Slot(Out):
    starts_at: datetime
    ends_at: datetime
    status: Literal["free", "booked", "full", "unavailable"]
    session_id: UUID | None
    booking_id: UUID | None
    capacity: int
    booked_count: int


class SlotList(Out):
    slot_offer_id: UUID
    slots: list[Slot]


class SlotBook(In):
    starts_at: AwareDatetime


# --- direct links (SCH-16), shared bookings (SCH-17, SSP-09), series merge (SCH-21) -----------------------


class DirectLinkOut(Out):
    session_id: UUID
    is_active: bool
    token: str | None = Field(description="Shown once, when the link is made; null when the link was already on.")
    path: str | None = Field(
        description="The web page with the token in the URL fragment; prefix the portal origin. Null with token."
    )


class DirectLinkResolve(In):
    token: Annotated[str, StringConstraints(min_length=8, max_length=64)]


class PublicDirectLinkOut(Out):
    session_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    location_name: str
    time_zone: str
    spots_left: int


class ParticipantAdd(In):
    client_id: UUID


class ParticipantUpdate(In):
    attendance: Literal["scheduled", "attended", "no_show"]


class ParticipantOut(Out):
    id: UUID
    booking_id: UUID
    client_id: UUID
    client_name: str | None
    is_organiser: bool
    attendance: Literal["scheduled", "attended", "no_show"]
    attendance_marked_at: datetime | None
    created_at: datetime


class SeriesMerge(In):
    booking_number: Annotated[int, Field(ge=1, le=2**31 - 1)]  # an int4 column
