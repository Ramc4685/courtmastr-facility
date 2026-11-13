"""integrations background jobs: one webhook delivery attempt per message, rescheduled with backoff; the
accounting sync, one committed day per chunk."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.jobs import chunked_actor, on_dead_letter, tenant_actor
from app.modules.integrations import quickbooks, service


@tenant_actor(max_retries=0)  # retries are ours (ADR 0007 schedule), not Dramatiq's
def deliver_webhook(session: Session, delivery_id: str) -> None:
    delay = service.attempt_delivery(session, UUID(delivery_id))
    if delay is not None:
        service._enqueue(session, UUID(delivery_id), delay)


@tenant_actor(max_retries=0)
def sweep_webhook_deliveries(session: Session) -> None:
    """Re-enqueue pending deliveries that are due, in case a message was lost (Redis restart).
    shortcut: nothing schedules this yet (no periodic scheduler exists); run it from cron or the scheduler
    module when one ships. A duplicate message is harmless: attempt_delivery locks and re-checks the row."""
    for delivery_id in service.due_deliveries(session):
        service._enqueue(session, delivery_id)


@chunked_actor(max_retries=3)
def sync_accounting_job(session: Session, connection_id: str) -> bool:
    """One day per committed chunk; the connection's `settings.sync` is the cursor (quickbooks.sync_chunk)."""
    return quickbooks.sync_chunk(session, UUID(connection_id))


@on_dead_letter("sync_accounting_job")
def _sync_dead(session: Session, connection_id: str) -> None:
    quickbooks.fail_sync(session, UUID(connection_id))
