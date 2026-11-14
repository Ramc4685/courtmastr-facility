"""staff (build module 12): payees, pay and commission rules, the time clock, manager entries, shifts,
instructor assignment and payroll runs, each through the API with both permission gates and location scope."""

from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import Principal
from app.core.db.session import tenant_session
from app.core.errors import PermissionDenied
from app.core.events import OutboxEvent
from app.modules.memberships.tests.support import package_plan
from app.modules.scheduling.tests.helpers import API, DAY, at, book, facility, local, ok
from app.modules.staff import service
from conftest import PASSWORD, add_staff, login, make_tenant, new_client, populate, scalar


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def _post(client, headers, path, body, status=201):
    return ok(client.post(f"{API}{path}", headers=headers, json=body), status)


def _code(response, status):
    assert response.status_code == status, response.text
    return response.json()["code"]


def _events(tenant, event_type: str) -> int:
    return scalar(tenant, select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == event_type))


def _session(client, headers, f, resources, start, end):
    created = ok(book(client, headers, f, resources, start, end, kind="session"))
    return created["booking"]


# --- payees ------------------------------------------------------------------------------------------------


def test_trainer_payee_creates_or_adopts_a_calendar_column(client, tenant, owner, f):
    _, coach_id = add_staff(tenant, "coach", location_ids=[f.location])
    made = _post(client, owner, "/staff-payees", {
        "kind": "trainer", "display_name": "Pat Lee", "location_id": f.location, "staff_user_id": str(coach_id)})  # fmt: skip
    column = ok(client.get(f"{API}/resources/{made['resource_id']}", headers=owner), 200)
    assert column["kind"] == "trainer" and column["resource_group_id"] == f.group and column["name"] == "Pat Lee"
    adopted = _post(client, owner, "/staff-payees", {
        "kind": "trainer", "display_name": "Coach Kim", "location_id": f.location, "resource_id": f.coach})  # fmt: skip
    assert adopted["resource_id"] == f.coach
    twice = client.post(f"{API}/staff-payees", headers=owner, json={
        "kind": "trainer", "display_name": "Again", "location_id": f.location, "resource_id": f.coach})  # fmt: skip
    assert _code(twice, 409) == "already-exists"
    court = client.post(f"{API}/staff-payees", headers=owner, json={
        "kind": "trainer", "display_name": "Court", "location_id": f.location, "resource_id": f.court})  # fmt: skip
    assert court.json()["errors"][0]["pointer"] == "/resource_id"
    nobody = client.post(f"{API}/staff-payees", headers=owner, json={
        "kind": "salesperson", "display_name": "Sam", "location_id": f.location})  # fmt: skip
    assert nobody.json()["errors"][0]["pointer"] == "/staff_user_id"
    _, elsewhere = add_staff(tenant, "front_desk")  # no access to this location
    stranger = client.post(f"{API}/staff-payees", headers=owner, json={
        "kind": "salesperson", "display_name": "Sam", "location_id": f.location, "staff_user_id": str(elsewhere)})  # fmt: skip
    assert stranger.status_code == 422
    desk_email, _ = add_staff(tenant, "front_desk", location_ids=[f.location])
    denied = client.post(f"{API}/staff-payees", headers=login(client, tenant, desk_email), json={
        "kind": "trainer", "display_name": "X", "location_id": f.location})  # fmt: skip
    assert _code(denied, 403) == "permission-denied"
    assert _events(tenant, "staff.trainer.created") == 2
    renamed = ok(client.patch(f"{API}/staff-payees/{made['id']}", headers=owner, json={"display_name": "Pat L."}), 200)
    assert renamed["display_name"] == "Pat L."
    listed = ok(client.get(f"{API}/staff-payees?kind=trainer", headers=owner), 200)["data"]
    assert {p["id"] for p in listed} == {made["id"], adopted["id"]}


def test_pay_and_commission_rules_are_admin_only(client, tenant, owner, f):
    trainer = _post(client, owner, "/staff-payees", {
        "kind": "trainer", "display_name": "Coach Kim", "location_id": f.location, "resource_id": f.coach})  # fmt: skip
    manager_email, _ = add_staff(tenant, "manager", location_ids=[f.location])
    manager = login(client, tenant, manager_email)
    url = f"{API}/staff-payees/{trainer['id']}"
    assert client.get(f"{url}/pay-rates", headers=manager).status_code == 403
    assert client.put(f"{url}/pay-rates/default", headers=manager, json={"pay_basis": "per_session"}).status_code == 403
    # Relinking the login moves the payee's pay and commission, so it is an admin change too.
    relink = client.patch(
        url, headers=manager | {"Idempotency-Key": "relink-manager"}, json={"staff_user_id": str(tenant.owner_id)}
    )
    assert relink.status_code == 403
    assert (
        client.patch(
            url, headers=manager | {"Idempotency-Key": "rename-manager"}, json={"display_name": "Kim"}
        ).status_code
        == 200
    )
    rate = ok(
        client.put(
            f"{url}/pay-rates/default", headers=owner, json={"pay_basis": "per_attendee", "rate_60_minor": 2500}
        ),
        200,
    )
    again = ok(
        client.put(f"{url}/pay-rates/default", headers=owner, json={"pay_basis": "per_session", "rate_60_minor": 4000}),
        200,
    )
    assert again["id"] == rate["id"] and len(ok(client.get(f"{url}/pay-rates", headers=owner), 200)) == 1
    bad = client.put(f"{url}/commission-rules", headers=owner, json={"rules": [
        {"applies_to": "package_sale", "reservation_type_id": "01a1c8fa-0000-7000-8000-000000000000"}]})  # fmt: skip
    assert bad.json()["errors"][0]["pointer"] == "/rules/0/reservation_type_id"
    rules = ok(client.put(f"{url}/commission-rules", headers=owner, json={"rules": [
        {"applies_to": "package_sale", "commission_pct": "10"},
        {"applies_to": "package_sale", "reservation_type_id": f.type, "commission_pct": "15"}]}), 200)  # fmt: skip
    assert len(rules["rules"]) == 2
    assert ok(client.put(f"{url}/commission-rules", headers=owner, json={"rules": []}), 200)["rules"] == []
    flagged = client.put(f"{url}/commission-rules", headers=owner, json={"rules": [
        {"applies_to": "package_sale", "is_first_invoice_only": True}]})  # fmt: skip
    assert flagged.status_code == 422  # ck_commission_rule_target
    seller = _post(client, owner, "/staff-payees", {"kind": "salesperson", "display_name": "Olive", "location_id": f.location,
                                                    "staff_user_id": str(tenant.owner_id)})  # fmt: skip
    wrong = client.put(
        f"{API}/staff-payees/{seller['id']}/pay-rates/default", headers=owner, json={"pay_basis": "per_session"}
    )
    assert wrong.status_code == 422
    assert (
        scalar(tenant, select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "staff.pay_rate.manage"))
        >= 3
    )


