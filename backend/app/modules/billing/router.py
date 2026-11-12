"""billing HTTP surface (docs/api/openapi-money.yaml, tag billing): staff routes, the client portal, the
public pay link and the provider webhook. Handlers are named after the spec's operationIds."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, current_ctx, public_session, require
from app.core.idempotency import KEY_PATTERN, idempotency
from app.core.pagination import ListQuery, list_query, paginate
from app.core.ratelimit import rate_limit
from app.modules.billing import (
    autopay,
    catalog,
    catalogue,
    desk,
    documents,
    methods,
    portal,
    service,
    statements,
    webhooks,
)
from app.modules.billing import schemas as s
from app.modules.billing.models import BillingNotice

router = APIRouter(
    route_class=TxRoute, tags=["billing"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]
# Money movement must be replay-safe (overview 3.12): these routes refuse a request without the header.
# The parameter must be called idempotency_key: it then merges with the router-level optional header in OpenAPI.
RequiredKey = Annotated[
    str, Header(min_length=8, max_length=255, pattern=KEY_PATTERN, description="Required; keys live 24 hours.")
]


@router.get("/revenue-categories", response_model=s.Page[s.RevenueCategoryOut])
def list_revenue_categories(query: Lists, ctx: Ctx = Depends(require())):
    """Filters: is_active; q searches code and label. Sort: code, label."""
    return service.list_revenue_categories(ctx.session, ctx.principal, query)


@router.get("/charges", response_model=s.Page[s.ChargeOut])
def list_charges(query: Lists, ctx: Ctx = Depends(require("billing.charge.read"))):
    """The items workbench. Filters: client_id, invoice_id, location_id, status, kind, source_id,
    revenue_category_id, bill_on, created_by_staff_user_id, is_uninvoiced (the "cart"), is_open; q searches the
    description. Voided items are hidden unless status=voided. Sort: bill_on, created_at, revenue_on."""
    return desk.list_charges(ctx.session, ctx.principal, query)


@router.post("/charges", response_model=s.ChargeOut, status_code=201)
def create_charge(body: s.ChargeCreate, ctx: Ctx = Depends(require("billing.charge.create"))):
    """Add a manual billing item; taxes come from its revenue category. Errors: period-locked."""
    return desk.create_charge(ctx.session, ctx.principal, body.model_dump())


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


# === build module 8 ========================================================================================

Client = Annotated[Ctx, Depends(current_ctx)]  # any signed-in principal; portal services check ownership
PDF = {200: {"content": {"application/pdf": {}}, "description": "The PDF, as an attachment."}}


def _pdf(named: tuple[str, bytes]) -> Response:
    name, data = named
    return Response(
        data, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "private, no-store"},
    )  # fmt: skip


Staff = Depends(require())  # configuration reads: any signed-in staff user


def _patch(body) -> dict:
    return body.model_dump(exclude_unset=True)


# --- catalogue ---------------------------------------------------------------------------------------------


@router.post("/revenue-categories", response_model=s.RevenueCategoryDetail, status_code=201)
def create_revenue_category(
    body: s.RevenueCategoryCreate, ctx: Ctx = Depends(require("billing.revenue_category.manage"))
):
    return catalogue.create_revenue_category(ctx.session, ctx.principal, body.model_dump())


@router.get("/revenue-categories/{revenue_category_id}", response_model=s.RevenueCategoryDetail)
def get_revenue_category(revenue_category_id: UUID, ctx: Ctx = Staff):
    return catalogue.get_revenue_category(ctx.session, ctx.principal, revenue_category_id)


@router.patch("/revenue-categories/{revenue_category_id}", response_model=s.RevenueCategoryDetail)
def update_revenue_category(
    revenue_category_id: UUID,
    body: s.RevenueCategoryUpdate,
    ctx: Ctx = Depends(require("billing.revenue_category.manage")),
):
    """`tax_ids` replaces the category's default taxes. Posted items keep the taxes they were created with."""
    return catalogue.update_revenue_category(ctx.session, ctx.principal, revenue_category_id, _patch(body))


@router.get("/taxes", response_model=s.Page[s.TaxOut])
def list_taxes(query: Lists, ctx: Ctx = Staff):
    return catalogue.list_taxes(ctx.session, ctx.principal, query)


@router.post("/taxes", response_model=s.TaxDetail, status_code=201)
def create_tax(body: s.TaxCreate, ctx: Ctx = Depends(require("billing.tax.manage"))):
    return catalogue.create_tax(ctx.session, ctx.principal, body.model_dump())


@router.get("/taxes/{tax_id}", response_model=s.TaxDetail)
def get_tax(tax_id: UUID, ctx: Ctx = Staff):
    return catalogue.get_tax(ctx.session, ctx.principal, tax_id)


@router.patch("/taxes/{tax_id}", response_model=s.TaxDetail)
def update_tax(tax_id: UUID, body: s.TaxUpdate, ctx: Ctx = Depends(require("billing.tax.manage"))):
    return catalogue.update_tax(ctx.session, ctx.principal, tax_id, _patch(body))


@router.post("/taxes/{tax_id}/rates", response_model=s.TaxDetail, status_code=201)
def add_tax_rate(tax_id: UUID, body: s.TaxRateIn, ctx: Ctx = Depends(require("billing.tax.manage"))):
    """A new rate from a date. Items are taxed at the rate in force on their revenue date."""
    return catalogue.add_tax_rate(ctx.session, ctx.principal, tax_id, body.model_dump())


