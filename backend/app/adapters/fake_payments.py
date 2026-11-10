"""FakeProvider: a deterministic, in-process PaymentProvider for development and tests (ADR 0003 section 5).

Scripted by method token (a stored method remembers the token it was attached with):

| token                   | create_payment                  | afterwards                                      |
|-------------------------|---------------------------------|-------------------------------------------------|
| `tok_card_ok`           | succeeded                       | succeeded                                       |
| `tok_card_declined`     | declined, card_declined         | declined                                        |
| `tok_card_insufficient` | declined, insufficient_funds    | declined                                        |
| `tok_card_expired`      | declined, expired_card          | declined                                        |
| `tok_card_flaky`        | first charge of a stored method declines (insufficient_funds), later ones succeed |    |
| `tok_card_auth`         | requires_action; off-session: declined, authentication_required | authenticate() -> succeeded |
| `tok_card_unknown`      | unknown (timeout)               | succeeded (the charge did go through)           |
| `tok_ach_ok`            | processing                      | processing until settle(); then succeeded       |
| `tok_ach_fail`          | processing                      | processing until settle(); then declined        |
| `tok_ach_closed`        | processing                      | settle(): declined, account_closed              |
| `tok_ach_unverified`    | attaches unverified; verify with micro-deposits (32, 45); pays like `tok_ach_ok` |     |
| anything else           | declined, processor_error       | declined                                        |

Every state change is also emitted as a signed webhook event into `outbox`, in the format parse_webhook()
reads, so tests and the dev tools can deliver them to `/webhooks/fake` like a real processor would.

shortcut: state lives in this process, so a restart forgets payments still `processing`; fine for a fake,
and the reason dev data should settle ACH payments in the same run that takes them.
"""

import json
from dataclasses import replace
from uuid import uuid4

from app.ports.payment_provider import (
    AccountState,
    MethodState,
    PaymentState,
    ProviderEvent,
    RefundState,
    SetupState,
    WebhookRejected,
    sign,
    verify_signature,
)

