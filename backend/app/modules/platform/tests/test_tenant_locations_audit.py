"""Tenant profile, locations with IANA zones, facility hours, onboarding and the audit trail."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core import clock
from app.core.audit import AuditEvent
from app.core.db.session import tenant_session
from app.core.errors import ValidationFailed
from app.core.settings import get_settings
from app.modules.platform import service
from app.modules.platform.models import FacilityHours
from conftest import WEEK, add_staff, link_token, login, make_tenant, scalar

API = "/api/v1"
MAIN = {"name": "Main Street", "time_zone": "America/Chicago", "country_code": "US"}


def test_tenant_profile(client, tenant, owner):
    profile = client.get(f"{API}/tenant", headers=owner).json()
    assert (
        profile["slug"] == tenant.slug
        and profile["currency"] == "USD"
        and profile["default_time_zone"] == "America/Chicago"
    )
    patch = {
        "name": "Renamed Club",
        "default_time_zone": "Asia/Kolkata",
        "locale": "en-IN",
        "settings": {"terminology": {"client": "member"}},
    }
    updated = client.patch(f"{API}/tenant", headers=owner, json=patch).json()
    assert {k: updated[k] for k in patch} == patch
    assert client.patch(f"{API}/tenant", headers=owner, json={"default_time_zone": "Mars/Olympus"}).status_code == 422
    assert client.patch(f"{API}/tenant", headers=owner, json={"currency": "dollars"}).status_code == 422
    assert (
        client.patch(f"{API}/tenant", headers=owner, json={"name": None}).status_code == 422
    )  # NOT NULL -> 422, not 500
    assert (
        client.patch(f"{API}/tenant", headers=owner, json={"status": "closed"}).status_code == 422
    )  # not a writable field


def test_explicit_null_for_a_required_field_is_422_not_500(client, tenant, owner):
    """PATCH models make every field optional, so null reaches the service; the NOT NULL column answers."""
    for body in ({"settings": None}, {"name": None}):
        response = client.patch(f"{API}/tenant", headers=owner, json=body)
        assert response.status_code == 422 and response.json()["code"] == "validation-failed", body
    assert client.get(f"{API}/tenant", headers=owner).json()["settings"] == {}


def test_location_lifecycle(client, tenant, owner):
    created = client.post(
        f"{API}/locations", headers=owner, json={**MAIN, "city": "Chicago", "autopay_run_time": "05:30"}
    )
    assert created.status_code == 201
    location = created.json()
    assert (
        location["slug"] == "main-street"
        and location["public_name"] == "Main Street"
        and location["status"] == "active"
    )
    assert (location["autopay_run_time"], location["membership_renewal_run_time"]) == (
        "05:30",
        "01:00",
    )  # local wall times
    url = f"{API}/locations/{location['id']}"

    duplicate = client.post(f"{API}/locations", headers=owner, json=MAIN)
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "already-exists"
    for bad in (
        {"time_zone": "Chicago"},
        {"country_code": "usa"},
        {"autopay_run_time": "25:00"},
        {"slug": "Not A Slug"},
    ):
        assert (
            client.post(f"{API}/locations", headers=owner, json={**MAIN, "name": "Other", **bad}).status_code == 422
        ), bad
    other_zone = client.post(
        f"{API}/locations",
        headers=owner,
        json={"name": "Auckland", "time_zone": "Pacific/Auckland", "country_code": "NZ"},
    ).json()

    updated = client.patch(
        url,
        headers=owner,
        json={"time_zone": "America/New_York", "phone": "+13125550100", "time_clock_rounding_min": 6},
    ).json()
    assert updated["time_zone"] == "America/New_York" and updated["time_clock_rounding_min"] == 6
    assert client.patch(url, headers=owner, json={"time_zone": "Nowhere"}).status_code == 422
    assert client.patch(url, headers=owner, json={"slug": "auckland"}).json()["field"] == "slug"
    assert client.patch(url, headers=owner, json={"time_clock_rounding_min": 7}).status_code == 422

    assert [loc["name"] for loc in client.get(f"{API}/locations?sort=name", headers=owner).json()["data"]] == [
        "Auckland",
        "Main Street",
    ]
    assert [loc["id"] for loc in client.get(f"{API}/locations?q=auck", headers=owner).json()["data"]] == [
        other_zone["id"]
    ]
    archived = client.post(f"{url}/archive", headers=owner)
    assert archived.status_code == 200 and archived.json()["status"] == "inactive"
    again = client.post(f"{url}/archive", headers=owner)
    assert again.status_code == 409 and again.json()["code"] == "invalid-state-transition"
    assert [loc["id"] for loc in client.get(f"{API}/locations?status=active", headers=owner).json()["data"]] == [
        other_zone["id"]
    ]
    assert client.get(url, headers=owner).json()["status"] == "inactive"  # archived, never deleted


def test_facility_hours(client, tenant, owner):
    location = client.post(f"{API}/locations", headers=owner, json=MAIN).json()
    url = f"{API}/locations/{location['id']}/facility-hours"
    seeded = client.get(url, headers=owner).json()
    assert [d["weekday"] for d in seeded["days"]] == [1, 2, 3, 4, 5, 6, 7] and seeded["days"][0][
        "opens_time"
    ] == "06:00"
    week = [dict(d) for d in WEEK]
    week[5] = {"weekday": 6, "opens_time": "00:00", "closes_time": "24:00", "is_closed": False}  # open until midnight
    week[6] = {"weekday": 7, "is_closed": True}
    replaced = client.put(url, headers=owner, json={"days": week}).json()
    assert replaced["days"][5]["closes_time"] == "24:00" and replaced["days"][6] == {
        "weekday": 7,
        "opens_time": None,
        "closes_time": None,
        "is_closed": True,
    }
    assert scalar(tenant, select(func.count()).select_from(FacilityHours)) == 7
    assert client.put(url, headers=owner, json={"days": week[:6]}).status_code == 422
    assert client.put(url, headers=owner, json={"days": [*week[:6], week[5]]}).status_code == 422  # a weekday twice
    backwards = [*week[:6], {"weekday": 7, "opens_time": "20:00", "closes_time": "08:00", "is_closed": False}]
    assert client.put(url, headers=owner, json={"days": backwards}).json()["errors"][0]["pointer"] == "/days/6"
    # The database holds the same rule for anything that bypasses the service.
    with pytest.raises(DBAPIError, match="ck_facility_hours_window"), tenant_session(tenant.id) as session:
        session.execute(text("UPDATE facility_hours SET closes_time = '01:00' WHERE weekday = 1"))

    public = client.get(f"{API}/public/locations", headers={"X-Tenant-Slug": tenant.slug})
    assert public.status_code == 200
    listed = public.json()["data"][0]
    assert listed["public_name"] == "Main Street" and len(listed["facility_hours"]) == 7 and "alert_email" not in listed
    client.post(f"{API}/locations/{location['id']}/archive", headers=owner)
    assert client.get(f"{API}/public/locations", headers={"X-Tenant-Slug": tenant.slug}).json()["data"] == []


def test_onboarding_through_the_operator_endpoint(client, mailbox):
    body = {"name": "Net Gain Tennis", "slug": "net-gain-tennis", "default_time_zone": "Europe/London",
            "owner_email": "pat@netgain.example.com", "owner_first_name": "Pat", "owner_last_name": "Rally"}  # fmt: skip
    with tenant_session(make_tenant().id) as session:
        session.execute(text("SELECT 1"))  # unrelated tenant exists; onboarding must not need one
    assert client.post(f"{API}/operator/tenants", json=body).status_code == 404  # no token: the route does not exist
    token = {"X-Operator-Token": get_settings().operator_token}
    body["slug"] = f"net-gain-{clock.now().timestamp():.0f}"
    created = client.post(f"{API}/operator/tenants", headers=token, json=body)
    assert created.status_code == 201
    # Without a password the owner is invited; accepting the link signs them in as Owner.
    accepted = client.post(
        f"{API}/auth/invitations/accept", json={"token": link_token(mailbox[-1]), "client_kind": "mobile"}
    )
    headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    me = client.get(f"{API}/me", headers=headers).json()
    assert me["role"]["system_key"] == "owner" and me["tenant"]["default_time_zone"] == "Europe/London"
    assert len(client.get(f"{API}/roles", headers=headers).json()["data"]) == 8  # the seeded system roles
    taken = client.post(f"{API}/operator/tenants", headers=token, json=body)
    assert taken.status_code == 409 and taken.json()["field"] == "slug"
    assert client.post(f"{API}/operator/tenants", headers=token, json={**body, "slug": "Bad Slug"}).status_code == 422


def test_onboarding_validates_and_leaves_no_orphan():
    with pytest.raises(ValidationFailed):
        service.onboard_tenant(name="X", slug="weak-pw-club", default_time_zone="UTC", owner_email="a@example.com",
                               owner_first_name="A", owner_last_name="B", owner_password="short")  # fmt: skip
    with pytest.raises(ValidationFailed):
        service.onboard_tenant(name="X", slug="bad-zone-club", default_time_zone="Not/AZone", owner_email="a@example.com",
                               owner_first_name="A", owner_last_name="B")  # fmt: skip
    from app.core.db.platform import resolve_tenant

    assert resolve_tenant(slug="weak-pw-club") is None and resolve_tenant(slug="bad-zone-club") is None


def test_audit_trail(client, tenant, owner):
    location = client.post(f"{API}/locations", headers=owner, json=MAIN).json()
    email, manager_id = add_staff(tenant, "manager", location_ids=[location["id"]])
    client.patch(
        f"{API}/staff-users/{manager_id}",
        headers={**owner, "X-Request-ID": "trace-abc-12345"},
        json={"first_name": "Morgan", "is_attendance_notified": True},
    )
    client.patch(f"{API}/tenant", headers=owner, json={"default_time_zone": "America/Denver"})
    client.patch(f"{API}/locations/{location['id']}", headers=owner, json={"phone": "+13125550100"})

    events = client.get(f"{API}/audit-events?limit=200", headers=owner).json()["data"]
    actions = [e["action"] for e in events]
    assert actions[0] == "platform.location.update"  # newest first
    assert {
        "platform.tenant.create",
        "platform.identity.sign_in",
        "platform.location.create",
        "platform.staff_user.update",
        "platform.tenant.update",
    } <= set(actions)
    update = next(e for e in events if e["action"] == "platform.staff_user.update")
    # PII is recorded as changed-flag only; non-PII values are kept as [old, new].
    assert update["changes"] == {"first_name": True, "is_attendance_notified": [False, True]}
    assert (
        update["actor_type"] == "staff"
        and update["actor_id"] == str(tenant.owner_id)
        and update["actor_label"] == "Olive Owner"
    )
    assert (
        update["entity_type"] == "staff_user"
        and update["entity_id"] == str(manager_id)
        and update["request_id"] == "trace-abc-12345"
    )
    tenant_update = next(e for e in events if e["action"] == "platform.tenant.update")
    assert tenant_update["changes"] == {"default_time_zone": ["America/Chicago", "America/Denver"]}
    assert next(e for e in events if e["action"] == "platform.tenant.create")["actor_type"] == "system"

    by_entity = client.get(f"{API}/audit-events?entity_type=staff_user&entity_id={manager_id}", headers=owner).json()[
        "data"
    ]
    assert [e["action"] for e in by_entity] == ["platform.staff_user.update"]
    by_action = client.get(
        f"{API}/audit-events?action[in]=platform.location.create,platform.location.update&sort=occurred_at",
        headers=owner,
    ).json()["data"]
    assert [e["action"] for e in by_action] == ["platform.location.create", "platform.location.update"]
    future = (clock.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert client.get(f"{API}/audit-events?occurred_at[gte]={future}", headers=owner).json()["data"] == []
    assert (
        client.get(
            f"{API}/audit-events?occurred_at[lt]={future}&actor_type[ne]=system&include=total", headers=owner
        ).json()["page"]["total"]
        == len(events) - 1
    )
    assert client.get(f"{API}/audit-events?occurred_at[gte]=yesterday", headers=owner).status_code == 422

    # A location-limited reader sees its locations' rows only; tenant-level rows need all-location access.
    manager = login(client, tenant, email)
    visible = client.get(f"{API}/audit-events", headers=manager).json()["data"]
    assert {e["action"] for e in visible} == {"platform.location.create", "platform.location.update"}
    assert {e["location_id"] for e in visible} == {location["id"]}

    # Role and permission changes are kept seven years, everything else two.
    client.post(f"{API}/roles", headers=owner, json={"name": "Auditor"})
    today = clock.now().date()
    retention = dict(scalar_rows(tenant, select(AuditEvent.action, AuditEvent.retain_until_on)))
    assert retention["platform.role.create"] == today + timedelta(days=2557)
    assert retention["platform.location.update"] == today + timedelta(days=730)


def scalar_rows(tenant, stmt):
    with tenant_session(tenant.id) as session:
        return [tuple(row) for row in session.execute(stmt)]


def test_audit_log_is_append_only(tenant, owner):
    """fh_app holds SELECT and INSERT only: history cannot be rewritten or erased by the application role."""
    assert scalar(tenant, select(func.count()).select_from(AuditEvent)) >= 2
    for statement in ("UPDATE audit_event SET action = 'tampered'", "DELETE FROM audit_event", "TRUNCATE audit_event"):
        with pytest.raises(DBAPIError, match="permission denied"), tenant_session(tenant.id) as session:
            session.execute(text(statement))


def test_failed_change_leaves_no_audit_row(client, tenant, owner):
    before = scalar(tenant, select(func.count()).select_from(AuditEvent))
    client.post(f"{API}/locations", headers=owner, json=MAIN)
    assert (
        client.post(f"{API}/locations", headers=owner, json=MAIN).status_code == 409
    )  # rolled back, audit row and all
    assert scalar(tenant, select(func.count()).select_from(AuditEvent)) == before + 1
