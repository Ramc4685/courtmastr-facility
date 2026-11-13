"""Session self-service (CLS-09) and its policy, the portal waitlist with open offers (CLS-06), and the staff
session tools: series batch (CLS-02), rebook (CLS-03) and the roster message (CLS-10)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.programs.tests.test_checkout import member
from app.modules.programs.tests.test_sessions import class_of, counts, enroll, people
from app.modules.scheduling.tests.helpers import API, at, book, facility, ok
from conftest import add_staff, login

SOON = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=3)
POLICY = {
    "listing_mode": "bookable", "requires_active_membership": False, "visible_range_days": 30,
    "hides_full_sessions": False, "booking_cutoff_minutes": 0, "allows_self_cancel": True,
    "cancel_notice_minutes": 0, "waitlist_mode": "open_offer",
}  # fmt: skip


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def soon(client, owner, f, capacity: int, hour: float = 10) -> str:
    booking = book(client, owner, f, [f.court], at(hour, SOON), at(hour + 1, SOON), kind="session",
                   session={"capacity": capacity})  # fmt: skip
    return ok(booking)["booking"]["session"]["id"]


def policy(client, owner, f, **fields) -> dict:
    put = client.put(f"{API}/locations/{f.location}/session-booking-policy", headers=owner, json=POLICY | fields)
    return ok(put, 200)


def listing(client, portal, seat: str) -> dict:
    rows = ok(client.get(f"{API}/portal/session-listings", headers=portal), 200)
    return next(r for r in rows if r["session_id"] == seat)


def test_policy_default_override_and_scope(client, owner, tenant, f):
    assert policy(client, owner, f)["reservation_type_id"] is None
    path = f"{API}/reservation-types/{f.type}/session-booking-policy"
    override = ok(client.put(path, headers=owner, json={"booking_cutoff_minutes": 90}), 200)
    assert override["location_id"] == f.location and override["listing_mode"] is None
    listed = ok(client.get(f"{API}/session-booking-policies?location_id={f.location}", headers=owner), 200)
    assert len(listed) == 2
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    assert client.put(path, headers=desk, json={"booking_cutoff_minutes": 5}).status_code == 403
    # engagement.portal_settings.manage (admin, manager) or, for league admins, programs.registration_config.manage:
    # they keep booking policies without the rest of the portal settings.
    league = login(client, tenant, add_staff(tenant, "league_admin", location_ids=[f.location])[0])
    assert client.put(path, headers=league, json={"booking_cutoff_minutes": 5}).status_code == 200
    assert client.get(f"{API}/locations/{f.location}/portal-settings", headers=league).status_code == 403
    elsewhere = facility(client, owner, "America/New_York")
    admin = login(client, tenant, add_staff(tenant, "admin", location_ids=[elsewhere.location])[0])
    assert client.put(path, headers=admin, json={"booking_cutoff_minutes": 5}).status_code == 404
    assert client.delete(path, headers=admin).status_code == 404
    assert client.delete(path, headers=owner).status_code == 204


def test_listings_explain_why_a_session_cannot_be_booked(client, owner, tenant, f, mailbox):
    policy(client, owner, f)
    seat, full = soon(client, owner, f, 4), soon(client, owner, f, 1, 13)
    (taken,) = people(client, owner, f, 1)
    ok(enroll(client, owner, full, taken))
    person, portal = member(client, tenant, owner, f, mailbox)
    assert listing(client, portal, seat)["is_bookable"] is True
    row = listing(client, portal, full)
    assert (row["reason"], row["can_join_waitlist"]) == ("full", True)
    policy(client, owner, f, requires_active_membership=True)
    assert listing(client, portal, seat)["reason"] == "members-only"
    policy(client, owner, f, booking_cutoff_minutes=100_000)
    assert listing(client, portal, seat)["reason"] == "cutoff-passed"
    refused = client.post(
        f"{API}/portal/enrollments", headers=portal, json={"client_id": person["id"], "session_id": seat}
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "policy-violation")
    policy(client, owner, f, listing_mode="hidden")
    assert all(r["session_id"] != seat for r in ok(client.get(f"{API}/portal/session-listings", headers=portal), 200))


def test_portal_books_and_cancels_early_or_late(client, owner, tenant, f, mailbox):
    policy(client, owner, f, cancel_notice_minutes=60 * 24 * 7)  # a week's notice: anything sooner is late
    seat = soon(client, owner, f, 2)
    person, portal = member(client, tenant, owner, f, mailbox)
    other, _ = member(client, tenant, owner, f, mailbox)
    body = {"client_id": person["id"], "session_id": seat}
    foreign = client.post(f"{API}/portal/enrollments", headers=portal, json=body | {"client_id": other["id"]})
    assert foreign.status_code == 404
    row = ok(client.post(f"{API}/portal/enrollments", headers=portal, json=body))
    assert row["status"] == "enrolled" and counts(tenant, seat) == (1, 1)
    mine = ok(client.get(f"{API}/portal/enrollments", headers=portal), 200)["data"]
    assert [r["id"] for r in mine] == [row["id"]]
    _, intruder = member(client, tenant, owner, f, mailbox)
    assert client.post(f"{API}/portal/enrollments/{row['id']}/cancel", headers=intruder).status_code == 404
    cancelled = ok(client.post(f"{API}/portal/enrollments/{row['id']}/cancel", headers=portal), 200)
    assert (cancelled["status"], cancelled["cancel_kind"]) == ("cancelled", "late")

    policy(client, owner, f, allows_self_cancel=False)
    again = ok(client.post(f"{API}/portal/enrollments", headers=portal, json=body))
    refused = client.post(f"{API}/portal/enrollments/{again['id']}/cancel", headers=portal)
    assert (refused.status_code, refused.json()["code"]) == (409, "policy-violation")


def test_open_offer_first_claim_wins(client, owner, tenant, f, mailbox):
    policy(client, owner, f)
    seat = soon(client, owner, f, 1)
    (holder,) = people(client, owner, f, 1)
    place = ok(enroll(client, owner, seat, holder))
    a, a_portal = member(client, tenant, owner, f, mailbox)
    b, b_portal = member(client, tenant, owner, f, mailbox)
    join = f"{API}/portal/waitlist-entries"
    first = ok(client.post(join, headers=a_portal, json={"client_id": a["id"], "session_id": seat}))
    second = ok(client.post(join, headers=b_portal, json={"client_id": b["id"], "session_id": seat}))
    assert (first["position"], second["position"]) == (1, 2)
    early = client.post(f"{join}/{first['id']}/claim", headers=a_portal, json={})
    assert (early.status_code, early.json()["code"]) == (409, "invalid-state-transition")

    ok(client.post(f"{API}/enrollments/{place['id']}/cancel", headers=owner, json={}), 200)
    offered = ok(client.get(join, headers=b_portal), 200)
    assert offered[0]["status"] == "offered" and offered[0]["offer_expires_at"]
    assert client.post(f"{join}/{second['id']}/claim", headers=a_portal, json={}).status_code == 404
    won = ok(client.post(f"{join}/{second['id']}/claim", headers=b_portal, json={}), 200)
    assert won["status"] == "promoted" and counts(tenant, seat) == (1, 1)
    lost = client.post(f"{join}/{first['id']}/claim", headers=a_portal, json={})
    assert (lost.status_code, lost.json()["code"]) == (409, "capacity-full")
    assert ok(client.get(join, headers=a_portal), 200)[0]["status"] == "waiting"  # the refusal put it back
    assert client.delete(f"{join}/{first['id']}", headers=a_portal).status_code == 204
    assert ok(client.get(join, headers=a_portal), 200) == []


def test_series_batch_rebook_and_roster_message(client, owner, tenant, f, mailbox):
    body = {
        "location_id": f.location, "kind": "session", "reservation_type_id": f.type,
        "starts_at": at(10), "ends_at": at(11), "resources": [{"resource_id": f.court2}],
        "session": {"capacity": 1},
        "recurrence": {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 3},
    }  # fmt: skip
    anchor = ok(client.post(f"{API}/bookings", headers=owner, json=body))["booking"]["session"]["id"]
    a, b = people(client, owner, f, 2)
    batch = ok(client.post(f"{API}/enrollments/batch", headers=owner,
                           json={"client_id": a, "session_id": anchor, "booked_scope": "all_linked"}), 200)  # fmt: skip
    assert len(batch["enrolled"]) == 3 and batch["skipped"] == []
    partial = ok(client.post(f"{API}/enrollments/batch", headers=owner,
                             json={"client_id": b, "session_id": anchor, "booked_scope": "all_linked"}), 200)  # fmt: skip
    assert partial["enrolled"] == [] and {s["code"] for s in partial["skipped"]} == {"capacity-full"}
    cancelled = client.post(f"{API}/enrollments/{batch['enrolled'][0]['id']}/cancel", headers=owner,
                            json={"scope": "batch"})  # fmt: skip
    assert ok(cancelled, 200)["status"] == "cancelled"
    assert counts(tenant, anchor) == (0, 0)

    seat, other = class_of(client, owner, f, 2, 15), class_of(client, owner, f, 2, 17)
    row = ok(enroll(client, owner, seat, a))
    moved = ok(client.post(f"{API}/enrollments/{row['id']}/rebook", headers=owner, json={"session_id": other}), 200)
    assert moved["session_id"] == other and counts(tenant, seat) == (0, 0) and counts(tenant, other) == (1, 1)

    sent = client.post(f"{API}/sessions/{other}/roster/messages", headers=owner,
                       json={"subject": "Court change", "body_html": "We moved to court 2."})  # fmt: skip
    assert ok(sent, 202)["status"] == "succeeded"
    league = login(client, tenant, add_staff(tenant, "league_admin", location_ids=[f.location])[0])
    by_league = client.post(  # the roster message is scheduling.enrollment.create, which league admins lack
        f"{API}/sessions/{other}/roster/messages", headers=league, json={"subject": "x", "body_html": "y"}
    )
    assert by_league.status_code == 403, by_league.text
    elsewhere = facility(client, owner, "America/New_York")
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[elsewhere.location])[0])
    blocked = client.post(
        f"{API}/sessions/{other}/roster/messages", headers=desk, json={"subject": "x", "body_html": "y"}
    )
    assert blocked.status_code == 404
    # A restricted reservation type: only staff granted it may message its sessions.
    granted_email, granted_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    unlisted = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    grants = {"staff_user_ids": [str(granted_id)]}
    ok(client.put(f"{API}/reservation-types/{f.type}/grants", headers=owner, json=grants), 200)
    message = {"subject": "x", "body_html": "y"}
    refused = client.post(f"{API}/sessions/{other}/roster/messages", headers=unlisted, json=message)
    assert refused.status_code == 403, refused.text
    granted = login(client, tenant, granted_email)
    assert client.post(f"{API}/sessions/{other}/roster/messages", headers=granted, json=message).status_code == 202


def test_portal_queue_and_booking_obey_the_whole_policy(client, owner, tenant, f, mailbox):
    policy(client, owner, f, requires_active_membership=True, visible_range_days=1)
    full = soon(client, owner, f, 1)  # three days out: beyond a one-day range
    (holder,) = people(client, owner, f, 1)
    ok(enroll(client, owner, full, holder))
    person, portal = member(client, tenant, owner, f, mailbox)
    body = {"client_id": person["id"], "session_id": full}
    beyond = client.post(f"{API}/portal/waitlist-entries", headers=portal, json=body)
    assert beyond.status_code == 422
    policy(client, owner, f, requires_active_membership=True)
    members = client.post(f"{API}/portal/waitlist-entries", headers=portal, json=body)
    assert (members.status_code, members.json()["code"], members.json()["reason"]) == (
        409,
        "policy-violation",
        "members-only",
    )