@router.patch("/taxes/{tax_id}/rates/{tax_rate_id}", response_model=s.TaxDetail)
def update_tax_rate(
    tax_id: UUID, tax_rate_id: UUID, body: s.TaxRateUpdate, ctx: Ctx = Depends(require("billing.tax.manage"))
):
    """Only a rate no item has used yet. Errors: tax-rate-in-use."""
    return catalogue.update_tax_rate(ctx.session, ctx.principal, tax_id, tax_rate_id, _patch(body))


@router.delete("/taxes/{tax_id}/rates/{tax_rate_id}", status_code=204)
def delete_tax_rate(tax_id: UUID, tax_rate_id: UUID, ctx: Ctx = Depends(require("billing.tax.manage"))) -> None:
    catalogue.delete_tax_rate(ctx.session, ctx.principal, tax_id, tax_rate_id)


@router.get("/tender-types", response_model=list[s.TenderTypeOut])
def list_tender_types(ctx: Ctx = Staff):
    return catalogue.list_tender_types(ctx.session, ctx.principal)


@router.post("/tender-types", response_model=s.TenderTypeOut, status_code=201)
def create_tender_type(body: s.TenderTypeCreate, ctx: Ctx = Depends(require("billing.settings.manage"))):
    return catalogue.create_tender_type(ctx.session, ctx.principal, body.model_dump())


@router.patch("/tender-types/{tender_type_id}", response_model=s.TenderTypeOut)
def update_tender_type(
    tender_type_id: UUID, body: s.TenderTypeUpdate, ctx: Ctx = Depends(require("billing.settings.manage"))
):
    return catalogue.update_tender_type(ctx.session, ctx.principal, tender_type_id, _patch(body))


@router.get("/billing-settings", response_model=s.BillingSettingsOut)
def get_billing_settings(location_id: UUID | None = None, ctx: Ctx = Staff):
    """The settings in force: a location's override if it has one, else the tenant's."""
    return catalogue.get_settings(ctx.session, ctx.principal, location_id)


@router.put("/billing-settings", response_model=s.BillingSettingsOut)
def put_billing_settings(
    body: s.BillingSettingsIn, location_id: UUID | None = None, ctx: Ctx = Depends(require("billing.settings.manage"))
):
    return catalogue.put_settings(ctx.session, ctx.principal, location_id, body.model_dump())


@router.delete("/billing-settings", status_code=204)
def delete_billing_settings_override(location_id: UUID, ctx: Ctx = Depends(require("billing.settings.manage"))) -> None:
    catalogue.delete_settings_override(ctx.session, ctx.principal, location_id)


@router.get("/billing-settings/period-lock", response_model=s.PeriodLockOut)
def get_billing_period_lock(ctx: Ctx = Depends(require("billing.settings.manage"))):
    return {"locked_through_on": catalogue.get_period_lock(ctx.session, ctx.principal)}


@router.put("/billing-settings/period-lock", response_model=s.PeriodLockOut)
def set_billing_period_lock(body: s.PeriodLock, ctx: Ctx = Depends(require("billing.settings.manage"))):
    """Close the books through a date: later postings dated on or before it are refused with period-locked."""
    return {"locked_through_on": catalogue.set_period_lock(ctx.session, ctx.principal, body.locked_through_on)}


@router.get("/coupons", response_model=s.Page[s.CouponOut])
def list_coupons(query: Lists, ctx: Ctx = Staff):
    return catalogue.list_coupons(ctx.session, ctx.principal, query)


@router.post("/coupons", response_model=s.CouponOut, status_code=201)
def create_coupon(body: s.CouponCreate, ctx: Ctx = Depends(require("billing.coupon.manage"))):
    return catalogue.create_coupon(ctx.session, ctx.principal, body.model_dump())


@router.post("/coupons/validate", response_model=s.CouponQuote)
def validate_coupon(body: s.CouponValidateRequest, ctx: Ctx = Depends(require("billing.discount.apply_preset"))):
    """Validation only; a coupon is redeemed inside the command that sells something."""
    return catalogue.quote_coupon(ctx.session, **body.model_dump())


@router.get("/coupons/{coupon_id}", response_model=s.CouponOut)
def get_coupon(coupon_id: UUID, ctx: Ctx = Staff):
    return catalogue.get_coupon(ctx.session, ctx.principal, coupon_id)


@router.patch("/coupons/{coupon_id}", response_model=s.CouponOut)
def update_coupon(coupon_id: UUID, body: s.CouponUpdate, ctx: Ctx = Depends(require("billing.coupon.manage"))):
    return catalogue.update_coupon(ctx.session, ctx.principal, coupon_id, _patch(body))


@router.delete("/coupons/{coupon_id}", status_code=204)
def delete_coupon(coupon_id: UUID, ctx: Ctx = Depends(require("billing.coupon.manage"))) -> None:
    """Errors: coupon-in-use (deactivate it instead)."""
    catalogue.delete_coupon(ctx.session, ctx.principal, coupon_id)


