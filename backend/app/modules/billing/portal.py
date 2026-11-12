"""The client surface of billing (PAY-18, PAY-06): a signed-in client sees and pays the invoices billed to
the clients they may handle invoices for, and manages their own stored methods.

Ownership is the gate here, not the permission catalogue (security-baseline 17.3): every function resolves
the caller's client ids first, and anything outside them is 404. Those are the clients the identity holds
portal access to plus the household members `can_act_for(..., "invoices")` allows (self, manager, guardian;
never a delegate). Paying a member's invoice spends the payer's own money: the payment is the signed-in
person's, its allocations go to the member's items (billing.service._require_payer allows a relative's).
"""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import clients, platform
from app.modules.billing import catalogue, documents, methods, service
from app.modules.billing.models import Charge, Invoice, Payment, PaymentMethod

_PAYABLE = ("open", "partially_paid")


def _own(session: Session, principal: Principal) -> list[UUID]:
    if principal.kind != "client" or principal.identity_id is None:
        return []
    return [
        client_id
        for client_id in clients.households.actable_client_ids(session, principal.identity_id)
        if clients.households.can_act_for(session, principal.identity_id, client_id, "invoices")
    ]


def _payer(session: Session, principal: Principal, bill_to: UUID) -> UUID:
    """Whose money pays an invoice: the invoice's client when the caller holds its portal access, otherwise
    (a household member's invoice) the caller's own record."""
    direct = clients.service.client_ids_for_identity(session, principal.identity_id)
    return bill_to if bill_to in direct else direct[0]


def _clients(session: Session, principal: Principal) -> list[UUID]:
    own = _own(session, principal)
    if not own:
        raise PermissionDenied("This is for signed-in clients.")
    return own


def _client(session: Session, principal: Principal, client_id: UUID | None) -> UUID:
    own = _clients(session, principal)
    if client_id is not None and client_id not in own:
        raise NotFound()
    return client_id or own[0]


