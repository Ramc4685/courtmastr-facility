"""programs x packages x scheduling: a package pays for a place in a session (PKG-12), end to end through the
HTTP API. The credit is held at enrolment and follows the attendance mark and the cancellation."""

import pytest

from app.modules.memberships.tests.support import package_plan
from app.modules.packages.tests.test_packages import package
from app.modules.scheduling.tests.helpers import API, at, book, facility, ok
from conftest import add_staff, login, new_client


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def lesson(client, owner, f, hour: float) -> str:
    """A two-seat session of the facility's reservation type that cannot be booked for free."""
    booking = book(client, owner, f, [f.court], at(hour), at(hour + 1), kind="session",
                   session={"capacity": 2, "allows_free_booking": False})  # fmt: skip
    return ok(booking)["booking"]["session"]["id"]


def sold(client, owner, tenant, f, person: str, **plan) -> str:
    plan = package_plan(client, owner, tenant, reservation_type_id=f.type, **plan)
    body = {"client_id": person, "location_id": f.location, "package_plan_id": plan["id"]}
    return ok(client.post(f"{API}/client-packages", headers=owner, json=body))["id"]


def counts(tenant, package_id: str) -> tuple[int, int]:
    row = package(tenant, package_id)
    return row.sessions_reserved_count, row.sessions_consumed_count


def test_a_package_pays_for_the_place_and_follows_the_attendance_mark(client, owner, tenant, f):
    person, other = (new_client(client, owner, f.location)["id"] for _ in range(2))
    pack = sold(client, owner, tenant, f, person, session_count=3)
    seat = lesson(client, owner, f, 10)
    email, _ = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, email)
    place = {"session_id": seat, "client_id": person}

    free = client.post(f"{API}/enrollments", headers=desk, json=place)
    assert (free.status_code, free.json()["code"]) == (403, "permission-denied")  # this session needs a package
    stranger = client.post(
        f"{API}/enrollments", headers=desk, json=place | {"client_id": other, "client_package_id": pack}
    )
    assert (stranger.status_code, stranger.json()["code"]) == (409, "package-not-shared")
    assert ok(client.get(f"{API}/sessions/{seat}", headers=owner), 200)["booked_count"] == 0  # the seat rolled back

    row = ok(client.post(f"{API}/enrollments", headers=desk, json=place | {"client_package_id": pack}))
    assert row["pricing"] == "entitlement" and counts(tenant, pack) == (1, 0)

    def mark(status: str) -> None:
        body = {"marks": [{"enrollment_id": row["id"], "status": status}]}
        ok(client.put(f"{API}/sessions/{seat}/attendance", headers=owner, json=body), 200)

    mark("attended")
    assert counts(tenant, pack) == (0, 1)
    mark("attended")  # the same mark again changes nothing
    assert counts(tenant, pack) == (0, 1)
    mark("excused")  # a corrected mark gives the credit back
    assert counts(tenant, pack) == (0, 0)
    mark("no_show")  # charged by default, on the same package
    assert counts(tenant, pack) == (0, 1)
    mark("attended")
    assert counts(tenant, pack) == (0, 1)


def test_cancelling_returns_the_credit_and_the_package_must_fit_the_session(client, owner, tenant, f):
    person = new_client(client, owner, f.location)["id"]
    pack = sold(client, owner, tenant, f, person, session_count=1)
    first, second = lesson(client, owner, f, 10), lesson(client, owner, f, 12)
    place = {"client_id": person, "client_package_id": pack}

    row = ok(client.post(f"{API}/enrollments", headers=owner, json=place | {"session_id": first}))
    spent = client.post(f"{API}/enrollments", headers=owner, json=place | {"session_id": second})
    assert (spent.status_code, spent.json()["code"]) == (409, "package-exhausted")
    ok(client.post(f"{API}/enrollments/{row['id']}/cancel", headers=owner, json={"cancel_kind": "early"}), 200)
    assert counts(tenant, pack) == (0, 0)
    ok(client.post(f"{API}/enrollments", headers=owner, json=place | {"session_id": second}))
    assert counts(tenant, pack) == (1, 0)

    other_type = ok(client.post(f"{API}/reservation-types", headers=owner,
                                json={"location_id": f.location, "name": "Yoga"}))["id"]  # fmt: skip
    yoga = ok(book(client, owner, f, [f.court2], at(10), at(11), kind="session", reservation_type_id=other_type,
                   session={"capacity": 2}))["booking"]["session"]["id"]  # fmt: skip
    wrong = client.post(f"{API}/enrollments", headers=owner, json=place | {"session_id": yoga})
    assert (wrong.status_code, wrong.json()["code"]) == (409, "package-wrong-type")
    unknown = client.post(f"{API}/enrollments", headers=owner,
                          json={"session_id": yoga, "client_id": person, "client_package_id": person})  # fmt: skip
    assert unknown.status_code == 422 and unknown.json()["errors"][0]["pointer"] == "/client_package_id"
