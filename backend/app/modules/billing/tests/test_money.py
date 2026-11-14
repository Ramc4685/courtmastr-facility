"""Build module 8, service level: the undo operations, item edits, invoice regrouping, payment schedules,
account credit, the pre-provider payment row, stored methods and coupons (ADR 0003), with the ledger
invariants checked after every scenario."""

import random
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core import clock
from app.core.db.session import tenant_session
from app.core.errors import Conflict, DomainError, ValidationFailed
from app.modules.billing import catalogue, methods, webhooks
from app.modules.billing.domain import dunning
from app.modules.billing.domain import schedule as plans
from app.modules.billing.models import (
    Charge,
    CouponRedemption,
    Invoice,
    LedgerTransaction,
    Payment,
    PaymentAllocation,
    PaymentSchedule,
    Refund,
    TenderType,
)
from app.modules.billing.tests.test_billing import (
    API,
    SYSTEM,
    assert_books_agree,
    balances,
    card,
    cash,
    charge,
    event_types,
    svc,
    work,
)
from app.ports import payment_provider
from conftest import new_client

NOON = datetime(2026, 11, 10, 18, 0, tzinfo=UTC)  # 12:00 on 10 November in America/Chicago
TODAY = date(2026, 11, 10)


@contextmanager
def refused(code: str, kind: type[DomainError] = Conflict):
    with pytest.raises(kind) as caught:
        yield
    assert caught.value.code == code


def ready(shop) -> None:
    """Commit the tenant's tender rows and fake processor account, as a tenant that has taken a payment has."""
    with work(shop.tenant) as session:
        svc.ensure_defaults(session)
        svc._provider_account(session)


def transactions(session) -> int:
    return session.scalar(select(func.count()).select_from(LedgerTransaction))


# --- pure domain -------------------------------------------------------------------------------------------


def test_instalment_generator_dates_and_amounts():
    assert plans.split(1000, 3) == [334, 333, 333]
    assert plans.split_by_weight(100, [1, 1, 1]) == [34, 33, 33]
    assert plans.split_by_weight(50, [300, 100]) == [38, 12] and plans.split_by_weight(5, [0, 0]) == [0, 0]
    monthly = plans.generate(1000, date(2027, 1, 31), 1, "month", 3)
    assert monthly == [(date(2027, 1, 31), 334), (date(2027, 2, 28), 333), (date(2027, 3, 31), 333)]
    assert plans.due_dates(date(2024, 2, 29), 1, "year", 2) == [date(2024, 2, 29), date(2025, 2, 28)]
    assert plans.due_dates(date(2026, 11, 10), 2, "week", 3)[-1] == date(2026, 12, 8)
    assert plans.due_dates(date(2026, 11, 10), 10, "day", 2)[-1] == date(2026, 11, 20)
    halves = plans.due_dates(date(2027, 1, 20), 1, "half_month", 4)
    assert halves == [date(2027, 1, 20), date(2027, 1, 31), date(2027, 2, 20), date(2027, 2, 28)]
    assert plans.generate(0, TODAY, 1, "month", 6) == [(TODAY, 0)]
    assert len(plans.generate(2, TODAY, 1, "month", 6)) == 2  # never a zero instalment
    for bad in ((1, "fortnight", 2), (0, "month", 2), (1, "month", 0), (1, "month", 500)):
        with pytest.raises(ValueError, match="unsupported"):
            plans.due_dates(TODAY, *bad)


def test_generated_and_rebalanced_plans_always_sum_to_the_total():
    """Property: for any total, cadence and count the instalments add up exactly, and they still do after
    any change of total, with nothing negative."""
    rng = random.Random(8)
    for _ in range(400):
        total, count = rng.randint(0, 10**7), rng.randint(1, 60)
        plan = plans.generate(total, TODAY, rng.randint(1, 4), rng.choice(plans.UNITS), count)
        assert sum(amount for _, amount in plan) == total and [due for due, _ in plan] == sorted(due for due, _ in plan)
        changed, applied = rng.randint(0, 10**7), rng.randint(0, total)
        again = plans.rebalance(plan, changed, applied, TODAY + timedelta(days=rng.randint(0, 400)))
        assert sum(amount for _, amount in again) == changed and all(amount >= 0 for _, amount in again)
        covered = plans.cover([amount for _, amount in again], applied)
        assert sum(covered) == min(applied, changed) and all(c <= a for c, (_, a) in zip(covered, again, strict=True))
        weights = [rng.randint(0, 5000) for _ in range(rng.randint(1, 8))]
        if sum(weights):
            assert sum(plans.split_by_weight(total % 9999, weights)) == total % 9999


def test_rebalance_rules():
    rows = [(date(2026, 11, 1), 100), (date(2026, 12, 1), 100), (date(2027, 1, 1), 100)]
    assert plans.rebalance(rows, 250, 0, TODAY) == [rows[0], rows[1], (date(2027, 1, 1), 50)]
    assert plans.rebalance(rows, 150, 0, TODAY) == [rows[0], (date(2026, 12, 1), 50)]  # emptied rows are dropped
    assert plans.rebalance(rows, 400, 150, TODAY)[-1] == (date(2027, 1, 1), 200)  # onto the last open one
    paid_up = plans.rebalance(rows, 360, 300, date(2027, 3, 3))
    assert paid_up[-1] == (date(2027, 3, 3), 60)  # all covered: a new instalment due today
    assert plans.rebalance(rows, 0, 0, TODAY) == [(date(2026, 11, 1), 0)]
    assert plans.rebalance([], 70, 0, TODAY) == [(TODAY, 70)]


@pytest.mark.parametrize(
    ("category", "tender", "failures", "expected"),
    [
        ("insufficient_funds", "card", 1, ("retrying", date(2026, 11, 13))),
        ("card_declined", "card", 2, ("retrying", date(2026, 11, 15))),
        ("processor_error", "card", 3, ("retrying", date(2026, 11, 17))),
        ("authentication_required", "card", 1, ("retrying", date(2026, 11, 13))),
        ("insufficient_funds", "card", 4, ("exhausted", None)),
        ("expired_card", "card", 1, ("awaiting_method", None)),
        ("account_closed", "bank_debit", 1, ("awaiting_method", None)),
        ("authorization_revoked", "bank_debit", 1, ("awaiting_method", None)),
        ("processor_error", "bank_debit", 1, ("awaiting_method", None)),  # a bank debit retries only for NSF
        ("insufficient_funds", "bank_debit", 2, ("retrying", date(2026, 11, 15))),
        ("insufficient_funds", "bank_debit", 3, ("exhausted", None)),  # re-presented at most twice
    ],
)
def test_dunning_decisions(category, tender, failures, expected):
    decision = dunning.decide(category, tender, failures, TODAY, [3, 5, 7])
    assert (decision.state, decision.next_attempt_on) == expected


def test_dunning_with_no_retries_configured_and_ageing_buckets():
    assert dunning.decide("card_declined", "card", 1, TODAY, []).state == "exhausted"
    ages = {0: "current", -5: "current", 1: "days_1_30", 30: "days_1_30", 31: "days_31_60", 60: "days_31_60",
            61: "days_61_90", 90: "days_61_90", 91: "days_over_90"}  # fmt: skip
    for days, bucket in ages.items():
        assert dunning.ageing_bucket(TODAY - timedelta(days=days), TODAY) == bucket


# --- the four undo operations ------------------------------------------------------------------------------


