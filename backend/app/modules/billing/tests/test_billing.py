"""billing kernel: taxed charges, invoices, payments through the fake provider, allocation, refund, reversal,
and the ledger invariants that must hold after every operation (ADR 0003)."""

import random
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import Principal, system_principal
from app.core.db.session import tenant_session
from app.core.errors import Conflict, PermissionDenied, ValidationFailed
from app.core.events import OutboxEvent
from app.core.pagination import ListQuery
from app.modules import billing, clients
from app.modules.billing.domain.money import net_amount, round_half_up, tax_amount
from app.modules.billing.models import (
    Charge,
    ChargeTax,
    Dispute,
    Invoice,
    LedgerEntry,
    LedgerTransaction,
    Payment,
    PaymentAllocation,
    ProviderAccount,
    Refund,
    Tax,
    TaxRate,
    TenderType,
)
from app.modules.platform.models import Tenant
from app.ports import payment_provider
from conftest import add_staff, login, new_client

API = "/api/v1"
SYSTEM = system_principal("tests")
svc = billing.service


def work(tenant):
    return tenant_session(tenant.id, actor=SYSTEM)


def key() -> dict:
    return {"Idempotency-Key": f"test-{uuid4().hex}"}


@pytest.fixture
def shop(client, tenant, owner):
    """A location, a client, and a revenue category taxed at 8.25% from 2020 and 10% from 2030."""
    location = client.post(
        f"{API}/locations", headers=owner, json={"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    ).json()["id"]
    person = new_client(client, owner, location)
    with work(tenant) as session:
        tax = svc.create_tax(
            session, code="ST", label="Sales tax", rate=Decimal("0.0825"), effective_from_on=date(2020, 1, 1)
        )
        session.add(TaxRate(tax_id=tax.id, rate=Decimal("0.10"), effective_from_on=date(2030, 1, 1)))
        category = svc.create_revenue_category(session, code="RENT", label="Rentals", tax_ids=[tax.id])
        assert svc.create_tax(session, code="st", label="x", rate=Decimal(0), effective_from_on=date.min).id == tax.id
        assert svc.create_revenue_category(session, code="rent", label="x").id == category.id  # idempotent by code
        ids = SimpleNamespace(
            tenant=tenant, owner=owner, location_id=UUID(location), client_id=UUID(person["id"]), tax_id=tax.id,
            category_id=category.id,
        )  # fmt: skip
    return ids


def charge(session, shop, price=2000, **over) -> Charge:
    args = {
        "client_id": shop.client_id, "location_id": shop.location_id, "description": "Court hire",
        "unit_price_minor": price, "revenue_category_id": shop.category_id, "source_context": "tests",
        "source_type": "thing", "source_id": uuid4(),
    }  # fmt: skip
    return svc.post_charge(session, **(args | over))


def cash(session, shop, amount, **over) -> Payment:
    args = {"client_id": shop.client_id, "location_id": shop.location_id, "amount_minor": amount, "tender_kind": "cash"}
    return svc.take_payment(session, **(args | over))


def card(session, shop, amount, token="tok_card_ok", **over) -> Payment:
    over = {"idempotency_key": uuid4().hex, "tender_kind": "card"} | over
    return cash(session, shop, amount, method_token=token, **over)


def balances(session) -> dict[str, int]:
    """Ledger account -> debit minus credit."""
    rows = session.execute(
        select(LedgerEntry.account, func.sum(LedgerEntry.debit_minor - LedgerEntry.credit_minor)).group_by(
            LedgerEntry.account
        )
    )
    return {account: int(balance) for account, balance in rows}


def assert_books_agree(session) -> None:
    """ADR 0003 section 2: the cached projections equal what the rows say, and both equal the ledger."""
    session.flush()
    ledger = balances(session)
    assert sum(ledger.values()) == 0  # every transaction balances, so the whole ledger does
    live = PaymentAllocation.status != "released"
    for row in session.scalars(select(Charge)):
        applied = session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount_minor), 0)).where(
                PaymentAllocation.charge_id == row.id, live
            )
        )
        assert row.applied_minor == applied, "charge.applied_minor drifted from its allocations"
    credit = 0
    for row in session.scalars(select(Payment)):
        allocated = session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount_minor), 0)).where(
                PaymentAllocation.payment_id == row.id, live
            )
        )
        expected = row.amount_minor - allocated - row.refunded_minor if row.status == "succeeded" else 0
        assert row.unapplied_minor == expected, "payment.unapplied_minor drifted"
        credit += row.unapplied_minor
    applied_total = session.scalar(
        select(func.coalesce(func.sum(PaymentAllocation.amount_minor), 0)).where(PaymentAllocation.status == "applied")
    )
    charged = session.scalar(select(func.coalesce(func.sum(Charge.total_minor), 0)))
    settled = session.scalar(
        select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.status == "succeeded")
    )
    refunded = session.scalar(
        select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(Refund.status == "succeeded")
    )
    # An open dispute's money stays a liability (client_credit) parked in disputed_funds until it closes.
    disputed = session.scalar(select(func.coalesce(func.sum(Dispute.amount_minor), 0)).where(Dispute.status == "open"))
    assert ledger.get("receivable", 0) == charged - applied_total
    assert -ledger.get("client_credit", 0) == credit + disputed
    assert ledger.get("disputed_funds", 0) == disputed
    assert ledger.get("funds_received", 0) == settled - refunded
    assert -ledger.get("revenue", 0) == session.scalar(select(func.coalesce(func.sum(Charge.net_minor), 0)))
    assert -ledger.get("tax_payable", 0) == session.scalar(select(func.coalesce(func.sum(Charge.tax_minor), 0)))
    for invoice in session.scalars(select(Invoice)):
        total = session.scalar(
            select(func.coalesce(func.sum(Charge.total_minor), 0)).where(Charge.invoice_id == invoice.id)
        )
        paid = session.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount_minor), 0))
            .join(Charge, Charge.id == PaymentAllocation.charge_id)
            .where(Charge.invoice_id == invoice.id, PaymentAllocation.status == "applied")
        )
        assert (invoice.total_minor, invoice.balance_minor) == (total, total - paid)


