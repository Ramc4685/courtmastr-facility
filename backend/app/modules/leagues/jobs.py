"""leagues background job: the schedule generator runs off the request, one competition per chunk
(core.jobs.chunked_actor); the schedule run row is its status (LGE-08)."""

from uuid import UUID

from app.core.jobs import chunked_actor, on_dead_letter
from app.modules.leagues import service


@chunked_actor(max_retries=3)
def generate_schedule_job(session, run_id: str) -> bool:
    return service.generate_schedule_chunk(session, UUID(run_id))


@on_dead_letter("generate_schedule_job")
def _generate_dead(session, run_id: str) -> None:
    service.fail_schedule_run(session, UUID(run_id))
