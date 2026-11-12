"""leagues depth (Phase 14 chip B1): venues mapped to facility resources (RES-06), team scheduling preferences
(LGE-10), per-competition league staff and scorekeepers (LGE-26, PLT-11), ladders (LGE-28), formula stats and
player stats (LGE-07), the team fee split across players (REG-26), publishing a program group as a competition
(REG-14), the captain's portal roster and printable game cards (LGE-16).

Same gates as `service`: location rows on their own `location_id`, competition children on their competition's,
stat tables tenant-wide under `leagues.competition.manage` (reads need the key, writes `authorize_tenant_wide`).
"""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as Db

from app.core import audit
from app.core.auth import Principal, authorize, scope_query
from app.core.auth.permissions import authorize_tenant_wide
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.pdf import Column, Document, local_date
from app.modules import billing, clients, platform, programs, resources
from app.modules.leagues import service as core
from app.modules.leagues.domain import formula
from app.modules.leagues.models import (
    Competition,
    CompetitionStaff,
    CompetitionTeam,
    Game,
    GameOfficial,
    LadderPosition,
    Official,
    PlayerStat,
    RosterEntry,
    Sport,
    StatDefinition,
    StatTable,
    Team,
    TeamFeeShare,
    TeamPreference,
    Venue,
)
from app.modules.leagues.service import CARDS, GAMES, GENERATE, MANAGE, RESULTS, ROSTER, TEAMS

# --- venues (RES-06) --------------------------------------------------------------------------------------------


def _check_resources(session: Db, location_id: UUID, ids: list[UUID]) -> list[UUID]:
    found = {r.id for r in resources.service.in_location(session, location_id, ids=ids)}
    if not ids or found != set(ids) or len(set(ids)) != len(ids):
        raise ValidationFailed("Unknown or repeated resource at this location.", pointer="/resource_ids")
    return ids


def list_venues(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, MANAGE)
    v = Venue
    return paginate(
        session, scope_query(select(v), principal, v.location_id), query, id_column=v.id,
        sort_fields={"name": v.name}, default_sort="name",
        filter_fields={"location_id": v.location_id, "is_active": v.is_active}, search=(v.name,),
    )  # fmt: skip


def get_venue(session: Db, principal: Principal, venue_id: UUID) -> Venue:
    return core._scoped(session, principal, Venue, venue_id, MANAGE)


def create_venue(session: Db, principal: Principal, data: dict) -> Venue:
    location_id = core._location(session, principal, data.pop("location_id"))
    authorize(principal, MANAGE, location_id=location_id)
    _check_resources(session, location_id, data["resource_ids"])
    row = Venue(location_id=location_id, **core._given(data))
    session.add(row)
    session.flush()
    audit.record(session, MANAGE, row, location_id=location_id, changes={"name": [None, row.name]})
    return row


def update_venue(session: Db, principal: Principal, venue_id: UUID, data: dict) -> Venue:
    row = core._scoped(session, principal, Venue, venue_id, MANAGE, lock=True)
    if data.get("resource_ids") is not None:
        _check_resources(session, row.location_id, data["resource_ids"])
    changes = core._apply(row, core._given(data, ("description",)))
    audit.record(session, MANAGE, row, location_id=row.location_id, changes=changes)
    session.flush()
    return row


def delete_venue(session: Db, principal: Principal, venue_id: UUID) -> None:
    """A venue with games is kept for their history: deactivate it instead (409 in-use)."""
    row = core._scoped(session, principal, Venue, venue_id, MANAGE, lock=True)
    if session.scalar(select(func.count()).select_from(Game).where(Game.venue_id == row.id)):
        raise Conflict("The venue has games; deactivate it instead.", code="in-use")
    audit.record(session, MANAGE, row, location_id=row.location_id, changes={"deleted": [False, True]})
    session.delete(row)
    session.flush()


# --- team scheduling preferences (LGE-10) -----------------------------------------------------------------------


def _check_preference(session: Db, competition: Competition, index: int, pref: dict) -> None:
    kind, value = pref["kind"], pref["value"]
    try:
        if kind == "date":
            date.fromisoformat(value)
        elif kind == "weekday":
            if not 1 <= int(value) <= 7:
                raise ValueError
        elif kind == "time":
            start, end = value.split("-")
            if time.fromisoformat(start) >= time.fromisoformat(end):
                raise ValueError
        else:
            place = UUID(value)
            venue = core._get(session, Venue, place)
            at_venue = venue is not None and venue.location_id == competition.location_id
            if not at_venue and not resources.service.in_location(session, competition.location_id, ids=[place]):
                raise ValueError
    except ValueError as exc:
        raise ValidationFailed(
            "Use YYYY-MM-DD, a weekday 1-7, HH:MM-HH:MM or a court or venue at this location.",
            pointer=f"/preferences/{index}/value",
        ) from exc


