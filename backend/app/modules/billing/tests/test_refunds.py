"""PAY-05 refunds: the refund row committed before the processor call, the sweep that finishes or cancels it,
the release-then-refund composite, and replays (retry, duplicate webhook) that never refund twice."""

import importlib
import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text

from app.core import clock, idempotency
from app.core.errors import Conflict, ValidationFailed
from app.core.settings import get_settings
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
        assert session.get(svc.Payment, payment_id).unapplied_minor == 200  # reserved, not yet posted
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


def test_a_refund_that_loses_the_key_race_is_told_to_retry(client, shop, owner, monkeypatch):
    ready(shop)
    payment_id = _paid(shop)
    headers, body = owner | key(), {"amount_minor": 100, "reason": "Changed plans"}
    assert client.post(f"{API}/payments/{payment_id}/refunds", headers=headers, json=body).status_code == 201
    monkeypatch.setattr(idempotency, "begin", lambda *_: None)  # the HTTP claim expired (24 h) or was bypassed
    monkeypatch.setattr(svc, "_refund_by_key", lambda *_: None)  # and the twin committed after our replay lookup
    lost = client.post(f"{API}/payments/{payment_id}/refunds", headers=headers, json=body)
    assert (lost.status_code, lost.json()["code"]) == (409, "request-in-progress")
    with work(shop.tenant) as session:
        assert _provider_refunded(session, payment_id) == 100  # the loser never reached the processor


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


def test_a_refund_key_is_bound_to_its_payment_and_its_request(shop, monkeypatch):
    ready(shop)
    first, second = _paid(shop), _paid(shop)
    refund_key = uuid4().hex
    with work(shop.tenant) as session:
        made_id = svc.refund(session, first, amount_minor=200, reason="Duplicate", idempotency_key=refund_key).id
    fake = payment_provider.get("fake")
    calls = []
    monkeypatch.setattr(fake, "refund", lambda **kw: calls.append(kw))
    for target, over in ((second, {}), (first, {"amount_minor": 300}), (first, {"method": "external"})):
        with pytest.raises(Conflict) as caught, work(shop.tenant) as session:
            svc.refund(
                session, target, **({"amount_minor": 200, "reason": "Duplicate"} | over), idempotency_key=refund_key
            )
        assert caught.value.code == "idempotency-key-reused"
    assert calls == []  # nothing reached the processor
    with work(shop.tenant) as session:
        assert session.get(svc.Payment, second).unapplied_minor == 500  # nothing refunded on the other payment
        replay = svc.refund(session, first, amount_minor=200, reason="Duplicate", idempotency_key=refund_key)
        assert replay.id == made_id and calls == []  # the same request replays the stored result


def test_a_key_reused_on_another_payment_releases_nothing(shop):
    ready(shop)
    refund_key = uuid4().hex
    with work(shop.tenant) as session:
        svc.refund(session, card(session, shop, 500).id, amount_minor=100, reason="x", idempotency_key=refund_key)
        item = charge(session, shop, 1000)
        other = card(session, shop, 1083, allocations=[(item.id, 1083)])
        allocation = session.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == other.id)).one()
        with pytest.raises(Conflict):
            svc.refund(
                session, other.id, amount_minor=100, reason="x", idempotency_key=refund_key,
                release_allocation_ids=[allocation.id],
            )  # fmt: skip
        assert allocation.status == "applied" and item.applied_minor == 1083


def test_release_then_refund_of_too_much_leaves_no_started_row(shop):
    """More than the unapplied remainder plus what is released is refused before the `initiated` row is written."""
    ready(shop)
    with work(shop.tenant) as session:
        item = charge(session, shop, 1000)
        payment = card(session, shop, 1083, allocations=[(item.id, 1083)])
        allocation = session.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)).one()
        payment_id, allocation_id = payment.id, allocation.id
    with pytest.raises(ValidationFailed) as caught, work(shop.tenant) as session:
        svc.refund(
            session, payment_id, amount_minor=1084, reason="Too much", idempotency_key=uuid4().hex,
            release_allocation_ids=[allocation_id],
        )  # fmt: skip
    assert caught.value.code == "refund-exceeds-unapplied"
    with work(shop.tenant) as session:
        assert session.scalar(select(func.count()).select_from(Refund)) == 0
        assert session.get(PaymentAllocation, allocation_id).status == "applied"


