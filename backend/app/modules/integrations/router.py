"""integrations HTTP surface (docs/api/openapi-programs.yaml, tag integrations): API keys, webhooks, provider
connections, the accounting export and the adapter directory. Staff routes are require()-gated, so API keys may
call them too, but minting credentials and subscribing need a signed-in person (service._require_person).
`inbound` routes are anonymous: provider webhooks and the OAuth callback (verified by signature or sealed
state) and the public calendar feed and schedule."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session as Db

from app.core import ratelimit
from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, current_ctx, public_session, request_session, require
from app.core.auth.principal import system_principal
from app.core.errors import NotFound, PermissionDenied
from app.core.idempotency import idempotency, secret_response
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import rate_limit
from app.modules.integrations import feeds, quickbooks, service
from app.modules.integrations import schemas as s
from app.modules.integrations.domain.webhooks import redact

router = APIRouter(
    route_class=TxRoute, tags=["integrations"], generate_unique_id_function=camel_id,
    dependencies=[Depends(idempotency)],
)  # fmt: skip
# Inbound provider webhooks: authenticated by the provider's signature, registered before billing's
# /webhooks/{provider} so these static paths win (app.main).
inbound = APIRouter(route_class=TxRoute, tags=["integrations"], generate_unique_id_function=camel_id)
Lists = Annotated[ListQuery, Depends(list_query)]
KEYS, HOOKS = "integrations.api_key.manage", "integrations.webhook.manage"


def _with_secret(model: type[s.Out], row, secret: str) -> dict:
    return model.model_validate(row).model_dump() | {"secret": secret}


@router.get("/api-keys", response_model=s.Page[s.ApiKeyOut])
def list_api_keys(query: Lists, ctx: Ctx = Depends(require(KEYS))):
    """Filters: status. Sort: created_at, name. Secrets are never listed."""
    return service.list_api_keys(ctx.session, ctx.principal, query)


@router.post("/api-keys", response_model=s.ApiKeyCreated, status_code=201)
@secret_response
def create_api_key(body: s.ApiKeyCreate, ctx: Ctx = Depends(require(KEYS))):
    """The secret is in this response only. Scopes must be ones you hold and that may be given to a key.
    Errors: scope-not-grantable, scope-exceeds-creator, confirmation-required, staff-session-required."""
    row, secret = service.create_api_key(ctx.session, ctx.principal, body.model_dump())
    return _with_secret(s.ApiKeyOut, row, secret)


@router.post("/api-keys/{api_key_id}/rotate", response_model=s.ApiKeyCreated)
@secret_response
def rotate_api_key(api_key_id: UUID, body: s.ApiKeyRotate, ctx: Ctx = Depends(require(KEYS))):
    """New secret now; the old one keeps working for `grace_minutes` (default 24 hours)."""
    row, secret = service.rotate_api_key(ctx.session, ctx.principal, api_key_id, body.model_dump())
    return _with_secret(s.ApiKeyOut, row, secret)


@router.delete("/api-keys/{api_key_id}", status_code=204)
def revoke_api_key(api_key_id: UUID, ctx: Ctx = Depends(require(KEYS))) -> None:
    """Stops the key (and any previous secret) at once."""
    service.revoke_api_key(ctx.session, ctx.principal, api_key_id)


@router.get("/webhook-event-types", response_model=list[s.WebhookEventTypeOut])
def list_webhook_event_types(ctx: Ctx = Depends(require(HOOKS))):
    """Every subscribable type with the read permission it needs and whether the caller may subscribe."""
    return service.list_event_types(ctx.principal)


@router.get("/webhook-endpoints", response_model=s.Page[s.WebhookEndpointOut])
def list_webhook_endpoints(query: Lists, ctx: Ctx = Depends(require(HOOKS))):
    """Filters: status. Sort: created_at."""
    return service.list_webhook_endpoints(ctx.session, ctx.principal, query)


@router.post("/webhook-endpoints", response_model=s.WebhookEndpointSecretOut, status_code=201)
@secret_response
def create_webhook_endpoint(body: s.WebhookEndpointCreate, ctx: Ctx = Depends(require(HOOKS))):
    """The signing secret is in this response only. Errors: url-not-allowed (private, loopback, link-local or
    metadata address, or not https), event-permission-denied, endpoint-limit-reached."""
    row, secret = service.create_webhook_endpoint(ctx.session, ctx.principal, body.model_dump())
    return _with_secret(s.WebhookEndpointOut, row, secret)


@router.get("/webhook-endpoints/{webhook_endpoint_id}", response_model=s.WebhookEndpointOut)
def get_webhook_endpoint(webhook_endpoint_id: UUID, ctx: Ctx = Depends(require(HOOKS))):
    return service.get_webhook_endpoint(ctx.session, ctx.principal, webhook_endpoint_id)


@router.patch("/webhook-endpoints/{webhook_endpoint_id}", response_model=s.WebhookEndpointOut)
def update_webhook_endpoint(
    webhook_endpoint_id: UUID, body: s.WebhookEndpointUpdate, ctx: Ctx = Depends(require(HOOKS))
):
    """Change the URL, description or types; pause, or re-enable a disabled endpoint (`status: active`)."""
    data = body.model_dump(exclude_unset=True)
    return service.update_webhook_endpoint(ctx.session, ctx.principal, webhook_endpoint_id, data)


@router.delete("/webhook-endpoints/{webhook_endpoint_id}", status_code=204)
def delete_webhook_endpoint(webhook_endpoint_id: UUID, ctx: Ctx = Depends(require(HOOKS))) -> None:
    service.delete_webhook_endpoint(ctx.session, ctx.principal, webhook_endpoint_id)


@router.post("/webhook-endpoints/{webhook_endpoint_id}/rotate-secret", response_model=s.WebhookEndpointSecretOut)
@secret_response
def rotate_webhook_secret(webhook_endpoint_id: UUID, ctx: Ctx = Depends(require(HOOKS))):
    """New signing secret, in this response only; the previous one also signs for 24 hours."""
    row, secret = service.rotate_webhook_secret(ctx.session, ctx.principal, webhook_endpoint_id)
    return _with_secret(s.WebhookEndpointOut, row, secret)


@router.post("/webhook-endpoints/{webhook_endpoint_id}/test", response_model=s.WebhookDeliveryOut, status_code=202)
def test_webhook_endpoint(webhook_endpoint_id: UUID, ctx: Ctx = Depends(require(HOOKS))):
    """Send a signed `integrations.webhook.tested` event now; the result is in the returned delivery."""
    return service.test_webhook_endpoint(ctx.session, ctx.principal, webhook_endpoint_id)


@router.get("/webhook-deliveries", response_model=s.Page[s.WebhookDeliveryOut])
def list_webhook_deliveries(query: Lists, ctx: Ctx = Depends(require("integrations.delivery.read"))):
    """Filters: webhook_endpoint_id, event_type, status (status[in]=failed,abandoned), created_at. Sort: created_at."""
    return service.list_webhook_deliveries(ctx.session, ctx.principal, query)


@router.get("/webhook-deliveries/{webhook_delivery_id}", response_model=s.WebhookDeliveryDetail)
def get_webhook_delivery(webhook_delivery_id: UUID, ctx: Ctx = Depends(require("integrations.delivery.read"))):
    row = service.get_webhook_delivery(ctx.session, ctx.principal, webhook_delivery_id)
    return s.WebhookDeliveryOut.model_validate(row).model_dump() | {"payload_preview": redact(row.payload)}


@router.post("/webhook-deliveries/{webhook_delivery_id}/replay", response_model=s.WebhookDeliveryOut, status_code=202)
def replay_webhook_delivery(webhook_delivery_id: UUID, ctx: Ctx = Depends(require(HOOKS))):
    """Queue the same event (same id) again with a fresh retry cycle. Errors: invalid-state-transition."""
    return service.replay_webhook_delivery(ctx.session, ctx.principal, webhook_delivery_id)


@router.get("/external-connections", response_model=s.Page[s.ExternalConnectionOut])
def list_external_connections(query: Lists, ctx: Ctx = Depends(require("integrations.connection.manage"))):
    """Filters: provider, status, location_id. Sort: created_at."""
    return service.list_external_connections(ctx.session, ctx.principal, query)


@router.post("/external-connections", response_model=s.ExternalConnectionCreated, status_code=201)
def create_external_connection(
    body: s.ExternalConnectionCreate, ctx: Ctx = Depends(require("integrations.connection.manage"))
):
    """Connect the accounting export, or start connecting QuickBooks (pending, with `authorize_url`).
    Errors: provider-not-configured (QuickBooks is switched off), staff-session-required."""
    row, authorize_url = service.create_external_connection(ctx.session, ctx.principal, body.model_dump())
    return s.ExternalConnectionOut.model_validate(row).model_dump() | {"authorize_url": authorize_url}


@inbound.post("/external-connections/oauth/callback", response_model=s.OAuthCallbackOut)
def complete_external_connection_o_auth(body: s.OAuthCallbackIn, request: Request):
    """Posted by the web app's callback page with what the provider sent back. Authenticated by the sealed
    state (tenant, connection, staff user, ten-minute expiry), never by a session. Errors: state-invalid."""
    tenant_id = quickbooks.tenant_of_state(body.state)
    if tenant_id is None:
        raise PermissionDenied("This connection link is not valid", code="state-invalid")
    session = request_session(request, tenant_id)
    session.info["actor"] = system_principal("quickbooks oauth")
    return quickbooks.complete(session, body.state, body.code, body.realm_id, body.error)


@router.get("/external-connections/{external_connection_id}", response_model=s.ExternalConnectionOut)
def get_external_connection(
    external_connection_id: UUID, ctx: Ctx = Depends(require("integrations.connection.manage"))
):
    return quickbooks.get_connection(ctx.session, ctx.principal, external_connection_id)


@router.patch("/external-connections/{external_connection_id}", response_model=s.ExternalConnectionOut)
def update_external_connection(
    external_connection_id: UUID, body: s.ExternalConnectionUpdate,
    ctx: Ctx = Depends(require("integrations.connection.manage")),
):  # fmt: skip
    """Merge-patch the provider settings. Errors: validation-failed (unknown setting)."""
    return quickbooks.update_settings(ctx.session, ctx.principal, external_connection_id, body.settings)


@router.get("/external-connections/{external_connection_id}/sync-mappings", response_model=s.SyncMappingsOut)
def get_sync_mappings(external_connection_id: UUID, ctx: Ctx = Depends(require("integrations.connection.manage"))):
    """The mappings, the posting keys recent exports carried that still lack one, and the provider's accounts
    and classes fetched live. Errors: provider-unavailable."""
    return quickbooks.get_mappings(ctx.session, ctx.principal, external_connection_id)


@router.put("/external-connections/{external_connection_id}/sync-mappings", response_model=s.SyncMappingsOut)
def put_sync_mappings(
    external_connection_id: UUID, body: s.SyncMappingsIn, ctx: Ctx = Depends(require("integrations.connection.manage"))
):
    """Replace every mapping; the daily export reads them from the next run."""
    mappings = [m.model_dump() for m in body.mappings]
    return quickbooks.put_mappings(ctx.session, ctx.principal, external_connection_id, mappings)


@router.post("/external-connections/{external_connection_id}/sync", response_model=s.SyncRunOut, status_code=202)
def run_sync(external_connection_id: UUID, body: s.SyncRun, ctx: Ctx = Depends(require("integrations.sync.run"))):
    """Export each past day in the range (default yesterday, at most 31 days) for the connection's location.
    Idempotent per day. Errors: invalid-state-transition, validation-failed."""
    return quickbooks.run_sync(ctx.session, ctx.principal, external_connection_id, body.model_dump(by_alias=True))


@router.post("/accounting-exports/{accounting_export_id}/retry", response_model=s.AccountingExportOut, status_code=202)
def retry_accounting_export(accounting_export_id: UUID, ctx: Ctx = Depends(require("integrations.sync.run"))):
    """Retry one failed day with the same provider request id. Errors: invalid-state-transition."""
    return quickbooks.retry_export(ctx.session, ctx.principal, accounting_export_id)


@inbound.post("/webhooks/quickbooks", status_code=200, response_model=s.InboundAck)
async def receive_quick_books_events(request: Request):
    """Signed QuickBooks notifications, verified (`intuit-signature`) and stored once. Errors: invalid-signature."""
    body = await request.body()
    stored = await run_in_threadpool(quickbooks.receive_webhook, body, request.headers.get("intuit-signature", ""))
    return {"stored": stored}


@router.post("/external-connections/{external_connection_id}/disconnect", response_model=s.ExternalConnectionOut)
def disconnect_external_connection(
    external_connection_id: UUID, ctx: Ctx = Depends(require("integrations.connection.manage"))
):
    return service.disconnect_external_connection(ctx.session, ctx.principal, external_connection_id)


@router.get("/accounting-exports", response_model=s.Page[s.AccountingExportOut])
def list_accounting_exports(query: Lists, ctx: Ctx = Depends(require("integrations.sync.run"))):
    """Filters: external_connection_id, location_id, status. Sort: business_on."""
    return service.list_accounting_exports(ctx.session, ctx.principal, query)


@router.post("/accounting-exports", response_model=s.AccountingExportOut)
def run_accounting_export(body: s.AccountingExportRun, ctx: Ctx = Depends(require("integrations.sync.run"))):
    """Post one location-day as a summarised journal. Safe to repeat: a finished day is returned unchanged."""
    return service.export_accounting_day(
        ctx.session, ctx.principal, body.external_connection_id, body.location_id, body.business_on
    )


@router.get("/integration-adapters", response_model=list[s.AdapterOut])
def list_integration_adapters(ctx: Ctx = Depends(require("integrations.connection.manage"))):
    """Each integration port with its adapter and whether it is connected, simulated or not configured."""
    return service.list_adapters(ctx.session, ctx.principal)


@router.get("/api-reference", response_model=list[s.ApiOperationOut])
def list_api_operations(request: Request, ctx: Ctx = Depends(require(KEYS))):
    """Every operation an API key may call and the scopes that open it, generated from the routes (INT-01)."""
    from app.modules.integrations import reference

    return reference.operations(request.app.openapi())


@router.get("/adapter-commands", response_model=s.Page[s.AdapterCommandOut])
def list_adapter_commands(query: Lists, ctx: Ctx = Depends(require("integrations.connection.manage"))):
    """What simulated adapters were asked to do. Filters: port, location_id. Sort: occurred_at."""
    return service.list_adapter_commands(ctx.session, ctx.principal, query)


# --- calendar feeds (INT-08, SCH-19, STF-13, LGE-25, SSP-19) and the public schedule (SCH-20) -----------------


def _feed_created(row, token: str | None) -> dict:
    return s.CalendarFeedOut.model_validate(row).model_dump() | {"url_token": token}


@router.get("/calendar-feeds", response_model=s.Page[s.CalendarFeedOut])
def list_calendar_feeds(query: Lists, ctx: Ctx = Depends(require())):
    """Your feeds; with integrations.calendar_feed.revoke_any, every staff feed in your locations.
    Filters: kind, status, owner_staff_user_id. Sort: created_at, name. URLs are never listed."""
    return feeds.list_feeds(ctx.session, ctx.principal, query)


@router.post("/calendar-feeds", response_model=s.CalendarFeedCreated, status_code=201)
@secret_response
def create_calendar_feed(body: s.CalendarFeedCreate, ctx: Ctx = Depends(require())):
    """A staff schedule (bookings you can read, optionally your shifts) or one team's games. The URL token is in
    this response only. Errors: staff-session-required, permission-denied."""
    row, token = feeds.create_feed(ctx.session, ctx.principal, body.model_dump())
    return _feed_created(row, token)


@router.patch("/calendar-feeds/{calendar_feed_id}", response_model=s.CalendarFeedCreated)
@secret_response
def update_calendar_feed(calendar_feed_id: UUID, body: s.CalendarFeedUpdate, ctx: Ctx = Depends(require())):
    """Rename, change shifts, disable, or re-enable with a new URL (`url_token` is set only then). Someone
    else's feed may only be disabled, under revoke_any."""
    row, token = feeds.update_feed(ctx.session, ctx.principal, calendar_feed_id, body.model_dump(exclude_unset=True))
    return _feed_created(row, token)


