"""scheduling HTTP surface (docs/api/openapi-core.yaml, tag scheduling). Not built: the public schedule and slot
offer direct links (see README)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import AwareDatetime

from app.core.api import TxRoute, camel_id
from app.core.auth import system_principal
from app.core.auth.deps import Ctx, public_session, require
from app.core.errors import ValidationFailed
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import rate_limit
from app.modules.scheduling import offers, service, sharing
from app.modules.scheduling import schemas as s

router = APIRouter(
    route_class=TxRoute, tags=["scheduling"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
public = APIRouter(route_class=TxRoute, tags=["scheduling"], generate_unique_id_function=camel_id)
Lists = Annotated[ListQuery, Depends(list_query)]
Staff = Depends(require())
Read = Depends(require(service.READ))
Types = Depends(require(service.TYPES))
Location = Depends(require(service.LOCATION))
Write = Depends(require(service.CREATE, service.BLOCK))
Change = Depends(require(service.UPDATE, service.BLOCK))
Instant = AwareDatetime  # RFC 3339 instant with an offset


def _uuids(raw: str | None, name: str) -> list[UUID] | None:
    try:
        return [UUID(part) for part in raw.split(",") if part] if raw else None
    except ValueError:
        raise ValidationFailed(f"Invalid value for {name}", pointer=f"/{name}") from None


# --- settings, categories, types ---------------------------------------------------------------------------


@router.get("/scheduling-settings", response_model=s.SettingsOut)
def get_scheduling_settings(location_id: UUID | None = None, ctx: Ctx = Staff):
    """The location's settings, or the tenant default it inherits when it has no row of its own."""
    return service.get_settings(ctx.session, ctx.principal, location_id)


@router.patch("/scheduling-settings", response_model=s.SettingsOut)
def update_scheduling_settings(body: s.SettingsUpdate, location_id: UUID | None = None, ctx: Ctx = Location):
    data = body.model_dump(exclude_unset=True)
    return service.update_settings(ctx.session, ctx.principal, location_id, data)


@router.get("/reservation-categories", response_model=s.Page[s.CategoryOut])
def list_reservation_categories(query: Lists, ctx: Ctx = Staff):
    return service.list_categories(ctx.session, ctx.principal, query)


@router.post("/reservation-categories", response_model=s.CategoryOut, status_code=201)
def create_reservation_category(body: s.CategoryCreate, ctx: Ctx = Types):
    return service.create_category(ctx.session, ctx.principal, body.model_dump())


@router.patch("/reservation-categories/{reservation_category_id}", response_model=s.CategoryOut)
def update_reservation_category(reservation_category_id: UUID, body: s.CategoryUpdate, ctx: Ctx = Types):
    data = body.model_dump(exclude_unset=True)
    return service.update_category(ctx.session, ctx.principal, reservation_category_id, data)


@router.get("/reservation-types", response_model=s.Page[s.TypeOut])
def list_reservation_types(query: Lists, ctx: Ctx = Staff):
    """Filters: location_id, is_active, is_schedulable, reservation_category_id; q searches the name."""
    return service.list_types(ctx.session, ctx.principal, query)


@router.post("/reservation-types", response_model=s.TypeOut, status_code=201)
def create_reservation_type(body: s.TypeCreate, ctx: Ctx = Types):
    return service.create_type(ctx.session, ctx.principal, body.model_dump(exclude_none=True))


@router.get("/reservation-types/{reservation_type_id}", response_model=s.TypeOut)
def get_reservation_type(reservation_type_id: UUID, ctx: Ctx = Staff):
    return service.get_type(ctx.session, ctx.principal, reservation_type_id)


@router.patch("/reservation-types/{reservation_type_id}", response_model=s.TypeOut)
def update_reservation_type(reservation_type_id: UUID, body: s.TypeUpdate, ctx: Ctx = Types):
    """Defaults are copied at creation: an edit never changes existing bookings or sessions."""
    data = body.model_dump(exclude_unset=True)
    return service.update_type(ctx.session, ctx.principal, reservation_type_id, data)


