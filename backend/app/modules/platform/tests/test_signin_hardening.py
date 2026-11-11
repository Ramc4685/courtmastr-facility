"""Chip S1: the session cookie and CSRF (security-baseline 5.2, 5.3), auth rate limits (6), lockout (5.1),
the common-password list and the staff IP allow-list (PLT-07)."""

from datetime import timedelta

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core import clock, ratelimit
from app.core.audit import AuditEvent
from app.core.auth import tokens
from app.core.settings import get_settings
from app.main import app as fastapi_app
from app.modules.platform.models import AuthSession, Identity
from conftest import PASSWORD, add_staff, login, scalar

API = "/api/v1"
INSIDE, OUTSIDE = "203.0.113.5", "198.51.100.7"
BROWSER = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}


def _sign_in(client, tenant, password=PASSWORD, email=None, headers=None, **extra):
    body = {"email": email or tenant.owner_email, "password": password, **extra}
    return client.post(f"{API}/auth/sign-in", headers={"X-Tenant-Slug": tenant.slug} | (headers or {}), json=body)


def _from(ip: str) -> TestClient:
    return TestClient(fastapi_app, client=(ip, 50000))


# --- cookie and CSRF -----------------------------------------------------------------------------------------


def test_secure_mode_uses_the_host_prefixed_cookie(client, tenant, monkeypatch):
    monkeypatch.setattr(get_settings().auth, "cookie_secure", True)
    (set_cookie,) = _sign_in(client, tenant).headers.get_list("set-cookie")
    name, _, rest = set_cookie.partition("=")
    attributes = sorted(rest.lower().split("; ")[1:])
    assert name == "__Host-fh_session" and attributes == ["httponly", "path=/", "samesite=lax", "secure"]
    pre = client.get(f"{API}/auth/pre-session").headers["set-cookie"]
    assert pre.startswith("__Host-fh_pre=") and "secure" in pre.lower() and "httponly" in pre.lower()


def test_csrf_token_is_stored_hashed_and_rotates_with_the_session(client, tenant):
    first = _sign_in(client, tenant).json()
    stored = scalar(tenant, select(AuthSession.csrf_token_hash).where(AuthSession.id == first["id"]))
    assert stored == tokens.digest(first["csrf_token"]) != first["csrf_token"]
    patch = {"settings": {"onboarding": {"dismissed": ["hours"]}}}
    missing = client.patch(f"{API}/tenant", json=patch)
    assert missing.status_code == 403 and missing.json()["code"] == "csrf-failed"

    second = _sign_in(client, tenant).json()  # a new sign-in is a new session and a new token
    assert second["csrf_token"] != first["csrf_token"]
    assert client.get(f"{API}/auth/session").json()["csrf_token"] == second["csrf_token"]
    stale = client.patch(f"{API}/tenant", json=patch, headers={"X-CSRF-Token": first["csrf_token"]})
    assert stale.status_code == 403 and stale.json()["code"] == "csrf-failed"
    assert client.patch(f"{API}/tenant", json=patch, headers={"X-CSRF-Token": second["csrf_token"]}).status_code == 200


def test_a_mobile_token_in_the_cookie_cannot_mutate(client, tenant):
    """Mobile sessions have no CSRF hash, so carrying one in a cookie never passes the synchroniser check."""
    access = _sign_in(client, tenant, client_kind="mobile").json()["access_token"]
    client.cookies.set("fh_session", f"{access}.forged")
    denied = client.patch(f"{API}/tenant", json={"locale": "en-US"}, headers={"X-CSRF-Token": "forged"})
    assert denied.status_code == 403 and denied.json()["code"] == "csrf-failed"
    # The bearer path for the same token is exempt, as before.
    ok = client.patch(f"{API}/tenant", json={"locale": "en-US"}, headers={"Authorization": f"Bearer {access}"})
    assert ok.status_code == 200


@pytest.mark.parametrize(
    ("path", "body"),
    [("/auth/sign-in", {"password": PASSWORD}), ("/auth/magic-links", {}), ("/auth/password-resets", {})],
)
def test_login_csrf_needs_the_pre_session_token_from_a_browser(client, tenant, path, body):
    body = {"email": tenant.owner_email, **body}
    slug = {"X-Tenant-Slug": tenant.slug}
    for headers in ({}, {"X-CSRF-Token": "guess"}):
        denied = client.post(f"{API}{path}", json=body, headers=slug | BROWSER | headers)
        assert denied.status_code == 403 and denied.json()["code"] == "csrf-failed"
    token = client.get(f"{API}/auth/pre-session").json()["csrf_token"]
    assert client.get(f"{API}/auth/pre-session").json()["csrf_token"] == token  # tabs share the live cookie
    ok = client.post(f"{API}{path}", json=body, headers=slug | BROWSER | {"X-CSRF-Token": token})
    assert ok.status_code in (200, 202)
    # A request without Origin or Sec-Fetch-Site is not a browser (the mobile app) and has no cookie to abuse.
    assert _from(INSIDE).post(f"{API}{path}", json=body, headers=slug).status_code in (200, 202)