def _applied(shop, amount=1083):
    with work(shop.tenant) as session:
        item = charge(session, shop, 1000)
        payment = card(session, shop, amount, allocations=[(item.id, amount)])
        allocation = session.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)).one()
        return item.id, payment.id, allocation.id


def test_a_composite_refund_that_dies_after_the_processor_is_reconciled_by_the_sweep(shop):
    ready(shop)
    item_id, payment_id, allocation_id = _applied(shop)
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        svc.refund(
            session, payment_id, amount_minor=600, reason="Closed", idempotency_key="crash",
            release_allocation_ids=[allocation_id],
        )  # fmt: skip
        raise RuntimeError("died after the processor refunded")
    with work(shop.tenant) as session:
        row = session.scalars(select(Refund)).one()
        assert (row.status, row.release_allocation_ids) == ("initiated", [allocation_id])
        assert session.get(PaymentAllocation, allocation_id).status == "applied"  # the release rolled back
    with clock.freeze(clock.now() + timedelta(minutes=10)), work(shop.tenant) as session:
        assert webhooks.reconcile(session)["refunds"] == 1
        assert session.scalar(select(Refund.status)) == "succeeded"
        assert session.get(PaymentAllocation, allocation_id).status == "released"
        assert session.get(svc.Charge, item_id).applied_minor == 0  # the invoice is open again
        assert session.get(svc.Payment, payment_id).unapplied_minor == 483
        assert_books_agree(session)


def test_an_initiated_refund_reserves_its_amount_and_the_sweep_covers_a_shortfall(shop):
    """A plain refund's money cannot be spent while it is `initiated`; if the remainder is gone anyway (applied
    by hand before the reservation existed), the sweep releases the newest allocations to cover it."""
    ready(shop)
    payment_id = _paid(shop, 500)
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        svc.refund(session, payment_id, amount_minor=300, reason="Changed plans", idempotency_key="reserve")
        raise RuntimeError("died after the processor refunded")
    with work(shop.tenant) as session:
        assert session.get(svc.Payment, payment_id).unapplied_minor == 200  # 300 is reserved
        item = charge(session, shop, 1000)
        assert svc.spend_credit(session, shop.client_id, allocations=None) == 200  # the reserved 300 stays put
        assert_books_agree(session)
        # simulate money applied behind the reservation's back: the sweep must still balance
        session.execute(svc.update(Refund).values(amount_minor=400))
    with clock.freeze(clock.now() + timedelta(minutes=10)), work(shop.tenant) as session:
        webhooks.reconcile(session)
        row = session.scalars(select(Refund)).one()
        assert row.status == "succeeded"
        assert session.get(svc.Charge, item.id).applied_minor == 0  # released to cover the refund
        assert_books_agree(session)


def test_one_unreconcilable_refund_does_not_stop_the_sweep(shop):
    ready(shop)
    bad, good = _paid(shop, 500), _paid(shop, 500)
    for payment_id, refund_key in ((bad, "bad"), (good, "good")):
        with pytest.raises(RuntimeError), work(shop.tenant) as session:
            svc.refund(session, payment_id, amount_minor=200, reason="x", idempotency_key=refund_key)
            raise RuntimeError("died")
    with work(shop.tenant) as session:  # the processor refunded more than the payment can cover
        session.execute(svc.update(Refund).where(Refund.idempotency_key == "bad").values(amount_minor=900))
    with clock.freeze(clock.now() + timedelta(minutes=10)), work(shop.tenant) as session:
        counts = webhooks.reconcile(session)
        assert (counts["refunds"], counts["failed"]) == (1, 1)
    with work(shop.tenant) as session:
        states = {r.idempotency_key: (r.status, r.failure_message) for r in session.scalars(select(Refund))}
        assert states["good"] == ("succeeded", None)
        assert states["bad"][0] == "initiated" and "reconcile" in states["bad"][1]


