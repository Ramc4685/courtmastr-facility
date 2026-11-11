"""Phase 10 chip A: opening-hours warnings, drag default and trainer hours on the calendar, per-staff type grants,
slot offers with derived slots, and changing a series pattern."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.scheduling import service
from app.modules.scheduling.models import Booking, Session
from app.modules.scheduling.tests.helpers import API, at, book, ok
from app.modules.scheduling.tests.helpers import facility as build
from conftest import WEEK, add_staff, login, new_client


@pytest.fixture
def f(client, owner):
    facility = build(client, owner)
    ok(client.put(f"{API}/locations/{facility.location}/facility-hours", headers=owner, json={"days": WEEK}), 200)
    return facility


def calendar(client, headers, f, start=at(0), end=at(24)) -> dict:
    return ok(client.get(f"{API}/calendar?location_id={f.location}&from={start}&to={end}", headers=headers), 200)


def window(client, owner, f, start="09:00", end="11:00") -> str:
    body = {"starts_on": "2031-05-05", "weekdays": [1], "start_time": start, "end_time": end}
    return ok(client.post(f"{API}/resources/{f.coach}/availability-windows", headers=owner, json=body))["id"]


# --- question 19: outside opening hours is a warning, never a refusal ---------------------------------------


def test_booking_outside_opening_hours_succeeds_with_a_warning(client, owner, f):
    inside = ok(book(client, owner, f, [f.court2], at(15), at(16)))  # 10:00 local, hours 08:00 to 20:00
    assert inside["warnings"] == []
    early = ok(book(client, owner, f, [f.court2], at(11), at(12)))  # 06:00 local
    assert early["warnings"] == [
        {"code": "outside-opening-hours", "detail": "Outside opening hours on 2031-05-05.", "count": 1}
    ]
    moved = ok(
        client.post(
            f"{API}/bookings/{inside['booking']['id']}/reschedule", headers=owner,
            json={"starts_at": at(24.5), "ends_at": at(25.5), "version": 1},
        ),
        200,
    )  # fmt: skip
    assert moved["warnings"][0]["code"] == "outside-opening-hours"  # 19:30 to 20:30 local runs past closing
    weekly = {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 3}
    preview = client.post(
        f"{API}/bookings/preview", headers=owner,
        json={"location_id": f.location, "kind": "block", "block_kind": "unavailable", "starts_at": at(35),
              "ends_at": at(36), "resources": [{"resource_id": f.court}], "recurrence": weekly},
    )  # fmt: skip
    assert ok(preview, 200)["warnings"] == [
        {"code": "outside-opening-hours", "detail": "3 occurrences are outside opening hours.", "count": 3}
    ]


def test_a_closed_day_warns(client, owner, f):
    closed = {"is_closed": True, "opens_time": None, "closes_time": None}
    days = [d | (closed if d["weekday"] == 1 else {}) for d in WEEK]
    ok(client.put(f"{API}/locations/{f.location}/facility-hours", headers=owner, json={"days": days}), 200)
    assert ok(book(client, owner, f, [f.court2], at(15), at(16)))["warnings"][0]["count"] == 1


# --- RES-01 and SCH-18 on the calendar ----------------------------------------------------------------------


def test_calendar_carries_the_drag_default_and_trainer_hours(client, owner, f):
    window(client, owner, f)
    view = calendar(client, owner, f)
    assert view["drag_drop_default"] == "ask"
    assert view["resource_hours"] == [
        {"resource_id": f.coach, "open": [{"starts_at": "2031-05-05T14:00:00Z", "ends_at": "2031-05-05T16:00:00Z"}]}
    ]
    url = f"{API}/scheduling-settings?location_id={f.location}"
    ok(client.patch(url, headers=owner, json={"drag_drop_default": "reschedule"}), 200)
    assert calendar(client, owner, f)["drag_drop_default"] == "reschedule"


# --- SCH-05: per-staff grants on a reservation type ---------------------------------------------------------


def test_a_restricted_type_is_booked_only_by_granted_staff(client, owner, f, tenant):
    allowed_email, allowed_id = add_staff(tenant, "front_desk", all_locations=True)
    other_email, _ = add_staff(tenant, "front_desk", all_locations=True)
    allowed, other = login(client, tenant, allowed_email), login(client, tenant, other_email)
    allowed_id = str(allowed_id)
    grants = f"{API}/reservation-types/{f.type}/grants"
    assert ok(client.get(grants, headers=owner), 200) == {
        "reservation_type_id": f.type, "is_restricted": False, "staff_user_ids": []
    }  # fmt: skip
    assert client.put(grants, headers=other, json={"staff_user_ids": []}).status_code == 403  # managers only
    saved = ok(client.put(grants, headers=owner, json={"staff_user_ids": [allowed_id, allowed_id]}), 200)
    assert (saved["is_restricted"], saved["staff_user_ids"]) == (True, [allowed_id])

    refused = book(client, other, f, [f.court2], at(15), at(16), kind="session")
    assert refused.status_code == 403 and refused.json()["code"] == "permission-denied"
    mine = ok(book(client, allowed, f, [f.court2], at(15), at(16), kind="session"))["booking"]
    ok(book(client, owner, f, [f.court], at(15), at(16), kind="session"))  # the owner is never restricted
    move = {"starts_at": at(17), "ends_at": at(18), "version": 1}
    assert client.post(f"{API}/bookings/{mine['id']}/reschedule", headers=other, json=move).status_code == 403
    assert client.post(f"{API}/bookings/{mine['id']}/cancel", headers=other, json={"version": 1}).status_code == 403
    tiles = {e["booking_id"]: e["can_edit"] for e in calendar(client, other, f)["entries"]}
    assert tiles[mine["id"]] is False
    ok(book(client, other, f, [f.half_b], at(19), at(20)))  # time blocks have no type: unaffected

    assert client.put(grants, headers=owner, json={"staff_user_ids": [str(UUID(int=7))]}).status_code == 422
    ok(client.put(grants, headers=owner, json={"staff_user_ids": []}), 200)  # open to everyone again
    ok(book(client, other, f, [f.court2], at(17), at(18), kind="session"))
    with tenant_session(tenant.id) as session:
        audited = session.scalars(select(AuditEvent).where(AuditEvent.action == service.GRANTS)).all()
    assert len(audited) == 2


def test_series_writes_check_the_grant_of_every_occurrence(client, owner, f, tenant):
    email, _ = add_staff(tenant, "manager", all_locations=True)
    manager = login(client, tenant, email)
    weekly = {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 2}
    created = ok(book(client, owner, f, [f.court2], at(15), at(16), kind="session", recurrence=weekly))
    _, someone = add_staff(tenant, "front_desk", all_locations=True)
    grants = f"{API}/reservation-types/{f.type}/grants"
    ok(client.put(grants, headers=owner, json={"staff_user_ids": [str(someone)]}), 200)
    series = f"{API}/booking-series/{created['booking_series_id']}"
    edit = {"scope": {"mode": "all"}, "patch": {"title": "Renamed"}}
    assert client.post(f"{series}/edits", headers=manager, json=edit).status_code == 403
    assert client.post(f"{series}/cancellations", headers=manager, json={"scope": {"mode": "all"}}).status_code == 403
    seat = ok(book(client, owner, f, [f.court], at(17), at(18), kind="session"))["booking"]["session"]["id"]
    assert client.patch(f"{API}/sessions/{seat}", headers=manager, json={"is_self_bookable": False}).status_code == 403
    resize = {"session_ids": [seat], "capacity": 2}
    assert client.post(f"{API}/sessions/capacity-changes", headers=manager, json=resize).status_code == 403


# --- SCH-07 and SCH-18: slot offers -------------------------------------------------------------------------


def _slots(client, owner, offer_id) -> list[dict]:
    return ok(client.get(f"{API}/slot-offers/{offer_id}/slots?from={at(0)}&to={at(24)}", headers=owner), 200)["slots"]


def test_slot_offer_derives_slots_and_materialises_one_on_first_use(client, owner, f, tenant):
    window_id = window(client, owner, f)  # Monday 09:00 to 11:00 local
    offer = ok(
        client.post(
            f"{API}/slot-offers", headers=owner,
            json={"availability_window_id": window_id, "reservation_type_id": f.type, "slot_min": 30,
                  "additional_resource_ids": [f.court2]},
        )
    )  # fmt: skip
    assert (offer["resource_id"], offer["additional_resource_ids"], offer["title"], offer["capacity"]) == (
        f.coach, [f.court2], "Clinic", 1
    )  # fmt: skip
    ok(book(client, owner, f, [f.court2], at(14.5), at(15)))  # the court is busy 09:30 to 10:00 local
    assert [(s["starts_at"][11:16], s["status"]) for s in _slots(client, owner, offer["id"])] == [
        ("14:00", "free"), ("14:30", "unavailable"), ("15:00", "free"), ("15:30", "free")
    ]  # fmt: skip
    url = f"{API}/slot-offers/{offer['id']}/slots"
    taken = ok(client.post(url, headers=owner, json={"starts_at": "2031-05-05T15:00:00Z"}), 200)
    again = ok(client.post(url, headers=owner, json={"starts_at": "2031-05-05T15:00:00Z"}), 200)
    assert taken["id"] == again["id"] and {r["resource_id"] for r in taken["resources"]} == {f.coach, f.court2}
    assert client.post(url, headers=owner, json={"starts_at": "2031-05-05T15:10:00Z"}).status_code == 422
    third = _slots(client, owner, offer["id"])[2]
    assert (third["status"], third["booking_id"]) == ("booked", taken["id"])

    seat_id = UUID(taken["session"]["id"])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        service.reserve_seat(session, seat_id)
    assert _slots(client, owner, offer["id"])[2]["status"] == "full"
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        service.release_seat(session, seat_id)  # the last seat goes: the time returns to the window
        assert session.get(Booking, session.get(Session, seat_id).booking_id).status == "cancelled"
    assert _slots(client, owner, offer["id"])[2]["status"] == "free"

    patch = {"is_active": False, "slot_min": 60}
    changed = ok(client.patch(f"{API}/slot-offers/{offer['id']}", headers=owner, json=patch), 200)
    assert (changed["is_active"], changed["slot_min"]) == (False, 60)
    assert client.post(url, headers=owner, json={"starts_at": "2031-05-05T14:00:00Z"}).status_code == 422
    assert [
        o["id"] for o in ok(client.get(f"{API}/slot-offers?resource_id={f.coach}", headers=owner), 200)["data"]
    ] == [offer["id"]]
    assert ok(client.get(f"{API}/slot-offers?resource_id={f.court}", headers=owner), 200)["data"] == []


def test_slot_offer_validation(client, owner, f):
    window_id = window(client, owner, f)
    body = {"availability_window_id": window_id, "reservation_type_id": f.type, "slot_min": 30}
    assert client.post(f"{API}/slot-offers", headers=owner, json=body | {"slot_min": 7}).status_code == 422
    unknown = body | {"availability_window_id": str(UUID(int=9))}
    assert client.post(f"{API}/slot-offers", headers=owner, json=unknown).status_code == 422
    other = build(client, owner, "America/New_York")
    elsewhere = body | {"additional_resource_ids": [other.court]}
    assert client.post(f"{API}/slot-offers", headers=owner, json=elsewhere).status_code == 422


# --- SCH-09: change an existing pattern with preview --------------------------------------------------------


def test_changing_a_pattern_cancels_later_occurrences_and_books_the_new_ones(client, owner, f, tenant):
    weekly = {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 4}
    created = ok(book(client, owner, f, [f.court2], at(15), at(16), recurrence=weekly))
    series = ok(client.get(f"{API}/booking-series/{created['booking_series_id']}", headers=owner), 200)
    url = f"{API}/booking-series/{series['id']}/rules/{series['rules'][0]['id']}"
    change = {"start_on": "2031-05-19", "start_time": "11:00", "end_time": "12:00",
              "rule": {"pattern": "weekly", "weekdays": [3], "range_type": "count", "occurrence_limit": 2}}  # fmt: skip
    desk_email, _ = add_staff(tenant, "front_desk", all_locations=True)  # edits series, cannot delete them
    assert client.patch(url, headers=login(client, tenant, desk_email), json=change).status_code == 403
    preview = ok(client.patch(url, headers=owner, json=change | {"preview": True}), 200)
    assert preview["cancelled_count"] == 2 and preview["preview"]["ok_count"] == 2
    assert ok(client.get(f"{API}/booking-series/{series['id']}", headers=owner), 200)["occurrence_count"] == 4

    done = ok(client.patch(url, headers=owner, json=change), 200)
    assert (done["cancelled_count"], done["created_count"]) == (2, 2)
    with tenant_session(tenant.id) as session:
        rows = session.execute(
            select(Booking.occurrence_on, Booking.status)
            .where(Booking.booking_series_id == UUID(series["id"]))
            .order_by(Booking.occurrence_on)
        ).all()
    assert [(str(d), s) for d, s in rows] == [
        ("2031-05-05", "confirmed"), ("2031-05-12", "confirmed"), ("2031-05-19", "cancelled"),
        ("2031-05-21", "confirmed"), ("2031-05-26", "cancelled"), ("2031-05-28", "confirmed"),
    ]  # fmt: skip
    assert client.patch(url, headers=owner, json=change | {"start_on": "2020-01-01"}).status_code == 422


# --- review follow-up (phase 10 chip A) ---------------------------------------------------------------------


def _offer(client, owner, f, window_id, **extra) -> dict:
    body = {"availability_window_id": window_id, "reservation_type_id": f.type, "slot_min": 30} | extra
    return ok(client.post(f"{API}/slot-offers", headers=owner, json=body))


def test_a_cancelled_slot_can_be_taken_again(client, owner, f, tenant):
    offer = _offer(client, owner, f, window(client, owner, f))
    url, slot = f"{API}/slot-offers/{offer['id']}/slots", {"starts_at": "2031-05-05T15:00:00Z"}
    first = ok(client.post(url, headers=owner, json=slot), 200)
    ok(client.post(f"{API}/bookings/{first['id']}/cancel", headers=owner, json={"version": first["version"]}), 200)
    second = ok(client.post(url, headers=owner, json=slot), 200)  # staff cancel freed the slot
    assert second["id"] != first["id"]
    seat_id = UUID(second["session"]["id"])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        service.reserve_seat(session, seat_id)
        service.release_seat(session, seat_id)  # the last seat goes: the session is cancelled
    third = ok(client.post(url, headers=owner, json=slot), 200)
    assert third["id"] not in (first["id"], second["id"])
    with tenant_session(tenant.id) as session:
        created = session.scalars(
            select(AuditEvent).where(AuditEvent.action == service.CREATE, AuditEvent.entity_id == UUID(third["id"]))
        ).all()
    ok(client.post(url, headers=owner, json=slot), 200)  # taking it again returns it without a second audit row
    with tenant_session(tenant.id) as session:
        again = session.scalars(
            select(AuditEvent).where(AuditEvent.action == service.CREATE, AuditEvent.entity_id == UUID(third["id"]))
        ).all()
    assert len(created) == len(again) == 1


def test_two_takers_of_one_slot_share_the_winners_session(client, owner, f, tenant):
    import threading

    from app.modules.scheduling.models import SlotOffer
    from app.modules.scheduling.offers import materialise_slot

    offer_id = UUID(_offer(client, owner, f, window(client, owner, f))["id"])
    starts_at = datetime(2031, 5, 5, 15, tzinfo=UTC)
    outcome, created, release = {}, threading.Event(), threading.Event()

    def take(name: str, hold: bool) -> None:
        try:
            with tenant_session(tenant.id, actor=system_principal("tests")) as session:
                outcome[name] = materialise_slot(session, session.get(SlotOffer, offer_id), starts_at).id
                if hold:
                    created.set()
                    release.wait(5)
        except Exception as exc:  # noqa: BLE001 - the assertion below reports it
            outcome[name] = exc

    first = threading.Thread(target=take, args=("first", True))
    second = threading.Thread(target=take, args=("second", False))
    first.start()
    created.wait(5)
    second.start()
    second.join(0.5)
    release.set()
    first.join(10)
    second.join(10)
    assert outcome["first"] == outcome["second"], outcome


def test_deleting_a_window_with_a_taken_slot_is_refused_not_a_crash(client, owner, f):
    window_id = window(client, owner, f)
    offer = _offer(client, owner, f, window_id)
    ok(
        client.post(
            f"{API}/slot-offers/{offer['id']}/slots", headers=owner, json={"starts_at": "2031-05-05T15:00:00Z"}
        ),
        200,
    )
    refused = client.delete(f"{API}/availability-windows/{window_id}", headers=owner)
    assert refused.status_code == 409 and refused.json()["code"] == "slot-offer-in-use"
    free = window(client, owner, f, "12:00", "13:00")
    _offer(client, owner, f, free)
    assert client.delete(f"{API}/availability-windows/{free}", headers=owner).status_code == 204  # no slot taken


def test_slots_step_in_real_time_across_a_clock_change(client, owner):
    f = build(client, owner)  # America/Chicago; 2031-11-02 01:00 happens twice
    body = {"starts_on": "2031-11-02", "weekdays": [7], "start_time": "00:00", "end_time": "04:00"}
    window_id = ok(client.post(f"{API}/resources/{f.coach}/availability-windows", headers=owner, json=body))["id"]
    offer = _offer(client, owner, f, window_id, slot_min=60)
    got = ok(
        client.get(
            f"{API}/slot-offers/{offer['id']}/slots?from=2031-11-02T00:00:00Z&to=2031-11-03T00:00:00Z", headers=owner
        ),
        200,
    )["slots"]  # fmt: skip
    assert [(s["starts_at"][11:16], s["ends_at"][11:16]) for s in got] == [
        ("05:00", "06:00"), ("06:00", "07:00"), ("07:00", "08:00"), ("08:00", "09:00"), ("09:00", "10:00")
    ]  # fmt: skip


def test_a_booking_across_midnight_between_open_days_has_no_warning(client, owner, f):
    allday = [{"weekday": d, "opens_time": "00:00", "closes_time": "24:00", "is_closed": False} for d in range(1, 8)]
    ok(client.put(f"{API}/locations/{f.location}/facility-hours", headers=owner, json={"days": allday}), 200)
    assert ok(book(client, owner, f, [f.court2], at(28), at(30)))["warnings"] == []  # 23:00 to 01:00 local


def test_a_pattern_change_above_the_sync_limit_is_refused(client, owner, f):
    weekly = {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 2}
    created = ok(book(client, owner, f, [f.court2], at(15), at(16), recurrence=weekly))
    series = ok(client.get(f"{API}/booking-series/{created['booking_series_id']}", headers=owner), 200)
    url = f"{API}/booking-series/{series['id']}/rules/{series['rules'][0]['id']}"
    daily = {"pattern": "daily", "range_type": "count", "occurrence_limit": service.SYNC_LIMIT + 1}
    change = {"start_on": "2031-05-12", "start_time": "11:00", "end_time": "12:00", "rule": daily}
    refused = client.patch(url, headers=owner, json=change)
    assert refused.status_code == 422 and refused.json()["errors"][0]["pointer"] == "/rule/occurrence_limit"
    assert client.patch(url, headers=owner, json=change | {"preview": True}).status_code == 422


def test_every_typed_write_checks_the_grant(client, owner, f, tenant):
    email, _ = add_staff(tenant, "manager", all_locations=True)
    manager = login(client, tenant, email)
    weekly = {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 2}
    single = ok(book(client, owner, f, [f.court], at(10), at(11), kind="session"))["booking"]
    series = ok(book(client, owner, f, [f.court2], at(15), at(16), kind="session", recurrence=weekly))
    rules = ok(client.get(f"{API}/booking-series/{series['booking_series_id']}", headers=owner), 200)["rules"]
    window_id = window(client, owner, f)
    offer = _offer(client, owner, f, window_id)
    _, someone = add_staff(tenant, "front_desk", all_locations=True)
    ok(
        client.put(f"{API}/reservation-types/{f.type}/grants", headers=owner, json={"staff_user_ids": [str(someone)]}),
        200,
    )

    pass_ = {"start_on": "2031-06-02", "start_time": "10:00", "end_time": "11:00",
             "rule": {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 1}}  # fmt: skip
    base = f"{API}/booking-series/{series['booking_series_id']}/rules"
    refused = [
        client.patch(f"{API}/bookings/{single['id']}", headers=manager, json={"title": "x", "version": 1}),
        client.post(base, headers=manager, json=pass_),
        client.patch(f"{base}/{rules[0]['id']}", headers=manager, json=pass_),
        client.post(f"{API}/slot-offers/{offer['id']}/slots", headers=manager, json={"starts_at": "2031-05-05T15:00:00Z"}),
        client.post(f"{API}/slot-offers", headers=manager,
                    json={"availability_window_id": window_id, "reservation_type_id": f.type, "slot_min": 30}),
        client.patch(f"{API}/slot-offers/{offer['id']}", headers=manager, json={"title": "x"}),
    ]  # fmt: skip
    assert [r.status_code for r in refused] == [403] * 6, [r.text for r in refused if r.status_code != 403]


def test_a_coach_cannot_take_over_another_trainers_offer_by_listing_their_own_resource(client, owner, f, tenant):
    coach_email, coach_id = add_staff(tenant, "coach", location_ids=[f.location])
    mine = ok(client.post(f"{API}/resources", headers=owner, json={
        "location_id": f.location, "resource_group_id": f.group, "name": "Coach Lee", "kind": "trainer",
        "staff_user_id": str(coach_id)}))["id"]  # fmt: skip
    coach = login(client, tenant, coach_email)
    theirs = window(client, owner, f)  # Coach Kim's window
    offer = _offer(client, owner, f, theirs)
    takeover = {"additional_resource_ids": [mine]}
    assert client.patch(f"{API}/slot-offers/{offer['id']}", headers=coach, json=takeover).status_code == 403
    body = {"availability_window_id": theirs, "reservation_type_id": f.type, "slot_min": 30} | takeover
    assert client.post(f"{API}/slot-offers", headers=coach, json=body).status_code == 403
    own_window = ok(client.post(f"{API}/resources/{mine}/availability-windows", headers=owner, json={
        "starts_on": "2031-05-05", "weekdays": [1], "start_time": "12:00", "end_time": "13:00"}))["id"]  # fmt: skip
    _offer(client, coach, f, own_window)  # their own window is fine


def test_staff_enrolment_and_instructor_assignment_need_the_type_grant(client, owner, f, tenant):
    email, _ = add_staff(tenant, "manager", all_locations=True)
    manager = login(client, tenant, email)
    seat = ok(book(client, owner, f, [f.court], at(15), at(16), kind="session"))["booking"]["session"]["id"]
    trainer = ok(client.post(f"{API}/staff-payees", headers=owner, json={
        "kind": "trainer", "display_name": "Coach Kim", "location_id": f.location, "resource_id": f.coach}))  # fmt: skip
    person = new_client(client, owner, f.location, first_name="Pat", primary_email="pat-grant@example.com")["id"]
    _, someone = add_staff(tenant, "front_desk", all_locations=True)
    grants = f"{API}/reservation-types/{f.type}/grants"
    ok(client.put(grants, headers=owner, json={"staff_user_ids": [str(someone)]}), 200)
    enrol = {"session_id": seat, "client_id": person}
    assert client.post(f"{API}/enrollments", headers=manager, json=enrol).status_code == 403
    instructor = {"staff_payee_id": trainer["id"]}
    assert client.put(f"{API}/sessions/{seat}/instructor", headers=manager, json=instructor).status_code == 403
    ok(client.put(grants, headers=owner, json={"staff_user_ids": []}), 200)  # open again: both go through
    ok(client.post(f"{API}/enrollments", headers=manager, json=enrol))
    ok(client.put(f"{API}/sessions/{seat}/instructor", headers=manager, json=instructor), 200)
