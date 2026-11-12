"""Phase 8 S3: OIDC sign-in for staff against an in-process fake provider that signs with a generated key.

The fake speaks discovery, JWKS and the token endpoint through httpx.MockTransport (oidc._transport), and checks
the client secret, the redirect URI and the PKCE verifier like a real provider. The authorization step (the
browser at the provider) is `FakeIdP.authorize`, which reads the URL the API built and mints a code.

A provider account signs in only once linked, and a link is stored only when the matched user redeems the
emailed confirmation in the same browser (`_connect`). The issuer's email claim alone never signs anyone in.
"""

import base64
import hashlib
import json
import socket
import threading
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
from conftest import PUBLIC_IP, add_staff, link_token, login, make_tenant, scalar

API = "/api/v1"
SECRET = "fake-client-secret-value-for-the-tests"


class FakeIdP:
    issuer = "https://idp.test"

    def __init__(self) -> None:
        self.client_id = f"client-{uuid4().hex[:8]}"
        self.kid, self.key = "k1", rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codes: dict[str, dict] = {}
        self.token_requests = 0
        self.requests: list[httpx.Request] = []
        self.forge = None  # a function nonce -> ID token, standing in for a well-behaved signature
        self.discovery: httpx.Response | None = None  # an answer to give instead of the discovery document

    def jwk(self) -> dict:
        return json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key())) | {"kid": self.kid, "use": "sig"}

    def rotate(self) -> None:
        self.kid, self.key = "k2", rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return self.discovery or httpx.Response(200, json={
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


def _pending(response) -> dict:
    assert response.status_code == 202 and response.json() == {"link_pending": True, "display_name": "Club SSO"}
    return response.json()


def _confirm(browser, token):
    return browser.post(f"{API}/auth/oidc/link", json={"token": token})


def _connect(tenant, idp, provider, mailbox, *, browser=None, **claims) -> TestClient:
    """A first sign-in, then the emailed confirmation redeemed in the same browser: the account is linked."""
    browser = browser or _browser()
    mailbox.clear()
    _pending(_sign_in(browser, tenant, idp, provider, **claims))
    assert len(mailbox) == 1 and "/auth/oidc/link#token=" in mailbox[0].body
    confirmed = _confirm(browser, link_token(mailbox[0]))
    assert confirmed.status_code == 200 and confirmed.json() == {"display_name": "Club SSO"}, confirmed.text
    mailbox.clear()
    return browser


def _audit(tenant, action):
    return scalar(tenant, select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id.desc()).limit(1))


def _refused(response):
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "oidc-sign-in-refused"
    return response.json()["detail"]


# --- the round trip -----------------------------------------------------------------------------------------------


def test_happy_path_links_by_emailed_confirmation_then_matches_on_subject(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp)
    listed = client.get(f"{API}/auth/oidc/providers", headers={"X-Tenant-Slug": tenant.slug}).json()
    assert listed == [{"id": provider["id"], "display_name": "Club SSO", "preset": "generic"}]

    browser = _browser()
    url = _start(browser, tenant, provider["id"])
    assert "prompt" not in url and "code_challenge=" in url
    state, code = idp.authorize(url, email=tenant.owner_email.upper())
    _pending(_callback(browser, state, code))  # a first sign-in: no session, nothing linked yet
    assert browser.get(f"{API}/me").status_code == 401
    assert scalar(tenant, select(ExternalLogin)) is None
    assert [m.to for m in mailbox] == [tenant.owner_email]
    assert _audit(tenant, "platform.identity.oidc_link_requested").changes == {"issuer": idp.issuer}

    assert _confirm(browser, link_token(mailbox[0])).status_code == 200
    link = scalar(tenant, select(ExternalLogin))
    assert (link.issuer, link.subject) == (idp.issuer, "subject-1")
    assert _audit(tenant, "platform.identity.oidc_link").changes == {"issuer": idp.issuer}
    assert browser.get(f"{API}/me").status_code == 401  # confirming links; it does not sign in

    response = _sign_in(browser, tenant, idp, provider, email=tenant.owner_email)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "web" and body["principal"]["email"] == tenant.owner_email
    assert body.get("elevated_until_at") is None  # the provider may have answered from its own session
    assert browser.get(f"{API}/me").status_code == 200  # the session cookie works
    assert _audit(tenant, "platform.identity.sign_in").reason == "oidc"

    # Afterwards the subject decides: a changed (even unverified) email at the provider still signs in.
    again = _sign_in(_browser(), tenant, idp, provider, email="renamed@elsewhere.example", email_verified=False)
    assert again.status_code == 200 and again.json()["principal"]["email"] == tenant.owner_email


def test_an_issuer_claiming_the_owners_email_never_signs_in_as_the_owner(client, tenant, idp, mailbox):
    """The review's Admin-to-Owner takeover: whoever runs the issuer controls its claims. A verified email claim
    (and an MFA claim on a provider trusted for MFA) is not enough; only the Owner's own mailbox can link."""
    provider = _configure(client, tenant, idp, asserts_mfa=True)
    attacker = _browser()
    answer = _sign_in(attacker, tenant, idp, provider, email=tenant.owner_email, sub="attacker", amr=["mfa"])
    _pending(answer)
    assert "csrf_token" not in answer.text and "set-cookie" not in {k.lower() for k in answer.headers}
    assert attacker.get(f"{API}/me").status_code == 401
    assert scalar(tenant, select(ExternalLogin)) is None
    # The Owner, who did not ask, may click the link from their own browser: it does not connect the account.
    owner_browser = _browser()
    owner_browser.get(f"{API}/auth/pre-session")
    other = _confirm(owner_browser, link_token(mailbox[-1]))
    assert other.status_code == 401 and other.json()["code"] == "oidc-link-other-browser"
    assert _confirm(attacker, link_token(mailbox[-1])).json()["code"] == "token-invalid"  # and it is spent
    assert scalar(tenant, select(ExternalLogin)) is None
    _pending(_sign_in(attacker, tenant, idp, provider, email=tenant.owner_email, sub="attacker", amr=["mfa"]))


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
    _pending(_callback(browser, state, code))
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
def test_bad_id_tokens_are_refused(client, tenant, idp, mailbox, claims):
    provider = _configure(client, tenant, idp)
    response = _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, **claims)
    assert response.status_code == 401 and response.json()["code"] == "oidc-failed", response.text
    assert scalar(tenant, select(ExternalLogin)) is None and mailbox == []


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


