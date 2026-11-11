"""Autopay runs, decline handling, the retry and dunning policy, the autopay-error queue and billing notices
(PAY-09, PAY-08, PAY-07, BIL-22; ADR 0005 section 8)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from dramatiq import Worker
from sqlalchemy import func, select

from app.core import clock
from app.core.errors import ValidationFailed
from app.core.jobs import broker
from app.modules.billing import autopay, catalogue, methods
from app.modules.billing.domain import schedule as plans
from app.modules.billing.models import AutopayAttempt, AutopayRun, BillingNotice, Invoice, Payment, PaymentMethod
from app.modules.billing.tests.test_billing import API, SYSTEM, assert_books_agree, card, cash, charge, svc, work
from app.modules.billing.tests.test_money import NOON, TODAY, provider_payments, ready, refused, transactions
from app.ports import payment_provider
from conftest import new_client


def drain() -> None:
    worker = Worker(broker, worker_timeout=100)
    worker.start()
    try:
        broker.join("default", fail_fast=True, timeout=300_000)
        worker.join()
    finally:
        worker.stop()


def due_invoice(session, shop, price=1000, **over) -> Invoice:
    client_id = over.pop("client_id", shop.client_id)
    return svc.create_invoice_for_charges(
        session, [charge(session, shop, price, client_id=client_id).id], is_autopay=True, **over
    )


def run_on(shop, day: int) -> dict:
    """Run autopay `day` days after the reference date; returns the run's counters."""
    with clock.freeze(NOON + timedelta(days=day)), work(shop.tenant) as session:
        run = autopay.run_location(session, shop.location_id)
        attempts = session.scalar(
            select(func.count()).select_from(AutopayAttempt).where(AutopayAttempt.autopay_run_id == run.id)
        )
        return {"status": run.status, "attempts": attempts, "succeeded": run.succeeded_count, "failed": run.failed_count,
                "collected": run.collected_minor, "id": run.id}  # fmt: skip


def state(shop, invoice_id) -> tuple:
    with work(shop.tenant) as session:
        invoice = session.get(Invoice, invoice_id)
        return invoice.status, invoice.dunning_state, invoice.next_attempt_on, invoice.attempt_count


@pytest.fixture
def payer(client, shop):
    """A client with an email address, so notices have somewhere to go."""
    person = new_client(client, shop.owner, shop.location_id, primary_email=f"pat@{shop.tenant.slug}.example.com")
    return UUID(person["id"])


def setup(shop, token: str | None, price=1000, client_id=None, **over) -> UUID:
    with clock.freeze(NOON), work(shop.tenant) as session:
        if token:
            methods.attach_method(session, client_id or shop.client_id, token)
        return due_invoice(session, shop, price, client_id=client_id or shop.client_id, **over).id


def test_a_run_collects_what_is_due_once(shop):
    with clock.freeze(NOON), work(shop.tenant) as session:
        methods.attach_method(session, shop.client_id, "tok_card_ok")
        invoice = due_invoice(session, shop)
        svc.create_invoice_for_charges(session, [charge(session, shop).id])  # not on autopay
        later = due_invoice(session, shop, due_on=TODAY + timedelta(days=5))  # not due yet
        posted = transactions(session)
        preview = autopay.preview(session, shop.location_id, TODAY)
        assert [(row["invoice_id"], row["due_minor"], row["has_payment_method"]) for row in preview] == [
            (invoice.id, 1083, True)
        ]
        assert transactions(session) == posted and session.scalar(select(func.count()).select_from(AutopayAttempt)) == 0
        run = autopay.run_location(session, shop.location_id)
        assert (run.status, run.business_on, run.selected_count, run.succeeded_count, run.failed_count) == (
            "completed",
            TODAY,
            1,
            1,
            0,
        )
        assert (run.collected_minor, invoice.status, later.status) == (1083, "paid", "open")
        attempt = session.scalars(select(AutopayAttempt)).one()
        payment = session.get(Payment, attempt.payment_id)
        assert (attempt.status, attempt.attempt_no, attempt.amount_minor, attempt.credit_applied_minor) == (
            "succeeded",
            1,
            1083,
            0,
        )
        assert (payment.origin, payment.idempotency_key, payment.payment_method_id) == (
            "autopay", f"autopay:{invoice.id}:1", attempt.payment_method_id
        )  # fmt: skip
        again = autopay.run_location(session, shop.location_id)  # the same run, resumed: nothing left to do
        assert (again.id, again.selected_count) == (run.id, 1)
        assert session.scalar(select(func.count()).select_from(Payment)) == 1
        assert_books_agree(session)


