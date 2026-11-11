"""staff (build module 12): payees, pay and commission rules, the time clock, manager entries, shifts,
instructor assignment and payroll runs, each through the API with both permission gates and location scope."""

from datetime import timedelta
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
