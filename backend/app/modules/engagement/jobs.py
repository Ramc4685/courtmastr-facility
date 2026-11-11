"""Periodic engagement work, run every minute by the clock (app/scheduler.py). Both are idempotent: rows are
locked with SKIP LOCKED and move out of their due state in the same transaction."""

from app.core.jobs import tenant_actor
from app.modules.engagement import service


@tenant_actor
def send_due_messages(session) -> None:
    """Scheduled campaigns whose time has come, then due reminders and delayed automations."""
    service.send_due_campaigns(session)
    service.send_due_notifications(session)
