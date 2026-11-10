"""integrations use cases: API keys, outbound webhooks, provider connections, accounting export, adapter log.

Every staff command authorizes on the loaded row with its location, audits once, and never commits. Ids from a
request are loaded through the scoped loaders below (`_load_*`), never a bare session.get.
Internal functions for the fan-out subscriber and the delivery job (no principal) are marked as such.
"""

import json
import secrets
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, any_, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import audit, clock, crypto, events
from app.core.auth import CATALOGUE as PERMISSIONS
from app.core.auth import Permission, Principal, authorize, tokens
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import platform
from app.modules.integrations import transport
from app.modules.integrations.catalogue import CATALOGUE, TEST_EVENT, EventType
from app.modules.integrations.domain import journal
from app.modules.integrations.domain import webhooks as rules
from app.modules.integrations.events import WebhookEndpointDisabled
from app.modules.integrations.models import (
    AccountingExport,
    AdapterCommandLog,
    ApiKey,
    ApiKeyStatus,
    ConnectionStatus,
    DeliveryStatus,
    EndpointStatus,
    ExportStatus,
    ExternalConnection,
    Provider,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.ports import notifications

notifications.register_template(
    "integrations.webhook_disabled",
    subject="A webhook endpoint was disabled",
    body="Deliveries to $url stopped ($reason). Fix the receiver, then re-enable the endpoint under Settings > "
    "Webhooks; failed deliveries can be replayed from the delivery log.",
)

# rbac-matrix section 11: never grantable to a key. `$` and `P` scopes need an explicit confirmation.
_NEVER_FOR_KEYS = {"A", "I", "G", "K", "OO", "OD", "+"}
_CONFIRM_FOR_KEYS = {"$", "P"}
MAX_ENDPOINTS = 10  # per tenant
SECRET_ROTATION_GRACE = timedelta(hours=24)


# --- shared rules ------------------------------------------------------------------------------------------


def grantable_to_key(permission: Permission) -> bool:
    flags = set(permission.flags)
    return not flags & _NEVER_FOR_KEYS and not (permission.key.startswith("staff.") and "W" in flags)


def _require_person(principal: Principal) -> None:
    """Credentials are minted by people: an API key never creates, rotates or subscribes."""
    if principal.kind != "staff":
        raise PermissionDenied("Only a signed-in staff user can do this", code="staff-session-required")


def _check_can_hold(principal: Principal, scopes: list[str]) -> None:
    """Whoever mints or re-mints a secret must already hold every scope it carries, or they would gain them."""
    for key in scopes:
        if principal.permissions.get(key) is None:
            raise PermissionDenied(f"You do not hold {key}", code="scope-exceeds-creator", required=key)


def _check_locations(session: Session, principal: Principal, location_ids: list[UUID] | None, pointer: str) -> None:
    """Ids go through platform's scoped loader. A location-limited principal may not create something that
    reaches every location (None): it would exceed their own reach."""
    if location_ids is None:
        if principal.location_ids is not None:
            raise ValidationFailed("Choose the locations this may reach", pointer=pointer)
        return
    for index, location_id in enumerate(location_ids):
        try:
            platform.service.get_location(session, principal, location_id)
        except NotFound:
            raise ValidationFailed("Unknown location", pointer=f"{pointer}/{index}") from None


# --- API keys ----------------------------------------------------------------------------------------------


def _scoped_keys(principal: Principal) -> Select:
    stmt = select(ApiKey)
    if principal.location_ids is not None:  # a limited manager sees only keys confined to their own locations
        stmt = stmt.where(
            ApiKey.location_ids.is_not(None), ApiKey.location_ids.contained_by(sorted(principal.location_ids))
        )
    return stmt


def _load_key(session: Session, principal: Principal, api_key_id: UUID) -> ApiKey:
    row = session.scalar(_scoped_keys(principal).where(ApiKey.id == api_key_id))
    if row is None:
        raise NotFound()
    return row


def _mint(tenant_id: UUID) -> tuple[str, str, str]:
    """(raw secret, lookup prefix, digest). The prefix is the first 12 characters of the random part."""
    raw, digest = tokens.mint("fhk", tenant_id)
    return raw, raw.split("_", 2)[2][:12], digest


def list_api_keys(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "integrations.api_key.manage")
    return paginate(
        session, _scoped_keys(principal), query, id_column=ApiKey.id,
        sort_fields={"created_at": ApiKey.created_at, "name": ApiKey.name}, default_sort="-created_at",
        filter_fields={"status": ApiKey.status},
    )  # fmt: skip


def create_api_key(session: Session, principal: Principal, data: dict) -> tuple[ApiKey, str]:
    """Scopes are catalogue keys the creator holds and that may be given to a machine; the location set must
    lie inside the creator's. Returns the row and the raw secret, which is never stored or shown again."""
    authorize(principal, "integrations.api_key.manage")
    _require_person(principal)
    scopes = sorted(set(data["scopes"]))
    for index, key in enumerate(scopes):
        permission = PERMISSIONS.get(key)
        pointer = f"/scopes/{index}"
        if permission is None:
            raise ValidationFailed(f"Unknown permission {key}", pointer=pointer)
        if not grantable_to_key(permission):
            raise ValidationFailed(f"{key} cannot be given to an API key", pointer=pointer, code="scope-not-grantable")
        if set(permission.flags) & _CONFIRM_FOR_KEYS and not data.get("confirm_sensitive_scopes"):
            raise ValidationFailed(
                f"{key} moves money or changes prices: confirm it", pointer=pointer, code="confirmation-required"
            )
    _check_can_hold(principal, scopes)
    location_ids = sorted(set(data["location_ids"])) if data.get("location_ids") is not None else None
    _check_locations(session, principal, location_ids, "/location_ids")
    if (expires_at := data.get("expires_at")) and expires_at <= clock.now():
        raise ValidationFailed("The expiry must be in the future", pointer="/expires_at")
    raw, prefix, digest = _mint(session.info["tenant_id"])
    row = ApiKey(
        name=data["name"], key_prefix=prefix, secret_hash=digest, scopes=scopes, location_ids=location_ids,
        expires_at=expires_at, created_by_staff_user_id=principal.staff_user_id,
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(session, "integrations.api_key.create", row, changes=audit.diff(row))
    return row, raw


def rotate_api_key(session: Session, principal: Principal, api_key_id: UUID, data: dict) -> tuple[ApiKey, str]:
    """New secret now; the old one keeps working for `grace_minutes` (0 = it stops at once)."""
    authorize(principal, "integrations.api_key.manage")
    _require_person(principal)
    row = _load_key(session, principal, api_key_id)
    if row.status != ApiKeyStatus.ACTIVE:
        raise Conflict("A revoked key cannot be rotated")
    _check_can_hold(principal, row.scopes)
    now, grace = clock.now(), timedelta(minutes=data.get("grace_minutes", 1440))
    if grace:
        row.previous_key_prefix, row.previous_secret_hash = row.key_prefix, row.secret_hash
        row.previous_valid_until = now + grace
    else:
        row.previous_key_prefix = row.previous_secret_hash = row.previous_valid_until = None
    raw, row.key_prefix, row.secret_hash = _mint(session.info["tenant_id"])
    # The new secret goes to the rotator, so the key now acts as them: never with someone else's wider reach.
    row.rotated_at, row.created_by_staff_user_id = now, principal.staff_user_id
    audit.record(session, "integrations.api_key.rotate", row, changes=audit.diff(row))
    session.flush()
    return row, raw


def revoke_api_key(session: Session, principal: Principal, api_key_id: UUID) -> None:
    authorize(principal, "integrations.api_key.manage")
    row = _load_key(session, principal, api_key_id)
    if row.status == ApiKeyStatus.REVOKED:
        return
    row.status, row.revoked_at = ApiKeyStatus.REVOKED, clock.now()
    row.previous_key_prefix = row.previous_secret_hash = row.previous_valid_until = None
    audit.record(session, "integrations.api_key.revoke", row, changes=audit.diff(row))
    session.flush()


# --- webhook subscriptions ---------------------------------------------------------------------------------


def may_subscribe(principal: Principal, event: EventType) -> bool:
    """security-baseline 17.4: the read permission at reach `all`; a location-limited subscriber only to events
    whose location can be found, so deliveries can be filtered to their locations."""
    if event.permission is not None and principal.permissions.get(event.permission) != "all":
        return False
    return principal.location_ids is None or event.locate is not None


def _resolve_types(principal: Principal, requested: list[str]) -> list[str]:
    """'*' expands to the concrete list at save time and only if the principal may have every type."""
    if "*" in requested:
        if len(requested) > 1:
            raise ValidationFailed("'*' cannot be combined with other types", pointer="/event_types")
        if not all(may_subscribe(principal, e) for e in CATALOGUE.values()):
            raise PermissionDenied("'*' needs every event's read permission", code="event-permission-denied")
        return sorted(CATALOGUE)
    for index, name in enumerate(requested):
        if name not in CATALOGUE:
            raise ValidationFailed(f"Unknown event type {name}", pointer=f"/event_types/{index}")
        if not may_subscribe(principal, CATALOGUE[name]):
            raise PermissionDenied(
                f"You may not receive {name}", code="event-permission-denied", required=CATALOGUE[name].permission
            )
    return sorted(set(requested))


def list_event_types(principal: Principal) -> list[dict]:
    authorize(principal, "integrations.webhook.manage")
    return [
        {
            "type": e.type, "context": e.context, "description": e.description, "required_permission": e.permission,
            "allowed": may_subscribe(principal, e),
        }
        for e in CATALOGUE.values()
    ]  # fmt: skip


def _scoped_endpoints(principal: Principal) -> Select:
    stmt = select(WebhookEndpoint)
    if principal.location_ids is not None:  # tenant-wide aggregate: a limited manager handles only their own
        stmt = stmt.where(WebhookEndpoint.created_by_staff_user_id == principal.staff_user_id)
    return stmt


def _load_endpoint(session: Session, principal: Principal, endpoint_id: UUID) -> WebhookEndpoint:
    row = session.scalar(_scoped_endpoints(principal).where(WebhookEndpoint.id == endpoint_id))
    if row is None:
        raise NotFound()
    return row


def _new_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


def list_webhook_endpoints(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "integrations.webhook.manage")
    return paginate(
        session, _scoped_endpoints(principal), query, id_column=WebhookEndpoint.id,
        sort_fields={"created_at": WebhookEndpoint.created_at}, default_sort="-created_at",
        filter_fields={"status": WebhookEndpoint.status},
    )  # fmt: skip


def get_webhook_endpoint(session: Session, principal: Principal, endpoint_id: UUID) -> WebhookEndpoint:
    authorize(principal, "integrations.webhook.manage")
    return _load_endpoint(session, principal, endpoint_id)


def create_webhook_endpoint(session: Session, principal: Principal, data: dict) -> tuple[WebhookEndpoint, str]:
    authorize(principal, "integrations.webhook.manage")
    _require_person(principal)
    if session.scalar(select(func.count()).select_from(WebhookEndpoint)) >= MAX_ENDPOINTS:
        raise Conflict(f"At most {MAX_ENDPOINTS} endpoints", code="endpoint-limit-reached")
    transport.check(data["url"])
    types = _resolve_types(principal, data["event_types"])
    secret = _new_secret()
    row = WebhookEndpoint(
        url=data["url"], description=data.get("description"), event_types=types,
        secret_ciphertext=crypto.encrypt(secret, session.info["tenant_id"]),
        created_by_staff_user_id=principal.staff_user_id,
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(session, "integrations.webhook.create", row, changes=audit.diff(row))
    return row, secret


def update_webhook_endpoint(session: Session, principal: Principal, endpoint_id: UUID, data: dict) -> WebhookEndpoint:
    """Added event types are checked against the caller and the endpoint's creator (deliveries follow the
    creator). Only `active` and `paused` can be set; re-enabling clears the failure state."""
    authorize(principal, "integrations.webhook.manage")
    _require_person(principal)
    row = _load_endpoint(session, principal, endpoint_id)
    if data.get("url") is not None:
        # Repointing redirects the creator's grants to a URL the caller picks: the caller must hold them too.
        if not all(may_subscribe(principal, CATALOGUE[t]) for t in row.event_types if t in CATALOGUE):
            raise PermissionDenied("You may not receive this endpoint's events", code="event-permission-denied")
        transport.check(data["url"])
        # Deliveries now follow the caller's own grants and locations, as with a rotated API key.
        row.url, row.created_by_staff_user_id = data["url"], principal.staff_user_id
    if "description" in data:
        row.description = data["description"]
    if data.get("event_types") is not None:
        types = _resolve_types(principal, data["event_types"])
        added = set(types) - set(row.event_types)
        creator = platform.staff.principal_for(session, row.created_by_staff_user_id)
        if added and (creator is None or not all(may_subscribe(creator, CATALOGUE[t]) for t in added)):
            raise PermissionDenied(
                "The endpoint's creator may not receive these events", code="event-permission-denied"
            )
        row.event_types = types
    if (status := data.get("status")) and status != row.status:
        if status == EndpointStatus.ACTIVE:
            row.failure_count, row.disabled_at, row.disabled_reason = 0, None, None
        row.status = status
    audit.record(session, "integrations.webhook.update", row, changes=audit.diff(row))
    session.flush()
    return row


def delete_webhook_endpoint(session: Session, principal: Principal, endpoint_id: UUID) -> None:
    authorize(principal, "integrations.webhook.manage")
    row = _load_endpoint(session, principal, endpoint_id)
    audit.record(session, "integrations.webhook.delete", row)
    session.delete(row)  # deliveries go with it (ON DELETE CASCADE)
    session.flush()


def rotate_webhook_secret(session: Session, principal: Principal, endpoint_id: UUID) -> tuple[WebhookEndpoint, str]:
    """The previous secret keeps signing (a second v1 value) for 24 hours, so receivers can switch over."""
    authorize(principal, "integrations.webhook.manage")
    _require_person(principal)
    row = _load_endpoint(session, principal, endpoint_id)
    secret = _new_secret()
    row.previous_secret_ciphertext = row.secret_ciphertext
    row.previous_secret_expires_at = clock.now() + SECRET_ROTATION_GRACE
    row.secret_ciphertext = crypto.encrypt(secret, session.info["tenant_id"])
    audit.record(session, "integrations.webhook.rotate_secret", row, changes=audit.diff(row))
    session.flush()
    return row, secret


def test_webhook_endpoint(session: Session, principal: Principal, endpoint_id: UUID) -> WebhookDelivery:
    """A signed synthetic event sent now, outside the outbox, one attempt; it appears in the delivery log and
    leaves the endpoint's failure counters alone."""
    authorize(principal, "integrations.webhook.manage")
    endpoint = _load_endpoint(session, principal, endpoint_id)
    delivery = WebhookDelivery(
        webhook_endpoint_id=endpoint.id, event_id=new_id(), event_type=TEST_EVENT, status=DeliveryStatus.PENDING,
        payload={"type": TEST_EVENT, "schema_version": 1, "webhook_endpoint_id": str(endpoint.id)},
    )  # fmt: skip
    session.add(delivery)
    session.flush()
    _attempt(session, delivery, endpoint, retry=False)
    audit.record(session, "integrations.webhook.test", endpoint)
    session.flush()
    return delivery


# --- delivery log ------------------------------------------------------------------------------------------


def _scoped_deliveries(principal: Principal) -> Select:
    stmt = select(WebhookDelivery).join(WebhookEndpoint, WebhookEndpoint.id == WebhookDelivery.webhook_endpoint_id)
    if principal.location_ids is not None:
        stmt = stmt.where(WebhookEndpoint.created_by_staff_user_id == principal.staff_user_id)
    return stmt


def _load_delivery(session: Session, principal: Principal, delivery_id: UUID) -> WebhookDelivery:
    row = session.scalar(_scoped_deliveries(principal).where(WebhookDelivery.id == delivery_id))
    if row is None:
        raise NotFound()
    return row


def list_webhook_deliveries(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "integrations.delivery.read")
    return paginate(
        session, _scoped_deliveries(principal), query, id_column=WebhookDelivery.id,
        sort_fields={"created_at": WebhookDelivery.created_at}, default_sort="-created_at",
        filter_fields={
            "webhook_endpoint_id": WebhookDelivery.webhook_endpoint_id, "event_type": WebhookDelivery.event_type,
            "status": WebhookDelivery.status, "created_at": WebhookDelivery.created_at,
        },
    )  # fmt: skip


def get_webhook_delivery(session: Session, principal: Principal, delivery_id: UUID) -> WebhookDelivery:
    authorize(principal, "integrations.delivery.read")
    return _load_delivery(session, principal, delivery_id)


def replay_webhook_delivery(session: Session, principal: Principal, delivery_id: UUID) -> WebhookDelivery:
    """Same row, same event id (receivers dedupe on it), a fresh retry cycle."""
    authorize(principal, "integrations.webhook.manage")
    delivery = _load_delivery(session, principal, delivery_id)
    if delivery.status == DeliveryStatus.PENDING:
        raise Conflict("This delivery is already queued")
    if delivery.event_type == TEST_EVENT:
        raise Conflict("Send a new test instead of replaying one")
    endpoint = session.get(WebhookEndpoint, delivery.webhook_endpoint_id)  # parent of a scoped row
    if endpoint.status != EndpointStatus.ACTIVE:
        raise Conflict("Re-enable the endpoint first", code="endpoint-not-active")
    delivery.status, delivery.attempt_count, delivery.next_attempt_at = DeliveryStatus.PENDING, 0, clock.now()
    audit.record(session, "integrations.webhook.replay", delivery, changes=audit.diff(delivery))
    session.flush()
    _enqueue(session, delivery.id)
    return delivery


# --- delivery engine (internal: the fan-out subscriber and the delivery job call these) --------------------


def fan_out(session: Session, event_id: UUID, payload: dict) -> list[UUID]:
    """Internal. One pending delivery per active endpoint subscribed to the event, filtered by the creator's
    current grants and locations (re-evaluated on every event, so a lost permission stops deliveries at once).
    Idempotent: the unique (endpoint, event) key makes a redelivered outbox message a no-op."""
    event = CATALOGUE.get(payload.get("type", ""))
    if event is None:
        return []
    endpoints = session.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.status == EndpointStatus.ACTIVE, literal(event.type) == any_(WebhookEndpoint.event_types)
        )
    ).all()
    created: list[UUID] = []
    for endpoint in endpoints:
        if not _may_deliver(session, endpoint, event, payload):
            continue
        delivery_id = session.scalar(
            pg_insert(WebhookDelivery)
            .values(
                id=new_id(),
                tenant_id=session.info["tenant_id"],
                webhook_endpoint_id=endpoint.id,
                event_id=event_id,
                event_type=event.type,
                payload=payload,
                status=DeliveryStatus.PENDING,
                next_attempt_at=clock.now(),
            )  # fmt: skip
            .on_conflict_do_nothing(constraint="uq_webhook_delivery_endpoint_event")
            .returning(WebhookDelivery.id)
        )
        if delivery_id:
            created.append(delivery_id)
            _enqueue(session, delivery_id)
    return created


def _may_deliver(session: Session, endpoint: WebhookEndpoint, event: EventType, payload: dict) -> bool:
    """The creator's grants as of now: checked at fan-out and again before every attempt, so a lost
    permission or location also stops retries already queued."""
    creator = reevaluate(session, endpoint)
    if creator is None or not may_subscribe(creator, event):
        return False  # disabled, or this type is suspended until the creator regains the permission
    return creator.location_ids is None or event.locate(session, payload) in creator.location_ids


def reevaluate(session: Session, endpoint: WebhookEndpoint) -> Principal | None:
    """Internal. security-baseline 17.4: an endpoint whose creator can no longer act, or may receive none of its
    types, is disabled. Returns the creator's current principal while the endpoint stays active."""
    creator = platform.staff.principal_for(session, endpoint.created_by_staff_user_id)
    if creator is None:
        _disable(session, endpoint, "creator-inactive")
        return None
    if not any(may_subscribe(creator, CATALOGUE[t]) for t in endpoint.event_types if t in CATALOGUE):
        _disable(session, endpoint, "creator-lost-permissions")
        return None
    return creator


def reevaluate_creator(session: Session, staff_user_id: UUID) -> None:
    """Internal: run when a staff user is deactivated or their grants change."""
    for endpoint in session.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.created_by_staff_user_id == staff_user_id, WebhookEndpoint.status == EndpointStatus.ACTIVE
        )
    ).all():
        reevaluate(session, endpoint)