def test_account_credit_is_used_before_the_card(shop):
    with clock.freeze(NOON), work(shop.tenant) as session:
        cash(session, shop, 1500)
        covered, part = due_invoice(session, shop, 1000), due_invoice(session, shop, 1000)  # 1083 each
        methods.attach_method(session, shop.client_id, "tok_card_ok")
        run = autopay.run_location(session, shop.location_id)
        first, second = session.scalars(select(AutopayAttempt).order_by(AutopayAttempt.id)).all()
        assert (first.status, first.credit_applied_minor, first.payment_id) == (
            "succeeded",
            1083,
            None,
        )  # no provider call
        assert (second.credit_applied_minor, session.get(Payment, second.payment_id).amount_minor) == (417, 666)
        assert (covered.status, part.status, run.collected_minor) == ("paid", "paid", 2166)
        assert_books_agree(session)


def test_no_method_on_file_waits_for_one_and_a_new_method_collects_at_once(shop, payer, mailbox):
    invoice_id = setup(shop, None, client_id=payer)
    assert run_on(shop, 0) == {"status": "completed_with_errors", "attempts": 1, "succeeded": 0, "failed": 1,
                               "collected": 0, "id": run_on(shop, 0)["id"]}  # fmt: skip
    assert state(shop, invoice_id) == ("open", "awaiting_method", None, 1)
    assert [m.to for m in mailbox if "no payment method on file" in m.body] == [f"pat@{shop.tenant.slug}.example.com"]
    assert run_on(shop, 1)["attempts"] == 0 and run_on(shop, 9)["attempts"] == 0  # never retried on its own
    with clock.freeze(NOON + timedelta(days=9)), work(shop.tenant) as session:
        methods.attach_method(session, payer, "tok_card_ok")  # saving a method retries what was waiting
    assert state(shop, invoice_id) == ("paid", "none", None, 2)


def test_soft_declines_retry_on_days_3_5_and_7_then_stop(shop, payer, mailbox):
    invoice_id = setup(shop, "tok_card_insufficient", client_id=payer)
    assert run_on(shop, 0)["failed"] == 1
    assert state(shop, invoice_id) == ("open", "retrying", TODAY + timedelta(days=3), 1)
    assert run_on(shop, 0)["attempts"] == 1 and run_on(shop, 1)["attempts"] == 0  # not before its retry date
    assert run_on(shop, 3)["failed"] == 1 and state(shop, invoice_id)[2] == TODAY + timedelta(days=5)
    assert run_on(shop, 5)["failed"] == 1 and state(shop, invoice_id)[2] == TODAY + timedelta(days=7)
    assert run_on(shop, 7)["failed"] == 1
    assert state(shop, invoice_id) == ("open", "exhausted", None, 4)
    assert run_on(shop, 8)["attempts"] == 0 and run_on(shop, 30)["attempts"] == 0  # nothing automatic any more
    declines = [m for m in mailbox if "did not go through" in m.subject]
    assert len(declines) == 4 and len([m for m in mailbox if m.subject.startswith("Final notice")]) == 1
    with work(shop.tenant) as session:
        attempts = session.scalars(select(AutopayAttempt).order_by(AutopayAttempt.attempt_no)).all()
        assert [(a.status, a.failure_category) for a in attempts] == [("failed", "insufficient_funds")] * 4
        assert session.scalar(select(func.count()).select_from(Payment).where(Payment.status == "failed")) == 4
        assert_books_agree(session)