def test_rotated_signing_key_is_fetched_once(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp)
    _connect(tenant, idp, provider, mailbox, email=tenant.owner_email)
    idp.rotate()  # the cached key set no longer has the token's kid
    assert _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email).status_code == 200


def test_first_sign_ins_answer_the_same_whether_or_not_anyone_matched(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp)
    unverified = _pending(_sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, email_verified=False))
    unknown = _pending(_sign_in(_browser(), tenant, idp, provider, email=f"nobody@{tenant.slug}.example.com"))
    no_email = _pending(_sign_in(_browser(), tenant, idp, provider))
    assert mailbox == []  # nobody matched, nobody was emailed
    matched = _pending(_sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email))
    assert unverified == unknown == no_email == matched and len(mailbox) == 1
    assert scalar(tenant, select(ExternalLogin)) is None


def test_never_links_to_a_member_an_unverified_or_a_disabled_identity(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp)
    email, staff_user_id = add_staff(tenant, "front_desk", password=None)
    with tenant_session(tenant.id) as session:
        session.execute(update(Identity).where(Identity.email == email).values(email_verified_at=None))
    _pending(_sign_in(_browser(), tenant, idp, provider, email=email))
    with tenant_session(tenant.id) as session:
        session.execute(update(Identity).where(Identity.email == email).values(email_verified_at=Identity.created_at))
        session.execute(update(StaffUser).where(StaffUser.id == staff_user_id).values(is_active=False))
    _pending(_sign_in(_browser(), tenant, idp, provider, email=email))
    assert mailbox == []


def test_a_link_confirmed_after_the_user_was_disabled_is_refused(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp)
    email, staff_user_id = add_staff(tenant, "front_desk", password=None)
    browser = _browser()
    _pending(_sign_in(browser, tenant, idp, provider, email=email))
    with tenant_session(tenant.id) as session:
        session.execute(update(StaffUser).where(StaffUser.id == staff_user_id).values(is_active=False))
    assert _confirm(browser, link_token(mailbox[-1])).json()["code"] == "token-invalid"
    assert scalar(tenant, select(ExternalLogin)) is None


