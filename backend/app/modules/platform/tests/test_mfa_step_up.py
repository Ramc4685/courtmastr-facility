"""Phase 8 S2: TOTP MFA, the pending sign-in, recovery codes, tenant MFA policy, step-up and session lifetimes."""

import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import CATALOGUE, Principal, authorize, system_principal
from app.core.auth.deps import Ctx, require
from app.core.db.session import tenant_session
from app.core.errors import PermissionDenied
from app.core.settings import get_settings
from app.main import app
from app.modules.platform.models import AuthSession, MfaFactor, MfaRecoveryCode, Role, RolePermission, StaffUser, Tenant
from conftest import PASSWORD, add_staff, drop_elevation, finish_enrolment, link_token, login, make_tenant, totp
from tests.test_security import ROUTES

API = "/api/v1"
STEP = timedelta(seconds=30)


def _sign_in(client, tenant, email=None, kind="mobile", password=PASSWORD):
    return client.post(
        f"{API}/auth/sign-in",
        headers={"X-Tenant-Slug": tenant.slug},
        json={"email": email or tenant.owner_email, "password": password, "client_kind": kind, "audience": "staff"},
    )


def _enrol(client, headers) -> tuple[str, list[str]]:
    """Turn TOTP on for the signed-in caller; returns (secret, recovery codes)."""
    started = client.post(f"{API}/me/mfa/totp", headers=headers)
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    assert started.json()["otpauth_uri"].startswith("otpauth://totp/")
    done = client.post(f"{API}/me/mfa/totp/confirm", headers=headers, json={"code": totp(secret)})
    assert done.status_code == 200, done.text
    return secret, done.json()["recovery_codes"]


def _link_sign_in(client, tenant, mailbox, email=None):
    """Sign in through an emailed magic link (mobile): the 202 challenge, or the session body."""
    client.post(
        f"{API}/auth/magic-links", headers={"X-Tenant-Slug": tenant.slug}, json={"email": email or tenant.owner_email}
    )
    return client.post(
        f"{API}/auth/magic-links/consume", json={"token": link_token(mailbox[-1]), "client_kind": "mobile"}
    )


def _verify(client, challenge, code):
    return client.post(f"{API}/auth/mfa/verify", json={"mfa_token": challenge["mfa_token"], "code": code})


def _bearer(body) -> dict:
    return {"Authorization": f"Bearer {body['access_token']}"}


def _iso(at) -> str:
    return at.isoformat().replace("+00:00", "Z")


@pytest.fixture
def now():
    """A frozen clock at the start of a 30-second step, so step arithmetic is exact."""
    at = clock.now().replace(microsecond=0)
    at -= timedelta(seconds=at.second % 30)
    with clock.freeze(at):
        yield at


# --- enrolment, sign-in with the second factor ---------------------------------------------------------------


def test_enrol_sign_in_and_disable(client, tenant, mailbox, now):
    owner = login(client, tenant)
    assert client.get(f"{API}/me/mfa", headers=owner).json() == {
        "enrolled": False, "confirmed_at": None, "recovery_codes_remaining": 0, "required": False,
        "provider_step_up": False,
    }  # fmt: skip
    secret, codes = _enrol(client, owner)
    assert len(codes) == 10 and len(set(codes)) == 10
    assert "turned on" in mailbox[-1].subject
    status = client.get(f"{API}/me/mfa", headers=owner).json()
    assert status["enrolled"] and status["recovery_codes_remaining"] == 10
    with tenant_session(tenant.id) as session:  # sealed at rest; never the plain secret, in the row or the audit
        sealed = session.scalar(select(MfaFactor.secret_encrypted))
        assert secret not in sealed and sealed.startswith("k1:")
        events = session.scalars(select(AuditEvent).where(AuditEvent.action == "platform.identity.mfa_enrol")).all()
        assert events and all(secret not in str(e.changes) for e in events)

    with clock.freeze(now + STEP):
        challenge = _sign_in(client, tenant)
        assert challenge.status_code == 202 and not challenge.json()["enrolment_required"]
        assert "access_token" not in challenge.json()
        signed_in = _verify(client, challenge.json(), totp(secret))
        assert signed_in.status_code == 200 and signed_in.json()["mfa_verified_at"]
        headers = _bearer(signed_in.json())
        assert client.delete(f"{API}/me/mfa/totp", headers=headers).status_code == 204
    assert "turned off" in mailbox[-1].subject
    assert _sign_in(client, tenant).status_code == 200  # password alone again