def event_types(tenant) -> list[str]:
    with tenant_session(tenant.id) as session:
        return list(
            session.scalars(
                select(OutboxEvent.event_type).where(OutboxEvent.event_type.like("billing.%")).order_by(OutboxEvent.id)
            )
        )


# --- arithmetic --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "rounded"), [("0.5", 1), ("1.5", 2), ("2.5", 3), ("2.4999", 2), ("-0.5", -1), ("-2.5", -3), ("0", 0)]
)
def test_rounding_is_half_up_away_from_zero(amount, rounded):
    assert round_half_up(Decimal(amount)) == rounded


def test_line_and_tax_amounts():
    assert net_amount(Decimal("1.5"), 1001) == 1502  # 1501.5 rounds up, once, at the line
    assert net_amount(Decimal(3), 333, 99) == 900
    assert tax_amount(2000, Decimal("0.0825")) == 165
    assert tax_amount(1006, Decimal("0.0825")) == 83  # 82.995 rounds up
    assert tax_amount(0, Decimal("0.0825")) == 0


# --- charges -----------------------------------------------------------------------------------------------


def test_post_charge_is_taxed_posted_audited_and_published(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop, 2000, quantity=Decimal("1.5"), discount_minor=500)
        assert (row.net_minor, row.tax_minor, row.total_minor) == (2500, 206, 2706)  # 2500 * 8.25% = 206.25
        assert row.status == "active" and row.kind == "standard" and row.applied_minor == 0
        assert row.bill_on == row.revenue_on  # today at the location
        snapshot = session.scalars(select(ChargeTax).where(ChargeTax.charge_id == row.id)).one()
        assert (snapshot.rate, snapshot.amount_minor, snapshot.is_excluded) == (Decimal("0.082500"), 206, False)
        assert balances(session) == {"receivable": 2706, "revenue": -2500, "tax_payable": -206}
        entries = session.scalars(select(LedgerEntry).where(LedgerEntry.charge_id == row.id)).all()
        assert {e.account: (e.revenue_category_id, e.tax_id) for e in entries} == {
            "receivable": (None, None), "revenue": (shop.category_id, None), "tax_payable": (None, shop.tax_id),
        }  # fmt: skip
        assert all(e.effective_on == row.revenue_on and e.currency == "USD" for e in entries)
        audit = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == row.id)).one()
        assert audit.action == "billing.charge.create" and audit.changes["total_minor"] == [None, 2706]
        assert_books_agree(session)
    assert event_types(shop.tenant) == ["billing.charge.created"]


def test_post_charge_is_idempotent_by_origin(shop):
    source = uuid4()
    with work(shop.tenant) as session:
        first = charge(session, shop, source_id=source)
        again = charge(session, shop, 9999, source_id=source)  # a retried job: same origin, nothing new
        assert again.id == first.id and again.total_minor == first.total_minor
        other_line = charge(session, shop, source_id=source, source_line_no=1)
        assert other_line.id != first.id
        assert session.scalar(select(func.count()).select_from(LedgerTransaction)) == 2


def test_tax_selection_by_date_exclusion_and_deactivation(shop):
    with work(shop.tenant) as session:
        assert charge(session, shop, 1000, revenue_on=date(2031, 6, 1)).tax_minor == 100  # the 2030 rate
        assert charge(session, shop, 1000, revenue_on=date(2019, 12, 31)).tax_minor == 0  # before any rate
        excluded = charge(session, shop, 1000, exclude_tax_ids=[shop.tax_id])
        row = session.scalars(select(ChargeTax).where(ChargeTax.charge_id == excluded.id)).one()
        assert (excluded.tax_minor, row.is_excluded, row.amount_minor) == (0, True, 0)  # the exclusion is kept
        untaxed = charge(session, shop, 1000, revenue_category_id=None)  # the seeded `uncategorised` row
        assert untaxed.tax_minor == 0 and untaxed.revenue_category_id == svc.default_revenue_category(session).id
        tax = session.get(Tax, shop.tax_id)
        tax.is_active, tax.deactivated_on = False, date(2026, 6, 1)
        session.flush()
        assert charge(session, shop, 1000, revenue_on=date(2026, 5, 31)).tax_minor == 83
        assert charge(session, shop, 1000, revenue_on=date(2026, 6, 1)).tax_minor == 0
        assert_books_agree(session)


def test_free_charge_is_recorded_but_posts_nothing(shop):
    with work(shop.tenant) as session:
        free = charge(session, shop, 1500, discount_minor=1500)
        assert free.total_minor == 0 and balances(session) == {}