def test_void_item_nets_to_zero_in_its_own_period_and_is_terminal(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop, 2000, revenue_on=date(2026, 9, 1))
        negation = svc.void_charge(session, row.id, reason="Entered twice")
        assert (row.status, negation.status, negation.kind) == ("voided", "voided", "reversal")
        assert (negation.revenue_on, negation.total_minor) == (date(2026, 9, 1), -row.total_minor)
        assert row.voided_at and row.reason == "Entered twice"
        assert all(amount == 0 for amount in balances(session).values())
        with refused("charge-not-reversible"):
            svc.void_charge(session, row.id, reason="Again")
        invoiced = charge(session, shop)
        svc.create_invoice_for_charges(session, [invoiced.id])
        paid = charge(session, shop)
        cash(session, shop, 500, allocations=[(paid.id, 500)])
        for blocked in (invoiced, paid):
            with refused("charge-not-voidable"):
                svc.void_charge(session, blocked.id, reason="No")
        with pytest.raises(ValidationFailed):
            svc.void_charge(session, charge(session, shop).id, reason="  ")
        assert_books_agree(session)
    assert event_types(shop.tenant).count("billing.charge.voided") == 1


def test_void_invoice_detaches_its_items_and_posts_nothing_of_its_own(shop):
    with work(shop.tenant) as session:
        first, second = charge(session, shop), charge(session, shop, 500)
        invoice = svc.create_invoice_for_charges(session, [first.id, second.id])
        payment = cash(session, shop, first.total_minor, allocations=[(first.id, first.total_minor)])
        posted = transactions(session)
        with refused("invoice-has-payments"):
            svc.void_invoice(session, invoice.id, reason="Wrong client")
        with pytest.raises(ValidationFailed):
            svc.void_invoice(session, invoice.id, reason="", release_allocations=True)
        svc.void_invoice(session, invoice.id, reason="Wrong client", release_allocations=True)
        assert (invoice.status, invoice.void_reason, invoice.balance_minor) == ("voided", "Wrong client", 0)
        assert first.invoice_id is None and second.invoice_id is None and first.status == "active"
        assert payment.unapplied_minor == first.total_minor  # the money is the payer's credit again
        assert transactions(session) == posted + 1  # only the release of the one allocation
        with refused("invoice-voided"):
            svc.void_invoice(session, invoice.id, reason="Twice")
        again = svc.create_invoice_for_charges(session, [first.id, second.id])
        assert again.number == invoice.number + 1 and again.total_minor == first.total_minor + second.total_minor
        empty = svc.create_invoice_for_charges(session, [charge(session, shop).id])
        before = transactions(session)
        svc.void_invoice(session, empty.id, reason="Not needed")  # nothing applied: no posting at all
        assert transactions(session) == before
        assert_books_agree(session)
    assert "billing.invoice.voided" in event_types(shop.tenant)


def test_void_payment_is_for_record_only_money_with_no_refunds(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop)
        invoice = svc.create_invoice_for_charges(session, [row.id])
        payment = cash(session, shop, row.total_minor, invoice_id=invoice.id)
        assert invoice.status == "paid"
        svc.void_payment(session, payment.id, reason="Keyed for the wrong person")
        assert (payment.status, payment.unapplied_minor, row.applied_minor) == ("voided", 0, 0)
        assert (invoice.status, invoice.balance_minor) == ("open", row.total_minor)
        ledger = balances(session)
        assert ledger["funds_received"] == 0 and ledger["client_credit"] == 0
        with refused("payment-not-voidable"):
            svc.void_payment(session, payment.id, reason="Twice")
        with refused("use-refund"):
            svc.void_payment(session, card(session, shop, 500).id, reason="No")
        refunded = cash(session, shop, 500)
        svc.refund(session, refunded.id, amount_minor=100, reason="Change")
        with refused("payment-not-voidable"):
            svc.void_payment(session, refunded.id, reason="No")
        with pytest.raises(ValidationFailed):
            svc.void_payment(session, cash(session, shop, 5).id, reason=" ")
        assert_books_agree(session)
    assert "billing.payment.voided" in event_types(shop.tenant)


def test_releasing_one_allocation_returns_it_to_credit(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop)
        invoice = svc.create_invoice_for_charges(session, [row.id])
        payment = cash(session, shop, row.total_minor, invoice_id=invoice.id)
        allocation = session.scalars(select(PaymentAllocation)).one()
        svc.release_allocation(session, payment.id, allocation.id)
        assert (allocation.status, allocation.release_reason) == ("released", "unapplied")
        assert (payment.unapplied_minor, invoice.status) == (row.total_minor, "open")
        with refused("allocation-released"):
            svc.release_allocation(session, payment.id, allocation.id)
        other = cash(session, shop, 10)
        with pytest.raises(DomainError):  # an allocation of another payment is not found under this one
            svc.release_allocation(session, other.id, allocation.id)
        assert_books_agree(session)


def test_price_edit_replaces_the_item_and_keeps_the_money_on_it(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop, 2000)  # 2000 + 8.25% = 2165
        invoice = svc.create_invoice_for_charges(session, [row.id])
        payment = cash(session, shop, row.total_minor, invoice_id=invoice.id)
        down = svc.adjust_charge(session, row.id, reason="Member rate", unit_price_minor=1000)
        assert (down.kind, down.adjusts_charge_id, down.status, row.status) == (
            "adjustment",
            row.id,
            "active",
            "reversed",
        )
        assert (down.net_minor, down.tax_minor, down.total_minor) == (1000, 83, 1083)
        assert (down.revenue_on, down.bill_on, down.invoice_id) == (row.revenue_on, row.bill_on, invoice.id)
        # the excess over the new price stays with the payer as credit; nothing is refunded
        assert (down.applied_minor, payment.unapplied_minor, payment.refunded_minor) == (1083, 1082, 0)
        assert (invoice.total_minor, invoice.balance_minor, invoice.status) == (1083, 0, "paid")
        up = svc.adjust_charge(session, down.id, reason="Two courts", quantity=2)
        assert (up.total_minor, up.applied_minor, up.adjusts_charge_id) == (2165, 1083, down.id)
        assert (invoice.status, invoice.balance_minor) == ("partially_paid", 1082)
        exempt = svc.adjust_charge(session, up.id, reason="Tax exempt", exclude_tax_ids=[shop.tax_id])
        assert (exempt.tax_minor, exempt.total_minor) == (0, 2000)
        discounted = svc.adjust_charge(session, exempt.id, reason="Goodwill", discount_minor=500)
        assert (discounted.net_minor, discounted.tax_minor) == (1500, 0)  # the exclusion survives the next edit
        with refused("charge-not-reversible"):
            svc.adjust_charge(session, row.id, reason="Old row", unit_price_minor=1)
        for bad in ({"unit_price_minor": -1}, {"quantity": 0}, {"discount_minor": 99999}):
            with pytest.raises(ValidationFailed):
                svc.adjust_charge(session, discounted.id, reason="Bad", **bad)
        with pytest.raises(ValidationFailed):
            svc.adjust_charge(session, discounted.id, reason="", unit_price_minor=5)
        assert_books_agree(session)
        assert (
            session.scalar(
                select(func.count()).select_from(Charge).where(Charge.status == "active", Charge.kind != "reversal")
            )
            == 1
        )
    sent = event_types(shop.tenant)
    assert sent.count("billing.charge.adjusted") == 4 and "billing.charge.reversed" not in sent


