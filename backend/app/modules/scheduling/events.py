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
