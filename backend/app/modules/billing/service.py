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

from collections.abc import Callable, Iterable, Sequence
from datetime import date
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize
from app.core.db.session import tenant_session
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import clients, platform
from app.modules.billing.domain import schedule as plans
from app.modules.billing.domain.money import net_amount, tax_amount
from app.modules.billing.events import (
    ChargeAdjusted,
    ChargeCreated,
    ChargeReversed,
    ChargeVoided,
    InvoiceIssued,
    InvoicePaid,
    InvoicePastDue,
    InvoiceVoided,
    PaymentDisputeClosed,
    PaymentDisputed,
    PaymentFailed,
    PaymentProcessing,
    PaymentRefunded,
    PaymentSucceeded,
    PaymentVoided,
)
from app.modules.billing.models import (
    Charge,
    ChargeTax,
    Dispute,
    Invoice,
    LedgerEntry,
    LedgerTransaction,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentSchedule,
    ProviderAccount,
    ProviderCustomer,
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
# Called as hook(session, payment, previous_status) after a payment changes status, in the same transaction.
# Autopay dunning and decline notices register here; billing.service stays below them.
PAYMENT_HOOKS: list[Callable[[Session, Payment, str], None]] = []
CONSTRAINT_CODES["ct_payment_schedule_balanced"] = "schedule-not-balanced"


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
    charges = []
    for charge_id in data["charge_ids"]:
        charge = _get(session, Charge, charge_id, pointer="/charge_ids")
        authorize(principal, "billing.invoice.create", location_id=charge.location_id)
        charges.append(charge)
    payer = data.get("bill_to_client_id")
    if payer is not None:
        clients.service.require_active(session, payer, pointer="/bill_to_client_id")  # unknown first, then unrelated
    if payer is not None and payer not in related_clients(session, [c.client_id for c in charges]):
        raise ValidationFailed(
            "Choose someone on the invoice or a relative of theirs.", pointer="/bill_to_client_id",
            code="payer-not-related",
        )  # fmt: skip
    invoice = create_invoice_for_charges(
        session, data["charge_ids"], bill_to_client_id=data.get("bill_to_client_id"), due_on=data.get("due_on"),
        is_autopay=bool(data.get("is_autopay")), comments=data.get("comments"),
    )  # fmt: skip
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


def get_invoice_row(session: Session, invoice_id: UUID) -> Invoice:
    """Internal (ADR 0009 section 9): the invoice row a sale raised, for `checkout.secure_online_checkout`."""
    return _get(session, Invoice, invoice_id)


def get_invoice(session: Session, principal: Principal, invoice_id: UUID) -> dict:
    authorize(principal, "billing.invoice.read")
    return _invoice_detail(session, _get(session, Invoice, invoice_id))


def take_payment_at_desk(session: Session, principal: Principal, data: dict, idempotency_key: str | None) -> dict:
    """Staff take-payment (PAY-01). Client-following key: holding it at any location suffices."""
    authorize(principal, "billing.payment.take")
    _location_in_scope(session, principal, data["location_id"])
    data = dict(data)
    allocations = [(row["charge_id"], row["amount_minor"]) for row in data.pop("allocations", None) or []]
    payment = take_payment(
        session, **data, allocations=allocations or None, idempotency_key=_staff_key(principal, idempotency_key)
    )
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
    payment = _get(session, Payment, payment_id)
    authorize(principal, "billing.payment.take", location_id=payment.location_id)
    return _payment_detail(session, confirm_payment(session, payment_id))


def allocate_payment(session: Session, principal: Principal, payment_id: UUID, data: dict) -> dict:
    payment = _get(session, Payment, payment_id)
    authorize(principal, "billing.payment.reallocate", location_id=payment.location_id)
    rows = [(row["charge_id"], row["amount_minor"]) for row in data.get("allocations") or []]
    if rows:
        targets = [_get(session, Charge, charge_id, pointer="/allocations") for charge_id, _ in rows]
    elif data.get("invoice_id"):
        targets = [_get(session, Invoice, data["invoice_id"], pointer="/invoice_id")]
    elif principal.kind != "system" and principal.location_ids is not None:
        raise ValidationFailed("Choose the items or the invoice to apply this payment to.", pointer="/allocations")
    else:
        targets = []
    for target in targets:  # the money moves onto each target's books, so each location must be in reach
        authorize(principal, "billing.payment.reallocate", location_id=target.location_id)
    payment = allocate(session, payment_id, invoice_id=data.get("invoice_id"), allocations=rows or None)
    return _payment_detail(session, payment)


def create_refund(
    session: Session, principal: Principal, payment_id: UUID, data: dict, idempotency_key: str | None
) -> Refund:
    payment = _get(session, Payment, payment_id)
    authorize(principal, "billing.refund.create", location_id=payment.location_id)
    return refund(session, payment_id, **data, idempotency_key=_staff_key(principal, idempotency_key))


def _staff_key(principal: Principal, idempotency_key: str | None) -> str | None:
    """A caller's Idempotency-Key is only unique to that caller (the HTTP layer scopes it the same way), so
    two people who happen to send the same key must never be handed each other's payment or refund."""
    return f"staff:{principal.actor_id}:{idempotency_key}" if idempotency_key else None


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
    system_keys = ("uncategorised", "surcharge")
    tenders = select(func.count(TenderType.kind.distinct())).where(TenderType.kind.in_(list(_TENDERS)))
    categories = select(func.count()).select_from(RevenueCategory).where(RevenueCategory.system_key.in_(system_keys))
    if tuple(session.execute(select(tenders.scalar_subquery(), categories.scalar_subquery())).one()) == (
        len(_TENDERS),
        len(system_keys),
    ):  # all there: one read instead of ten upserts on every tender (docs/ops/performance-budget.md)
        return
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
    coupon_id: UUID | None = None,
    tax_ids: Iterable[UUID] | None = None,
) -> Charge:
    """Create a receivable and post it to the ledger (debit receivable; credit revenue and each tax).

    Idempotent by origin: a second call with the same (source_context, source_type, source_id,
    source_line_no) returns the charge the first call made, whatever its status, so a retried job never bills
    twice. To bill the same thing again after a reversal, use the next source_line_no.

    Amounts: net = round(quantity * unit_price) - discount, half-up once at the line; each tax mapped to the
    revenue category (minus exclude_tax_ids) is computed on the net at the rate in force on revenue_on.
    Dates default to today at the location. A zero-total charge is recorded but posts nothing. `tax_ids`
    replaces the revenue category's taxes with these (a POS product's own tax codes), at the same rates.
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
        for tax_id, rate in taxes_in_force(session, revenue_on, revenue_category_id=category.id, tax_ids=tax_ids)
    ]  # fmt: skip
    tax_total = sum(row.amount_minor for row in taxes)
    charge = Charge(
        client_id=client_id, location_id=location_id, source_context=source_context, source_type=source_type,
        source_id=source_id, source_line_no=source_line_no, description=description,
        additional_description=additional_description, internal_remarks=internal_remarks, quantity=quantity,
        unit_price_minor=unit_price_minor, discount_minor=discount_minor, net_minor=net, tax_minor=tax_total,
        total_minor=net + tax_total, bill_on=bill_on, revenue_on=revenue_on, service_starts_on=service_starts_on,
        service_ends_on=service_ends_on, revenue_category_id=category.id, created_by_staff_user_id=_staff_id(session),
        coupon_id=coupon_id,
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
    _require_live(charge)
    reversal = _negate(
        session, charge, reason=reason, revenue_on=revenue_on, status="reversed", release_reason="charge_reversed"
    )
    audit.record(
        session, "billing.charge.reverse", charge, location_id=charge.location_id, reason=reason,
        changes={"status": ["active", "reversed"]},
    )  # fmt: skip
    events.publish(session, ChargeReversed(**_charge_ref(charge), reversal_charge_id=reversal.id), charge.id)
    session.flush()
    if charge.invoice_id:
        _refresh_invoice(session, charge.invoice_id)
    return reversal


def void_charge(session: Session, charge_id: UUID, *, reason: str) -> Charge:
    """Void an item (BIL-08): it nets to zero in its original period and both rows are `voided`, hidden from
    default lists and statements. Only an uninvoiced item with no money applied; terminal. Not a delete: the
    rows and the audit event stay (overview divergence 5)."""
    charge = _lock(session, Charge, charge_id)
    _require_live(charge)
    if charge.invoice_id is not None or charge.applied_minor:
        raise Conflict(
            "Only an uninvoiced item with no payments can be voided; reverse it instead.", code="charge-not-voidable"
        )
    negation = _negate(session, charge, reason=reason, revenue_on=None, status="voided", release_reason="unapplied")
    audit.record(
        session, "billing.charge.void", charge, location_id=charge.location_id, reason=reason,
        changes={"status": ["active", "voided"]},
    )  # fmt: skip
    events.publish(session, ChargeVoided(**_charge_ref(charge)), charge.id)
    session.flush()
    return negation


def adjust_charge(
    session: Session,
    charge_id: UUID,
    *,
    reason: str,
    quantity: Decimal | int | None = None,
    unit_price_minor: int | None = None,
    discount_minor: int | None = None,
    exclude_tax_ids: Iterable[UUID] | None = None,
) -> Charge:
    """Change the money of a posted charge (BIL-01) and return the row that replaces it.

    Money columns are immutable, so the edit is two rows: the charge is negated at its own revenue date and
    becomes `reversed`, and an `adjustment` charge carrying the new values takes its place on the same
    invoice (`adjusts_charge_id` links them; the UI folds the three rows into one line). Taxes use the rates
    snapshotted on the original. Money applied to the old row is re-applied to the new one from the same
    payments, up to its total; any excess stays on those payments as account credit, and nothing is refunded
    (a price change and a refund are two steps). It emits `billing.charge.adjusted`, not `.reversed`: what was
    sold still stands.
    """
    charge = _lock(session, Charge, charge_id)
    _require_live(charge)
    quantity = charge.quantity if quantity is None else Decimal(quantity)
    unit_price_minor = charge.unit_price_minor if unit_price_minor is None else unit_price_minor
    discount_minor = charge.discount_minor if discount_minor is None else discount_minor
    gross = net_amount(quantity, unit_price_minor)
    if quantity <= 0 or unit_price_minor < 0:
        raise ValidationFailed(
            "Quantity must be positive and the price cannot be negative.", pointer="/unit_price_minor"
        )
    if not 0 <= discount_minor <= gross:
        raise ValidationFailed("The discount cannot exceed the line amount.", pointer="/discount_minor")
    net = gross - discount_minor
    snapshot = session.scalars(select(ChargeTax).where(ChargeTax.charge_id == charge.id)).all()
    excluded = {row.tax_id for row in snapshot if row.is_excluded} if exclude_tax_ids is None else set(exclude_tax_ids)
    paid = [
        (allocation.payment_id, allocation.amount_minor)
        for allocation in session.scalars(_live_allocations(PaymentAllocation.charge_id == charge.id))
    ]
    old_total = charge.total_minor
    _negate(session, charge, reason=reason, revenue_on=None, status="reversed", release_reason="charge_adjusted")
    taxes = [
        ChargeTax(tax_id=row.tax_id, rate=row.rate, is_excluded=row.tax_id in excluded,
                  amount_minor=0 if row.tax_id in excluded else tax_amount(net, row.rate))
        for row in snapshot
    ]  # fmt: skip
    tax_total = sum(row.amount_minor for row in taxes)
    replacement = Charge(
        client_id=charge.client_id, location_id=charge.location_id, invoice_id=charge.invoice_id, kind="adjustment",
        source_context=charge.source_context, source_type=charge.source_type, source_id=charge.source_id,
        source_line_no=charge.source_line_no, description=charge.description,
        additional_description=charge.additional_description, internal_remarks=charge.internal_remarks,
        quantity=quantity, unit_price_minor=unit_price_minor, discount_minor=discount_minor, net_minor=net,
        tax_minor=tax_total, total_minor=net + tax_total, bill_on=charge.bill_on, revenue_on=charge.revenue_on,
        service_starts_on=charge.service_starts_on, service_ends_on=charge.service_ends_on,
        revenue_category_id=charge.revenue_category_id, adjusts_charge_id=charge.id, reason=reason,
        coupon_id=charge.coupon_id, created_by_staff_user_id=_staff_id(session),
    )  # fmt: skip
    session.add(replacement)
    session.flush()
    for row in taxes:
        row.charge_id = replacement.id
    session.add_all(taxes)
    _post_charge_to_ledger(session, replacement, taxes)
    for payment_id, amount in paid:
        amount = min(amount, replacement.total_minor - replacement.applied_minor)
        if amount > 0:
            _allocate(session, _lock(session, Payment, payment_id), None, [(replacement.id, amount)])
    audit.record(
        session, "billing.charge.update", charge, location_id=charge.location_id, reason=reason,
        changes={"total_minor": [old_total, replacement.total_minor], "status": ["active", "reversed"]},
    )  # fmt: skip
    events.publish(session, ChargeAdjusted(**_charge_ref(charge), replacement_charge_id=replacement.id), charge.id)
    session.flush()
    if charge.invoice_id:
        _refresh_invoice(session, charge.invoice_id)
    return replacement


def _require_live(charge: Charge) -> None:
    if charge.status != "active" or charge.kind == "reversal":
        raise Conflict("This item was already reversed or voided.", code="charge-not-reversible")


def _negate(
    session: Session, charge: Charge, *, reason: str, revenue_on: date | None, status: str, release_reason: str
) -> Charge:
    """The shared arithmetic of reverse, void and adjust: release what was applied, mark the original, insert
    the negating row with the original tax snapshot flipped, and post it."""
    if not reason.strip():
        raise ValidationFailed("A reason is required.", pointer="/reason")
    today = platform.service.location_today(session, charge.location_id)
    for allocation in session.scalars(_live_allocations(PaymentAllocation.charge_id == charge.id)):
        _release(session, allocation, release_reason)
    now, voided = clock.now(), status == "voided"
    charge.status = status
    if voided:
        charge.voided_at, charge.voided_by_staff_user_id, charge.reason = now, _staff_id(session), reason
    else:
        charge.reversed_at = now
    negation = Charge(
        client_id=charge.client_id, location_id=charge.location_id, invoice_id=charge.invoice_id, kind="reversal",
        source_context=charge.source_context, source_type=charge.source_type, source_id=charge.source_id,
        source_line_no=charge.source_line_no, description=charge.description, quantity=charge.quantity,
        unit_price_minor=-charge.unit_price_minor, discount_minor=-charge.discount_minor,
        net_minor=-charge.net_minor, tax_minor=-charge.tax_minor, total_minor=-charge.total_minor, bill_on=today,
        revenue_on=revenue_on or charge.revenue_on, revenue_category_id=charge.revenue_category_id,
        reverses_charge_id=charge.id, reason=reason, created_by_staff_user_id=_staff_id(session),
        status="voided" if voided else "active", voided_at=now if voided else None,
        voided_by_staff_user_id=_staff_id(session) if voided else None,
    )  # fmt: skip
    session.add(negation)
    session.flush()
    taxes = [
        ChargeTax(charge_id=negation.id, tax_id=row.tax_id, rate=row.rate, amount_minor=-row.amount_minor,
                  is_excluded=row.is_excluded)
        for row in session.scalars(select(ChargeTax).where(ChargeTax.charge_id == charge.id))
    ]  # fmt: skip
    session.add_all(taxes)
    _post_charge_to_ledger(session, negation, taxes)
    return negation


def create_invoice_for_charges(
    session: Session,
    charge_ids: Sequence[UUID],
    *,
    bill_to_client_id: UUID | None = None,
    due_on: date | None = None,
    origin: str = "staff",
    is_autopay: bool = False,
    comments: str | None = None,
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
        location_id=location_id, origin=origin, invoice_on=today, due_on=due_on or today, is_autopay=is_autopay,
        comments=comments, created_by_staff_user_id=_staff_id(session),
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
    payment_method_id: UUID | None = None,
    off_session: bool = False,
    save_method: bool = False,
    tender_type_id: UUID | None = None,
    origin: str = "staff",
    invoice_id: UUID | None = None,
    allocations: Allocations | None = None,
    external_reference: str | None = None,
    memo: str | None = None,
    audit_changes: dict | None = None,
    internal_tender: bool = False,
) -> Payment:
    """Receive money from one payer in one tender, then allocate it (see allocate()).

    Record-only tenders (cash, cheque, bank transfer, gift card...) are `succeeded` at once. Processed tenders
    (card, bank_debit) call the payment provider and need `idempotency_key` plus either `method_token` (an
    opaque one-time provider reference, never card data) or `payment_method_id` (a stored method of this
    payer). `off_session` is for charges with the payer absent (autopay). `save_method` asks the processor to
    keep a `method_token`'s method on the payer's provider customer with this charge (the caller ensures the
    customer exists; `methods.save_from_payment` records it once the payment is secured).

    Replay safety: a payment is found again by its `idempotency_key`, whatever the tender, so the same key
    always resolves to the same row and the same provider payment. For a processed tender the row is
    committed as `initiated` before the provider is called (ADR 0003 section 8): if this transaction dies
    after the provider answered, a retry with the same key or the reconciliation sweep finishes it.

    The result is a state, not an exception: check `payment.status`. `succeeded` is settled and in the
    ledger. `processing` (bank debit) holds its allocations as provisional until confirm_payment() settles
    it. `requires_action` waits for the payer to authenticate (`payment.client_secret`). `failed` (declined)
    and `unknown` (provider timeout: NOT a decline, resolved by confirm_payment()) allocate nothing. Money
    left unallocated is the payer's account credit.

    `internal_tender` (internal; only post_opening_balance passes it, no router can) lets a billing-owned tender
    (`system_key` set, never enabled) through; any other caller naming one is refused like a disabled tender.
    """
    payment = _payment_by_key(session, idempotency_key)
    if payment is not None and payment.status != "initiated":
        return payment
    if amount_minor <= 0:
        raise ValidationFailed("The amount must be greater than zero.", pointer="/amount_minor")
    tender = _tender(session, tender_kind, tender_type_id)
    if not (internal_tender if tender.system_key else tender.is_enabled):
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
    if invoice_id or allocations:  # refuse a bad allocation before any money moves
        _plan(session, client_id, amount_minor, invoice_id, allocations)
    tenant = platform.service.get_tenant(session)
    values = {
        "client_id": client_id, "location_id": location_id, "tender_type_id": tender.id, "tender_kind": tender.kind,
        "amount_minor": amount_minor, "currency": tenant.currency, "origin": origin,
        "external_reference": external_reference, "memo": memo, "received_at": clock.now(),
        "taken_by_staff_user_id": _staff_id(session), "idempotency_key": idempotency_key,
        "payment_method_id": payment_method_id,
    }  # fmt: skip
    if tender.is_processed:
        account = _provider_account(session)
        customer_ref = None
        if payment_method_id is not None:
            method = _get(session, PaymentMethod, payment_method_id, pointer="/payment_method_id")
            usable = (
                method.client_id == client_id and method.status == "active"
                and method.provider_account_id == account.id
                and (method.kind == "card") == (tender.kind == "card")
            )  # fmt: skip
            if not usable:
                raise ValidationFailed(
                    "This stored payment method cannot be used for this payment.", pointer="/payment_method_id",
                    code="payment-method-not-usable",
                )  # fmt: skip
            method_token = method.provider_method_ref
            customer_ref = session.scalar(
                select(ProviderCustomer.provider_customer_ref).where(
                    ProviderCustomer.client_id == client_id, ProviderCustomer.provider_account_id == account.id
                )
            )
        if save_method and payment_method_id is None:
            customer_ref = session.scalar(
                select(ProviderCustomer.provider_customer_ref).where(
                    ProviderCustomer.client_id == client_id, ProviderCustomer.provider_account_id == account.id
                )
            )
        if not method_token or not idempotency_key:
            raise ValidationFailed(
                "A processed payment needs a payment method and an Idempotency-Key.", pointer="/method_token"
            )
        values["provider_account_id"] = account.id
        if payment is None:
            payment = _initiate(session, values, idempotency_key)
            if payment.status != "initiated":  # a concurrent request with the same key finished first
                return payment
        state = payment_provider.get(account.provider).create_payment(
            account_ref=account.provider_account_ref, amount_minor=amount_minor, currency=tenant.currency,
            method_token=method_token, idempotency_key=_provider_key(session, payment),
            customer_ref=customer_ref, off_session=off_session, save_method=save_method and customer_ref is not None,
        )  # fmt: skip
        payment.provider_payment_ref = state.provider_payment_ref or None  # none yet when the call timed out
    else:
        state = PaymentState(provider_payment_ref="", outcome="succeeded")
        if payment is None:
            payment = Payment(**values, receipt_number=platform.service.next_number(session, "receipt"))
            session.add(payment)
    session.flush()
    _apply_state(session, payment, state)
    if payment.status in ("succeeded", "processing") and (invoice_id or allocations):
        _allocate(session, payment, invoice_id, allocations)
    audit.record(
        session, "billing.payment.take", payment, location_id=location_id,
        changes={
            "amount_minor": [None, amount_minor], "tender_kind": [None, tender.kind], "status": [None, payment.status]
        } | (audit_changes or {}),
    )  # fmt: skip
    return payment


def find_payment(session: Session, idempotency_key: str) -> Payment | None:
    """Internal: the payment taken with this Idempotency-Key, locked, or None (a caller's replay check)."""
    return _payment_by_key(session, idempotency_key)


def refundable_minor(session: Session, payment_id: UUID) -> int:
    """Internal: what refund() can still return from this payment (its settled, unapplied remainder)."""
    payment = _lock(session, Payment, payment_id)
    return payment.unapplied_minor if payment.status == "succeeded" else 0


def _payment_by_key(session: Session, idempotency_key: str | None) -> Payment | None:
    if not idempotency_key:
        return None
    return session.execute(
        select(Payment).where(Payment.idempotency_key == idempotency_key).with_for_update()
    ).scalar_one_or_none()


def _provider_key(session: Session, payment: Payment) -> str:
    return f"{session.info['tenant_id']}:payment:{payment.idempotency_key}"


def _initiate(session: Session, values: dict, idempotency_key: str) -> Payment:
    """Commit the `initiated` payment row in a short transaction of its own, before the provider call (ADR
    0003 section 8), and return it locked in the caller's transaction. This is the one place billing opens a
    session: the row must outlive a failure of the request that created it.

    The short transaction cannot see what the caller has not committed and must never wait on the caller's
    own locks, so it gives up quickly (a client created in this same transaction, the receipt counter already
    held by an earlier payment of this transaction). Then the row is inserted in the caller's transaction
    instead, as the kernel did: replay stays safe through the provider's idempotency key, only the
    survives-a-crash guarantee is lost for that one payment.
    """
    try:
        with tenant_session(session.info["tenant_id"], actor=session.info.get("actor")) as short:
            short.execute(text("SET LOCAL lock_timeout = '500ms'"))
            row = Payment(**values, receipt_number=platform.service.next_number(short, "receipt"))
            short.add(row)
            short.flush()
            payment_id = row.id
    except (IntegrityError, OperationalError):
        existing = _payment_by_key(session, idempotency_key)  # lost a race to the same key?
        if existing is not None:
            return existing
        payment = Payment(**values, receipt_number=platform.service.next_number(session, "receipt"))
        session.add(payment)
        session.flush()
        return payment
    return _lock(session, Payment, payment_id)


def cancel_payment(session: Session, payment_id: UUID) -> Payment:
    """Abandon a payment the payer never completed (`requires_action`) or that never reached the provider."""
    payment = _lock(session, Payment, payment_id)
    if payment.status not in ("initiated", "requires_action"):
        raise Conflict("Only a payment that has not completed can be cancelled.", code="payment-not-cancellable")
    ref = payment.provider_payment_ref
    if ref:
        account = session.get(ProviderAccount, payment.provider_account_id)
        state = payment_provider.get(account.provider).cancel_payment(
            account_ref=account.provider_account_ref, provider_payment_ref=ref
        )
    else:
        state = PaymentState(provider_payment_ref="", outcome="cancelled")
    was = payment.status
    _apply_state(session, payment, state)
    audit.record(
        session, "billing.payment.cancel", payment, location_id=payment.location_id,
        changes={"status": [was, payment.status]},
    )  # fmt: skip
    return payment


def confirm_payment(session: Session, payment_id: UUID) -> Payment:
    """Re-read the provider and apply its current state: settles a `processing` bank debit, resolves an
    `unknown`. Safe to call any number of times and from any path (request, webhook actor, sweep)."""
    payment = _lock(session, Payment, payment_id)
    if payment.provider_account_id is None or payment.status not in _TRANSITIONS:
        return payment
    account = session.get(ProviderAccount, payment.provider_account_id)
    provider = payment_provider.get(account.provider)
    if payment.provider_payment_ref:
        state = provider.get_payment(
            account_ref=account.provider_account_ref, provider_payment_ref=payment.provider_payment_ref
        )
    else:  # the request died around the provider call: ask the provider what, if anything, it did
        state = provider.find_payment(
            account_ref=account.provider_account_ref, idempotency_key=_provider_key(session, payment)
        )
        if state is None:
            return payment
        payment.provider_payment_ref = state.provider_payment_ref
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


def _plan(
    session: Session,
    client_id: UUID | None,
    available: int,
    invoice_id: UUID | None,
    allocations: Allocations | None,
) -> list[tuple[Charge, int]]:
    """Decide which charges `available` money goes to, locking them. Explicit amounts are validated;
    automatic allocation takes open charges oldest first and stops when the money runs out."""
    if allocations is None:
        open_charges = select(Charge).where(Charge.status == "active", Charge.applied_minor < Charge.total_minor)
        if invoice_id is not None:
            invoice = _get(session, Invoice, invoice_id, pointer="/invoice_id")
            open_charges = open_charges.where(Charge.invoice_id == invoice.id)
        else:
            open_charges = open_charges.where(Charge.client_id == client_id)
        plan = []
        for charge in session.scalars(open_charges.order_by(Charge.bill_on, Charge.id).with_for_update()):
            amount = min(available - sum(a for _, a in plan), charge.total_minor - charge.applied_minor)
            if amount > 0:
                plan.append((charge, amount))
        _require_payer(session, client_id, [charge for charge, _ in plan], "/invoice_id")
        return plan
    if len({charge_id for charge_id, _ in allocations}) != len(allocations):
        raise ValidationFailed("List each item once.", pointer="/allocations")
    # Lock in id order so two concurrent allocations cannot deadlock.
    plan = [
        (_lock(session, Charge, charge_id, pointer="/allocations"), amount)
        for charge_id, amount in sorted(allocations, key=lambda row: row[0])
    ]
    _require_payer(session, client_id, [charge for charge, _ in plan], "/allocations")
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
    return plan


def related_clients(session: Session, client_ids: Iterable[UUID]) -> set[UUID]:
    """Internal: these clients and everyone with an active relationship to one of them. The people whose money
    may settle an item, and who an invoice may be billed to: a parent, never a stranger. A pending request
    (not yet accepted or approved) counts for nothing."""
    people = set(client_ids) - {None}
    return people | {
        other
        for person in people
        for rel in clients.households.relationships_of(session, person, live_only=True)
        if rel.status == "active"
        for other in (rel.from_client_id, rel.to_client_id)
    }


def _require_payer(session: Session, client_id: UUID | None, charges: Sequence[Charge], pointer: str) -> None:
    """Money goes only where its owner points it: each item is the payer's own, on an invoice billed to the
    payer, or a live relative's. A walk-in payment (no client) settles only items with no client."""
    if client_id is None:
        allowed = all(charge.client_id is None for charge in charges)
    else:
        payers = related_clients(session, [client_id])
        billed_to = {
            row.id: row.bill_to_client_id
            for row in session.scalars(select(Invoice).where(Invoice.id.in_({c.invoice_id for c in charges} - {None})))
        }
        allowed = all(charge.client_id in payers or billed_to.get(charge.invoice_id) == client_id for charge in charges)
    if not allowed:
        raise ValidationFailed(
            "This money belongs to someone else: it can only pay the payer's or a relative's items.",
            pointer=pointer, code="payer-mismatch",
        )  # fmt: skip


def _allocate(
    session: Session,
    payment: Payment,
    invoice_id: UUID | None,
    allocations: Allocations | None,
    *,
    limit: int | None = None,
) -> int:
    if payment.status not in ("succeeded", "processing"):
        raise Conflict("Only a settled or pending payment can be applied.", code="payment-not-allocatable")
    available = payment.amount_minor - payment.refunded_minor - _live_total(session, payment.id)
    if limit is not None:
        available = min(available, limit)
    plan = _plan(session, payment.client_id, available, invoice_id, allocations)
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
    refund_batch_id: UUID | None = None,
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
        refund_batch_id=refund_batch_id,
    )  # fmt: skip
    provider = account = provider_key = None
    if method == "original":
        if not idempotency_key:
            raise ValidationFailed("A processed refund needs an Idempotency-Key.", pointer="/amount_minor")
        account = session.get(ProviderAccount, payment.provider_account_id)
        provider = payment_provider.get(account.provider)
        provider_key = f"{session.info['tenant_id']}:refund:{idempotency_key}"
        # A replay is answered before the amount guard: the first call already consumed the remainder.
        sent = provider.find_refund(
            account_ref=account.provider_account_ref, idempotency_key=provider_key,
            provider_payment_ref=payment.provider_payment_ref,
        )  # fmt: skip
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
        row.provider_refund_ref, row.status = result.provider_refund_ref or None, result.outcome
        row.failure_message = result.failure_message
    session.add(row)
    session.flush()
    if row.status != "failed":  # a pending refund reserves the remainder; only a succeeded one is posted
        payment.refunded_minor += amount_minor
    if row.status == "succeeded":
        _post_refund(session, row, payment)
    audit.record(
        session, "billing.refund.create", row, location_id=payment.location_id, reason=reason,
        changes={"amount_minor": [None, amount_minor], "status": [None, row.status]},
    )  # fmt: skip
    _settle_projections(session, payment, ())
    return row


