"""Court use (`court_use`, `court_use_heatmap`): available time from opening hours, court windows and closures in
the location's zone; holds on halves counted once; changeover, blocks and league use apart from rented play;
peak bands read from the rate rules; revenue per court-hour. Every expected figure is worked out by hand below.

The facility (scheduling test helper): Court 1 with halves 1A and 1B (1A has a quarter) and Court 2, in Chicago.
Monday 5 May 2031: open 08:00-20:00, closed 08:00-09:00 for cleaning, so Court 1 has 11 hours. Court 2 has its own
window, Mondays 10:00-14:00 (4 hours). "Court hire" costs 40.00 an hour, 50.00 from 17:00 (peak: dearer than the
base) and 30.00 before 10:00 (cheaper: not peak), with 15-minute changeovers either side."""

from datetime import UTC, date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import billing
from app.modules.reporting.tests.test_reporting import ran, rows
from app.modules.scheduling.tests.helpers import API, book, facility, ok
from conftest import add_staff, login, new_client

ZONE = ZoneInfo("America/Chicago")
MONDAY = date(2031, 5, 5)


def at(day: date, hhmm: str) -> str:
    return datetime.combine(day, time.fromisoformat(hhmm), ZONE).astimezone(UTC).isoformat().replace("+00:00", "Z")


def hours(open_: str, close: str) -> dict:
    return {"opens_time": open_, "closes_time": close, "is_closed": False}


@pytest.fixture
def f(client, owner, tenant):
    f = facility(client, owner)
    week = {1: hours("08:00", "20:00"), 7: hours("00:00", "24:00")}
    ok(client.put(f"{API}/locations/{f.location}/facility-hours", headers=owner, json={
        "days": [{"weekday": d} | week.get(d, hours("06:00", "22:00")) for d in range(1, 8)]}), 200)  # fmt: skip
    ok(client.post(f"{API}/resources/{f.court2}/availability-windows", headers=owner, json={
        "starts_on": "2031-01-06", "weekdays": [1], "start_time": "10:00", "end_time": "14:00"}))  # fmt: skip
    ok(client.post(f"{API}/blackouts", headers=owner, json={
        "location_id": f.location, "name": "Cleaning", "starts_at": at(MONDAY, "08:00"), "ends_at": at(MONDAY, "09:00")}))  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        category = billing.service.create_revenue_category(session, code="RENT", label="Rentals")
        f.category = str(category.id)
    f.rtype = ok(client.post(f"{API}/rental-types", headers=owner, json={
        "location_id": f.location, "name": "Court hire", "revenue_category_id": f.category,
        "resource_ids": [f.court, f.half_a, f.half_b, f.court2], "buffer_before_min": 15, "buffer_after_min": 15,
        "slot_granularity_min": 30,
    }))["id"]  # fmt: skip
    f.rate = ok(client.post(f"{API}/rental-types/{f.rtype}/rates", headers=owner, json={
        "name": "Standard", "amount_minor": 4000, "basis": "per_hour", "rules": [
            {"kind": "rate", "name": "Evening", "start_time": "17:00", "end_time": "24:00", "amount_minor": 5000},
            {"kind": "rate", "name": "Early", "start_time": "06:00", "end_time": "10:00", "amount_minor": 3000},
        ]}))["id"]  # fmt: skip
    f.person = new_client(client, owner, f.location)["id"]
    f.rent = lambda resource, day, start, end: ok(client.post(f"{API}/rentals", headers=owner | {"Idempotency-Key": uuid4().hex}, json={
        "location_id": f.location, "rental_type_id": f.rtype, "client_id": f.person, "resources": [{"resource_id": resource}],
        "starts_at": at(day, start), "ends_at": at(day, end), "charge": {"decision": "bill", "rental_rate_id": f.rate},
    }))  # fmt: skip
    f.rent(f.half_a, MONDAY, "10:00", "11:00")  # both halves at once: Court 1 is in use for one hour, not two
    f.rent(f.half_b, MONDAY, "10:00", "11:00")
    f.rent(f.court, MONDAY, "16:30", "17:30")  # the whole court, half of it in the peak band
    f.rent(f.court2, MONDAY, "13:00", "14:00")  # its after-changeover runs past Court 2's window
    ok(book(client, owner, f, [f.court], at(MONDAY, "19:00"), at(MONDAY, "20:30"), kind="session"))  # past closing
    ok(book(client, owner, f, [f.half_a], at(MONDAY, "12:00"), at(MONDAY, "13:00")))  # maintenance block
    return f


def report(client, headers, key: str, f, **params) -> tuple[dict, list[dict]]:
    run = ran(client, headers, key, location_ids=[f.location], **params)
    return run, rows(client, headers, run["id"], limit=200)["data"]


