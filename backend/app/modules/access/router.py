"""access HTTP surface (openapi-money.yaml, tag access): staff check-in, credentials, kiosk settings and devices,
portal app cards, the kiosk itself, and building control: door devices, lighting zones, the building activity log,
portal door codes, and the door controllers' verify endpoint.

The kiosk router has no signed-in principal: a device is paired with a single-use code and then carries an
HttpOnly, SameSite=Strict cookie holding its token (hash stored). Every kiosk route resolves the device from that
cookie; pairing and look-ups are rate limited per IP."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app.core import clock
from app.core.api import TxRoute, camel_id
from app.core.auth import Principal, tokens
from app.core.auth.deps import Ctx, _host_tenant, current_ctx, public_session, request_session, require
from app.core.errors import DomainError, NotFound, Unauthenticated
from app.core.idempotency import KEY_PATTERN, Replay, begin, idempotency, secret_response
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import _redis, rate_limit
from app.core.settings import get_settings
from app.modules.access import building, desk, service
from app.modules.access import schemas as s
from app.modules.access.models import DoorDevice, KioskDevice

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
Rules = Annotated[Ctx, Depends(require("access.rule.manage"))]
Mode = Annotated[Ctx, Depends(require("access.client.set_access_mode"))]
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
@secret_response
def create_kiosk_device(body: s.KioskDeviceCreate, ctx: Manage):
    """Register a kiosk device; the pairing code is shown once."""
    return service.create_kiosk_device(ctx.session, ctx.principal, body.model_dump())


@router.post("/kiosk-devices/{kiosk_device_id}/pairing-codes", response_model=s.KioskPairingCode, status_code=201)
@secret_response
def create_kiosk_pairing_code(kiosk_device_id: UUID, ctx: Launch):
    """Launch kiosk mode on a registered device (CHK-05)."""
    return service.create_kiosk_pairing_code(ctx.session, ctx.principal, kiosk_device_id)


@router.post("/kiosk-devices/{kiosk_device_id}/revoke", response_model=s.KioskDeviceOut)
def revoke_kiosk_device(kiosk_device_id: UUID, ctx: Manage):
    return service.revoke_kiosk_device(ctx.session, ctx.principal, kiosk_device_id)


# --- access settings, rules, client mode, schedules (CHK-02, CHK-08, CHK-09, CHK-10) -------------------------


def _staff(ctx: Ctx) -> Ctx:
    if ctx.principal.kind != "staff":
        raise NotFound()
    return ctx


@router.get("/access-settings", response_model=s.AccessSettingsOut)
def get_access_settings(location_id: Annotated[UUID, Query()], ctx: Staff):
    """Staff check-in settings and the status-card fields hidden without full details (CHK-02)."""
    return service.get_access_settings(ctx.session, _staff(ctx).principal, location_id)


@router.put("/access-settings", response_model=s.AccessSettingsOut)
def put_access_settings(location_id: Annotated[UUID, Query()], body: s.AccessSettingsWrite, ctx: Settings):
    return service.put_access_settings(ctx.session, ctx.principal, location_id, body.model_dump(exclude_unset=True))


@router.get("/access-rules", response_model=s.AccessRulesOut)
def list_access_rules(location_id: Annotated[UUID, Query()], ctx: Staff):
    """What each membership condition does at a location: allow or deny (CHK-08)."""
    return service.list_access_rules(ctx.session, _staff(ctx).principal, location_id)


@router.put("/access-rules", response_model=s.AccessRulesOut)
def put_access_rules(location_id: Annotated[UUID, Query()], body: s.AccessRulesWrite, ctx: Rules):
    return service.put_access_rules(ctx.session, ctx.principal, location_id, body.model_dump()["rules"])


@router.get("/clients/{client_id}/access-mode", response_model=s.ClientAccessOut)
def get_client_access_mode(client_id: UUID, ctx: Create):
    return service.get_client_access_mode(ctx.session, ctx.principal, client_id)


@router.put("/clients/{client_id}/access-mode", response_model=s.ClientAccessOut)
def set_client_access_mode(client_id: UUID, body: s.ClientAccessWrite, ctx: Mode):
    """Normal (the rules decide), always admit or always deny one client, with a reason (CHK-08)."""
    return service.set_client_access_mode(ctx.session, ctx.principal, client_id, body.model_dump())


@router.get("/access-schedules", response_model=s.Page[s.AccessScheduleOut])
def list_access_schedules(query: Lists, ctx: Staff):
    """Time-of-day schedules (CHK-09). Filter: is_active."""
    return service.list_access_schedules(ctx.session, _staff(ctx).principal, query)


@router.post("/access-schedules", response_model=s.AccessScheduleOut, status_code=201)
def create_access_schedule(body: s.AccessScheduleCreate, ctx: Rules):
    return service.create_access_schedule(ctx.session, ctx.principal, body.model_dump())


@router.patch("/access-schedules/{access_schedule_id}", response_model=s.AccessScheduleOut)
def update_access_schedule(access_schedule_id: UUID, body: s.AccessScheduleUpdate, ctx: Rules):
    return service.update_access_schedule(
        ctx.session, ctx.principal, access_schedule_id, body.model_dump(exclude_unset=True)
    )


@router.get("/membership-type-access", response_model=s.Page[s.MembershipTypeAccessOut])
def list_membership_type_access(ctx: Staff):
    """Membership types limited to a schedule or admitting at further locations (CHK-09, CHK-10)."""
    return {"data": service.list_membership_type_access(ctx.session, _staff(ctx).principal), "page": _EMPTY}


@router.put("/membership-types/{membership_type_id}/access", response_model=s.MembershipTypeAccessOut)
def put_membership_type_access(membership_type_id: UUID, body: s.MembershipTypeAccessWrite, ctx: Rules):
    return service.put_membership_type_access(ctx.session, ctx.principal, membership_type_id, body.model_dump())


# --- check-in desk (CHK-04, CHK-07, CHK-12, MEM-19) ----------------------------------------------------------

CheckOut = Annotated[Ctx, Depends(require("access.checkin.check_out"))]
Enroll = Annotated[Ctx, Depends(require("scheduling.enrollment.create"))]


@router.get("/check-in-stations", response_model=s.Page[s.CheckInStationOut])
def list_check_in_stations(location_id: Annotated[UUID, Query()], ctx: Staff):
    """The named check-in points of a location (CHK-07)."""
    return {"data": desk.list_stations(ctx.session, _staff(ctx).principal, location_id), "page": _EMPTY}


@router.post("/check-in-stations", response_model=s.CheckInStationOut, status_code=201)
def create_check_in_station(body: s.CheckInStationCreate, ctx: Settings):
    return desk.create_station(ctx.session, ctx.principal, body.model_dump())


@router.patch("/check-in-stations/{check_in_station_id}", response_model=s.CheckInStationOut)
def update_check_in_station(check_in_station_id: UUID, body: s.CheckInStationUpdate, ctx: Settings):
    return desk.update_station(ctx.session, ctx.principal, check_in_station_id, body.model_dump(exclude_unset=True))


@router.post("/check-ins/{check_in_id}/check-out", response_model=s.CheckInOut)
def check_out(check_in_id: UUID, ctx: CheckOut, body: s.CheckOutRequest | None = None):
    """End the client's visit at the location (CHK-07); a visit never checked out ends at local midnight."""
    row = desk.check_out(ctx.session, ctx.principal, check_in_id, body.model_dump() if body else {})
    return service.check_in_view(ctx.session, row)


