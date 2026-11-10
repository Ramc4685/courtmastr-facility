"""Calendar and availability reads, master data, sessions, permissions, audit and the 1,500-occurrence run."""

import time
from datetime import date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.core.events import OutboxEvent
from app.modules.scheduling import service
from app.modules.scheduling.models import Booking, ResourceHold, SchedulingSettings
from app.modules.scheduling.tests.helpers import API, at, book, booking_body, drain, facility, local, ok
from conftest import WEEK, add_staff, login


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def calendar(client, headers, f, start: str, end: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in ({"location_id": f.location, "from": start, "to": end} | params).items())
    return ok(client.get(f"{API}/calendar?{query}", headers=headers), 200)


def test_calendar_is_one_tile_per_booking_and_column_with_colour_fill_and_legend(client, owner, f, tenant):
    session_booking = ok(book(client, owner, f, [f.coach, f.half_a], at(10), at(11), kind="session", title="Juniors"))[
        "booking"
    ]
    ok(book(client, owner, f, [f.court2], at(34), at(35)))  # next day, a time block
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        service.reserve_seat(session, UUID(session_booking["session"]["id"]), 4)
    view = calendar(client, owner, f, at(0), at(24))
    assert (view["time_zone"], view["calendar_slot_min"]) == ("America/Chicago", 15)
    assert [r["name"] for r in view["resources"]] == [
        "Coach Kim",
        "Court 1",
        "Court 1A",
        "Court 1A-1",
        "Court 1B",
        "Court 2",
    ]
    tiles = {e["resource_id"]: e for e in view["entries"]}
    # The trainer column draws the tile, the booked venue is "additional", its sub-venue a greyed descendant.
    assert {r: t["resource_role"] for r, t in tiles.items()} == {
        f.coach: "primary",
        f.half_a: "additional",
        f.quarter: "descendant",
    }
    tile = tiles[f.coach]
    assert (tile["title"], tile["color"], tile["capacity"], tile["booked_count"], tile["fill"]) == (
        "Juniors",
        "#22aa66",
        4,
        4,
        "full",
    )
    assert (
        tile["can_edit"] is True
        and tile["version"] == 1
        and tile["booking_number"] == session_booking["booking_number"]
    )
    assert view["legend"] == {
        "reservation_types": [{"reservation_type_id": f.type, "name": "Clinic", "color": "#22aa66"}],
        "fill_states": ["empty", "partial", "full"],
    }
    week = calendar(client, owner, f, at(0), at(24 * 7))
    assert len(week["entries"]) == 4 and {e["kind"] for e in week["entries"]} == {"session", "block"}
    assert week["entries"][-1]["fill"] is None and week["entries"][-1]["block_kind"] == "unavailable"
    month = calendar(client, owner, f, at(-24 * 4), at(24 * 31), **{"kind[in]": "block"})
    assert [e["resource_id"] for e in month["entries"]] == [f.court2]
    assert [
        e["resource_id"]
        for e in calendar(client, owner, f, at(0), at(48), **{"resource_id[in]": f"{f.half_a},{f.court2}"})["entries"]
    ] == [f.half_a, f.court2]
    assert len(calendar(client, owner, f, at(0), at(48), **{"reservation_type_id[in]": f.type})["entries"]) == 3
    assert calendar(client, owner, f, at(0), at(24), resource_group_id=str(uuid4()))["resources"] == []
    assert (
        calendar(client, owner, f, at(11), at(12))["entries"] == []
    )  # half-open: an 11:00 end is not in 11:00 to 12:00
    too_wide = client.get(f"{API}/calendar?location_id={f.location}&from={at(0)}&to={at(24 * 43)}", headers=owner)
    assert too_wide.status_code == 422
    # A six-week month grid across the autumn clock change is 42 days and one hour of UTC: still one window.
    calendar(client, owner, f, "2026-10-26T00:00:00-05:00", "2026-12-07T00:00:00-06:00")
    assert (
        client.get(
            f"{API}/calendar?location_id={f.location}&from={at(0)}&to={at(24)}&resource_id[in]=nope", headers=owner
        ).status_code
        == 422
    )
    assert (
        client.get(f"{API}/calendar?location_id={uuid4()}&from={at(0)}&to={at(24)}", headers=owner).status_code == 422
    )


