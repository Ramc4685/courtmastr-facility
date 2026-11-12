"""access's side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). A merge moves
check-ins and credentials to the survivor and keeps the stricter of the two access modes (a ban survives); open
kiosk match tokens of the merged client are dropped. Erasure keeps the check-in log (visit history, counted
visits), revokes every credential, which wipes app-card secrets, and drops the access mode and match tokens."""

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.access import service
from app.modules.access.models import CheckIn, ClientAccess, Credential, KioskMatch

_STRICT = ("always_deny", "normal", "always_admit")


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    for model in (CheckIn, Credential):
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
    return {"retained_check_ins": kept, "revoked_credentials": revoked}


_TABLES = ("check_in", "credential", "client_access", "kiosk_match")
clients.merge.register_merge_handler("access", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("access", tables=_TABLES, export=_export, erase=_erase)