@router.get("/reservation-types/{reservation_type_id}/grants", response_model=s.TypeGrants)
def list_reservation_type_grants(reservation_type_id: UUID, ctx: Ctx = Depends(require(service.GRANTS))):
    """Staff allowed to book this type (SCH-05). Not restricted means every staff user with the booking keys."""
    return offers.get_grants(ctx.session, ctx.principal, reservation_type_id)


@router.put("/reservation-types/{reservation_type_id}/grants", response_model=s.TypeGrants)
def replace_reservation_type_grants(
    reservation_type_id: UUID, body: s.TypeGrantsReplace, ctx: Ctx = Depends(require(service.GRANTS))
):
    """Restrict booking this type to these staff users; an empty list opens it to all staff again."""
    return offers.replace_grants(ctx.session, ctx.principal, reservation_type_id, body.staff_user_ids)


# --- blackouts ---------------------------------------------------------------------------------------------


@router.get("/blackouts", response_model=list[s.BlackoutOut])
def list_blackouts(location_id: UUID, from_: Instant | None = Query(None, alias="from"), to: Instant | None = None, ctx: Ctx = Staff):  # fmt: skip
    return service.list_blackouts(ctx.session, ctx.principal, location_id, from_, to)


@router.post("/blackouts", response_model=s.BlackoutSaved, status_code=201)
def create_blackout(body: s.BlackoutCreate, ctx: Ctx = Location):
    """Existing bookings inside the closure are returned, never cancelled."""
    return service.create_blackout(ctx.session, ctx.principal, body.model_dump())


@router.patch("/blackouts/{blackout_id}", response_model=s.BlackoutSaved)
def update_blackout(blackout_id: UUID, body: s.BlackoutUpdate, ctx: Ctx = Location):
    return service.update_blackout(ctx.session, ctx.principal, blackout_id, body.model_dump(exclude_unset=True))


@router.delete("/blackouts/{blackout_id}", status_code=204)
def delete_blackout(blackout_id: UUID, ctx: Ctx = Location):
    service.delete_blackout(ctx.session, ctx.principal, blackout_id)


# --- reads -------------------------------------------------------------------------------------------------


@router.get("/calendar", response_model=s.CalendarView)
def get_calendar(
    location_id: UUID, from_: Instant = Query(alias="from"), to: Instant = Query(),
    resource_group_id: UUID | None = None, resource_ids: str | None = Query(None, alias="resource_id[in]"),
    kinds: str | None = Query(None, alias="kind[in]"),
    reservation_type_ids: str | None = Query(None, alias="reservation_type_id[in]"), ctx: Ctx = Read,
):  # fmt: skip
    """Not paginated: one window of at most 42 days, one query. Serves the day, week, month and resource
    views; `legend` carries the colour and fill vocabulary."""
    return service.get_calendar(
        ctx.session, ctx.principal, location_id, from_, to, resource_group_id=resource_group_id,
        resource_ids=_uuids(resource_ids, "resource_id[in]"), kinds=kinds.split(",") if kinds else None,
        reservation_type_ids=_uuids(reservation_type_ids, "reservation_type_id[in]"),
    )  # fmt: skip


@router.get("/availability", response_model=s.Availability)
def get_resource_availability(
    location_id: UUID, from_: Instant = Query(alias="from"), to: Instant = Query(),
    resource_ids: str | None = Query(None, alias="resource_id[in]"), min_free_min: int = Query(15, ge=1, le=1440),
    ctx: Ctx = Read,
):  # fmt: skip
    """Free intervals per resource: availability windows (or facility hours) minus holds and closures."""
    ids = _uuids(resource_ids, "resource_id[in]")
    return service.get_availability(
        ctx.session, ctx.principal, location_id, from_, to, resource_ids=ids, min_free_min=min_free_min
    )


# --- bookings ----------------------------------------------------------------------------------------------


@router.get("/bookings", response_model=s.Page[s.BookingOut])
def list_bookings(query: Lists, ctx: Ctx = Read):
    """Filters: location_id, kind, status, booking_series_id, reservation_type_id, client_id, occurrence_on,
    starts_at, booking_number; q searches the title. Sort: occurrence_on, starts_at, booking_number."""
    return service.list_bookings(ctx.session, ctx.principal, query)


