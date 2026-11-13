"""reporting background jobs: export files are always rendered off the request (ADR 0010 section 5), in chunks
(ADR 0008 section 3): the worked example of core.jobs.chunked_actor. Expired result bytes are purged hourly."""

from uuid import UUID

from app.core.jobs import chunked_actor, tenant_actor
from app.modules.reporting import schedules, service


@chunked_actor(max_retries=3)
def run_export(session, export_job_id: str) -> bool:
    return service.render_export_chunk(session, UUID(export_job_id))


@tenant_actor
def purge_expired_results(session) -> int:
    return service.purge_expired_results(session)


@chunked_actor(max_retries=3)
def run_report_schedules(session) -> bool:
    """Hourly per tenant (app/scheduler.py): one due schedule per message, re-sent until none is due."""
    return schedules.run_due_schedule(session)
