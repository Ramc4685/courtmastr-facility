"""Direct registration links (SCH-16), shared bookings with their own attendance (SCH-17, SSP-09) and merging
two reservations into one series (SCH-21)."""

from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.scheduling.models import Booking, BookingParticipant, BookingSeries, Session
from app.modules.scheduling.tests.helpers import API, at, book, ok
from app.modules.scheduling.tests.helpers import facility as build_facility
from conftest import new_client


@pytest.fixture
def f(client, owner):
    return build_facility(client, owner)


def session_booking(client, owner, f, start: float, **extra) -> dict:
    return ok(book(client, owner, f, [f.court], at(start), at(start + 1), kind="session", **extra))["booking"]


def refused(response, status: int, code: str) -> None:
    assert (response.status_code, response.json()["code"]) == (status, code), response.text


# --- direct registration links (SCH-16) ---------------------------------------------------------------------


def test_link_lives_in_the_fragment_resolves_publicly_and_dies_on_revoke(client, owner, tenant, f):
    seat = session_booking(client, owner, f, 10)["session"]["id"]
    link = ok(client.post(f"{API}/sessions/{seat}/direct-link", headers=owner), 200)
    assert link["is_active"] and link["path"] == f"/direct-link#token={link['token']}" and "?" not in link["path"]
    assert ok(client.post(f"{API}/sessions/{seat}/direct-link", headers=owner), 200)["token"] == link["token"]

    public = {"X-Tenant-Slug": tenant.slug}
    shown = ok(client.post(f"{API}/public/direct-links/resolve", headers=public, json={"token": link["token"]}), 200)
    assert shown["session_id"] == seat and shown["spots_left"] == 4 and shown["time_zone"] == f.zone
    assert set(shown) == {"session_id", "title", "starts_at", "ends_at", "location_name", "time_zone", "spots_left"}

    ok(client.delete(f"{API}/sessions/{seat}/direct-link", headers=owner), 204)
    ok(client.delete(f"{API}/sessions/{seat}/direct-link", headers=owner), 204)  # idempotent
    refused(client.post(f"{API}/public/direct-links/resolve", headers=public, json={"token": link["token"]}),
            404, "link-invalid")  # fmt: skip
    again = ok(client.post(f"{API}/sessions/{seat}/direct-link", headers=owner), 200)
    assert again["token"] != link["token"]  # revoking rotated the token: old copies stay dead


def test_inactive_or_cancelled_session_links_do_not_resolve(client, owner, tenant, f):
    booking = session_booking(client, owner, f, 12)
    seat = booking["session"]["id"]
    public = {"X-Tenant-Slug": tenant.slug}
    with tenant_session(tenant.id) as session:
        token = session.get(Session, UUID(seat)).direct_link_token
    resolve = lambda: client.post(f"{API}/public/direct-links/resolve", headers=public, json={"token": token})  # noqa: E731
    refused(resolve(), 404, "link-invalid")  # off until staff turn it on
    ok(client.post(f"{API}/sessions/{seat}/direct-link", headers=owner), 200)
    ok(resolve(), 200)
    ok(client.post(f"{API}/bookings/{booking['id']}/cancel", headers=owner, json={"version": booking["version"]}), 200)
    refused(resolve(), 404, "link-invalid")
    refused(client.post(f"{API}/sessions/{seat}/direct-link", headers=owner), 409, "invalid-state-transition")


# --- shared bookings (SCH-17, SSP-09) -----------------------------------------------------------------------


def relate(client, owner, parent_id: str, child_id: str) -> None:
    types = ok(client.get(f"{API}/relationship-types", headers=owner), 200)
    parent_of = next(t for t in types if t["code"] == "parent_of")
    ok(client.post(f"{API}/clients/{parent_id}/relationships", headers=owner,
                   json={"other_client_id": child_id, "relationship_type_id": parent_of["id"]}))  # fmt: skip


