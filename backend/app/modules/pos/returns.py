"""Returns, refunds and voids (POS-16): per line and quantity, through billing.

Billing money is immutable, so a return changes the line's charge: a partial quantity is `adjust_charge`
(quantity and a pro-rated discount), the rest of a line is `reverse`. Either releases the applied money back
to the payments as credit; the refund mode then decides where it goes:

- `original_tenders`: back through the sale's own payment legs, newest first (a card to the card, a
  record-only tender handed back), up to what each still holds;
- `cash` / `external`: handed back from the drawer or outside it, drawn on the same legs;
- `account_credit`: nothing leaves; the money stays on the client's account.

Anything paid with account credit goes back to account credit in every mode, and a pay-later balance is
simply reduced (nothing was paid). Restocked units go back through a `return` stock movement. A void is a
full return of every remaining unit to the original tenders, with restock, under pos.sale.void.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, DomainError, ValidationFailed
from app.modules import billing
from app.modules.pos import inventory, sales
from app.modules.pos.domain.pricing import round_half_up
from app.modules.pos.events import SaleReturned
from app.modules.pos.models import PosReturn, PosReturnLine, PosSale, PosSaleLine, Product
from app.modules.pos.service import get_row, open_drawer

_RETURN = "pos.sale.return"


def create_return(session: Session, principal: Principal, sale_id: UUID, data: dict, *, key: str = _RETURN) -> dict:
    sale = get_row(session, PosSale, sale_id, lock=True)
    authorize(principal, key, location_id=sale.location_id)
    if sale.status != "completed":
        raise Conflict("Only a completed sale can be returned.")
    mode = data["refund_mode"]
    if mode != "account_credit":
        authorize(principal, "billing.refund.create", location_id=sale.location_id)
    if mode == "account_credit" and sale.client_id is None:
        raise ValidationFailed("A walk-in sale cannot be refunded to an account.", pointer="/refund_mode",
                               code="client-required")  # fmt: skip
    lines = {line.id: line for line in session.scalars(
        select(PosSaleLine).where(PosSaleLine.pos_sale_id == sale.id).with_for_update())}  # fmt: skip
    requested = data["lines"]
    if not requested or len({r["pos_sale_line_id"] for r in requested}) != len(requested):
        raise ValidationFailed("List each line to return once.", pointer="/lines")
    for index, item in enumerate(requested):
        line = lines.get(item["pos_sale_line_id"])
        if line is None:
            raise ValidationFailed("This line is not on the sale.", pointer=f"/lines/{index}/pos_sale_line_id")
        if line.line_kind == "equipment":
            raise ValidationFailed("Return rented equipment through its loan.", pointer=f"/lines/{index}")
        if item["quantity"] > line.quantity - line.returned_quantity:
            raise ValidationFailed(f"Only {line.quantity - line.returned_quantity} left to return.",
                                   pointer=f"/lines/{index}/quantity", code="return-exceeds-sold")  # fmt: skip

    drawer = open_drawer(session, sale.register_id)
    row = PosReturn(
        pos_sale_id=sale.id, location_id=sale.location_id, register_id=sale.register_id,
        drawer_session_id=drawer.id if drawer else None, refund_mode=mode, amount_minor=0,
        reason=data.get("reason"), processed_by_staff_user_id=principal.staff_user_id, processed_at=clock.now(),
    )  # fmt: skip
    session.add(row)
    session.flush()
    reason = data.get("reason") or f"POS return on sale {sale.invoice_number}"
    for item in requested:
        line = lines[item["pos_sale_line_id"]]
        amount, adjusted = _return_line(session, line, item["quantity"], reason)
        restock = item.get("is_restocked", True)
        return_line = PosReturnLine(
            pos_return_id=row.id, pos_sale_line_id=line.id, quantity=item["quantity"], amount_minor=amount,
            is_restocked=restock, adjustment_charge_id=adjusted,
        )  # fmt: skip
        session.add(return_line)
        session.flush()
        product = session.get(Product, line.product_id) if line.product_id else None
        if restock and product is not None and product.is_stock_tracked:
            inventory.move(
                session, product, sale.location_id, kind="return", reason="return",
                delta=item["quantity"] * product.units_per_sale, pos_return_line_id=return_line.id,
                staff_user_id=principal.staff_user_id,
            )  # fmt: skip
        row.amount_minor += amount

    row.refunded_minor, row.cash_refunded_minor = _refund(session, sale, row, mode, reason)
    remaining = sum(line.quantity - line.returned_quantity for line in lines.values() if line.line_kind == "product")
    rented = any(line.line_kind == "equipment" for line in lines.values())
    sale.return_state = "full" if remaining == 0 and not rented else "partial"
    if remaining == 0 and sale.coupon_code:
        billing.catalogue.release_coupon(session, f"pos:pos_sale:{sale.id}")
    audit.record(session, key, row, location_id=sale.location_id, changes={
        "amount_minor": [None, row.amount_minor], "refund_mode": [None, mode], "refunded_minor": [None, row.refunded_minor],
    })  # fmt: skip
    events.publish(session, SaleReturned(pos_sale_id=sale.id, pos_return_id=row.id, client_id=sale.client_id), row.id)
    session.flush()
    return next(r for r in sales.sale_detail(session, sale)["returns"] if r["id"] == row.id)


def _return_line(session: Session, line: PosSaleLine, quantity: int, reason: str) -> tuple[int, UUID | None]:
    """Shrink or reverse the line's charge; return (amount released, replacement charge id or None). The
    charge's current total is the line total less what earlier returns of this line released."""
    returned = session.scalar(
        select(func.coalesce(func.sum(PosReturnLine.amount_minor), 0)).where(PosReturnLine.pos_sale_line_id == line.id)
    )
    current = line.total_minor - int(returned)  # SUM(bigint) is numeric
    left = line.quantity - line.returned_quantity - quantity
    line.returned_quantity += quantity
    if left == 0:
        billing.service.reverse(session, line.charge_id, reason=reason)
        return current, None
    discount = round_half_up(Decimal(line.discount_minor) * left / line.quantity)
    replacement = billing.service.adjust_charge(
        session, line.charge_id, reason=reason, quantity=left, discount_minor=discount
    )
    line.charge_id = replacement.id
    return current - replacement.total_minor, replacement.id


