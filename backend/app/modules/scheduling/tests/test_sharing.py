"""Direct registration links (SCH-16), shared bookings with their own attendance (SCH-17, SSP-09) and merging
two reservations into one series (SCH-21)."""

from uuid import UUID

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.engine import Engine

from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.auth.tokens import digest
from app.core.db.session import tenant_session
from app.modules.programs.tests.test_checkout import member
from app.modules.programs.tests.test_selfservice import SOON, policy
from app.modules.scheduling import service as scheduling_service
from app.modules.scheduling import subject
from app.modules.scheduling.models import Booking, BookingParticipant, BookingSeries, BookingSeriesRun, Session
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
    with tenant_session(tenant.id) as session:  # only a digest is stored: a database read yields no link
        assert session.get(Session, UUID(seat)).direct_link_token == digest(link["token"])

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
        stored = session.get(Session, UUID(seat)).direct_link_token
    resolve = lambda t: client.post(f"{API}/public/direct-links/resolve", headers=public, json={"token": t})  # noqa: E731
    refused(resolve(stored), 404, "link-invalid")  # off until staff turn it on
    first = ok(client.post(f"{API}/sessions/{seat}/direct-link", headers=owner), 200)["token"]
    status = ok(client.post(f"{API}/sessions/{seat}/direct-link", headers=owner), 200)
    assert (status["is_active"], status["token"], status["path"]) == (True, None, None)  # links already sent live on
    ok(resolve(first), 200)
    token = ok(client.post(f"{API}/sessions/{seat}/direct-link/regenerate", headers=owner), 200)["token"]
    assert token != first  # an explicit new link replaces the old one
    refused(resolve(first), 404, "link-invalid")
    ok(resolve(token), 200)
    ok(client.post(f"{API}/bookings/{booking['id']}/cancel", headers=owner, json={"version": booking["version"]}), 200)
    refused(resolve(token), 404, "link-invalid")
    refused(client.post(f"{API}/sessions/{seat}/direct-link", headers=owner), 409, "invalid-state-transition")
    refused(client.post(f"{API}/sessions/{seat}/direct-link/regenerate", headers=owner), 409,
            "invalid-state-transition")  # fmt: skip


def test_a_link_books_a_private_session_only_while_it_is_live(client, owner, tenant, f, mailbox):
    policy(client, owner, f)  # the location takes bookings online; this session is not self-bookable
    private = {"capacity": 2, "is_self_bookable": False}
    seat = ok(book(client, owner, f, [f.court], at(13, SOON), at(14, SOON), kind="session", session=private))
    seat = seat["booking"]["session"]["id"]
    person, portal = member(client, tenant, owner, f, mailbox)
    body = {"client_id": person["id"], "session_id": seat}
    enrol = lambda extra: client.post(f"{API}/portal/enrollments", headers=portal, json=body | extra)  # noqa: E731
    refused(enrol({}), 409, "policy-violation")  # not self-bookable: no link, no booking
    refused(enrol({"direct_link_token": "made-up"}), 409, "policy-violation")
    link = ok(client.post(f"{API}/sessions/{seat}/direct-link", headers=owner), 200)
    booked = ok(enrol({"direct_link_token": link["token"]}))
    assert booked["status"] == "enrolled"

    other, other_portal = member(client, tenant, owner, f, mailbox)
    ok(client.delete(f"{API}/sessions/{seat}/direct-link", headers=owner), 204)
    late = client.post(f"{API}/portal/enrollments", headers=other_portal,
                       json={"client_id": other["id"], "session_id": seat, "direct_link_token": link["token"]})  # fmt: skip
    refused(late, 409, "policy-violation")  # revoked: the old link books nothing


def test_a_link_still_applies_cutoff_membership_capacity_and_package_rules(client, owner, tenant, f, mailbox):
    policy(client, owner, f, requires_active_membership=True)
    free = {"capacity": 1, "is_self_bookable": False, "allows_free_booking": True}
    seat = ok(book(client, owner, f, [f.court], at(13, SOON), at(14, SOON), kind="session", session=free))
    seat = seat["booking"]["session"]["id"]
    paid = {"capacity": 5, "is_self_bookable": False, "allows_free_booking": False}
    priced = ok(book(client, owner, f, [f.court], at(15, SOON), at(16, SOON), kind="session", session=paid))
    priced = priced["booking"]["session"]["id"]
    links = {sid: ok(client.post(f"{API}/sessions/{sid}/direct-link", headers=owner), 200)["token"]
             for sid in (seat, priced)}  # fmt: skip
    person, portal = member(client, tenant, owner, f, mailbox)

    def enrol(sid, who=person, headers=portal):
        body = {"client_id": who["id"], "session_id": sid, "direct_link_token": links[sid]}
        return client.post(f"{API}/portal/enrollments", headers=headers, json=body)

    assert enrol(seat).json().get("reason") == "members-only"  # membership still required
    policy(client, owner, f, booking_cutoff_minutes=60 * 24 * 30)
    assert enrol(seat).json().get("reason") == "cutoff-passed"
    policy(client, owner, f)
    refused(enrol(priced), 409, "entitlement-not-eligible")  # a paid session still needs a package
    ok(enrol(seat))
    other, other_portal = member(client, tenant, owner, f, mailbox)
    refused(enrol(seat, other, other_portal), 409, "capacity-full")


