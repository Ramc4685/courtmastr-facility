"""access HTTP surface (openapi-money.yaml, tag access): staff check-in, credentials, kiosk settings and devices,
portal app cards, and the kiosk itself.

The kiosk router has no signed-in principal: a device is paired with a single-use code and then carries an
HttpOnly, SameSite=Strict cookie holding its token (hash stored). Every kiosk route resolves the device from that
cookie; pairing and look-ups are rate limited per IP."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app.core.api import TxRoute, camel_id
from app.core.auth import Principal, tokens
from app.core.auth.deps import Ctx, _host_tenant, current_ctx, public_session, request_session, require
from app.core.errors import NotFound, Unauthenticated
from app.core.idempotency import KEY_PATTERN, Replay, begin, idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import rate_limit
from app.core.settings import get_settings
from app.modules.access import schemas as s
from app.modules.access import service
from app.modules.access.models import KioskDevice

router = APIRouter(
    route_class=TxRoute, tags=["access"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
kiosk = APIRouter(route_class=TxRoute, tags=["access"], generate_unique_id_function=camel_id)
Lists = Annotated[ListQuery, Depends(list_query)]
Create = Annotated[Ctx, Depends(require("access.checkin.create"))]
Read = Annotated[Ctx, Depends(require("access.checkin.read"))]
Assign = Annotated[Ctx, Depends(require("access.credential.assign"))]
Launch = Annotated[Ctx, Depends(require("access.kiosk.launch"))]
Manage = Annotated[Ctx, Depends(require("access.kiosk.manage"))]
Settings = Annotated[Ctx, Depends(require("access.settings.manage"))]
Staff = Annotated[Ctx, Depends(current_ctx)]  # configuration reads: any staff at the location (rbac 1)
Portal = Annotated[Ctx, Depends(current_ctx)]
KIOSK_COOKIE = "fh_kiosk"
_EMPTY = {"next_cursor": None, "has_more": False}


# --- staff check-in ------------------------------------------------------------------------------------------


@router.post("/check-ins", response_model=s.CheckInResult, status_code=201)
def create_check_in(body: s.CheckInCreate, ctx: Create):
    """Check a client in from the front desk or their profile (CHK-01, CHK-03). A denial is returned, not raised."""
    return service.create_check_in(ctx.session, ctx.principal, body.model_dump())


@router.post("/check-ins/evaluate", response_model=s.AccessDecision)
def evaluate_check_in(body: s.AccessEvaluateRequest, ctx: Create):
    """What a check-in would decide, without writing anything."""
    return service.evaluate_check_in(ctx.session, ctx.principal, body.model_dump())


@router.get("/check-ins", response_model=s.Page[s.CheckInRowOut])
def list_check_ins(query: Lists, ctx: Read):
    """Recent check-ins (CHK-18) and a client's history (CHK-19). Filters: location_id, client_id, result,
    channel, local_on, checked_in_at[gte|lte]."""
    return service.list_check_ins(ctx.session, ctx.principal, query)


@router.get("/check-ins/{check_in_id}", response_model=s.CheckInOut)
def get_check_in(check_in_id: UUID, ctx: Read):
    return service.get_check_in(ctx.session, ctx.principal, check_in_id)


@router.post("/credentials/resolve", response_model=s.CredentialMatch)
def resolve_credential(body: s.CredentialResolveRequest, ctx: Create):
    """The client behind a scanned or typed value (CHK-14)."""
    return service.resolve_credential(ctx.session, ctx.principal, body.value)


# --- credentials ---------------------------------------------------------------------------------------------


@router.get("/clients/{client_id}/credentials", response_model=s.Page[s.CredentialOut])
def list_client_credentials(client_id: UUID, ctx: Read):
    return {"data": service.list_credentials(ctx.session, ctx.principal, client_id), "page": _EMPTY}


@router.post("/clients/{client_id}/credentials", response_model=s.CredentialOut, status_code=201)
def assign_credential(client_id: UUID, body: s.CredentialCreate, ctx: Assign):
    """Scan, type or generate a barcode or RFID value (CHK-11)."""
    row = service.assign_credential(ctx.session, ctx.principal, client_id, body.model_dump())
    return service.credential_view(row)


@router.post("/credentials/{credential_id}/revoke", response_model=s.CredentialOut)
def revoke_credential(credential_id: UUID, ctx: Assign):
    return service.credential_view(service.revoke_credential(ctx.session, ctx.principal, credential_id))


@router.post("/clients/{client_id}/credentials/revoke-all", status_code=204)
def revoke_client_app_cards(client_id: UUID, body: s.CredentialRevokeAllRequest, ctx: Assign) -> None:
    """Clear every digital card of a client (CHK-13)."""
    service.revoke_client_app_cards(ctx.session, ctx.principal, client_id)


# --- kiosk settings and devices ------------------------------------------------------------------------------


@router.get("/kiosk-settings", response_model=s.KioskSettingsOut)
def get_kiosk_settings(location_id: Annotated[UUID, Query()], ctx: Staff):
    if ctx.principal.kind != "staff":
        raise NotFound()
    return service.get_kiosk_settings(ctx.session, ctx.principal, location_id)


@router.put("/kiosk-settings", response_model=s.KioskSettingsOut)
def put_kiosk_settings(location_id: Annotated[UUID, Query()], body: s.KioskSettingsWrite, ctx: Settings):
    data = body.model_dump(exclude_unset=True)
    return service.put_kiosk_settings(ctx.session, ctx.principal, location_id, data)


@router.get("/kiosk-devices", response_model=s.Page[s.KioskDeviceOut])
def list_kiosk_devices(query: Lists, ctx: Launch):
    return service.list_kiosk_devices(ctx.session, ctx.principal, query)


@router.post("/kiosk-devices", response_model=s.KioskPairingCode, status_code=201)
def create_kiosk_device(body: s.KioskDeviceCreate, ctx: Manage):
    """Register a kiosk device; the pairing code is shown once."""
    return service.create_kiosk_device(ctx.session, ctx.principal, body.model_dump())


@router.post("/kiosk-devices/{kiosk_device_id}/pairing-codes", response_model=s.KioskPairingCode, status_code=201)
def create_kiosk_pairing_code(kiosk_device_id: UUID, ctx: Launch):
    """Launch kiosk mode on a registered device (CHK-05)."""
    return service.create_kiosk_pairing_code(ctx.session, ctx.principal, kiosk_device_id)


@router.post("/kiosk-devices/{kiosk_device_id}/revoke", response_model=s.KioskDeviceOut)
def revoke_kiosk_device(kiosk_device_id: UUID, ctx: Manage):
    return service.revoke_kiosk_device(ctx.session, ctx.principal, kiosk_device_id)


# --- portal app cards (CHK-13) -------------------------------------------------------------------------------


@router.get("/portal/app-cards", response_model=s.Page[s.PortalAppCardOut])
def list_app_cards(ctx: Portal, client_id: Annotated[UUID | None, Query()] = None):
    return {"data": service.list_app_cards(ctx.session, ctx.principal, client_id), "page": _EMPTY}


@router.post("/portal/app-cards", response_model=s.PortalAppCardIssued, status_code=201)
def issue_app_card(body: s.PortalAppCardCreate, ctx: Portal):
    """A digital member card for this device; the payload is shown once and drives rotating QR codes offline."""
    return service.issue_app_card(ctx.session, ctx.principal, body.model_dump())


@router.delete("/portal/app-cards/{credential_id}", status_code=204)
def revoke_app_card(credential_id: UUID, ctx: Portal) -> None:
    service.revoke_app_card(ctx.session, ctx.principal, credential_id)


# --- the kiosk -----------------------------------------------------------------------------------------------


def kiosk_device(request: Request) -> KioskDevice:
    """The paired device behind the kiosk cookie, with its own audit actor."""
    raw = request.cookies.get(KIOSK_COOKIE)
    tenant_id = tokens.tenant_of(raw, "fhd")
    if tenant_id is None:
        raise Unauthenticated("Pair this kiosk to continue", code="kiosk-unpaired")
    host = _host_tenant(request)
    if host is not None and host.id != tenant_id:
        raise Unauthenticated("Host and token disagree", code="kiosk-unpaired")
    session = request_session(request, tenant_id)
    device = service.device_for_token(session, raw)
    if device is None:
        raise Unauthenticated("Pair this kiosk to continue", code="kiosk-unpaired")
    session.info["actor"] = Principal(kind="kiosk", tenant_id=tenant_id, display_name=f"Kiosk {device.name}")
    return device


def kiosk_idempotency(
    request: Request,
    device: Annotated[KioskDevice, Depends(kiosk_device)],
    idempotency_key: Annotated[str | None, Header(pattern=KEY_PATTERN)] = None,
) -> None:
    """The router-level idempotency dependency needs a principal; a kiosk scopes its keys to the device."""
    if idempotency_key is None:
        return
    scope = f"kiosk:{device.id}:{request.scope['route'].path}"
    stored = begin(device.tenant_id, scope, idempotency_key, request.state.body_hash)
    if stored is not None:
        raise Replay(*stored)
    request.state.idempotency = (scope, idempotency_key)


Device = Annotated[KioskDevice, Depends(kiosk_device)]


def _session(request: Request):
    return request.state.session


@kiosk.post("/kiosk/pair", response_model=s.KioskConfig, dependencies=[Depends(rate_limit("kiosk-pair"))])
def pair_kiosk(body: s.KioskPairRequest, request: Request, response: Response):
    """Exchange a pairing code for this device's kiosk cookie."""
    session = public_session(request)
    session.info["actor"] = Principal(kind="kiosk", tenant_id=session.info["tenant_id"], display_name="Kiosk pairing")
    raw, device = service.kiosk_pair(session, body.pairing_code)
    response.set_cookie(
        KIOSK_COOKIE, raw, max_age=400 * 86400, path="/api/v1/kiosk", httponly=True,
        secure=get_settings().auth.cookie_secure, samesite="strict",
    )  # fmt: skip
    return service.kiosk_config(session, device)