def test_post_charge_validation(shop):
    with work(shop.tenant) as session:
        for bad in ({"unit_price_minor": -1}, {"quantity": 0}, {"discount_minor": 2001}, {"discount_minor": -1}):
            with pytest.raises(ValidationFailed):
                charge(session, shop, **bad)
        with pytest.raises(ValidationFailed) as unknown:
            charge(session, shop, revenue_category_id=uuid4())
        assert unknown.value.extra["errors"][0]["pointer"] == "/revenue_category_id"
        with pytest.raises(ValidationFailed):
            charge(session, shop, client_id=uuid4())
        person = clients.service.get(session, shop.client_id)
        person.status, person.disabled_at = "disabled", clock.now()
        session.flush()
        with pytest.raises(ValidationFailed):
            charge(session, shop)  # nothing new is sold to a disabled client
        assert session.scalar(select(func.count()).select_from(Charge)) == 0


@pytest.mark.parametrize(
    ("zone", "expected"),
    [("America/Chicago", date(2026, 10, 31)), ("Asia/Kolkata", date(2026, 11, 1)), ("Pacific/Auckland", date(2026, 11, 1))],
)  # fmt: skip
def test_dates_are_local_to_the_location(client, shop, zone, expected):
    """One instant, three sites: bill date, revenue date and the ledger's effective date follow the wall there."""
    site = client.post(
        f"{API}/locations", headers=shop.owner, json={"name": zone, "time_zone": zone, "country_code": "US"}
    ).json()["id"]
    with clock.freeze(datetime(2026, 11, 1, 3, 0, tzinfo=UTC)), work(shop.tenant) as session:
        row = charge(session, shop, location_id=site)
        invoice = svc.create_invoice_for_charges(session, [row.id])
        payment = cash(session, shop, row.total_minor, location_id=site, invoice_id=invoice.id)
        assert (row.bill_on, row.revenue_on, invoice.invoice_on, invoice.due_on) == (expected,) * 4
        assert payment.received_at == datetime(2026, 11, 1, 3, 0, tzinfo=UTC)  # instants stay UTC
        assert set(session.scalars(select(LedgerEntry.effective_on))) == {expected}


def test_period_lock_refuses_back_dated_postings(shop):
    with work(shop.tenant) as session:
        session.get(Tenant, shop.tenant.id).billing_locked_through_on = date(2026, 9, 30)
        session.flush()
        with pytest.raises(Conflict) as locked:
            charge(session, shop, revenue_on=date(2026, 9, 30))
        assert locked.value.code == "period-locked"
        assert charge(session, shop, revenue_on=date(2026, 10, 1)).id


# --- invoices ----------------------------------------------------------------------------------------------


def test_invoice_groups_charges_and_numbers_are_sequential(client, shop):
    with work(shop.tenant) as session:
        a, b, c = charge(session, shop, 1000), charge(session, shop, 2000), charge(session, shop, 500)
        first = svc.create_invoice_for_charges(session, [a.id, b.id, a.id])  # a duplicate id is harmless
        second = svc.create_invoice_for_charges(session, [c.id], due_on=first.invoice_on)
        assert (first.number, second.number) == (1, 2)
        assert (first.total_minor, first.balance_minor, first.status) == (a.total_minor + b.total_minor,) * 2 + (
            "open",
        )
        assert first.bill_to_client_id == shop.client_id and a.invoice_id == b.invoice_id == first.id
        assert balances(session)["receivable"] == a.total_minor + b.total_minor + c.total_minor  # no posting of its own
        with pytest.raises(Conflict) as taken:
            svc.create_invoice_for_charges(session, [a.id])
        assert taken.value.code == "charge-not-invoiceable"
        with pytest.raises(ValidationFailed):
            svc.create_invoice_for_charges(session, [])
        with pytest.raises(ValidationFailed):
            svc.create_invoice_for_charges(session, [uuid4()])
        with pytest.raises(ValidationFailed):
            svc.create_invoice_for_charges(session, [charge(session, shop).id], due_on=date(2000, 1, 1))
    assert event_types(shop.tenant).count("billing.invoice.issued") == 2


def test_invoice_needs_one_location_and_a_named_payer(client, shop):
    other_site = client.post(
        f"{API}/locations", headers=shop.owner, json={"name": "West", "time_zone": "UTC", "country_code": "US"}
    ).json()["id"]
    child = new_client(client, shop.owner, shop.location_id)["id"]
    with work(shop.tenant) as session:
        here, there = charge(session, shop), charge(session, shop, location_id=other_site)
        with pytest.raises(ValidationFailed):
            svc.create_invoice_for_charges(session, [here.id, there.id])
        for_child = charge(session, shop, client_id=child)
        with pytest.raises(ValidationFailed) as payer:
            svc.create_invoice_for_charges(session, [here.id, for_child.id])
        assert payer.value.extra["errors"][0]["pointer"] == "/bill_to_client_id"
        family = svc.create_invoice_for_charges(session, [here.id, for_child.id], bill_to_client_id=shop.client_id)
        assert family.bill_to_client_id == shop.client_id  # a parent pays for the child's item (FAM-03)


# --- payments ----------------------------------------------------------------------------------------------


def test_cash_payment_pays_an_invoice_and_keeps_the_change_as_credit(shop):
    with work(shop.tenant) as session:
        first, second = charge(session, shop, 1000), charge(session, shop, 3000)
        invoice = svc.create_invoice_for_charges(session, [first.id])
        payment = cash(session, shop, first.total_minor + 700, invoice_id=invoice.id, external_reference="R-1")
        assert (payment.status, payment.receipt_number, payment.currency) == ("succeeded", 1, "USD")
        assert payment.settled_at is not None and payment.provider_account_id is None
        assert (invoice.status, invoice.balance_minor) == ("paid", 0)
        assert (first.applied_minor, payment.unapplied_minor) == (first.total_minor, 700)
        assert balances(session)["client_credit"] == -700  # the overpayment is a liability to the client
        assert_books_agree(session)

        # Spending account credit: oldest open item of the payer first, and only as far as the money goes.
        svc.allocate(session, payment.id)
        assert (second.applied_minor, payment.unapplied_minor) == (700, 0)
        assert svc.allocate(session, payment.id).unapplied_minor == 0  # nothing left: a no-op, not an error
        assert_books_agree(session)
        audits = session.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == payment.id)).all()
        assert audits == ["billing.payment.take", "billing.payment.reallocate"]  # one event per command
    assert event_types(shop.tenant)[-3:] == [
        "billing.invoice.issued", "billing.payment.succeeded", "billing.invoice.paid",
    ]  # fmt: skip


