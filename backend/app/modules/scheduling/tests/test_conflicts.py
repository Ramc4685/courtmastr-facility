"""The hold engine (ADR 0004): table-driven conflict cases, a randomized check against a pure oracle,
buffers, linked resources, tree edits, closures, checkout holds and real concurrency on PostgreSQL."""

import random
import threading
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.errors import Conflict
from app.main import app
from app.modules.scheduling import service
from app.modules.scheduling.models import Booking, ResourceHold
from app.modules.scheduling.tests.helpers import API, DAY, at, book, facility, ok
from conftest import add_staff, login


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


# (first booking's resources, second booking's resources, second start hour, second end hour, conflict on)
# The first booking is always 10:00 to 11:00.
CASES = {
    "same resource overlapping": (["court"], ["court"], 10.5, 11.5, "court"),
    "same resource contained": (["court"], ["court"], 10.25, 10.75, "court"),
    "back to back is adjacent, not overlapping": (["court"], ["court"], 11, 12, None),
    "ends exactly at the start": (["court"], ["court"], 9, 10, None),
    "sibling halves do not collide": (["half_a"], ["half_b"], 10, 11, None),
    "parent then child": (["court"], ["half_a"], 10, 11, "half_a"),
    "child then parent": (["half_a"], ["court"], 10, 11, "half_a"),
    "grandparent then grandchild": (["court"], ["quarter"], 10.5, 11.5, "quarter"),
    "grandchild then grandparent": (["quarter"], ["court"], 10, 11, "quarter"),
    "grandchild does not block its uncle": (["quarter"], ["half_b"], 10, 11, None),
    "child blocks its own child": (["half_a"], ["quarter"], 10, 11, "quarter"),
    "another court is free": (["court"], ["court2"], 10, 11, None),
    "linked trainer is held": (["coach", "court2"], ["coach"], 10, 11, "coach"),
    "linked venue is held": (["coach", "court2"], ["court2"], 10.5, 12, "court2"),
    "linked venue blocks through the tree": (["coach", "court"], ["half_b"], 10, 11, "half_b"),
    "trainer on two courts at once": (["coach", "court"], ["court2", "coach"], 10, 11, "coach"),
    "two trainersless courts": (["court", "court2"], ["half_a", "coach"], 11, 12, None),
}


@pytest.mark.parametrize("name", CASES)
def test_conflict_table(client, owner, f, tenant, name):
    first, second, start, end, clash = CASES[name]
    winner = ok(book(client, owner, f, [getattr(f, r) for r in first], at(10), at(11)))["booking"]
    response = book(client, owner, f, [getattr(f, r) for r in second], at(start), at(end))
    if clash is None:
        assert response.status_code == 201, response.text
        return
    problem = ok(response, 409)
    assert problem["code"] == "booking-conflict"
    # The error names the booking in the way: id, number, the resource and the range it holds.
    conflict = next(c for c in problem["conflicts"] if c["resource_id"] == getattr(f, clash))
    assert conflict["booking_id"] == winner["id"] and conflict["booking_number"] == winner["booking_number"]
    assert conflict["starts_at"] == at(10) and conflict["resource_name"]
    assert f"booking #{winner['booking_number']}" in problem["detail"]
    with tenant_session(tenant.id) as session:  # nothing of the loser remains
        assert session.scalar(select(func.count()).select_from(Booking)) == 1


def test_hold_rows_are_self_descendants_and_linked_never_ancestors(client, owner, f, tenant):
    booking = ok(book(client, owner, f, [f.half_a, f.coach], at(10), at(11)))["booking"]
    with tenant_session(tenant.id) as session:
        holds = {
            str(h.resource_id): (h.origin, str(h.source_resource_id)) for h in session.scalars(select(ResourceHold))
        }
    assert holds == {
        f.half_a: ("booked", f.half_a),
        f.quarter: ("descendant", f.half_a),
        f.coach: ("linked", f.coach),
    }  # fmt: skip  (no row on Court 1, the parent)
    assert [r["role"] for r in booking["resources"]] == ["primary", "additional"]


def test_a_resource_reached_twice_gets_one_hold_with_the_stronger_origin(client, owner, f, tenant):
    ok(book(client, owner, f, [f.court, f.half_a], at(10), at(11)))
    with tenant_session(tenant.id) as session:
        holds = {str(h.resource_id): h.origin for h in session.scalars(select(ResourceHold))}
    assert holds == {f.court: "booked", f.half_a: "linked", f.half_b: "descendant", f.quarter: "descendant"}


