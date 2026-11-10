"""billing service (kernel): charges, invoices, payments, allocations, refunds and the immutable ledger.

Two kinds of function (ADR 0009 section 9). Staff commands and queries take a principal and authorize it.
The functions under "internal" are the cross-context interface (post_charge, create_invoice_for_charges,
take_payment, confirm_payment, allocate, refund, reverse): they do not consult the permission catalogue,
because the calling use case already authorized the user's intent (Front Desk booking a rental creates a
charge without holding billing.charge.create). Audit attribution comes from the session's actor either way.

Money rules (ADR 0003): a charge's money never changes after insert; every undo is a negating row; nothing
reaches the ledger before a payment has settled; every posting is one balanced ledger_transaction whose
unique (kind, source) key makes a replay a no-op.
"""

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import clients, platform
from app.modules.billing.domain.money import net_amount, tax_amount
from app.modules.billing.events import (
    ChargeCreated,
    ChargeReversed,
    InvoiceIssued,
    InvoicePaid,
    PaymentFailed,
    PaymentProcessing,
    PaymentRefunded,
    PaymentSucceeded,
)
from app.modules.billing.models import (
    Charge,
    ChargeTax,
    Invoice,
    LedgerEntry,
    LedgerTransaction,
    Payment,
    PaymentAllocation,
    ProviderAccount,
    Refund,
    RevenueCategory,
    RevenueCategoryTax,
    Tax,
    TaxRate,
    TenderType,
)
from app.ports import payment_provider
from app.ports.payment_provider import PaymentState

# kind -> (default label, cannot be hidden). Processed kinds need an active provider account.
_TENDERS = {
    "card": ("Card", False), "bank_debit": ("Bank debit", False), "cash": ("Cash", False),
    "cheque": ("Cheque", True), "bank_transfer": ("Bank transfer", True), "gift_card": ("Gift card", True),
    "external": ("External", True), "other": ("Other", True),
}  # fmt: skip
_PROCESSED = ("card", "bank_debit")
# payment.status transitions (ADR 0003 section 7). Anything else is ignored, so replays and late or
# out-of-order provider answers are harmless.
_TRANSITIONS = {
    "initiated": {"succeeded", "processing", "requires_action", "failed", "unknown", "cancelled"},
    "processing": {"succeeded", "failed"},
    "requires_action": {"succeeded", "processing", "failed", "cancelled"},
    "unknown": {"succeeded", "processing", "requires_action", "failed", "cancelled"},
}
Allocations = Sequence[tuple[UUID, int]]  # (charge_id, amount_minor)


# === staff commands and queries ============================================================================


