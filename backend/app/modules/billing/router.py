"""billing HTTP surface (kernel): just enough to exercise the money path end to end. Build module 8 adds the
rest of openapi-money.yaml (workbench, stored methods, autopay, voids, statements, settings)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.billing import schemas as s
from app.modules.billing import service

router = APIRouter(
    route_class=TxRoute, tags=["billing"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]
# Money movement must be replay-safe (overview 3.12): these routes refuse a request without the header.
# The parameter must be called idempotency_key: it then merges with the router-level optional header in OpenAPI.
RequiredKey = Annotated[str, Header(min_length=8, max_length=255, description="Required; keys live 24 hours.")]


@router.get("/revenue-categories", response_model=s.Page[s.RevenueCategoryOut])
def list_revenue_categories(query: Lists, ctx: Ctx = Depends(require())):
    """Filters: is_active; q searches code and label. Sort: code, label."""
    return service.list_revenue_categories(ctx.session, ctx.principal, query)


@router.get("/charges", response_model=s.Page[s.ChargeOut])
def list_charges(query: Lists, ctx: Ctx = Depends(require("billing.charge.read"))):
    """Filters: client_id, invoice_id, location_id, status, kind, source_id. Sort: bill_on, created_at."""
    return service.list_charges(ctx.session, ctx.principal, query)


@router.post("/charges", response_model=s.ChargeOut, status_code=201)
def create_charge(body: s.ChargeCreate, ctx: Ctx = Depends(require("billing.charge.create"))):
    """Add a manual billing item; taxes come from its revenue category. Errors: period-locked."""
    return service.create_charge(ctx.session, ctx.principal, body.model_dump())


@router.post("/charges/{charge_id}/reverse", response_model=s.ChargeOut, status_code=201)
def reverse_charge(
    charge_id: UUID,
    body: s.ChargeReverseRequest,
    idempotency_key: RequiredKey,
    ctx: Ctx = Depends(require("billing.charge.reverse")),
):
    """Returns the new negating item. Money applied to the original becomes account credit; returning it
    is a separate refund. Errors: charge-not-reversible, period-locked."""
    return service.reverse_charge(ctx.session, ctx.principal, charge_id, body.model_dump())


@router.get("/invoices", response_model=s.Page[s.InvoiceOut])
def list_invoices(query: Lists, ctx: Ctx = Depends(require("billing.invoice.read"))):
    """Filters: bill_to_client_id, status, location_id. Sort: number, invoice_on, due_on."""
    return service.list_invoices(ctx.session, ctx.principal, query)


@router.post("/invoices", response_model=s.InvoiceDetail, status_code=201)
def create_invoice(body: s.InvoiceCreate, ctx: Ctx = Depends(require("billing.invoice.create"))):
    """Invoice selected uninvoiced items for one payer. Errors: charge-not-invoiceable."""
    return service.create_invoice(ctx.session, ctx.principal, body.model_dump())


@router.get("/invoices/{invoice_id}", response_model=s.InvoiceDetail)
def get_invoice(invoice_id: UUID, ctx: Ctx = Depends(require("billing.invoice.read"))):
    return service.get_invoice(ctx.session, ctx.principal, invoice_id)


@router.get("/payments", response_model=s.Page[s.PaymentOut])
def list_payments(query: Lists, ctx: Ctx = Depends(require("billing.payment.read"))):
    """Filters: client_id, status, location_id. Sort: received_at."""
    return service.list_payments(ctx.session, ctx.principal, query)


@router.post("/payments", response_model=s.PaymentDetail, status_code=201)
def take_payment(
    body: s.PaymentTake, idempotency_key: RequiredKey, ctx: Ctx = Depends(require("billing.payment.take"))
):
    """Take a payment and allocate it. 201 whatever the outcome: read `status` (`succeeded`, `processing`
    for a bank debit, `failed` for a decline, `unknown` when the processor did not answer). Errors:
    allocation-exceeds-balance, allocation-exceeds-payment, processor-not-connected."""
    return service.take_payment_at_desk(ctx.session, ctx.principal, body.model_dump(), idempotency_key)


@router.get("/payments/{payment_id}", response_model=s.PaymentDetail)
def get_payment(payment_id: UUID, ctx: Ctx = Depends(require("billing.payment.read"))):
    return service.get_payment(ctx.session, ctx.principal, payment_id)


@router.post("/payments/{payment_id}/confirm", response_model=s.PaymentDetail)
def confirm_payment(payment_id: UUID, ctx: Ctx = Depends(require("billing.payment.take"))):
    """Re-read the processor and apply its answer (settles a pending bank debit). Safe to repeat."""
    return service.confirm_payment_at_desk(ctx.session, ctx.principal, payment_id)


@router.post("/payments/{payment_id}/allocations", response_model=s.PaymentDetail)
def allocate_payment(
    payment_id: UUID, body: s.AllocationsCreate, ctx: Ctx = Depends(require("billing.payment.reallocate"))
):
    """Apply a payment's remainder to items. Errors: allocation-exceeds-balance, allocation-exceeds-payment,
    payment-not-allocatable."""
    return service.allocate_payment(ctx.session, ctx.principal, payment_id, body.model_dump())


@router.post("/payments/{payment_id}/refunds", response_model=s.RefundOut, status_code=201)
def create_refund(
    payment_id: UUID,
    body: s.RefundCreate,
    idempotency_key: RequiredKey,
    ctx: Ctx = Depends(require("billing.refund.create")),
):
    """Refund a payment's unapplied remainder. Errors: refund-exceeds-unapplied, payment-not-refundable."""
    return service.create_refund(ctx.session, ctx.principal, payment_id, body.model_dump(), idempotency_key)


@router.get("/ledger-entries", response_model=s.Page[s.LedgerEntryOut])
def list_ledger_entries(query: Lists, ctx: Ctx = Depends(require("billing.ledger.read"))):
    """Raw double-entry rows. Filters: account, client_id, charge_id, payment_id, location_id, effective_on."""
    return service.list_ledger_entries(ctx.session, ctx.principal, query)