@router.delete("/calendar-feeds/{calendar_feed_id}", status_code=204)
def delete_calendar_feed(calendar_feed_id: UUID, ctx: Ctx = Depends(require())) -> None:
    feeds.delete_feed(ctx.session, ctx.principal, calendar_feed_id)


@router.post("/portal/calendar-feeds", response_model=s.CalendarFeedCreated, status_code=201)
@secret_response
def create_portal_calendar_feed(body: s.PortalCalendarFeedCreate, ctx: Ctx = Depends(current_ctx)):
    """My schedule: the sessions I and my household are enrolled in. The URL token is in this response only."""
    row, token = feeds.create_member_feed(ctx.session, ctx.principal, body.model_dump())
    return _feed_created(row, token)


@inbound.get(
    "/public/calendar-feeds/{token}", response_class=Response, responses={200: {"content": {"text/calendar": {}}}}
)
def get_public_calendar_feed(token: str, request: Request, response: Response):
    """iCalendar text, recomputed from the owner's current access on each fetch. 404 for any unusable URL."""
    # The token is a credential: keep it out of the access log and error bodies from here on.
    request.scope["path"] = request.scope["path"].replace(token, "[redacted]")
    request.scope["raw_path"] = request.scope["path"].encode()
    tenant_id = feeds.tenant_of(token)
    if tenant_id is None:
        raise NotFound()
    ratelimit.hit("calendar-feed", token, response, tenant=tenant_id)
    session = request_session(request, tenant_id)
    session.info["actor"] = system_principal("calendar feed")
    body = feeds.render(session, token)
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers=dict(response.headers) | {"Cache-Control": "private, max-age=900"},
    )


