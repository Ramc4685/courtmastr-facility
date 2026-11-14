"""CSV imports through the API and the worker: each type's happy path and validation failures, a dry run that
writes nothing, idempotent re-runs and chunk retries, the plan limit mid-file, both gates and the location set."""

import csv
import io
import os
import time
from datetime import timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from dramatiq import Worker
from sqlalchemy import text

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.jobs import broker
from app.core.settings import get_settings
from app.modules import billing, imports
from conftest import add_staff, login, new_client, scalar

API = "/api/v1"
TABLES = ("client", "client_relationship", "membership_contract", "charge", "invoice", "payment", "product",
          "stock_movement", "consent_event")  # fmt: skip


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def drain() -> None:
    worker = Worker(broker, worker_timeout=100)
    worker.start()
    try:
        broker.join("default", fail_fast=True, timeout=600_000)
        worker.join()
    finally:
        worker.stop()


def counts(tenant) -> dict:
    return {table: scalar(tenant, text(f"SELECT count(*) FROM {table}")) for table in TABLES}


def to_csv(rows: list[list]) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows)
    return out.getvalue().encode()


def report(client, headers, job) -> list[list[str]]:
    response = client.get(f"{API}/import-jobs/{job['id']}/error-report", headers=headers)
    assert response.status_code == 200, response.text
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


