"""Phase 12 chip A: XLSX and PDF exports for every spec, scheduled delivery of saved reports, and the management
dashboard, through the API with both gates over the two-zone `world` of test_reporting (Main in Chicago, North in
New York), plus the pure rules of the XLSX engine, the PDF detail cap and the schedule clock."""

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from app.core import xlsx
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.reporting import dashboard, schedules
from app.modules.reporting.catalogue import REGISTRY
from app.modules.reporting.domain import report_files
from app.modules.reporting.models import ExportJob, ReportSchedule
from app.modules.reporting.tests.test_reporting import (  # noqa: F401 (fixtures)
    API, code, drain, ok, ran, same_day_everywhere, world,
)  # fmt: skip
from conftest import add_staff, login


def _export(client, headers, run_id, fmt, **extra) -> tuple[dict, bytes]:
    job = ok(client.post(f"{API}/export-jobs", headers=headers,
                         json={"report_run_id": run_id, "format": fmt} | extra), 202)  # fmt: skip
    drain()
    done = ok(client.get(f"{API}/export-jobs/{job['id']}", headers=headers))
    assert done["status"] == "succeeded", done
    response = client.get(f"{API}/export-jobs/{job['id']}/download", headers=headers)
    assert response.status_code == 200
    return done | {"content_type": response.headers["content-type"]}, response.content


# --- formats on every spec -----------------------------------------------------------------------------------


def test_every_spec_offers_csv_xlsx_and_pdf(client, owner):
    found = ok(client.get(f"{API}/report-definitions", headers=owner))["data"]
    assert {tuple(d["export_formats"]) for d in found} == {("csv", "xlsx", "pdf")}


def test_xlsx_export_has_a_cover_typed_cells_and_one_sheet_per_section(client, owner, world):
    done = ran(client, owner, "revenue_summary", period="last_30_days")
    job, data = _export(client, owner, done["id"], "xlsx", includes_details=True)
    assert job["file_name"].endswith(".xlsx") and "spreadsheetml" in job["content_type"]
    book = load_workbook(io.BytesIO(data))
    assert book.sheetnames == ["Cover", "Summary", "Totals", "Details"]
    cover = {row[0]: row[1] for row in book["Cover"].iter_rows(values_only=True)}
    assert cover["Report"] == "Revenue summary" and cover["Locations"] == "All locations" and cover["From"]
    summary = list(book["Summary"].iter_rows(values_only=True))
    assert summary[0][:4] == ("Revenue category", "Charges", "Discounts (USD)", "Net revenue (USD)")
    assert summary[1][:4] == ("Rentals", 2, 0, 90) and book["Summary"].freeze_panes == "A2"
    assert len(list(book["Details"].iter_rows())) == 3  # header and the two charges, one per zone


def test_pdf_export_follows_page_options_and_states_the_parameters(client, owner, world):
    done = ran(client, owner, "revenue_summary", location_ids=[world.main], period="last_30_days")
    job, data = _export(client, owner, done["id"], "pdf", page_size="a4", orientation="portrait")
    assert job["file_name"].endswith(".pdf") and job["content_type"] == "application/pdf"
    assert data.startswith(b"%PDF") and b"Revenue summary" in data and b"Rentals" in data
    assert b"Main" in data and b"20.00 USD" in data  # the location named, Main's net only
    assert b"/MediaBox [0 0 595.28 841.89]" in data  # A4 portrait


def test_xlsx_cells_are_typed_and_text_never_becomes_a_formula(monkeypatch):
    sheet = xlsx.Sheet("A:B/C", [xlsx.Column("Name"), xlsx.Column("Net", "money"), xlsx.Column("On", "date"),
                                 xlsx.Column("Paid", "bool")], [["=HYPERLINK(1)", 12345, "2026-01-05", True]])  # fmt: skip
    book = load_workbook(io.BytesIO(xlsx.workbook([("Report", "=1+1")], [sheet])))
    page = book["A B C"]
    assert page["A2"].data_type == "s" and page["A2"].value == "=HYPERLINK(1)"
    assert book["Cover"]["B1"].data_type == "s"
    assert page["B2"].value == Decimal("123.45") and page["C2"].value.date() == date(2026, 1, 5)
    assert page["D2"].value == "yes"
    monkeypatch.setattr(xlsx, "MAX_ROWS", 2)
    with pytest.raises(xlsx.TooLarge):
        xlsx.workbook([], [xlsx.Sheet("Big", [xlsx.Column("n", "count")], [[1], [2], [3]])])


