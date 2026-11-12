"""platform HTTP surface. Routers validate, call one service function and shape the response; they never
build error bodies or open transactions (TxRoute and the auth dependencies do)."""

import secrets
from functools import cache
from pathlib import Path
from typing import Annotated
from uuid import UUID

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.api import TxRoute
from app.core.api import camel_id as _camel
from app.core.auth import CATALOGUE, tokens
from app.core.auth.deps import (
    Ctx,
    cookie_parts,
    current_ctx,
    pre_session_cookie,
    pre_session_csrf,
    public_session,
    request_session,
    require,
    session_cookie,
)
from app.core.db.platform import platform_engine
from app.core.db.session import app_engine
from app.core.errors import NotFound, Unauthenticated, ValidationFailed
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import _redis, hit, rate_limit
from app.core.settings import get_settings
from app.modules.platform import auth, service, staff
from app.modules.platform import schemas as s

API_PREFIX = "/api/v1"
_OUTBOX_LAG_SLO_SEC = 300


def _router(**kwargs) -> APIRouter:
    return APIRouter(route_class=TxRoute, tags=["platform"], generate_unique_id_function=_camel, **kwargs)


public = _router()  # anonymous: tenant from host or token prefix
me = _router()  # any signed-in principal acting on itself
admin = _router(dependencies=[Depends(idempotency)])  # staff sessions; POSTs honour Idempotency-Key
operator = APIRouter(tags=["operator"], generate_unique_id_function=_camel)

Lists = Annotated[ListQuery, Depends(list_query)]
Authenticated = Annotated[Ctx, Depends(require())]
PublicSession = Annotated[Session, Depends(public_session)]


# --- health (no tenant, no transaction) --------------------------------------------------------------------


@cache
def _migration_head() -> str:
    return ScriptDirectory(str(Path(__file__).resolve().parents[3] / "migrations")).get_current_head()


@public.get("/health/live", response_model=s.HealthStatus, response_model_exclude_none=True)
def get_liveness():
    """Process liveness; no dependencies checked."""
    return {"status": "ok"}


@public.get("/health/ready", response_model=s.HealthStatus, responses={503: {"model": s.HealthStatus}})
def get_readiness(response: Response):
    """PostgreSQL, Redis and migration head must be right (503 otherwise). A lagging outbox relay reports
    `degraded` with 200 so a development stack without the relay still serves."""
    checks: dict[str, str] = {}

    def check(name: str, probe) -> None:
        try:
            checks[name] = "ok" if probe() else "failed"
        except Exception:
            checks[name] = "failed"

    def migrations() -> bool:
        with app_engine().connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == _migration_head()

    def relay() -> bool:
        with platform_engine().connect() as conn:
            lag = conn.execute(
                text("SELECT extract(epoch FROM now() - min(occurred_at)) FROM outbox_event WHERE published_at IS NULL")
            ).scalar()
        return lag is None or lag < _OUTBOX_LAG_SLO_SEC

    check("postgres", lambda: app_engine().connect().close() is None)
    check("migrations", migrations)
    check("redis", lambda: _redis().ping())
    check("outbox_relay", relay)
    if any(checks[name] != "ok" for name in ("postgres", "migrations", "redis")):
        response.status_code = 503
        return {"status": "unavailable", "checks": checks}
    return {"status": "ok" if checks["outbox_relay"] == "ok" else "degraded", "checks": checks}


# --- auth: anonymous ---------------------------------------------------------------------------------------


def _session_body(row, principal) -> dict:
    return {
        "id": row.id, "kind": row.kind, "principal": principal, "access_expires_at": row.access_expires_at,
        "idle_expires_at": row.idle_expires_at, "absolute_expires_at": row.absolute_expires_at,
        "mfa_verified_at": row.mfa_verified_at, "elevated_until_at": row.elevated_until_at,
    }  # fmt: skip


def _cookie_flags() -> dict:
    # Path=/; Secure; HttpOnly; SameSite=Lax and nothing else: no Domain, no Max-Age (security-baseline 5.2).
    return {"path": "/", "httponly": True, "secure": get_settings().auth.cookie_secure, "samesite": "lax"}