@router.post("/check-ins/{check_in_id}/attendances", response_model=s.CheckInOut, status_code=201)
def create_check_in_attendance(check_in_id: UUID, body: s.CheckInAttendanceCreate, ctx: Enroll):
    """Book the checked-in client into a session starting soon and mark it attended (CHK-04)."""
    row = desk.book_session(ctx.session, ctx.principal, check_in_id, body.model_dump())
    return service.check_in_view(ctx.session, row)


@router.get("/occupancy", response_model=s.OccupancyOut)
def get_occupancy(location_id: Annotated[UUID, Query()], ctx: Read):
    """Who is in now, the count and the count per station, in the location's day (CHK-07)."""
    return desk.occupancy(ctx.session, ctx.principal, location_id)


@router.get("/id-card-templates", response_model=s.Page[s.IdCardTemplateOut])
def list_id_card_templates(ctx: Staff):
    """Member card layouts: tenant-wide and the caller's locations (CHK-12)."""
    return {"data": desk.list_templates(ctx.session, _staff(ctx).principal), "page": _EMPTY}


@router.post("/id-card-templates", response_model=s.IdCardTemplateOut, status_code=201)
def create_id_card_template(body: s.IdCardTemplateCreate, ctx: Settings):
    return desk.create_template(ctx.session, ctx.principal, body.model_dump())


