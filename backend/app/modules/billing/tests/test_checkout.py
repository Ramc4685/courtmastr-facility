"""billing.checkout.secure_online_checkout: one case per row of wave 1 hardening spec 0.4, on FakeProvider."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, DomainError, ValidationFailed
from app.modules.billing import checkout, methods
from app.modules.billing.models import Invoice, Payment
from app.modules.billing.tests.test_billing import charge, svc, work
from app.modules.billing.tests.test_money import provider_payments, ready


def _invoice(session, shop, price=2000):
    return svc.create_invoice_for_charges(session, [charge(session, shop, price).id], origin="portal")


def _secure(session, shop, invoice, **over):
    args = {
        "client_id": shop.client_id, "location_id": shop.location_id, "invoice": invoice,
        "total_minor": invoice.total_minor if invoice is not None else 1000, "idempotency_key": uuid4().hex,
    }  # fmt: skip
    return checkout.secure_online_checkout(session, **(args | over))


class _Code:
    """pytest.raises that also checks the error code."""

    def __init__(self, kind, code):
        self.raises, self.code = pytest.raises(kind), code

    def __enter__(self):
        self.info = self.raises.__enter__()
        return self.info

    def __exit__(self, *exc):
        handled = self.raises.__exit__(*exc)
        assert self.info.value.code == self.code
        return handled


def test_nothing_to_secure(shop):
    ready(shop)
    with work(shop.tenant) as session:
        assert _secure(session, shop, None, total_minor=0) is None
        assert _secure(session, shop, _invoice(session, shop), on_account_ok=True) is None  # sold on account
        assert checkout.is_secured(None) is False


@pytest.mark.parametrize(("token", "status"), [("tok_card_ok", "succeeded"), ("tok_ach_ok", "processing")])
def test_the_balance_is_paid_and_secured(shop, token, status):
    ready(shop)
    with work(shop.tenant) as session:
        invoice = _invoice(session, shop)
        payment = _secure(
            session, shop, invoice, method_token=token, tender_kind="card" if "card" in token else "bank_debit"
        )
        assert (payment.status, payment.amount_minor, payment.origin) == (status, invoice.total_minor, "portal")
        assert checkout.is_secured(payment)


@pytest.mark.parametrize("token", ["tok_card_declined", "tok_card_auth"])
def test_a_payment_that_did_not_go_through_refuses_the_sale(shop, token):
    ready(shop)
    with work(shop.tenant) as session:
        invoice = _invoice(session, shop)
        key = uuid4().hex
        with _Code(Conflict, "payment-failed"):
            _secure(session, shop, invoice, method_token=token, idempotency_key=key)
        left = session.scalar(select(Payment).where(Payment.idempotency_key == key))
        assert left.status == ("failed" if token == "tok_card_declined" else "cancelled")


def test_a_processor_timeout_is_a_503_and_the_retry_pays_once(shop):
    ready(shop)
    with work(shop.tenant) as session:
        invoice_id = _invoice(session, shop).id
    key = uuid4().hex
    with _Code(DomainError, "provider-unavailable") as caught, work(shop.tenant) as session:
        _secure(session, shop, session.get(Invoice, invoice_id), method_token="tok_card_unknown",
                idempotency_key=key)  # fmt: skip
    assert caught.value.status == 503
    with work(shop.tenant) as session:  # the sale rolled back; the initiated row survived
        assert session.scalar(select(Payment.status).where(Payment.idempotency_key == key)) == "initiated"
    with work(shop.tenant) as session:
        payment = _secure(session, shop, session.get(Invoice, invoice_id), method_token="tok_card_unknown",
                          idempotency_key=key)  # fmt: skip
        assert (payment.status, payment.unapplied_minor) == ("succeeded", 0)  # and it pays the invoice
        assert session.get(Invoice, invoice_id).balance_minor == 0
    assert provider_payments(shop, key) == 1


def test_paid_in_full_with_nothing_invoiced_is_refused(shop):
    ready(shop)
    with work(shop.tenant) as session, _Code(Conflict, "payment-failed"):
        _secure(session, shop, None, method_token="tok_card_ok")


def test_nothing_due_now_needs_a_chargeable_method_on_file(shop):
    ready(shop)
    with work(shop.tenant) as session:
        for token in (None, "tok_ach_unverified"):
            with _Code(ValidationFailed, "payment-method-required"):
                _secure(session, shop, None, must_pay_now=False, method_token=token)
        assert _secure(session, shop, None, must_pay_now=False, method_token="tok_card_ok") is None
        stored = methods.autopay_method(session, shop.client_id)
        assert stored is not None and stored.status == "active"
        assert _secure(session, shop, None, must_pay_now=False) is None  # the stored autopay method suffices
