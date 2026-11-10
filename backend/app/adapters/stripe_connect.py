"""StripeConnectProvider: the PaymentProvider port over Stripe Connect (ADR 0003 section 6).

Direct charges on the tenant's connected account (`Stripe-Account` header): the tenant is merchant of record
and its customers, stored methods, refunds and disputes live on its own account. No card or bank number
passes through here: `method_token` is a `pm_...` reference made by Stripe's hosted fields.

Disabled by default (`payments.stripe.enabled`). It has only ever been run against a mocked HTTP layer:
before a live tenant, re-check the request shapes below against Stripe's current API reference (ADR 0003
open question 8), in particular the connected-account controller properties and the ACH capability name.

The HTTP layer is one injectable function, so tests need no network and no Stripe SDK.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from app.ports.payment_provider import (
    AccountState,
    MethodState,
    PaymentState,
    ProviderEvent,
    RefundState,
    SetupState,
    WebhookRejected,
    verify_signature,
)

# (method, url, headers, form-encoded body or None) -> (HTTP status, decoded JSON body)
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict]]
_DECLINES = {
    "insufficient_funds": "insufficient_funds", "expired_card": "expired_card",
    "authentication_required": "authentication_required", "account_closed": "account_closed",
    "debit_not_authorized": "authorization_revoked", "no_account": "account_closed",
    "processing_error": "processor_error",
}  # fmt: skip
_EVENT_KINDS = (
    ("payment_intent.", "payment"), ("refund.", "refund"), ("charge.refund.", "refund"),
    ("payment_method.", "method"), ("account.", "account"),
)  # fmt: skip


class ProviderUnavailable(Exception):
    """No usable answer: a timeout, a connection failure or a 5xx. The outcome of the call is not known."""


def _flatten(params: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's form encoding: nested keys as a[b], lists as a[]."""
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            pairs += _flatten(value, name)
        elif isinstance(value, list | tuple):
            pairs += [(f"{name}[]", str(item)) for item in value]
        elif value is not None:
            pairs.append((name, str(value).lower() if isinstance(value, bool) else str(value)))
    return pairs


def _urllib_transport(timeout: float) -> Transport:
    def send(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, dict]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310 (https base)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            except ValueError:
                return error.code, {}
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise ProviderUnavailable(str(error)) from error

    return send