# --- shared bookings (SCH-17, SSP-09) -----------------------------------------------------------------------


def relate(client, owner, parent_id: str, child_id: str, code: str = "parent_of") -> None:
    types = ok(client.get(f"{API}/relationship-types", headers=owner), 200)
    kind = next(t for t in types if t["code"] == code)
    ok(client.post(f"{API}/clients/{parent_id}/relationships", headers=owner,
                   json={"other_client_id": child_id, "relationship_type_id": kind["id"]}))  # fmt: skip


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
    with tenant_session(tenant.id) as session:  # the organiser's row is audited like any other participant
        audited = set(
            session.scalars(select(AuditEvent.entity_id).where(AuditEvent.entity_type == "booking_participant"))
        )
    assert {UUID(r["id"]) for r in rows} <= audited

    kid_row = rows[1]
    marked = ok(client.patch(f"{url}/{kid_row['id']}", headers=owner, json={"attendance": "no_show"}), 200)
    assert marked["attendance"] == "no_show" and marked["attendance_marked_at"]
    assert {r["client_id"]: r["attendance"] for r in ok(client.get(url, headers=owner), 200)} == {
        organiser["id"]: "scheduled", kid["id"]: "no_show"}  # fmt: skip

    refused(client.delete(f"{url}/{rows[0]['id']}", headers=owner), 409, "invalid-state-transition")
    ok(client.delete(f"{url}/{kid_row['id']}", headers=owner), 204)
    assert [r["client_id"] for r in ok(client.get(url, headers=owner), 200)] == [organiser["id"]]


def test_erasure_waits_for_a_shared_booking_ahead(client, owner, tenant, f):
    booking = session_booking(client, owner, f, 15)
    organiser, kid = new_client(client, owner, f.location), new_client(client, owner, f.location)
    relate(client, owner, organiser["id"], kid["id"], "sibling_of")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.get(Booking, UUID(booking["id"])).client_id = UUID(organiser["id"])
    ok(client.post(f"{API}/bookings/{booking['id']}/participants", headers=owner, json={"client_id": kid["id"]}))
    with tenant_session(tenant.id) as session:
        assert [c["code"] for c in subject._erase_precheck(session, UUID(kid["id"]))] == ["upcoming-booking"]


def test_participants_follow_a_client_merge(client, owner, tenant, f):
    booking = session_booking(client, owner, f, 16)
    organiser, keep, lose = (new_client(client, owner, f.location) for _ in range(3))
    relate(client, owner, organiser["id"], keep["id"], "sibling_of")
    relate(client, owner, organiser["id"], lose["id"], "sibling_of")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.get(Booking, UUID(booking["id"])).client_id = UUID(organiser["id"])
    url = f"{API}/bookings/{booking['id']}/participants"
    ok(client.post(url, headers=owner, json={"client_id": keep["id"]}))
    ok(client.post(url, headers=owner, json={"client_id": lose["id"]}))
    ok(client.post(f"{API}/clients/{keep['id']}/merge", headers=owner, json={"merged_client_ids": [lose["id"]]}), 200)
    assert [r["client_id"] for r in ok(client.get(url, headers=owner), 200)] == [organiser["id"], keep["id"]]
    with tenant_session(tenant.id) as session:
        stmt = select(func.count()).select_from(BookingParticipant)
        assert session.scalar(stmt.where(BookingParticipant.booking_id == UUID(booking["id"]))) == 2