@kiosk.get("/kiosk/config", response_model=s.KioskConfig)
def get_kiosk_config(request: Request, device: Device):
    return service.kiosk_config(_session(request), device)


@kiosk.post("/kiosk/lookups", response_model=s.KioskLookupResult, dependencies=[Depends(rate_limit("kiosk-lookup"))])
def kiosk_lookup(body: s.KioskLookupRequest, request: Request, device: Device):
    """Find yourself by card or the first letters of your last name: first name and last initial only."""
    return service.kiosk_lookup(_session(request), device, body.model_dump())


@kiosk.post(
    "/kiosk/check-ins", response_model=s.KioskCheckInResult, status_code=201,
    dependencies=[Depends(kiosk_idempotency)],
)  # fmt: skip
def create_kiosk_check_in(body: s.KioskCheckInCreate, request: Request, device: Device):
    """Self check-in (CHK-05): admitted or see staff, never amounts or reasons."""
    return service.kiosk_check_in(_session(request), device, body.model_dump())


@kiosk.post("/kiosk/exit", status_code=204)
def exit_kiosk(request: Request, response: Response, device: Device) -> None:
    """Leave kiosk mode: the device token stops working until staff pair it again."""
    service.kiosk_exit(_session(request), device)
    response.delete_cookie(KIOSK_COOKIE, path="/api/v1/kiosk")
