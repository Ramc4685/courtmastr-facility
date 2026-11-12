"""OpenID Connect sign-in for staff (Phase 8 S3; ADR 0002 sections 3, 6 and 9; security-baseline 5.1).

Authorization code flow with PKCE (S256). One round trip is an `auth_token` row of purpose `oidc_state`: the
`state` parameter is its token (the tenant rides in its prefix, as in every other token), and its payload holds
the nonce, the sealed PKCE verifier, the provider and a digest of the browser's pre-session cookie, so a
callback completes once, in the browser that started it, within ten minutes.

The ID token is checked against the issuer's JWKS: signature (RS256, PS256 or ES256 only), `iss`, `aud` (and
`azp` when there are several audiences), `exp`, `iat` and `nonce`. A sign-in maps to an existing staff identity
of this tenant: by issuer and subject once linked, else by a verified email, which then stores the link. Staff
are never created here. Every sign-in goes through auth._second_factor and auth._start_session.

Outbound requests (discovery, JWKS, token endpoint) go to https URLs whose every address is globally routable,
checked at connect time and pinned to the checked address (no DNS rebinding), with a timeout, no redirects and
a response cap.
"""

import base64
import hashlib
import hmac
import re
import secrets
import socket
import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpcore
import httpx
import jwt
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import audit, clock, crypto, networks
from app.core.auth import Principal, authorize, tokens
from app.core.errors import DomainError, NotFound, PermissionDenied, Unauthenticated, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules.platform import auth, mfa
from app.modules.platform.models import (
    AuthSession,
    AuthToken,
    ExternalLogin,
    Identity,
    IdentityProviderConfig,
    TokenPurpose,
)

STATE_PREFIX = "fho"
CALLBACK_PATH = "/auth/oidc/callback"  # the web route; the one redirect URI an owner registers
_STATE_TTL = timedelta(minutes=10)
_CACHE_SEC = 3600
_TIMEOUT_SEC = 5.0
_MAX_BYTES = 1 << 20
_LEEWAY_SEC = 60
_ALGORITHMS = {"RS256", "PS256", "ES256"}
# RFC 8176 methods that are a factor beyond a password; "mfa" is the provider saying so itself.
_MFA_AMR = {"mfa", "otp", "hwk", "swk", "sms", "tel", "fido"}
_MFA_ACR = {"http://schemas.openid.net/pape/policies/2007/06/multi-factor", "mfa"}
GOOGLE_ISSUER = "https://accounts.google.com"
# A single Entra ID directory. The multi-tenant endpoints (common, organizations, consumers) publish a templated
# issuer that never equals the token's, and would admit any directory's users: refused.
_MICROSOFT_ISSUER = re.compile(r"https://login\.microsoftonline\.com/[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}/v2\.0")
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
_SCOPE = re.compile(r"[\x21\x23-\x5b\x5d-\x7e]+")


class ProviderError(Exception):
    """The provider could not be reached or answered something unusable. Never shown verbatim."""


class UnsafeUrl(ProviderError):
    pass


def _failed(persist: bool = True) -> Unauthenticated:
    return Unauthenticated(
        "Sign-in with that provider did not complete. Try again.", code="oidc-failed", persist=persist
    )


def _refused() -> Unauthenticated:
    # One answer for an unknown user, an unverified or disallowed email and a disabled identity: no enumeration.
    return Unauthenticated(
        "We could not sign you in with that account. Use the account your administrator invited, or sign in another way.",
        code="oidc-sign-in-refused", persist=True,
    )  # fmt: skip


def redirect_uri() -> str:
    return f"{get_settings().app.web_base_url}{CALLBACK_PATH}"


# --- outbound HTTP ---------------------------------------------------------------------------------------------