def test_an_unreconcilable_refund_records_a_code_and_a_fixed_sentence_only(shop, caplog):
    """Error text can carry SQL and its parameters (names, emails): staff see a code and a fixed sentence, and
    the log names the refund and the code, never the text."""
    payment_id = _paid(shop, 500)
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        svc.refund(session, payment_id, amount_minor=200, reason="x", idempotency_key="leaky")
        raise RuntimeError("died")
    leak = "UPDATE client SET email='jane@example.com'"
    with work(shop.tenant) as session:
        refund_id = session.scalar(select(Refund.id).where(Refund.idempotency_key == "leaky"))
        for error in (RuntimeError(leak), Conflict(leak, code="refund-unreconcilable")):
            assert webhooks._isolated(session, refund_id, lambda e=error: (_ for _ in ()).throw(e)) is False
            message = session.scalar(select(Refund.failure_message).where(Refund.id == refund_id))
            code = getattr(error, "code", "internal-error")
            assert code in message and "jane" not in message
    assert caplog.records and not any("jane" in record.getMessage() for record in caplog.records)


def test_a_declined_composite_refund_releases_nothing(shop, monkeypatch):
    ready(shop)
    item_id, payment_id, allocation_id = _applied(shop)
    monkeypatch.setattr(payment_provider.get("fake"), "refund", lambda **_: RefundState("fake_ref_no", "failed", "No"))
    with work(shop.tenant) as session:
        row = svc.refund(
            session, payment_id, amount_minor=600, reason="Closed", idempotency_key=uuid4().hex,
            release_allocation_ids=[allocation_id],
        )  # fmt: skip
        assert row.status == "failed"
        assert session.get(PaymentAllocation, allocation_id).status == "applied"
        assert session.get(svc.Charge, item_id).applied_minor == 1083
        assert_books_agree(session)


def test_a_pending_composite_refund_that_fails_pays_the_item_again(shop, monkeypatch):
    ready(shop)
    item_id, payment_id, allocation_id = _applied(shop)
    with work(shop.tenant) as session:
        before = (session.get(svc.Charge, item_id).applied_minor, session.get(svc.Payment, payment_id).unapplied_minor)
    fake = payment_provider.get("fake")
    monkeypatch.setattr(fake, "refund", lambda **_: RefundState("fake_ref_slow", "pending"))
    with work(shop.tenant) as session:
        row = svc.refund(
            session, payment_id, amount_minor=600, reason="Closed", idempotency_key=uuid4().hex,
            release_allocation_ids=[allocation_id],
        )  # fmt: skip
        assert row.status == "pending" and session.get(svc.Charge, item_id).applied_minor == 0
        assert session.get(svc.Payment, payment_id).unapplied_minor == 483  # 600 is held for the pending refund
    monkeypatch.setattr(fake, "get_refund", lambda **_: RefundState("fake_ref_slow", "failed", "Declined"))
    for _ in range(2):  # a repeated webhook re-applies nothing
        with work(shop.tenant) as session:
            webhooks.apply_event(session, "refund", "fake_ref_slow")
    with work(shop.tenant) as session:
        assert session.get(Refund, row.id).status == "failed"
        after = (session.get(svc.Charge, item_id).applied_minor, session.get(svc.Payment, payment_id).unapplied_minor)
        assert after == before == (1083, 0)  # the item is paid again, no stray account credit
        assert_books_agree(session)


