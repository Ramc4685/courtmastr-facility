"""Phase 9 chip C through HTTP: portal pay (partial amounts, a household member's invoice, receipts), 3-D Secure
on the fake processor's "requires action" mode (portal, pay link, staff), coupons at online checkout and the
retry of webhooks that were stored but never processed."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.core import clock, inbound_webhooks
from app.core.db.platform import platform_engine
from app.core.errors import ValidationFailed
from app.modules.billing import checkout, documents, webhooks
from app.modules.billing.models import Coupon, CouponRedemption, InvoicePayLink, Payment
from app.modules.billing.tests.test_billing import assert_books_agree, svc, work
from app.modules.billing.tests.test_checkout import _invoice, _secure
from app.modules.billing.tests.test_money import ready
from app.modules.billing.tests.test_surface import item
from app.ports import payment_provider
from conftest import new_client


def _invoice_for(api, shop, client_id, price=1000):
    charge_id = api("POST", "/charges", item(shop, price, client_id=client_id), 201)["id"]
    return api("POST", "/invoices", {"charge_ids": [charge_id]}, 201)


def _authenticate(client, secret, approve=True, status=204):
    response = client.post(
        "/api/v1/public/fake-processor/authentications", json={"client_secret": secret, "approve": approve}
    )
    assert response.status_code == status, response.text


def test_partial_pay_never_pays_more_than_is_owed_and_has_a_receipt(api, shop, member, client):
    first, second = _invoice_for(api, shop, member.id), _invoice_for(api, shop, member.id, 500)  # 1083 + 541
    pay = lambda body, status=201, code=None: member.api("POST", "/portal/payments", body, status, code)  # noqa: E731
    both = [first["id"], second["id"]]
    pay({"invoice_ids": both, "method_token": "tok_card_ok", "amount_minor": 1625}, 422, "amount-exceeds-balance")
    part = pay({"invoice_ids": both, "method_token": "tok_card_ok", "amount_minor": 1200})["payment"]
    assert (part["amount_minor"], part["status"]) == (1200, "succeeded")
    states = sorted(
        (api("GET", f"/invoices/{i}")["status"], api("GET", f"/invoices/{i}")["balance_minor"]) for i in both
    )
    assert states == [("paid", 0), ("partially_paid", 424)]  # oldest item first
    pay({"invoice_ids": both, "method_token": "tok_card_ok"}, 409, "invoice-not-payable")  # the first is paid
    rest = pay({"invoice_ids": both[1:], "method_token": "tok_card_ok"})["payment"]
    assert rest["amount_minor"] == 424
    assert {api("GET", f"/invoices/{i}")["status"] for i in both} == {"paid"}

    receipt = member.api("GET", f"/portal/payments/{part['id']}/receipt")
    assert (receipt["received_minor"], receipt["applied_minor"], len(receipt["lines"])) == (1200, 1200, 2)
    pdf = client.get(f"/api/v1/portal/payments/{part['id']}/receipt/pdf", headers=member.headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    theirs = api("POST", "/payments", {"client_id": member.stranger, "location_id": str(shop.location_id),
                                      "amount_minor": 100, "tender_kind": "cash"}, 201)  # fmt: skip
    member.api("GET", f"/portal/payments/{theirs['id']}/receipt", None, 404)
    member.api("POST", f"/portal/payments/{theirs['id']}/confirm", {"invoice_ids": both}, 404)
    with work(shop.tenant) as session:
        assert_books_agree(session)


def test_a_guardian_pays_a_dependents_invoice_with_their_own_card(api, shop, member, client):
    kid = new_client(client, shop.owner, shop.location_id)["id"]
    types = {t["code"]: t["id"] for t in api("GET", "/relationship-types")}
    api("POST", f"/clients/{member.id}/relationships",
        {"other_client_id": kid, "relationship_type_id": types["parent_of"]}, 201)  # fmt: skip
    kids, strangers = _invoice_for(api, shop, kid), _invoice_for(api, shop, member.stranger)
    assert kids["id"] in {row["id"] for row in member.api("GET", "/portal/invoices?is_payable=true")["data"]}
    member.api("POST", "/portal/payments", {"invoice_ids": [strangers["id"]], "method_token": "tok_card_ok"}, 404)
    kid_card = api("POST", f"/clients/{kid}/payment-methods", {"method_token": "tok_card_ok"}, 201)
    member.api(
        "POST",
        "/portal/payments",
        {"invoice_ids": [kids["id"]], "payment_method_id": kid_card["id"]},
        422,
        "payment-method-not-usable",
    )  # fmt: skip  (the payer is the guardian: the child's card is not theirs)
    mine = member.api("POST", "/portal/payment-methods", {"method_token": "tok_card_ok"}, 201)
    paid = member.api("POST", "/portal/payments", {"invoice_ids": [kids["id"]], "payment_method_id": mine["id"]}, 201)
    assert paid["payment"]["client_id"] == member.id and paid["payment"]["status"] == "succeeded"
    assert api("GET", f"/invoices/{kids['id']}")["status"] == "paid"


def test_three_d_secure_in_the_portal_lands_on_the_invoice_once_authenticated(api, shop, member, client):
    invoice = _invoice_for(api, shop, member.id)
    body = {"invoice_ids": [invoice["id"]], "method_token": "tok_card_auth"}
    started = member.api("POST", "/portal/payments", body, 201)
    payment = started["payment"]
    assert payment["status"] == "requires_action" and started["client_secret"]
    assert api("GET", f"/invoices/{invoice['id']}")["status"] == "open"
    _authenticate(client, "fake_pay_never_issued_secret", status=404)
    _authenticate(client, started["client_secret"])
    confirm = f"/portal/payments/{payment['id']}/confirm"
    done = member.api("POST", confirm, {"invoice_ids": [invoice["id"]]})
    assert done["payment"]["status"] == "succeeded" and api("GET", f"/invoices/{invoice['id']}")["status"] == "paid"
    again = member.api("POST", confirm, {"invoice_ids": [invoice["id"]]})  # safe to repeat: nothing moves twice
    assert again["payment"]["allocations"] == done["payment"]["allocations"]

    other = _invoice_for(api, shop, member.id)
    failing = member.api(
        "POST", "/portal/payments", {"invoice_ids": [other["id"]], "method_token": "tok_card_auth"}, 201
    )
    _authenticate(client, failing["client_secret"], approve=False)
    failed = member.api("POST", f"/portal/payments/{failing['payment']['id']}/confirm", {"invoice_ids": [other["id"]]})
    assert (failed["payment"]["status"], failed["payment"]["allocations"]) == ("failed", [])
    assert api("GET", f"/invoices/{other['id']}")["status"] == "open"
    with work(shop.tenant) as session:
        assert_books_agree(session)


def test_three_d_secure_on_the_pay_link_and_at_the_desk(api, shop, client):
    ready(shop)
    with work(shop.tenant) as session:
        invoice = _invoice(session, shop)
        token, invoice_id = documents.create_pay_link(session, invoice).split("#token=")[1], invoice.id
    public = {"X-Tenant-Slug": shop.tenant.slug}
    post = lambda path, body: client.post(  # noqa: E731
        f"/api/v1/public/invoice-links/{path}", json=body, headers=public | {"Idempotency-Key": uuid4().hex}
    )
    started = post("payments", {"token": token, "method_token": "tok_card_auth"}).json()
    assert started["status"] == "requires_action" and started["client_secret"]
    payment_id = started["id"]
    with work(shop.tenant) as session:
        other = svc.take_payment(session, client_id=shop.client_id, location_id=shop.location_id, amount_minor=5,
                                 tender_kind="cash").id  # fmt: skip
    assert post("payments/confirm", {"token": token, "payment_id": str(other)}).status_code == 404  # not this link's
    _authenticate(client, started["client_secret"])
    assert post("payments/confirm", {"token": token, "payment_id": payment_id}).json()["status"] == "succeeded"
    assert api("GET", f"/invoices/{invoice_id}")["status"] == "paid"
    assert post("payments/confirm", {"token": token, "payment_id": payment_id}).status_code == 404  # used up
    with work(shop.tenant) as session:
        assert session.scalar(select(InvoicePayLink.payment_id).where(InvoicePayLink.invoice_id == invoice_id))

    # at the desk: staff confirm, then apply what it left to the invoice (TakePaymentDialog does both)
    desk_invoice = _invoice_for(api, shop, str(shop.client_id))
    taken = api("POST", "/payments", {"client_id": str(shop.client_id), "location_id": str(shop.location_id),
                                     "invoice_id": desk_invoice["id"], "amount_minor": desk_invoice["balance_minor"],
                                     "tender_kind": "card", "method_token": "tok_card_auth"}, 201)  # fmt: skip
    assert taken["status"] == "requires_action" and taken["client_secret"]
    _authenticate(client, taken["client_secret"])
    assert api("POST", f"/payments/{taken['id']}/confirm")["status"] == "succeeded"
    api("POST", f"/payments/{taken['id']}/allocations", {"invoice_id": desk_invoice["id"]})
    assert api("GET", f"/invoices/{desk_invoice['id']}")["status"] == "paid"


def _coupon(session, code, **over):
    values = {
        "name": code.title(),
        "code": code,
        "starts_at": clock.now() - timedelta(days=1),
        "is_portal_enabled": True,
    }
    session.add(Coupon(**(values | over)))


def test_a_portal_coupon_comes_off_the_sale_before_payment(shop, member):
    ready(shop)
    with work(shop.tenant) as session:
        _coupon(session, "SPRING", discount_pct=10, limit_per_client=1)
        _coupon(session, "DESK", discount_minor=100, is_portal_enabled=False)
        _coupon(session, "FREE", discount_pct=100)
    with work(shop.tenant) as session:
        invoice = _invoice(session, shop)
        before = invoice.balance_minor
        payment = _secure(session, shop, invoice, method_token="tok_card_ok", coupon_code="SPRING")
        assert payment.amount_minor == invoice.total_minor < before and invoice.status == "paid"
        assert session.scalar(select(CouponRedemption.id).where(CouponRedemption.invoice_id == invoice.id))
    for code, error in (("SPRING", "coupon-limit-reached"), ("DESK", "coupon-not-portal-enabled")):
        with pytest.raises(ValidationFailed) as refused, work(shop.tenant) as session:
            _secure(session, shop, _invoice(session, shop), method_token="tok_card_ok", coupon_code=code)
        assert refused.value.code == error
    with work(shop.tenant) as session:
        assert _secure(session, shop, _invoice(session, shop), coupon_code="FREE") is None  # nothing left to pay
    with pytest.raises(ValidationFailed) as refused, work(shop.tenant) as session:
        checkout.secure_online_checkout(session, client_id=shop.client_id, location_id=shop.location_id,
                                        total_minor=500, invoice=None, idempotency_key="x", coupon_code="FREE",
                                        must_pay_now=False)  # fmt: skip
    assert refused.value.code == "coupon-not-applicable"

    quote = member.api("POST", "/portal/coupon-quotes", {"code": "SPRING", "subtotal_minor": 5000})
    assert quote == {"is_valid": True, "invalid_reason": None, "discount_minor": 500}  # the member has not used it
    desk = member.api("POST", "/portal/coupon-quotes", {"code": "DESK", "subtotal_minor": 5000})
    assert desk["invalid_reason"] == "not_portal_enabled"
    member.api("POST", "/portal/coupon-quotes", {"code": "SPRING", "subtotal_minor": 1, "client_id": member.stranger},
               404)  # fmt: skip


def test_a_webhook_stored_but_never_processed_is_retried(shop):
    ready(shop)
    with work(shop.tenant) as session:
        payment = svc.take_payment(session, client_id=shop.client_id, location_id=shop.location_id,
                                   amount_minor=900, tender_kind="bank_debit", method_token="tok_ach_ok",
                                   idempotency_key=uuid4().hex)  # fmt: skip
        payment_id, ref = payment.id, payment.provider_payment_ref
        account_ref = svc._provider_account(session).provider_account_ref
    payment_provider.get("fake").settle(ref)
    stored = inbound_webhooks.record("fake", f"evt_{uuid4().hex}", account_ref, "payment.succeeded",
                                     {"kind": "payment", "object": ref, "account": account_ref})  # fmt: skip
    assert stored is not None  # stored, but (as if the broker was down) never enqueued
    with platform_engine().begin() as conn:  # it arrived ten minutes ago
        conn.execute(text("UPDATE inbound_webhook_event SET received_at = now() - interval '10 minutes' "
                          "WHERE id = :id"), {"id": stored[0]})  # fmt: skip
    assert stored[0] in inbound_webhooks.stale(shop.tenant.id, clock.now(), webhooks.RETRY_ATTEMPTS)
    for _ in range(2):  # a second sweep finds nothing to do
        webhooks.retry_provider_events.fn(str(shop.tenant.id))
    with work(shop.tenant) as session:
        assert session.get(Payment, payment_id).status == "succeeded"
    assert inbound_webhooks.get(stored[0]).status == "processed"
    assert stored[0] not in inbound_webhooks.stale(shop.tenant.id, clock.now(), webhooks.RETRY_ATTEMPTS)
