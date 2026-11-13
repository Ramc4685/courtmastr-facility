"""Provider webhooks and the reconciliation sweep (ADR 0003 section 8).

A webhook is verified, stored once (the unique provider event id makes a redelivery a no-op) and routed to
its tenant through the global lookup; the work then happens in a tenant actor. The event is a notification,
never a source of truth: the actor re-reads the object from the provider and applies that state through the
same functions the request path uses, so order of arrival does not matter and a replay changes nothing.
"""

import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import clock, inbound_webhooks
from app.core.errors import DomainError, NotFound
from app.core.jobs import tenant_actor
from app.modules.billing import autopay, methods, service
from app.modules.billing.models import Payment, ProviderAccount, Refund
from app.ports import payment_provider
from app.ports.payment_provider import PaymentState, WebhookRejected

log = logging.getLogger(__name__)
STALE_AFTER = timedelta(minutes=5)  # leave a request that is still running alone
RETRY_ATTEMPTS = 5  # a failed event is tried this many times, then left `failed` for an operator
ABANDON_AFTER = timedelta(minutes=30)  # an `initiated` payment the provider never heard of


def receive(provider_name: str, headers: dict[str, str], body: bytes) -> str:
    """The HTTP side: verify, store, enqueue. Returns what happened, for the log; the provider always gets
    a 2xx for a correctly signed event so it stops redelivering."""
    if not payment_provider.registered(provider_name):
        raise NotFound()
    try:
        event = payment_provider.get(provider_name).parse_webhook(headers, body)
    except WebhookRejected as error:
        raise DomainError("The webhook signature is not valid.", code="invalid-signature", status=400) from error
    stored = inbound_webhooks.record(
        provider_name, event.provider_event_id, event.account_ref, event.event_type,
        {"kind": event.kind, "object": event.object_ref, "account": event.account_ref},
    )  # fmt: skip
    if stored is None:
        return "duplicate"
    row_id, tenant_id = stored
    if tenant_id is None:  # kept as `ignored`, never dropped: an operator can see an unroutable account
        log.warning("webhook for unknown %s account %s", provider_name, event.account_ref)
        return "ignored"
    process_provider_event.send(str(tenant_id), str(row_id))
    return "accepted"


def apply_event(session: Session, kind: str, object_ref: str | None, account_ref: str | None = None) -> None:
    """Bring our row in line with the provider's current state of the object the event names."""
    if not object_ref:
        return
    if kind == "payment":
        payment_id = session.scalar(select(Payment.id).where(Payment.provider_payment_ref == object_ref))
        if payment_id is not None:
            service.confirm_payment(session, payment_id)
    elif kind == "refund":
        refund_id = session.scalar(select(Refund.id).where(Refund.provider_refund_ref == object_ref))
        if refund_id is not None:
            service.confirm_refund(session, refund_id)
    elif kind == "method":
        methods.sync_method(session, object_ref)
    elif kind == "dispute":
        account = session.scalar(select(ProviderAccount).where(ProviderAccount.provider_account_ref == account_ref))
        if account is not None:
            service.sync_dispute(session, account, object_ref)
    elif kind == "account":
        account_id = session.scalar(
            select(ProviderAccount.id).where(ProviderAccount.provider_account_ref == object_ref)
        )
        if account_id is not None:
            methods.refresh_provider_account(session, account_id)


@tenant_actor
def process_provider_event(session: Session, row_id: str) -> None:
    row = inbound_webhooks.get(UUID(row_id))
    if row is None or row.status == "processed":
        return
    try:
        apply_event(session, row.payload.get("kind"), row.payload.get("object"), row.payload.get("account"))
    except Exception as error:
        inbound_webhooks.finish(UUID(row_id), error=str(error)[:500])
        raise
    # Marked only once our transaction has committed: a failed commit leaves the event to be retried.
    session.info.setdefault("after_commit", []).append(lambda: inbound_webhooks.finish(UUID(row_id)))