def test_an_edit_in_a_closed_period_is_refused(shop):
    from app.modules.platform.models import Tenant

    with work(shop.tenant) as session:
        row = charge(session, shop, revenue_on=date(2026, 9, 1))
    with work(shop.tenant) as session:
        session.get(Tenant, shop.tenant.id).billing_locked_through_on = date(2026, 9, 30)
    for undo in (
        lambda s: svc.adjust_charge(s, row.id, reason="Late", unit_price_minor=1),
        lambda s: svc.void_charge(s, row.id, reason="Late"),
    ):
        with refused("period-locked"), work(shop.tenant) as session:
            undo(session)
    with work(shop.tenant) as session:  # a reversal dated in the open period is the way out
        svc.reverse(session, row.id, reason="Late", revenue_on=date(2026, 10, 1))
        assert_books_agree(session)


# --- invoices: regrouping and payer ------------------------------------------------------------------------


def test_items_move_between_invoices_of_one_payer_only(client, shop):
    stranger = new_client(client, shop.owner, shop.location_id)["id"]
    with work(shop.tenant) as session:
        first, second, loose = charge(session, shop), charge(session, shop, 500), charge(session, shop, 300)
        theirs = charge(session, shop, 100, client_id=UUID(stranger))
        invoice = svc.create_invoice_for_charges(session, [first.id])
        other = svc.create_invoice_for_charges(session, [second.id])
        svc.attach_charges(session, invoice.id, [loose.id])
        assert invoice.total_minor == first.total_minor + loose.total_minor
        with refused("payer-mismatch", ValidationFailed):
            svc.attach_charges(session, invoice.id, [theirs.id])  # never bill a stranger's item to this payer
        with refused("charge-not-invoiceable"):
            svc.attach_charges(session, invoice.id, [second.id])
        cash(session, shop, 100, allocations=[(loose.id, 100)])
        with refused("charge-has-payments"):
            svc.detach_charge(session, invoice.id, loose.id)
        svc.detach_charge(session, invoice.id, loose.id, to_invoice_id=other.id)  # the payment moves with it
        assert (invoice.total_minor, invoice.balance_minor) == (first.total_minor, first.total_minor)
        assert other.balance_minor == second.total_minor + loose.total_minor - 100 and other.status == "partially_paid"
        their_invoice = svc.create_invoice_for_charges(session, [theirs.id])
        with refused("payer-mismatch", ValidationFailed):
            svc.detach_charge(session, invoice.id, first.id, to_invoice_id=their_invoice.id)
        svc.detach_charge(session, invoice.id, first.id)
        assert (first.invoice_id, invoice.total_minor, invoice.status) == (None, 0, "open")  # empty until voided
        with refused("invoice-has-payments"):
            svc.reassign_payer(session, other.id, UUID(stranger))
        svc.reassign_payer(session, invoice.id, UUID(stranger))
        assert (invoice.bill_to_client_id, invoice.version) == (UUID(stranger), 2)
        assert_books_agree(session)


# --- payment schedules -------------------------------------------------------------------------------------


def amounts(session, invoice) -> list[tuple[int, int]]:
    return [(row.amount_minor, row.covered_minor) for row in svc.schedule_of(session, invoice.id)]


def test_instalments_always_add_up_to_the_invoice_total(shop):
    with clock.freeze(NOON), work(shop.tenant) as session:
        big, small = charge(session, shop, 3000), charge(session, shop, 1000)  # 3248 + 1083
        invoice = svc.create_invoice_for_charges(session, [big.id, small.id])
        assert [(row.due_on, row.amount_minor) for row in svc.schedule_of(session, invoice.id)] == [(TODAY, 4331)]
        with refused("schedule-not-balanced", ValidationFailed):
            svc.set_schedule(session, invoice.id, [(date(2026, 12, 1), 100)], basis={})
        with refused("schedule-not-balanced", ValidationFailed):
            svc.set_schedule(session, invoice.id, [(TODAY, 4331), (date(2026, 12, 1), 0)], basis={})
        with refused("schedule-not-balanced", ValidationFailed):
            svc.set_schedule(session, invoice.id, [(date(2026, 11, 9), 4331)], basis={})  # before the invoice date
        svc.set_schedule(session, invoice.id, plans.generate(4331, TODAY, 1, "month", 3), basis={"count": 3})
        assert amounts(session, invoice) == [(1444, 0), (1444, 0), (1443, 0)]
        cash(session, shop, 1544, invoice_id=invoice.id)
        assert amounts(session, invoice) == [(1444, 1444), (1444, 100), (1443, 0)]
        assert invoice.due_on == date(2026, 12, 10)  # the earliest instalment not yet covered
        svc.reverse(session, small.id, reason="Cancelled")  # total falls by 1083: taken off the end
        assert amounts(session, invoice) == [(1444, 1444), (1444, 100), (360, 0)]
        svc.adjust_charge(session, big.id, reason="Extra hour", unit_price_minor=4000)  # total rises to 4330
        assert amounts(session, invoice) == [(1444, 1444), (1444, 100), (1442, 0)]
        assert sum(row.amount_minor for row in svc.schedule_of(session, invoice.id)) == invoice.total_minor == 4330
        assert_books_agree(session)
        invoice_id = invoice.id
    tamper = "UPDATE payment_schedule SET amount_minor = amount_minor + 1 WHERE invoice_id = :i AND seq = 3"
    with pytest.raises(IntegrityError, match="not balanced"), tenant_session(shop.tenant.id) as session:
        session.execute(text(tamper), {"i": invoice_id})  # the database refuses what the service would not do
    with pytest.raises(IntegrityError, match="not balanced"), tenant_session(shop.tenant.id) as session:
        session.execute(text("DELETE FROM payment_schedule WHERE invoice_id = :i AND seq = 3"), {"i": invoice_id})


def test_an_instalment_becomes_past_due_once_and_a_payment_clears_it(shop):
    with clock.freeze(NOON), work(shop.tenant) as session:
        invoice = svc.create_invoice_for_charges(session, [charge(session, shop, 1000).id])
        svc.set_schedule(session, invoice.id, plans.generate(1083, TODAY, 1, "month", 2), basis={})
        cash(session, shop, 542, invoice_id=invoice.id)
        assert invoice.past_due_since_on is None and invoice.due_on == date(2026, 12, 10)
        invoice_id = invoice.id
    with clock.freeze(NOON + timedelta(days=35)), work(shop.tenant) as session:
        svc.refresh_invoice(session, invoice_id)
        svc.refresh_invoice(session, invoice_id)
        invoice = session.get(Invoice, invoice_id)
        assert invoice.past_due_since_on == date(2026, 12, 15)
        # A pending debit pauses the dunning clock; it does not restart it (Stripe Billing, Chargebee).
        bounced = card(session, shop, 541, token="tok_ach_fail", tender_kind="bank_debit", invoice_id=invoice_id)
        assert (invoice.status, invoice.past_due_since_on) == ("payment_pending", date(2026, 12, 15))
        payment_provider.get("fake").settle(bounced.provider_payment_ref)
        svc.confirm_payment(session, bounced.id)
        svc.refresh_invoice(session, invoice_id)
        assert invoice.past_due_since_on == date(2026, 12, 15)  # returned: past due from the first day, not today
        pending = card(session, shop, 541, token="tok_ach_ok", tender_kind="bank_debit", invoice_id=invoice_id)
        assert (invoice.status, invoice.past_due_since_on) == ("payment_pending", date(2026, 12, 15))
        payment_provider.get("fake").settle(pending.provider_payment_ref)
        svc.confirm_payment(session, pending.id)
        assert (invoice.status, invoice.past_due_since_on) == ("paid", None)
    assert event_types(shop.tenant).count("billing.invoice.past_due") == 1  # paused and resumed: no second notice


