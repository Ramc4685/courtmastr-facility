"""Phase 8 K2: retention purges and dead letters, on the real Postgres as fh_app."""

from datetime import timedelta
from uuid import uuid4

import pytest
from dramatiq import Worker
from sqlalchemy import func, select, text

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.errors import Conflict
from app.core.events import OutboxEvent, ProcessedEvent
from app.core.idempotency import IdempotencyKey
from app.core.jobs import FailedJobRecorder, broker, tenant_actor
from app.core.settings import get_settings
from app.modules.platform import retention
from app.modules.platform.models import AuthSession, AuthToken, FailedJob, FailedJobResolution
from conftest import login, make_tenant

MARK = "k2.retention"


def _seed(client, tenant) -> None:
    """One row past retention and one inside it, for every purged table, plus an old unpublished event."""
    now, day = clock.now(), timedelta(days=1)
    login(client, tenant), login(client, tenant)  # two auth sessions
    with tenant_session(tenant.id) as session:
        live = session.scalars(select(AuthSession.id).where(AuthSession.revoked_at.is_(None))).first()
        session.execute(
            text("UPDATE auth_session SET revoked_at = :at, revoked_reason = 'sign_out' WHERE id = :id"),
            {"at": now - 91 * day, "id": live},
        )
        for age in (31, 1):
            session.add(AuthToken(purpose="magic_link", token_hash=uuid4().hex, expires_at=now - age * day))
            session.add(IdempotencyKey(scope=MARK, key=uuid4().hex, request_hash="h", status="completed",
                                       expires_at=now + (-1 if age > 1 else 1) * day))  # fmt: skip
            session.add(ProcessedEvent(consumer_name=MARK, event_id=uuid4(), processed_at=now - (age + 15) * day))
            session.add(OutboxEvent(event_type=MARK, aggregate_type="t", aggregate_id=uuid4(), payload={},
                                    occurred_at=now - age * day, published_at=now - age * day))  # fmt: skip
            session.add(AuditEvent(actor_type="system", actor_label=MARK, action=MARK, entity_type="tenant",
                                   entity_id=tenant.id, retain_until_on=(now - (age - 1) * day).date()))  # fmt: skip
        session.add(OutboxEvent(event_type=MARK, aggregate_type="t", aggregate_id=uuid4(), payload={},
                                occurred_at=now - 90 * day))  # fmt: skip


def _left(tenant) -> dict[str, int]:
    with tenant_session(tenant.id) as session:
        return {
            "auth_session": session.scalar(select(func.count()).select_from(AuthSession)),
            "auth_token": session.scalar(select(func.count()).select_from(AuthToken)),
            "idempotency_key": session.scalar(select(func.count()).where(IdempotencyKey.scope == MARK)),
            "outbox_event": session.scalar(select(func.count()).where(OutboxEvent.event_type == MARK)),
            "processed_event": session.scalar(select(func.count()).where(ProcessedEvent.consumer_name == MARK)),
            "audit_event": session.scalar(select(func.count()).where(AuditEvent.action == MARK)),
        }


def _purge(tenant) -> dict[str, int]:
    with tenant_session(tenant.id) as session:
        return retention.purge(session)


def test_purge_removes_only_rows_past_retention_in_its_own_tenant_and_is_idempotent(client, tenant):
    other = make_tenant()
    _seed(client, tenant), _seed(client, other)
    before = _left(tenant)
    assert _purge(tenant) == dict.fromkeys(before, 1)  # one expired row each
    assert _left(tenant) == {name: count - 1 for name, count in before.items()}
    assert _purge(tenant) == dict.fromkeys(before, 0)  # a repeat finds nothing
    assert _left(other) == before  # the other tenant's expired rows are untouched
    with tenant_session(tenant.id) as session:  # an unpublished event survives any age
        unpublished = select(func.count()).where(OutboxEvent.event_type == MARK, OutboxEvent.published_at.is_(None))
        assert session.scalar(unpublished) == 1


def test_purge_is_bounded_per_run(client, tenant, monkeypatch):
    monkeypatch.setattr(get_settings().retention, "batch_rows", 1)
    _seed(client, tenant), _seed(client, tenant)  # two expired rows per table
    assert [_purge(tenant)["processed_event"] for _ in range(3)] == [1, 1, 0]


