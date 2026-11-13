"""integrations background jobs: one webhook delivery attempt per message, rescheduled with backoff."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.jobs import tenant_actor
from app.modules.integrations import service


@tenant_actor(max_retries=0)  # retries are ours (ADR 0007 schedule), not Dramatiq's
def deliver_webhook(session: Session, delivery_id: str) -> None:
    delay = service.attempt_delivery(session, UUID(delivery_id))
    if delay is not None:
        service._enqueue(session, UUID(delivery_id), delay)


@tenant_actor(max_retries=0)
def sweep_webhook_deliveries(session: Session) -> None:
    """Re-enqueue pending deliveries that are due, in case a message was lost (Redis restart).
    The scheduler enqueues this every minute (app/scheduler.py). A duplicate message is harmless:
    attempt_delivery locks and re-checks the row."""
    for delivery_id in service.due_deliveries(session):
        service._enqueue(session, delivery_id)
