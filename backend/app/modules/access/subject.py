"""access's side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). A merge moves
check-ins and credentials to the survivor. Erasure keeps the check-in log (visit history, counted visits) and
revokes every credential, which wipes app-card secrets."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.access import service
from app.modules.access.models import CheckIn, Credential


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    for model in (CheckIn, Credential):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))


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
    }  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    live = session.scalars(select(Credential).where(Credential.client_id == client_id, Credential.status == "active"))
    revoked = 0
    for row in live.all():
        service._revoke(session, row, None)
        revoked += 1
    kept = len(session.scalars(select(CheckIn.id).where(CheckIn.client_id == client_id)).all())
    return {"retained_check_ins": kept, "revoked_credentials": revoked}


_TABLES = ("check_in", "credential")
clients.merge.register_merge_handler("access", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("access", tables=_TABLES, export=_export, erase=_erase)
