"""Plans and entitlements (Phase 8 T1: PLT-14, PLT-09, PLT-13): resolution, the operator routes, the three metered
create points, the two gated add-ons (API keys, the branded mobile app) and the tenant's plan screen."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core import clock
from app.core.db.session import tenant_session
from app.core.settings import get_settings
from app.modules.platform import entitlements
from conftest import PASSWORD, add_staff, link_token, login, new_client, role_id, scalar

API = "/api/v1"


@pytest.fixture
def op():
    return {"X-Operator-Token": get_settings().operator_token}


def _plan(client, op, tenant, code: str) -> dict:
    response = client.put(f"{API}/operator/tenants/{tenant.id}/plan", headers=op, json={"plan_code": code})
    assert response.status_code == 200, response.text
    return response.json()


def _grant(client, op, tenant, status: int = 201, **body) -> dict:
    response = client.post(f"{API}/operator/tenants/{tenant.id}/entitlements", headers=op, json=body)
    assert response.status_code == status, response.text
    return response.json()


def _location(client, headers, status: int = 201) -> dict:
    body = {"name": f"Site {clock.now().timestamp()}", "time_zone": "America/Chicago", "country_code": "US"}
    response = client.post(f"{API}/locations", headers=headers, json=body)
    assert response.status_code == status, response.text
    return response.json()


def _limits(body: dict) -> dict:
    return {row["key"]: (row["limit"], row["used"]) for row in body["limits"]}


def test_a_new_tenant_is_on_the_default_plan_with_everything(client, tenant, owner):
    me = client.get(f"{API}/me", headers=owner).json()["entitlements"]
    assert me["plan"]["code"] == get_settings().entitlements.default_plan == "complete"
    assert me["features"] == ["api_access", "branded_app"]
    assert {key: limit for key, (limit, used) in _limits(me).items()} == dict.fromkeys(entitlements.LIMITS)
    assert all(used is None for _, used in _limits(me).values())  # nothing capped, so nothing counted


def test_operator_routes_need_the_token(client, tenant, op):
    for method, path in [("GET", "/operator/plans"), ("GET", f"/operator/tenants/{tenant.id}/entitlements"),
                         ("PUT", f"/operator/tenants/{tenant.id}/plan")]:  # fmt: skip
        response = client.request(method, f"{API}{path}", headers={"X-Operator-Token": "wrong"}, json={})
        assert response.status_code == 404, path
    plans = {p["code"]: p for p in client.get(f"{API}/operator/plans", headers=op).json()}
    assert set(plans) >= {"essentials", "growth", "complete"} and plans["essentials"]["limits"]["locations"] == 1
    other = client.get(f"{API}/operator/tenants/{tenant.id.hex[:-4]}0000/entitlements", headers=op)
    assert other.status_code == 404


def test_changing_the_plan_is_audited_and_unknown_plans_refused(client, tenant, op):
    assert _plan(client, op, tenant, "essentials")["plan"]["code"] == "essentials"
    refused = client.put(f"{API}/operator/tenants/{tenant.id}/plan", headers=op, json={"plan_code": "nope"})
    assert (refused.status_code, refused.json()["code"]) == (422, "unknown-plan")
    changes = scalar(tenant, text(
        "SELECT changes FROM audit_event WHERE action = 'platform.tenant.manage_subscription' AND entity_type = 'tenant'"
    ))  # fmt: skip
    assert changes == {"plan": ["complete", "essentials"]}


def test_location_limit_is_enforced_and_an_override_raises_it(client, tenant, owner, op):
    _plan(client, op, tenant, "essentials")  # one location
    _location(client, owner)
    refused = _location(client, owner, status=409)
    assert (refused["code"], refused["limit_key"], refused["limit"]) == ("plan-limit-reached", "locations", 1)
    _grant(client, op, tenant, key="locations", limit_value=2, source="addon")
    _location(client, owner)
    _grant(client, op, tenant, key="locations", limit_value=None, source="promo")  # unlimited wins
    _location(client, owner)


def test_staff_seats_are_not_metered(client, tenant, owner, op):
    """Owner decision (phase 8 S4): no staff-seat limit on any plan, at invite or reactivate, nor on display."""
    location = _location(client, owner)
    _plan(client, op, tenant, "essentials")  # the smallest plan; it once allowed 5 staff users
    ids = [add_staff(tenant, "front_desk", all_locations=True)[1] for _ in range(5)]
    invite = {"email": f"x@{tenant.slug}.example.com", "first_name": "X", "last_name": "Y",
              "role_id": str(role_id(tenant, "front_desk")), "location_ids": [location["id"]],
              "primary_location_id": location["id"]}  # fmt: skip
    assert client.post(f"{API}/staff-users", headers=owner, json=invite).status_code == 201
    assert client.post(f"{API}/staff-users/{ids[0]}/deactivate", headers=owner).status_code == 200
    assert client.post(f"{API}/staff-users/{ids[0]}/reactivate", headers=owner).status_code == 200
    assert _grant(client, op, tenant, 422, key="staff_users", limit_value=2)["code"] == "unknown-entitlement"
    for body in (client.get(f"{API}/me", headers=owner).json()["entitlements"],
                 client.get(f"{API}/tenant/entitlements", headers=owner).json()):  # fmt: skip
        assert "staff_users" not in _limits(body)


def test_client_limit_counts_active_clients_on_create_and_enable(client, tenant, owner, op):
    location = _location(client, owner)
    first = new_client(client, owner, location["id"])
    _grant(client, op, tenant, key="clients", limit_value=1)
    body = {"first_name": "B", "last_name": "C", "home_location_id": location["id"]}
    refused = client.post(f"{API}/clients", headers=owner, json=body)
    assert (refused.status_code, refused.json()["code"]) == (409, "plan-limit-reached")
    assert client.post(f"{API}/clients/{first['id']}/disable", headers=owner).status_code == 200
    second = new_client(client, owner, location["id"])
    enable = client.post(f"{API}/clients/{first['id']}/enable", headers=owner)
    assert (enable.status_code, enable.json()["code"]) == (409, "plan-limit-reached")
    me = client.get(f"{API}/me", headers=owner).json()["entitlements"]
    assert _limits(me)["clients"] == (1, 1) and second["id"]


def test_api_keys_need_the_api_access_feature(client, tenant, owner, op):
    created = client.post(f"{API}/api-keys", headers=owner, json={"name": "P", "scopes": ["clients.client.read"]})
    bearer = {"Authorization": f"Bearer {created.json()['secret']}"}
    assert client.get(f"{API}/clients", headers=bearer).status_code == 200
    _plan(client, op, tenant, "essentials")  # no add-ons
    used = client.get(f"{API}/clients", headers=bearer)
    assert (used.status_code, used.json()["code"]) == (403, "feature-not-in-plan")
    another = client.post(f"{API}/api-keys", headers=owner, json={"name": "Q", "scopes": ["clients.client.read"]})
    assert (another.status_code, another.json()["code"]) == (403, "feature-not-in-plan")
    assert "api_access" not in client.get(f"{API}/me", headers=owner).json()["entitlements"]["features"]
    _grant(client, op, tenant, key="api_access", source="addon")
    assert client.get(f"{API}/clients", headers=bearer).status_code == 200


def test_a_flag_off_removes_a_plan_feature_and_dates_bound_every_row(client, tenant, owner, op):
    detail = _grant(client, op, tenant, key="api_access", is_enabled=False, source="flag")
    assert "api_access" not in detail["features"]
    flag = next(row for row in detail["overrides"] if row["key"] == "api_access")
    assert client.delete(f"{API}/operator/tenants/{tenant.id}/entitlements/{flag['id']}", headers=op).status_code == 204
    today = clock.now().date()
    future = _grant(client, op, tenant, key="api_access", is_enabled=False, source="flag",
                    starts_on=str(today + timedelta(days=3)))  # fmt: skip
    past = _grant(client, op, tenant, key="branded_app", is_enabled=False, source="flag",
                  starts_on=str(today - timedelta(days=9)), ends_on=str(today - timedelta(days=3)))  # fmt: skip
    assert future["features"] == past["features"] == ["api_access", "branded_app"]
    bad = _grant(client, op, tenant, status=422, key="api_access", ends_on=str(today - timedelta(days=1)))
    assert bad["code"] == "validation-failed"
    assert _grant(client, op, tenant, status=422, key="nope")["code"] == "unknown-entitlement"
    assert _grant(client, op, tenant, status=422, key="clients", is_enabled=False)["code"] == "validation-failed"
    assert _grant(client, op, tenant, status=422, key="api_access", limit_value=3)["code"] == "validation-failed"


def _member(client, tenant, owner, location_id, mailbox) -> str:
    person = new_client(client, owner, location_id, primary_email=f"m-{clock.now().timestamp()}@example.com")
    assert client.post(f"{API}/clients/{person['id']}/portal-access/invite", headers=owner, json={}).status_code == 200
    client.post(f"{API}/auth/invitations/accept", json={"token": link_token(mailbox[-1]), "new_password": PASSWORD})
    return person["primary_email"]


def _app_sign_in(client, tenant, email: str):
    return client.post(f"{API}/auth/sign-in", headers={"X-Tenant-Slug": tenant.slug},
                       json={"email": email, "password": PASSWORD, "client_kind": "mobile", "audience": "client"})  # fmt: skip


def test_member_app_sign_in_needs_the_branded_app_and_counts_app_users(client, tenant, owner, op, mailbox):
    location = _location(client, owner)
    first = _member(client, tenant, owner, location["id"], mailbox)
    second = _member(client, tenant, owner, location["id"], mailbox)
    _plan(client, op, tenant, "growth")  # no branded app
    refused = _app_sign_in(client, tenant, first)
    assert (refused.status_code, refused.json()["code"]) == (403, "feature-not-in-plan")
    assert (
        client.post(
            f"{API}/auth/sign-in",
            headers={"X-Tenant-Slug": tenant.slug},
            json={"email": first, "password": PASSWORD, "audience": "client"},
        ).status_code
        == 200
    )  # web
    assert login(client, tenant)  # staff on the mobile client are not members
    _grant(client, op, tenant, key="branded_app", source="addon")
    _grant(client, op, tenant, key="app_users", limit_value=1)
    session = _app_sign_in(client, tenant, first)
    assert session.status_code == 200
    full = _app_sign_in(client, tenant, second)
    assert (full.status_code, full.json()["code"], full.json()["limit_key"]) == (409, "plan-limit-reached", "app_users")
    assert _app_sign_in(client, tenant, first).status_code == 200  # a second device is the same user
    with tenant_session(tenant.id) as s:
        assert entitlements.usage(s, "app_users") == 1
    # Removing the add-on ends app sessions at their next refresh.
    _plan(client, op, tenant, "essentials")
    detail = client.get(f"{API}/operator/tenants/{tenant.id}/entitlements", headers=op).json()
    addon = next(row for row in detail["overrides"] if row["key"] == "branded_app")
    client.delete(f"{API}/operator/tenants/{tenant.id}/entitlements/{addon['id']}", headers=op)
    refresh = client.post(f"{API}/auth/refresh", json={"refresh_token": session.json()["refresh_token"]})
    assert (refresh.status_code, refresh.json()["code"]) == (403, "feature-not-in-plan")


def test_plan_screen_is_for_owner_and_admin_and_counts_every_limit(client, tenant, owner, op):
    _location(client, owner)
    _grant(client, op, tenant, key="clients", limit_value=50, source="promo")
    body = client.get(f"{API}/tenant/entitlements", headers=owner).json()
    assert _limits(body)["locations"] == (None, 1) and _limits(body)["clients"] == (50, 0)
    assert [(o["key"], o["source"], o["limit_value"]) for o in body["overrides"]] == [("clients", "promo", 50)]
    assert [(f["key"], f["included"]) for f in body["feature_catalogue"]] == [
        ("api_access", True),
        ("branded_app", True),
    ]
    admin, _ = add_staff(tenant, "admin", all_locations=True)
    assert client.get(f"{API}/tenant/entitlements", headers=login(client, tenant, admin)).status_code == 200
    desk, _ = add_staff(tenant, "front_desk", all_locations=True)
    assert client.get(f"{API}/tenant/entitlements", headers=login(client, tenant, desk)).status_code == 403


def test_a_tenant_without_a_plan_resolves_to_the_default(tenant):
    from app.modules.platform.models import Tenant

    with tenant_session(tenant.id) as session:
        session.get(Tenant, tenant.id).subscription_plan_id = None
    with tenant_session(tenant.id) as session:
        assert entitlements.resolve(session).plan.code == "complete"
        assert entitlements.has_feature(session, "branded_app") and entitlements.limit(session, "clients") is None
