"""rentals HTTP surface (docs/api/openapi-core.yaml, tag rentals). Not routed: updateRental (P1; move a rental
on the calendar instead; see README)."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, current_ctx, public_session, require
from app.core.idempotency import KEY_PATTERN, idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.rentals import schemas as s
from app.modules.rentals import service

staff = APIRouter(
    route_class=TxRoute, tags=["rentals"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
public = APIRouter(route_class=TxRoute, tags=["rentals"], generate_unique_id_function=camel_id)  # anonymous
Lists = Annotated[ListQuery, Depends(list_query)]
Staff = Depends(require())
Read = Depends(require(service.READ))
Types = Depends(require(service.TYPES))
Plans = Depends(require(service.PLANS))
Sell = Depends(require(service.SELL))
Share = Depends(require(service.SHARE))
Lockers = Depends(require(service.LOCKER_RENT))
ActFor = Annotated[UUID | None, Query(alias="client_id")]
PortalSettings = Depends(require(service.PORTAL_SETTINGS))
Public = Annotated[Session, Depends(public_session)]
Client = Annotated[Ctx, Depends(current_ctx)]
# The parameter must be called idempotency_key: it then merges with the router-level optional header in OpenAPI.
RequiredKey = Annotated[
    str, Header(min_length=8, max_length=255, pattern=KEY_PATTERN, description="Required; keys live 24 hours.")
]


# --- types and rates ---------------------------------------------------------------------------------------


@staff.get("/rental-types", response_model=s.Page[s.RentalTypeOut])
def list_rental_types(query: Lists, ctx: Ctx = Staff):
    """Filters: location_id, is_active, access. Sort: sort_order, name. q searches the name."""
    return service.list_types(ctx.session, ctx.principal, query)


@staff.post("/rental-types", response_model=s.RentalTypeOut, status_code=201)
def create_rental_type(body: s.RentalTypeCreate, ctx: Ctx = Types):
    return service.create_type(ctx.session, ctx.principal, body.model_dump())


@staff.get("/rental-types/{rental_type_id}", response_model=s.RentalTypeOut)
def get_rental_type(rental_type_id: UUID, ctx: Ctx = Staff):
    return service.get_type(ctx.session, ctx.principal, rental_type_id)


@staff.patch("/rental-types/{rental_type_id}", response_model=s.RentalTypeOut)
def update_rental_type(rental_type_id: UUID, body: s.RentalTypeUpdate, ctx: Ctx = Types):
    """`resource_ids` and `rental_plan_ids` replace the whole set when given."""
    return service.update_type(ctx.session, ctx.principal, rental_type_id, body.model_dump(exclude_unset=True))


@staff.get("/rental-types/{rental_type_id}/rates", response_model=s.Page[s.RentalRateOut])
def list_rental_rates(rental_type_id: UUID, query: Lists, ctx: Ctx = Staff):
    return service.list_rates(ctx.session, ctx.principal, rental_type_id, query)


@staff.post("/rental-types/{rental_type_id}/rates", response_model=s.RentalRateOut, status_code=201)
def create_rental_rate(rental_type_id: UUID, body: s.RentalRateWrite, ctx: Ctx = Types):
    return service.create_rate(ctx.session, ctx.principal, rental_type_id, body.model_dump())


@staff.get("/rental-rates/{rental_rate_id}", response_model=s.RentalRateOut)
def get_rental_rate(rental_rate_id: UUID, ctx: Ctx = Staff):
    return service.get_rate(ctx.session, ctx.principal, rental_rate_id)


@staff.patch("/rental-rates/{rental_rate_id}", response_model=s.RentalRateOut)
def update_rental_rate(rental_rate_id: UUID, body: s.RentalRateWrite, ctx: Ctx = Types):
    return service.update_rate(ctx.session, ctx.principal, rental_rate_id, body.model_dump(exclude_unset=True))


# --- rentals -----------------------------------------------------------------------------------------------


@staff.get("/rentals", response_model=s.Page[s.RentalOut])
def list_rentals(query: Lists, ctx: Ctx = Read):
    """Filters: location_id, rental_type_id, charge_state, booked_via, starts_at[gte|lt], and booking-side
    client_id, status, booking_series_id, resource_id. `charge_state=unbilled` is the unbilled queue."""
    return service.list_rentals(ctx.session, ctx.principal, query)


@staff.post("/rentals", response_model=s.RentalCreated, status_code=201)
def create_rental(body: s.RentalCreate, response: Response, idempotency_key: RequiredKey, ctx: Ctx = Depends(require(service.CREATE))):  # fmt: skip
    """Book and decide billing in one transaction. Above 50 occurrences: 202 with `status_url`, unbilled.
    Errors: booking-conflict, resource-blacked-out, rate-not-applicable, insufficient-plan-balance."""
    result = service.create_rental(ctx.session, ctx.principal, body.model_dump())
    if result["status_url"]:
        response.status_code = 202
    return result


@staff.post("/rentals/preview", response_model=s.RentalPreview)
def preview_rental(body: s.RentalCreate, ctx: Ctx = Depends(require(service.CREATE))):
    """Dry run: what each occurrence would meet and the quote of the bookable ones. Nothing is written."""
    return service.preview_rental(ctx.session, ctx.principal, body.model_dump())


@staff.post("/rentals/charges", response_model=s.Billed)
def bill_selected_rentals(body: s.BillSelected, idempotency_key: RequiredKey, ctx: Ctx = Depends(require(service.UPDATE))):  # fmt: skip
    """Bill unbilled occurrences of one client and type. `preview: true` returns the quote only."""
    return service.bill_selected(ctx.session, ctx.principal, body.model_dump())


@staff.get("/rentals/{rental_id}", response_model=s.RentalOut)
def get_rental(rental_id: UUID, ctx: Ctx = Read):
    return service.get_rental(ctx.session, ctx.principal, rental_id)


@staff.post("/rentals/{rental_id}/cancel", response_model=s.RentalCancelResult)
def cancel_rental(rental_id: UUID, body: s.RentalCancel, ctx: Ctx = Depends(require(service.CANCEL))):
    """Cancel this occurrence or a scope of its series and settle the money (reverse, re-post, credit)."""
    return service.cancel_rental(ctx.session, ctx.principal, rental_id, body.model_dump())


@staff.post("/rentals/{rental_id}/extensions", response_model=s.Extended, status_code=201)
def extend_rental(rental_id: UUID, body: s.Extension, response: Response, ctx: Ctx = Depends(require(service.UPDATE))):
    """Add occurrences to a recurring rental; they arrive unbilled. 202 with `status_url` above 50."""
    result = service.extend_rental(ctx.session, ctx.principal, rental_id, body.model_dump())
    if result.get("status_url"):
        response.status_code = 202
    return result


@staff.put("/rentals/{rental_id}/public-schedule", response_model=s.RentalOut)
def set_rental_public_schedule(rental_id: UUID, body: s.PublicSchedule, ctx: Ctx = Depends(require(service.PUBLISH))):
    return service.set_public_schedule(ctx.session, ctx.principal, rental_id, body.is_on_public_schedule)


# --- online ------------------------------------------------------------------------------------------------


@public.get("/public/rental-types", response_model=list[s.PublicRentalType])
def list_public_rental_types(session: Public):
    return service.list_public_types(session)


@public.get("/public/rental-availability", response_model=s.Page[s.RentalSlot])
def search_rental_availability(
    session: Public, rental_type_id: UUID, on: Annotated[date, Query(alias="on")], length_min: int | None = None,
    resource_id: UUID | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 200,
):  # fmt: skip
    """Advisory: the hold insert at checkout decides. One page of at most `limit` slots for the day."""
    slots = service.search_availability(session, rental_type_id, on, length_min=length_min, resource_id=resource_id)
    return {"data": slots[:limit], "page": {"next_cursor": None, "has_more": len(slots) > limit}}


@staff.get("/locations/{location_id}/rental-portal-settings", response_model=s.RentalPortalSettingsOut)
def get_rental_portal_settings(location_id: UUID, ctx: Ctx = PortalSettings):
    return service.get_portal_settings(ctx.session, ctx.principal, location_id)


@staff.put("/locations/{location_id}/rental-portal-settings", response_model=s.RentalPortalSettingsOut)
def put_rental_portal_settings(location_id: UUID, body: s.RentalPortalSettings, ctx: Ctx = PortalSettings):
    """SSP-04: whether the portal books rentals at this location, and limits for every self-service type."""
    return service.put_portal_settings(ctx.session, ctx.principal, location_id, body.model_dump())


@staff.get("/portal/rentals", response_model=s.Page[s.PortalRentalOut])
def list_portal_rentals(query: Lists, ctx: Client):
    return service.list_portal_rentals(ctx.session, ctx.principal, query)


@staff.post("/portal/rentals", response_model=s.PortalRentalCheckout, status_code=201)
def create_portal_rental(body: s.PortalRentalCreate, ctx: Client):
    """Holds the time for the location's checkout window (scheduling settings) while the client pays."""
    return service.create_portal_rental(ctx.session, ctx.principal, body.model_dump())


