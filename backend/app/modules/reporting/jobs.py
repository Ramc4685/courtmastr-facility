"""reporting background jobs: export files are always rendered off the request (ADR 0010 section 5)."""

from uuid import UUID

from app.core.jobs import tenant_actor
from app.modules.reporting import service


@tenant_actor(max_retries=3)
def run_export(session, export_job_id: str) -> None:
    service.render_export(session, UUID(export_job_id))
