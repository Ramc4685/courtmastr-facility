"""clients HTTP surface (skeleton): list, create, get. Build module 4 adds the rest of openapi-people.yaml."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.clients import schemas as s
from app.modules.clients import service

router = APIRouter(
    route_class=TxRoute, tags=["clients"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]


@router.get("/clients", response_model=s.Page[s.ClientOut])
def list_clients(query: Lists, ctx: Ctx = Depends(require("clients.client.read"))):
    """Filters: status, home_location_id; q searches name, email, mobile phone and member number.
    Sort: last_name, first_name, created_at."""
    return service.list_clients(ctx.session, ctx.principal, query)


@router.post("/clients", response_model=s.ClientOut, status_code=201)
def create_client(body: s.ClientCreate, ctx: Ctx = Depends(require("clients.client.create"))):
    """Errors: already-exists (member_number), validation-failed."""
    return service.create_client(ctx.session, ctx.principal, body.model_dump())


@router.get("/clients/{client_id}", response_model=s.ClientOut)
def get_client(client_id: UUID, ctx: Ctx = Depends(require("clients.client.read"))):
    return service.get_client(ctx.session, ctx.principal, client_id)