@router.patch("/id-card-templates/{id_card_template_id}", response_model=s.IdCardTemplateOut)
def update_id_card_template(id_card_template_id: UUID, body: s.IdCardTemplateUpdate, ctx: Settings):
    return desk.update_template(ctx.session, ctx.principal, id_card_template_id, body.model_dump(exclude_unset=True))


@router.get("/clients/{client_id}/id-card", response_model=s.ClientIdCardOut)
def get_client_id_card(
    client_id: UUID, ctx: Assign, location_id: Annotated[UUID | None, Query()] = None,
    id_card_template_id: Annotated[UUID | None, Query()] = None,
):  # fmt: skip
    """The printable member card with the value its barcode encodes (MEM-19)."""
    return desk.client_id_card(ctx.session, ctx.principal, client_id, location_id, id_card_template_id)


# --- portal app cards (CHK-13) -------------------------------------------------------------------------------


@router.get("/portal/app-cards", response_model=s.Page[s.PortalAppCardOut])
def list_app_cards(ctx: Portal, client_id: Annotated[UUID | None, Query()] = None):
    return {"data": service.list_app_cards(ctx.session, ctx.principal, client_id), "page": _EMPTY}


@router.post("/portal/app-cards", response_model=s.PortalAppCardIssued, status_code=201)
@secret_response
def issue_app_card(body: s.PortalAppCardCreate, ctx: Portal):
    """A digital member card for this device; the payload is shown once and drives rotating QR codes offline."""
    return service.issue_app_card(ctx.session, ctx.principal, body.model_dump())


@router.delete("/portal/app-cards/{credential_id}", status_code=204)
def revoke_app_card(credential_id: UUID, ctx: Portal) -> None:
    service.revoke_app_card(ctx.session, ctx.principal, credential_id)


# --- portal wallet passes (CHK-13, APP-06) --------------------------------------------------------------------


@router.get("/portal/wallet-passes", response_model=s.Page[s.PortalWalletPassOut])
def list_wallet_passes(ctx: Portal, client_id: Annotated[UUID | None, Query()] = None):
    return {"data": service.list_wallet_passes(ctx.session, ctx.principal, client_id), "page": _EMPTY}


@router.post("/portal/wallet-passes", response_model=s.PortalWalletPassIssued, status_code=201)
@secret_response
def issue_wallet_pass(body: s.PortalWalletPassCreate, ctx: Portal):
    """A wallet pass with its own long-lived credential; issuing again revokes the client's previous pass."""
    return service.issue_wallet_pass(ctx.session, ctx.principal, body.model_dump())


@router.delete("/portal/wallet-passes/{credential_id}", status_code=204)
def revoke_wallet_pass(credential_id: UUID, ctx: Portal) -> None:
    service.revoke_wallet_pass(ctx.session, ctx.principal, credential_id)


# --- building control (CHK-15, CHK-16) ------------------------------------------------------------------------

Devices = Annotated[Ctx, Depends(require("access.device.manage"))]
Unlock = Annotated[Ctx, Depends(require("access.door.unlock"))]
Lights = Annotated[Ctx, Depends(require("access.lighting.override"))]


