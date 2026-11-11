"""Online checkout: the one rule every portal sale follows (wave 1 hardening 0.4).

An entitlement with a non-zero total exists only once payment is secured. Call secure_online_checkout()
inside the sale's transaction, after the sale wrote its rows; every refusal raises without `persist`, so the
entitlement rolls back with it.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import Conflict, DomainError, ValidationFailed
from app.modules.billing import methods, service
from app.modules.billing.models import Invoice, Payment

SECURED = ("succeeded", "processing")


def is_secured(payment: Payment | None) -> bool:
    return payment is not None and payment.status in SECURED


def secure_online_checkout(
    session: Session,
    *,
    client_id: UUID,
    location_id: UUID,
    total_minor: int,
    invoice: Invoice | None,
    idempotency_key: str,
    method_token: str | None = None,
    payment_method_id: UUID | None = None,
    tender_kind: str = "card",
    must_pay_now: bool = True,
    on_account_ok: bool = False,
) -> Payment | None:
    """Pay what is due now, or prove a chargeable method is on file for what falls due later.

    None when nothing needed securing (a free sale, or a plan that explicitly sells on account); the payment
    when it went through. `unknown` or `initiated` is a 503: the `initiated` row was committed before the
    provider call, so a retry with the same key replays it and money that did go through lands as credit.
    """
    if total_minor <= 0:
        return None
    has_method = bool(method_token or payment_method_id)
    if on_account_ok and not has_method:
        return None
    if invoice is not None and invoice.balance_minor > 0:
        if not has_method:  # something is due now and nothing was offered to pay it
            if must_pay_now:
                raise Conflict("The payment did not go through, so nothing was bought.", code="payment-failed")
            raise ValidationFailed(
                "A payment method is needed for what is due now.", pointer="/method_token",
                code="payment-method-required",
            )  # fmt: skip
        earlier = service.find_payment(session, idempotency_key)
        if earlier is not None:
            if earlier.client_id != client_id:
                raise _key_reused()
            if earlier.status in ("unknown", "initiated"):
                # a retry after a timeout: ask the processor first, so the card is never charged twice
                earlier = service.confirm_payment(session, earlier.id)
            if is_secured(earlier):  # a replay: the key's money secures this sale only if it covers it
                return _covering(session, invoice, service.allocate(session, earlier.id, invoice_id=invoice.id))
        payment = service.take_payment(
            session, client_id=client_id, location_id=location_id, amount_minor=invoice.balance_minor,
            tender_kind=tender_kind, method_token=method_token, payment_method_id=payment_method_id,
            idempotency_key=idempotency_key, origin="portal", invoice_id=invoice.id,
        )  # fmt: skip
        if is_secured(payment):
            return _covering(session, invoice, payment)
        if payment.status in ("unknown", "initiated"):
            raise DomainError(
                "The card processor did not answer; retry with the same Idempotency-Key.", status=503,
                code="provider-unavailable",
            )  # fmt: skip
        if payment.status == "requires_action":
            service.cancel_payment(session, payment.id)
        raise Conflict(payment.failure_message or "The payment did not go through, so nothing was bought.",
                       code="payment-failed")  # fmt: skip
    if must_pay_now:  # a paid-in-full sale that raised no invoice has secured nothing
        raise Conflict("The payment did not go through, so nothing was bought.", code="payment-failed")
    if method_token:
        method = methods.attach_method(session, client_id, method_token, is_autopay=True)
    else:
        method = methods.autopay_method(session, client_id)
    if method is None or method.status != "active":
        raise ValidationFailed(
            "A payment method is needed for what falls due later.", pointer="/method_token",
            code="payment-method-required",
        )  # fmt: skip
    return None


def _key_reused() -> ValidationFailed:
    return ValidationFailed("This Idempotency-Key was used for another payment.", code="idempotency-key-reused")


def _covering(session: Session, invoice: Invoice, payment: Payment) -> Payment:
    """The payment, once the invoice is covered (settled or pending); a key whose money is spent buys nothing."""
    session.flush()
    session.refresh(invoice)
    if invoice.status not in ("paid", "payment_pending"):
        raise _key_reused()
    return payment
