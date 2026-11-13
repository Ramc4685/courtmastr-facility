"""Phase 11 C2 part 2: favourites with a personal schedule (APP-13) and anonymous app usage counts (APP-17)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import Principal, system_principal
from app.core.db.session import tenant_session
from app.core.errors import PermissionDenied
from app.modules.engagement import member
from app.modules.engagement.models import AppUsageDay, ClientFavorite
from app.modules.platform import privacy, retention
from app.modules.programs.tests.test_checkout import member as portal_member
from app.modules.programs.tests.test_groups import program
from app.modules.programs.tests.test_selfservice import POLICY
from app.modules.scheduling.tests.helpers import at, book, facility
from conftest import add_staff, login, make_tenant, new_client

API = "/api/v1"
SOON = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=3)


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def favorite(client, portal, client_id, kind, target_id):
    return client.post(f"{API}/portal/favorites", headers=portal,
                       json={"client_id": client_id, "kind": kind, "target_id": str(target_id)})  # fmt: skip


def seat(client, owner, f, hour: float, **extra) -> str:
    booking = book(client, owner, f, [f.court], at(hour, SOON), at(hour + 1, SOON), kind="session",
                   session={"capacity": 4}, **extra)  # fmt: skip
    return ok(booking, 201)["booking"]["session"]["id"]


def usage_rows(tenant) -> list[AppUsageDay]:
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        rows = list(session.scalars(select(AppUsageDay).order_by(AppUsageDay.kind, AppUsageDay.name)))
        session.expunge_all()
        return rows


# --- favourites ------------------------------------------------------------------------------------------------


def test_favorites_are_own_idempotent_and_audited(client, tenant, owner, f, mailbox):
    person, portal = portal_member(client, tenant, owner, f, mailbox)
    first = ok(favorite(client, portal, person["id"], "reservation_type", f.type), 201)
    again = ok(favorite(client, portal, person["id"], "reservation_type", f.type), 201)
    assert again["id"] == first["id"]
    listed = ok(client.get(f"{API}/portal/favorites", headers=portal, params={"client_id": person["id"]}))["data"]
    assert [r["id"] for r in listed] == [first["id"]]

    stranger = new_client(client, owner, f.location)
    assert favorite(client, portal, stranger["id"], "reservation_type", f.type).status_code == 404
    assert (
        client.get(f"{API}/portal/favorites", headers=portal, params={"client_id": stranger["id"]}).status_code == 404
    )
    assert favorite(client, owner, person["id"], "reservation_type", f.type).status_code == 404  # staff: no portal

    other, other_portal = portal_member(client, tenant, owner, f, mailbox)
    assert client.delete(f"{API}/portal/favorites/{first['id']}", headers=other_portal).status_code == 404
    assert client.delete(f"{API}/portal/favorites/{first['id']}", headers=portal).status_code == 204
    assert client.delete(f"{API}/portal/favorites/{first['id']}", headers=portal).status_code == 404
    with tenant_session(tenant.id) as session:
        actions = session.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == UUID(first["id"]))).all()
    assert sorted(actions) == [member.FAVORITE_ADD, member.FAVORITE_REMOVE]


def test_targets_must_exist_in_this_tenant(client, tenant, owner, f, mailbox):
    person, portal = portal_member(client, tenant, owner, f, mailbox)
    camp = program(client, owner, f)
    assert ok(favorite(client, portal, person["id"], "program_group", camp["id"]), 201)["kind"] == "program_group"
    foreign = make_tenant()
    foreign_owner = login(client, foreign)
    elsewhere = facility(client, foreign_owner)
    foreign_camp = program(client, foreign_owner, elsewhere)
    for kind, target in (("reservation_type", elsewhere.type), ("program_group", foreign_camp["id"]),
                         ("program_group", f.type), ("reservation_type", uuid4())):  # fmt: skip
        refused = favorite(client, portal, person["id"], kind, target)
        assert (refused.status_code, refused.json()["code"]) == (422, "unknown-target"), (kind, target)


def test_schedule_shows_favourite_groups_and_types_within_31_days(client, tenant, owner, f, mailbox):
    ok(client.put(f"{API}/locations/{f.location}/session-booking-policy", headers=owner, json=POLICY))
    typed = seat(client, owner, f, 9, reservation_type_id=f.type)
    play = ok(client.post(f"{API}/reservation-types", headers=owner, json={
        "location_id": f.location, "name": "Open play", "default_capacity": 4, "color": "#2266aa"}), 201)["id"]  # fmt: skip
    linked, other = (
        seat(client, owner, f, 11, reservation_type_id=play),
        seat(client, owner, f, 13, reservation_type_id=play),
    )
    camp = program(client, owner, f)
    ok(client.post(f"{API}/program-groups/{camp['id']}/sessions", headers=owner, json={"session_ids": [linked]}))
    person, portal = portal_member(client, tenant, owner, f, mailbox)
    url = f"{API}/portal/favorites/schedule"
    window = {"client_id": person["id"], "from": clock.now().isoformat(),
              "to": (clock.now() + timedelta(days=7)).isoformat()}  # fmt: skip
    assert ok(client.get(url, headers=portal, params=window))["data"] == []

    ok(favorite(client, portal, person["id"], "reservation_type", f.type), 201)
    ok(favorite(client, portal, person["id"], "program_group", camp["id"]), 201)
    rows = ok(client.get(url, headers=portal, params=window))["data"]
    assert {r["session_id"]: r["program_group_id"] for r in rows} == {typed: None, linked: camp["id"]}
    assert other not in {r["session_id"] for r in rows}

    too_long = window | {"to": (clock.now() + timedelta(days=32)).isoformat()}
    backwards = window | {"to": window["from"], "from": window["to"]}
    for params in (too_long, backwards):
        refused = client.get(url, headers=portal, params=params)
        assert (refused.status_code, refused.json()["code"]) == (422, "invalid-range")
    stranger = new_client(client, owner, f.location)
    assert client.get(url, headers=portal, params=window | {"client_id": stranger["id"]}).status_code == 404


def test_merge_drops_duplicate_favourites_and_erasure_deletes_them(client, tenant, owner, f, mailbox):
    person, portal = portal_member(client, tenant, owner, f, mailbox)
    survivor, survivor_portal = portal_member(client, tenant, owner, f, mailbox)
    camp = program(client, owner, f)
    ok(favorite(client, portal, person["id"], "reservation_type", f.type), 201)
    ok(favorite(client, portal, person["id"], "program_group", camp["id"]), 201)
    ok(favorite(client, survivor_portal, survivor["id"], "reservation_type", f.type), 201)
    ok(client.post(f"{API}/clients/{survivor['id']}/merge", headers=owner,
                   json={"merged_client_ids": [person["id"]]}), 200)  # fmt: skip
    with tenant_session(tenant.id) as session:
        held = session.execute(select(ClientFavorite.client_id, ClientFavorite.kind)).all()
    assert sorted((str(c), k) for c, k in held) == [(survivor["id"], "program_group"),
                                                   (survivor["id"], "reservation_type")]  # fmt: skip

    handler = privacy.HANDLERS["engagement_favorite"]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert len(handler.export(session, UUID(survivor["id"]))["app_favorites"]) == 2
        assert handler.erase(session, UUID(survivor["id"])) == {"app_favorites_deleted": 2}


# --- usage counts ------------------------------------------------------------------------------------------------


def test_usage_adds_up_per_day_and_stores_no_sender(client, tenant, owner, f, mailbox):
    _, portal = portal_member(client, tenant, owner, f, mailbox)
    url = f"{API}/portal/app-usage"
    body = {"items": [{"kind": "screen", "name": "home", "count": 2}, {"kind": "screen", "name": "home", "count": 1},
                      {"kind": "action", "name": "book.tap", "count": 5}]}  # fmt: skip
    assert client.post(url, headers=portal, json=body).status_code == 204
    assert (
        client.post(url, headers=portal, json={"items": [{"kind": "screen", "name": "home", "count": 4}]}).status_code
        == 204
    )
    rows = usage_rows(tenant)
    assert [(r.kind, r.name, r.count, r.day) for r in rows] == [
        ("action", "book.tap", 5, clock.now().date()), ("screen", "home", 7, clock.now().date())]  # fmt: skip
    assert set(AppUsageDay.__table__.columns.keys()) == {"id", "tenant_id", "day", "kind", "name", "count",
                                                         "created_at", "updated_at"}  # fmt: skip

    for bad in ({"items": []}, {"items": [{"kind": "screen", "name": "Home!", "count": 1}]},
                {"items": [{"kind": "screen", "name": "home", "count": 101}]},
                {"items": [{"kind": "screen", "name": "home", "count": 1}] * 51}):  # fmt: skip
        assert client.post(url, headers=portal, json=bad).status_code == 422
    assert client.post(url, json=body).status_code in (401, 403)  # no portal principal
    assert client.post(url, headers=owner, json=body).status_code == 404  # staff are not a portal client

    today = clock.now().date().isoformat()
    listed = ok(client.get(f"{API}/app-usage", headers=owner, params={"from": today, "to": today, "kind": "screen"}))
    assert listed["data"] == [{"day": today, "kind": "screen", "name": "home", "count": 7}]
    long = {"from": (clock.now() - timedelta(days=90)).date().isoformat(), "to": today}
    refused = client.get(f"{API}/app-usage", headers=owner, params=long)
    assert (refused.status_code, refused.json()["code"]) == (422, "invalid-range")


def test_purge_deletes_rows_older_than_90_days(tenant):
    today = clock.now().date()
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.add_all([AppUsageDay(day=today - timedelta(days=91), kind="screen", name="old", count=1),
                         AppUsageDay(day=today - timedelta(days=90), kind="screen", name="kept", count=1)])  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert retention._PURGERS["engagement_app_usage_day"](session) == 1
    assert [r.name for r in usage_rows(tenant)] == ["kept"]


def test_usage_read_has_both_gates(client, tenant, owner, f):
    today = clock.now().date().isoformat()
    params = {"from": today, "to": today}
    desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    assert client.get(f"{API}/app-usage", headers=desk, params=params).status_code == 403
    manager = login(client, tenant, add_staff(tenant, "manager", all_locations=True)[0])
    assert ok(client.get(f"{API}/app-usage", headers=manager, params=params))["data"] == []

    nobody = Principal(kind="staff", tenant_id=tenant.id, permissions={})
    with pytest.raises(PermissionDenied), tenant_session(tenant.id) as session:
        member.list_usage(session, nobody, clock.now().date(), clock.now().date(), None)
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(AppUsageDay)) == 0
