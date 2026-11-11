"""PaymentProvider port (ADR 0003 section 5). billing is the only caller.

No card or bank number ever crosses this interface: `method_token` is an opaque provider reference, either a
one-time token from the provider's hosted fields or the reference of a stored method.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Literal, Protocol

Outcome = Literal["succeeded", "processing", "requires_action", "declined", "unknown", "cancelled"]
FailureCategory = Literal[
    "insufficient_funds", "card_declined", "expired_card", "authentication_required", "account_closed",
    "authorization_revoked", "processor_error",
]  # fmt: skip
EventKind = Literal["payment", "refund", "method", "account", "other"]


@dataclass(frozen=True)
class PaymentState:
    provider_payment_ref: str
    outcome: Outcome
    failure_category: FailureCategory | None = None
    failure_message: str | None = None
    card_brand: str | None = None
    card_last4: str | None = None
    card_funding: str | None = None
    client_secret: str | None = None  # for the payer to authenticate a `requires_action` payment; never stored


@dataclass(frozen=True)
class RefundState:
    provider_refund_ref: str
    outcome: Literal["succeeded", "pending", "failed"]
    failure_message: str | None = None


@dataclass(frozen=True)
class MethodState:
    """Display data of a stored method. `usable` is false for a bank account awaiting verification."""

    provider_method_ref: str
    kind: Literal["card", "bank_account"]
    last4: str
    brand: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None
    funding: str | None = None
    wallet: str | None = None
    usable: bool = True
    mandate_ref: str | None = None


@dataclass(frozen=True)
class SetupState:
    provider_setup_ref: str
    client_secret: str


@dataclass(frozen=True)
class AccountState:
    provider_account_ref: str
    status: Literal["pending", "restricted", "active", "disabled"]
    has_card: bool = False
    has_bank_debit: bool = False
    is_payouts_enabled: bool = False
    requirements_due: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderEvent:
    """A verified webhook, normalised. It is a notification, never a source of truth: the handler re-reads
    the object named by `object_ref` from the provider."""

    provider_event_id: str
    account_ref: str | None
    kind: EventKind
    object_ref: str | None
    event_type: str


class WebhookRejected(Exception):
    """The signature is missing, wrong or too old."""


class PaymentProvider(Protocol):
    name: str

    def create_account(self, *, tenant_ref: str, email: str, country: str, currency: str) -> AccountState: ...

    def get_account(self, *, account_ref: str) -> AccountState: ...

    def onboarding_link(self, *, account_ref: str, return_url: str, refresh_url: str) -> str: ...

    def ensure_customer(self, *, account_ref: str, client_ref: str, idempotency_key: str) -> str:
        """The provider customer for one of our clients; created once per client per account."""

    def create_setup(self, *, account_ref: str, customer_ref: str, kinds: tuple[str, ...]) -> SetupState:
        """Start saving a card or bank account without charging; the hosted fields finish it."""

    def attach_method(self, *, account_ref: str, customer_ref: str, method_token: str) -> MethodState:
        """Store a tokenised method on the customer and return its display data."""

    def get_method(self, *, account_ref: str, provider_method_ref: str) -> MethodState: ...

    def verify_method(self, *, account_ref: str, provider_method_ref: str, amounts: tuple[int, ...]) -> MethodState:
        """Micro-deposit verification of a bank account."""

    def detach_method(self, *, account_ref: str, provider_method_ref: str) -> None: ...

    def create_payment(
        self, *, account_ref: str, amount_minor: int, currency: str, method_token: str, idempotency_key: str,
        customer_ref: str | None = None, off_session: bool = False,
    ) -> PaymentState:  # fmt: skip
        """Charge. The same idempotency_key always returns the same provider payment, never a second charge.
        A timeout is `unknown`, never `declined`. Off-session, a payment that would need the payer present is
        `declined` with `authentication_required`."""

    def get_payment(self, *, account_ref: str, provider_payment_ref: str) -> PaymentState:
        """Current state, for settling `processing` and recovering `unknown`."""

    def find_payment(self, *, account_ref: str, idempotency_key: str) -> PaymentState | None:
        """The payment an earlier create_payment with this key made, if it reached the provider."""

    def cancel_payment(self, *, account_ref: str, provider_payment_ref: str) -> PaymentState: ...

    def refund(
        self, *, account_ref: str, provider_payment_ref: str, amount_minor: int, idempotency_key: str
    ) -> RefundState:
        """Return money to the original method. Idempotent by key."""

    def find_refund(
        self, *, account_ref: str, idempotency_key: str, provider_payment_ref: str | None = None
    ) -> RefundState | None:
        """The refund an earlier call with this key created, if any (replay and crash recovery)."""

    def get_refund(self, *, account_ref: str, provider_refund_ref: str) -> RefundState: ...

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> ProviderEvent:
        """Verify the signature and normalise. Raises WebhookRejected."""


SIGNATURE_TOLERANCE_SECONDS = 300


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """`t=<unix>,v1=<hex hmac-sha256 of "t.body">`: the scheme Stripe uses, shared by the fake."""
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_signature(secret: str, header: str | None, body: bytes) -> None:
    """Constant-time check of a `t=,v1=` header, refusing one older than five minutes (replay window)."""
    if not secret:
        raise WebhookRejected("no signing secret configured")
    parts = [item.partition("=") for item in (header or "").split(",")]
    stamp = next((value for name, _, value in parts if name.strip() == "t"), "")
    signatures = [value for name, _, value in parts if name.strip() == "v1"]
    if not stamp.isdigit() or abs(time.time() - int(stamp)) > SIGNATURE_TOLERANCE_SECONDS:
        raise WebhookRejected("timestamp outside tolerance")
    expected = sign(secret, body, int(stamp)).split("v1=")[1]
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise WebhookRejected("signature mismatch")


_providers: dict[str, PaymentProvider] = {}


def register(provider: PaymentProvider) -> None:
    _providers[provider.name] = provider


def get(name: str) -> PaymentProvider:
    return _providers[name]


def registered(name: str) -> bool:
    return name in _providers
