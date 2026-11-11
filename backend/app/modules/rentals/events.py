"""Events the rentals context emits (overview section 2). Thin payloads: ids and the transition."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _RentalEvent(Event):
    aggregate_type: ClassVar[str] = "rental_booking"
    rental_booking_id: UUID
    booking_id: UUID
    location_id: UUID


class RentalBooked(_RentalEvent):
    type: Literal["rentals.rental.booked"] = "rentals.rental.booked"


class RentalExtended(Event):
    aggregate_type: ClassVar[str] = "booking_series"
    type: Literal["rentals.rental.extended"] = "rentals.rental.extended"
    booking_series_id: UUID
    location_id: UUID


class RentalCancelled(_RentalEvent):
    type: Literal["rentals.rental.cancelled"] = "rentals.rental.cancelled"


class RentalPlanSold(Event):
    aggregate_type: ClassVar[str] = "rental_plan_purchase"
    type: Literal["rentals.rental_plan.sold"] = "rentals.rental_plan.sold"
    rental_plan_purchase_id: UUID
    client_id: UUID