def test_calendar_shows_closures_and_facility_hours(client, owner, f):
    ok(client.put(f"{API}/locations/{f.location}/facility-hours", headers=owner, json={"days": WEEK}), 200)
    ok(
        client.post(
            f"{API}/blackouts",
            headers=owner,
            json={"location_id": f.location, "name": "Holiday", "starts_at": at(0), "ends_at": at(24)},
        )
    )
    view = calendar(client, owner, f, at(0), at(24))
    assert view["blackouts"][0]["name"] == "Holiday" and len(view["facility_hours"]) == 7
    assert view["facility_hours"][0] == {
        "weekday": 1,
        "opens_time": "08:00",
        "closes_time": "20:00",
        "is_closed": False,
    }


def free(client, headers, f, start: str, end: str, resources: str, minimum: int = 15) -> dict:
    url = f"{API}/availability?location_id={f.location}&from={start}&to={end}&resource_id[in]={resources}&min_free_min={minimum}"
    return {
        r["resource_id"]: [(i["starts_at"], i["ends_at"]) for i in r["free"]]
        for r in ok(client.get(url, headers=headers), 200)["resources"]
    }


def test_availability_is_windows_or_hours_minus_holds_and_closures(client, owner, f):
    zone = "America/Chicago"
    ok(client.put(f"{API}/locations/{f.location}/facility-hours", headers=owner, json={"days": WEEK}), 200)
    day = (2031, 5, 5)
    window = {"starts_on": "2031-05-01", "weekdays": [1], "start_time": "09:00", "end_time": "12:00"}
    ok(client.post(f"{API}/resources/{f.coach}/availability-windows", headers=owner, json=window))
    ok(book(client, owner, f, [f.coach, f.half_a], local(zone, *day, 10), local(zone, *day, 11), buffer_after_min=15))
    start, end = local(zone, *day, 0), local(zone, 2031, 5, 6, 0)
    result = free(client, owner, f, start, end, f"{f.coach},{f.court},{f.half_b},{f.court2}")
    # The trainer is offered inside the window only; the booking's buffer is busy time too.
    assert result[f.coach] == [
        (local(zone, *day, 9), local(zone, *day, 10)),
        (local(zone, *day, 11, 15), local(zone, *day, 12)),
    ]
    # A venue with no window follows facility hours. Court 1 is not free while its half is booked ...
    assert result[f.court2] == [(local(zone, *day, 8), local(zone, *day, 20))]
    assert result[f.half_b] == [(local(zone, *day, 8), local(zone, *day, 20))]  # ... but the sibling half is
    assert free(client, owner, f, start, end, f.half_a)[f.half_a][0] == (local(zone, *day, 8), local(zone, *day, 10))
    ok(
        client.post(
            f"{API}/blackouts",
            headers=owner,
            json={
                "location_id": f.location,
                "name": "Lunch",
                "starts_at": local(zone, *day, 12),
                "ends_at": local(zone, *day, 19, 50),
            },
        )
    )
    assert free(client, owner, f, start, end, f.court2)[f.court2] == [
        (local(zone, *day, 8), local(zone, *day, 12))
    ]  # 10 minutes is too short
    assert len(free(client, owner, f, start, end, f.court2, 10)[f.court2]) == 2
    assert (
        free(client, owner, f, local(zone, 2031, 5, 6, 0), local(zone, 2031, 5, 7, 0), f.coach)[f.coach] == []
    )  # a Tuesday
    assert (
        client.get(f"{API}/availability?location_id={f.location}&from={start}&to={start}", headers=owner).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("zone", "day", "open_minutes"),
    [
        ("America/Chicago", (2031, 3, 9), 23 * 60), ("America/Chicago", (2031, 11, 2), 25 * 60),
        ("Asia/Kolkata", (2031, 3, 9), 24 * 60), ("Pacific/Auckland", (2031, 9, 28), 23 * 60),
        ("Pacific/Auckland", (2031, 4, 6), 25 * 60),
    ],
)  # fmt: skip
def test_availability_follows_the_local_day_across_dst(client, owner, zone, day, open_minutes):
    """Open around the clock: a local day is 23, 24 or 25 hours long."""
    f = facility(client, owner, zone)
    all_day = [{"weekday": d, "opens_time": "00:00", "closes_time": "24:00", "is_closed": d == 2} for d in range(1, 8)]
    ok(client.put(f"{API}/locations/{f.location}/facility-hours", headers=owner, json={"days": all_day}), 200)
    start = date(*day)
    nxt = start.fromordinal(start.toordinal() + 1)
    result = free(client, owner, f, local(zone, *day, 0), local(zone, nxt.year, nxt.month, nxt.day, 0), f.court2)[
        f.court2
    ]
    total = sum((datetime.fromisoformat(e) - datetime.fromisoformat(s)).total_seconds() for s, e in result) / 60
    assert total == open_minutes and len(result) == 1


