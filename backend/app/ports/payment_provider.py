"""PaymentProvider port (ADR 0003 section 5). billing.service is the only caller.

The kernel slice defines the calls needed to take, settle and refund a payment. The Money module adds the
connected-account, customer, stored-method, dispute and webhook calls with the Stripe Connect adapter.
No card or bank number ever crosses this interface: `method_token` is an opaque provider reference.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

Outcome = Literal["succeeded", "processing", "requires_action", "declined", "unknown"]
FailureCategory = Literal[
    "insufficient_funds", "card_declined", "expired_card", "authentication_required", "account_closed",
    "authorization_revoked", "processor_error",
]  # fmt: skip


@dataclass(frozen=True)
class PaymentState:
    provider_payment_ref: str
    outcome: Outcome
    failure_category: FailureCategory | None = None
    failure_message: str | None = None
    card_brand: str | None = None
    card_last4: str | None = None
    card_funding: str | None = None


@dataclass(frozen=True)
class RefundState:
    provider_refund_ref: str
    outcome: Literal["succeeded", "pending", "failed"]
    failure_message: str | None = None


class PaymentProvider(Protocol):
    name: str

    def create_payment(
        self, *, account_ref: str, amount_minor: int, currency: str, method_token: str, idempotency_key: str
    ) -> PaymentState:
        """Charge. The same idempotency_key always returns the same provider payment, never a second charge.
        A timeout is `unknown`, never `declined`."""

    def get_payment(self, *, account_ref: str, provider_payment_ref: str) -> PaymentState:
        """Current state, for settling `processing` and recovering `unknown`."""

    def refund(
        self, *, account_ref: str, provider_payment_ref: str, amount_minor: int, idempotency_key: str
    ) -> RefundState:
        """Return money to the original method. Idempotent by key."""

    def find_refund(self, *, account_ref: str, idempotency_key: str) -> RefundState | None:
        """The refund an earlier call with this key created, if any (replay and crash recovery)."""


_providers: dict[str, PaymentProvider] = {}


def register(provider: PaymentProvider) -> None:
    _providers[provider.name] = provider


def get(name: str) -> PaymentProvider:
    return _providers[name]