def test_pdf_leaves_out_detail_rows_past_the_cap():
    columns = [{"key": "n", "label": "N", "type": "count"}]
    snapshot = {"columns": columns, "rows": [{"n": 1}], "detail_columns": columns,
                "details": [{"n": i} for i in range(report_files.PDF_DETAIL_ROWS + 1)]}  # fmt: skip
    data = report_files.to_pdf(snapshot, [("Report", "X")], [], title="X", organization="Org", details=True,
                               currency="USD", page_size=None, orientation=None)  # fmt: skip
    assert b"more than a PDF lists" in data and data.count(b"5000") == 0


# --- scheduled delivery --------------------------------------------------------------------------------------


@pytest.fixture
def team(client, tenant, world):
    manager_email, manager_id = add_staff(tenant, "manager", location_ids=[world.main])
    desk_email, desk_id = add_staff(tenant, "front_desk", all_locations=True)
    return SimpleNamespace(manager=login(client, tenant, manager_email), manager_id=manager_id, desk_id=desk_id)


def _saved(client, headers, key="revenue_summary", **params) -> dict:
    body = {"report_key": key, "name": f"Daily {key}", "params": params or {"period": "last_30_days"}}
    return ok(client.post(f"{API}/saved-reports", headers=headers, json=body), 201)


def _schedule_body(saved, world, recipients, **extra) -> dict:
    return {"saved_report_id": saved["id"], "location_id": world.main, "frequency": "daily", "send_time": "07:00",
            "format": "xlsx", "recipient_staff_user_ids": [str(r) for r in recipients]} | extra  # fmt: skip


def test_schedules_check_their_shape_location_and_recipients(client, tenant, owner, world, team):
    saved = _saved(client, owner)
    url = f"{API}/report-schedules"
    weekly = client.post(url, headers=owner, json=_schedule_body(saved, world, [tenant.owner_id], frequency="weekly"))
    assert code(weekly, 422) == "validation-failed" and weekly.json()["errors"][0]["pointer"] == "/weekday"
    desk = client.post(url, headers=owner, json=_schedule_body(saved, world, [tenant.owner_id, team.desk_id]))
    assert code(desk, 422) == "validation-failed"  # front desk cannot run financial reports
    assert desk.json()["errors"][0]["pointer"] == "/recipient_staff_user_ids/1"
    names = ok(client.get(f"{API}/report-definitions/revenue_summary/recipients", headers=owner))["data"]
    assert {r["id"] for r in names} == {str(tenant.owner_id), str(team.manager_id)}

    body = _schedule_body(saved, world, [tenant.owner_id, team.manager_id], frequency="monthly", month_day=1,
                          weekday=3)  # fmt: skip
    made = ok(client.post(url, headers=owner, json=body), 201)
    assert made["weekday"] is None and made["month_day"] == 1 and made["send_time"] == "07:00"
    assert [s["id"] for s in ok(client.get(url, headers=owner))["data"]] == [made["id"]]
    assert code(client.get(f"{url}/{made['id']}", headers=team.manager), 404) == "not-found"  # not theirs
    changed = ok(client.patch(f"{url}/{made['id']}", headers=owner, json={"frequency": "daily", "is_active": False}))
    assert changed["month_day"] is None and changed["is_active"] is False

    # a manager at Main only: North is outside their locations (404, as everywhere)
    mine = _saved(client, team.manager)
    north = _schedule_body(mine, world, [team.manager_id], location_id=world.north)
    assert code(client.post(url, headers=team.manager, json=north), 404) == "not-found"
    # deleting the saved report takes its schedules with it
    ok(client.delete(f"{API}/saved-reports/{saved['id']}", headers=owner), 204)
    assert code(client.get(f"{url}/{made['id']}", headers=owner), 404) == "not-found"


def _tick(tenant) -> bool:
    with tenant_session(tenant.id, actor=system_principal("run_report_schedules")) as session:
        return schedules.run_due_schedule(session)