def _session_out(grant: auth.Grant, response: Response) -> dict:
    """Bearer clients get the tokens in the body; web gets the one HttpOnly session cookie and a CSRF token.
    The cookie carries the CSRF token too, because the database keeps only its hash and GET /auth/session
    must be able to hand it to a freshly loaded page."""
    out = _session_body(grant.auth_session, grant.principal) | {"recovery_codes": grant.recovery_codes}
    if grant.auth_session.kind == "mobile":
        return out | {"access_token": grant.access_token, "refresh_token": grant.refresh_token}
    response.set_cookie(session_cookie(), f"{grant.access_token}.{grant.csrf_token}", **_cookie_flags())
    return out | {"csrf_token": grant.csrf_token}


def _token_session(request: Request, token: str | None, prefix: str, code: str) -> Session:
    """Consume endpoints find their tenant in the token prefix (an address, not a credential)."""
    tenant_id = tokens.tenant_of(token, prefix)
    if tenant_id is None:
        raise Unauthenticated("This link or token is not valid.", code=code)
    return request_session(request, tenant_id)


_session_route = {"response_model": s.AuthSessionOut, "response_model_exclude_none": True}
# Sign-in routes answer 202 with a pending MFA challenge when a second factor (or forced enrolment) comes next.
_sign_in_route = {
    "response_model": s.AuthSessionOut | s.MfaChallengeOut, "response_model_exclude_none": True,
    "responses": {202: {"model": s.MfaChallengeOut}},
}  # fmt: skip


def _sign_in_out(result: auth.Grant | auth.Challenge, response: Response) -> dict:
    if isinstance(result, auth.Challenge):
        response.status_code = 202
        return {
            "mfa_token": result.token, "expires_at": result.expires_at,
            "enrolment_required": result.enrolment_required,
        }  # fmt: skip
    return _session_out(result, response)


def _guarded(bucket: str) -> list:
    """Anonymous auth POSTs: the per-IP bucket, then the login-CSRF check for browsers (baseline 5.3 item 4)."""
    return [Depends(rate_limit(bucket)), Depends(pre_session_csrf)]


def _per_address(session: Session, bucket: str, body, response: Response) -> None:
    """The per-identity or per-target-address bucket beside the per-IP one (baseline 6). Keyed by the address
    asked for, whether or not it exists, so the limit itself reveals nothing."""
    hit(bucket, f"{body.audience}:{body.email}", response, tenant=session.info["tenant_id"])


@public.get("/auth/pre-session", response_model=s.PreSessionOut)
def get_pre_session(request: Request, response: Response):
    """Start the login-CSRF pair for a browser: an HttpOnly pre-session cookie, and the same token in the body
    to send as X-CSRF-Token on sign-in, emailed-link, reset and link-consume requests. Reuses a live cookie,
    so several tabs share one token."""
    token = request.cookies.get(pre_session_cookie(), "")
    if len(token) != 43:  # tokens.secret(): 32 bytes, url-safe base64
        token = tokens.secret()
    flags = _cookie_flags() | {"max_age": get_settings().auth.pre_session_ttl_min * 60}
    response.set_cookie(pre_session_cookie(), token, **flags)
    return {"csrf_token": token}


@public.post("/auth/sign-in", dependencies=_guarded("sign-in"), **_sign_in_route)
def sign_in(body: s.SignInRequest, response: Response, session: PublicSession):
    """Sign in with email and password. 202 with an MFA challenge when a second factor comes next. Errors:
    invalid-credentials, identity-locked, ip-not-allowed, csrf-failed, rate-limited."""
    _per_address(session, "sign-in-identity", body, response)
    return _sign_in_out(auth.sign_in(session, **body.model_dump()), response)


@public.post("/auth/magic-links", status_code=202, dependencies=_guarded("magic-link"))
def request_magic_link(body: s.EmailLinkRequest, response: Response, session: PublicSession) -> None:
    """Email a single-use 15-minute sign-in link. Always 202, whether or not the address exists."""
    _per_address(session, "link-address", body, response)
    auth.request_magic_link(session, **body.model_dump())