@router.get("/public-schedule-settings", response_model=s.PublicScheduleSettingsOut, tags=["scheduling"])
def get_public_schedule_settings(location_id: UUID, ctx: Ctx = Depends(require("scheduling.public_schedule.manage"))):
    """What the location's public schedule shows. A location never configured is unpublished."""
    return feeds.get_public_schedule_settings(ctx.session, ctx.principal, location_id)


@router.patch("/public-schedule-settings", response_model=s.PublicScheduleSettingsOut, tags=["scheduling"])
def update_public_schedule_settings(
    body: s.PublicScheduleSettingsUpdate, ctx: Ctx = Depends(require("scheduling.public_schedule.manage"))
):
    """Publish or hide a location's schedule and choose what it shows; omitted fields keep their value."""
    return feeds.update_public_schedule_settings(ctx.session, ctx.principal, body.model_dump())


@inbound.get(
    "/public/schedule", response_model=s.PublicScheduleOut, tags=["scheduling"],
    dependencies=[Depends(rate_limit("public-schedule"))],
)  # fmt: skip
def get_public_schedule(
    location_id: UUID, response: Response, session: Annotated[Db, Depends(public_session)],
    from_on: date | None = None, days: Annotated[int | None, Query(ge=1, le=31)] = None,
):  # fmt: skip
    """Embeddable: a published location's sessions with seats left and, if shown, busy times with no names.
    Tenant from the host or X-Tenant-Slug. 404 when the location has not published its schedule."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return feeds.public_schedule(session, location_id, from_on, days)
