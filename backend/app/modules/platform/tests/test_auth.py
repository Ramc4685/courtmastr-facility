"""Auth flows end to end: password, magic link, reset, invite, sessions, cookies and CSRF."""

from datetime import timedelta

from sqlalchemy import func, select, text

from app.core import clock
from app.core.audit import AuditEvent
from app.core.db.platform import platform_engine
from app.core.db.session import tenant_session
from app.core.settings import get_settings
from app.modules.platform.models import AuthSession, Identity
from conftest import PASSWORD, add_staff, link_token, login, role_id, scalar

API = "/api/v1"


def _sign_in(client, tenant, password=PASSWORD, email=None, **extra):
    body = {"email": email or tenant.owner_email, "password": password, **extra}
    return client.post(f"{API}/auth/sign-in", headers={"X-Tenant-Slug": tenant.slug}, json=body)


def _bearer(response) -> dict:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_password_sign_in_and_me(client, tenant):
    response = _sign_in(client, tenant, client_kind="mobile")
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"].startswith(f"fhs_{tenant.id.hex}_") and "csrf_token" not in body
    assert body["principal"]["kind"] == "staff" and body["principal"]["display_name"] == "Olive Owner"
    me = client.get(f"{API}/me", headers=_bearer(response)).json()
    assert me["role"]["system_key"] == "owner" and me["has_all_location_access"] is True
    assert me["tenant"]["slug"] == tenant.slug
    keys = {p["key"] for p in me["permissions"]}
    assert "platform.tenant.manage_subscription" in keys  # the owner holds every key, owner-only ones included
    assert client.get(f"{API}/auth/session", headers=_bearer(response)).json()["id"] == body["id"]
    # Only hashes are stored.
    stored = scalar(tenant, select(AuthSession.access_token_hash).where(AuthSession.id == body["id"]))
    assert stored != body["access_token"] and len(stored) == 64


