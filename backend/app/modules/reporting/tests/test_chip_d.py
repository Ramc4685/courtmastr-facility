"""Phase 12 chip D reports (staff, fitness, leagues, app, operations) over two locations in different zones: Main
(Chicago) and North (New York). 05:30 UTC on 8 March 2026 is still the 7th in Chicago and already the 8th in
New York, so each test puts a record at that instant in both and expects it on each location's own day."""
# ruff: noqa: F811  (pytest fixtures imported from test_reporting are redefined as parameters)

from datetime import UTC, datetime
from uuid import uuid4

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import platform
from app.modules.engagement.models import DeviceRegistration
from app.modules.platform.models import Identity
from app.modules.reporting.reports import fitness, operations, staff
from app.modules.reporting.tests.test_reporting import (  # noqa: F401 (fixtures)
    API,
    IN_2030,
    IN_2031,
    _location,
    ok,
    ran,
    rows,
    same_day_everywhere,
    world,
)
from conftest import add_staff, login, new_client

CHIP_D = [s.key for family in (staff.SPECS, fitness.SPECS, operations.SPECS) for s in family]
EDGE = datetime(2026, 3, 8, 5, 30, tzinfo=UTC)


def _params(key: str, definition: dict) -> dict:
    if key in IN_2030:
        return {"from_on": "2030-01-01", "to_on": "2030-12-31"}
    if key in IN_2031:
        return {"from_on": "2031-01-01", "to_on": "2031-06-30"}
    if "period" in definition["params_schema"]["properties"]:
        return {"period": "last_30_days"}
    return {}


def post(client, headers, path, body, status=201):
    return ok(client.post(f"{API}{path}", headers=headers, json=body), status)


def test_every_chip_d_report_keeps_to_the_locations_asked_for(client, tenant):
    """populate() fills Main; a New York location with nothing in it must see none of Main's rows."""
    from conftest import populate

    world_ = populate(client, tenant)
    north = _location(client, world_.headers, "North", "America/New_York")
    definitions = {d["key"]: d for d in ok(client.get(f"{API}/report-definitions", headers=world_.headers))["data"]}
    leaked, empty = {}, []
    for key in CHIP_D:
        params = _params(key, definitions[key])
        if not ran(client, world_.headers, key, **params)["row_count"]:
            empty.append(key)
        got = ran(client, world_.headers, key, location_ids=[north], **params)
        if got["row_count"]:
            leaked[key] = got["row_count"]
    assert not empty and not leaked, (empty, leaked)