def resolve(host: str, port: int) -> list[str]:
    return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def _checked_address(url: str) -> str:
    """The SSRF guard: https, no credentials in the URL, every resolved address globally routable."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise UnsafeUrl("https URLs only, without credentials")
    try:
        addresses = resolve(parts.hostname, parts.port or 443)
    except (OSError, ValueError, UnicodeError):
        raise UnsafeUrl("the host does not resolve") from None
    for address in addresses or ["0.0.0.0"]:
        if reason := networks.blocked_reason(address):
            raise UnsafeUrl(f"the host resolves to a {reason} address")
    return addresses[0]


class _PinnedBackend(httpcore.SyncBackend):
    def __init__(self, address: str) -> None:
        self.address = address

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return super().connect_tcp(self.address, port, timeout, local_address, socket_options)


class _PinnedTransport(httpx.BaseTransport):
    """Connects only to the address the guard checked; TLS still verifies the certificate for the URL's host."""

    def __init__(self, address: str) -> None:
        self._pool = httpcore.ConnectionPool(network_backend=_PinnedBackend(address))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        with self._pool.stream(
            request.method, str(request.url), headers=request.headers.raw, content=request.read(),
            extensions=request.extensions,
        ) as response:  # fmt: skip
            body = b"".join(_capped(response.iter_stream()))
            return httpx.Response(response.status, headers=response.headers, content=body)

    def close(self) -> None:
        self._pool.close()


def _capped(chunks: Iterator[bytes]) -> Iterator[bytes]:
    size = 0
    for chunk in chunks:
        size += len(chunk)
        if size > _MAX_BYTES:
            raise ProviderError("response too large")
        yield chunk


def _transport(address: str) -> httpx.BaseTransport:
    return _PinnedTransport(address)  # the test suite swaps in its in-process provider here


def _fetch(method: str, url: str, **kwargs: Any) -> dict:
    address = _checked_address(url)
    try:
        with httpx.Client(transport=_transport(address), timeout=_TIMEOUT_SEC, follow_redirects=False) as client:
            response = client.request(method, url, headers={"accept": "application/json"}, **kwargs)
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError(type(exc).__name__) from None
    if response.status_code != 200 or not isinstance(data, dict):
        raise ProviderError(f"status {response.status_code}")
    return data


# shortcut: a per-process cache of discovery documents and key sets; a shared cache (Redis) if workers multiply.
_cache: dict[str, tuple[float, dict]] = {}


def _cached(url: str, *, refresh: bool = False) -> dict:
    hit = _cache.get(url)
    if hit and not refresh and hit[0] > time.monotonic():
        return hit[1]
    data = _fetch("GET", url)
    _cache[url] = (time.monotonic() + _CACHE_SEC, data)
    return data


def discover(issuer: str) -> dict:
    """The issuer's discovery document; its `issuer` must equal the configured one exactly (OIDC Discovery 4.3)."""
    doc = _cached(issuer.rstrip("/") + "/.well-known/openid-configuration")
    if doc.get("issuer") != issuer:
        raise ProviderError("issuer mismatch")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not isinstance(doc.get(key), str) or not doc[key].startswith("https://"):
            raise ProviderError(f"no {key}")
    if "S256" not in doc.get("code_challenge_methods_supported", ["S256"]):
        raise ProviderError("no PKCE S256")
    return doc


def _signing_key(jwks_uri: str, kid: str | None, alg: str) -> Any:
    """The JWK for `kid`; an unknown kid refetches the set once (the provider rotated its keys)."""
    for refresh in (False, True):
        keys = [k for k in _cached(jwks_uri, refresh=refresh).get("keys", []) if isinstance(k, dict)]
        keys = [k for k in keys if k.get("use", "sig") == "sig" and (kid is None or k.get("kid") == kid)]
        if len(keys) == 1:
            return jwt.PyJWK(keys[0], algorithm=alg).key
    raise ProviderError("signing key not found")


# --- ID token ----------------------------------------------------------------------------------------------------


def _issuers(config: IdentityProviderConfig) -> list[str]:
    # Google documents both forms of its issuer in ID tokens.
    return [config.issuer_url, "accounts.google.com"] if config.preset == "google" else [config.issuer_url]


def verify_id_token(config: IdentityProviderConfig, doc: dict, id_token: str, nonce: str) -> dict:
    try:
        alg = jwt.get_unverified_header(id_token).get("alg")
        if alg not in _ALGORITHMS:
            raise ProviderError("algorithm not allowed")
        key = _signing_key(doc["jwks_uri"], jwt.get_unverified_header(id_token).get("kid"), alg)
        claims = jwt.decode(
            id_token, key=key, algorithms=[alg], audience=config.client_id, issuer=_issuers(config),
            leeway=_LEEWAY_SEC, options={"require": ["iss", "sub", "aud", "exp", "iat"]},
        )  # fmt: skip
    except jwt.PyJWTError as exc:
        raise ProviderError(type(exc).__name__) from None
    audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    if len(audiences) > 1 and claims.get("azp") != config.client_id:
        raise ProviderError("azp")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ProviderError("nonce")
    return claims


