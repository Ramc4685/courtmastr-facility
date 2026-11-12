"""Phase 8 T2: GDPR mode settings, DSR deadlines and shorter retention (PLT-16); the tenant export bundle (IMP-04);
report export bytes purged on expiry."""

import csv
import io
import json
import zipfile
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db import Base
from app.core.db.session import tenant_session
from app.core.errors import NotFound
from app.core.jobs import FailedJobRecorder, broker
from app.modules.platform import files, privacy, retention, tenant_export
from app.modules.platform.models import AuthToken, DataSubjectRequest, StoredFile, TenantExport
from app.modules.reporting.tests.test_reporting import drain
from conftest import add_staff, login, new_client

API = "/api/v1"


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def _location(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return ok(client.post(f"{API}/locations", headers=owner, json=body), 201)["id"]


# --- GDPR mode (PLT-16) ---------------------------------------------------------------------------------------


def test_gdpr_mode_is_a_gated_audited_setting(client, tenant, owner):
    assert ok(client.get(f"{API}/privacy-settings", headers=owner)) == {"is_gdpr_mode": False}
    email, _ = add_staff(tenant, "manager", all_locations=True)
    manager = login(client, tenant, email)
    assert client.put(f"{API}/privacy-settings", headers=manager, json={"is_gdpr_mode": True}).status_code == 403
    assert ok(client.put(f"{API}/privacy-settings", headers=owner, json={"is_gdpr_mode": True})) == {
        "is_gdpr_mode": True
    }
    with tenant_session(tenant.id) as session:
        event = session.scalars(select(AuditEvent).where(AuditEvent.action == "platform.security.manage")
                                .order_by(AuditEvent.occurred_at.desc())).first()  # fmt: skip
        assert event.changes == {"is_gdpr_mode": [False, True]}


def test_dsr_carries_its_response_deadline(client, tenant, owner):
    person = new_client(client, owner, _location(client, owner))
    made = ok(client.post(f"{API}/data-subject-requests", headers=owner,
                          json={"client_id": person["id"], "kind": "erasure", "reason": "Asked by email"}), 201)  # fmt: skip
    assert made["status"] == "requested" and not made["is_overdue"]
    created, due = (datetime.fromisoformat(made[k].replace("Z", "+00:00")) for k in ("created_at", "due_at"))
    assert due - created == timedelta(days=30)
    with tenant_session(tenant.id) as session, clock.freeze(clock.now() + timedelta(days=31)):
        assert privacy.view(session.get(DataSubjectRequest, made["id"]))["is_overdue"]  # (sessions expire by then)


def test_gdpr_mode_shortens_sign_in_token_retention(client, tenant, owner):
    now = clock.now()
    with tenant_session(tenant.id) as session:
        session.add(AuthToken(purpose="magic_link", token_hash=uuid4().hex, expires_at=now - timedelta(days=10)))

    def left():
        with tenant_session(tenant.id) as session:
            retention.purge(session)
            return session.scalar(select(func.count()).select_from(AuthToken).where(AuthToken.purpose == "magic_link"))

    assert left() == 1  # ten days old: kept under the 30-day default
    ok(client.put(f"{API}/privacy-settings", headers=owner, json={"is_gdpr_mode": True}))
    assert left() == 0  # GDPR mode keeps them 7 days


# --- tenant export (IMP-04) -----------------------------------------------------------------------------------


def test_tenant_export_is_owner_only_and_needs_step_up(client, tenant):
    email, _ = add_staff(tenant, "admin", all_locations=True)
    assert client.post(f"{API}/tenant-exports", headers=login(client, tenant, email)).status_code == 403
    stale = client.post(f"{API}/tenant-exports", headers=login(client, tenant, elevated=False))
    assert stale.status_code == 403 and stale.json()["code"] == "step-up-required"


def test_tenant_export_builds_a_zip_without_secrets_downloads_and_expires(client, tenant, owner):
    person = new_client(client, owner, _location(client, owner), primary_email=f"x@{tenant.slug}.example.com")
    made = ok(client.post(f"{API}/tenant-exports", headers=owner), 202)
    assert made["status"] == "queued" and made["progress"]["tables_done"] == 0
    busy = client.post(f"{API}/tenant-exports", headers=owner)
    assert busy.status_code == 409 and busy.json()["code"] == "export-in-progress"
    early = client.post(f"{API}/tenant-exports/{made['id']}/download-url", headers=owner)
    assert early.status_code == 409 and early.json()["code"] == "export-not-ready"

    drain()
    done = ok(client.get(f"{API}/tenant-exports/{made['id']}", headers=owner))
    assert done["status"] == "succeeded" and done["expires_at"] and done["row_count"] > 0
    assert done["progress"]["tables_done"] == done["progress"]["tables_total"]
    link = ok(client.post(f"{API}/tenant-exports/{made['id']}/download-url", headers=owner))
    assert link["expires_in"] == files.URL_TTL_SECONDS and "/files/" in link["url"]

    with tenant_session(tenant.id) as session:
        row = session.get(TenantExport, made["id"])
        _, data = files.read(session, row.file_id)
    archive = zipfile.ZipFile(io.BytesIO(data))
    names = set(archive.namelist())
    assert {"manifest.json", "client.csv", "identity.csv", "location.csv"} <= names
    assert not {"auth_session.csv", "auth_token.csv", "mfa_factor.csv", "tenant_export.csv"} & names
    header = next(csv.reader(io.StringIO(archive.read("identity.csv").decode())))
    assert "email" in header and not [c for c in header if "hash" in c or "secret" in c]
    assert person["id"] in archive.read("client.csv").decode()
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["row_counts"]["client"] == 1 and manifest["tenant_id"] == str(tenant.id)

    with clock.freeze(clock.now() + timedelta(days=8)):  # sessions expire by then, so the service is called direct
        with tenant_session(tenant.id) as session, pytest.raises(NotFound):
            tenant_export.download_url(session, system_principal("tests"), row.id)
        assert tenant_export.purge_expired_exports.fn(str(tenant.id)) == 1
        assert tenant_export.purge_expired_exports.fn(str(tenant.id)) == 0  # idempotent
    with tenant_session(tenant.id) as session:
        assert session.get(StoredFile, row.file_id).status != "ready"
        assert session.get(TenantExport, made["id"]).status == "expired"
        actions = set(session.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == row.id)))
    assert {"platform.tenant.export", "platform.tenant.export.complete", "platform.tenant.export.expire"} <= actions


