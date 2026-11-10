"""StripeConnectProvider against a mocked HTTP layer (no keys, no network): request shapes, the mapping of
Stripe's answers onto the port's outcomes, and webhook signature verification."""

import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from app.adapters.stripe_connect import ProviderUnavailable, StripeConnectProvider, _flatten
from app.core.settings import get_settings
from app.ports.payment_provider import WebhookRejected, sign, verify_signature

ACCOUNT = "acct_tenant1"
SECRET = "whsec_test_only"  # noqa: S105


class Http:
    """Scripted transport: answers queued responses in order and records what was sent."""

    def __init__(self):
        self.calls, self.answers = [], []

    def reply(self, status: int, payload: dict) -> "Http":
        self.answers.append((status, payload))
        return self

    def __call__(self, method, url, headers, body):
        parts = urlsplit(url)
        sent = parse_qs(body.decode() if body else parts.query)
        self.calls.append({"method": method, "path": parts.path, "headers": headers, "params": sent})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def last(self):
        return self.calls[-1]


@pytest.fixture
def http():
    return Http()


@pytest.fixture
def stripe(http):
    return StripeConnectProvider("sk_test_not_a_real_key", SECRET, api_base="https://stripe.test", transport=http)


def intent(status="succeeded", **over) -> dict:
    card = {"brand": "visa", "last4": "4242", "funding": "debit"}
    return {"id": "pi_1", "status": status, "client_secret": "pi_1_secret",
            "latest_charge": {"payment_method_details": {"card": card}}} | over  # fmt: skip


def test_form_encoding_and_disabled_by_default():
    assert _flatten({"a": {"b": True, "c": None}, "d": ["x", 2], "e": 5}) == [
        ("a[b]", "true"),
        ("d[]", "x"),
        ("d[]", "2"),
        ("e", "5"),
    ]
    assert get_settings().payments.stripe.enabled is False
    with pytest.raises(RuntimeError, match="FH_STRIPE_SECRET_KEY"):
        StripeConnectProvider.from_environment(get_settings().payments.stripe)


def test_payment_is_a_direct_charge_on_the_connected_account_with_our_key(stripe, http):
    http.reply(200, intent())
    state = stripe.create_payment(
        account_ref=ACCOUNT, amount_minor=1083, currency="USD", method_token="pm_card", idempotency_key="t1:payment:k1",
        customer_ref="cus_1", off_session=True,
    )  # fmt: skip
    assert (state.outcome, state.provider_payment_ref, state.card_last4, state.card_funding) == (
        "succeeded",
        "pi_1",
        "4242",
        "debit",
    )
    sent = http.last
    assert (sent["method"], sent["path"]) == ("POST", "/v1/payment_intents")
    assert sent["headers"]["Stripe-Account"] == ACCOUNT and sent["headers"]["Idempotency-Key"] == "t1:payment:k1"
    assert sent["headers"]["Authorization"] == "Bearer sk_test_not_a_real_key"
    params = sent["params"]
    assert (params["amount"], params["currency"], params["payment_method"], params["confirm"]) == (
        ["1083"],
        ["usd"],
        ["pm_card"],
        ["true"],
    )
    assert (params["customer"], params["off_session"], params["metadata[fh_key]"]) == (
        ["cus_1"],
        ["true"],
        ["t1:payment:k1"],
    )
    http.reply(200, intent())
    stripe.create_payment(
        account_ref=ACCOUNT, amount_minor=5, currency="USD", method_token="pm_card", idempotency_key="k2"
    )
    assert "off_session" not in http.last["params"] and "customer" not in http.last["params"]


@pytest.mark.parametrize(
    ("status", "payload", "outcome", "category"),
    [
        (200, intent("processing"), "processing", None),
        (200, intent("requires_action"), "requires_action", None),
        (200, intent("canceled"), "cancelled", None),
        (200, intent("requires_capture"), "unknown", None),
        (200, intent("requires_payment_method", last_payment_error={"decline_code": "insufficient_funds"}), "declined",
         "insufficient_funds"),
        (402, {"error": {"type": "card_error", "code": "card_declined", "decline_code": "generic_decline",
                         "message": "Your card was declined.", "payment_intent": {"id": "pi_9"}}}, "declined", "card_declined"),
        (402, {"error": {"type": "card_error", "code": "expired_card", "payment_intent": {"id": "pi_9"}}}, "declined", "expired_card"),
        (402, {"error": {"type": "card_error", "code": "authentication_required", "payment_intent": {"id": "pi_9"}}},
         "declined", "authentication_required"),
        (400, {"error": {"type": "invalid_request_error", "message": "No such payment_method"}}, "declined", "processor_error"),
    ],
)  # fmt: skip
def test_stripe_answers_map_onto_the_ports_outcomes(stripe, http, status, payload, outcome, category):
    http.reply(status, payload)
    state = stripe.create_payment(
        account_ref=ACCOUNT, amount_minor=5, currency="usd", method_token="pm_x", idempotency_key="k"
    )
    assert (state.outcome, state.failure_category) == (outcome, category)
    assert (state.client_secret is not None) == (outcome == "requires_action")


