"""StripeConnectProvider against a mocked HTTP layer (no keys, no network): request shapes, the mapping of
Stripe's answers onto the port's outcomes, and webhook signature verification."""

import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from app.adapters.stripe_connect import ProviderUnavailable, StripeConnectProvider, _flatten
from app.core.settings import REPO_ROOT, get_settings
from app.ports import payment_provider
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


def test_form_encoding_and_fake_by_default(monkeypatch):
    assert _flatten({"a": {"b": True, "c": None}, "d": ["x", 2], "e": 5}) == [
        ("a[b]", "true"),
        ("d[]", "x"),
        ("d[]", "2"),
        ("e", "5"),
    ]
    assert get_settings().payments.provider == "fake"  # tests and CI never reach Stripe
    assert not payment_provider.registered("stripe")
    monkeypatch.setenv("FH_PAYMENTS_PROVIDER", "stripe")
    assert get_settings.__wrapped__().payments.provider == "fake"  # the override never applies to tests


TEST_KEYS = {"FH_STRIPE_SECRET_KEY": "sk_test_x", "FH_STRIPE_PUBLISHABLE_KEY": "pk_test_x",
             "FH_STRIPE_WEBHOOK_SECRET": "whsec_x"}  # fmt: skip  # noqa: S105


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"FH_STRIPE_PUBLISHABLE_KEY": ""}, "needs FH_STRIPE_SECRET_KEY"),
        ({"FH_STRIPE_SECRET_KEY": "pk_test_x"}, "wrong variables"),
        ({"FH_STRIPE_WEBHOOK_SECRET": "sk_test_x"}, "wrong variables"),
        ({"FH_STRIPE_SECRET_KEY": "rk_live_x"}, "different modes"),
    ],
)
def test_the_adapter_refuses_missing_or_mismatched_keys(monkeypatch, override, message):
    for name, value in (TEST_KEYS | override).items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=message):
        StripeConnectProvider.from_environment(get_settings().payments.stripe)


def test_test_mode_keys_build_a_pinned_adapter(monkeypatch, http):
    for name, value in (TEST_KEYS | {"FH_STRIPE_SECRET_KEY": "rk_test_restricted"}).items():
        monkeypatch.setenv(name, value)
    adapter = StripeConnectProvider.from_environment(get_settings().payments.stripe)
    assert adapter.publishable_key == "pk_test_x"
    adapter._send = http.reply(200, intent())
    adapter.get_payment(account_ref=ACCOUNT, provider_payment_ref="pi_1")
    assert http.last["headers"]["Stripe-Version"] == get_settings().payments.stripe.api_version
    assert http.last["headers"]["Authorization"] == "Bearer rk_test_restricted"


def test_api_onboarding_fills_stripe_test_values_with_a_stable_key(http):
    with pytest.raises(RuntimeError, match="test-mode key"):
        StripeConnectProvider("sk_live_x", SECRET, api_base="https://stripe.test", transport=http, api_onboarding=True)
    stripe = StripeConnectProvider(
        "sk_test_x", SECRET, api_base="https://stripe.test", transport=http, api_onboarding=True
    )
    http.reply(200, {"id": ACCOUNT, "charges_enabled": True}).reply(200, {"id": ACCOUNT, "charges_enabled": True})
    for _ in range(2):
        assert (
            stripe.create_account(tenant_ref="t1", email="o@example.com", country="US", currency="USD").status
            == "active"
        )
    first = http.calls[0]["params"]
    assert first["controller[requirement_collection]"] == ["application"]
    assert first["controller[stripe_dashboard][type]"] == ["none"] and first["external_account"] == ["btok_us_verified"]
    assert first["individual[dob][year]"] == ["1901"] and first["tos_acceptance[date]"]
    assert http.calls[0]["headers"]["Idempotency-Key"] == http.calls[1]["headers"]["Idempotency-Key"]


def test_api_onboarding_is_refused_outside_dev_and_test(monkeypatch, tmp_path, deploy_secrets):
    config = (REPO_ROOT / "config" / "app.yaml").read_text().replace("cookie_secure: false", "cookie_secure: true")
    (tmp_path / "app.yaml").write_text(config)
    (tmp_path / "app.staging.yaml").write_text(
        "email:\n  log_links: false\npayments:\n  provider: stripe\n  stripe:\n    test_onboarding: api\n"
    )
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", "staging")
    with pytest.raises(RuntimeError, match="test_onboarding must be hosted"):
        get_settings.__wrapped__()