@public.post("/auth/magic-links/consume", dependencies=_guarded("consume"), **_sign_in_route)
def consume_magic_link(body: s.TokenConsumeRequest, request: Request, response: Response):
    """Exchange a magic-link token for a session. Errors: token-invalid, token-expired."""
    session = _token_session(request, body.token, "fhl", "token-invalid")
    return _sign_in_out(auth.consume_magic_link(session, token=body.token, client_kind=body.client_kind), response)


@public.post("/auth/password-resets", status_code=202, dependencies=_guarded("reset-request"))
def request_password_reset(body: s.EmailLinkRequest, response: Response, session: PublicSession) -> None:
    """Email a single-use 60-minute reset link. Always 202."""
    _per_address(session, "link-address", body, response)
    auth.request_password_reset(session, email=body.email, audience=body.audience)


@public.post("/auth/password-resets/consume", dependencies=_guarded("consume"), **_sign_in_route)
def consume_password_reset(body: s.TokenConsumeRequest, request: Request, response: Response):
    """Set a new password; revokes every other session. Errors: token-invalid, token-expired, password-too-weak."""
    if not body.new_password:
        raise ValidationFailed("new_password is required.", pointer="/new_password")
    session = _token_session(request, body.token, "fhl", "token-invalid")
    grant = auth.consume_password_reset(
        session, token=body.token, new_password=body.new_password, client_kind=body.client_kind
    )
    return _sign_in_out(grant, response)


@public.post("/auth/invitations/accept", dependencies=_guarded("consume"), **_sign_in_route)
def accept_invitation(body: s.TokenConsumeRequest, request: Request, response: Response):
    """Accept an invite and activate the identity; the password is optional (magic link remains available)."""
    session = _token_session(request, body.token, "fhl", "token-invalid")
    return _sign_in_out(auth.accept_invitation(session, **body.model_dump()), response)


@public.post("/auth/mfa/enrolment", dependencies=_guarded("mfa"), response_model=s.MfaEnrolmentOut)
def start_mfa_challenge_enrolment(body: s.MfaChallengeToken, request: Request):
    """Forced enrolment inside a pending sign-in: a new TOTP secret as an otpauth URI (render the QR on the
    device). Only after an emailed link: a password-only sign-in gets a sign-in link by email instead. Errors:
    mfa-challenge-invalid, mfa-already-enrolled, mfa-enrolment-needs-email-link."""
    session = _token_session(request, body.mfa_token, "fhm", "mfa-challenge-invalid")
    secret, uri = auth.start_challenge_enrolment(session, token=body.mfa_token)
    return {"secret": secret, "otpauth_uri": uri}


@public.post("/auth/mfa/verify", dependencies=_guarded("mfa"), **_session_route)
def verify_mfa_challenge(body: s.MfaChallengeCode, request: Request, response: Response):
    """Complete a pending sign-in with a TOTP code or a recovery code (consumed); for a forced enrolment, the
    first code of the new factor, and the response carries the ten recovery codes once. Errors:
    mfa-challenge-invalid, mfa-code-invalid, mfa-enrolment-not-started, mfa-enrolment-needs-email-link, mfa-locked,
    rate-limited."""
    session = _token_session(request, body.mfa_token, "fhm", "mfa-challenge-invalid")
    hit("mfa-challenge", body.mfa_token, response, tenant=session.info["tenant_id"])
    return _session_out(auth.complete_challenge(session, token=body.mfa_token, code=body.code), response)


@public.post("/auth/refresh", dependencies=[Depends(rate_limit("refresh"))], **_session_route)
def refresh_session(request: Request, response: Response, body: s.RefreshRequest | None = None):
    """Rotate a mobile token pair (web sessions have no refresh token: their cookie slides on use).
    Errors: session-revoked, refresh-reuse-detected."""
    token = body.refresh_token if body else None
    session = _token_session(request, token, "fhr", "session-revoked")
    return _session_out(auth.refresh(session, refresh_token=token), response)


# --- auth: self --------------------------------------------------------------------------------------------


@me.post("/auth/sign-out", status_code=204)
def sign_out(response: Response, ctx: Ctx = Depends(current_ctx)) -> None:
    """Revoke the current session."""
    auth.sign_out(ctx.session, ctx.principal)
    response.delete_cookie(session_cookie(), **_cookie_flags())