@router.post("/bookings", response_model=s.BookingCreated, status_code=201)
def create_booking(body: s.BookingCreate, response: Response, ctx: Ctx = Write):
    """A session or time block, single or recurring. Above 50 occurrences the answer is 202 with
    `status_url`. Errors: booking-conflict (with `conflicts[]` naming each rival booking),
    resource-blacked-out, series-too-long."""
    result = service.create_booking_command(ctx.session, ctx.principal, body.model_dump())
    if result["status_url"]:
        response.status_code = 202
    return result


@router.post("/bookings/preview", response_model=s.SeriesPreview)
def preview_booking(body: s.BookingCreate, ctx: Ctx = Write):
    """Dry run of a create: every occurrence with what it would meet. Nothing is written."""
    return service.create_booking_command(ctx.session, ctx.principal, body.model_dump(), preview=True)


@router.get("/bookings/{booking_id}", response_model=s.BookingOut)
def get_booking(booking_id: UUID, ctx: Ctx = Read):
    return service.get_booking_view(ctx.session, ctx.principal, booking_id)


@router.patch("/bookings/{booking_id}", response_model=s.BookingOut)
def update_booking(booking_id: UUID, body: s.BookingUpdate, ctx: Ctx = Change):
    """Errors: version-conflict, booking-conflict (buffer change)."""
    return service.update_booking_command(ctx.session, ctx.principal, booking_id, body.model_dump(exclude_unset=True))


@router.post("/bookings/{booking_id}/reschedule", response_model=s.BookingOut)
def reschedule_booking(booking_id: UUID, body: s.BookingReschedule, ctx: Ctx = Change):
    """Move, resize or change resources; linked resources move as one. Errors: version-conflict,
    booking-conflict, resource-blacked-out."""
    return service.reschedule_command(ctx.session, ctx.principal, booking_id, body.model_dump())


@router.post("/bookings/{booking_id}/cancel", response_model=s.BookingOut)
def cancel_booking(booking_id: UUID, body: s.BookingCancel, ctx: Ctx = Depends(require(service.DELETE, service.BLOCK))):
    """Soft cancel: every resource of the booking is released together."""
    return service.cancel_command(ctx.session, ctx.principal, booking_id, body.model_dump())


# --- series ------------------------------------------------------------------------------------------------


@router.get("/booking-series/{booking_series_id}", response_model=s.SeriesOut)
def get_booking_series(booking_series_id: UUID, ctx: Ctx = Read):
    return service.get_series(ctx.session, ctx.principal, booking_series_id)


@router.get("/booking-series/{booking_series_id}/rules/{rule_id}", response_model=s.SeriesRuleOut)
def get_booking_series_rule(booking_series_id: UUID, rule_id: UUID, ctx: Ctx = Read):
    return service.get_series_rule(ctx.session, ctx.principal, booking_series_id, rule_id)


@router.post("/booking-series/{booking_series_id}/rules", response_model=s.SeriesRuleAdded, status_code=201)
def add_booking_series_rule(booking_series_id: UUID, body: s.SeriesRuleAdd, response: Response, ctx: Ctx = Depends(require(service.UPDATE_SERIES))):  # fmt: skip
    """Stack another pass onto a series. `preview: true` returns the dry run only."""
    result = service.add_series_rule(ctx.session, ctx.principal, booking_series_id, body.model_dump())
    if result.get("status_url"):
        response.status_code = 202
    return result


@router.post("/booking-series/{booking_series_id}/edits", response_model=s.SeriesCommandResult)
def edit_booking_series(
    booking_series_id: UUID, body: s.SeriesEdit, ctx: Ctx = Depends(require(service.UPDATE_SERIES))
):
    """Mass edit over a scope (this, following, all, selected, date_range). Only supplied fields change."""
    data = body.model_dump() | {"patch": body.patch.model_dump(exclude_unset=True)}
    return service.edit_series(ctx.session, ctx.principal, booking_series_id, data)