def test_partial_payments_move_the_invoice_through_its_states(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop, 1000)
        invoice = svc.create_invoice_for_charges(session, [row.id])
        cash(session, shop, 400, invoice_id=invoice.id)
        assert (invoice.status, invoice.balance_minor) == ("partially_paid", row.total_minor - 400)
        cash(session, shop, row.total_minor - 400, allocations=[(row.id, row.total_minor - 400)])
        assert (invoice.status, invoice.balance_minor) == ("paid", 0)
        assert_books_agree(session)
    assert event_types(shop.tenant).count("billing.invoice.paid") == 1


def test_explicit_allocation_guards(shop):
    with work(shop.tenant) as session:
        row, other = charge(session, shop, 1000), charge(session, shop, 1000)
        for bad, code in (
            ([(row.id, row.total_minor + 1)], "allocation-exceeds-balance"),
            ([(row.id, 0)], "allocation-exceeds-balance"),
            ([(row.id, 600), (other.id, 600)], "allocation-exceeds-payment"),
            ([(row.id, 100), (row.id, 100)], "validation-failed"),
            ([(uuid4(), 100)], "validation-failed"),
        ):
            with pytest.raises(ValidationFailed) as refused:
                cash(session, shop, 1000, allocations=bad)
            assert refused.value.code == code
        with pytest.raises(ValidationFailed):
            cash(session, shop, 0)
        with pytest.raises(ValidationFailed):
            cash(session, shop, 100, tender_kind="barter")
        with pytest.raises(ValidationFailed):
            cash(session, shop, 100, client_id=uuid4())
        with pytest.raises(ValidationFailed):
            cash(session, shop, 100, location_id=uuid4())
        with pytest.raises(ValidationFailed):
            cash(session, shop, 100, tender_kind="card")  # no method token, no key
        session.scalars(select(TenderType).where(TenderType.kind == "cheque")).one().is_enabled = False
        session.flush()
        with pytest.raises(ValidationFailed):
            cash(session, shop, 100, tender_kind="cheque")


def test_card_success_is_settled_and_keeps_no_card_data(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop, 2000)
        payment = card(session, shop, row.total_minor, allocations=[(row.id, row.total_minor)])
        assert (payment.status, payment.tender_kind, payment.card_brand, payment.card_last4) == (
            "succeeded", "card", "visa", "4242",
        )  # fmt: skip
        account = session.get(ProviderAccount, payment.provider_account_id)
        assert (account.provider, account.status) == ("fake", "active")
        assert payment.provider_payment_ref.startswith("fake_pay_") and row.applied_minor == row.total_minor
        assert_books_agree(session)


def test_declined_card_is_a_state_not_an_exception(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop, 2000)
        ledger = balances(session)
        payment = card(session, shop, row.total_minor, "tok_card_insufficient", allocations=[(row.id, row.total_minor)])
        assert (payment.status, payment.failure_category) == ("failed", "insufficient_funds")
        assert payment.failure_message and payment.settled_at is None and payment.unapplied_minor == 0
        assert row.applied_minor == 0 and balances(session) == ledger  # nothing settled, nothing posted
        with pytest.raises(Conflict) as dead:
            svc.allocate(session, payment.id)
        assert dead.value.code == "payment-not-allocatable"
        with pytest.raises(Conflict):
            svc.refund(session, payment.id, amount_minor=1, reason="x")
        assert svc.confirm_payment(session, payment.id).status == "failed"  # terminal
        assert_books_agree(session)
    assert event_types(shop.tenant)[-1] == "billing.payment.failed"


def test_unknown_outcome_is_never_treated_as_a_decline(shop):
    """A processor timeout: no failure event, no retry under a new key; confirm_payment resolves it."""
    with work(shop.tenant) as session:
        row = charge(session, shop, 2000)
        payment = card(session, shop, row.total_minor, "tok_card_unknown", allocations=[(row.id, row.total_minor)])
        assert payment.status == "unknown" and row.applied_minor == 0
    assert "billing.payment.failed" not in event_types(shop.tenant)
    with work(shop.tenant) as session:
        payment = svc.confirm_payment(session, payment.id)
        assert (payment.status, payment.unapplied_minor) == ("succeeded", payment.amount_minor)  # credit to apply
        assert_books_agree(session)