@pytest.mark.parametrize("failure", [(500, {}), (503, {"error": {}}), ProviderUnavailable("timed out")])
def test_a_timeout_or_server_error_is_unknown_never_a_decline(stripe, http, failure):
    http.answers.append(failure)
    state = stripe.create_payment(
        account_ref=ACCOUNT, amount_minor=5, currency="usd", method_token="pm_x", idempotency_key="k"
    )
    assert (state.outcome, state.provider_payment_ref, state.failure_category) == ("unknown", "", None)


def test_reading_finding_and_cancelling_a_payment(stripe, http):
    http.reply(200, intent("processing"))
    assert stripe.get_payment(account_ref=ACCOUNT, provider_payment_ref="pi_1").outcome == "processing"
    assert (http.last["method"], http.last["path"], http.last["params"]["expand[]"]) == (
        "GET",
        "/v1/payment_intents/pi_1",
        ["latest_charge"],
    )
    http.reply(200, {"data": [intent()]}).reply(200, {"data": []})
    assert stripe.find_payment(account_ref=ACCOUNT, idempotency_key="t1:payment:k1").provider_payment_ref == "pi_1"
    assert http.last["params"]["query"] == ["metadata['fh_key']:'t1:payment:k1'"]
    assert stripe.find_payment(account_ref=ACCOUNT, idempotency_key="never-sent") is None
    http.reply(200, intent("canceled"))
    assert stripe.cancel_payment(account_ref=ACCOUNT, provider_payment_ref="pi_1").outcome == "cancelled"
    http.reply(400, {"error": {"message": "already succeeded"}}).reply(200, intent())
    assert stripe.cancel_payment(account_ref=ACCOUNT, provider_payment_ref="pi_1").outcome == "succeeded"
    http.reply(404, {"error": {"message": "No such payment_intent"}})
    with pytest.raises(ValueError, match="No such payment_intent"):
        stripe.get_payment(account_ref=ACCOUNT, provider_payment_ref="pi_missing")


def test_refunds(stripe, http):
    http.reply(200, {"id": "re_1", "status": "succeeded"})
    done = stripe.refund(
        account_ref=ACCOUNT, provider_payment_ref="pi_1", amount_minor=500, idempotency_key="t1:refund:k"
    )
    assert (done.outcome, done.provider_refund_ref) == ("succeeded", "re_1")
    assert http.last["params"] == {"payment_intent": ["pi_1"], "amount": ["500"], "metadata[fh_key]": ["t1:refund:k"]}
    assert http.last["headers"]["Idempotency-Key"] == "t1:refund:k"
    http.reply(200, {"id": "re_2", "status": "pending"}).reply(400, {"error": {"message": "charge already refunded"}})
    assert (
        stripe.refund(account_ref=ACCOUNT, provider_payment_ref="pi_1", amount_minor=1, idempotency_key="a").outcome
        == "pending"
    )
    refused = stripe.refund(account_ref=ACCOUNT, provider_payment_ref="pi_1", amount_minor=1, idempotency_key="b")
    assert (refused.outcome, refused.failure_message) == ("failed", "charge already refunded")
    rows = {"data": [{"id": "re_0", "status": "succeeded", "metadata": {"fh_key": "other"}},
                     {"id": "re_1", "status": "failed", "failure_reason": "lost_or_stolen_card", "metadata": {"fh_key": "mine"}}]}  # fmt: skip
    http.reply(200, rows).reply(200, rows).reply(200, rows["data"][1])
    found = stripe.find_refund(account_ref=ACCOUNT, idempotency_key="mine", provider_payment_ref="pi_1")
    assert (found.provider_refund_ref, found.outcome, found.failure_message) == (
        "re_1",
        "failed",
        "lost_or_stolen_card",
    )
    assert stripe.find_refund(account_ref=ACCOUNT, idempotency_key="absent", provider_payment_ref="pi_1") is None
    assert (
        stripe.find_refund(account_ref=ACCOUNT, idempotency_key="mine") is None
    )  # nothing to search without the payment
    assert stripe.get_refund(account_ref=ACCOUNT, provider_refund_ref="re_1").outcome == "failed"