def _truthy(value: Any) -> bool:
    return value is True or value in ("true", "1", 1)


def verified_email(config: IdentityProviderConfig, claims: dict) -> str | None:
    """The token's email when the provider vouches for it, lower-cased; else None.

    Microsoft Entra ID sends no `email_verified`, and its `email` is whatever an administrator typed, so for the
    Microsoft preset we accept the email only with the optional claim `xms_edov` (email domain owner verified)
    true, or an explicit `email_verified`. `preferred_username` and `upn` are never used: they are not verified.
    """
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        return None
    ok = _truthy(claims.get("email_verified"))
    if config.preset == "microsoft":
        ok = ok or _truthy(claims.get("xms_edov"))
    return email.strip().lower() if ok else None


def shows_mfa(claims: dict) -> bool:
    """Whether the token says a second factor was used. A provider that sends neither `amr` nor `acr` (Google,
    Microsoft by default) leaves it to the tenant's `asserts_mfa` flag; one that sends them must show a factor."""
    amr, acr = claims.get("amr"), claims.get("acr")
    if amr is None and acr is None:
        return True
    if isinstance(amr, list) and _MFA_AMR & {str(v) for v in amr}:
        return True
    return isinstance(acr, str) and acr in _MFA_ACR


# --- the round trip -------------------------------------------------------------------------------------------------


def list_sign_in_providers(session: Session) -> list[IdentityProviderConfig]:
    """The tenant's enabled staff providers, for the "Continue with" buttons (anonymous)."""
    stmt = select(IdentityProviderConfig).where(
        IdentityProviderConfig.audience == "staff", IdentityProviderConfig.is_enabled.is_(True)
    )
    return list(session.scalars(stmt.order_by(IdentityProviderConfig.display_name)))


def _enabled(session: Session, provider_id: UUID | str) -> IdentityProviderConfig | None:
    config = session.get(IdentityProviderConfig, UUID(str(provider_id)))
    return config if config is not None and config.is_enabled and config.audience == "staff" else None


def _need_pre_session(pre_session: str | None) -> str:
    if not pre_session:
        raise PermissionDenied("Start from the sign-in page in your browser.", code="csrf-failed")
    return pre_session


def _authorization_url(
    session: Session, config: IdentityProviderConfig, pre_session: str, payload: dict, *, step_up: bool = False,
    identity_id: UUID | None = None,
) -> str:  # fmt: skip
    try:
        doc = discover(config.issuer_url)
    except ProviderError:
        raise DomainError(
            "That sign-in provider is not answering. Try again later.", status=503, code="oidc-unavailable"
        ) from None
    now = clock.now()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    nonce = tokens.secret()
    state, hashed = tokens.mint(STATE_PREFIX, config.tenant_id)
    session.add(
        AuthToken(
            identity_id=identity_id, purpose=TokenPurpose.OIDC_STATE, token_hash=hashed, expires_at=now + _STATE_TTL,
            payload=payload | {
                "provider_id": str(config.id), "nonce": nonce, "verifier": crypto.encrypt(verifier, config.tenant_id),
                "pre_session": tokens.digest(pre_session), "started_at": now.timestamp(),
            },
        )
    )  # fmt: skip
    params = {
        "response_type": "code", "client_id": config.client_id, "redirect_uri": redirect_uri(),
        "scope": " ".join(config.scopes), "state": state, "nonce": nonce, "code_challenge": challenge,
        "code_challenge_method": "S256",
    }  # fmt: skip
    if step_up:
        params |= {"prompt": "login", "max_age": "0"}
    endpoint = doc["authorization_endpoint"]
    return f"{endpoint}{'&' if '?' in endpoint else '?'}{urlencode(params)}"


def start_sign_in(session: Session, *, provider_id: UUID, pre_session: str | None) -> str:
    config = _enabled(session, provider_id)
    if config is None:
        raise NotFound()
    return _authorization_url(session, config, _need_pre_session(pre_session), {"mode": "sign_in"})