@pytest.mark.parametrize(
    ("zone", "at_0530", "at_1130"),
    [("America/Chicago", True, True), ("Asia/Kolkata", False, False), ("Pacific/Auckland", False, True)],
)
def test_past_due_follows_the_calendar_on_the_wall_at_the_location(client, shop, zone, at_0530, at_1130):
    """One invoice per site, created at the same instant and due "today" there. The US site changes its
    clocks that night (1 November 2026) and Auckland is already on summer time."""
    site = client.post(
        f"{API}/locations", headers=shop.owner, json={"name": zone, "time_zone": zone, "country_code": "US"}
    ).json()["id"]
    with clock.freeze(datetime(2026, 10, 31, 20, 0, tzinfo=UTC)), work(shop.tenant) as session:
        invoice_id = svc.create_invoice_for_charges(session, [charge(session, shop, location_id=site).id]).id
    for instant, expected in (
        (datetime(2026, 11, 1, 5, 30, tzinfo=UTC), at_0530),
        (datetime(2026, 11, 1, 11, 30, tzinfo=UTC), at_1130),
    ):
        with clock.freeze(instant), work(shop.tenant) as session:
            svc.refresh_invoice(session, invoice_id)
            assert (session.get(Invoice, invoice_id).past_due_since_on is not None) is expected


# --- account credit, split tender --------------------------------------------------------------------------


def test_money_on_account_is_spent_oldest_first_and_refunded_newest_first(shop):
    with work(shop.tenant) as session:
        with clock.freeze(NOON):
            oldest = cash(session, shop, 1000)
        with clock.freeze(NOON + timedelta(hours=1)):
            newer = cash(session, shop, 500)
        assert svc.credit_balance(session, shop.client_id) == 1500
        first = charge(session, shop, 1000)  # 1083
        assert svc.spend_credit(session, shop.client_id) == 1083
        assert (oldest.unapplied_minor, newer.unapplied_minor, first.applied_minor) == (0, 417, 1083)
        assert session.scalar(select(func.count()).select_from(Payment)) == 2  # spending credit makes no payment
        second = charge(session, shop, 200)  # 217
        with refused("allocation-exceeds-payment", ValidationFailed):
            svc.spend_credit(session, shop.client_id, allocations=[(second.id, 9999)])
        assert svc.spend_credit(session, shop.client_id, allocations=[(second.id, 217)]) == 217
        third = charge(session, shop, 1000)
        assert svc.spend_credit(session, shop.client_id, limit=50) == 50 and third.applied_minor == 50
        assert svc.credit_balance(session, shop.client_id) == 150
        with clock.freeze(NOON + timedelta(hours=2)):
            newest = card(session, shop, 300)
    # the payments commit first, as in production: a credit refund plans in a short transaction of its own
    with work(shop.tenant) as session:
        with refused("refund-exceeds-unapplied", ValidationFailed):
            svc.refund_credit(session, shop.client_id, amount_minor=451, reason="Leaving", idempotency_key="a" * 12)
        refunds = svc.refund_credit(
            session, shop.client_id, amount_minor=320, reason="Leaving", idempotency_key="b" * 12
        )
        assert [(r.payment_id, r.amount_minor, r.method) for r in refunds] == [
            (newest.id, 300, "original"), (newer.id, 20, "external")
        ]  # fmt: skip
        assert len({r.refund_batch_id for r in refunds}) == 1 and svc.credit_balance(session, shop.client_id) == 130
        assert_books_agree(session)


def test_split_tender_pays_one_invoice_from_cash_gift_card_card_and_credit(shop):
    with work(shop.tenant) as session:
        cash(session, shop, 200)  # an earlier overpayment sitting on account
        row = charge(session, shop, 2000)  # 2165
        invoice = svc.create_invoice_for_charges(session, [row.id])
        assert svc.spend_credit(session, shop.client_id, invoice_id=invoice.id) == 200
        cash(session, shop, 500, invoice_id=invoice.id)
        gift = cash(session, shop, 465, tender_kind="gift_card", external_reference="GC-1001", invoice_id=invoice.id)
        assert (invoice.status, invoice.balance_minor) == ("partially_paid", 1000)
        declined = card(session, shop, 1000, token="tok_card_declined", invoice_id=invoice.id)
        assert declined.status == "failed" and invoice.balance_minor == 1000  # the other tenders stand
        card(session, shop, 1000, invoice_id=invoice.id)
        assert (invoice.status, invoice.balance_minor, gift.tender_kind) == ("paid", 0, "gift_card")
        kinds = set(session.scalars(select(Payment.tender_kind).where(Payment.status == "succeeded")))
        assert kinds == {"cash", "gift_card", "card"}
        assert_books_agree(session)


def test_a_tenant_labelled_tender_and_a_disabled_one(client, shop):
    paypal = client.post(f"{API}/tender-types", headers=shop.owner, json={"kind": "external", "label": "PayPal"})
    assert paypal.status_code == 201, paypal.text
    with work(shop.tenant) as session:
        paypal_id = UUID(paypal.json()["id"])
        assert cash(session, shop, 100, tender_kind="external", tender_type_id=paypal_id).tender_type_id == paypal_id
        with pytest.raises(ValidationFailed):
            cash(session, shop, 100, tender_kind="cash", tender_type_id=paypal_id)
    off = client.patch(f"{API}/tender-types/{paypal.json()['id']}", headers=shop.owner, json={"is_enabled": False})
    assert off.status_code == 200 and off.json()["is_enabled"] is False
    with pytest.raises(ValidationFailed), work(shop.tenant) as session:
        cash(session, shop, 100, tender_kind="external", tender_type_id=paypal_id)


def test_the_opening_balance_tender_is_billing_owned_and_never_a_desk_choice(client, shop):
    # A disabled ordinary tender renamed to the opening-balance label earns no exemption.
    paypal = client.post(f"{API}/tender-types", headers=shop.owner, json={"kind": "external", "label": "PayPal"})
    renamed = client.patch(f"{API}/tender-types/{paypal.json()['id']}", headers=shop.owner,
                           json={"label": svc.OPENING_BALANCE_TENDER, "is_enabled": False})  # fmt: skip
    assert renamed.status_code == 200, renamed.text
    with pytest.raises(ValidationFailed), work(shop.tenant) as session:
        cash(session, shop, 100, tender_kind="external", tender_type_id=UUID(paypal.json()["id"]))
    with work(shop.tenant) as session:
        _, payment_id, _ = svc.post_opening_balance(
            session, client_id=shop.client_id, location_id=shop.location_id, amount_minor=500, kind="credit",
            as_of=date(2026, 1, 1), description="Opening balance", key="t-1",
        )  # fmt: skip
        tender = session.get(TenderType, session.get(Payment, payment_id).tender_type_id)
        tender_id, tender_label = tender.id, tender.label
        assert tender.system_key == "opening_balance" and tender.id != UUID(paypal.json()["id"])
    assert tender_label == f"{svc.OPENING_BALANCE_TENDER} (import)"  # the tenant's own name stands
    listed = client.get(f"{API}/tender-types", headers=shop.owner).json()
    assert str(tender_id) not in {row["id"] for row in listed}
    desk = client.post(f"{API}/payments", headers=shop.owner, json={
        "client_id": str(shop.client_id), "location_id": str(shop.location_id), "amount_minor": 100,
        "tender_kind": "external", "tender_type_id": str(tender_id)})  # fmt: skip
    assert desk.status_code == 422, desk.text
    for body in ({"label": "Mine now"}, {"is_enabled": True}, {"sort_order": 1}):
        edit = client.patch(f"{API}/tender-types/{tender_id}", headers=shop.owner, json=body)
        assert (edit.status_code, edit.json().get("code")) == (409, "tender-system"), edit.text
    assert client.delete(f"{API}/tender-types/{tender_id}", headers=shop.owner).status_code == 405  # no delete