@router.get("/coupons/{coupon_id}/redemptions", response_model=list[s.CouponRedemptionOut])
def list_coupon_redemptions(coupon_id: UUID, ctx: Ctx = Depends(require("billing.coupon.manage"))):
    return catalogue.list_coupon_redemptions(ctx.session, ctx.principal, coupon_id)


# --- pre-defined items (BIL-14) ----------------------------------------------------------------------------


@router.get("/catalog-items", response_model=s.Page[s.CatalogItemOut])
def list_catalog_items(query: Lists, ctx: Ctx = Staff):
    """Filters: location_id, kind, is_active; q searches the description. Sort: description, created_at."""
    return catalog.list_items(ctx.session, ctx.principal, query)


@router.post("/catalog-items", response_model=s.CatalogItemOut, status_code=201)
def create_catalog_item(body: s.CatalogItemCreate, ctx: Ctx = Depends(require("billing.item.manage"))):
    return catalog.create_item(ctx.session, ctx.principal, body.model_dump())


@router.get("/catalog-items/{catalog_item_id}", response_model=s.CatalogItemOut)
def get_catalog_item(catalog_item_id: UUID, ctx: Ctx = Staff):
    return catalog.get_item(ctx.session, ctx.principal, catalog_item_id)


@router.patch("/catalog-items/{catalog_item_id}", response_model=s.CatalogItemOut)
def update_catalog_item(
    catalog_item_id: UUID, body: s.CatalogItemUpdate, ctx: Ctx = Depends(require("billing.item.manage"))
):
    """Edits apply to later sales; set is_active false to stop selling it."""
    return catalog.update_item(ctx.session, ctx.principal, catalog_item_id, _patch(body))


@router.post("/catalog-items/{catalog_item_id}/sales", response_model=s.CatalogItemSaleOut, status_code=201)
def sell_catalog_item(
    catalog_item_id: UUID,
    body: s.CatalogItemSaleCreate,
    idempotency_key: RequiredKey,
    ctx: Ctx = Depends(require("billing.charge.create")),
):
    """Sell an item to a client: one billing item per occurrence, invoiced as the item says. A fee or
    discount other than the item's needs billing.charge.override_price."""
    return catalog.sell_item(ctx.session, ctx.principal, catalog_item_id, _patch(body) | {"client_id": body.client_id})


@router.get("/catalog-item-sales", response_model=s.Page[s.CatalogItemSaleOut])
def list_catalog_item_sales(query: Lists, ctx: Ctx = Depends(require("billing.charge.read"))):
    """Filters: client_id, catalog_item_id, status, location_id. Sort: starts_on, created_at."""
    return catalog.list_sales(ctx.session, ctx.principal, query)


@router.post("/catalog-item-sales/{catalog_item_sale_id}/cancel", response_model=s.CatalogItemSaleOut)
def cancel_catalog_item_sale(
    catalog_item_sale_id: UUID, body: s.ReasonRequest, ctx: Ctx = Depends(require("billing.charge.reverse"))
):
    """Occurrences not started yet are reversed; money applied to them becomes account credit."""
    return catalog.cancel_sale(ctx.session, ctx.principal, catalog_item_sale_id, body.model_dump())


# --- items -------------------------------------------------------------------------------------------------


@router.post("/charges/preview", response_model=s.ChargePreview)
def preview_charge(body: s.ChargePreviewRequest, ctx: Ctx = Depends(require("billing.charge.create"))):
    return desk.preview_charge(ctx.session, ctx.principal, body.model_dump())


@router.get("/charges/{charge_id}", response_model=s.ChargeDetail)
def get_charge(charge_id: UUID, ctx: Ctx = Depends(require("billing.charge.read"))):
    return desk.get_charge(ctx.session, ctx.principal, charge_id)


@router.patch("/charges/{charge_id}", response_model=s.ChargeDetail)
def update_charge(charge_id: UUID, body: s.ChargeUpdate, ctx: Ctx = Depends(require("billing.charge.update"))):
    """Text fields change in place. A money field returns the adjustment item that replaces this one (its
    `adjusts_charge_id` points back). Errors: charge-not-reversible, period-locked."""
    return desk.update_charge(ctx.session, ctx.principal, charge_id, _patch(body))


@router.post("/charges/{charge_id}/void", response_model=s.ChargeOut)
def void_charge(
    charge_id: UUID,
    body: s.ReasonRequest,
    idempotency_key: RequiredKey,
    ctx: Ctx = Depends(require("billing.charge.void")),
):
    """Only an uninvoiced item with no payments. Errors: charge-not-voidable, period-locked."""
    return desk.void_charge(ctx.session, ctx.principal, charge_id, body.model_dump())


# --- invoices ----------------------------------------------------------------------------------------------


@router.patch("/invoices/{invoice_id}", response_model=s.InvoiceDetail)
def update_invoice(invoice_id: UUID, body: s.InvoiceUpdate, ctx: Ctx = Depends(require("billing.invoice.update"))):
    """Errors: stale-version, invoice-voided, invoice-has-schedule."""
    return desk.update_invoice(ctx.session, ctx.principal, invoice_id, _patch(body))


@router.post("/invoices/{invoice_id}/charges", response_model=s.InvoiceDetail)
def add_invoice_charges(
    invoice_id: UUID, body: s.InvoiceChargesAdd, ctx: Ctx = Depends(require("billing.invoice.update"))
):
    """Errors: charge-not-invoiceable, payer-mismatch."""
    return desk.add_invoice_charges(ctx.session, ctx.principal, invoice_id, body.model_dump())