def test_settings_types_and_categories(client, owner, f, tenant):
    url = f"{API}/scheduling-settings"
    assert ok(client.get(url, headers=owner), 200)["location_id"] is None  # the tenant default, created on first use
    ok(client.patch(url, headers=owner, json={"calendar_slot_min": 30}), 200)
    assert ok(client.get(f"{url}?location_id={f.location}", headers=owner), 200)["calendar_slot_min"] == 30  # inherited
    own = ok(client.patch(f"{url}?location_id={f.location}", headers=owner, json={"checkout_hold_min": 20}), 200)
    assert (own["location_id"], own["calendar_slot_min"], own["checkout_hold_min"]) == (f.location, 30, 20)
    assert (
        ok(
            client.patch(f"{url}?location_id={f.location}", headers=owner, json={"drag_drop_default": "reschedule"}),
            200,
        )["checkout_hold_min"]
        == 20
    )
    assert client.patch(url, headers=owner, json={"calendar_slot_min": 7}).status_code == 422
    assert client.get(f"{url}?location_id={uuid4()}", headers=owner).status_code == 422
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(SchedulingSettings)) == 2

    parent = ok(
        client.post(f"{API}/reservation-categories", headers=owner, json={"location_id": f.location, "name": "Racquet"})
    )
    child = ok(
        client.post(
            f"{API}/reservation-categories",
            headers=owner,
            json={"location_id": f.location, "name": "Tennis", "parent_id": parent["id"]},
        )
    )
    deeper = client.post(
        f"{API}/reservation-categories",
        headers=owner,
        json={"location_id": f.location, "name": "Clay", "parent_id": child["id"]},
    )
    assert deeper.status_code == 422  # two levels only
    assert (
        ok(client.patch(f"{API}/reservation-categories/{child['id']}", headers=owner, json={"name": "Padel"}), 200)[
            "name"
        ]
        == "Padel"
    )
    assert (
        len(ok(client.get(f"{API}/reservation-categories?location_id={f.location}", headers=owner), 200)["data"]) == 2
    )

    new = {
        "location_id": f.location,
        "name": "Private lesson",
        "reservation_category_id": child["id"],
        "default_capacity": 1,
        "default_duration_min": 30,
    }
    rtype = ok(client.post(f"{API}/reservation-types", headers=owner, json=new))
    assert (
        rtype["default_capacity"],
        rtype["uses_default_buffer"],
        rtype["is_self_bookable_default"],
        rtype["color"],
    ) == (1, True, True, None)
    assert client.post(f"{API}/reservation-types", headers=owner, json=new).json()["code"] == "already-exists"
    assert (
        client.post(f"{API}/reservation-types", headers=owner, json=new | {"name": "Bad", "color": "red"}).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/reservation-types",
            headers=owner,
            json=new | {"name": "Bad", "reservation_category_id": str(uuid4())},
        ).status_code
        == 422
    )
    assert ok(client.get(f"{API}/reservation-types/{rtype['id']}", headers=owner), 200)["name"] == "Private lesson"
    assert [
        t["name"]
        for t in ok(client.get(f"{API}/reservation-types?location_id={f.location}&q=private", headers=owner), 200)[
            "data"
        ]
    ] == ["Private lesson"]
    # Defaults are copied at creation; editing the type changes only what is created afterwards (CLS-04).
    before = ok(book(client, owner, f, [f.court], at(10), at(11), kind="session", reservation_type_id=rtype["id"]))[
        "booking"
    ]
    ok(
        client.patch(
            f"{API}/reservation-types/{rtype['id']}",
            headers=owner,
            json={"default_capacity": 8, "is_self_bookable_default": False, "reservation_category_id": None},
        ),
        200,
    )
    after = ok(book(client, owner, f, [f.court], at(12), at(13), kind="session", reservation_type_id=rtype["id"]))[
        "booking"
    ]
    assert (before["session"]["capacity"], after["session"]["capacity"], after["session"]["is_self_bookable"]) == (
        1,
        8,
        False,
    )
    assert ok(client.get(f"{API}/bookings/{before['id']}", headers=owner), 200)["session"]["capacity"] == 1
    assert before["title"] == "Private lesson"  # a session takes its type's name unless titled
    # An archived type keeps its bookings and cannot be scheduled again.
    ok(client.patch(f"{API}/reservation-types/{rtype['id']}", headers=owner, json={"is_active": False}), 200)
    assert (
        book(client, owner, f, [f.court], at(14), at(15), kind="session", reservation_type_id=rtype["id"]).status_code
        == 422
    )
    untyped = ok(book(client, owner, f, [f.court], at(16), at(17), kind="session", reservation_type_id=None))["booking"]
    assert (untyped["session"]["capacity"], untyped["session"]["is_self_bookable"]) == (0, False)  # a placeholder
    retyped = ok(
        client.patch(
            f"{API}/bookings/{untyped['id']}",
            headers=owner,
            json={"reservation_type_id": f.type, "title": None, "version": 1},
        ),
        200,
    )
    assert (retyped["reservation_type_id"], retyped["title"]) == (f.type, "")
    block = ok(book(client, owner, f, [f.court2], at(16), at(17)))["booking"]
    assert (
        client.patch(
            f"{API}/bookings/{block['id']}", headers=owner, json={"reservation_type_id": f.type, "version": 1}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"{API}/bookings/{untyped['id']}", headers=owner, json={"block_kind": "unpaid", "version": 2}
        ).status_code
        == 422
    )
    assert (
        ok(
            client.patch(
                f"{API}/bookings/{block['id']}", headers=owner, json={"block_kind": "floor_shift", "version": 1}
            ),
            200,
        )["block_kind"]
        == "floor_shift"
    )


