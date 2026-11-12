"""Sign-in, emailed links and server-side sessions (ADR 0002 sections 3 and 4)."""

import hmac
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import audit, clock, context, events, networks
from app.core.auth import Principal, passwords, tokens
from app.core.auth.permissions import require_elevated
from app.core.errors import NotFound, PermissionDenied, Unauthenticated, ValidationFailed
from app.core.settings import get_settings
from app.modules.platform import mfa, rbac
from app.modules.platform.events import IdentityLocked
from app.modules.platform.models import AuthSession, AuthToken, Identity, StaffUser, Tenant, TokenPurpose
from app.ports import notifications
from app.ports.email import EmailMessage, send_after_commit

notifications.register_template(
    "platform.identity_locked",
    subject="$app: sign-in paused after failed attempts",
    body=(
        "There were too many wrong passwords for your account, so password sign-in is paused for $minutes minutes.\n\n"
        "You can still sign in with an emailed link. If these attempts were not you, reset your password."
    ),
)
notifications.register_template(
    "platform.mfa_locked",
    subject="$app: two-step verification paused after wrong codes",
    body=(
        "There were too many wrong verification codes for your account, so sign-in is paused for $minutes minutes.\n\n"
        "Someone who knows your password may be trying codes. If these attempts were not you, reset your password."
    ),
)


@dataclass
class Grant:
    """A freshly minted session. The raw tokens exist only here; the database keeps hashes. Web sessions carry
    the session token and a CSRF token; mobile sessions an access and a refresh token."""

    auth_session: AuthSession
    principal: Principal
    access_token: str
    refresh_token: str | None = None
    csrf_token: str | None = None
    recovery_codes: list[str] | None = None  # shown once, when enrolment completed at sign-in


@dataclass
class Challenge:
    """The pending sign-in after a correct first factor: a single-purpose token that can only complete the
    second factor (or the forced enrolment). It grants nothing else; no session exists yet."""

    token: str
    expires_at: datetime
    enrolment_required: bool


def _invalid_credentials(persist: bool = False) -> Unauthenticated:
    # One message for unknown email, wrong password, disabled identity: no account enumeration.
    return Unauthenticated("Email or password is incorrect.", code="invalid-credentials", persist=persist)


def _find_identity(session: Session, kind: str, email: str) -> Identity | None:
    return session.execute(select(Identity).where(Identity.kind == kind, Identity.email == email)).scalar_one_or_none()


def _principal_for(session: Session, identity: Identity, session_id: UUID | None = None) -> Principal | None:
    """None when the identity may not act right now (deactivated or expired staff user)."""
    if identity.kind == "client":
        return Principal(
            kind="client", tenant_id=identity.tenant_id, identity_id=identity.id, email=identity.email,
            display_name=identity.email, session_id=session_id,
        )  # fmt: skip
    staff = session.execute(select(StaffUser).where(StaffUser.identity_id == identity.id)).scalar_one_or_none()
    expired = staff is not None and staff.access_expires_on and staff.access_expires_on < clock.now().date()
    if staff is None or not staff.is_active or expired:
        return None
    return rbac.staff_principal(session, staff, session_id)


def check_ip_allowlist(session: Session, principal: Principal) -> None:
    """PLT-07: staff act only from the tenant's listed networks, unless the list is empty or they hold the
    bypass key. Checked at sign-in and on every staff request; client sessions and API keys are not staff."""
    if principal.kind != "staff" or principal.has("platform.security.bypass_ip_allowlist"):
        return
    if _outside(session, principal.tenant_id):
        raise _ip_not_allowed()


def _outside(session: Session, tenant_id) -> bool:
    allowed = session.get(Tenant, tenant_id).staff_ip_allowlist
    return bool(allowed) and not networks.contains(allowed, context.client_ip.get())


def _ip_not_allowed() -> PermissionDenied:
    return PermissionDenied("Staff access is not allowed from this network.", code="ip-not-allowed")


def _refused_before_password(session: Session, audience: str, identity: Identity | None) -> bool:
    """Decided before the password is checked, and the same for an unknown email, so a refusal from outside
    the allow-list says nothing about the credentials. Only bypass holders go on to the password check."""
    if audience != "staff" or not _outside(session, session.info["tenant_id"]):
        return False
    principal = identity is not None and identity.kind == "staff" and _principal_for(session, identity)
    return not (principal and principal.has("platform.security.bypass_ip_allowlist"))


