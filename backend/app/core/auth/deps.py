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
from app.core.settings import get_settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _cookie_name(base: str) -> str:
    # Browsers accept a __Host- cookie only with Secure, so local http development uses the bare name.
    return f"__Host-{base}" if get_settings().auth.cookie_secure else base


def session_cookie() -> str:
    """The one web session cookie (security-baseline 5.2): `<session token>.<csrf token>`, HttpOnly."""
    return _cookie_name("fh_session")


def pre_session_cookie() -> str:
    """The short-lived login-CSRF cookie for the anonymous auth POSTs (baseline 5.3 item 4)."""
    return _cookie_name("fh_pre")


def cookie_parts(request: Request) -> tuple[str | None, str | None]:
    """(session token, csrf token) from the session cookie; the CSRF half is what GET /auth/session hands
    the page, because the database keeps only its hash."""
    token, _, csrf = request.cookies.get(session_cookie(), "").partition(".")
    return token or None, csrf or None


@dataclass
class Ctx:
    session: Session
    principal: Principal


# Modules register how a bearer token becomes a Principal, by token prefix; core stays below the modules.
# fhs: staff/client session (platform); fhk: API key (integrations), accepted only on require(<key>) routes.
_authenticators: dict[str, Callable[[Session, str], Principal]] = {}
_API_KEY_PREFIX = "fhk"


def set_authenticator(fn: Callable[[Session, str], Principal], prefix: str = "fhs") -> None:
    _authenticators[prefix] = fn


# How a cookie session's X-CSRF-Token is checked against server state: fn(session, principal, header) -> ok.
_csrf_verifier: Callable[[Session, Principal, str], bool] = lambda session, principal, header: False  # noqa: E731


def set_csrf_verifier(fn: Callable[[Session, Principal, str], bool]) -> None:
    global _csrf_verifier
    _csrf_verifier = fn


def _accepts_api_key(route) -> bool:
    """True when the route is gated by require() with at least one key: API keys reach the staff surface only, never the self-service
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
    token = token or cookie_parts(request)[0]
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
        # Cookies are attached by the browser on its own, so unsafe methods must also present the session's
        # synchroniser token, checked against the hash on the session row (security-baseline 5.3). Bearer
        # callers are exempt.
        if not _csrf_verifier(session, principal, request.headers.get("x-csrf-token", "")):
            raise PermissionDenied("Missing or wrong X-CSRF-Token", code="csrf-failed")
    session.info["actor"] = principal
    request.state.principal = principal
    return Ctx(session, principal)


def pre_session_csrf(request: Request) -> None:
    """Login CSRF on the anonymous auth POSTs (baseline 5.3 item 4): a browser must echo the token that
    GET /auth/pre-session put in the HttpOnly pre-session cookie. Browsers always send Origin or Sec-Fetch-Site
    on a POST and a page cannot remove them; a request with neither is not a browser (the mobile app, a server),
    has no ambient cookie to abuse, and passes."""
    if "origin" not in request.headers and "sec-fetch-site" not in request.headers:
        return
    cookie = request.cookies.get(pre_session_cookie(), "")
    if not cookie or not hmac.compare_digest(cookie.encode(), request.headers.get("x-csrf-token", "").encode()):
        raise PermissionDenied("Missing or wrong X-CSRF-Token", code="csrf-failed")


def require(*keys: str) -> Callable[..., Ctx]:
    """Router gate: an active staff or API-key principal holding at least one of the keys anywhere.
    With no keys it means `authenticated` staff, and API keys are refused: a key's scopes name keys, so a keyless
    route (configuration reads with no authorize()) is outside every key (W2-02). The service-layer authorize()
    remains the real gate."""

    def dependency(ctx: Ctx = Depends(current_ctx)) -> Ctx:
        principal = ctx.principal
        if principal.kind not in STAFF_SURFACE:
            raise PermissionDenied("Staff only")
        if keys and not any(principal.has(key) for key in keys):
            raise PermissionDenied(f"Requires {keys[0]}", required=keys[0])
        return ctx

    dependency.accepts_api_key = bool(keys)
    dependency.keys = keys  # read by the generated location-scope tests
    return dependency
