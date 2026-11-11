"""reporting background jobs: export files are always rendered off the request (ADR 0010 section 5), in chunks
(ADR 0008 section 3): the worked example of core.jobs.chunked_actor."""

from uuid import UUID

from app.core.jobs import chunked_actor
from app.modules.reporting import service


@chunked_actor(max_retries=3)
def run_export(session, export_job_id: str) -> bool:
    return service.render_export_chunk(session, UUID(export_job_id))