def test_blocks_and_class_sessions_take_no_participants(client, owner, tenant, f):
    block = ok(book(client, owner, f, [f.court2], at(9), at(10)))["booking"]
    someone = new_client(client, owner, f.location)
    refused(client.post(f"{API}/bookings/{block['id']}/participants", headers=owner, json={"client_id": someone["id"]}),
            409, "invalid-state-transition")  # fmt: skip
    # A class session has no organiser: its seats go through enrolments (capacity, waivers, payment), never here.
    seat = session_booking(client, owner, f, 11, session={"capacity": 2})
    url = f"{API}/bookings/{seat['id']}/participants"
    refused(client.post(url, headers=owner, json={"client_id": someone["id"]}), 409, "invalid-state-transition")
    with tenant_session(tenant.id) as session:
        assert session.get(Session, UUID(seat["session"]["id"])).booked_count == 0
        assert session.scalar(select(func.count()).select_from(BookingParticipant)
                              .where(BookingParticipant.booking_id == UUID(seat["id"]))) == 0  # fmt: skip


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


def test_merge_waits_for_a_series_run_in_progress(client, owner, tenant, f):
    mine, other = weekly(client, owner, f, 10, f.court), weekly(client, owner, f, 10, f.court2)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.add(BookingSeriesRun(booking_series_id=UUID(other["booking_series_id"]), kind="edit",
                                     status="running", command={}))  # fmt: skip
    refused(client.post(f"{API}/bookings/{mine['booking']['id']}/merge", headers=owner,
                        json={"booking_number": other["booking"]["booking_number"]}), 409, "series-run-in-progress")  # fmt: skip


def test_merge_takes_every_lock_before_any_check(client, owner, f):
    mine, other = weekly(client, owner, f, 14, f.court), weekly(client, owner, f, 14, f.court2)
    seen: list[str] = []

    def spy(conn, cursor, statement, params, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(Engine, "before_cursor_execute", spy)
    try:
        ok(client.post(f"{API}/bookings/{mine['booking']['id']}/merge", headers=owner,
                       json={"booking_number": other["booking"]["booking_number"]}), 200)  # fmt: skip
    finally:
        event.remove(Engine, "before_cursor_execute", spy)
    start = next(i for i, sql in enumerate(seen) if "booking.booking_number =" in sql)
    merge = seen[start:]
    locks = [sql for sql in merge if sql.endswith("FOR UPDATE")]
    assert "FROM booking_series WHERE" in locks[0] and "ORDER BY booking_series.id" in locks[0]
    assert "FROM booking WHERE" in locks[1] and "ORDER BY booking.id" in locks[1]
    first_check = next(i for i, sql in enumerate(merge) if "FROM booking_series_run" in sql)
    assert merge.index(locks[1]) < first_check  # series, then bookings, then the run check


def test_merge_refuses_when_a_booking_changed_series_while_linking(client, owner, f, monkeypatch):
    mine, other = weekly(client, owner, f, 16, f.court), weekly(client, owner, f, 16, f.court2)
    third = weekly(client, owner, f, 18, f.court)
    real = scheduling_service._own

    def moved(session, *args, **kwargs):  # another request moves the other booking between the read and the locks
        session.execute(update(Booking).where(Booking.id == UUID(other["booking"]["id"]))
                        .values(booking_series_id=UUID(third["booking_series_id"])))  # fmt: skip
        return real(session, *args, **kwargs)

    monkeypatch.setattr(scheduling_service, "_own", moved)
    refused(client.post(f"{API}/bookings/{mine['booking']['id']}/merge", headers=owner,
                        json={"booking_number": other["booking"]["booking_number"]}), 409, "invalid-state-transition")  # fmt: skip


def test_merge_links_a_single_reservation_and_refuses_mismatches(client, owner, tenant, f):
    single, other = session_booking(client, owner, f, 18), session_booking(client, owner, f, 20)
    merged = ok(client.post(f"{API}/bookings/{single['id']}/merge", headers=owner,
                            json={"booking_number": other["booking_number"]}), 200)  # fmt: skip
    assert merged["occurrence_count"] == 2
    with tenant_session(tenant.id) as session:  # both bookings changed series: each is audited
        audited = set(session.scalars(select(AuditEvent.entity_id).where(
            AuditEvent.entity_type == "booking", AuditEvent.action == "scheduling.booking.update_series")))  # fmt: skip
    assert {UUID(single["id"]), UUID(other["id"])} <= audited
    block = ok(book(client, owner, f, [f.court2], at(22), at(23)))["booking"]
    refused(client.post(f"{API}/bookings/{single['id']}/merge", headers=owner,
                        json={"booking_number": block["booking_number"]}), 409, "merge-mismatch")  # fmt: skip
    missing = client.post(f"{API}/bookings/{single['id']}/merge", headers=owner, json={"booking_number": 999_999})
    refused(missing, 422, "validation-failed")