BUFFERS = [
    # (first after, second before, gap in minutes between the two, allowed)
    (15, 0, 0, False), (15, 0, 10, False), (15, 0, 15, True), (0, 15, 10, False), (0, 15, 15, True),
    (10, 10, 15, False), (10, 10, 20, True), (0, 0, 0, True),
]  # fmt: skip


@pytest.mark.parametrize(("after", "before", "gap", "allowed"), BUFFERS)
def test_buffers_are_inside_the_hold_and_add_up(client, owner, f, after, before, gap, allowed):
    ok(book(client, owner, f, [f.court], at(10), at(11), buffer_after_min=after))
    response = book(client, owner, f, [f.court], at(11 + gap / 60), at(12.5), buffer_before_min=before)
    assert response.status_code == (201 if allowed else 409), response.text
    if allowed:  # the customer-facing range stays unpadded
        assert response.json()["booking"]["starts_at"] == at(11 + gap / 60)


def test_buffer_defaults_copy_from_type_then_settings_and_are_never_recomputed(client, owner, f):
    ok(
        client.patch(
            f"{API}/scheduling-settings?location_id={f.location}", headers=owner, json={"default_buffer_after_min": 10}
        ),
        200,
    )
    first = ok(book(client, owner, f, [f.court], at(8), at(9), kind="session"))["booking"]
    assert (first["buffer_before_min"], first["buffer_after_min"]) == (0, 10)
    ok(
        client.patch(
            f"{API}/reservation-types/{f.type}",
            headers=owner,
            json={"uses_default_buffer": False, "buffer_before_min": 5, "buffer_after_min": 20},
        ),
        200,
    )
    second = ok(book(client, owner, f, [f.court], at(12), at(13), kind="session"))["booking"]
    assert (second["buffer_before_min"], second["buffer_after_min"]) == (5, 20)
    assert ok(client.get(f"{API}/bookings/{first['id']}", headers=owner), 200)["buffer_after_min"] == 10
    # Editing a buffer on an existing booking rewrites its holds and can conflict (SCH-14).
    ok(book(client, owner, f, [f.court], at(9.25), at(10)))
    patch = {"buffer_after_min": 30, "version": first["version"]}
    assert client.patch(f"{API}/bookings/{first['id']}", headers=owner, json=patch).json()["code"] == "booking-conflict"
    assert (
        ok(client.patch(f"{API}/bookings/{first['id']}", headers=owner, json=patch | {"buffer_after_min": 15}), 200)[
            "version"
        ]
        == 2
    )


def test_standing_links_are_held_by_default_and_can_be_left_out(client, owner, f):
    ok(client.put(f"{API}/resources/{f.coach}/links", headers=owner, json={"to_resource_ids": [f.court2]}), 200)
    linked = ok(book(client, owner, f, [f.coach], at(10), at(11)))["booking"]
    assert [r["resource_id"] for r in linked["resources"]] == [f.coach, f.court2]
    assert book(client, owner, f, [f.court2], at(10), at(11)).status_code == 409
    alone = ok(book(client, owner, f, [f.coach], at(12), at(13), include_linked_resources=False))["booking"]
    assert [r["resource_id"] for r in alone["resources"]] == [f.coach]


def test_linked_booking_moves_and_cancels_as_a_unit(client, owner, f, tenant):
    booking = ok(book(client, owner, f, [f.coach, f.court], at(10), at(11)))["booking"]
    ok(book(client, owner, f, [f.court2], at(14), at(15)))
    url = f"{API}/bookings/{booking['id']}"
    move = {"starts_at": at(14), "ends_at": at(15), "version": 1}
    # One linked venue clashes: the whole move fails and nothing changed.
    clash = client.post(
        f"{url}/reschedule",
        headers=owner,
        json=move | {"resources": [{"resource_id": f.coach}, {"resource_id": f.court2}]},
    )
    assert clash.json()["code"] == "booking-conflict" and clash.json()["conflicts"][0]["resource_id"] == f.court2
    assert ok(client.get(url, headers=owner), 200)["starts_at"] == at(10)
    moved = ok(client.post(f"{url}/reschedule", headers=owner, json=move), 200)
    assert moved["starts_at"] == at(14) and moved["version"] == 2 and moved["occurrence_on"] == "2031-05-05"
    with tenant_session(tenant.id) as session:
        ranges = {
            h.during.lower
            for h in session.scalars(select(ResourceHold).where(ResourceHold.booking_id == UUID(booking["id"])))
        }
        assert (
            ranges == {DAY + timedelta(hours=14)}
            and session.scalar(select(func.count()).select_from(ResourceHold)) == 6
        )
    assert book(client, owner, f, [f.half_a], at(10), at(11)).status_code == 201  # the old time is free again
    stale = client.post(f"{url}/reschedule", headers=owner, json=move | {"starts_at": at(16), "ends_at": at(17)})
    assert stale.json()["code"] == "version-conflict"
    # A booking can move onto its own old range: its holds are replaced, not compared with themselves.
    ok(
        client.post(
            f"{url}/reschedule", headers=owner, json={"starts_at": at(14.5), "ends_at": at(15.5), "version": 2}
        ),
        200,
    )
    cancelled = ok(
        client.post(f"{url}/cancel", headers=owner, json={"version": 3, "reason": "other", "note": "Rain"}), 200
    )
    assert (
        cancelled["status"] == "cancelled"
        and cancelled["cancel_reason"] == "other"
        and len(cancelled["resources"]) == 2
    )
    with tenant_session(tenant.id) as session:  # every resource released together; the booking row stays
        assert session.scalar(select(func.count()).where(ResourceHold.booking_id == UUID(booking["id"]))) == 0
    assert book(client, owner, f, [f.coach, f.court], at(14.5), at(15.5)).status_code == 201
    assert client.post(f"{url}/reschedule", headers=owner, json=move | {"version": 4}).status_code == 409


