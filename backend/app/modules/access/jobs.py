"""access jobs. Tenant actors: the body runs inside tenant_session(tenant_id) as the system principal."""

from app.core.jobs import tenant_actor
from app.modules.access import building


@tenant_actor
def run_building_control(session) -> None:
    """Every minute (app.scheduler): door codes in step with bookings, court lights in step with holds. Idempotent:
    it computes the wanted state now and sends only differences, so a repeated or missed tick changes nothing."""
    building.run_building_control(session)