@router.patch("/booking-series/{booking_series_id}/rules/{rule_id}", response_model=s.SeriesRuleChanged)
def update_booking_series_rule(
    booking_series_id: UUID, rule_id: UUID, body: s.SeriesRuleChange, response: Response,
    ctx: Ctx = Depends(require(service.UPDATE_SERIES)),
):  # fmt: skip
    """Change a pass's pattern from `start_on`: its later occurrences are cancelled and the new pattern is
    booked in one command. `preview: true` returns the dry run (new occurrences and the cancel count) only."""
    result = service.change_series_rule(ctx.session, ctx.principal, booking_series_id, rule_id, body.model_dump())
    if result.get("status_url"):
        response.status_code = 202
    return result


@router.get("/booking-series/{booking_series_id}/runs/{run_id}", response_model=s.SeriesRunOut)
def get_booking_series_run(booking_series_id: UUID, run_id: UUID, ctx: Ctx = Read):
    """Status of a long generation pass, with the occurrences that could not be booked."""
    return service.get_series_run(ctx.session, ctx.principal, booking_series_id, run_id)


@router.post("/booking-series/{booking_series_id}/cancellations", response_model=s.SeriesCommandResult)
def cancel_booking_series(
    booking_series_id: UUID, body: s.SeriesCancel, ctx: Ctx = Depends(require(service.DELETE_SERIES))
):
    return service.cancel_series(ctx.session, ctx.principal, booking_series_id, body.model_dump())


# --- sessions ----------------------------------------------------------------------------------------------


@router.get("/sessions", response_model=s.Page[s.SessionOut])
def list_sessions(query: Lists, ctx: Ctx = Read):
    """Filters: location_id, starts_at, status, reservation_type_id, booking_series_id, is_self_bookable."""
    return service.list_sessions(ctx.session, ctx.principal, query)


@router.post("/sessions/capacity-changes", response_model=s.CapacityChanged)
def change_session_capacity(body: s.CapacityChange, ctx: Ctx = Depends(require(service.CAPACITY))):
    """Single or bulk class size. A session with more seats taken is reported capacity-below-booked."""
    return service.change_capacity(ctx.session, ctx.principal, body.session_ids, body.capacity)


@router.get("/sessions/{schedule_session_id}", response_model=s.SessionOut)
def get_session(schedule_session_id: UUID, ctx: Ctx = Read):
    return service.get_session_view(ctx.session, ctx.principal, schedule_session_id)


@router.patch("/sessions/{schedule_session_id}", response_model=s.SessionOut)
def update_session(schedule_session_id: UUID, body: s.SessionUpdate, ctx: Ctx = Depends(require(service.SESSION))):
    return service.update_session(ctx.session, ctx.principal, schedule_session_id, body.model_dump(exclude_none=True))


# --- slot offers -------------------------------------------------------------------------------------------


@router.get("/slot-offers", response_model=s.Page[s.SlotOfferOut])
def list_slot_offers(query: Lists, ctx: Ctx = Read):
    """Filters: location_id, reservation_type_id, availability_window_id, is_active; resource_id (the window's)."""
    return offers.list_offers(ctx.session, ctx.principal, query)


@router.post("/slot-offers", response_model=s.SlotOfferOut, status_code=201)
def create_slot_offer(body: s.SlotOfferCreate, ctx: Ctx = Depends(require(service.SESSION))):
    """Offer an availability window as bookable slots of fixed length (SCH-07 split into slots, SCH-18)."""
    return offers.create_offer(ctx.session, ctx.principal, body.model_dump())


@router.patch("/slot-offers/{slot_offer_id}", response_model=s.SlotOfferOut)
def update_slot_offer(slot_offer_id: UUID, body: s.SlotOfferUpdate, ctx: Ctx = Depends(require(service.SESSION))):
    return offers.update_offer(ctx.session, ctx.principal, slot_offer_id, body.model_dump(exclude_unset=True))


@router.get("/slot-offers/{slot_offer_id}/slots", response_model=s.SlotList)
def list_slot_offer_slots(slot_offer_id: UUID, from_: Instant | None = Query(None, alias="from"), to: Instant | None = None, ctx: Ctx = Read):  # fmt: skip
    """Derived slots over at most 42 days (default: the next 7): free, booked, full or unavailable."""
    return offers.slots(ctx.session, ctx.principal, slot_offer_id, from_, to)


