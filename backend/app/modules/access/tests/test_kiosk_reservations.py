"""The kiosk reservation page, booking from it and auto-book (CHK-05, CHK-06; owner decisions 2026-11-13, question
15). Booking runs the portal's rules for the client the kiosk identified: the kiosk adds no bypass."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core import clock
from app.modules.access.models import CheckIn
from app.modules.access.tests.test_checkin import _pair, ok
from app.modules.memberships.tests.support import API, package_plan, world
from app.modules.programs.models import Enrollment
from conftest import new_client, scalar


def soon(client, owner, loc: str, minutes: int, *, free: bool = True, capacity: int = 5) -> SimpleNamespace:
    """A confirmed, self-bookable session at `loc` starting `minutes` from now, on its own type and resource."""
    tag = uuid4().hex[:6]
    rtype = ok(client.post(f"{API}/reservation-types", headers=owner, json={
        "location_id": loc, "name": f"Class {tag}", "default_capacity": capacity, "default_allows_free_booking": free,
    }), 201)  # fmt: skip
    group = ok(client.post(f"{API}/resource-groups", headers=owner, json={"location_id": loc, "name": f"G {tag}"}), 201)
    room = ok(client.post(f"{API}/resources", headers=owner,
                          json={"location_id": loc, "resource_group_id": group["id"], "name": f"Room {tag}"}), 201)  # fmt: skip
    starts = (clock.now() + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
    booking = ok(client.post(f"{API}/bookings", headers=owner, json={
        "location_id": loc, "kind": "session", "reservation_type_id": rtype["id"], "starts_at": starts.isoformat(),
        "ends_at": (starts + timedelta(hours=1)).isoformat(), "resources": [{"resource_id": room["id"], "role": "primary"}],
    }), 201)  # fmt: skip
    return SimpleNamespace(id=booking["booking"]["session"]["id"], type_id=rtype["id"])


@pytest.fixture
def k(client, tenant, owner):
    w = world(client, owner, tenant)
    person = new_client(client, owner, w.location_id, first_name="Robin", last_name=f"Kiosk{uuid4().hex[:6]}")
    _pair(client, tenant, owner, w.location_id)
    return SimpleNamespace(loc=w.location_id, person=person, tenant=tenant)


def enter(client, person) -> dict:
    found = ok(client.post(f"{API}/kiosk/lookups", json={"last_name_prefix": person["last_name"]}))["matches"]
    return ok(client.post(f"{API}/kiosk/check-ins", json={"match_token": found[0]["match_token"]}), 201)


def book(client, check_in_id, session_id, key: str | None = None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"{API}/kiosk/check-ins/{check_in_id}/attendances", headers=headers,
                       json={"target_type": "session", "target_id": session_id})  # fmt: skip


def test_the_reservation_page_lists_and_books_by_the_portal_rules(client, tenant, owner, k):
    now_free = soon(client, owner, k.loc, 30)
    paid = soon(client, owner, k.loc, 90, free=False)
    later = soon(client, owner, k.loc, 300)  # beyond the default visible range of four hours
    entered = enter(client, k.person)
    listed = {s["target_id"]: s for s in entered["sessions"]}
    assert set(listed) == {now_free.id, paid.id}
    assert listed[now_free.id]["is_bookable"] and not listed[paid.id]["is_bookable"]  # needs a package
    assert set(listed[paid.id]) == {
        "target_type",
        "target_id",
        "title",
        "starts_at",
        "ends_at",
        "is_booked",
        "is_bookable",
    }

    visit = entered["check_in_id"]
    refused = book(client, visit, paid.id)
    assert refused.status_code == 409 and refused.json()["code"] == "no-entitlement"
    outside = book(client, visit, later.id)
    assert outside.status_code == 422 and outside.json()["code"] == "outside-check-in-window"
    done = ok(book(client, visit, now_free.id, "kiosk-book-1"))
    assert [a["session_id"] for a in done["attended"]] == [now_free.id]  # starts inside the early window: marked
    assert next(s for s in done["sessions"] if s["target_id"] == now_free.id)["is_booked"]
    replay = book(client, visit, now_free.id, "kiosk-book-1")
    assert replay.headers.get("idempotent-replayed") == "true"
    again = book(client, visit, now_free.id)
    assert again.status_code == 409 and again.json()["code"] == "already-enrolled"
    channel = scalar(tenant, select(Enrollment.channel).where(Enrollment.session_id == UUID(now_free.id)))
    assert channel == "kiosk"

    # A package covering the paid session's type makes it bookable; it books against the package, not marked yet.
    plan = package_plan(client, owner, tenant, reservation_type_id=paid.type_id)
    ok(client.post(f"{API}/client-packages", headers=owner,
                   json={"client_id": k.person["id"], "location_id": k.loc, "package_plan_id": plan["id"]}), 201)  # fmt: skip
    booked = ok(book(client, visit, paid.id))
    assert paid.id not in [a["session_id"] for a in booked["attended"]]
    assert next(s for s in booked["sessions"] if s["target_id"] == paid.id)["is_booked"]


def test_a_visit_is_reachable_only_from_its_own_kiosk_for_ten_minutes(client, tenant, owner, k, monkeypatch):
    seat = soon(client, owner, k.loc, 30)
    visit = enter(client, k.person)["check_in_id"]
    assert book(client, str(uuid4()), seat.id).status_code == 404
    _pair(client, tenant, owner, k.loc)  # this browser is now another device
    assert book(client, visit, seat.id).status_code == 404
    visit = enter(client, k.person)["check_in_id"]
    from app.modules.access import kiosk

    later = clock.now() + timedelta(minutes=11)
    monkeypatch.setattr(kiosk, "clock", SimpleNamespace(now=lambda: later))
    assert book(client, visit, seat.id).status_code == 404


def test_a_client_who_must_see_staff_gets_no_reservation_page(client, tenant, owner, k):
    soon(client, owner, k.loc, 30)
    ok(client.put(f"{API}/clients/{k.person['id']}/access-mode", headers=owner,
                  json={"access_mode": "always_deny", "reason": "Test"}))  # fmt: skip
    entered = enter(client, k.person)
    assert entered["status"] == "see_staff" and entered["sessions"] == []
    assert book(client, entered["check_in_id"], str(uuid4())).status_code == 404


def test_auto_book_takes_the_earliest_bookable_session_once(client, tenant, owner, k):
    first = soon(client, owner, k.loc, 20)
    soon(client, owner, k.loc, 45)
    soon(client, owner, k.loc, 10, free=False)  # earlier, but needs a package: skipped
    ok(client.put(f"{API}/kiosk-settings?location_id={k.loc}", headers=owner,
                  json={"is_auto_book": True, "visible_range_minutes": 120, "reservation_timeout_seconds": 20}))  # fmt: skip
    entered = enter(client, k.person)
    assert [a["session_id"] for a in entered["attended"]] == [first.id]
    assert [s["target_id"] for s in entered["sessions"] if s["is_booked"]] == [first.id]
    row = scalar(tenant, select(CheckIn).where(CheckIn.id == UUID(entered["check_in_id"])))
    assert row.result == "granted"
    again = enter(client, k.person)  # a place is already held: nothing more is booked
    assert [s["target_id"] for s in again["sessions"] if s["is_booked"]] == [first.id]
    assert client.put(f"{API}/kiosk-settings?location_id={k.loc}", headers=owner,
                      json={"reservation_timeout_seconds": 1}).status_code == 422  # fmt: skip
