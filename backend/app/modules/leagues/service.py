"""leagues service (build module 11): sports, age groups, seasons, competitions and divisions, teams and team
entries with the registration fee, rosters, officials, the round-robin schedule generator, games, results,
standings, single-elimination brackets and the public schedule and standings.

Every game that holds a court owns a booking written by `scheduling.service` with source ('leagues', 'game',
id), so the resource-hold exclusion constraint is the final conflict guard for generated and manual games alike.
Team fees go through `billing.service` (post_charge, idempotent by source, then create_invoice_for_charges).

Gates: location rows (competition, team, official, schedule run, game) are loaded and authorized on their own
`location_id`; child rows on their competition's. Sports, age groups and seasons are tenant-wide rows under the
location-scoped `leagues.competition.manage`: reads need the key, writes `authorize_tenant_wide`.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session as Db

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query
from app.core.auth.permissions import authorize_tenant_wide
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, platform, resources, scheduling
from app.modules.leagues import events as ev
from app.modules.leagues.domain import bracket as bracket_layout
from app.modules.leagues.domain import roundrobin, standings
from app.modules.leagues.models import (
    DEFAULT_COLUMNS,
    DEFAULT_SORT,
    AgeGroup,
    Bracket,
    BracketSlot,
    Competition,
    CompetitionStaff,
    CompetitionTeam,
    Division,
    Game,
    GameOfficial,
    GameResult,
    LadderPosition,
    Official,
    RosterEntry,
    ScheduleRun,
    Season,
    Sport,
    Standing,
    Team,
    TeamPreference,
    Venue,
)

MANAGE = "leagues.competition.manage"
DELETE = "leagues.competition.delete"
TEAMS = "leagues.team.manage"
ROSTER = "leagues.roster.manage"
GENERATE = "leagues.schedule.generate"
GAMES = "leagues.game.manage"
RESULTS = "leagues.result.enter"
AMEND = "leagues.result.amend_final"
ADJUST = "leagues.standings.adjust"
OFFICIALS = "leagues.official.manage"
CARDS = "leagues.game_card.print"
NO_TIME = datetime(9999, 12, 31, tzinfo=UTC)  # sorts games with no start time last in keyset paging

CONSTRAINT_CODES.update({
    "ex_game_official_overlap": "official-conflict",
    "uq_sport_name": "already-exists",
    "uq_age_group_name": "already-exists",
    "uq_season_name": "already-exists",
    "uq_division_competition_name": "already-exists",
    "uq_competition_team_team": "already-entered",
    "uq_competition_team_seed": "seed-taken",
    "uq_roster_entry_team_client": "already-on-roster",
    "uq_official_staff_user": "already-exists",
    "uq_venue_name": "already-exists",
    "uq_stat_table_name": "already-exists",
    "uq_stat_definition_code": "already-exists",
    "uq_competition_staff_user": "already-assigned",
    "uq_ladder_position_team": "already-on-ladder",
    "uq_team_fee_share_client": "already-shared",
})  # fmt: skip

_SCORING = (
    "points_win", "points_tie", "points_loss", "points_overtime_loss", "points_forfeit_win", "points_forfeit_loss",
    "points_default_loss", "forfeit_score_for", "tracks_sportsmanship", "standings_columns", "standings_sort",
)  # fmt: skip
_PLACED = ("scheduled", "played", "postponed")
_SOURCE = ("leagues", "game")


# --- shared helpers ---------------------------------------------------------------------------------------------


def _plain(value):
    if isinstance(value, list | tuple):  # uuid[] and date[] columns (qualifications, schedule-run arrays)
        return [_plain(v) for v in value]
    return str(value) if isinstance(value, UUID | Decimal) or hasattr(value, "isoformat") else value


def _apply(row, data: dict, fields=None) -> dict:
    """Set the given fields; return the audit diff of the ones that changed."""
    changes = {}
    for name, value in data.items():
        if (fields is None or name in fields) and getattr(row, name) != value:
            changes[name] = [_plain(getattr(row, name)), _plain(value)]
            setattr(row, name, value)
    return changes


def _columns(row) -> dict:
    return {c.key: getattr(row, c.key) for c in type(row).__table__.columns if c.key != "tenant_id"}


def _zone(session: Db, location_id: UUID) -> ZoneInfo:
    return ZoneInfo(platform.service.location_time_zone(session, location_id))


def _location(session: Db, principal: Principal, location_id: UUID) -> UUID:
    try:
        return platform.service.get_location(session, principal, location_id).id
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None


def _get(session: Db, model, row_id: UUID, *, lock: bool = False):
    stmt = select(model).where(model.id == row_id)
    row = session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    if row is None:
        raise NotFound()
    return row


def _scoped(session: Db, principal: Principal, model, row_id: UUID, key: str, *, lock: bool = False):
    """A location-owned row, gated on its own location: missing or outside the caller's locations is 404."""
    row = _get(session, model, row_id, lock=lock)
    authorize(principal, key, location_id=row.location_id)
    return row


def _competition(session: Db, principal: Principal, competition_id: UUID, key: str, *, lock: bool = False):
    return _scoped(session, principal, Competition, competition_id, key, lock=lock)


def _child(session: Db, principal: Principal, model, row_id: UUID, key: str, *, lock: bool = False):
    """(row, competition) for a row owned by a competition; gated on the competition's location."""
    row = _get(session, model, row_id, lock=lock)
    return row, _competition(session, principal, row.competition_id, key)


def _ref(session: Db, model, row_id: UUID | None, pointer: str):
    """A tenant-wide reference from a request body: unknown is a 422 on that field."""
    if row_id is None:
        return None
    row = session.get(model, row_id)
    if row is None:
        raise ValidationFailed(f"Unknown {model.__tablename__.replace('_', ' ')}.", pointer=pointer)
    return row


def _client(session: Db, principal: Principal, client_id: UUID | None, key: str, pointer: str) -> UUID | None:
    """A client id from the request: out of the caller's client reach is 404 before any 422 (W2-01, W2-06)."""
    if client_id is not None:
        clients.service.load(session, principal, client_id, key)
        clients.service.require_active(session, client_id, pointer=pointer)
    return client_id


def _range(start: datetime, end: datetime) -> Range:
    return Range(start, end, bounds="[)")


def _given(data: dict, nullable=()) -> dict:
    """PATCH semantics: drop unset (None) fields except those that may be cleared."""
    return {k: v for k, v in data.items() if v is not None or k in nullable}


# --- sports, age groups, seasons (tenant-wide reference lists) --------------------------------------------------


def _layout(data: dict) -> dict:
    for name in ("standings_columns", "standings_sort"):
        if data.get(name) is not None:
            data[name] = [{k: v for k, v in item.items() if v is not None} for item in data[name]]
    return data


def list_sports(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, MANAGE)
    return paginate(
        session, select(Sport), query, id_column=Sport.id, sort_fields={"name": Sport.name}, default_sort="name",
        filter_fields={"is_active": Sport.is_active}, search=(Sport.name,),
    )  # fmt: skip


def get_sport(session: Db, principal: Principal, sport_id: UUID) -> Sport:
    authorize(principal, MANAGE)
    return _get(session, Sport, sport_id)


def create_sport(session: Db, principal: Principal, data: dict) -> Sport:
    authorize_tenant_wide(principal, MANAGE)
    data = _given(_layout(data))
    data.setdefault("standings_columns", DEFAULT_COLUMNS)
    data.setdefault("standings_sort", DEFAULT_SORT)
    row = Sport(**data)
    session.add(row)
    session.flush()
    audit.record(session, MANAGE, row, changes={"name": [None, row.name]})
    return row


def update_sport(session: Db, principal: Principal, sport_id: UUID, data: dict) -> Sport:
    authorize_tenant_wide(principal, MANAGE)
    row = _get(session, Sport, sport_id, lock=True)
    changes = _apply(row, _given(_layout(data), ("default_team_fee_minor", "fees_text", "rules_text")))
    audit.record(session, MANAGE, row, changes=changes)
    session.flush()
    return row


def _deletable(session: Db, column, row) -> None:
    if session.scalar(select(func.count()).select_from(Competition).where(column == row.id)):
        raise Conflict("It is used by a competition; deactivate it instead.", code="in-use")


def delete_sport(session: Db, principal: Principal, sport_id: UUID) -> None:
    authorize_tenant_wide(principal, MANAGE)
    row = _get(session, Sport, sport_id, lock=True)
    _deletable(session, Competition.sport_id, row)
    audit.record(session, MANAGE, row, changes={"deleted": [False, True]})
    session.delete(row)
    session.flush()


def _reference_crud(model):
    sort_fields = {"name": model.name}
    if hasattr(model, "sort_order"):
        sort_fields["sort_order"] = model.sort_order

    def list_rows(session: Db, principal: Principal, query: ListQuery) -> dict:
        authorize(principal, MANAGE)
        return paginate(
            session, select(model), query, id_column=model.id, sort_fields=sort_fields, default_sort="name",
            filter_fields={"is_active": model.is_active}, search=(model.name,),
        )  # fmt: skip

    def get_row(session: Db, principal: Principal, row_id: UUID):
        authorize(principal, MANAGE)
        return _get(session, model, row_id)

    def create_row(session: Db, principal: Principal, data: dict):
        authorize_tenant_wide(principal, MANAGE)
        row = model(**_given(data))
        session.add(row)
        session.flush()
        audit.record(session, MANAGE, row, changes={"name": [None, row.name]})
        return row

    def update_row(session: Db, principal: Principal, row_id: UUID, data: dict):
        authorize_tenant_wide(principal, MANAGE)
        row = _get(session, model, row_id, lock=True)
        changes = _apply(row, _given(data, ("min_age", "max_age", "starts_on", "ends_on")))
        audit.record(session, MANAGE, row, changes=changes)
        session.flush()
        return row

    def delete_row(session: Db, principal: Principal, row_id: UUID) -> None:
        authorize_tenant_wide(principal, MANAGE)
        row = _get(session, model, row_id, lock=True)
        _deletable(session, getattr(Competition, f"{model.__tablename__}_id"), row)
        audit.record(session, MANAGE, row, changes={"deleted": [False, True]})
        session.delete(row)
        session.flush()

    return list_rows, get_row, create_row, update_row, delete_row


list_age_groups, get_age_group, create_age_group, update_age_group, delete_age_group = _reference_crud(AgeGroup)
list_seasons, get_season, create_season, update_season, delete_season = _reference_crud(Season)


# --- competitions and divisions ---------------------------------------------------------------------------------

_COMPETITION_FIELDS = (
    "name", "format", "age_group_id", "season_id", "division_label", "starts_on", "ends_on", "game_length_min",
    "is_public", "shows_roster_publicly", "show_players", "max_defaults", "max_forfeits", "min_sportsmanship", "team_fee_text",
    "more_info", "rules_text", "registration_url", "color", "team_fee_minor", "revenue_category_id", *_SCORING,
)  # fmt: skip
_COMPETITION_NULLABLE = (
    "age_group_id", "season_id", "ends_on", "division_label", "team_fee_minor", "revenue_category_id",
    "max_defaults", "max_forfeits", "min_sportsmanship", "team_fee_text", "more_info", "rules_text",
    "registration_url", "color",
)  # fmt: skip
_TRANSITIONS = {
    "activate": (("draft",), "active"),
    "complete": (("active",), "completed"),
    "archive": (("draft", "completed"), "archived"),
    "reopen": (("completed", "archived"), "active"),
}


def _check_refs(session: Db, principal: Principal, data: dict) -> None:
    _ref(session, AgeGroup, data.get("age_group_id"), "/age_group_id")
    _ref(session, Season, data.get("season_id"), "/season_id")
    if data.get("revenue_category_id") is not None:
        try:
            billing.catalogue.get_revenue_category(session, principal, data["revenue_category_id"])
        except NotFound:
            raise ValidationFailed("Unknown revenue category.", pointer="/revenue_category_id") from None