def start_step_up(session: Session, principal: Principal, *, pre_session: str | None) -> str:
    """Re-authentication at the provider the caller is linked to (`prompt=login`, `max_age=0`), for a staff user
    who cannot confirm with a code or password. Ends in auth.rotate_for_step_up."""
    current = session.get(AuthSession, principal.session_id)
    issuers = select(ExternalLogin.issuer).where(ExternalLogin.identity_id == principal.identity_id)
    configs = session.scalars(
        select(IdentityProviderConfig)
        .where(IdentityProviderConfig.issuer_url.in_(issuers), IdentityProviderConfig.is_enabled.is_(True))
        .order_by(IdentityProviderConfig.display_name)
    ).all()
    if current is None or current.kind != "web" or principal.kind != "staff" or not configs:
        raise PermissionDenied("Your account is not linked to a sign-in provider.", code="oidc-step-up-unavailable")
    payload = {"mode": "step_up", "session_id": str(current.id)}
    return _authorization_url(
        session, configs[0], _need_pre_session(pre_session), payload, step_up=True, identity_id=principal.identity_id
    )


def _take_state(session: Session, state: str, pre_session: str | None) -> AuthToken:
    """The round trip's row, locked and consumed whatever happens next: a state works once."""
    row = session.execute(
        select(AuthToken)
        .where(AuthToken.token_hash == tokens.digest(state), AuthToken.purpose == TokenPurpose.OIDC_STATE)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None or row.expires_at <= clock.now():
        raise _failed(persist=False)
    row.consumed_at = clock.now()
    if not hmac.compare_digest(row.payload["pre_session"], tokens.digest(pre_session or "")):
        raise _failed()  # another browser: a forwarded callback link must not sign its reader in
    return row


def _exchange(config: IdentityProviderConfig, row: AuthToken, code: str) -> dict:
    doc = discover(config.issuer_url)
    answer = _fetch(
        "POST", doc["token_endpoint"],
        data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
            "client_id": config.client_id, "client_secret": crypto.decrypt(config.client_secret_encrypted, config.tenant_id),
            "code_verifier": crypto.decrypt(row.payload["verifier"], config.tenant_id),
        },
    )  # fmt: skip
    if not isinstance(answer.get("id_token"), str):
        raise ProviderError("no id_token")
    return verify_id_token(config, doc, answer["id_token"], row.payload["nonce"])


def _domain_allowed(config: IdentityProviderConfig, email: str | None) -> bool:
    return not config.allowed_email_domains or (
        email is not None and email.rsplit("@", 1)[1] in config.allowed_email_domains
    )


def _match(session: Session, config: IdentityProviderConfig, claims: dict) -> tuple[Identity, ExternalLogin | None]:
    """(identity, the new link to store or None). Within this tenant only: RLS scopes every lookup."""
    email = verified_email(config, claims)
    if not _domain_allowed(config, email):
        raise _refused()
    link = session.scalar(
        select(ExternalLogin).where(ExternalLogin.issuer == config.issuer_url, ExternalLogin.subject == claims["sub"])
    )
    new_link = None
    if link is not None:
        identity = session.get(Identity, link.identity_id)
    else:
        staff_with_email = select(Identity).where(
            Identity.kind == "staff", Identity.email == email, Identity.email_verified_at.is_not(None)
        )
        identity = session.scalar(staff_with_email) if email else None
        linked = identity and session.scalar(
            select(ExternalLogin.id).where(
                ExternalLogin.identity_id == identity.id, ExternalLogin.issuer == config.issuer_url
            )
        )
        if not identity or linked:  # linked: a different account at this provider already holds the link
            raise _refused()
        link = new_link = ExternalLogin(identity_id=identity.id, issuer=config.issuer_url, subject=claims["sub"])
    if identity is None or identity.kind != "staff" or identity.status != "active":
        raise _refused()
    if auth._principal_for(session, identity) is None:  # deactivated, or staff access expired
        raise _refused()
    link.last_used_at = clock.now()
    return identity, new_link