_CARD = {"card_brand": "visa", "card_last4": "4242", "card_funding": "credit"}
_SCRIPTS: dict[str, tuple[str, str | None, str]] = {
    # token: (outcome at creation, failure category, outcome once settled)
    "tok_card_ok": ("succeeded", None, "succeeded"),
    "tok_card_declined": ("declined", "card_declined", "declined"),
    "tok_card_insufficient": ("declined", "insufficient_funds", "declined"),
    "tok_card_expired": ("declined", "expired_card", "declined"),
    "tok_card_flaky": ("declined", "insufficient_funds", "declined"),
    "tok_card_auth": ("requires_action", None, "succeeded"),
    "tok_card_unknown": ("unknown", None, "succeeded"),
    "tok_ach_ok": ("processing", None, "succeeded"),
    "tok_ach_fail": ("processing", "insufficient_funds", "declined"),
    "tok_ach_closed": ("processing", "account_closed", "declined"),
    "tok_ach_unverified": ("processing", None, "succeeded"),
}
_UNKNOWN_TOKEN = ("declined", "processor_error", "declined")
MICRO_DEPOSITS = (32, 45)
WEBHOOK_SECRET = "whsec_fake_dev_only"  # noqa: S105  (the fake moves no money; refused outside dev and test)


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}  # idempotency key -> provider ref (payments, refunds, customers)
        self._payments: dict[str, tuple[PaymentState, str, int, str]] = {}  # ref -> (state, token, amount, account)
        self._refunds: dict[str, RefundState] = {}
        self._refunded: dict[str, int] = {}
        self._methods: dict[str, tuple[MethodState, str]] = {}  # stored method ref -> (state, script token)
        self._charges: dict[str, int] = {}  # stored method ref -> charges attempted
        self.outbox: list[tuple[dict[str, str], bytes]] = []  # signed webhook deliveries, oldest first

    # --- webhooks ------------------------------------------------------------------------------------------

    def _emit(self, account_ref: str, kind: str, object_ref: str, event_type: str) -> None:
        body = json.dumps(
            {"id": f"fake_evt_{uuid4().hex}", "account": account_ref, "kind": kind, "object": object_ref,
             "type": event_type}
        ).encode()  # fmt: skip
        self.outbox.append(({"fake-signature": sign(WEBHOOK_SECRET, body)}, body))

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> ProviderEvent:
        verify_signature(WEBHOOK_SECRET, headers.get("fake-signature"), body)
        try:
            event = json.loads(body)
            return ProviderEvent(event["id"], event["account"], event["kind"], event["object"], event["type"])
        except (ValueError, KeyError, TypeError) as error:
            raise WebhookRejected("malformed event") from error

    # --- accounts, customers, stored methods -----------------------------------------------------------------

    def create_account(self, *, tenant_ref: str, email: str, country: str, currency: str) -> AccountState:
        return self.get_account(account_ref=f"fake_acct_{tenant_ref.replace('-', '')}")

    def get_account(self, *, account_ref: str) -> AccountState:
        return AccountState(account_ref, "active", has_card=True, has_bank_debit=True, is_payouts_enabled=True)

    def onboarding_link(self, *, account_ref: str, return_url: str, refresh_url: str) -> str:
        return return_url

    def ensure_customer(self, *, account_ref: str, client_ref: str, idempotency_key: str) -> str:
        return self._by_key.setdefault(idempotency_key, f"fake_cus_{uuid4().hex}")

    def create_setup(self, *, account_ref: str, customer_ref: str, kinds: tuple[str, ...]) -> SetupState:
        ref = f"fake_seti_{uuid4().hex}"
        return SetupState(ref, f"{ref}_secret")

    def attach_method(self, *, account_ref: str, customer_ref: str, method_token: str) -> MethodState:
        if method_token not in _SCRIPTS:
            raise ValueError("The processor does not recognise this payment method.")
        ref = f"fake_pm_{uuid4().hex}"
        if method_token.startswith("tok_ach"):
            state = MethodState(
                ref, "bank_account", "6789", brand="Test Bank", usable=method_token != "tok_ach_unverified",
                mandate_ref=f"fake_mandate_{uuid4().hex}",
            )  # fmt: skip
        else:
            expired = method_token == "tok_card_expired"
            state = MethodState(
                ref, "card", "4242", brand="visa", exp_month=1 if expired else 12,
                exp_year=2020 if expired else 2099, funding="credit",
            )  # fmt: skip
        self._methods[ref] = (state, method_token)
        return state

    def get_method(self, *, account_ref: str, provider_method_ref: str) -> MethodState:
        return self._methods[provider_method_ref][0]

    def verify_method(self, *, account_ref: str, provider_method_ref: str, amounts: tuple[int, ...]) -> MethodState:
        state, token = self._methods[provider_method_ref]
        if tuple(sorted(amounts)) == MICRO_DEPOSITS:
            state = replace(state, usable=True)
            self._methods[provider_method_ref] = (state, token)
        return state

    def detach_method(self, *, account_ref: str, provider_method_ref: str) -> None:
        self._methods.pop(provider_method_ref, None)

    # --- payments ----------------------------------------------------------------------------------------------

    def create_payment(
        self, *, account_ref: str, amount_minor: int, currency: str, method_token: str, idempotency_key: str,
        customer_ref: str | None = None, off_session: bool = False,
    ) -> PaymentState:  # fmt: skip
        if ref := self._by_key.get(idempotency_key):
            return self._payments[ref][0]
        stored = self._methods.get(method_token)
        token = stored[1] if stored else method_token
        # A token the processor does not know is refused by it, as a real one would refuse a stale method.
        outcome, category, _ = _SCRIPTS.get(token, _UNKNOWN_TOKEN)
        if token == "tok_card_flaky" and stored:
            self._charges[method_token] = self._charges.get(method_token, 0) + 1
            if self._charges[method_token] > 1:
                outcome, category = "succeeded", None
        if outcome == "requires_action" and off_session:
            outcome, category = "declined", "authentication_required"
        ref = f"fake_pay_{uuid4().hex}"
        declined = outcome == "declined"
        state = PaymentState(
            ref, outcome, failure_category=category if declined else None,
            failure_message="The card was declined." if declined else None,
            client_secret=f"{ref}_secret" if outcome == "requires_action" else None,
            **(_CARD if token.startswith("tok_card") else {}),
        )  # fmt: skip
        self._by_key[idempotency_key] = ref
        self._payments[ref] = (state, token, amount_minor, account_ref)
        return state

    def get_payment(self, *, account_ref: str, provider_payment_ref: str) -> PaymentState:
        state, token, amount, account = self._payments[provider_payment_ref]
        if state.outcome == "unknown":  # the lost response was a success
            state = replace(state, outcome="succeeded")
            self._payments[provider_payment_ref] = (state, token, amount, account)
        return state

    def find_payment(self, *, account_ref: str, idempotency_key: str) -> PaymentState | None:
        ref = self._by_key.get(idempotency_key)
        return self.get_payment(account_ref=account_ref, provider_payment_ref=ref) if ref in self._payments else None

    def cancel_payment(self, *, account_ref: str, provider_payment_ref: str) -> PaymentState:
        state, token, amount, account = self._payments[provider_payment_ref]
        if state.outcome in ("requires_action", "processing"):
            state = replace(state, outcome="cancelled", client_secret=None)
            self._payments[provider_payment_ref] = (state, token, amount, account)
        return state

    def _finish(self, provider_payment_ref: str, waiting: str, message: str) -> None:
        state, token, amount, account = self._payments[provider_payment_ref]
        if state.outcome != waiting:
            return
        _, category, final = _SCRIPTS.get(token, _UNKNOWN_TOKEN)
        failed = final == "declined"
        state = replace(
            state, outcome=final, failure_category=category if failed else None,
            failure_message=message if failed else None, client_secret=None,
        )  # fmt: skip
        self._payments[provider_payment_ref] = (state, token, amount, account)
        self._emit(account, "payment", provider_payment_ref, f"payment.{'failed' if failed else 'succeeded'}")

    def settle(self, provider_payment_ref: str) -> None:
        """Test and demo hook: the bank answers. Moves a `processing` payment to its scripted final outcome
        and emits the webhook a processor would send."""
        self._finish(provider_payment_ref, "processing", "The bank returned the debit.")

    def authenticate(self, provider_payment_ref: str) -> None:
        """Test and demo hook: the payer completes authentication of a `requires_action` payment."""
        self._finish(provider_payment_ref, "requires_action", "Authentication failed.")

    # --- refunds -------------------------------------------------------------------------------------------------

    def find_refund(
        self, *, account_ref: str, idempotency_key: str, provider_payment_ref: str | None = None
    ) -> RefundState | None:
        return self._refunds.get(self._by_key.get(idempotency_key, ""))

    def get_refund(self, *, account_ref: str, provider_refund_ref: str) -> RefundState:
        return self._refunds[provider_refund_ref]

    def refund(
        self, *, account_ref: str, provider_payment_ref: str, amount_minor: int, idempotency_key: str
    ) -> RefundState:
        if ref := self._by_key.get(idempotency_key):
            return self._refunds[ref]
        state, _, amount, _ = self._payments[provider_payment_ref]
        ref = f"fake_ref_{uuid4().hex}"
        refunded = self._refunded.get(provider_payment_ref, 0)
        if state.outcome != "succeeded" or refunded + amount_minor > amount:
            result = RefundState(ref, "failed", "The payment cannot be refunded for this amount.")
        else:
            self._refunded[provider_payment_ref] = refunded + amount_minor
            result = RefundState(ref, "succeeded")
        self._by_key[idempotency_key] = ref
        self._refunds[ref] = result
        return result