def test_bank_debit_is_pending_until_the_bank_answers(shop):
    fake = payment_provider.get("fake")
    with work(shop.tenant) as session:
        row = charge(session, shop, 2000)
        invoice = svc.create_invoice_for_charges(session, [row.id])
        ledger = balances(session)
        payment = card(session, shop, row.total_minor, "tok_ach_ok", tender_kind="bank_debit", invoice_id=invoice.id)
        allocation = session.scalars(select(PaymentAllocation)).one()
        assert (payment.status, allocation.status, invoice.status) == ("processing", "provisional", "payment_pending")
        assert row.applied_minor == row.total_minor  # "amount due now" is covered, so nobody charges it again
        assert invoice.balance_minor == row.total_minor and payment.unapplied_minor == 0
        assert balances(session) == ledger  # the ledger holds settled facts only
        assert svc.confirm_payment(session, payment.id).status == "processing"  # the bank has not answered yet
        assert_books_agree(session)

        fake.settle(payment.provider_payment_ref)
        svc.confirm_payment(session, payment.id)
        assert (payment.status, allocation.status, invoice.status) == ("succeeded", "applied", "paid")
        assert allocation.applied_at is not None and invoice.balance_minor == 0
        posted = session.scalar(select(func.count()).select_from(LedgerTransaction))
        for _ in range(3):  # a replayed webhook, a second sweep: nothing happens twice
            svc.confirm_payment(session, payment.id)
        assert session.scalar(select(func.count()).select_from(LedgerTransaction)) == posted
        assert_books_agree(session)
    events = event_types(shop.tenant)
    assert events[-3:] == ["billing.payment.processing", "billing.payment.succeeded", "billing.invoice.paid"]
    assert events.count("billing.payment.succeeded") == 1


def test_returned_bank_debit_releases_what_it_was_holding(shop):
    fake = payment_provider.get("fake")
    with work(shop.tenant) as session:
        row = charge(session, shop, 2000)
        invoice = svc.create_invoice_for_charges(session, [row.id])
        ledger = balances(session)
        payment = card(session, shop, row.total_minor, "tok_ach_fail", tender_kind="bank_debit", invoice_id=invoice.id)
        fake.settle(payment.provider_payment_ref)
        svc.confirm_payment(session, payment.id)
        allocation = session.scalars(select(PaymentAllocation)).one()
        assert (payment.status, payment.failure_category) == ("failed", "insufficient_funds")
        assert (allocation.status, allocation.release_reason) == ("released", "payment_failed")
        assert (row.applied_minor, invoice.status, invoice.balance_minor) == (0, "open", row.total_minor)
        assert balances(session) == ledger
        assert_books_agree(session)
    assert event_types(shop.tenant)[-1] == "billing.payment.failed"


def test_take_payment_is_idempotent_by_key(shop):
    with work(shop.tenant) as session:
        first = card(session, shop, 1500, idempotency_key="same-key")
        again = card(session, shop, 1500, idempotency_key="same-key")
        assert again.id == first.id
        assert session.scalar(select(func.count()).select_from(Payment)) == 1
    # A retry after the first attempt rolled back resolves to the same provider payment: no second charge.
    refs = []
    for attempt in range(2):
        try:
            with work(shop.tenant) as session:
                refs.append(card(session, shop, 900, idempotency_key="crashy").provider_payment_ref)
                if attempt == 0:
                    raise RuntimeError("the request dies after the provider answered")
        except RuntimeError:
            pass
    assert refs[0] == refs[1]
    with work(shop.tenant) as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 2


# --- refunds and reversals ---------------------------------------------------------------------------------


def test_refund_returns_only_unapplied_money(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop, 1000)
        payment = card(session, shop, row.total_minor + 500, allocations=[(row.id, row.total_minor)])
        with pytest.raises(ValidationFailed) as too_much:
            svc.refund(session, payment.id, amount_minor=501, reason="Overpaid", idempotency_key="r0")
        assert too_much.value.code == "refund-exceeds-unapplied"
        with pytest.raises(ValidationFailed):
            svc.refund(session, payment.id, amount_minor=500, reason="  ", idempotency_key="r0")
        with pytest.raises(ValidationFailed):
            svc.refund(session, payment.id, amount_minor=500, reason="Overpaid")  # processed: key required
        refund = svc.refund(session, payment.id, amount_minor=300, reason="Overpaid", idempotency_key="r1")
        assert (refund.status, refund.method, refund.currency) == ("succeeded", "original", "USD")
        assert refund.provider_refund_ref.startswith("fake_ref_") and refund.refund_on == row.bill_on
        assert (payment.refunded_minor, payment.unapplied_minor) == (300, 200)
        assert (
            svc.refund(session, payment.id, amount_minor=300, reason="Overpaid", idempotency_key="r1").id == refund.id
        )
        assert payment.refunded_minor == 300  # the replay moved nothing
        assert balances(session)["funds_received"] == payment.amount_minor - 300
        assert_books_agree(session)
    assert event_types(shop.tenant)[-1] == "billing.payment.refunded"


def test_cash_refund_is_external_and_a_provider_refusal_moves_nothing(shop):
    fake = payment_provider.get("fake")
    with work(shop.tenant) as session:
        payment = cash(session, shop, 800)
        with pytest.raises(ValidationFailed):
            svc.refund(session, payment.id, amount_minor=800, reason="Left", method="original")
        refund = svc.refund(session, payment.id, amount_minor=800, reason="Left")
        assert (refund.method, refund.status, refund.provider_refund_ref) == ("external", "succeeded", None)
        assert payment.unapplied_minor == 0

        by_card = card(session, shop, 600)
        # The processor already returned part of it out of band, so it refuses the full amount.
        fake.refund(
            account_ref="x", provider_payment_ref=by_card.provider_payment_ref, amount_minor=200, idempotency_key="oob"
        )
        failed = svc.refund(session, by_card.id, amount_minor=600, reason="Left", idempotency_key=uuid4().hex)
        assert failed.status == "failed" and failed.failure_message
        assert (by_card.refunded_minor, by_card.unapplied_minor) == (0, 600)
        assert_books_agree(session)