def confirm_refund(session: Session, refund_id: UUID) -> Refund:
    """Re-read a `pending` provider refund and apply its answer: `succeeded` posts it, `failed` gives the
    reserved money back to the payment. Safe to repeat (webhook, sweep)."""
    row = _lock(session, Refund, refund_id)
    if row.status != "pending" or not row.provider_refund_ref:
        return row
    payment = _lock(session, Payment, row.payment_id)
    account = session.get(ProviderAccount, payment.provider_account_id)
    state = payment_provider.get(account.provider).get_refund(
        account_ref=account.provider_account_ref, provider_refund_ref=row.provider_refund_ref
    )
    if state.outcome == "pending":
        return row
    row.status, row.failure_message = state.outcome, state.failure_message
    if state.outcome == "succeeded":
        _post_refund(session, row, payment)
    else:
        payment.refunded_minor -= row.amount_minor
    audit.record(
        session, "billing.refund.confirm", row, location_id=row.location_id,
        changes={"status": ["pending", row.status]},
    )  # fmt: skip
    _settle_projections(session, payment, ())
    return row


def _post_refund(session: Session, row: Refund, payment: Payment) -> None:
    _post(
        session, "refund_succeeded", "refund", row.id, row.refund_on, payment.location_id, payment.client_id,
        [("client_credit", row.amount_minor, 0, {}), ("funds_received", 0, row.amount_minor, {})],
        payment_id=payment.id,
    )  # fmt: skip
    events.publish(
        session,
        PaymentRefunded(
            payment_id=payment.id, client_id=payment.client_id, refund_id=row.id, amount_minor=row.amount_minor
        ),
        payment.id,
    )