@router.delete("/invoices/{invoice_id}/charges/{charge_id}", response_model=s.InvoiceDetail)
def remove_invoice_charge(invoice_id: UUID, charge_id: UUID, ctx: Ctx = Depends(require("billing.invoice.update"))):
    """The item becomes uninvoiced. Errors: charge-has-payments."""
    return desk.remove_invoice_charge(ctx.session, ctx.principal, invoice_id, charge_id)


@router.post("/invoices/{invoice_id}/charges/{charge_id}/move", response_model=s.InvoiceDetail)
def move_invoice_charge(
    invoice_id: UUID,
    charge_id: UUID,
    body: s.InvoiceChargeMove,
    ctx: Ctx = Depends(require("billing.invoice.update")),
):
    """To another invoice of the same payer and location. Errors: payer-mismatch."""
    return desk.move_invoice_charge(ctx.session, ctx.principal, invoice_id, charge_id, body.model_dump())


@router.post("/invoices/{invoice_id}/void", response_model=s.InvoiceDetail)
def void_invoice(
    invoice_id: UUID,
    body: s.InvoiceVoidRequest,
    idempotency_key: RequiredKey,
    ctx: Ctx = Depends(require("billing.invoice.void")),
):
    """Its items go back to uninvoiced. Errors: invoice-has-payments (pass release_allocations)."""
    return desk.void_invoice(ctx.session, ctx.principal, invoice_id, body.model_dump())


@router.post("/invoices/{invoice_id}/reassign-payer", response_model=s.InvoiceDetail)
def reassign_invoice_payer(
    invoice_id: UUID, body: s.InvoiceReassign, ctx: Ctx = Depends(require("billing.invoice.reassign_payer"))
):
    """Errors: invoice-has-payments."""
    return desk.reassign_invoice_payer(ctx.session, ctx.principal, invoice_id, body.model_dump())


@router.post("/invoices/{invoice_id}/mark-paid", response_model=s.PaymentDetail, status_code=201)
def mark_invoice_paid(
    invoice_id: UUID,
    body: s.MarkPaidRequest,
    idempotency_key: RequiredKey,
    ctx: Ctx = Depends(require("billing.payment.take")),
):
    """Records an external payment for the balance. Errors: invoice-not-payable."""
    return desk.mark_invoice_paid(ctx.session, ctx.principal, invoice_id, body.model_dump(), idempotency_key)


@router.get("/invoices/{invoice_id}/payment-schedule", response_model=s.ScheduleOut)
def get_payment_schedule(invoice_id: UUID, ctx: Ctx = Depends(require("billing.invoice.read"))):
    return desk.get_schedule(ctx.session, ctx.principal, invoice_id)


@router.put("/invoices/{invoice_id}/payment-schedule", response_model=s.ScheduleOut)
def put_payment_schedule(
    invoice_id: UUID, body: s.ScheduleReplace, ctx: Ctx = Depends(require("billing.payment_schedule.manage"))
):
    """The instalments must add up to the invoice total. Errors: schedule-not-balanced."""
    return desk.put_schedule(ctx.session, ctx.principal, invoice_id, body.model_dump())


@router.post("/invoices/{invoice_id}/payment-schedule/generate", response_model=s.ScheduleOut)
def generate_payment_schedule(
    invoice_id: UUID, body: s.ScheduleGenerate, ctx: Ctx = Depends(require("billing.payment_schedule.manage"))
):
    return desk.generate_schedule(ctx.session, ctx.principal, invoice_id, body.model_dump())


@router.post("/invoices/{invoice_id}/deliveries", response_model=s.DeliveryOut, status_code=201)
def send_invoice(invoice_id: UUID, body: s.DocumentSendRequest, ctx: Ctx = Depends(require("billing.invoice.send"))):
    """Email the invoice with a single-use pay link. Errors: no-email-address, invoice-voided."""
    return documents.send_invoice(ctx.session, ctx.principal, invoice_id, body.model_dump())


@router.get("/invoices/{invoice_id}/deliveries", response_model=list[s.DeliveryOut])
def list_invoice_deliveries(invoice_id: UUID, ctx: Ctx = Depends(require("billing.invoice.read"))):
    return documents.list_invoice_deliveries(ctx.session, ctx.principal, invoice_id)


@router.get("/invoices/{invoice_id}/document", response_model=s.InvoiceDocument)
def get_invoice_document(invoice_id: UUID, ctx: Ctx = Depends(require("billing.invoice.read"))):
    """The printable content of the invoice as data; `/pdf` renders the same content."""
    return documents.get_invoice_document(ctx.session, ctx.principal, invoice_id)


@router.get("/invoices/{invoice_id}/pdf", response_class=Response, responses=PDF)
def get_invoice_pdf(invoice_id: UUID, ctx: Ctx = Depends(require("billing.invoice.read"))):
    return _pdf(documents.get_invoice_pdf(ctx.session, ctx.principal, invoice_id))