def test_a_retry_that_succeeds_ends_dunning(shop):
    invoice_id = setup(shop, "tok_card_flaky")
    assert run_on(shop, 0)["failed"] == 1
    paid = run_on(shop, 3)
    assert (paid["succeeded"], paid["collected"], paid["status"]) == (1, 1083, "completed")
    assert state(shop, invoice_id) == ("paid", "none", None, 2)


@pytest.mark.parametrize(
    ("token", "category"), [("tok_card_expired", "expired_card"), ("tok_card_auth", "authentication_required")]
)
def test_hard_and_authentication_declines(shop, token, category):
    """An expired card can never work again: wait for a new method. A card that needs the payer present is a
    soft failure off-session: retried, and the payer is pointed at the portal."""
    invoice_id = setup(shop, token)
    run_on(shop, 0)
    with work(shop.tenant) as session:
        assert session.scalars(select(AutopayAttempt.failure_category)).one() == category
    expected = ("awaiting_method", None) if token == "tok_card_expired" else ("retrying", TODAY + timedelta(days=3))
    assert state(shop, invoice_id)[1:3] == expected


def test_a_bank_debit_is_pending_then_its_return_arrives_by_webhook(client, shop):
    invoice_id = setup(shop, "tok_ach_fail")
    first = run_on(shop, 0)
    assert (first["status"], first["failed"], first["succeeded"]) == ("completed", 0, 0)
    assert state(shop, invoice_id) == ("payment_pending", "none", None, 1)
    assert run_on(shop, 1)["attempts"] == 0  # a pending debit covers the invoice: never charged twice
    fake = payment_provider.get("fake")
    with work(shop.tenant) as session:
        attempt = session.scalars(select(AutopayAttempt)).one()
        assert attempt.status == "processing"
        fake.settle(session.get(Payment, attempt.payment_id).provider_payment_ref)
    headers, body = fake.outbox.pop()
    with clock.freeze(NOON + timedelta(days=4)):
        assert client.post(f"{API}/webhooks/fake", content=body, headers=headers).json() == {"result": "accepted"}
        drain()
    assert state(shop, invoice_id) == ("open", "retrying", TODAY + timedelta(days=3), 1)  # 3 days after the run's date
    with work(shop.tenant) as session:
        attempt = session.scalars(select(AutopayAttempt)).one()
        run = session.get(AutopayRun, attempt.autopay_run_id)
        assert (attempt.status, attempt.failure_category, run.failed_count, run.status) == (
            "failed", "insufficient_funds", 1, "completed_with_errors"
        )  # fmt: skip
        assert_books_agree(session)


def test_a_closed_bank_account_suspends_the_method(shop):
    invoice_id = setup(shop, "tok_ach_closed")
    run_on(shop, 0)
    with work(shop.tenant) as session:
        payment = session.scalars(select(Payment)).one()
        payment_provider.get("fake").settle(payment.provider_payment_ref)
        svc.confirm_payment(session, payment.id)
        method = session.scalars(select(PaymentMethod)).one()
        assert (method.status, method.is_autopay) == ("suspended", False)
    assert state(shop, invoice_id)[:3] == ("open", "awaiting_method", None)


def test_only_the_instalments_due_are_collected(shop):
    with clock.freeze(NOON), work(shop.tenant) as session:
        methods.attach_method(session, shop.client_id, "tok_card_ok")
        invoice = due_invoice(session, shop, 3000)  # 3248
        svc.set_schedule(session, invoice.id, plans.generate(3248, TODAY, 1, "month", 3), basis={})
        invoice_id = invoice.id
    assert run_on(shop, 0)["collected"] == 1083 and state(shop, invoice_id)[0] == "partially_paid"
    assert run_on(shop, 1)["attempts"] == 0
    assert run_on(shop, 30)["collected"] == 1083  # 10 December
    assert run_on(shop, 61)["collected"] == 1082 and state(shop, invoice_id)[0] == "paid"  # 10 January


