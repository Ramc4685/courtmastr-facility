"""API-key bearer authentication (registered for the `fhk` token prefix in app.bootstrap).

A key acts as its creator, narrowed: permissions = the key's scopes the creator still holds (with the creator's
reach), locations = the overlap of the key's and the creator's. It is recomputed on every request, so losing a
grant, a location or the account itself narrows or stops the key at once.
"""

import hmac
import logging
from dataclasses import replace

import redis
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import clock, ratelimit
from app.core.auth import CATALOGUE, Principal, tokens
from app.core.errors import DomainError, PermissionDenied, Unauthenticated
from app.core.ratelimit import _redis
from app.core.settings import get_settings
from app.modules import platform
from app.modules.integrations.models import ApiKey, ApiKeyStatus
from app.modules.integrations.service import grantable_to_key

log = logging.getLogger(__name__)
_INVALID = "Invalid or expired API key"


def _find(session: Session, token: str) -> ApiKey:
    parts = token.split("_", 2)
    prefix = parts[2][:12] if len(parts) == 3 else ""
    row = session.scalar(
        select(ApiKey).where(or_(ApiKey.key_prefix == prefix, ApiKey.previous_key_prefix == prefix))
    ) if prefix else None  # fmt: skip
    if row is None or row.status != ApiKeyStatus.ACTIVE:
        raise Unauthenticated(_INVALID)
    now, digest = clock.now(), tokens.digest(token)
    current = row.key_prefix == prefix and hmac.compare_digest(row.secret_hash, digest)
    previous = (
        row.previous_key_prefix == prefix and row.previous_secret_hash is not None
        and row.previous_valid_until is not None and row.previous_valid_until > now
        and hmac.compare_digest(row.previous_secret_hash, digest)
    )  # fmt: skip
    if not (current or previous) or (row.expires_at and row.expires_at <= now):
        raise Unauthenticated(_INVALID)
    return row


def _bounded(creator: Principal, key: ApiKey) -> Principal:
    if creator.location_ids is None:
        locations = frozenset(key.location_ids) if key.location_ids is not None else None
    else:
        locations = (
            creator.location_ids & set(key.location_ids) if key.location_ids is not None else creator.location_ids
        )
    return replace(
        creator, kind="api_key", api_key_id=key.id, staff_user_id=None, session_id=None, role_system_key=None,
        display_name=f"API key: {key.name}",
        # The allow-list applies here too, so a scope stored some other way never reaches the key.
        permissions={
            k: creator.permissions[k]
            for k in key.scopes
            if k in creator.permissions and k in CATALOGUE and grantable_to_key(CATALOGUE[k])
        },
        location_ids=locations,
    )  # fmt: skip


def _rate_limit(key: ApiKey) -> None:
    """shortcut: fixed one-minute window per key (not a token bucket), no RateLimit-* headers; fails open when
    Redis is down. Upgrade when a partner needs burst control or remaining-quota headers."""
    cfg = get_settings().rate_limit
    if not cfg.enabled:
        return
    window = int(clock.now().timestamp() // 60)
    name = f"t:{key.tenant_id}:rl:api:{key.id}:{window}"
    try:
        pipe = _redis().pipeline()
        pipe.incr(name)
        pipe.expire(name, 60)
        count = pipe.execute()[0]
    except redis.RedisError:
        log.warning("api key rate limit unavailable")
        return
    if count > cfg.api_per_minute:
        raise DomainError(
            "Too many requests for this API key", status=429, code="rate-limited", headers={"Retry-After": "60"}
        )
    # The tenant's ceiling across all its keys (ADR 0012 section 2, bucket `api-tenant` in config/app.yaml).
    ratelimit.hit("api-tenant", str(key.tenant_id), tenant=key.tenant_id)


def authenticate(session: Session, token: str) -> Principal:
    key = _find(session, token)
    if platform.service.get_tenant(session).status != "active":
        raise PermissionDenied("This account is not active.", code="tenant-suspended")
    platform.entitlements.require_feature(session, "api_access")  # PLT-14: keys stop when the plan drops it
    creator = platform.staff.principal_for(session, key.created_by_staff_user_id)
    if creator is None:  # the person behind the key can no longer act, so neither can the key
        raise Unauthenticated(_INVALID)
    _rate_limit(key)
    now = clock.now()
    if key.last_used_at is None or (now - key.last_used_at).total_seconds() > 60:
        key.last_used_at = now  # at most one write a minute per key
    return _bounded(creator, key)