def _lifetime(session: Session, identity: Identity, client_kind: str) -> tuple[timedelta, timedelta]:
    """(idle, absolute) for this kind of session (security-baseline 5.1). Staff web idle is the tenant's
    setting (15 to 60 minutes) when it has one."""
    life = get_settings().auth.sessions[f"{identity.kind}_{client_kind}"]
    idle = life.idle_min
    if identity.kind == "staff" and client_kind == "web":
        idle = session.get(Tenant, identity.tenant_id).staff_idle_timeout_min or idle
    return timedelta(minutes=idle), timedelta(hours=life.absolute_hours)


def _start_session(
    session: Session, identity: Identity, client_kind: str, *, elevated: bool = False, mfa_verified_at=None,
    absolute_expires_at=None,
) -> Grant:  # fmt: skip
    """The one place a session is minted. Web: one token for the session cookie, valid until the sliding idle
    limit, plus a CSRF token whose hash sits on the row (security-baseline 5.2, 5.3). Mobile: a short access token
    and a rotating refresh token. `elevated`: the credential just checked satisfies step-up for 10 minutes.
    `absolute_expires_at`: a rotation (step-up) keeps the original absolute limit."""
    cfg = get_settings().auth
    idle_for, absolute_for = _lifetime(session, identity, client_kind)
    now = clock.now()
    absolute = absolute_expires_at or now + absolute_for
    idle = min(now + idle_for, absolute)
    access, access_hash = tokens.mint("fhs", identity.tenant_id)
    row = AuthSession(
        identity_id=identity.id, kind=client_kind, access_token_hash=access_hash, idle_expires_at=idle,
        absolute_expires_at=absolute, ip=context.client_ip.get(), last_seen_at=now, mfa_verified_at=mfa_verified_at,
        elevated_until_at=now + timedelta(minutes=cfg.step_up_min) if elevated else None,
    )  # fmt: skip
    grant = Grant(row, None, access)
    if client_kind == "web":
        grant.csrf_token = tokens.secret()
        row.access_expires_at, row.csrf_token_hash = idle, tokens.digest(grant.csrf_token)
    else:
        grant.refresh_token, row.refresh_token_hash = tokens.mint("fhr", identity.tenant_id)
        row.access_expires_at = now + timedelta(minutes=cfg.access_ttl_min)
    session.add(row)
    session.flush()
    principal = _principal_for(session, identity, row.id)
    if principal is None:
        raise _invalid_credentials()
    grant.principal = replace(principal, elevated=elevated)
    check_ip_allowlist(session, grant.principal)
    identity.last_sign_in_at = now
    return grant


def verify_csrf(session: Session, principal: Principal, header: str) -> bool:
    """A cookie session's X-CSRF-Token against the hash on its row (set by core.auth.deps)."""
    row = session.get(AuthSession, principal.session_id)
    expected = row.csrf_token_hash if row else None
    return bool(expected and header) and hmac.compare_digest(tokens.digest(header), expected)


def revoke_sessions(session: Session, identity_id: UUID, reason: str, *, keep: UUID | None = None) -> None:
    stmt = update(AuthSession).where(AuthSession.identity_id == identity_id, AuthSession.revoked_at.is_(None))
    if keep:
        stmt = stmt.where(AuthSession.id != keep)
    session.execute(stmt.values(revoked_at=clock.now(), revoked_reason=reason))


# --- password ----------------------------------------------------------------------------------------------


def _count_failure(row) -> int | None:
    """Count one failure on a row with the four lockout fields (identity for passwords, mfa_factor for codes)
    inside the window (baseline 5.1). At the threshold, lock it: 15 minutes, doubling with each further lockout
    up to the cap. Returns the minutes when this failure locked it. Lock the row before calling."""
    cfg = get_settings().auth
    now = clock.now()
    started = row.failed_window_started_at
    if started is None or now - started > timedelta(minutes=cfg.lockout_window_min):
        row.failed_window_started_at, row.failed_attempt_count = now, 0
    row.failed_attempt_count += 1
    if row.failed_attempt_count < cfg.lockout_threshold:
        return None
    minutes = min(cfg.lockout_min * 2 ** min(row.lockout_count, 16), cfg.lockout_max_min)
    row.locked_until_at = now + timedelta(minutes=minutes)
    row.lockout_count += 1
    row.failed_attempt_count, row.failed_window_started_at = 0, None
    return minutes


def _password_failed(session: Session, identity: Identity) -> None:
    """A wrong password. The lock stops password sign-in only and mails the owner once per lockout. Attempts
    while locked are refused before they get here, so they neither count nor mail."""
    minutes = _count_failure(identity)
    if minutes is None:
        return
    events.publish(session, IdentityLocked(identity_id=identity.id), identity.id)
    data = {"app": get_settings().app.display_name, "minutes": minutes}
    notifications.send(session, "platform.identity_locked", identity.email, data)