def attempt_delivery(session: Session, delivery_id: UUID) -> timedelta | None:
    """Internal. One attempt of a pending delivery under a row lock. Returns the wait before the next attempt."""
    delivery = session.scalar(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id).with_for_update())
    if delivery is None or delivery.status != DeliveryStatus.PENDING:
        return None  # already handled: at-least-once delivery of the job message is harmless
    endpoint = session.get(WebhookEndpoint, delivery.webhook_endpoint_id)
    event = CATALOGUE.get(delivery.event_type)
    if (
        endpoint.status != EndpointStatus.ACTIVE
        or event is None
        or not _may_deliver(session, endpoint, event, delivery.payload)
    ):
        delivery.status, delivery.next_attempt_at = DeliveryStatus.ABANDONED, None
        return None
    return _attempt(session, delivery, endpoint, retry=True)


def due_deliveries(session: Session, limit: int = 100) -> list[UUID]:
    """Internal: pending deliveries whose time has come (the sweep re-enqueues them after a lost message)."""
    return list(
        session.scalars(
            select(WebhookDelivery.id)
            .where(WebhookDelivery.status == DeliveryStatus.PENDING, WebhookDelivery.next_attempt_at <= clock.now())
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(limit)
        )
    )


def envelope(delivery: WebhookDelivery) -> bytes:
    body = {
        "id": str(delivery.event_id), "type": delivery.event_type, "created_at": delivery.created_at.isoformat(),
        "data": delivery.payload,
    }  # fmt: skip
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode()