@pytest.fixture
def location_id(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return ok(client.post(f"{API}/locations", headers=owner, json=body), 201)["id"]


def start(client, headers, location_id, kind, data: bytes, *, content_type="text/csv") -> dict:
    job = ok(client.post(f"{API}/import-jobs", headers=headers, json={"kind": kind, "location_id": location_id}), 201)
    url = f"{API}/import-jobs/{job['id']}/source"
    return ok(client.put(url, headers=headers | {"Content-Type": content_type, "X-File-Name": "a.csv"}, content=data))


def check(client, headers, job, **body) -> dict:
    ok(client.post(f"{API}/import-jobs/{job['id']}/dry-runs", headers=headers, json=body), 202)
    drain()
    return ok(client.get(f"{API}/import-jobs/{job['id']}", headers=headers))


def commit(client, headers, job) -> dict:
    ok(client.post(f"{API}/import-jobs/{job['id']}/commits", headers=headers), 202)
    drain()
    return ok(client.get(f"{API}/import-jobs/{job['id']}", headers=headers))


def run(client, headers, location_id, kind, rows, **body) -> dict:
    job = check(client, headers, start(client, headers, location_id, kind, to_csv(rows)), **body)
    return commit(client, headers, job)


def outcomes(tenant, job) -> dict[int, tuple[str, list[str]]]:
    with tenant_session(tenant.id) as session:
        rows = session.execute(text(
            "SELECT row_number, status, errors FROM import_job_row WHERE import_job_id = :j ORDER BY row_number"
        ), {"j": job["id"]})  # fmt: skip
        return {n: (status, [e["code"] for e in errors]) for n, status, errors in rows}


CLIENT_HEADER = ["member_number", "first_name", "last_name", "email", "mobile_phone", "birth_date", "household_ref",
                 "household_head", "relationship_to_head", "email_marketing"]  # fmt: skip


# --- templates and files -------------------------------------------------------------------------------------------


def test_templates_list_every_type_and_download_our_columns(client, owner):
    listing = ok(client.get(f"{API}/import-templates", headers=owner))["data"]
    assert [t["kind"] for t in listing] == ["clients", "memberships", "balances", "products"]
    assert all(t["guide"] and t["fields"] for t in listing)
    response = client.get(f"{API}/import-templates/clients", headers=owner)
    assert (
        response.headers["content-type"].startswith("text/csv")
        and "attachment" in response.headers["content-disposition"]
    )
    header, example = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert header[:3] == ["member_number", "first_name", "last_name"] and len(example) == len(header)
    assert client.get(f"{API}/import-templates/nope", headers=owner).status_code == 404


def test_upload_refuses_other_encodings_types_and_sizes(client, owner, location_id):
    job = ok(
        client.post(f"{API}/import-jobs", headers=owner, json={"kind": "clients", "location_id": location_id}), 201
    )
    url = f"{API}/import-jobs/{job['id']}/source"

    def put(data, content_type="text/csv"):
        response = client.put(url, headers=owner | {"Content-Type": content_type}, content=data)
        return response.status_code, response.json().get("code")

    assert put("first_name,last_name\r\nJosé,Núñez\r\n".encode("latin-1")) == (422, "file-not-utf8")
    assert put(b"first_name\r\nA\r\n", "application/pdf") == (422, "file-type-mismatch")
    assert put(b"") == (422, "file-empty")
    assert put(b"a,A\r\n") == (422, "file-duplicate-header")
    assert put(b"x" * (imports.service.MAX_UPLOAD_BYTES + 1))[0] in (413, 422)
    uploaded = ok(client.put(url, headers=owner | {"Content-Type": "text/csv; charset=utf-8"},
                             content="﻿first_name,Last Name\r\nJosé,Núñez\r\n".encode()))  # fmt: skip
    assert uploaded["status"] == "uploaded" and uploaded["total_row_count"] == 1
    assert uploaded["column_mapping"] == {"first_name": "first_name", "last_name": "Last Name"}
    other = ok(
        client.post(f"{API}/import-jobs", headers=owner, json={"kind": "clients", "location_id": location_id}), 201
    )
    refused = client.post(f"{API}/import-jobs/{other['id']}/dry-runs", headers=owner, json={})
    assert refused.status_code == 409  # nothing uploaded yet
    bad = client.post(
        f"{API}/import-jobs/{job['id']}/dry-runs", headers=owner, json={"column_mapping": {"first_name": "first_name"}}
    )
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/column_mapping/last_name"


# --- clients and households ----------------------------------------------------------------------------------------


def test_clients_dry_run_writes_nothing_then_commit_creates_households(client, tenant, owner, location_id):
    rows = [CLIENT_HEADER,
            ["M-1", "Ana", "Rivera", "ana@example.com", "+1 (309) 555-0101", "1980-02-03", "RIV", "yes", "", "yes"],
            ["M-2", "Ben", "Rivera", "", "", "2014-06-07", "RIV", "", "child", ""],
            ["", "Cai", "Solo", "cai@example.com", "", "", "", "", "", "no"]]  # fmt: skip
    before = counts(tenant)
    job = check(client, owner, start(client, owner, location_id, "clients", to_csv(rows)))
    assert job["status"] == "validated" and (job["valid_row_count"], job["created_count"], job["error_count"]) == (
        3,
        3,
        0,
    )
    assert counts(tenant) == before  # a dry run writes nothing
    assert job["has_error_report"] is False
    done = commit(client, owner, job)
    assert done["status"] == "completed" and (done["created_count"], done["error_count"]) == (3, 0)
    after = counts(tenant)
    assert after["client"] == before["client"] + 3 and after["client_relationship"] == before["client_relationship"] + 1
    with tenant_session(tenant.id) as session:
        ana, ben = (session.execute(text("SELECT id, created_via, phone_mobile FROM client WHERE member_number = :m"),
                                    {"m": m}).one() for m in ("M-1", "M-2"))  # fmt: skip
        assert ana.created_via == "import" and ana.phone_mobile == "+13095550101"
        rel = session.execute(text("SELECT from_client_id, to_client_id FROM client_relationship")).one()
        assert (rel.from_client_id, rel.to_client_id) == (ben.id, ana.id)  # Ben is child of the head
        consent = session.execute(
            text("SELECT source FROM consent_event WHERE client_id = :c AND channel = 'email'"), {"c": ana.id}
        ).all()
        assert consent and {row.source for row in consent} == {"import"}
        actions = {r[0] for r in session.execute(text("SELECT action FROM audit_event WHERE action LIKE 'imports.%'"))}
        assert actions >= {"imports.import_job.create", "imports.import_job.upload", "imports.import_job.complete"}
        changes = session.execute(text(
            "SELECT changes::text FROM audit_event WHERE action LIKE 'imports.%'")).scalars().all()  # fmt: skip
        assert not any("ana@example.com" in c or "Rivera" in c for c in changes)  # flag-only, no PII
    listed = ok(client.get(f"{API}/import-jobs", headers=owner))["data"]
    assert [j["id"] for j in listed] == [job["id"]]


def test_clients_validation_failures_are_reported_per_row(client, tenant, owner, location_id):
    header = ["first_name", "=Surname", "email", "mobile_phone", "birth_date", "gender", "country_code",
              "household_ref", "household_head", "relationship_to_head", "sms_marketing"]  # fmt: skip
    future = (clock.now().date() + timedelta(days=30)).isoformat()
    rows = [header,
            ["NoLast", "", "", "", "", "", "", "", "", "", ""],                        # 2 required
            ["Bad", "Email", "nope", "", "", "", "", "", "", "", ""],                  # 3 invalid-email
            ["Bad", "Phone", "", "3095550101", "", "", "", "", "", "", ""],            # 4 invalid-phone
            ["Bad", "Date", "", "", "31/12/2000", "", "", "", "", "", ""],             # 5 invalid-date
            ["Future", "Born", "", "", future, "", "", "", "", "", ""],                # 6 date-in-future
            ["Bad", "Gender", "", "", "", "robot", "", "", "", "", ""],                # 7 invalid-choice
            ["Bad", "Country", "", "", "", "", "USA", "", "", "", ""],                 # 8 invalid-country
            ["No", "Head", "", "", "", "", "", "ORPHAN", "", "child", ""],             # 9 household
            ["Two", "Heads", "", "", "", "", "", "DUO", "yes", "", ""],                # 10 household
            ["Two", "Heads2", "", "", "", "", "", "DUO", "yes", "", ""],               # 11 household
            ["No", "Mobile", "", "", "", "", "", "", "", "", "yes"],                   # 12 no-address
            ["Fine", "Person", "fine@example.com", "", "", "", "", "", "", "", ""],    # 13 ok
            [],                                                                        # 14 blank, ignored
            ["Fine", "Person", "fine@example.com", "", "", "", "", "", "", "", ""]]  # 15 duplicate of 13  # fmt: skip
    mapping = {"first_name": "first_name", "last_name": "=Surname", "email": "email", "mobile_phone": "mobile_phone",
               "birth_date": "birth_date", "gender": "gender", "country_code": "country_code",
               "household_ref": "household_ref", "household_head": "household_head",
               "relationship_to_head": "relationship_to_head", "sms_marketing": "sms_marketing"}  # fmt: skip
    job = check(client, owner, start(client, owner, location_id, "clients", to_csv(rows)), column_mapping=mapping)
    assert job["status"] == "needs_review" and job["total_row_count"] == 13
    assert (job["valid_row_count"], job["error_count"], job["skipped_count"]) == (1, 11, 1)
    found = outcomes(tenant, job)
    assert found[2] == ("invalid", ["required"]) and found[3][1] == ["invalid-email"]
    assert found[4][1] == ["invalid-phone"] and found[5][1] == ["invalid-date"] and found[6][1] == ["date-in-future"]
    assert found[7][1] == ["invalid-choice"] and found[8][1] == ["invalid-country"]
    assert found[9][1] == found[10][1] == found[11][1] == ["household"] and found[12][1] == ["no-address"]
    assert found[13] == ("valid", []) and found[15] == ("skipped", ["duplicate-row"]) and 14 not in found
    lines = report(client, owner, job)
    assert lines[0] == ["Row", "Outcome", "Column", "Problem"]
    assert ["2", "Would fail", "'=Surname", "Last name is required."] in lines  # header neutralised, never a formula
    assert all("nope" not in line[3] for line in lines[1:])  # problems never quote the cell
    done = commit(client, owner, job)
    assert (done["status"], done["created_count"], done["error_count"], done["skipped_count"]) == (
        "completed",
        1,
        11,
        1,
    )
    assert outcomes(tenant, done)[3] == ("failed", ["invalid-email"])
    assert report(client, owner, done)[1][1] == "Failed"


def test_possible_duplicate_is_skipped_and_rerun_updates_instead_of_duplicating(client, tenant, owner, location_id):
    new_client(client, owner, location_id, first_name="Dana", last_name="Existing", primary_email="dana@example.com")
    rows = [["first_name", "last_name", "email", "member_number", "city"],
            ["Dana", "Existing", "dana@example.com", "", "Peoria"],       # matches by email and name: update
            ["Eli", "New", "eli@example.com", "E-1", ""]]  # fmt: skip
    first = run(client, owner, location_id, "clients", rows)
    assert (first["created_count"], first["updated_count"]) == (1, 1)
    before = counts(tenant)["client"]
    again = run(client, owner, location_id, "clients", rows)
    assert (again["created_count"], again["updated_count"], again["error_count"]) == (0, 2, 0)
    assert counts(tenant)["client"] == before
    lookalike = check(
        client,
        owner,
        start(
            client,
            owner,
            location_id,
            "clients",
            to_csv([["first_name", "last_name", "email"], ["Elias", "New", "eli@example.com"]]),
        ),
    )
    assert lookalike["skipped_count"] == 1 and outcomes(tenant, lookalike)[2] == ("skipped", ["possible-duplicate"])
    assert counts(tenant)["client"] == before


def test_chunk_retry_never_duplicates(client, tenant, owner, location_id, monkeypatch):
    monkeypatch.setattr(imports.kinds.KINDS["clients"], "chunk_rows", 2)
    rows = [["first_name", "last_name", "member_number"]] + [[f"P{i}", "Chunk", f"C-{i}"] for i in range(5)]
    job = check(client, owner, start(client, owner, location_id, "clients", to_csv(rows)))
    assert job["valid_row_count"] == 5 and job["processed_row_count"] == 5
    ok(client.post(f"{API}/import-jobs/{job['id']}/commits", headers=owner), 202)
    with pytest.raises(RuntimeError):  # a chunk that crashes before its commit leaves nothing behind
        with tenant_session(tenant.id, actor=system_principal("run_import")) as session:
            assert imports.service.run_chunk(session, UUID(job["id"])) is True
            raise RuntimeError("worker died")
    with tenant_session(tenant.id, actor=system_principal("run_import")) as session:  # a duplicate delivery
        assert imports.service.run_chunk(session, UUID(job["id"])) is True
    drain()  # the queued message resumes from the cursor
    done = ok(client.get(f"{API}/import-jobs/{job['id']}", headers=owner))
    assert (done["status"], done["created_count"], done["skipped_count"], done["error_count"]) == ("completed", 5, 0, 0)
    assert scalar(tenant, text("SELECT count(*) FROM client WHERE last_name = 'Chunk'")) == 5


def test_plan_limit_reached_mid_file_is_a_row_error(client, tenant, owner, location_id):
    used = scalar(tenant, text("SELECT count(*) FROM client WHERE status = 'active' AND merged_into_id IS NULL"))
    op = {"X-Operator-Token": get_settings().operator_token}
    ok(client.post(f"{API}/operator/tenants/{tenant.id}/entitlements", headers=op,
                   json={"key": "clients", "limit_value": used + 2}), 201)  # fmt: skip
    rows = [["first_name", "last_name"]] + [[f"L{i}", "Limit"] for i in range(4)]
    job = check(client, owner, start(client, owner, location_id, "clients", to_csv(rows)))
    assert (job["valid_row_count"], job["error_count"]) == (2, 2)
    assert outcomes(tenant, job)[4] == ("invalid", ["plan-limit-reached"])
    done = commit(client, owner, job)
    assert (done["created_count"], done["error_count"]) == (2, 2)
    assert outcomes(tenant, done)[5] == ("failed", ["plan-limit-reached"])
    assert "plan" in report(client, owner, done)[1][3]


# --- memberships ---------------------------------------------------------------------------------------------------


@pytest.fixture
def plan(client, tenant, owner):
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        category = billing.service.create_revenue_category(session, code="MEM", label="Memberships", tax_ids=[])
        category_id = str(category.id)
    kind = ok(client.post(f"{API}/membership-types", headers=owner,
                          json={"name": "Adult", "revenue_category_id": category_id}), 201)  # fmt: skip
    return ok(client.post(f"{API}/membership-plans", headers=owner, json={
        "membership_type_id": kind["id"], "name": "Adult Monthly", "billing_occurrences_count": 12,
        "term_fee_minor": 5000}), 201)  # fmt: skip


def test_memberships_import_once_and_validate(client, tenant, owner, location_id, plan):
    person = new_client(client, owner, location_id, primary_email="mem@example.com", member_number="MM-1")
    today = clock.now().date()
    start_on, end_on = (today - timedelta(days=60)).isoformat(), (today + timedelta(days=300)).isoformat()
    next_bill = (today + timedelta(days=5)).isoformat()
    header = ["client_member_number", "client_email", "membership", "start_date", "end_date", "next_bill_date",
              "status", "price"]  # fmt: skip
    rows = [header,
            ["MM-1", "", "adult monthly", start_on, end_on, next_bill, "active", "45.00"],   # 2 ok
            ["", "", "Adult Monthly", start_on, "", "", "", ""],                            # 3 no client ref
            ["NOPE", "", "Adult Monthly", start_on, "", "", "", ""],                        # 4 unknown client
            ["MM-1", "", "Gold", start_on, "", "", "", ""],                                 # 5 unknown plan
            ["", "mem@example.com", "Adult Monthly", end_on, "", "", "expired", ""],     # 6 status mismatch
            ["MM-1", "", "Adult Monthly", end_on, start_on, "", "", ""],                    # 7 end before start
            ["MM-1", "", "Adult Monthly", "2026-13-01", "", "", "", "4,50"]]  # fmt: skip  # 8 bad date and money
    before = counts(tenant)
    job = check(client, owner, start(client, owner, location_id, "memberships", to_csv(rows)))
    assert counts(tenant) == before
    found = outcomes(tenant, job)
    assert found[2] == ("valid", []) and found[3][1] == ["required"] and found[4][1] == ["unknown-client"]
    assert found[5][1] == ["unknown-plan"] and found[6][1] == ["status-mismatch"]
    assert found[7][1] == ["end-before-start"] and sorted(found[8][1]) == ["invalid-amount", "invalid-date"]
    done = commit(client, owner, job)
    assert (done["created_count"], done["error_count"]) == (1, 6)
    with tenant_session(tenant.id) as session:
        contract = session.execute(text(
            "SELECT status, term_fee_minor, owner_client_id FROM membership_contract")).one()  # fmt: skip
        assert (contract.status, contract.term_fee_minor, str(contract.owner_client_id)) == (
            "active",
            4500,
            person["id"],
        )
    again = check(client, owner, start(client, owner, location_id, "memberships", to_csv(rows[:2])))
    assert (again["valid_row_count"], again["skipped_count"]) == (0, 1)
    assert client.post(f"{API}/import-jobs/{again['id']}/commits", headers=owner).json()["code"] == "nothing-to-import"
    assert outcomes(tenant, again)[2] == ("skipped", ["already-imported"])
    assert counts(tenant)["membership_contract"] == before["membership_contract"] + 1


# --- opening balances ----------------------------------------------------------------------------------------------


def test_opening_balances_post_through_billing_once(client, tenant, owner, location_id):
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        billing.service.create_revenue_category(session, code="GEN", label="General", tax_ids=[])
    new_client(client, owner, location_id, primary_email="owes@example.com", member_number="B-1")
    new_client(client, owner, location_id, primary_email="credit@example.com")
    yesterday = (clock.now().date() - timedelta(days=1)).isoformat()
    future = (clock.now().date() + timedelta(days=3)).isoformat()
    rows = [["client_member_number", "client_email", "amount", "as_of_date", "direction", "description"],
            ["B-1", "", "120.50", yesterday, "owed", ""],
            ["", "credit@example.com", "30", yesterday, "credit", "Old credit"],
            ["B-1", "", "0", yesterday, "owed", ""],
            ["B-1", "", "10", future, "owed", ""],
            ["B-1", "", "10", yesterday, "sideways", ""]]  # fmt: skip
    job = check(client, owner, start(client, owner, location_id, "balances", to_csv(rows)))
    found = outcomes(tenant, job)
    assert found[4][1] == ["invalid-amount"] and found[5][1] == ["date-in-future"] and found[6][1] == ["invalid-choice"]
    before = counts(tenant)
    done = commit(client, owner, job)
    assert (done["created_count"], done["error_count"]) == (2, 3)
    after = counts(tenant)
    assert after["charge"] == before["charge"] + 1 and after["invoice"] == before["invoice"] + 1
    assert after["payment"] == before["payment"] + 1
    with tenant_session(tenant.id) as session:
        total = session.execute(text("SELECT total_minor FROM charge WHERE source_type = 'opening_balance'")).scalar()
        assert total == 12050
        kinds = dict(session.execute(text(
            "SELECT row_number, entity_type FROM import_job_row WHERE import_job_id = :j AND status = 'created'"),
            {"j": done["id"]}).all())  # fmt: skip
        assert kinds == {2: "charge", 3: "payment"}
    again = check(client, owner, start(client, owner, location_id, "balances", to_csv(rows[:3])))
    assert (again["valid_row_count"], again["skipped_count"]) == (0, 2)
    assert counts(tenant)["charge"] == after["charge"] and counts(tenant)["payment"] == after["payment"]


def test_a_card_number_in_imported_free_text_is_a_row_error(client, tenant, owner, location_id):
    """CSV rows skip the request schemas, so the import checks free text itself (security-baseline section 3)."""
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        billing.service.create_revenue_category(session, code="GEN", label="General", tax_ids=[])
    new_client(client, owner, location_id, member_number="C-1")
    yesterday = (clock.now().date() - timedelta(days=1)).isoformat()
    rows = [["client_member_number", "client_email", "amount", "as_of_date", "direction", "description"],
            ["C-1", "", "10", yesterday, "owed", "Card 4111 1111 1111 1111"],
            ["C-1", "", "12", yesterday, "owed", "Locker 4006381333931"]]  # fmt: skip
    job = check(client, owner, start(client, owner, location_id, "balances", to_csv(rows)))
    found = outcomes(tenant, job)
    assert found[2] == ("invalid", ["card-data-not-allowed"]) and found[3][0] == "valid"
    assert "4111" not in str(report(client, owner, job))


# --- products ------------------------------------------------------------------------------------------------------


def test_products_create_update_by_sku_and_count_stock(client, tenant, owner, location_id):
    from datetime import date

    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        billing.service.create_tax(session, code="ST", label="Sales tax", rate=Decimal("0.0825"),
                                   effective_from_on=date(2020, 1, 1))  # fmt: skip
    header = ["sku", "name", "category", "price", "tax_codes", "stock_on_hand"]
    rows = [header, ["W-1", "Water", "Drinks", "2.50", "st", "48"], ["G-1", "Grip tape", "Gear", "9", "", ""],
            ["X-1", "Bad tax", "Gear", "1", "NOPE", ""], ["", "No SKU", "Gear", "1", "", ""],
            ["Y-1", "Bad price", "Gear", "free", "", ""], ["Z-1", "Bad stock", "Gear", "1", "", "-3"]]  # fmt: skip
    job = check(client, owner, start(client, owner, location_id, "products", to_csv(rows)))
    found = outcomes(tenant, job)
    assert found[4][1] == ["unknown-tax"] and found[5][1] == ["required"] and found[6][1] == ["invalid-amount"]
    assert found[7][1] == ["invalid-number"]
    done = commit(client, owner, job)
    assert (done["created_count"], done["error_count"]) == (2, 4)
    again = run(client, owner, location_id, "products", [header, ["w-1", "Water 500 ml", "drinks", "2.75", "", "40"]])
    assert (again["created_count"], again["updated_count"]) == (0, 1)
    with tenant_session(tenant.id) as session:
        water = session.execute(text("SELECT name, unit_price_minor FROM product WHERE sku = 'W-1'")).one()
        assert tuple(water) == ("Water 500 ml", 275)
        assert session.execute(text("SELECT count(*) FROM product_category WHERE parent_id IS NULL")).scalar() == 2


# --- gates ---------------------------------------------------------------------------------------------------------


def test_run_needs_the_key_and_step_up_and_jobs_follow_the_location_set(client, tenant, owner, location_id):
    job = start(client, owner, location_id, "clients", b"first_name,last_name\r\nA,B\r\n")
    stale = login(client, tenant, elevated=False)
    refused = client.post(f"{API}/import-jobs", headers=stale, json={"kind": "clients", "location_id": location_id})
    assert refused.json()["code"] == "step-up-required"
    assert client.get(f"{API}/import-jobs/{job['id']}", headers=stale).status_code == 200  # reading needs no step-up
    email, _ = add_staff(tenant, "manager", all_locations=True)
    manager = login(client, tenant, email)
    assert client.get(f"{API}/import-jobs", headers=manager).status_code == 200
    denied = client.post(f"{API}/import-jobs", headers=manager, json={"kind": "clients", "location_id": location_id})
    assert denied.status_code == 403
    other = ok(client.post(f"{API}/locations", headers=owner,
                           json={"name": "Other", "time_zone": "America/Chicago", "country_code": "US"}), 201)  # fmt: skip
    email, _ = add_staff(tenant, "admin", location_ids=[other["id"]])
    outsider = login(client, tenant, email)
    assert client.get(f"{API}/import-jobs/{job['id']}", headers=outsider).status_code == 404
    assert client.get(f"{API}/import-jobs/{job['id']}/error-report", headers=outsider).status_code == 404
    refused = client.post(f"{API}/import-jobs/{job['id']}/dry-runs", headers=outsider, json={})
    assert refused.json()["code"] == "all-locations-required"  # before any lookup, so it reveals nothing
    assert ok(client.get(f"{API}/import-jobs", headers=outsider))["data"] == []
    elsewhere = client.post(
        f"{API}/import-jobs", headers=outsider, json={"kind": "clients", "location_id": location_id}
    )
    assert elsewhere.status_code == 422


def test_expired_files_are_purged_by_retention(client, tenant, owner, location_id):
    job = check(client, owner, start(client, owner, location_id, "clients", b"first_name,last_name\r\n,B\r\n"))
    assert job["has_error_report"]
    with tenant_session(tenant.id) as session:
        session.execute(
            text("UPDATE import_job SET expires_at = now() - interval '1 day' WHERE id = :j"), {"j": job["id"]}
        )
    from app.modules.platform import retention

    with tenant_session(tenant.id, actor=system_principal("purge_expired")) as session:
        assert retention.purge(session)["import_job_files"] == 1
    purged = ok(client.get(f"{API}/import-jobs/{job['id']}", headers=owner))
    assert purged["files_purged_at"] and not purged["has_error_report"] and purged["source_file_name"] is None
    assert client.get(f"{API}/import-jobs/{job['id']}/error-report", headers=owner).status_code == 404


# --- side effects: automations, GDPR consent, dry runs, dead letters ------------------------------------------------


def _automation_sends(tenant, client_ids) -> int:
    return scalar(tenant, text(
        "SELECT count(*) FROM scheduled_notification WHERE automation_rule_id IS NOT NULL AND client_id = ANY(:c)"
    ).bindparams(c=[UUID(c) for c in client_ids]))  # fmt: skip


def test_imports_never_start_welcome_automations(client, tenant, owner, location_id, plan):
    from app.modules.memberships.tests.support import deliver_events

    template = ok(client.post(f"{API}/message-templates", headers=owner,
                              json={"name": "Welcome", "subject": "Hi", "body_text": "Welcome"}), 201)  # fmt: skip
    for trigger in ("clients.client.created", "memberships.contract.activated"):
        ok(client.post(f"{API}/automation-rules", headers=owner, json={
            "name": trigger, "trigger_event_type": trigger, "channel": "email", "message_template_id": template["id"],
        }), 201)  # fmt: skip
    run(client, owner, location_id, "clients", [CLIENT_HEADER, ["W-1", "Wren", "Import", "wren@example.com", "", "",
                                                                 "", "", "", "yes"]])  # fmt: skip
    today = clock.now().date()
    later = today + timedelta(days=10)
    header = ["client_member_number", "membership", "start_date", "end_date", "status"]
    done = run(client, owner, location_id, "memberships", [header,
               ["W-1", "Adult Monthly", (today - timedelta(days=30)).isoformat(), (today + timedelta(days=5)).isoformat(),
                "active"],  # ends before the next one starts (contracts may not overlap)
               ["W-1", "Adult Monthly", later.isoformat(), (later + timedelta(days=30)).isoformat(), "upcoming"]])  # fmt: skip
    assert done["created_count"] == 2
    wren = str(scalar(tenant, text("SELECT id FROM client WHERE member_number = 'W-1'")))
    payload = scalar(tenant, text("SELECT payload FROM outbox_event WHERE event_type = 'clients.client.created' "
                                  "AND aggregate_id = :c").bindparams(c=UUID(wren)))  # fmt: skip
    assert payload["source"] == "import" and payload["import_job_id"]
    with (
        tenant_session(tenant.id, actor=system_principal("tests")) as session,
        clock.freeze(clock.now() + timedelta(days=11)),
    ):
        from app.modules import memberships

        memberships.service.run_daily(session)  # the upcoming imported contract starts: still an import
    reasons = {row[0] for row in scalar_rows(tenant, "SELECT payload->>'reason' FROM outbox_event "
                                             "WHERE event_type = 'memberships.contract.activated'")}  # fmt: skip
    assert reasons == {"import"}
    walk_in = new_client(client, owner, location_id, primary_email="walkin@example.com")  # control: a real sign-up
    deliver_events()
    assert _automation_sends(tenant, [wren]) == 0
    assert _automation_sends(tenant, [walk_in["id"]]) == 1


def scalar_rows(tenant, sql: str) -> list:
    with tenant_session(tenant.id) as session:
        return list(session.execute(text(sql)))


def test_gdpr_mode_needs_consent_evidence_and_outside_it_the_basis_is_import(client, tenant, owner, location_id):
    header = ["member_number", "first_name", "last_name", "email", "email_marketing", "consent_date", "consent_source"]
    run(client, owner, location_id, "clients", [header, ["G-0", "Old", "Optin", "old@example.com", "yes", "", ""]])
    with tenant_session(tenant.id) as session:
        old = session.execute(text("SELECT id FROM client WHERE member_number = 'G-0'")).scalar_one()
        basis = session.execute(text("SELECT basis FROM consent_event WHERE client_id = :c"), {"c": old}).scalar_one()
        assert basis == "import" and engagement_subscribed(session, old, "old@example.com")

    ok(client.put(f"{API}/privacy-settings", headers=owner, json={"is_gdpr_mode": True}))
    rows = [header,
            ["G-1", "Proof", "Given", "proof@example.com", "yes", "2025-03-04", "Paper form at sign-up"],  # 2
            ["G-2", "No", "Proof", "noproof@example.com", "yes", "2025-03-04", ""],                      # 3 warning
            ["G-3", "Says", "No", "no@example.com", "no", "", ""]]  # fmt: skip                           # 4 opt-out
    job = check(client, owner, start(client, owner, location_id, "clients", to_csv(rows)))
    assert job["status"] == "validated" and job["has_error_report"]  # a warning is not a failure
    assert report(client, owner, job)[1][:2] == ["3", "Would import with a warning"]
    done = commit(client, owner, job)
    assert (done["created_count"], done["error_count"]) == (3, 0)
    assert outcomes(tenant, done)[3] == ("created", ["consent-evidence-missing"])
    lines = report(client, owner, done)
    assert len(lines) == 2 and lines[1][:3] == ["3", "Imported with a warning", "email_marketing"]
    with tenant_session(tenant.id) as session:
        ids = dict(session.execute(text("SELECT member_number, id FROM client WHERE member_number LIKE 'G-%'")).all())
        events = {r.client_id: r for r in session.execute(text(
            "SELECT client_id, kind, basis, note, occurred_at FROM consent_event WHERE client_id = ANY(:c)"
        ), {"c": list(ids.values())})}  # fmt: skip
        proof = events[ids["G-1"]]
        assert (proof.kind, proof.basis) == ("opt_in", "express") and "Paper form at sign-up" in proof.note
        assert proof.occurred_at.astimezone(ZoneInfo("America/Chicago")).date().isoformat() == "2025-03-04"
        assert ids["G-2"] not in events and events[ids["G-3"]].kind == "opt_out"
        assert engagement_subscribed(session, ids["G-1"], "proof@example.com")
        assert not engagement_subscribed(session, ids["G-2"], "noproof@example.com")
        assert not engagement_subscribed(session, old, "old@example.com")  # an `import` basis is not express


def engagement_subscribed(session, client_id, address) -> bool:
    from app.modules import engagement

    return engagement.service.is_subscribed(session, client_id, "email", "email_campaigns", address)


def test_a_dry_run_leaks_nothing_outside_its_transaction(client, tenant, owner, location_id, mailbox):
    from app.modules import clients

    with tenant_session(tenant.id) as session:
        settings = clients.service.settings_row(session)
        settings.is_member_number_auto_generated, settings.member_number_trigger = True, "client_created"
    rows = [CLIENT_HEADER, ["", "Dee", "Dryden", "dee@example.com", "", "", "", "", "", "yes"],
            ["", "Eli", "Okafor", "eli@example.com", "", "", "", "", "", "yes"]]  # fmt: skip

    def state() -> tuple:
        return (scalar(tenant, text("SELECT coalesce(max(next_value), 0) FROM tenant_counter "
                                    "WHERE counter_key = 'member_number'")),  # member numbers handed out
                scalar(tenant, text("SELECT count(*) FROM outbox_event")),  # events for subscribers
                scalar(tenant, text("SELECT count(*) FROM consent_event")))  # fmt: skip

    mailbox.clear()
    before = state()
    job = check(client, owner, start(client, owner, location_id, "clients", to_csv(rows)))
    assert job["status"] == "validated" and state() == before and not mailbox
    commit(client, owner, job)
    numbers = scalar_rows(tenant, "SELECT member_number FROM client WHERE last_name IN ('Dryden', 'Okafor')")
    assert len(numbers) == 2 and all(n[0] for n in numbers)  # the commit hands them out; the dry run did not
    assert state()[0] == (before[0] or 1) + 2  # gapless: the check consumed none


def test_a_dead_lettered_chunk_stops_the_job_instead_of_running_forever(client, tenant, owner, location_id):
    from app.core.jobs import FailedJobRecorder

    job = start(client, owner, location_id, "clients", to_csv([CLIENT_HEADER, ["", "Fay", "Fail", "", "", "", "",
                                                                                "", "", ""]]))  # fmt: skip
    ok(client.post(f"{API}/import-jobs/{job['id']}/dry-runs", headers=owner, json={}), 202)
    proxy = type("Proxy", (), {"args": (str(tenant.id), job["id"]), "actor_name": "run_import",
                               "queue_name": "default", "message_id": "m", "options": {},
                               "_exception": RuntimeError("boom")})()  # fmt: skip
    FailedJobRecorder().after_nack(broker, proxy)
    stopped = ok(client.get(f"{API}/import-jobs/{job['id']}", headers=owner))
    assert stopped["status"] == "failed" and stopped["finished_at"]
    drain()  # the queued chunk finds a failed job and does nothing
    assert ok(client.get(f"{API}/import-jobs/{job['id']}", headers=owner))["status"] == "failed"


# --- volume --------------------------------------------------------------------------------------------------------


def test_five_thousand_clients_complete_through_the_worker(client, tenant, owner, location_id):
    rows = [["member_number", "first_name", "last_name", "email"]]
    rows += [[f"V-{i}", f"First{i}", f"Volume{i}", f"v{i}@example.com"] for i in range(5000)]
    began = time.monotonic()
    done = run(client, owner, location_id, "clients", rows)
    elapsed = time.monotonic() - began
    assert (done["status"], done["created_count"], done["error_count"]) == ("completed", 5000, 0)
    assert scalar(tenant, text("SELECT count(*) FROM client WHERE last_name LIKE 'Volume%'")) == 5000
    # FH_PERF=1 make test, on an otherwise idle machine; under load it measures the machine, not the code.
    if os.environ.get("FH_PERF") == "1":
        assert elapsed < 180, f"5,000 clients took {elapsed:.0f}s"


# --- review round 2 (findings 1 to 11) ------------------------------------------------------------------------------


def _subscribed(session, client_id, channel, topic, address) -> bool:
    from app.modules import engagement

    return engagement.service.is_subscribed(session, client_id, channel, topic, address)


def test_an_import_never_resubscribes_an_opt_out_or_changes_a_primary_email(client, tenant, owner, location_id):
    out = new_client(client, owner, location_id, first_name="Opal", last_name="Out", member_number="R-1",
                     primary_email="opal@example.com", phone_mobile="+13095550188")  # fmt: skip
    ok(client.put(f"{API}/clients/{out['id']}/communication-preferences", headers=owner, json={
        "note": "Asked at the desk", "changes": [
            {"channel": "email", "address": "opal@example.com", "topic": "email_campaigns", "is_subscribed": False},
            {"channel": "sms", "address": "+13095550188", "topic": "sms_marketing", "is_subscribed": False}]}))  # fmt: skip
    moved = new_client(client, owner, location_id, first_name="Mo", last_name="Ved", member_number="R-2",
                       primary_email="mo@example.com")  # fmt: skip
    header = ["member_number", "first_name", "last_name", "email", "mobile_phone", "email_marketing", "sms_marketing",
              "consent_date", "consent_source"]  # fmt: skip
    today = (clock.now().date() - timedelta(days=1)).isoformat()  # recent, yet the opt-out stands
    job = check(client, owner, start(client, owner, location_id, "clients", to_csv([header,
                ["R-1", "Opal", "Out", "opal@example.com", "+13095550188", "yes", "yes", today, "Paper form"],
                ["R-2", "Mo", "Ved", "mo.new@example.com", "", "yes", "", today, "Paper form"]])))  # fmt: skip
    assert outcomes(tenant, job)[2] == ("valid", ["consent-withheld", "consent-withheld"]), outcomes(tenant, job)
    done = commit(client, owner, job)
    found = outcomes(tenant, done)
    assert found[2] == ("updated", ["consent-withheld", "consent-withheld"])
    assert found[3] == ("updated", ["consent-withheld"])
    assert "opted out" in report(client, owner, done)[1][3]
    with tenant_session(tenant.id) as session:
        assert not _subscribed(session, UUID(out["id"]), "email", "email_campaigns", "opal@example.com")
        assert not _subscribed(session, UUID(out["id"]), "sms", "sms_marketing", "+13095550188")
        emails = dict(session.execute(text("SELECT email, is_primary FROM client_email WHERE client_id = :c"),
                                      {"c": moved["id"]}).all())  # fmt: skip
        assert emails == {"mo@example.com": True, "mo.new@example.com": False}  # kept primary, new one secondary
        primary = session.execute(text("SELECT primary_email FROM client WHERE id = :c"), {"c": moved["id"]}).scalar()
        assert primary == "mo@example.com"
        assert not session.execute(text("SELECT count(*) FROM consent_event WHERE client_id = :c AND kind = 'opt_in'"),
                                   {"c": moved["id"]}).scalar()  # fmt: skip


def test_an_opening_balance_posts_once_however_it_arrives_and_reads_as_an_opening_balance(
    client, tenant, owner, location_id
):
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        billing.service.create_revenue_category(session, code="GEN", label="General", tax_ids=[])
    new_client(client, owner, location_id, primary_email="ob@example.com", member_number="OB-1")
    yesterday = (clock.now().date() - timedelta(days=1)).isoformat()
    header = ["client_member_number", "client_email", "amount", "as_of_date", "direction"]
    first = run(client, owner, location_id, "balances", [header, ["OB-1", "", "40", yesterday, "owed"],
                                                          ["OB-1", "", "25", yesterday, "credit"],
                                                          ["OB-1", "", "100001", yesterday, "owed"]])  # fmt: skip
    assert (first["created_count"], first["error_count"]) == (2, 1)
    assert outcomes(tenant, first)[4] == ("failed", ["amount-too-large"])
    before = counts(tenant)
    # The same balances again, naming the client by email: a new row key, but the same balances.
    again = check(client, owner, start(client, owner, location_id, "balances", to_csv(
        [header, ["", "ob@example.com", "40.00", yesterday, "owed"], ["", "ob@example.com", "25", yesterday, "credit"]])))  # fmt: skip
    assert (again["valid_row_count"], again["skipped_count"]) == (0, 2)
    assert outcomes(tenant, again)[2] == ("skipped", ["already-posted"])
    assert "already posted" in report(client, owner, again)[1][3]
    assert (counts(tenant)["charge"], counts(tenant)["payment"]) == (before["charge"], before["payment"])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        payment = session.execute(text(
            "SELECT p.id, p.external_reference, p.tender_kind, tt.label, tt.is_enabled FROM payment p "
            "JOIN tender_type tt ON tt.id = p.tender_type_id WHERE p.client_id = (SELECT id FROM client "
            "WHERE member_number = 'OB-1')")).one()  # fmt: skip
        assert payment.external_reference == f"import-job:{first['id']}" and payment.tender_kind == "external"
        assert (payment.label, payment.is_enabled) == ("Opening balance", False)  # never offered at the desk
        label = session.execute(text("SELECT tender_label FROM rpt_payment WHERE payment_id = :p"),
                                {"p": payment.id}).scalar()  # fmt: skip
        assert label == "Opening balance"  # the deposits report groups by it, apart from cash taken that day
        changes = session.execute(text("SELECT changes FROM audit_event WHERE action = 'billing.payment.take' "
                                       "AND entity_id = :p"), {"p": payment.id}).scalar()  # fmt: skip
        assert changes["submitted_by_staff_user_id"][1] == str(first["submitted_by_staff_user_id"])
        back = billing.service.refund(session, payment.id, amount_minor=2500, reason="Hand back")
        assert back.status == "succeeded" and back.provider_refund_ref is None  # external hand-back, never a card
        desk = billing.service.take_payment(  # the plain external tender is still the kind's default
            session, client_id=None, location_id=UUID(location_id), amount_minor=100, tender_kind="external",
            origin="pos")  # fmt: skip
        assert session.execute(text("SELECT label FROM tender_type WHERE id = :t"),
                               {"t": desk.tender_type_id}).scalar() != "Opening balance"  # fmt: skip


def _staff_principal(tenant, permissions, location_ids=None):
    from app.core.auth import Principal

    return Principal(kind="staff", tenant_id=tenant.id, elevated=True, permissions={k: "all" for k in permissions},
                     location_ids=location_ids)  # fmt: skip


def test_running_an_import_needs_every_location_and_the_keys_of_its_writes(client, tenant, owner, location_id):
    from app.core.errors import PermissionDenied

    job = check(client, owner, start(client, owner, location_id, "clients", b"first_name,last_name\r\nA,B\r\n"))
    email, _ = add_staff(tenant, "admin", location_ids=[location_id])
    local = login(client, tenant, email)
    assert client.get(f"{API}/import-jobs/{job['id']}", headers=local).status_code == 200  # reading is fine
    for step in ("dry-runs", "commits"):
        refused = client.post(f"{API}/import-jobs/{job['id']}/{step}", headers=local, json={})
        assert (refused.status_code, refused.json()["code"]) == (403, "all-locations-required")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        keys = (*imports.service.KIND_KEYS["clients"], imports.service.RUN)
        here = _staff_principal(tenant, keys, frozenset({UUID(location_id)}))
        with pytest.raises(PermissionDenied) as caught:
            imports.service.start_dry_run(session, here, UUID(job["id"]), {})
        assert caught.value.code == "all-locations-required"
        run_only = _staff_principal(tenant, (imports.service.RUN,))
        with pytest.raises(PermissionDenied) as caught:
            imports.service.start_commit(session, run_only, UUID(job["id"]))
        assert "clients.client.create" in caught.value.detail


def test_a_queued_job_stops_when_its_submitter_loses_the_right(client, tenant, owner, location_id):
    email, staff_id = add_staff(tenant, "admin", all_locations=True)
    admin = login(client, tenant, email)
    job = start(client, admin, location_id, "clients", b"first_name,last_name\r\nA,B\r\n")
    ok(client.post(f"{API}/import-jobs/{job['id']}/dry-runs", headers=admin, json={}), 202)
    ok(client.post(f"{API}/staff-users/{staff_id}/deactivate", headers=owner))
    drain()
    stopped = ok(client.get(f"{API}/import-jobs/{job['id']}", headers=owner))
    assert stopped["status"] == "failed" and "can no longer sign in" in stopped["stop_reason"]
    assert outcomes(tenant, stopped) == {}  # not a row was processed


def test_chunk_size_per_kind_keeps_counter_locks_short(tenant):
    from app.modules import clients

    kinds = imports.kinds.KINDS
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        sizes = {key: imports.service.chunk_rows(session, kind) for key, kind in kinds.items()}
        assert sizes == {"clients": 200, "memberships": 20, "balances": 20, "products": 200}
        settings = clients.service.settings_row(session)
        settings.is_member_number_auto_generated, settings.member_number_trigger = True, "client_created"
        session.flush()
        assert imports.service.chunk_rows(session, kinds["clients"]) == 20  # each row takes the member counter


def test_one_poison_row_fails_alone_and_the_job_carries_on(client, tenant, owner, location_id, monkeypatch):
    kind = imports.kinds.KINDS["products"]
    real = kind.apply

    def flaky(session, data, ctx):
        if data["sku"] == "BAD-1":
            raise KeyError("a bug, not a refusal")
        return real(session, data, ctx)

    monkeypatch.setattr(kind, "apply", flaky)
    header = ["sku", "name", "category", "price"]
    done = run(client, owner, location_id, "products", [header, ["OK-1", "Fine", "Gear", "1"],
                                                         ["BAD-1", "Poison", "Gear", "1"], ["OK-2", "Fine", "Gear", "1"]])  # fmt: skip
    assert (done["status"], done["created_count"], done["error_count"]) == ("completed", 2, 1)
    assert outcomes(tenant, done)[3] == ("failed", ["unexpected"])


def test_a_commit_needs_a_check_of_the_current_file(client, tenant, owner, location_id):
    checked = check(client, owner, start(client, owner, location_id, "clients", b"first_name,last_name\r\nA,B\r\n"))
    other = start(client, owner, location_id, "clients", b"first_name,last_name\r\nC,D\r\n")
    with tenant_session(tenant.id) as session:  # the state a racing upload would leave without the row lock
        session.execute(text("UPDATE import_job SET source_file_id = (SELECT source_file_id FROM import_job "
                             "WHERE id = :o) WHERE id = :j"), {"o": other["id"], "j": checked["id"]})  # fmt: skip
    refused = client.post(f"{API}/import-jobs/{checked['id']}/commits", headers=owner)
    assert (refused.status_code, refused.json()["code"]) == (409, "check-stale")


def test_row_keys_are_keyed_and_rows_are_erased_and_expire(client, tenant, owner, location_id):
    import hashlib

    from app.core import crypto
    from app.modules.platform import privacy, retention

    done = run(client, owner, location_id, "clients", [["member_number", "first_name", "last_name", "email"],
                                                        ["K-1", "Kay", "Keyed", "kay@example.com"]])  # fmt: skip
    with tenant_session(tenant.id) as session:
        key, kay = session.execute(text("SELECT row_key, entity_id FROM import_job_row WHERE import_job_id = :j"),
                                   {"j": done["id"]}).one()  # fmt: skip
    assert key == crypto.mac("import-row\x1fclients\x1fm:K-1")
    assert key != hashlib.sha256(b"clients\x1fm:K-1").hexdigest()
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:  # the erasure handler
        assert privacy.HANDLERS["imports"].erase(session, kay) == {
            "deleted_import_job_rows": 1,
            "purged_import_jobs": 1,
        }
    erased = ok(client.get(f"{API}/import-jobs/{done['id']}", headers=owner))
    assert erased["files_purged_at"] and erased["source_file_name"] is None and outcomes(tenant, done) == {}

    kept = check(client, owner, start(client, owner, location_id, "clients", b"first_name,last_name\r\nA,B\r\n"))
    stuck = start(client, owner, location_id, "clients", b"first_name,last_name\r\nE,F\r\n")
    with tenant_session(tenant.id) as session:
        session.execute(text("UPDATE import_job SET files_purged_at = now() - interval '31 days' WHERE id = :j"),
                        {"j": kept["id"]})  # fmt: skip
        session.execute(text("UPDATE import_job SET status = 'validating', updated_at = now() - interval '2 hours' "
                             "WHERE id = :j"), {"j": stuck["id"]})  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("purge_expired")) as session:
        purged = retention.purge(session)
    assert purged["import_job_rows"] == 1 and outcomes(tenant, kept) == {}
    abandoned = ok(client.get(f"{API}/import-jobs/{stuck['id']}", headers=owner))
    assert abandoned["status"] == "failed" and "progress" in abandoned["stop_reason"]