def test_random_bookings_agree_with_a_pure_oracle(client, owner, f):
    """Property: the engine accepts a booking exactly when no accepted booking holds an ancestor-or-self
    related resource over an overlapping padded range. 80 random bookings, fixed seed."""
    parent = {f.half_a: f.court, f.half_b: f.court, f.quarter: f.half_a}
    lineage = lambda r: {r} | (lineage(parent[r]) if r in parent else set())  # noqa: E731
    related = lambda a, b: a in lineage(b) or b in lineage(a)  # noqa: E731
    rng, accepted = random.Random(20261110), []
    pool = [f.court, f.half_a, f.half_b, f.quarter, f.court2, f.coach]
    for _ in range(80):
        chosen = rng.sample(pool, rng.choice([1, 1, 2]))
        start = rng.randrange(0, 36) * 20  # minutes from 08:00, 20-minute grid
        length, before, after = rng.choice([20, 40, 60, 100]), rng.choice([0, 0, 10]), rng.choice([0, 0, 20])
        padded = (start - before, start + length + after)
        expected = not any(
            related(mine, theirs) and padded[0] < other[1] and other[0] < padded[1]
            for other, held in accepted for mine in chosen for theirs in held
        )  # fmt: skip
        response = book(
            client, owner, f, chosen, at(8 + start / 60), at(8 + (start + length) / 60),
            buffer_before_min=before, buffer_after_min=after, include_linked_resources=False,
        )  # fmt: skip
        assert (response.status_code == 201) == expected, (chosen, padded, response.text)
        if expected:
            accepted.append((padded, chosen))
    assert 10 < len(accepted) < 70  # the seed exercises both outcomes


# --- tree edits --------------------------------------------------------------------------------------------


def test_adding_and_moving_a_sub_resource_back_fills_holds_or_fails_whole(client, owner, f, tenant):
    parent_booking = ok(book(client, owner, f, [f.court2], at(10), at(11)))["booking"]
    new = {"location_id": f.location, "resource_group_id": f.group, "name": "Court 2A", "parent_id": f.court2}
    child = ok(client.post(f"{API}/resources", headers=owner, json=new))
    assert child["counts_toward_plan"] is False  # a split court is one metered resource
    clash = ok(book(client, owner, f, [child["id"]], at(10.5), at(11.5)), 409)
    assert clash["conflicts"][0]["booking_id"] == parent_booking["id"]
    # Re-parenting Court 1B (booked at 10:00 on its own) under Court 2 (booked at 10:00) cannot be honoured.
    ok(book(client, owner, f, [f.half_b], at(10), at(11)))
    moved = client.patch(f"{API}/resources/{f.half_b}", headers=owner, json={"parent_id": f.court2})
    assert moved.status_code == 409 and moved.json()["code"] == "booking-conflict"
    assert ok(client.get(f"{API}/resources/{f.half_b}", headers=owner), 200)["parent_id"] == f.court
    # Court 1A-1 is free then: it moves, loses Court 1's future holds and gains Court 2's.
    ok(book(client, owner, f, [f.court], at(13), at(14)))
    ok(client.patch(f"{API}/resources/{f.quarter}", headers=owner, json={"parent_id": child["id"]}), 200)
    assert book(client, owner, f, [f.quarter], at(13), at(14)).status_code == 201
    assert book(client, owner, f, [f.quarter], at(10), at(11)).status_code == 409