@router.post("/billing-bulk-actions", response_model=s.BulkInvoiceResult)
def create_billing_bulk_action(body: s.BulkInvoiceRequest, ctx: Ctx = Depends(require("billing.invoice.bulk_create"))):
    """Invoice many uninvoiced items: one invoice per client, never mixed. Runs in the request and reports
    per client; `is_dry_run` previews."""
    return documents.bulk_invoice(ctx.session, ctx.principal, body.model_dump())


@router.get("/billing-history", response_model=s.Page[s.HistoryOut])
def list_billing_history(query: Lists, ctx: Ctx = Depends(require("billing.history.read"))):
    """Filters: entity_type (invoice, charge, payment...), entity_id, action, location_id."""
    return documents.list_history(ctx.session, ctx.principal, query)


@router.get("/billing-notices", response_model=s.Page[s.NoticeOut])
def list_billing_notices(query: Lists, ctx: Ctx = Depends(require("billing.invoice.read"))):
    """Reminders, decline notices and alerts that were sent. Filters: kind, client_id, subject_id."""
    return paginate(
        ctx.session, select(BillingNotice), query, id_column=BillingNotice.id,
        sort_fields={"sent_at": BillingNotice.sent_at}, default_sort="-sent_at",
        filter_fields={
            "kind": BillingNotice.kind, "client_id": BillingNotice.client_id, "subject_id": BillingNotice.subject_id
        },
    )  # fmt: skip


@router.get("/receivables-ageing", response_model=s.AgeingReport)
def get_receivables_ageing(
    as_of: date | None = None, location_id: UUID | None = None, ctx: Ctx = Depends(require("billing.invoice.read"))
):
    """Accounts receivable by client and age, as at a date (default today)."""
    return documents.receivables_ageing(ctx.session, ctx.principal, as_of=as_of, location_id=location_id)


# --- payments, credit, receipts, statements ----------------------------------------------------------------


@router.post("/payments/{payment_id}/cancel", response_model=s.PaymentDetail)
def cancel_payment(payment_id: UUID, ctx: Ctx = Depends(require("billing.payment.take"))):
    """Errors: payment-not-cancellable."""
    return desk.cancel_payment(ctx.session, ctx.principal, payment_id)


@router.delete("/payments/{payment_id}/allocations/{payment_allocation_id}", response_model=s.PaymentDetail)
def release_allocation(
    payment_id: UUID, payment_allocation_id: UUID, ctx: Ctx = Depends(require("billing.payment.reallocate"))
):
    """Take the money back off one item; it becomes account credit. Errors: allocation-released."""
    return desk.release_allocation(ctx.session, ctx.principal, payment_id, payment_allocation_id)


@router.post("/payments/{payment_id}/void", response_model=s.PaymentDetail)
def void_payment(
    payment_id: UUID,
    body: s.ReasonRequest,
    idempotency_key: RequiredKey,
    ctx: Ctx = Depends(require("billing.payment.void")),
):
    """Record-only payments only. Errors: use-refund, payment-not-voidable."""
    return desk.void_payment(ctx.session, ctx.principal, payment_id, body.model_dump())


@router.get("/refunds", response_model=s.Page[s.RefundOut])
def list_refunds(query: Lists, ctx: Ctx = Depends(require("billing.payment.read"))):
    """Filters: client_id, payment_id, status, location_id, refund_batch_id."""
    return desk.list_refunds(ctx.session, ctx.principal, query)


@router.get("/payments/{payment_id}/receipt", response_model=s.ReceiptOut)
def get_receipt(payment_id: UUID, ctx: Ctx = Depends(require("billing.payment.read"))):
    return documents.get_receipt(ctx.session, ctx.principal, payment_id)


@router.get("/payments/{payment_id}/receipt/pdf", response_class=Response, responses=PDF)
def get_receipt_pdf(payment_id: UUID, ctx: Ctx = Depends(require("billing.payment.read"))):
    return _pdf(documents.get_receipt_pdf(ctx.session, ctx.principal, payment_id))


@router.post("/payments/{payment_id}/receipt-deliveries", response_model=s.DeliveryOut, status_code=201)
def send_receipt(payment_id: UUID, body: s.DocumentSendRequest, ctx: Ctx = Depends(require("billing.invoice.send"))):
    return documents.send_receipt(ctx.session, ctx.principal, payment_id, body.model_dump())


@router.get("/clients/{client_id}/billing-summary", response_model=s.BillingSummary)
def get_client_billing_summary(client_id: UUID, ctx: Ctx = Depends(require("billing.invoice.read"))):
    return documents.get_billing_summary(ctx.session, ctx.principal, client_id)


@router.get("/clients/{client_id}/account-credit", response_model=s.AccountCredit)
def get_account_credit(client_id: UUID, ctx: Ctx = Depends(require("billing.payment.read"))):
    return documents.get_account_credit(ctx.session, ctx.principal, client_id)


@router.post("/clients/{client_id}/account-credit/apply", response_model=s.CreditApplied)
def apply_account_credit(
    client_id: UUID, body: s.CreditApplyRequest, ctx: Ctx = Depends(require("billing.credit.apply"))
):
    """Pay with money on account, oldest payment first."""
    return desk.apply_account_credit(ctx.session, ctx.principal, client_id, body.model_dump())