def test_memberships_refuse_billing_before_the_next_bill_date_and_a_moved_start(
    client, tenant, owner, location_id, plan
):
    from app.core.dates import add_interval
    from app.modules import memberships

    new_client(client, owner, location_id, member_number="NB-1")
    start_on = clock.now().date() - timedelta(days=60)
    next_bill = add_interval(start_on, "month", 3).isoformat()  # a period start, ahead of today
    rows = [["client_member_number", "membership", "start_date", "next_bill_date"],
            ["NB-1", "Adult Monthly", start_on.isoformat(), next_bill]]  # fmt: skip
    with tenant_session(tenant.id) as session:
        memberships.service.settings_row(session).billing_lead_days = 7  # bills a week before each due date
    job = check(client, owner, start(client, owner, location_id, "memberships", to_csv(rows)))
    assert outcomes(tenant, job)[2] == ("invalid", ["bills-before-next-bill-date"])
    with tenant_session(tenant.id) as session:
        memberships.service.settings_row(session).billing_lead_days = 0
        session.execute(text("UPDATE membership_plan SET fixed_start_on = :d WHERE id = :p"),
                        {"d": start_on + timedelta(days=1), "p": plan["id"]})  # fmt: skip
    job = check(client, owner, start(client, owner, location_id, "memberships", to_csv(rows)))
    assert outcomes(tenant, job)[2] == ("invalid", ["plan-fixed-start"])