def test_sessions_capacity_and_seats(client, owner, f, tenant):
    system = system_principal("tests")
    first = ok(book(client, owner, f, [f.court], at(10), at(11), kind="session", session={"capacity": 2}))["booking"]
    second = ok(book(client, owner, f, [f.court], at(12), at(13), kind="session"))["booking"]
    one, two = first["session"]["id"], second["session"]["id"]
    with tenant_session(tenant.id, actor=system) as session:
        assert service.reserve_seat(session, UUID(one), 2).booked_count == 2
        with pytest.raises(Conflict) as full:
            service.reserve_seat(session, UUID(one))
        assert full.value.code == "capacity-full"
        with pytest.raises(NotFound):
            service.reserve_seat(session, uuid4())
        with pytest.raises(NotFound):
            service.get_session(session, uuid4())
    listed = ok(client.get(f"{API}/sessions?location_id={f.location}&sort=starts_at", headers=owner), 200)["data"]
    assert [(s["id"], s["fill"], s["capacity"]) for s in listed] == [(one, "full", 2), (two, "empty", 4)]
    changed = ok(
        client.post(f"{API}/sessions/capacity-changes", headers=owner, json={"session_ids": [one, two], "capacity": 1}),
        200,
    )
    by_id = {r["session_id"]: r["status"] for r in changed["results"]}
    assert by_id == {one: "capacity-below-booked", two: "ok"} and changed["changed_count"] == 1
    raised = ok(
        client.post(f"{API}/sessions/capacity-changes", headers=owner, json={"session_ids": [one], "capacity": 5}), 200
    )
    assert raised["results"][0]["capacity"] == 5
    with tenant_session(tenant.id) as session:
        events = (
            session.execute(
                select(OutboxEvent.payload).where(OutboxEvent.event_type == "scheduling.session.capacity_changed")
            )
            .scalars()
            .all()
        )
    assert sorted((e["old_capacity"], e["new_capacity"]) for e in events) == [(2, 5), (4, 1)]
    updated = ok(
        client.patch(
            f"{API}/sessions/{two}", headers=owner, json={"allows_free_booking": False, "is_self_bookable": False}
        ),
        200,
    )
    assert (updated["allows_free_booking"], updated["is_self_bookable"], updated["title"]) == (False, False, "Clinic")
    assert ok(client.get(f"{API}/sessions/{one}", headers=owner), 200)["booked_count"] == 2
    with tenant_session(tenant.id, actor=system) as session:
        assert service.release_seat(session, UUID(one), 5).booked_count == 0  # never below zero
    ok(client.post(f"{API}/bookings/{first['id']}/cancel", headers=owner, json={"version": 1}), 200)
    with tenant_session(tenant.id, actor=system) as session, pytest.raises(Conflict) as closed:
        service.reserve_seat(session, UUID(one))
    assert closed.value.code == "session-not-bookable"
    assert (
        client.patch(f"{API}/bookings/{first['id']}", headers=owner, json={"title": "X", "version": 2}).status_code
        == 409
    )
    assert (
        ok(client.post(f"{API}/bookings/{first['id']}/cancel", headers=owner, json={"version": 2}), 200)["status"]
        == "cancelled"
    )  # idempotent