def test_export_cells_cannot_run_as_spreadsheet_formulas():
    assert tenant_export._cell("=SUM(A1)") == "'=SUM(A1)" and tenant_export._cell("Ok") == "Ok"
    assert tenant_export._cell(None) == "" and tenant_export._cell({"a": 1}) == '{"a": 1}'
    assert tenant_export._cell(-5) == "-5"  # numbers are not text a spreadsheet would evaluate


def test_a_dead_lettered_export_says_failed_and_a_stalled_one_frees_the_slot(client, tenant, owner):
    made = ok(client.post(f"{API}/tenant-exports", headers=owner), 202)
    with tenant_session(tenant.id) as session:  # one chunk ran: the row holds a partial zip
        assert tenant_export.export_chunk(session, UUID(made["id"]))
    proxy = type("Proxy", (), {"args": (str(tenant.id), made["id"]), "actor_name": "run_tenant_export",
                               "queue_name": "default", "message_id": uuid4().hex, "options": {},
                               "_exception": RuntimeError("boom")})()  # fmt: skip
    FailedJobRecorder().after_nack(broker, proxy)
    with tenant_session(tenant.id) as session:
        row = session.get(TenantExport, made["id"])
        assert (row.status, row.partial) == ("failed", None) and row.error and row.finished_at

    second = ok(client.post(f"{API}/tenant-exports", headers=owner), 202)  # a failed export no longer blocks
    with tenant_session(tenant.id) as session:
        tenant_export.export_chunk(session, UUID(second["id"]))
    with clock.freeze(clock.now() + tenant_export.STALE_AFTER + timedelta(minutes=1)):
        tenant_export.purge_expired_exports.fn(str(tenant.id))
    with tenant_session(tenant.id) as session:
        row = session.get(TenantExport, second["id"])
        assert (row.status, row.partial) == ("failed", None)
    drain()  # the queued messages find failed rows and stop
    ok(client.post(f"{API}/tenant-exports", headers=owner), 202)


def test_export_pages_a_big_table_by_key_into_numbered_files(client, tenant, owner, monkeypatch):
    location = _location(client, owner)
    people = {new_client(client, owner, location)["id"] for _ in range(3)}
    monkeypatch.setattr(tenant_export, "CHUNK_ROWS", 2)
    made = ok(client.post(f"{API}/tenant-exports", headers=owner), 202)
    drain()
    with tenant_session(tenant.id) as session:
        _, data = files.read(session, session.get(TenantExport, made["id"]).file_id)
    archive = zipfile.ZipFile(io.BytesIO(data))
    rows = [r for name in ("client.csv", "client.2.csv")
            for r in csv.DictReader(io.StringIO(archive.read(name).decode()))]  # fmt: skip
    assert {r["id"] for r in rows} == people and len(rows) == 3  # every row once, none repeated across pages


def test_no_never_audited_or_door_opening_column_is_exported():
    leaked = [f"{t.name}.{c.name}" for t in Base.metadata.tables.values() for c in tenant_export.columns(t)
              if c.info.get("audit") == "never"]  # fmt: skip
    assert leaked == []
    names = {t.name: {c.name for c in tenant_export.columns(t)} for t in Base.metadata.tables.values()}
    assert not {"key_prefix", "previous_key_prefix"} & names["api_key"] and "value" not in names["credential"]