@me.get("/auth/session", **_session_route)
def get_current_session(request: Request, ctx: Ctx = Depends(current_ctx)):
    """The current session. For cookie sessions this is where the web app reads its CSRF token."""
    out = _session_body(auth.get_session(ctx.session, ctx.principal), ctx.principal)
    csrf = cookie_parts(request)[1]
    if csrf and "authorization" not in request.headers:
        out["csrf_token"] = csrf
    return out


@me.get("/auth/sessions", response_model=list[s.OwnSession])
def list_own_sessions(ctx: Ctx = Depends(current_ctx)):
    """The caller's live sessions."""
    rows = auth.list_sessions(ctx.session, ctx.principal)
    return [
        s.OwnSession.model_validate(row).model_copy(update={"is_current": row.id == ctx.principal.session_id})
        for row in rows
    ]


@me.delete("/auth/sessions/{session_id}", status_code=204)
def revoke_own_session(session_id: UUID, ctx: Ctx = Depends(current_ctx)) -> None:
    """Sign one of the caller's sessions out."""
    auth.revoke_session(ctx.session, ctx.principal, session_id)


@me.post("/auth/password", status_code=204)
def change_own_password(body: s.PasswordChange, ctx: Ctx = Depends(current_ctx)) -> None:
    """Change the caller's password; other sessions are revoked. A first password needs a magic-link session
    from the last 15 minutes. Errors: invalid-credentials, password-too-weak, password-reset-required."""
    auth.change_password(ctx.session, ctx.principal, **body.model_dump())


@me.post("/auth/step-up", dependencies=[Depends(rate_limit("step-up"))], **_session_route)
def step_up(body: s.StepUpRequest, response: Response, ctx: Ctx = Depends(current_ctx)):
    """Re-authenticate (TOTP or recovery code when enrolled, else password) so `+` permissions work for 10
    minutes. The session rotates: new cookie and CSRF token (web) or token pair (mobile). Errors:
    reauthentication-failed, identity-locked, mfa-locked, mfa-enrolment-required, step-up-unavailable, rate-limited."""
    hit("step-up-identity", str(ctx.principal.identity_id), response, tenant=ctx.principal.tenant_id)
    return _session_out(auth.step_up(ctx.session, ctx.principal, **body.model_dump()), response)


@me.get("/me/mfa", response_model=s.MfaStatus)
def get_own_mfa(ctx: Ctx = Depends(current_ctx)):
    """Whether two-step verification is on for the caller, and whether their role requires it."""
    return auth.mfa_status(ctx.session, ctx.principal)


@me.post("/me/mfa/totp", response_model=s.MfaEnrolmentOut)
def start_own_mfa_enrolment(ctx: Ctx = Depends(current_ctx)):
    """Start TOTP enrolment (needs step-up): the secret as an otpauth URI. Errors: step-up-required,
    mfa-already-enrolled."""
    secret, uri = auth.begin_mfa_enrolment(ctx.session, ctx.principal)
    return {"secret": secret, "otpauth_uri": uri}


@me.post("/me/mfa/totp/confirm", response_model=s.MfaRecoveryCodesOut)
def confirm_own_mfa_enrolment(body: s.MfaCode, ctx: Ctx = Depends(current_ctx)):
    """Turn TOTP on with the first code; returns ten single-use recovery codes, shown once. Other sessions are
    signed out. Errors: mfa-code-invalid, mfa-enrolment-not-started."""
    return {"recovery_codes": auth.confirm_mfa_enrolment(ctx.session, ctx.principal, body.code)}


@me.delete("/me/mfa/totp", status_code=204)
def disable_own_mfa(ctx: Ctx = Depends(current_ctx)) -> None:
    """Turn two-step verification off (needs step-up; refused when the caller's role requires it). Errors:
    step-up-required, mfa-required."""
    auth.disable_mfa(ctx.session, ctx.principal)


@me.post("/me/mfa/recovery-codes", response_model=s.MfaRecoveryCodesOut)
def regenerate_own_recovery_codes(ctx: Ctx = Depends(current_ctx)):
    """Replace every recovery code with ten new ones (needs step-up), shown once."""
    return {"recovery_codes": auth.regenerate_recovery_codes(ctx.session, ctx.principal)}