# --- the row committed before the provider call (ADR 0003 section 8) --------------------------------------


def provider_payments(shop, key: str) -> int:
    fake = payment_provider.get("fake")
    return sum(1 for stored in fake._by_key if stored == f"{shop.tenant.id}:payment:{key}")


def test_a_request_that_dies_after_the_processor_answered_is_finished_by_a_retry(shop):
    ready(shop)
    key = uuid4().hex
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        payment_id = card(session, shop, 700, idempotency_key=key).id
        raise RuntimeError("the process died before commit")
    with work(shop.tenant) as session:
        left = session.get(Payment, payment_id)
        assert (left.status, left.provider_payment_ref, left.idempotency_key) == ("initiated", None, key)
        assert transactions(session) == 0  # nothing reached the ledger
    with work(shop.tenant) as session:
        again = card(session, shop, 700, idempotency_key=key)
        assert (again.id, again.status, again.unapplied_minor) == (payment_id, "succeeded", 700)
        assert card(session, shop, 700, idempotency_key=key).id == payment_id  # and a third time is a replay
        assert session.scalar(select(func.count()).select_from(Payment)) == 1
        assert_books_agree(session)
    assert provider_payments(shop, key) == 1  # the card was charged once


def test_the_sweep_finishes_an_orphan_and_cancels_what_never_reached_the_processor(shop, monkeypatch):
    ready(shop)
    charged, lost = uuid4().hex, uuid4().hex
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        card(session, shop, 700, idempotency_key=charged)
        raise RuntimeError("died after the provider call")
    fake = payment_provider.get("fake")
    with monkeypatch.context() as patched, pytest.raises(RuntimeError), work(shop.tenant) as session:
        patched.setattr(fake, "create_payment", lambda **_: (_ for _ in ()).throw(RuntimeError("no network")))
        card(session, shop, 300, idempotency_key=lost)
    with work(shop.tenant) as session:
        # too fresh to touch
        assert webhooks.reconcile(session) == {"payments": 0, "cancelled": 0, "refunds": 0, "failed": 0}
    with clock.freeze(clock.now() + timedelta(minutes=10)), work(shop.tenant) as session:
        assert webhooks.reconcile(session) == {"payments": 2, "cancelled": 0, "refunds": 0, "failed": 0}
        states = dict(session.execute(select(Payment.idempotency_key, Payment.status)).all())
        assert states == {charged: "succeeded", lost: "initiated"}
    with clock.freeze(clock.now() + timedelta(minutes=45)), work(shop.tenant) as session:
        assert webhooks.reconcile(session)["cancelled"] == 1
        assert session.scalar(select(Payment.status).where(Payment.idempotency_key == lost)) == "cancelled"
        assert webhooks.reconcile(session) == {"payments": 0, "cancelled": 0, "refunds": 0, "failed": 0}
        assert_books_agree(session)


def test_first_payment_of_a_new_tenant_in_one_transaction_still_works(shop):
    """The short transaction cannot see the tender rows this transaction has just created, so it falls back
    to inserting the payment here; a replay is still safe through the key."""
    key = uuid4().hex
    with work(shop.tenant) as session:
        first = card(session, shop, 400, idempotency_key=key)
        assert first.status == "succeeded" and card(session, shop, 400, idempotency_key=key).id == first.id
    with pytest.raises(RuntimeError), work(shop.tenant) as session:
        cash(session, shop, 5)  # holds the receipt counter, so the short transaction gives up quickly
        card(session, shop, 100, idempotency_key="held-counter")
        raise RuntimeError("rolled back")
    with work(shop.tenant) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1
    assert provider_payments(shop, key) == 1


def test_record_only_payments_replay_by_key_too(shop):
    with work(shop.tenant) as session:
        first = cash(session, shop, 100, idempotency_key="cash-key-1")
        assert cash(session, shop, 100, idempotency_key="cash-key-1").id == first.id
        assert session.scalar(select(func.count()).select_from(Payment)) == 1


def test_a_payment_that_needs_the_payer_waits_and_can_be_cancelled(shop):
    fake = payment_provider.get("fake")
    with work(shop.tenant) as session:
        invoice = svc.create_invoice_for_charges(session, [charge(session, shop).id])
        waiting = card(session, shop, invoice.total_minor, token="tok_card_auth", invoice_id=invoice.id)
        assert waiting.status == "requires_action" and waiting.client_secret.endswith("_secret")
        assert (invoice.status, waiting.unapplied_minor, transactions(session)) == ("open", 0, 1)
        fake.authenticate(waiting.provider_payment_ref)
        svc.confirm_payment(session, waiting.id)
        assert (
            waiting.status == "succeeded" and waiting.unapplied_minor == invoice.total_minor
        )  # then allocated by staff
        with refused("payment-not-cancellable"):
            svc.cancel_payment(session, waiting.id)
        abandoned = card(session, shop, 100, token="tok_card_auth")
        svc.cancel_payment(session, abandoned.id)
        assert abandoned.status == "cancelled"
        fake.authenticate(abandoned.provider_payment_ref)  # too late: a cancelled payment stays cancelled
        assert svc.confirm_payment(session, abandoned.id).status == "cancelled"
        assert_books_agree(session)
    assert "billing.payment.failed" not in event_types(shop.tenant)


# --- stored methods ----------------------------------------------------------------------------------------


def test_stored_methods_hold_display_data_only_and_one_is_for_autopay(client, shop):
    stranger = new_client(client, shop.owner, shop.location_id)["id"]
    with work(shop.tenant) as session:
        visa = methods.attach_method(session, shop.client_id, "tok_card_ok")
        assert (visa.kind, visa.brand, visa.last4, visa.status, visa.is_autopay) == (
            "card",
            "visa",
            "4242",
            "active",
            True,
        )
        assert (visa.exp_month, visa.exp_year, visa.funding) == (12, 2099, "credit")
        second = methods.attach_method(session, shop.client_id, "tok_card_flaky")
        assert second.is_autopay is False  # the first usable method keeps the flag
        methods.set_autopay(session, second.id, True)
        assert (visa.is_autopay, second.is_autopay) == (False, True)
        bank = methods.attach_method(session, shop.client_id, "tok_ach_unverified", is_autopay=True)
        assert (bank.kind, bank.status, bank.is_autopay) == ("bank_account", "pending_verification", False)
        with refused("payment-method-not-usable"):
            methods.set_autopay(session, bank.id, True)
        with refused("verification-failed", ValidationFailed):
            methods.verify_bank_account(session, bank.id, (1, 2))
        assert methods.verify_bank_account(session, bank.id, (45, 32)).status == "active"
        with refused("payment-method-not-pending"):
            methods.verify_bank_account(session, bank.id, (45, 32))
        with refused("payment-method-rejected", ValidationFailed):
            methods.attach_method(session, shop.client_id, "4242424242424242")  # not a token: never stored
        theirs = methods.attach_method(session, stranger, "tok_card_ok")

        def pay(**over):
            args = {"client_id": shop.client_id, "location_id": shop.location_id, "amount_minor": 500,
                    "tender_kind": "card", "payment_method_id": visa.id, "idempotency_key": uuid4().hex}  # fmt: skip
            return svc.take_payment(session, **(args | over))

        paid = pay()
        assert (paid.status, paid.payment_method_id, paid.card_last4) == ("succeeded", visa.id, "4242")
        assert pay(tender_kind="bank_debit", payment_method_id=bank.id).status == "processing"
        for wrong in ({"payment_method_id": theirs.id}, {"tender_kind": "bank_debit"}, {"payment_method_id": uuid4()}):
            with pytest.raises(ValidationFailed):
                pay(**wrong)  # someone else's method, a card as a bank debit, an unknown id
        methods.remove_method(session, visa.id)
        assert (visa.status, visa.is_autopay) == ("removed", False) and visa not in methods.methods_of(
            session, shop.client_id
        )
        with refused("payment-method-removed"):
            methods.set_autopay(session, visa.id, True)
        with refused("payment-method-not-usable", ValidationFailed):
            pay()
        methods.suspend_method(session, second.id)
        assert (second.status, second.is_autopay, second.suspended_on) == ("suspended", False, clock.now().date())
        assert methods.autopay_method(session, shop.client_id) is None