def test_permissions_per_role_own_reach_and_location_containment(client, owner, tenant, f):
    other = ok(
        client.post(
            f"{API}/locations", headers=owner, json={"name": "Elsewhere", "time_zone": "UTC", "country_code": "US"}
        )
    )["id"]
    elsewhere_group = ok(
        client.post(f"{API}/resource-groups", headers=owner, json={"location_id": other, "name": "Fields"})
    )["id"]
    field = ok(
        client.post(
            f"{API}/resources",
            headers=owner,
            json={"location_id": other, "resource_group_id": elsewhere_group, "name": "Field 1"},
        )
    )["id"]
    far = ok(
        client.post(
            f"{API}/bookings",
            headers=owner,
            json={
                "location_id": other,
                "kind": "block",
                "block_kind": "unpaid",
                "starts_at": at(10),
                "ends_at": at(11),
                "resources": [{"resource_id": field}],
            },
        )
    )["booking"]
    here = ok(book(client, owner, f, [f.court], at(10), at(11), kind="session"))["booking"]
    headers = {
        role: login(client, tenant, add_staff(tenant, role, location_ids=[f.location])[0])
        for role in ("manager", "front_desk", "view_only", "scorekeeper")
    }
    coach_email, coach_id = add_staff(tenant, "coach", location_ids=[f.location])
    mine = ok(
        client.post(
            f"{API}/resources",
            headers=owner,
            json={
                "location_id": f.location,
                "resource_group_id": f.group,
                "name": "Coach Lee",
                "kind": "trainer",
                "staff_user_id": str(coach_id),
            },
        )
    )["id"]
    headers["coach"] = login(client, tenant, coach_email)

    # Router gate follows the matrix.
    assert book(client, headers["front_desk"], f, [f.court2], at(10), at(11), kind="session").status_code == 201
    for role in ("view_only", "scorekeeper"):
        assert book(client, headers[role], f, [f.court2], at(12), at(13)).status_code == 403
    assert (
        client.get(
            f"{API}/calendar?location_id={f.location}&from={at(0)}&to={at(24)}", headers=headers["view_only"]
        ).status_code
        == 200
    )
    assert client.get(f"{API}/bookings", headers=headers["scorekeeper"]).status_code == 403
    assert (
        client.post(
            f"{API}/reservation-types", headers=headers["front_desk"], json={"location_id": f.location, "name": "X"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{API}/blackouts",
            headers=headers["front_desk"],
            json={"location_id": f.location, "name": "X", "starts_at": at(0), "ends_at": at(1)},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{API}/sessions/capacity-changes",
            headers=headers["front_desk"],
            json={"session_ids": [here["session"]["id"]], "capacity": 9},
        ).status_code
        == 403
    )
    series_cancel = client.post(
        f"{API}/booking-series/{uuid4()}/cancellations", headers=headers["front_desk"], json={"scope": {"mode": "all"}}
    )
    assert series_cancel.status_code == 403  # delete_series is Manager and above

    # Location containment: outside the user's locations is 404 and lists are filtered.
    for role in ("manager", "front_desk", "coach"):
        assert client.get(f"{API}/bookings/{far['id']}", headers=headers[role]).status_code == 404
        assert (
            client.post(f"{API}/bookings/{far['id']}/cancel", headers=headers[role], json={"version": 1}).status_code
            == 404
        )
        assert {b["location_id"] for b in ok(client.get(f"{API}/bookings", headers=headers[role]), 200)["data"]} == {
            f.location
        }
    assert (
        client.get(
            f"{API}/calendar?location_id={other}&from={at(0)}&to={at(24)}", headers=headers["manager"]
        ).status_code
        == 422
    )
    assert (
        book(client, headers["manager"], f, [field], at(14), at(15)).status_code == 422
    )  # a resource of another location
    assert {r["location_id"] for r in ok(client.get(f"{API}/resources", headers=headers["manager"]), 200)["data"]} == {
        f.location
    }
    assert client.get(f"{API}/resources/{field}", headers=headers["manager"]).status_code == 404

    # `own` reach: a coach reads the whole calendar and writes only bookings on their own resource.
    assert (
        len(
            ok(
                client.get(
                    f"{API}/calendar?location_id={f.location}&from={at(0)}&to={at(24)}", headers=headers["coach"]
                ),
                200,
            )["entries"]
        )
        >= 1
    )
    assert book(client, headers["coach"], f, [f.court2], at(14), at(15), kind="session").status_code == 403
    own = ok(book(client, headers["coach"], f, [mine, f.court2], at(14), at(15), kind="session"))["booking"]
    assert ok(book(client, headers["coach"], f, [mine], at(16), at(17)))["booking"]["kind"] == "block"
    assert (
        client.post(
            f"{API}/bookings/{here['id']}/reschedule",
            headers=headers["coach"],
            json={"starts_at": at(18), "ends_at": at(19), "version": 1},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{API}/bookings/{own['id']}/reschedule",
            headers=headers["coach"],
            json={"starts_at": at(18), "ends_at": at(19), "version": 1},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{API}/bookings/{own['id']}/reschedule",
            headers=headers["coach"],
            json={"starts_at": at(18), "ends_at": at(19), "version": 2, "resources": [{"resource_id": f.court2}]},
        ).status_code
        == 403
    )
    assert (
        client.post(f"{API}/bookings/{own['id']}/cancel", headers=headers["coach"], json={"version": 2}).status_code
        == 403
    )  # no delete key
    tiles = ok(
        client.get(f"{API}/calendar?location_id={f.location}&from={at(0)}&to={at(24)}", headers=headers["coach"]), 200
    )["entries"]
    assert {t["can_edit"] for t in tiles if t["booking_id"] == own["id"]} == {True} and {
        t["can_edit"] for t in tiles if t["booking_id"] == here["id"]
    } == {False}
    window = {"starts_on": "2031-05-01", "weekdays": [1], "start_time": "09:00", "end_time": "12:00"}
    assert (
        client.post(f"{API}/resources/{mine}/availability-windows", headers=headers["coach"], json=window).status_code
        == 201
    )
    assert (
        client.post(
            f"{API}/resources/{f.coach}/availability-windows", headers=headers["coach"], json=window
        ).status_code
        == 403
    )

    # The service gate holds without the router.
    viewer = service_principal(client, tenant, headers["view_only"])
    with tenant_session(tenant.id, actor=viewer) as session:
        with pytest.raises(PermissionDenied):
            service.create_booking_command(
                session,
                viewer,
                booking_body(f, [UUID(f.court2)], datetime.fromisoformat(at(20)), datetime.fromisoformat(at(21)))
                | {"location_id": UUID(f.location)},
            )
        with pytest.raises(PermissionDenied):
            service.cancel_command(session, viewer, UUID(here["id"]), {"version": 1})
        with pytest.raises(PermissionDenied):
            service.create_type(session, viewer, {"location_id": UUID(f.location), "name": "X"})
        with pytest.raises(PermissionDenied):
            service.update_settings(session, viewer, UUID(f.location), {"calendar_slot_min": 5})
        with pytest.raises(PermissionDenied):
            service.change_capacity(session, viewer, [UUID(here["session"]["id"])], 1)


def service_principal(client, tenant, headers):
    from app.modules.platform import auth

    with tenant_session(tenant.id) as session:
        return auth.authenticate(session, headers["Authorization"].removeprefix("Bearer "))


def test_each_mutation_writes_one_audit_event_and_a_failed_one_writes_none(client, owner, f, tenant):
    def actions() -> list[str]:
        with tenant_session(tenant.id) as session:
            return list(
                session.scalars(
                    select(AuditEvent.action).where(AuditEvent.action.like("scheduling.b%")).order_by(AuditEvent.id)
                )
            )

    booking = ok(book(client, owner, f, [f.court], at(10), at(11), kind="session", notes="Allergy: nuts"))["booking"]
    assert book(client, owner, f, [f.half_a], at(10), at(11)).status_code == 409
    ok(
        client.post(
            f"{API}/bookings/{booking['id']}/reschedule",
            headers=owner,
            json={"starts_at": at(12), "ends_at": at(13), "version": 1},
        ),
        200,
    )
    ok(
        client.patch(f"{API}/bookings/{booking['id']}", headers=owner, json={"notes": "Allergy: none", "version": 2}),
        200,
    )
    ok(book(client, owner, f, [f.court2], at(10), at(11)))
    ok(client.post(f"{API}/bookings/{booking['id']}/cancel", headers=owner, json={"version": 3}), 200)
    assert actions() == [
        "scheduling.booking.create",
        "scheduling.booking.update",
        "scheduling.booking.update",
        "scheduling.block.manage",
        "scheduling.booking.delete",
    ]
    with tenant_session(tenant.id) as session:
        edit = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "scheduling.booking.update").order_by(AuditEvent.id)
        ).all()[1]
        assert edit.changes["notes"] is True and edit.changes["version"] == [2, 3]  # free text is flag-only
        types = list(
            session.scalars(
                select(OutboxEvent.event_type)
                .where(OutboxEvent.event_type.like("scheduling.%"))
                .order_by(OutboxEvent.id)
            )
        )
    assert sorted(types) == [  # ids within one flush are not ordered, so compare as a multiset
        "scheduling.booking.cancelled", "scheduling.booking.created", "scheduling.booking.created",
        "scheduling.booking.rescheduled", "scheduling.session.cancelled", "scheduling.session.created",
    ]  # fmt: skip