def _signing_secrets(endpoint: WebhookEndpoint, tenant_id: UUID) -> list[str]:
    found = [crypto.decrypt(endpoint.secret_ciphertext, tenant_id)]
    expires = endpoint.previous_secret_expires_at
    if endpoint.previous_secret_ciphertext and expires and expires > clock.now():
        found.append(crypto.decrypt(endpoint.previous_secret_ciphertext, tenant_id))
    return found


def _attempt(
    session: Session, delivery: WebhookDelivery, endpoint: WebhookEndpoint, *, retry: bool
) -> timedelta | None:
    now = clock.now()
    body = envelope(delivery)
    headers = {
        "Content-Type": "application/json", "User-Agent": "FacilityHub-Webhooks/1",
        "FH-Event-Id": str(delivery.event_id), "FH-Event-Type": delivery.event_type, "FH-Delivery-Id": str(delivery.id),
        "FH-Signature": rules.signature_header(
            _signing_secrets(endpoint, session.info["tenant_id"]), int(now.timestamp()), body
        ),
    }  # fmt: skip
    delivery.attempt_count += 1
    response, error = None, None
    try:
        response = transport.send(transport.check(endpoint.url), headers, body)  # re-resolved and pinned every time
        delivery.last_response_status, delivery.last_duration_ms = response.status, response.duration_ms
    except transport.UrlNotAllowed as exc:
        error = f"url-not-allowed: {exc.detail}"
    except Exception as exc:  # the network boundary: any transport failure is one failed attempt
        error = f"{type(exc).__name__}: {exc}"[:300]
    if response is not None and 200 <= response.status < 300:
        delivery.status, delivery.delivered_at, delivery.next_attempt_at = DeliveryStatus.DELIVERED, now, None
        delivery.last_error = None
        if retry:
            endpoint.failure_count, endpoint.last_success_at = 0, now
        return None
    delivery.last_error = error or f"HTTP {response.status}: {response.snippet}"[:300]
    if not retry or (response is not None and response.status == 410):
        delivery.status, delivery.next_attempt_at = DeliveryStatus.FAILED, None
        if retry:
            _disable(session, endpoint, "gone")  # 410 Gone: the receiver asked us to stop
        return None
    if delivery.attempt_count >= rules.MAX_ATTEMPTS:
        delivery.status, delivery.next_attempt_at = DeliveryStatus.FAILED, None
        endpoint.failure_count += 1
        if endpoint.failure_count >= rules.DISABLE_AFTER_FAILED_DELIVERIES:
            _disable(session, endpoint, "sustained-failure")
        return None
    if _silent_for(session, endpoint, now) > rules.DISABLE_AFTER_SILENCE:
        delivery.status, delivery.next_attempt_at = DeliveryStatus.FAILED, None
        _disable(session, endpoint, "no-success-for-5-days")
        return None
    delay = rules.next_delay(delivery.attempt_count)
    delivery.next_attempt_at = now + delay
    return delay


