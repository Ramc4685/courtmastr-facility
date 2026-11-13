"""Leagues' side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2). A merge moves
captaincies, fee payers and roster places to the survivor; where both records are active on the same team the
merged record's place is removed. Fee shares move too, except where the survivor already has a share on that team:
that share stays on the merged tombstone, like the ledger. Erasure keeps billed team entries and fee shares (money
history) and past roster rows, drops the client as a team captain and takes them off every active roster."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.leagues.models import CompetitionTeam, RosterEntry, Team, TeamFeeShare


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    r = RosterEntry
    held = set(session.scalars(select(r.competition_team_id).where(r.client_id == survivor_id, r.status == "active")))
    for row in session.scalars(select(r).where(r.client_id == loser_id, r.status == "active")).all():
        if row.competition_team_id in held:
            row.status = "removed"
    session.flush()
    session.execute(update(r).where(r.client_id == loser_id).values(client_id=survivor_id))
    session.execute(update(Team).where(Team.captain_client_id == loser_id).values(captain_client_id=survivor_id))
    session.execute(
        update(CompetitionTeam).where(CompetitionTeam.fee_client_id == loser_id).values(fee_client_id=survivor_id)
    )
    s = TeamFeeShare
    shared = select(s.competition_team_id).where(s.client_id == survivor_id)
    session.execute(
        update(s).where(s.client_id == loser_id, s.competition_team_id.not_in(shared)).values(client_id=survivor_id)
    )


def _export(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(select(RosterEntry).where(RosterEntry.client_id == client_id))
    teams = session.scalars(select(Team).where(Team.captain_client_id == client_id))
    return {
        "roster_entries": [
            {"competition_team_id": str(r.competition_team_id), "role": r.role, "status": r.status,
             "jersey_number": r.jersey_number, "position": r.position}
            for r in rows
        ],
        "captain_of": [{"team_id": str(t.id), "name": t.name} for t in teams],
        "fee_shares": [
            {"competition_team_id": str(f.competition_team_id), "amount_minor": f.amount_minor}
            for f in session.scalars(select(TeamFeeShare).where(TeamFeeShare.client_id == client_id))
        ],
    }  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    captain = session.execute(
        update(Team).where(Team.captain_client_id == client_id).values(captain_client_id=None)
    ).rowcount
    r = RosterEntry
    removed = session.execute(
        update(r).where(r.client_id == client_id, r.status == "active").values(status="removed")
    ).rowcount
    return {"captaincies_cleared": captain, "removed_roster_entries": removed}


_TABLES = ("team", "competition_team", "roster_entry", "team_fee_share")
clients.merge.register_merge_handler("leagues", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("leagues", tables=_TABLES, export=_export, erase=_erase)