def test_tree_rules_depth_cycles_and_archive(client, owner, f):
    new = {"location_id": f.location, "resource_group_id": f.group, "name": "Too deep", "parent_id": f.quarter}
    assert client.post(f"{API}/resources", headers=owner, json=new).json()["errors"][0]["code"] == "tree-too-deep"
    cycle = client.patch(f"{API}/resources/{f.court}", headers=owner, json={"parent_id": f.quarter})
    assert cycle.json()["errors"][0]["code"] == "resource-cycle"
    deep = client.patch(f"{API}/resources/{f.court}", headers=owner, json={"parent_id": f.court2})
    assert deep.json()["errors"][0]["code"] == "tree-too-deep"  # Court 1 is three levels tall already
    trainer_child = {**new, "name": "Assistant", "kind": "trainer", "parent_id": f.court2}
    assert client.post(f"{API}/resources", headers=owner, json=trainer_child).status_code == 422
    assert client.post(f"{API}/resources/{f.court}/archive", headers=owner).json()["code"] == "resource-has-children"
    ok(book(client, owner, f, [f.court2], at(10), at(11)))
    busy = client.post(f"{API}/resources/{f.court2}/archive", headers=owner)
    assert busy.status_code == 409 and busy.json()["code"] == "resource-has-future-bookings"
    assert ok(client.post(f"{API}/resources/{f.half_b}/archive", headers=owner), 200)["status"] == "archived"
    assert book(client, owner, f, [f.half_b], at(10), at(11)).status_code == 422  # archived: not bookable
    ok(book(client, owner, f, [f.court], at(10), at(11)))  # and no longer part of its parent's hold set
    restored = client.post(f"{API}/resources/{f.half_b}/restore", headers=owner)
    assert restored.status_code == 200 and book(client, owner, f, [f.half_b], at(10.5), at(11)).status_code == 409


# --- closures ----------------------------------------------------------------------------------------------


def test_blackout_blocks_bookings_lists_what_it_covers_and_can_be_overridden(client, owner, f, tenant):
    kept = ok(book(client, owner, f, [f.court], at(10), at(11), kind="session"))["booking"]
    closure = {"location_id": f.location, "name": "Floor resurfacing", "starts_at": at(0), "ends_at": at(24)}
    saved = ok(client.post(f"{API}/blackouts", headers=owner, json=closure))
    assert [b["id"] for b in saved["overlapping_bookings"]] == [kept["id"]]  # listed, not cancelled
    blocked = book(client, owner, f, [f.court2], at(12), at(13), kind="session")
    assert blocked.status_code == 409 and blocked.json()["code"] == "resource-blacked-out"
    assert blocked.json()["blackout"]["name"] == "Floor resurfacing"
    assert book(client, owner, f, [f.court2], at(12), at(13)).status_code == 201  # a staff time block is allowed
    assert book(client, owner, f, [f.court2], at(14), at(15), kind="session", override_policy=True).status_code == 201
    desk, _ = add_staff(tenant, "front_desk", all_locations=True)
    denied = book(
        client, login(client, tenant, desk), f, [f.court2], at(16), at(17), kind="session", override_policy=True
    )
    assert denied.status_code == 403 and denied.json()["required"] == "scheduling.booking.override_policy"
    move = {"starts_at": at(18), "ends_at": at(19), "version": 1}
    assert (
        client.post(f"{API}/bookings/{kept['id']}/reschedule", headers=owner, json=move).json()["code"]
        == "resource-blacked-out"
    )
    online = ok(client.patch(f"{API}/blackouts/{saved['id']}", headers=owner, json={"scope": "online_only"}), 200)
    assert (
        online["scope"] == "online_only"
        and book(client, owner, f, [f.court2], at(16), at(17), kind="session").status_code == 201
    )
    listed = ok(client.get(f"{API}/blackouts?location_id={f.location}&from={at(1)}&to={at(2)}", headers=owner), 200)
    assert [b["id"] for b in listed] == [saved["id"]]
    assert client.delete(f"{API}/blackouts/{saved['id']}", headers=owner).status_code == 204
    assert ok(client.get(f"{API}/blackouts?location_id={f.location}", headers=owner), 200) == []
    bad = client.post(f"{API}/blackouts", headers=owner, json=closure | {"ends_at": at(0)})
    assert bad.status_code == 422


# --- checkout holds (internal interface used by rentals) ---------------------------------------------------