@router.get("/door-devices", response_model=s.Page[s.DoorDeviceOut])
def list_door_devices(location_id: Annotated[UUID, Query()], ctx: Read):
    return {"data": building.list_doors(ctx.session, ctx.principal, location_id), "page": _EMPTY}


@router.post("/door-devices", response_model=s.DoorDeviceIssued, status_code=201)
@secret_response
def create_door_device(body: s.DoorDeviceCreate, ctx: Devices):
    """Register a door controller; its bearer credential is shown once."""
    return building.create_door(ctx.session, ctx.principal, body.model_dump())


@router.patch("/door-devices/{door_device_id}", response_model=s.DoorDeviceOut)
def update_door_device(door_device_id: UUID, body: s.DoorDeviceUpdate, ctx: Devices):
    """Rename, re-address or retire a door (retiring drops its credential)."""
    return building.update_door(ctx.session, ctx.principal, door_device_id, body.model_dump(exclude_unset=True))


@router.post("/door-devices/{door_device_id}/credential", response_model=s.DoorDeviceIssued, status_code=201)
@secret_response
def rotate_door_device_credential(door_device_id: UUID, ctx: Devices):
    """A new bearer credential for the controller; the old one stops working at once."""
    return building.rotate_door_credential(ctx.session, ctx.principal, door_device_id)


@router.post("/door-devices/{door_device_id}/unlock", response_model=s.BuildingEventOut, status_code=201)
def unlock_door_device(door_device_id: UUID, body: s.DoorUnlockRequest, ctx: Unlock):
    """Open the door now for someone standing at it (the help line when a code fails). Reason required."""
    return building.remote_unlock(ctx.session, ctx.principal, door_device_id, body.model_dump())


@router.get("/lighting-zones", response_model=s.Page[s.LightingZoneOut])
def list_lighting_zones(location_id: Annotated[UUID, Query()], ctx: Read):
    return {"data": building.list_zones(ctx.session, ctx.principal, location_id), "page": _EMPTY}


@router.post("/lighting-zones", response_model=s.LightingZoneOut, status_code=201)
def create_lighting_zone(body: s.LightingZoneCreate, ctx: Devices):
    """A light circuit and the courts whose bookings switch it."""
    return building.create_zone(ctx.session, ctx.principal, body.model_dump())


@router.patch("/lighting-zones/{lighting_zone_id}", response_model=s.LightingZoneOut)
def update_lighting_zone(lighting_zone_id: UUID, body: s.LightingZoneUpdate, ctx: Devices):
    return building.update_zone(ctx.session, ctx.principal, lighting_zone_id, body.model_dump(exclude_unset=True))


@router.put("/lighting-zones/{lighting_zone_id}/override", response_model=s.LightingZoneOut)
def override_lighting_zone(lighting_zone_id: UUID, body: s.LightingZoneOverride, ctx: Lights):
    """Hold a zone on or off until a time (cleaning, an event); `is_on: null` hands it back to the bookings."""
    return building.override_zone(ctx.session, ctx.principal, lighting_zone_id, body.model_dump())


@router.get("/building-events", response_model=s.Page[s.BuildingEventOut])
def list_building_events(query: Lists, ctx: Read):
    """Entries, denied attempts, unlocks, light switches, overrides, codes and failed commands. Filters:
    location_id, local_on, kind, door_device_id, lighting_zone_id."""
    return building.list_building_events(ctx.session, ctx.principal, query)


@router.get("/building-status", response_model=s.BuildingStatusOut)
def get_building_status(location_id: Annotated[UUID, Query()], ctx: Read):
    """Per zone: should it be on now, what was last commanded, and whether the two agree. Per door: its state."""
    return building.building_status(ctx.session, ctx.principal, location_id)


@router.get("/portal/entry-codes", response_model=s.Page[s.PortalEntryCodeOut])
def list_portal_entry_codes(ctx: Portal):
    """Live door codes of the caller's (and dependants') bookings: the portal and the app show them."""
    return {"data": building.list_portal_entry_codes(ctx.session, ctx.principal), "page": _EMPTY}