# --- rate limits (keys carry a fresh tenant id or a per-test IP, so tests never share a counter) ----------


@pytest.fixture
def limits(monkeypatch):
    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)

    def set_limit(bucket: str, limit: int) -> None:
        monkeypatch.setitem(cfg.buckets, bucket, cfg.buckets[bucket].model_copy(update={"limit": limit}))

    return set_limit


def test_per_identity_limit_beside_the_per_ip_one(tenant, limits):
    limits("sign-in-identity", 2)
    first, second = _from("192.0.2.10"), _from("192.0.2.11")  # different IPs: only the identity bucket counts
    ok = _sign_in(first, tenant, client_kind="mobile")
    assert ok.status_code == 200 and ok.headers["ratelimit-limit"] == "2" and ok.headers["ratelimit-remaining"] == "1"
    assert _sign_in(second, tenant, password="wrong-password-x").status_code == 401
    limited = _sign_in(second, tenant)
    assert limited.status_code == 429 and limited.json()["code"] == "rate-limited"
    assert int(limited.headers["retry-after"]) > 0 and limited.headers["ratelimit-remaining"] == "0"
    # Another address at the same tenant is unaffected.
    email, _ = add_staff(tenant, "admin", all_locations=True)
    assert _sign_in(second, tenant, email=email, client_kind="mobile").status_code == 200


def test_per_address_limit_on_emailed_links(tenant, mailbox, limits):
    limits("link-address", 1)
    body = {"email": tenant.owner_email}
    slug = {"X-Tenant-Slug": tenant.slug}
    assert _from("192.0.2.20").post(f"{API}/auth/magic-links", json=body, headers=slug).status_code == 202
    # The reset request shares the per-address bucket, from any IP.
    assert _from("192.0.2.21").post(f"{API}/auth/password-resets", json=body, headers=slug).status_code == 429
    assert len(mailbox) == 1


def test_closed_buckets_refuse_and_open_ones_allow_when_redis_is_down(client, tenant, limits, monkeypatch):
    down = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    monkeypatch.setattr(ratelimit, "_redis", lambda: down)
    refused = _sign_in(client, tenant, client_kind="mobile")
    assert refused.status_code == 503 and refused.json()["code"] == "rate-limit-unavailable"
    assert refused.headers["retry-after"] == "30"
    # refresh is an open bucket: it reaches the handler, which answers on the token itself.
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": "fhr_x_y"}).status_code == 401


# --- lockout -------------------------------------------------------------------------------------------------


def _fail(client, tenant, times: int) -> list[str]:
    return [_sign_in(client, tenant, password="not-the-password").json()["code"] for _ in range(times)]


def _locked_until(tenant):
    return scalar(tenant, select(Identity.locked_until_at).where(Identity.email == tenant.owner_email))


def test_lockout_doubles_and_mails_once_per_lockout(client, tenant, mailbox):
    cfg = get_settings().auth
    start = clock.now()
    with clock.freeze(start):
        assert set(_fail(client, tenant, cfg.lockout_threshold)) == {"invalid-credentials"}
        assert _fail(client, tenant, 3) == ["identity-locked"] * 3  # refused attempts neither count nor mail
    locks = [m for m in mailbox if "sign-in paused" in m.subject]
    assert len(locks) == 1 and locks[0].to == tenant.owner_email and "15 minutes" in locks[0].body

    second = start + timedelta(minutes=cfg.lockout_min, seconds=1)
    with clock.freeze(second):
        _fail(client, tenant, cfg.lockout_threshold)
    with clock.freeze(second + timedelta(minutes=29)):
        assert _sign_in(client, tenant).json()["code"] == "identity-locked"  # doubled to 30 minutes
    with clock.freeze(second + timedelta(minutes=30, seconds=1)):
        assert _sign_in(client, tenant).status_code == 200  # a proven sign-in ends the doubling
    locks = [m for m in mailbox if "sign-in paused" in m.subject]
    assert len(locks) == 2 and "30 minutes" in locks[1].body
    assert scalar(tenant, select(Identity.lockout_count).where(Identity.email == tenant.owner_email)) == 0


def test_lockout_doubling_is_capped(client, tenant):
    cfg = get_settings().auth
    when, durations = clock.now(), []
    for _ in range(6):
        with clock.freeze(when):
            _fail(client, tenant, cfg.lockout_threshold)
        durations.append(round((_locked_until(tenant) - when).total_seconds() / 60))
        when = _locked_until(tenant) + timedelta(seconds=1)
    assert durations == [15, 30, 60, 120, 240, 240]