def sync_dispute(session: Session, account: ProviderAccount, provider_dispute_ref: str) -> Dispute | None:
    """Mirror a processor dispute (ADR 0003 section 9). Opened: the payment becomes `disputed`, its allocations
    are released (the invoices reopen) and the funds move to `disputed_funds`. Won: they come back as unapplied
    credit on the same payment, for staff or autopay to re-apply. Lost: the payment is `charged_back` and the
    credit is gone. A bank-debit dispute is lost on arrival. Re-reads the processor, so a replayed or
    out-of-order webhook changes nothing; inquiries (no money withdrawn) are ignored.

    shortcut: one dispute per payment for its whole disputed amount; a second dispute on a payment that is
    already disputed or charged back is stored but moves no money. Partial disputes are rare; revisit with them.
    """
    state = payment_provider.get(account.provider).get_dispute(
        account_ref=account.provider_account_ref, provider_dispute_ref=provider_dispute_ref
    )
    payment = session.execute(
        select(Payment)
        .where(Payment.provider_account_id == account.id, Payment.provider_payment_ref == state.provider_payment_ref)
        .with_for_update()
    ).scalar_one_or_none()
    if state.status is None or payment is None or not state.provider_payment_ref:
        return None
    row = session.execute(
        select(Dispute).where(Dispute.provider_dispute_ref == state.provider_dispute_ref).with_for_update()
    ).scalar_one_or_none()
    status = "lost" if payment.tender_kind == "bank_debit" else state.status
    ref = {"payment_id": payment.id, "client_id": payment.client_id}
    today = platform.service.location_today(session, payment.location_id)
    if row is None:
        if payment.status != "succeeded":  # only settled money can be disputed (section 7 transitions)
            return None
        row = Dispute(
            payment_id=payment.id, provider_dispute_ref=state.provider_dispute_ref, amount_minor=state.amount_minor,
            currency=platform.service.get_tenant(session).currency, reason_code=state.reason_code,
            opened_at=clock.now(), evidence_due_at=state.evidence_due_at,
        )  # fmt: skip
        session.add(row)
        session.flush()
        payment.status = "disputed"
        for allocation in session.scalars(_live_allocations(PaymentAllocation.payment_id == payment.id)):
            _release(session, allocation, "dispute_opened")
        _post(
            session, "dispute_opened", "dispute", row.id, today, payment.location_id, payment.client_id,
            [("disputed_funds", row.amount_minor, 0, {}), ("funds_received", 0, row.amount_minor, {})],
            payment_id=payment.id,
        )  # fmt: skip
        audit.record(session, "billing.dispute.open", row, location_id=payment.location_id)
        events.publish(session, PaymentDisputed(**ref, dispute_id=row.id), payment.id)
    row.evidence_due_at = state.evidence_due_at or row.evidence_due_at
    if status == "open" or row.status != "open":
        _settle_projections(session, payment, ())
        return row
    row.status, row.closed_at = status, clock.now()
    if status == "won":
        lines = [("funds_received", row.amount_minor, 0, {}), ("disputed_funds", 0, row.amount_minor, {})]
        payment.status = "succeeded"
    else:
        lines = [("client_credit", row.amount_minor, 0, {}), ("disputed_funds", 0, row.amount_minor, {})]
        payment.status = "charged_back"
    _post(
        session, f"dispute_{status}", "dispute", row.id, today, payment.location_id, payment.client_id, lines,
        payment_id=payment.id,
    )  # fmt: skip
    audit.record(
        session, "billing.dispute.close", row, location_id=payment.location_id, changes={"status": ["open", status]}
    )
    events.publish(session, PaymentDisputeClosed(**ref, dispute_id=row.id, outcome=status), payment.id)
    _settle_projections(session, payment, ())
    return row


