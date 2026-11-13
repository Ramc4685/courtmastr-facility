"""security-baseline 2.3 retention: message bodies go after 90 days (the row and its counts stay), and processed
inbound provider payloads are emptied after 90 days (ADR 0007 section 9) (the row stays, so a late duplicate is still deduplicated)."""

import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, text

from app import scheduler
from app.core import clock, inbound_webhooks
from app.core.db.platform import platform_engine
from app.core.db.session import tenant_session
from app.modules.engagement.models import Message
from app.modules.platform import retention
from app.scheduler import tick_hour


def _message(session, *, days_old: int, status: str = "sent") -> Message:
    row = Message(channel="email", category="transactional", to_address=f"m-{uuid4().hex[:6]}@example.com",
                  subject="Your booking", body_text="Hi Jane, see you at 6pm.", status=status,
                  queued_at=clock.now() - timedelta(days=days_old))  # fmt: skip
    session.add(row)
    session.flush()
    return row


def test_message_bodies_are_nulled_after_90_days_and_the_rows_stay(tenant):
    with tenant_session(tenant.id) as session:
        old, recent, stuck = (
            _message(session, days_old=91),
            _message(session, days_old=89),
            _message(session, days_old=91, status="queued"),
        )
        ids = old.id, recent.id, stuck.id
    with tenant_session(tenant.id) as session:
        assert retention.purge(session)["engagement_message_bodies"] >= 1
    with tenant_session(tenant.id) as session:
        rows = {m.id: m for m in session.scalars(select(Message).where(Message.id.in_(ids)))}
        assert rows[ids[0]].body_text is None and rows[ids[0]].subject == "Your booking"  # the row and counts stay
        assert rows[ids[1]].body_text  # inside the 90 days
        assert rows[ids[2]].body_text  # not sent yet: the body is still needed
    with tenant_session(tenant.id) as session:
        assert retention.purge(session)["engagement_message_bodies"] == 0  # idempotent


def _event(status: str, days_old: int, tenant_id=None):
    row = inbound_webhooks.record("fake", f"evt-ret-{uuid4().hex}", None, "charge.succeeded", {"email": "j@x.io"})
    with platform_engine().begin() as conn:
        conn.execute(
            text("UPDATE inbound_webhook_event SET status = :s, tenant_id = :t, received_at = :at, processed_at = :at"
                 " WHERE id = :id"),
            {"s": status, "t": tenant_id, "at": clock.now() - timedelta(days=days_old), "id": row[0]},
        )  # fmt: skip
    return row[0]


def _payload(row_id):
    with platform_engine().connect() as conn:
        value = conn.execute(text("SELECT payload FROM inbound_webhook_event WHERE id = :id"), {"id": row_id}).scalar()
    return value if isinstance(value, dict) else json.loads(value)


def _error(row_id):
    with platform_engine().connect() as conn:
        return conn.execute(text("SELECT error FROM inbound_webhook_event WHERE id = :id"), {"id": row_id}).scalar()


def _row(row_id):
    with platform_engine().connect() as conn:
        return conn.execute(text("SELECT status, attempt_count FROM inbound_webhook_event WHERE id = :id"),
                            {"id": row_id}).one()  # fmt: skip


def _suspend(tenant_id, status: str) -> None:
    with platform_engine().begin() as conn:
        conn.execute(text("UPDATE tenant SET status = :s WHERE id = :id"), {"s": status, "id": tenant_id})


def test_finished_inbound_payloads_are_emptied_after_90_days(tenant):
    """Past the window every event loses payload and error text, whatever its status, attempt count or tenant
    state. A failed or never-processed event is made terminal (attempt count at the cap) in the same statement,
    so the retry sweep never picks up an emptied event. Inside the window a failure keeps both and is retried."""
    processed, ignored, recent = (
        _event("processed", 91, tenant.id),
        _event("ignored", 91),
        _event("processed", 89, tenant.id),
    )
    failed_once, recent_failed, never_run = (
        _event("failed", 91, tenant.id),
        _event("failed", 1, tenant.id),
        _event("received", 91, tenant.id),
    )
    with platform_engine().begin() as conn:
        conn.execute(text("UPDATE inbound_webhook_event SET error = 'card declined for j@x.io', attempt_count = 1 "
                          "WHERE id IN (:a, :b, :c)"), {"a": failed_once, "b": recent_failed, "c": processed})  # fmt: skip
    _suspend(tenant.id, "suspended")  # its sweep never runs; the purge must not depend on it
    try:
        assert inbound_webhooks.purge_payloads() >= 4
    finally:
        _suspend(tenant.id, "active")
    for gone in (processed, ignored, failed_once, never_run):
        assert _payload(gone) == {} and _error(gone) is None, gone
    assert _row(processed) == ("processed", 1) and _row(ignored).status == "ignored"
    assert _row(failed_once) == ("failed", inbound_webhooks.RETRY_ATTEMPTS)
    assert _row(never_run) == ("failed", inbound_webhooks.RETRY_ATTEMPTS)
    stale = inbound_webhooks.stale(tenant.id, clock.now(), inbound_webhooks.RETRY_ATTEMPTS)
    assert failed_once not in stale and never_run not in stale  # never retried
    assert recent_failed in stale and _payload(recent_failed) and _error(recent_failed)  # kept, and retried
    assert _payload(recent)
    assert inbound_webhooks.purge_payloads() == 0  # idempotent
    with platform_engine().connect() as conn:
        event_id = conn.execute(text("SELECT provider_event_id FROM inbound_webhook_event WHERE id = :id"),
                                {"id": processed}).scalar()  # fmt: skip
    assert inbound_webhooks.record("fake", event_id, None, "x", {}) is None  # the emptied row still deduplicates


def test_the_hourly_tick_runs_the_inbound_purge(tenant, monkeypatch):
    calls = []
    monkeypatch.setattr(inbound_webhooks, "purge_payloads", lambda: calls.append(1) or 0)
    monkeypatch.setattr(scheduler, "enqueue", lambda names, tenant_ids: 0)  # nothing left in the shared broker
    tick_hour()
    assert calls == [1]


def test_a_failing_inbound_purge_does_not_skip_the_hour(tenant, monkeypatch, caplog):
    def boom():
        raise RuntimeError("database gone")

    sent = []
    monkeypatch.setattr(inbound_webhooks, "purge_payloads", boom)
    monkeypatch.setattr(scheduler, "enqueue", lambda names, tenant_ids: sent.append(tuple(names)) or 0)
    tick_hour()
    assert scheduler.EVERY_HOUR in sent  # the tenants' jobs still went out
    assert "inbound payload purge failed" in caplog.text