def _clear_failures(row) -> None:
    """A proof ends that row's failure window and doubling: a right password or a redeemed link clears the
    identity's password count, a right code clears the factor's. Neither clears the other."""
    row.failed_attempt_count, row.failed_window_started_at = 0, None
    row.locked_until_at, row.lockout_count = None, 0


def sign_in(
    session: Session, *, email: str, password: str, audience: str = "staff", client_kind: str = "web"
) -> Grant | Challenge:
    now = clock.now()
    identity = _find_identity(session, audience, email)
    if _refused_before_password(session, audience, identity):
        passwords.burn(password)
        raise _ip_not_allowed()
    if identity is None or identity.password_hash is None:
        passwords.burn(password)
        raise _invalid_credentials()
    if identity.locked_until_at and identity.locked_until_at > now:
        # Password path only: magic link keeps working, so lockout cannot deny service (ADR 0002).
        raise Unauthenticated(
            "Too many failed attempts. Try again later or use an emailed link.", code="identity-locked"
        )
    if not passwords.verify_password(identity.password_hash, password):
        _password_failed(session, identity)
        audit.record(session, "platform.identity.sign_in_failed", identity, actor=_actor(identity))
        raise _invalid_credentials(persist=True)
    if identity.status != "active":
        raise _invalid_credentials()
    if passwords.needs_rehash(identity.password_hash):
        identity.password_hash = passwords.hash_password(password)
    _clear_failures(identity)  # codes have their own count on the factor
    if challenge := _second_factor(session, identity, client_kind, "password"):
        return challenge
    grant = _start_session(session, identity, client_kind, elevated=True)
    audit.record(session, "platform.identity.sign_in", identity, actor=grant.principal)
    return grant


def reauthenticate(session: Session, principal: Principal, password: str) -> None:
    """Re-check the signed-in staff user's own password before a time-clock punch (STF-07). Failures count
    toward the same lockout as sign-in, so a punch screen cannot be used to guess. Raise before any write."""
    now = clock.now()
    identity = session.get(Identity, principal.identity_id)
    if identity is None or identity.password_hash is None or (identity.locked_until_at or now) > now:
        passwords.burn(password)
        raise PermissionDenied("Password is incorrect.", code="reauthentication-failed")
    if not passwords.verify_password(identity.password_hash, password):
        _password_failed(session, identity)
        audit.record(session, "platform.identity.reauthentication_failed", identity)
        raise PermissionDenied("Password is incorrect.", code="reauthentication-failed", persist=True)
    _clear_failures(identity)


_FRESH_PROOF = timedelta(minutes=15)  # the step-up window of rbac-matrix.md section 2


def _is_fresh_magic_link_session(session: Session, principal: Principal) -> bool:
    """The session's sign-in audit event is the record of how and when it was established (append-only)."""
    return (
        session.scalar(
            select(audit.AuditEvent.id)
            .where(
                audit.AuditEvent.entity_type == Identity.__tablename__,
                audit.AuditEvent.entity_id == principal.identity_id,
                audit.AuditEvent.action == "platform.identity.sign_in",
                audit.AuditEvent.reason == "magic_link",
                audit.AuditEvent.auth_session_id == principal.session_id,
                audit.AuditEvent.occurred_at > clock.now() - _FRESH_PROOF,
            )
            .limit(1)
        )
        is not None
    )


def change_password(session: Session, principal: Principal, *, current_password: str | None, new_password: str) -> None:
    identity = session.get(Identity, principal.identity_id)
    if identity.password_hash:
        if not passwords.verify_password(identity.password_hash, current_password or ""):
            raise _invalid_credentials()
    elif not _is_fresh_magic_link_session(session, principal):
        # A first password turns a session into a durable credential: demand fresh proof of the mailbox.
        raise PermissionDenied(
            "To set a password, use the password-reset link we email you, or sign in again with an emailed link.",
            code="password-reset-required",
        )
    _set_password(session, identity, new_password, principal.display_name)
    _clear_failures(identity)
    revoke_sessions(session, identity.id, "password_reset", keep=principal.session_id)
    audit.record(session, "platform.identity.change_password", identity)


def _set_password(session: Session, identity: Identity, new_password: str, *names: str) -> None:
    passwords.check_policy(new_password, forbidden=(identity.email, *names))
    identity.password_hash = passwords.hash_password(new_password)
    identity.password_changed_at = clock.now()
    settings = get_settings()
    body = "The password for your account was just set or changed. If this was not you, reset it now."
    send_after_commit(
        session, EmailMessage(identity.email, f"{settings.app.display_name}: your password was changed", body)
    )