# --- time clock --------------------------------------------------------------------------------------------


def _hourly(client, owner, staff_user_id, rate=1500):
    job = _post(client, owner, "/job-classifications", {"name": f"Desk {staff_user_id}"[:40]})
    _post(client, owner, f"/staff-users/{staff_user_id}/hourly-rates",
          {"job_classification_id": job["id"], "rate_minor": rate, "effective_from_on": "2020-01-01"})  # fmt: skip
    return job["id"]


def test_clock_in_and_out_with_password_and_network(client, tenant, owner, f):
    desk_email, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, desk_email)
    job = _post(client, owner, "/job-classifications", {"name": "Desk"})
    state = ok(client.get(f"{API}/time-entries/current?location_id={f.location}", headers=desk), 200)
    assert state == {"open_entry": None, "job_classifications": [], "is_network_allowed": True}
    punch = {"location_id": f.location, "job_classification_id": job["id"], "password": PASSWORD}
    no_rate = client.post(f"{API}/time-entries/clock-in", headers=desk, json=punch)
    assert no_rate.json()["errors"][0]["pointer"] == "/job_classification_id"
    _post(client, owner, f"/staff-users/{desk_id}/hourly-rates",
          {"job_classification_id": job["id"], "rate_minor": 1500, "effective_from_on": "2020-01-01"})  # fmt: skip
    wrong = client.post(f"{API}/time-entries/clock-in", headers=desk, json=punch | {"password": "not-it"})
    assert _code(wrong, 403) == "reauthentication-failed"
    failed = AuditEvent.action == "platform.identity.reauthentication_failed"
    assert scalar(tenant, select(func.count()).select_from(AuditEvent).where(failed)) == 1  # kept despite the 403
    entry = _post(client, desk, "/time-entries/clock-in", punch)
    assert entry["source"] == "self" and entry["clock_out_at"] is None and entry["staff_user_id"] == str(desk_id)
    assert _code(client.post(f"{API}/time-entries/clock-in", headers=desk, json=punch), 409) == "already-clocked-in"
    state = ok(client.get(f"{API}/time-entries/current?location_id={f.location}", headers=desk), 200)
    assert state["open_entry"]["id"] == entry["id"] and [j["id"] for j in state["job_classifications"]] == [job["id"]]
    closed = ok(client.post(f"{API}/time-entries/clock-out", headers=desk, json={"password": PASSWORD}), 200)
    assert closed["clock_out_at"] and closed["duration_minutes"] == 0
    assert _events(tenant, "staff.time_entry.closed") == 1
    again = client.post(f"{API}/time-entries/clock-out", headers=desk, json={"password": PASSWORD})
    assert _code(again, 409) == "not-clocked-in"
    ok(client.put(f"{API}/staff-settings?location_id={f.location}", headers=owner,
                  json={"is_time_clock_network_restricted": True, "time_clock_networks": ["10.0.0.0/8"]}), 200)  # fmt: skip
    assert ok(client.get(f"{API}/staff-settings?location_id={f.location}", headers=desk), 200)["is_override"] is True
    assert ok(client.get(f"{API}/time-entries/current?location_id={f.location}", headers=desk), 200)[
        "is_network_allowed"] is False  # fmt: skip
    blocked = client.post(f"{API}/time-entries/clock-in", headers=desk, json=punch)
    assert _code(blocked, 403) == "network-not-allowed"
    viewer_email, _ = add_staff(tenant, "view_only", location_ids=[f.location])
    viewer = login(client, tenant, viewer_email)
    assert client.post(f"{API}/time-entries/clock-in", headers=viewer, json=punch).status_code == 403


def test_manager_entries_never_their_own_and_own_reach_lists(client, tenant, owner, f):
    manager_email, manager_id = add_staff(tenant, "manager", location_ids=[f.location])
    manager = login(client, tenant, manager_email)
    desk_email, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, desk_email)
    job = _hourly(client, owner, desk_id)
    body = {"staff_user_id": str(desk_id), "location_id": f.location, "job_classification_id": job,
            "clock_in_at": at(9), "clock_out_at": at(13), "edit_reason": "Forgot to punch"}  # fmt: skip
    entry = _post(client, manager, "/time-entries", body)
    assert entry["source"] == "manager" and entry["duration_minutes"] == 240
    assert entry["edited_by_staff_user_id"] == str(manager_id)
    overlap = client.post(
        f"{API}/time-entries", headers=manager, json=body | {"clock_in_at": at(12), "clock_out_at": at(14)}
    )
    assert _code(overlap, 409) == "time-entry-overlap"
    mine = body | {"staff_user_id": str(manager_id)}
    assert _code(client.post(f"{API}/time-entries", headers=manager, json=mine), 403) == "own-time-entry"
    theirs = _post(client, owner, "/time-entries", mine)  # Owner may enter anyone's hours
    patch = client.patch(
        f"{API}/time-entries/{theirs['id']}", headers=manager, json={"edit_reason": "x", "clock_out_at": at(12)}
    )
    assert _code(patch, 403) == "own-time-entry"
    assert {e["staff_user_id"] for e in ok(client.get(f"{API}/time-entries", headers=desk), 200)["data"]} == {
        str(desk_id)
    }
    assert len(ok(client.get(f"{API}/time-entries", headers=manager), 200)["data"]) == 2
    moved = ok(client.patch(f"{API}/time-entries/{entry['id']}", headers=manager,
                            json={"clock_out_at": at(12), "edit_reason": "Left early"}), 200)  # fmt: skip
    assert moved["duration_minutes"] == 180 and moved["edit_reason"] == "Left early"
    assert client.post(f"{API}/time-entries/{entry['id']}/void", headers=manager, json={}).status_code == 422
    voided = ok(
        client.post(f"{API}/time-entries/{entry['id']}/void", headers=manager, json={"edit_reason": "Dup"}), 200
    )
    assert voided["voided_at"]
    again = client.patch(f"{API}/time-entries/{entry['id']}", headers=manager, json={"edit_reason": "x"})
    assert _code(again, 409) == "time-entry-voided"
    assert client.post(f"{API}/time-entries", headers=desk, json=body).status_code == 403


