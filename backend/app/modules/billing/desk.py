"""Staff commands of build module 8 for items, invoices, payments and account credit: each authorizes the
principal on the loaded record (outside its location scope is 404), then calls the internal function in
`service` that does the work. The kernel's staff commands stay in `service.py`."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.modules import clients
from app.modules.billing import catalogue, service
from app.modules.billing.domain import schedule as plans
from app.modules.billing.domain.money import net_amount, tax_amount
from app.modules.billing.models import Charge, ChargeTax, Invoice, Payment, Refund, RevenueCategory

_TEXT_FIELDS = ("description", "additional_description", "internal_remarks", "service_starts_on", "service_ends_on")
_MONEY_FIELDS = ("quantity", "unit_price_minor", "discount_minor", "exclude_tax_ids")

# --- items -------------------------------------------------------------------------------------------------


def list_charges(session: Session, principal: Principal, query: ListQuery) -> dict:
    """The billing-items workbench (BIL-02) and the uninvoiced "carts" (BIL-03): `is_uninvoiced=true` with
    `location_id` is the location's cart, with `created_by_staff_user_id` a person's. Voided items are hidden
    unless asked for by status."""
    authorize(principal, "billing.charge.read")
    stmt = select(Charge)
    uninvoiced = query.filters.pop("is_uninvoiced", None)
    if uninvoiced is not None:
        wanted = str(uninvoiced).lower() == "true"
        stmt = stmt.where(Charge.invoice_id.is_(None) if wanted else Charge.invoice_id.is_not(None))
        if wanted:
            stmt = stmt.where(Charge.status == "active", Charge.kind != "reversal")
    if query.filters.pop("is_open", None) is not None:
        stmt = stmt.where(Charge.status == "active", Charge.applied_minor < Charge.total_minor)
    if "status" not in query.filters:
        stmt = stmt.where(Charge.status != "voided")
    return paginate(
        session, stmt, query, id_column=Charge.id,
        sort_fields={"bill_on": Charge.bill_on, "created_at": Charge.created_at, "revenue_on": Charge.revenue_on},
        default_sort="-bill_on",
        filter_fields={
            "client_id": Charge.client_id, "invoice_id": Charge.invoice_id, "location_id": Charge.location_id,
            "status": Charge.status, "kind": Charge.kind, "source_id": Charge.source_id,
            "revenue_category_id": Charge.revenue_category_id, "bill_on": Charge.bill_on,
            "created_by_staff_user_id": Charge.created_by_staff_user_id,
        },
        search=(Charge.description,),
    )  # fmt: skip


def _charge_detail(session: Session, charge: Charge) -> dict:
    taxes = session.scalars(select(ChargeTax).where(ChargeTax.charge_id == charge.id).order_by(ChargeTax.id)).all()
    return {**{c.key: getattr(charge, c.key) for c in Charge.__table__.columns}, "taxes": taxes}


def get_charge(session: Session, principal: Principal, charge_id: UUID) -> dict:
    authorize(principal, "billing.charge.read")
    return _charge_detail(session, service._get(session, Charge, charge_id))


def preview_charge(session: Session, principal: Principal, data: dict) -> dict:
    """What an item would cost, tax by tax, without creating it."""
    authorize(principal, "billing.charge.create", location_id=data["location_id"])
    service._location_in_scope(session, principal, data["location_id"])
    quantity = Decimal(data.get("quantity", 1))
    net = net_amount(quantity, data["unit_price_minor"], data.get("discount_minor", 0))
    if net < 0:
        raise ValidationFailed("The discount cannot exceed the line amount.", pointer="/discount_minor")
    category = (
        service._get(session, RevenueCategory, data["revenue_category_id"], pointer="/revenue_category_id")
        if data.get("revenue_category_id")
        else service.default_revenue_category(session)
    )
    on = data.get("revenue_on") or service.platform.service.location_today(session, data["location_id"])
    excluded = set(data.get("exclude_tax_ids") or ())
    taxes = [
        {"tax_id": tax_id, "rate": rate, "is_excluded": tax_id in excluded,
         "amount_minor": 0 if tax_id in excluded else tax_amount(net, rate)}
        for tax_id, rate in service._taxes_in_force(session, category.id, on)
    ]  # fmt: skip
    tax_total = sum(row["amount_minor"] for row in taxes)
    return {"net_minor": net, "tax_minor": tax_total, "total_minor": net + tax_total, "taxes": taxes}


def create_charge(session: Session, principal: Principal, data: dict) -> Charge:
    """A manual billing item (BIL-01), optionally with a coupon code. A hand-typed discount needs the custom
    discount permission; a coupon needs only the preset one. The coupon comes off after the manual discount
    and before tax."""
    authorize(principal, "billing.charge.create", location_id=data["location_id"])
    service._location_in_scope(session, principal, data["location_id"])
    data = dict(data)
    code = data.pop("coupon_code", None)
    if data.get("discount_minor"):
        authorize(principal, "billing.discount.apply_custom", location_id=data["location_id"])
    source_id, coupon_id = new_id(), None
    if code:
        authorize(principal, "billing.discount.apply_preset", location_id=data["location_id"])
        net = net_amount(Decimal(data.get("quantity", 1)), data["unit_price_minor"], data.get("discount_minor", 0))
        coupon_id, parts = catalogue.redeem_coupon(
            session, code, redemption_key=f"billing:manual:{source_id}", line_nets=[max(net, 0)],
            redeemer_client_id=data["client_id"],
        )  # fmt: skip
        data["discount_minor"] = data.get("discount_minor", 0) + parts[0]
    return service.post_charge(
        session, **data, source_context="billing", source_type="manual", source_id=source_id, coupon_id=coupon_id
    )


def update_charge(session: Session, principal: Principal, charge_id: UUID, data: dict) -> dict:
    """Text and service-period fields change in place. Any money field (quantity, price, discount, which
    taxes apply) replaces the item with an adjustment (see service.adjust_charge), needs a reason and the
    price-override permission, and returns the row that now stands for the item."""
    charge = service._lock(session, Charge, charge_id)
    authorize(principal, "billing.charge.update", location_id=charge.location_id)
    service._require_live(charge)
    money = {key: data[key] for key in _MONEY_FIELDS if data.get(key) is not None}
    for key in _TEXT_FIELDS:
        if key in data:
            setattr(charge, key, data[key])
    changes = audit.diff(charge)
    if changes:
        audit.record(session, "billing.charge.update", charge, location_id=charge.location_id, changes=changes)
        session.flush()
    if money:
        authorize(principal, "billing.charge.override_price", location_id=charge.location_id)
        if not data.get("reason"):
            raise ValidationFailed("Changing an amount needs a reason.", pointer="/reason")
        charge = service.adjust_charge(session, charge.id, reason=data["reason"], **money)
    return _charge_detail(session, charge)


def void_charge(session: Session, principal: Principal, charge_id: UUID, data: dict) -> Charge:
    charge = service._get(session, Charge, charge_id)
    authorize(principal, "billing.charge.void", location_id=charge.location_id)
    service.void_charge(session, charge_id, reason=data["reason"])
    session.refresh(charge)
    return charge


# --- invoices ----------------------------------------------------------------------------------------------


def _invoice(session: Session, principal: Principal, invoice_id: UUID, key: str) -> Invoice:
    invoice = service._get(session, Invoice, invoice_id)
    authorize(principal, key, location_id=invoice.location_id)
    return invoice


def _detail(session: Session, invoice_id: UUID) -> dict:
    session.expire_all()
    return service._invoice_detail(session, service._get(session, Invoice, invoice_id))


def update_invoice(session: Session, principal: Principal, invoice_id: UUID, data: dict) -> dict:
    """Dates, comments, organisation name and the autopay flag (BIL-04, BIL-17). `version` guards against two
    people editing at once. The due date of an invoice with several instalments is its schedule's business."""
    _invoice(session, principal, invoice_id, "billing.invoice.update")
    invoice = service._invoice_for_edit(session, invoice_id)
    if data.get("version") is not None and data["version"] != invoice.version:
        raise Conflict("Someone else changed this invoice; reload it.", code="stale-version")
    rows = service.schedule_of(session, invoice.id)
    for key in ("comments", "organization_name"):  # nullable text: an explicit null clears it
        if key in data:
            setattr(invoice, key, data[key])
    for key in ("is_autopay", "invoice_on"):
        if data.get(key) is not None:
            setattr(invoice, key, data[key])
    if data.get("due_on") is not None:
        if len(rows) > 1:
            raise Conflict("This invoice has instalments; change its payment schedule.", code="invoice-has-schedule")
        rows[0].due_on = data["due_on"]
    if min(row.due_on for row in rows) < invoice.invoice_on:
        raise ValidationFailed("The due date cannot be before the invoice date.", pointer="/due_on")
    invoice.version += 1
    audit.record(
        session, "billing.invoice.update", invoice, location_id=invoice.location_id, changes=audit.diff(invoice)
    )
    session.flush()
    service.refresh_invoice(session, invoice.id)
    return _detail(session, invoice_id)