def test_a_linked_account_whose_user_was_disabled_is_refused(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp)
    email, staff_user_id = add_staff(tenant, "front_desk", password=None, all_locations=True)
    _connect(tenant, idp, provider, mailbox, email=email)
    with tenant_session(tenant.id) as session:
        session.execute(update(StaffUser).where(StaffUser.id == staff_user_id).values(is_active=False))
    _refused(_sign_in(_browser(), tenant, idp, provider, email=email))


def test_allowed_domains_and_disabled_providers(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp, allowed_email_domains=["Staff.Example", "@other.example"])
    assert provider["allowed_email_domains"] == ["other.example", "staff.example"]
    _pending(_sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email))
    assert mailbox == []  # outside the allowed domains: nobody is emailed
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


def test_a_second_account_at_the_same_provider_cannot_take_over_a_link(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp)
    _connect(tenant, idp, provider, mailbox, email=tenant.owner_email)
    _pending(_sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, sub="subject-2"))
    assert mailbox == []  # the owner already has an account at this provider: no second link is offered
    assert scalar(tenant, select(ExternalLogin.subject)) == "subject-1"


def test_subjects_never_cross_tenants(client, idp, mailbox):
    a, b = make_tenant(), make_tenant()
    provider_a, provider_b = _configure(client, a, idp), _configure(client, b, idp)
    _connect(a, idp, provider_a, mailbox, email=a.owner_email)
    # The same provider account at B: A's link is invisible there, and A's owner is not B's staff.
    _pending(_sign_in(_browser(), b, idp, provider_b, email=a.owner_email))
    assert mailbox == [] and scalar(b, select(ExternalLogin)) is None
    # B's owner links their own account at B; the two links stay apart.
    browser = _connect(b, idp, provider_b, mailbox, email=b.owner_email, sub="subject-b")
    signed = _sign_in(browser, b, idp, provider_b, email=b.owner_email, sub="subject-b")
    assert signed.status_code == 200 and signed.json()["principal"]["email"] == b.owner_email
    assert scalar(b, select(ExternalLogin.identity_id)) != scalar(a, select(ExternalLogin.identity_id))


# --- MFA, IP allow-list ----------------------------------------------------------------------------------------------


def test_mfa_challenge_unless_the_provider_asserts_it_and_the_token_shows_it(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp)
    _connect(tenant, idp, provider, mailbox, email=tenant.owner_email)
    with tenant_session(tenant.id) as session:  # the product default: the Owner must use two-step verification
        session.get(Tenant, tenant.id).staff_mfa_policy = "privileged"

    def sign_in(**claims):
        return _sign_in(_browser(), tenant, idp, provider, email=tenant.owner_email, **claims)

    challenge = sign_in()
    assert challenge.status_code == 202 and challenge.json()["enrolment_required"] is True
    with tenant_session(tenant.id) as session:
        session.get(IdentityProviderConfig, provider["id"]).asserts_mfa = True
    # Asserted, but the token shows nothing (no amr, no acr): the tenant's flag alone is no evidence.
    assert "mfa_token" in sign_in().json()
    assert "mfa_token" in sign_in(amr=["pwd"]).json()  # a password only
    assert "mfa_token" in sign_in(acr="urn:x:loa1").json()
    trusted = sign_in(amr=["pwd", "otp"])
    assert trusted.status_code == 200 and trusted.json()["mfa_verified_at"] is not None
    assert "mfa_token" in sign_in(amr=["hwk"]).json()  # one factor, however strong
    assert sign_in(acr="http://schemas.openid.net/pape/policies/2007/06/multi-factor").status_code == 200


def test_ip_allowlist_applies(client, tenant, idp, mailbox):
    provider = _configure(client, tenant, idp)
    email, _ = add_staff(tenant, "front_desk", all_locations=True)
    _connect(tenant, idp, provider, mailbox, browser=_browser("203.0.113.5"), email=email)
    with tenant_session(tenant.id) as session:
        session.get(Tenant, tenant.id).staff_ip_allowlist = ["203.0.113.0/24"]
    outside = _sign_in(_browser("198.51.100.7"), tenant, idp, provider, email=email)
    assert outside.status_code == 403 and outside.json()["code"] == "ip-not-allowed"
    assert _sign_in(_browser("203.0.113.5"), tenant, idp, provider, email=email).status_code == 200


# --- step-up -----------------------------------------------------------------------------------------------------------