# --- emailed links -----------------------------------------------------------------------------------------

_LINKS = {
    # purpose: (web path, subject, first line of the email)
    TokenPurpose.MAGIC_LINK: ("/auth/magic-link", "your sign-in link", "Use this link to sign in."),
    TokenPurpose.PASSWORD_RESET: (
        "/auth/reset-password",
        "reset your password",
        "Use this link to choose a new password.",
    ),
    TokenPurpose.INVITE: ("/auth/accept-invite", "you have been invited", "Use this link to activate your account."),
}


def safe_redirect_path(path: str | None) -> str | None:
    """No open redirect: a local path only. Browsers treat a backslash as a slash, so "/\\host" is refused
    too, as are control characters, which browsers strip before resolving."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in path):
        return None
    return path


def issue_link(
    session: Session, identity: Identity, purpose: TokenPurpose, ttl: timedelta, *, redirect_path: str | None = None
) -> str:
    """Mint a single-use link token, supersede older ones of the same purpose and email the link.

    The emailed URL opens a confirmation page in the web app; the token is consumed only by the POST that
    page makes, so mail scanners that prefetch links cannot burn it.
    """
    settings = get_settings()
    now = clock.now()
    session.execute(
        update(AuthToken)
        .where(AuthToken.identity_id == identity.id, AuthToken.purpose == purpose, AuthToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    raw, hashed = tokens.mint("fhl", identity.tenant_id)
    session.add(AuthToken(identity_id=identity.id, purpose=purpose, token_hash=hashed, expires_at=now + ttl))
    path, subject, intro = _LINKS[purpose]
    # The token rides in the URL fragment, which browsers never send to a server or put in a Referer
    # (security-baseline 17.2); the landing page reads it and posts it.
    url = f"{settings.app.web_base_url}{path}#token={raw}"
    if safe := safe_redirect_path(redirect_path):
        url += f"&redirect={quote(safe, safe='/')}"
    minutes = int(ttl.total_seconds() // 60)
    lifetime = f"{minutes} minutes" if minutes < 120 else f"{minutes // 1440} days"
    body = f"{intro}\n\n{url}\n\nThe link works once and expires in {lifetime}. If you did not ask for it, ignore this email."
    send_after_commit(session, EmailMessage(identity.email, f"{settings.app.display_name}: {subject}", body))
    return raw


def _consume(session: Session, token: str, purpose: TokenPurpose) -> Identity:
    row = session.execute(
        select(AuthToken)
        .where(AuthToken.token_hash == tokens.digest(token), AuthToken.purpose == purpose)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None or row.identity_id is None:
        raise Unauthenticated("This link is not valid or was already used.", code="token-invalid")
    if row.expires_at <= clock.now():
        raise Unauthenticated("This link has expired. Ask for a new one.", code="token-expired")
    row.consumed_at = clock.now()
    return session.get(Identity, row.identity_id)


def request_magic_link(
    session: Session, *, email: str, audience: str = "staff", redirect_path: str | None = None
) -> None:
    """Always succeeds from the caller's point of view, whether or not the email exists."""
    identity = _find_identity(session, audience, email)
    if identity is not None and identity.status == "active" and _principal_for(session, identity) is not None:
        ttl = timedelta(minutes=get_settings().auth.magic_link_ttl_min)
        issue_link(session, identity, TokenPurpose.MAGIC_LINK, ttl, redirect_path=redirect_path)


def consume_magic_link(session: Session, *, token: str, client_kind: str = "web") -> Grant | Challenge:
    identity = _consume(session, token, TokenPurpose.MAGIC_LINK)
    if identity.status != "active":
        raise Unauthenticated("This link is not valid or was already used.", code="token-invalid")
    # Redeeming the link proves the mailbox: verify the address and clear a password lockout (not the code one).
    identity.email_verified_at = identity.email_verified_at or clock.now()
    _clear_failures(identity)
    if challenge := _second_factor(session, identity, client_kind, "magic_link"):
        return challenge
    grant = _start_session(session, identity, client_kind)
    audit.record(session, "platform.identity.sign_in", identity, actor=grant.principal, reason="magic_link")
    return grant


def request_password_reset(session: Session, *, email: str, audience: str = "staff") -> None:
    identity = _find_identity(session, audience, email)
    if identity is not None and identity.status == "active":
        ttl = timedelta(minutes=get_settings().auth.password_reset_ttl_min)
        issue_link(session, identity, TokenPurpose.PASSWORD_RESET, ttl)