def test_confirming_enrolment_signs_out_other_sessions(client, tenant, now):
    other = login(client, tenant)
    owner = login(client, tenant)
    _enrol(client, owner)
    assert client.get(f"{API}/me", headers=other).status_code == 401
    assert client.get(f"{API}/me", headers=owner).status_code == 200


def test_enrolment_and_disable_need_step_up(client, tenant, now):
    stale = login(client, tenant, elevated=False)
    assert client.post(f"{API}/me/mfa/totp", headers=stale).json()["code"] == "step-up-required"
    owner = login(client, tenant)
    _enrol(client, owner)
    drop_elevation(tenant, owner["Authorization"][7:])
    assert client.delete(f"{API}/me/mfa/totp", headers=owner).json()["code"] == "step-up-required"
    assert client.post(f"{API}/me/mfa/recovery-codes", headers=owner).json()["code"] == "step-up-required"


def test_a_used_code_cannot_be_replayed(client, tenant, now):
    owner = login(client, tenant)
    secret, _ = _enrol(client, owner)
    with clock.freeze(now + STEP):
        code = totp(secret)
        assert _verify(client, _sign_in(client, tenant).json(), code).status_code == 200
        again = _verify(client, _sign_in(client, tenant).json(), code)
        assert again.status_code == 401 and again.json()["code"] == "mfa-code-invalid"
    # The code from before the one used is refused too, even inside the drift window.
    with clock.freeze(now + 2 * STEP):
        assert _verify(client, _sign_in(client, tenant).json(), totp(secret, -2)).status_code == 401


def test_one_step_of_drift_either_way(client, tenant, now):
    owner = login(client, tenant)
    secret, _ = _enrol(client, owner)  # spends the code at `now`
    with clock.freeze(now + 3 * STEP):
        assert _verify(client, _sign_in(client, tenant).json(), totp(secret, -2)).status_code == 401
        assert _verify(client, _sign_in(client, tenant).json(), totp(secret, -1)).status_code == 200
        assert _verify(client, _sign_in(client, tenant).json(), totp(secret, +1)).status_code == 200
        assert _verify(client, _sign_in(client, tenant).json(), totp(secret, +2)).status_code == 401


def test_recovery_codes_are_single_use_and_regenerate(client, tenant, now):
    owner = login(client, tenant)
    _, codes = _enrol(client, owner)
    signed_in = _verify(client, _sign_in(client, tenant).json(), codes[0].upper())  # case tolerant
    assert signed_in.status_code == 200
    assert _verify(client, _sign_in(client, tenant).json(), codes[0]).status_code == 401
    headers = _bearer(signed_in.json())
    assert client.get(f"{API}/me/mfa", headers=headers).json()["recovery_codes_remaining"] == 9
    fresh = client.post(f"{API}/me/mfa/recovery-codes", headers=headers)
    assert fresh.status_code == 200 and len(fresh.json()["recovery_codes"]) == 10
    assert _verify(client, _sign_in(client, tenant).json(), codes[1]).status_code == 401  # the old set is gone
    with tenant_session(tenant.id) as session:
        stored = set(session.scalars(select(MfaRecoveryCode.code_hash)))
    assert len(stored) == 10
    # Review fix 7: keyed and bound to the identity, so a table dump cannot be checked offline.
    plain = {hashlib.sha256(c.replace("-", "").encode()).hexdigest() for c in fresh.json()["recovery_codes"]}
    assert not stored & plain


def test_wrong_codes_lock_the_factor_not_the_password(client, tenant, mailbox, now):
    owner = login(client, tenant)
    secret, _ = _enrol(client, owner)
    for _ in range(10):
        challenge = _sign_in(client, tenant).json()  # a correct password does not reset the code count
        assert _verify(client, challenge, "000000").json()["code"] == "mfa-code-invalid"
    assert "wrong codes" in mailbox[-1].subject  # mailed once, with its own wording
    challenge = _sign_in(client, tenant)
    assert challenge.status_code == 202  # the password stage is not locked
    with clock.freeze(now + STEP):
        assert _verify(client, challenge.json(), totp(secret)).json()["code"] == "mfa-locked"
        consumed = _link_sign_in(client, tenant, mailbox)  # nor does an emailed link reset the code lock
        assert consumed.status_code == 202
        assert _verify(client, consumed.json(), totp(secret)).json()["code"] == "mfa-locked"