def test_time_entries_and_payroll_count_on_each_location_s_own_day(client, tenant, owner, world):
    workers = {
        location: str(add_staff(tenant, "front_desk", all_locations=True)[1]) for location in (world.main, world.north)
    }
    job = post(client, owner, "/job-classifications", {"name": "Desk"})
    for location, worker in workers.items():
        post(client, owner, f"/staff-users/{worker}/hourly-rates",
             {"job_classification_id": job["id"], "rate_minor": 1500, "effective_from_on": "2020-01-01"})  # fmt: skip
        post(client, owner, "/time-entries", {
            "staff_user_id": worker, "location_id": location, "job_classification_id": job["id"],
            "clock_in_at": EDGE.isoformat(), "clock_out_at": EDGE.replace(hour=7).isoformat(), "edit_reason": "Missed",
        })  # fmt: skip
    eighth = ran(client, owner, "time_entries", from_on="2026-03-08", to_on="2026-03-08", group_by="day")
    seventh = ran(client, owner, "time_entries", from_on="2026-03-07", to_on="2026-03-07", group_by="staff_day")
    assert (eighth["totals"]["entry_count"], eighth["totals"]["minutes"], seventh["totals"]["entry_count"]) == (
        1,
        120,
        1,
    )
    assert [r["label"] for r in rows(client, owner, eighth["id"])["data"]] == ["2026-03-08"]
    assert rows(client, owner, seventh["id"])["data"][0]["label"].endswith("2026-03-07")
    assert eighth["totals"]["unpaid_count"] == 1 and eighth["totals"]["paid_minutes"] == 0

    # A payroll run at Main over the 7th takes Main's entry (in payroll, 2 h paid); North's stays unpaid.
    assert client.put(f"{API}/staff-settings", headers=owner, json={"pay_period": "biweekly"}).status_code == 200
    post(client, owner, "/payroll-runs", {"location_id": world.main, "period_starts_on": "2026-03-01",
                                          "period_ends_on": "2026-03-07"})  # fmt: skip
    both = ran(client, owner, "time_entries", from_on="2026-03-07", to_on="2026-03-08")
    states = [rows(client, owner, both["id"], group_key=workers[at])["data"][0]["pay_status"] for at in workers]
    assert states == ["in_payroll", "unpaid"] and both["totals"]["paid_minutes"] == 120
    pay = ran(client, owner, "payroll_statements", from_on="2026-03-01", to_on="2026-03-07")
    statement = next(r for r in rows(client, owner, pay["id"])["data"] if r["hourly_pay_minor"])
    assert (statement["hourly_pay_minor"], statement["run_status"]) == (3000, "calculated")
    lines = rows(client, owner, pay["id"], group_key=statement["group_key"])["data"]
    assert [(line["kind"], line["quantity"]) for line in lines] == [("hourly", 2.0)]
    north = ran(
        client, owner, "payroll_statements", from_on="2026-03-01", to_on="2026-03-07", location_ids=[world.north]
    )
    assert north["row_count"] == 0
    assert ran(client, owner, "payroll_statements", from_on="2026-03-01", to_on="2026-03-07",
               finalized_only=True)["row_count"] == 0  # fmt: skip


def test_assessment_history_and_summary_on_local_days(client, tenant, owner, world):
    template = post(client, owner, "/assessment-templates", {"name": "Body composition"})
    weight = post(client, owner, f"/assessment-templates/{template['id']}/fields",
                  {"name": "Weight", "decimal_places": 1, "unit_label": "kg", "better_direction": "lower"})  # fmt: skip
    other = new_client(client, owner, world.north)["id"]
    for person, location, at, value in (
        (world.person, world.main, "2026-03-01T15:00:00Z", "80.0"),
        (world.person, world.north, EDGE.isoformat(), "76.5"),  # the 8th in New York
        (other, world.main, EDGE.isoformat(), "90.0"),  # the 7th in Chicago
        (other, world.main, "2026-03-02T15:00:00Z", "88.0"),
    ):
        post(client, owner, "/assessment-results", {"client_id": person, "location_id": location, "recorded_at": at,
                                                     "values": [{"assessment_field_id": weight["id"], "value": value}]})  # fmt: skip
    eighth = ran(client, owner, "assessment_history", from_on="2026-03-08", to_on="2026-03-08")
    assert eighth["totals"] == {"client_count": 1, "value_count": 1}
    week = ran(client, owner, "assessment_history", from_on="2026-03-01", to_on="2026-03-08", client_ids=[world.person])
    [mine] = rows(client, owner, week["id"])["data"]
    assert (mine["first_value"], mine["last_value"], mine["change"], mine["best_value"]) == (80.0, 76.5, -3.5, 76.5)
    assert [d["value"] for d in rows(client, owner, week["id"], group_key=mine["group_key"])["data"]] == [80.0, 76.5]

    summary = ran(client, owner, "assessment_summary", from_on="2026-03-01", to_on="2026-03-08")
    [field] = rows(client, owner, summary["id"])["data"]
    # the other client went 88 -> 90 (worse); ours 80 -> 76.5 (better, weight is lower-is-better)
    assert (field["client_count"], field["compared_count"], field["improved_count"], field["improved_pct"]) == (
        2, 2, 1, 50.0)  # fmt: skip
    assert (field["min_value"], field["max_value"], field["average_change"]) == (76.5, 90.0, -0.8)
    north = ran(
        client, owner, "assessment_summary", from_on="2026-03-01", to_on="2026-03-08", location_ids=[world.north]
    )
    assert north["totals"]["value_count"] == 1


