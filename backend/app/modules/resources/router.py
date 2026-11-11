"""resources HTTP surface (docs/api/openapi-core.yaml, tag resources). Locker operations are not built."""

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