@router.post("/portal/bookings/{booking_id}/door-unlock", response_model=s.PortalDoorUnlockResult)
def unlock_portal_booking_door(booking_id: UUID, ctx: Portal):
    """Open the door from the portal, inside the booking's code window only."""
    return building.member_unlock(ctx.session, ctx.principal, booking_id)


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
KIOSK_CHECKINS_PER_MINUTE = 30  # one device, one queue: more than this is a script, not a line of people


def kiosk_rate_limit(device: Device) -> None:
    """Per device, not per IP: kiosks behind one NAT share an address. Fails open like rate_limit."""
    if not get_settings().rate_limit.enabled:
        return
    key = f"rl:kiosk-check-in:{device.id}:{int(clock.now().timestamp() // 60)}"
    try:
        pipe = _redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        count = pipe.execute()[0]
    except Exception:  # noqa: BLE001 - a Redis outage must not stop check-in
        return
    if count > KIOSK_CHECKINS_PER_MINUTE:
        raise DomainError("Too many requests", status=429, code="rate-limited", headers={"Retry-After": "60"})


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
    dependencies=[Depends(kiosk_rate_limit), Depends(kiosk_idempotency)],
)  # fmt: skip
def create_kiosk_check_in(body: s.KioskCheckInCreate, request: Request, device: Device):
    """Self check-in (CHK-05): admitted or see staff, never amounts or reasons."""
    return service.kiosk_check_in(_session(request), device, body.model_dump())


@kiosk.post("/kiosk/exit", status_code=204, dependencies=[Depends(rate_limit("kiosk-exit"))])
def exit_kiosk(body: s.KioskExitRequest, request: Request, response: Response, device: Device) -> None:
    """Leave kiosk mode with the location's exit PIN: the device token stops working until staff pair it again."""
    service.kiosk_exit(_session(request), device, body.staff_pin)
    response.delete_cookie(KIOSK_COOKIE, path="/api/v1/kiosk")


# --- door controllers (device credential, no principal) --------------------------------------------------------


def _door_credential(request: Request) -> tuple[str, UUID]:
    scheme, _, raw = request.headers.get("authorization", "").partition(" ")
    tenant_id = tokens.tenant_of(raw if scheme.lower() == "bearer" else None, "fhb")
    if tenant_id is None:
        raise Unauthenticated("Door credential required", code="device-unauthenticated")
    return raw, tenant_id


def door_device(request: Request) -> DoorDevice:
    """The door behind `Authorization: Bearer fhb_...`, with its own audit actor."""
    raw, tenant_id = _door_credential(request)
    host = _host_tenant(request)
    if host is not None and host.id != tenant_id:
        raise Unauthenticated("Host and token disagree", code="device-unauthenticated")
    session = request_session(request, tenant_id)
    door = building.door_for_token(session, raw)
    if door is None:
        raise Unauthenticated("Door credential required", code="device-unauthenticated")
    session.info["actor"] = Principal(kind="kiosk", tenant_id=tenant_id, display_name=f"Door {door.name}")
    return door


@kiosk.post("/door/verify", response_model=s.DoorVerifyResult)
def verify_door_code(body: s.DoorVerifyRequest, request: Request):
    """A keypad's code: allow (with how long to release the lock) or deny, and nothing else. Before any database
    work: a code that is not CODE_DIGITS long is denied, then `door_enter` queues the verify for its location,
    serialises it and sleeps the current delay (Redis only); a full queue or an unreachable Redis is denied with
    nothing written. The session is opened only after the delay. This sync route holds a threadpool thread while it
    waits; the queue bounds that to DOOR_QUEUE + 1 threads per location (README)."""
    raw, _ = _door_credential(request)
    if len(body.code) != building.CODE_DIGITS:
        return building.DENY
    ticket = building.door_enter(raw)
    if ticket is None:
        return building.DENY
    door = None
    try:
        door = door_device(request)
        return building.verify_code(_session(request), door, body.code)
    finally:
        building.door_leave(ticket, raw, door.location_id if door else None)