def list_team_preferences(session: Db, principal: Principal, competition_team_id: UUID) -> list[TeamPreference]:
    entry, _ = core._child(session, principal, CompetitionTeam, competition_team_id, GENERATE)
    stmt = select(TeamPreference).where(TeamPreference.competition_team_id == entry.id)
    return list(session.scalars(stmt.order_by(TeamPreference.created_at, TeamPreference.id)))


def replace_team_preferences(
    session: Db, principal: Principal, competition_team_id: UUID, data: dict
) -> list[TeamPreference]:
    """Replace the entry's preferences: soft inputs to the generator, never hard blocks (README)."""
    entry, competition = core._child(session, principal, CompetitionTeam, competition_team_id, GENERATE, lock=True)
    for index, pref in enumerate(data["preferences"]):
        _check_preference(session, competition, index, pref)
    before = len(list_team_preferences(session, principal, entry.id))
    session.execute(delete(TeamPreference).where(TeamPreference.competition_team_id == entry.id))
    session.add_all(TeamPreference(competition_team_id=entry.id, **pref) for pref in data["preferences"])
    audit.record(
        session, GENERATE, entry, location_id=competition.location_id,
        changes={"preferences": [before, len(data["preferences"])]},
    )  # fmt: skip
    session.flush()
    return list_team_preferences(session, principal, entry.id)


# --- league staff and scorekeepers (LGE-26, PLT-11) -------------------------------------------------------------


def list_competition_staff(session: Db, principal: Principal, competition_id: UUID) -> list[CompetitionStaff]:
    competition = core._competition(session, principal, competition_id, MANAGE)
    stmt = select(CompetitionStaff).where(CompetitionStaff.competition_id == competition.id)
    return list(session.scalars(stmt.order_by(CompetitionStaff.created_at, CompetitionStaff.id)))


def list_staff_candidates(session: Db, principal: Principal, competition_id: UUID) -> list[dict]:
    """Who may be assigned: active staff who work at the competition's location (names only, no staff read key)."""
    competition = core._competition(session, principal, competition_id, MANAGE)
    return [{"id": i, "name": n} for i, n in platform.service.staff_users_at(session, competition.location_id)]


def replace_competition_staff(
    session: Db, principal: Principal, competition_id: UUID, data: dict
) -> list[CompetitionStaff]:
    """Replace who runs the competition. A scorekeeper (the result key without the game key) then reaches only
    the games of competitions they are assigned to; sign-in is the tenant's usual sign-in, SSO included."""
    competition = core._competition(session, principal, competition_id, MANAGE, lock=True)
    seen = set()
    for index, member in enumerate(data["staff"]):
        if member["staff_user_id"] in seen or not platform.service.staff_user_exists(session, member["staff_user_id"]):
            raise ValidationFailed("Unknown or repeated staff user.", pointer=f"/staff/{index}/staff_user_id")
        seen.add(member["staff_user_id"])
    before = len(list_competition_staff(session, principal, competition.id))
    session.execute(delete(CompetitionStaff).where(CompetitionStaff.competition_id == competition.id))
    session.add_all(CompetitionStaff(competition_id=competition.id, **member) for member in data["staff"])
    audit.record(
        session, MANAGE, competition, location_id=competition.location_id, changes={"staff": [before, len(seen)]}
    )
    session.flush()
    return list_competition_staff(session, principal, competition.id)


# --- ladders (LGE-28) -------------------------------------------------------------------------------------------

DEFAULT_CHALLENGE_RANGE = 3


def _ladder(session: Db, principal: Principal, competition_id: UUID, key: str, *, lock: bool = False):
    competition = core._competition(session, principal, competition_id, key, lock=lock)
    if competition.format != "ladder":
        raise Conflict("This competition is not a ladder.", code="not-a-ladder")
    return competition


def _assigned(session: Db, principal: Principal, competition):
    """A scorekeeper-only caller reaches only the competitions it is assigned to (404 otherwise)."""
    mine = core.assigned_competitions(principal)
    if mine is not None and competition.id not in set(session.scalars(mine)):
        raise NotFound()
    return competition