def consume_password_reset(
    session: Session, *, token: str, new_password: str, client_kind: str = "web"
) -> Grant | Challenge:
    identity = _consume(session, token, TokenPurpose.PASSWORD_RESET)
    if identity.status != "active":
        raise Unauthenticated("This link is not valid or was already used.", code="token-invalid")
    _set_password(session, identity, new_password)
    _clear_failures(identity)
    revoke_sessions(session, identity.id, "password_reset")
    if challenge := _second_factor(session, identity, client_kind, "password_reset"):
        audit.record(session, "platform.identity.reset_password", identity, actor=_actor(identity))
        return challenge  # a reset never bypasses MFA (ADR 0002 section 3)
    grant = _start_session(session, identity, client_kind)
    audit.record(session, "platform.identity.reset_password", identity, actor=grant.principal)
    return grant


# Other contexts append fn(session, identity_id) to run when an invited identity activates (clients: access rows).
ACTIVATION_HOOKS: list = []


def accept_invitation(
    session: Session, *, token: str, new_password: str | None = None, client_kind: str = "web"
) -> Grant | Challenge:
    """Activate an invited identity. The password is optional: the invitee may stay on magic links."""
    identity = _consume(session, token, TokenPurpose.INVITE)
    if identity.status != "invited":
        raise Unauthenticated("This invitation was already accepted.", code="token-invalid")
    if new_password:
        _set_password(session, identity, new_password)
    identity.status = "active"
    identity.email_verified_at = clock.now()
    for hook in ACTIVATION_HOOKS:
        hook(session, identity.id)
    if challenge := _second_factor(session, identity, client_kind, "invite"):
        audit.record(session, "platform.identity.accept_invitation", identity, actor=_actor(identity))
        return challenge
    _clear_failures(identity)
    grant = _start_session(session, identity, client_kind)
    audit.record(session, "platform.identity.accept_invitation", identity, actor=grant.principal)
    return grant


# --- sessions ----------------------------------------------------------------------------------------------


def authenticate(session: Session, access_token: str) -> Principal:
    """Session or access token -> Principal: one indexed lookup under the tenant named by the token prefix.
    A web session slides its idle limit on use (never past the absolute one)."""
    now = clock.now()
    row = session.execute(
        select(AuthSession).where(AuthSession.access_token_hash == tokens.digest(access_token))
    ).scalar_one_or_none()
    if row is None or row.revoked_at or row.access_expires_at <= now or row.absolute_expires_at <= now:
        raise Unauthenticated("Your session has expired. Sign in again.")
    if session.get(Tenant, row.tenant_id).status != "active":
        raise PermissionDenied("This account is not active.", code="tenant-suspended")
    identity = session.get(Identity, row.identity_id)
    principal = _principal_for(session, identity, row.id) if identity.status == "active" else None
    if principal is None:  # deactivation is immediate: the next request fails
        raise Unauthenticated("Your session has expired. Sign in again.")
    check_ip_allowlist(session, principal)
    if row.last_seen_at is None or now - row.last_seen_at > timedelta(minutes=1):
        row.last_seen_at = now
        if row.kind == "web":
            row.idle_expires_at = min(now + _lifetime(session, identity, "web")[0], row.absolute_expires_at)
            row.access_expires_at = row.idle_expires_at
    return replace(principal, elevated=row.elevated_until_at is not None and row.elevated_until_at > now)


