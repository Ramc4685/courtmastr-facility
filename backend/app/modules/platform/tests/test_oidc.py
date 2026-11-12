"""Phase 8 S3: OIDC sign-in for staff against an in-process fake provider that signs with a generated key.

The fake speaks discovery, JWKS and the token endpoint through httpx.MockTransport (oidc._transport), and checks
the client secret, the redirect URI and the PKCE verifier like a real provider. The authorization step (the
browser at the provider) is `FakeIdP.authorize`, which reads the URL the API built and mints a code.
"""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.audit import AuditEvent
from app.core.db.session import tenant_session
from app.main import app as fastapi_app
from app.modules.platform import oidc
from app.modules.platform.models import ExternalLogin, Identity, IdentityProviderConfig, StaffUser, Tenant
from conftest import PUBLIC_IP, add_staff, login, make_tenant, scalar

API = "/api/v1"
SECRET = "fake-client-secret-value-for-the-tests"


class FakeIdP:
    issuer = "https://idp.test"

    def __init__(self) -> None:
        self.client_id = f"client-{uuid4().hex[:8]}"
        self.kid, self.key = "k1", rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codes: dict[str, dict] = {}
        self.token_requests = 0
        self.forge = None  # a function nonce -> ID token, standing in for a well-behaved signature

    def jwk(self) -> dict:
        return json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key())) | {"kid": self.kid, "use": "sig"}

    def rotate(self) -> None:
        self.kid, self.key = "k2", rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": self.issuer, "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token", "jwks_uri": f"{self.issuer}/jwks",
                "code_challenge_methods_supported": ["S256"],
            })  # fmt: skip
        if path == "/jwks":
            return httpx.Response(200, json={"keys": [self.jwk()]})
        if path == "/token":
            self.token_requests += 1
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            grant = self.codes.pop(form.get("code", ""), None)  # a code works once
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
            ok = (
                grant is not None and form.get("client_id") == self.client_id and form.get("client_secret") == SECRET
                and form.get("redirect_uri") == grant["redirect_uri"]
                and challenge.rstrip(b"=").decode() == grant["challenge"]
            )  # fmt: skip
            if not ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            nonce = grant["nonce"]
            token = self.forge(nonce) if self.forge else self.id_token(**({"nonce": nonce} | grant["claims"]))
            return httpx.Response(200, json={"id_token": token})
        return httpx.Response(404)

    def id_token(self, *, alg: str = "RS256", key=None, **claims) -> str:
        now = int(time.time())
        body = {
            "iss": self.issuer, "aud": self.client_id, "sub": "subject-1", "email_verified": True,
            "iat": now, "exp": now + 300,
        } | claims  # fmt: skip
        body = {k: v for k, v in body.items() if v is not None}
        return jwt.encode(body, key or self.key, algorithm=alg, headers={"kid": self.kid})

    def authorize(self, url: str, **claims) -> tuple[str, str]:
        """The browser at the provider: sign the user in, redirect back with a code. (state, code)."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert url.startswith(f"{self.issuer}/authorize?")
        assert query["response_type"] == "code" and query["code_challenge_method"] == "S256"
        assert query["client_id"] == self.client_id and query["redirect_uri"].endswith("/auth/oidc/callback")
        code = uuid4().hex
        self.codes[code] = {
            "nonce": query["nonce"], "challenge": query["code_challenge"], "redirect_uri": query["redirect_uri"],
            "claims": claims, "query": query,
        }  # fmt: skip
        return query["state"], code


@pytest.fixture
def idp(monkeypatch):
    fake = FakeIdP()
    monkeypatch.setattr(oidc, "_transport", lambda address: httpx.MockTransport(fake.handle))
    monkeypatch.setattr(oidc, "resolve", lambda host, port: [PUBLIC_IP])
    oidc._cache.clear()
    yield fake
    oidc._cache.clear()


def _configure(client, tenant, idp, **fields) -> dict:
    body = {"preset": "generic", "display_name": "Club SSO", "issuer_url": idp.issuer, "client_id": idp.client_id,
            "client_secret": SECRET} | fields  # fmt: skip
    response = client.post(f"{API}/identity-providers", headers=login(client, tenant), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _browser(ip: str = "testclient") -> TestClient:
    return TestClient(fastapi_app, client=(ip, 50000))


def _start(browser, tenant, provider_id) -> str:
    browser.get(f"{API}/auth/pre-session")
    response = browser.post(
        f"{API}/auth/oidc/authorize", headers={"X-Tenant-Slug": tenant.slug}, json={"provider_id": provider_id}
    )
    assert response.status_code == 200, response.text
    return response.json()["authorization_url"]


def _callback(browser, state, code):
    return browser.post(f"{API}/auth/oidc/callback", json={"state": state, "code": code})


def _sign_in(browser, tenant, idp, provider, **claims):
    state, code = idp.authorize(_start(browser, tenant, provider["id"]), **claims)
    return _callback(browser, state, code)


def _audit(tenant, action):
    return scalar(tenant, select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id.desc()).limit(1))


def _refused(response):
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "oidc-sign-in-refused"
    return response.json()["detail"]


# --- the round trip -----------------------------------------------------------------------------------------------


def test_happy_path_links_by_verified_email_then_matches_on_subject(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    listed = client.get(f"{API}/auth/oidc/providers", headers={"X-Tenant-Slug": tenant.slug}).json()
    assert listed == [{"id": provider["id"], "display_name": "Club SSO", "preset": "generic"}]

    browser = _browser()
    url = _start(browser, tenant, provider["id"])
    assert "prompt" not in url and "code_challenge=" in url
    state, code = idp.authorize(url, email=tenant.owner_email.upper())
    response = _callback(browser, state, code)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "web" and body["principal"]["email"] == tenant.owner_email
    assert body.get("elevated_until_at") is None  # the provider may have answered from its own session
    assert browser.get(f"{API}/me").status_code == 200  # the session cookie works
    link = scalar(tenant, select(ExternalLogin))
    assert (link.issuer, link.subject) == (idp.issuer, "subject-1")
    assert _audit(tenant, "platform.identity.sign_in").reason == "oidc"
    assert _audit(tenant, "platform.identity.oidc_link").changes == {"issuer": idp.issuer}

    # Afterwards the subject decides: a changed (even unverified) email at the provider still signs in.
    again = _sign_in(_browser(), tenant, idp, provider, email="renamed@elsewhere.example", email_verified=False)
    assert again.status_code == 200 and again.json()["principal"]["email"] == tenant.owner_email


def test_wrong_or_foreign_state_is_refused(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    browser = _browser()
    state, code = idp.authorize(_start(browser, tenant, provider["id"]), email=tenant.owner_email)
    forged = f"fho_{tenant.id.hex}_{'x' * 43}"
    assert _callback(browser, forged, code).json()["code"] == "oidc-failed"
    assert _callback(browser, "not-a-state", code).status_code == 401
    # The callback link opened in another browser (no matching pre-session cookie) does not sign that browser in.
    other = _callback(_browser(), state, code)
    assert other.status_code == 401 and other.json()["code"] == "oidc-failed"
    assert _callback(browser, state, code).status_code == 401  # and the state is spent
    assert scalar(tenant, select(ExternalLogin)) is None
    # Nor can a round trip start without a pre-session cookie to bind it to.
    bare = _browser().post(
        f"{API}/auth/oidc/authorize", headers={"X-Tenant-Slug": tenant.slug}, json={"provider_id": provider["id"]}
    )
    assert bare.status_code == 403 and bare.json()["code"] == "csrf-failed"


def test_replayed_code_and_state_are_refused(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    browser = _browser()
    state, code = idp.authorize(_start(browser, tenant, provider["id"]), email=tenant.owner_email)
    assert _callback(browser, state, code).status_code == 200
    replay = _callback(browser, state, code)
    assert replay.status_code == 401 and replay.json()["code"] == "oidc-failed"
    assert idp.token_requests == 1  # refused before the provider is asked again


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "another-nonce"},
        {"aud": "someone-else"},
        {"aud": ["someone-else", "x"]},
        {"iss": "https://evil.test"},
        {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
        {"sub": None},
    ],
    ids=["wrong-nonce", "wrong-audience", "foreign-audiences", "wrong-issuer", "expired", "no-subject"],
)
def test_bad_id_tokens_are_refused(client, tenant, idp, claims):
    provider = _configure(client, tenant, idp)
    response = _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, **claims)
    assert response.status_code == 401 and response.json()["code"] == "oidc-failed", response.text
    assert scalar(tenant, select(ExternalLogin)) is None


def test_tokens_signed_another_way_are_refused(client, tenant, idp):
    """No `none`, no HMAC (alg confusion with the client secret), no key the provider did not publish."""
    provider = _configure(client, tenant, idp)
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    email = tenant.owner_email
    for forge in (
        lambda nonce: idp.id_token(nonce=nonce, alg="HS256", key=SECRET, email=email),
        lambda nonce: idp.id_token(nonce=nonce, key=stranger, email=email),
        lambda nonce: jwt.encode({"iss": idp.issuer, "aud": idp.client_id, "sub": "s", "nonce": nonce}, None, "none"),
    ):
        idp.forge = forge
        response = _sign_in(_browser(), tenant, idp, provider)
        assert response.status_code == 401 and response.json()["code"] == "oidc-failed"
    assert scalar(tenant, select(ExternalLogin)) is None


def test_rotated_signing_key_is_fetched_once(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    assert _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email).status_code == 200
    idp.rotate()  # the cached key set no longer has the token's kid
    assert _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email).status_code == 200


def test_unverified_email_and_unknown_user_get_the_same_refusal(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    unverified = _refused(_sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, email_verified=False))
    unknown = _refused(_sign_in(_browser(), tenant, idp, provider, email=f"nobody@{tenant.slug}.example.com"))
    no_email = _refused(_sign_in(_browser(), tenant, idp, provider))
    assert unverified == unknown == no_email
    assert scalar(tenant, select(ExternalLogin)) is None


def test_never_links_to_a_member_an_unverified_or_a_disabled_identity(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    email, staff_user_id = add_staff(tenant, "front_desk", password=None)
    with tenant_session(tenant.id) as session:
        session.execute(update(Identity).where(Identity.email == email).values(email_verified_at=None))
    _refused(_sign_in(_browser(), tenant, idp, provider, email=email))
    with tenant_session(tenant.id) as session:
        session.execute(update(Identity).where(Identity.email == email).values(email_verified_at=Identity.created_at))
        session.execute(update(StaffUser).where(StaffUser.id == staff_user_id).values(is_active=False))
    _refused(_sign_in(_browser(), tenant, idp, provider, email=email))


def test_allowed_domains_and_disabled_providers(client, tenant, idp):
    provider = _configure(client, tenant, idp, allowed_email_domains=["Staff.Example", "@other.example"])
    assert provider["allowed_email_domains"] == ["other.example", "staff.example"]
    _refused(_sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email))
    headers = login(client, tenant)
    patched = client.patch(f"{API}/identity-providers/{provider['id']}", headers=headers, json={"is_enabled": False})
    assert patched.status_code == 200 and patched.json()["is_enabled"] is False
    assert client.get(f"{API}/auth/oidc/providers", headers={"X-Tenant-Slug": tenant.slug}).json() == []
    browser = _browser()
    browser.get(f"{API}/auth/pre-session")
    started = browser.post(
        f"{API}/auth/oidc/authorize", headers={"X-Tenant-Slug": tenant.slug}, json={"provider_id": provider["id"]}
    )
    assert started.status_code == 404


def test_a_second_account_at_the_same_provider_cannot_take_over_a_link(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    assert _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email).status_code == 200
    _refused(_sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, sub="subject-2"))


def test_subjects_never_cross_tenants(client, idp):
    a, b = make_tenant(), make_tenant()
    provider_a, provider_b = _configure(client, a, idp), _configure(client, b, idp)
    assert _sign_in(_browser(), a, idp, provider_a, email=a.owner_email).status_code == 200
    # The same provider account at B: A's link is invisible there, and A's owner is not B's staff.
    _refused(_sign_in(_browser(), b, idp, provider_b, email=a.owner_email))
    assert scalar(b, select(ExternalLogin)) is None
    # A state minted for A cannot be completed as B: the tenant comes from the state, and B's link stays B's.
    signed = _sign_in(_browser(), b, idp, provider_b, email=b.owner_email)
    assert signed.status_code == 200 and signed.json()["principal"]["email"] == b.owner_email
    assert scalar(b, select(ExternalLogin.identity_id)) != scalar(a, select(ExternalLogin.identity_id))


# --- MFA, IP allow-list ----------------------------------------------------------------------------------------------


def test_mfa_challenge_unless_the_provider_asserts_it(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    with tenant_session(tenant.id) as session:  # the product default: the Owner must use two-step verification
        session.get(Tenant, tenant.id).staff_mfa_policy = "privileged"

    challenge = _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email)
    assert challenge.status_code == 202 and challenge.json()["enrolment_required"] is True
    with tenant_session(tenant.id) as session:
        session.get(IdentityProviderConfig, provider["id"]).asserts_mfa = True
    # Asserted, and the token does not contradict it (no amr): MFA is satisfied by the provider.
    trusted = _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email)
    assert trusted.status_code == 200 and trusted.json()["mfa_verified_at"] is not None
    # Asserted, but the token shows a password only: the normal challenge.
    password_only = _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, amr=["pwd"])
    assert password_only.status_code == 202
    assert _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, amr=["pwd", "otp"]).status_code == 200
    assert _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, acr="urn:x:loa1").status_code == 202


def test_ip_allowlist_applies(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    email, _ = add_staff(tenant, "front_desk", all_locations=True)
    with tenant_session(tenant.id) as session:
        session.get(Tenant, tenant.id).staff_ip_allowlist = ["203.0.113.0/24"]
    outside = _sign_in(_browser("198.51.100.7"), tenant, idp, provider, email=email)
    assert outside.status_code == 403 and outside.json()["code"] == "ip-not-allowed"
    assert _sign_in(_browser("203.0.113.5"), tenant, idp, provider, email=email).status_code == 200


# --- step-up -----------------------------------------------------------------------------------------------------------


def _oidc_admin(client, tenant, idp):
    """An Admin with no password and no factor, signed in through the provider: (browser, provider, csrf token)."""
    provider = _configure(client, tenant, idp)
    email, _ = add_staff(tenant, "admin", password=None, all_locations=True)
    browser = _browser()
    signed = _sign_in(browser, tenant, idp, provider, email=email, sub="admin-subject")
    assert signed.status_code == 200, signed.text
    return browser, provider, signed.json()["csrf_token"]


def test_step_up_round_trip_for_an_oidc_only_user(client, tenant, idp):
    browser, _, csrf = _oidc_admin(client, tenant, idp)
    refused = browser.get(f"{API}/identity-providers")
    assert refused.status_code == 403 and refused.json()["code"] == "step-up-required"
    no_password = browser.post(f"{API}/auth/step-up", json={"password": "guess"}, headers={"X-CSRF-Token": csrf})
    assert no_password.json()["code"] == "step-up-unavailable"

    started = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf})
    assert started.status_code == 200, started.text
    state, code = idp.authorize(started.json()["authorization_url"], sub="admin-subject", auth_time=int(time.time()))
    assert idp.codes[code]["query"]["prompt"] == "login" and idp.codes[code]["query"]["max_age"] == "0"
    rotated = _callback(browser, state, code)
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["elevated_until_at"] is not None and rotated.json()["csrf_token"] != csrf
    assert browser.get(f"{API}/identity-providers").status_code == 200
    assert _audit(tenant, "platform.identity.step_up").reason == "oidc"


def test_step_up_needs_a_fresh_login_by_the_same_user(client, tenant, idp):
    browser, _, csrf = _oidc_admin(client, tenant, idp)

    def attempt(**claims):
        started = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf}).json()
        return _callback(browser, *idp.authorize(started["authorization_url"], **claims))

    stale = attempt(sub="admin-subject", auth_time=int(time.time()) - 3600)
    assert stale.status_code == 403 and stale.json()["code"] == "oidc-reauthentication-stale"
    assert attempt(sub="admin-subject").json()["code"] == "oidc-reauthentication-stale"  # no auth_time at all
    someone_else = attempt(sub="subject-1", email=tenant.owner_email, auth_time=int(time.time()))
    assert someone_else.status_code == 401 and someone_else.json()["code"] == "oidc-failed"
    assert browser.get(f"{API}/identity-providers").status_code == 403  # still not elevated


def test_step_up_needs_the_code_when_the_user_has_a_factor(client, tenant, idp):
    from app.core import clock
    from app.modules.platform import mfa

    browser, provider, csrf = _oidc_admin(client, tenant, idp)
    with tenant_session(tenant.id) as session:
        identity = session.scalar(select(Identity).join(ExternalLogin, ExternalLogin.identity_id == Identity.id))
        mfa.start_enrolment(session, identity)
        mfa.factor(session, identity.id).confirmed_at = clock.now()
    started = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf}).json()
    answer = _callback(
        browser, *idp.authorize(started["authorization_url"], sub="admin-subject", auth_time=int(time.time()))
    )
    assert answer.status_code == 403 and answer.json()["code"] == "step-up-needs-code"


def test_step_up_unavailable_without_a_link(client, tenant):
    browser = _browser()
    signed = browser.post(
        f"{API}/auth/sign-in", headers={"X-Tenant-Slug": tenant.slug},
        json={"email": tenant.owner_email, "password": "correct-horse-battery"},
    )  # fmt: skip
    csrf = signed.json()["csrf_token"]
    answer = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf})
    assert answer.status_code == 403 and answer.json()["code"] == "oidc-step-up-unavailable"


# --- provider settings ---------------------------------------------------------------------------------------------------


def test_the_secret_is_sealed_and_never_shown_or_audited(client, tenant, idp):
    provider = _configure(client, tenant, idp)
    assert "client_secret" not in provider and provider["has_client_secret"] is True
    assert provider["redirect_uri"].endswith("/auth/oidc/callback")
    headers = login(client, tenant)
    patched = client.patch(
        f"{API}/identity-providers/{provider['id']}", headers=headers,
        json={"client_secret": "a-new-secret-value", "asserts_mfa": True},
    )  # fmt: skip
    listed = client.get(f"{API}/identity-providers", headers=headers)
    stored = scalar(tenant, select(IdentityProviderConfig.client_secret_encrypted))
    assert stored.startswith("k1:") and "a-new-secret-value" not in stored
    with tenant_session(tenant.id) as session:
        trail = json.dumps([e.changes for e in session.scalars(select(AuditEvent))])
    for text in (patched.text, listed.text, trail):
        assert SECRET not in text and "a-new-secret-value" not in text
    update_event = _audit(tenant, "platform.identity_provider.update")
    assert update_event.changes == {"asserts_mfa": [False, True], "client_secret": "changed"}
    assert client.delete(f"{API}/identity-providers/{provider['id']}", headers=headers).status_code == 204
    assert _audit(tenant, "platform.identity_provider.delete") is not None


def test_managing_providers_needs_step_up_and_the_key(client, tenant, idp):
    body = {"preset": "generic", "display_name": "X", "issuer_url": idp.issuer, "client_id": "c", "client_secret": "s"}
    stale = client.post(f"{API}/identity-providers", headers=login(client, tenant, elevated=False), json=body)
    assert stale.status_code == 403 and stale.json()["code"] == "step-up-required"
    email, _ = add_staff(tenant, "manager", all_locations=True)
    assert client.get(f"{API}/identity-providers", headers=login(client, tenant, email)).status_code == 403


@pytest.mark.parametrize(
    ("preset", "issuer", "addresses", "code"),
    [
        ("generic", "http://idp.test", [PUBLIC_IP], "url-not-allowed"),
        ("generic", "https://idp.test", ["127.0.0.1"], "url-not-allowed"),
        ("generic", "https://idp.test", ["10.0.0.7"], "url-not-allowed"),
        ("generic", "https://idp.test", ["169.254.169.254"], "url-not-allowed"),
        ("generic", "https://user:pw@idp.test", [PUBLIC_IP], "url-not-allowed"),
        ("generic", "https://other.test", [PUBLIC_IP], "oidc-discovery-failed"),  # its document names idp.test
        ("google", "https://idp.test", [PUBLIC_IP], "oidc-issuer-invalid"),
        ("microsoft", "https://login.microsoftonline.com/common/v2.0", [PUBLIC_IP], "oidc-issuer-invalid"),
    ],
)
def test_issuer_checks_and_ssrf_refusal(client, tenant, idp, monkeypatch, preset, issuer, addresses, code):
    monkeypatch.setattr(oidc, "resolve", lambda host, port: addresses)
    body = {"preset": preset, "display_name": "X", "issuer_url": issuer, "client_id": "c", "client_secret": "s"}
    response = client.post(f"{API}/identity-providers", headers=login(client, tenant), json=body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == code


def test_ssrf_guard_without_the_test_resolver():
    for url in ("https://127.0.0.1/x", "https://localhost/x", "https://[::1]/x", "http://example.com/x"):
        with pytest.raises(oidc.UnsafeUrl):
            oidc._checked_address(url)


def test_microsoft_and_google_email_claims():
    microsoft = IdentityProviderConfig(preset="microsoft")
    google = IdentityProviderConfig(preset="google")
    assert oidc.verified_email(microsoft, {"email": "a@b.example"}) is None  # Entra's email alone is not verified
    assert oidc.verified_email(microsoft, {"email": "A@b.example", "xms_edov": True}) == "a@b.example"
    assert oidc.verified_email(microsoft, {"preferred_username": "a@b.example", "xms_edov": True}) is None
    assert oidc.verified_email(google, {"email": "a@b.example", "email_verified": "true"}) == "a@b.example"
    assert oidc.verified_email(google, {"email": "a@b.example", "xms_edov": True}) is None
    assert oidc.shows_mfa({"amr": ["pwd"]}) is False and oidc.shows_mfa({}) is True


def test_google_issuer_variants(monkeypatch):
    config = IdentityProviderConfig(preset="google", issuer_url=oidc.GOOGLE_ISSUER)
    assert oidc._issuers(config) == [oidc.GOOGLE_ISSUER, "accounts.google.com"]