def _silent_for(session: Session, endpoint: WebhookEndpoint, now: datetime) -> timedelta:
    """How long deliveries have been failing: since the oldest delivery created after the last success."""
    stmt = select(func.min(WebhookDelivery.created_at)).where(
        WebhookDelivery.webhook_endpoint_id == endpoint.id, WebhookDelivery.event_type != TEST_EVENT
    )
    if endpoint.last_success_at:
        stmt = stmt.where(WebhookDelivery.created_at > endpoint.last_success_at)
    oldest = session.scalar(stmt)
    return now - oldest if oldest else timedelta(0)


def _disable(session: Session, endpoint: WebhookEndpoint, reason: str) -> None:
    endpoint.status, endpoint.disabled_at, endpoint.disabled_reason = EndpointStatus.DISABLED, clock.now(), reason
    session.execute(
        update(WebhookDelivery)
        .where(WebhookDelivery.webhook_endpoint_id == endpoint.id, WebhookDelivery.status == DeliveryStatus.PENDING)
        .values(status=DeliveryStatus.ABANDONED, next_attempt_at=None)
    )
    audit.record(session, "integrations.webhook.disable", endpoint, changes=audit.diff(endpoint))
    events.publish(session, WebhookEndpointDisabled(webhook_endpoint_id=endpoint.id, reason=reason), endpoint.id)
    creator = platform.staff.principal_for(session, endpoint.created_by_staff_user_id)
    if creator is not None and creator.email:
        data = {"url": endpoint.url, "reason": reason}
        notifications.send(session, "integrations.webhook_disabled", creator.email, data)


