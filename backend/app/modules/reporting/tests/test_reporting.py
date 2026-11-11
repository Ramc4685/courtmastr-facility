"""reporting (build module 15): the report centre and the P0 reports, through the API with both gates, against
real billing data, plus the view contract and the pure date, aging and CSV rules."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dramatiq import Worker
from sqlalchemy import text, update

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.jobs import broker
from app.modules import billing
from app.modules.reporting import views
from app.modules.reporting.domain import csv_file, periods
from app.modules.reporting.models import ReportRun
from conftest import add_staff, login, new_client

API = "/api/v1"
NOON = datetime(2026, 1, 5, 18, 0, tzinfo=UTC)  # noon in Chicago


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def code(response, status):
    assert response.status_code == status, response.text
    return response.json()["code"]


def drain() -> None:
    worker = Worker(broker, worker_timeout=100)
    worker.start()
    try:
        broker.join("default", fail_fast=True, timeout=60_000)
        worker.join()
    finally:
        worker.stop()


def _location(client, owner, name, zone="America/Chicago"):
    body = {"name": name, "time_zone": zone, "country_code": "US"}
    return ok(client.post(f"{API}/locations", headers=owner, json=body), 201)["id"]


def _sale(client, headers, person, location_id, category_id, price, *, pay=True):
    item = {"client_id": person, "location_id": location_id, "description": "Court hire", "unit_price_minor": price,
            "revenue_category_id": category_id}  # fmt: skip
    charge = ok(client.post(f"{API}/charges", headers=headers, json=item), 201)
    invoice = ok(client.post(f"{API}/invoices", headers=headers, json={"charge_ids": [charge["id"]]}), 201)
    if pay:
        _pay(client, headers, person, location_id, invoice["id"], charge["total_minor"])
    return charge, invoice


def _pay(client, headers, person, location_id, invoice_id, amount):
    body = {"client_id": person, "location_id": location_id, "amount_minor": amount, "tender_kind": "card",
            "method_token": "tok_card_ok", "invoice_id": invoice_id}  # fmt: skip
    return ok(client.post(f"{API}/payments", headers=headers | {"Idempotency-Key": uuid4().hex}, json=body), 201)


@pytest.fixture
def world(client, tenant, owner):
    main, north = _location(client, owner, "Main"), _location(client, owner, "North", "America/New_York")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        tax = billing.service.create_tax(
            session, code="ST", label="Sales tax", rate=Decimal("0.10"), effective_from_on=date(2020, 1, 1)
        )
        category = str(
            billing.service.create_revenue_category(session, code="RENT", label="Rentals", tax_ids=[tax.id]).id
        )
    person = new_client(client, owner, main)["id"]
    main_charge, _ = _sale(client, owner, person, main, category, 2000)
    north_charge, _ = _sale(client, owner, person, north, category, 7000)
    return SimpleNamespace(main=main, north=north, category=category, person=person, main_charge=main_charge,
                           north_charge=north_charge)  # fmt: skip


def run(client, headers, key, status=200, **params):
    return client.post(f"{API}/report-runs", headers=headers, json={"report_key": key, "params": params}), status


def ran(client, headers, key, **params) -> dict:
    response, status = run(client, headers, key, **params)
    return ok(response, status)


def rows(client, headers, run_id, **query) -> dict:
    return ok(client.get(f"{API}/report-runs/{run_id}/rows", headers=headers, params=query))


# --- the read models -----------------------------------------------------------------------------------------


def test_views_match_their_column_contract_and_run_as_the_invoker(tenant):
    with tenant_session(tenant.id) as session:
        for view in views.ALL:
            found = session.scalars(text(
                "SELECT attname FROM pg_attribute WHERE attrelid = CAST(:v AS regclass) AND attnum > 0 "
                "AND NOT attisdropped ORDER BY attnum"
            ), {"v": view.name}).all()  # fmt: skip
            assert [c for c in found if c != "tenant_id"] == [c.name for c in view.columns], view.name
            options = session.scalar(text("SELECT reloptions FROM pg_class WHERE oid = CAST(:v AS regclass)"),
                                     {"v": view.name})  # fmt: skip
            assert "security_invoker=true" in options, view.name  # RLS of the base tables applies to fh_app


# --- catalogue -----------------------------------------------------------------------------------------------


def test_catalogue_lists_only_what_the_caller_may_run(client, tenant, owner):
    everything = ok(client.get(f"{API}/report-definitions", headers=owner))["data"]
    assert len(everything) == 10 and all(d["params_schema"]["properties"] for d in everything)
    financial = ok(client.get(f"{API}/report-definitions?category=financial", headers=owner))["data"]
    assert {d["key"] for d in financial} == {"revenue_summary", "deposits", "invoices", "open_invoices"}
    desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    assert {d["key"] for d in ok(client.get(f"{API}/report-definitions", headers=desk))["data"]} == {
        "attendance",
        "attendance_overview",
    }
    assert code(client.get(f"{API}/report-definitions/revenue_summary", headers=desk), 403) == "permission-denied"
    assert code(client.get(f"{API}/report-definitions/nope", headers=owner), 404) == "not-found"
    assert ok(client.get(f"{API}/report-definitions/deposits", headers=owner))["date_basis"] == "payment_date"


# --- financial reports ---------------------------------------------------------------------------------------


def test_revenue_and_deposits_total_in_minor_units_with_drill_down(client, owner, world):
    revenue = ran(client, owner, "revenue_summary", period="last_30_days", goal_minor=10_000)
    totals = revenue["totals"]
    net = 2000 + 7000
    assert (totals["net_minor"], totals["tax_minor"], totals["total_minor"]) == (net, 900, 9900)
    assert totals["goal_pct"] == 90.0 and totals["payments_received_minor"] == 9900
    page = rows(client, owner, revenue["id"])
    assert page["data"][0]["share_pct"] == 100.0 and page["columns"][0]["key"] == "revenue_category"
    group = page["data"][0]["group_key"]
    detail = rows(client, owner, revenue["id"], group_key=group, sort="-net_minor", limit=1)
    assert [d["net_minor"] for d in detail["data"]] == [7000] and detail["page"]["has_more"]
    following = rows(
        client, owner, revenue["id"], group_key=group, sort="-net_minor", cursor=detail["page"]["next_cursor"]
    )
    assert [d["net_minor"] for d in following["data"]] == [2000] and not following["page"]["has_more"]

    north = ran(client, owner, "revenue_summary", period="last_30_days", location_ids=[world.north])
    assert north["totals"]["net_minor"] == 7000 and north["params"]["location_ids"] == [world.north]
    deposits = ran(client, owner, "deposits", period="last_30_days")
    assert (deposits["totals"]["received_minor"], deposits["totals"]["net_minor"]) == (9900, 9900)
    assert rows(client, owner, deposits["id"])["data"][0]["tender_kind"] == "card"


def test_invoices_and_open_invoices_cut_at_the_end_of_the_as_of_day(client, tenant, world):
    day = lambda n: NOON + timedelta(days=n)  # noqa: E731
    with clock.freeze(day(0)):
        headers = login(client, tenant)
        charge, invoice = _sale(client, headers, world.person, world.main, world.category, 500, pay=False)
    with clock.freeze(day(2)):
        headers = login(client, tenant)
        _pay(client, headers, world.person, world.main, invoice["id"], charge["total_minor"])
        listing = ran(client, headers, "invoices", from_on="2026-01-05", to_on="2026-01-05")
        assert [r["number"] for r in rows(client, headers, listing["id"])["data"]] == [invoice["number"]]
        before = ran(client, headers, "open_invoices", as_of_on="2026-01-06")
        after = ran(client, headers, "open_invoices", as_of_on="2026-01-07")  # paid on the 7th: counts that day
    assert before["totals"]["balance_minor"] == charge["total_minor"] and before["params"]["as_of_on"] == "2026-01-06"
    assert after["totals"]["balance_minor"] == 0 and after["row_count"] == 0


def test_relative_periods_resolve_in_the_location_time_zone(client, tenant, world):
    # 05:30 UTC on 8 March: still the 7th in Chicago, already the 8th in New York.
    with clock.freeze(datetime(2026, 3, 8, 5, 30, tzinfo=UTC)):
        headers = login(client, tenant)
        chicago = ran(client, headers, "deposits", period="today", location_ids=[world.main])
        new_york = ran(client, headers, "deposits", period="today", location_ids=[world.north])
        both = ran(client, headers, "deposits", period="today")
    assert chicago["params"]["from_on"] == "2026-03-07" and new_york["params"]["from_on"] == "2026-03-08"
    assert both["params"]["from_on"] == "2026-03-07"  # the location furthest behind


def test_parameters_are_validated_with_a_pointer(client, owner, world):
    def pointer(**params):
        response, _ = run(client, owner, "deposits", **params)
        assert response.status_code == 422, response.text
        return response.json()["errors"][0]["pointer"]

    assert pointer(period="fortnight") == "/params/period"
    assert pointer(from_on="2026-02-01", to_on="2026-01-01") == "/params/to_on"
    assert pointer(from_on="2025-01-01", to_on="2026-01-02") == "/params/to_on"
    assert pointer(colour="blue") == "/params/colour"
    assert code(run(client, owner, "nope")[0], 404) == "not-found"


# --- scope and ownership -------------------------------------------------------------------------------------


def test_location_scope_is_404_outside_and_filters_before_aggregation(client, tenant, world):
    manager = login(client, tenant, add_staff(tenant, "manager", location_ids=[world.main])[0])
    assert code(run(client, manager, "revenue_summary", location_ids=[world.north])[0], 404) == "not-found"
    mine = ran(client, manager, "revenue_summary", period="last_30_days")
    assert mine["totals"]["net_minor"] == 2000 and mine["params"]["location_ids"] == [world.main]


def test_runs_belong_to_their_requester(client, tenant, owner, world):
    mine = ran(client, owner, "deposits", period="last_30_days")
    other = login(client, tenant, add_staff(tenant, "admin", all_locations=True)[0])
    assert code(client.get(f"{API}/report-runs/{mine['id']}", headers=other), 404) == "not-found"
    assert code(client.get(f"{API}/report-runs/{mine['id']}/rows", headers=other), 404) == "not-found"
    assert ok(client.get(f"{API}/report-runs", headers=other))["data"] == []
    listed = ok(client.get(f"{API}/report-runs?report_key=deposits", headers=owner))["data"]
    assert [r["id"] for r in listed] == [mine["id"]]


def test_coaches_see_only_their_own_sessions_and_no_other_family(client, tenant, world):
    coach = login(client, tenant, add_staff(tenant, "coach", all_locations=True)[0])
    attendance = ran(client, coach, "attendance", period="last_30_days")
    assert attendance["row_count"] == 0  # no linked trainer resource: nothing is theirs
    assert code(run(client, coach, "time_clock", period="last_30_days")[0], 403) == "permission-denied"
    assert code(run(client, coach, "deposits")[0], 403) == "permission-denied"
    # a run built with every row (reach since narrowed to own) is no longer theirs to read
    with tenant_session(tenant.id) as session:
        built = session.get(ReportRun, attendance["id"])
        built.params = {**built.params, "scope": {"own_only": False, "own_resource_id": None}}
    assert code(client.get(f"{API}/report-runs/{attendance['id']}/rows", headers=coach), 404) == "not-found"


def test_expired_results_are_gone(client, tenant, owner, world):
    done = ran(client, owner, "deposits", period="last_30_days")
    with tenant_session(tenant.id) as session:
        session.execute(update(ReportRun).values(expires_at=clock.now() - timedelta(seconds=1)))
    assert ok(client.get(f"{API}/report-runs/{done['id']}", headers=owner))["status"] == "expired"
    assert code(client.get(f"{API}/report-runs/{done['id']}/rows", headers=owner), 404) == "not-found"
    response = client.post(f"{API}/export-jobs", headers=owner, json={"report_run_id": done["id"]})
    assert code(response, 409) == "invalid-state-transition"


# --- saved reports -------------------------------------------------------------------------------------------


def test_saved_reports_are_personal_unless_shared_and_grant_nothing(client, tenant, owner, world):
    body = {"report_key": "deposits", "name": "Weekly deposits", "params": {"period": "last_week"}}
    saved = ok(client.post(f"{API}/saved-reports", headers=owner, json=body), 201)
    assert code(client.post(f"{API}/saved-reports", headers=owner, json=body | {"name": "weekly DEPOSITS"}), 409) == (
        "already-exists"
    )
    bad = client.post(f"{API}/saved-reports", headers=owner, json=body | {"name": "x", "params": {"period": "x"}})
    assert code(bad, 422) == "validation-failed"
    manager = login(client, tenant, add_staff(tenant, "manager", all_locations=True)[0])
    url = f"{API}/saved-reports/{saved['id']}"
    assert code(client.get(url, headers=manager), 404) == "not-found"
    ok(client.patch(url, headers=owner, json={"is_shared": True}))
    assert ok(client.get(f"{API}/saved-reports", headers=manager))["data"][0]["id"] == saved["id"]
    assert code(client.patch(url, headers=manager, json={"name": "Mine"}), 403) == "permission-denied"
    desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    assert code(client.get(url, headers=desk), 404) == "not-found"  # shared, but no financial key

    rerun = ok(client.post(f"{API}/report-runs", headers=manager, json={"report_key": "deposits",
                                                                         "saved_report_id": saved["id"]}))  # fmt: skip
    assert rerun["saved_report_id"] == saved["id"] and rerun["params"]["from_on"] < rerun["params"]["to_on"]
    assert ok(client.get(url, headers=owner))["last_run_at"] is not None
    ok(client.delete(url, headers=owner), 204)
    assert ok(client.get(f"{API}/report-runs/{rerun['id']}", headers=manager))["saved_report_id"] is None


# --- export jobs ---------------------------------------------------------------------------------------------


def test_csv_exports_render_in_a_job_from_the_snapshot(client, tenant, owner, world):
    done = ran(client, owner, "revenue_summary", period="last_30_days")
    url = f"{API}/export-jobs"
    assert code(client.post(url, headers=owner, json={"report_run_id": done["id"], "format": "xlsx"}), 422) == (
        "not-supported"
    )
    job = ok(client.post(url, headers=owner, json={"report_run_id": done["id"], "includes_details": True}), 202)
    assert job["status"] == "queued"
    assert code(client.get(f"{url}/{job['id']}/download", headers=owner), 409) == "invalid-state-transition"
    drain()
    finished = ok(client.get(f"{url}/{job['id']}", headers=owner))
    assert finished["status"] == "succeeded" and finished["file_name"].startswith("revenue_summary-")
    response = client.get(f"{url}/{job['id']}/download", headers=owner)
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    body = response.content.decode("utf-8-sig").splitlines()
    assert body[0].startswith("Revenue category,Charges,Discounts (USD),Net revenue (USD)")
    assert body[1] == "Rentals,2,0.00,90.00,9.00,99.00,100.0" and "Revenue date" in body[3]
    assert len(body) == 6  # summary header and row, blank line, detail header and two charges

    desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    assert code(client.get(f"{url}/{job['id']}", headers=desk), 403) == "permission-denied"
    other = login(client, tenant, add_staff(tenant, "admin", all_locations=True)[0])
    assert code(client.get(f"{url}/{job['id']}/download", headers=other), 404) == "not-found"
    foreign = client.post(url, headers=other, json={"report_run_id": done["id"]})
    assert code(foreign, 422) == "validation-failed"


# --- pure rules ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("period", "expected"), [
    ("today", ("2026-05-14", "2026-05-14")), ("yesterday", ("2026-05-13", "2026-05-13")),
    ("this_week", ("2026-05-11", "2026-05-17")), ("last_week", ("2026-05-04", "2026-05-10")),
    ("this_month", ("2026-05-01", "2026-05-31")), ("last_month", ("2026-04-01", "2026-04-30")),
    ("this_quarter", ("2026-04-01", "2026-06-30")), ("this_year", ("2026-01-01", "2026-12-31")),
    ("last_year", ("2025-01-01", "2025-12-31")), ("last_30_days", ("2026-04-15", "2026-05-14")),
])  # fmt: skip
def test_periods_resolve_inclusively(period, expected):
    assert tuple(d.isoformat() for d in periods.resolve(period, date(2026, 5, 14))) == expected


def test_last_month_crosses_the_year_and_quarters_end_on_the_last_day():
    assert periods.resolve("last_month", date(2026, 1, 9)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert periods.resolve("this_quarter", date(2026, 11, 30))[1] == date(2026, 12, 31)
    with pytest.raises(ValueError):
        periods.resolve("fortnight", date(2026, 1, 1))


@pytest.mark.parametrize(("days", "bucket"), [
    (-3, "current_minor"), (0, "current_minor"), (1, "days_1_30_minor"), (30, "days_1_30_minor"),
    (31, "days_31_60_minor"), (61, "days_61_90_minor"), (90, "days_61_90_minor"), (91, "days_over_90_minor"),
])  # fmt: skip
def test_aging_buckets_have_inclusive_upper_bounds(days, bucket):
    assert periods.aging_bucket(days) == bucket


def test_csv_cells_guard_formulas_and_format_money():
    assert csv_file.cell(123456, "money") == "1234.56" and csv_file.cell(-5, "money") == "-0.05"
    assert csv_file.cell(7, "money", exponent=0) == "7"
    assert csv_file.cell("=SUM(A1)", "text") == "'=SUM(A1)" and csv_file.cell(-4, "count") == "-4"
    assert (csv_file.cell(True, "bool"), csv_file.cell(None, "text")) == ("yes", "")
    data = csv_file.render([{"key": "a", "label": "Amount", "type": "money"}], [{"a": 100}], currency="EUR")
    assert data == "﻿Amount (EUR)\r\n1.00\r\n".encode()


def test_every_report_has_rows_against_a_fully_populated_tenant(client, tenant):
    """populate() writes a row in every table, so every report family must find something (sessions are 2030)."""
    from conftest import populate

    world = populate(client, tenant)
    around_today = {
        "from_on": str(clock.now().date() - timedelta(days=180)),
        "to_on": str(clock.now().date() + timedelta(days=180)),
    }
    found = {}
    for definition in ok(client.get(f"{API}/report-definitions", headers=world.headers))["data"]:
        if definition["key"].startswith("attendance"):
            params = {"from_on": "2030-01-01", "to_on": "2030-12-31"}
        else:
            params = around_today if "period" in definition["params_schema"]["properties"] else {}
        done = ran(client, world.headers, definition["key"], **params)
        found[definition["key"]] = done["row_count"]
        if definition["supports_detail"] and done["row_count"]:
            group = rows(client, world.headers, done["id"])["data"][0]["group_key"]
            assert rows(client, world.headers, done["id"], group_key=group)["data"], definition["key"]
    assert all(found.values()), found