@router.post("/clients/{client_id}/account-credit/refund", response_model=list[s.RefundOut], status_code=201)
def refund_account_credit(
    client_id: UUID,
    body: s.CreditRefundRequest,
    idempotency_key: RequiredKey,
    ctx: Ctx = Depends(require("billing.refund.create")),
):
    """One refund per payment, newest first, each to its original method. Errors: refund-exceeds-unapplied."""
    return desk.refund_account_credit(ctx.session, ctx.principal, client_id, body.model_dump(), idempotency_key)


@router.get("/clients/{client_id}/statement", response_model=s.StatementOut)
def get_client_statement(
    client_id: UUID,
    from_on: date | None = None,
    to_on: date | None = None,
    date_basis: Annotated[str, Query(pattern="^(invoice_date|due_date)$")] = "invoice_date",
    ctx: Ctx = Depends(require("billing.invoice.read")),
):
    """Default period: the 30 days up to today at the client's home location, whose days the dates are."""
    return documents.get_statement(ctx.session, ctx.principal, client_id, from_on, to_on, date_basis)


@router.get("/clients/{client_id}/statement/pdf", response_class=Response, responses=PDF)
def get_client_statement_pdf(
    client_id: UUID,
    from_on: date | None = None,
    to_on: date | None = None,
    date_basis: Annotated[str, Query(pattern="^(invoice_date|due_date)$")] = "invoice_date",
    ctx: Ctx = Depends(require("billing.invoice.read")),
):
    return _pdf(documents.get_statement_pdf(
        ctx.session, ctx.principal, client_id, from_on, to_on, date_basis
    ))  # fmt: skip


@router.post("/clients/{client_id}/statement/deliveries", response_model=s.DeliveryOut, status_code=201)
def send_client_statement(
    client_id: UUID, body: s.StatementSend, ctx: Ctx = Depends(require("billing.statement.send"))
):
    return documents.send_statement(ctx.session, ctx.principal, client_id, body.model_dump())


@router.post("/statement-batches", response_model=s.StatementBatchOut, status_code=201)
def create_statement_batch(body: s.StatementBatchCreate, ctx: Ctx = Depends(require("billing.statement.send"))):
    """Statements for every payer with an invoice at the location in the period (`is_open_only`: still owing;
    `client_ids` narrows). Up to 25 recipients run in the request, more as a job: follow `status`."""
    return statements.create_batch(ctx.session, ctx.principal, body.model_dump())


@router.get("/statement-batches", response_model=s.Page[s.StatementBatchOut])
def list_statement_batches(query: Lists, ctx: Ctx = Depends(require("billing.statement.send"))):
    """Newest first, recipients left out (read one batch for them). Filters: location_id, status."""
    return statements.list_batches(ctx.session, ctx.principal, query)


@router.get("/statement-batches/{statement_batch_id}", response_model=s.StatementBatchOut)
def get_statement_batch(statement_batch_id: UUID, ctx: Ctx = Depends(require("billing.statement.send"))):
    return statements.get_batch(ctx.session, ctx.principal, statement_batch_id)


@router.get("/statement-batches/{statement_batch_id}/recipients", response_model=list[s.StatementRecipientOut])
def list_statement_recipients(statement_batch_id: UUID, ctx: Ctx = Depends(require("billing.statement.send"))):
    """Per-recipient outcome: sent, skipped_no_email, failed (with the reason) or still queued."""
    return statements.get_batch(ctx.session, ctx.principal, statement_batch_id)["recipients"]


@router.post("/statement-batches/{statement_batch_id}/resend", response_model=s.StatementBatchOut)
def resend_statement_batch(
    statement_batch_id: UUID, body: s.StatementBatchResend, ctx: Ctx = Depends(require("billing.statement.send"))
):
    """Send again to the listed recipients, or to every failed and skipped one when none are listed."""
    return statements.resend(ctx.session, ctx.principal, statement_batch_id, body.model_dump())


# --- stored methods, autopay, processor --------------------------------------------------------------------


@router.get("/clients/{client_id}/payment-methods", response_model=list[s.PaymentMethodOut])
def list_client_payment_methods(client_id: UUID, ctx: Ctx = Depends(require("billing.payment_method.read"))):
    return methods.list_client_methods(ctx.session, ctx.principal, client_id)


@router.post("/clients/{client_id}/payment-methods", response_model=s.PaymentMethodOut, status_code=201)
def attach_payment_method(
    client_id: UUID, body: s.PaymentMethodAttach, ctx: Ctx = Depends(require("billing.payment_method.manage"))
):
    """Store a method tokenised by the processor's hosted fields. Errors: payment-method-rejected."""
    return methods.attach_client_method(ctx.session, ctx.principal, client_id, body.model_dump())


@router.post("/clients/{client_id}/payment-methods/setup-intents", response_model=s.SetupIntentOut, status_code=201)
def create_setup_intent(
    client_id: UUID, body: s.SetupIntentRequest, ctx: Ctx = Depends(require("billing.payment_method.manage"))
):
    return methods.create_client_setup(ctx.session, ctx.principal, client_id, tuple(body.kinds))


@router.get("/payment-methods", response_model=s.Page[s.PaymentMethodOut])
def list_payment_methods(query: Lists, ctx: Ctx = Depends(require("billing.payment_method.read"))):
    """Expiring cards: filter exp_year and exp_month. Other filters: client_id, kind, status, is_autopay."""
    return methods.list_methods(ctx.session, ctx.principal, query)


