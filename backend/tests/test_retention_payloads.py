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


def test_finished_inbound_payloads_are_emptied_after_90_days(tenant):
    """Terminal events only: processed, ignored, and failed at the retry cap lose payload and error text after
    90 days. A failure the sweep would still retry keeps both, however old, as does a recent failure."""
    processed, ignored, recent, failed, recent_failed, retryable = (
        _event("processed", 91, tenant.id), _event("ignored", 91), _event("processed", 89, tenant.id),
        _event("failed", 91, tenant.id), _event("failed", 1, tenant.id), _event("failed", 91, tenant.id),
    )  # fmt: skip
    with platform_engine().begin() as conn:
        conn.execute(text("UPDATE inbound_webhook_event SET error = 'card declined for j@x.io' WHERE id IN (:a, :b, :c)"),
                     {"a": failed, "b": recent_failed, "c": retryable})  # fmt: skip
        conn.execute(text("UPDATE inbound_webhook_event SET attempt_count = :n WHERE id IN (:a, :b)"),
                     {"n": inbound_webhooks.RETRY_ATTEMPTS, "a": failed, "b": recent_failed})  # fmt: skip
        conn.execute(text("UPDATE inbound_webhook_event SET attempt_count = 1 WHERE id = :c"), {"c": retryable})
    assert inbound_webhooks.purge_payloads() >= 3
    assert _payload(processed) == {} and _payload(ignored) == {} and _payload(failed) == {}
    assert _error(failed) is None
    assert _payload(recent) and _payload(recent_failed) and _error(recent_failed)
    assert _payload(retryable) and _error(retryable)  # stale() still hands it to the sweep
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