def release_allocation(session: Session, payment_id: UUID, allocation_id: UUID) -> Payment:
    """Take money back off one item (PAY-01 "unpay"): it returns to the payment as account credit."""
    payment = _lock(session, Payment, payment_id)
    allocation = _get(session, PaymentAllocation, allocation_id)
    if allocation.payment_id != payment.id:
        raise NotFound()
    if allocation.status == "released":
        raise Conflict("This allocation was already released.", code="allocation-released")
    _release(session, allocation, "unapplied")
    audit.record(
        session, "billing.payment.reallocate", payment, location_id=payment.location_id,
        changes={"released_minor": [None, allocation.amount_minor]},
    )  # fmt: skip
    return payment


def void_payment(session: Session, payment_id: UUID, *, reason: str) -> Payment:
    """Void a record-only payment taken by mistake (PAY-04): its allocations are released, then the receipt
    is negated in the ledger, dated today. A processed payment moved real money and must be refunded."""
    payment = _lock(session, Payment, payment_id)
    if not reason.strip():
        raise ValidationFailed("A reason is required.", pointer="/reason")
    if payment.provider_account_id is not None:
        raise Conflict("A processed payment cannot be voided; refund it instead.", code="use-refund")
    if payment.status != "succeeded" or payment.refunded_minor:
        raise Conflict("Only a settled payment with no refunds can be voided.", code="payment-not-voidable")
    for allocation in session.scalars(_live_allocations(PaymentAllocation.payment_id == payment.id)):
        _release(session, allocation, "payment_voided")
    today = platform.service.location_today(session, payment.location_id)
    _post(
        session, "payment_voided", "payment", payment.id, today, payment.location_id, payment.client_id,
        [("client_credit", payment.amount_minor, 0, {}), ("funds_received", 0, payment.amount_minor, {})],
        payment_id=payment.id,
    )  # fmt: skip
    payment.status, payment.voided_at, payment.void_reason = "voided", clock.now(), reason
    payment.voided_by_staff_user_id = _staff_id(session)
    audit.record(
        session, "billing.payment.void", payment, location_id=payment.location_id, reason=reason,
        changes={"status": ["succeeded", "voided"]},
    )  # fmt: skip
    events.publish(session, PaymentVoided(payment_id=payment.id, client_id=payment.client_id), payment.id)
    _settle_projections(session, payment, ())
    return payment