def test_app_installs_count_on_each_location_s_own_day(client, tenant, owner, world):
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        for location, platform_ in ((world.main, "ios"), (world.north, "android")):
            identity = Identity(kind="client", email=f"app-{uuid4().hex[:8]}@example.com", status="active")
            session.add(identity)
            session.flush()
            session.add(DeviceRegistration(
                identity_id=identity.id, client_id=new_client(client, owner, location)["id"], location_id=location,
                platform=platform_, push_token=f"tok-{uuid4().hex}", app_version="2.1.0", created_at=EDGE,
                last_active_at=EDGE,
            ))  # fmt: skip
    eighth = ran(client, owner, "app_devices", from_on="2026-03-08", to_on="2026-03-08")
    found = {r["platform"]: r["registered_count"] for r in rows(client, owner, eighth["id"])["data"]}
    assert found == {"android": 1, "ios": 0}
    assert eighth["totals"]["installed_count"] == 2  # North's of the 8th and Main's of the 7th
    seventh = ran(client, owner, "app_devices", from_on="2026-03-07", to_on="2026-03-07")
    assert (seventh["totals"]["registered_count"], seventh["totals"]["installed_count"]) == (1, 1)


def test_operations_reports_use_local_time_and_trainers_see_only_themselves(client, tenant):
    """populate()'s Coach Kim is open Monday and Wednesday 09:00-12:00 from 2030 and runs a 09:00 Monday clinic
    (15:00 UTC, Chicago) three weeks running from 4 March 2030."""
    from conftest import populate

    world_ = populate(client, tenant)
    week = {"from_on": "2030-03-04", "to_on": "2030-03-10"}
    used = ran(client, world_.headers, "resource_utilization", resource_kinds=["trainer"], **week)
    coach = next(r for r in rows(client, world_.headers, used["id"])["data"] if r["resource_name"] == "Coach Kim")
    assert coach["open_hours"] == 6.0 and coach["held_hours"] >= 1
    peak = ran(client, world_.headers, "peak_times", **week)
    assert any(r["weekday"] == "Monday" and r["hour"] == "09:00" and r["booking_count"]
               for r in rows(client, world_.headers, peak["id"])["data"])  # fmt: skip
    assert ran(client, world_.headers, "class_popularity", **week)["totals"]["session_count"] >= 1

    linked_email, linked = add_staff(tenant, "coach", all_locations=True)
    loose_email, _ = add_staff(tenant, "coach", all_locations=True)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        platform.service.set_linked_resource(session, linked, world_.trainer_resource_id)
    year = {"from_on": "2030-01-01", "to_on": "2030-12-31"}
    mine = ran(client, login(client, tenant, linked_email), "trainer_performance", **year)
    assert [r["trainer"] for r in rows(client, login(client, tenant, linked_email), mine["id"])["data"]] == [
        "Coach Kim"
    ]
    assert ran(client, login(client, tenant, loose_email), "trainer_performance", **year)["row_count"] == 0
    pay = ran(client, login(client, tenant, linked_email), "payroll_statements", period="last_30_days")
    assert {r["payee_name"] for r in rows(client, login(client, tenant, linked_email), pay["id"])["data"]} <= {
        "Coach Kim"
    }
    assert (
        ran(client, login(client, tenant, loose_email), "payroll_statements", period="last_30_days")["row_count"] == 0
    )
    denied = client.post(f"{API}/report-runs", headers=login(client, tenant, linked_email),
                         json={"report_key": "resource_utilization", "params": week})  # fmt: skip
    assert denied.status_code == 403, denied.text
