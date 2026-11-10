"""FakeProvider: a deterministic, in-process PaymentProvider for development and tests (ADR 0003 section 5).

Scripted by method token:

| token                      | create_payment          | get_payment afterwards                         |
|----------------------------|-------------------------|------------------------------------------------|
| `tok_card_ok`              | succeeded               | succeeded                                      |
| `tok_card_declined`        | declined, card_declined | declined                                       |
| `tok_card_insufficient`    | declined, insufficient_funds | declined                                  |
| `tok_card_unknown`         | unknown (timeout)       | succeeded (the charge did go through)          |
| `tok_ach_ok`               | processing              | processing until settle(); then succeeded      |
| `tok_ach_fail`             | processing              | processing until settle(); then declined       |
| anything else              | declined, processor_error | declined                                     |

shortcut: state lives in this process, so a restart forgets payments still `processing`; fine for a fake,
and the reason dev data should settle ACH payments in the same run that takes them.
"""

from dataclasses import replace
from uuid import uuid4

from app.ports.payment_provider import PaymentState, RefundState

_CARD = {"card_brand": "visa", "card_last4": "4242", "card_funding": "credit"}
_SCRIPTS: dict[str, tuple[str, str | None, str]] = {
    # token: (outcome at creation, failure category, outcome once settled)
    "tok_card_ok": ("succeeded", None, "succeeded"),
    "tok_card_declined": ("declined", "card_declined", "declined"),
    "tok_card_insufficient": ("declined", "insufficient_funds", "declined"),
    "tok_card_unknown": ("unknown", None, "succeeded"),
    "tok_ach_ok": ("processing", None, "succeeded"),
    "tok_ach_fail": ("processing", "insufficient_funds", "declined"),
}


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}  # idempotency key -> provider ref (payments and refunds)
        self._payments: dict[str, tuple[PaymentState, str, int]] = {}  # ref -> (state, token, amount)
        self._refunds: dict[str, RefundState] = {}
        self._refunded: dict[str, int] = {}

    def create_payment(
        self, *, account_ref: str, amount_minor: int, currency: str, method_token: str, idempotency_key: str
    ) -> PaymentState:
        if ref := self._by_key.get(idempotency_key):
            return self._payments[ref][0]
        # A token the processor does not know is refused by it, as a real one would refuse a stale method.
        outcome, category, _ = _SCRIPTS.get(method_token, ("declined", "processor_error", "declined"))
        ref = f"fake_pay_{uuid4().hex}"
        state = PaymentState(
            ref, outcome, failure_category=category if outcome == "declined" else None,
            failure_message="The card was declined." if outcome == "declined" else None,
            **(_CARD if method_token.startswith("tok_card") else {}),
        )  # fmt: skip
        self._by_key[idempotency_key] = ref
        self._payments[ref] = (state, method_token, amount_minor)
        return state

    def get_payment(self, *, account_ref: str, provider_payment_ref: str) -> PaymentState:
        state, token, amount = self._payments[provider_payment_ref]
        if state.outcome == "unknown":  # the lost response was a success
            state = replace(state, outcome="succeeded")
            self._payments[provider_payment_ref] = (state, token, amount)
        return state

    def settle(self, provider_payment_ref: str) -> None:
        """Test and demo hook: the bank answers. Moves a `processing` payment to its scripted final outcome."""
        state, token, amount = self._payments[provider_payment_ref]
        if state.outcome != "processing":
            return
        _, category, final = _SCRIPTS.get(token, ("declined", "processor_error", "declined"))
        failed = final == "declined"
        state = replace(
            state, outcome=final, failure_category=category if failed else None,
            failure_message="The bank returned the debit." if failed else None,
        )  # fmt: skip
        self._payments[provider_payment_ref] = (state, token, amount)

    def find_refund(self, *, account_ref: str, idempotency_key: str) -> RefundState | None:
        return self._refunds.get(self._by_key.get(idempotency_key, ""))

    def refund(
        self, *, account_ref: str, provider_payment_ref: str, amount_minor: int, idempotency_key: str
    ) -> RefundState:
        if ref := self._by_key.get(idempotency_key):
            return self._refunds[ref]
        state, _, amount = self._payments[provider_payment_ref]
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