def get_ladder(session: Db, principal: Principal, competition_id: UUID) -> list[dict]:
    competition = _assigned(
        session, principal, _ladder(session, principal, competition_id, core._game_reader(principal))
    )
    rows = session.scalars(
        select(LadderPosition).where(LadderPosition.competition_id == competition.id).order_by(LadderPosition.position)
    ).all()
    names = core._names(session, [r.competition_team_id for r in rows])
    return [
        {"competition_team_id": r.competition_team_id, "position": r.position, "team_name": names.get(r.competition_team_id)}
        for r in rows
    ]  # fmt: skip


def replace_ladder(session: Db, principal: Principal, competition_id: UUID, data: dict) -> list[dict]:
    """Set the ladder order: rung 1 first. Every listed team must be an active entry, each once."""
    competition = _ladder(session, principal, competition_id, MANAGE, lock=True)
    ids = data["competition_team_ids"]
    active = set(session.scalars(select(CompetitionTeam.id).where(
        CompetitionTeam.competition_id == competition.id, CompetitionTeam.status == "active"
    )))  # fmt: skip
    if len(set(ids)) != len(ids) or not set(ids) <= active:
        raise ValidationFailed("Unknown, inactive or repeated team entry.", pointer="/competition_team_ids")
    session.execute(delete(LadderPosition).where(LadderPosition.competition_id == competition.id))
    session.add_all(
        LadderPosition(competition_id=competition.id, competition_team_id=team_id, position=index)
        for index, team_id in enumerate(ids, start=1)
    )
    audit.record(
        session, MANAGE, competition, location_id=competition.location_id, changes={"ladder": [None, len(ids)]}
    )
    session.flush()
    return get_ladder(session, principal, competition.id)


def create_ladder_challenge(session: Db, principal: Principal, competition_id: UUID, data: dict) -> dict:
    """A challenge game: the challenger (home) may challenge a team up to `ladder_challenge_range` rungs above
    (default 3). A challenger win swaps the two rungs when the result is recorded."""
    competition = _ladder(session, principal, competition_id, GAMES, lock=True)
    rungs = dict(session.execute(
        select(LadderPosition.competition_team_id, LadderPosition.position).where(
            LadderPosition.competition_id == competition.id
        )
    ).all())  # fmt: skip
    challenger, defender = data["challenger_id"], data["defender_id"]
    if challenger not in rungs or defender not in rungs:
        raise ValidationFailed("Both teams must be on the ladder.", pointer="/defender_id")
    reach = competition.ladder_challenge_range or DEFAULT_CHALLENGE_RANGE
    if not 0 < rungs[challenger] - rungs[defender] <= reach:
        raise ValidationFailed(
            f"Challenge a team at most {reach} rungs above.", pointer="/defender_id", code="out-of-range"
        )
    body = {k: v for k, v in data.items() if k not in ("challenger_id", "defender_id")}
    return core.create_game(
        session, principal,
        body | {"competition_id": competition.id, "home_team_id": challenger, "away_team_id": defender,
                "round_label": "Ladder challenge"},
    )  # fmt: skip


# --- stat tables, formula stats and player stats (LGE-07) -------------------------------------------------------


def _table_view(session: Db, table: StatTable) -> dict:
    stmt = select(StatDefinition).where(StatDefinition.stat_table_id == table.id)
    stats = session.scalars(stmt.order_by(StatDefinition.sort_order, StatDefinition.code))
    return core._columns(table) | {"stats": [core._columns(d) for d in stats]}


def list_stat_tables(session: Db, principal: Principal, sport_id: UUID) -> list[dict]:
    authorize(principal, MANAGE)
    core._get(session, Sport, sport_id)
    stmt = select(StatTable).where(StatTable.sport_id == sport_id).order_by(StatTable.sort_order, StatTable.name)
    return [_table_view(session, t) for t in session.scalars(stmt)]


def create_stat_table(session: Db, principal: Principal, sport_id: UUID, data: dict) -> dict:
    authorize_tenant_wide(principal, MANAGE)
    core._get(session, Sport, sport_id)
    row = StatTable(sport_id=sport_id, **core._given(data))
    session.add(row)
    session.flush()
    audit.record(session, MANAGE, row, changes={"name": [None, row.name]})
    return _table_view(session, row)


def update_stat_table(session: Db, principal: Principal, stat_table_id: UUID, data: dict) -> dict:
    authorize_tenant_wide(principal, MANAGE)
    row = core._get(session, StatTable, stat_table_id, lock=True)
    audit.record(session, MANAGE, row, changes=core._apply(row, core._given(data)))
    session.flush()
    return _table_view(session, row)


