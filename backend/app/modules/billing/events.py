"""Events the billing context emits. Thin payloads: ids and the transition, no PII (overview 3.11)."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _ChargeEvent(Event):
    aggregate_type: ClassVar[str] = "charge"
    charge_id: UUID
    client_id: UUID | None
    source_context: str
    source_type: str
    source_id: UUID


class ChargeCreated(_ChargeEvent):
    type: Literal["billing.charge.created"] = "billing.charge.created"


class ChargeReversed(_ChargeEvent):
    type: Literal["billing.charge.reversed"] = "billing.charge.reversed"
    reversal_charge_id: UUID


class _InvoiceEvent(Event):
    aggregate_type: ClassVar[str] = "invoice"
    invoice_id: UUID
    bill_to_client_id: UUID | None


class InvoiceIssued(_InvoiceEvent):
    type: Literal["billing.invoice.issued"] = "billing.invoice.issued"


class InvoicePaid(_InvoiceEvent):
    type: Literal["billing.invoice.paid"] = "billing.invoice.paid"


class _PaymentEvent(Event):
    aggregate_type: ClassVar[str] = "payment"
    payment_id: UUID
    client_id: UUID | None


class PaymentProcessing(_PaymentEvent):
    type: Literal["billing.payment.processing"] = "billing.payment.processing"


class PaymentSucceeded(_PaymentEvent):
    type: Literal["billing.payment.succeeded"] = "billing.payment.succeeded"


class PaymentFailed(_PaymentEvent):
    type: Literal["billing.payment.failed"] = "billing.payment.failed"
    failure_category: str | None


class PaymentRefunded(_PaymentEvent):
    type: Literal["billing.payment.refunded"] = "billing.payment.refunded"
    refund_id: UUID
    amount_minor: int