# --- coupons -----------------------------------------------------------------------------------------------


def coupon(session, code="TEN", **over):
    data = {"name": code, "code": code, "starts_at": NOON - timedelta(days=1), "discount_pct": Decimal(10)}
    return catalogue.create_coupon(session, SYSTEM, data | over)


def test_coupon_quotes_caps_and_idempotent_redemption(client, shop):
    stranger = new_client(client, shop.owner, shop.location_id)["id"]
    with clock.freeze(NOON), work(shop.tenant) as session:
        coupon(session, limit_per_client=1)
        coupon(session, "FIVER", discount_pct=None, discount_minor=500)
        coupon(session, "LATER", starts_at=NOON + timedelta(days=1))
        coupon(session, "GONE", ends_at=NOON)
        coupon(session, "OFF", is_active=False)
        quote = lambda code, **kw: catalogue.quote_coupon(session, code, subtotal_minor=1995, **kw)  # noqa: E731
        assert quote("ten", redeemer_client_id=shop.client_id)["discount_minor"] == 200  # 199.5 rounds half up
        assert quote("FIVER")["discount_minor"] == 500
        assert catalogue.quote_coupon(session, "FIVER", subtotal_minor=300)["discount_minor"] == 300  # capped
        reasons = {"LATER": "not_started", "GONE": "expired", "OFF": "inactive", "TEN": "client_required"}
        for code, reason in reasons.items():
            answer = quote(code)
            assert (answer["is_valid"], answer["invalid_reason"], answer["discount_minor"]) == (False, reason, 0)
        assert quote("FIVER", channel="portal")["invalid_reason"] == "not_portal_enabled"
        with refused("coupon-not-found", ValidationFailed):
            quote("NOPE")
        args = {"line_nets": [1000, 600, 395], "redeemer_client_id": shop.client_id}
        coupon_id, parts = catalogue.redeem_coupon(session, "TEN", redemption_key="tests:sale:1", **args)
        assert parts == [100, 60, 40] and sum(parts) == 200
        assert catalogue.redeem_coupon(session, "TEN", redemption_key="tests:sale:1", **args) == (coupon_id, parts)
        assert session.scalar(select(func.count()).select_from(CouponRedemption)) == 1  # a retry counts once
        with refused("coupon-limit-reached", ValidationFailed):
            catalogue.redeem_coupon(session, "TEN", redemption_key="tests:sale:2", **args)
        other = catalogue.redeem_coupon(  # the cap is per purchasing person
            session, "TEN", redemption_key="tests:sale:3", line_nets=[1000], redeemer_client_id=stranger
        )
        assert other[1] == [100]
        catalogue.release_coupon(session, "tests:sale:1")  # the sale was abandoned: the use is given back
        assert catalogue.redeem_coupon(session, "TEN", redemption_key="tests:sale:2", **args)[1] == parts
        catalogue.release_coupon(session, "tests:sale:2")
        assert catalogue.redeem_coupon(session, "TEN", redemption_key="tests:sale:2", **args)[1] == parts  # revived
        assert session.scalar(select(func.count()).select_from(CouponRedemption)) == 3
        with refused("coupon-in-use"):
            catalogue.delete_coupon(session, SYSTEM, coupon_id)
        unused = coupon(session, "UNUSED")
        catalogue.delete_coupon(session, SYSTEM, unused.id)
        with refused("already-exists"):
            coupon(session, "ten")
        for bad in ({"discount_minor": 5}, {"discount_pct": None}, {"ends_at": NOON - timedelta(days=2)}):
            with pytest.raises(ValidationFailed):
                coupon(session, uuid4().hex[:8], **bad)


def test_two_sales_cannot_both_take_the_last_use_of_a_coupon(shop):
    from concurrent.futures import ThreadPoolExecutor

    with work(shop.tenant) as session:
        coupon(session, "ONCE", limit_per_client=1, starts_at=clock.now() - timedelta(days=1))

    def redeem(index: int) -> bool:
        try:
            with work(shop.tenant) as session:
                catalogue.redeem_coupon(
                    session, "ONCE", redemption_key=f"tests:race:{index}", line_nets=[1000],
                    redeemer_client_id=shop.client_id,
                )  # fmt: skip
            return True
        except ValidationFailed:
            return False

    with ThreadPoolExecutor(4) as pool:
        assert sorted(pool.map(redeem, range(4))) == [False, False, False, True]


# --- concurrency and the whole-ledger property -------------------------------------------------------------


def test_concurrent_spending_cannot_overspend_a_payment(shop):
    """Four desks apply the same 1000 of credit to four different items at once: exactly 1000 is applied."""
    from concurrent.futures import ThreadPoolExecutor

    with work(shop.tenant) as session:
        payment_id = cash(session, shop, 1000).id
        targets = [charge(session, shop, 1000).id for _ in range(4)]

    def apply(charge_id):
        try:
            with work(shop.tenant) as session:
                svc.allocate(session, payment_id, allocations=[(charge_id, 600)])
            return 600
        except ValidationFailed:
            return 0

    with ThreadPoolExecutor(4) as pool:
        assert sorted(pool.map(apply, targets)) == [0, 0, 0, 600]
    with work(shop.tenant) as session:
        assert session.get(Payment, payment_id).unapplied_minor == 400
        assert svc.spend_credit(session, shop.client_id) == 400
        assert_books_agree(session)


def test_concurrent_payments_with_one_key_charge_once(shop):
    from concurrent.futures import ThreadPoolExecutor

    ready(shop)
    key = uuid4().hex

    def pay(_):
        with work(shop.tenant) as session:
            return card(session, shop, 900, idempotency_key=key).id

    with ThreadPoolExecutor(4) as pool:
        assert len(set(pool.map(pay, range(4)))) == 1
    with work(shop.tenant) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1
        assert_books_agree(session)
    assert provider_payments(shop, key) == 1


