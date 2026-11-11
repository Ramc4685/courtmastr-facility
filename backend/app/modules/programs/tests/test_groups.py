"""Program groups (REG-01, 02, 05, 07): the tree, capacity along the chain, linked sessions, fees, staff
registration with its invoice, the group waitlist and cancellation, and the coach's `own` reach."""

import pytest

from app.modules.programs.tests.test_sessions import class_of, people
from app.modules.scheduling.tests.helpers import API, at, book, facility, ok
from conftest import add_staff, login


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def program(client, headers, f, **fields) -> dict:
    body = {"location_id": f.location, "name": "Camp"} | fields
    return ok(client.post(f"{API}/program-groups", headers=headers, json=body))


def register(client, headers, group: str, person: str, **extra):
    body = {"program_group_id": group, "client_id": person} | extra
    return client.post(f"{API}/enrollments", headers=headers, json=body)


def group_of(client, headers, group: str) -> dict:
    return ok(client.get(f"{API}/program-groups/{group}", headers=headers), 200)


def fee_of(client, headers, group: str, amount: int, description: str = "Camp") -> dict:
    body = {"description": description, "amount_minor": amount}
    return ok(client.post(f"{API}/program-groups/{group}/fees", headers=headers, json=body))


def test_tree_capacity_runs_along_the_chain_and_reaches_linked_sessions(client, owner, f):
    camp = program(client, owner, f, capacity=2, kind="camp")
    week = ok(
        client.post(
            f"{API}/program-groups", headers=owner, json={"parent_id": camp["id"], "name": "Wk 1", "capacity": 5}
        )
    )
    assert week["location_id"] == f.location and week["depth"] == camp["depth"] + 1
    seat = class_of(client, owner, f, 10)
    linked = client.post(f"{API}/program-groups/{camp['id']}/sessions", headers=owner, json={"session_ids": [seat]})
    assert [s["id"] for s in ok(linked, 200)] == [seat]

    a, b, c = people(client, owner, f, 3)
    ok(register(client, owner, week["id"], a))
    ok(register(client, owner, week["id"], b))
    full = register(client, owner, week["id"], c)  # the parent's capacity binds the child
    assert (full.status_code, full.json()["code"]) == (409, "capacity-full")
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 2
    assert ok(client.get(f"{API}/sessions/{seat}", headers=owner), 200)["booked_count"] == 2
    tree = ok(client.get(f"{API}/program-groups/{camp['id']}/tree", headers=owner), 200)
    assert [n["id"] for n in tree["children"]] == [week["id"]]
    roster = ok(client.get(f"{API}/program-groups/{camp['id']}/roster", headers=owner), 200)
    assert {p["client_id"] for p in roster["participants"]} == {a, b}

    busy = client.delete(f"{API}/program-groups/{camp['id']}", headers=owner)
    assert (busy.status_code, busy.json()["code"]) == (409, "has-registrations")


def test_lifecycle_delete_and_restore(client, owner, f):
    camp = program(client, owner, f)
    path = f"{API}/program-groups/{camp['id']}"
    assert ok(client.post(f"{path}/complete", headers=owner), 200)["status"] == "completed"
    assert ok(client.post(f"{path}/reopen", headers=owner), 200)["status"] == "active"
    assert ok(client.post(f"{path}/archive", headers=owner), 200)["status"] == "archived"
    (person,) = people(client, owner, f, 1)
    closed = register(client, owner, camp["id"], person)
    assert (closed.status_code, closed.json()["code"]) == (409, "program-not-active")
    ok(client.post(f"{path}/reopen", headers=owner), 200)
    assert client.delete(path, headers=owner).status_code == 204
    assert client.get(path, headers=owner).status_code == 404
    assert ok(client.post(f"{path}/restore", headers=owner), 200)["id"] == camp["id"]


def test_fees_are_billed_on_one_invoice_to_a_related_payer(client, owner, f):
    camp = program(client, owner, f)
    fee, extra = fee_of(client, owner, camp["id"], 12000), fee_of(client, owner, camp["id"], 3000, "Lunch")
    assert len(ok(client.get(f"{API}/program-groups/{camp['id']}/fees", headers=owner), 200)) == 2
    kid, stranger = people(client, owner, f, 2)
    unrelated = register(client, owner, camp["id"], kid, program_fee_ids=[fee["id"]], payer_client_id=stranger)
    assert (unrelated.status_code, unrelated.json()["code"]) == (422, "payer-not-related")

    row = ok(register(client, owner, camp["id"], kid, program_fee_ids=[fee["id"], extra["id"]]))
    assert row["program_group_id"] == camp["id"] and row["status"] == "enrolled"
    invoices = ok(client.get(f"{API}/invoices?bill_to_client_id={kid}", headers=owner), 200)["data"]
    assert [i["total_minor"] for i in invoices] == [15000]

    other = program(client, owner, f, name="Other")  # a fee of another program is not chosen for this one
    foreign = register(client, owner, other["id"], stranger, program_fee_ids=[fee["id"]])
    assert foreign.status_code in (404, 422), foreign.text


def test_group_waitlist_promotes_when_a_place_frees(client, owner, f):
    camp = program(client, owner, f, capacity=1, waitlist_mode="manual")
    a, b = people(client, owner, f, 2)
    first = ok(register(client, owner, camp["id"], a))
    body = {"program_group_id": camp["id"], "client_id": b}
    entry = ok(client.post(f"{API}/waitlist-entries", headers=owner, json=body))
    listed = ok(client.get(f"{API}/waitlist-entries?program_group_id={camp['id']}", headers=owner), 200)
    assert [e["id"] for e in listed] == [entry["id"]]
    full = client.post(f"{API}/waitlist-entries/{entry['id']}/promote", headers=owner)
    assert (full.status_code, full.json()["code"]) == (409, "capacity-full")

    cancelled = ok(client.post(f"{API}/enrollments/{first['id']}/cancel", headers=owner, json={}), 200)
    assert cancelled["status"] == "cancelled" and group_of(client, owner, camp["id"])["enrolled_count"] == 0
    promoted = ok(client.post(f"{API}/waitlist-entries/{entry['id']}/promote", headers=owner), 200)
    assert promoted["status"] == "promoted" and group_of(client, owner, camp["id"])["enrolled_count"] == 1