@router.post("/slot-offers/{slot_offer_id}/slots", response_model=s.BookingOut)
def book_slot_offer_slot(slot_offer_id: UUID, body: s.SlotBook, ctx: Ctx = Depends(require(service.CREATE))):
    """Take one slot: its session is created (or the existing one returned) so clients can be registered."""
    return offers.book_slot(ctx.session, ctx.principal, slot_offer_id, body.starts_at)


# --- direct registration links (SCH-16) --------------------------------------------------------------------


@router.post("/sessions/{schedule_session_id}/direct-link", response_model=s.DirectLinkOut)
def create_session_direct_link(schedule_session_id: UUID, ctx: Ctx = Depends(require(sharing.LINK))):
    """Turn on the session's reusable link, or return it when it is on. Share `path` (token in the fragment)."""
    return sharing.create_link(ctx.session, ctx.principal, schedule_session_id)


@router.delete("/sessions/{schedule_session_id}/direct-link", status_code=204)
def revoke_session_direct_link(schedule_session_id: UUID, ctx: Ctx = Depends(require(sharing.LINK))):
    """Stop the link; every copy already sent stops working. A new link has a new token."""
    sharing.revoke_link(ctx.session, ctx.principal, schedule_session_id)
    return Response(status_code=204)


@public.post("/public/direct-links/resolve", response_model=s.PublicDirectLinkOut,
             dependencies=[Depends(rate_limit("direct-link"))])  # fmt: skip
def resolve_direct_link(body: s.DirectLinkResolve, request: Request):
    """The session a direct link names, listed or not. The token travels in the body, never the URL. Tenant from
    the host or X-Tenant-Slug. Booking it is the portal's enrolment. Errors: link-invalid (404)."""
    session = public_session(request)
    session.info["actor"] = system_principal("public")
    return sharing.resolve_link(session, body.token)


# --- shared bookings (SCH-17, SSP-09) ----------------------------------------------------------------------


@router.get("/bookings/{booking_id}/participants", response_model=list[s.ParticipantOut])
def list_booking_participants(booking_id: UUID, ctx: Ctx = Read):
    return sharing.list_participants(ctx.session, ctx.principal, booking_id)


@router.post("/bookings/{booking_id}/participants", response_model=list[s.ParticipantOut], status_code=201)
def add_booking_participant(body: s.ParticipantAdd, booking_id: UUID, ctx: Ctx = Depends(require(sharing.ENROLL))):
    """Share the booking with a related client of its organiser. Returns everyone on it. Errors: already-enrolled."""
    return sharing.add_participant(ctx.session, ctx.principal, booking_id, body.client_id)


@router.patch("/bookings/{booking_id}/participants/{participant_id}", response_model=s.ParticipantOut)
def update_booking_participant(
    booking_id: UUID, participant_id: UUID, body: s.ParticipantUpdate, ctx: Ctx = Depends(require(sharing.MARK))
):
    """Mark one participant's attendance (no-show needs scheduling.attendance.mark_exception)."""
    return sharing.mark_attendance(ctx.session, ctx.principal, booking_id, participant_id, body.attendance)


@router.delete("/bookings/{booking_id}/participants/{participant_id}", status_code=204)
def remove_booking_participant(booking_id: UUID, participant_id: UUID, ctx: Ctx = Depends(require(sharing.UNENROLL))):
    sharing.remove_participant(ctx.session, ctx.principal, booking_id, participant_id)
    return Response(status_code=204)


# --- series merge (SCH-21) ---------------------------------------------------------------------------------


@router.post("/bookings/{booking_id}/merge", response_model=s.SeriesOut)
def merge_booking_series(booking_id: UUID, body: s.SeriesMerge, ctx: Ctx = Depends(require(service.UPDATE_SERIES))):
    """Link the booking with that number (or its whole series) into this booking's series. Errors:
    already-linked, merge-mismatch (another location, kind or client)."""
    return service.merge_series(ctx.session, ctx.principal, booking_id, body.model_dump())
