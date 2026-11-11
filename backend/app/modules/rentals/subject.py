"""Rentals' side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). Parties,
rental charges and plan purchases move to the survivor. The plan ledger is append-only: its `used_by` stays
on the merged record (a tombstone). Erasure keeps all of it: these are financial records with no free text."""

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.rentals.models import RentalBookingCharge, RentalParty, RentalPlanPurchase


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    p = RentalParty
    shared = select(p.rental_booking_id).where(p.client_id == survivor_id)
    both = session.scalars(select(p).where(p.client_id == loser_id, p.rental_booking_id.in_(shared))).all()
    for row in both:  # both were on the rental: one party row remains, charged if either was
        if row.is_charged:
            session.execute(
                update(p)
                .where(p.rental_booking_id == row.rental_booking_id, p.client_id == survivor_id)
                .values(is_charged=True)
            )
    session.execute(delete(p).where(p.id.in_([row.id for row in both])))
    for model in (RentalParty, RentalBookingCharge, RentalPlanPurchase):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))


def _export(session: Session, client_id: UUID) -> dict:
    plans = session.scalars(select(RentalPlanPurchase).where(RentalPlanPurchase.client_id == client_id))
    rentals = session.scalar(select(func.count()).select_from(RentalParty).where(RentalParty.client_id == client_id))
    return {
        "rental_count": rentals,
        "rental_plans": [
            {"status": r.status, "price_minor": r.price_minor, "starts_on": r.starts_on and r.starts_on.isoformat(),
             "balance": r.balance is not None and str(r.balance)}
            for r in plans
        ],
    }  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    p = RentalPlanPurchase
    kept = session.execute(update(p).where(p.client_id == client_id).values(is_auto_renew=False)).rowcount
    return {"retained_plan_purchases": kept}


_TABLES = ("rental_party", "rental_booking_charge", "rental_plan_purchase", "rental_plan_ledger_entry")
clients.merge.register_merge_handler("rentals", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("rentals", tables=_TABLES, export=_export, erase=_erase)