def post_opening_balance(
    session: Session, *, client_id: UUID, location_id: UUID, amount_minor: int, kind: str, as_of: date,
    description: str, key: str, reference: str | None = None, submitted_by: UUID | None = None,
) -> tuple[str, UUID, bool]:  # fmt: skip
    """Internal (imports): a balance carried over from another system, as ledger entries, never a written
    balance. `owed`: an untaxed charge on the uncategorised revenue category with revenue on `as_of`, on its own
    invoice. `credit`: an `external` payment allocated to nothing (the client's account credit), on the tender
    "Opening balance" (disabled, so never offered at the desk), so reports never read it as money taken on the
    import day; `reference` goes in its external reference and `submitted_by` (the importing staff user, id
    only) in its audit row. Refunding it is an external hand-back, never to a card. Idempotent by `key`: it is
    the charge's origin and the payment's idempotency key. Returns (entity, id, created)."""
    if amount_minor <= 0:
        raise ValidationFailed("The amount must be greater than zero.", pointer="/amount_minor")
    if kind == "credit":
        idempotency_key = f"import:{key}"
        if (existing := _payment_by_key(session, idempotency_key)) is not None:
            return "payment", existing.id, False
        payment = take_payment(
            session, client_id=client_id, location_id=location_id, amount_minor=amount_minor, tender_kind="external",
            tender_type_id=_opening_balance_tender(session).id, idempotency_key=idempotency_key, memo=description,
            external_reference=reference, internal_tender=True,
            audit_changes={"submitted_by_staff_user_id": [None, str(submitted_by)]} if submitted_by else None,
        )  # fmt: skip
        return "payment", payment.id, True
    source_id = uuid5(NAMESPACE_URL, f"import:{key}")
    exists_ = session.scalar(select(Charge.id).where(
        Charge.source_context == "imports", Charge.source_type == "opening_balance", Charge.source_id == source_id))  # fmt: skip
    if exists_ is not None:
        return "charge", exists_, False
    charge = post_charge(
        session, client_id=client_id, location_id=location_id, description=description,
        unit_price_minor=amount_minor, source_context="imports", source_type="opening_balance",
        source_id=source_id, revenue_category_id=default_revenue_category(session).id, revenue_on=as_of, tax_ids=(),
    )  # fmt: skip
    if charge.invoice_id is None:
        create_invoice_for_charges(session, [charge.id], origin="system")
    return "charge", charge.id, True