@staff.post("/portal/rentals/{rental_id}/confirm", response_model=s.PortalRentalCheckout)
def confirm_portal_rental(rental_id: UUID, body: s.PortalRentalConfirm, idempotency_key: RequiredKey, ctx: Client):
    """Pays through secure_online_checkout. Errors: hold-expired, payment-failed, payment-method-required,
    payment-method-not-usable, provider-unavailable (503, retry with the same key)."""
    return service.confirm_portal_rental(ctx.session, ctx.principal, rental_id, body.model_dump(), idempotency_key)


@staff.post("/portal/rentals/{rental_id}/abandon", status_code=204)
def abandon_portal_rental(rental_id: UUID, ctx: Client):
    service.abandon_portal_rental(ctx.session, ctx.principal, rental_id)


@staff.post("/portal/rentals/{rental_id}/cancel", response_model=s.PortalRentalCancelResult)
def cancel_portal_rental(rental_id: UUID, ctx: Client):
    return service.cancel_portal_rental(ctx.session, ctx.principal, rental_id)


# --- plans -------------------------------------------------------------------------------------------------


@staff.get("/rental-plans", response_model=s.Page[s.RentalPlanOut])
def list_rental_plans(query: Lists, ctx: Ctx = Staff):
    """Filters: location_id, status, rental_type_id. q searches the name."""
    return service.list_plans(ctx.session, ctx.principal, query)