def _oidc_user(client, tenant, idp, mailbox, role="admin", ip="testclient"):
    """A staff user with no password and no factor, signed in through the provider: (browser, provider, csrf)."""
    provider = _configure(client, tenant, idp)
    email, _ = add_staff(tenant, role, password=None, all_locations=True)
    browser = _connect(tenant, idp, provider, mailbox, browser=_browser(ip), email=email, sub="admin-subject")
    signed = _sign_in(browser, tenant, idp, provider, email=email, sub="admin-subject")
    assert signed.status_code == 200, signed.text
    return browser, provider, signed.json()["csrf_token"]


def test_step_up_round_trip_for_an_oidc_only_user(client, tenant, idp, mailbox):
    browser, _, csrf = _oidc_user(client, tenant, idp, mailbox)
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


def test_step_up_needs_a_fresh_login_by_the_same_user(client, tenant, idp, mailbox):
    browser, _, csrf = _oidc_user(client, tenant, idp, mailbox)

    def attempt(**claims):
        started = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf}).json()
        return _callback(browser, *idp.authorize(started["authorization_url"], **claims))

    stale = attempt(sub="admin-subject", auth_time=int(time.time()) - 3600)
    assert stale.status_code == 403 and stale.json()["code"] == "oidc-reauthentication-stale"
    assert attempt(sub="admin-subject").json()["code"] == "oidc-reauthentication-stale"  # no auth_time at all
    someone_else = attempt(sub="subject-1", email=tenant.owner_email, auth_time=int(time.time()))
    assert someone_else.status_code == 401 and someone_else.json()["code"] == "oidc-failed"
    assert browser.get(f"{API}/identity-providers").status_code == 403  # still not elevated


def test_step_up_needs_the_code_when_the_user_has_a_factor(client, tenant, idp, mailbox):
    from app.core import clock
    from app.modules.platform import mfa

    browser, provider, csrf = _oidc_user(client, tenant, idp, mailbox)
    with tenant_session(tenant.id) as session:
        identity = session.scalar(select(Identity).join(ExternalLogin, ExternalLogin.identity_id == Identity.id))
        mfa.start_enrolment(session, identity)
        mfa.factor(session, identity.id).confirmed_at = clock.now()
    started = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf}).json()
    answer = _callback(
        browser, *idp.authorize(started["authorization_url"], sub="admin-subject", auth_time=int(time.time()))
    )
    assert answer.status_code == 403 and answer.json()["code"] == "step-up-needs-code"


def test_step_up_round_trip_obeys_the_ip_allowlist(client, tenant, idp, mailbox):
    """Both legs of the step-up authenticate the session, and that checks the staff IP allow-list."""
    browser, _, csrf = _oidc_user(client, tenant, idp, mailbox, role="front_desk", ip="203.0.113.5")
    started = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf}).json()
    with tenant_session(tenant.id) as session:
        session.get(Tenant, tenant.id).staff_ip_allowlist = ["192.0.2.0/24"]
    finished = _callback(
        browser, *idp.authorize(started["authorization_url"], sub="admin-subject", auth_time=int(time.time()))
    )
    assert finished.status_code == 403 and finished.json()["code"] == "ip-not-allowed"
    again = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf})
    assert again.status_code == 403 and again.json()["code"] == "ip-not-allowed"


def test_step_up_unavailable_without_a_link(client, tenant):
    browser = _browser()
    signed = browser.post(
        f"{API}/auth/sign-in", headers={"X-Tenant-Slug": tenant.slug},
        json={"email": tenant.owner_email, "password": "correct-horse-battery"},
    )  # fmt: skip
    csrf = signed.json()["csrf_token"]
    answer = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf})
    assert answer.status_code == 403 and answer.json()["code"] == "oidc-step-up-unavailable"


def test_step_up_after_the_pre_session_cookie_lapsed(client, tenant, idp, mailbox):
    """The pre-session cookie lives an hour; the session lives longer. A fresh GET /auth/pre-session (the web
    client makes one before the step-up POST) is all a lapsed cookie needs, and the state stays bound to it."""
    from app.core.auth.deps import pre_session_cookie

    browser, _, csrf = _oidc_user(client, tenant, idp, mailbox)
    for cookie in [c for c in browser.cookies.jar if c.name == pre_session_cookie()]:
        browser.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
    lapsed = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf})
    assert lapsed.status_code == 403 and lapsed.json()["code"] == "csrf-failed"

    assert browser.get(f"{API}/auth/pre-session").status_code == 200
    started = browser.post(f"{API}/auth/oidc/step-up", headers={"X-CSRF-Token": csrf})
    assert started.status_code == 200, started.text
    state, code = idp.authorize(started.json()["authorization_url"], sub="admin-subject", auth_time=int(time.time()))
    assert _callback(browser, state, code).json()["elevated_until_at"] is not None


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