OPENING_BALANCE_TENDER = "Opening balance"


def _opening_balance_tender(session: Session) -> TenderType:
    """The billing-owned tender opening credits are booked on (`system_key` 'opening_balance', one per tenant),
    created disabled on first use. It is found by its key, never its label: a tenant tender already named
    "Opening balance" keeps its name and this one is labelled "Opening balance (import)" instead."""
    stmt = select(TenderType).where(TenderType.system_key == "opening_balance")
    tender = session.scalar(stmt)
    if tender is None:
        ensure_defaults(session)  # first: the plain external tender must stay the kind's default (sort order)
        taken = session.scalar(select(TenderType.id).where(TenderType.label == OPENING_BALANCE_TENDER))
        session.execute(pg_insert(TenderType).values(
            id=new_id(), tenant_id=session.info["tenant_id"], kind="external", system_key="opening_balance",
            label=f"{OPENING_BALANCE_TENDER} (import)" if taken else OPENING_BALANCE_TENDER,
            is_processed=False, is_optional=True, is_enabled=False, sort_order=1000,
        ).on_conflict_do_nothing())  # fmt: skip
        tender = session.scalar(stmt)
        if tender is None:
            raise Conflict("The opening balance payment method could not be created.", code="tender-system")
    return tender


def tax_ids_by_code(session: Session, codes: Iterable[str]) -> dict[str, UUID]:
    """Internal (pos import): tax ids by code, compared without case; unknown codes are absent."""
    wanted = {code.lower() for code in codes}
    rows = session.execute(select(Tax.code, Tax.id).where(func.lower(Tax.code).in_(wanted)))
    return {code.lower(): tax_id for code, tax_id in rows}


def credit_balance(session: Session, client_id: UUID) -> int:
    """A client's account credit (BIL-21): the unapplied remainders of their settled payments, pooled."""
    return _int(
        session,
        select(func.coalesce(func.sum(Payment.unapplied_minor), 0)).where(
            Payment.client_id == client_id, Payment.status == "succeeded"
        ),
    )


def spend_credit(
    session: Session,
    client_id: UUID,
    *,
    invoice_id: UUID | None = None,
    allocations: Allocations | None = None,
    limit: int | None = None,
) -> int:
    """Pay with money on account (BIL-21): allocate from the client's existing payments, oldest first. It
    never creates a payment. Targets are chosen as in allocate(); `limit` caps automatic spending. Returns
    the amount applied."""
    payments = session.scalars(
        select(Payment)
        .where(Payment.client_id == client_id, Payment.status == "succeeded", Payment.unapplied_minor > 0)
        .order_by(Payment.received_at, Payment.id)
        .with_for_update()
    ).all()
    if allocations is not None and sum(amount for _, amount in allocations) > sum(p.unapplied_minor for p in payments):
        raise ValidationFailed(
            "The amounts exceed the credit on account.", pointer="/allocations", code="allocation-exceeds-payment"
        )
    wanted = [[charge_id, amount] for charge_id, amount in allocations or []]
    spent = 0
    for payment in payments:
        if allocations is None:
            if limit is not None and spent >= limit:
                break
            spent += _allocate(session, payment, invoice_id, None, limit=None if limit is None else limit - spent)
            continue
        left, part = payment.unapplied_minor, []
        for target in wanted:
            take = min(left, target[1])
            if take > 0:
                part.append((target[0], take))
                target[1] -= take
                left -= take
        if part:
            spent += _allocate(session, payment, None, part)
    return spent


def refund_credit(
    session: Session,
    client_id: UUID,
    *,
    amount_minor: int,
    reason: str,
    idempotency_key: str,
    location_ids: Iterable[UUID] | None = None,
) -> list[Refund]:
    """Give account credit back (PAY-05): one refund per payment, newest payment first, each to its own
    original method (or as an external record for record-only tenders), grouped by one refund_batch_id.
    `location_ids` (not None) draws only on payments taken at those locations."""
    stmt = select(Payment).where(
        Payment.client_id == client_id, Payment.status == "succeeded", Payment.unapplied_minor > 0
    )
    if location_ids is not None:
        stmt = stmt.where(Payment.location_id.in_(list(location_ids)))
    payments = session.scalars(stmt.order_by(Payment.received_at.desc(), Payment.id.desc())).all()
    if not 0 < amount_minor <= sum(payment.unapplied_minor for payment in payments):
        raise ValidationFailed(
            "The amount exceeds the credit on account.", pointer="/amount_minor", code="refund-exceeds-unapplied"
        )
    batch_id, refunds, left = new_id(), [], amount_minor
    for payment in payments:
        part = min(left, payment.unapplied_minor)
        if part > 0:
            refunds.append(
                refund(
                    session,
                    payment.id,
                    amount_minor=part,
                    reason=reason,
                    refund_batch_id=batch_id,
                    idempotency_key=f"{idempotency_key}:{payment.id}",
                )  # fmt: skip
            )
            left -= part
    return refunds


# --- invoices: edits, regrouping, void, schedule -----------------------------------------------------------


def _invoice_for_edit(session: Session, invoice_id: UUID) -> Invoice:
    invoice = _lock(session, Invoice, invoice_id)
    if invoice.status == "voided":
        raise Conflict("This invoice is voided.", code="invoice-voided")
    return invoice


def _has_live_allocations(session: Session, invoice_id: UUID) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(PaymentAllocation)
            .join(Charge, Charge.id == PaymentAllocation.charge_id)
            .where(Charge.invoice_id == invoice_id, PaymentAllocation.status != "released")
        )
    )


def attach_charges(session: Session, invoice_id: UUID, charge_ids: Sequence[UUID]) -> Invoice:
    """Add uninvoiced items to an invoice (BIL-04). Same location, and only items of the payer or of someone
    already on the invoice: an item of an unrelated client is never billed to this payer by accident."""
    invoice = _invoice_for_edit(session, invoice_id)
    known = set(session.scalars(select(Charge.client_id).where(Charge.invoice_id == invoice.id)))
    known.add(invoice.bill_to_client_id)
    for charge_id in sorted(set(charge_ids)):
        charge = _lock(session, Charge, charge_id, pointer="/charge_ids")
        if charge.status != "active" or charge.invoice_id is not None:
            raise Conflict("An item is already invoiced, reversed or voided.", code="charge-not-invoiceable")
        if charge.location_id != invoice.location_id or charge.client_id not in known:
            raise ValidationFailed(
                "The item belongs to another client or location.", pointer="/charge_ids", code="payer-mismatch"
            )
        charge.invoice_id = invoice.id
    session.flush()
    audit.record(
        session, "billing.invoice.update", invoice, location_id=invoice.location_id,
        changes={"charges_added": [None, len(set(charge_ids))]},
    )  # fmt: skip
    _refresh_invoice(session, invoice.id)
    return invoice


