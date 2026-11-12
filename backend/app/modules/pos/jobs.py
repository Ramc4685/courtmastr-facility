"""pos background jobs, run hourly by the clock (app/scheduler.py)."""

from app.core.jobs import tenant_actor
from app.modules.pos import sales


@tenant_actor
def abandon_stale_drafts(session) -> None:
    """Idempotent: only drafts idle for a day move to abandoned, rows are locked SKIP LOCKED, and a repeat
    finds nothing left to do."""
    sales.abandon_stale_drafts(session)