@me.get("/me", response_model=s.Me)
def get_me(ctx: Ctx = Depends(current_ctx)):
    """Principal, tenant, role, effective permissions and locations: what the web app routes by."""
    return service.get_me(ctx.session, ctx.principal)


# --- tenant ------------------------------------------------------------------------------------------------


@admin.get("/tenant", response_model=s.TenantOut)
def get_tenant(ctx: Authenticated):
    return service.get_tenant(ctx.session)


@admin.patch("/tenant", response_model=s.TenantOut)
def update_tenant(body: s.TenantUpdate, ctx: Ctx = Depends(require("platform.tenant.update"))):
    return service.update_tenant(ctx.session, ctx.principal, body.model_dump(exclude_unset=True))


# --- security settings -------------------------------------------------------------------------------------


@admin.get("/security-settings", response_model=s.SecuritySettings)
def get_security_settings(ctx: Ctx = Depends(require("platform.security.manage"))):
    """Tenant security policy: the staff IP allow-list (PLT-07)."""
    return service.get_security_settings(ctx.session, ctx.principal)


@admin.patch("/security-settings", response_model=s.SecuritySettings)
def update_security_settings(body: s.SecuritySettingsUpdate, ctx: Ctx = Depends(require("platform.security.manage"))):
    """Replace the staff IP allow-list; empty lifts the restriction. A list that leaves out the caller's own
    address is refused. Errors: ip-allowlist-excludes-you, validation-failed."""
    return service.update_security_settings(ctx.session, ctx.principal, body.model_dump(exclude_unset=True))


# --- locations ---------------------------------------------------------------------------------------------


@admin.get("/locations", response_model=s.Page[s.LocationOut])
def list_locations(ctx: Authenticated, query: Lists):
    """Locations the caller may act in. Filters: status. Sort: name, sort_order, created_at."""
    return service.list_locations(ctx.session, ctx.principal, query)


@admin.post("/locations", response_model=s.LocationOut, status_code=201)
def create_location(body: s.LocationCreate, ctx: Ctx = Depends(require("platform.location.create"))):
    """Create a location with its seven facility-hours rows. Errors: already-exists."""
    return service.create_location(ctx.session, ctx.principal, body.model_dump(exclude_unset=True))


@admin.get("/locations/{location_id}", response_model=s.LocationOut)
def get_location(location_id: UUID, ctx: Authenticated):
    return service.get_location(ctx.session, ctx.principal, location_id)


@admin.patch("/locations/{location_id}", response_model=s.LocationOut)
def update_location(location_id: UUID, body: s.LocationUpdate, ctx: Ctx = Depends(require("platform.location.update"))):
    return service.update_location(ctx.session, ctx.principal, location_id, body.model_dump(exclude_unset=True))


@admin.post("/locations/{location_id}/archive", response_model=s.LocationOut)
def archive_location(location_id: UUID, ctx: Ctx = Depends(require("platform.location.archive"))):
    """Set a location inactive. Errors: invalid-state-transition."""
    return service.archive_location(ctx.session, ctx.principal, location_id)


@admin.get("/locations/{location_id}/facility-hours", response_model=s.FacilityHoursOut)
def get_facility_hours(location_id: UUID, ctx: Authenticated):
    return service.get_facility_hours(ctx.session, ctx.principal, location_id)


@admin.put("/locations/{location_id}/facility-hours", response_model=s.FacilityHoursOut)
def replace_facility_hours(
    location_id: UUID, body: s.FacilityHoursReplace, ctx: Ctx = Depends(require("platform.location.update"))
):
    """Replace the whole week (one entry per ISO weekday). closes_time 24:00 is a midnight close."""
    return service.replace_facility_hours(ctx.session, ctx.principal, location_id, body.model_dump()["days"])


@public.get("/public/locations", response_model=s.Page[s.PublicLocation])
def list_public_locations(session: PublicSession, query: Lists):
    """Public location directory of the tenant resolved from the host."""
    return service.list_public_locations(session, query)


# --- staff users -------------------------------------------------------------------------------------------