def detach_charge(session: Session, invoice_id: UUID, charge_id: UUID, *, to_invoice_id: UUID | None = None) -> Invoice:
    """Take an item off an invoice (it becomes uninvoiced), or move it to another invoice of the same payer
    and location (the reference's editable "invoice number"). Payments applied to the item move with it."""
    invoice = _invoice_for_edit(session, invoice_id)
    charge = _lock(session, Charge, charge_id)
    if charge.invoice_id != invoice.id:
        raise NotFound()
    if charge.status != "active" or charge.kind == "reversal":
        raise Conflict("A reversed item stays on its invoice.", code="charge-not-reversible")
    target = None
    if to_invoice_id is not None:
        target = _invoice_for_edit(session, _get(session, Invoice, to_invoice_id, pointer="/target_invoice_id").id)
        if (target.bill_to_client_id, target.location_id) != (invoice.bill_to_client_id, invoice.location_id):
            raise ValidationFailed(
                "Both invoices must have the same payer and location.", pointer="/target_invoice_id",
                code="payer-mismatch",
            )  # fmt: skip
    elif charge.applied_minor:
        raise Conflict("Release the payments on this item first.", code="charge-has-payments")
    charge.invoice_id = target.id if target else None
    session.flush()
    audit.record(
        session, "billing.invoice.update", invoice, location_id=invoice.location_id,
        changes={"charge_moved": [str(charge.id), str(target.id) if target else None]},
    )  # fmt: skip
    _refresh_invoice(session, invoice.id)
    if target:
        _refresh_invoice(session, target.id)
    return invoice


def void_invoice(session: Session, invoice_id: UUID, *, reason: str, release_allocations: bool = False) -> Invoice:
    """Void an invoice (BIL-08): one atomic command that detaches every item back to uninvoiced. An invoice
    has no money of its own, so nothing is posted, except the releases when `release_allocations` frees
    payments already applied (they become account credit)."""
    invoice = _invoice_for_edit(session, invoice_id)
    if not reason.strip():
        raise ValidationFailed("A reason is required.", pointer="/reason")
    live = session.scalars(
        _live_allocations(PaymentAllocation.charge_id.in_(select(Charge.id).where(Charge.invoice_id == invoice.id)))
    ).all()
    if live and not release_allocations:
        raise Conflict("Payments are applied to this invoice; release them to void it.", code="invoice-has-payments")
    was = invoice.status
    invoice.status, invoice.voided_at, invoice.void_reason = "voided", clock.now(), reason
    # Totals are projections of the invoice's items, and a voided invoice has none.
    invoice.voided_by_staff_user_id, invoice.total_minor, invoice.balance_minor = _staff_id(session), 0, 0
    invoice.past_due_since_on, invoice.dunning_state, invoice.next_attempt_on = None, "none", None
    invoice.version += 1
    session.flush()
    for allocation in live:
        _release(session, allocation, "invoice_voided")
    session.execute(update(Charge).where(Charge.invoice_id == invoice.id).values(invoice_id=None))
    audit.record(
        session, "billing.invoice.void", invoice, location_id=invoice.location_id, reason=reason,
        changes={"status": [was, "voided"]},
    )  # fmt: skip
    events.publish(
        session, InvoiceVoided(invoice_id=invoice.id, bill_to_client_id=invoice.bill_to_client_id), invoice.id
    )
    session.flush()
    session.expire_all()
    return invoice


def reassign_payer(session: Session, invoice_id: UUID, bill_to_client_id: UUID) -> Invoice:
    """Bill an invoice to someone else (BIL-05). Refused while money is applied: it belongs to the old
    payer's payments."""
    invoice = _invoice_for_edit(session, invoice_id)
    clients.service.require_active(session, bill_to_client_id, pointer="/bill_to_client_id")
    if _has_live_allocations(session, invoice.id):
        raise Conflict("Payments are applied to this invoice.", code="invoice-has-payments")
    was, invoice.bill_to_client_id = invoice.bill_to_client_id, bill_to_client_id
    invoice.version += 1
    audit.record(
        session, "billing.invoice.reassign_payer", invoice, location_id=invoice.location_id,
        changes={"bill_to_client_id": [str(was), str(bill_to_client_id)]},
    )  # fmt: skip
    session.flush()
    return invoice


def schedule_of(session: Session, invoice_id: UUID) -> list[PaymentSchedule]:
    return list(
        session.scalars(
            select(PaymentSchedule)
            .where(PaymentSchedule.invoice_id == invoice_id)
            .order_by(PaymentSchedule.due_on, PaymentSchedule.seq)
        )
    )


def equal_instalments(total_minor: int, start_on: date, unit: str, count: int) -> list[tuple[date, int]]:
    """Internal: `count` equal instalments of a total, one per `unit` from `start_on` (REG-10 payment plans)."""
    return plans.generate(total_minor, start_on, 1, unit, count)


def set_schedule(session: Session, invoice_id: UUID, rows: Sequence[tuple[date, int]], *, basis: dict) -> Invoice:
    """Replace an invoice's instalment plan (BIL-06). The instalments must sum to the invoice total and none
    may be due before the invoice date; the database enforces both again at commit. `basis` (the generator's
    inputs, or how many rows were typed) goes to the audit event, not to storage."""
    invoice = _invoice_for_edit(session, invoice_id)
    rows = sorted(rows)
    if not 1 <= len(rows) <= plans.MAX_INSTALMENTS:
        raise ValidationFailed("A schedule has between 1 and 120 instalments.", pointer="/instalments")
    total = max(invoice.total_minor, 0)
    if sum(amount for _, amount in rows) != total or any(amount <= 0 for _, amount in rows) != (total == 0):
        raise ValidationFailed(
            f"The instalments must be positive and add up to the invoice total ({total}).",
            pointer="/instalments", code="schedule-not-balanced",
        )  # fmt: skip
    if rows[0][0] < invoice.invoice_on:
        raise ValidationFailed(
            "An instalment cannot be due before the invoice date.", pointer="/instalments",
            code="schedule-not-balanced",
        )  # fmt: skip
    _write_schedule(session, invoice, rows)
    audit.record(
        session, "billing.payment_schedule.manage", invoice, location_id=invoice.location_id,
        changes={"instalments": [None, len(rows)], **{key: [None, str(value)] for key, value in basis.items()}},
    )  # fmt: skip
    _refresh_invoice(session, invoice.id)
    return invoice


def _write_schedule(session: Session, invoice: Invoice, rows: Sequence[tuple[date, int]]) -> None:
    session.execute(PaymentSchedule.__table__.delete().where(PaymentSchedule.invoice_id == invoice.id))
    session.add_all(
        PaymentSchedule(invoice_id=invoice.id, seq=seq, due_on=due_on, amount_minor=amount)
        for seq, (due_on, amount) in enumerate(rows, start=1)
    )
    session.flush()


def _sync_schedule(session: Session, invoice: Invoice, total: int, applied: int, provisional: int) -> None:
    """Keep the plan equal to the invoice total (ADR 0003 section 3), then project what is covered, the
    invoice's due date (its earliest uncovered instalment) and whether it is past due."""
    rows = schedule_of(session, invoice.id)
    today = platform.service.location_today(session, invoice.location_id)
    plan = [(row.due_on, row.amount_minor) for row in rows]
    if not rows or sum(amount for _, amount in plan) != max(total, 0):
        # A new invoice gets one instalment on its due date; a changed total is rebalanced.
        plan = plans.rebalance(plan, total, applied, today if rows else invoice.due_on)
        _write_schedule(session, invoice, plan)
        rows = schedule_of(session, invoice.id)
    covered = plans.cover([row.amount_minor for row in rows], applied)
    overdue = 0
    for row, amount in zip(rows, covered, strict=True):
        row.covered_minor = amount
        if row.due_on < today:
            overdue += row.amount_minor - amount
    open_rows = [row for row in rows if row.covered_minor < row.amount_minor]
    invoice.due_on = max((open_rows[0] if open_rows else rows[-1]).due_on, invoice.invoice_on)
    if overdue > provisional:
        if invoice.past_due_since_on is None:
            invoice.past_due_since_on = today
            events.publish(
                session, InvoicePastDue(invoice_id=invoice.id, bill_to_client_id=invoice.bill_to_client_id), invoice.id
            )
    elif overdue <= 0:
        invoice.past_due_since_on = None
    # else a pending bank debit covers what is overdue: the dunning clock pauses, it does not restart (the usual
    # practice in Stripe Billing and Chargebee). The invoice is `payment_pending`, so reminders, the portal
    # lockout and non-payment suspension skip it meanwhile; if the debit fails they resume from the first
    # overdue day instead of a fresh one, so a debit that keeps failing cannot hold off dunning forever.
    session.flush()