def test_reverse_negates_the_charge_and_frees_the_money(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop, 2000)
        invoice = svc.create_invoice_for_charges(session, [row.id])
        payment = card(session, shop, row.total_minor, invoice_id=invoice.id)
        with pytest.raises(ValidationFailed):
            svc.reverse(session, row.id, reason=" ")
        reversal = svc.reverse(session, row.id, reason="Booked by mistake")
        assert (reversal.kind, reversal.reverses_charge_id, reversal.invoice_id) == ("reversal", row.id, invoice.id)
        assert (reversal.net_minor, reversal.tax_minor, reversal.total_minor) == (-2000, -165, -2165)
        assert reversal.revenue_on == row.revenue_on and reversal.reason == "Booked by mistake"
        assert (row.status, row.applied_minor) == ("reversed", 0) and row.reversed_at is not None
        negated = session.scalars(select(ChargeTax).where(ChargeTax.charge_id == reversal.id)).one()
        assert (negated.amount_minor, negated.rate) == (-165, Decimal("0.082500"))  # the snapshot, not a recompute
        allocation = session.scalars(select(PaymentAllocation)).one()
        assert (allocation.status, allocation.release_reason) == ("released", "charge_reversed")
        assert payment.unapplied_minor == payment.amount_minor  # the money is the client's credit again
        assert (invoice.total_minor, invoice.balance_minor, invoice.status) == (0, 0, "open")
        ledger = balances(session)
        assert (ledger["receivable"], ledger["revenue"], ledger["tax_payable"]) == (0, 0, 0)
        assert ledger["client_credit"] == -payment.amount_minor
        assert all(e.debit_minor >= 0 and e.credit_minor >= 0 for e in session.scalars(select(LedgerEntry)))
        for target in (row.id, reversal.id):  # at most once, and a reversal cannot itself be reversed
            with pytest.raises(Conflict) as twice:
                svc.reverse(session, target, reason="Again")
            assert twice.value.code == "charge-not-reversible"
        # Giving the money back is a separate, deliberate step.
        svc.refund(session, payment.id, amount_minor=payment.amount_minor, reason="Cancelled", idempotency_key="x1")
        assert sum(abs(v) for v in balances(session).values()) == 0
        # The same thing can be billed again under the next line number of its origin.
        assert charge(session, shop, source_id=row.source_id).id == row.id
        assert charge(session, shop, source_id=row.source_id, source_line_no=1).status == "active"
        assert_books_agree(session)
    types = event_types(shop.tenant)
    assert "billing.charge.reversed" in types and types.count("billing.invoice.paid") == 1


def test_reverse_releases_a_pending_bank_debit_without_touching_the_ledger(shop):
    with work(shop.tenant) as session:
        row = charge(session, shop, 1000)
        payment = card(session, shop, row.total_minor, "tok_ach_ok", tender_kind="bank_debit",
                       allocations=[(row.id, row.total_minor)])  # fmt: skip
        svc.reverse(session, row.id, reason="Cancelled", revenue_on=row.revenue_on)
        assert session.scalars(select(PaymentAllocation.status)).one() == "released"
        assert payment.unapplied_minor == 0 and balances(session).get("client_credit", 0) == 0
        payment_provider.get("fake").settle(payment.provider_payment_ref)
        assert svc.confirm_payment(session, payment.id).unapplied_minor == row.total_minor  # settles as credit
        assert_books_agree(session)


# --- the ledger itself -------------------------------------------------------------------------------------


def test_books_agree_after_a_random_sequence_of_operations(shop):
    """Property test (overview section 5): whatever the order of operations, projections equal the ledger."""
    rng = random.Random(20261110)
    fake = payment_provider.get("fake")
    with work(shop.tenant) as session:
        for _step in range(80):
            action = rng.choice(["charge", "charge", "cash", "card", "ach", "settle", "allocate", "refund", "reverse"])
            if action == "charge":
                row = charge(session, shop, rng.randint(1, 5000), quantity=Decimal(rng.choice(["1", "2", "0.5"])))
                if rng.random() < 0.5:
                    svc.create_invoice_for_charges(session, [row.id])
            elif action in ("cash", "card", "ach"):
                take = {"cash": cash, "card": card, "ach": card}[action]
                extra = {"token": "tok_ach_ok" if rng.random() < 0.7 else "tok_ach_fail", "tender_kind": "bank_debit"}
                payment = take(session, shop, rng.randint(1, 6000), **(extra if action == "ach" else {}))
                svc.allocate(session, payment.id)
            elif action == "settle":
                for payment in session.scalars(select(Payment).where(Payment.status == "processing")):
                    fake.settle(payment.provider_payment_ref)
                    svc.confirm_payment(session, payment.id)
            elif action == "allocate":
                for payment in session.scalars(select(Payment).where(Payment.unapplied_minor > 0)):
                    svc.allocate(session, payment.id)
            elif action == "refund":
                payment = session.scalars(select(Payment).where(Payment.unapplied_minor > 0).limit(1)).first()
                if payment:
                    amount = rng.randint(1, payment.unapplied_minor)
                    svc.refund(session, payment.id, amount_minor=amount, reason="Test", idempotency_key=uuid4().hex)
            else:
                row = session.scalars(
                    select(Charge).where(Charge.status == "active", Charge.kind == "standard").limit(1)
                ).first()
                if row:
                    svc.reverse(session, row.id, reason="Test")
            assert_books_agree(session)
        assert session.scalar(select(func.count()).select_from(LedgerTransaction)) > 40