def complete(
    session: Session, *, state: str, code: str, pre_session: str | None, session_token: str | None
) -> auth.Grant | auth.Challenge:
    """The callback: check the round trip, exchange the code, verify the ID token, find the identity, then sign
    in (through the second-factor policy) or finish a step-up."""
    row = _take_state(session, state, pre_session)
    config = _enabled(session, row.payload["provider_id"])
    if config is None:
        raise _failed()
    try:
        claims = _exchange(config, row, code)
    except ProviderError:
        raise _failed() from None
    identity, new_link = _match(session, config, claims)
    mfa_ok = config.asserts_mfa and shows_mfa(claims)
    if row.payload["mode"] == "step_up":
        return _finish_step_up(session, row, identity, claims, mfa_ok, session_token, new_link)
    if auth._refused_before_password(session, "staff", identity):
        raise auth._ip_not_allowed()
    _store_link(session, identity, new_link)
    if mfa_ok:  # the tenant trusts this provider's MFA and the token does not contradict it
        grant = auth._start_session(session, identity, "web", mfa_verified_at=clock.now())
    elif challenge := auth._second_factor(session, identity, "web", "oidc"):
        return challenge
    else:
        grant = auth._start_session(session, identity, "web")
    audit.record(session, "platform.identity.sign_in", identity, actor=grant.principal, reason="oidc")
    return grant


def _store_link(session: Session, identity: Identity, link: ExternalLogin | None) -> None:
    if link is None:
        return
    session.add(link)
    session.flush()
    audit.record(
        session, "platform.identity.oidc_link", identity, actor=auth._actor(identity), changes={"issuer": link.issuer}
    )


def _finish_step_up(
    session: Session, row: AuthToken, identity: Identity, claims: dict, mfa_ok: bool, session_token: str | None,
    new_link: ExternalLogin | None,
) -> auth.Grant:  # fmt: skip
    """The provider must have re-checked the user just now (`auth_time` after the round trip began), the account
    must be the signed-in user's own, and a user who has (or must have) a second factor needs it asserted."""
    try:
        principal = auth.authenticate(session, session_token or "")
    except Unauthenticated:
        raise _failed() from None
    current = session.get(AuthSession, principal.session_id)
    if current is None or str(current.id) != row.payload["session_id"]:
        raise _failed()
    if principal.identity_id != identity.id or new_link is not None:
        raise _failed()
    auth_time = claims.get("auth_time")
    if not isinstance(auth_time, int | float) or auth_time < row.payload["started_at"] - _LEEWAY_SEC:
        raise PermissionDenied(
            "The provider did not ask you to sign in again. Try once more, or confirm another way.",
            code="oidc-reauthentication-stale", persist=True,
        )  # fmt: skip
    if not mfa_ok and (mfa.confirmed_factor(session, identity.id) or mfa.is_required(session, identity)):
        raise PermissionDenied("Confirm with your authenticator code instead.", code="step-up-needs-code", persist=True)
    return auth.rotate_for_step_up(session, identity, current, mfa_verified=mfa_ok, reason="oidc")


# --- provider configuration (Security settings; platform.security.manage, a `+` key) ---------------------------------


def provider_view(config: IdentityProviderConfig) -> dict:
    """What the API shows: never the secret, only that one is set."""
    return {
        "id": config.id, "preset": config.preset, "display_name": config.display_name, "issuer_url": config.issuer_url,
        "client_id": config.client_id, "has_client_secret": bool(config.client_secret_encrypted),
        "scopes": config.scopes, "allowed_email_domains": config.allowed_email_domains,
        "asserts_mfa": config.asserts_mfa, "is_enabled": config.is_enabled, "redirect_uri": redirect_uri(),
        "created_at": config.created_at, "updated_at": config.updated_at,
    }  # fmt: skip


def list_providers(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "platform.security.manage")
    page = paginate(
        session, select(IdentityProviderConfig), query, id_column=IdentityProviderConfig.id,
        sort_fields={"display_name": IdentityProviderConfig.display_name, "created_at": IdentityProviderConfig.created_at},
        default_sort="display_name",
    )  # fmt: skip
    return page | {"data": [provider_view(c) for c in page["data"]]}


def _load(session: Session, provider_id: UUID) -> IdentityProviderConfig:
    config = session.get(IdentityProviderConfig, provider_id)
    if config is None:
        raise NotFound()
    return config


def get_provider(session: Session, principal: Principal, provider_id: UUID) -> dict:
    authorize(principal, "platform.security.manage")
    return provider_view(_load(session, provider_id))