def refresh_invoice(session: Session, invoice_id: UUID) -> None:
    """Re-derive an invoice's projections; the daily job calls it so past-due status follows the calendar."""
    _refresh_invoice(session, invoice_id)


def charge_states(session: Session, charge_ids: Iterable[UUID]) -> dict[UUID, dict]:
    """Internal read for owning contexts: status, invoice, invoice status and total of each charge."""
    ids = list(charge_ids)
    rows = session.execute(
        select(Charge.id, Charge.status, Charge.invoice_id, Invoice.status, Charge.total_minor)
        .outerjoin(Invoice, Invoice.id == Charge.invoice_id)
        .where(Charge.id.in_(ids))
    ).all() if ids else []  # fmt: skip
    return {
        row[0]: {"status": row[1], "invoice_id": row[2], "invoice_status": row[3], "total_minor": row[4]}
        for row in rows
    }


def excluded_tax_ids(session: Session, charge_id: UUID) -> list[UUID]:
    """Internal: the taxes a charge was posted without, so a re-post can keep the same choice."""
    return list(
        session.scalars(select(ChargeTax.tax_id).where(ChargeTax.charge_id == charge_id, ChargeTax.is_excluded))
    )


def invoice_charge_ids(session: Session, invoice_id: UUID) -> list[UUID]:
    """Internal: the active charges grouped under an invoice."""
    return list(session.scalars(select(Charge.id).where(Charge.invoice_id == invoice_id, Charge.status == "active")))


def charge_ids_for_source(session: Session, source_context: str, source_type: str, source_id: UUID) -> list[UUID]:
    """Internal: the charges a selling context raised for one of its records, in line order."""
    return list(
        session.scalars(
            select(Charge.id)
            .where(
                Charge.source_context == source_context,
                Charge.source_type == source_type,
                Charge.source_id == source_id,
            )
            .order_by(Charge.source_line_no)
        )
    )


def category_taxes(session: Session, revenue_category_id: UUID, on: date) -> list[tuple[UUID, Decimal]]:
    """(tax_id, rate) of the taxes post_charge would apply to a line of this category on that date; callers
    quote with it and pass the unticked ones to post_charge as exclude_tax_ids (rentals)."""
    return taxes_in_force(session, on, revenue_category_id=revenue_category_id)


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


def taxes_in_force(
    session: Session, on: date, *, revenue_category_id: UUID | None = None, tax_ids: Iterable[UUID] | None = None
) -> list[tuple[UUID, Decimal]]:
    """(tax_id, rate) for each tax mapped to the category (or each of `tax_ids`, when given) that applies on
    the date: not deactivated by then, with the latest rate whose effective_from_on is not after it. A tax with
    no rate yet does not apply. Internal: other contexts quote the tax a charge will carry with it."""
    if tax_ids is not None:
        taxes = session.scalars(select(Tax).where(Tax.id.in_(list(tax_ids))).order_by(Tax.code))
    else:
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


def _tender(session: Session, kind: str, tender_type_id: UUID | None = None) -> TenderType:
    """The tenant's tender row for a built-in kind, created with its default label on first use; or the
    row named by id (a tenant-labelled record-only tender such as "PayPal"), which must be of that kind."""
    if tender_type_id is not None:
        tender = _get(session, TenderType, tender_type_id, pointer="/tender_type_id")
        if tender.kind != kind:
            raise ValidationFailed("That payment method is of another kind.", pointer="/tender_type_id")
        return tender
    if kind not in _TENDERS:
        raise ValidationFailed("Unknown payment method.", pointer="/tender_kind")
    stmt = (select(TenderType).where(TenderType.kind == kind, TenderType.system_key.is_(None))
            .order_by(TenderType.sort_order, TenderType.id).limit(1))  # fmt: skip
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
        # The fake connects itself, but only for a tenant that never had an account: one that was
        # disconnected stays disconnected until an Owner connects a processor again.
        ever = session.scalar(select(func.count()).select_from(ProviderAccount))
        if get_settings().payments.provider != "fake" or ever:
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
        register_account_lookup(session, account)
    return account


def register_account_lookup(session: Session, account: ProviderAccount) -> None:
    """Publish (provider, account ref) -> tenant to the global lookup that routes inbound webhooks."""
    session.execute(
        text("SELECT app.register_provider_account(:provider, :ref)"),
        {"provider": account.provider, "ref": account.provider_account_ref},
    )


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
    _settle_projections(session, payment, {charge.invoice_id})


def _apply_state(session: Session, payment: Payment, state: PaymentState) -> None:
    """The one place a payment changes status (ADR 0003 section 7). A transition the table does not allow is
    ignored, which makes this safe to replay and to receive out of order."""
    status = "failed" if state.outcome == "declined" else state.outcome
    payment.client_secret = state.client_secret  # transient: handed to the payer's browser, never stored
    if status not in _TRANSITIONS.get(payment.status, ()):
        return
    was, payment.status = payment.status, status
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
    elif status in ("failed", "cancelled"):
        payment.failure_category, payment.failure_message = state.failure_category, state.failure_message
        for allocation in session.scalars(_live_allocations(PaymentAllocation.payment_id == payment.id)):
            charge = session.get(Charge, allocation.charge_id)
            allocation.status, allocation.released_at, allocation.release_reason = (
                "released", clock.now(), "payment_failed",
            )  # fmt: skip
            charge.applied_minor -= allocation.amount_minor
            invoice_ids.add(charge.invoice_id)
        if status == "failed":
            events.publish(session, PaymentFailed(**ref, failure_category=state.failure_category), payment.id)
    elif status == "processing":
        events.publish(session, PaymentProcessing(**ref), payment.id)
    _settle_projections(session, payment, invoice_ids)
    for hook in PAYMENT_HOOKS:
        hook(session, payment, was)


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
    if invoice.status == "paid":
        invoice.dunning_state, invoice.next_attempt_on = "none", None
    _sync_schedule(session, invoice, total, applied, provisional)
    if invoice.status == "paid" and was != "paid":
        events.publish(
            session, InvoicePaid(invoice_id=invoice.id, bill_to_client_id=invoice.bill_to_client_id), invoice.id
        )


def _invoice_detail(session: Session, invoice: Invoice) -> dict:
    charges = session.scalars(select(Charge).where(Charge.invoice_id == invoice.id).order_by(Charge.id)).all()
    return {**{c.key: getattr(invoice, c.key) for c in Invoice.__table__.columns}, "charges": charges}


def _payment_detail(session: Session, payment: Payment) -> dict:
    session.flush()
    session.refresh(payment)
    allocations = session.scalars(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id).order_by(PaymentAllocation.id)
    ).all()
    refunds = session.scalars(select(Refund).where(Refund.payment_id == payment.id).order_by(Refund.id)).all()
    return {
        **{c.key: getattr(payment, c.key) for c in Payment.__table__.columns},
        "allocations": allocations, "refunds": refunds, "client_secret": getattr(payment, "client_secret", None),
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


def source_totals(session: Session, source_context: str, source_type: str, source_ids: Iterable[UUID]) -> dict:
    """Internal read for payroll commission (STF-09, STF-10): per source id, the invoiced and the paid amount
    of its live charges (adjustments and reversals included, voided charges left out)."""
    ids = list(source_ids)
    rows = session.execute(
        select(Charge.source_id, func.sum(Charge.total_minor), func.sum(Charge.applied_minor))
        .where(
            Charge.source_context == source_context, Charge.source_type == source_type,
            Charge.source_id.in_(ids), Charge.status != "voided",
        )
        .group_by(Charge.source_id)
    ).all() if ids else []  # fmt: skip
    return {row[0]: {"invoiced_minor": int(row[1]), "paid_minor": int(row[2])} for row in rows}
