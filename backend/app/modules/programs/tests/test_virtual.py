"""Virtual sessions (CLS-08 and SSP-18, phase 11 B): staff make a session virtual through the video port, and the
join link reaches only enrolled clients, from 15 minutes before the start to the end, never in listings."""

from datetime import timedelta

from app.core import clock
from app.modules.programs.tests.test_checkout import member
from app.modules.programs.tests.test_groups import program, register
from app.modules.programs.tests.test_selfservice import POLICY, SOON
from app.modules.programs.tests.test_sessions import enroll
from app.modules.scheduling.tests.helpers import API, at, book, facility, ok
from conftest import add_staff, login


def test_meeting_and_join_window(client, owner, tenant, mailbox):
    f = facility(client, owner)
    ok(client.put(f"{API}/locations/{f.location}/session-booking-policy", headers=owner, json=POLICY), 200)
    made = ok(book(client, owner, f, [f.court], at(10, SOON), at(11, SOON), kind="session", session={"capacity": 4}))
    booking, seat = made["booking"], made["booking"]["session"]["id"]
    path = f"{API}/sessions/{seat}/meeting"
    assert ok(client.get(path, headers=owner), 200)["is_virtual"] is False
    elsewhere = facility(client, owner, "America/New_York")
    admin = login(client, tenant, add_staff(tenant, "admin", location_ids=[elsewhere.location])[0])
    assert client.put(path, headers=admin).status_code == 404  # another location's staff
    assert client.get(path, headers=admin).status_code == 404
    meeting = ok(client.put(path, headers=owner), 200)
    assert meeting["is_virtual"] and meeting["join_url"] and meeting["host_url"]
    # The host link starts the meeting: only staff who may run the session get it, not every schedule reader.
    viewer = login(client, tenant, add_staff(tenant, "view_only", location_ids=[f.location])[0])
    seen = ok(client.get(path, headers=viewer), 200)
    assert seen["join_url"] == meeting["join_url"] and seen["host_url"] is None
    coach = login(client, tenant, add_staff(tenant, "coach", location_ids=[f.location])[0])
    assert ok(client.get(path, headers=coach), 200)["host_url"] is None  # not this session's instructor
    assert ok(client.get(path, headers=owner), 200)["host_url"] == meeting["host_url"]
    assert ok(client.put(path, headers=owner), 200)["join_url"] == meeting["join_url"]  # idempotent

    person, portal = member(client, tenant, owner, f, mailbox)
    row = next(r for r in ok(client.get(f"{API}/portal/session-listings", headers=portal), 200)
               if r["session_id"] == seat)  # fmt: skip
    assert row["is_virtual"] is True and "join_url" not in row and row["reservation_type_id"] == f.type
    join = f"{API}/portal/sessions/{seat}/join-link"
    assert client.get(join, headers=portal).status_code == 404  # not enrolled
    ok(enroll(client, owner, seat, person["id"]))
    early = client.get(join, headers=portal)
    assert early.status_code == 409 and early.json()["code"] == "join-not-open"
    starts = SOON + timedelta(hours=10)
    with clock.freeze(starts - timedelta(minutes=15)):  # sign in again: a token from now would have expired
        later = login(client, tenant, person["primary_email"], audience="client")
        assert ok(client.get(join, headers=later), 200)["join_url"] == meeting["join_url"]
    with clock.freeze(starts + timedelta(hours=1)):
        later = login(client, tenant, person["primary_email"], audience="client")
        assert client.get(join, headers=later).status_code == 409  # ended

    assert client.delete(path, headers=owner).status_code == 204
    assert client.get(join, headers=portal).status_code == 404  # no longer virtual
    ok(client.put(path, headers=owner), 200)
    ok(client.post(f"{API}/bookings/{booking['id']}/cancel", headers=owner, json={"version": booking["version"]}), 200)
    assert ok(client.get(path, headers=owner), 200)["is_virtual"] is False  # cancelling drops the meeting
    assert client.get(join, headers=portal).status_code == 404


def test_program_enrolment_gets_the_join_link_of_its_sessions(client, owner, tenant, mailbox):
    """A group registration (no session_id on the enrolment) takes a seat in every session linked to its group or
    an ancestor, so it reaches their join links too; someone not registered does not."""
    f = facility(client, owner)
    made = ok(book(client, owner, f, [f.court], at(10, SOON), at(11, SOON), kind="session", session={"capacity": 4}))
    seat = made["booking"]["session"]["id"]
    meeting = ok(client.put(f"{API}/sessions/{seat}/meeting", headers=owner), 200)
    camp = program(client, owner, f, kind="camp")
    week = ok(client.post(f"{API}/program-groups", headers=owner, json={"parent_id": camp["id"], "name": "Wk 1"}))
    ok(client.post(f"{API}/program-groups/{camp['id']}/sessions", headers=owner, json={"session_ids": [seat]}), 200)
    person, _ = member(client, tenant, owner, f, mailbox)
    stranger, _ = member(client, tenant, owner, f, mailbox)
    ok(register(client, owner, week["id"], person["id"]))
    join = f"{API}/portal/sessions/{seat}/join-link"
    with clock.freeze(SOON + timedelta(hours=10, minutes=-5)):
        mine = login(client, tenant, person["primary_email"], audience="client")
        assert ok(client.get(join, headers=mine), 200)["join_url"] == meeting["join_url"]
        theirs = login(client, tenant, stranger["primary_email"], audience="client")
        assert client.get(join, headers=theirs).status_code == 404

    # a session linked to Wk 1 only: a registration in its sibling Wk 2 does not reach it (subtree, not siblings)
    later = ok(book(client, owner, f, [f.court], at(12, SOON), at(13, SOON), kind="session", session={"capacity": 4}))
    only_week = later["booking"]["session"]["id"]
    week_meeting = ok(client.put(f"{API}/sessions/{only_week}/meeting", headers=owner), 200)
    ok(
        client.post(f"{API}/program-groups/{week['id']}/sessions", headers=owner, json={"session_ids": [only_week]}),
        200,
    )
    sibling = ok(client.post(f"{API}/program-groups", headers=owner, json={"parent_id": camp["id"], "name": "Wk 2"}))
    neighbour, _ = member(client, tenant, owner, f, mailbox)
    ok(register(client, owner, sibling["id"], neighbour["id"]))
    week_join = f"{API}/portal/sessions/{only_week}/join-link"
    with clock.freeze(SOON + timedelta(hours=12, minutes=-5)):
        mine = login(client, tenant, person["primary_email"], audience="client")
        assert ok(client.get(week_join, headers=mine), 200)["join_url"] == week_meeting["join_url"]
        next_door = login(client, tenant, neighbour["primary_email"], audience="client")
        assert client.get(week_join, headers=next_door).status_code == 404
