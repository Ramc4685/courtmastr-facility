"""Public self-registration for the member portal (SSP-05; phase-11 decision Q7).

Per location and off by default (`portal_settings.allows_self_signup`). A request answers the same whether or
not the address is known: an unknown address gets a verification link (token in the URL fragment, only its hash
kept, single use, 24 hours); an address that already signs in gets a sign-in link instead; anything else gets
nothing. Confirming creates a new client (never matched to an existing one by email, staff merge duplicates),
an active portal login for it, and signs in. Staff invitations keep working unchanged.
"""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import audit, clock, context, events
from app.core.auth import tokens
from app.core.errors import Conflict, Unauthenticated
from app.core.settings import get_settings
from app.modules import clients, platform
from app.modules.engagement.events import PortalSignupConfirmed
from app.modules.engagement.models import PortalSettings, PortalSignup
from app.ports import notifications

TOKEN_PREFIX = "fhp"
TTL = timedelta(hours=24)
REQUEST = "engagement.portal_signup.request"
CONFIRM = "engagement.portal_signup.confirm"

notifications.register_template(
    "engagement.portal_signup",
    subject="$app: confirm your email to finish signing up",
    body="Hello $name,\n\nTo create your $facility account, confirm this address by opening the link below.\n\n"
    "$url\n\nThe link works once and expires in 24 hours. If you did not sign up, ignore this email.",
)


def _open_location(session: Session, location_id) -> PortalSettings:
    row = session.scalar(select(PortalSettings).where(PortalSettings.location_id == location_id))
    if row is None or not (row.is_enabled and row.allows_self_signup):
        raise Conflict("Online sign-up is not available at this location.", code="signup-disabled")
    return row


def request_signup(session: Session, data: dict) -> None:
    """Start a sign-up. Field policy (portal context) is checked first, so the form shows what it needs."""
    _open_location(session, data["location_id"])
    email = data["email"].lower()
    clients.service.check_capture(
        session, "portal", {"email": email, "phone_mobile": data.get("phone_mobile"), "birth_on": data.get("birth_on")}
    )
    identity = platform.service.find_client_identity(session, email)
    if identity is not None:
        if identity.status == "active":  # already has a login: a sign-in link, not a second account
            platform.auth.request_magic_link(session, email=email, audience="client")
        return
    session.execute(
        update(PortalSignup)
        .where(PortalSignup.email == email, PortalSignup.status == "pending")
        .values(status="superseded")
    )
    raw, hashed = tokens.mint(TOKEN_PREFIX, session.info["tenant_id"])
    row = PortalSignup(
        location_id=data["location_id"], email=email, first_name=data["first_name"], last_name=data["last_name"],
        phone_mobile=data.get("phone_mobile"), birth_on=data.get("birth_on"), token_hash=hashed,
        expires_at=clock.now() + TTL, ip=context.client_ip.get(),
    )  # fmt: skip
    session.add(row)
    session.flush()
    settings = get_settings()
    tenant = platform.service.get_tenant(session)
    # The token rides in the URL fragment (security-baseline 17.2); the confirm page posts it.
    url = f"{settings.app.web_base_url}/f/{tenant.slug}/signup/confirm#token={raw}"
    notifications.send(session, "engagement.portal_signup", email,
                       {"app": settings.app.display_name, "name": row.first_name, "facility": tenant.name,
                        "url": url})  # fmt: skip
    audit.record(session, REQUEST, row, location_id=row.location_id, changes={"status": [None, "pending"]})


def confirm_signup(session: Session, *, token: str, client_kind: str = "web"):
    """Redeem the emailed token: the client, its login, and a session (or an MFA challenge). Errors:
    token-invalid, token-expired."""
    row = session.scalar(select(PortalSignup).where(PortalSignup.token_hash == tokens.digest(token)).with_for_update())
    if row is None or row.status != "pending":
        raise Unauthenticated("This link is not valid or was already used.", code="token-invalid")
    if row.expires_at <= clock.now():
        raise Unauthenticated("This link has expired. Sign up again.", code="token-expired")
    if platform.service.find_client_identity(session, row.email) is not None:
        row.status = "superseded"  # an account was made for this address in the meantime
        raise Unauthenticated("This link is not valid or was already used.", code="token-invalid", persist=True)
    client = clients.service.create_self_service(
        session,
        {"first_name": row.first_name, "last_name": row.last_name, "home_location_id": row.location_id,
         "primary_email": row.email, "phone_mobile": row.phone_mobile, "birth_on": row.birth_on},
        created_via="portal", verified_email=True,
    )  # fmt: skip
    identity = platform.service.create_client_identity(session, row.email)
    identity.status, identity.email_verified_at = "active", clock.now()
    clients.service.link_identity(session, client.id, identity.id)
    row.status, row.confirmed_at, row.client_id = "confirmed", clock.now(), client.id
    session.flush()
    audit.record(session, CONFIRM, row, location_id=row.location_id, changes={"status": ["pending", "confirmed"]})
    events.publish(session, PortalSignupConfirmed(client_id=client.id, location_id=row.location_id), row.id)
    return platform.auth.sign_in_verified(session, identity, client_kind=client_kind, reason="portal_signup")
