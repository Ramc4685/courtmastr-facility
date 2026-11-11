"""The client surface of billing (PAY-18, PAY-06): a signed-in client sees and pays the invoices billed to
the clients their identity holds portal access to, and manages their own stored methods.

Ownership is the gate here, not the permission catalogue (security-baseline 17.3): every function resolves
the caller's own client ids first, and anything outside them is 404. `can_act_for` across a household arrives
with build module 4; until then "own" means direct portal access.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import clients
from app.modules.billing import documents, methods, service
from app.modules.billing.models import Charge, Invoice, Payment, PaymentMethod

_PAYABLE = ("open", "partially_paid")


def _own(session: Session, principal: Principal) -> list[UUID]:
    if principal.kind != "client" or principal.identity_id is None:
        return []
    return list(clients.service.client_ids_for_identity(session, principal.identity_id))


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
    """Pay the full balance of one or more of the caller's invoices, all billed to the same client, with
    account credit first if asked and then one card or bank payment. The payer is always that client and a
    stored method must be theirs: a caller never spends someone else's method or credit."""
    own = _clients(session, principal)
    invoices = [_invoice(session, principal, invoice_id, lock=True) for invoice_id in sorted(set(data["invoice_ids"]))]
    payer = invoices[0].bill_to_client_id
    if any(invoice.bill_to_client_id != payer for invoice in invoices) or payer not in own:
        raise ValidationFailed("Pay one person's invoices at a time.", pointer="/invoice_ids")
    if any(invoice.status not in _PAYABLE or invoice.balance_minor <= 0 for invoice in invoices):
        raise Conflict("An invoice is not payable.", code="invoice-not-payable")
    credit = 0
    if data.get("use_account_credit"):
        for invoice in invoices:
            credit += service.spend_credit(session, payer, invoice_id=invoice.id)
    open_charges = session.scalars(
        select(Charge)
        .where(
            Charge.invoice_id.in_([invoice.id for invoice in invoices]),
            Charge.status == "active",
            Charge.applied_minor < Charge.total_minor,
        )  # fmt: skip
        .order_by(Charge.bill_on, Charge.id)
    ).all()
    allocations = [(charge.id, charge.total_minor - charge.applied_minor) for charge in open_charges]
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