@router.patch("/payment-methods/{payment_method_id}", response_model=s.PaymentMethodOut)
def update_payment_method(
    payment_method_id: UUID,
    body: s.PaymentMethodUpdate,
    ctx: Ctx = Depends(require("billing.payment_method.manage")),
):
    """Making a method the autopay method clears the flag on the client's other one and retries what waited."""
    return methods.update_method(ctx.session, ctx.principal, payment_method_id, body.model_dump())


@router.delete("/payment-methods/{payment_method_id}", status_code=204)
def remove_payment_method(
    payment_method_id: UUID, ctx: Ctx = Depends(require("billing.payment_method.manage"))
) -> None:
    methods.remove_client_method(ctx.session, ctx.principal, payment_method_id)


@router.post("/payment-methods/{payment_method_id}/verify", response_model=s.PaymentMethodOut)
def verify_bank_account(
    payment_method_id: UUID, body: s.BankVerifyRequest, ctx: Ctx = Depends(require("billing.payment_method.manage"))
):
    """Errors: verification-failed, payment-method-not-pending."""
    return methods.verify_client_bank_account(ctx.session, ctx.principal, payment_method_id, body.amounts)


@router.get("/autopay-runs", response_model=s.Page[s.AutopayRunOut])
def list_autopay_runs(query: Lists, ctx: Ctx = Depends(require("billing.payment.read"))):
    return autopay.list_runs(ctx.session, ctx.principal, query)


@router.post("/autopay-runs", response_model=s.AutopayRunResult, status_code=201)
def start_autopay_run(
    body: s.AutopayRunStart, idempotency_key: RequiredKey, ctx: Ctx = Depends(require("billing.autopay.run"))
):
    """Collect what is due at a location now, or preview it with is_dry_run. Safe to repeat for a date."""
    result = autopay.start_run(ctx.session, ctx.principal, body.model_dump())
    return {"preview": result} if isinstance(result, list) else {"run": result}


@router.get("/autopay-runs/{autopay_run_id}", response_model=s.AutopayRunOut)
def get_autopay_run(autopay_run_id: UUID, ctx: Ctx = Depends(require("billing.payment.read"))):
    return autopay.get_run(ctx.session, ctx.principal, autopay_run_id)


@router.get("/autopay-attempts", response_model=s.Page[s.AutopayAttemptOut])
def list_autopay_attempts(query: Lists, ctx: Ctx = Depends(require("billing.payment.read"))):
    """The autopay-error queue is status=failed&is_error_open=true. Filters: status, invoice_id,
    autopay_run_id, is_error_open."""
    return autopay.list_attempts(ctx.session, ctx.principal, query)


@router.post("/autopay-attempts/{autopay_attempt_id}/retry", response_model=s.AutopayAttemptOut, status_code=201)
def retry_autopay_attempt(
    autopay_attempt_id: UUID, idempotency_key: RequiredKey, ctx: Ctx = Depends(require("billing.autopay.run"))
):
    """Returns the new attempt. Errors: autopay-attempt-not-failed, invoice-not-payable."""
    return autopay.retry_attempt(ctx.session, ctx.principal, autopay_attempt_id)


@router.post("/autopay-attempts/{autopay_attempt_id}/clear-error", response_model=s.AutopayAttemptOut)
def clear_autopay_error(autopay_attempt_id: UUID, ctx: Ctx = Depends(require("billing.autopay.run"))):
    return autopay.clear_error(ctx.session, ctx.principal, autopay_attempt_id)


@router.get("/provider-accounts", response_model=list[s.ProviderAccountOut])
def list_provider_accounts(ctx: Ctx = Staff):
    return methods.list_provider_accounts(ctx.session, ctx.principal)


@router.post("/provider-accounts", response_model=s.ProviderAccountOut, status_code=201)
def connect_provider_account(body: s.ProviderConnect, ctx: Ctx = Depends(require("billing.provider.manage"))):
    """Errors: provider-unavailable, processor-already-connected."""
    return methods.connect_provider_account(ctx.session, ctx.principal, body.provider)


@router.post("/provider-accounts/{provider_account_id}/onboarding-links", response_model=s.OnboardingLink)
def create_onboarding_link(provider_account_id: UUID, ctx: Ctx = Depends(require("billing.provider.manage"))):
    return {"url": methods.create_onboarding_link(ctx.session, ctx.principal, provider_account_id)}


@router.post("/provider-accounts/{provider_account_id}/disconnect", response_model=s.ProviderAccountOut)
def disconnect_provider_account(provider_account_id: UUID, ctx: Ctx = Depends(require("billing.provider.manage"))):
    return methods.disconnect_provider_account(ctx.session, ctx.principal, provider_account_id)


# --- client portal: ownership is checked in billing.portal -------------------------------------------------


@router.get("/portal/invoices", response_model=s.Page[s.PortalInvoiceOut])
def list_portal_invoices(query: Lists, ctx: Client):
    """The caller's invoices. Filter is_payable=true for what can be paid now."""
    return portal.list_invoices(ctx.session, ctx.principal, query)


@router.get("/portal/invoices/{invoice_id}", response_model=s.InvoiceDocument)
def get_portal_invoice(invoice_id: UUID, ctx: Client):
    return portal.get_invoice(ctx.session, ctx.principal, invoice_id)