def test_wrong_password_and_unknown_email_look_the_same(client, tenant):
    wrong = _sign_in(client, tenant, password="not-the-password")
    unknown = _sign_in(client, tenant, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.headers["content-type"] == "application/problem+json"
    strip = lambda r: {k: v for k, v in r.json().items() if k != "trace_id"}  # noqa: E731
    assert strip(wrong) == strip(unknown) and wrong.json()["code"] == "invalid-credentials"
    # The failure is recorded even though the request failed (the transaction is committed, not rolled back).
    assert scalar(tenant, select(Identity.failed_attempt_count).where(Identity.email == tenant.owner_email)) == 1
    assert scalar(tenant, select(func.count()).where(AuditEvent.action == "platform.identity.sign_in_failed")) == 1


def test_lockout_blocks_password_but_not_magic_link(client, tenant, mailbox):
    for _ in range(get_settings().auth.lockout_threshold):
        assert _sign_in(client, tenant, password="not-the-password").json()["code"] == "invalid-credentials"
    locked = _sign_in(client, tenant)
    assert locked.status_code == 401 and locked.json()["code"] == "identity-locked"
    with tenant_session(tenant.id) as session:
        assert (
            session.scalar(text("SELECT count(*) FROM outbox_event WHERE event_type = 'platform.identity.locked'")) == 1
        )
    # Magic link still works, proves the mailbox and clears the lockout.
    client.post(f"{API}/auth/magic-links", headers={"X-Tenant-Slug": tenant.slug}, json={"email": tenant.owner_email})
    consumed = client.post(f"{API}/auth/magic-links/consume", json={"token": link_token(mailbox[-1])})
    assert consumed.status_code == 200
    assert _sign_in(client, tenant).status_code == 200
    # The lock also expires on its own.
    for _ in range(get_settings().auth.lockout_threshold):
        _sign_in(client, tenant, password="not-the-password")
    with clock.freeze(clock.now() + timedelta(minutes=16)):
        assert _sign_in(client, tenant).status_code == 200


def test_magic_link_is_single_use_and_does_not_reveal_accounts(client, tenant, mailbox):
    headers = {"X-Tenant-Slug": tenant.slug}
    unknown = client.post(f"{API}/auth/magic-links", headers=headers, json={"email": "nobody@example.com"})
    assert unknown.status_code == 202 and mailbox == []
    known = client.post(
        f"{API}/auth/magic-links", headers=headers, json={"email": tenant.owner_email, "redirect_path": "/calendar"}
    )
    assert known.status_code == 202 and known.content == unknown.content
    message = mailbox[-1]
    assert message.to == tenant.owner_email and message.subject.startswith(get_settings().app.display_name)
    assert "&redirect=/calendar" in message.body
    token = link_token(message)
    first = client.post(f"{API}/auth/magic-links/consume", json={"token": token, "client_kind": "mobile"})
    assert first.status_code == 200 and client.get(f"{API}/me", headers=_bearer(first)).status_code == 200
    again = client.post(f"{API}/auth/magic-links/consume", json={"token": token})
    assert again.status_code == 401 and again.json()["code"] == "token-invalid"
    assert client.post(f"{API}/auth/magic-links/consume", json={"token": "garbage"}).json()["code"] == "token-invalid"
    # An open redirect is never embedded in the link.
    client.post(
        f"{API}/auth/magic-links",
        headers=headers,
        json={"email": tenant.owner_email, "redirect_path": "//evil.example"},
    )
    assert "redirect" not in mailbox[-1].body


def test_magic_link_expires_and_a_newer_link_supersedes_the_older(client, tenant, mailbox):
    headers = {"X-Tenant-Slug": tenant.slug}
    for _ in range(2):
        client.post(f"{API}/auth/magic-links", headers=headers, json={"email": tenant.owner_email})
    older, newer = (link_token(m) for m in mailbox)
    assert client.post(f"{API}/auth/magic-links/consume", json={"token": older}).json()["code"] == "token-invalid"
    with clock.freeze(clock.now() + timedelta(minutes=16)):
        expired = client.post(f"{API}/auth/magic-links/consume", json={"token": newer})
    assert expired.status_code == 401 and expired.json()["code"] == "token-expired"


def test_password_reset_revokes_sessions(client, tenant, mailbox):
    old = login(client, tenant)
    assert (
        client.post(
            f"{API}/auth/password-resets", headers={"X-Tenant-Slug": tenant.slug}, json={"email": tenant.owner_email}
        ).status_code
        == 202
    )
    token = link_token(mailbox[-1])
    assert client.post(f"{API}/auth/password-resets/consume", json={"token": token}).status_code == 422
    weak = client.post(f"{API}/auth/password-resets/consume", json={"token": token, "new_password": "short"})
    assert weak.status_code == 422 and weak.json()["code"] == "password-too-weak"
    assert weak.json()["errors"][0]["pointer"] == "/new_password"
    same_as_email = client.post(
        f"{API}/auth/password-resets/consume", json={"token": token, "new_password": tenant.owner_email}
    )
    assert same_as_email.json()["code"] == "password-too-weak"
    # A rejected password rolls back, so the link is still usable.
    done = client.post(
        f"{API}/auth/password-resets/consume",
        json={"token": token, "new_password": "a-brand-new-passphrase", "client_kind": "mobile"},
    )
    assert done.status_code == 200
    assert client.get(f"{API}/me", headers=old).status_code == 401
    assert client.get(f"{API}/me", headers=_bearer(done)).status_code == 200
    assert _sign_in(client, tenant).status_code == 401
    assert _sign_in(client, tenant, password="a-brand-new-passphrase").status_code == 200


def test_invite_accept_activates_the_identity(client, tenant, owner, mailbox):
    invite = {
        "email": f"coach@{tenant.slug}.example.com",
        "first_name": "Cora",
        "last_name": "Coach",
        "role_id": str(role_id(tenant, "coach")),
    }
    created = client.post(f"{API}/staff-users", headers=owner, json=invite)
    assert created.status_code == 201 and created.json()["identity_status"] == "invited"
    token = link_token(mailbox[-1])
    assert "/auth/accept-invite?token=" in mailbox[-1].body and "7 days" in mailbox[-1].body
    # Invited identities cannot sign in by magic link before accepting.
    client.post(f"{API}/auth/magic-links", headers={"X-Tenant-Slug": tenant.slug}, json={"email": invite["email"]})
    assert len(mailbox) == 1
    accepted = client.post(
        f"{API}/auth/invitations/accept",
        json={"token": token, "new_password": "cora-coaches-tennis", "client_kind": "mobile"},
    )
    assert accepted.status_code == 200
    me = client.get(f"{API}/me", headers=_bearer(accepted)).json()
    assert me["role"]["system_key"] == "coach" and me["permissions"] == []
    assert client.post(f"{API}/auth/invitations/accept", json={"token": token}).json()["code"] == "token-invalid"
    assert _sign_in(client, tenant, email=invite["email"], password="cora-coaches-tennis").status_code == 200
    assert client.post(f"{API}/staff-users/{created.json()['id']}/invitation/resend", headers=owner).status_code == 409


def test_invite_accept_without_password_stays_on_magic_link(client, tenant, owner, mailbox):
    invite = {
        "email": f"desk@{tenant.slug}.example.com",
        "first_name": "Dee",
        "last_name": "Desk",
        "role_id": str(role_id(tenant, "front_desk")),
    }
    client.post(f"{API}/staff-users", headers=owner, json=invite)
    assert client.post(f"{API}/auth/invitations/accept", json={"token": link_token(mailbox[-1])}).status_code == 200
    assert _sign_in(client, tenant, email=invite["email"], password="anything-at-all-12").status_code == 401
    client.post(f"{API}/auth/magic-links", headers={"X-Tenant-Slug": tenant.slug}, json={"email": invite["email"]})
    assert client.post(f"{API}/auth/magic-links/consume", json={"token": link_token(mailbox[-1])}).status_code == 200


def test_refresh_rotates_and_detects_reuse(client, tenant):
    first = _sign_in(client, tenant, client_kind="mobile").json()
    second = client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    second = second.json()
    assert second["id"] == first["id"] and second["refresh_token"] != first["refresh_token"]
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {first['access_token']}"}).status_code == 401
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {second['access_token']}"}).status_code == 200
    # The immediately previous refresh token is tolerated inside the grace window (concurrent tabs).
    third = client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert third.status_code == 200
    # Outside it, a rotated-away token is a theft signal: the whole session is revoked.
    with clock.freeze(clock.now() + timedelta(seconds=60)):
        reuse = client.post(f"{API}/auth/refresh", json={"refresh_token": second["refresh_token"]})
        assert reuse.status_code == 401 and reuse.json()["code"] == "refresh-reuse-detected"
        latest = client.post(f"{API}/auth/refresh", json={"refresh_token": third.json()["refresh_token"]})
        assert latest.status_code == 401 and latest.json()["code"] == "session-revoked"
    assert scalar(tenant, select(AuthSession.revoked_reason).where(AuthSession.id == first["id"])) == "rotation_reuse"
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": "fhr_nope"}).json()["code"] == "session-revoked"
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_session_expiry(client, tenant):
    session = _sign_in(client, tenant, client_kind="mobile").json()
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    with clock.freeze(clock.now() + timedelta(minutes=31)):
        assert client.get(f"{API}/me", headers=headers).status_code == 401  # access token is 30 minutes
        assert client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 200
    with clock.freeze(clock.now() + timedelta(hours=13)):  # past the staff idle window
        assert client.post(f"{API}/auth/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 401


def test_sign_out_and_session_management(client, tenant):
    one, two = login(client, tenant), login(client, tenant)
    sessions = client.get(f"{API}/auth/sessions", headers=one).json()
    assert len(sessions) == 2 and sum(s["is_current"] for s in sessions) == 1
    other = next(s["id"] for s in sessions if not s["is_current"])
    assert client.delete(f"{API}/auth/sessions/{other}", headers=one).status_code == 204
    assert client.get(f"{API}/me", headers=two).status_code == 401
    assert client.delete(f"{API}/auth/sessions/{tenant.id}", headers=one).status_code == 404
    assert client.post(f"{API}/auth/sign-out", headers=one).status_code == 204
    assert client.get(f"{API}/me", headers=one).status_code == 401
    assert client.get(f"{API}/me").status_code == 401
    assert client.get(f"{API}/me", headers={"Authorization": "Bearer fhs_not-a-token"}).status_code == 401


def test_change_own_password(client, tenant):
    here, elsewhere = login(client, tenant), login(client, tenant)
    wrong = client.post(
        f"{API}/auth/password",
        headers=here,
        json={"current_password": "nope", "new_password": "another-long-passphrase"},
    )
    assert wrong.status_code == 401
    ok = client.post(
        f"{API}/auth/password",
        headers=here,
        json={"current_password": PASSWORD, "new_password": "another-long-passphrase"},
    )
    assert ok.status_code == 204
    assert client.get(f"{API}/me", headers=here).status_code == 200  # this session survives
    assert client.get(f"{API}/me", headers=elsewhere).status_code == 401  # the others do not
    assert _sign_in(client, tenant, password="another-long-passphrase").status_code == 200


def test_password_change_sends_a_notification(client, tenant, mailbox):
    here = login(client, tenant)
    body = {"current_password": PASSWORD, "new_password": "another-long-passphrase"}
    assert client.post(f"{API}/auth/password", headers=here, json=body).status_code == 204
    assert mailbox[-1].to == tenant.owner_email and "password was changed" in mailbox[-1].subject


def test_first_password_needs_a_fresh_magic_link_session(client, tenant, owner, mailbox):
    email, _ = add_staff(tenant, "front_desk", password=None)
    body = {"new_password": "a-first-long-passphrase"}

    def magic_link_session() -> dict:
        client.post(f"{API}/auth/magic-links", headers={"X-Tenant-Slug": tenant.slug}, json={"email": email})
        consumed = client.post(
            f"{API}/auth/magic-links/consume", json={"token": link_token(mailbox[-1]), "client_kind": "mobile"}
        )
        return _bearer(consumed)

    def refused(response) -> bool:
        return response.status_code == 403 and response.json()["code"] == "password-reset-required"

    # A magic-link session older than the proof window cannot set a first password (stolen-session case).
    stale = magic_link_session()
    with clock.freeze(clock.now() + timedelta(minutes=16)):
        assert refused(client.post(f"{API}/auth/password", headers=stale, json=body))
    # Nor can a session established some other way, however fresh: here an invite accepted without a password.
    invite = {"email": f"new@{tenant.slug}.example.com", "first_name": "N", "last_name": "U"}
    client.post(f"{API}/staff-users", headers=owner, json=invite | {"role_id": str(role_id(tenant, "front_desk"))})
    accepted = client.post(
        f"{API}/auth/invitations/accept", json={"token": link_token(mailbox[-1]), "client_kind": "mobile"}
    )
    assert refused(client.post(f"{API}/auth/password", headers=_bearer(accepted), json=body))
    assert scalar(tenant, select(Identity.password_hash).where(Identity.email == email)) is None

    # A fresh magic-link session can, and the owner of the mailbox is told.
    mailbox.clear()
    assert client.post(f"{API}/auth/password", headers=magic_link_session(), json=body).status_code == 204
    assert mailbox[-1].to == email and "password was changed" in mailbox[-1].subject
    assert _sign_in(client, tenant, email=email, password=body["new_password"]).status_code == 200


def test_web_session_uses_cookies_and_csrf(client, tenant):
    response = _sign_in(client, tenant)  # client_kind defaults to web
    body = response.json()
    assert "access_token" not in body and "refresh_token" not in body
    set_cookie = response.headers["set-cookie"].lower()
    assert "fh_access=" in set_cookie and "httponly" in set_cookie and "samesite=lax" in set_cookie
    assert client.get(f"{API}/me").status_code == 200  # the cookie alone authenticates safe methods
    assert client.get(f"{API}/auth/session").json()["csrf_token"] == body["csrf_token"]
    patch = {"settings": {"onboarding": {"dismissed": ["hours"]}}}
    denied = client.patch(f"{API}/tenant", json=patch)
    assert denied.status_code == 403 and denied.json()["code"] == "csrf-failed"
    assert client.patch(f"{API}/tenant", json=patch, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.patch(f"{API}/tenant", json=patch, headers={"X-CSRF-Token": body["csrf_token"]}).status_code == 200
    # Refresh from the cookie rotates both cookies and the CSRF token with them.
    refreshed = client.post(f"{API}/auth/refresh")
    assert refreshed.status_code == 200 and refreshed.json()["csrf_token"] != body["csrf_token"]
    assert (
        client.post(f"{API}/auth/sign-out", headers={"X-CSRF-Token": refreshed.json()["csrf_token"]}).status_code == 204
    )
    assert client.get(f"{API}/me").status_code == 401


def test_client_identity_is_a_separate_principal_kind(client, tenant):
    """Staff and clients share the email namespace per kind, not across kinds."""
    from app.core.auth import passwords

    with tenant_session(tenant.id) as session:
        session.add(
            Identity(
                kind="client",
                email=tenant.owner_email,
                status="active",
                password_hash=passwords.hash_password("member-passphrase-1"),
            )
        )
    assert _sign_in(client, tenant, password="member-passphrase-1").status_code == 401  # staff audience by default
    headers = login(client, tenant, password="member-passphrase-1", audience="client")
    me = client.get(f"{API}/me", headers=headers).json()
    assert me["principal"]["kind"] == "client" and me["role"] is None and me["permissions"] is None
    for path in ("/tenant", "/locations", "/staff-users", "/roles", "/audit-events"):
        assert client.get(f"{API}{path}", headers=headers).status_code == 403


def test_deactivation_and_expiry_are_immediate(client, tenant, owner):
    email, staff_user_id = add_staff(tenant, "admin", all_locations=True)
    admin = login(client, tenant, email)
    assert client.get(f"{API}/me", headers=admin).status_code == 200
    assert client.post(f"{API}/staff-users/{staff_user_id}/deactivate", headers=owner).status_code == 200
    assert client.get(f"{API}/me", headers=admin).status_code == 401
    assert _sign_in(client, tenant, email=email).status_code == 401
    client.post(f"{API}/staff-users/{staff_user_id}/reactivate", headers=owner)
    admin = login(client, tenant, email)
    yesterday = (clock.now() - timedelta(days=1)).date().isoformat()
    client.patch(f"{API}/staff-users/{staff_user_id}", headers=owner, json={"access_expires_on": yesterday})
    assert client.get(f"{API}/me", headers=admin).status_code == 401  # time-boxed access has run out


def test_tenant_resolution(client, tenant, owner):
    body = {"email": tenant.owner_email, "password": PASSWORD}
    by_host = client.post(f"{API}/auth/sign-in", headers={"Host": f"{tenant.slug}.localhost:8100"}, json=body)
    assert by_host.status_code == 200
    unknown = client.post(f"{API}/auth/sign-in", headers={"X-Tenant-Slug": "no-such-tenant"}, json=body)
    assert unknown.status_code == 404 and unknown.json()["code"] == "tenant-not-found"
    assert client.post(f"{API}/auth/sign-in", json=body).status_code == 404
    # A suspended tenant's sessions stop working on the next request.
    with platform_engine().begin() as conn:
        conn.execute(text("UPDATE tenant SET status = 'suspended' WHERE id = :id"), {"id": tenant.id})
    suspended = client.get(f"{API}/me", headers=owner)
    assert suspended.status_code == 403 and suspended.json()["code"] == "tenant-suspended"


def test_rate_limit_on_auth_endpoints(client, tenant, monkeypatch):
    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setattr(cfg, "auth_per_minute", 2)
    statuses = [_sign_in(client, tenant, password="not-the-password").status_code for _ in range(4)]
    assert statuses[-1] == 429
    limited = _sign_in(client, tenant)
    assert limited.json()["code"] == "rate-limited" and limited.headers["retry-after"] == "60"