def test_ledger_rows_cannot_be_changed_and_must_balance(shop):
    with work(shop.tenant) as session:
        charge(session, shop)
    for statement in ("UPDATE ledger_entry SET debit_minor = 1", "DELETE FROM ledger_entry",
                      "UPDATE ledger_transaction SET kind = 'correction'", "DELETE FROM ledger_transaction"):  # fmt: skip
        with pytest.raises(DBAPIError, match="permission denied"), tenant_session(shop.tenant.id) as session:
            session.execute(text(statement))
    lopsided = (
        "INSERT INTO ledger_entry (tenant_id, ledger_transaction_id, account, debit_minor, currency, effective_on, "
        "location_id) SELECT tenant_id, id, 'receivable', 5, 'USD', effective_on, :location FROM ledger_transaction"
    )
    with pytest.raises(IntegrityError, match="is not balanced"), tenant_session(shop.tenant.id) as s:
        s.execute(text(lopsided), {"location": shop.location_id})
    with pytest.raises(IntegrityError, match="is not balanced"), work(shop.tenant) as session:
        session.add(
            LedgerTransaction(
                kind="correction",
                source_type="charge",
                source_id=uuid4(),
                effective_on=date(2026, 1, 1),
                actor_type="system",
            )  # fmt: skip
        )  # a header with no lines
    with tenant_session(shop.tenant.id) as session:
        assert sum(balances(session).values()) == 0


def test_concurrent_allocations_cannot_overspend_a_charge(shop):
    """Two payments race for one charge: row locks serialise them, the second sees what is left."""
    from concurrent.futures import ThreadPoolExecutor

    with work(shop.tenant) as session:
        row_id = charge(session, shop, 1000).id
        total = session.get(Charge, row_id).total_minor

    def pay(_):
        with work(shop.tenant) as session:
            payment = cash(session, shop, total)
            svc.allocate(session, payment.id)
            return payment.unapplied_minor

    with ThreadPoolExecutor(4) as pool:
        left = sorted(pool.map(pay, range(4)))
    assert left == [0, total, total, total]
    with work(shop.tenant) as session:
        assert session.get(Charge, row_id).applied_minor == total
        assert_books_agree(session)


# --- API: gates, idempotency, shapes -----------------------------------------------------------------------


@pytest.fixture
def desk(client, shop):
    """Front Desk limited to the shop's location, and a Manager limited to another one."""
    west = client.post(
        f"{API}/locations", headers=shop.owner, json={"name": "West", "time_zone": "UTC", "country_code": "US"}
    ).json()["id"]
    front_email, _ = add_staff(shop.tenant, "front_desk", location_ids=[shop.location_id])
    manager_email, _ = add_staff(shop.tenant, "manager", location_ids=[west])
    view_email, _ = add_staff(shop.tenant, "view_only", location_ids=[shop.location_id])
    return SimpleNamespace(
        west=west, front=login(client, shop.tenant, front_email), west_manager=login(client, shop.tenant, manager_email),
        viewer=login(client, shop.tenant, view_email),
    )  # fmt: skip


def test_money_path_through_the_api(client, shop, desk):
    owner = shop.owner
    who = {"client_id": str(shop.client_id), "location_id": str(shop.location_id)}
    body = who | {"description": "Court hire", "unit_price_minor": 2000, "revenue_category_id": str(shop.category_id)}
    created = client.post(f"{API}/charges", headers=desk.front, json=body)
    assert created.status_code == 201, created.text
    item = created.json()
    assert (item["total_minor"], item["tax_minor"], item["source_type"]) == (2165, 165, "manual")
    listed = client.get(f"{API}/charges?client_id={shop.client_id}", headers=desk.front).json()["data"]
    assert [c["id"] for c in listed] == [item["id"]]
    invoice = client.post(f"{API}/invoices", headers=desk.front, json={"charge_ids": [item["id"]]}).json()
    assert invoice["number"] == 1 and [c["id"] for c in invoice["charges"]] == [item["id"]]

    pay = who | {"amount_minor": 2165 + 335, "tender_kind": "card", "method_token": "tok_card_ok",
                 "invoice_id": invoice["id"]}  # fmt: skip
    missing_key = client.post(f"{API}/payments", headers=desk.front, json=pay)
    assert missing_key.status_code == 422  # money movement refuses a request that cannot be replayed safely
    headers = desk.front | key()
    taken = client.post(f"{API}/payments", headers=headers, json=pay)
    assert taken.status_code == 201, taken.text
    payment = taken.json()
    assert (payment["status"], payment["unapplied_minor"], payment["allocations"][0]["status"]) == (
        "succeeded", 335, "applied",
    )  # fmt: skip
    assert "card_last4" not in payment and "provider_payment_ref" not in payment  # instrument details stay inside
    replay = client.post(f"{API}/payments", headers=headers, json=pay)
    assert replay.headers["Idempotent-Replayed"] == "true" and replay.json()["id"] == payment["id"]
    assert (
        client.get(f"{API}/payments?client_id={shop.client_id}", headers=owner).json()["data"][0]["id"] == payment["id"]
    )
    paid = client.get(f"{API}/invoices/{invoice['id']}", headers=desk.front).json()
    assert (paid["status"], paid["balance_minor"]) == ("paid", 0)
    assert client.get(f"{API}/invoices?status=paid", headers=owner).json()["data"][0]["id"] == invoice["id"]

    # Front Desk takes money but cannot give it back or undo a sale (rbac-matrix 6.10).
    refund = {"amount_minor": 335, "reason": "Overpaid"}
    url = f"{API}/payments/{payment['id']}"
    assert client.post(f"{url}/refunds", headers=desk.front | key(), json=refund).status_code == 403
    assert (
        client.post(f"{API}/charges/{item['id']}/reverse", headers=desk.front | key(), json={"reason": "x"}).status_code
        == 403
    )
    assert client.post(f"{url}/allocations", headers=desk.front, json={}).status_code == 403
    assert client.get(f"{API}/ledger-entries", headers=desk.front).status_code == 403
    # A manager of another location holds the keys but not this location: 404, never 403.
    assert client.post(f"{url}/refunds", headers=desk.west_manager | key(), json=refund).status_code == 404
    assert client.post(
        f"{API}/charges/{item['id']}/reverse", headers=desk.west_manager | key(), json={"reason": "x"}
    ).status_code == 404  # fmt: skip
    assert client.post(f"{url}/allocations", headers=desk.west_manager, json={}).status_code == 404
    # ...while client-following reads work from any location they serve.
    assert client.get(url, headers=desk.west_manager).status_code == 200
    for path in ("/charges", "/invoices", "/payments", f"/invoices/{invoice['id']}"):
        assert client.get(f"{API}{path}", headers=desk.viewer).status_code == 403, path
    assert client.get(f"{API}/revenue-categories", headers=desk.viewer).status_code == 200  # configuration read
    assert client.post(f"{API}/charges", headers=desk.west_manager, json=body).status_code == 404

    done = client.post(f"{url}/refunds", headers=owner | key(), json=refund)
    assert done.status_code == 201 and done.json()["status"] == "succeeded"
    reversed_ = client.post(f"{API}/charges/{item['id']}/reverse", headers=owner | key(), json={"reason": "Mistake"})
    assert reversed_.status_code == 201 and reversed_.json()["total_minor"] == -2165
    spent = client.post(f"{url}/allocations", headers=owner, json={})
    assert spent.status_code == 200 and spent.json()["unapplied_minor"] == 2165  # nothing open to apply it to
    confirmed = client.post(f"{url}/confirm", headers=desk.front)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "succeeded"

    ledger = client.get(f"{API}/ledger-entries?limit=200", headers=owner).json()["data"]
    assert sum(e["debit_minor"] for e in ledger) == sum(e["credit_minor"] for e in ledger) > 0
    assert client.get(f"{API}/ledger-entries", headers=desk.viewer).status_code == 403
    categories = client.get(f"{API}/revenue-categories?q=rent", headers=desk.front).json()["data"]
    assert [c["code"] for c in categories] == ["RENT"]