def test_every_template_example_row_passes_its_own_check_and_names_match_in_nfc(client, tenant, owner, location_id):
    from datetime import UTC, datetime

    with clock.freeze(datetime(2026, 11, 11, 18, tzinfo=UTC)):  # the examples carry 2026 dates
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:
            category = billing.service.create_revenue_category(session, code="MEM", label="Memberships", tax_ids=[])
            category_id = str(category.id)
        kind = ok(client.post(f"{API}/membership-types", headers=owner,
                              json={"name": "Adult", "revenue_category_id": category_id}), 201)  # fmt: skip
        ok(client.post(f"{API}/membership-plans", headers=owner, json={
            "membership_type_id": kind["id"], "name": "Adult monthly", "billing_occurrences_count": 12,
            "term_fee_minor": 4500}), 201)  # fmt: skip
        for key in ("clients", "products", "memberships", "balances"):  # clients first: the others name Sam
            template = client.get(f"{API}/import-templates/{key}", headers=owner).content
            job = check(client, owner, start(client, owner, location_id, key, template))
            assert (job["status"], job["error_count"]) == ("validated", 0), (key, outcomes(tenant, job))
            if key == "clients":
                commit(client, owner, job)
    new_client(client, owner, location_id, first_name="José", last_name="Nfc", primary_email="jose@example.com")
    again = run(client, owner, location_id, "clients", [["first_name", "last_name", "email", "city"],
                                                         ["José", "Nfc", "jose@example.com", "Peoria"]])  # fmt: skip
    assert (again["created_count"], again["updated_count"], again["skipped_count"]) == (0, 1, 0)