def _pending_composite(shop, monkeypatch):
    item_id, payment_id, allocation_id = _applied(shop)
    fake = payment_provider.get("fake")
    monkeypatch.setattr(fake, "refund", lambda **_: RefundState("fake_ref_slow", "pending"))
    with work(shop.tenant) as session:
        row = svc.refund(
            session, payment_id, amount_minor=600, reason="Closed", idempotency_key=uuid4().hex,
            release_allocation_ids=[allocation_id],
        )  # fmt: skip
        assert row.status == "pending"
    monkeypatch.undo()
    return item_id, payment_id, row.id


def _fail_twice(shop, monkeypatch, refund_id) -> None:
    """The failure webhook arrives twice; the refund must end `failed` whatever happened to the payment."""
    monkeypatch.setattr(
        payment_provider.get("fake"), "get_refund", lambda **_: RefundState("fake_ref_slow", "failed", "Declined")
    )
    for _ in range(2):
        with work(shop.tenant) as session:
            webhooks.apply_event(session, "refund", "fake_ref_slow")
    with work(shop.tenant) as session:
        assert session.get(Refund, refund_id).status == "failed"
        assert_books_agree(session)


def test_a_pending_refund_that_fails_after_a_dispute_leaves_the_money_as_credit(shop, monkeypatch):
    ready(shop)
    item_id, payment_id, refund_id = _pending_composite(shop, monkeypatch)
    fake = payment_provider.get("fake")
    with work(shop.tenant) as session:
        payment = session.get(svc.Payment, payment_id)
        account = session.get(svc.ProviderAccount, payment.provider_account_id)
        svc.sync_dispute(session, account, fake.open_dispute(payment.provider_payment_ref))
        assert payment.status == "disputed"
    fake.outbox.clear()
    _fail_twice(shop, monkeypatch, refund_id)
    with work(shop.tenant) as session:
        assert session.get(svc.Payment, payment_id).refunded_minor == 0
        assert session.get(svc.Charge, item_id).applied_minor == 0  # a disputed payment takes no allocation


def test_a_pending_refund_that_fails_after_the_item_was_paid_otherwise_leaves_credit(shop, monkeypatch):
    ready(shop)
    item_id, payment_id, refund_id = _pending_composite(shop, monkeypatch)
    with work(shop.tenant) as session:
        card(session, shop, 1083, allocations=[(item_id, 1083)])
    _fail_twice(shop, monkeypatch, refund_id)
    with work(shop.tenant) as session:
        payment = session.get(svc.Payment, payment_id)
        assert (payment.refunded_minor, payment.unapplied_minor) == (0, 1083)  # all of it is credit now
        assert session.get(svc.Charge, item_id).applied_minor == 1083  # paid once, not twice


def test_a_pending_refund_that_fails_after_a_second_refund_reapplies_only_what_is_free(shop, monkeypatch):
    ready(shop)
    item_id, payment_id, refund_id = _pending_composite(shop, monkeypatch)
    with work(shop.tenant) as session:
        assert (
            svc.refund(session, payment_id, amount_minor=483, reason="Rest", idempotency_key=uuid4().hex).status
            == "succeeded"
        )
    _fail_twice(shop, monkeypatch, refund_id)
    with work(shop.tenant) as session:
        payment = session.get(svc.Payment, payment_id)
        assert (payment.refunded_minor, payment.unapplied_minor) == (483, 0)
        assert session.get(svc.Charge, item_id).applied_minor == 600


def test_a_caller_holding_the_payment_lock_still_gets_a_committed_refund_row(shop):
    """Cross-context refunds (membership cancel, POS return) lock the payment first; the pre-provider row must
    still commit on its own so a crash after the processor call is recoverable."""
    ready(shop)
    payment_id = _paid(shop)
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        svc._lock(session, svc.Payment, payment_id)
        svc.refund(session, payment_id, amount_minor=100, reason="Cancel", idempotency_key="locked")
        raise RuntimeError("died")
    with work(shop.tenant) as session:
        assert session.scalar(select(Refund.status).where(Refund.idempotency_key == "locked")) == "initiated"