def test_wrong_passwords_do_not_lock_out_the_second_factor(client, tenant, mailbox, now):
    """Review fix 1: anyone who knows the address could otherwise lock the owner out of every sign-in."""
    secret, _ = _enrol(client, login(client, tenant))
    for _ in range(10):
        _sign_in(client, tenant, password="wrong-password-x")
    assert _sign_in(client, tenant).json()["code"] == "identity-locked"
    consumed = _link_sign_in(client, tenant, mailbox)
    assert consumed.status_code == 202
    with clock.freeze(now + STEP):
        assert _verify(client, consumed.json(), totp(secret)).status_code == 200


def test_the_pending_state_grants_nothing(client, tenant, now):
    owner = login(client, tenant)
    _enrol(client, owner)
    challenge = _sign_in(client, tenant).json()
    token = challenge["mfa_token"]
    assert token.startswith("fhm_")
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get(f"{API}/locations", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    with clock.freeze(now + timedelta(minutes=6)):  # five-minute lifetime
        assert _verify(client, challenge, "123456").json()["code"] == "mfa-challenge-invalid"
    # A newer sign-in supersedes the older challenge.
    first, second = _sign_in(client, tenant).json(), _sign_in(client, tenant).json()
    assert _verify(client, first, "123456").json()["code"] == "mfa-challenge-invalid"
    assert _verify(client, second, "123456").json()["code"] == "mfa-code-invalid"


def test_magic_link_and_reset_do_not_bypass_mfa(client, tenant, mailbox, now):
    owner = login(client, tenant)
    _enrol(client, owner)
    slug = {"X-Tenant-Slug": tenant.slug}
    client.post(f"{API}/auth/magic-links", headers=slug, json={"email": tenant.owner_email})
    consumed = client.post(
        f"{API}/auth/magic-links/consume", json={"token": link_token(mailbox[-1]), "client_kind": "mobile"}
    )
    assert consumed.status_code == 202
    client.post(f"{API}/auth/password-resets", headers=slug, json={"email": tenant.owner_email})
    reset = client.post(
        f"{API}/auth/password-resets/consume",
        json={"token": link_token(mailbox[-1]), "new_password": "another-long-passphrase", "client_kind": "mobile"},
    )
    assert reset.status_code == 202


# --- tenant policy ---------------------------------------------------------------------------------------------


def test_required_roles_are_walked_through_enrolment(mailbox):
    client = TestClient(app)
    tenant = make_tenant(mfa_policy="privileged")  # the product default
    desk_email, _ = add_staff(tenant, "front_desk")
    admin_email, _ = add_staff(tenant, "admin")
    assert _sign_in(client, tenant, desk_email).status_code == 200  # optional for other staff
    challenge = _link_sign_in(client, tenant, mailbox, admin_email)
    assert challenge.status_code == 202 and challenge.json()["enrolment_required"]
    early = _verify(client, challenge.json(), "123456")
    assert early.status_code == 422 and early.json()["code"] == "mfa-enrolment-not-started"
    signed_in, _ = finish_enrolment(client, challenge.json())
    assert len(signed_in["recovery_codes"]) == 10
    headers = _bearer(signed_in)
    assert client.get(f"{API}/me/mfa", headers=headers).json()["required"] is True
    refused = client.delete(f"{API}/me/mfa/totp", headers=headers)
    assert refused.status_code == 403 and refused.json()["code"] == "mfa-required"


def test_a_password_alone_cannot_bind_a_new_authenticator(mailbox):
    """Review fix 3: forced enrolment follows an emailed link, so a leaked password cannot enrol an attacker."""
    client = TestClient(app)
    tenant = make_tenant(mfa_policy="privileged")
    admin_email, _ = add_staff(tenant, "admin")
    challenge = _sign_in(client, tenant, admin_email).json()
    assert challenge["enrolment_required"]
    sent = len(mailbox)
    for _ in range(2):  # one link per pending sign-in, however often the device asks
        refused = client.post(f"{API}/auth/mfa/enrolment", json={"mfa_token": challenge["mfa_token"]})
        assert refused.status_code == 403 and refused.json()["code"] == "mfa-enrolment-needs-email-link"
    assert len(mailbox) == sent + 1 and mailbox[-1].to == admin_email
    assert _verify(client, challenge, "123456").json()["code"] == "mfa-enrolment-not-started"
    consumed = client.post(
        f"{API}/auth/magic-links/consume", json={"token": link_token(mailbox[-1]), "client_kind": "mobile"}
    )
    assert consumed.status_code == 202 and consumed.json()["enrolment_required"]
    finish_enrolment(client, consumed.json())


def test_forced_enrolment_ends_older_sessions(client, tenant, mailbox):
    """Review fix 5: as turning MFA on from account settings does."""
    admin_email, _ = add_staff(tenant, "admin")
    older = login(client, tenant, admin_email)
    with tenant_session(tenant.id) as session:
        session.get(Tenant, tenant.id).staff_mfa_policy = "privileged"
    finish_enrolment(client, _link_sign_in(client, tenant, mailbox, admin_email).json())
    assert client.get(f"{API}/me", headers=older).status_code == 401


def test_privileged_covers_any_role_holding_a_step_up_key():
    """Review fix 4: ADR 0002 section 6, not just the Owner and Admin role names."""
    client = TestClient(app)
    tenant = make_tenant(mfa_policy="privileged")
    email, user_id = add_staff(tenant, "front_desk")
    plain = _sign_in(client, tenant, email)
    assert plain.status_code == 200
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        role = Role(name="Integrator")
        session.add(role)
        session.flush()
        session.add(RolePermission(role_id=role.id, permission_key="integrations.api_key.manage"))
        session.get(StaffUser, user_id).role_id = role.id
    assert CATALOGUE["integrations.api_key.manage"].needs_step_up
    challenge = _sign_in(client, tenant, email)
    assert challenge.status_code == 202 and challenge.json()["enrolment_required"]


def test_a_tightened_policy_stops_password_step_up_on_live_sessions(client, tenant):
    stale = login(client, tenant, elevated=False)
    with tenant_session(tenant.id) as session:
        session.get(Tenant, tenant.id).staff_mfa_policy = "privileged"
    refused = client.post(f"{API}/auth/step-up", headers=stale, json={"password": PASSWORD})
    assert refused.status_code == 403 and refused.json()["code"] == "mfa-enrolment-required"


def test_policy_change_is_audited_behind_step_up_and_owner_only_to_relax(client, tenant, mailbox):
    path = f"{API}/security-settings"
    assert client.get(path, headers=login(client, tenant)).json() == {
        "staff_ip_allowlist": [], "staff_mfa_policy": "optional", "staff_idle_timeout_min": 30,
    }  # fmt: skip
    stale = login(client, tenant, elevated=False)
    refused = client.patch(path, headers=stale, json={"staff_mfa_policy": "all"})
    assert refused.status_code == 403 and refused.json()["code"] == "step-up-required"
    owner = login(client, tenant)
    assert client.patch(path, headers=owner, json={"staff_mfa_policy": "all"}).json()["staff_mfa_policy"] == "all"
    admin_email, _ = add_staff(tenant, "admin")
    admin, _ = finish_enrolment(client, _link_sign_in(client, tenant, mailbox, admin_email).json())  # must enrol
    relax = client.patch(path, headers=_bearer(admin), json={"staff_mfa_policy": "optional"})
    assert relax.status_code == 403 and relax.json()["code"] == "owner-only"
    done = client.patch(path, headers=owner, json={"staff_mfa_policy": "optional", "staff_idle_timeout_min": 15})
    assert done.json()["staff_mfa_policy"] == "optional" and done.json()["staff_idle_timeout_min"] == 15
    assert client.patch(path, headers=owner, json={"staff_idle_timeout_min": 61}).status_code == 422
    with tenant_session(tenant.id) as session:
        stmt = select(AuditEvent).where(AuditEvent.action == "platform.security.manage").order_by(AuditEvent.id)
        changes = [event.changes for event in session.scalars(stmt)]
    assert changes == [
        {"staff_mfa_policy": ["optional", "all"]},
        {"staff_mfa_policy": ["all", "optional"], "staff_idle_timeout_min": [None, 15]},
    ]


# --- step-up ---------------------------------------------------------------------------------------------------

PLUS_ROUTES = [
    ("post", "/provider-accounts", {}),  # billing.provider.manage
    ("get", "/api-keys", None),  # integrations.api_key.manage
    ("post", "/payroll-runs/{id}/finalize", {}),  # staff.payroll_run.approve
]


@pytest.mark.parametrize(("method", "path", "body"), PLUS_ROUTES)
def test_plus_keys_in_three_contexts_need_step_up(client, tenant, method, path, body):
    url = API + path.replace("{id}", str(uuid4()))
    stale = client.request(method, url, headers=login(client, tenant, elevated=False), json=body)
    assert stale.status_code == 403 and stale.json()["code"] == "step-up-required"
    fresh = client.request(method, url, headers=login(client, tenant), json=body)
    assert fresh.status_code in (200, 404, 422), fresh.text  # past the gate: a list, an unknown run, a bad body


def test_step_up_by_password_lasts_ten_minutes(client, tenant, now):
    stale = login(client, tenant, elevated=False)
    wrong = client.post(f"{API}/auth/step-up", headers=stale, json={"password": "wrong"})
    assert wrong.status_code == 403 and wrong.json()["code"] == "reauthentication-failed"
    stepped = client.post(f"{API}/auth/step-up", headers=stale, json={"password": PASSWORD})
    assert stepped.status_code == 200
    headers = _bearer(stepped.json())
    assert client.get(f"{API}/me", headers=stale).status_code == 401  # the old session was rotated away
    with clock.freeze(now + timedelta(minutes=9, seconds=50)):
        assert client.get(f"{API}/api-keys", headers=headers).status_code == 200
    with clock.freeze(now + timedelta(minutes=10, seconds=1)):
        assert client.get(f"{API}/api-keys", headers=headers).json()["code"] == "step-up-required"


def test_step_up_with_mfa_needs_a_code_not_the_password(client, tenant, now):
    owner = login(client, tenant)
    secret, codes = _enrol(client, owner)
    drop_elevation(tenant, owner["Authorization"][7:])
    assert client.post(f"{API}/auth/step-up", headers=owner, json={"password": PASSWORD}).status_code == 403
    with clock.freeze(now + STEP):
        stepped = client.post(f"{API}/auth/step-up", headers=owner, json={"code": totp(secret)})
        assert stepped.status_code == 200 and stepped.json()["mfa_verified_at"]
    by_recovery = client.post(f"{API}/auth/step-up", headers=_bearer(stepped.json()), json={"code": codes[3]})
    assert by_recovery.status_code == 200


def test_step_up_is_limited_per_identity(client, tenant, monkeypatch, now):
    """Review fix 2: a per-IP limit alone lets an attacker spread code guesses over many addresses."""
    sessions = [login(client, tenant, elevated=False) for _ in range(3)]  # before the limits are on
    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    for bucket, limit in (("step-up", 1000), ("step-up-identity", 2)):
        monkeypatch.setitem(cfg.buckets, bucket, cfg.buckets[bucket].model_copy(update={"limit": limit}))
    assert client.post(f"{API}/auth/step-up", headers=sessions[0], json={"password": "x"}).status_code == 403
    assert client.post(f"{API}/auth/step-up", headers=sessions[1], json={"password": "x"}).status_code == 403
    limited = client.post(f"{API}/auth/step-up", headers=sessions[2], json={"password": PASSWORD})
    assert limited.status_code == 429 and limited.json()["code"] == "rate-limited"


def test_step_up_rotates_the_web_session_and_csrf_token(client, tenant, now):
    first = _sign_in(client, tenant, kind="web").json()
    old_cookie = client.cookies.get("fh_session")
    with tenant_session(tenant.id) as session:
        session.get(AuthSession, first["id"]).elevated_until_at = None
    assert client.get(f"{API}/security-settings").json()["code"] == "step-up-required"
    csrf = {"X-CSRF-Token": first["csrf_token"]}
    stepped = client.post(f"{API}/auth/step-up", json={"password": PASSWORD}, headers=csrf)
    assert stepped.status_code == 200, stepped.text
    second = stepped.json()
    assert second["id"] != first["id"] and second["csrf_token"] != first["csrf_token"]
    assert client.cookies.get("fh_session") != old_cookie
    assert second["absolute_expires_at"] == first["absolute_expires_at"]  # rotation keeps the absolute limit
    assert client.get(f"{API}/security-settings").status_code == 200
    patch = {"staff_idle_timeout_min": 45}
    assert client.patch(f"{API}/security-settings", json=patch, headers=csrf).json()["code"] == "csrf-failed"
    new_csrf = {"X-CSRF-Token": second["csrf_token"]}
    assert client.patch(f"{API}/security-settings", json=patch, headers=new_csrf).status_code == 200
    with tenant_session(tenant.id) as session:
        assert session.get(AuthSession, first["id"]).revoked_reason == "step_up"


def test_api_keys_cannot_use_plus_keys():
    """rbac-matrix 11: `+` keys are never grantable to an API key, and an API-key principal is never elevated."""
    key = Principal(kind="api_key", permissions=dict.fromkeys(CATALOGUE, "all"), api_key_id=uuid4())
    with pytest.raises(PermissionDenied) as refused:
        authorize(key, "integrations.api_key.manage")
    assert refused.value.code == "step-up-required"


# --- the single enforcement point covers every `+` key -----------------------------------------------------------

PLUS_KEYS = sorted(key for key, permission in CATALOGUE.items() if permission.needs_step_up)


def test_the_catalogue_marks_the_matrix_step_up_keys():
    assert len(PLUS_KEYS) >= 12 and "staff.payroll_run.approve" in PLUS_KEYS


@pytest.mark.parametrize("key", PLUS_KEYS)
def test_every_plus_key_is_enforced_by_authorize_and_require(key):
    everything = dict.fromkeys(CATALOGUE, "all")
    stale = Principal(kind="staff", role_system_key="owner", permissions=everything)
    with pytest.raises(PermissionDenied) as refused:
        authorize(stale, key)
    assert refused.value.code == "step-up-required"
    with pytest.raises(PermissionDenied) as refused:
        require(key)(Ctx(None, stale))
    assert refused.value.code == "step-up-required"
    fresh = Principal(kind="staff", role_system_key="owner", permissions=everything, elevated=True)
    authorize(fresh, key)
    require(key)(Ctx(None, fresh))


def _plus_only_routes():
    for path, route, calls in ROUTES:
        gates = [getattr(call, "keys", ()) for call in calls if getattr(call, "keys", ())]
        if gates and all(key in CATALOGUE and CATALOGUE[key].needs_step_up for keys in gates for key in keys):
            for method in route.methods:
                yield method, path


def test_every_route_gated_only_by_plus_keys_refuses_an_unelevated_session(client):
    stale = login(client, make_tenant(), elevated=False)
    routes = sorted(set(_plus_only_routes()))
    assert len(routes) >= 10
    for method, path in routes:
        url = path
        for name in [part[1:-1] for part in path.split("/") if part.startswith("{")]:
            url = url.replace(f"{{{name}}}", str(uuid4()))
        response = client.request(method, url, headers=stale, json={})
        assert response.status_code == 403 and response.json().get("code") == "step-up-required", (method, path)


# --- session lifetimes (security-baseline 5.1) ------------------------------------------------------------------


def test_staff_web_idle_slides_and_absolute_caps(client, tenant, now):
    body = _sign_in(client, tenant, kind="web").json()
    assert body["absolute_expires_at"] == _iso(now + timedelta(hours=12))
    assert body["idle_expires_at"] == _iso(now + timedelta(minutes=30))
    with clock.freeze(now + timedelta(minutes=29)):
        assert client.get(f"{API}/me").status_code == 200  # slides the idle limit
    with clock.freeze(now + timedelta(minutes=58)):
        assert client.get(f"{API}/me").status_code == 200
    with clock.freeze(now + timedelta(minutes=58 + 31)):
        assert client.get(f"{API}/me").status_code == 401  # unused for 31 minutes
    _sign_in(client, tenant, kind="web")
    at = now
    while at < now + timedelta(hours=11, minutes=40):  # kept busy all day
        at += timedelta(minutes=20)
        with clock.freeze(at):
            assert client.get(f"{API}/me").status_code == 200
    with clock.freeze(now + timedelta(hours=12, minutes=1)):
        assert client.get(f"{API}/me").status_code == 401


def test_tenant_idle_timeout_applies_to_staff_web(client, tenant, now):
    client.patch(f"{API}/security-settings", headers=login(client, tenant), json={"staff_idle_timeout_min": 15})
    assert _sign_in(client, tenant, kind="web").json()["idle_expires_at"] == _iso(now + timedelta(minutes=15))
    with clock.freeze(now + timedelta(minutes=16)):
        assert client.get(f"{API}/me").status_code == 401


def test_member_web_session_lifetimes(client, tenant, now):
    from app.core.auth import passwords
    from app.modules.platform.models import Identity

    email = f"member-{uuid4().hex[:6]}@example.com"
    with tenant_session(tenant.id) as session:
        session.add(
            Identity(kind="client", email=email, status="active", password_hash=passwords.hash_password(PASSWORD))
        )
    body = client.post(
        f"{API}/auth/sign-in", headers={"X-Tenant-Slug": tenant.slug},
        json={"email": email, "password": PASSWORD, "audience": "client"},
    ).json()  # fmt: skip
    assert body["idle_expires_at"] == _iso(now + timedelta(days=30))
    assert body["absolute_expires_at"] == _iso(now + timedelta(days=90))