def test_time_summary_counts_the_local_day_and_masks_pay(client, tenant, owner, f):
    manager_email, _ = add_staff(tenant, "manager", location_ids=[f.location])
    manager = login(client, tenant, manager_email)
    _, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    job = _hourly(client, owner, desk_id, rate=1500)
    # 23:30 on the night clocks spring forward in Chicago: 04:30 UTC on 10 March, but 9 March on the wall.
    _post(client, manager, "/time-entries", {
        "staff_user_id": str(desk_id), "location_id": f.location, "job_classification_id": job,
        "clock_in_at": local("America/Chicago", 2031, 3, 9, 23, 30),
        "clock_out_at": local("America/Chicago", 2031, 3, 10, 0, 30), "edit_reason": "Late close"})  # fmt: skip
    rows = ok(client.get(f"{API}/time-entries/summary?from=2031-03-09&to=2031-03-09", headers=owner), 200)
    assert [(r["minutes"], r["pay_minor"], r["entry_count"]) for r in rows] == [(60, 1500, 1)]
    assert rows[0]["display_name"] == "Front_Desk Tester"
    assert ok(client.get(f"{API}/time-entries/summary?from=2031-03-10&to=2031-03-10", headers=owner), 200) == []
    masked = ok(client.get(f"{API}/time-entries/summary?from=2031-03-09&to=2031-03-09", headers=manager), 200)
    assert masked[0]["pay_minor"] is None
    too_long = client.get(f"{API}/time-entries/summary?from=2031-01-01&to=2031-06-01", headers=owner)
    assert too_long.status_code == 422


# --- shifts ------------------------------------------------------------------------------------------------


def test_shifts_plan_publish_and_my_shifts(client, tenant, owner, f):
    manager_email, _ = add_staff(tenant, "manager", location_ids=[f.location])
    manager = login(client, tenant, manager_email)
    desk_email, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, desk_email)
    body = {
        "staff_user_id": str(desk_id),
        "location_id": f.location,
        "starts_at": at(14),
        "ends_at": at(22),
        "note": "Close",
    }
    shift = _post(client, manager, "/shifts", body)
    assert shift["status"] == "draft"
    assert _code(
        client.post(f"{API}/shifts", headers=manager, json=body | {"starts_at": at(20), "ends_at": at(23)}), 409
    ) == ("shift-conflict")
    _, outsider = add_staff(tenant, "front_desk")
    assert (
        client.post(f"{API}/shifts", headers=manager, json=body | {"staff_user_id": str(outsider)}).status_code == 422
    )
    assert client.post(f"{API}/shifts", headers=manager, json=body | {"ends_at": at(13)}).status_code == 422
    assert client.get(f"{API}/shifts", headers=desk).status_code == 403
    assert ok(client.get(f"{API}/my-shifts", headers=desk), 200)["data"] == []
    assert ok(client.post(f"{API}/shifts/publish", headers=manager, json={"shift_ids": [shift["id"]]}), 200) == {
        "published_count": 1
    }
    mine = ok(client.get(f"{API}/my-shifts", headers=desk), 200)["data"]
    assert [s["id"] for s in mine] == [shift["id"]] and "note" not in mine[0]
    day2 = DAY + timedelta(days=1)
    for start in (9, 15):
        _post(client, manager, "/shifts", body | {"starts_at": at(start, day2), "ends_at": at(start + 4, day2)})
    window = {"location_id": f.location, "starts_from": at(0, day2), "starts_to": at(24, day2)}
    assert ok(client.post(f"{API}/shifts/publish", headers=manager, json=window), 200) == {"published_count": 2}
    assert client.post(f"{API}/shifts/publish", headers=manager, json={}).status_code == 422
    cancelled = ok(client.post(f"{API}/shifts/{shift['id']}/cancel", headers=manager), 200)
    assert cancelled["status"] == "cancelled"
    assert (
        _code(client.patch(f"{API}/shifts/{shift['id']}", headers=manager, json={"note": "x"}), 409)
        == "shift-cancelled"
    )
    ok(client.post(f"{API}/shifts", headers=manager, json=body), 201)  # the cancelled shift no longer blocks the slot


# --- instructors -------------------------------------------------------------------------------------------


def test_instructor_assignment_goes_through_scheduling(client, tenant, owner, f):
    trainer = _post(client, owner, "/staff-payees", {
        "kind": "trainer", "display_name": "Coach Kim", "location_id": f.location, "resource_id": f.coach})  # fmt: skip
    first = _session(client, owner, f, [f.court], at(15), at(16))
    seat = first["session"]["id"]
    assigned = ok(client.put(f"{API}/sessions/{seat}/instructor", headers=owner,
                             json={"staff_payee_id": trainer["id"]}), 200)  # fmt: skip
    assert set(assigned["resource_ids"]) == {f.court, f.coach}
    listed = ok(
        client.get(f"{API}/staff-payees/{trainer['id']}/sessions?from=2031-05-05&to=2031-05-05", headers=owner), 200
    )
    assert [s["session_id"] for s in listed] == [seat]
    clash = _session(client, owner, f, [f.court2], at(15, DAY), at(16))["session"]["id"]
    busy = client.put(f"{API}/sessions/{clash}/instructor", headers=owner, json={"staff_payee_id": trainer["id"]})
    assert _code(busy, 409) == "booking-conflict"
    removed = ok(client.put(f"{API}/sessions/{seat}/instructor", headers=owner, json={"staff_payee_id": None}), 200)
    assert removed["resource_ids"] == [f.court]
    alone = _session(client, owner, f, [f.coach], at(18), at(19))["session"]["id"]
    empty = client.put(f"{API}/sessions/{alone}/instructor", headers=owner, json={"staff_payee_id": None})
    assert _code(empty, 409) == "session-needs-resource"
    coach_email, coach_id = add_staff(tenant, "coach", location_ids=[f.location])
    own = _post(client, owner, "/staff-payees", {"kind": "trainer", "display_name": "Pat", "location_id": f.location,
                                                 "staff_user_id": str(coach_id)})  # fmt: skip
    coach = login(client, tenant, coach_email)
    refused = client.put(f"{API}/sessions/{seat}/instructor", headers=coach, json={"staff_payee_id": own["id"]})
    assert _code(refused, 403) == "permission-denied"  # own reach: the session is not on the coach's column
    mine = _session(client, owner, f, [f.court, own["resource_id"]], at(20), at(21))["session"]["id"]
    swap = client.put(f"{API}/sessions/{mine}/instructor", headers=coach, json={"staff_payee_id": trainer["id"]})
    assert _code(swap, 403) == "own-sessions-only"  # a coach cannot hand their session to someone else
    off = client.put(f"{API}/sessions/{mine}/instructor", headers=coach, json={"staff_payee_id": None})
    assert _code(off, 403) == "own-sessions-only"
    ok(client.put(f"{API}/sessions/{mine}/instructor", headers=coach, json={"staff_payee_id": own["id"]}), 200)


# --- payroll -----------------------------------------------------------------------------------------------