def test_books_agree_after_a_random_sequence_including_every_undo(shop):
    """Property test (overview section 5) over the whole command set: after every step the ledger balances,
    the projections equal the rows, and every invoice's instalments add up to its total."""
    rng = random.Random(20261111)
    fake = payment_provider.get("fake")
    steps = ["charge", "charge", "invoice", "cash", "card", "ach", "settle", "credit", "refund", "reverse", "void_item",
             "adjust", "void_invoice", "void_payment", "release", "schedule", "move", "refund_credit"]  # fmt: skip

    def pick(session, stmt):
        rows = session.scalars(stmt.order_by(func.random()).limit(1)).all()
        return rows[0] if rows else None

    live = (Charge.status == "active", Charge.kind != "reversal")
    for _step in range(160):
        # one transaction per step, as one request each: a credit refund plans only over committed payments
        with work(shop.tenant) as session:
            action = rng.choice(steps)
            if action == "charge":
                charge(session, shop, rng.randint(1, 5000), quantity=Decimal(rng.choice(["1", "3", "0.5"])))
            elif action == "invoice":
                loose = session.scalars(select(Charge.id).where(*live, Charge.invoice_id.is_(None)).limit(3)).all()
                if loose:
                    svc.create_invoice_for_charges(session, loose)
            elif action in ("cash", "card", "ach"):
                token = {"cash": None, "card": "tok_card_ok", "ach": rng.choice(["tok_ach_ok", "tok_ach_fail"])}[action]
                kind = {"cash": rng.choice(["cash", "gift_card", "cheque"]), "card": "card", "ach": "bank_debit"}[
                    action
                ]
                payment = svc.take_payment(
                    session, client_id=shop.client_id, location_id=shop.location_id, amount_minor=rng.randint(1, 6000),
                    tender_kind=kind, method_token=token, idempotency_key=uuid4().hex,
                )  # fmt: skip
                svc.allocate(session, payment.id)
            elif action == "settle":
                for payment in session.scalars(select(Payment).where(Payment.status == "processing")).all():
                    fake.settle(payment.provider_payment_ref)
                    svc.confirm_payment(session, payment.id)
            elif action == "credit":
                svc.spend_credit(session, shop.client_id, limit=rng.randint(1, 3000))
            elif action == "refund" and (payment := pick(session, select(Payment).where(Payment.unapplied_minor > 0))):
                svc.refund(session, payment.id, amount_minor=rng.randint(1, payment.unapplied_minor), reason="Test",
                           idempotency_key=uuid4().hex)  # fmt: skip
            elif action == "refund_credit" and (credit := svc.credit_balance(session, shop.client_id)):
                svc.refund_credit(session, shop.client_id, amount_minor=rng.randint(1, credit), reason="Test",
                                  idempotency_key=uuid4().hex)  # fmt: skip
            elif action == "reverse" and (row := pick(session, select(Charge).where(*live))):
                svc.reverse(session, row.id, reason="Test")
            elif action == "void_item" and (
                row := pick(
                    session, select(Charge).where(*live, Charge.invoice_id.is_(None), Charge.applied_minor == 0)
                )
            ):
                svc.void_charge(session, row.id, reason="Test")
            elif action == "adjust" and (row := pick(session, select(Charge).where(*live))):
                svc.adjust_charge(session, row.id, reason="Test", unit_price_minor=rng.randint(0, 6000))
            elif action == "void_invoice" and (
                invoice := pick(session, select(Invoice).where(Invoice.status != "voided"))
            ):
                svc.void_invoice(session, invoice.id, reason="Test", release_allocations=True)
            elif action == "void_payment" and (
                payment := pick(session, select(Payment).where(
                    Payment.status == "succeeded", Payment.provider_account_id.is_(None), Payment.refunded_minor == 0))
            ):  # fmt: skip
                svc.void_payment(session, payment.id, reason="Test")
            elif action == "release" and (
                allocation := pick(session, select(PaymentAllocation).where(PaymentAllocation.status != "released"))
            ):
                svc.release_allocation(session, allocation.payment_id, allocation.id)
            elif action == "schedule" and (invoice := pick(session, select(Invoice).where(Invoice.status != "voided"))):
                plan = plans.generate(max(invoice.total_minor, 0), invoice.invoice_on, 1, "month", rng.randint(1, 6))
                svc.set_schedule(session, invoice.id, plan, basis={})
            elif action == "move" and (
                row := pick(session, select(Charge).where(*live, Charge.invoice_id.is_not(None)))
            ):
                target = pick(session, select(Invoice).where(Invoice.status != "voided", Invoice.id != row.invoice_id))
                if target:
                    svc.detach_charge(session, row.invoice_id, row.id, to_invoice_id=target.id)
            assert_books_agree(session)
            planned = dict(
                session.execute(
                    select(PaymentSchedule.invoice_id, func.sum(PaymentSchedule.amount_minor)).group_by(
                        PaymentSchedule.invoice_id
                    )
                ).all()
            )
            for invoice in session.scalars(select(Invoice).where(Invoice.status != "voided")):
                assert planned[invoice.id] == max(invoice.total_minor, 0)
    with work(shop.tenant) as session:
        assert transactions(session) > 100 and session.scalar(select(func.count()).select_from(Refund)) > 0
    with tenant_session(shop.tenant.id) as session:  # and it all committed: the deferred triggers agreed
        assert sum(balances(session).values()) == 0


@pytest.mark.parametrize(("answer", "refunded", "credit"), [("succeeded", 300, 200), ("failed", 0, 500)])
def test_a_pending_provider_refund_reserves_the_money_until_it_settles(shop, monkeypatch, answer, refunded, credit):
    from app.ports.payment_provider import RefundState

    fake = payment_provider.get("fake")
    monkeypatch.setattr(fake, "refund", lambda **_: RefundState("fake_ref_slow", "pending"))
    monkeypatch.setattr(fake, "find_refund", lambda **_: None)
    with work(shop.tenant) as session:  # the payment commits first, as in production
        payment_id = card(session, shop, 500).id
    with work(shop.tenant) as session:
        payment = session.get(svc.Payment, payment_id)
        posted = transactions(session)
        pending = svc.refund(session, payment.id, amount_minor=300, reason="Slow bank", idempotency_key=uuid4().hex)
        assert (pending.status, payment.refunded_minor, payment.unapplied_minor) == ("pending", 300, 200)  # reserved
        assert transactions(session) == posted  # not in the ledger until it has happened
        monkeypatch.setattr(fake, "get_refund", lambda **_: RefundState("fake_ref_slow", "pending"))
        assert svc.confirm_refund(session, pending.id).status == "pending"
        assert webhooks.reconcile(session)["refunds"] == 1
        monkeypatch.setattr(fake, "get_refund", lambda **_: RefundState("fake_ref_slow", answer, "Returned"))
        webhooks.apply_event(session, "refund", "fake_ref_slow")  # the processor's webhook
        assert (pending.status, payment.refunded_minor, payment.unapplied_minor) == (answer, refunded, credit)
        assert transactions(session) == posted + (answer == "succeeded")
        assert svc.confirm_refund(session, pending.id).status == answer  # a replay changes nothing
        assert transactions(session) == posted + (answer == "succeeded")
        assert_books_agree(session)