def by_label(found: list[dict]) -> dict:
    return {r["label"]: r for r in found}


def test_a_day_per_court_against_opening_hours_windows_and_closures(client, owner, f):
    run, found = report(client, owner, "court_use", f, from_on=MONDAY.isoformat(), to_on=MONDAY.isoformat())
    court1, court2 = by_label(found)["Court 1"], by_label(found)["Court 2"]
    # Court 1: 08:00-20:00 less the 08:00-09:00 closure = 11 h; peak 17:00-20:00 = 3 h. Rented 10-11 (both halves,
    # once) and 16:30-17:30 = 2 h; the clinic 19:00-20:00 = 1 h inside, 20:00-20:30 outside the hours. Changeover:
    # 09:45-10:00, 11:00-11:15, 16:15-16:30, 17:30-17:45 = 1 h. Block 12-13 = 1 h. Played 3 of 11 h = 27.3%.
    # Peak played 17:00-17:30 and 19:00-20:00 = 1.5 of 3 h = 50%; off-peak 1.5 of 8 h = 18.75%, half up 18.8%.
    assert {k: court1[k] for k in ("hours_source", "available_hours", "played_hours", "utilization_pct",
                                   "rental_hours", "program_hours", "buffer_hours", "blocked_hours", "outside_hours",
                                   "peak_available_hours", "peak_played_hours", "peak_utilization_pct",
                                   "offpeak_utilization_pct")} == {
        "hours_source": "Opening hours", "available_hours": 11.0, "played_hours": 3.0, "utilization_pct": 27.3,
        "rental_hours": 2.0, "program_hours": 1.0, "buffer_hours": 1.0, "blocked_hours": 1.0, "outside_hours": 0.5,
        "peak_available_hours": 3.0, "peak_played_hours": 1.5, "peak_utilization_pct": 50.0,
        "offpeak_utilization_pct": 18.8,
    }  # fmt: skip
    # Revenue: 40.00 + 40.00 (10-11) + 20.00 + 25.00 (half an hour at each rate) = 125.00; the peak share of the
    # 16:30 booking is half its minutes, 22.50. Per available hour 125.00 / 11 = 11.36; per rented hour 62.50.
    assert (court1["revenue_minor"], court1["peak_revenue_minor"], court1["offpeak_revenue_minor"]) == (
        12500,
        2250,
        10250,
    )
    assert (court1["revenue_per_available_hour_minor"], court1["revenue_per_sold_hour_minor"]) == (1136, 6250)
    # Court 2: its window 10:00-14:00 inside the hours = 4 h, no peak; rented 1 h; changeover 12:45-13:00 inside.
    assert court2["hours_source"] == "Court windows" and court2["period_on"] == MONDAY.isoformat()
    assert (court2["available_hours"], court2["played_hours"], court2["utilization_pct"], court2["buffer_hours"]) == (
        4.0,
        1.0,
        25.0,
        0.25,
    )
    assert (court2["peak_available_hours"], court2["peak_utilization_pct"], court2["offpeak_utilization_pct"]) == (
        0.0,
        None,
        25.0,
    )
    assert (
        court2["revenue_minor"],
        court2["revenue_per_available_hour_minor"],
        court2["revenue_per_sold_hour_minor"],
    ) == (4000, 1000, 4000)
    totals = run["totals"]  # 15 h available, 4 h played (26.67%), 165.00
    assert (totals["available_hours"], totals["played_hours"], totals["utilization_pct"]) == (15.0, 4.0, 26.7)
    assert (totals["buffer_hours"], totals["revenue_minor"], totals["revenue_per_sold_hour_minor"]) == (
        1.25,
        16500,
        5500,
    )
    assert totals["offpeak_utilization_pct"] == 20.8  # 2.5 of 12 h


def test_groups_and_sports(client, owner, f):
    day = {"from_on": MONDAY.isoformat(), "to_on": MONDAY.isoformat()}
    run, [group] = report(client, owner, "court_use", f, group_by="court_group", **day)
    assert (group["label"], group["hours_source"], group["available_hours"], group["played_hours"]) == (
        "Courts",
        "Mixed",
        15.0,
        4.0,
    )
    _, found = report(client, owner, "court_use", f, group_by="sport", **day)
    hire, league = by_label(found)["Court hire"], by_label(found)["League and programs"]
    # Court hire is offered on both courts (15 h, 3 h peak): rented 3 h = 20%, peak 0.5 of 3 h = 16.7%.
    assert (hire["available_hours"], hire["played_hours"], hire["rental_hours"], hire["utilization_pct"]) == (
        15.0,
        3.0,
        3.0,
        20.0,
    )
    assert (hire["peak_utilization_pct"], hire["buffer_hours"], hire["revenue_minor"]) == (16.7, 1.25, 16500)
    assert (
        league["available_hours"],
        league["program_hours"],
        league["utilization_pct"],
        league["peak_utilization_pct"],
    ) == (15.0, 1.0, 6.7, 33.3)
    assert league["outside_hours"] == 0.5 and league["revenue_minor"] == 0
    _, [only] = report(client, owner, "court_use", f, resource_ids=[f.court2], **day)
    assert only["label"] == "Court 2"