def test_an_import_never_confirms_an_age_and_the_row_report_says_so(client, tenant, owner, location_id):
    """Owner decision: no import confirms an age, for anyone, under any flag. Imported adults wait in the age-check
    queue (go-live: its bulk confirm); a row that brought a date says it was imported with the age not confirmed."""
    rows = [CLIENT_HEADER,
            ["", "Ada", "AdultNever", "", "", "1980-02-03", "", "", "", ""],
            ["", "Kit", "ChildNever", "", "", "2016-06-07", "", "", "", ""],
            ["", "Nod", "NodateNever", "", "", "", "", "", "", ""]]  # fmt: skip
    job = check(client, owner, start(client, owner, location_id, "clients", to_csv(rows)))
    ok(client.post(f"{API}/import-jobs/{job['id']}/commits", headers=owner, json={"confirm_ages": True}), 202)
    drain()
    assert ok(client.get(f"{API}/import-jobs/{job['id']}", headers=owner))["created_count"] == 3
    with tenant_session(tenant.id) as session:
        confirmed = session.execute(text(
            "SELECT count(*) FROM client WHERE last_name LIKE '%Never' AND age_confirmed_at IS NOT NULL")).scalar()  # fmt: skip
    assert confirmed == 0
    seen = outcomes(tenant, job)
    assert {n: codes for n, (_, codes) in seen.items()} == {2: ["age-not-confirmed"], 3: ["age-not-confirmed"], 4: []}
    queue = ok(client.get(f"{API}/client-age-reviews", headers=owner, params={"created_via": "import", "limit": 200}))
    assert "AdultNever" in {c["last_name"] for c in queue["data"]}  # a child never enters the queue
    assert "ChildNever" not in {c["last_name"] for c in queue["data"]}
