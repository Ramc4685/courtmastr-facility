"""Equipment rental (POS-17, POS-18): checkout through a sale line, the loans list, return with fees.

A rental is a sale line of kind `equipment`; completing the sale opens one loan per line and holds the units
(`on_loan_count`, guarded by a CHECK so two sales cannot lend the same last unit). The loan is due
`rental_days` after the local checkout date at the item's return time, else at the location's closing time
that day, else 23:59 (README assumption). Returning late posts a late fee per unit per started day late;
returning lost (or damaged, when asked) posts the replacement fee. Fees go onto the client's account as
billing charges (origin `pos`/`equipment_loan`), payable at the desk or the register like any open charge.
"""

import math
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, platform
from app.modules.pos import catalogue
from app.modules.pos.events import EquipmentLoaned, EquipmentReturned
from app.modules.pos.models import EquipmentItem, EquipmentLoan, PosSale, PosSaleLine
from app.modules.pos.service import get_row

_RENT = "pos.equipment.rent"


def _due_at(session: Session, principal: Principal, item: EquipmentItem) -> datetime:
    zone = ZoneInfo(platform.service.get_location(session, principal, item.location_id).time_zone)
    day = platform.service.location_today(session, item.location_id) + timedelta(days=item.rental_days)
    wall = item.return_time
    if wall is None:
        days = platform.service.get_facility_hours(session, principal, item.location_id)["days"]
        hours = next((d for d in days if d.weekday == day.isoweekday()), None)
        wall = hours.closes_time if hours is not None and not hours.is_closed and hours.closes_time else "23:59"
    hour, minute = (int(part) for part in wall.split(":")[:2])
    if hour == 24:  # a midnight close
        day, hour = day + timedelta(days=1), 0
    return datetime.combine(day, time(hour, minute), zone).astimezone(ZoneInfo("UTC"))


def check_out(session: Session, principal: Principal, sale: PosSale, line: PosSaleLine) -> EquipmentLoan:
    """Internal to sale completion: hold the units and open the loan."""
    item = get_row(session, EquipmentItem, line.equipment_item_id, lock=True)
    if not item.is_active or item.unit_count - item.on_loan_count < line.quantity:
        raise Conflict(f"Only {item.unit_count - item.on_loan_count} of {item.name} available.",
                       code="equipment-unavailable")  # fmt: skip
    item.on_loan_count += line.quantity
    loan = EquipmentLoan(
        equipment_item_id=item.id, client_id=sale.client_id, location_id=item.location_id, pos_sale_line_id=line.id,
        quantity=line.quantity, checked_out_at=clock.now(), due_at=_due_at(session, principal, item),
    )  # fmt: skip
    session.add(loan)
    session.flush()
    audit.record(session, _RENT, loan, location_id=loan.location_id,
                 changes={"status": [None, "open"], "quantity": [None, loan.quantity]})  # fmt: skip
    events.publish(
        session,
        EquipmentLoaned(equipment_loan_id=loan.id, equipment_item_id=item.id, client_id=loan.client_id),
        loan.id,
    )
    return loan


def loan_out(session: Session, loan: EquipmentLoan, now: datetime | None = None) -> dict:
    item = session.get(EquipmentItem, loan.equipment_item_id)
    client = clients.service.get(session, loan.client_id)
    now = now or clock.now()
    return {
        **{c.key: getattr(loan, c.key) for c in EquipmentLoan.__table__.columns},
        "item_name": item.name, "asset_code": item.asset_code, "client_name": clients.service.display_name(client),
        "is_overdue": loan.status == "open" and now > loan.due_at,
    }  # fmt: skip


def list_loans(session: Session, principal: Principal, query: ListQuery, *, is_overdue: bool | None = None) -> dict:
    authorize(principal, _RENT)
    stmt = scope_query(select(EquipmentLoan), principal, EquipmentLoan.location_id)
    if is_overdue is not None:
        late = (EquipmentLoan.status == "open") & (EquipmentLoan.due_at < clock.now())
        stmt = stmt.where(late if is_overdue else ~late)
    page = paginate(
        session, stmt, query, id_column=EquipmentLoan.id,
        sort_fields={"due_at": EquipmentLoan.due_at, "checked_out_at": EquipmentLoan.checked_out_at},
        default_sort="due_at",
        filter_fields={
            "status": EquipmentLoan.status, "location_id": EquipmentLoan.location_id,
            "client_id": EquipmentLoan.client_id, "equipment_item_id": EquipmentLoan.equipment_item_id,
        },
    )  # fmt: skip
    page["data"] = [loan_out(session, row) for row in page["data"]]
    return page