def _enqueue(session: Session, delivery_id: UUID, delay: timedelta | None = None) -> None:
    from app.modules.integrations import jobs

    args = (str(session.info["tenant_id"]), str(delivery_id))
    options = {"delay": int(delay.total_seconds() * 1000)} if delay else {}
    session.info.setdefault("after_commit", []).append(
        lambda: jobs.deliver_webhook.send_with_options(args=args, **options)
    )


# --- provider connections, accounting export, adapters -----------------------------------------------------


def _scoped_connections(principal: Principal) -> Select:
    stmt = select(ExternalConnection)
    if principal.location_ids is not None:
        stmt = stmt.where(ExternalConnection.location_id.in_(principal.location_ids))
    return stmt


def _load_connection(session: Session, principal: Principal, connection_id: UUID) -> ExternalConnection:
    row = session.scalar(_scoped_connections(principal).where(ExternalConnection.id == connection_id))
    if row is None:
        raise NotFound()
    return row


def list_external_connections(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "integrations.connection.manage")
    return paginate(
        session, _scoped_connections(principal), query, id_column=ExternalConnection.id,
        sort_fields={"created_at": ExternalConnection.created_at}, default_sort="-created_at",
        filter_fields={
            "provider": ExternalConnection.provider, "status": ExternalConnection.status,
            "location_id": ExternalConnection.location_id,
        },
    )  # fmt: skip


