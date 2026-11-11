"""POS's side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). Sales and
equipment loans are financial and stock records: they move on a merge and stay, without notes, on erasure."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.pos.models import EquipmentLoan, PosSale


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    for model in (PosSale, EquipmentLoan):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))


def _export(session: Session, client_id: UUID) -> dict:
    sales = session.scalars(select(PosSale).where(PosSale.client_id == client_id, PosSale.status == "completed"))
    loans = session.scalars(select(EquipmentLoan).where(EquipmentLoan.client_id == client_id))
    return {
        "pos_sales": [
            {"invoice_number": r.invoice_number, "total_minor": r.total_minor, "completed_at": r.completed_at.isoformat()}
            for r in sales
        ],
        "equipment_loans": [
            {"checked_out_at": r.checked_out_at.isoformat(), "status": r.status, "quantity": r.quantity} for r in loans
        ],
    }  # fmt: skip


def _erase_precheck(session: Session, client_id: UUID) -> list[dict]:
    loan = EquipmentLoan
    if session.scalar(select(loan.id).where(loan.client_id == client_id, loan.status == "open").limit(1)):
        return [{"code": "equipment-on-loan", "detail": "The client still has rented equipment out."}]
    return []


def _erase(session: Session, client_id: UUID) -> dict:
    kept = session.execute(update(PosSale).where(PosSale.client_id == client_id).values(note=None)).rowcount
    session.execute(update(EquipmentLoan).where(EquipmentLoan.client_id == client_id).values(note=None))
    return {"retained_sales": kept}


_TABLES = ("pos_sale", "equipment_loan")
clients.merge.register_merge_handler("pos", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("pos", tables=_TABLES, export=_export, erase=_erase, precheck=_erase_precheck)