def add_invoice_charges(session: Session, principal: Principal, invoice_id: UUID, data: dict) -> dict:
    _invoice(session, principal, invoice_id, "billing.invoice.update")
    service.attach_charges(session, invoice_id, data["charge_ids"])
    return _detail(session, invoice_id)


def remove_invoice_charge(session: Session, principal: Principal, invoice_id: UUID, charge_id: UUID) -> dict:
    _invoice(session, principal, invoice_id, "billing.invoice.update")
    service.detach_charge(session, invoice_id, charge_id)
    return _detail(session, invoice_id)


def move_invoice_charge(session: Session, principal: Principal, invoice_id: UUID, charge_id: UUID, data: dict) -> dict:
    _invoice(session, principal, invoice_id, "billing.invoice.update")
    service.detach_charge(session, invoice_id, charge_id, to_invoice_id=data["target_invoice_id"])
    return _detail(session, invoice_id)


def void_invoice(session: Session, principal: Principal, invoice_id: UUID, data: dict) -> dict:
    _invoice(session, principal, invoice_id, "billing.invoice.void")
    service.void_invoice(session, invoice_id, **data)
    return _detail(session, invoice_id)


def reassign_invoice_payer(session: Session, principal: Principal, invoice_id: UUID, data: dict) -> dict:
    """BIL-05. Until `clients` exposes household relationships, any active client may be chosen; the
    permission (Manager and above) is the guard, and the change is audited."""
    _invoice(session, principal, invoice_id, "billing.invoice.reassign_payer")
    service.reassign_payer(session, invoice_id, data["bill_to_client_id"])
    return _detail(session, invoice_id)