def _check_issuer(preset: str, issuer: str) -> None:
    if preset == "google" and issuer != GOOGLE_ISSUER:
        raise ValidationFailed(
            f"Google's issuer is {GOOGLE_ISSUER}.", code="oidc-issuer-invalid", pointer="/issuer_url"
        )
    if preset == "microsoft" and not _MICROSOFT_ISSUER.fullmatch(issuer):
        raise ValidationFailed(
            "Use https://login.microsoftonline.com/<directory (tenant) ID>/v2.0 with your directory's ID.",
            code="oidc-issuer-invalid", pointer="/issuer_url",
        )  # fmt: skip
    try:
        discover(issuer)
    except UnsafeUrl as exc:
        raise ValidationFailed(
            f"That issuer is not allowed: {exc}.", code="url-not-allowed", pointer="/issuer_url"
        ) from None
    except ProviderError:
        raise ValidationFailed(
            "No OpenID Connect discovery document for that issuer, or its issuer does not match.",
            code="oidc-discovery-failed", pointer="/issuer_url",
        ) from None  # fmt: skip


def _domains(values: list[str]) -> list[str]:
    out = sorted({v.strip().lower().lstrip("@") for v in values if v.strip()})
    for index, value in enumerate(out):
        if not _DOMAIN.fullmatch(value):
            raise ValidationFailed("Give domains like example.com.", pointer=f"/allowed_email_domains/{index}")
    return out


def _scopes(values: list[str]) -> list[str]:
    out = list(dict.fromkeys(v.strip() for v in values if v.strip()))
    if "openid" not in out or "email" not in out or not all(_SCOPE.fullmatch(v) for v in out):
        raise ValidationFailed("Scopes must include openid and email.", pointer="/scopes")
    return out


def _apply(session: Session, config: IdentityProviderConfig, data: dict) -> None:
    for key in ("display_name", "client_id", "asserts_mfa", "is_enabled"):
        if data.get(key) is not None:
            setattr(config, key, data[key])
    if data.get("allowed_email_domains") is not None:
        config.allowed_email_domains = _domains(data["allowed_email_domains"])
    if data.get("scopes") is not None:
        config.scopes = _scopes(data["scopes"])
    if data.get("client_secret"):
        config.client_secret_encrypted = crypto.encrypt(data["client_secret"], session.info["tenant_id"])


def create_provider(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, "platform.security.manage")
    preset = data["preset"]
    issuer = data.get("issuer_url") or (GOOGLE_ISSUER if preset == "google" else "")
    _check_issuer(preset, issuer)
    taken = session.scalar(select(IdentityProviderConfig.id).where(IdentityProviderConfig.issuer_url == issuer))
    if taken:
        raise ValidationFailed("A provider with that issuer exists.", code="already-exists", pointer="/issuer_url")
    config = IdentityProviderConfig(preset=preset, issuer_url=issuer, client_secret_encrypted="")
    _apply(session, config, data | {"scopes": data.get("scopes") or ["openid", "email", "profile"]})
    session.add(config)
    session.flush()
    audit.record(session, "platform.identity_provider.create", config, changes=_values(config))
    return provider_view(config)


def _values(config: IdentityProviderConfig) -> dict:
    # Configuration, not personal data: audited as values. The secret never; the name as a flag (free text).
    return {
        "preset": config.preset, "issuer_url": config.issuer_url, "client_id": config.client_id,
        "asserts_mfa": config.asserts_mfa, "is_enabled": config.is_enabled,
        "allowed_email_domains": config.allowed_email_domains, "scopes": config.scopes,
    }  # fmt: skip


def update_provider(session: Session, principal: Principal, provider_id: UUID, data: dict) -> dict:
    authorize(principal, "platform.security.manage")
    config = _load(session, provider_id)
    before = _values(config)
    secret_before = config.client_secret_encrypted
    _apply(session, config, data)
    after = _values(config)
    changes: dict[str, Any] = {k: [before[k], after[k]] for k in after if before[k] != after[k]}
    if config.client_secret_encrypted != secret_before:
        changes["client_secret"] = "changed"  # a flag, never the value
    if "display_name" in data and data["display_name"] is not None:
        changes["display_name"] = "changed"
    session.flush()
    if changes:
        audit.record(session, "platform.identity_provider.update", config, changes=changes)
    return provider_view(config)


def delete_provider(session: Session, principal: Principal, provider_id: UUID) -> None:
    """Links stay: they are keyed by issuer, so adding the provider back restores them."""
    authorize(principal, "platform.security.manage")
    config = _load(session, provider_id)
    audit.record(session, "platform.identity_provider.delete", config, changes=_values(config))
    session.execute(delete(IdentityProviderConfig).where(IdentityProviderConfig.id == config.id))