def refresh(session: Session, *, refresh_token: str) -> Grant:
    """Rotate both tokens. A refresh token that was already rotated away is a theft signal and revokes the
    session, except the immediately previous one inside a short grace window (concurrent tabs, flaky networks)."""
    cfg = get_settings().auth
    now = clock.now()
    hashed = tokens.digest(refresh_token)
    row = session.execute(
        select(AuthSession)
        .where((AuthSession.refresh_token_hash == hashed) | (AuthSession.previous_refresh_token_hash == hashed))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.revoked_at or row.idle_expires_at <= now or row.absolute_expires_at <= now:
        raise Unauthenticated("Your session has ended. Sign in again.", code="session-revoked")
    if row.refresh_token_hash != hashed:
        if now - row.refresh_rotated_at > timedelta(seconds=cfg.refresh_grace_sec):
            row.revoked_at, row.revoked_reason = now, "rotation_reuse"
            raise Unauthenticated("Your session has ended. Sign in again.", code="refresh-reuse-detected", persist=True)
    identity = session.get(Identity, row.identity_id)
    principal = _principal_for(session, identity, row.id) if identity.status == "active" else None
    if principal is None:
        raise Unauthenticated("Your session has ended. Sign in again.", code="session-revoked")
    access, row.access_token_hash = tokens.mint("fhs", row.tenant_id)
    row.previous_refresh_token_hash, row.refresh_rotated_at = row.refresh_token_hash, now
    refresh_token, row.refresh_token_hash = tokens.mint("fhr", row.tenant_id)
    row.access_expires_at = now + timedelta(minutes=cfg.access_ttl_min)
    row.idle_expires_at = min(now + _lifetime(session, identity, row.kind)[0], row.absolute_expires_at)
    row.last_seen_at = now
    return Grant(row, principal, access, refresh_token)


def sign_out(session: Session, principal: Principal) -> None:
    row = session.get(AuthSession, principal.session_id)
    row.revoked_at, row.revoked_reason = clock.now(), "sign_out"
    audit.record(session, "platform.identity.sign_out", session.get(Identity, principal.identity_id))


def get_session(session: Session, principal: Principal) -> AuthSession:
    return session.get(AuthSession, principal.session_id)


def list_sessions(session: Session, principal: Principal) -> list[AuthSession]:
    """The caller's own live sessions, newest first."""
    now = clock.now()
    return list(
        session.scalars(
            select(AuthSession)
            .where(
                AuthSession.identity_id == principal.identity_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.idle_expires_at > now,
                AuthSession.absolute_expires_at > now,
            )
            .order_by(AuthSession.id.desc())
        )
    )


def revoke_session(session: Session, principal: Principal, session_id: UUID) -> None:
    row = session.get(AuthSession, session_id)
    if row is None or row.identity_id != principal.identity_id:
        raise NotFound()
    if row.revoked_at is None:
        row.revoked_at, row.revoked_reason = clock.now(), "sign_out"


# --- second factor (chip S2: ADR 0002 section 6, security-baseline 5.1) -------------------------------------


def _actor(identity: Identity) -> Principal:
    """Audit attribution before a session exists."""
    return Principal(kind=identity.kind, tenant_id=identity.tenant_id, identity_id=identity.id, email=identity.email)


def _second_factor(session: Session, identity: Identity, client_kind: str, method: str) -> Challenge | None:
    """After a correct first factor: None when a session may start now; otherwise the pending challenge, for an
    identity with a confirmed factor (any kind) or a staff identity the tenant policy requires to enrol."""
    if mfa.confirmed_factor(session, identity.id) is None and not mfa.is_required(session, identity):
        return None
    if _principal_for(session, identity) is None:
        raise _invalid_credentials()
    now = clock.now()
    session.execute(
        update(AuthToken)
        .where(
            AuthToken.identity_id == identity.id,
            AuthToken.purpose == TokenPurpose.MFA_CHALLENGE,
            AuthToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    raw, hashed = tokens.mint("fhm", identity.tenant_id)
    expires = now + timedelta(minutes=get_settings().auth.mfa_challenge_ttl_min)
    payload = {"client_kind": client_kind, "method": method}
    session.add(
        AuthToken(
            identity_id=identity.id, purpose=TokenPurpose.MFA_CHALLENGE, token_hash=hashed, expires_at=expires,
            payload=payload,
        )
    )  # fmt: skip
    session.flush()
    return Challenge(raw, expires, mfa.confirmed_factor(session, identity.id) is None)


def _pending(session: Session, token: str) -> tuple[AuthToken, Identity]:
    """A live challenge, locked, not consumed: a wrong code may be retried within the challenge's budget."""
    row = session.execute(
        select(AuthToken)
        .where(AuthToken.token_hash == tokens.digest(token), AuthToken.purpose == TokenPurpose.MFA_CHALLENGE)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None or row.consumed_at is not None or row.expires_at <= clock.now():
        raise Unauthenticated("This sign-in has expired. Sign in again.", code="mfa-challenge-invalid")
    identity = session.get(Identity, row.identity_id)
    if identity.status != "active":
        raise Unauthenticated("This sign-in has expired. Sign in again.", code="mfa-challenge-invalid")
    return row, identity


def _refuse_if_locked(identity: Identity, error=Unauthenticated) -> None:
    """The password lock. Signed-in callers get 403: a 401 would mean their session is over."""
    if identity.locked_until_at and identity.locked_until_at > clock.now():
        raise error("Too many failed attempts. Try again later or use an emailed link.", code="identity-locked")


def _refuse_if_code_locked(factor, error=Unauthenticated) -> None:
    """The code lock, on the factor: wrong passwords never set it, and links never clear it."""
    if factor.locked_until_at and factor.locked_until_at > clock.now():
        raise error("Too many wrong codes. Try again later.", code="mfa-locked")


def _code_failed(session: Session, identity: Identity, factor, action: str, error) -> None:
    """A wrong code counts on the (locked) factor row, then is refused with a persisted error so the count
    survives the rollback of the rest. The lock mails the owner once, like the password lock."""
    minutes = _count_failure(factor)
    if minutes is not None:
        data = {"app": get_settings().app.display_name, "minutes": minutes}
        notifications.send(session, "platform.mfa_locked", identity.email, data)
    audit.record(session, action, identity, actor=_actor(identity))
    raise error


def _refuse_password_only_enrolment(session: Session, row: AuthToken, identity: Identity) -> None:
    """Forced enrolment binds a new authenticator, so a password alone (which may have leaked) is not enough:
    it must follow an emailed link (magic link, reset, invitation). Email one sign-in link per pending sign-in."""
    if row.payload.get("method") != "password":
        return
    if not row.payload.get("link_sent"):
        ttl = timedelta(minutes=get_settings().auth.magic_link_ttl_min)
        issue_link(session, identity, TokenPurpose.MAGIC_LINK, ttl)
        row.payload = {**row.payload, "link_sent": True}
    raise PermissionDenied(
        "To set up two-step verification, open the sign-in link we just emailed you.",
        code="mfa-enrolment-needs-email-link",
        persist=True,
    )


def start_challenge_enrolment(session: Session, *, token: str) -> tuple[str, str]:
    """Forced enrolment inside a pending sign-in that began with an emailed link: a new secret for the
    identity. (secret, otpauth URI)."""
    row, identity = _pending(session, token)
    _refuse_password_only_enrolment(session, row, identity)
    return mfa.start_enrolment(session, identity)


def complete_challenge(session: Session, *, token: str, code: str) -> Grant:
    """Second factor of a pending sign-in: a TOTP code, a recovery code (consumed), or, for a forced enrolment,
    the first code of the new factor. Only now is a session minted, MFA-verified and elevated."""
    row, identity = _pending(session, token)
    wrong = Unauthenticated("That code is not right. Try the current one.", code="mfa-code-invalid", persist=True)
    factor = mfa.factor(session, identity.id, lock=True)
    if factor is None:
        raise ValidationFailed("Set up your authenticator app first.", code="mfa-enrolment-not-started")
    _refuse_if_code_locked(factor)
    recovery_codes = None
    if factor.confirmed_at is not None:
        used = mfa.verify(session, factor, code)
    else:  # forced enrolment: the first code proves the authenticator was set up
        _refuse_password_only_enrolment(session, row, identity)
        used = "totp" if mfa.match_totp(factor, code) else None
        if used:
            recovery_codes = _confirm(session, identity, factor)
            revoke_sessions(session, identity.id, "mfa_change")  # as confirm_mfa_enrolment does
    if used is None:
        _code_failed(session, identity, factor, "platform.identity.mfa_failed", wrong)
    now = clock.now()
    row.consumed_at = now
    _clear_failures(factor)
    grant = _start_session(session, identity, row.payload["client_kind"], elevated=True, mfa_verified_at=now)
    grant.recovery_codes = recovery_codes
    if used == "recovery":
        audit.record(session, "platform.identity.mfa_recovery_used", identity, actor=grant.principal)
    audit.record(session, "platform.identity.sign_in", identity, actor=grant.principal, reason=row.payload["method"])
    return grant


def _confirm(session: Session, identity: Identity, factor) -> list[str]:
    factor.confirmed_at = clock.now()
    codes = mfa.new_recovery_codes(session, identity.id)
    audit.record(session, "platform.identity.mfa_enrol", identity, actor=_actor(identity))
    _mfa_changed_email(session, identity, "turned on")
    return codes


def _mfa_changed_email(session: Session, identity: Identity, what: str) -> None:
    name = get_settings().app.display_name
    body = f"Two-step verification was just {what} for your account. If this was not you, reset your password now."
    send_after_commit(session, EmailMessage(identity.email, f"{name}: two-step verification {what}", body))


# --- step-up -------------------------------------------------------------------------------------------------


def step_up(session: Session, principal: Principal, *, code: str | None = None, password: str | None = None) -> Grant:
    """Re-authenticate the signed-in caller (ADR 0002 section 4): their TOTP or recovery code when enrolled, else
    their password. Rotates the session through _start_session (new session id and CSRF token, baseline 5.1),
    keeps its absolute limit, and makes it satisfy `+` keys for 10 minutes. Failures count toward lockout."""
    identity = session.get(Identity, principal.identity_id)
    current = session.get(AuthSession, principal.session_id)
    if current is None or current.kind not in ("web", "mobile"):
        raise PermissionDenied("This session cannot be confirmed.", code="step-up-unavailable")
    wrong = PermissionDenied("That did not match. Try again.", code="reauthentication-failed", persist=True)
    factor = mfa.confirmed_factor(session, identity.id, lock=True)  # locked before counting: no lost updates
    if factor is not None:
        _refuse_if_code_locked(factor, PermissionDenied)
        if not (code and mfa.verify(session, factor, code)):
            _code_failed(session, identity, factor, "platform.identity.step_up_failed", wrong)
        _clear_failures(factor)
    elif mfa.is_required(session, identity):
        # The policy was tightened under a live session: a password alone no longer confirms this user.
        raise PermissionDenied(
            "Two-step verification is now required for your role. Sign out and sign in again to set it up.",
            code="mfa-enrolment-required",
        )
    elif identity.password_hash:
        session.refresh(identity, with_for_update=True)  # count on a locked row
        _refuse_if_locked(identity, PermissionDenied)
        if not (password and passwords.verify_password(identity.password_hash, password)):
            _password_failed(session, identity)
            audit.record(session, "platform.identity.step_up_failed", identity, actor=_actor(identity))
            raise wrong
        _clear_failures(identity)
    else:
        raise PermissionDenied(
            "Set a password or turn on two-step verification to confirm it is you.", code="step-up-unavailable"
        )
    now = clock.now()
    current.revoked_at, current.revoked_reason = now, "step_up"
    grant = _start_session(
        session, identity, current.kind, elevated=True, absolute_expires_at=current.absolute_expires_at,
        mfa_verified_at=now if factor is not None else current.mfa_verified_at,
    )  # fmt: skip
    audit.record(session, "platform.identity.step_up", identity, actor=grant.principal)
    return grant


# --- the caller's own second factor ---------------------------------------------------------------------------


def mfa_status(session: Session, principal: Principal) -> dict:
    identity = session.get(Identity, principal.identity_id)
    factor = mfa.confirmed_factor(session, identity.id)
    return {
        "enrolled": factor is not None,
        "confirmed_at": factor.confirmed_at if factor else None,
        "recovery_codes_remaining": mfa.remaining_recovery_codes(session, identity.id) if factor else 0,
        "required": mfa.is_required(session, identity),
    }


def begin_mfa_enrolment(session: Session, principal: Principal) -> tuple[str, str]:
    """Changing MFA needs a recent re-authentication (ADR 0002 section 4)."""
    require_elevated(principal)
    return mfa.start_enrolment(session, session.get(Identity, principal.identity_id))


def confirm_mfa_enrolment(session: Session, principal: Principal, code: str) -> list[str]:
    """First code of the new factor: turns it on, returns the ten recovery codes once, signs out other sessions
    (MFA change, ADR 0002 section 4) and marks this one MFA-verified."""
    identity = session.get(Identity, principal.identity_id)
    factor = mfa.factor(session, identity.id, lock=True)
    if factor is None or factor.confirmed_at is not None:
        raise ValidationFailed("Set up your authenticator app first.", code="mfa-enrolment-not-started")
    _refuse_if_code_locked(factor, PermissionDenied)
    if not mfa.match_totp(factor, code):
        wrong = PermissionDenied("That code is not right. Try the current one.", code="mfa-code-invalid", persist=True)
        _code_failed(session, identity, factor, "platform.identity.mfa_failed", wrong)
    _clear_failures(factor)
    codes = _confirm(session, identity, factor)
    revoke_sessions(session, identity.id, "mfa_change", keep=principal.session_id)
    session.get(AuthSession, principal.session_id).mfa_verified_at = clock.now()
    return codes


def disable_mfa(session: Session, principal: Principal) -> None:
    require_elevated(principal)
    identity = session.get(Identity, principal.identity_id)
    if mfa.confirmed_factor(session, identity.id) is None:
        raise NotFound()
    if mfa.is_required(session, identity):
        raise PermissionDenied("Your role requires two-step verification.", code="mfa-required")
    mfa.remove(session, identity.id)
    revoke_sessions(session, identity.id, "mfa_change", keep=principal.session_id)
    audit.record(session, "platform.identity.mfa_disable", identity)
    _mfa_changed_email(session, identity, "turned off")


def regenerate_recovery_codes(session: Session, principal: Principal) -> list[str]:
    require_elevated(principal)
    if mfa.confirmed_factor(session, principal.identity_id) is None:
        raise NotFound()
    codes = mfa.new_recovery_codes(session, principal.identity_id)
    audit.record(session, "platform.identity.mfa_recovery_regenerate", session.get(Identity, principal.identity_id))
    return codes