def create_external_connection(session: Session, principal: Principal, data: dict) -> ExternalConnection:
    """v1 connects the JSON-file accounting export. QuickBooks needs a registered Intuit app
    (integrations.quickbooks_enabled) and its OAuth round trip, which are not built: 422 until then."""
    location_id = data.get("location_id")
    authorize(principal, "integrations.connection.manage", location_id=location_id)
    _require_person(principal)
    if data["provider"] == Provider.QUICKBOOKS_ONLINE and not get_settings().integrations.quickbooks_enabled:
        raise ValidationFailed(
            "QuickBooks Online is not configured", pointer="/provider", code="provider-not-configured"
        )
    _check_locations(session, principal, [location_id] if location_id else None, "/location_id")
    row = ExternalConnection(
        provider=data["provider"], location_id=location_id, status=ConnectionStatus.ACTIVE,
        settings=data.get("settings") or {}, connected_by_staff_user_id=principal.staff_user_id,
        connected_at=clock.now(),
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(session, "integrations.connection.create", row, location_id=location_id, changes=audit.diff(row))
    return row


def disconnect_external_connection(session: Session, principal: Principal, connection_id: UUID) -> ExternalConnection:
    row = _load_connection(session, principal, connection_id)
    authorize(principal, "integrations.connection.manage", location_id=row.location_id)
    row.status, row.credentials_ciphertext = ConnectionStatus.DISCONNECTED, None
    audit.record(
        session, "integrations.connection.disconnect", row, location_id=row.location_id, changes=audit.diff(row)
    )
    session.flush()
    return row


def _accounting_adapter(connection: ExternalConnection, tenant_id: UUID) -> Any:
    from app.adapters.accounting import FakeAccounting, JsonFileAccounting, QuickBooksOnline

    cfg = get_settings().integrations
    if connection.provider == Provider.ACCOUNTING_FILE:
        return JsonFileAccounting(cfg.accounting_file_dir)
    if (
        connection.provider == Provider.QUICKBOOKS_ONLINE
        and cfg.quickbooks_enabled
        and connection.credentials_ciphertext
    ):
        token = json.loads(crypto.decrypt(connection.credentials_ciphertext, tenant_id))["access_token"]
        return QuickBooksOnline(realm_id=connection.external_account_id or "", access_token=token)
    return FakeAccounting()


def _ledger_rows(session: Session, location_id: UUID, business_on: date) -> tuple[list, str]:
    """(posting key, debit, credit) per ledger dimension for one location-day.
    shortcut: reads billing's ledger_entry directly (read-only, under RLS) because billing exposes no day-totals
    function and reporting's ledger copy does not exist yet; switch to that call when one ships."""
    rows = session.execute(
        text(
            "SELECT account, revenue_category_id, tax_id, sum(debit_minor), sum(credit_minor), max(currency) "
            "FROM ledger_entry WHERE location_id = :l AND effective_on = :d GROUP BY 1, 2, 3"
        ),
        {"l": location_id, "d": business_on},
    ).all()
    currency = next((r[5] for r in rows), "USD")
    return [(journal.posting_key(r[0], r[1], r[2]), int(r[3]), int(r[4])) for r in rows], currency


def export_accounting_day(
    session: Session, principal: Principal, connection_id: UUID, location_id: UUID, business_on: date
) -> AccountingExport:
    """Post one location-day as a summarised journal. Re-running a finished day returns it unchanged; a failed
    or pending day is attempted again with the same request id (the provider dedupes on it)."""
    connection = _load_connection(session, principal, connection_id)
    authorize(principal, "integrations.sync.run", location_id=location_id)
    if connection.provider not in (Provider.ACCOUNTING_FILE, Provider.QUICKBOOKS_ONLINE):
        raise ValidationFailed("Not an accounting connection", pointer="/external_connection_id")
    if connection.status != ConnectionStatus.ACTIVE:
        raise Conflict("The connection is not active")
    if connection.location_id not in (None, location_id):
        raise ValidationFailed("The connection serves another location", pointer="/location_id")
    try:
        location = platform.service.get_location(session, principal, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location", pointer="/location_id") from None
    export = session.scalar(
        select(AccountingExport).where(
            AccountingExport.external_connection_id == connection.id,
            AccountingExport.location_id == location_id,
            AccountingExport.business_on == business_on,
        )
    )
    if export is None:
        export = AccountingExport(
            external_connection_id=connection.id, location_id=location_id, business_on=business_on
        )
        session.add(export)
        session.flush()
    elif export.status in (ExportStatus.POSTED, ExportStatus.COMPLETED_WITH_WARNINGS, ExportStatus.SKIPPED):
        return export
    export.attempt_count += 1
    export.last_attempt_at = clock.now()
    export.doc_number = f"FH-{location.slug.upper()[:12]}-{business_on:%Y%m%d}"
    try:
        rows, currency = _ledger_rows(session, location_id, business_on)
        lines = journal.build(rows)
        if not lines:
            export.status = ExportStatus.SKIPPED
        else:
            export.external_id, unmapped = _post_journal(session, connection, export, lines, currency, location_id)
            export.status = ExportStatus.COMPLETED_WITH_WARNINGS if unmapped else ExportStatus.POSTED
            export.posted_at, export.last_error = clock.now(), None
            export.totals = {"lines": [vars(line) for line in lines], "unmapped": unmapped, "currency": currency}
        connection.last_sync_at = clock.now()
    except Exception as exc:  # the provider boundary (and an unbalanced day): the export fails, visibly
        export.status, export.last_error = ExportStatus.FAILED, f"{type(exc).__name__}: {exc}"[:300]
    audit.record(session, "integrations.sync.run", export, location_id=location_id, changes=audit.diff(export))
    session.flush()
    return export


def _post_journal(
    session: Session, connection: ExternalConnection, export: AccountingExport, lines: list, currency: str,
    location_id: UUID,
) -> tuple[str, list[str]]:  # fmt: skip
    from app.ports.accounting import Journal, JournalLine

    account_map: dict[str, str] = connection.settings.get("account_map", {})
    default_income = connection.settings.get("default_income_account")
    unmapped, out = [], []
    for line in lines:
        ref = account_map.get(line.posting_key)
        if ref is None and line.posting_key.startswith("revenue:") and default_income:
            ref = default_income  # never block on an unmapped category: post it unclassed and warn
            unmapped.append(line.posting_key)
        if ref is None and connection.provider == Provider.QUICKBOOKS_ONLINE:
            raise ValidationFailed(f"No QuickBooks account mapped for {line.posting_key}")
        out.append(
            JournalLine(ref or line.posting_key, line.debit_minor, line.credit_minor, description=line.posting_key)
        )
    entry = Journal(
        doc_number=export.doc_number, business_on=export.business_on.isoformat(), currency=currency,
        memo=f"FacilityHub daily summary {export.business_on.isoformat()}", lines=out,
    )  # fmt: skip
    adapter = adapter_for(
        session, _accounting_adapter(connection, session.info["tenant_id"]), "accounting", location_id
    )
    return adapter.post_journal(entry, request_id=f"{session.info['tenant_id']}:qbo_je:{export.id}"), unmapped


def list_accounting_exports(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "integrations.sync.run")
    stmt = select(AccountingExport)
    if principal.location_ids is not None:
        stmt = stmt.where(AccountingExport.location_id.in_(principal.location_ids))
    return paginate(
        session, stmt, query, id_column=AccountingExport.id,
        sort_fields={"business_on": AccountingExport.business_on}, default_sort="-business_on",
        filter_fields={
            "external_connection_id": AccountingExport.external_connection_id,
            "location_id": AccountingExport.location_id, "status": AccountingExport.status,
        },
    )  # fmt: skip


def list_adapter_commands(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "integrations.connection.manage")
    stmt = select(AdapterCommandLog)
    if principal.location_ids is not None:
        stmt = stmt.where(AdapterCommandLog.location_id.in_(principal.location_ids))
    return paginate(
        session, stmt, query, id_column=AdapterCommandLog.id,
        sort_fields={"occurred_at": AdapterCommandLog.occurred_at}, default_sort="-occurred_at",
        filter_fields={"port": AdapterCommandLog.port, "location_id": AdapterCommandLog.location_id},
    )  # fmt: skip


# Ports the integrations ADR names and what this build wires for each: the directory page's truthful status.
_DIRECTORY = (
    ("accounting", "Accounting export (daily journal)"),
    ("video_meeting", "Video meetings"),
    ("payment_provider", "Card payments"),
    ("email", "Email delivery"),
    ("door_controller", "Door access control"),
    ("credential_reader", "Credential and biometric readers"),
    ("card_terminal", "Card-present terminals"),
    ("waiver_provider", "Waiver provider intake"),
    ("sms", "Text messages"),
)


def list_adapters(session: Session, principal: Principal) -> list[dict]:
    authorize(principal, "integrations.connection.manage")
    settings = get_settings()
    active = set(
        session.scalars(
            _scoped_connections(principal)
            .where(ExternalConnection.status == ConnectionStatus.ACTIVE)
            .with_only_columns(ExternalConnection.provider)
        )
    )
    out = []
    for port, label in _DIRECTORY:
        adapter, status, detail = None, "not_configured", "No adapter is built for this port yet."
        if port == "accounting":
            if Provider.ACCOUNTING_FILE in active:
                adapter, status, detail = "accounting_file", "connected", "Daily journal written as a JSON file."
            else:
                adapter, status = "fake_accounting", "simulated"
                detail = "Simulated. QuickBooks Online is built behind the port but switched off."
        elif port == "video_meeting":
            adapter, status, detail = "fake_video", "simulated", "Simulated meetings; no Zoom app is registered."
        elif port == "payment_provider":
            simulated = settings.payments.provider == "fake"
            adapter, status = settings.payments.provider, "simulated" if simulated else "not_configured"
            detail = "Fake processor: takes no real money." if simulated else "No processor connected."
        elif port == "email":
            adapter, status, detail = settings.email.adapter, "connected", "Transactional email."
        out.append({"port": port, "label": label, "adapter": adapter, "status": status, "detail": detail})
    return out


class _Recorded:
    """Wraps a simulated adapter so every call is written to adapter_command_log (plain values only)."""

    def __init__(self, session: Session, adapter: Any, port: str, location_id: UUID | None) -> None:
        self._session, self._adapter, self._port, self._location_id = session, adapter, port, location_id

    def __getattr__(self, command: str) -> Any:
        target = getattr(self._adapter, command)

        def call(*args: Any, **kwargs: Any) -> Any:
            plain = (str, int, float, bool, type(None))
            arguments = {k: v if isinstance(v, plain) else str(v) for k, v in kwargs.items()}
            self._session.add(
                AdapterCommandLog(
                    port=self._port,
                    adapter=self._adapter.name,
                    location_id=self._location_id,
                    command=command,
                    arguments=arguments,
                    occurred_at=clock.now(),
                )  # fmt: skip
            )
            return target(*args, **kwargs)

        return call


def adapter_for(session: Session, adapter: Any, port: str, location_id: UUID | None = None) -> Any:
    """Internal: later modules get their port adapter through here so simulated adapters leave evidence. Real
    adapters are returned untouched (their evidence is the provider's own log and our audit)."""
    return _Recorded(session, adapter, port, location_id) if getattr(adapter, "simulated", False) else adapter


def video_meetings(session: Session, location_id: UUID | None = None) -> Any:
    """Internal: the VideoMeeting port for a location (the simulated adapter in v1)."""
    from app.adapters.video import FakeVideo

    return adapter_for(session, FakeVideo(), "video_meeting", location_id)