@staff.post("/rental-plans", response_model=s.RentalPlanOut, status_code=201)
def create_rental_plan(body: s.RentalPlanCreate, ctx: Ctx = Plans):
    return service.create_plan(ctx.session, ctx.principal, body.model_dump())


@staff.get("/rental-plans/{rental_plan_id}", response_model=s.RentalPlanOut)
def get_rental_plan(rental_plan_id: UUID, ctx: Ctx = Staff):
    return service.get_plan(ctx.session, ctx.principal, rental_plan_id)


@staff.patch("/rental-plans/{rental_plan_id}", response_model=s.RentalPlanOut)
def update_rental_plan(rental_plan_id: UUID, body: s.RentalPlanUpdate, ctx: Ctx = Plans):
    return service.update_plan(ctx.session, ctx.principal, rental_plan_id, body.model_dump(exclude_unset=True))


@staff.delete("/rental-plans/{rental_plan_id}", status_code=204)
def delete_rental_plan(rental_plan_id: UUID, ctx: Ctx = Plans):
    """Archives the plan: sold purchases are unaffected."""
    service.archive_plan(ctx.session, ctx.principal, rental_plan_id)


@staff.get("/rental-plan-purchases", response_model=s.Page[s.PurchaseOut])
def list_rental_plan_purchases(query: Lists, ctx: Ctx = Sell):
    """Filters: location_id, client_id, status, rental_plan_id."""
    return service.list_purchases(ctx.session, ctx.principal, query)


@staff.post("/rental-plan-purchases", response_model=s.PurchaseOut, status_code=201)
def sell_rental_plan(body: s.PlanSale, idempotency_key: RequiredKey, ctx: Ctx = Sell):
    return service.sell_plan(ctx.session, ctx.principal, body.model_dump())


@staff.get("/rental-plan-purchases/{purchase_id}", response_model=s.PurchaseOut)
def get_rental_plan_purchase(purchase_id: UUID, ctx: Ctx = Sell):
    return service.get_purchase(ctx.session, ctx.principal, purchase_id)


@staff.get("/rental-plan-purchases/{purchase_id}/ledger", response_model=list[s.RentalPlanLedgerEntryOut])
def list_rental_plan_ledger(purchase_id: UUID, ctx: Ctx = Sell):
    return service.list_ledger(ctx.session, ctx.principal, purchase_id)


@staff.patch("/rental-plan-purchases/{purchase_id}", response_model=s.PurchaseOut)
def update_rental_plan_purchase(purchase_id: UUID, body: s.PurchaseUpdate, ctx: Ctx = Sell):
    """Auto-renew and autopay of one purchase. Errors: plan-not-valid."""
    return service.update_purchase(ctx.session, ctx.principal, purchase_id, body.model_dump(exclude_unset=True))


