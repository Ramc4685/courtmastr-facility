"""programs jobs. Tenant actors: the body runs inside tenant_session(tenant_id) as the system principal."""

from app.core.jobs import tenant_actor
from app.modules.programs import checkout, groups, service


@tenant_actor
def expire_registration_holds(session) -> None:
    """Every minute: release basket holds that ran out of time and lapse unclaimed open offers."""
    checkout.expire_holds(session)
    service.lapse_offers(session)


@tenant_actor
def auto_archive_programs(session) -> None:
    """Hourly: archive programs whose auto-archive date has come at their location (REG-05)."""
    groups.auto_archive_due(session)