@pytest.mark.parametrize("name", list(TEST_KEYS))
@pytest.mark.parametrize("env", ["dev", "test", "staging"])
def test_a_live_key_refuses_to_start_outside_production(monkeypatch, tmp_path, name, env, deploy_secrets):
    config = (REPO_ROOT / "config" / "app.yaml").read_text().replace("cookie_secure: false", "cookie_secure: true")
    (tmp_path / "app.yaml").write_text(config.replace("provider: fake ", "provider: stripe "))
    overlay = (
        "email:\n  log_links: false\nstorage:\n  scanner: clamd\n"  # outside dev and test, uploads must be scanned
        "api:\n  exposed_directly: true\n"  # and a proxy in front must be listed
    )
    (tmp_path / f"app.{env}.yaml").write_text(overlay)
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", env)
    live = {"FH_STRIPE_SECRET_KEY": "sk_live_x", "FH_STRIPE_PUBLISHABLE_KEY": "pk_live_x"}.get(name, "rk_live_x")
    monkeypatch.setenv(name, live)
    with pytest.raises(RuntimeError, match="live Stripe key"):
        get_settings.__wrapped__()
    monkeypatch.setenv(name, TEST_KEYS[name])
    assert get_settings.__wrapped__().payments.provider == "stripe"  # test-mode keys start anywhere
    monkeypatch.setenv(name, live)
    monkeypatch.setenv("FH_ENV", "production")
    (tmp_path / "app.production.yaml").write_text(overlay)
    assert get_settings.__wrapped__().env == "production"  # only production may hold a live key


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
    assert "payment_method_types[]" not in params and params["automatic_payment_methods[enabled]"] == ["true"]
    assert (params["customer"], params["off_session"], params["metadata[fh_key]"]) == (
        ["cus_1"],
        ["true"],
        ["t1:payment:k1"],
    )
    assert "use_stripe_sdk" not in params  # nobody is there to authenticate an off-session charge
    http.reply(200, intent())
    stripe.create_payment(
        account_ref=ACCOUNT, amount_minor=5, currency="USD", method_token="pm_card", idempotency_key="k2"
    )
    assert "off_session" not in http.last["params"] and "customer" not in http.last["params"]
    assert http.last["params"]["use_stripe_sdk"] == ["true"]  # 3-D Secure runs in the browser (handleNextAction)
    assert "setup_future_usage" not in http.last["params"]
    http.reply(200, intent(payment_method="pm_card"))  # save during payment: kept on the customer with the charge
    saved = stripe.create_payment(
        account_ref=ACCOUNT, amount_minor=5, currency="USD", method_token="pm_card", idempotency_key="k3",
        customer_ref="cus_1", save_method=True,
    )  # fmt: skip
    assert http.last["params"]["setup_future_usage"] == ["off_session"]
    assert saved.provider_method_ref == "pm_card"


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
    http.reply(200, {"data": [intent(metadata={"fh_key": "t1:payment:k1"})]}).reply(200, {"data": []})
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


def test_find_payment_cannot_be_steered(stripe, http):
    """M-07: the key is escaped in the search query, and only an intent carrying exactly our key is adopted."""
    steer = "x' OR status:'succeeded"
    http.reply(200, {"data": [intent(metadata={"fh_key": "someone-else"})]})
    assert stripe.find_payment(account_ref=ACCOUNT, idempotency_key=steer) is None
    assert http.last["params"]["query"] == ["metadata['fh_key']:'x\\' OR status:\\'succeeded'"]
    http.reply(200, {"data": [intent(metadata={"fh_key": "a\\b"})]})
    assert stripe.find_payment(account_ref=ACCOUNT, idempotency_key="a\\b").provider_payment_ref == "pi_1"
    assert http.last["params"]["query"] == ["metadata['fh_key']:'a\\\\b'"]


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
    # Stripe rejects card_payments requested without transfers (seen against real test mode).
    assert sent["capabilities[card_payments][requested]"] == sent["capabilities[transfers][requested]"] == ["true"]
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
    assert setup.client_secret == "seti_1_secret" and "payment_method_types[]" not in http.last["params"]
    assert http.last["params"]["automatic_payment_methods[allow_redirects]"] == ["never"]
    card = {"id": "pm_1", "type": "card", "card": {"brand": "mastercard", "last4": "4444", "exp_month": 8, "exp_year": 2030,
                                                    "funding": "credit", "wallet": {"type": "apple_pay"}}}  # fmt: skip
    bank = {
        "id": "pm_2",
        "type": "us_bank_account",
        "us_bank_account": {"bank_name": "STRIPE TEST BANK", "last4": "6789"},
    }
    http.reply(200, card).reply(200, card).reply(200, bank).reply(200, bank).reply(200, {}).reply(
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
    # A bank account saved through a setup intent (Financial Connections) is already on the customer: no attach.
    http.reply(200, bank | {"customer": "cus_1"})
    saved = stripe.attach_method(account_ref=ACCOUNT, customer_ref="cus_1", method_token="pm_2")
    assert (saved.kind, saved.last4, http.last["method"], http.last["path"]) == (
        "bank_account", "6789", "GET", "/v1/payment_methods/pm_2",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("status", "ours"),
    [("needs_response", "open"), ("under_review", "open"), ("won", "won"), ("lost", "lost"),
     ("warning_needs_response", None), ("warning_closed", None), ("prevented", None)],
)  # fmt: skip
def test_disputes_map_onto_the_port(stripe, http, status, ours):
    http.reply(200, {"id": "du_1", "payment_intent": "pi_1", "amount": 1083, "status": status, "reason": "fraudulent",
                     "evidence_details": {"due_by": 1_900_000_000}})  # fmt: skip
    state = stripe.get_dispute(account_ref=ACCOUNT, provider_dispute_ref="du_1")
    assert (state.provider_payment_ref, state.amount_minor, state.status, state.reason_code) == (
        "pi_1", 1083, ours, "fraudulent",
    )  # fmt: skip
    assert state.evidence_due_at.year == 2030
    assert (http.last["path"], http.last["headers"]["Stripe-Account"]) == ("/v1/disputes/du_1", ACCOUNT)


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
             "payment_method.automatically_updated": "method", "charge.dispute.created": "dispute", "charge.dispute.closed": "dispute", "payout.paid": "other"}  # fmt: skip
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