def _recorded(session: Db, definition_ids: list[UUID]) -> bool:
    if not definition_ids:
        return False
    stmt = select(func.count()).select_from(PlayerStat).where(PlayerStat.stat_definition_id.in_(definition_ids))
    return bool(session.scalar(stmt))


def _uses(session: Db, sport_id: UUID, code: str, *, exclude: UUID | None = None) -> bool:
    """Whether a formula stat of the sport (outside table `exclude`) names `code`."""
    stmt = select(StatDefinition).where(StatDefinition.sport_id == sport_id, StatDefinition.kind == "formula")
    if exclude is not None:
        stmt = stmt.where(StatDefinition.stat_table_id != exclude)
    return any(code in formula.names(formula.parse(d.formula or "")) for d in session.scalars(stmt))


def delete_stat_table(session: Db, principal: Principal, stat_table_id: UUID) -> None:
    authorize_tenant_wide(principal, MANAGE)
    row = core._get(session, StatTable, stat_table_id, lock=True)
    defs = list(session.scalars(select(StatDefinition).where(StatDefinition.stat_table_id == row.id)))
    if _recorded(session, [d.id for d in defs]):
        raise Conflict("Player stats are recorded in this table.", code="in-use")
    if any(_uses(session, row.sport_id, d.code, exclude=row.id) for d in defs if d.kind == "entry"):
        raise Conflict("A formula in another table uses a stat in this table.", code="in-use")
    audit.record(session, MANAGE, row, changes={"deleted": [False, True]})
    session.execute(delete(StatDefinition).where(StatDefinition.stat_table_id == row.id))
    session.delete(row)
    session.flush()


def _check_formula(session: Db, sport_id: UUID, kind: str, text: str | None) -> None:
    if kind != "formula":
        if text:
            raise ValidationFailed("Only a formula stat has a formula.", pointer="/formula")
        return
    if not text:
        raise ValidationFailed("A formula stat needs a formula.", pointer="/formula")
    known = set(session.scalars(
        select(StatDefinition.code).where(StatDefinition.sport_id == sport_id, StatDefinition.kind == "entry")
    ))  # fmt: skip
    try:
        formula.validate(text, known)
    except formula.FormulaError as exc:
        raise ValidationFailed(str(exc), pointer="/formula", code="invalid-formula") from exc


def create_stat_definition(session: Db, principal: Principal, stat_table_id: UUID, data: dict) -> StatDefinition:
    """A stat in a table: an entry stat (typed per player per game) or a formula over the sport's entry stats,
    validated on save by the formula parser (never eval)."""
    authorize_tenant_wide(principal, MANAGE)
    table = core._get(session, StatTable, stat_table_id, lock=True)
    _check_formula(session, table.sport_id, data.get("kind") or "entry", data.get("formula"))
    row = StatDefinition(stat_table_id=table.id, sport_id=table.sport_id, **core._given(data))
    session.add(row)
    session.flush()
    audit.record(session, MANAGE, row, changes={"code": [None, row.code], "kind": [None, row.kind]})
    return row


def update_stat_definition(session: Db, principal: Principal, stat_definition_id: UUID, data: dict) -> StatDefinition:
    """Name, decimals, order and formula change freely; the code of an entry stat a formula uses cannot."""
    authorize_tenant_wide(principal, MANAGE)
    row = core._get(session, StatDefinition, stat_definition_id, lock=True)
    given = core._given(data)
    renamed = "code" in given and given["code"] != row.code
    if renamed and row.kind == "entry" and _uses(session, row.sport_id, row.code):
        raise Conflict("A formula uses this stat; its code cannot change.", code="in-use")
    if "formula" in given:
        _check_formula(session, row.sport_id, row.kind, given["formula"])
    audit.record(session, MANAGE, row, changes=core._apply(row, given))
    session.flush()
    return row


def delete_stat_definition(session: Db, principal: Principal, stat_definition_id: UUID) -> None:
    authorize_tenant_wide(principal, MANAGE)
    row = core._get(session, StatDefinition, stat_definition_id, lock=True)
    if _recorded(session, [row.id]) or (row.kind == "entry" and _uses(session, row.sport_id, row.code)):
        raise Conflict("The stat is recorded or used by a formula.", code="in-use")
    audit.record(session, MANAGE, row, changes={"deleted": [False, True]})
    session.delete(row)
    session.flush()