def test_two_refunds_racing_on_one_payment_leave_one_refund_and_no_stray_row(shop, monkeypatch):
    """Both pass the unlocked early check; the short transaction's lock lets one through and refuses the other
    before it writes anything, so neither is stuck counting the other's `initiated` row."""
    ready(shop)
    payment_id = _paid(shop)  # 500 free: room for one 300 refund, not two
    barrier, real = threading.Barrier(2, timeout=20), svc._initiate_refund

    def gated(session, values):
        barrier.wait()  # both requests are past the early check before either writes
        return real(session, values)

    monkeypatch.setattr(svc, "_initiate_refund", gated)
    outcomes: dict[str, str] = {}

    def attempt(name: str) -> None:
        try:
            with work(shop.tenant) as session:
                outcomes[name] = svc.refund(
                    session, payment_id, amount_minor=300, reason="Twice", idempotency_key=name
                ).status
        except ValidationFailed as error:
            outcomes[name] = error.code

    threads = [threading.Thread(target=attempt, args=(name,)) for name in ("first", "second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(outcomes.values()) == ["refund-exceeds-unapplied", "succeeded"]
    with work(shop.tenant) as session:
        assert session.scalars(select(Refund.status)).all() == ["succeeded"]  # the loser left no row
        assert _provider_refunded(session, payment_id) == 300
        assert_books_agree(session)


def test_an_on_account_refund_replays_with_its_key(shop):
    """A record-only (external) refund of account credit keeps its key: the same request returns the first row."""
    with work(shop.tenant) as session:
        payment = cash(session, shop, 800)
        refund_key = uuid4().hex
        first = svc.refund(session, payment.id, amount_minor=300, reason="On account", idempotency_key=refund_key)
        again = svc.refund(session, payment.id, amount_minor=300, reason="On account", idempotency_key=refund_key)
        assert (again.id, first.method, payment.unapplied_minor) == (first.id, "external", 500)
        with pytest.raises(Conflict) as caught:
            svc.refund(session, payment.id, amount_minor=200, reason="On account", idempotency_key=refund_key)
        assert caught.value.code == "idempotency-key-reused"
        assert_books_agree(session)


# --- account-credit refunds: the plan is stored, a retry replays it ---------------------------------------


def _three_cards(shop) -> tuple:
    """P1 1000 (oldest), P2 500, P3 500 (newest), all on account: a credit refund of 1000 plans P3 then P2."""
    ids = []
    with work(shop.tenant) as session:
        for minutes, amount in ((0, 1000), (1, 500), (2, 500)):
            with clock.freeze(clock.now() + timedelta(minutes=minutes)):
                ids.append(card(session, shop, amount).id)
    return tuple(ids)


def _paid_out(session, payment_ids) -> int:
    return sum(_provider_refunded(session, payment_id) for payment_id in payment_ids)


def _sweep(shop):
    with clock.freeze(clock.now() + timedelta(minutes=10)), work(shop.tenant) as session:
        webhooks.reconcile(session)


def test_a_credit_refund_retried_after_a_leg_timed_out_pays_the_plan_once(shop, monkeypatch):
    ready(shop)
    p1, p2, p3 = _three_cards(shop)
    with work(shop.tenant) as session:
        p2_ref = session.get(svc.Payment, p2).provider_payment_ref
    fake, real = payment_provider.get("fake"), payment_provider.get("fake").refund
    stalls = {"n": 1}

    def refund(**kw):
        if kw["provider_payment_ref"] == p2_ref and stalls["n"]:
            stalls["n"] -= 1
            raise TimeoutError("the processor did not answer")
        return real(**kw)

    monkeypatch.setattr(fake, "refund", refund)
    refund_key = uuid4().hex
    with pytest.raises(TimeoutError), work(shop.tenant) as session:
        svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving", idempotency_key=refund_key)
    with work(shop.tenant) as session:
        assert [session.get(svc.Payment, p).unapplied_minor for p in (p1, p2, p3)] == [1000, 0, 0]  # reserved
        refunds = svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving",
                                    idempotency_key=refund_key)  # fmt: skip
        assert [(r.payment_id, r.amount_minor, r.status) for r in refunds] == [
            (p3, 500, "succeeded"), (p2, 500, "succeeded")
        ]  # fmt: skip
    _sweep(shop)
    with work(shop.tenant) as session:
        assert _paid_out(session, (p1, p2, p3)) == 1000  # never the 1500 a re-plan from balances would pay
        assert session.get(svc.Payment, p1).unapplied_minor == 1000
        assert_books_agree(session)


def test_a_credit_refund_whose_legs_all_timed_out_replays_them(shop, monkeypatch):
    ready(shop)
    p1, p2, p3 = _three_cards(shop)
    fake, real = payment_provider.get("fake"), payment_provider.get("fake").refund
    monkeypatch.setattr(fake, "refund", lambda **kw: (_ for _ in ()).throw(TimeoutError("no answer")))
    refund_key = uuid4().hex
    with pytest.raises(TimeoutError), work(shop.tenant) as session:
        svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving", idempotency_key=refund_key)
    monkeypatch.setattr(fake, "refund", real)
    with work(shop.tenant) as session:
        refunds = svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving",
                                    idempotency_key=refund_key)  # fmt: skip
        assert [(r.payment_id, r.amount_minor, r.status) for r in refunds] == [
            (p3, 500, "succeeded"), (p2, 500, "succeeded")
        ]  # fmt: skip
    _sweep(shop)
    with work(shop.tenant) as session:
        assert _paid_out(session, (p1, p2, p3)) == 1000
        assert_books_agree(session)