def _check_shape(row: Competition) -> None:
    if row.kind == "league" and row.format not in ("round_robin", "ladder"):
        raise ValidationFailed("A league is a round robin or a ladder.", pointer="/format")
    if row.ends_on is not None and row.ends_on < row.starts_on:
        raise ValidationFailed("The end date is before the start date.", pointer="/ends_on")


def list_competitions(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, MANAGE)
    c = Competition
    return paginate(
        session, scope_query(select(c), principal, c.location_id), query, id_column=c.id,
        sort_fields={"name": c.name, "starts_on": c.starts_on, "created_at": c.created_at}, default_sort="-starts_on",
        filter_fields={
            "location_id": c.location_id, "kind": c.kind, "status": c.status, "sport_id": c.sport_id,
            "season_id": c.season_id, "age_group_id": c.age_group_id,
        },
        search=(c.name,),
    )  # fmt: skip


def get_competition(session: Db, principal: Principal, competition_id: UUID) -> Competition:
    return _competition(session, principal, competition_id, MANAGE)


def create_competition(session: Db, principal: Principal, data: dict) -> Competition:
    """The sport's scoring, game length and team fee are copied in as defaults (the request may override)."""
    location_id = _location(session, principal, data["location_id"])
    authorize(principal, MANAGE, location_id=location_id)
    sport = _ref(session, Sport, data["sport_id"], "/sport_id")
    _check_refs(session, principal, data)
    defaults = {name: getattr(sport, name) for name in _SCORING} | {
        "game_length_min": sport.default_game_length_min, "team_fee_minor": sport.default_team_fee_minor,
    }  # fmt: skip
    row = Competition(**defaults | _given(_layout(data)))
    _check_shape(row)
    session.add(row)
    session.flush()
    session.add(Division(competition_id=row.id, name="Main"))
    changes = {"name": [None, row.name], "kind": [None, row.kind]}
    if row.program_group_id:
        changes["program_group_id"] = [None, str(row.program_group_id)]
    audit.record(session, MANAGE, row, location_id=location_id, changes=changes)
    session.flush()
    return row


def update_competition(session: Db, principal: Principal, competition_id: UUID, data: dict) -> Competition:
    row = _competition(session, principal, competition_id, MANAGE, lock=True)
    _check_refs(session, principal, data)
    changes = _apply(row, _given(_layout(data), _COMPETITION_NULLABLE), _COMPETITION_FIELDS)
    _check_shape(row)
    audit.record(session, MANAGE, row, location_id=row.location_id, changes=changes)
    session.flush()
    return row


def transition_competition(session: Db, principal: Principal, competition_id: UUID, verb: str) -> Competition:
    row = _competition(session, principal, competition_id, MANAGE, lock=True)
    allowed, target = _TRANSITIONS[verb]
    if row.status not in allowed:
        raise Conflict(f"A {row.status} competition cannot {verb}.")
    audit.record(session, MANAGE, row, location_id=row.location_id, changes={"status": [row.status, target]})
    row.status = target
    session.flush()
    return row


def delete_competition(session: Db, principal: Principal, competition_id: UUID) -> None:
    """Only a competition with no booked or played game and no billed fee: those are history (archive it)."""
    row = _competition(session, principal, competition_id, DELETE, lock=True)
    booked = session.scalar(
        select(func.count()).select_from(Game).where(
            Game.competition_id == row.id, or_(Game.booking_id.is_not(None), Game.status == "played")
        )
    )  # fmt: skip
    billed = session.scalar(
        select(func.count()).select_from(CompetitionTeam).where(
            CompetitionTeam.competition_id == row.id, CompetitionTeam.fee_status == "billed"
        )
    )  # fmt: skip
    if booked or billed:
        raise Conflict("The competition has booked games, results or billed fees; archive it instead.", code="in-use")
    audit.record(session, DELETE, row, location_id=row.location_id, changes={"deleted": [False, True]})
    brackets = select(Bracket.id).where(Bracket.competition_id == row.id)
    session.execute(update(BracketSlot).where(BracketSlot.bracket_id.in_(brackets)).values(game_id=None))
    session.execute(delete(Game).where(Game.competition_id == row.id))
    session.delete(row)
    session.flush()


def list_divisions(session: Db, principal: Principal, competition_id: UUID) -> list[Division]:
    competition = _competition(session, principal, competition_id, MANAGE)
    stmt = select(Division).where(Division.competition_id == competition.id)
    return list(session.scalars(stmt.order_by(Division.sort_order, Division.name)))


def create_division(session: Db, principal: Principal, competition_id: UUID, data: dict) -> Division:
    competition = _competition(session, principal, competition_id, MANAGE)
    row = Division(competition_id=competition.id, **_given(data))
    session.add(row)
    session.flush()
    audit.record(session, MANAGE, row, location_id=competition.location_id, changes={"name": [None, row.name]})
    return row


def update_division(session: Db, principal: Principal, division_id: UUID, data: dict) -> Division:
    row, competition = _child(session, principal, Division, division_id, MANAGE, lock=True)
    audit.record(session, MANAGE, row, location_id=competition.location_id, changes=_apply(row, _given(data)))
    session.flush()
    return row


def delete_division(session: Db, principal: Principal, division_id: UUID) -> None:
    row, competition = _child(session, principal, Division, division_id, MANAGE, lock=True)
    entries = session.scalar(
        select(func.count()).select_from(CompetitionTeam).where(CompetitionTeam.division_id == row.id)
    )
    games = session.scalar(select(func.count()).select_from(Game).where(Game.division_id == row.id))
    if entries or games:
        raise Conflict("Move its teams and games to another division first.", code="in-use")
    siblings = session.scalar(
        select(func.count()).select_from(Division).where(Division.competition_id == competition.id)
    )
    if siblings == 1:
        raise Conflict("A competition keeps at least one division.", code="in-use")
    audit.record(session, MANAGE, row, location_id=competition.location_id, changes={"deleted": [False, True]})
    session.delete(row)
    session.flush()


def _division(session: Db, competition: Competition, division_id: UUID | None) -> Division:
    """The named division of this competition, or its first one when none is named."""
    stmt = select(Division).where(Division.competition_id == competition.id)
    if division_id is not None:
        row = session.scalar(stmt.where(Division.id == division_id))
        if row is None:
            raise ValidationFailed("Unknown division of this competition.", pointer="/division_id")
        return row
    return session.scalars(stmt.order_by(Division.sort_order, Division.created_at)).first()


# --- teams ------------------------------------------------------------------------------------------------------


def list_teams(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, TEAMS)
    return paginate(
        session, scope_query(select(Team), principal, Team.location_id), query, id_column=Team.id,
        sort_fields={"name": Team.name}, default_sort="name",
        filter_fields={"location_id": Team.location_id, "is_active": Team.is_active}, search=(Team.name,),
    )  # fmt: skip


def get_team(session: Db, principal: Principal, team_id: UUID) -> Team:
    return _scoped(session, principal, Team, team_id, TEAMS)


def _new_team(session: Db, principal: Principal, location_id: UUID, data: dict, *, placeholder: bool = False) -> Team:
    _client(session, principal, data.get("captain_client_id"), TEAMS, "/captain_client_id")
    row = Team(location_id=location_id, is_placeholder=placeholder, **_given(data))
    session.add(row)
    session.flush()
    audit.record(session, TEAMS, row, location_id=location_id, changes={"name": [None, row.name]})
    return row


def create_team(session: Db, principal: Principal, data: dict) -> Team:
    location_id = _location(session, principal, data.pop("location_id"))
    authorize(principal, TEAMS, location_id=location_id)
    return _new_team(session, principal, location_id, data)


def update_team(session: Db, principal: Principal, team_id: UUID, data: dict) -> Team:
    """Renaming a generated placeholder team makes it a real one (LGE-03)."""
    row = _scoped(session, principal, Team, team_id, TEAMS, lock=True)
    _client(session, principal, data.get("captain_client_id"), TEAMS, "/captain_client_id")
    data = _given(data, ("captain_client_id", "color"))
    if data.get("name"):
        data["is_placeholder"] = False
    audit.record(session, TEAMS, row, location_id=row.location_id, changes=_apply(row, data))
    session.flush()
    return row


def delete_team(session: Db, principal: Principal, team_id: UUID) -> None:
    row = _scoped(session, principal, Team, team_id, TEAMS, lock=True)
    if session.scalar(select(func.count()).select_from(CompetitionTeam).where(CompetitionTeam.team_id == row.id)):
        raise Conflict("The team has entered a competition; deactivate it instead.", code="in-use")
    audit.record(session, TEAMS, row, location_id=row.location_id, changes={"deleted": [False, True]})
    session.delete(row)
    session.flush()


# --- team entries and the registration fee ----------------------------------------------------------------------


def _entry_views(session: Db, rows: list[CompetitionTeam]) -> list[dict]:
    ids = {r.team_id for r in rows}
    names = dict(session.execute(select(Team.id, Team.name).where(Team.id.in_(ids))).all()) if ids else {}
    return [_columns(r) | {"name": r.display_name or names.get(r.team_id, ""), "invoice_id": None} for r in rows]


def _entry_view(session: Db, row: CompetitionTeam, invoice_id: UUID | None = None) -> dict:
    return _entry_views(session, [row])[0] | {"invoice_id": invoice_id}


def list_competition_teams(session: Db, principal: Principal, competition_id: UUID) -> list[dict]:
    competition = _competition(session, principal, competition_id, TEAMS)
    rows = session.scalars(
        select(CompetitionTeam).where(CompetitionTeam.competition_id == competition.id)
        .order_by(CompetitionTeam.seed.nulls_last(), CompetitionTeam.created_at)
    ).all()  # fmt: skip
    return _entry_views(session, list(rows))