def list_game_player_stats(session: Db, principal: Principal, game_id: UUID) -> list[PlayerStat]:
    game = core._scored(session, principal, game_id, RESULTS)
    return list(session.scalars(select(PlayerStat).where(PlayerStat.game_id == game.id).order_by(PlayerStat.id)))


def replace_game_player_stats(session: Db, principal: Principal, game_id: UUID, data: dict) -> list[PlayerStat]:
    """Replace the game's player stats: players of the two teams, entry stats of the competition's sport."""
    game = core._scored(session, principal, game_id, RESULTS, lock=True)
    competition = core._get(session, Competition, game.competition_id)
    sides = [t for t in (game.home_team_id, game.away_team_id) if t]
    players = set(session.scalars(select(RosterEntry.id).where(RosterEntry.competition_team_id.in_(sides))))
    entry_stats = set(session.scalars(select(StatDefinition.id).where(
        StatDefinition.sport_id == competition.sport_id, StatDefinition.kind == "entry"
    )))  # fmt: skip
    seen = set()
    for index, line in enumerate(data["stats"]):
        if line["roster_entry_id"] not in players:
            raise ValidationFailed("The player is not on either team.", pointer=f"/stats/{index}/roster_entry_id")
        if line["stat_definition_id"] not in entry_stats:
            raise ValidationFailed("Unknown entry stat for this sport.", pointer=f"/stats/{index}/stat_definition_id")
        key = (line["roster_entry_id"], line["stat_definition_id"])
        if key in seen:
            raise ValidationFailed("A stat is given twice for one player.", pointer=f"/stats/{index}")
        seen.add(key)
    session.execute(delete(PlayerStat).where(PlayerStat.game_id == game.id))
    session.add_all(PlayerStat(game_id=game.id, **line) for line in data["stats"])
    audit.record(
        session, RESULTS, game, location_id=game.location_id, changes={"player_stats": [None, len(data["stats"])]}
    )
    session.flush()
    return list_game_player_stats(session, principal, game.id)


def list_competition_player_stats(session: Db, principal: Principal, competition_id: UUID) -> list[dict]:
    """Season totals per player: every entry stat summed over the competition's games, then each formula stat
    evaluated on those totals (blank on division by zero)."""
    competition = core._competition(session, principal, competition_id, core._game_reader(principal))
    if (mine := core.assigned_competitions(principal)) is not None and competition.id not in set(session.scalars(mine)):
        raise NotFound()
    defs = list(session.scalars(
        select(StatDefinition).where(StatDefinition.sport_id == competition.sport_id)
        .order_by(StatDefinition.sort_order, StatDefinition.code)
    ))  # fmt: skip
    sums = session.execute(
        select(PlayerStat.roster_entry_id, PlayerStat.stat_definition_id, func.sum(PlayerStat.value))
        .join(Game, Game.id == PlayerStat.game_id).where(Game.competition_id == competition.id)
        .group_by(PlayerStat.roster_entry_id, PlayerStat.stat_definition_id)
    ).all()  # fmt: skip
    codes = {d.id: d.code for d in defs}
    totals: dict[UUID, dict[str, Decimal]] = defaultdict(dict)
    for roster_entry_id, definition_id, value in sums:
        totals[roster_entry_id][codes[definition_id]] = value
    trees = {d.code: formula.parse(d.formula or "") for d in defs if d.kind == "formula"}
    rows = list(session.scalars(select(RosterEntry).where(RosterEntry.id.in_(list(totals))))) if totals else []
    out = []
    for view in core._roster_views(session, rows):
        values = totals[view["id"]]
        stats = {}
        for d in defs:
            raw = formula.evaluate(trees[d.code], values) if d.kind == "formula" else values.get(d.code, Decimal(0))
            stats[d.code] = None if raw is None else round(raw, d.decimal_places)
        out.append({
            "roster_entry_id": view["id"], "competition_team_id": view["competition_team_id"],
            "player_name": view["name"], "stats": stats,
        })  # fmt: skip
    return sorted(out, key=lambda r: (str(r["competition_team_id"]), r["player_name"]))


# --- team fee split (REG-26) ------------------------------------------------------------------------------------


def list_team_fee_shares(session: Db, principal: Principal, competition_team_id: UUID) -> list[TeamFeeShare]:
    entry, _ = core._child(session, principal, CompetitionTeam, competition_team_id, TEAMS)
    stmt = select(TeamFeeShare).where(TeamFeeShare.competition_team_id == entry.id)
    return list(session.scalars(stmt.order_by(TeamFeeShare.created_at, TeamFeeShare.id)))