def test_ledger_list_is_limited_to_the_callers_locations(client, shop, desk):
    with work(shop.tenant) as session:
        charge(session, shop)
        charge(session, shop, location_id=desk.west)
        role = session.execute(text("SELECT id FROM role WHERE system_key = 'admin'")).scalar()
        session.execute(
            text("UPDATE staff_user SET role_id = :r WHERE id IN (SELECT staff_user_id FROM user_location_access "
                 "WHERE location_id = :w)"), {"r": role, "w": desk.west},
        )  # fmt: skip
    rows = client.get(f"{API}/ledger-entries", headers=desk.west_manager).json()["data"]
    assert rows and {row["location_id"] for row in rows} == {desk.west}


def test_declined_payment_through_the_api_is_recorded(client, shop):
    pay = {"client_id": str(shop.client_id), "location_id": str(shop.location_id), "amount_minor": 500,
           "tender_kind": "card", "method_token": "tok_card_declined"}  # fmt: skip
    response = client.post(f"{API}/payments", headers=shop.owner | key(), json=pay)
    assert response.status_code == 201
    assert (response.json()["status"], response.json()["failure_category"]) == ("failed", "card_declined")
    unknown_token = client.post(f"{API}/payments", headers=shop.owner | key(), json=pay | {"method_token": "tok_nope"})
    assert unknown_token.json()["failure_category"] == "processor_error"  # refused, never a silent success


def test_service_gates_without_the_router(shop):
    member = Principal(kind="client", tenant_id=shop.tenant.id)
    nobody = Principal(kind="staff", tenant_id=shop.tenant.id, permissions={})
    with work(shop.tenant) as session:
        row = charge(session, shop)
        payment = cash(session, shop, 100)
        for who in (member, nobody):
            for call in (
                lambda who=who: svc.create_charge(session, who, {"location_id": shop.location_id}),
                lambda who=who: svc.list_charges(session, who, ListQuery()),
                lambda who=who: svc.reverse_charge(session, who, row.id, {"reason": "x"}),
                lambda who=who: svc.create_invoice(session, who, {"charge_ids": [row.id]}),
                lambda who=who: svc.list_invoices(session, who, ListQuery()),
                lambda who=who: svc.take_payment_at_desk(session, who, {"location_id": shop.location_id}, "k"),
                lambda who=who: svc.list_payments(session, who, ListQuery()),
                lambda who=who: svc.get_payment(session, who, payment.id),
                lambda who=who: svc.confirm_payment_at_desk(session, who, payment.id),
                lambda who=who: svc.allocate_payment(session, who, payment.id, {}),
                lambda who=who: svc.create_refund(session, who, payment.id, {"amount_minor": 1, "reason": "x"}, "k"),
                lambda who=who: svc.list_ledger_entries(session, who, ListQuery()),
            ):
                with pytest.raises(PermissionDenied):
                    call()


def test_no_processor_connected_outside_the_fake(shop, monkeypatch):
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings().payments, "provider", "none")
    with work(shop.tenant) as session:
        with pytest.raises(Conflict) as none:
            card(session, shop, 100)
        assert none.value.code == "processor-not-connected"
        assert cash(session, shop, 100).status == "succeeded"  # record-only tenders need no processor