@staff.put("/rental-plan-purchases/{purchase_id}/shares", response_model=s.PurchaseOut)
def replace_rental_plan_shares(purchase_id: UUID, body: s.RentalPlanShares, ctx: Ctx = Share):
    """Share with related clients; the list replaces the live shares. Errors: plan-not-shareable,
    client-not-related."""
    return service.replace_shares(ctx.session, ctx.principal, purchase_id, body.client_ids)


@staff.post("/rental-plan-purchases/{purchase_id}/cancel", response_model=s.PurchaseOut)
def cancel_rental_plan_purchase(purchase_id: UUID, body: s.PurchaseCancel, ctx: Ctx = Depends(require(service.REMOVE))):
    return service.cancel_purchase(ctx.session, ctx.principal, purchase_id, body.model_dump())


# --- portal plans (RNT-09, RNT-10) -------------------------------------------------------------------------


@staff.get("/portal/rental-plans", response_model=s.Page[s.PortalRentalPlanOut])
def list_portal_rental_plans(query: Lists, ctx: Client, client_id: ActFor = None):
    """Plans sold online, priced for the acting client. Filters: location_id, rental_type_id."""
    query.filters.pop("client_id", None)
    return service.portal_list_plans(ctx.session, ctx.principal, client_id, query)


@staff.get("/portal/rental-plan-purchases", response_model=s.Page[s.PortalRentalPlanPurchaseOut])
def list_portal_rental_plan_purchases(query: Lists, ctx: Client, client_id: ActFor = None):
    """Live plans the acting client owns or may draw on through a share."""
    query.filters.pop("client_id", None)
    return service.portal_list_purchases(ctx.session, ctx.principal, client_id, query)


@staff.post("/portal/rental-plan-purchases", response_model=s.PortalRentalPlanPurchaseOut, status_code=201)
def buy_portal_rental_plan(body: s.PortalRentalPlanBuy, idempotency_key: RequiredKey, ctx: Client):
    """Errors: payment-failed (nothing is sold), membership-required."""
    return service.portal_buy_plan(ctx.session, ctx.principal, body.model_dump(), idempotency_key)


@staff.post("/portal/rental-plan-purchases/{purchase_id}/auto-renew-opt-out",
            response_model=s.PortalRentalPlanPurchaseOut)  # fmt: skip
def portal_opt_out_rental_plan_auto_renew(purchase_id: UUID, ctx: Client):
    return service.portal_disable_auto_renew(ctx.session, ctx.principal, purchase_id)


# --- locker leases (RNT-17, RNT-18) ------------------------------------------------------------------------


@staff.get("/locker-leases", response_model=s.Page[s.LockerLeaseOut])
def list_locker_leases(query: Lists, ctx: Ctx = Lockers):
    """Filters: location_id, locker_id, client_id, ends_on ([gte], [lte]), is_open. Sort: ends_on, created_at."""
    return service.list_locker_leases(ctx.session, ctx.principal, query)


@staff.post("/locker-leases", response_model=s.LockerLeaseOut, status_code=201)
def create_locker_lease(body: s.LockerLeaseCreate, ctx: Ctx = Lockers):
    """Errors: locker-already-rented, locker-unavailable, term-ended."""
    return service.create_locker_lease(ctx.session, ctx.principal, body.model_dump(exclude_unset=True))


@staff.post("/locker-leases/clear-expired", response_model=s.LockerLeaseClearResult)
def clear_expired_locker_leases(body: s.LockerLeaseClearExpired, ctx: Ctx = Lockers):
    return service.clear_expired_locker_leases(ctx.session, ctx.principal, body.model_dump())


@staff.post("/locker-leases/{locker_lease_id}/clear", response_model=s.LockerLeaseOut)
def clear_locker_lease(locker_lease_id: UUID, ctx: Ctx = Lockers):
    return service.clear_locker_lease(ctx.session, ctx.principal, locker_lease_id)


@staff.post("/locker-leases/{locker_lease_id}/renew", response_model=s.LockerLeaseOut, status_code=201)
def renew_locker_lease(locker_lease_id: UUID, body: s.LockerLeaseRenew, ctx: Ctx = Lockers):
    """Closes the lease as renewed and starts the next term with its own charge (a lapsed lease restarts
    today). Errors: lease-cleared, lease-overlaps, locker-unavailable."""
    return service.renew_locker_lease(ctx.session, ctx.principal, locker_lease_id, body.model_dump(exclude_unset=True))


router = APIRouter()
router.include_router(staff)
router.include_router(public)