def split_team_fee(session: Db, principal: Principal, competition_team_id: UUID, data: dict) -> list[TeamFeeShare]:
    """Bill the unbilled team fee as shares charged to rostered players (one charge and invoice each, through
    billing.service, idempotent by share); any remainder is billed to `bill_to_client_id` like a whole fee."""
    entry, competition = core._child(session, principal, CompetitionTeam, competition_team_id, TEAMS, lock=True)
    if entry.fee_status != "unbilled" or not competition.team_fee_minor:
        raise Conflict("This team owes no unbilled fee.", code="fee-not-due")
    roster = {r.id: r for r in session.scalars(select(RosterEntry).where(
        RosterEntry.competition_team_id == entry.id, RosterEntry.status == "active", RosterEntry.client_id.is_not(None)
    ))}  # fmt: skip
    seen = set()
    for index, share in enumerate(data["shares"]):
        pointer = f"/shares/{index}/roster_entry_id"
        player = roster.get(share["roster_entry_id"])
        if player is None or player.client_id in seen:
            raise ValidationFailed("Shares go to rostered client players, once each.", pointer=pointer)
        core._client(session, principal, player.client_id, TEAMS, pointer)
        seen.add(player.client_id)
    remainder = competition.team_fee_minor - sum(s["amount_minor"] for s in data["shares"])
    if remainder < 0:
        raise ValidationFailed("The shares add up to more than the team fee.", pointer="/shares")
    if remainder and data.get("bill_to_client_id") is None:
        raise ValidationFailed("Name who pays the rest of the fee.", pointer="/bill_to_client_id")
    team = core._get(session, Team, entry.team_id)
    name = entry.display_name or team.name
    for share in data["shares"]:
        player = roster[share["roster_entry_id"]]
        row = TeamFeeShare(
            competition_team_id=entry.id, roster_entry_id=player.id, client_id=player.client_id,
            amount_minor=share["amount_minor"],
        )  # fmt: skip
        session.add(row)
        session.flush()
        charge = billing.service.post_charge(
            session, client_id=player.client_id, location_id=competition.location_id,
            description=f"{competition.name}: team fee share ({name})", unit_price_minor=row.amount_minor,
            source_context="leagues", source_type="team_fee_share", source_id=row.id,
            revenue_category_id=competition.revenue_category_id,
        )  # fmt: skip
        billing.service.create_invoice_for_charges(session, [charge.id], bill_to_client_id=player.client_id)
        row.charge_id = charge.id
        audit.record(
            session, TEAMS, row, location_id=competition.location_id, changes={"amount_minor": [None, row.amount_minor]}
        )
    if remainder:
        full = competition.team_fee_minor
        competition.team_fee_minor = remainder  # _bill charges the competition's fee: bill only the rest
        try:
            core._bill(session, principal, competition, entry, team, data["bill_to_client_id"])
        finally:
            competition.team_fee_minor = full
    else:
        entry.fee_status, entry.fee_client_id = "billed", roster[data["shares"][0]["roster_entry_id"]].client_id
        audit.record(
            session, TEAMS, entry, location_id=competition.location_id, changes={"fee_status": ["unbilled", "billed"]}
        )
    session.flush()
    return list_team_fee_shares(session, principal, entry.id)


# --- publish a program group as a competition (REG-14) ----------------------------------------------------------


def publish_program_group(session: Db, principal: Principal, data: dict) -> Competition:
    """A league or tournament from a program group: each direct subgroup becomes a team, and with
    `include_players` each subgroup's enrolled clients join its roster (origin 'enrollment'). A one-off copy:
    later enrolment changes do not follow (README)."""
    group = programs.groups.load(session, principal, data["program_group_id"], programs.groups.READ)
    pg = programs.models.ProgramGroup
    subgroups = list(session.scalars(
        select(pg).where(pg.parent_id == group.id, pg.deleted_at.is_(None)).order_by(pg.name)
    ))  # fmt: skip
    if len(subgroups) < 2:
        raise ValidationFailed("The group needs at least two subgroups to become teams.", pointer="/program_group_id")
    body = {k: v for k, v in data.items() if k not in ("program_group_id", "include_players")}
    competition = core.create_competition(
        session, principal, body | {"location_id": group.location_id, "name": data.get("name") or group.name}
    )
    competition.program_group_id = group.id
    authorize(principal, TEAMS, location_id=competition.location_id)
    division = core._division(session, competition, None)
    players = defaultdict(list)
    if data.get("include_players"):
        for person in programs.groups.roster(session, principal, group.id)["participants"]:
            players[person["program_group_id"]].append(person["client_id"])
    for sub in subgroups:
        team = Team(location_id=competition.location_id, name=sub.name[:100])
        session.add(team)
        session.flush()
        entry = core._enter(session, competition, team, division)
        for client_id in dict.fromkeys(players[sub.id]):
            session.add(RosterEntry(competition_team_id=entry.id, client_id=client_id, origin="enrollment"))
    session.flush()
    return competition