def _loan(session: Session, principal: Principal, loan_id: UUID, *, lock: bool = False) -> EquipmentLoan:
    loan = get_row(session, EquipmentLoan, loan_id, lock=lock)
    authorize(principal, _RENT, location_id=loan.location_id)
    return loan


def get_loan(session: Session, principal: Principal, loan_id: UUID) -> dict:
    return loan_out(session, _loan(session, principal, loan_id))


def propose_fees(loan: EquipmentLoan, item: EquipmentItem, *, outcome: str, condition: str | None,
                 now: datetime) -> dict:  # fmt: skip
    """The late fee is per unit per started day past due; replacement is proposed when lost or damaged."""
    days_late = max(0, math.ceil((now - loan.due_at).total_seconds() / 86400))
    return {
        "equipment_loan_id": loan.id, "is_late": days_late > 0, "days_late": days_late,
        "proposed_late_fee_minor": item.late_fee_minor * loan.quantity * days_late if outcome == "returned" else 0,
        "proposed_replacement_fee_minor": (
            item.replacement_fee_minor * loan.quantity if outcome == "lost" or condition == "damaged" else 0
        ),
    }  # fmt: skip


def quote_return(session: Session, principal: Principal, loan_id: UUID, *, outcome: str = "returned",
                 return_condition: str | None = None) -> dict:  # fmt: skip
    loan = _loan(session, principal, loan_id)
    item = session.get(EquipmentItem, loan.equipment_item_id)
    return propose_fees(loan, item, outcome=outcome, condition=return_condition, now=clock.now())


def return_loan(session: Session, principal: Principal, loan_id: UUID, data: dict) -> dict:
    """Close the loan as `returned` (good or damaged) or `lost`. Fees are what staff confirm (the quote is
    only a proposal) and become uninvoiced charges on the client; a fee needs billing.charge.create. Lost
    units leave the item's count (README)."""
    loan = _loan(session, principal, loan_id, lock=True)
    if loan.status != "open":
        raise Conflict("This loan is already closed.")
    outcome, condition = data["outcome"], data.get("return_condition")
    if outcome == "returned" and condition is None:
        raise ValidationFailed("Say what condition it came back in.", pointer="/return_condition")
    if outcome == "lost":
        condition = None
    item = get_row(session, EquipmentItem, loan.equipment_item_id, lock=True)
    revenue = (
        catalogue.equipment_revenue_category(session, item) or billing.service.default_revenue_category(session).id
    )
    for line_no, key, label in ((1, "late_fee_minor", "Late return"), (2, "replacement_fee_minor", "Replacement")):
        if not data.get(key):
            continue
        authorize(principal, "billing.charge.create", location_id=loan.location_id)
        charge = billing.service.post_charge(
            session, client_id=loan.client_id, location_id=loan.location_id, description=f"{label}: {item.name}",
            unit_price_minor=data[key], revenue_category_id=revenue, source_context="pos",
            source_type="equipment_loan", source_id=loan.id, source_line_no=line_no,
        )  # fmt: skip
        setattr(loan, "late_fee_charge_id" if line_no == 1 else "replacement_fee_charge_id", charge.id)
    item.on_loan_count -= loan.quantity
    if outcome == "lost":
        if item.unit_count - loan.quantity >= 1:
            item.unit_count -= loan.quantity
        else:  # shortcut: the last units are gone; the item stays (history) but can no longer be rented
            item.is_active = False
    now = clock.now()
    loan.status, loan.returned_at, loan.returned_by_staff_user_id = outcome, now, principal.staff_user_id
    loan.return_condition = condition
    if data.get("note") is not None:
        loan.note = data["note"]
    audit.record(session, _RENT, loan, location_id=loan.location_id, changes=audit.diff(loan))
    events.publish(
        session, EquipmentReturned(equipment_loan_id=loan.id, equipment_item_id=item.id, client_id=loan.client_id),
        loan.id,
    )  # fmt: skip
    session.flush()
    return loan_out(session, loan, now)
