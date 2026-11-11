"""Billing's side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2).

The ledger is immutable (ADR 0003): `ledger_entry` and `billing_notice` rows keep the merged record as their
subject (it stays as a tombstone). Balances are derived from the documents, not from those rows, so the
documents (invoices, items, payments, refunds) simply move to the survivor. Erasure keeps every financial record,
strips its free text and stored payment methods, and is blocked while money is still owed either way.
"""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.modules import clients, platform
from app.modules.billing import methods, service
from app.modules.billing.models import (
    BillingDocumentDelivery,
    Charge,
    CouponRedemption,
    Invoice,
    Payment,
    PaymentMethod,
    ProviderCustomer,
    Refund,
)

_OPEN_INVOICE = ("open", "payment_pending", "partially_paid")
_OPEN_PAYMENT = ("initiated", "requires_action", "processing", "unknown")


def _open_balance(session: Session, client_id: UUID) -> list[dict]:
    owes = session.scalar(
        select(Invoice.id).where(Invoice.bill_to_client_id == client_id, Invoice.status.in_(_OPEN_INVOICE)).limit(1)
    ) or session.scalar(
        select(Charge.id)
        .where(Charge.client_id == client_id, Charge.status == "active", Charge.kind != "reversal")
        .where(Charge.applied_minor < Charge.total_minor)
        .limit(1)
    )
    in_flight = session.scalar(
        select(Payment.id).where(Payment.client_id == client_id, Payment.status.in_(_OPEN_PAYMENT)).limit(1)
    )
    if owes or in_flight or service.credit_balance(session, client_id):
        return [{"code": "open-balance", "detail": "Settle the unpaid items and account credit first."}]
    return []


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    for model, column in (
        (Invoice, Invoice.bill_to_client_id),
        (Charge, Charge.client_id),
        (Payment, Payment.client_id),
        (Refund, Refund.client_id),
        (CouponRedemption, CouponRedemption.redeemer_client_id),
        (BillingDocumentDelivery, BillingDocumentDelivery.client_id),
    ):
        session.execute(update(model).where(column == loser_id).values({column.key: survivor_id}))
    # A stored method belongs to the processor's customer. Where the survivor already has one at that
    # processor the merged record's methods cannot follow: they are detached. Otherwise customer and methods move.
    m, customer = PaymentMethod, ProviderCustomer
    has_autopay = methods.autopay_method(session, survivor_id) is not None
    for row in session.scalars(select(customer).where(customer.client_id == loser_id)).all():
        clash = session.scalar(
            select(customer.id).where(
                customer.client_id == survivor_id, customer.provider_account_id == row.provider_account_id
            )
        )
        for method in session.scalars(
            select(m).where(m.client_id == loser_id, m.provider_account_id == row.provider_account_id)
        ).all():
            if clash and method.status != "removed":
                methods.remove_method(session, method.id)
            elif method.is_autopay and has_autopay:
                method.is_autopay = False
            has_autopay = has_autopay or method.is_autopay
            session.flush()
            method.client_id = survivor_id
        if clash:
            session.delete(row)
        else:
            row.client_id = survivor_id
        session.flush()
    session.execute(update(m).where(m.client_id == loser_id).values(client_id=survivor_id, is_autopay=False))


def _export(session: Session, client_id: UUID) -> dict:
    invoices = session.scalars(select(Invoice).where(Invoice.bill_to_client_id == client_id))
    payments = session.scalars(select(Payment).where(Payment.client_id == client_id))
    stored = session.scalars(select(PaymentMethod).where(PaymentMethod.client_id == client_id))
    return {
        "invoices": [
            {"number": r.number, "invoice_on": r.invoice_on.isoformat(), "total_minor": r.total_minor,
             "status": r.status}
            for r in invoices
        ],
        "payments": [
            {"receipt_number": r.receipt_number, "amount_minor": r.amount_minor, "tender_kind": r.tender_kind,
             "status": r.status, "received_at": r.received_at.isoformat() if r.received_at else None}
            for r in payments
        ],
        "payment_methods": [{"kind": r.kind, "brand": r.brand, "last4": r.last4, "status": r.status} for r in stored],
    }  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    """Invoices, items, payments, refunds and the ledger are financial records and stay, without free text.
    Stored payment methods are detached at the processor."""
    removed = 0
    for method in session.scalars(
        select(PaymentMethod).where(PaymentMethod.client_id == client_id, PaymentMethod.status != "removed")
    ).all():
        methods.remove_method(session, method.id)
        removed += 1
    kept = session.execute(
        update(Invoice).where(Invoice.bill_to_client_id == client_id).values(comments=None, organization_name=None)
    ).rowcount
    session.execute(
        update(Charge).where(Charge.client_id == client_id).values(internal_remarks=None, additional_description=None)
    )
    session.execute(update(Payment).where(Payment.client_id == client_id).values(memo=None, external_reference=None))
    session.execute(update(Refund).where(Refund.client_id == client_id).values(comments=None))
    d = BillingDocumentDelivery
    session.execute(update(d).where(d.client_id == client_id).values(to_email=None))
    return {"retained_invoices": kept, "removed_payment_methods": removed, "erased_at": clock.now().isoformat()}


_TABLES = (
    "invoice", "charge", "payment", "refund", "ledger_entry", "coupon_redemption", "provider_customer",
    "payment_method", "billing_notice", "billing_document_delivery",
)  # fmt: skip
clients.merge.register_merge_handler("billing", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler(
    "billing", tables=_TABLES, export=_export, erase=_erase, precheck=_open_balance
)