# --- captain portal roster (REG-26) -----------------------------------------------------------------------------


def _actable(session: Db, principal: Principal) -> list[UUID]:
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    return clients.households.actable_client_ids(session, principal.identity_id)


def _captain_entry(session: Db, principal: Principal, competition_team_id: UUID, *, lock: bool = False):
    """The entry when the caller acts for its team's captain; anything else is 404."""
    mine = _actable(session, principal)
    entry = core._get(session, CompetitionTeam, competition_team_id, lock=lock)
    team = core._get(session, Team, entry.team_id)
    if team.captain_client_id not in mine or entry.status != "active":
        raise NotFound()
    return entry, mine


def portal_list_league_teams(session: Db, principal: Principal) -> list[dict]:
    mine = _actable(session, principal)
    if not mine:
        return []
    rows = session.execute(
        select(CompetitionTeam, Team, Competition).join(Team, Team.id == CompetitionTeam.team_id)
        .join(Competition, Competition.id == CompetitionTeam.competition_id)
        .where(Team.captain_client_id.in_(mine), CompetitionTeam.status == "active")
        .order_by(Competition.starts_on.desc(), Team.name)
    ).all()  # fmt: skip
    return [
        {"competition_team_id": e.id, "team_name": e.display_name or t.name, "competition_name": c.name,
         "starts_on": c.starts_on}
        for e, t, c in rows
    ]  # fmt: skip


def portal_list_team_roster(session: Db, principal: Principal, competition_team_id: UUID) -> list[dict]:
    entry, _ = _captain_entry(session, principal, competition_team_id)
    rows = session.scalars(select(RosterEntry).where(
        RosterEntry.competition_team_id == entry.id, RosterEntry.status == "active"
    ).order_by(RosterEntry.created_at, RosterEntry.id)).all()  # fmt: skip
    return core._roster_views(session, list(rows))


def portal_add_roster_entry(session: Db, principal: Principal, competition_team_id: UUID, data: dict) -> dict:
    """The captain adds a player: one of the clients they act for, or a typed walk-on name."""
    entry, mine = _captain_entry(session, principal, competition_team_id, lock=True)
    if data.get("client_id") is not None:
        if data["client_id"] not in mine:
            raise ValidationFailed("Unknown client.", pointer="/client_id")
        data = data | {"first_name": None, "last_name": None}
    elif not (data.get("first_name") and data.get("last_name")):
        raise ValidationFailed("A first and last name is required.", pointer="/first_name")
    competition = core._get(session, Competition, entry.competition_id)
    row = RosterEntry(competition_team_id=entry.id, origin="roster_invite", **core._given(data))
    session.add(row)
    session.flush()
    audit.record(session, ROSTER, row, location_id=competition.location_id, changes={"role": [None, row.role]})
    return core._roster_views(session, [row])[0]


def portal_remove_roster_entry(session: Db, principal: Principal, roster_entry_id: UUID) -> None:
    _actable(session, principal)
    row = session.get(RosterEntry, roster_entry_id, with_for_update=True)
    if row is None or row.status != "active":
        raise NotFound()
    entry, _ = _captain_entry(session, principal, row.competition_team_id)
    competition = core._get(session, Competition, entry.competition_id)
    row.status = "removed"
    audit.record(session, ROSTER, row, location_id=competition.location_id, changes={"status": ["active", "removed"]})
    session.flush()


# --- game cards (LGE-16) ----------------------------------------------------------------------------------------

_SPARE_LINES = 3  # blank roster lines for walk-ons


def _document(session: Db, title: str, subtitle: str) -> Document:
    return Document(title, organization=platform.service.get_tenant(session).name, subtitle=subtitle)