def test_accounts_customers_and_stored_methods(stripe, http):
    account = {"id": ACCOUNT, "charges_enabled": True, "payouts_enabled": True,
               "capabilities": {"card_payments": "active", "us_bank_account_ach_payments": "pending"},
               "requirements": {"currently_due": ["external_account"]}}  # fmt: skip
    http.reply(200, account)
    created = stripe.create_account(tenant_ref="tenant-1", email="owner@example.com", country="US", currency="USD")
    assert (created.status, created.has_card, created.has_bank_debit, created.requirements_due) == (
        "active",
        True,
        False,
        ("external_account",),
    )
    sent = http.last["params"]
    assert sent["controller[stripe_dashboard][type]"] == ["full"] and sent["controller[losses][payments]"] == ["stripe"]
    assert sent["default_currency"] == ["usd"] and "Stripe-Account" not in http.last["headers"]  # a platform call
    http.reply(200, {"id": ACCOUNT, "details_submitted": True}).reply(200, {"id": ACCOUNT})
    assert stripe.get_account(account_ref=ACCOUNT).status == "restricted"
    assert stripe.get_account(account_ref=ACCOUNT).status == "pending"
    http.reply(200, {"url": "https://connect.stripe.test/setup/abc"})
    assert stripe.onboarding_link(
        account_ref=ACCOUNT, return_url="https://app/r", refresh_url="https://app/r"
    ).startswith("https://connect")
    assert http.last["params"]["type"] == ["account_onboarding"]

    http.reply(200, {"id": "cus_1"}).reply(200, {"id": "seti_1", "client_secret": "seti_1_secret"})
    assert (
        stripe.ensure_customer(account_ref=ACCOUNT, client_ref="client-1", idempotency_key="t1:customer:c1") == "cus_1"
    )
    assert http.last["headers"]["Stripe-Account"] == ACCOUNT and http.last["params"]["metadata[fh_client]"] == [
        "client-1"
    ]
    setup = stripe.create_setup(account_ref=ACCOUNT, customer_ref="cus_1", kinds=("card", "bank_account"))
    assert setup.client_secret == "seti_1_secret" and http.last["params"]["payment_method_types[]"] == [
        "card",
        "us_bank_account",
    ]
    card = {"id": "pm_1", "type": "card", "card": {"brand": "mastercard", "last4": "4444", "exp_month": 8, "exp_year": 2030,
                                                    "funding": "credit", "wallet": {"type": "apple_pay"}}}  # fmt: skip
    bank = {
        "id": "pm_2",
        "type": "us_bank_account",
        "us_bank_account": {"bank_name": "STRIPE TEST BANK", "last4": "6789"},
    }
    http.reply(200, card).reply(200, bank).reply(200, bank).reply(200, {}).reply(
        402, {"error": {"message": "Card declined."}}
    )
    stored = stripe.attach_method(account_ref=ACCOUNT, customer_ref="cus_1", method_token="pm_1")
    assert (stored.kind, stored.brand, stored.last4, stored.exp_year, stored.wallet) == (
        "card",
        "mastercard",
        "4444",
        2030,
        "apple_pay",
    )
    assert http.last["path"] == "/v1/payment_methods/pm_1/attach"
    assert stripe.get_method(account_ref=ACCOUNT, provider_method_ref="pm_2").kind == "bank_account"
    assert stripe.verify_method(account_ref=ACCOUNT, provider_method_ref="pm_2", amounts=(1, 2)).usable is True
    stripe.detach_method(account_ref=ACCOUNT, provider_method_ref="pm_1")
    assert http.last["path"] == "/v1/payment_methods/pm_1/detach"
    with pytest.raises(ValueError, match="Card declined"):
        stripe.attach_method(account_ref=ACCOUNT, customer_ref="cus_1", method_token="pm_bad")


def test_webhook_signature_and_normalisation(stripe):
    def event(kind: str, object_id: str = "pi_1") -> bytes:
        return json.dumps(
            {"id": f"evt_{kind}", "type": kind, "account": ACCOUNT, "data": {"object": {"id": object_id}}}
        ).encode()

    def parse(body: bytes, header: str | None = None):
        return stripe.parse_webhook({"stripe-signature": header or sign(SECRET, body)}, body)

    paid = parse(event("payment_intent.succeeded"))
    assert (paid.provider_event_id, paid.account_ref, paid.kind, paid.object_ref) == (
        "evt_payment_intent.succeeded",
        ACCOUNT,
        "payment",
        "pi_1",
    )
    kinds = {"payment_intent.payment_failed": "payment", "refund.updated": "refund", "charge.refund.updated": "refund",
             "payment_method.automatically_updated": "method", "charge.dispute.created": "other", "payout.paid": "other"}  # fmt: skip
    assert {name: parse(event(name)).kind for name in kinds} == kinds
    updated = parse(event("account.updated", "acct_ignored"))
    assert (updated.kind, updated.object_ref) == ("account", ACCOUNT)  # the account the event is about
    body = event("payment_intent.succeeded")
    for bad in ("", "t=abc,v1=00", sign("another-secret", body), sign(SECRET, body, int(time.time()) - 3600),
                sign(SECRET, body + b" ")):  # fmt: skip
        with pytest.raises(WebhookRejected):
            stripe.parse_webhook({"stripe-signature": bad}, body)
    with pytest.raises(WebhookRejected):
        stripe.parse_webhook({}, body)
    with pytest.raises(WebhookRejected, match="malformed"):
        parse(b'{"id": "evt_1"}')
    with pytest.raises(WebhookRejected, match="no signing secret"):
        verify_signature("", sign(SECRET, body), body)
    # Two signatures in one header (Stripe sends both during a secret rotation): either may match.
    now = int(time.time())
    rotated = f"{sign('old-secret', body, now)},v1={sign(SECRET, body, now).split('v1=')[1]}"
    assert parse(body, rotated).kind == "payment"