def test_due_schedules_send_each_recipient_a_link_to_their_own_export(client, tenant, owner, world, team, mailbox):
    saved = _saved(client, owner)
    body = _schedule_body(saved, world, [tenant.owner_id, team.manager_id])
    made = ok(client.post(f"{API}/report-schedules", headers=owner, json=body), 201)
    assert _tick(tenant) is True  # noon in Chicago, sent at 07:00: due
    assert _tick(tenant) is False  # once a day, however often the clock ticks
    drain()
    with tenant_session(tenant.id) as session:
        exports = session.query(ExportJob).filter(ExportJob.notify_on_complete).all()
        assert session.get(ReportSchedule, made["id"]).last_run_on is not None
    assert {e.requested_by_staff_user_id for e in exports} == {tenant.owner_id, team.manager_id}
    assert all(e.status == "succeeded" and e.format == "xlsx" for e in exports)
    by_owner = {e.requested_by_staff_user_id: e for e in exports}
    # each run is built with its recipient's own reach: the manager's covers Main only
    assert by_owner[team.manager_id].params["location_ids"] == [world.main]
    assert by_owner[tenant.owner_id].params["location_ids"] is None
    assert len(mailbox) == 2
    for message in mailbox:
        link = next(line for line in message.body.splitlines() if "/reports/exports/" in line)
        assert "?" not in link and "#" not in link  # the id alone; signing in is what grants the download
        assert "Rentals" not in message.body  # no report data in the mailbox
    manager_job = by_owner[team.manager_id]
    assert code(client.get(f"{API}/export-jobs/{manager_job.id}/download", headers=owner), 404) == "not-found"
    assert client.get(f"{API}/export-jobs/{manager_job.id}/download", headers=team.manager).status_code == 200


def test_a_recipient_who_lost_access_is_skipped(client, tenant, owner, world, team, mailbox):
    saved = _saved(client, owner, location_ids=[world.north], period="last_30_days")
    body = _schedule_body(saved, world, [tenant.owner_id, team.manager_id], format="csv")
    ok(client.post(f"{API}/report-schedules", headers=owner, json=body), 201)
    assert _tick(tenant) is True  # the manager cannot see North: no run for them, the owner still gets theirs
    drain()
    with tenant_session(tenant.id) as session:
        found = session.query(ExportJob).filter(ExportJob.notify_on_complete).all()
        assert [e.requested_by_staff_user_id for e in found] == [tenant.owner_id]
    assert len(mailbox) == 1


def _schedule(**fields) -> ReportSchedule:
    return ReportSchedule(**({"frequency": "daily", "send_time": "07:00", "last_run_on": None} | fields))


@pytest.mark.parametrize(("fields", "local", "due"), [
    ({}, datetime(2026, 1, 5, 6, 59), False),
    ({}, datetime(2026, 1, 5, 7, 0), True),
    ({"last_run_on": date(2026, 1, 5)}, datetime(2026, 1, 5, 23, 0), False),
    ({"last_run_on": date(2026, 1, 4)}, datetime(2026, 1, 5, 9, 0), True),
    ({"frequency": "weekly", "weekday": 0}, datetime(2026, 1, 5, 9, 0), True),  # a Monday
    ({"frequency": "weekly", "weekday": 1}, datetime(2026, 1, 5, 9, 0), False),
    ({"frequency": "monthly", "month_day": 5}, datetime(2026, 1, 5, 9, 0), True),
    ({"frequency": "monthly", "month_day": 6}, datetime(2026, 1, 5, 9, 0), False),
])  # fmt: skip
def test_schedules_fall_due_once_a_local_day_after_the_send_time(fields, local, due):
    assert schedules.is_due(_schedule(**fields), local.replace(tzinfo=UTC)) is due


# --- the dashboard -------------------------------------------------------------------------------------------


def test_dashboard_tiles_name_real_totals():
    for key, _, shown in dashboard.TILES:
        assert set(shown) <= {c.key for c in REGISTRY[key].totals}, key


def test_dashboard_composes_reports_per_caller_and_caches_briefly(client, tenant, owner, world, team):
    first = ok(client.get(f"{API}/dashboard", headers=owner))
    tiles = {t["key"]: t for t in first["tiles"]}
    assert {"revenue_summary", "deposits", "open_invoices", "attendance_overview"} <= set(tiles)
    net = next(t for t in tiles["revenue_summary"]["totals"] if t["key"] == "net_minor")
    assert net["value"] == 9000 and net["type"] == "money"
    assert ok(client.get(f"{API}/dashboard", headers=owner))["generated_at"] == first["generated_at"]  # cached

    managed = {t["key"]: t for t in ok(client.get(f"{API}/dashboard", headers=team.manager))["tiles"]}
    assert next(t for t in managed["revenue_summary"]["totals"] if t["key"] == "net_minor")["value"] == 2000
    assert code(client.get(f"{API}/dashboard?location_id={world.north}", headers=team.manager), 404) == "not-found"
    coach = login(client, tenant, add_staff(tenant, "coach", all_locations=True)[0])
    assert code(client.get(f"{API}/dashboard", headers=coach), 403) == "permission-denied"