def test_a_month_is_the_sum_of_its_days(client, owner, f):
    f.rent(f.court, date(2031, 5, 12), "18:00", "19:00")
    month = {"from_on": "2031-05-01", "to_on": "2031-05-31"}
    _, days = report(client, owner, "court_use", f, **month)
    _, months = report(client, owner, "court_use", f, grain="month", **month)
    assert len(days) == 62 and {r["period_on"] for r in months} == {"2031-05-01"}
    for court in ("Court 1", "Court 2"):
        daily = [r for r in days if r["label"] == court]
        monthly = by_label(months)[court]
        for k in ("available_hours", "played_hours", "buffer_hours", "peak_available_hours", "peak_played_hours"):
            assert sum(round(r[k] * 60) for r in daily) == round(monthly[k] * 60), (court, k)
        for k in ("revenue_minor", "peak_revenue_minor"):
            assert sum(r[k] for r in daily) == monthly[k], (court, k)
    assert by_label(months)["Court 1"]["revenue_minor"] == 12500 + 5000  # the 12 May hour is at the evening rate
    _, weeks = report(client, owner, "court_use", f, grain="week", **month)
    assert {r["period_on"] for r in weeks} == {"2031-04-28", "2031-05-05", "2031-05-12", "2031-05-19", "2031-05-26"}


@pytest.mark.parametrize(("day", "expected"), [(date(2031, 3, 9), 23.0), (date(2031, 11, 2), 25.0)])
def test_a_24_hour_sunday_across_a_clock_change(client, owner, f, day, expected):
    _, found = report(client, owner, "court_use", f, from_on=day.isoformat(), to_on=day.isoformat())
    court1, court2 = by_label(found)["Court 1"], by_label(found)["Court 2"]
    assert court1["available_hours"] == expected and court1["hours_source"] == "Opening hours"
    assert court2["available_hours"] == 0.0 and court2["utilization_pct"] is None  # its window is Mondays only


def test_heatmap_by_hour_and_weekday(client, owner, f):
    run, found = report(client, owner, "court_use_heatmap", f, from_on=MONDAY.isoformat(), to_on=MONDAY.isoformat())
    cells = {r["hour"]: r for r in found}
    # 08:00 is closed for cleaning and 20:00 is after closing: never open, left out.
    assert list(cells) == [f"{h:02d}:00" for h in range(9, 20)]
    assert cells["10:00"]["monday_pct"] == 50.0  # Court 1 played, Court 2 open and idle
    assert cells["13:00"]["monday_pct"] == 50.0  # the reverse
    assert cells["17:00"]["monday_pct"] == 50.0  # Court 1 alone, half an hour of play
    assert cells["19:00"]["monday_pct"] == 100.0 and cells["09:00"]["monday_pct"] == 0.0
    assert cells["10:00"]["tuesday_pct"] is None and run["totals"]["utilization_pct"] == 26.7


def test_permissions_and_location_scope(client, owner, tenant, f):
    desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    day = {"location_ids": [f.location], "from_on": MONDAY.isoformat(), "to_on": MONDAY.isoformat()}
    response = client.post(f"{API}/report-runs", headers=desk, json={"report_key": "court_use", "params": day})
    assert response.status_code == 403  # revenue: the financial family
    assert ran(client, desk, "court_use_heatmap", **day)["row_count"] == 11
    north = ok(client.post(f"{API}/locations", headers=owner, json={
        "name": "North", "time_zone": "America/New_York", "country_code": "US"}))["id"]  # fmt: skip
    assert (
        ran(client, owner, "court_use", location_ids=[north], from_on=day["from_on"], to_on=day["to_on"])["row_count"]
        == 0
    )
    elsewhere = login(client, tenant, add_staff(tenant, "manager", location_ids=[north])[0])
    hidden = client.post(f"{API}/report-runs", headers=elsewhere, json={"report_key": "court_use", "params": day})
    assert hidden.status_code == 404
    assert ran(client, elsewhere, "court_use", from_on=day["from_on"], to_on=day["to_on"])["row_count"] == 0