def _refund(session: Session, sale: PosSale, row: PosReturn, mode: str, reason: str) -> tuple[int, int]:
    if mode == "account_credit" or row.amount_minor == 0:
        return 0, 0
    remaining, refunded, cash = row.amount_minor, 0, 0
    legs = [t for t in sales._tenders(session, sale.id) if t.status == "captured" and t.tender == "payment"]
    for leg in reversed(legs):
        if remaining == 0:
            break
        amount = min(remaining, billing.service.refundable_minor(session, leg.payment_id))
        if amount <= 0:
            continue
        processed = leg.tender_kind in sales.PROCESSED_KINDS
        method = "original" if mode == "original_tenders" and processed else "external"
        refund = billing.service.refund(
            session, leg.payment_id, amount_minor=amount, reason=reason, method=method,
            idempotency_key=f"pos:return:{row.id}:{leg.payment_id}", refund_batch_id=row.refund_batch_id,
        )  # fmt: skip
        if refund.status in ("failed", "cancelled"):
            raise DomainError("The card refund was declined; choose another refund mode.", status=502,
                              code="refund-failed")  # fmt: skip
        remaining -= amount
        refunded += amount
        if mode == "cash" or (mode == "original_tenders" and leg.tender_kind == "cash"):
            cash += amount
    return refunded, cash


def void_sale(session: Session, principal: Principal, sale_id: UUID, data: dict) -> dict:
    """Undo a whole completed sale: every unit not yet returned, back to the original tenders, restocked."""
    sale = get_row(session, PosSale, sale_id)
    authorize(principal, "pos.sale.void", location_id=sale.location_id)
    if sale.return_state == "full":
        raise Conflict("Everything on this sale has already been returned.", code="already-returned")
    lines = session.scalars(
        select(PosSaleLine).where(PosSaleLine.pos_sale_id == sale.id, PosSaleLine.line_kind == "product")
    ).all()
    requested = [
        {"pos_sale_line_id": line.id, "quantity": line.quantity - line.returned_quantity}
        for line in lines if line.quantity > line.returned_quantity
    ]  # fmt: skip
    if not requested:
        raise Conflict("Nothing on this sale can be voided at the register.", code="already-returned")
    reason = data.get("reason") or "Voided at the register"
    return create_return(session, principal, sale.id, {"refund_mode": "original_tenders", "reason": reason,
                                                        "lines": requested}, key="pos.sale.void")  # fmt: skip
