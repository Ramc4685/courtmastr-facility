"""FastAPI dependencies: tenant resolution, principal resolution and the router permission gate.

The request transaction is opened here and stored on request.state; app.core.api.TxRoute commits it
before the response leaves, or rolls it back.
"""

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.auth import tokens
from app.core.auth.permissions import STAFF_SURFACE
from app.core.auth.principal import Principal
from app.core.db.platform import TenantRef, resolve_tenant
from app.core.db.session import open_tenant_session
from app.core.errors import NotFound, PermissionDenied, Unauthenticated

ACCESS_COOKIE = "fh_access"
REFRESH_COOKIE = "fh_refresh"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Ctx:
    session: Session
    principal: Principal


# Modules register how a bearer token becomes a Principal, by token prefix; core stays below the modules.
# fhs: staff/client session (platform); fhk: API key (integrations), accepted only on require() routes.
_authenticators: dict[str, Callable[[Session, str], Principal]] = {}
_API_KEY_PREFIX = "fhk"


def set_authenticator(fn: Callable[[Session, str], Principal], prefix: str = "fhs") -> None:
    _authenticators[prefix] = fn


def _accepts_api_key(route) -> bool:
    """True when the route is gated by require(): API keys reach the staff surface only, never the self-service
    routes (/me, /auth/*) or the portal, which assume a person behind the principal."""

    def walk(dependant) -> bool:
        return getattr(dependant.call, "accepts_api_key", False) or any(walk(d) for d in dependant.dependencies)

    dependant = getattr(route, "dependant", None)
    return dependant is not None and walk(dependant)


def request_session(request: Request, tenant_id: UUID) -> Session:
    existing = getattr(request.state, "session", None)
    if existing is None:
        request.state.session = existing = open_tenant_session(tenant_id)
    elif existing.info["tenant_id"] != tenant_id:
        raise Unauthenticated("Host and token disagree")
    request.state.tenant_id = tenant_id
    return existing


def _host_tenant(request: Request) -> TenantRef | None:
    host = request.headers.get("host", "").split(":")[0].lower()
    return resolve_tenant(host=host) if host else None


def public_session(request: Request) -> Session:
    """Anonymous routes: tenant from the request host, or from X-Tenant-Slug where there is no tenant host
    (the shared mobile app, local development). The slug is an address, not a credential."""
    ref = _host_tenant(request)
    if ref is None and (slug := request.headers.get("x-tenant-slug")):
        ref = resolve_tenant(slug=slug.lower())
    if ref is None:
        raise NotFound("Unknown tenant", code="tenant-not-found")
    if ref.status != "active":
        raise PermissionDenied("This account is not active", code="tenant-suspended")
    return request_session(request, ref.id)


def current_ctx(request: Request) -> Ctx:
    """Any signed-in principal (staff or client)."""
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else None
    via_cookie = token is None
    token = token or request.cookies.get(ACCESS_COOKIE)
    prefix = "fhs"
    if not via_cookie and token.startswith(f"{_API_KEY_PREFIX}_") and _API_KEY_PREFIX in _authenticators:
        if not _accepts_api_key(request.scope.get("route")):
            raise PermissionDenied("API keys cannot use this operation", code="api-key-not-allowed")
        prefix = _API_KEY_PREFIX
    tenant_id = tokens.tenant_of(token, prefix)
    if tenant_id is None:
        raise Unauthenticated("Sign in to continue")
    host_ref = _host_tenant(request)
    if host_ref is not None and host_ref.id != tenant_id:
        raise Unauthenticated("Host and token disagree")
    session = request_session(request, tenant_id)
    assert prefix in _authenticators, "no authenticator registered"
    principal = _authenticators[prefix](session, token)
    if via_cookie and request.method not in _SAFE_METHODS:
        # Cookies are attached by the browser on its own, so unsafe methods must also prove the page can read
        # the session-bound token (security-baseline 5.3). Bearer callers are exempt.
        if not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), tokens.csrf_for(token).encode()):
            raise PermissionDenied("Missing or wrong X-CSRF-Token", code="csrf-failed")
    session.info["actor"] = principal
    request.state.principal = principal
    return Ctx(session, principal)


def require(*keys: str) -> Callable[..., Ctx]:
    """Router gate: an active staff or API-key principal holding at least one of the keys anywhere.
    With no keys it means `authenticated` staff. The service-layer authorize() remains the real gate."""

    def dependency(ctx: Ctx = Depends(current_ctx)) -> Ctx:
        principal = ctx.principal
        if principal.kind not in STAFF_SURFACE:
            raise PermissionDenied("Staff only")
        if keys and not any(principal.has(key) for key in keys):
            raise PermissionDenied(f"Requires {keys[0]}", required=keys[0])
        return ctx

    dependency.accepts_api_key = True
    dependency.keys = keys  # read by the generated location-scope tests
    return dependency
