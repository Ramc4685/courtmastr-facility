"""Events the scheduling context emits (overview section 2). Thin payloads: ids and the transition."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _BookingEvent(Event):
    aggregate_type: ClassVar[str] = "booking"
    booking_id: UUID
    location_id: UUID
    kind: str
    block_kind: str | None = None
    source_context: str | None = None
    source_type: str | None = None
    source_id: UUID | None = None


class BookingCreated(_BookingEvent):
    type: Literal["scheduling.booking.created"] = "scheduling.booking.created"


class BookingRescheduled(_BookingEvent):
    type: Literal["scheduling.booking.rescheduled"] = "scheduling.booking.rescheduled"


class BookingCancelled(_BookingEvent):
    type: Literal["scheduling.booking.cancelled"] = "scheduling.booking.cancelled"
    cancel_reason: str


class HoldExpired(_BookingEvent):
    type: Literal["scheduling.hold.expired"] = "scheduling.hold.expired"


class _SessionEvent(Event):
    aggregate_type: ClassVar[str] = "session"
    session_id: UUID
    booking_id: UUID
    location_id: UUID


class SessionCreated(_SessionEvent):
    type: Literal["scheduling.session.created"] = "scheduling.session.created"


class SessionCancelled(_SessionEvent):
    type: Literal["scheduling.session.cancelled"] = "scheduling.session.cancelled"


class SessionCapacityChanged(_SessionEvent):
    type: Literal["scheduling.session.capacity_changed"] = "scheduling.session.capacity_changed"
    old_capacity: int
    new_capacity: int


class SeriesGenerated(Event):
    aggregate_type: ClassVar[str] = "booking_series"
    type: Literal["scheduling.series.generated"] = "scheduling.series.generated"
    booking_series_id: UUID
    booking_series_rule_id: UUID
    created_count: int
    conflict_count: int


class SlotOfferSaved(Event):
    """A slot offer was created or changed (SCH-07, SCH-18): portal schedules re-read its slots."""

    aggregate_type: ClassVar[str] = "slot_offer"
    type: Literal["scheduling.slot_offer.saved"] = "scheduling.slot_offer.saved"
    slot_offer_id: UUID
    location_id: UUID
    is_active: bool


class ReservationTypeGrantsReplaced(Event):
    """The staff allowed to book a reservation type changed (SCH-05). Empty means open to all staff."""

    aggregate_type: ClassVar[str] = "reservation_type"
    type: Literal["scheduling.reservation_type.grants_replaced"] = "scheduling.reservation_type.grants_replaced"
    reservation_type_id: UUID
    staff_user_count: int


class DirectLinkChanged(Event):
    """A session's direct registration link was turned on or revoked (SCH-16)."""

    aggregate_type: ClassVar[str] = "session"
    type: Literal["scheduling.session.direct_link_changed"] = "scheduling.session.direct_link_changed"
    session_id: UUID
    location_id: UUID
    is_active: bool


class _ParticipantEvent(Event):
    aggregate_type: ClassVar[str] = "booking_participant"
    participant_id: UUID
    booking_id: UUID
    location_id: UUID
    client_id: UUID
    attendance: str


class ParticipantAdded(_ParticipantEvent):
    """A client joined a shared booking (SCH-17, SSP-09)."""

    type: Literal["scheduling.participant.added"] = "scheduling.participant.added"


class ParticipantRemoved(_ParticipantEvent):
    type: Literal["scheduling.participant.removed"] = "scheduling.participant.removed"


class ParticipantAttendanceMarked(_ParticipantEvent):
    type: Literal["scheduling.participant.attendance_marked"] = "scheduling.participant.attendance_marked"


class SeriesMerged(Event):
    """Another booking or series was merged into this series (SCH-21)."""

    aggregate_type: ClassVar[str] = "booking_series"
    type: Literal["scheduling.series.merged"] = "scheduling.series.merged"
    booking_series_id: UUID
    location_id: UUID
    merged_booking_count: int