def test_only_the_owner_changes_providers_admins_may_read(client, tenant, idp):
    """A provider decides who can sign in, so changing one is Owner-only (`platform.identity_provider.manage`)."""
    provider = _configure(client, tenant, idp)
    email, _ = add_staff(tenant, "admin", all_locations=True)
    admin = login(client, tenant, email)  # a fresh password sign-in: elevated
    assert client.get(f"{API}/identity-providers", headers=admin).status_code == 200
    assert client.get(f"{API}/identity-providers/{provider['id']}", headers=admin).status_code == 200
    body = {"preset": "generic", "display_name": "Mine", "issuer_url": "https://mine.test", "client_id": "c",
            "client_secret": "s"}  # fmt: skip
    attempts = [
        client.post(f"{API}/identity-providers", headers=admin, json=body),
        client.patch(f"{API}/identity-providers/{provider['id']}", headers=admin, json={"client_id": "x"}),
        client.patch(f"{API}/identity-providers/{provider['id']}", headers=admin, json={"display_name": "x"}),
        client.delete(f"{API}/identity-providers/{provider['id']}", headers=admin),
    ]
    for response in attempts:
        assert response.status_code == 403 and response.json()["code"] != "step-up-required", response.text
    assert scalar(tenant, select(IdentityProviderConfig.client_id)) == idp.client_id


