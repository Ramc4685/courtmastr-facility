"""access jobs. Tenant actors: the body runs inside tenant_session(tenant_id) as the system principal."""

from app.core.jobs import tenant_actor
from app.modules.access import building


@tenant_actor
def run_building_control(session) -> None:
    """Every minute (app.scheduler): door codes in step with bookings, court lights in step with holds. Idempotent:
    it computes the wanted state now and sends only differences, so a repeated or missed tick changes nothing."""
    building.run_building_control(session)


@tenant_actor
def mark_code_notified(session, entry_code_id: str) -> None:
    """Called right after the email adapter accepted a code email (not queued: the hand-off has happened)."""
    building.mark_notified(session, entry_code_id)