@router.get("/portal/invoices/{invoice_id}/pdf", response_class=Response, responses=PDF)
def get_portal_invoice_pdf(invoice_id: UUID, ctx: Client):
    return _pdf(portal.get_invoice_pdf(ctx.session, ctx.principal, invoice_id))


@router.get("/portal/statement", response_model=s.PortalStatementOut)
def get_portal_statement(
    ctx: Client, client_id: UUID | None = None, from_on: date | None = None, to_on: date | None = None
):
    """The caller's own statement; default period the 30 days up to today at their home location."""
    return portal.statement(ctx.session, ctx.principal, client_id, from_on, to_on)


@router.get("/portal/statement/pdf", response_class=Response, responses=PDF)
def get_portal_statement_pdf(
    ctx: Client, client_id: UUID | None = None, from_on: date | None = None, to_on: date | None = None
):
    return _pdf(portal.statement_pdf(ctx.session, ctx.principal, client_id, from_on, to_on))


@router.get("/portal/payments", response_model=s.Page[s.PortalPaymentOut])
def list_portal_payments(query: Lists, ctx: Client):
    return portal.list_payments(ctx.session, ctx.principal, query)


@router.post("/portal/payments", response_model=s.PortalPayment, status_code=201)
def pay_portal_invoices(body: s.PortalPaymentCreate, idempotency_key: RequiredKey, ctx: Client):
    """Pay the full balance of the caller's own invoices. The payer is the caller's client and a stored
    method must be theirs. Read `payment.status`. Errors: invoice-not-payable, payment-method-not-usable."""
    return portal.pay(ctx.session, ctx.principal, body.model_dump(), idempotency_key)


@router.get("/portal/billing-summary", response_model=s.BillingSummary)
def get_portal_billing_summary(ctx: Client, client_id: UUID | None = None):
    return portal.billing_summary(ctx.session, ctx.principal, client_id)


@router.get("/portal/payment-methods", response_model=list[s.PaymentMethodOut])
def list_portal_payment_methods(ctx: Client):
    return portal.list_methods(ctx.session, ctx.principal)


@router.post("/portal/payment-methods", response_model=s.PaymentMethodOut, status_code=201)
def attach_portal_payment_method(body: s.PaymentMethodAttach, ctx: Client):
    return portal.attach_method(ctx.session, ctx.principal, body.model_dump())


@router.post("/portal/payment-methods/setup-intents", response_model=s.SetupIntentOut, status_code=201)
def create_portal_setup_intent(body: s.SetupIntentRequest, ctx: Client):
    return portal.create_setup(ctx.session, ctx.principal, tuple(body.kinds))


@router.patch("/portal/payment-methods/{payment_method_id}", response_model=s.PaymentMethodOut)
def update_portal_payment_method(payment_method_id: UUID, body: s.PaymentMethodUpdate, ctx: Client):
    return portal.update_method(ctx.session, ctx.principal, payment_method_id, body.model_dump())


@router.delete("/portal/payment-methods/{payment_method_id}", status_code=204)
def remove_portal_payment_method(payment_method_id: UUID, ctx: Client) -> None:
    """Errors: payment-method-required (the last method while an autopay invoice is open)."""
    portal.remove_method(ctx.session, ctx.principal, payment_method_id)


# === anonymous: the emailed pay link and the provider webhook ==============================================

staff_and_portal, public = (
    router,
    APIRouter(route_class=TxRoute, tags=["billing"], generate_unique_id_function=camel_id),
)
PublicSession = Annotated[Session, Depends(public_session)]
_link_limit = [Depends(rate_limit("consume"))]


@public.post("/public/invoice-links/lookup", response_model=s.LinkInvoice, dependencies=_link_limit)
def get_invoice_by_link(body: s.InvoiceLinkLookup, session: PublicSession):
    """What the emailed link pays. The token travels in the body, never the URL. Errors: link-invalid."""
    return documents.invoice_by_link(session, body.token)


@public.post("/public/invoice-links/payments", response_model=s.LinkPayment, status_code=201, dependencies=_link_limit)
def pay_invoice_by_link(body: s.InvoiceLinkPayment, session: PublicSession, idempotency_key: RequiredKey):
    """Pay the invoice's balance by card. A payment that goes through uses the link up. Errors: link-invalid,
    invoice-not-payable."""
    payment = documents.pay_by_link(
        session, body.token, method_token=body.method_token, idempotency_key=idempotency_key
    )
    return {
        "status": payment.status, "amount_minor": payment.amount_minor, "currency": payment.currency,
        "receipt_number": payment.receipt_number, "client_secret": getattr(payment, "client_secret", None),
    }  # fmt: skip


@public.post("/webhooks/{provider}", response_model=s.WebhookAck)
async def receive_provider_webhook(provider: str, request: Request):
    """Signed events from the payment processor (`stripe`, or `fake` in development). Verified, stored once
    by event id, then processed in the tenant. A duplicate is acknowledged and ignored. Errors:
    invalid-signature."""
    body = await request.body()
    return {"result": await run_in_threadpool(webhooks.receive, provider, dict(request.headers), body)}


router = APIRouter()
router.include_router(staff_and_portal)
router.include_router(public)