class StripeConnectProvider:
    name = "stripe"

    def __init__(self, secret_key: str, webhook_secret: str, *, api_base: str, transport: Transport) -> None:
        self._key, self._webhook_secret, self._base, self._send = secret_key, webhook_secret, api_base, transport

    @classmethod
    def from_environment(cls, cfg) -> "StripeConnectProvider":
        key, secret = os.environ.get("FH_STRIPE_SECRET_KEY", ""), os.environ.get("FH_STRIPE_WEBHOOK_SECRET", "")
        if not key or not secret:
            raise RuntimeError("payments.stripe.enabled needs FH_STRIPE_SECRET_KEY and FH_STRIPE_WEBHOOK_SECRET")
        return cls(key, secret, api_base=cfg.api_base, transport=_urllib_transport(cfg.timeout_seconds))

    def _call(
        self, method: str, path: str, params: dict | None = None, *, account: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict]:  # fmt: skip
        headers = {"Authorization": f"Bearer {self._key}"}
        if account:
            headers["Stripe-Account"] = account
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        encoded = urllib.parse.urlencode(_flatten(params or {}))
        url, body = f"{self._base}{path}", None
        if method == "GET":
            url += f"?{encoded}" if encoded else ""
        else:
            body = encoded.encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        status, payload = self._send(method, url, headers, body)
        if status >= 500:
            raise ProviderUnavailable(f"Stripe answered {status}")
        return status, payload

    def _ok(self, *args, **kwargs) -> dict:
        status, payload = self._call(*args, **kwargs)
        if status >= 400:
            raise ValueError(payload.get("error", {}).get("message") or f"Stripe refused the request ({status}).")
        return payload

    # --- accounts ----------------------------------------------------------------------------------------------

    @staticmethod
    def _account(payload: dict) -> AccountState:
        capabilities = payload.get("capabilities") or {}
        if payload.get("charges_enabled"):
            status = "active"
        else:
            status = "restricted" if payload.get("details_submitted") else "pending"
        return AccountState(
            payload["id"], status, has_card=capabilities.get("card_payments") == "active",
            has_bank_debit=capabilities.get("us_bank_account_ach_payments") == "active",
            is_payouts_enabled=bool(payload.get("payouts_enabled")),
            requirements_due=tuple((payload.get("requirements") or {}).get("currently_due") or ()),
        )  # fmt: skip

    def create_account(self, *, tenant_ref: str, email: str, country: str, currency: str) -> AccountState:
        params = {
            "email": email, "country": country, "default_currency": currency.lower(),
            # Standard-equivalent: the tenant has the full dashboard, pays Stripe's fees, Stripe bears losses.
            "controller": {
                "stripe_dashboard": {"type": "full"}, "fees": {"payer": "account"},
                "losses": {"payments": "stripe"}, "requirement_collection": "stripe",
            },
            "capabilities": {
                "card_payments": {"requested": True}, "us_bank_account_ach_payments": {"requested": True},
            },
            "metadata": {"fh_tenant": tenant_ref},
        }  # fmt: skip
        return self._account(self._ok("POST", "/v1/accounts", params, idempotency_key=f"{tenant_ref}:account"))

    def get_account(self, *, account_ref: str) -> AccountState:
        return self._account(self._ok("GET", f"/v1/accounts/{account_ref}"))

    def onboarding_link(self, *, account_ref: str, return_url: str, refresh_url: str) -> str:
        params = {"account": account_ref, "return_url": return_url, "refresh_url": refresh_url,
                  "type": "account_onboarding"}  # fmt: skip
        return self._ok("POST", "/v1/account_links", params)["url"]

    # --- customers and stored methods ----------------------------------------------------------------------------

    def ensure_customer(self, *, account_ref: str, client_ref: str, idempotency_key: str) -> str:
        params = {"metadata": {"fh_client": client_ref}}
        return self._ok("POST", "/v1/customers", params, account=account_ref, idempotency_key=idempotency_key)["id"]

    def create_setup(self, *, account_ref: str, customer_ref: str, kinds: tuple[str, ...]) -> SetupState:
        types = ["us_bank_account" if kind == "bank_account" else "card" for kind in kinds]
        params = {"customer": customer_ref, "usage": "off_session", "payment_method_types": types}
        payload = self._ok("POST", "/v1/setup_intents", params, account=account_ref)
        return SetupState(payload["id"], payload["client_secret"])

    @staticmethod
    def _method(payload: dict) -> MethodState:
        if payload.get("type") == "us_bank_account":
            bank = payload["us_bank_account"]
            return MethodState(payload["id"], "bank_account", bank["last4"], brand=bank.get("bank_name"))
        card = payload["card"]
        return MethodState(
            payload["id"], "card", card["last4"], brand=card.get("brand"), exp_month=card.get("exp_month"),
            exp_year=card.get("exp_year"), funding=card.get("funding"), wallet=(card.get("wallet") or {}).get("type"),
        )  # fmt: skip

    def attach_method(self, *, account_ref: str, customer_ref: str, method_token: str) -> MethodState:
        path = f"/v1/payment_methods/{urllib.parse.quote(method_token, safe='')}/attach"
        return self._method(self._ok("POST", path, {"customer": customer_ref}, account=account_ref))

    def get_method(self, *, account_ref: str, provider_method_ref: str) -> MethodState:
        return self._method(self._ok("GET", f"/v1/payment_methods/{provider_method_ref}", account=account_ref))

    def verify_method(self, *, account_ref: str, provider_method_ref: str, amounts: tuple[int, ...]) -> MethodState:
        # Stripe verifies a bank account inside its hosted setup flow, before we ever hold the method.
        return self.get_method(account_ref=account_ref, provider_method_ref=provider_method_ref)

    def detach_method(self, *, account_ref: str, provider_method_ref: str) -> None:
        self._call("POST", f"/v1/payment_methods/{provider_method_ref}/detach", account=account_ref)

    # --- payments ------------------------------------------------------------------------------------------------

    @staticmethod
    def _declined(ref: str, error: dict) -> PaymentState:
        reason = error.get("decline_code") or error.get("code") or ""
        return PaymentState(
            ref, "declined", failure_category=_DECLINES.get(reason, "card_declined"),
            failure_message=error.get("message"),
        )  # fmt: skip

    def _payment(self, payload: dict) -> PaymentState:
        status, ref = payload.get("status"), payload["id"]
        if status == "requires_payment_method":
            return self._declined(ref, payload.get("last_payment_error") or {})
        outcome = {"canceled": "cancelled", "requires_confirmation": "requires_action"}.get(status, status)
        if outcome not in ("succeeded", "processing", "requires_action", "cancelled"):
            outcome = "unknown"
        charge = payload.get("latest_charge")
        card = (
            ((charge or {}).get("payment_method_details") or {}).get("card") or {} if isinstance(charge, dict) else {}
        )
        return PaymentState(
            ref, outcome, card_brand=card.get("brand"), card_last4=card.get("last4"), card_funding=card.get("funding"),
            client_secret=payload.get("client_secret") if outcome == "requires_action" else None,
        )  # fmt: skip

    def create_payment(
        self, *, account_ref: str, amount_minor: int, currency: str, method_token: str, idempotency_key: str,
        customer_ref: str | None = None, off_session: bool = False,
    ) -> PaymentState:  # fmt: skip
        params = {
            "amount": amount_minor, "currency": currency.lower(), "payment_method": method_token, "confirm": True,
            "customer": customer_ref, "off_session": True if off_session else None,
            "payment_method_types": ["card", "us_bank_account"], "metadata": {"fh_key": idempotency_key},
            "expand": ["latest_charge"],
        }  # fmt: skip
        try:
            status, payload = self._call(
                "POST", "/v1/payment_intents", params, account=account_ref, idempotency_key=idempotency_key
            )
        except ProviderUnavailable:
            # A timeout is never a decline: the charge may have gone through. Resolved by find_payment().
            return PaymentState("", "unknown")
        if status >= 400:
            error = payload.get("error") or {}
            intent = error.get("payment_intent") or {}
            if error.get("type") != "card_error" and not intent:
                return PaymentState(
                    "", "declined", failure_category="processor_error", failure_message=error.get("message")
                )
            return self._declined(intent.get("id", ""), error)
        return self._payment(payload)

    def get_payment(self, *, account_ref: str, provider_payment_ref: str) -> PaymentState:
        path = f"/v1/payment_intents/{provider_payment_ref}"
        return self._payment(self._ok("GET", path, {"expand": ["latest_charge"]}, account=account_ref))

    def find_payment(self, *, account_ref: str, idempotency_key: str) -> PaymentState | None:
        # Stripe's search index lags creation by up to a minute; the sweep only looks after five.
        params = {"query": f"metadata['fh_key']:'{idempotency_key}'", "limit": 1}
        found = self._ok("GET", "/v1/payment_intents/search", params, account=account_ref).get("data") or []
        return self._payment(found[0]) if found else None

    def cancel_payment(self, *, account_ref: str, provider_payment_ref: str) -> PaymentState:
        status, payload = self._call("POST", f"/v1/payment_intents/{provider_payment_ref}/cancel", account=account_ref)
        if status >= 400:  # already finished: report where it actually is
            return self.get_payment(account_ref=account_ref, provider_payment_ref=provider_payment_ref)
        return self._payment(payload)

    # --- refunds ---------------------------------------------------------------------------------------------------

    @staticmethod
    def _refund(payload: dict) -> RefundState:
        status = payload.get("status")
        outcome = (
            "succeeded"
            if status == "succeeded"
            else "pending"
            if status in ("pending", "requires_action")
            else "failed"
        )
        return RefundState(payload["id"], outcome, payload.get("failure_reason") if outcome == "failed" else None)

    def refund(
        self, *, account_ref: str, provider_payment_ref: str, amount_minor: int, idempotency_key: str
    ) -> RefundState:
        params = {
            "payment_intent": provider_payment_ref,
            "amount": amount_minor,
            "metadata": {"fh_key": idempotency_key},
        }
        status, payload = self._call(
            "POST", "/v1/refunds", params, account=account_ref, idempotency_key=idempotency_key
        )
        if status >= 400:
            return RefundState("", "failed", (payload.get("error") or {}).get("message"))
        return self._refund(payload)

    def find_refund(
        self, *, account_ref: str, idempotency_key: str, provider_payment_ref: str | None = None
    ) -> RefundState | None:
        if not provider_payment_ref:
            return None
        params = {"payment_intent": provider_payment_ref, "limit": 100}
        for row in self._ok("GET", "/v1/refunds", params, account=account_ref).get("data") or []:
            if (row.get("metadata") or {}).get("fh_key") == idempotency_key:
                return self._refund(row)
        return None

    def get_refund(self, *, account_ref: str, provider_refund_ref: str) -> RefundState:
        return self._refund(self._ok("GET", f"/v1/refunds/{provider_refund_ref}", account=account_ref))

    # --- webhooks --------------------------------------------------------------------------------------------------

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> ProviderEvent:
        verify_signature(self._webhook_secret, headers.get("stripe-signature"), body)
        try:
            event = json.loads(body)
            event_type, account = event["type"], event.get("account")
            kind = next((kind for prefix, kind in _EVENT_KINDS if event_type.startswith(prefix)), "other")
            object_ref = account if kind == "account" else event["data"]["object"].get("id")
            return ProviderEvent(event["id"], account, kind, object_ref, event_type)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise WebhookRejected("malformed event") from error
