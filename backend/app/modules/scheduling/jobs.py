"""scheduling jobs. Tenant actors: the body runs inside tenant_session(tenant_id) as the system principal."""

from uuid import UUID

from app.core.jobs import tenant_actor
from app.modules.scheduling import service


@tenant_actor
def generate_series(session, run_id: str) -> None:
    """One chunk of a long series per message, each in its own transaction; re-enqueues itself until the
    run is done (ADR 0004 section 6). Redelivery is harmless: progress is in the run row."""
    if service.run_generation_chunk(session, UUID(run_id)):
        tenant_id = str(session.info["tenant_id"])
        session.info.setdefault("after_commit", []).append(lambda: generate_series.send(tenant_id, run_id))


@tenant_actor
def expire_checkout_holds(session) -> None:
    """Reaper for tentative bookings whose checkout clock ran out (ADR 0004 section 9)."""
    service.expire_holds(session)