def list_revenue_categories(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Configuration read: any signed-in staff user (rbac-matrix section 1)."""
    return paginate(
        session, select(RevenueCategory), query, id_column=RevenueCategory.id,
        sort_fields={"code": RevenueCategory.code, "label": RevenueCategory.label}, default_sort="code",
        filter_fields={"is_active": RevenueCategory.is_active}, search=(RevenueCategory.code, RevenueCategory.label),
    )  # fmt: skip


def create_charge(session: Session, principal: Principal, data: dict) -> Charge:
    """A manual billing item (BIL-01). Its origin is itself, so two manual items never collide."""
    authorize(principal, "billing.charge.create", location_id=data["location_id"])
    _location_in_scope(session, principal, data["location_id"])
    return post_charge(session, **data, source_context="billing", source_type="manual", source_id=new_id())


def list_charges(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "billing.charge.read")
    return paginate(
        session, select(Charge), query, id_column=Charge.id,
        sort_fields={"bill_on": Charge.bill_on, "created_at": Charge.created_at}, default_sort="-bill_on",
        filter_fields={
            "client_id": Charge.client_id, "invoice_id": Charge.invoice_id, "location_id": Charge.location_id,
            "status": Charge.status, "kind": Charge.kind, "source_id": Charge.source_id,
        },
    )  # fmt: skip


def reverse_charge(session: Session, principal: Principal, charge_id: UUID, data: dict) -> Charge:
    charge = _get(session, Charge, charge_id)
    authorize(principal, "billing.charge.reverse", location_id=charge.location_id)
    return reverse(session, charge_id, **data)


def create_invoice(session: Session, principal: Principal, data: dict) -> dict:
    for charge_id in data["charge_ids"]:
        charge = _get(session, Charge, charge_id, pointer="/charge_ids")
        authorize(principal, "billing.invoice.create", location_id=charge.location_id)
    invoice = create_invoice_for_charges(
        session, data["charge_ids"], bill_to_client_id=data.get("bill_to_client_id"), due_on=data.get("due_on")
    )
    return _invoice_detail(session, invoice)


def list_invoices(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "billing.invoice.read")
    return paginate(
        session, select(Invoice), query, id_column=Invoice.id,
        sort_fields={"invoice_on": Invoice.invoice_on, "due_on": Invoice.due_on, "number": Invoice.number},
        default_sort="-number",
        filter_fields={
            "bill_to_client_id": Invoice.bill_to_client_id, "status": Invoice.status,
            "location_id": Invoice.location_id,
        },
    )  # fmt: skip


def get_invoice(session: Session, principal: Principal, invoice_id: UUID) -> dict:
    authorize(principal, "billing.invoice.read")
    return _invoice_detail(session, _get(session, Invoice, invoice_id))


def take_payment_at_desk(session: Session, principal: Principal, data: dict, idempotency_key: str | None) -> dict:
    """Staff take-payment (PAY-01). Client-following key: holding it at any location suffices."""
    authorize(principal, "billing.payment.take")
    _location_in_scope(session, principal, data["location_id"])
    data = dict(data)
    allocations = [(row["charge_id"], row["amount_minor"]) for row in data.pop("allocations", None) or []]
    payment = take_payment(session, **data, allocations=allocations or None, idempotency_key=idempotency_key)
    return _payment_detail(session, payment)


def list_payments(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "billing.payment.read")
    return paginate(
        session, select(Payment), query, id_column=Payment.id,
        sort_fields={"received_at": Payment.received_at}, default_sort="-received_at",
        filter_fields={"client_id": Payment.client_id, "status": Payment.status, "location_id": Payment.location_id},
    )  # fmt: skip


def get_payment(session: Session, principal: Principal, payment_id: UUID) -> dict:
    authorize(principal, "billing.payment.read")
    return _payment_detail(session, _get(session, Payment, payment_id))


def confirm_payment_at_desk(session: Session, principal: Principal, payment_id: UUID) -> dict:
    authorize(principal, "billing.payment.take")
    _get(session, Payment, payment_id)
    return _payment_detail(session, confirm_payment(session, payment_id))


def allocate_payment(session: Session, principal: Principal, payment_id: UUID, data: dict) -> dict:
    payment = _get(session, Payment, payment_id)
    authorize(principal, "billing.payment.reallocate", location_id=payment.location_id)
    rows = [(row["charge_id"], row["amount_minor"]) for row in data.get("allocations") or []]
    payment = allocate(session, payment_id, invoice_id=data.get("invoice_id"), allocations=rows or None)
    return _payment_detail(session, payment)


def create_refund(
    session: Session, principal: Principal, payment_id: UUID, data: dict, idempotency_key: str | None
) -> Refund:
    payment = _get(session, Payment, payment_id)
    authorize(principal, "billing.refund.create", location_id=payment.location_id)
    return refund(session, payment_id, **data, idempotency_key=idempotency_key)


def list_ledger_entries(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Raw double-entry rows. Location-scoped: a limited user sees only their locations' entries."""
    authorize(principal, "billing.ledger.read")
    stmt = select(LedgerEntry)
    if principal.kind != "system" and principal.location_ids is not None:
        stmt = stmt.where(LedgerEntry.location_id.in_(principal.location_ids))
    return paginate(
        session, stmt, query, id_column=LedgerEntry.id,
        sort_fields={"effective_on": LedgerEntry.effective_on}, default_sort="effective_on",
        filter_fields={
            "account": LedgerEntry.account, "client_id": LedgerEntry.client_id, "charge_id": LedgerEntry.charge_id,
            "payment_id": LedgerEntry.payment_id, "location_id": LedgerEntry.location_id,
            "effective_on": LedgerEntry.effective_on,
        },
    )  # fmt: skip


# === internal: the cross-context interface =================================================================


def ensure_defaults(session: Session) -> None:
    """The rows every tenant has: the two system revenue categories and one tender per built-in kind.
    Idempotent and safe under concurrency; called by seeds and lazily by the functions that need a row."""
    tenant_id = session.info["tenant_id"]
    for key, label in (("uncategorised", "Uncategorised"), ("surcharge", "Surcharge")):
        session.execute(
            pg_insert(RevenueCategory)
            .values(id=new_id(), tenant_id=tenant_id, code=key.upper(), label=label, system_key=key)
            .on_conflict_do_nothing()
        )
    for order, (kind, (label, optional)) in enumerate(_TENDERS.items()):
        session.execute(
            pg_insert(TenderType)
            .values(
                id=new_id(),
                tenant_id=tenant_id,
                kind=kind,
                label=label,
                is_processed=kind in _PROCESSED,
                is_optional=optional,
                sort_order=order,
            )  # fmt: skip
            .on_conflict_do_nothing()
        )


def default_revenue_category(session: Session) -> RevenueCategory:
    """The seeded `uncategorised` row: what a charge is classified as when its seller names no category."""
    stmt = select(RevenueCategory).where(RevenueCategory.system_key == "uncategorised")
    category = session.execute(stmt).scalar_one_or_none()
    if category is None:
        ensure_defaults(session)
        category = session.execute(stmt).scalar_one()
    return category


def create_revenue_category(
    session: Session, *, code: str, label: str, tax_ids: Iterable[UUID] = (), parent_id: UUID | None = None
) -> RevenueCategory:
    """Create a category and map its default taxes (BIL-13). Idempotent by code: an existing code is returned
    unchanged. The management endpoints arrive with build module 8; seeds and selling contexts use this."""
    existing = session.execute(select(RevenueCategory).where(RevenueCategory.code == code)).scalar_one_or_none()
    if existing is not None:
        return existing
    category = RevenueCategory(code=code, label=label, parent_id=parent_id)
    session.add(category)
    session.flush()
    session.add_all(RevenueCategoryTax(revenue_category_id=category.id, tax_id=tax_id) for tax_id in tax_ids)
    audit.record(session, "billing.revenue_category.manage", category)
    session.flush()
    return category


def create_tax(session: Session, *, code: str, label: str, rate: Decimal, effective_from_on: date) -> Tax:
    """Create a tax with its first dated rate (BIL-12). Idempotent by code."""
    existing = session.execute(select(Tax).where(Tax.code == code)).scalar_one_or_none()
    if existing is not None:
        return existing
    tax = Tax(code=code, label=label)
    session.add(tax)
    session.flush()
    session.add(TaxRate(tax_id=tax.id, rate=rate, effective_from_on=effective_from_on))
    audit.record(session, "billing.tax.manage", tax, changes={"rate": [None, str(rate)]})
    session.flush()
    return tax


def post_charge(
    session: Session,
    *,
    client_id: UUID | None,
    location_id: UUID,
    description: str,
    unit_price_minor: int,
    source_context: str,
    source_type: str,
    source_id: UUID,
    source_line_no: int = 0,
    quantity: Decimal | int = 1,
    discount_minor: int = 0,
    revenue_category_id: UUID | None = None,
    revenue_on: date | None = None,
    exclude_tax_ids: Iterable[UUID] = (),
    additional_description: str | None = None,
    internal_remarks: str | None = None,
    service_starts_on: date | None = None,
    service_ends_on: date | None = None,
) -> Charge:
    """Create a receivable and post it to the ledger (debit receivable; credit revenue and each tax).

    Idempotent by origin: a second call with the same (source_context, source_type, source_id,
    source_line_no) returns the charge the first call made, whatever its status, so a retried job never bills
    twice. To bill the same thing again after a reversal, use the next source_line_no.

    Amounts: net = round(quantity * unit_price) - discount, half-up once at the line; each tax mapped to the
    revenue category (minus exclude_tax_ids) is computed on the net at the rate in force on revenue_on.
    Dates default to today at the location. A zero-total charge is recorded but posts nothing.
    """
    origin = (
        Charge.source_context == source_context, Charge.source_type == source_type, Charge.source_id == source_id,
        Charge.source_line_no == source_line_no, Charge.kind == "standard",
    )  # fmt: skip
    existing = session.execute(select(Charge).where(*origin)).scalar_one_or_none()
    if existing is not None:
        return existing

    quantity = Decimal(quantity)
    gross = net_amount(quantity, unit_price_minor)
    if quantity <= 0 or unit_price_minor < 0:
        raise ValidationFailed(
            "Quantity must be positive and the price cannot be negative.", pointer="/unit_price_minor"
        )
    if not 0 <= discount_minor <= gross:
        raise ValidationFailed("The discount cannot exceed the line amount.", pointer="/discount_minor")
    if client_id is not None:
        clients.service.require_active(session, client_id)
    bill_on = platform.service.location_today(session, location_id)
    revenue_on = revenue_on or bill_on
    category = (
        _get(session, RevenueCategory, revenue_category_id, pointer="/revenue_category_id")
        if revenue_category_id
        else default_revenue_category(session)
    )

    net = gross - discount_minor
    excluded = set(exclude_tax_ids)
    taxes = [
        ChargeTax(tax_id=tax_id, rate=rate, is_excluded=tax_id in excluded,
                  amount_minor=0 if tax_id in excluded else tax_amount(net, rate))
        for tax_id, rate in _taxes_in_force(session, category.id, revenue_on)
    ]  # fmt: skip
    tax_total = sum(row.amount_minor for row in taxes)
    charge = Charge(
        client_id=client_id, location_id=location_id, source_context=source_context, source_type=source_type,
        source_id=source_id, source_line_no=source_line_no, description=description,
        additional_description=additional_description, internal_remarks=internal_remarks, quantity=quantity,
        unit_price_minor=unit_price_minor, discount_minor=discount_minor, net_minor=net, tax_minor=tax_total,
        total_minor=net + tax_total, bill_on=bill_on, revenue_on=revenue_on, service_starts_on=service_starts_on,
        service_ends_on=service_ends_on, revenue_category_id=category.id, created_by_staff_user_id=_staff_id(session),
    )  # fmt: skip
    session.add(charge)
    session.flush()
    for row in taxes:
        row.charge_id = charge.id
    session.add_all(taxes)
    _post_charge_to_ledger(session, charge, taxes)
    audit.record(
        session, "billing.charge.create", charge, location_id=location_id,
        changes={"total_minor": [None, charge.total_minor], "source_type": [None, source_type]},
    )  # fmt: skip
    events.publish(session, ChargeCreated(**_charge_ref(charge)), charge.id)
    session.flush()
    return charge


def reverse(session: Session, charge_id: UUID, *, reason: str, revenue_on: date | None = None) -> Charge:
    """Reverse a charge (BIL-07) and return the new negating charge.

    The original becomes `reversed`; its live allocations are released, so money already applied goes back to
    the paying payments as account credit, dated today (refunding it is a separate refund() call). The
    negating charge copies the original tax snapshot with the signs flipped and posts at revenue_on, which
    defaults to the original revenue date. A charge is reversed at most once.
    """
    charge = _lock(session, Charge, charge_id)
    if charge.status != "active" or charge.kind == "reversal":
        raise Conflict("This item was already reversed or voided.", code="charge-not-reversible")
    if not reason.strip():
        raise ValidationFailed("A reason is required.", pointer="/reason")
    today = platform.service.location_today(session, charge.location_id)
    for allocation in session.scalars(_live_allocations(PaymentAllocation.charge_id == charge.id)):
        _release(session, allocation, "charge_reversed")
    charge.status, charge.reversed_at = "reversed", clock.now()
    reversal = Charge(
        client_id=charge.client_id, location_id=charge.location_id, invoice_id=charge.invoice_id, kind="reversal",
        source_context=charge.source_context, source_type=charge.source_type, source_id=charge.source_id,
        source_line_no=charge.source_line_no, description=charge.description, quantity=charge.quantity,
        unit_price_minor=-charge.unit_price_minor, discount_minor=-charge.discount_minor,
        net_minor=-charge.net_minor, tax_minor=-charge.tax_minor, total_minor=-charge.total_minor, bill_on=today,
        revenue_on=revenue_on or charge.revenue_on, revenue_category_id=charge.revenue_category_id,
        reverses_charge_id=charge.id, reason=reason, created_by_staff_user_id=_staff_id(session),
    )  # fmt: skip
    session.add(reversal)
    session.flush()
    taxes = [
        ChargeTax(charge_id=reversal.id, tax_id=row.tax_id, rate=row.rate, amount_minor=-row.amount_minor,
                  is_excluded=row.is_excluded)
        for row in session.scalars(select(ChargeTax).where(ChargeTax.charge_id == charge.id))
    ]  # fmt: skip
    session.add_all(taxes)
    _post_charge_to_ledger(session, reversal, taxes)
    audit.record(
        session, "billing.charge.reverse", charge, location_id=charge.location_id, reason=reason,
        changes={"status": ["active", "reversed"]},
    )  # fmt: skip
    events.publish(session, ChargeReversed(**_charge_ref(charge), reversal_charge_id=reversal.id), charge.id)
    session.flush()
    if charge.invoice_id:
        _refresh_invoice(session, charge.invoice_id)
    return reversal


def create_invoice_for_charges(
    session: Session,
    charge_ids: Sequence[UUID],
    *,
    bill_to_client_id: UUID | None = None,
    due_on: date | None = None,
    origin: str = "staff",
) -> Invoice:
    """Group uninvoiced, active charges of one location under a new numbered invoice for one payer.

    The payer defaults to the charges' client when they all share one; pass bill_to_client_id when a parent
    pays for several people. invoice_on is today at the location; due_on defaults to it. An invoice has no
    money of its own: voiding or regrouping never posts to the ledger.
    """
    if not charge_ids:
        raise ValidationFailed("Select at least one item.", pointer="/charge_ids")
    charges = [_lock(session, Charge, charge_id, pointer="/charge_ids") for charge_id in sorted(set(charge_ids))]
    if any(charge.status != "active" or charge.invoice_id is not None for charge in charges):
        raise Conflict("An item is already invoiced, reversed or voided.", code="charge-not-invoiceable")
    if len({charge.location_id for charge in charges}) > 1:
        raise ValidationFailed("All items of an invoice belong to one location.", pointer="/charge_ids")
    payers = {charge.client_id for charge in charges}
    if bill_to_client_id is None:
        if len(payers) > 1:
            raise ValidationFailed("Say who pays: the items belong to several clients.", pointer="/bill_to_client_id")
        bill_to_client_id = payers.pop()
    elif origin != "pos":
        clients.service.require_active(session, bill_to_client_id, pointer="/bill_to_client_id")
    location_id = charges[0].location_id
    today = platform.service.location_today(session, location_id)
    if due_on is not None and due_on < today:
        raise ValidationFailed("The due date cannot be before the invoice date.", pointer="/due_on")
    invoice = Invoice(
        number=platform.service.next_number(session, "invoice"), bill_to_client_id=bill_to_client_id,
        location_id=location_id, origin=origin, invoice_on=today, due_on=due_on or today,
        created_by_staff_user_id=_staff_id(session),
    )  # fmt: skip
    session.add(invoice)
    session.flush()
    for charge in charges:
        charge.invoice_id = invoice.id
    session.flush()
    audit.record(
        session, "billing.invoice.create", invoice, location_id=location_id,
        changes={"number": [None, invoice.number], "charge_count": [None, len(charges)]},
    )  # fmt: skip
    events.publish(session, InvoiceIssued(invoice_id=invoice.id, bill_to_client_id=bill_to_client_id), invoice.id)
    _refresh_invoice(session, invoice.id)
    return invoice


def take_payment(
    session: Session,
    *,
    client_id: UUID | None,
    location_id: UUID,
    amount_minor: int,
    tender_kind: str,
    idempotency_key: str | None = None,
    method_token: str | None = None,
    origin: str = "staff",
    invoice_id: UUID | None = None,
    allocations: Allocations | None = None,
    external_reference: str | None = None,
    memo: str | None = None,
) -> Payment:
    """Receive money from one payer in one tender, then allocate it (see allocate()).

    Record-only tenders (cash, cheque, bank transfer...) are `succeeded` at once. Processed tenders (card,
    bank_debit) call the payment provider and need `method_token` (an opaque provider reference, never card
    data) and `idempotency_key`: the same key always resolves to the same provider payment and the same
    payment row, so a retry can never charge twice.

    The result is a state, not an exception: check `payment.status`. `succeeded` is settled and in the
    ledger. `processing` (bank debit) holds its allocations as provisional until confirm_payment() settles
    it. `failed` (declined) and `unknown` (provider timeout: NOT a decline, resolved by confirm_payment())
    allocate nothing. Money left unallocated is the payer's account credit.
    """
    if amount_minor <= 0:
        raise ValidationFailed("The amount must be greater than zero.", pointer="/amount_minor")
    tender = _tender(session, tender_kind)
    if not tender.is_enabled:
        raise ValidationFailed("This payment method is not offered.", pointer="/tender_kind")
    if client_id is not None:
        try:
            clients.service.get(session, client_id)  # a disabled client can still pay what they owe
        except NotFound:
            raise ValidationFailed("Unknown client.", pointer="/client_id") from None
    try:
        platform.service.location_today(session, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    tenant = platform.service.get_tenant(session)
    payment = Payment(
        client_id=client_id, location_id=location_id, tender_type_id=tender.id, tender_kind=tender.kind,
        amount_minor=amount_minor, currency=tenant.currency, origin=origin, external_reference=external_reference,
        memo=memo, received_at=clock.now(), taken_by_staff_user_id=_staff_id(session),
    )  # fmt: skip
    if tender.is_processed:
        if not method_token or not idempotency_key:
            raise ValidationFailed(
                "A processed payment needs a payment method and an Idempotency-Key.", pointer="/method_token"
            )
        account = _provider_account(session)
        state = payment_provider.get(account.provider).create_payment(
            account_ref=account.provider_account_ref, amount_minor=amount_minor, currency=tenant.currency,
            method_token=method_token, idempotency_key=f"{tenant.id}:payment:{idempotency_key}",
        )  # fmt: skip
        replayed = session.execute(
            select(Payment).where(
                Payment.provider_account_id == account.id, Payment.provider_payment_ref == state.provider_payment_ref
            )
        ).scalar_one_or_none()
        if replayed is not None:
            return replayed
        payment.provider_account_id, payment.provider_payment_ref = account.id, state.provider_payment_ref
    else:
        state = PaymentState(provider_payment_ref="", outcome="succeeded")
    payment.receipt_number = platform.service.next_number(session, "receipt")
    session.add(payment)
    session.flush()
    _apply_state(session, payment, state)
    if payment.status in ("succeeded", "processing") and (invoice_id or allocations):
        _allocate(session, payment, invoice_id, allocations)
    audit.record(
        session, "billing.payment.take", payment, location_id=location_id,
        changes={
            "amount_minor": [None, amount_minor], "tender_kind": [None, tender.kind], "status": [None, payment.status]
        },
    )  # fmt: skip
    return payment


def confirm_payment(session: Session, payment_id: UUID) -> Payment:
    """Re-read the provider and apply its current state: settles a `processing` bank debit, resolves an
    `unknown`. Safe to call any number of times and from any path (request, webhook actor, sweep)."""
    payment = _lock(session, Payment, payment_id)
    if payment.provider_account_id is None or payment.status not in _TRANSITIONS:
        return payment
    account = session.get(ProviderAccount, payment.provider_account_id)
    state = payment_provider.get(account.provider).get_payment(
        account_ref=account.provider_account_ref, provider_payment_ref=payment.provider_payment_ref
    )
    was = payment.status
    _apply_state(session, payment, state)
    if payment.status != was:
        audit.record(
            session, "billing.payment.confirm", payment, location_id=payment.location_id,
            changes={"status": [was, payment.status]},
        )  # fmt: skip
    return payment


def allocate(
    session: Session, payment_id: UUID, *, invoice_id: UUID | None = None, allocations: Allocations | None = None
) -> Payment:
    """Apply a payment's remainder to charges (PAY-01 allocates per item, not per invoice).

    Give explicit `allocations` [(charge_id, amount_minor)], or an `invoice_id` to cover that invoice's open
    charges oldest first, or neither to cover the payer's open charges oldest first (spending account credit).
    Automatic allocation stops when the money runs out; explicit amounts that exceed the payment's remainder
    or a charge's balance are refused. Allocations of a settled payment are `applied` and posted; those of a
    `processing` payment are `provisional` and post only when it settles.
    """
    payment = _lock(session, Payment, payment_id)
    allocated = _allocate(session, payment, invoice_id, allocations)
    if allocated:
        audit.record(
            session, "billing.payment.reallocate", payment, location_id=payment.location_id,
            changes={"allocated_minor": [None, allocated]},
        )  # fmt: skip
    return payment


def _allocate(session: Session, payment: Payment, invoice_id: UUID | None, allocations: Allocations | None) -> int:
    if payment.status not in ("succeeded", "processing"):
        raise Conflict("Only a settled or pending payment can be applied.", code="payment-not-allocatable")
    available = payment.amount_minor - payment.refunded_minor - _live_total(session, payment.id)
    if allocations is None:
        open_charges = select(Charge).where(Charge.status == "active", Charge.applied_minor < Charge.total_minor)
        if invoice_id is not None:
            invoice = _get(session, Invoice, invoice_id, pointer="/invoice_id")
            open_charges = open_charges.where(Charge.invoice_id == invoice.id)
        else:
            open_charges = open_charges.where(Charge.client_id == payment.client_id)
        plan = []
        for charge in session.scalars(open_charges.order_by(Charge.bill_on, Charge.id).with_for_update()):
            amount = min(available - sum(a for _, a in plan), charge.total_minor - charge.applied_minor)
            if amount > 0:
                plan.append((charge, amount))
    else:
        if len({charge_id for charge_id, _ in allocations}) != len(allocations):
            raise ValidationFailed("List each item once.", pointer="/allocations")
        # Lock in id order so two concurrent allocations cannot deadlock.
        plan = [
            (_lock(session, Charge, charge_id, pointer="/allocations"), amount)
            for charge_id, amount in sorted(allocations, key=lambda row: row[0])
        ]
        for charge, amount in plan:
            if amount <= 0 or charge.status != "active" or amount > charge.total_minor - charge.applied_minor:
                raise ValidationFailed(
                    "An amount exceeds what is still owed on its item.", pointer="/allocations",
                    code="allocation-exceeds-balance",
                )  # fmt: skip
        if sum(amount for _, amount in plan) > available:
            raise ValidationFailed(
                "The amounts exceed what is left of this payment.", pointer="/allocations",
                code="allocation-exceeds-payment",
            )  # fmt: skip
    settled = payment.status == "succeeded"
    for charge, amount in plan:
        allocation = PaymentAllocation(
            payment_id=payment.id, charge_id=charge.id, amount_minor=amount,
            status="applied" if settled else "provisional", applied_at=clock.now() if settled else None,
            created_by_staff_user_id=_staff_id(session),
        )  # fmt: skip
        session.add(allocation)
        charge.applied_minor += amount
        session.flush()
        if settled:
            _post_allocation(session, allocation, payment, charge, released=False)
    _settle_projections(session, payment, {charge.invoice_id for charge, _ in plan})
    return sum(amount for _, amount in plan)


def refund(
    session: Session,
    payment_id: UUID,
    *,
    amount_minor: int,
    reason: str,
    idempotency_key: str | None = None,
    method: str | None = None,
    comments: str | None = None,
) -> Refund:
    """Return part or all of a settled payment's UNAPPLIED remainder (PAY-05). To refund money that is
    applied to a charge, reverse() the charge first: that releases the money to credit.

    `method` defaults to `original` for processed tenders (the provider returns it to the card or bank
    account; needs idempotency_key) and to `external` for record-only tenders (staff hand the money back).
    Check `refund.status`: `succeeded` is posted to the ledger; `failed` moved no money.
    """
    payment = _lock(session, Payment, payment_id)
    processed = payment.provider_account_id is not None
    method = method or ("original" if processed else "external")
    if payment.status != "succeeded":
        raise Conflict("Only a settled payment can be refunded.", code="payment-not-refundable")
    if method == "original" and not processed:
        raise ValidationFailed("This payment was not processed by us; refund it externally.", pointer="/method")
    if not reason.strip():
        raise ValidationFailed("A reason is required.", pointer="/reason")
    today = platform.service.location_today(session, payment.location_id)
    row = Refund(
        payment_id=payment.id, client_id=payment.client_id, location_id=payment.location_id,
        amount_minor=amount_minor, currency=payment.currency, method=method, status="succeeded", refund_on=today,
        reason=reason, comments=comments, issued_by_staff_user_id=_staff_id(session),
    )  # fmt: skip
    provider = account = provider_key = None
    if method == "original":
        if not idempotency_key:
            raise ValidationFailed("A processed refund needs an Idempotency-Key.", pointer="/amount_minor")
        account = session.get(ProviderAccount, payment.provider_account_id)
        provider = payment_provider.get(account.provider)
        provider_key = f"{session.info['tenant_id']}:refund:{idempotency_key}"
        # A replay is answered before the amount guard: the first call already consumed the remainder.
        sent = provider.find_refund(account_ref=account.provider_account_ref, idempotency_key=provider_key)
        if sent is not None:
            replayed = session.execute(
                select(Refund).where(Refund.provider_refund_ref == sent.provider_refund_ref)
            ).scalar_one_or_none()
            if replayed is not None:
                return replayed
    if not 0 < amount_minor <= payment.unapplied_minor:
        raise ValidationFailed(
            "A refund returns money that is not applied to any item. Reverse the item first.",
            pointer="/amount_minor", code="refund-exceeds-unapplied",
        )  # fmt: skip
    if provider is not None:
        result = provider.refund(
            account_ref=account.provider_account_ref, provider_payment_ref=payment.provider_payment_ref,
            amount_minor=amount_minor, idempotency_key=provider_key,
        )  # fmt: skip
        row.provider_refund_ref, row.status = result.provider_refund_ref, result.outcome
        row.failure_message = result.failure_message
    session.add(row)
    session.flush()
    if row.status != "failed":  # a pending refund reserves the remainder; only a succeeded one is posted
        payment.refunded_minor += amount_minor
    if row.status == "succeeded":
        _post(
            session, "refund_succeeded", "refund", row.id, today, payment.location_id, payment.client_id,
            [("client_credit", amount_minor, 0, {}), ("funds_received", 0, amount_minor, {})], payment_id=payment.id,
        )  # fmt: skip
        events.publish(
            session,
            PaymentRefunded(
                payment_id=payment.id, client_id=payment.client_id, refund_id=row.id, amount_minor=amount_minor
            ),
            payment.id,
        )
    audit.record(
        session, "billing.refund.create", row, location_id=payment.location_id, reason=reason,
        changes={"amount_minor": [None, amount_minor], "status": [None, row.status]},
    )  # fmt: skip
    _settle_projections(session, payment, ())
    return row


# === private ===============================================================================================


def _get(session: Session, model, row_id: UUID, *, pointer: str | None = None, lock: bool = False):
    """Load by id under RLS. A missing row is 404 for a path id, 422 on the body pointer for a body id."""
    row = session.get(model, row_id, with_for_update=lock or None, populate_existing=lock)
    if row is None:
        if pointer:
            raise ValidationFailed(f"Unknown {model.__tablename__.replace('_', ' ')}.", pointer=pointer)
        raise NotFound()
    return row


def _lock(session: Session, model, row_id: UUID, *, pointer: str | None = None):
    return _get(session, model, row_id, pointer=pointer, lock=True)


def _location_in_scope(session: Session, principal: Principal, location_id: UUID) -> None:
    try:
        platform.service.get_location(session, principal, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None


def _staff_id(session: Session) -> UUID | None:
    return getattr(session.info.get("actor"), "staff_user_id", None)


def _charge_ref(charge: Charge) -> dict:
    return {
        "charge_id": charge.id, "client_id": charge.client_id, "source_context": charge.source_context,
        "source_type": charge.source_type, "source_id": charge.source_id,
    }  # fmt: skip


def _taxes_in_force(session: Session, revenue_category_id: UUID, on: date) -> list[tuple[UUID, Decimal]]:
    """(tax_id, rate) for each tax mapped to the category that applies on the date: not deactivated by then,
    with the latest rate whose effective_from_on is not after it. A tax with no rate yet does not apply."""
    taxes = session.scalars(
        select(Tax)
        .join(RevenueCategoryTax, RevenueCategoryTax.tax_id == Tax.id)
        .where(RevenueCategoryTax.revenue_category_id == revenue_category_id)
        .order_by(Tax.code)
    )
    in_force = []
    for tax in taxes:
        if tax.deactivated_on is not None and on >= tax.deactivated_on:
            continue
        rate = session.scalar(
            select(TaxRate.rate)
            .where(TaxRate.tax_id == tax.id, TaxRate.effective_from_on <= on)
            .order_by(TaxRate.effective_from_on.desc())
            .limit(1)
        )
        if rate is not None:
            in_force.append((tax.id, rate))
    return in_force


def _tender(session: Session, kind: str) -> TenderType:
    """The tenant's tender row for a built-in kind, created with its default label on first use."""
    if kind not in _TENDERS:
        raise ValidationFailed("Unknown payment method.", pointer="/tender_kind")
    stmt = select(TenderType).where(TenderType.kind == kind).order_by(TenderType.sort_order, TenderType.id).limit(1)
    tender = session.execute(stmt).scalar_one_or_none()
    if tender is None:
        ensure_defaults(session)
        tender = session.execute(stmt).scalar_one()
    return tender


def _provider_account(session: Session) -> ProviderAccount:
    """The tenant's active provider account. With payments.provider = fake (development and tests) one is
    connected on first use; a real processor is onboarded by an Owner (build module 8)."""
    stmt = select(ProviderAccount).where(ProviderAccount.status == "active", ProviderAccount.location_id.is_(None))
    account = session.execute(stmt).scalar_one_or_none()
    if account is None:
        if get_settings().payments.provider != "fake":
            raise Conflict("No payment processor is connected.", code="processor-not-connected")
        tenant_id = session.info["tenant_id"]
        session.execute(
            pg_insert(ProviderAccount)
            .values(
                id=new_id(),
                tenant_id=tenant_id,
                provider="fake",
                provider_account_ref=f"fake_acct_{tenant_id.hex}",
                status="active",
                has_card=True,
                has_bank_debit=True,
                connected_at=clock.now(),
            )  # fmt: skip
            .on_conflict_do_nothing()
        )
        account = session.execute(stmt).scalar_one()
    return account


def _live_allocations(*where):
    return (
        select(PaymentAllocation).where(PaymentAllocation.status != "released", *where).order_by(PaymentAllocation.id)
    )


def _live_total(session: Session, payment_id: UUID) -> int:
    return _int(
        session,
        select(func.coalesce(func.sum(PaymentAllocation.amount_minor), 0)).where(
            PaymentAllocation.payment_id == payment_id, PaymentAllocation.status != "released"
        ),
    )


def _int(session: Session, stmt) -> int:
    """SUM over bigint is numeric in PostgreSQL; money stays an int on our side."""
    return int(session.scalar(stmt))


def _check_period(session: Session, effective_on: date) -> None:
    locked_through = platform.service.get_tenant(session).billing_locked_through_on
    if locked_through is not None and effective_on <= locked_through:
        raise Conflict(
            f"The books are closed through {locked_through.isoformat()}; use a later date.", code="period-locked"
        )


def _post(
    session: Session,
    kind: str,
    source_type: str,
    source_id: UUID,
    effective_on: date,
    location_id: UUID,
    client_id: UUID | None,
    lines: list[tuple[str, int, int, dict]],
    *,
    charge_id: UUID | None = None,
    payment_id: UUID | None = None,
) -> None:
    """Write one balanced ledger transaction: lines are (account, debit, credit, dimensions).

    Idempotent: the same (kind, source) is posted once, ever. Zero lines are dropped, and a posting with no
    money writes nothing. The deferred database trigger rejects an unbalanced transaction at commit.
    """
    lines = [line for line in lines if line[1] or line[2]]
    already = session.scalar(
        select(LedgerTransaction.id).where(
            LedgerTransaction.kind == kind,
            LedgerTransaction.source_type == source_type,
            LedgerTransaction.source_id == source_id,
        )  # fmt: skip
    )
    if not lines or already is not None:
        return
    _check_period(session, effective_on)
    actor = session.info["actor"]
    transaction = LedgerTransaction(
        kind=kind, source_type=source_type, source_id=source_id, effective_on=effective_on, posted_at=clock.now(),
        actor_type=actor.actor_type, actor_id=actor.actor_id,
    )  # fmt: skip
    session.add(transaction)
    session.flush()
    currency = platform.service.get_tenant(session).currency
    session.add_all(
        LedgerEntry(
            ledger_transaction_id=transaction.id,
            account=account,
            debit_minor=debit,
            credit_minor=credit,
            currency=currency,
            effective_on=effective_on,
            location_id=location_id,
            client_id=client_id,
            charge_id=charge_id,
            payment_id=payment_id,
            **dimensions,
        )  # fmt: skip
        for account, debit, credit, dimensions in lines
    )
    session.flush()


def _sides(amount: int) -> tuple[int, int]:
    """(debit, credit) for an amount that is naturally a debit: a negative amount swaps sides, because ledger
    amounts are never negative."""
    return (amount, 0) if amount >= 0 else (0, -amount)


def _post_charge_to_ledger(session: Session, charge: Charge, taxes: list[ChargeTax]) -> None:
    receivable = _sides(charge.total_minor)
    revenue = _sides(charge.net_minor)[::-1]
    lines = [
        ("receivable", *receivable, {}),
        ("revenue", *revenue, {"revenue_category_id": charge.revenue_category_id}),
        *(("tax_payable", *_sides(row.amount_minor)[::-1], {"tax_id": row.tax_id}) for row in taxes),
    ]
    _post(
        session, "charge_posted", "charge", charge.id, charge.revenue_on, charge.location_id, charge.client_id,
        lines, charge_id=charge.id,
    )  # fmt: skip


def _post_allocation(
    session: Session, allocation: PaymentAllocation, payment: Payment, charge: Charge, *, released: bool
) -> None:
    today = platform.service.location_today(session, payment.location_id)
    credit, receivable = (allocation.amount_minor, 0), (0, allocation.amount_minor)
    if released:
        credit, receivable = receivable, credit
    _post(
        session, "allocation_released" if released else "allocation_applied", "payment_allocation", allocation.id,
        today, charge.location_id, charge.client_id,
        [("client_credit", *credit, {}), ("receivable", *receivable, {})],
        charge_id=charge.id, payment_id=payment.id,
    )  # fmt: skip


def _release(session: Session, allocation: PaymentAllocation, reason: str) -> None:
    """Release a live allocation. An applied one posts the release (the money returns to the payment as
    credit); a provisional one never reached the ledger. Refreshes the payment's projection."""
    payment = _lock(session, Payment, allocation.payment_id)
    charge = session.get(Charge, allocation.charge_id)
    was_applied = allocation.status == "applied"
    allocation.status, allocation.released_at, allocation.release_reason = "released", clock.now(), reason
    charge.applied_minor -= allocation.amount_minor
    session.flush()
    if was_applied:
        _post_allocation(session, allocation, payment, charge, released=True)
    _settle_projections(session, payment, ())


def _apply_state(session: Session, payment: Payment, state: PaymentState) -> None:
    """The one place a payment changes status (ADR 0003 section 7). A transition the table does not allow is
    ignored, which makes this safe to replay and to receive out of order."""
    status = "failed" if state.outcome == "declined" else state.outcome
    if status not in _TRANSITIONS.get(payment.status, ()):
        return
    payment.status = status
    payment.card_brand = state.card_brand or payment.card_brand
    payment.card_last4 = state.card_last4 or payment.card_last4
    payment.card_funding = state.card_funding or payment.card_funding
    ref = {"payment_id": payment.id, "client_id": payment.client_id}
    invoice_ids: set[UUID | None] = set()
    if status == "succeeded":
        payment.settled_at = clock.now()
        today = platform.service.location_today(session, payment.location_id)
        _post(
            session, "payment_settled", "payment", payment.id, today, payment.location_id, payment.client_id,
            [("funds_received", payment.amount_minor, 0, {}), ("client_credit", 0, payment.amount_minor, {})],
            payment_id=payment.id,
        )  # fmt: skip
        for allocation in session.scalars(_live_allocations(PaymentAllocation.payment_id == payment.id)):
            charge = session.get(Charge, allocation.charge_id)
            allocation.status, allocation.applied_at = "applied", clock.now()
            session.flush()
            _post_allocation(session, allocation, payment, charge, released=False)
            invoice_ids.add(charge.invoice_id)
        events.publish(session, PaymentSucceeded(**ref), payment.id)
    elif status == "failed":
        payment.failure_category, payment.failure_message = state.failure_category, state.failure_message
        for allocation in session.scalars(_live_allocations(PaymentAllocation.payment_id == payment.id)):
            charge = session.get(Charge, allocation.charge_id)
            allocation.status, allocation.released_at, allocation.release_reason = (
                "released", clock.now(), "payment_failed",
            )  # fmt: skip
            charge.applied_minor -= allocation.amount_minor
            invoice_ids.add(charge.invoice_id)
        events.publish(session, PaymentFailed(**ref, failure_category=state.failure_category), payment.id)
    elif status == "processing":
        events.publish(session, PaymentProcessing(**ref), payment.id)
    _settle_projections(session, payment, invoice_ids)


def _settle_projections(session: Session, payment: Payment, invoice_ids: Iterable[UUID | None]) -> None:
    """Recompute the cached remainders after any allocation, release, settlement or refund. They are
    projections of the rows, never inputs to the ledger (ADR 0003 section 2)."""
    session.flush()
    payment.unapplied_minor = (
        payment.amount_minor - payment.refunded_minor - _live_total(session, payment.id)
        if payment.status == "succeeded"
        else 0
    )
    session.flush()
    for invoice_id in sorted({i for i in invoice_ids if i}):
        _refresh_invoice(session, invoice_id)


def _refresh_invoice(session: Session, invoice_id: UUID) -> None:
    """Derive total, balance and status from the invoice's charges and their allocations."""
    invoice = _lock(session, Invoice, invoice_id)
    if invoice.status == "voided":
        return
    total = _int(session, select(func.coalesce(func.sum(Charge.total_minor), 0)).where(Charge.invoice_id == invoice.id))
    by_status = dict(
        session.execute(
            select(PaymentAllocation.status, func.sum(PaymentAllocation.amount_minor))
            .join(Charge, Charge.id == PaymentAllocation.charge_id)
            .where(Charge.invoice_id == invoice.id, PaymentAllocation.status != "released")
            .group_by(PaymentAllocation.status)
        ).all()
    )
    applied, provisional = int(by_status.get("applied", 0)), int(by_status.get("provisional", 0))
    was = invoice.status
    invoice.total_minor, invoice.balance_minor = total, total - applied
    if total > 0 and applied >= total:
        invoice.status = "paid"
    elif total > 0 and applied + provisional >= total:
        invoice.status = "payment_pending"  # covered, but part of the cover has not settled yet
    elif applied > 0:
        invoice.status = "partially_paid"
    else:
        invoice.status = "open"
    session.flush()
    if invoice.status == "paid" and was != "paid":
        events.publish(
            session, InvoicePaid(invoice_id=invoice.id, bill_to_client_id=invoice.bill_to_client_id), invoice.id
        )


def _invoice_detail(session: Session, invoice: Invoice) -> dict:
    charges = session.scalars(select(Charge).where(Charge.invoice_id == invoice.id).order_by(Charge.id)).all()
    return {**{c.key: getattr(invoice, c.key) for c in Invoice.__table__.columns}, "charges": charges}


def _payment_detail(session: Session, payment: Payment) -> dict:
    session.refresh(payment)
    allocations = session.scalars(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id).order_by(PaymentAllocation.id)
    ).all()
    refunds = session.scalars(select(Refund).where(Refund.payment_id == payment.id).order_by(Refund.id)).all()
    return {
        **{c.key: getattr(payment, c.key) for c in Payment.__table__.columns},
        "allocations": allocations, "refunds": refunds,
    }  # fmt: skip


# === internal reads for the selling contexts (memberships, packages) =========================================


def get_charge(session: Session, charge_id: UUID) -> Charge:
    """The charge, for a caller that needs its state (status, applied_minor, total_minor). Internal."""
    return _get(session, Charge, charge_id)


def charge_payments(session: Session, charge_id: UUID) -> list[tuple[UUID, int]]:
    """(payment_id, amount_minor) for each live allocation on the charge: what a cancel reads before it
    reverses, so the released money can be re-applied or refunded payment by payment. Internal."""
    rows = session.scalars(_live_allocations(PaymentAllocation.charge_id == charge_id))
    return [(row.payment_id, row.amount_minor) for row in rows]
