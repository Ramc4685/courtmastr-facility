"""PAY-05 refunds: the refund row committed before the processor call, the sweep that finishes or cancels it,
the release-then-refund composite, and replays (retry, duplicate webhook) that never refund twice."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.errors import ValidationFailed
from app.modules.billing import webhooks
from app.modules.billing.models import PaymentAllocation, Refund
from app.modules.billing.tests.test_billing import API, assert_books_agree, card, cash, charge, key, svc, work
from app.modules.billing.tests.test_money import ready, transactions
from app.ports import payment_provider
from app.ports.payment_provider import RefundState


def _paid(shop, amount=500):
    with work(shop.tenant) as session:
        return card(session, shop, amount).id


def _provider_refunded(session, payment_id) -> int:
    ref = session.get(svc.Payment, payment_id).provider_payment_ref
    return payment_provider.get("fake")._refunded.get(ref, 0)


def test_a_refund_row_is_committed_before_the_processor_and_a_retry_finishes_it(shop):
    ready(shop)
    payment_id, refund_key = _paid(shop), uuid4().hex
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        svc.refund(session, payment_id, amount_minor=300, reason="Changed plans", idempotency_key=refund_key)
        raise RuntimeError("the process died before commit")
    with work(shop.tenant) as session:
        left = session.scalars(select(Refund)).one()
        assert (left.status, left.idempotency_key, left.provider_refund_ref) == ("initiated", refund_key, None)
        assert session.get(svc.Payment, payment_id).unapplied_minor == 500  # nothing reserved, nothing posted
        posted = transactions(session)
        again = svc.refund(session, payment_id, amount_minor=300, reason="Changed plans", idempotency_key=refund_key)
        assert (again.id, again.status) == (left.id, "succeeded")
        assert session.get(svc.Payment, payment_id).unapplied_minor == 200
        assert transactions(session) == posted + 1
        third = svc.refund(session, payment_id, amount_minor=300, reason="Changed plans", idempotency_key=refund_key)
        assert third.id == left.id and transactions(session) == posted + 1  # a replay posts nothing
        assert _provider_refunded(session, payment_id) == 300  # the card was refunded once
        assert_books_agree(session)


def test_the_sweep_finishes_an_orphan_refund_and_cancels_one_that_never_reached_the_processor(shop, monkeypatch):
    ready(shop)
    first, second = _paid(shop), _paid(shop)
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        svc.refund(session, first, amount_minor=500, reason="Duplicate", idempotency_key="done")
        raise RuntimeError("died after the processor refunded")
    fake = payment_provider.get("fake")
    with monkeypatch.context() as patched, pytest.raises(RuntimeError), work(shop.tenant) as session:
        patched.setattr(fake, "refund", lambda **_: (_ for _ in ()).throw(RuntimeError("no network")))
        svc.refund(session, second, amount_minor=200, reason="Duplicate", idempotency_key="lost")
    with work(shop.tenant) as session:
        assert webhooks.reconcile(session)["refunds"] == 0  # too fresh: the request may still be running
    with clock.freeze(clock.now() + timedelta(minutes=10)), work(shop.tenant) as session:
        assert webhooks.reconcile(session)["refunds"] == 2
        states = dict(session.execute(select(Refund.idempotency_key, Refund.status)).all())
        assert states == {"done": "succeeded", "lost": "initiated"}
        assert session.get(svc.Payment, first).unapplied_minor == 0
    with clock.freeze(clock.now() + timedelta(minutes=45)), work(shop.tenant) as session:
        webhooks.reconcile(session)
        assert session.scalar(select(Refund.status).where(Refund.idempotency_key == "lost")) == "cancelled"
        assert session.get(svc.Payment, second).unapplied_minor == 500  # the cancelled one reserved nothing
        assert webhooks.reconcile(session)["refunds"] == 0
        assert_books_agree(session)


def test_release_then_refund_unpays_the_item_and_refunds_in_one_command(shop):
    ready(shop)
    with work(shop.tenant) as session:
        item = charge(session, shop, 1000)
        payment = card(session, shop, 1083, allocations=[(item.id, 1083)])
        allocation = session.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)).one()
        with pytest.raises(ValidationFailed) as caught:  # plain refund of applied money is still refused
            svc.refund(session, payment.id, amount_minor=600, reason="Cancelled", idempotency_key=uuid4().hex)
        assert caught.value.code == "refund-exceeds-unapplied"
        refund_key = uuid4().hex
        row = svc.refund(
            session, payment.id, amount_minor=600, reason="Cancelled", idempotency_key=refund_key,
            release_allocation_ids=[allocation.id],
        )  # fmt: skip
        assert row.status == "succeeded" and allocation.status == "released"
        assert (payment.unapplied_minor, item.applied_minor) == (483, 0)  # the rest stays as account credit
        replay = svc.refund(
            session, payment.id, amount_minor=600, reason="Cancelled", idempotency_key=refund_key,
            release_allocation_ids=[allocation.id],
        )  # fmt: skip
        assert replay.id == row.id and payment.unapplied_minor == 483  # nothing released or refunded twice
        assert_books_agree(session)


def test_release_then_refund_of_cash_and_its_gate(client, shop, owner):
    with work(shop.tenant) as session:
        item = charge(session, shop, 1000)
        payment = cash(session, shop, 1083, allocations=[(item.id, 1083)])
        allocation_id = session.scalars(
            select(PaymentAllocation.id).where(PaymentAllocation.payment_id == payment.id)
        ).one()
    body = {"amount_minor": 1083, "reason": "Closed for repairs", "release_allocation_ids": [str(allocation_id)]}
    made = client.post(f"{API}/payments/{payment.id}/refunds", headers=owner | key(), json=body)
    assert made.status_code == 201, made.text
    assert (made.json()["status"], made.json()["method"]) == ("succeeded", "external")
    again = client.post(f"{API}/payments/{payment.id}/refunds", headers=owner | key(), json=body)
    assert again.status_code == 409 and again.json()["code"] == "allocation-released"
    other = client.post(
        f"{API}/payments/{payment.id}/refunds", headers=owner | key(),
        json=body | {"release_allocation_ids": [str(uuid4())]},
    )  # fmt: skip
    assert other.status_code == 422


def test_a_duplicate_refund_webhook_posts_once(shop, monkeypatch):
    ready(shop)
    payment_id = _paid(shop)
    fake = payment_provider.get("fake")
    monkeypatch.setattr(fake, "refund", lambda **_: RefundState("fake_ref_dup", "pending"))
    with work(shop.tenant) as session:
        row = svc.refund(session, payment_id, amount_minor=500, reason="Slow bank", idempotency_key=uuid4().hex)
        assert row.status == "pending"
        posted = transactions(session)
    monkeypatch.setattr(fake, "get_refund", lambda **_: RefundState("fake_ref_dup", "succeeded"))
    for _ in range(2):  # the processor delivers the same news twice
        with work(shop.tenant) as session:
            webhooks.apply_event(session, "refund", "fake_ref_dup")
    with work(shop.tenant) as session:
        assert session.get(Refund, row.id).status == "succeeded"
        assert transactions(session) == posted + 1
        assert session.scalar(select(func.count()).select_from(Refund)) == 1
        assert_books_agree(session)
