"""Rentals' side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). Parties,
rental charges, plan purchases, plan shares and locker leases move to the survivor. The plan ledger is append-only: its `used_by` stays
on the merged record (a tombstone). Erasure keeps all of it (financial records with no free text) but ends
auto-renewal and the client's live plan shares."""

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.modules import clients, platform
from app.modules.rentals.models import (
    LockerLease,
    RentalBookingCharge,
    RentalParty,
    RentalPlanPurchase,
    RentalPlanShare,
)


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
    for model in (RentalParty, RentalBookingCharge, RentalPlanPurchase, LockerLease):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))
    share = RentalPlanShare
    for row in session.scalars(select(share).where(share.client_id == loser_id)):
        duplicate = session.scalar(select(share.id).where(
            share.rental_plan_purchase_id == row.rental_plan_purchase_id, share.client_id == survivor_id,
            share.revoked_at.is_(None),
        ))  # fmt: skip
        if row.revoked_at is None and duplicate is not None:
            row.revoked_at = clock.now()  # the survivor already holds this share
        session.flush()
        row.client_id = survivor_id
    session.flush()
    own = select(RentalPlanPurchase.client_id).where(RentalPlanPurchase.id == share.rental_plan_purchase_id)
    session.execute(  # a share with oneself ends
        update(share).where(share.client_id == survivor_id, share.revoked_at.is_(None),
                            share.client_id == own.scalar_subquery()).values(revoked_at=clock.now())
    )  # fmt: skip


def _export(session: Session, client_id: UUID) -> dict:
    plans = session.scalars(select(RentalPlanPurchase).where(RentalPlanPurchase.client_id == client_id))
    rentals = session.scalar(select(func.count()).select_from(RentalParty).where(RentalParty.client_id == client_id))
    leases = session.scalars(select(LockerLease).where(LockerLease.client_id == client_id))
    return {
        "rental_count": rentals,
        "locker_leases": [{"starts_on": r.starts_on.isoformat(), "ends_on": r.ends_on.isoformat(),
                           "fee_minor": r.fee_minor} for r in leases],
        "shared_rental_plan_count": session.scalar(select(func.count()).select_from(RentalPlanShare).where(
            RentalPlanShare.client_id == client_id, RentalPlanShare.revoked_at.is_(None))),
        "rental_plans": [
            {"status": r.status, "price_minor": r.price_minor, "starts_on": r.starts_on and r.starts_on.isoformat(),
             "balance": r.balance is not None and str(r.balance)}
            for r in plans
        ],
    }  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    p = RentalPlanPurchase
    kept = session.execute(update(p).where(p.client_id == client_id).values(is_auto_renew=False)).rowcount
    revoked = session.execute(update(RentalPlanShare).where(
        RentalPlanShare.client_id == client_id, RentalPlanShare.revoked_at.is_(None)
    ).values(revoked_at=clock.now())).rowcount  # fmt: skip
    return {"retained_plan_purchases": kept, "revoked_plan_shares": revoked}


_TABLES = (
    "rental_party", "rental_booking_charge", "rental_plan_purchase", "rental_plan_ledger_entry", "rental_plan_share",
    "locker_lease",
)  # fmt: skip
clients.merge.register_merge_handler("rentals", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("rentals", tables=_TABLES, export=_export, erase=_erase)