def test_shared_booking_lists_organiser_and_relatives_each_with_own_attendance(client, owner, tenant, f):
    booking = session_booking(client, owner, f, 14)
    organiser, kid, stranger = (new_client(client, owner, f.location) for _ in range(3))
    relate(client, owner, organiser["id"], kid["id"])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:  # a client's own reservation
        session.get(Booking, UUID(booking["id"])).client_id = UUID(organiser["id"])
    url = f"{API}/bookings/{booking['id']}/participants"

    refused(client.post(url, headers=owner, json={"client_id": stranger["id"]}), 422, "validation-failed")
    rows = ok(client.post(url, headers=owner, json={"client_id": kid["id"]}))
    assert [(r["client_id"], r["is_organiser"], r["attendance"]) for r in rows] == [
        (organiser["id"], True, "scheduled"), (kid["id"], False, "scheduled")]  # fmt: skip
    refused(client.post(url, headers=owner, json={"client_id": kid["id"]}), 409, "already-enrolled")

    kid_row = rows[1]
    marked = ok(client.patch(f"{url}/{kid_row['id']}", headers=owner, json={"attendance": "no_show"}), 200)
    assert marked["attendance"] == "no_show" and marked["attendance_marked_at"]
    assert {r["client_id"]: r["attendance"] for r in ok(client.get(url, headers=owner), 200)} == {
        organiser["id"]: "scheduled", kid["id"]: "no_show"}  # fmt: skip

    refused(client.delete(f"{url}/{rows[0]['id']}", headers=owner), 409, "invalid-state-transition")
    ok(client.delete(f"{url}/{kid_row['id']}", headers=owner), 204)
    assert [r["client_id"] for r in ok(client.get(url, headers=owner), 200)] == [organiser["id"]]


def test_participants_follow_a_client_merge(client, owner, tenant, f):
    booking = session_booking(client, owner, f, 16)
    keep, lose = new_client(client, owner, f.location), new_client(client, owner, f.location)
    url = f"{API}/bookings/{booking['id']}/participants"
    ok(client.post(url, headers=owner, json={"client_id": keep["id"]}))
    ok(client.post(url, headers=owner, json={"client_id": lose["id"]}))
    ok(client.post(f"{API}/clients/{keep['id']}/merge", headers=owner, json={"merged_client_ids": [lose["id"]]}), 200)
    assert [r["client_id"] for r in ok(client.get(url, headers=owner), 200)] == [keep["id"]]
    with tenant_session(tenant.id) as session:
        stmt = select(func.count()).select_from(BookingParticipant)
        assert session.scalar(stmt.where(BookingParticipant.booking_id == UUID(booking["id"]))) == 1


def test_block_bookings_take_no_participants(client, owner, f):
    block = ok(book(client, owner, f, [f.court2], at(9), at(10)))["booking"]
    someone = new_client(client, owner, f.location)
    refused(client.post(f"{API}/bookings/{block['id']}/participants", headers=owner, json={"client_id": someone["id"]}),
            409, "invalid-state-transition")  # fmt: skip


# --- merging reservations into one series (SCH-21) ----------------------------------------------------------


def weekly(client, owner, f, start: float, resource: str) -> dict:
    recurrence = {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 2}
    return ok(book(client, owner, f, [resource], at(start), at(start + 1), kind="session", recurrence=recurrence))


def test_merge_moves_the_other_series_into_this_one(client, owner, tenant, f):
    mine, other = weekly(client, owner, f, 8, f.court), weekly(client, owner, f, 8, f.court2)
    number = other["booking"]["booking_number"]
    merged = ok(client.post(f"{API}/bookings/{mine['booking']['id']}/merge", headers=owner,
                            json={"booking_number": number}), 200)  # fmt: skip
    assert merged["id"] == mine["booking_series_id"] and len(merged["rules"]) == 2
    with tenant_session(tenant.id) as session:
        ids = [UUID(mine["booking_series_id"]), UUID(other["booking_series_id"])]
        series_ids = set(session.scalars(select(Booking.booking_series_id).where(Booking.booking_series_id.in_(ids))))
        assert series_ids == {ids[0]}
        assert session.get(BookingSeries, ids[1]) is None
    refused(client.post(f"{API}/bookings/{mine['booking']['id']}/merge", headers=owner, json={"booking_number": number}),
            409, "already-linked")  # fmt: skip


def test_merge_links_a_single_reservation_and_refuses_mismatches(client, owner, f):
    single, other = session_booking(client, owner, f, 18), session_booking(client, owner, f, 20)
    merged = ok(client.post(f"{API}/bookings/{single['id']}/merge", headers=owner,
                            json={"booking_number": other["booking_number"]}), 200)  # fmt: skip
    assert merged["occurrence_count"] == 2
    block = ok(book(client, owner, f, [f.court2], at(22), at(23)))["booking"]
    refused(client.post(f"{API}/bookings/{single['id']}/merge", headers=owner,
                        json={"booking_number": block["booking_number"]}), 409, "merge-mismatch")  # fmt: skip
    missing = client.post(f"{API}/bookings/{single['id']}/merge", headers=owner, json={"booking_number": 999_999})
    refused(missing, 422, "validation-failed")