@tenant_actor
def retry_provider_events(session: Session) -> None:
    """The sweep for a webhook that was stored but never processed (PAY-11): the enqueue after the store
    was lost, or processing failed. Each event is applied here, in its own savepoint, by the same idempotent
    apply_event(), so an event that a worker also picks up changes nothing twice."""
    tenant_id = session.info["tenant_id"]
    for row_id in inbound_webhooks.stale(tenant_id, clock.now() - STALE_AFTER, RETRY_ATTEMPTS):
        row = inbound_webhooks.get(row_id)
        try:
            with session.begin_nested():
                apply_event(session, row.payload.get("kind"), row.payload.get("object"), row.payload.get("account"))
        except Exception as error:  # noqa: BLE001  (recorded on the event; the next sweep tries again)
            log.warning("webhook %s failed again: %s", row_id, error)
            inbound_webhooks.finish(row_id, error=str(error)[:500])
            continue
        session.info.setdefault("after_commit", []).append(lambda done=row_id: inbound_webhooks.finish(done))


def reconcile(session: Session) -> dict:
    """The sweep: finish what a webhook or a dying request left behind. Re-reads every payment that is not in
    a final state and every pending or `initiated` refund; an `initiated` payment or refund the provider has no
    record of after 30 minutes is cancelled. Idempotent; run it as often as you like."""
    now, counts = clock.now(), {"payments": 0, "cancelled": 0, "refunds": 0, "failed": 0}
    unsettled = session.scalars(
        select(Payment.id)
        .where(
            Payment.status.in_(("initiated", "unknown", "requires_action", "processing")),
            Payment.provider_account_id.is_not(None),
            Payment.received_at < now - STALE_AFTER,
        )  # fmt: skip
        .order_by(Payment.received_at)
    ).all()
    for payment_id in unsettled:
        payment = service.confirm_payment(session, payment_id)
        counts["payments"] += 1
        if payment.status == "initiated" and payment.received_at < now - ABANDON_AFTER:
            service._apply_state(session, payment, PaymentState(provider_payment_ref="", outcome="cancelled"))
            counts["cancelled"] += 1
    for refund_id in session.scalars(select(Refund.id).where(Refund.status == "pending")).all():
        done = _isolated(session, refund_id, lambda rid=refund_id: service.confirm_refund(session, rid))
        counts["refunds" if done else "failed"] += 1
    orphans = session.execute(
        select(Refund.id, Refund.created_at).where(Refund.status == "initiated", Refund.created_at < now - STALE_AFTER)
    ).all()
    for refund_id, created_at in orphans:  # a refund whose request died around the processor call (PAY-05)
        abandon = created_at < now - ABANDON_AFTER
        done = _isolated(
            session, refund_id, lambda rid=refund_id, a=abandon: service.resume_refund(session, rid, abandon=a)
        )
        counts["refunds" if done else "failed"] += 1
    return counts


def _isolated(session: Session, refund_id: UUID, work) -> bool:
    """One sweep item in a savepoint: a refund that cannot be reconciled is recorded on its row for staff (the
    payment's refund list shows the message) and the rest of the pass, autopay included, carries on."""
    try:
        with session.begin_nested():
            work()
    except Exception as error:  # noqa: BLE001  (recorded on the row; retried by the next sweep)
        # Error text can carry SQL and its parameters: staff and the log get the code only, never the text.
        code = error.code if isinstance(error, DomainError) else "internal-error"
        log.warning("refund %s could not be reconciled: %s (%s)", refund_id, code, type(error).__name__)
        session.execute(
            update(Refund)
            .where(Refund.id == refund_id)
            .values(failure_message=f"Could not reconcile ({code}); the next sweep tries again.")
        )
        return False
    return True


@tenant_actor
def billing_daily(session: Session) -> None:
    """One tenant's daily billing pass plus the sweep. A scheduler fans this out per tenant."""
    autopay.daily(session)
    reconcile(session)
