"""resources: schedule groups, the resource record, standing links and availability windows."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.audit import AuditEvent
from app.core.db.session import tenant_session
from app.core.errors import PermissionDenied
from app.core.events import OutboxEvent
from app.modules.platform import auth
from app.modules.resources import service
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import add_staff, login


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def test_groups(client, owner, f):
    second = ok(
        client.post(
            f"{API}/resource-groups",
            headers=owner,
            json={"location_id": f.location, "name": "Studios", "sort_order": 2},
        )
    )
    assert (
        client.post(
            f"{API}/resource-groups", headers=owner, json={"location_id": f.location, "name": "Studios"}
        ).json()["code"]
        == "already-exists"
    )
    assert (
        client.post(
            f"{API}/resource-groups", headers=owner, json={"location_id": str(uuid4()), "name": "X"}
        ).status_code
        == 422
    )
    names = [
        g["name"] for g in ok(client.get(f"{API}/resource-groups?location_id={f.location}", headers=owner), 200)["data"]
    ]
    assert names == ["Courts", "Studios"]
    assert (
        ok(
            client.patch(
                f"{API}/resource-groups/{second['id']}", headers=owner, json={"name": "Rooms", "is_active": False}
            ),
            200,
        )["is_active"]
        is False
    )
    in_use = client.patch(f"{API}/resource-groups/{f.group}", headers=owner, json={"is_active": False})
    assert in_use.status_code == 409 and in_use.json()["code"] == "resource-group-in-use"
    retired = {"location_id": f.location, "resource_group_id": second["id"], "name": "Studio 1"}
    assert (
        client.post(f"{API}/resources", headers=owner, json=retired).json()["errors"][0]["pointer"]
        == "/resource_group_id"
    )


def test_resource_kinds_names_and_edits(client, owner, f, tenant):
    base = {"location_id": f.location, "resource_group_id": f.group}
    room = ok(
        client.post(
            f"{API}/resources",
            headers=owner,
            json=base | {"name": "Zoom host 1", "kind": "virtual_room", "external_ref": "host-123"},
        )
    )
    assert (room["kind"], room["counts_toward_plan"], room["parent_id"]) == ("virtual_room", False, None)
    assert (
        client.post(
            f"{API}/resources", headers=owner, json=base | {"name": "No ref", "kind": "virtual_room"}
        ).status_code
        == 422
    )
    assert (
        client.post(f"{API}/resources", headers=owner, json=base | {"name": "Ref", "external_ref": "x"}).status_code
        == 422
    )
    assert (
        client.post(f"{API}/resources", headers=owner, json=base | {"name": "Court 2"}).json()["code"]
        == "already-exists"
    )
    same_name_elsewhere = client.post(
        f"{API}/resources", headers=owner, json=base | {"name": "Court 2", "parent_id": f.court}
    )
    assert same_name_elsewhere.status_code == 201  # names are unique per parent, not per location
    assert (
        client.post(
            f"{API}/resources", headers=owner, json=base | {"name": "X", "staff_user_id": str(tenant.owner_id)}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/resources",
            headers=owner,
            json=base | {"name": "Coach X", "kind": "trainer", "staff_user_id": str(uuid4())},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/resources", headers=owner, json=base | {"name": "Orphan", "parent_id": str(uuid4())}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/resources", headers=owner, json=base | {"name": "Under coach", "parent_id": f.coach}
        ).status_code
        == 422
    )
    edited = ok(
        client.patch(
            f"{API}/resources/{f.court2}",
            headers=owner,
            json={"public_name": "Show court", "is_online_bookable": False, "sort_order": 5},
        ),
        200,
    )
    assert (edited["public_name"], edited["is_online_bookable"], edited["sort_order"]) == ("Show court", False, 5)
    assert (
        client.patch(f"{API}/resources/{f.court2}", headers=owner, json={"resource_group_id": str(uuid4())}).status_code
        == 422
    )
    listing = ok(
        client.get(f"{API}/resources?location_id={f.location}&kind=venue&parent_id={f.court}&sort=name", headers=owner),
        200,
    )["data"]
    assert [r["name"] for r in listing] == ["Court 1A", "Court 1B", "Court 2"]
    assert [r["name"] for r in ok(client.get(f"{API}/resources?q=kim", headers=owner), 200)["data"]] == ["Coach Kim"]
    archived = ok(client.post(f"{API}/resources/{f.court2}/archive", headers=owner), 200)
    assert (
        archived["status"] == "archived"
        and ok(client.post(f"{API}/resources/{f.court2}/archive", headers=owner), 200)["status"] == "archived"
    )
    assert client.patch(f"{API}/resources/{f.court2}", headers=owner, json={"name": "X"}).status_code == 409
    assert ok(client.post(f"{API}/resources/{f.court2}/restore", headers=owner), 200)["status"] == "active"
    with tenant_session(tenant.id) as session:
        types = set(session.scalars(select(OutboxEvent.event_type).where(OutboxEvent.event_type.like("resources.%"))))
        audited = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == f.court2)).all()
    assert types == {"resources.resource.created", "resources.resource.archived", "resources.resource.tree_changed"}
    assert [a.action for a in audited] == ["resources.resource.manage"] * 4 and audited[1].changes[
        "public_name"
    ] is True


def test_links(client, owner, f):
    url = f"{API}/resources/{f.coach}/links"
    assert ok(client.put(url, headers=owner, json={"to_resource_ids": [f.court, f.court2]}), 200)[
        "linked_resource_ids"
    ] == sorted([f.court, f.court2])
    assert ok(client.put(url, headers=owner, json={"to_resource_ids": [f.court2]}), 200)["linked_resource_ids"] == [
        f.court2
    ]
    assert ok(client.get(f"{API}/resources/{f.coach}", headers=owner), 200)["linked_resource_ids"] == [f.court2]
    assert (
        client.put(url, headers=owner, json={"to_resource_ids": [f.coach]}).json()["errors"][0]["pointer"]
        == "/to_resource_ids/0"
    )
    assert (
        client.put(url, headers=owner, json={"to_resource_ids": [f.court2, str(uuid4())]}).json()["errors"][0][
            "pointer"
        ]
        == "/to_resource_ids/1"
    )
    assert ok(client.put(url, headers=owner, json={"to_resource_ids": []}), 200)["linked_resource_ids"] == []


def test_availability_windows(client, owner, f, tenant):
    url = f"{API}/resources/{f.coach}/availability-windows"
    body = {"starts_on": "2031-05-01", "weekdays": [2, 4], "start_time": "09:00", "end_time": "12:00"}
    window = ok(client.post(url, headers=owner, json=body | {"interval_weeks": 2, "note": "Mornings"}))
    assert (
        window["weekdays"],
        window["start_time"],
        window["end_time"],
        window["interval_weeks"],
        window["is_active"],
    ) == ([2, 4], "09:00", "12:00", 2, True)
    ok(
        client.post(
            url, headers=owner, json=body | {"starts_on": "2031-01-01", "ends_on": "2031-01-01", "end_time": "24:00"}
        )
    )
    assert [w["starts_on"] for w in ok(client.get(url, headers=owner), 200)] == ["2031-01-01", "2031-05-01"]
    for bad in (
        {"end_time": "08:00"},
        {"weekdays": []},
        {"weekdays": [8]},
        {"interval_weeks": 9},
        {"ends_on": "2031-04-01"},
        {"start_time": "9am"},
    ):
        assert client.post(url, headers=owner, json=body | bad).status_code == 422, bad
    one = f"{API}/availability-windows/{window['id']}"
    assert (
        ok(client.patch(one, headers=owner, json={"is_active": False, "end_time": "13:00"}), 200)["end_time"] == "13:00"
    )
    assert client.patch(one, headers=owner, json={"end_time": "08:00"}).status_code == 422
    assert client.delete(one, headers=owner).status_code == 204 and client.delete(one, headers=owner).status_code == 404
    assert len(ok(client.get(url, headers=owner), 200)) == 1


def test_permissions_and_service_gate(client, owner, f, tenant):
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    assert client.get(f"{API}/resources", headers=desk).status_code == 200  # any signed-in staff reads
    assert (
        client.post(f"{API}/resource-groups", headers=desk, json={"location_id": f.location, "name": "X"}).status_code
        == 403
    )
    assert client.post(f"{API}/resources/{f.court}/archive", headers=desk).status_code == 403
    assert client.put(f"{API}/resources/{f.coach}/links", headers=desk, json={"to_resource_ids": []}).status_code == 403
    assert (
        client.post(
            f"{API}/resources/{f.coach}/availability-windows",
            headers=desk,
            json={"starts_on": "2031-05-01", "weekdays": [1], "start_time": "09:00", "end_time": "10:00"},
        ).status_code
        == 403
    )
    with tenant_session(tenant.id) as session:
        principal = auth.authenticate(session, desk["Authorization"].removeprefix("Bearer "))
        location, court, court2, coach = (UUID(value) for value in (f.location, f.court, f.court2, f.coach))
        for call in (
            lambda: service.create_group(session, principal, {"location_id": location, "name": "X"}),
            lambda: service.update_resource(session, principal, court, {"name": "X"}),
            lambda: service.archive_resource(session, principal, court2),
            lambda: service.restore_resource(session, principal, court2),
            lambda: service.replace_links(session, principal, coach, []),
            lambda: service.create_window(session, principal, coach, {}),
        ):
            with pytest.raises(PermissionDenied):
                call()
