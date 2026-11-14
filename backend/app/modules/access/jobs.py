"""access jobs. Tenant actors: the body runs inside tenant_session(tenant_id) as the system principal."""

import logging
from uuid import UUID

import dramatiq

from app.core.auth import system_principal
from app.core.db import tenant_session
from app.core.jobs import tenant_actor
from app.modules.access import building

log = logging.getLogger(__name__)


@dramatiq.actor(actor_name="run_building_control")
def run_building_control(tenant_id: str) -> None:
    """Every minute (app.scheduler): door codes in step with bookings, court lights in step with holds. Each
    location's codes and its lights run in their own transaction, so one failing step never rolls back another;
    the next tick retries it. Idempotent: it computes the wanted state now and sends only differences."""
    tenant, actor = UUID(tenant_id), system_principal("run_building_control")
    with tenant_session(tenant, actor=actor) as session:
        steps = building.control_steps(session)
    for location_id, step in steps:
        try:
            with tenant_session(tenant, actor=actor) as session:
                building.run_control_step(session, location_id, step)
        except Exception:
            log.exception("building control step failed", extra={"location_id": str(location_id), "step": step})


@tenant_actor
def mark_code_notified(session, entry_code_id: str) -> None:
    """Called right after the email adapter accepted a code email (not queued: the hand-off has happened)."""
    building.mark_notified(session, entry_code_id)


@tenant_actor
def controller_call(session, entry_code_id: str, op: str, quiet: bool) -> None:
    """Called right after a commit that issued or revoked a code (not queued): one push or revoke of that code."""
    building.controller_call(session, entry_code_id, op, quiet)