def test_fifteen_hundred_linked_occurrences_commit_through_the_worker(client, owner, f, tenant):
    """ADR 0004: a linked series must commit at 1,500+ occurrences (the reference timed out near 300)."""
    body = booking_body(
        f,
        [f.coach, f.court2],
        at(6),
        at(6.5),
        kind="session",
        recurrence={
            "pattern": "daily",
            "weekdays": [1, 2, 3, 4, 5, 6, 7],
            "interval_count": 1,
            "range_type": "count",
            "occurrence_limit": 750,
        },
    )
    started = time.perf_counter()
    first = ok(client.post(f"{API}/bookings", headers=owner, json=body), 202)
    second = ok(
        client.post(
            f"{API}/booking-series/{first['booking_series_id']}/rules",
            headers=owner,
            json={
                "start_on": "2031-05-05",
                "start_time": "09:00",
                "end_time": "09:30",
                "rule": {"pattern": "daily", "range_type": "count", "occurrence_limit": 750},
            },
        ),
        202,
    )
    drain()
    elapsed = time.perf_counter() - started
    for url in (first["status_url"], second["status_url"]):
        run = ok(client.get(url, headers=owner), 200)
        assert (run["status"], run["ok_count"], run["conflict_count"]) == ("completed", 750, 0)
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 1500
        assert session.scalar(select(func.count()).select_from(ResourceHold)) == 3000
    assert (
        ok(client.get(f"{API}/booking-series/{first['booking_series_id']}", headers=owner), 200)["occurrence_count"]
        == 1500
    )
    assert elapsed < 120, f"1,500 occurrences took {elapsed:.0f}s"
    print(f"\n1,500 occurrences with two holds each: {elapsed:.1f}s")
