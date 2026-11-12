"""imports background job: dry runs and commits run off the request in chunks (core.jobs.chunked_actor)."""

from uuid import UUID

from app.core.jobs import chunked_actor
from app.modules.imports import service


@chunked_actor(max_retries=3)
def run_import(session, import_job_id: str) -> bool:
    return service.run_chunk(session, UUID(import_job_id))