def test_a_payment_under_a_held_receipt_counter_charges_nothing_and_its_key_replays(shop, monkeypatch):
    """The `initiated` payment row commits in a short transaction before the processor is charged. When another
    transaction holds what that needs (the receipt counter) past 500 ms, the payment is 409 `request-in-progress`
    before any charge; it never falls back to an uncommitted row a dying request would leave unfindable. The same
    Idempotency-Key afterwards charges once."""
    import threading

    from app.modules import platform

    ready(shop)
    with work(shop.tenant) as session:
        cash(session, shop, 100)  # the tenant has issued a receipt: its counter row exists
    fake, charged = payment_provider.get("fake"), []
    real = fake.create_payment

    def spy(**kwargs):
        with tenant_session(shop.tenant.id) as other:
            charged.append(other.scalar(select(func.count()).select_from(Payment)))
        return real(**kwargs)

    monkeypatch.setattr(fake, "create_payment", spy)
    locked, release = threading.Event(), threading.Event()

    def hold():
        with tenant_session(shop.tenant.id) as other:
            platform.service.next_number(other, "receipt")
            locked.set()
            release.wait(15)
        # rolled back: the number is not used

    holder = threading.Thread(target=hold)
    holder.start()
    assert locked.wait(10)
    try:
        with pytest.raises(Conflict) as refused, work(shop.tenant) as session:
            card(session, shop, 500, idempotency_key="pay-1")
        assert refused.value.code == "request-in-progress"
    finally:
        release.set()
        holder.join(20)
    assert charged == []  # the processor was never asked to charge
    with work(shop.tenant) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1  # the cash payment only
        first = card(session, shop, 500, idempotency_key="pay-1")
        assert first.status == "succeeded"
    with work(shop.tenant) as session:
        again = card(session, shop, 500, idempotency_key="pay-1")
        assert again.id == first.id and charged == [2]  # committed before the charge, and charged once


def _charges_seen(shop, monkeypatch) -> list:
    """Spy on the fake processor: each charge records how many committed rows carry its Idempotency-Key."""
    fake, seen = payment_provider.get("fake"), []
    real = fake.create_payment

    def spy(**kwargs):
        key = kwargs["idempotency_key"].split(":payment:")[1]
        with tenant_session(shop.tenant.id) as other:
            seen.append(other.scalar(select(func.count()).select_from(Payment).where(Payment.idempotency_key == key)))
        return real(**kwargs)

    monkeypatch.setattr(fake, "create_payment", spy)
    return seen


def _hold_receipt_counter(shop, release_after: float | None = None):
    """Another request takes a receipt number and keeps its transaction open until released (then rolls back)."""
    import threading

    from app.modules import platform

    locked, release = threading.Event(), threading.Event()

    def hold():
        with tenant_session(shop.tenant.id) as other:
            platform.service.next_number(other, "receipt")
            locked.set()
            release.wait(release_after if release_after is not None else 15)

    holder = threading.Thread(target=hold)
    holder.start()
    assert locked.wait(10)
    return release, holder


@pytest.mark.parametrize("held_ms", [505, 515, 530])
def test_a_counter_freed_just_after_the_timeout_never_charges_an_uncommitted_payment(shop, monkeypatch, held_ms):
    """Another request holds the receipt counter a little past the 500 ms lock timeout, then lets go: the payment
    is 409 or charged with its row committed, never charged with only an uncommitted row."""
    ready(shop)
    with work(shop.tenant) as session:
        cash(session, shop, 100)
    seen = _charges_seen(shop, monkeypatch)
    release, holder = _hold_receipt_counter(shop, release_after=held_ms / 1000)
    try:
        with work(shop.tenant) as session:
            card(session, shop, 500, idempotency_key=f"edge-{held_ms}")
    except Conflict as refused:
        assert refused.code == "request-in-progress"
    finally:
        release.set()
        holder.join(20)
    assert all(committed == 1 for committed in seen), seen


def test_a_first_receipt_while_another_request_creates_the_counter_charges_nothing(shop, monkeypatch):
    """The tenant's counter row is being inserted by another, uncommitted request: 409 before any charge."""
    ready(shop)
    seen = _charges_seen(shop, monkeypatch)
    release, holder = _hold_receipt_counter(shop)
    try:
        with pytest.raises(Conflict) as refused, work(shop.tenant) as session:
            card(session, shop, 500, idempotency_key="first-receipt")
        assert refused.value.code == "request-in-progress"
    finally:
        release.set()
        holder.join(20)
    assert seen == []


def test_a_database_error_that_is_not_a_lock_charges_nothing(shop, monkeypatch):
    """The short transaction fails for another reason (here it cannot connect): the error stands, nothing is
    charged, nothing falls back to the caller's transaction."""
    from sqlalchemy.exc import OperationalError

    from app.modules.billing import service as svc

    ready(shop)
    seen = _charges_seen(shop, monkeypatch)
    real = svc.tenant_session

    def refused(*args, **kwargs):
        raise OperationalError("connect", None, Exception("too many clients already"))

    with pytest.raises(OperationalError), work(shop.tenant) as session:
        monkeypatch.setattr(svc, "tenant_session", refused)
        card(session, shop, 500, idempotency_key="no-connection")
    monkeypatch.setattr(svc, "tenant_session", real)
    assert seen == []
    with work(shop.tenant) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 0


def test_a_payment_for_a_client_created_in_the_same_transaction_does_not_hold_the_counter_over_the_charge(
    shop, monkeypatch
):
    """Own-row path (a guest's new client): the row is written in the caller's transaction, its receipt number is
    taken and committed in a short step first, so no other request waits on the counter during the charge; the
    provider key is the tenant and the request's Idempotency-Key, so a retry replays the same charge."""
    from app.modules import platform
    from app.modules.clients.models import Client

    ready(shop)
    fake, numbers = payment_provider.get("fake"), []
    real = fake.create_payment

    def spy(**kwargs):
        assert kwargs["idempotency_key"] == f"{shop.tenant.id}:payment:guest-1"
        with tenant_session(shop.tenant.id) as other:
            other.execute(text("SET LOCAL lock_timeout = '100ms'"))
            numbers.append(platform.service.next_number(other, "receipt"))  # would time out under a held counter
        return real(**kwargs)

    monkeypatch.setattr(fake, "create_payment", spy)
    with work(shop.tenant) as session:
        guest = Client(first_name="Guest", last_name="Payer", home_location_id=shop.location_id)
        session.add(guest)
        session.flush()
        paid = card(session, shop, 500, idempotency_key="guest-1", client_id=guest.id)
        assert paid.status == "succeeded"
    assert len(numbers) == 1 and paid.receipt_number < numbers[0]


def test_an_unknown_payment_the_processor_never_created_is_abandoned_and_its_key_freed(shop, monkeypatch):
    """A 429 (or a timeout before the processor saw the call) leaves the payment `unknown` with no processor
    object: after the abandon window the sweep, finding nothing by the key, cancels it, so the key stops
    answering `unknown` and the payer can start again."""
    from app.ports.payment_provider import PaymentState

    ready(shop)
    fake = payment_provider.get("fake")
    monkeypatch.setattr(fake, "create_payment", lambda **_: PaymentState("", "unknown"))
    with work(shop.tenant) as session:
        assert card(session, shop, 500, idempotency_key="rate-limited").status == "unknown"
    monkeypatch.setattr(fake, "find_payment", lambda **_: None)
    with clock.freeze(clock.now() + timedelta(minutes=10)), work(shop.tenant) as session:
        webhooks.reconcile(session)  # inside the window: still unknown, the processor may yet show it
    with work(shop.tenant) as session:
        assert session.scalar(select(Payment.status)) == "unknown"
    with clock.freeze(clock.now() + timedelta(minutes=40)), work(shop.tenant) as session:
        webhooks.reconcile(session)
    with work(shop.tenant) as session:
        assert card(session, shop, 500, idempotency_key="rate-limited").status == "cancelled"
