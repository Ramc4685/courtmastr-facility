"""Virtual sessions (CLS-08 and SSP-18, phase 11 B): staff make a session virtual through the video port, and the
join link reaches only enrolled clients, from 15 minutes before the start to the end, never in listings."""

from datetime import timedelta

from app.core import clock
from app.modules.programs.tests.test_checkout import member
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
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    assert client.put(path, headers=desk).status_code == 403
    meeting = ok(client.put(path, headers=owner), 200)
    assert meeting["is_virtual"] and meeting["join_url"] and meeting["host_url"]
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