def test_failures_outside_the_window_do_not_lock(client, tenant):
    cfg = get_settings().auth
    start = clock.now()
    with clock.freeze(start):
        _fail(client, tenant, cfg.lockout_threshold - 1)
    with clock.freeze(start + timedelta(minutes=cfg.lockout_window_min, seconds=1)):
        assert _fail(client, tenant, 1) == ["invalid-credentials"]  # a new window: count is 1, not 10
        assert _sign_in(client, tenant).status_code == 200


# --- common passwords ----------------------------------------------------------------------------------------


def test_a_common_password_is_refused():
    from app.core.auth import passwords
    from app.core.errors import ValidationFailed

    with pytest.raises(ValidationFailed) as refused:
        passwords.check_policy("unbelievable")  # 12 characters, on the list
    assert refused.value.code == "password-too-weak"
    assert len(passwords._common()) >= 10_000
    passwords.check_policy("correct-horse-battery-staple")


# --- staff IP allow-list (PLT-07) ----------------------------------------------------------------------------


def _allowlist(client, headers, networks):
    return client.patch(f"{API}/security-settings", headers=headers, json={"staff_ip_allowlist": networks})


def test_owner_cannot_save_a_list_that_excludes_their_own_address(tenant):
    inside = _from(INSIDE)
    owner = login(inside, tenant)
    refused = _allowlist(inside, owner, ["198.51.100.0/24"])
    assert refused.status_code == 422 and refused.json()["code"] == "ip-allowlist-excludes-you"
    saved = _allowlist(inside, owner, ["203.0.113.7/24", " 2001:db8::/32 "])
    assert saved.status_code == 200 and saved.json()["staff_ip_allowlist"] == ["203.0.113.0/24", "2001:db8::/32"]
    assert inside.get(f"{API}/security-settings", headers=owner).json() == saved.json()
    bad = _allowlist(inside, owner, ["not-a-network"])
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/staff_ip_allowlist/0"
    assert scalar(tenant, select(func.count()).where(AuditEvent.action == "platform.security.manage")) == 1
    assert _allowlist(inside, owner, []).json()["staff_ip_allowlist"] == []  # empty lifts the restriction


def test_staff_outside_the_list_are_refused_at_sign_in_and_on_every_request(tenant):
    inside, outside = _from(INSIDE), _from(OUTSIDE)
    desk_email, _ = add_staff(tenant, "front_desk", all_locations=True)
    admin_email, _ = add_staff(tenant, "admin", all_locations=True)
    desk_session = login(inside, tenant, desk_email)  # signed in before the list exists
    assert _allowlist(inside, login(inside, tenant), [f"{INSIDE}/32"]).status_code == 200

    refused = _sign_in(outside, tenant, email=desk_email, client_kind="mobile")
    assert refused.status_code == 403 and refused.json()["code"] == "ip-not-allowed"
    assert _sign_in(inside, tenant, email=desk_email, client_kind="mobile").status_code == 200
    assert inside.get(f"{API}/me", headers=desk_session).status_code == 200
    moved = outside.get(f"{API}/me", headers=desk_session)
    assert moved.status_code == 403 and moved.json()["code"] == "ip-not-allowed"
    # The Owner and Admin hold platform.security.bypass_ip_allowlist by default.
    assert _sign_in(outside, tenant, client_kind="mobile").status_code == 200
    assert _sign_in(outside, tenant, email=admin_email, client_kind="mobile").status_code == 200


def test_client_ip_comes_from_the_proxy_header_only_behind_a_trusted_proxy(tenant, monkeypatch):
    owner = login(_from(INSIDE), tenant)
    assert _allowlist(_from(INSIDE), owner, [f"{INSIDE}/32"]).status_code == 200
    desk_email, _ = add_staff(tenant, "front_desk", all_locations=True)
    forged = {"X-Forwarded-For": f"10.9.9.9, {INSIDE}"}
    # An untrusted peer's header is ignored.
    assert _sign_in(_from(OUTSIDE), tenant, email=desk_email, headers=forged).json()["code"] == "ip-not-allowed"
    monkeypatch.setattr(get_settings().api, "trusted_proxies", ["10.0.0.0/8"])
    proxy = _from("10.0.0.2")
    assert _sign_in(proxy, tenant, email=desk_email, client_kind="mobile", headers=forged).status_code == 200
    # Only the right-most untrusted hop counts: a client cannot prepend its way in.
    spoofed = {"X-Forwarded-For": f"{INSIDE}, {OUTSIDE}"}
    assert _sign_in(proxy, tenant, email=desk_email, headers=spoofed).json()["code"] == "ip-not-allowed"