def test_a_declined_credit_refund_leg_is_not_paid_on_retry(shop, monkeypatch):
    ready(shop)
    p1, p2, p3 = _three_cards(shop)
    with work(shop.tenant) as session:
        p2_ref = session.get(svc.Payment, p2).provider_payment_ref
    fake, real = payment_provider.get("fake"), payment_provider.get("fake").refund

    def refund(**kw):
        if kw["provider_payment_ref"] == p2_ref:
            return RefundState(f"fake_ref_{uuid4().hex}", "failed", "Declined by the bank.")
        return real(**kw)

    monkeypatch.setattr(fake, "refund", refund)
    refund_key = uuid4().hex
    with work(shop.tenant) as session:
        first = svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving",
                                  idempotency_key=refund_key)  # fmt: skip
        assert [r.status for r in first] == ["succeeded", "failed"]
    monkeypatch.setattr(fake, "refund", real)
    with work(shop.tenant) as session:
        again = svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving",
                                  idempotency_key=refund_key)  # fmt: skip
        assert [r.id for r in again] == [r.id for r in first]  # replayed, the declined leg is not re-sent
        assert _paid_out(session, (p1, p2, p3)) == 500
        assert_books_agree(session)


def test_another_key_while_a_credit_refund_is_initiated_plans_around_it(shop, monkeypatch):
    """Every leg is reserved when the plan is committed: a second key plans only from genuinely free credit, and
    the first request still completes."""
    ready(shop)
    p1, p2, p3 = _three_cards(shop)
    fake, real = payment_provider.get("fake"), payment_provider.get("fake").refund
    monkeypatch.setattr(fake, "refund", lambda **kw: (_ for _ in ()).throw(TimeoutError("no answer")))
    first_key, second_key = uuid4().hex, uuid4().hex
    with pytest.raises(TimeoutError), work(shop.tenant) as session:
        svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving", idempotency_key=first_key)
    monkeypatch.setattr(fake, "refund", real)
    with work(shop.tenant) as session:
        assert [session.get(svc.Payment, p).unapplied_minor for p in (p1, p2, p3)] == [1000, 0, 0]  # both legs held
        with pytest.raises(ValidationFailed):  # only 1000 is free
            svc.refund_credit(session, shop.client_id, amount_minor=1001, reason="Moving", idempotency_key=uuid4().hex)
    with work(shop.tenant) as session:
        second = svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Moving",
                                   idempotency_key=second_key)  # fmt: skip
        assert [(r.payment_id, r.amount_minor) for r in second] == [(p1, 1000)]
    with work(shop.tenant) as session:
        first = svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving",
                                  idempotency_key=first_key)  # fmt: skip
        assert [(r.payment_id, r.status) for r in first] == [(p3, "succeeded"), (p2, "succeeded")]
    _sweep(shop)
    with work(shop.tenant) as session:
        assert _paid_out(session, (p1, p2, p3)) == 2000  # two requests of 1000, each paid once
        assert_books_agree(session)