def test_checkout_hold_blocks_until_it_expires_then_is_reaped_inline(client, owner, f, tenant):
    system = system_principal("tests")
    args = {
        "location_id": UUID(f.location),
        "kind": "rental",
        "resource_ids": [UUID(f.court)],
        "starts_at": DAY + timedelta(hours=10),
        "ends_at": DAY + timedelta(hours=11),
    }
    with tenant_session(tenant.id, actor=system) as session:
        held = service.create_booking(
            session, **args, hold_minutes=10, created_via="portal", source=("rentals", "rental_booking", UUID(f.court))
        )
        assert held.status == "tentative" and held.expires_at is not None
    assert book(client, owner, f, [f.half_a], at(10), at(11)).status_code == 409  # a live hold is a real hold
    with clock.freeze(clock.now() + timedelta(minutes=11)):
        with tenant_session(tenant.id, actor=system) as session, pytest.raises(Conflict) as late:
            service.confirm_booking(session, held.id)
        assert late.value.code == "hold-expired"
        assert book(client, owner, f, [f.half_a], at(10), at(11)).status_code == 201  # reaped inline, no job needed
    after = ok(client.get(f"{API}/bookings/{held.id}", headers=owner), 200)
    assert (after["status"], after["cancel_reason"], after["source_context"]) == (
        "cancelled",
        "hold_expired",
        "rentals",
    )
    with tenant_session(tenant.id, actor=system) as session:
        second = service.create_booking(session, **args | {"resource_ids": [UUID(f.court2)]}, hold_minutes=10)
        assert service.confirm_booking(session, second.id).status == "confirmed"
        assert service.confirm_booking(session, second.id).expires_at is None  # idempotent
        third = service.create_booking(session, **args | {"resource_ids": [UUID(f.coach)]}, hold_minutes=5)
    with clock.freeze(clock.now() + timedelta(minutes=6)), tenant_session(tenant.id, actor=system) as session:
        assert service.expire_holds(session) == 1 and service.expire_holds(session) == 0
        assert session.get(Booking, third.id).cancel_reason == "hold_expired"


# --- concurrency on real PostgreSQL ------------------------------------------------------------------------


def test_two_transactions_race_for_a_range_and_the_constraint_decides(f, tenant):
    """The second writer passes the pre-check (the first has not committed), blocks on the exclusion
    constraint, and fails with the mapped conflict naming the winner once the first commits."""
    system, outcome = system_principal("tests"), {}
    args = {
        "location_id": UUID(f.location),
        "kind": "rental",
        "starts_at": DAY + timedelta(hours=10),
        "ends_at": DAY + timedelta(hours=11),
    }
    inserted, release = threading.Event(), threading.Event()

    def first() -> None:
        with tenant_session(tenant.id, actor=system) as session:
            outcome["winner"] = service.create_booking(session, **args, resource_ids=[UUID(f.court)]).id
            inserted.set()
            release.wait(5)

    def second() -> None:
        inserted.wait(5)
        try:
            with tenant_session(tenant.id, actor=system) as session:
                service.create_booking(session, **args, resource_ids=[UUID(f.half_a)])  # a child of the court
            outcome["second"] = "committed"
        except Conflict as exc:
            outcome["second"] = exc

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    inserted.wait(5)
    threads[1].join(0.5)
    assert threads[1].is_alive(), "the second writer should be waiting on the first one's uncommitted hold"
    release.set()
    for thread in threads:
        thread.join(10)
    error = outcome["second"]
    assert isinstance(error, Conflict) and error.code == "booking-conflict"
    assert error.extra["conflicts"][0]["booking_id"] == str(outcome["winner"])
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 1


def test_many_clients_race_for_one_slot_through_the_api(owner, f, tenant):
    results, barrier = [], threading.Barrier(8)

    def attempt(resource: str) -> None:
        barrier.wait(5)
        with TestClient(app) as racer:
            results.append(book(racer, owner, f, [resource], at(10), at(11)))

    threads = [threading.Thread(target=attempt, args=(r,)) for r in [f.court, f.half_a, f.half_b, f.quarter] * 2]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    codes = sorted(r.status_code for r in results)
    assert set(codes) == {201, 409} and all(
        r.json()["code"] == "booking-conflict" for r in results if r.status_code == 409
    )
    # Whatever the interleaving, what was accepted is consistent: the whole court, or halves that do not overlap.
    with tenant_session(tenant.id) as session:
        booked = [
            str(h.resource_id) for h in session.scalars(select(ResourceHold).where(ResourceHold.origin == "booked"))
        ]
    assert booked == [f.court] or (
        f.court not in booked and len(set(booked)) == len(booked) and not {f.half_a, f.quarter} <= set(booked)
    )
    assert codes.count(201) == len(booked)