def _enter(
    session: Db, competition: Competition, team: Team, division: Division, *, seed=None, display_name=None
) -> CompetitionTeam:
    """The one place a team joins a competition (add, generate and copy): the team must be at the competition's
    location, and the entry owes the team fee when the competition has one."""
    if team.location_id != competition.location_id:
        raise ValidationFailed("The team belongs to another location.", pointer="/team_id")
    row = CompetitionTeam(
        competition_id=competition.id, division_id=division.id, team_id=team.id, seed=seed,
        display_name=display_name, fee_status="unbilled" if competition.team_fee_minor else "none",
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(
        session, TEAMS, row, location_id=competition.location_id,
        changes={"team_id": [None, str(team.id)], "fee_status": [None, row.fee_status]},
    )  # fmt: skip
    return row


def _bill(
    session: Db,
    principal: Principal,
    competition: Competition,
    entry: CompetitionTeam,
    team: Team,
    client_id: UUID,
    *,
    amount_minor: int | None = None,
) -> UUID:
    """Charge the team fee to the payer and invoice it. The charge is idempotent by source, so the fee is owed
    once per entry however the command is retried. The payer is in the caller's reach and is the captain, a
    rostered client or an active relative of one (W2-01): a team fee never lands on a stranger."""
    if entry.fee_status != "unbilled":
        raise Conflict("This team owes no unbilled fee.", code="fee-not-due")
    _client(session, principal, client_id, TEAMS, "/bill_to_client_id")
    members = set(
        session.scalars(
            select(RosterEntry.client_id).where(
                RosterEntry.competition_team_id == entry.id, RosterEntry.status == "active"
            )
        )
    ) | {team.captain_client_id}
    if client_id not in billing.service.related_clients(session, members):
        raise ValidationFailed(
            "The payer must be the captain, a rostered player or an active relative of one.",
            pointer="/bill_to_client_id",
        )
    team_name = entry.display_name or team.name
    charge = billing.service.post_charge(
        session, client_id=client_id, location_id=competition.location_id,
        description=f"{competition.name}: team fee ({team_name})",
        unit_price_minor=competition.team_fee_minor if amount_minor is None else amount_minor,
        source_context="leagues", source_type="competition_team", source_id=entry.id,
        revenue_category_id=competition.revenue_category_id,
    )  # fmt: skip
    invoice = billing.service.create_invoice_for_charges(session, [charge.id], bill_to_client_id=client_id)
    entry.fee_status, entry.fee_client_id = "billed", client_id
    session.flush()
    return invoice.id


def add_competition_team(session: Db, principal: Principal, competition_id: UUID, data: dict) -> dict:
    competition = _competition(session, principal, competition_id, TEAMS, lock=True)
    division = _division(session, competition, data.get("division_id"))
    if (data.get("team_id") is None) == (data.get("team") is None):
        raise ValidationFailed("Give either team_id or team.", pointer="/team_id")
    if data.get("bill_to_client_id") is not None and not competition.team_fee_minor:
        raise ValidationFailed("This competition has no team fee.", pointer="/bill_to_client_id")
    if data.get("team_id") is not None:
        team = _scoped(session, principal, Team, data["team_id"], TEAMS)
    else:
        team = _new_team(session, principal, competition.location_id, data["team"])
    entry = _enter(session, competition, team, division, seed=data.get("seed"), display_name=data.get("display_name"))
    invoice_id = None
    if data.get("bill_to_client_id") is not None:
        invoice_id = _bill(session, principal, competition, entry, team, data["bill_to_client_id"])
    return _entry_view(session, entry, invoice_id)


def bill_competition_team(session: Db, principal: Principal, competition_team_id: UUID, data: dict) -> dict:
    entry, competition = _child(session, principal, CompetitionTeam, competition_team_id, TEAMS, lock=True)
    team = session.get(Team, entry.team_id)
    invoice_id = _bill(session, principal, competition, entry, team, data["bill_to_client_id"])
    audit.record(
        session, TEAMS, entry, location_id=competition.location_id, changes={"fee_status": ["unbilled", "billed"]}
    )
    return _entry_view(session, entry, invoice_id)


def generate_competition_teams(session: Db, principal: Principal, competition_id: UUID, data: dict) -> list[dict]:
    """Generic placeholder teams "<prefix> 1..N", renamed later (LGE-03)."""
    competition = _competition(session, principal, competition_id, TEAMS, lock=True)
    division = _division(session, competition, data.get("division_id"))
    taken = session.scalar(
        select(func.count()).select_from(CompetitionTeam).where(CompetitionTeam.competition_id == competition.id)
    )
    entries = []
    for n in range(taken + 1, taken + data["count"] + 1):
        name = {"name": f"{data['name_prefix']} {n}"}
        team = _new_team(session, principal, competition.location_id, name, placeholder=True)
        entries.append(_enter(session, competition, team, division))
    return _entry_views(session, entries)


def copy_competition_teams(session: Db, principal: Principal, competition_id: UUID, data: dict) -> list[dict]:
    """Re-enter the teams of an earlier competition (same `team` rows), optionally with their active rosters.
    Teams already entered are skipped."""
    competition = _competition(session, principal, competition_id, TEAMS, lock=True)
    source = _competition(session, principal, data["source_competition_id"], TEAMS)
    if data.get("includes_rosters"):
        authorize(principal, ROSTER, location_id=competition.location_id)  # copied rosters are roster writes (W2-07)
    if source.id == competition.id:
        raise ValidationFailed("Copy from another competition.", pointer="/source_competition_id")
    stmt = select(CompetitionTeam).where(CompetitionTeam.competition_id == source.id)
    wanted = data.get("competition_team_ids")
    if wanted:
        stmt = stmt.where(CompetitionTeam.id.in_(wanted))
    picked = list(session.scalars(stmt.order_by(CompetitionTeam.seed.nulls_last(), CompetitionTeam.created_at)))
    if wanted and len(picked) != len(set(wanted)):
        raise ValidationFailed("Unknown team entry of the source competition.", pointer="/competition_team_ids")
    entered = set(
        session.scalars(select(CompetitionTeam.team_id).where(CompetitionTeam.competition_id == competition.id))
    )
    division = _division(session, competition, None)
    entries = []
    for old in picked:
        if old.team_id in entered:
            continue
        entry = _enter(session, competition, session.get(Team, old.team_id), division, display_name=old.display_name)
        entries.append(entry)
        if data.get("includes_rosters"):
            people = session.scalars(
                select(RosterEntry).where(RosterEntry.competition_team_id == old.id, RosterEntry.status == "active")
            )
            for person in people:
                if person.client_id is not None:  # the same client reach as adding the place by hand
                    clients.service.load(session, principal, person.client_id, ROSTER)
                session.add(RosterEntry(
                    competition_team_id=entry.id, client_id=person.client_id, first_name=person.first_name,
                    last_name=person.last_name, role=person.role, jersey_number=person.jersey_number,
                    position=person.position, origin="copied",
                ))  # fmt: skip
    session.flush()
    return _entry_views(session, entries)


def put_seeding(session: Db, principal: Principal, competition_id: UUID, data: dict) -> list[dict]:
    """Seeds 1..n in the given order; entries not listed lose their seed. The seed unique is deferred, so a
    reorder inside one transaction never trips it."""
    competition = _competition(session, principal, competition_id, TEAMS, lock=True)
    ids = data["competition_team_ids"]
    if len(set(ids)) != len(ids):
        raise ValidationFailed("A team is listed twice.", pointer="/competition_team_ids")
    rows = {
        r.id: r
        for r in session.scalars(select(CompetitionTeam).where(CompetitionTeam.competition_id == competition.id))
    }
    if any(i not in rows for i in ids):
        raise ValidationFailed("Unknown team entry of this competition.", pointer="/competition_team_ids")
    order = {entry_id: seed for seed, entry_id in enumerate(ids, start=1)}
    for row in rows.values():
        row.seed = order.get(row.id)
    audit.record(
        session, TEAMS, competition, location_id=competition.location_id,
        changes={"seeding": [None, [str(i) for i in ids]]},
    )  # fmt: skip
    session.flush()
    return list_competition_teams(session, principal, competition_id)


def update_competition_team(session: Db, principal: Principal, competition_team_id: UUID, data: dict) -> dict:
    row, competition = _child(session, principal, CompetitionTeam, competition_team_id, TEAMS, lock=True)
    if data.get("division_id") is not None:
        _division(session, competition, data["division_id"])
    changes = _apply(row, _given(data, ("seed", "display_name")))
    audit.record(session, TEAMS, row, location_id=competition.location_id, changes=changes)
    session.flush()
    if {"division_id", "status"} & set(changes):
        rebuild_standings(session, competition)
    return _entry_view(session, row)


def remove_competition_team(session: Db, principal: Principal, competition_team_id: UUID) -> None:
    """A team that has games or a billed fee is withdrawn rather than deleted (results stay in history)."""
    row, competition = _child(session, principal, CompetitionTeam, competition_team_id, TEAMS, lock=True)
    in_games = session.scalar(
        select(func.count()).select_from(Game).where(or_(Game.home_team_id == row.id, Game.away_team_id == row.id))
    )
    if in_games or row.fee_status == "billed":
        raise Conflict("The team has games or a billed fee; withdraw it instead.", code="in-use")
    audit.record(session, TEAMS, row, location_id=competition.location_id, changes={"deleted": [False, True]})
    session.delete(row)
    session.flush()


# --- rosters ----------------------------------------------------------------------------------------------------


def _roster_views(session: Db, rows: list[RosterEntry]) -> list[dict]:
    people = {
        client_id: clients.service.display_name(clients.service.get(session, client_id))
        for client_id in {r.client_id for r in rows if r.client_id}
    }
    return [
        _columns(r) | {"name": people.get(r.client_id) or f"{r.first_name or ''} {r.last_name or ''}".strip()}
        for r in rows
    ]


def list_team_roster(session: Db, principal: Principal, competition_team_id: UUID) -> list[dict]:
    entry, _ = _child(session, principal, CompetitionTeam, competition_team_id, ROSTER)
    stmt = select(RosterEntry).where(RosterEntry.competition_team_id == entry.id).order_by(RosterEntry.created_at)
    return _roster_views(session, list(session.scalars(stmt)))


def _person(session: Db, principal: Principal, data: dict) -> dict:
    """A roster person is a client (names cleared) or a typed walk-on name."""
    if data.get("client_id") is not None:
        _client(session, principal, data["client_id"], ROSTER, "/client_id")
        return data | {"first_name": None, "last_name": None}
    return data


def add_roster_entry(session: Db, principal: Principal, competition_team_id: UUID, data: dict) -> dict:
    entry, competition = _child(session, principal, CompetitionTeam, competition_team_id, ROSTER, lock=True)
    data = _person(session, principal, data)
    if data.get("client_id") is None and not (data.get("first_name") and data.get("last_name")):
        raise ValidationFailed("A client or a first and last name is required.", pointer="/client_id")
    row = RosterEntry(competition_team_id=entry.id, origin="manual", **_given(data))
    session.add(row)
    session.flush()
    audit.record(session, ROSTER, row, location_id=competition.location_id, changes={"role": [None, row.role]})
    return _roster_views(session, [row])[0]


def _roster_entry(session: Db, principal: Principal, roster_entry_id: UUID, *, lock: bool = False):
    row = _get(session, RosterEntry, roster_entry_id, lock=lock)
    _, competition = _child(session, principal, CompetitionTeam, row.competition_team_id, ROSTER)
    return row, competition


def update_roster_entry(session: Db, principal: Principal, roster_entry_id: UUID, data: dict) -> dict:
    row, competition = _roster_entry(session, principal, roster_entry_id, lock=True)
    data = _given(_person(session, principal, data), ("jersey_number", "position", "first_name", "last_name"))
    if (data.get("client_id", row.client_id) is None) and not (
        data.get("first_name", row.first_name) and data.get("last_name", row.last_name)
    ):
        raise ValidationFailed("A client or a first and last name is required.", pointer="/first_name")
    audit.record(session, ROSTER, row, location_id=competition.location_id, changes=_apply(row, data))
    session.flush()
    return _roster_views(session, [row])[0]


def remove_roster_entry(session: Db, principal: Principal, roster_entry_id: UUID) -> None:
    row, competition = _roster_entry(session, principal, roster_entry_id, lock=True)
    audit.record(session, ROSTER, row, location_id=competition.location_id, changes={"status": [row.status, "removed"]})
    row.status = "removed"
    session.flush()


def search_roster_entries(session: Db, principal: Principal, query: ListQuery) -> dict:
    """Roster rows across competitions at the caller's locations; filter by client, team entry or competition."""
    authorize(principal, ROSTER)
    stmt = (
        select(RosterEntry)
        .join(CompetitionTeam, CompetitionTeam.id == RosterEntry.competition_team_id)
        .join(Competition, Competition.id == CompetitionTeam.competition_id)
    )
    page = paginate(
        session, scope_query(stmt, principal, Competition.location_id), query, id_column=RosterEntry.id,
        sort_fields={"created_at": RosterEntry.created_at}, default_sort="created_at",
        filter_fields={
            "client_id": RosterEntry.client_id, "competition_team_id": RosterEntry.competition_team_id,
            "status": RosterEntry.status, "competition_id": CompetitionTeam.competition_id,
        },
        search=(RosterEntry.first_name, RosterEntry.last_name, RosterEntry.jersey_number),
    )  # fmt: skip
    return page | {"data": _roster_views(session, page["data"])}


# --- officials --------------------------------------------------------------------------------------------------


def _check_qualifications(session: Db, data: dict) -> None:
    for field, model in (("sport_ids", Sport), ("age_group_ids", AgeGroup)):
        if data.get(field) is None:
            continue
        ids = list(dict.fromkeys(data[field]))
        if ids and session.scalar(select(func.count()).select_from(model).where(model.id.in_(ids))) != len(ids):
            raise ValidationFailed(f"Unknown {model.__tablename__.replace('_', ' ')}.", pointer=f"/{field}")
        data[field] = ids
    if data.get("staff_user_id") is not None and not platform.service.staff_user_exists(session, data["staff_user_id"]):
        raise ValidationFailed("Unknown staff user.", pointer="/staff_user_id")


def list_officials(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, OFFICIALS)
    o = Official
    return paginate(
        session, scope_query(select(o), principal, o.location_id), query, id_column=o.id,
        sort_fields={"last_name": o.last_name}, default_sort="last_name",
        filter_fields={"location_id": o.location_id, "is_active": o.is_active}, search=(o.first_name, o.last_name),
    )  # fmt: skip


def get_official(session: Db, principal: Principal, official_id: UUID) -> Official:
    return _scoped(session, principal, Official, official_id, OFFICIALS)


def create_official(session: Db, principal: Principal, data: dict) -> Official:
    location_id = _location(session, principal, data.pop("location_id"))
    authorize(principal, OFFICIALS, location_id=location_id)
    _check_qualifications(session, data)
    row = Official(location_id=location_id, **_given(data))
    session.add(row)
    session.flush()
    audit.record(session, OFFICIALS, row, location_id=location_id, changes={"first_name": [None, "set"]})
    return row


def update_official(session: Db, principal: Principal, official_id: UUID, data: dict) -> Official:
    row = _scoped(session, principal, Official, official_id, OFFICIALS, lock=True)
    _check_qualifications(session, data)
    changes = _apply(row, _given(data, ("email", "phone", "staff_user_id")))
    audit.record(session, OFFICIALS, row, location_id=row.location_id, changes=changes)
    session.flush()
    return row


def delete_official(session: Db, principal: Principal, official_id: UUID) -> None:
    row = _scoped(session, principal, Official, official_id, OFFICIALS, lock=True)
    if session.scalar(select(func.count()).select_from(GameOfficial).where(GameOfficial.official_id == row.id)):
        raise Conflict("The official has game assignments; deactivate them instead.", code="in-use")
    audit.record(session, OFFICIALS, row, location_id=row.location_id, changes={"deleted": [False, True]})
    session.delete(row)
    session.flush()


def _assignment_views(session: Db, game: Game) -> list[dict]:
    rows = session.execute(
        select(GameOfficial, Official).join(Official, Official.id == GameOfficial.official_id)
        .where(GameOfficial.game_id == game.id).order_by(GameOfficial.created_at)
    ).all()  # fmt: skip
    return [_columns(a) | {"name": f"{o.first_name} {o.last_name}"} for a, o in rows]


def list_game_officials(session: Db, principal: Principal, game_id: UUID) -> list[dict]:
    return _assignment_views(session, _scoped(session, principal, Game, game_id, OFFICIALS))


def put_game_officials(session: Db, principal: Principal, game_id: UUID, data: dict) -> list[dict]:
    """Replace a game's officials. Each must be active, at the game's location, and qualified for the
    competition's sport (and age group when set). Double-booking an official is refused by the exclusion
    constraint `ex_game_official_overlap` (409 official-conflict), as a court is."""
    game = _scoped(session, principal, Game, game_id, OFFICIALS, lock=True)
    if game.starts_at is None or game.status not in _PLACED:
        raise Conflict("Schedule the game before assigning officials.")
    competition = session.get(Competition, game.competition_id)
    ids = [a["official_id"] for a in data["assignments"]]
    if len(set(ids)) != len(ids):
        raise ValidationFailed("An official is listed twice.", pointer="/assignments")
    for index, assignment in enumerate(data["assignments"]):
        official = session.get(Official, assignment["official_id"])
        pointer = f"/assignments/{index}/official_id"
        if official is None or official.location_id != game.location_id or not official.is_active:
            raise ValidationFailed("Unknown official at this location.", pointer=pointer)
        qualified = competition.sport_id in (official.sport_ids or []) and (
            competition.age_group_id is None or competition.age_group_id in (official.age_group_ids or [])
        )
        if not qualified:
            raise ValidationFailed(
                "The official is not qualified for this sport or age group.", pointer=pointer,
                code="official-not-qualified",
            )  # fmt: skip
    session.execute(delete(GameOfficial).where(GameOfficial.game_id == game.id))
    during = _range(game.starts_at, game.ends_at)
    for assignment in data["assignments"]:
        session.add(GameOfficial(
            game_id=game.id, official_id=assignment["official_id"], role=assignment["role"], during=during
        ))  # fmt: skip
    audit.record(
        session, OFFICIALS, game, location_id=game.location_id, changes={"officials": [None, [str(i) for i in ids]]}
    )
    session.flush()
    return _assignment_views(session, game)


# --- games ------------------------------------------------------------------------------------------------------


def _names(session: Db, ids) -> dict[UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = session.execute(
        select(CompetitionTeam.id, CompetitionTeam.display_name, Team.name)
        .join(Team, Team.id == CompetitionTeam.team_id).where(CompetitionTeam.id.in_(ids))
    ).all()  # fmt: skip
    return {i: display or name for i, display, name in rows}


def game_views(session: Db, games: list[Game]) -> list[dict]:
    names = _names(session, [g.home_team_id for g in games] + [g.away_team_id for g in games])
    scores: dict[UUID, dict] = defaultdict(dict)
    titles: dict = {}
    if games:
        for row in session.scalars(select(GameResult).where(GameResult.game_id.in_([g.id for g in games]))):
            scores[row.game_id][row.side] = row.score
        ids = {g.competition_id for g in games}
        titles = {
            i: (n, sp)
            for i, n, sp in session.execute(
                select(Competition.id, Competition.name, Competition.sport_id).where(Competition.id.in_(ids))
            )
        }
    return [
        _columns(g) | {
            "home_name": names.get(g.home_team_id), "away_name": names.get(g.away_team_id),
            "home_score": scores[g.id].get("home"), "away_score": scores[g.id].get("away"),
            "competition_name": titles.get(g.competition_id, (None, None))[0],
            "sport_id": titles.get(g.competition_id, (None, None))[1],
        }
        for g in games
    ]  # fmt: skip


def _title(session: Db, game: Game) -> str:
    names = _names(session, [game.home_team_id, game.away_team_id])
    home = names.get(game.home_team_id) or game.home_label or "TBD"
    away = names.get(game.away_team_id) or game.away_label or "TBD"
    return f"{home} vs {away}"


def _place(
    session: Db,
    game: Game,
    resource_id: UUID | None,
    starts_at: datetime,
    length_min: int | None = None,
    venue: Venue | None = None,
) -> None:
    """Give a game its court and time through scheduling: a new booking, or the existing one moved. A game at a
    league venue holds every facility resource the venue maps to (RES-06). A clash is scheduling's 409
    booking-conflict (the exclusion constraint decides); officials' ranges follow the game."""
    length = length_min or game.length_min
    ends_at = starts_at + timedelta(minutes=length)
    held = list(venue.resource_ids) if venue is not None else [resource_id]
    if game.booking_id is not None:
        booking = scheduling.service.get_booking(session, game.booking_id)
        scheduling.service.reschedule_booking(session, booking, starts_at=starts_at, ends_at=ends_at, resource_ids=held)
    else:
        booking = scheduling.service.create_booking(
            session, location_id=game.location_id, kind="game", starts_at=starts_at, ends_at=ends_at,
            resource_ids=held, title=_title(session, game), source=(*_SOURCE, game.id), created_via="staff",
        )  # fmt: skip
        game.booking_id = booking.id
    game.venue_id = venue.id if venue is not None else None
    game.resource_id, game.starts_at, game.ends_at, game.length_min = held[0], starts_at, ends_at, length
    game.status = "played" if game.status == "played" else "scheduled"
    game.conflict_note = None
    game.version += 1
    session.execute(
        update(GameOfficial).where(GameOfficial.game_id == game.id).values(during=_range(starts_at, ends_at))
    )
    session.flush()


def _release(session: Db, game: Game, status: str) -> None:
    """Free the court (the booking is cancelled, not deleted), drop the officials and move the game to `status`
    in the same flush: a 'scheduled' game without a booking breaks the table's check."""
    game.status = status
    if game.booking_id is not None:
        booking_id, game.booking_id = game.booking_id, None
        session.flush()
        scheduling.service.cancel_booking(session, scheduling.service.get_booking(session, booking_id), reason="staff")
    session.execute(delete(GameOfficial).where(GameOfficial.game_id == game.id))


def _publish(session: Db, game: Game, event_class) -> None:
    fields = {"game_id": game.id, "competition_id": game.competition_id, "location_id": game.location_id}
    if event_class is ev.GameRescheduled:
        fields["status"] = game.status
    events.publish(session, event_class(**fields), game.id)


def _check_sides(session: Db, competition: Competition, home_id: UUID | None, away_id: UUID | None) -> None:
    for field, value in (("home_team_id", home_id), ("away_team_id", away_id)):
        if value is not None:
            entry = session.get(CompetitionTeam, value)
            if entry is None or entry.competition_id != competition.id:
                raise ValidationFailed("Unknown team entry of this competition.", pointer=f"/{field}")
    if home_id is not None and home_id == away_id:
        raise ValidationFailed("A team cannot play itself.", pointer="/away_team_id")


def _court_and_time(data: dict) -> bool:
    where = data.get("resource_id") is not None or data.get("venue_id") is not None
    if data.get("resource_id") is not None and data.get("venue_id") is not None:
        raise ValidationFailed("Give a court or a venue, not both.", pointer="/venue_id")
    if where != (data.get("starts_at") is not None):
        raise ValidationFailed("Give a court or venue and a start time together.", pointer="/starts_at")
    return where


def _venue(session: Db, location_id: UUID, venue_id: UUID | None, pointer: str = "/venue_id") -> Venue | None:
    """A venue from a request body: active and at the game's or run's location, else 422."""
    if venue_id is None:
        return None
    row = session.get(Venue, venue_id)
    if row is None or row.location_id != location_id or not row.is_active:
        raise ValidationFailed("Unknown venue at this location.", pointer=pointer)
    return row


def _place_from(session: Db, game: Game, data: dict, length_min: int | None = None) -> None:
    venue = _venue(session, game.location_id, data.get("venue_id"))
    _place(session, game, data.get("resource_id"), data["starts_at"], length_min, venue)


def _game_reader(principal: Principal) -> str:
    """Reading games: the game-manage key, or the result key for a scorekeeper."""
    return GAMES if principal.has(GAMES) else RESULTS


def assigned_competitions(principal: Principal):
    """LGE-26, PLT-11: a scorekeeper-only caller (the result key without the game key) reaches only the
    competitions they are assigned to. None means no narrowing; otherwise a SELECT of competition ids."""
    if principal.has(GAMES):
        return None
    return select(CompetitionStaff.competition_id).where(CompetitionStaff.staff_user_id == principal.staff_user_id)


def _scored(session: Db, principal: Principal, game_id: UUID, key: str, *, lock: bool = False) -> Game:
    """A game loaded under `key` and, for a scorekeeper-only caller, one of their assigned competitions (404)."""
    game = _scoped(session, principal, Game, game_id, key, lock=lock)
    mine = assigned_competitions(principal)
    if mine is not None and game.competition_id not in set(session.scalars(mine)):
        raise NotFound()
    return game


def list_games(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _game_reader(principal))
    g = Game
    stmt = scope_query(select(g), principal, g.location_id)
    if (mine := assigned_competitions(principal)) is not None:
        stmt = stmt.where(g.competition_id.in_(mine))
    page = paginate(
        session, stmt, query, id_column=g.id,
        sort_fields={"created_at": g.created_at, "starts_at": func.coalesce(g.starts_at, NO_TIME)},
        default_sort="created_at",
        filter_fields={
            "location_id": g.location_id, "competition_id": g.competition_id, "division_id": g.division_id,
            "status": g.status, "resource_id": g.resource_id, "schedule_run_id": g.schedule_run_id,
            "game_type": g.game_type,
        },
    )  # fmt: skip
    return page | {"data": game_views(session, page["data"])}


def get_game(session: Db, principal: Principal, game_id: UUID) -> dict:
    return game_views(session, [_scored(session, principal, game_id, _game_reader(principal))])[0]


def create_game(session: Db, principal: Principal, data: dict) -> dict:
    """A manual game (LGE-31), regular or post-season, with placeholder labels for undecided sides. Given a
    court and a time it is booked at once; otherwise it waits as 'proposed'."""
    competition = _competition(session, principal, data["competition_id"], GAMES)
    division = _division(session, competition, data["division_id"]) if data.get("division_id") else None
    _check_sides(session, competition, data.get("home_team_id"), data.get("away_team_id"))
    placed = _court_and_time(data)
    game = Game(
        location_id=competition.location_id, competition_id=competition.id,
        division_id=division.id if division else None, home_team_id=data.get("home_team_id"),
        away_team_id=data.get("away_team_id"), home_label=data.get("home_label"), away_label=data.get("away_label"),
        length_min=data.get("length_min") or competition.game_length_min, status="proposed",
        game_type=data.get("game_type") or "regular", round_label=data.get("round_label"), notes=data.get("notes"),
    )  # fmt: skip
    session.add(game)
    session.flush()
    if placed:
        _place_from(session, game, data)
    audit.record(session, GAMES, game, location_id=game.location_id, changes={"status": [None, game.status]})
    return game_views(session, [game])[0]


def update_game(session: Db, principal: Principal, game_id: UUID, data: dict) -> dict:
    """Teams, labels and notes. Optimistic `version` check when given."""
    game = _scoped(session, principal, Game, game_id, GAMES, lock=True)
    version = data.pop("version", None)
    if version is not None and version != game.version:
        raise Conflict("The game was changed by someone else; reload it.", code="version-mismatch")
    data = _given(data, ("home_label", "away_label", "round_label", "notes"))
    if game.status == "played" and {"home_team_id", "away_team_id"} & set(data):
        raise Conflict("Remove the result before changing the teams of a played game.")
    competition = session.get(Competition, game.competition_id)
    _check_sides(
        session, competition, data.get("home_team_id", game.home_team_id), data.get("away_team_id", game.away_team_id)
    )
    changes = _apply(game, data)
    if changes:
        game.version += 1
    audit.record(session, GAMES, game, location_id=game.location_id, changes=changes)
    session.flush()
    return game_views(session, [game])[0]


def reschedule_game(session: Db, principal: Principal, game_id: UUID, data: dict) -> dict:
    """Move (or first place) a game on a court and time; a postponed or unschedulable game becomes scheduled."""
    game = _scoped(session, principal, Game, game_id, GAMES, lock=True)
    if game.status in ("cancelled", "bye"):
        raise Conflict(f"A {game.status} game cannot be scheduled.")
    if not _court_and_time(data):
        raise ValidationFailed("Give a court or a venue.", pointer="/resource_id")
    before = {"starts_at": _plain(game.starts_at), "resource_id": _plain(game.resource_id)}
    _place_from(session, game, data, data.get("length_min"))
    changes = {k: [v, _plain(getattr(game, k))] for k, v in before.items()}
    audit.record(session, GAMES, game, location_id=game.location_id, changes=changes)
    _publish(session, game, ev.GameRescheduled)
    return game_views(session, [game])[0]


def postpone_game(session: Db, principal: Principal, game_id: UUID, data: dict) -> dict:
    """Postpone keeps the game: with a new court and time it moves there, otherwise the court is released and
    the game waits as 'postponed' until rescheduled."""
    game = _scoped(session, principal, Game, game_id, GAMES, lock=True)
    if game.status not in ("scheduled", "proposed", "unschedulable"):
        raise Conflict(f"A {game.status} game cannot be postponed.")
    before = game.status
    if _court_and_time(data):
        _place_from(session, game, data)
    else:
        _release(session, game, "postponed")
        game.version += 1
    audit.record(session, GAMES, game, location_id=game.location_id, changes={"status": [before, game.status]})
    session.flush()
    _publish(session, game, ev.GameRescheduled)
    return game_views(session, [game])[0]


def cancel_game(session: Db, principal: Principal, game_id: UUID) -> dict:
    """Cancel releases the court; a cancelled game does not count in the standings (LGE-06)."""
    game = _scoped(session, principal, Game, game_id, GAMES, lock=True)
    if game.status in ("played", "cancelled", "bye"):
        raise Conflict(f"A {game.status} game cannot be cancelled.")
    audit.record(session, GAMES, game, location_id=game.location_id, changes={"status": [game.status, "cancelled"]})
    _release(session, game, "cancelled")
    game.version += 1
    session.flush()
    _publish(session, game, ev.GameCancelled)
    return game_views(session, [game])[0]


def on_booking_rescheduled(session: Db, booking_id: UUID) -> None:
    """A game's booking moved on the calendar: the game follows (idempotent: a game already there is left)."""
    game = session.scalar(select(Game).where(Game.booking_id == booking_id).with_for_update())
    if game is None:
        return
    booking = scheduling.service.get_booking(session, booking_id)
    if booking.starts_at == game.starts_at and booking.ends_at == game.ends_at:
        return
    game.starts_at, game.ends_at = booking.starts_at, booking.ends_at
    game.length_min = int((booking.ends_at - booking.starts_at).total_seconds() // 60)
    view = scheduling.service.booking_views(session, [booking_id]).get(booking_id) or {}
    court = [r for r in view.get("resources", []) if r.get("role", "primary") == "primary"]
    if court:
        game.resource_id = UUID(str(court[0]["resource_id"]))
    game.version += 1
    session.execute(
        update(GameOfficial).where(GameOfficial.game_id == game.id).values(during=_range(game.starts_at, game.ends_at))
    )
    audit.record(
        session, GAMES, game, location_id=game.location_id, changes={"starts_at": [None, _plain(game.starts_at)]}
    )
    session.flush()
    _publish(session, game, ev.GameRescheduled)


def on_booking_cancelled(session: Db, booking_id: UUID) -> None:
    """A game's booking cancelled on the calendar: the game is cancelled with it (idempotent)."""
    game = session.scalar(select(Game).where(Game.booking_id == booking_id).with_for_update())
    if game is None or game.status != "scheduled":
        return
    game.booking_id, game.status = None, "cancelled"
    game.version += 1
    session.execute(delete(GameOfficial).where(GameOfficial.game_id == game.id))
    audit.record(session, GAMES, game, location_id=game.location_id, changes={"status": ["scheduled", "cancelled"]})
    session.flush()
    _publish(session, game, ev.GameCancelled)


# --- results and standings --------------------------------------------------------------------------------------


def _result_view(session: Db, game: Game) -> dict:
    rows = {r.side: r for r in session.scalars(select(GameResult).where(GameResult.game_id == game.id))}
    home, away = rows.get("home"), rows.get("away")

    def side(mine, theirs):
        if mine is None or theirs is None:
            return None
        return _columns(mine) | {"outcome": standings.outcome(_columns(mine), _columns(theirs))}

    return {
        "game_id": game.id, "status": game.status, "home": side(home, away), "away": side(away, home),
        "recorded_at": home.recorded_at if home else None,
    }  # fmt: skip


def get_game_result(session: Db, principal: Principal, game_id: UUID) -> dict:
    return _result_view(session, _scored(session, principal, game_id, RESULTS))


def _slot_of(session: Db, game: Game) -> BracketSlot | None:
    return session.scalar(select(BracketSlot).where(BracketSlot.game_id == game.id).with_for_update())


def put_game_result(session: Db, principal: Principal, game_id: UUID, data: dict) -> dict:
    """Record or correct both sides. The game becomes 'played', the competition's standings are rebuilt and a
    bracket game advances its winner (and loser, into a third-place game). A correction that would change who
    advanced after the next game was played is refused."""
    game = _scored(session, principal, game_id, RESULTS, lock=True)
    if game.status not in ("scheduled", "played"):
        raise Conflict("Only a scheduled or played game takes a result.")
    if game.home_team_id is None or game.away_team_id is None:
        raise Conflict("Both teams must be known before a result is entered.")
    competition = _get(session, Competition, game.competition_id, lock=True)
    sides = {"home": (game.home_team_id, data["home"]), "away": (game.away_team_id, data["away"])}
    for given in data["home"], data["away"]:
        given.setdefault("participation", "full")
        given.setdefault("went_to_overtime", False)
    played = data["home"]["participation"] == data["away"]["participation"] == "full"
    for name, (_, given) in sides.items():
        if given.get("sportsmanship") is not None and not competition.tracks_sportsmanship:
            raise ValidationFailed("This competition does not track sportsmanship.", pointer=f"/{name}/sportsmanship")
        if played and given.get("score") is None:
            raise ValidationFailed("A score is required.", pointer=f"/{name}/score")
    slot = _slot_of(session, game)
    if slot is not None and standings.winner(data["home"], data["away"]) is None:
        raise ValidationFailed("A bracket game needs a winner.", pointer="/home/score", code="bracket-needs-winner")
    existing = {r.side: r for r in session.scalars(select(GameResult).where(GameResult.game_id == game.id))}
    changes = {}
    for name, (team_id, given) in sides.items():
        row = existing.get(name)
        if row is None:
            row = GameResult(game_id=game.id, side=name, competition_team_id=team_id)
            session.add(row)
        row.competition_team_id = team_id
        for field, diff in _apply(row, given).items():
            changes[f"{name}_{field}"] = diff
        row.recorded_by_staff_user_id, row.recorded_at = principal.staff_user_id, clock.now()
    before = game.status
    game.status = "played"
    game.version += 1
    session.flush()
    if slot is not None:
        _advance(session, slot, game, data)
    if competition.format == "ladder":
        _ladder_settle(session, game, standings.winner(data["home"], data["away"]) == "home")
    audit.record(session, RESULTS, game, location_id=game.location_id, changes=changes | {"status": [before, "played"]})
    _publish(session, game, ev.GameResultRecorded)
    rebuild_standings(session, competition)
    return _result_view(session, game)


def delete_game_result(session: Db, principal: Principal, game_id: UUID) -> None:
    """Remove a recorded result (amend-final key): the game returns to scheduled and standings are rebuilt."""
    game = _scoped(session, principal, Game, game_id, AMEND, lock=True)
    if game.status != "played":
        raise Conflict("The game has no result.")
    competition = _get(session, Competition, game.competition_id, lock=True)
    slot = _slot_of(session, game)
    if slot is not None:
        _unadvance(session, slot)
    if competition.format == "ladder":
        _ladder_settle(session, game, False)
    session.execute(delete(GameResult).where(GameResult.game_id == game.id))
    game.status = "scheduled" if game.booking_id else "proposed"
    game.version += 1
    audit.record(session, AMEND, game, location_id=game.location_id, changes={"status": ["played", game.status]})
    session.flush()
    rebuild_standings(session, competition)


def _ladder_settle(session: Db, game: Game, challenger_won: bool) -> None:
    """LGE-28: a challenger (home) who beats a higher-ranked team swaps rungs with it; a corrected or removed
    result swaps back. `game.ladder_swapped` remembers the swap, so settling is idempotent."""
    if game.ladder_swapped == challenger_won:
        return
    rows = {
        r.competition_team_id: r
        for r in session.scalars(select(LadderPosition).where(
            LadderPosition.competition_id == game.competition_id,
            LadderPosition.competition_team_id.in_((game.home_team_id, game.away_team_id)),
        ).with_for_update())
    }  # fmt: skip
    home, away = rows.get(game.home_team_id), rows.get(game.away_team_id)
    if home is None or away is None:
        return
    if challenger_won and home.position < away.position:
        return  # the challenger was already above: nothing to swap
    home.position, away.position = away.position, home.position  # rung uniqueness is checked at commit
    game.ladder_swapped = challenger_won
    session.flush()


def rebuild_standings(session: Db, competition: Competition) -> None:
    """Rebuild every standing row of the competition from its played regular-season games, inside the caller's
    transaction (callers that write results hold the competition row lock). Manual adjustments survive."""
    entries = list(session.scalars(
        select(CompetitionTeam).where(
            CompetitionTeam.competition_id == competition.id, CompetitionTeam.status == "active"
        )
    ))  # fmt: skip
    current = {
        s.competition_team_id: s
        for s in session.scalars(select(Standing).where(Standing.competition_id == competition.id))
    }
    in_brackets = select(BracketSlot.game_id).where(BracketSlot.game_id.is_not(None))
    game_ids = list(session.scalars(
        select(Game.id).where(
            Game.competition_id == competition.id, Game.status == "played", Game.game_type == "regular",
            Game.id.not_in(in_brackets),
        )
    ))  # fmt: skip
    results: dict[UUID, dict] = defaultdict(dict)
    if game_ids:
        for row in session.scalars(select(GameResult).where(GameResult.game_id.in_(game_ids))):
            results[row.game_id][row.side] = _columns(row)
    played = [r for r in results.values() if "home" in r and "away" in r]
    scoring = {name: getattr(competition, name) for name in _SCORING}
    sort = competition.standings_sort or DEFAULT_SORT
    by_division = defaultdict(list)
    for entry in entries:
        by_division[entry.division_id].append(entry.id)
    keep = set()
    now = clock.now()
    for division_id, team_ids in by_division.items():
        adjustments = {i: current[i].adjustment_points for i in team_ids if i in current}
        for row in standings.compute(team_ids, played, scoring, sort, adjustments):
            team_id = row.pop("competition_team_id")
            keep.add(team_id)
            target = current.get(team_id)
            if target is None:
                target = Standing(competition_id=competition.id, competition_team_id=team_id)
                session.add(target)
            target.division_id = division_id
            for name, value in row.items():
                setattr(target, name, value)
            target.is_over_discipline_cap = bool(
                (competition.max_forfeits is not None and row["forfeits"] > competition.max_forfeits)
                or (competition.max_defaults is not None and row["defaults"] > competition.max_defaults)
            )
            target.computed_at = now
    for team_id, row in current.items():
        if team_id not in keep:
            session.delete(row)
    session.flush()
    events.publish(
        session, ev.StandingsUpdated(competition_id=competition.id, location_id=competition.location_id), competition.id
    )


def _standing_views(session: Db, rows: list[Standing]) -> list[dict]:
    names = _names(session, [r.competition_team_id for r in rows])
    return [
        _columns(r) | {
            "team_name": names.get(r.competition_team_id, ""), "goal_difference": r.goals_for - r.goals_against,
            "win_pct": Decimal(standings.metric(_columns(r), "WP")).quantize(Decimal("0.001")),
        }
        for r in rows
    ]  # fmt: skip


def _ordered_standings(session: Db, competition_id: UUID, division_id: UUID | None = None) -> list[Standing]:
    stmt = (
        select(Standing).join(Division, Division.id == Standing.division_id)
        .where(Standing.competition_id == competition_id)
        .order_by(Division.sort_order, Division.name, Standing.rank)
    )  # fmt: skip
    if division_id is not None:
        stmt = stmt.where(Standing.division_id == division_id)
    return list(session.scalars(stmt))


def list_standings(
    session: Db, principal: Principal, competition_id: UUID, division_id: UUID | None = None
) -> list[dict]:
    competition = _competition(session, principal, competition_id, MANAGE)
    return _standing_views(session, _ordered_standings(session, competition.id, division_id))


def recompute_standings(session: Db, principal: Principal, competition_id: UUID) -> list[dict]:
    competition = _competition(session, principal, competition_id, MANAGE, lock=True)
    rebuild_standings(session, competition)
    audit.record(
        session, MANAGE, competition, location_id=competition.location_id, changes={"standings": [None, "rebuilt"]}
    )
    return _standing_views(session, _ordered_standings(session, competition.id))


def adjust_standing(session: Db, principal: Principal, standing_id: UUID, data: dict) -> dict:
    """Manual points (penalty or award) kept through rebuilds; the reason is audited as a flag only."""
    row, competition = _child(session, principal, Standing, standing_id, ADJUST, lock=True)
    _get(session, Competition, competition.id, lock=True)
    changes = {
        "adjustment_points": [_plain(row.adjustment_points), _plain(data["adjustment_points"])],
        "adjustment_reason": [None, "set"],
    }  # fmt: skip
    row.adjustment_points, row.adjustment_reason = data["adjustment_points"], data["reason"]
    audit.record(session, ADJUST, row, location_id=competition.location_id, changes=changes)
    session.flush()
    rebuild_standings(session, competition)
    session.refresh(row)
    return _standing_views(session, [row])[0]


# --- schedule runs (LGE-08, LGE-09) -----------------------------------------------------------------------------


def run_view(row: ScheduleRun) -> dict:
    return _columns(row) | {
        "stats": row.result_stats, "blackout_dates": row.excluded_dates,
        "progress": {"done": row.progress.get("next", 0), "total": len(row.competition_ids)},
    }  # fmt: skip


def _check_run_inputs(session: Db, principal: Principal, location_id: UUID, data: dict) -> None:
    """Every id in the run goes through a scoped loader: competitions must be the caller's, at the run's
    location; resources must be active courts there; windows must use the run's resources."""
    for index, competition_id in enumerate(data.get("competition_ids") or []):
        competition = _competition(session, principal, competition_id, GENERATE)
        if competition.location_id != location_id:
            raise ValidationFailed("The competition is at another location.", pointer=f"/competition_ids/{index}")
        if competition.format not in ("round_robin", "pool_play"):
            raise ValidationFailed("Elimination formats use brackets.", pointer=f"/competition_ids/{index}")
    resource_ids = data.get("resource_ids")
    if resource_ids is not None:
        found = {r.id for r in resources.service.in_location(session, location_id, ids=resource_ids)}
        if found != set(resource_ids):
            raise ValidationFailed("Unknown resource at this location.", pointer="/resource_ids")
    for index, window in enumerate(data.get("time_slots") or []):
        if (window.get("resource_id") is None) == (window.get("venue_id") is None):
            raise ValidationFailed("Give a court or a venue.", pointer=f"/time_slots/{index}/resource_id")
        if window.get("venue_id") is not None:
            _venue(session, location_id, window["venue_id"], f"/time_slots/{index}/venue_id")
        elif resource_ids is not None and window["resource_id"] not in set(resource_ids):
            raise ValidationFailed(
                "The window's resource is not in the run.", pointer=f"/time_slots/{index}/resource_id"
            )
        if window["ends_at"] <= window["starts_at"]:
            raise ValidationFailed("The window ends before it starts.", pointer=f"/time_slots/{index}/ends_at")


def _run_fields(data: dict) -> dict:
    out = _given(data, ("rounds", "ends_on"))
    if "blackout_dates" in out:
        out["excluded_dates"] = out.pop("blackout_dates")
    if "time_slots" in out:
        out["time_slots"] = [
            {"weekday": w["weekday"], "starts_at": str(w["starts_at"])[:5], "ends_at": str(w["ends_at"])[:5]}
            | {k: str(w[k]) for k in ("resource_id", "venue_id") if w.get(k) is not None}
            for w in out["time_slots"]
        ]
    return out


def list_schedule_runs(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, GENERATE)
    r = ScheduleRun
    page = paginate(
        session, scope_query(select(r), principal, r.location_id), query, id_column=r.id,
        sort_fields={"created_at": r.created_at}, default_sort="-created_at",
        filter_fields={"location_id": r.location_id, "state": r.state},
    )  # fmt: skip
    return page | {"data": [run_view(row) for row in page["data"]]}


def get_schedule_run(session: Db, principal: Principal, run_id: UUID) -> dict:
    return run_view(_scoped(session, principal, ScheduleRun, run_id, GENERATE))


def create_schedule_run(session: Db, principal: Principal, data: dict) -> dict:
    location_id = _location(session, principal, data.pop("location_id"))
    authorize(principal, GENERATE, location_id=location_id)
    if not data.get("competition_ids"):
        raise ValidationFailed("Pick at least one competition.", pointer="/competition_ids")
    _check_run_inputs(session, principal, location_id, data)
    if data.get("ends_on") is not None and data["ends_on"] < data["starts_on"]:
        raise ValidationFailed("The end date is before the start date.", pointer="/ends_on")
    fields = _run_fields(data)
    fields.setdefault("game_length_min", session.get(Competition, data["competition_ids"][0]).game_length_min)
    row = ScheduleRun(
        location_id=location_id, created_by_staff_user_id=principal.staff_user_id, kind="round_robin", **fields
    )
    session.add(row)
    session.flush()
    audit.record(session, GENERATE, row, location_id=location_id, changes={"state": [None, row.state]})
    return run_view(row)


def _open_run(session: Db, principal: Principal, run_id: UUID) -> ScheduleRun:
    row = _scoped(session, principal, ScheduleRun, run_id, GENERATE, lock=True)
    if row.state not in ("draft", "previewed", "failed"):
        raise Conflict(f"A {row.state} run cannot change.")
    return row


def update_schedule_run(session: Db, principal: Principal, run_id: UUID, data: dict) -> dict:
    row = _open_run(session, principal, run_id)
    checked = data | {"resource_ids": data.get("resource_ids") or row.resource_ids}
    _check_run_inputs(session, principal, row.location_id, checked)
    changes = _apply(row, _run_fields(data))
    if row.ends_on is not None and row.ends_on < row.starts_on:
        raise ValidationFailed("The end date is before the start date.", pointer="/ends_on")
    audit.record(session, GENERATE, row, location_id=row.location_id, changes=changes)
    session.flush()
    return run_view(row)


def generate_schedule(session: Db, principal: Principal, run_id: UUID) -> dict:
    """Start the preview (LGE-08): the run turns 'generating' and the chunked job `generate_schedule_job` pairs and
    places one competition per chunk, writing games as 'proposed' (no booking yet). The run row is the job's
    status: poll it until 'previewed'. Re-generating replaces the previous preview. Commit books the courts."""
    run = _open_run(session, principal, run_id)
    if not run.time_slots:
        raise ValidationFailed("Add at least one weekly time window.", pointer="/time_slots")
    session.execute(delete(Game).where(Game.schedule_run_id == run.id))
    before = run.state
    run.state, run.result_stats = "generating", None
    run.progress = {"next": 0, "counts": {"games": 0, "byes": 0, "unschedulable": 0}, "home_away": {}}
    audit.record(session, GENERATE, run, location_id=run.location_id, changes={"state": [before, "generating"]})
    session.flush()
    tenant_id, ident = str(session.info["tenant_id"]), str(run.id)

    def enqueue() -> None:
        from app.modules.leagues.jobs import generate_schedule_job

        generate_schedule_job.send(tenant_id, ident)

    session.info.setdefault("after_commit", []).append(enqueue)
    return run_view(run)


def _run_places(session: Db, run: ScheduleRun) -> tuple[list[dict], dict[UUID, Venue]]:
    """The run's windows keyed by place (a court, or a venue standing for all its courts) and the venues used."""
    windows, venues = [], {}
    for window in run.time_slots:
        place = UUID(window.get("venue_id") or window["resource_id"])
        if window.get("venue_id"):
            venue = session.get(Venue, place)
            if venue is None or not venue.is_active:
                continue  # a venue removed or deactivated since the run was set up: its window offers no slots
            venues[place] = venue
        windows.append(window | {"resource_id": place})
    return windows, venues


def _preferences(session: Db, team_ids: list[UUID]) -> dict:
    rows = (
        session.scalars(select(TeamPreference).where(TeamPreference.competition_team_id.in_(team_ids)))
        if team_ids
        else []
    )
    prefs: dict = defaultdict(list)
    for row in rows:
        prefs[row.competition_team_id].append(
            {"kind": row.kind, "value": row.value, "wants": row.wants, "is_priority": row.is_priority}
        )
    return prefs


def generate_schedule_chunk(session: Db, run_id: UUID) -> bool:
    """One chunk of the generator job (internal): the next competition of a 'generating' run. Slots already
    taken by this run's games are not offered again, so a redelivered chunk after a crash starts from the
    committed cursor. Returns True while competitions remain; the last chunk sets 'previewed' and the stats."""
    run = session.get(ScheduleRun, run_id, with_for_update=True)
    if run is None or run.state != "generating":
        return False
    progress = dict(run.progress)
    index = progress.get("next", 0)
    zone = _zone(session, run.location_id)
    windows, venues = _run_places(session, run)
    every = roundrobin.slots(
        run.starts_on, run.ends_on or run.starts_on, windows, run.game_length_min, frozenset(run.excluded_dates or [])
    )
    if index < len(run.competition_ids):
        taken = set()
        for game in session.scalars(select(Game).where(Game.schedule_run_id == run.id, Game.starts_at.is_not(None))):
            local = game.starts_at.astimezone(zone)
            taken.add(roundrobin.Slot(local.date(), local.time(), game.venue_id or game.resource_id))
        free = [slot for slot in every if slot not in taken]
        counts, home_away = progress["counts"], progress["home_away"]
        competition_id = UUID(str(run.competition_ids[index]))
        divisions = session.scalars(
            select(Division).where(Division.competition_id == competition_id).order_by(Division.sort_order)
        ).all()
        for division in divisions:
            teams = list(session.scalars(
                select(CompetitionTeam.id).where(
                    CompetitionTeam.competition_id == competition_id, CompetitionTeam.division_id == division.id,
                    CompetitionTeam.status == "active",
                ).order_by(CompetitionTeam.seed.nulls_last(), CompetitionTeam.created_at)
            ))  # fmt: skip
            rounds = roundrobin.pairings(teams, run.rounds)
            if run.bye_mode == "fold_last_round":
                rounds = roundrobin.fold_last_round(rounds)
            elif run.bye_mode == "rotate_extra_game":
                rounds = roundrobin.rotate_extra_games(rounds)
            placed = roundrobin.assign(
                rounds, free, bye_takes_slot=run.bye_mode == "occupy_slot", prefs=_preferences(session, teams),
                length_min=run.game_length_min,
            )  # fmt: skip
            used = {p["slot"] for p in placed if p["slot"] is not None}
            free = [slot for slot in free if slot not in used]
            for pair in placed:
                bye, slot = pair["away"] is None, pair["slot"]
                venue = venues.get(slot.resource_id) if slot else None
                starts = datetime.combine(slot.on, slot.start, zone) if slot else None
                status = "bye" if bye else ("proposed" if slot else "unschedulable")
                session.add(Game(
                    location_id=run.location_id, competition_id=competition_id, division_id=division.id,
                    schedule_run_id=run.id, home_team_id=pair["home"], away_team_id=pair["away"],
                    venue_id=venue.id if venue else None,
                    resource_id=(venue.resource_ids[0] if venue else slot.resource_id) if slot else None,
                    starts_at=starts, ends_at=starts + timedelta(minutes=run.game_length_min) if starts else None,
                    length_min=run.game_length_min, status=status, round_no=pair["round_no"], is_bye=bye,
                    conflict_note=None if slot or bye else {"reason": "no-free-slot"},
                ))  # fmt: skip
                counts["byes" if bye else "games"] += 1
                counts["unschedulable"] += status == "unschedulable"
                if not bye:
                    for side in ("home", "away"):
                        tally = home_away.setdefault(str(pair[side]), {"home": 0, "away": 0})
                        tally[side] += 1
        index += 1
        progress |= {"next": index, "counts": counts, "home_away": home_away}
        run.progress = progress
        session.flush()
    if index < len(run.competition_ids):
        return True
    last = session.scalar(select(func.max(Game.starts_at)).where(Game.schedule_run_id == run.id))
    run.state, run.wizard_step = "previewed", max(run.wizard_step or 0, 6)
    run.result_stats = progress["counts"] | {
        "home_away": progress["home_away"],
        "predicted_completion_on": last.astimezone(zone).date().isoformat() if last else None,
    }  # fmt: skip
    audit.record(
        session, GENERATE, run, location_id=run.location_id,
        changes={"state": ["generating", "previewed"]} | {k: [None, v] for k, v in progress["counts"].items()},
    )  # fmt: skip
    session.flush()
    return False


def fail_schedule_run(session: Db, run_id: UUID) -> None:
    """Dead-letter hook of the generator job: the run shows 'failed' and can be generated again."""
    run = session.get(ScheduleRun, run_id, with_for_update=True)
    if run is not None and run.state == "generating":
        run.state = "failed"
        audit.record(session, GENERATE, run, location_id=run.location_id, changes={"state": ["generating", "failed"]})
        session.flush()


def list_schedule_run_games(session: Db, principal: Principal, run_id: UUID, query: ListQuery) -> dict:
    run = _scoped(session, principal, ScheduleRun, run_id, GENERATE)
    page = paginate(
        session, select(Game).where(Game.schedule_run_id == run.id), query, id_column=Game.id,
        sort_fields={"created_at": Game.created_at}, default_sort="created_at",
        filter_fields={"status": Game.status, "competition_id": Game.competition_id},
    )  # fmt: skip
    return page | {"data": game_views(session, page["data"])}


def commit_schedule(session: Db, principal: Principal, run_id: UUID) -> dict:
    """Book every proposed game through scheduling, each in its own savepoint. A clash with any hold (another
    game, a rental, a blackout) leaves that game 'unschedulable' with the reason; the rest are booked. With
    `removes_previous_games` the competitions' unplayed games from earlier runs are cancelled first."""
    run = _scoped(session, principal, ScheduleRun, run_id, GENERATE, lock=True)
    if run.state != "previewed":
        raise Conflict("Generate a preview before committing.")
    if run.removes_previous_games:
        stale = session.scalars(select(Game).where(
            Game.competition_id.in_(run.competition_ids), Game.schedule_run_id.is_not(None),
            Game.schedule_run_id != run.id, Game.status.in_(("scheduled", "proposed", "unschedulable", "postponed")),
        )).all()  # fmt: skip
        for game in stale:
            _release(session, game, "cancelled")
    booked = failed = 0
    proposed = session.scalars(
        select(Game).where(Game.schedule_run_id == run.id, Game.status == "proposed").order_by(Game.starts_at)
    ).all()
    for game in proposed:
        resource_id, starts_at = game.resource_id, game.starts_at
        venue = session.get(Venue, game.venue_id) if game.venue_id else None
        try:
            with session.begin_nested():
                _place(session, game, resource_id, starts_at, venue=venue)
            booked += 1
        except Conflict as exc:
            session.refresh(game)
            game.status, game.booking_id = "unschedulable", None
            game.conflict_note = {"reason": exc.code, "detail": exc.detail}
            failed += 1
    run.state, run.committed_at, run.wizard_step = "committed", clock.now(), 7
    run.result_stats = (run.result_stats or {}) | {"booked": booked, "unschedulable_on_commit": failed}
    audit.record(
        session, GENERATE, run, location_id=run.location_id,
        changes={"state": ["previewed", "committed"], "booked": [None, booked]},
    )  # fmt: skip
    session.flush()
    events.publish(
        session, ev.ScheduleGenerated(
            schedule_run_id=run.id, location_id=run.location_id, scheduled_count=booked, unschedulable_count=failed,
        ), run.id,
    )  # fmt: skip
    return run_view(run)


def discard_schedule_run(session: Db, principal: Principal, run_id: UUID) -> dict:
    run = _open_run(session, principal, run_id)
    session.execute(delete(Game).where(Game.schedule_run_id == run.id))
    audit.record(session, GENERATE, run, location_id=run.location_id, changes={"state": [run.state, "discarded"]})
    run.state = "discarded"
    session.flush()
    return run_view(run)


# --- brackets (LGE-12) ------------------------------------------------------------------------------------------


def _bracket_view(session: Db, bracket: Bracket) -> dict:
    slots = session.scalars(
        select(BracketSlot).where(BracketSlot.bracket_id == bracket.id)
        .order_by(BracketSlot.side.desc(), BracketSlot.round_no, BracketSlot.position)
    ).all()  # fmt: skip
    return _columns(bracket) | {"slots": [_columns(s) for s in slots]}


def list_brackets(session: Db, principal: Principal, competition_id: UUID) -> list[dict]:
    competition = _competition(session, principal, competition_id, MANAGE)
    rows = session.scalars(select(Bracket).where(Bracket.competition_id == competition.id).order_by(Bracket.created_at))
    return [_bracket_view(session, b) for b in rows]


def get_bracket(session: Db, principal: Principal, bracket_id: UUID) -> dict:
    bracket, _ = _child(session, principal, Bracket, bracket_id, MANAGE)
    return _bracket_view(session, bracket)


def _seeded(session: Db, competition: Competition, data: dict) -> list[UUID]:
    stmt = select(CompetitionTeam).where(
        CompetitionTeam.competition_id == competition.id, CompetitionTeam.status == "active"
    )
    if data.get("division_id"):
        stmt = stmt.where(CompetitionTeam.division_id == data["division_id"])
    entries = {e.id: e for e in session.scalars(stmt)}
    source = data.get("seed_source") or "seeds"
    if source == "manual":
        ids = data.get("competition_team_ids") or []
        if len(set(ids)) != len(ids) or any(i not in entries for i in ids):
            raise ValidationFailed("Unknown or repeated team entry.", pointer="/competition_team_ids")
        return ids
    if source == "standings":
        ranked = _ordered_standings(session, competition.id, data.get("division_id"))
        return [s.competition_team_id for s in ranked if s.competition_team_id in entries]
    if source == "pools":
        # LGE-11: each division is a pool; the top N of every pool advance, rank by rank (A1, B1, A2, B2), so the
        # bracket's seed order crosses the pools over (A1 meets B2)
        per = data.get("advance_per_pool") or 2
        pools = session.scalars(
            select(Division).where(Division.competition_id == competition.id).order_by(Division.sort_order)
        ).all()
        ranked = [
            [s.competition_team_id for s in _ordered_standings(session, competition.id, pool.id)
             if s.competition_team_id in entries][:per]
            for pool in pools
        ]  # fmt: skip
        return [pool[rank] for rank in range(per) for pool in ranked if rank < len(pool)]
    return [e.id for e in sorted(entries.values(), key=lambda e: (e.seed is None, e.seed or 0, e.created_at))]


def generate_bracket(session: Db, principal: Principal, competition_id: UUID, data: dict) -> dict:
    """A draft bracket from seeds, final standings, pool standings (crossover) or a manual order: single
    elimination (optional third-place game), double elimination (LGE-12, optional grand-final reset) or
    three games guaranteed (LGE-13, exactly eight teams). Byes go to the top seeds and advance at once."""
    competition = _competition(session, principal, competition_id, GENERATE, lock=True)
    kind = data.get("bracket_type") or "single_elimination"
    division = _division(session, competition, data["division_id"]) if data.get("division_id") else None
    teams = _seeded(session, competition, data)
    if len(teams) < 2:
        raise ValidationFailed("A bracket needs at least two teams.", pointer="/seed_source")
    third = bool(data.get("has_third_place_game")) and kind == "single_elimination"
    reset = bool(data.get("has_reset_game")) and kind == "double_elimination"
    try:
        if kind == "double_elimination":
            size, layout = bracket_layout.double_elimination(len(teams), reset=reset)
        elif kind == "three_games_guaranteed":
            size, layout = bracket_layout.three_games_guaranteed(len(teams))
        else:
            size, layout = bracket_layout.single_elimination(len(teams), third_place=third)
    except ValueError as exc:
        raise ValidationFailed(str(exc), pointer="/bracket_type") from exc
    bracket = Bracket(
        competition_id=competition.id, division_id=division.id if division else None, name=data["name"],
        bracket_type=kind, size=size, has_third_place_game=third, has_reset_game=reset,
    )  # fmt: skip
    session.add(bracket)
    session.flush()
    by_key = {}
    for spec in layout:
        slot = BracketSlot(
            bracket_id=bracket.id, side=spec["side"], round_no=spec["round_no"], position=spec["position"],
            round_name=spec["round_name"], home_seed=spec["home_seed"], away_seed=spec["away_seed"],
            is_bye=spec["is_bye"], home_team_id=teams[spec["home_seed"] - 1] if spec["home_seed"] else None,
            away_team_id=teams[spec["away_seed"] - 1] if spec["away_seed"] else None,
        )  # fmt: skip
        for side in ("home", "away"):
            source = spec[f"{side}_source"]
            if source:
                setattr(slot, f"{side}_source_slot_id", by_key[source[:3]].id)
                setattr(slot, f"{side}_source_outcome", source[3])
        session.add(slot)
        session.flush()
        by_key[(spec["side"], spec["round_no"], spec["position"])] = slot
    for slot in by_key.values():
        if slot.is_bye:
            slot.winner_competition_team_id = slot.home_team_id
            _feed(session, slot, slot.home_team_id, None)
    audit.record(session, GENERATE, bracket, location_id=competition.location_id, changes={"size": [None, size]})
    session.flush()
    return _bracket_view(session, bracket)


def _feed(session: Db, slot: BracketSlot, winner_id: UUID | None, loser_id: UUID | None) -> None:
    """Write a decided slot's winner (and loser) into the slots it feeds, and into their games."""
    dependants = session.scalars(select(BracketSlot).where(
        or_(BracketSlot.home_source_slot_id == slot.id, BracketSlot.away_source_slot_id == slot.id)
    ).with_for_update()).all()  # fmt: skip
    for dependant in dependants:
        for side in ("home", "away"):
            if getattr(dependant, f"{side}_source_slot_id") != slot.id:
                continue
            team = winner_id if getattr(dependant, f"{side}_source_outcome") == "winner" else loser_id
            if dependant.game_id is not None:
                game = session.get(Game, dependant.game_id)
                if game.status == "played" and getattr(game, f"{side}_team_id") != team:
                    raise Conflict("The next game has been played; remove its result first.")
                setattr(game, f"{side}_team_id", team)
            setattr(dependant, f"{side}_team_id", team)
    session.flush()


def _advance(session: Db, slot: BracketSlot, game: Game, data: dict) -> None:
    home_won = standings.winner(data["home"], data["away"]) == "home"
    winner_id = game.home_team_id if home_won else game.away_team_id
    loser_id = game.away_team_id if home_won else game.home_team_id
    slot.winner_competition_team_id = winner_id
    _feed(session, slot, winner_id, loser_id)
    reset = _reset_slot(session, slot)
    if reset is not None and winner_id == slot.home_team_id:
        # the unbeaten winners champion took the grand final: the reset game is not needed
        reset.winner_competition_team_id = winner_id
        if reset.game_id is not None:
            _release(session, session.get(Game, reset.game_id), "cancelled")
    elif reset is not None and reset.winner_competition_team_id is not None:
        reset_game = session.get(Game, reset.game_id) if reset.game_id else None
        if reset_game is None or reset_game.status == "cancelled":  # a corrected grand final: the reset is on again
            reset.winner_competition_team_id = None
            if reset_game is not None:
                reset_game.status = "proposed"
    open_slots = session.scalar(
        select(func.count()).select_from(BracketSlot).where(
            BracketSlot.bracket_id == slot.bracket_id, BracketSlot.winner_competition_team_id.is_(None)
        )
    )  # fmt: skip
    if not open_slots:
        session.get(Bracket, slot.bracket_id).status = "completed"


def _reset_slot(session: Db, slot: BracketSlot) -> BracketSlot | None:
    """The grand-final reset slot fed by this slot, when it is the first grand final of a reset bracket."""
    if (slot.side, slot.round_no) != ("final", 1):
        return None
    return session.scalar(
        select(BracketSlot).where(BracketSlot.bracket_id == slot.bracket_id, BracketSlot.side == "final",
                                  BracketSlot.round_no == 2).with_for_update()
    )  # fmt: skip


def _unadvance(session: Db, slot: BracketSlot) -> None:
    reset = _reset_slot(session, slot)
    if reset is not None and reset.winner_competition_team_id is not None:
        game = session.get(Game, reset.game_id) if reset.game_id else None
        if game is not None and game.status == "played":
            raise Conflict("The next game has been played; remove its result first.")
        reset.winner_competition_team_id = None
        if game is not None and game.status == "cancelled":
            game.status = "proposed"
    _feed(session, slot, None, None)
    slot.winner_competition_team_id = None
    bracket = session.get(Bracket, slot.bracket_id)
    if bracket.status == "completed":
        bracket.status = "published"


def delete_bracket(session: Db, principal: Principal, bracket_id: UUID) -> None:
    bracket, competition = _child(session, principal, Bracket, bracket_id, GENERATE, lock=True)
    games = list(session.scalars(
        select(Game).join(BracketSlot, BracketSlot.game_id == Game.id).where(BracketSlot.bracket_id == bracket.id)
    ))  # fmt: skip
    if any(g.status == "played" for g in games):
        raise Conflict("The bracket has results; it cannot be deleted.", code="in-use")
    audit.record(session, GENERATE, bracket, location_id=competition.location_id, changes={"deleted": [False, True]})
    session.execute(update(BracketSlot).where(BracketSlot.bracket_id == bracket.id).values(game_id=None))
    for game in games:
        _release(session, game, "cancelled")
        session.delete(game)
    session.delete(bracket)
    session.flush()


def update_bracket_slot(session: Db, principal: Principal, slot_id: UUID, data: dict) -> dict:
    """In a draft: set the teams of a first-round slot by hand. Once published: give the slot's game a court
    and time (the same booking path as any game)."""
    slot = _get(session, BracketSlot, slot_id, lock=True)
    bracket, competition = _child(session, principal, Bracket, slot.bracket_id, GENERATE, lock=True)
    teams = {k: data[k] for k in ("home_team_id", "away_team_id") if data.get(k) is not None}
    if teams:
        if bracket.status != "draft" or slot.round_no != 1 or slot.side != "winners":
            raise Conflict("Teams are set by hand only on first-round slots of a draft bracket.")
        _check_sides(
            session, competition, teams.get("home_team_id", slot.home_team_id),
            teams.get("away_team_id", slot.away_team_id),
        )  # fmt: skip
        audit.record(session, GENERATE, slot, location_id=competition.location_id, changes=_apply(slot, teams))
    if _court_and_time(data):
        if slot.game_id is None:
            raise Conflict("Publish the bracket before scheduling its games.")
        authorize(principal, GAMES, location_id=competition.location_id)  # booking a court is a game move (W2-07)
        game = session.get(Game, slot.game_id)
        _place_from(session, game, data)
        audit.record(
            session, GAMES, game, location_id=game.location_id, changes={"starts_at": [None, _plain(game.starts_at)]}
        )
        _publish(session, game, ev.GameRescheduled)
    session.flush()
    return _columns(slot)


def publish_bracket(session: Db, principal: Principal, bracket_id: UUID) -> dict:
    """Create a post-season game for every slot that will be played, with placeholder labels for sides still
    to be decided. Games start 'proposed' and are booked slot by slot (updateBracketSlot)."""
    bracket, competition = _child(session, principal, Bracket, bracket_id, GENERATE, lock=True)
    if bracket.status != "draft":
        raise Conflict("The bracket is already published.")
    slots = session.scalars(
        select(BracketSlot).where(BracketSlot.bracket_id == bracket.id, BracketSlot.is_bye.is_(False))
    ).all()
    by_id = {s.id: s for s in slots} | {
        s.id: s for s in session.scalars(select(BracketSlot).where(BracketSlot.bracket_id == bracket.id))
    }
    for slot in slots:
        labels = {}
        for side in ("home", "away"):
            source = getattr(slot, f"{side}_source_slot_id")
            if source is not None and getattr(slot, f"{side}_team_id") is None:
                feeder = by_id[source]
                outcome = getattr(slot, f"{side}_source_outcome").title()
                labels[side] = f"{outcome} of {feeder.round_name} {feeder.position}"
        game = Game(
            location_id=competition.location_id, competition_id=competition.id, division_id=bracket.division_id,
            home_team_id=slot.home_team_id, away_team_id=slot.away_team_id, home_label=labels.get("home"),
            away_label=labels.get("away"), length_min=competition.game_length_min, status="proposed",
            game_type="post_season", round_no=slot.round_no, round_label=slot.round_name,
        )  # fmt: skip
        session.add(game)
        session.flush()
        slot.game_id = game.id
    bracket.status = "published"
    audit.record(
        session, GENERATE, bracket, location_id=competition.location_id, changes={"status": ["draft", "published"]}
    )
    session.flush()
    return _bracket_view(session, bracket)


# --- public schedule and standings (anonymous, tenant from the host) --------------------------------------------

_PUBLIC_STATUSES = ("active", "completed")


def _public_competition(session: Db, competition_id: UUID) -> Competition:
    row = session.get(Competition, competition_id)
    if row is None or not row.is_public or row.status not in _PUBLIC_STATUSES:
        raise NotFound()
    return row


def _public_view(row: Competition, sport_name: str) -> dict:
    return _columns(row) | {"sport_name": sport_name}


def list_public_competitions(session: Db, location_id: UUID | None = None, filters: dict | None = None) -> list[dict]:
    """LGE-17 filters: sport_id, season_id, kind, status (active or completed) and q (name contains)."""
    stmt = select(Competition).where(Competition.is_public.is_(True), Competition.status.in_(_PUBLIC_STATUSES))
    if location_id is not None:
        stmt = stmt.where(Competition.location_id == location_id)
    for name, value in (filters or {}).items():
        if value is None:
            continue
        if name == "q":
            stmt = stmt.where(Competition.name.ilike(f"%{value.replace('%', '').replace('_', '')}%"))
        else:
            stmt = stmt.where(getattr(Competition, name) == value)
    rows = session.scalars(stmt.order_by(Competition.starts_on.desc(), Competition.name)).all()
    sports = dict(session.execute(select(Sport.id, Sport.name)).all())
    return [_public_view(row, sports.get(row.sport_id, "")) for row in rows]


def get_public_competition(session: Db, competition_id: UUID) -> dict:
    row = _public_competition(session, competition_id)
    return _public_view(row, session.get(Sport, row.sport_id).name)


def list_public_games(session: Db, competition_id: UUID) -> list[dict]:
    """Placed and cancelled games in start order, with venue names; no staff fields."""
    competition = _public_competition(session, competition_id)
    games = session.scalars(
        select(Game).where(Game.competition_id == competition.id, Game.status.in_((*_PLACED, "cancelled")))
        .order_by(Game.starts_at.nulls_last(), Game.id)
    ).all()  # fmt: skip
    courts = {g.resource_id for g in games if g.resource_id}
    venues = {r.id: r.name for r in resources.service.get_many(session, courts)}
    return [
        {
            "id": v["id"], "starts_at": v["starts_at"], "ends_at": v["ends_at"], "venue": venues.get(v["resource_id"]),
            "status": v["status"], "round_label": v["round_label"],
            "home_name": v["home_name"] or v["home_label"], "away_name": v["away_name"] or v["away_label"],
            "home_score": v["home_score"], "away_score": v["away_score"],
        }
        for v in game_views(session, list(games))
    ]  # fmt: skip


def list_public_standings(session: Db, competition_id: UUID) -> list[dict]:
    competition = _public_competition(session, competition_id)
    divisions = dict(
        session.execute(select(Division.id, Division.name).where(Division.competition_id == competition.id)).all()
    )
    fields = (
        "rank", "team_name", "games_played", "wins", "losses", "ties", "goals_for", "goals_against",
        "goal_difference", "win_pct", "points",
    )  # fmt: skip
    return [
        {"division_name": divisions.get(row["division_id"], "")} | {k: row[k] for k in fields}
        for row in _standing_views(session, _ordered_standings(session, competition.id))
    ]
