"""access's side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). A merge moves
check-ins and credentials to the survivor and keeps the stricter of the two access modes (a ban survives); open
kiosk match tokens of the merged client are dropped. Erasure keeps the check-in log (visit history, counted
visits), revokes every credential, which wipes app-card secrets, and drops the access mode and match tokens. Entry
codes and held codes (`entry_code_hold`) follow the merge; erasure revokes live codes, unlinks every code and deletes
the person's holds, and scrubs their id from building event text, so the log no longer leads to them."""

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.access import building, service
from app.modules.access.models import CheckIn, ClientAccess, Credential, EntryCode, EntryCodeHold, KioskMatch

_STRICT = ("always_deny", "normal", "always_admit")


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    # a hold the survivor already has for the same booking wins (one hold per booking and person)
    session.execute(delete(EntryCodeHold).where(EntryCodeHold.client_id == loser_id, EntryCodeHold.booking_id.in_(
        select(EntryCodeHold.booking_id).where(EntryCodeHold.client_id == survivor_id))))  # fmt: skip
    for model in (CheckIn, Credential, EntryCode, EntryCodeHold):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))
    session.execute(delete(KioskMatch).where(KioskMatch.client_id == loser_id))
    loser_id, survivor_id = UUID(str(loser_id)), UUID(str(survivor_id))
    # The stricter access mode survives a merge, so a banned duplicate cannot be merged away (or widen access).
    modes = dict(
        session.execute(
            select(ClientAccess.client_id, ClientAccess.access_mode).where(
                ClientAccess.client_id.in_((loser_id, survivor_id))
            )
        ).all()
    )
    keep = min((modes.get(loser_id, "normal"), modes.get(survivor_id, "normal")), key=_STRICT.index)
    session.execute(delete(ClientAccess).where(ClientAccess.client_id == loser_id))
    if survivor_id in modes:
        session.execute(update(ClientAccess).where(ClientAccess.client_id == survivor_id).values(access_mode=keep))
    elif keep != "normal":
        session.add(ClientAccess(client_id=survivor_id, access_mode=keep))


def _export(session: Session, client_id: UUID) -> dict:
    visits = session.scalars(select(CheckIn).where(CheckIn.client_id == client_id).order_by(CheckIn.checked_in_at))
    cards = session.scalars(select(Credential).where(Credential.client_id == client_id))
    return {
        "check_ins": [
            {"location_id": str(r.location_id), "checked_in_at": r.checked_in_at.isoformat(), "result": r.result,
             "channel": r.channel}
            for r in visits
        ],
        "credentials": [{"kind": r.kind, "status": r.status, "issued_at": r.issued_at.isoformat()} for r in cards],
        "access_mode": service.access_mode(session, client_id),
        "entry_codes": building.export_client_codes(session, client_id),
        "entry_code_holds": building.export_client_holds(session, client_id),
    }  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    live = session.scalars(select(Credential).where(Credential.client_id == client_id, Credential.status == "active"))
    revoked = 0
    for row in live.all():
        service._revoke(session, row, None)
        revoked += 1
    kept = len(session.scalars(select(CheckIn.id).where(CheckIn.client_id == client_id)).all())
    session.execute(delete(ClientAccess).where(ClientAccess.client_id == client_id))
    session.execute(delete(KioskMatch).where(KioskMatch.client_id == client_id))
    codes = building.erase_client_codes(session, client_id)
    return {"retained_check_ins": kept, "revoked_credentials": revoked, "revoked_entry_codes": codes}


_TABLES = ("check_in", "credential", "client_access", "kiosk_match", "entry_code", "entry_code_hold")
clients.merge.register_merge_handler("access", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("access", tables=_TABLES, export=_export, erase=_erase)
# events first: a spent code goes only once no building event names it
platform.retention.register_purge("building_event", building.purge_building_events)
platform.retention.register_purge("entry_code", building.purge_spent_codes)
platform.retention.register_purge("entry_code_hold", building.purge_old_holds)
