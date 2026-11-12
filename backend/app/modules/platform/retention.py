"""Retention purges (ADR 0007 section 9, ADR 0008 section 4 `platform.purge_expired`, security-baseline 2.3).

Every table here is tenant-owned, so the purge is a @tenant_actor run hourly per tenant by the clock: RLS keeps
each delete inside its tenant and fh_platform gains nothing (ADR 0007 open question 4, second option). Each table
loses at most `retention.batch_rows` rows per run; a backlog drains over later ticks. Idempotent: a repeat
deletes only what became eligible in between. Periods are in config `retention`; a tenant in GDPR mode (PLT-16)
gets the shorter `gdpr_*` periods for sessions and sign-in links. Audit rows keep their fixed retain_until_on.

Not purged here: unpublished outbox rows (never), report result bytes (`reporting.jobs.purge_expired_results`),
tenant export bundles (`platform.tenant_export.purge_expired_exports`), webhook deliveries and inbound provider
events (their owning contexts; not built yet).
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.errors import Conflict, NotFound
from app.core.jobs import broker, tenant_actor
from app.core.settings import get_settings
from app.modules.platform.models import FailedJob, FailedJobResolution, Tenant

# table -> rows past retention. shortcut: outbox published_at and processed_event processed_at have no index, so
# each run scans the tenant's rows; add partial indexes when the purge shows up in the slow-query log.
_PAST_RETENTION = {
    "auth_session": "absolute_expires_at < :sessions OR idle_expires_at < :sessions OR revoked_at < :sessions",
    "auth_token": "expires_at < :tokens OR consumed_at < :tokens",
    "idempotency_key": "expires_at <= :now",
    "outbox_event": "published_at < :outbox",  # NULL (unpublished) never matches
    "processed_event": "processed_at < :processed",
}


def purge(session: Session) -> dict[str, int]:
    """Delete one batch per table in the session's tenant; returns rows deleted per table."""
    cfg = get_settings().retention
    now = clock.now()
    gdpr = session.scalar(select(Tenant.is_gdpr_mode).where(Tenant.id == session.info["tenant_id"]))  # PLT-16
    params = {
        "now": now,
        "sessions": now - timedelta(days=cfg.gdpr_auth_session_days if gdpr else cfg.auth_session_days),
        "tokens": now - timedelta(days=cfg.gdpr_auth_token_days if gdpr else cfg.auth_token_days),
        "outbox": now - timedelta(days=cfg.outbox_days),
        "processed": now - timedelta(days=cfg.processed_event_days),
        "n": cfg.batch_rows,
    }
    deleted = {}
    for table, where in _PAST_RETENTION.items():
        sql = f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} WHERE {where} LIMIT :n FOR UPDATE SKIP LOCKED)"
        deleted[table] = session.execute(text(sql), params).rowcount
    # Append-only: fh_app cannot delete audit rows, only call the owner's function, which removes rows whose
    # retain_until_on (24 months, or 7 years for the long class, fixed at insert) has passed (migration 1210).
    deleted["audit_event"] = session.execute(text("SELECT app.purge_audit_event(:n)"), params).scalar_one()
    return deleted


@tenant_actor
def purge_expired(session: Session) -> None:
    purge(session)


# --- dead letters (ADR 0008 section 7) -------------------------------------------------------------------------


def open_failed_jobs(session: Session) -> list[FailedJob]:
    """Operator tooling (`python -m app.cli failed-jobs`), not a staff route: unresolved, newest first."""
    return list(session.scalars(select(FailedJob).where(FailedJob.resolved_at.is_(None)).order_by(FailedJob.id.desc())))


def resolve_failed_job(session: Session, failed_job_id: UUID, resolution: FailedJobResolution) -> FailedJob:
    """Requeue (send the same actor and args again, after commit; safe because actors are idempotent) or discard.
    A row is resolved once; its message id stays, so a requeued message that fails again is a new row."""
    row = session.scalars(select(FailedJob).where(FailedJob.id == failed_job_id).with_for_update()).one_or_none()
    if row is None:
        raise NotFound()
    if row.resolved_at is not None:
        raise Conflict("This dead letter is already resolved.")
    row.resolved_at, row.resolution = clock.now(), resolution
    if resolution == FailedJobResolution.REQUEUED:
        actor, args = broker.get_actor(row.actor_name), [str(session.info["tenant_id"]), *row.args]
        session.info.setdefault("after_commit", []).append(lambda: actor.send(*args))
    session.flush()
    audit.record(session, f"platform.failed_job.{resolution}", row, changes={"resolution": resolution})
    return row