def test_a_run_that_dies_is_resumed_without_charging_twice(shop):
    ready(shop)
    invoice_id = setup(shop, "tok_card_ok")
    with pytest.raises(RuntimeError), clock.freeze(NOON), work(shop.tenant) as session:
        autopay.run_location(session, shop.location_id)
        raise RuntimeError("the worker died before commit")
    with work(shop.tenant) as session:  # the payment row outlived the dead transaction; the attempt did not
        assert session.scalars(select(Payment.status)).all() == ["initiated"]
        assert session.scalar(select(func.count()).select_from(AutopayAttempt)) == 0
    assert run_on(shop, 0)["succeeded"] == 1 and state(shop, invoice_id)[0] == "paid"
    with work(shop.tenant) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1
        assert_books_agree(session)
    assert provider_payments(shop, f"autopay:{invoice_id}:1") == 1


def test_two_runs_at_once_make_one_attempt(shop):
    ready(shop)
    invoice_id = setup(shop, "tok_card_ok")

    def run(_):
        with work(shop.tenant) as session:
            return autopay.run_location(session, shop.location_id).id

    with clock.freeze(NOON), ThreadPoolExecutor(3) as pool:
        assert len(set(pool.map(run, range(3)))) == 1
    with work(shop.tenant) as session:
        assert session.scalar(select(func.count()).select_from(AutopayAttempt)) == 1
        assert session.scalar(select(func.count()).select_from(Payment)) == 1
    assert state(shop, invoice_id)[0] == "paid"


def test_staff_work_the_error_queue(shop):
    invoice_id = setup(shop, "tok_card_flaky")
    run_on(shop, 0)
    with clock.freeze(NOON), work(shop.tenant) as session:
        failed = session.scalars(select(AutopayAttempt)).one()
        query = lambda **filters: autopay.list_attempts(session, SYSTEM, autopay.ListQuery(filters=filters))["data"]  # noqa: E731
        assert [a.id for a in query(status="failed", is_error_open="true")] == [failed.id]
        again = autopay.retry_attempt(session, SYSTEM, failed.id)  # staff decided not to wait for day 3
        assert (again.attempt_no, again.status) == (2, "succeeded")
        with refused("autopay-attempt-not-failed"):
            autopay.retry_attempt(session, SYSTEM, again.id)
        with refused("invoice-not-payable"):
            autopay.retry_attempt(session, SYSTEM, failed.id)
        autopay.clear_error(session, SYSTEM, failed.id)
        assert failed.error_cleared_at is not None and query(status="failed", is_error_open="true") == []
        assert [a.id for a in query(is_error_open="false")] == [failed.id]
        with refused("autopay-error-not-open"):
            autopay.clear_error(session, SYSTEM, failed.id)
        with refused("autopay-error-not-open"):
            autopay.clear_error(session, SYSTEM, again.id)
        assert autopay.get_run(session, SYSTEM, failed.autopay_run_id).succeeded_count == 1
        assert len(autopay.list_runs(session, SYSTEM, autopay.ListQuery())["data"]) == 1
    assert state(shop, invoice_id)[:2] == ("paid", "none")


def test_starting_a_run_by_hand(shop):
    setup(shop, "tok_card_ok")
    with clock.freeze(NOON), work(shop.tenant) as session:
        with pytest.raises(ValidationFailed):
            autopay.start_run(
                session, SYSTEM, {"location_id": shop.location_id, "business_on": TODAY + timedelta(days=1)}
            )
        with pytest.raises(ValidationFailed):
            autopay.start_run(session, SYSTEM, {"location_id": UUID(int=1)})
        dry = autopay.start_run(session, SYSTEM, {"location_id": shop.location_id, "is_dry_run": True})
        assert len(dry) == 1 and session.scalar(select(func.count()).select_from(AutopayRun)) == 0
        assert autopay.start_run(session, SYSTEM, {"location_id": shop.location_id}).succeeded_count == 1