@admin.get("/staff-users", response_model=s.Page[s.StaffUserOut])
def list_staff_users(query: Lists, ctx: Ctx = Depends(require("platform.staff_user.read"))):
    """Filters: role_id, is_active, identity_status, location_id; q searches name and email.
    Sort: last_name, first_name, email, created_at."""
    return staff.list_staff_users(ctx.session, ctx.principal, query)


@admin.post("/staff-users", response_model=s.StaffUserOut, status_code=201)
def invite_staff_user(body: s.StaffUserInvite, ctx: Ctx = Depends(require("platform.staff_user.invite"))):
    """Create a staff user and email the invite link. Errors: already-exists, self-escalation."""
    return staff.invite_staff_user(ctx.session, ctx.principal, body.model_dump())


@admin.get("/staff-users/{staff_user_id}", response_model=s.StaffUserOut)
def get_staff_user(staff_user_id: UUID, ctx: Ctx = Depends(require("platform.staff_user.read"))):
    return staff.get_staff_user(ctx.session, ctx.principal, staff_user_id)


@admin.patch("/staff-users/{staff_user_id}", response_model=s.StaffUserOut)
def update_staff_user(
    staff_user_id: UUID, body: s.StaffUserUpdate, ctx: Ctx = Depends(require("platform.staff_user.update"))
):
    return staff.update_staff_user(ctx.session, ctx.principal, staff_user_id, body.model_dump(exclude_unset=True))


@admin.post("/staff-users/{staff_user_id}/deactivate", response_model=s.StaffUserOut)
def deactivate_staff_user(staff_user_id: UUID, ctx: Ctx = Depends(require("platform.staff_user.deactivate"))):
    """Deactivate and sign out everywhere, immediately. Errors: last-owner."""
    return staff.deactivate_staff_user(ctx.session, ctx.principal, staff_user_id)


@admin.post("/staff-users/{staff_user_id}/reactivate", response_model=s.StaffUserOut)
def reactivate_staff_user(staff_user_id: UUID, ctx: Ctx = Depends(require("platform.staff_user.deactivate"))):
    return staff.reactivate_staff_user(ctx.session, ctx.principal, staff_user_id)


@admin.post("/staff-users/{staff_user_id}/invitation/resend", status_code=202)
def resend_staff_invitation(staff_user_id: UUID, ctx: Ctx = Depends(require("platform.staff_user.invite"))) -> None:
    """Errors: invalid-state-transition when the invitation was already accepted."""
    staff.resend_invitation(ctx.session, ctx.principal, staff_user_id)


@admin.post("/staff-users/{staff_user_id}/credential-reset", status_code=202)
def reset_staff_credentials(
    staff_user_id: UUID, ctx: Ctx = Depends(require("platform.staff_user.reset_credentials"))
) -> None:
    """Send a reset link (never a temporary password) and revoke the user's sessions."""
    staff.reset_credentials(ctx.session, ctx.principal, staff_user_id)


@admin.put("/staff-users/{staff_user_id}/role", response_model=s.StaffUserOut)
def assign_staff_role(
    staff_user_id: UUID, body: s.StaffUserRoleAssign, ctx: Ctx = Depends(require("platform.staff_user.assign_role"))
):
    """Assign the user's single role. Errors: last-owner, self-escalation."""
    return staff.assign_role(
        ctx.session, ctx.principal, staff_user_id, body.role_id, reset_overrides=body.reset_overrides
    )


@admin.put("/staff-users/{staff_user_id}/locations", response_model=s.StaffUserOut)
def assign_staff_locations(
    staff_user_id: UUID,
    body: s.StaffUserLocationsAssign,
    ctx: Ctx = Depends(require("platform.staff_user.assign_locations")),
):
    return staff.assign_locations(ctx.session, ctx.principal, staff_user_id, body.model_dump())


@admin.get("/staff-users/{staff_user_id}/permissions", response_model=s.StaffUserPermissions)
def get_staff_user_permissions(staff_user_id: UUID, ctx: Ctx = Depends(require("platform.staff_user.read"))):
    return staff.get_permissions(ctx.session, ctx.principal, staff_user_id)