def list_invoices(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Filter `is_payable=true` for what can be paid now."""
    stmt = select(Invoice).where(
        Invoice.bill_to_client_id.in_(_clients(session, principal)), Invoice.status != "voided"
    )
    if str(query.filters.pop("is_payable", "")).lower() == "true":
        stmt = stmt.where(Invoice.status.in_(_PAYABLE), Invoice.balance_minor > 0)
    return paginate(
        session, stmt, query, id_column=Invoice.id,
        sort_fields={"due_on": Invoice.due_on, "number": Invoice.number}, default_sort="due_on",
        filter_fields={"status": Invoice.status, "bill_to_client_id": Invoice.bill_to_client_id},
    )  # fmt: skip


def _invoice(session: Session, principal: Principal, invoice_id: UUID, *, lock: bool = False) -> Invoice:
    invoice = service._get(session, Invoice, invoice_id, lock=lock)
    if invoice.bill_to_client_id not in _own(session, principal) or invoice.status == "voided":
        raise NotFound()
    return invoice


def get_invoice(session: Session, principal: Principal, invoice_id: UUID) -> dict:
    return documents.invoice_document(session, _invoice(session, principal, invoice_id))


def pay(session: Session, principal: Principal, data: dict, idempotency_key: str) -> dict:
    """Pay one or more of the caller's invoices, all billed to the same client: the whole balance, or
    `amount_minor` of it (oldest item first, never more than is owed). Account credit goes first if asked,
    then one card or bank payment for the rest. The payer is the invoice's client, or the signed-in person
    when it is a household member's invoice; a stored method must be the payer's, so a caller never spends
    someone else's method or credit. A payment that needs the payer to authenticate (3-D Secure) comes back
    `requires_action` with a `client_secret`: the browser authenticates, then calls confirm()."""
    invoices = [_invoice(session, principal, invoice_id, lock=True) for invoice_id in sorted(set(data["invoice_ids"]))]
    if len({invoice.bill_to_client_id for invoice in invoices}) != 1:
        raise ValidationFailed("Pay one person's invoices at a time.", pointer="/invoice_ids")
    if any(invoice.status not in _PAYABLE or invoice.balance_minor <= 0 for invoice in invoices):
        raise Conflict("An invoice is not payable.", code="invoice-not-payable")
    payer = _payer(session, principal, invoices[0].bill_to_client_id)
    owed = sum(invoice.balance_minor for invoice in invoices)
    wanted = data.get("amount_minor") or owed
    if wanted > owed:
        raise ValidationFailed(
            "That is more than is owed on these invoices.", pointer="/amount_minor", code="amount-exceeds-balance"
        )
    credit = 0
    if data.get("use_account_credit"):
        for invoice in invoices:
            credit += service.spend_credit(session, payer, invoice_id=invoice.id, limit=wanted - credit)
    allocations = _allocations(session, invoices, wanted - credit)
    payment = None
    if allocations:
        method_id, tender = data.get("payment_method_id"), "card"
        if method_id is not None:
            method = session.get(PaymentMethod, method_id)
            if method is None or method.client_id != payer or method.status != "active":
                raise ValidationFailed(
                    "Choose one of your own payment methods.", pointer="/payment_method_id",
                    code="payment-method-not-usable",
                )  # fmt: skip
            tender = "card" if method.kind == "card" else "bank_debit"
        elif not data.get("method_token"):
            raise ValidationFailed("Choose how to pay.", pointer="/payment_method_id")
        payment = service.take_payment(
            session, client_id=payer, location_id=invoices[0].location_id,
            amount_minor=sum(amount for _, amount in allocations), tender_kind=tender, payment_method_id=method_id,
            method_token=data.get("method_token"), origin="portal", allocations=allocations,
            idempotency_key=f"portal:{principal.identity_id}:{idempotency_key}",
        )  # fmt: skip
        if data.get("set_autopay") and payment.status in ("succeeded", "processing"):
            for invoice in invoices:
                invoice.is_autopay = True
    session.flush()
    return {
        "credit_applied_minor": credit, "payment": service._payment_detail(session, payment) if payment else None,
        "client_secret": getattr(payment, "client_secret", None),
    }  # fmt: skip


def _allocations(session: Session, invoices: list[Invoice], amount: int) -> list[tuple[UUID, int]]:
    """`amount` over the invoices' open items, oldest first."""
    rows = []
    for charge in session.scalars(
        select(Charge)
        .where(
            Charge.invoice_id.in_([invoice.id for invoice in invoices]),
            Charge.status == "active",
            Charge.applied_minor < Charge.total_minor,
        )  # fmt: skip
        .order_by(Charge.bill_on, Charge.id)
    ):
        take = min(amount - sum(part for _, part in rows), charge.total_minor - charge.applied_minor)
        if take > 0:
            rows.append((charge.id, take))
    return rows


def _payment(session: Session, principal: Principal, payment_id: UUID, *, lock: bool = False) -> Payment:
    payment = service._get(session, Payment, payment_id, lock=lock)
    if payment.client_id not in _own(session, principal):
        raise NotFound()
    return payment


def confirm(session: Session, principal: Principal, payment_id: UUID, data: dict) -> dict:
    """Back from the processor's authentication (3-D Secure): re-read the payment and, once it went through,
    apply what it has left to the invoices it was for (the caller's own, oldest item first). Safe to repeat;
    a webhook that settled the payment first leaves the money on account until this applies it."""
    payment = _payment(session, principal, payment_id, lock=True)
    payment = service.confirm_payment(session, payment.id)
    if payment.status in ("succeeded", "processing"):
        for invoice_id in sorted(set(data["invoice_ids"])):
            invoice = _invoice(session, principal, invoice_id)
            if invoice.status in _PAYABLE and invoice.balance_minor > 0:
                service.allocate(session, payment.id, invoice_id=invoice.id)
    return {"credit_applied_minor": 0, "payment": service._payment_detail(session, payment), "client_secret": None}


def receipt(session: Session, principal: Principal, payment_id: UUID) -> dict:
    return documents.receipt(session, _payment(session, principal, payment_id))


def receipt_pdf(session: Session, principal: Principal, payment_id: UUID) -> tuple[str, bytes]:
    payment = _payment(session, principal, payment_id)
    return f"receipt-{payment.receipt_number}.pdf", documents.receipt_pdf(session, payment)


def quote_coupon(session: Session, principal: Principal, data: dict) -> dict:
    """Would this code work online for this sale (SSP-11)? Validation only: the sale's checkout redeems it.
    `client_id` is who the sale is for (a household member the caller may buy for); default the caller."""
    _clients(session, principal)
    own = clients.households.actable_client_ids(session, principal.identity_id)
    client_id = data.get("client_id") or own[0]
    if client_id not in own:
        raise NotFound()
    quote = catalogue.quote_coupon(
        session, data["code"], subtotal_minor=data["subtotal_minor"], redeemer_client_id=client_id, channel="portal"
    )
    return {key: quote[key] for key in ("is_valid", "invalid_reason", "discount_minor")}


def list_payments(session: Session, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, select(Payment).where(Payment.client_id.in_(_clients(session, principal))), query,
        id_column=Payment.id, sort_fields={"received_at": Payment.received_at}, default_sort="-received_at",
        filter_fields={"status": Payment.status},
    )  # fmt: skip


def billing_summary(session: Session, principal: Principal, client_id: UUID | None) -> dict:
    return documents.billing_summary(session, _client(session, principal, client_id))


def list_methods(session: Session, principal: Principal) -> list[PaymentMethod]:
    return methods.methods_of(session, _client(session, principal, None))


def create_setup(session: Session, principal: Principal, kinds: tuple[str, ...]) -> dict:
    return methods.create_setup(session, _client(session, principal, None), kinds)


def attach_method(session: Session, principal: Principal, data: dict) -> PaymentMethod:
    return methods.attach_method(
        session, _client(session, principal, None), data["method_token"], is_autopay=data.get("is_autopay")
    )


def _method(session: Session, principal: Principal, method_id: UUID) -> PaymentMethod:
    method = service._get(session, PaymentMethod, method_id)
    if method.client_id not in _own(session, principal) or method.status == "removed":
        raise NotFound()
    return method


def update_method(session: Session, principal: Principal, method_id: UUID, data: dict) -> PaymentMethod:
    return methods.set_autopay(session, _method(session, principal, method_id).id, data["is_autopay"])


def remove_method(session: Session, principal: Principal, method_id: UUID) -> None:
    """A client may replace but not remove their last usable method while an autopay invoice is still open."""
    method = _method(session, principal, method_id)
    others = [m for m in methods.methods_of(session, method.client_id) if m.id != method.id and m.status == "active"]
    owes = session.scalar(
        select(Invoice.id)
        .where(
            Invoice.bill_to_client_id == method.client_id,
            Invoice.is_autopay,
            Invoice.balance_minor > 0,
            Invoice.status.in_(_PAYABLE),
        )
        .limit(1)  # fmt: skip
    )
    if not others and owes is not None:
        raise Conflict(
            "Add another payment method before removing this one: an autopay invoice is open.",
            code="payment-method-required",
        )
    methods.remove_method(session, method.id)


def get_invoice_pdf(session: Session, principal: Principal, invoice_id: UUID) -> tuple[str, bytes]:
    document = documents.invoice_document(session, _invoice(session, principal, invoice_id))
    return f"invoice-{document['number']}.pdf", documents.invoice_pdf(document, session)


def statement(
    session: Session, principal: Principal, client_id: UUID | None, from_on: date | None, to_on: date | None
) -> dict:
    """The caller's own statement (BIL-11). Default period: the 30 days up to today at their home location."""
    payer = _client(session, principal, client_id)
    to_on = to_on or platform.service.location_today(session, clients.service.get(session, payer).home_location_id)
    return documents.statement(session, payer, from_on or to_on - timedelta(days=30), to_on)


def statement_pdf(
    session: Session, principal: Principal, client_id: UUID | None, from_on: date | None, to_on: date | None
) -> tuple[str, bytes]:
    document = statement(session, principal, client_id, from_on, to_on)
    return documents.statement_name(document), documents.statement_pdf(session, document)