def mark_invoice_paid(session: Session, principal: Principal, invoice_id: UUID, data: dict, key: str) -> dict:
    """BIL-23: record that the invoice was paid elsewhere. It never sets a status: it inserts a record-only
    `external` payment for the balance and allocates it."""
    invoice = service._get(session, Invoice, invoice_id)
    authorize(principal, "billing.payment.take")
    if invoice.status not in ("open", "partially_paid") or invoice.balance_minor <= 0:
        raise Conflict("Nothing is owed on this invoice.", code="invoice-not-payable")
    payment = service.take_payment(
        session, client_id=invoice.bill_to_client_id, location_id=invoice.location_id,
        amount_minor=invoice.balance_minor, tender_kind="external", invoice_id=invoice.id,
        external_reference=data.get("external_reference"), memo=data.get("memo"),
        idempotency_key=f"mark-paid:{principal.actor_id}:{key}",
    )  # fmt: skip
    return service._payment_detail(session, payment)


def get_schedule(session: Session, principal: Principal, invoice_id: UUID) -> dict:
    authorize(principal, "billing.invoice.read")
    invoice = service._get(session, Invoice, invoice_id)
    return {
        "invoice_id": invoice.id,
        "total_minor": invoice.total_minor,
        "instalments": service.schedule_of(session, invoice.id),
    }


