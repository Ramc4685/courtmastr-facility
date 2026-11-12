"""The chunked export (core.jobs.chunked_actor's worked example): one chunk per message, progress on the job row,
and a crash mid-chunk loses nothing that committed."""

from uuid import UUID

import pytest

from app.core.db.session import tenant_session
from app.modules.reporting import service
from app.modules.reporting.domain import csv_file
from app.modules.reporting.models import ExportJob, ReportRun
from app.modules.reporting.tests.test_reporting import API, drain, ok, ran, world  # noqa: F401  (world: fixture)


def _job(tenant, job_id) -> ExportJob:
    with tenant_session(tenant.id) as session:
        job = session.get(ExportJob, job_id)
        session.expunge(job)
        return job


@pytest.mark.usefixtures("world")  # the charges the revenue report reads
def test_an_export_resumes_from_its_row_after_a_crash_and_matches_a_one_shot_render(client, tenant, owner, monkeypatch):
    monkeypatch.setattr(service, "EXPORT_CHUNK_ROWS", 1)  # summary row plus two detail rows: three chunks
    done = ran(client, owner, "revenue_summary", period="last_30_days")
    body = {"report_run_id": done["id"], "includes_details": True}
    job_id = UUID(ok(client.post(f"{API}/export-jobs", headers=owner, json=body), 202)["id"])

    with tenant_session(tenant.id) as session:  # the first chunk commits
        assert service.render_export_chunk(session, job_id) is True
    first = _job(tenant, job_id)
    assert (first.status, first.progress) == ("running", {"next": 1, "total": 3})

    real_body = csv_file.body

    def crash(*args):
        raise RuntimeError("worker killed mid-chunk")

    monkeypatch.setattr(csv_file, "body", crash)
    with pytest.raises(RuntimeError), tenant_session(tenant.id) as session:
        service.render_export_chunk(session, job_id)
    monkeypatch.setattr(csv_file, "body", real_body)
    after_crash = _job(tenant, job_id)
    assert (after_crash.progress, after_crash.partial) == (first.progress, first.partial)  # rolled back whole

    drain()  # the message queued at creation resumes from the row and re-sends itself until done
    finished = _job(tenant, job_id)
    assert (finished.status, finished.progress, finished.partial) == ("succeeded", {"next": 3, "total": 3}, None)

    with tenant_session(tenant.id) as session:
        snapshot = service._read_snapshot(session, session.get(ReportRun, finished.report_run_id))
    one_shot = (
        csv_file.render(snapshot["columns"], snapshot["rows"], currency="USD")
        + b"\r\n"
        + (csv_file.render(snapshot["detail_columns"], snapshot["details"], currency="USD")[len(csv_file.BOM) :])
    )
    download = client.get(f"{API}/export-jobs/{job_id}/download", headers=owner)
    assert download.status_code == 200 and download.content == one_shot

    with tenant_session(tenant.id) as session:  # a late duplicate message changes nothing
        assert service.render_export_chunk(session, job_id) is False