def test_scope_other_location_staff_get_404(client, owner, tenant, f):
    camp = program(client, owner, f)
    elsewhere = facility(client, owner, "America/New_York")
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[elsewhere.location])[0])
    assert client.get(f"{API}/program-groups/{camp['id']}", headers=desk).status_code == 404
    (person,) = people(client, owner, elsewhere, 1)
    assert register(client, desk, camp["id"], person).status_code == 404
    listed = ok(client.get(f"{API}/program-groups", headers=desk), 200)["data"]
    assert camp["id"] not in {g["id"] for g in listed}


def test_coach_reaches_only_programs_on_their_calendar(client, owner, tenant, f):
    email, staff_id = add_staff(tenant, "coach", location_ids=[f.location])
    trainer = {"location_id": f.location, "resource_group_id": f.group, "name": "Coach Lee", "kind": "trainer",
               "staff_user_id": str(staff_id)}  # fmt: skip
    trainer = ok(client.post(f"{API}/resources", headers=owner, json=trainer))["id"]
    coach = login(client, tenant, email)
    mine, theirs = program(client, owner, f, name="Mine"), program(client, owner, f, name="Theirs")
    seat = ok(book(client, owner, f, [trainer], at(14), at(15), kind="session", session={"capacity": 4}))
    body = {"session_ids": [seat["booking"]["session"]["id"]]}
    ok(client.post(f"{API}/program-groups/{mine['id']}/sessions", headers=owner, json=body), 200)
    assert client.get(f"{API}/program-groups/{mine['id']}/roster", headers=coach).status_code == 200
    assert client.get(f"{API}/program-groups/{theirs['id']}/roster", headers=coach).status_code == 404


def test_admin_edits_fees_sessions_and_a_reversed_cancellation(client, owner, tenant, f):
    camp = program(client, owner, f, capacity=1, waitlist_mode="auto_promote")
    path = f"{API}/program-groups/{camp['id']}"
    a, b = people(client, owner, f, 2)
    fee = fee_of(client, owner, camp["id"], 5000)
    edited = ok(client.patch(f"{API}/program-fees/{fee['id']}", headers=owner, json={"amount_minor": 6000}), 200)
    assert edited["amount_minor"] == 6000
    spare = fee_of(client, owner, camp["id"], 100, "Spare")
    assert client.delete(f"{API}/program-fees/{spare['id']}", headers=owner).status_code == 204
    catalogue = {"location_id": f.location, "description": "Late pickup", "amount_minor": 700}
    ok(client.post(f"{API}/program-fees", headers=owner, json=catalogue))
    listed = ok(client.get(f"{API}/program-fees?location_id={f.location}", headers=owner), 200)["data"]
    assert "Late pickup" in {x["description"] for x in listed}

    seat = class_of(client, owner, f, 4, 9)
    ok(client.post(f"{path}/sessions", headers=owner, json={"session_ids": [seat]}), 200)
    first = ok(register(client, owner, camp["id"], a, program_fee_ids=[fee["id"]]))
    entry = ok(
        client.post(
            f"{API}/waitlist-entries",
            headers=owner,
            json={"program_group_id": camp["id"], "client_id": b, "program_fee_id": fee["id"]},
        )
    )
    low = client.patch(path, headers=owner, json={"capacity": 0})
    assert (low.status_code, low.json()["code"]) == (409, "capacity-below-enrolled")
    assert (
        ok(client.patch(path, headers=owner, json={"description": "Week of fun"}), 200)["description"] == "Week of fun"
    )

    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    reverse = {"billing_disposition": "reversed", "reason": "Family moved"}
    denied = client.post(f"{API}/enrollments/{first['id']}/cancel", headers=desk, json=reverse)
    assert denied.status_code == 403
    ok(client.post(f"{API}/enrollments/{first['id']}/cancel", headers=owner, json=reverse), 200)
    invoices = ok(client.get(f"{API}/invoices?bill_to_client_id={a}", headers=owner), 200)["data"]
    assert all(i["balance_minor"] == 0 for i in invoices)
    promoted = ok(client.get(f"{API}/waitlist-entries?program_group_id={camp['id']}", headers=owner), 200)
    assert entry["id"] not in {e["id"] for e in promoted}  # the freed place went to the auto-promote queue
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 1

    assert client.delete(f"{path}/sessions/{seat}", headers=owner).status_code == 204
    assert ok(client.get(f"{path}/sessions", headers=owner), 200) == []
    assert ok(client.get(f"{API}/sessions/{seat}", headers=owner), 200)["booked_count"] == 0


def test_auto_archive_on_the_location_date(client, owner, tenant, f):
    from datetime import date

    from app.core.auth import system_principal
    from app.core.db.session import tenant_session
    from app.modules.programs import groups

    camp = program(client, owner, f, auto_archive_on=str(date(2020, 1, 1)))
    later = program(client, owner, f, name="Later", auto_archive_on=str(date(2099, 1, 1)))
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert groups.auto_archive_due(session) == 1
    assert group_of(client, owner, camp["id"])["status"] == "archived"
    assert group_of(client, owner, later["id"])["status"] == "active"