@admin.put("/staff-users/{staff_user_id}/permission-overrides", response_model=s.StaffUserPermissions)
def replace_staff_permission_overrides(
    staff_user_id: UUID,
    body: s.PermissionGrantsReplace,
    ctx: Ctx = Depends(require("platform.staff_user.override_permissions")),
):
    """Replace the user's whole override set. Errors: self-escalation, unknown-permission."""
    return staff.replace_permission_overrides(ctx.session, ctx.principal, staff_user_id, body.model_dump()["grants"])


@admin.post("/staff-users/{staff_user_id}/permissions/reset", response_model=s.StaffUserPermissions)
def reset_staff_permissions(
    staff_user_id: UUID, ctx: Ctx = Depends(require("platform.staff_user.override_permissions"))
):
    """Reset to role: delete every override."""
    return staff.reset_permissions(ctx.session, ctx.principal, staff_user_id)


# --- roles and the permission catalogue ---------------------------------------------------------------------


@admin.get("/permissions", response_model=s.Page[s.PermissionDefinition])
def list_permission_catalogue(context: str | None = None, ctx: Ctx = Depends(require("platform.role.read"))):
    """The static catalogue declared in code. It is small, so it comes back as a single page."""
    rows = [p for p in CATALOGUE.values() if context in (None, p.context)]
    return {"data": rows, "page": {"next_cursor": None, "has_more": False, "total": len(rows)}}


@admin.get("/roles", response_model=s.Page[s.RoleOut])
def list_roles(query: Lists, ctx: Ctx = Depends(require("platform.role.read"))):
    return staff.list_roles(ctx.session, ctx.principal, query)


@admin.post("/roles", response_model=s.RoleOut, status_code=201)
def create_role(body: s.RoleCreate, ctx: Ctx = Depends(require("platform.role.manage"))):
    """Create a custom role, optionally cloning another. Errors: already-exists, self-escalation."""
    return staff.create_role(ctx.session, ctx.principal, body.model_dump())


@admin.get("/roles/{role_id}", response_model=s.RoleOut)
def get_role(role_id: UUID, ctx: Ctx = Depends(require("platform.role.read"))):
    return staff.get_role(ctx.session, ctx.principal, role_id)


@admin.patch("/roles/{role_id}", response_model=s.RoleOut)
def update_role(role_id: UUID, body: s.RoleUpdate, ctx: Ctx = Depends(require("platform.role.manage"))):
    """Errors: system-role-immutable, already-exists."""
    return staff.update_role(ctx.session, ctx.principal, role_id, body.model_dump(exclude_unset=True))


@admin.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: UUID, ctx: Ctx = Depends(require("platform.role.manage"))) -> None:
    """Errors: system-role-immutable, role-in-use."""
    staff.delete_role(ctx.session, ctx.principal, role_id)


@admin.put("/roles/{role_id}/permissions", response_model=s.RoleOut)
def replace_role_permissions(
    role_id: UUID, body: s.PermissionGrantsReplace, ctx: Ctx = Depends(require("platform.role.manage"))
):
    """Replace the role's whole grant set. Errors: system-role-immutable, unknown-permission, self-escalation."""
    return staff.replace_role_permissions(ctx.session, ctx.principal, role_id, body.model_dump()["grants"])


# --- audit -------------------------------------------------------------------------------------------------


@admin.get("/audit-events", response_model=s.Page[s.AuditEventOut])
def list_audit_events(query: Lists, ctx: Ctx = Depends(require("platform.audit.read"))):
    """Staff activity trail, newest first. Filters: actor_id, actor_type, action, entity_type, entity_id,
    location_id, occurred_at[gte|lt|...]."""
    return service.list_audit_events(ctx.session, ctx.principal, query)


# --- operator: tenant onboarding ----------------------------------------------------------------------------


@operator.post("/operator/tenants", response_model=s.TenantOnboarded, status_code=201)
def onboard_tenant(body: s.TenantOnboard, x_operator_token: str = Header("")):
    """Create a tenant and its first Owner. Guarded by the FH_OPERATOR_TOKEN secret; absent when unset."""
    expected = get_settings().operator_token
    if not expected or not secrets.compare_digest(x_operator_token.encode(), expected.encode()):
        raise NotFound()
    return service.onboard_tenant(**body.model_dump())


router = APIRouter()
for part in (public, me, admin, operator):
    router.include_router(part)
