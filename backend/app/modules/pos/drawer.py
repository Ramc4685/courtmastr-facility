"""Cash drawer sessions (POS-12 cash handling; our design, the reference documents none, and it covers the
likely intent of POS-20). One open session per register. Expected cash at close is the opening float plus the
cash legs of the sales completed in the session minus the cash handed back by returns made in it; the counted
amount and the variance (counted - expected) are recorded, never adjusted."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict
from app.core.pagination import ListQuery, paginate
from app.modules.pos.events import DrawerClosed
from app.modules.pos.models import DrawerSession, PosReturn, PosSale, PosSaleTender, Register
from app.modules.pos.service import get_row, open_drawer

_OPERATE = "pos.drawer.operate"


def session_out(session: Session, row: DrawerSession) -> dict:
    out = {c.key: getattr(row, c.key) for c in DrawerSession.__table__.columns}
    out["cash_sales_minor"], out["cash_refunds_minor"] = _cash(session, row.id)
    expected = row.expected_cash_minor
    if expected is None:
        expected = row.opening_float_minor + out["cash_sales_minor"] - out["cash_refunds_minor"]
        out["expected_cash_minor"] = expected  # running figure while open
    out["variance_minor"] = None if row.counted_cash_minor is None else row.counted_cash_minor - expected
    return out


def _cash(session: Session, drawer_session_id: UUID) -> tuple[int, int]:
    sales = session.scalar(
        select(func.coalesce(func.sum(PosSaleTender.amount_minor), 0))
        .join(PosSale, PosSale.id == PosSaleTender.pos_sale_id)
        .where(
            PosSale.drawer_session_id == drawer_session_id,
            PosSale.status == "completed",
            PosSaleTender.status == "captured",
            PosSaleTender.tender_kind == "cash",
        )  # fmt: skip
    )
    refunds = session.scalar(
        select(func.coalesce(func.sum(PosReturn.cash_refunded_minor), 0)).where(
            PosReturn.drawer_session_id == drawer_session_id
        )
    )
    return int(sales), int(refunds)


def open_session(session: Session, principal: Principal, register_id: UUID, data: dict) -> dict:
    register = get_row(session, Register, register_id, lock=True)  # the lock serialises two "open" clicks
    authorize(principal, _OPERATE, location_id=register.location_id)
    if not register.is_active:
        raise Conflict("This register is not active.", code="register-inactive")
    if open_drawer(session, register.id) is not None:
        raise Conflict("The drawer is already open.", code="drawer-already-open")
    row = DrawerSession(
        register_id=register.id, location_id=register.location_id, opened_by_staff_user_id=principal.staff_user_id,
        opening_float_minor=data.get("opening_float_minor", 0), note=data.get("note"), opened_at=clock.now(),
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(session, _OPERATE, row, location_id=row.location_id,
                 changes={"status": [None, "open"], "opening_float_minor": [None, row.opening_float_minor]})  # fmt: skip
    return session_out(session, row)


def close_session(session: Session, principal: Principal, drawer_session_id: UUID, data: dict) -> dict:
    row = get_row(session, DrawerSession, drawer_session_id, lock=True)
    authorize(principal, _OPERATE, location_id=row.location_id)
    if row.status != "open":
        raise Conflict("This drawer session is already closed.")
    busy = session.scalar(
        select(func.count())
        .select_from(PosSaleTender)
        .join(PosSale, PosSale.id == PosSaleTender.pos_sale_id)
        .where(
            PosSale.register_id == row.register_id,
            PosSale.status == "draft",
            PosSaleTender.status == "captured",
            PosSaleTender.tender == "payment",
        )  # fmt: skip
    )
    if busy:
        raise Conflict("A sale on this register has money taken; complete it first.", code="open-draft-sale")
    sales, refunds = _cash(session, row.id)
    row.expected_cash_minor = row.opening_float_minor + sales - refunds
    row.counted_cash_minor = data["counted_cash_minor"]
    row.closed_at, row.closed_by_staff_user_id, row.status = clock.now(), principal.staff_user_id, "closed"
    if data.get("note") is not None:
        row.note = data["note"]
    audit.record(session, _OPERATE, row, location_id=row.location_id, changes=audit.diff(row))
    events.publish(session, DrawerClosed(drawer_session_id=row.id, register_id=row.register_id), row.id)
    session.flush()
    return session_out(session, row)


def reconcile_session(session: Session, principal: Principal, drawer_session_id: UUID, data: dict) -> dict:
    """A manager accepts a closed session's counted variance (P1); the count itself never changes."""
    row = get_row(session, DrawerSession, drawer_session_id, lock=True)
    authorize(principal, "pos.drawer.reconcile", location_id=row.location_id)
    if row.status != "closed":
        raise Conflict("Close and count the drawer first.")
    if row.reconciled_at is not None:
        raise Conflict("This drawer session is already reconciled.")
    row.reconciled_at, row.reconciled_by_staff_user_id = clock.now(), principal.staff_user_id
    row.reconcile_note = data.get("note")
    audit.record(session, "pos.drawer.reconcile", row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return session_out(session, row)


def open_no_sale(session: Session, principal: Principal, register_id: UUID, data: dict) -> None:
    """Record a no-sale drawer opening (audited). Kicking a physical drawer needs the printer bridge (POS-15,
    v2), so this is the audit trail only."""
    register = get_row(session, Register, register_id)
    authorize(principal, "pos.drawer.open_no_sale", location_id=register.location_id)
    audit.record(session, "pos.drawer.open_no_sale", register, location_id=register.location_id,
                 changes={"drawer_opened": [None, True]}, reason=data.get("reason"))  # fmt: skip


def list_sessions(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "pos.sale.read")
    page = paginate(
        session, scope_query(select(DrawerSession), principal, DrawerSession.location_id), query,
        id_column=DrawerSession.id, sort_fields={"opened_at": DrawerSession.opened_at}, default_sort="-opened_at",
        filter_fields={
            "register_id": DrawerSession.register_id, "location_id": DrawerSession.location_id,
            "status": DrawerSession.status, "opened_at": DrawerSession.opened_at,
        },
    )  # fmt: skip
    page["data"] = [session_out(session, row) for row in page["data"]]
    return page