def test_a_crashed_credit_refund_holds_its_credit_until_the_retry(shop):
    """The request died after planning: the cash leg's credit stays reserved, so it cannot be spent, and the retry
    pays both legs once (the record-only leg is finished without a processor)."""
    ready(shop)
    with work(shop.tenant) as session:
        older = cash(session, shop, 500).id
        with clock.freeze(clock.now() + timedelta(minutes=1)):
            newest = card(session, shop, 500).id
    refund_key = uuid4().hex
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving", idempotency_key=refund_key)
        raise RuntimeError("the process died before commit")
    with work(shop.tenant) as session:
        item = charge(session, shop, 400)
        assert svc.spend_credit(session, shop.client_id) == 0  # the reserved credit cannot be spent
        assert item.applied_minor == 0
    with work(shop.tenant) as session:
        refunds = svc.refund_credit(session, shop.client_id, amount_minor=1000, reason="Leaving",
                                    idempotency_key=refund_key)  # fmt: skip
        assert [(r.payment_id, r.method, r.status) for r in refunds] == [
            (newest, "original", "succeeded"), (older, "external", "succeeded")
        ]  # fmt: skip
        assert _provider_refunded(session, newest) == 500
        assert session.get(svc.Payment, older).refunded_minor == 500
        assert_books_agree(session)


def test_an_abandoned_credit_refund_plan_frees_its_reservations(shop):
    ready(shop)
    with work(shop.tenant) as session:
        older = cash(session, shop, 500).id
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        svc.refund_credit(session, shop.client_id, amount_minor=300, reason="Leaving", idempotency_key=uuid4().hex)
        raise RuntimeError("died")
    with clock.freeze(clock.now() + timedelta(minutes=40)), work(shop.tenant) as session:
        webhooks.reconcile(session)
    with work(shop.tenant) as session:
        assert session.scalars(select(Refund.status)).all() == ["cancelled"]
        assert session.get(svc.Payment, older).unapplied_minor == 500
        assert_books_agree(session)


def test_the_1801_downgrade_guard_sees_initiated_refunds_through_forced_rls(shop):
    """The owner reads no tenant rows under forced RLS, so a plain count let the downgrade drop `initiated`."""
    ready(shop)
    with work(shop.tenant) as session:
        cash(session, shop, 500)
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        svc.refund_credit(session, shop.client_id, amount_minor=300, reason="Leaving", idempotency_key=uuid4().hex)
        raise RuntimeError("died after planning")  # the plan's short transaction committed an `initiated` leg
    migration = importlib.import_module("migrations.versions.1801_billing_refund_initiated")
    owner = create_engine(get_settings().db_url("owner"))
    try:
        with owner.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM refund WHERE status = 'initiated'")).scalar() == 0
            assert migration.count_initiated(conn) >= 1
            conn.rollback()
    finally:
        owner.dispose()
