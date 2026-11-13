"""integrations HTTP surface (docs/api/openapi-programs.yaml, tag integrations): API keys, webhooks, provider
connections, the accounting export and the adapter directory. Every route is require()-gated, so API keys may
call them too, but minting credentials and subscribing need a signed-in person (service._require_person)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency, secret_response
from app.core.pagination import ListQuery, list_query
from app.modules.integrations import schemas as s
from app.modules.integrations import service
from app.modules.integrations.domain.webhooks import redact

router = APIRouter(
    route_class=TxRoute, tags=["integrations"], generate_unique_id_function=camel_id,
    dependencies=[Depends(idempotency)],
)  # fmt: skip
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


@router.post("/external-connections", response_model=s.ExternalConnectionOut, status_code=201)
def create_external_connection(
    body: s.ExternalConnectionCreate, ctx: Ctx = Depends(require("integrations.connection.manage"))
):
    """Connect the accounting export. Errors: provider-not-configured (QuickBooks needs an Intuit app)."""
    return service.create_external_connection(ctx.session, ctx.principal, body.model_dump())


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


@router.get("/adapter-commands", response_model=s.Page[s.AdapterCommandOut])
def list_adapter_commands(query: Lists, ctx: Ctx = Depends(require("integrations.connection.manage"))):
    """What simulated adapters were asked to do. Filters: port, location_id. Sort: occurred_at."""
    return service.list_adapter_commands(ctx.session, ctx.principal, query)
