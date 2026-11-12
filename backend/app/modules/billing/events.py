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


class ChargeVoided(_ChargeEvent):
    type: Literal["billing.charge.voided"] = "billing.charge.voided"


class ChargeAdjusted(_ChargeEvent):
    """A money edit: the charge was replaced by `replacement_charge_id`. Not a cancellation of what was sold."""

    type: Literal["billing.charge.adjusted"] = "billing.charge.adjusted"
    replacement_charge_id: UUID


class _InvoiceEvent(Event):
    aggregate_type: ClassVar[str] = "invoice"
    invoice_id: UUID
    bill_to_client_id: UUID | None


class InvoiceIssued(_InvoiceEvent):
    type: Literal["billing.invoice.issued"] = "billing.invoice.issued"


class InvoicePaid(_InvoiceEvent):
    type: Literal["billing.invoice.paid"] = "billing.invoice.paid"


class InvoiceVoided(_InvoiceEvent):
    type: Literal["billing.invoice.voided"] = "billing.invoice.voided"


class InvoicePastDue(_InvoiceEvent):
    type: Literal["billing.invoice.past_due"] = "billing.invoice.past_due"


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


class PaymentVoided(_PaymentEvent):
    type: Literal["billing.payment.voided"] = "billing.payment.voided"


class PaymentDisputed(_PaymentEvent):
    type: Literal["billing.payment.disputed"] = "billing.payment.disputed"
    dispute_id: UUID


class PaymentDisputeClosed(_PaymentEvent):
    type: Literal["billing.payment.dispute_closed"] = "billing.payment.dispute_closed"
    dispute_id: UUID
    outcome: Literal["won", "lost"]


class PaymentMethodExpiring(Event):
    aggregate_type: ClassVar[str] = "payment_method"
    type: Literal["billing.payment_method.expiring"] = "billing.payment_method.expiring"
    payment_method_id: UUID
    client_id: UUID


class StatementBatchCompleted(Event):
    """Every recipient of a statement batch has an outcome (BIL-11). Counts only, no addresses."""

    aggregate_type: ClassVar[str] = "statement_batch"
    type: Literal["billing.statement_batch.completed"] = "billing.statement_batch.completed"
    statement_batch_id: UUID
    location_id: UUID
    sent_count: int
    failed_count: int
    skipped_count: int


class _CatalogItemSaleEvent(Event):
    aggregate_type: ClassVar[str] = "catalog_item_sale"
    catalog_item_sale_id: UUID
    catalog_item_id: UUID
    client_id: UUID


class CatalogItemSold(_CatalogItemSaleEvent):
    type: Literal["billing.catalog_item_sale.sold"] = "billing.catalog_item_sale.sold"


class CatalogItemSaleRenewed(_CatalogItemSaleEvent):
    type: Literal["billing.catalog_item_sale.renewed"] = "billing.catalog_item_sale.renewed"
    successor_sale_id: UUID


class CatalogItemSaleEnded(_CatalogItemSaleEvent):
    """The term is over (no renewal) or staff cancelled it; `status` says which."""

    type: Literal["billing.catalog_item_sale.ended"] = "billing.catalog_item_sale.ended"
    status: Literal["ended", "cancelled"]