def _card(doc: Document, session: Db, competition: Competition, game: Game | None) -> None:
    """One game card: the game facts, then per side the roster with blank points and fouls columns."""
    teams: list[tuple[UUID | None, str | None, str]] = [(None, None, "Home"), (None, None, "Away")]
    if game is None:
        doc.heading(f"{competition.name} - game card")
        doc.fields([("Date", ""), ("Time", ""), ("Court", ""), ("Officials", "")])
    else:
        zone = core._zone(session, game.location_id)
        when = game.starts_at.astimezone(zone) if game.starts_at else None
        if game.venue_id:
            place = core._get(session, Venue, game.venue_id).name
        elif game.resource_id:
            place = resources.service.get_many(session, [game.resource_id])[0].name
        else:
            place = "-"
        officials = session.scalars(
            select(Official).join(GameOfficial, GameOfficial.official_id == Official.id)
            .where(GameOfficial.game_id == game.id)
        ).all()  # fmt: skip
        doc.heading(
            f"{competition.name} - {game.round_label or (f'Round {game.round_no}' if game.round_no else 'Game')}"
        )
        doc.fields([
            ("Date", local_date(when)), ("Time", when.strftime("%H:%M") if when else "-"), ("Court", place),
            ("Officials", ", ".join(f"{o.first_name} {o.last_name}" for o in officials) or "-"),
        ])  # fmt: skip
        teams = [(game.home_team_id, game.home_label, "Home"), (game.away_team_id, game.away_label, "Away")]
    names = core._names(session, [t[0] for t in teams if t[0]])
    for team_id, label, side in teams:
        rows = []
        if team_id is not None:
            players = session.scalars(select(RosterEntry).where(
                RosterEntry.competition_team_id == team_id, RosterEntry.status == "active"
            ).order_by(RosterEntry.jersey_number, RosterEntry.created_at)).all()  # fmt: skip
            rows = [[p["jersey_number"] or "", p["name"], "", ""] for p in core._roster_views(session, list(players))]
        rows += [["", "", "", ""]] * _SPARE_LINES
        doc.text(
            f"{side}: {(names.get(team_id) if team_id else None) or label or '________________'}    Final score: ______"
        )
        doc.table([Column("No.", 15), Column("Player"), Column("Points", 25, "R"), Column("Fouls", 25, "R")], rows)


def game_card_pdf(session: Db, principal: Principal, game_id: UUID) -> tuple[str, bytes]:
    game = core._scored(session, principal, game_id, CARDS)
    competition = core._get(session, Competition, game.competition_id)
    doc = _document(session, "Game card", competition.name)
    _card(doc, session, competition, game)
    return f"game-card-{game.id}.pdf", doc.output()


def manual_game_card_pdf(session: Db, principal: Principal, competition_id: UUID) -> tuple[str, bytes]:
    """A blank card for a game not in the system (a pickup or makeup game), filled in by hand."""
    competition = _assigned(session, principal, core._competition(session, principal, competition_id, CARDS))
    doc = _document(session, "Game card", competition.name)
    _card(doc, session, competition, None)
    return f"game-card-{competition.id}-blank.pdf", doc.output()


MAX_CARD_DAYS = 31
MAX_CARDS = 200


def game_cards_pdf(session: Db, principal: Principal, sport_id: UUID, from_on: date, to_on: date) -> tuple[str, bytes]:
    """Every scheduled game of a sport in the date range (each game's local date), one card after another."""
    authorize(principal, CARDS)
    if to_on < from_on or (to_on - from_on).days > MAX_CARD_DAYS:
        raise ValidationFailed(f"Pick a range of at most {MAX_CARD_DAYS} days.", pointer="/to_on")
    core._get(session, Sport, sport_id)
    # a day of margin each side in UTC, then each game is kept by its own location's local date
    lo = datetime.combine(from_on - timedelta(days=1), time.min, UTC)
    hi = datetime.combine(to_on + timedelta(days=2), time.min, UTC)
    stmt = scope_query(
        select(Game).join(Competition, Competition.id == Game.competition_id).where(
            Competition.sport_id == sport_id, Game.status == "scheduled", Game.starts_at >= lo, Game.starts_at < hi,
        ), principal, Game.location_id,
    ).order_by(Game.starts_at)  # fmt: skip
    if (mine := core.assigned_competitions(principal)) is not None:
        stmt = stmt.where(Game.competition_id.in_(mine))
    games = [
        g for g in session.scalars(stmt)
        if from_on <= g.starts_at.astimezone(core._zone(session, g.location_id)).date() <= to_on
    ][:MAX_CARDS]  # fmt: skip
    doc = _document(session, "Game cards", f"{from_on.isoformat()} to {to_on.isoformat()}")
    if not games:
        doc.text("No scheduled games in this range.")
    for game in games:
        _card(doc, session, core._get(session, Competition, game.competition_id), game)
    return f"game-cards-{from_on}-{to_on}.pdf", doc.output()