def put_schedule(session: Session, principal: Principal, invoice_id: UUID, data: dict) -> dict:
    _invoice(session, principal, invoice_id, "billing.payment_schedule.manage")
    rows = [(row["due_on"], row["amount_minor"]) for row in data["instalments"]]
    service.set_schedule(session, invoice_id, rows, basis={"entered": len(rows)})
    return get_schedule(session, principal, invoice_id)


def generate_schedule(session: Session, principal: Principal, invoice_id: UUID, data: dict) -> dict:
    """Equal instalments from a start date, one every N days, weeks, half months, months or years."""
    invoice = _invoice(session, principal, invoice_id, "billing.payment_schedule.manage")
    rows = plans.generate(max(invoice.total_minor, 0), data["start_on"], data["every"], data["unit"], data["count"])
    service.set_schedule(session, invoice_id, rows, basis=data)
    return get_schedule(session, principal, invoice_id)


# --- payments and credit -----------------------------------------------------------------------------------


def _payment(session: Session, principal: Principal, payment_id: UUID, key: str) -> Payment:
    payment = service._get(session, Payment, payment_id)
    authorize(principal, key, location_id=payment.location_id)
    return payment


def cancel_payment(session: Session, principal: Principal, payment_id: UUID) -> dict:
    authorize(principal, "billing.payment.take")
    service._get(session, Payment, payment_id)
    return service._payment_detail(session, service.cancel_payment(session, payment_id))


def release_allocation(session: Session, principal: Principal, payment_id: UUID, allocation_id: UUID) -> dict:
    _payment(session, principal, payment_id, "billing.payment.reallocate")
    return service._payment_detail(session, service.release_allocation(session, payment_id, allocation_id))


def void_payment(session: Session, principal: Principal, payment_id: UUID, data: dict) -> dict:
    _payment(session, principal, payment_id, "billing.payment.void")
    return service._payment_detail(session, service.void_payment(session, payment_id, reason=data["reason"]))


def list_refunds(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "billing.payment.read")
    return paginate(
        session, select(Refund), query, id_column=Refund.id,
        sort_fields={"refund_on": Refund.refund_on, "created_at": Refund.created_at}, default_sort="-created_at",
        filter_fields={
            "client_id": Refund.client_id, "payment_id": Refund.payment_id, "status": Refund.status,
            "location_id": Refund.location_id, "refund_batch_id": Refund.refund_batch_id,
        },
    )  # fmt: skip


def apply_account_credit(session: Session, principal: Principal, client_id: UUID, data: dict) -> dict:
    """Pay items with money on account (BIL-21): explicit amounts per item, or an invoice, or the client's
    open items oldest first."""
    authorize(principal, "billing.credit.apply")
    clients.service.get(session, client_id)
    rows = [(row["charge_id"], row["amount_minor"]) for row in data.get("allocations") or []]
    applied = service.spend_credit(session, client_id, invoice_id=data.get("invoice_id"), allocations=rows or None)
    return {
        "client_id": client_id,
        "applied_minor": applied,
        "credit_minor": service.credit_balance(session, client_id),
    }


def refund_account_credit(session: Session, principal: Principal, client_id: UUID, data: dict, key: str) -> list:
    authorize(principal, "billing.refund.create")
    clients.service.get(session, client_id)
    return service.refund_credit(
        session,
        client_id,
        amount_minor=data["amount_minor"],
        reason=data["reason"],
        idempotency_key=f"staff:{principal.actor_id}:{key}",
    )