def test_purge_expired_runs_as_a_tenant_actor(client, tenant):
    _seed(client, tenant)
    for _ in range(2):  # twice, one effect
        retention.purge_expired.send(str(tenant.id))
        _drain(fail_fast=True)
        assert _left(tenant)["processed_event"] == 1


def test_audit_rows_are_deleted_only_through_the_purge_function(tenant):
    """fh_app keeps SELECT, INSERT on audit_event; the definer function is its only delete path."""
    with tenant_session(tenant.id) as session:
        grants = session.execute(text(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = 'fh_app' AND table_name = 'audit_event'"
        )).scalars().all()  # fmt: skip
        callers = session.execute(text(
            "SELECT grantee FROM information_schema.routine_privileges "
            "WHERE routine_schema = 'app' AND routine_name = 'purge_audit_event'"
        )).scalars().all()  # fmt: skip
    assert sorted(grants) == ["INSERT", "SELECT"]
    assert set(callers) - {"fh_owner"} == {"fh_app"}


# --- dead letters ----------------------------------------------------------------------------------------------


@tenant_actor
def k2_always_fails(session, thing_id: str) -> None:
    raise RuntimeError("boom\nDETAIL: a row value that must not be stored")


def _drain(*, fail_fast: bool) -> None:
    worker = Worker(broker, worker_timeout=100)
    worker.start()
    try:
        broker.join("default", fail_fast=fail_fast, timeout=60_000)
        worker.join()
    finally:
        worker.stop()
        broker.dead_letters_by_queue.clear()  # later drains in this process join with fail_fast


def test_a_message_that_exhausts_its_retries_lands_in_failed_job_once(tenant):
    other = make_tenant()
    thing = str(uuid4())
    message = k2_always_fails.send(str(tenant.id), thing)
    _drain(fail_fast=False)
    with tenant_session(tenant.id) as session:
        row = session.scalars(select(FailedJob).where(FailedJob.actor_name == "k2_always_fails")).one()
    assert (row.message_id, row.queue, row.args, row.attempts) == (message.message_id, "default", [thing], 1)
    assert (row.error_class, row.error_detail, row.resolved_at) == ("RuntimeError", "boom", None)
    with tenant_session(other.id) as session:
        assert session.scalar(select(func.count()).select_from(FailedJob)) == 0

    # one row per message: a second rejection of the same message (a redelivery) adds nothing
    proxy = type("Proxy", (), {"args": (str(tenant.id), thing), "actor_name": "k2_always_fails",
                               "queue_name": "default", "message_id": message.message_id, "options": {},
                               "_exception": RuntimeError("again")})()  # fmt: skip
    FailedJobRecorder().after_nack(broker, proxy)
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).where(FailedJob.message_id == message.message_id)) == 1


def test_an_operator_requeues_or_discards_a_dead_letter_once(tenant):
    for _ in range(2):
        k2_always_fails.send(str(tenant.id), str(uuid4()))
    _drain(fail_fast=False)
    with tenant_session(tenant.id, actor=system_principal("operator-cli")) as session:
        requeue, discard = (row.id for row in retention.open_failed_jobs(session))
        retention.resolve_failed_job(session, requeue, FailedJobResolution.REQUEUED)
        retention.resolve_failed_job(session, discard, FailedJobResolution.DISCARDED)
    with tenant_session(tenant.id, actor=system_principal("operator-cli")) as session:
        with pytest.raises(Conflict):
            retention.resolve_failed_job(session, discard, FailedJobResolution.REQUEUED)
        assert retention.open_failed_jobs(session) == []
        actions = session.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "failed_job")).all()
    assert sorted(actions) == ["platform.failed_job.discarded", "platform.failed_job.requeued"]

    _drain(fail_fast=False)  # the requeued message ran again, failed again, and is a new dead letter
    with tenant_session(tenant.id) as session:
        again = retention.open_failed_jobs(session)
        original = session.get(FailedJob, requeue)
    assert len(again) == 1 and again[0].args == original.args and again[0].message_id != original.message_id