@pytest.mark.parametrize(
    ("preset", "issuer", "addresses", "code"),
    [
        ("generic", "http://idp.test", [PUBLIC_IP], "url-not-allowed"),
        ("generic", "https://idp.test", ["127.0.0.1"], "url-not-allowed"),
        ("generic", "https://idp.test", ["10.0.0.7"], "url-not-allowed"),
        ("generic", "https://idp.test", ["169.254.169.254"], "url-not-allowed"),
        ("generic", "https://idp.test", [], "url-not-allowed"),  # does not resolve
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


def test_the_ssrf_refusal_says_the_same_for_private_and_unresolvable_hosts(client, tenant, idp, monkeypatch):
    def unresolvable(host, port):
        raise OSError("no such host")

    details = []
    for resolver in (unresolvable, lambda host, port: ["10.0.0.7"], lambda host, port: [PUBLIC_IP, "127.0.0.1"]):
        monkeypatch.setattr(oidc, "resolve", resolver)
        oidc._cache.clear()
        body = {"preset": "generic", "display_name": "X", "issuer_url": "https://h.test", "client_id": "c",
                "client_secret": "s"}  # fmt: skip
        details.append(client.post(f"{API}/identity-providers", headers=login(client, tenant), json=body).json())
    assert {d["code"] for d in details} == {"url-not-allowed"} and len({d["detail"] for d in details}) == 1


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


def test_mfa_needs_evidence_in_the_token():
    assert oidc.shows_mfa({}) is False  # neither amr nor acr: no evidence
    assert oidc.shows_mfa({"amr": ["pwd"]}) is False and oidc.shows_mfa({"amr": "otp"}) is False
    # One method alone is one factor, however strong: a passkey, a code, a text message.
    for single in (["hwk"], ["swk"], ["fido"], ["sms"], ["tel"], ["otp", "sms"]):
        assert oidc.shows_mfa({"amr": single}) is False, single
    assert oidc.shows_mfa({"amr": ["pwd", "hwk"]}) is True and oidc.shows_mfa({"amr": ["mfa"]}) is True
    assert oidc.shows_mfa({"amr": ["hwk", "fpt"]}) is True  # something you have + something you are
    assert oidc.shows_mfa({"acr": "mfa"}) is False  # not a standard level
    assert oidc.shows_mfa({"acr": "http://schemas.openid.net/pape/policies/2007/06/multi-factor"}) is True


def test_google_issuer_variants(monkeypatch):
    config = IdentityProviderConfig(preset="google", issuer_url=oidc.GOOGLE_ISSUER)
    assert oidc._issuers(config) == [oidc.GOOGLE_ISSUER, "accounts.google.com"]


# --- outbound fetches ------------------------------------------------------------------------------------------------


def test_fetches_ask_for_identity_encoding_and_refuse_encoded_bodies(idp):
    assert oidc.discover(idp.issuer)["issuer"] == idp.issuer
    assert idp.requests[-1].headers["accept-encoding"] == "identity"
    oidc._cache.clear()
    idp.discovery = httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"\x1f\x8b")
    with pytest.raises(oidc.ProviderError):
        oidc.discover(idp.issuer)


def test_a_failed_discovery_is_cached_briefly(idp, monkeypatch):
    idp.discovery = httpx.Response(500)
    for _ in range(3):
        with pytest.raises(oidc.ProviderError):
            oidc.discover(idp.issuer)
    assert len(idp.requests) == 1  # one fetch, then the remembered failure
    idp.discovery = None
    monkeypatch.setattr(oidc.time, "monotonic", lambda: time.monotonic_ns() / 1e9 + oidc._FAILED_CACHE_SEC + 1)
    assert oidc.discover(idp.issuer)["issuer"] == idp.issuer  # retried once the failure expires


def test_the_cache_is_bounded_least_recently_used_out(idp, monkeypatch):
    monkeypatch.setattr(oidc, "_CACHE_MAX", 2)
    oidc._remember("https://a.test/x", 60, {"n": "a"})
    oidc._remember("https://b.test/x", 60, {"n": "b"})
    assert oidc._cached("https://a.test/x") == {"n": "a"}  # a is used, so b is now the least recent
    oidc._remember("https://c.test/x", 60, {"n": "c"})
    assert list(oidc._cache) == ["https://a.test/x", "https://c.test/x"]


def test_the_size_cap():
    assert b"".join(oidc._capped(iter([b"a", b"b"]))) == b"ab"
    with pytest.raises(oidc.ProviderError):
        list(oidc._capped(iter([b"x" * (oidc._MAX_BYTES + 1)])))


@pytest.mark.parametrize(
    "drip",
    [
        [b"H", b"T", b"T", b"P", b"/", b"1", b".", b"1", b" ", b"2"] * 20,  # one header byte at a time
        [b"HTTP/1.1 100 Continue\r\n\r\n"] * 200,  # informational responses forever
    ],
    ids=["slow-headers", "endless-100-continue"],
)
def test_the_deadline_bounds_headers_and_1xx_on_a_real_socket(drip):
    """A real local server that answers slowly: the fetch ends at its wall-clock deadline, not one timeout per
    read (each drip comes well inside the per-read wait)."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve():
        conn, _ = server.accept()
        with conn:
            conn.recv(65536)
            for piece in drip:
                try:
                    conn.sendall(piece)
                except OSError:
                    return  # the client hung up: what we want
                time.sleep(0.05)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    transport = oidc._PinnedTransport("127.0.0.1")
    started = time.monotonic()
    # http here only because the transport is driven directly; the guard in _fetch allows https alone.
    request = httpx.Request("GET", f"http://localhost:{port}/x", extensions={"fh_deadline": started + 0.5})
    try:
        with pytest.raises(oidc.ProviderError):
            transport.handle_request(request)
        assert time.monotonic() - started < 2  # the drip would last 10 s
    finally:
        transport.close()
        server.close()
        thread.join(5)


def test_malformed_issuer_documents_are_provider_errors(idp):
    doc = {
        "issuer": idp.issuer, "authorization_endpoint": f"{idp.issuer}/authorize",
        "token_endpoint": f"{idp.issuer}/token", "jwks_uri": f"{idp.issuer}/jwks",
    }  # fmt: skip
    for methods in ("S256", 7, {"S256": True}):
        oidc._cache.clear()
        idp.discovery = httpx.Response(200, json=doc | {"code_challenge_methods_supported": methods})
        with pytest.raises(oidc.ProviderError):
            oidc.discover(idp.issuer)
    oidc._remember(f"{idp.issuer}/jwks", 60, {"keys": {"kid": "k1"}})
    with pytest.raises(oidc.ProviderError):
        oidc._signing_key(f"{idp.issuer}/jwks", "k1", "RS256")
    with pytest.raises(oidc.ProviderError):
        oidc._fetch("GET", f"{idp.issuer}/jw\x01ks")  # httpx.InvalidURL, not an HTTPError


def test_connection_errors_become_provider_errors():
    """httpcore raises its own exceptions; they must not escape as a 500."""
    transport = oidc._PinnedTransport("127.0.0.1")  # nothing listens on port 1
    with pytest.raises(oidc.ProviderError):
        transport.handle_request(httpx.Request("GET", "https://localhost:1/x"))