def test_payroll_run_pays_sessions_and_hours_then_freezes(client, tenant, owner, f):
    trainer = _post(client, owner, "/staff-payees", {
        "kind": "trainer", "display_name": "Coach Kim", "location_id": f.location, "resource_id": f.coach})  # fmt: skip
    ok(client.put(f"{API}/staff-payees/{trainer['id']}/pay-rates/default", headers=owner,
                  json={"pay_basis": "per_attendee", "rate_60_minor": 3000}), 200)  # fmt: skip
    desk_email, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, desk_email)
    job = _hourly(client, owner, desk_id, rate=1500)
    _post(client, owner, "/time-entries", {"staff_user_id": str(desk_id), "location_id": f.location,
                                           "job_classification_id": job, "clock_in_at": at(9), "clock_out_at": at(11),
                                           "edit_reason": "Manual"})  # fmt: skip
    booked = _session(client, owner, f, [f.coach], at(15), at(16))
    person = new_client(client, owner, f.location)
    enrolled = _post(client, owner, "/enrollments", {"session_id": booked["session"]["id"], "client_id": person["id"]})
    with clock.freeze(DAY + timedelta(days=1)):
        owner, desk = login(client, tenant), login(client, tenant, desk_email)  # tokens minted on the frozen clock
        ok(client.put(f"{API}/sessions/{booked['session']['id']}/attendance", headers=owner,
                      json={"marks": [{"enrollment_id": enrolled["id"], "status": "attended"}]}), 200)  # fmt: skip
        period = {"location_id": f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-10"}
        run = _post(client, owner, "/payroll-runs", period)
        assert (run["status"], run["statement_count"], run["total_minor"]) == ("calculated", 2, 6000)
        statements = {
            s["display_name"]: s
            for s in ok(client.get(f"{API}/payroll-runs/{run['id']}/statements", headers=owner), 200)["data"]
        }
        coach_lines = ok(client.get(f"{API}/pay-statements/{statements['Coach Kim']['id']}/lines", headers=owner), 200)[
            "data"
        ]
        assert [(line["kind"], line["amount_minor"], line["occurred_on"]) for line in coach_lines] == [
            ("session", 3000, "2031-05-05")
        ]
        desk_line = ok(
            client.get(f"{API}/pay-statements/{statements['Front_Desk Tester']['id']}/lines", headers=owner), 200
        )["data"][0]
        assert (desk_line["kind"], desk_line["quantity"], desk_line["amount_minor"]) == ("hourly", "2.00", 3000)
        assert client.get(f"{API}/payroll-runs/{run['id']}/statements", headers=desk).status_code == 404  # not final
        extra = ok(client.patch(f"{API}/pay-statements/{statements['Coach Kim']['id']}", headers=owner,
                                json={"additional_income_minor": 500, "additional_income_note": "Bonus"}), 200)  # fmt: skip
        assert extra["total_minor"] == 3500
        assert ok(client.get(f"{API}/payroll-runs/{run['id']}", headers=owner), 200)["total_minor"] == 6500
        assert ok(client.post(f"{API}/payroll-runs/{run['id']}/recalculate", headers=owner), 200)["total_minor"] == 6000
        # recalculating rebuilds the statements, so their ids change
        statements = {
            s["display_name"]: s
            for s in ok(client.get(f"{API}/payroll-runs/{run['id']}/statements", headers=owner), 200)["data"]
        }
        final = ok(client.post(f"{API}/payroll-runs/{run['id']}/finalize", headers=owner), 200)
        assert final["status"] == "finalized" and final["finalized_by_staff_user_id"] == str(tenant.owner_id)
        frozen = client.patch(f"{API}/pay-statements/{statements['Coach Kim']['id']}", headers=owner,
                              json={"additional_income_minor": 1})  # fmt: skip
        assert _code(frozen, 409) == "invalid-state-transition"
        assert (
            _code(client.post(f"{API}/payroll-runs/{run['id']}/recalculate", headers=owner), 409)
            == "payroll-run-frozen"
        )
        own = ok(client.get(f"{API}/payroll-runs/{run['id']}/statements", headers=desk), 200)["data"]
        assert [s["staff_user_id"] for s in own] == [str(desk_id)]
        assert client.get(f"{API}/pay-statements/{statements['Coach Kim']['id']}", headers=desk).status_code == 404
        csv = ok(client.post(f"{API}/payroll-runs/{run['id']}/export", headers=owner), 200)
        assert csv["content_type"] == "text/csv" and "Coach Kim,30.00,0.00,0.00,0.00,0.00,30.00" in csv["content"]
        assert ok(client.post(f"{API}/payroll-runs/{run['id']}/void", headers=owner), 200)["status"] == "voided"
        assert _events(tenant, "staff.payroll_run.finalized") == 1
        manager_email, _ = add_staff(tenant, "manager", location_ids=[f.location])
        assert (
            client.post(f"{API}/payroll-runs", headers=login(client, tenant, manager_email), json=period).status_code
            == 403
        )
        long = client.post(f"{API}/payroll-runs", headers=owner, json=period | {"period_ends_on": "2031-08-01"})
        assert long.status_code == 422


def test_package_sale_commission_and_paid_before_flag(client):
    ids = populate(client, make_tenant())
    owner = ids.headers
    seller = _post(client, owner, "/staff-payees", {"kind": "salesperson", "display_name": "Olive", "location_id": ids.location_id,
                                                    "staff_user_id": str(ids.tenant.owner_id)})  # fmt: skip
    ok(client.put(f"{API}/staff-payees/{seller['id']}/commission-rules", headers=owner,
                  json={"rules": [{"applies_to": "package_sale", "commission_pct": "10"}]}), 200)  # fmt: skip
    today = clock.now().astimezone(ZoneInfo("America/Chicago")).date()
    body = {"location_id": ids.location_id, "period_starts_on": (today - timedelta(days=1)).isoformat(),
            "period_ends_on": today.isoformat(), "commission_basis": "invoiced", "includes": ["commissions"],
            "scope_staff_payee_id": seller["id"]}  # fmt: skip

    def lines(run_id):
        statement = ok(client.get(f"{API}/payroll-runs/{run_id}/statements", headers=owner), 200)["data"][0]
        return ok(
            client.get(f"{API}/pay-statements/{statement['id']}/lines?kind=package_sale_commission", headers=owner), 200
        )["data"]

    first = _post(client, owner, "/payroll-runs", body)
    found = lines(first["id"])
    assert found and all(line["amount_minor"] == (line["base_minor"] + 5) // 10 for line in found)
    assert not any(line["was_paid_before"] for line in found)
    ok(client.post(f"{API}/payroll-runs/{first['id']}/finalize", headers=owner), 200)
    assert all(line["was_paid_before"] for line in lines(_post(client, owner, "/payroll-runs", body)["id"]))


# --- location scope ----------------------------------------------------------------------------------------


def test_other_location_admin_sees_nothing_and_cannot_run_tenant_wide(client, tenant, owner, f):
    other = f_other = _post(
        client, owner, "/locations", {"name": "Elsewhere", "time_zone": "America/Chicago", "country_code": "US"}
    )
    del f_other
    trainer = _post(client, owner, "/staff-payees", {
        "kind": "trainer", "display_name": "Coach Kim", "location_id": f.location, "resource_id": f.coach})  # fmt: skip
    admin_email, _ = add_staff(tenant, "admin", location_ids=[other["id"]])
    admin = login(client, tenant, admin_email)
    assert _code(client.get(f"{API}/staff-payees/{trainer['id']}", headers=admin), 404) == "not-found"
    assert (
        client.patch(f"{API}/staff-payees/{trainer['id']}", headers=admin, json={"display_name": "x"}).status_code
        == 404
    )
    assert ok(client.get(f"{API}/staff-payees", headers=admin), 200)["data"] == []
    tenant_wide = {"period_starts_on": "2031-05-01", "period_ends_on": "2031-05-10"}
    assert client.post(f"{API}/payroll-runs", headers=admin, json=tenant_wide).status_code == 403
    run = _post(client, owner, "/payroll-runs", tenant_wide)
    assert client.get(f"{API}/payroll-runs/{run['id']}", headers=admin).status_code == 404
    assert ok(client.get(f"{API}/payroll-runs", headers=admin), 200)["data"] == []
    assert client.put(f"{API}/staff-settings", headers=admin, json={}).status_code == 403
    assert client.post(f"{API}/job-classifications", headers=admin, json={"name": "Coach"}).status_code == 403


# --- wave 2 hardening (docs/status/security-wave2.md) ------------------------------------------------------


def test_w2_03_linking_a_login_to_a_payee_needs_the_pay_key_and_never_overwrites(client, tenant, owner, f):
    _, coach_id = add_staff(tenant, "coach", location_ids=[f.location])
    manager_email, _ = add_staff(tenant, "manager", location_ids=[f.location])
    manager = login(client, tenant, manager_email)  # holds resources.resource.manage, not staff.pay_rate.manage
    body = {"kind": "trainer", "display_name": "Pat", "location_id": f.location, "staff_user_id": str(coach_id)}
    assert client.post(f"{API}/staff-payees", headers=manager, json=body).status_code == 403
    unlinked = body | {"staff_user_id": None, "display_name": "Pat unlinked"}
    assert _post(client, manager, "/staff-payees", unlinked)["staff_user_id"] is None
    _post(client, owner, "/staff-payees", body)  # links the coach to a new calendar column
    relink = client.post(
        f"{API}/staff-payees", headers=owner, json=body | {"display_name": "Pat 2", "resource_id": f.coach}
    )
    assert _code(relink, 409) == "already-linked"


def test_w2_05_a_payroll_runner_never_adds_income_to_their_own_statement(client, tenant, owner, f):
    desk_email, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    job = _hourly(client, owner, desk_id)
    _post(client, owner, "/time-entries", {"staff_user_id": str(desk_id), "location_id": f.location,
                                           "job_classification_id": job, "clock_in_at": at(9), "clock_out_at": at(11),
                                           "edit_reason": "Manual"})  # fmt: skip
    with clock.freeze(DAY + timedelta(days=1)):
        owner = login(client, tenant)
        period = {"location_id": f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-10"}
        run = _post(client, owner, "/payroll-runs", period)
        mine = ok(client.get(f"{API}/payroll-runs/{run['id']}/statements", headers=owner), 200)["data"][0]
    runner = Principal(kind="staff", tenant_id=tenant.id, staff_user_id=desk_id,
                       permissions={service.RUN_CREATE: "all"})  # a custom role below Admin  # fmt: skip
    with tenant_session(tenant.id, actor=runner) as session, pytest.raises(PermissionDenied):
        service.update_pay_statement(session, runner, UUID(mine["id"]), {"additional_income_minor": 500})


# --- Phase 10 chip D: floor and flat pay, overrides, bonuses, shift tools -----------------------------------


def _utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _coach_payee(client, owner, f, **rate):
    trainer = _post(client, owner, "/staff-payees", {
        "kind": "trainer", "display_name": "Coach Kim", "location_id": f.location, "resource_id": f.coach})  # fmt: skip
    body = {"pay_basis": "per_session", "rate_60_minor": 3000} | rate
    ok(client.put(f"{API}/staff-payees/{trainer['id']}/pay-rates/default", headers=owner, json=body), 200)
    return trainer


def _lines(client, owner, run_id, name="Coach Kim"):
    statements = ok(client.get(f"{API}/payroll-runs/{run_id}/statements", headers=owner), 200)["data"]
    statement = next(s for s in statements if s["display_name"] == name)
    lines = ok(client.get(f"{API}/pay-statements/{statement['id']}/lines", headers=owner), 200)["data"]
    return statement, [(line["kind"], line["amount_minor"]) for line in lines]


def test_floor_flat_and_bonus_lines_are_their_own_statement_lines(client, tenant, owner, f):
    trainer = _coach_payee(client, owner, f, floor_rate_minor=1800, program_instruction_rate_minor=4000)
    rules = {"rules": [
        {"kind": "trained_hours", "threshold_minutes": 120, "amount_minor": 500},
        {"kind": "off_hours", "weekdays": [0], "from_minute": 17 * 60, "to_minute": 1440, "amount_minor": 600},
    ]}  # fmt: skip
    ok(client.put(f"{API}/staff-payees/{trainer['id']}/bonus-rules", headers=owner, json=rules), 200)
    booked = _session(client, owner, f, [f.coach], local(f.zone, 2031, 5, 5, 10), local(f.zone, 2031, 5, 5, 11))
    person = new_client(client, owner, f.location)
    enrolled = _post(client, owner, "/enrollments", {"session_id": booked["session"]["id"], "client_id": person["id"]})
    for kind, (start, end) in (("floor_shift", (12, 13.5)), ("instruction", (18, 19)), ("unpaid", (14, 15))):
        ok(book(client, owner, f, [f.coach], local(f.zone, 2031, 5, 5, int(start), int(start % 1 * 60)),
                local(f.zone, 2031, 5, 5, int(end), int(end % 1 * 60)), block_kind=kind))  # fmt: skip
    with clock.freeze(DAY + timedelta(days=1)):
        owner = login(client, tenant)
        ok(client.put(f"{API}/sessions/{booked['session']['id']}/attendance", headers=owner,
                      json={"marks": [{"enrollment_id": enrolled["id"], "status": "attended"}]}), 200)  # fmt: skip
        period = {"location_id": f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-10"}
        run = _post(client, owner, "/payroll-runs", period)
        statement, lines = _lines(client, owner, run["id"])
        assert sorted(lines) == sorted([
            ("session", 3000), ("floor", 2700), ("program_instruction", 4000),
            ("trained_hours_bonus", 500),  # session and instruction block: 120 trained minutes, exactly the threshold
            ("off_hours_bonus", 600),  # the 18:00 to 19:00 Monday block is the only trained time after 17:00
        ])  # fmt: skip
        assert (statement["session_pay_minor"], statement["bonus_minor"], statement["total_minor"]) == (
            9700,
            1100,
            10800,
        )
        # One minute under the threshold earns no trained-hours bonus.
        rules["rules"][0]["threshold_minutes"] = 121
        ok(client.put(f"{API}/staff-payees/{trainer['id']}/bonus-rules", headers=owner, json=rules), 200)
        ok(client.post(f"{API}/payroll-runs/{run['id']}/recalculate", headers=owner), 200)
        assert _lines(client, owner, run["id"])[0]["bonus_minor"] == 600
        # A finalized run is frozen: changing the rules afterwards does not touch it, and a void stays frozen.
        ok(client.post(f"{API}/payroll-runs/{run['id']}/finalize", headers=owner), 200)
        ok(client.put(f"{API}/staff-payees/{trainer['id']}/bonus-rules", headers=owner, json={"rules": []}), 200)
        assert _lines(client, owner, run["id"])[0]["bonus_minor"] == 600
        ok(client.post(f"{API}/payroll-runs/{run['id']}/void", headers=owner), 200)
        assert (
            _code(client.post(f"{API}/payroll-runs/{run['id']}/recalculate", headers=owner), 409)
            == "payroll-run-frozen"
        )
        assert _lines(client, owner, run["id"])[0]["total_minor"] == 3000 + 2700 + 4000 + 600


def test_override_rates_by_reservation_type_and_membership_type(client, tenant, owner, f):
    trainer = _coach_payee(client, owner, f)
    url = f"{API}/staff-payees/{trainer['id']}/pay-rates"
    override = ok(
        client.put(f"{url}/{f.type}", headers=owner, json={"pay_basis": "per_session", "rate_60_minor": 5000}), 200
    )
    assert override["reservation_type_id"] == f.type and override["membership_type_id"] is None
    assert len(ok(client.get(url, headers=owner), 200)) == 2
    again = ok(
        client.put(f"{url}/{f.type}", headers=owner, json={"pay_basis": "per_session", "rate_60_minor": 5500}), 200
    )
    assert again["id"] == override["id"] and again["rate_60_minor"] == 5500
    flat = client.put(f"{url}/{f.type}", headers=owner, json={"pay_basis": "per_session", "floor_rate_minor": 1})
    assert flat.status_code == 422 and flat.json()["errors"][0]["pointer"] == "/floor_rate_minor"
    nowhere = client.put(f"{url}/{UUID(int=7)}", headers=owner, json={"pay_basis": "per_session"})
    assert nowhere.json()["errors"][0]["pointer"] == "/reservation_type_id"
    unknown = client.put(f"{url}/membership-types/{UUID(int=7)}", headers=owner, json={"pay_basis": "per_session"})
    assert unknown.status_code == 422 and unknown.json()["errors"][0]["pointer"] == "/membership_type_id"
    manager_email, _ = add_staff(tenant, "manager", location_ids=[f.location])
    manager = login(client, tenant, manager_email)
    assert client.put(f"{url}/{f.type}", headers=manager, json={"pay_basis": "per_session"}).status_code == 403
    assert client.delete(f"{url}/{f.type}", headers=manager).status_code == 403
    booked = _session(client, owner, f, [f.coach], at(15), at(16))
    person = new_client(client, owner, f.location)
    enrolled = _post(client, owner, "/enrollments", {"session_id": booked["session"]["id"], "client_id": person["id"]})
    with clock.freeze(DAY + timedelta(days=1)):
        owner = login(client, tenant)
        ok(client.put(f"{API}/sessions/{booked['session']['id']}/attendance", headers=owner,
                      json={"marks": [{"enrollment_id": enrolled["id"], "status": "attended"}]}), 200)  # fmt: skip
        period = {"location_id": f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-10"}
        assert _lines(client, owner, _post(client, owner, "/payroll-runs", period)["id"])[1] == [("session", 5500)]
        assert client.delete(f"{url}/{f.type}", headers=owner).status_code == 204
        assert client.delete(f"{url}/{f.type}", headers=owner).status_code == 404
        assert _lines(client, owner, _post(client, owner, "/payroll-runs", period)["id"])[1] == [("session", 3000)]


def test_bonus_rule_shapes_and_keys(client, tenant, owner, f):
    trainer = _coach_payee(client, owner, f)
    url = f"{API}/staff-payees/{trainer['id']}/bonus-rules"
    bad = [
        {"kind": "trained_hours", "amount_minor": 1},
        {"kind": "trained_hours", "amount_minor": 1, "threshold_minutes": 60, "weekdays": [1]},
        {"kind": "off_hours", "amount_minor": 1, "weekdays": [0], "from_minute": 600, "to_minute": 600},
        {"kind": "off_hours", "amount_minor": 1, "weekdays": [7], "from_minute": 0, "to_minute": 60},
        {"kind": "off_hours", "amount_minor": 1, "from_minute": 0, "to_minute": 60},
    ]
    for rule in bad:
        assert client.put(url, headers=owner, json={"rules": [rule]}).status_code == 422, rule
    saved = ok(
        client.put(
            url,
            headers=owner,
            json={
                "rules": [
                    {
                        "kind": "off_hours",
                        "amount_minor": 300,
                        "weekdays": [5, 6, 5],
                        "from_minute": 0,
                        "to_minute": 1440,
                    }
                ]
            },
        ),
        200,
    )
    assert saved["rules"][0]["weekdays"] == [5, 6]
    assert len(ok(client.get(url, headers=owner), 200)["rules"]) == 1
    manager_email, manager_id = add_staff(tenant, "manager", location_ids=[f.location])
    manager = login(client, tenant, manager_email)
    assert client.get(url, headers=manager).status_code == 403
    assert client.put(url, headers=manager, json={"rules": []}).status_code == 403
    seller = _post(client, owner, "/staff-payees", {"kind": "salesperson", "display_name": "Sam",
                                                    "location_id": f.location, "staff_user_id": str(manager_id)})  # fmt: skip
    assert (
        client.put(f"{API}/staff-payees/{seller['id']}/bonus-rules", headers=owner, json={"rules": []}).status_code
        == 422
    )


def test_shift_publish_notifies_copy_week_and_variance(client, tenant, owner, f, mailbox):
    manager_email, _ = add_staff(tenant, "manager", location_ids=[f.location])
    manager = login(client, tenant, manager_email)
    desk_email, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    job = _hourly(client, owner, desk_id)
    mon, tue = local(f.zone, 2031, 5, 5, 10), local(f.zone, 2031, 5, 6, 10)
    first = _post(client, manager, "/shifts", {"staff_user_id": str(desk_id), "location_id": f.location,
                  "job_classification_id": job, "starts_at": mon, "ends_at": local(f.zone, 2031, 5, 5, 14)})  # fmt: skip
    second = _post(client, manager, "/shifts", {"staff_user_id": str(desk_id), "location_id": f.location,
                   "starts_at": tue, "ends_at": local(f.zone, 2031, 5, 6, 14)})  # fmt: skip
    mailbox.clear()
    ok(client.post(f"{API}/shifts/publish", headers=manager, json={"shift_ids": [first["id"], second["id"]]}), 200)
    assert [m.to for m in mailbox] == [desk_email]  # one email per employee, not per shift
    assert "Mon May 5, 10:00 to 14:00" in mailbox[0].body and "Tue May 6, 10:00 to 14:00" in mailbox[0].body
    mailbox.clear()
    ok(client.post(f"{API}/shifts/publish", headers=manager, json={"shift_ids": [first["id"]]}), 200)
    assert mailbox == [] and _events(tenant, "staff.shift.published") == 2  # nothing newly published

    # copy the week to the next: Mon and Tue come across as drafts, wall times kept; a second copy collides
    copy = {"location_id": f.location, "from_starts_on": "2031-05-05", "to_starts_on": "2031-05-12"}
    assert ok(client.post(f"{API}/shifts/copy", headers=manager, json=copy), 200) == {
        "copied_count": 2,
        "skipped_count": 0,
    }
    assert ok(client.post(f"{API}/shifts/copy", headers=manager, json=copy), 200) == {
        "copied_count": 0,
        "skipped_count": 2,
    }
    every = ok(client.get(f"{API}/shifts?location_id={f.location}&limit=50", headers=manager), 200)["data"]
    copied = [(row["status"], _utc(row["starts_at"])) for row in every if _utc(row["starts_at"]).day >= 12]
    assert copied == [("draft", _utc(local(f.zone, 2031, 5, 12, 10))), ("draft", _utc(local(f.zone, 2031, 5, 13, 10)))]
    same = client.post(f"{API}/shifts/copy", headers=manager, json=copy | {"to_starts_on": "2031-05-05"})
    assert same.status_code == 422
    desk = login(client, tenant, desk_email)
    assert client.post(f"{API}/shifts/copy", headers=desk, json=copy).status_code == 403

    # variance: Monday was worked 10:30 to 13:00 plus a punch outside the shift; Tuesday nobody came
    for start, end in ((local(f.zone, 2031, 5, 5, 9), local(f.zone, 2031, 5, 5, 10, 30)),
                       (local(f.zone, 2031, 5, 5, 10, 45), local(f.zone, 2031, 5, 5, 13))):  # fmt: skip
        _post(client, owner, "/time-entries", {"staff_user_id": str(desk_id), "location_id": f.location,
              "job_classification_id": job, "clock_in_at": start, "clock_out_at": end, "edit_reason": "Manual"})  # fmt: skip
    window = f"{API}/shifts/variance?from=2031-05-05&to=2031-05-11&location_id={f.location}"
    assert [r["state"] for r in ok(client.get(window, headers=manager), 200)] == ["upcoming"] * 2  # not yet worked
    with clock.freeze(DAY + timedelta(days=7)):
        manager = login(client, tenant, manager_email)
        rows = ok(client.get(window, headers=manager), 200)
        assert [(r["state"], r["scheduled_minutes"], r["worked_minutes"], r["variance_minutes"]) for r in rows] == [
            ("short", 240, 30 + 135, -75), ("no_show", 240, 0, -240)]  # fmt: skip
        assert _utc(rows[0]["first_in_at"]) == _utc(local(f.zone, 2031, 5, 5, 10)) and rows[1]["first_in_at"] is None
        assert client.get(window.replace("2031-05-11", "2031-09-01"), headers=manager).status_code == 422
        assert client.get(window, headers=login(client, tenant, desk_email)).status_code == 403


# --- review fixes: credits per attendee, overlapping runs, own pay, copy across the clock change -------------


def test_comp_and_completion_commission_are_decided_per_attendee(client, tenant, owner, f):
    trainer = _coach_payee(client, owner, f, pay_basis="per_attendee", comp_session_rate_minor=1000)
    ok(client.put(f"{API}/staff-payees/{trainer['id']}/commission-rules", headers=owner,
                  json={"rules": [{"applies_to": "session_completion", "commission_pct": "10"}]}), 200)  # fmt: skip
    plan = package_plan(client, owner, tenant, reservation_type_id=f.type)  # ten sessions at 100.00: 10.00 each
    gifted, bought = (new_client(client, owner, f.location)["id"] for _ in range(2))
    gift = ok(client.post(f"{API}/client-packages/complimentary", headers=owner,
                          json={"client_id": gifted, "location_id": f.location, "package_plan_id": plan["id"]}))  # fmt: skip
    paid = ok(client.post(f"{API}/client-packages", headers=owner,
                          json={"client_id": bought, "location_id": f.location, "package_plan_id": plan["id"]}))  # fmt: skip
    booked = ok(book(client, owner, f, [f.coach], at(15), at(16), kind="session",
                     session={"capacity": 2, "allows_free_booking": False}))["booking"]  # fmt: skip
    seat = booked["session"]["id"]
    places = [_post(client, owner, "/enrollments", {"session_id": seat, "client_id": person, "client_package_id": pack})
              for person, pack in ((gifted, gift["id"]), (bought, paid["id"]))]  # fmt: skip
    with clock.freeze(DAY + timedelta(days=1)):
        owner = login(client, tenant)
        ok(client.put(f"{API}/sessions/{seat}/attendance", headers=owner,
                      json={"marks": [{"enrollment_id": p["id"], "status": "attended"} for p in places]}), 200)  # fmt: skip
        period = {"location_id": f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-10"}
        both = _post(client, owner, "/payroll-runs", period)
        assert sorted(_lines(client, owner, both["id"])[1]) == [
            ("comp_session", 1000), ("session", 3000), ("session_completion_commission", 100)]  # fmt: skip
        # A commissions-only run still lists the completion commission (it is not session pay).
        only = _post(client, owner, "/payroll-runs", period | {"includes": ["commissions"]})
        assert _lines(client, owner, only["id"])[1] == [("session_completion_commission", 100)]


def test_a_second_run_never_pays_finalized_sessions_again(client, tenant, owner, f):
    _coach_payee(client, owner, f)
    booked = _session(client, owner, f, [f.coach], at(15), at(16))
    person = new_client(client, owner, f.location)
    enrolled = _post(client, owner, "/enrollments", {"session_id": booked["session"]["id"], "client_id": person["id"]})
    with clock.freeze(DAY + timedelta(days=30)):
        owner = login(client, tenant)
        ok(client.put(f"{API}/sessions/{booked['session']['id']}/attendance", headers=owner,
                      json={"marks": [{"enrollment_id": enrolled["id"], "status": "attended"}]}), 200)  # fmt: skip
        week = {"location_id": f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-07"}
        month = week | {"period_ends_on": "2031-05-30"}
        pending = _post(client, owner, "/payroll-runs", month)  # calculated before the week is finalized
        weekly = _post(client, owner, "/payroll-runs", week)
        ok(client.post(f"{API}/payroll-runs/{weekly['id']}/finalize", headers=owner), 200)
        assert _code(client.post(f"{API}/payroll-runs", headers=owner, json=month), 409) == "payroll-period-overlap"
        tenant_wide = {k: v for k, v in month.items() if k != "location_id"}
        assert (
            _code(client.post(f"{API}/payroll-runs", headers=owner, json=tenant_wide), 409) == "payroll-period-overlap"
        )
        recalc = client.post(f"{API}/payroll-runs/{pending['id']}/recalculate", headers=owner)
        assert _code(recalc, 409) == "payroll-period-overlap"
        # Commissions only, or a later period, does not pay sessions again and is allowed.
        _post(client, owner, "/payroll-runs", month | {"includes": ["commissions"]})
        _post(client, owner, "/payroll-runs", week | {"period_starts_on": "2031-05-08", "period_ends_on": "2031-05-14"})
        ok(client.post(f"{API}/payroll-runs/{weekly['id']}/void", headers=owner), 200)  # a voided run blocks nothing
        assert _lines(client, owner, _post(client, owner, "/payroll-runs", month)["id"])[1] == [("session", 3000)]


def test_a_pay_manager_below_admin_never_edits_their_own_pay(client, tenant, owner, f):
    _, coach_id = add_staff(tenant, "coach", location_ids=[f.location])
    trainer = _post(client, owner, "/staff-payees", {"kind": "trainer", "display_name": "Pat", "location_id": f.location,
                                                     "staff_user_id": str(coach_id)})  # fmt: skip
    payee_id = UUID(trainer["id"])
    self_manager = Principal(kind="staff", tenant_id=tenant.id, staff_user_id=coach_id,
                             permissions={service.PAY_MANAGE: "all"})  # a custom role below Admin  # fmt: skip
    rate = {"pay_basis": "per_session", "rate_60_minor": 9999}
    attempts = (
        lambda s: service.put_default_pay_rate(s, self_manager, payee_id, rate),
        lambda s: service.put_pay_rate_override(s, self_manager, payee_id, rate, reservation_type_id=UUID(f.type)),
        lambda s: service.delete_pay_rate_override(s, self_manager, payee_id, reservation_type_id=UUID(f.type)),
        lambda s: service.put_bonus_rules(s, self_manager, payee_id, []),
    )
    for attempt in attempts:
        with tenant_session(tenant.id, actor=self_manager) as session, pytest.raises(PermissionDenied):
            attempt(session)
    ok(client.put(f"{API}/staff-payees/{trainer['id']}/pay-rates/default", headers=owner, json=rate), 200)


def test_copying_a_shift_into_the_spring_forward_gap_skips_it(client, tenant, owner, f):
    desk_email, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    _post(client, owner, "/shifts", {"staff_user_id": str(desk_id), "location_id": f.location,
                                     "starts_at": local(f.zone, 2031, 3, 2, 2, 30),
                                     "ends_at": local(f.zone, 2031, 3, 2, 5)})  # fmt: skip
    copy = {"location_id": f.location, "from_starts_on": "2031-02-24", "to_starts_on": "2031-03-03"}
    # 02:30 on Sunday 9 March 2031 does not exist in Chicago: the copy is skipped, never moved an hour.
    assert ok(client.post(f"{API}/shifts/copy", headers=owner, json=copy), 200) == {
        "copied_count": 0,
        "skipped_count": 1,
    }


def test_own_pay_covers_commissions_relinking_and_the_calendar_column(client, tenant, owner, f):
    _, me = add_staff(tenant, "coach", location_ids=[f.location])
    _, other = add_staff(tenant, "front_desk", location_ids=[f.location])
    mine = _post(client, owner, "/staff-payees", {"kind": "trainer", "display_name": "Me coaching",
                                                  "location_id": f.location, "staff_user_id": str(me)})  # fmt: skip
    unlinked = _post(client, owner, "/staff-payees", {"kind": "trainer", "display_name": "Nobody",
                                                      "location_id": f.location})  # fmt: skip
    pay_manager = Principal(kind="staff", tenant_id=tenant.id, staff_user_id=me,
                            permissions={service.PAY_MANAGE: "all", service.PAYEE_MANAGE: "all"})  # fmt: skip
    rule = [{"applies_to": "session_completion", "commission_pct": "50"}]
    attempts = (
        lambda s: service.put_commission_rules(s, pay_manager, UUID(mine["id"]), rule),
        lambda s: service.update_payee(s, pay_manager, UUID(mine["id"]), {"staff_user_id": None}),  # unlink me
        lambda s: service.update_payee(s, pay_manager, UUID(mine["id"]), {"staff_user_id": other}),
        lambda s: service.update_payee(s, pay_manager, UUID(unlinked["id"]), {"staff_user_id": me}),  # link me
        lambda s: service.create_payee(s, pay_manager, {"kind": "salesperson", "display_name": "Me selling",
                                                        "location_id": UUID(f.location), "staff_user_id": me}),
    )  # fmt: skip
    for attempt in attempts:
        with tenant_session(tenant.id, actor=pay_manager) as session, pytest.raises(PermissionDenied):
            attempt(session)
    # Unlinked from the payee row by an admin, the trainer's calendar column is still mine.
    ok(client.patch(f"{API}/staff-payees/{mine['id']}", headers=owner, json={"staff_user_id": None}), 200)
    with tenant_session(tenant.id, actor=pay_manager) as session, pytest.raises(PermissionDenied):
        service.put_default_pay_rate(session, pay_manager, UUID(mine["id"]), {"pay_basis": "per_session"})
    with tenant_session(tenant.id, actor=pay_manager) as session:  # someone else's pay is fine
        service.put_default_pay_rate(session, pay_manager, UUID(unlinked["id"]), {"pay_basis": "per_session"})


def test_year_one_dates_are_a_422_not_a_500(client, owner):
    """Dates far outside any payroll period (year 1) overflowed the local-midnight arithmetic: a 500."""
    summary = client.get(f"{API}/time-entries/summary?from=0001-01-01&to=0001-01-02", headers=owner)
    assert summary.status_code == 422, summary.text
    run = client.post(f"{API}/payroll-runs", headers=owner,
                      json={"period_starts_on": "0001-01-01", "period_ends_on": "0001-01-07"})  # fmt: skip
    assert run.status_code == 422, run.text
