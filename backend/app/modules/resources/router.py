"""resources HTTP surface (docs/api/openapi-core.yaml, tag resources), lockers and padlocks included."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.resources import schemas as s
from app.modules.resources import service

router = APIRouter(
    route_class=TxRoute, tags=["resources"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]
Manage = Depends(require(service.MANAGE))
Windows = Depends(require(service.WINDOWS))
Staff = Depends(require())
Lockers = Depends(require(service.LOCKERS))
Padlocks = Depends(require(service.PADLOCKS))
Reveal = Depends(require(service.REVEAL))


@router.get("/resource-groups", response_model=s.Page[s.ResourceGroupOut])
def list_resource_groups(query: Lists, ctx: Ctx = Staff):
    """Filters: location_id, is_active. Sort: sort_order, name."""
    return service.list_groups(ctx.session, ctx.principal, query)


@router.post("/resource-groups", response_model=s.ResourceGroupOut, status_code=201)
def create_resource_group(body: s.ResourceGroupCreate, ctx: Ctx = Manage):
    return service.create_group(ctx.session, ctx.principal, body.model_dump())


@router.patch("/resource-groups/{resource_group_id}", response_model=s.ResourceGroupOut)
def update_resource_group(resource_group_id: UUID, body: s.ResourceGroupUpdate, ctx: Ctx = Manage):
    """Errors: resource-group-in-use when deactivating a group that still has active resources."""
    return service.update_group(ctx.session, ctx.principal, resource_group_id, body.model_dump(exclude_unset=True))


@router.get("/resources", response_model=s.Page[s.ResourceOut])
def list_resources(query: Lists, ctx: Ctx = Staff):
    """Filters: location_id, resource_group_id, kind, status, parent_id, is_online_bookable; q searches names."""
    return service.list_resources(ctx.session, ctx.principal, query)


@router.post("/resources", response_model=s.ResourceDetail, status_code=201)
def create_resource(body: s.ResourceCreate, ctx: Ctx = Manage):
    """A sub-venue (parent_id) inherits holds from its ancestors' future bookings in the same transaction.
    Errors: booking-conflict, tree-too-deep, already-exists (name)."""
    return service.create_resource(ctx.session, ctx.principal, body.model_dump())


@router.get("/resources/{resource_id}", response_model=s.ResourceDetail)
def get_resource(resource_id: UUID, ctx: Ctx = Staff):
    return service.get_resource(ctx.session, ctx.principal, resource_id)


@router.patch("/resources/{resource_id}", response_model=s.ResourceDetail)
def update_resource(resource_id: UUID, body: s.ResourceUpdate, ctx: Ctx = Manage):
    """Re-parenting rewrites inherited holds and fails as a whole with booking-conflict."""
    return service.update_resource(ctx.session, ctx.principal, resource_id, body.model_dump(exclude_unset=True))


@router.post("/resources/{resource_id}/archive", response_model=s.ResourceDetail)
def archive_resource(resource_id: UUID, ctx: Ctx = Manage):
    """Errors: resource-has-future-bookings, resource-has-children."""
    return service.archive_resource(ctx.session, ctx.principal, resource_id)


@router.post("/resources/{resource_id}/restore", response_model=s.ResourceDetail)
def restore_resource(resource_id: UUID, ctx: Ctx = Manage):
    return service.restore_resource(ctx.session, ctx.principal, resource_id)


@router.put("/resources/{resource_id}/links", response_model=s.ResourceDetail)
def replace_resource_links(resource_id: UUID, body: s.ResourceLinks, ctx: Ctx = Manage):
    """Standing links: booking this resource also holds each linked one by default (RES-05)."""
    return service.replace_links(ctx.session, ctx.principal, resource_id, body.to_resource_ids)


@router.get("/resources/{resource_id}/availability-windows", response_model=list[s.WindowOut])
def list_availability_windows(resource_id: UUID, ctx: Ctx = Staff):
    return service.list_windows(ctx.session, ctx.principal, resource_id)


@router.post("/resources/{resource_id}/availability-windows", response_model=s.WindowOut, status_code=201)
def create_availability_window(resource_id: UUID, body: s.WindowCreate, ctx: Ctx = Windows):
    return service.create_window(ctx.session, ctx.principal, resource_id, body.model_dump())


@router.patch("/availability-windows/{availability_window_id}", response_model=s.WindowOut)
def update_availability_window(availability_window_id: UUID, body: s.WindowUpdate, ctx: Ctx = Windows):
    data = body.model_dump(exclude_unset=True)
    return service.update_window(ctx.session, ctx.principal, availability_window_id, data)


@router.delete("/availability-windows/{availability_window_id}", status_code=204)
def delete_availability_window(availability_window_id: UUID, ctx: Ctx = Windows):
    service.delete_window(ctx.session, ctx.principal, availability_window_id)


# --- lockers (RES-07, RES-08) ------------------------------------------------------------------------------


@router.get("/locker-rooms", response_model=s.Page[s.LockerRoomOut])
def list_locker_rooms(query: Lists, ctx: Ctx = Staff):
    """Filters: location_id, is_active. Sort: sort_order, name."""
    return service.list_locker_rooms(ctx.session, ctx.principal, query)


@router.post("/locker-rooms", response_model=s.LockerRoomOut, status_code=201)
def create_locker_room(body: s.LockerRoomCreate, ctx: Ctx = Lockers):
    return service.create_locker_room(ctx.session, ctx.principal, body.model_dump())


@router.patch("/locker-rooms/{locker_room_id}", response_model=s.LockerRoomOut)
def update_locker_room(locker_room_id: UUID, body: s.LockerRoomUpdate, ctx: Ctx = Lockers):
    return service.update_locker_room(ctx.session, ctx.principal, locker_room_id, body.model_dump(exclude_unset=True))


@router.post("/locker-rooms/{locker_room_id}/lockers/bulk", response_model=s.LockerBulkResult, status_code=201)
def bulk_create_lockers(locker_room_id: UUID, body: s.LockerBulkCreate, ctx: Ctx = Lockers):
    """Numbers the room already has are skipped. Errors: locker-room-inactive."""
    return service.bulk_create_lockers(ctx.session, ctx.principal, locker_room_id, body.model_dump())


@router.get("/lockers", response_model=s.Page[s.LockerOut])
def list_lockers(query: Lists, ctx: Ctx = Staff):
    """Lockers with their lease state (available, rented, expired). Filters: location_id, locker_room_id, status."""
    return service.list_lockers(ctx.session, ctx.principal, query)


@router.patch("/lockers/{locker_id}", response_model=s.LockerOut)
def update_locker(locker_id: UUID, body: s.LockerUpdate, ctx: Ctx = Lockers):
    """Errors: locker-leased (taking a rented locker out of service)."""
    return service.update_locker(ctx.session, ctx.principal, locker_id, body.model_dump(exclude_unset=True))


@router.get("/locker-terms", response_model=s.Page[s.LockerTermOut])
def list_locker_terms(query: Lists, ctx: Ctx = Staff):
    """Filters: location_id, is_active."""
    return service.list_locker_terms(ctx.session, ctx.principal, query)


@router.post("/locker-terms", response_model=s.LockerTermOut, status_code=201)
def create_locker_term(body: s.LockerTermCreate, ctx: Ctx = Lockers):
    return service.create_locker_term(ctx.session, ctx.principal, body.model_dump())


@router.patch("/locker-terms/{locker_term_id}", response_model=s.LockerTermOut)
def update_locker_term(locker_term_id: UUID, body: s.LockerTermUpdate, ctx: Ctx = Lockers):
    return service.update_locker_term(ctx.session, ctx.principal, locker_term_id, body.model_dump(exclude_unset=True))


# --- padlocks (RES-09) -------------------------------------------------------------------------------------


@router.get("/padlocks", response_model=s.Page[s.PadlockOut])
def list_padlocks(query: Lists, ctx: Ctx = Padlocks):
    """Filters: location_id, status; q searches the number."""
    return service.list_padlocks(ctx.session, ctx.principal, query)


@router.post("/padlocks", response_model=s.PadlockOut, status_code=201)
def create_padlock(body: s.PadlockCreate, ctx: Ctx = Padlocks):
    return service.create_padlock(ctx.session, ctx.principal, body.model_dump())


@router.patch("/padlocks/{padlock_id}", response_model=s.PadlockOut)
def update_padlock(padlock_id: UUID, body: s.PadlockUpdate, ctx: Ctx = Padlocks):
    return service.update_padlock(ctx.session, ctx.principal, padlock_id, body.model_dump(exclude_unset=True))


@router.delete("/padlocks/{padlock_id}", status_code=204)
def delete_padlock(padlock_id: UUID, ctx: Ctx = Padlocks):
    """Removes the lock from the inventory and from its locker; the row is kept for the audit trail."""
    service.delete_padlock(ctx.session, ctx.principal, padlock_id)


@router.post("/padlocks/{padlock_id}/reveal", response_model=s.PadlockCombinationOut)
def reveal_padlock_combination(padlock_id: UUID, ctx: Ctx = Reveal):
    """A POST because each reveal is written to the audit log (who looked, never the value)."""
    return service.reveal_combination(ctx.session, ctx.principal, padlock_id)
