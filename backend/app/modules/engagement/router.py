"""engagement HTTP surface (slice): communication preferences, staff and portal (openapi-programs.yaml)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, current_ctx, require
from app.core.idempotency import idempotency
from app.modules.engagement import schemas as s
from app.modules.engagement import service

router = APIRouter(
    route_class=TxRoute, tags=["engagement"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)


@router.get("/clients/{client_id}/communication-preferences", response_model=s.Preferences)
def get_client_communication_preferences(client_id: UUID, ctx: Annotated[Ctx, Depends(require("clients.client.read"))]):
    """Every channel, address and topic for the client's current addresses; absent rows show the default."""
    return {"data": service.get_client_preferences(ctx.session, ctx.principal, client_id)}


@router.put("/clients/{client_id}/communication-preferences", response_model=s.Preferences)
def put_client_communication_preferences(
    client_id: UUID, body: s.PreferencesReplace, ctx: Annotated[Ctx, Depends(require("clients.consent.update"))]
):
    """Record consent given to staff; `note` (how and when) is required. Errors: email-unverified."""
    return {"data": service.put_client_preferences(ctx.session, ctx.principal, client_id, body.model_dump())}


@router.get("/portal/clients/{client_id}/communication-preferences", response_model=s.Preferences)
def get_portal_communication_preferences(client_id: UUID, ctx: Annotated[Ctx, Depends(current_ctx)]):
    return {"data": service.get_portal_preferences(ctx.session, ctx.principal, client_id)}


@router.put("/portal/clients/{client_id}/communication-preferences", response_model=s.Preferences)
def put_portal_communication_preferences(
    client_id: UUID, body: s.PortalPreferencesReplace, ctx: Annotated[Ctx, Depends(current_ctx)]
):
    return {"data": service.put_portal_preferences(ctx.session, ctx.principal, client_id, body.model_dump())}
