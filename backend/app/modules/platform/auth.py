"""Sign-in, emailed links and server-side sessions (ADR 0002 sections 3 and 4)."""

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import audit, clock, context, events
from app.core.auth import Principal, passwords, tokens
from app.core.errors import NotFound, PermissionDenied, Unauthenticated
from app.core.settings import get_settings
from app.modules.platform import rbac
from app.modules.platform.events import IdentityLocked
from app.modules.platform.models import AuthSession, AuthToken, Identity, StaffUser, Tenant, TokenPurpose
from app.ports.email import EmailMessage, send_after_commit


@dataclass
class Grant:
    """A freshly minted session. The raw tokens exist only here; the database keeps hashes."""

    auth_session: AuthSession
    principal: Principal
    access_token: str
    refresh_token: str


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


def _start_session(session: Session, identity: Identity, client_kind: str) -> Grant:
    cfg = get_settings().auth
    life = cfg.sessions[f"{identity.kind}_{client_kind}"]
    now = clock.now()
    absolute = now + timedelta(days=life.absolute_days)
    access, access_hash = tokens.mint("fhs", identity.tenant_id)
    refresh, refresh_hash = tokens.mint("fhr", identity.tenant_id)
    row = AuthSession(
        identity_id=identity.id,
        kind=client_kind,
        access_token_hash=access_hash,
        access_expires_at=now + timedelta(minutes=cfg.access_ttl_min),
        refresh_token_hash=refresh_hash,
        idle_expires_at=min(now + timedelta(hours=life.idle_hours), absolute),
        absolute_expires_at=absolute,
        ip=context.client_ip.get(),
        last_seen_at=now,
    )
    session.add(row)
    session.flush()
    principal = _principal_for(session, identity, row.id)
    if principal is None:
        raise _invalid_credentials()
    identity.last_sign_in_at = now
    return Grant(row, principal, access, refresh)


def revoke_sessions(session: Session, identity_id: UUID, reason: str, *, keep: UUID | None = None) -> None:
    stmt = update(AuthSession).where(AuthSession.identity_id == identity_id, AuthSession.revoked_at.is_(None))
    if keep:
        stmt = stmt.where(AuthSession.id != keep)
    session.execute(stmt.values(revoked_at=clock.now(), revoked_reason=reason))


# --- password ----------------------------------------------------------------------------------------------


def sign_in(session: Session, *, email: str, password: str, audience: str = "staff", client_kind: str = "web") -> Grant:
    cfg = get_settings().auth
    now = clock.now()
    identity = _find_identity(session, audience, email)
    if identity is None or identity.password_hash is None:
        passwords.burn(password)
        raise _invalid_credentials()
    if identity.locked_until_at and identity.locked_until_at > now:
        # Password path only: magic link keeps working, so lockout cannot deny service (ADR 0002).
        raise Unauthenticated(
            "Too many failed attempts. Try again later or use an emailed link.", code="identity-locked"
        )
    actor = Principal(kind=identity.kind, tenant_id=identity.tenant_id, identity_id=identity.id, email=identity.email)
    if not passwords.verify_password(identity.password_hash, password):
        identity.failed_attempt_count += 1
        if identity.failed_attempt_count >= cfg.lockout_threshold:
            identity.failed_attempt_count = 0
            identity.locked_until_at = now + timedelta(minutes=cfg.lockout_min)
            events.publish(session, IdentityLocked(identity_id=identity.id), identity.id)
        audit.record(session, "platform.identity.sign_in_failed", identity, actor=actor)
        raise _invalid_credentials(persist=True)
    if identity.status != "active":
        raise _invalid_credentials()
    if passwords.needs_rehash(identity.password_hash):
        identity.password_hash = passwords.hash_password(password)
    identity.failed_attempt_count, identity.locked_until_at = 0, None
    grant = _start_session(session, identity, client_kind)
    audit.record(session, "platform.identity.sign_in", identity, actor=grant.principal)
    return grant


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
    revoke_sessions(session, identity.id, "password_reset", keep=principal.session_id)
    audit.record(session, "platform.identity.change_password", identity)


def _set_password(session: Session, identity: Identity, new_password: str, *names: str) -> None:
    passwords.check_policy(new_password, forbidden=(identity.email, *names))
    identity.password_hash = passwords.hash_password(new_password)
    identity.password_changed_at = clock.now()
    identity.failed_attempt_count, identity.locked_until_at = 0, None
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


def consume_magic_link(session: Session, *, token: str, client_kind: str = "web") -> Grant:
    identity = _consume(session, token, TokenPurpose.MAGIC_LINK)
    if identity.status != "active":
        raise Unauthenticated("This link is not valid or was already used.", code="token-invalid")
    # Redeeming the link proves the mailbox: verify the address and clear a password lockout.
    identity.email_verified_at = identity.email_verified_at or clock.now()
    identity.failed_attempt_count, identity.locked_until_at = 0, None
    grant = _start_session(session, identity, client_kind)
    audit.record(session, "platform.identity.sign_in", identity, actor=grant.principal, reason="magic_link")
    return grant


def request_password_reset(session: Session, *, email: str, audience: str = "staff") -> None:
    identity = _find_identity(session, audience, email)
    if identity is not None and identity.status == "active":
        ttl = timedelta(minutes=get_settings().auth.password_reset_ttl_min)
        issue_link(session, identity, TokenPurpose.PASSWORD_RESET, ttl)


def consume_password_reset(session: Session, *, token: str, new_password: str, client_kind: str = "web") -> Grant:
    identity = _consume(session, token, TokenPurpose.PASSWORD_RESET)
    if identity.status != "active":
        raise Unauthenticated("This link is not valid or was already used.", code="token-invalid")
    _set_password(session, identity, new_password)
    revoke_sessions(session, identity.id, "password_reset")
    grant = _start_session(session, identity, client_kind)
    audit.record(session, "platform.identity.reset_password", identity, actor=grant.principal)
    return grant


# Other contexts append fn(session, identity_id) to run when an invited identity activates (clients: access rows).
ACTIVATION_HOOKS: list = []


def accept_invitation(
    session: Session, *, token: str, new_password: str | None = None, client_kind: str = "web"
) -> Grant:
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
    grant = _start_session(session, identity, client_kind)
    audit.record(session, "platform.identity.accept_invitation", identity, actor=grant.principal)
    return grant


# --- sessions ----------------------------------------------------------------------------------------------


def authenticate(session: Session, access_token: str) -> Principal:
    """Access token -> Principal: one indexed lookup under the tenant named by the token prefix."""
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
    if row.last_seen_at is None or now - row.last_seen_at > timedelta(minutes=1):
        row.last_seen_at = now
    return principal


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
    life = cfg.sessions[f"{identity.kind}_{row.kind}"]
    access, row.access_token_hash = tokens.mint("fhs", row.tenant_id)
    row.previous_refresh_token_hash, row.refresh_rotated_at = row.refresh_token_hash, now
    refresh_token, row.refresh_token_hash = tokens.mint("fhr", row.tenant_id)
    row.access_expires_at = now + timedelta(minutes=cfg.access_ttl_min)
    row.idle_expires_at = min(now + timedelta(hours=life.idle_hours), row.absolute_expires_at)
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