# --- notices -----------------------------------------------------------------------------------------------


def test_decline_notices_follow_the_settings_and_a_timeout_never_notifies(shop, payer, mailbox):
    with work(shop.tenant) as session:
        card(session, shop, 100, token="tok_card_unknown", client_id=payer)  # not a decline: the money may be taken
        assert session.scalar(select(func.count()).select_from(BillingNotice)) == 0
        declined = card(session, shop, 100, token="tok_card_declined", client_id=payer)
        assert session.scalars(select(BillingNotice.kind)).all() == ["payment_declined"]
        autopay._notify_decline(session, declined)  # a replayed webhook: the notice is not sent again
        assert session.scalar(select(func.count()).select_from(BillingNotice)) == 1
        cfg = {"decline_notice_scope": "autopay_payments", "decline_alert_email": "desk@example.com"}
        catalogue.put_settings(session, SYSTEM, None, cfg)
        card(session, shop, 100, token="tok_card_declined", client_id=payer)  # a desk payment: staff alert only
        assert session.scalars(select(BillingNotice.kind).order_by(BillingNotice.id)).all()[1:] == [
            "staff_decline_alert"
        ]
        catalogue.put_settings(
            session, SYSTEM, None, {"decline_notice_scope": "off", "decline_alert_mode": "daily_digest"}
        )
        card(session, shop, 100, token="tok_card_declined", client_id=payer)
        assert session.scalar(select(func.count()).select_from(BillingNotice)) == 2
    assert [m.to for m in mailbox] == [f"pat@{shop.tenant.slug}.example.com", "desk@example.com"]
    assert "Casey" in mailbox[1].body and "card_declined" in mailbox[1].body


def test_the_daily_pass_reminds_marks_past_due_warns_and_starts_autopay(shop, payer, mailbox):
    with clock.freeze(NOON), work(shop.tenant) as session:
        soon = due_invoice(session, shop, client_id=payer, due_on=TODAY + timedelta(days=3))
        visa = methods.attach_method(session, payer, "tok_card_ok")
        visa.exp_month, visa.exp_year = 12, 2026  # good through 31 December
        soon_id = soon.id
    early = NOON.replace(hour=11)  # 05:00 in Chicago: before the location's 06:00 autopay time
    with clock.freeze(early), work(shop.tenant) as session:
        assert autopay.daily(session) == {"past_due": 0, "reminders": 1, "expiry_notices": 0, "runs": 0}
        assert autopay.daily(session)["reminders"] == 0  # the same day again: nothing new
    with clock.freeze(early + timedelta(days=3)), work(shop.tenant) as session:
        assert autopay.daily(session)["runs"] == 0  # due today, but still before 06:00 there
    with clock.freeze(NOON + timedelta(days=3)), work(shop.tenant) as session:
        assert autopay.daily(session)["runs"] == 1 and session.get(Invoice, soon_id).status == "paid"
    with clock.freeze(NOON + timedelta(days=21)), work(shop.tenant) as session:  # 1 December: 30 days of card left
        unpaid = svc.create_invoice_for_charges(session, [charge(session, shop, client_id=payer).id])
        assert autopay.daily(session) == {"past_due": 0, "reminders": 0, "expiry_notices": 1, "runs": 0}
    with clock.freeze(NOON + timedelta(days=22)), work(shop.tenant) as session:
        assert autopay.daily(session)["past_due"] == 1 and session.get(Invoice, unpaid.id).past_due_since_on is not None
    subjects = [m.subject for m in mailbox]
    assert subjects[0].endswith("is due on 2026-11-13") and "about to expire" in subjects[-1]
    assert "12/2026" in mailbox[-1].body and "/portal/billing" in mailbox[0].body
