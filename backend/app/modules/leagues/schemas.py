"""leagues request and response models (docs/api/openapi-programs.yaml, tag leagues). Where the YAML and the data
model disagree the data model wins (README). Public models are separate classes and carry no staff fields."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.core.schemas import In, Out, Page

__all__ = ["Page"]

Name = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(max_length=4000)]
Points = Annotated[Decimal, Field(ge=-100, le=100, max_digits=5, decimal_places=2)]
Wall = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Color = Annotated[str, Field(pattern=r"^#[0-9a-f]{6}$")]
Metric = Literal["GP", "W", "L", "T", "GF", "GA", "PTS", "GD", "WP", "OTL", "FF", "BP", "SPT", "H2H"]
Email = Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class StandingsColumn(In):
    metric: Metric
    heading: Annotated[str, Field(max_length=40)] | None = None


class StandingsSort(In):
    metric: Metric
    direction: Literal["asc", "desc"] = "desc"


class _ScoringIn(In):
    points_win: Points | None = None
    points_tie: Points | None = None
    points_loss: Points | None = None
    points_overtime_loss: Points | None = None
    points_forfeit_win: Points | None = None
    points_forfeit_loss: Points | None = None
    points_default_loss: Points | None = None
    forfeit_score_for: Annotated[int, Field(ge=0, le=1000)] | None = None
    tracks_sportsmanship: bool | None = None
    standings_columns: Annotated[list[StandingsColumn], Field(min_length=1, max_length=14)] | None = None
    standings_sort: Annotated[list[StandingsSort], Field(min_length=1, max_length=8)] | None = None


class _ScoringOut(Out):
    points_win: Decimal
    points_tie: Decimal
    points_loss: Decimal
    points_overtime_loss: Decimal
    points_forfeit_win: Decimal
    points_forfeit_loss: Decimal
    points_default_loss: Decimal
    forfeit_score_for: int
    tracks_sportsmanship: bool
    standings_columns: list[dict]
    standings_sort: list[dict]


# --- reference lists --------------------------------------------------------------------------------------------


class SportCreate(_ScoringIn):
    name: Name
    default_game_length_min: Annotated[int, Field(gt=0, le=600)] = 60
    default_team_fee_minor: Annotated[int, Field(ge=0)] | None = None
    fees_text: Text | None = None
    rules_text: Text | None = None
    is_active: bool = True


class SportUpdate(_ScoringIn):
    name: Name | None = None
    default_game_length_min: Annotated[int, Field(gt=0, le=600)] | None = None
    default_team_fee_minor: Annotated[int, Field(ge=0)] | None = None
    fees_text: Text | None = None
    rules_text: Text | None = None
    is_active: bool | None = None


class SportOut(_ScoringOut):
    id: UUID
    name: str
    default_game_length_min: int
    default_team_fee_minor: int | None
    fees_text: str | None
    rules_text: str | None
    is_active: bool


class AgeGroupWrite(In):
    name: Name | None = None
    min_age: Annotated[int, Field(ge=0, le=120)] | None = None
    max_age: Annotated[int, Field(ge=0, le=120)] | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class AgeGroupOut(Out):
    id: UUID
    name: str
    min_age: int | None
    max_age: int | None
    sort_order: int
    is_active: bool


class SeasonWrite(In):
    name: Name | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool | None = None


class SeasonOut(Out):
    id: UUID
    name: str
    starts_on: date | None
    ends_on: date | None
    is_active: bool


# --- competitions -----------------------------------------------------------------------------------------------

_KIND = Literal["league", "tournament"]
_FORMAT = Literal["round_robin", "pool_play", "single_elimination", "double_elimination", "three_games_guaranteed"]


class _CompetitionFields(_ScoringIn):
    age_group_id: UUID | None = None
    season_id: UUID | None = None
    division_label: Annotated[str, Field(max_length=100)] | None = None
    ends_on: date | None = None
    game_length_min: Annotated[int, Field(gt=0, le=600)] | None = None
    is_public: bool | None = None
    shows_roster_publicly: bool | None = None
    max_defaults: Annotated[int, Field(ge=0)] | None = None
    max_forfeits: Annotated[int, Field(ge=0)] | None = None
    min_sportsmanship: Annotated[Decimal, Field(ge=0, le=99, max_digits=4, decimal_places=2)] | None = None
    team_fee_text: Text | None = None
    more_info: Text | None = None
    rules_text: Text | None = None
    registration_url: Annotated[str, Field(max_length=500, pattern=r"^https://")] | None = None
    color: Color | None = None
    team_fee_minor: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    revenue_category_id: UUID | None = None


class CompetitionCreate(_CompetitionFields):
    location_id: UUID
    kind: _KIND
    format: _FORMAT = "round_robin"
    name: Name
    sport_id: UUID
    starts_on: date


class CompetitionUpdate(_CompetitionFields):
    name: Name | None = None
    format: _FORMAT | None = None
    starts_on: date | None = None


class CompetitionOut(_ScoringOut):
    id: UUID
    location_id: UUID
    kind: str
    format: str
    name: str
    sport_id: UUID
    age_group_id: UUID | None
    season_id: UUID | None
    division_label: str | None
    starts_on: date
    ends_on: date | None
    game_length_min: int
    status: str
    is_public: bool
    shows_roster_publicly: bool
    max_defaults: int | None
    max_forfeits: int | None
    min_sportsmanship: Decimal | None
    team_fee_text: str | None
    more_info: str | None
    rules_text: str | None
    registration_url: str | None
    color: str | None
    team_fee_minor: int | None
    revenue_category_id: UUID | None
    created_at: datetime


class DivisionWrite(In):
    name: Name | None = None
    kind: Literal["division", "pool"] | None = None
    sort_order: int | None = None


class DivisionOut(Out):
    id: UUID
    competition_id: UUID
    name: str
    kind: str
    sort_order: int


# --- teams, entries and rosters ---------------------------------------------------------------------------------


class LeagueTeamCreate(In):
    location_id: UUID
    name: Name
    captain_client_id: UUID | None = None
    color: Color | None = None


class LeagueTeamUpdate(In):
    name: Name | None = None
    captain_client_id: UUID | None = None
    color: Color | None = None
    is_active: bool | None = None


class LeagueTeamOut(Out):
    id: UUID
    location_id: UUID
    name: str
    captain_client_id: UUID | None
    color: str | None
    is_placeholder: bool
    is_active: bool


class NewTeam(In):
    name: Name
    captain_client_id: UUID | None = None
    color: Color | None = None


class CompetitionTeamCreate(In):
    """Register a team: an existing `team_id` or a new `team`. `bill_to_client_id` charges the competition's
    team fee to that client through billing in the same transaction."""

    team_id: UUID | None = None
    team: NewTeam | None = None
    division_id: UUID | None = None
    seed: Annotated[int, Field(gt=0)] | None = None
    display_name: Name | None = None
    bill_to_client_id: UUID | None = None


class CompetitionTeamUpdate(In):
    division_id: UUID | None = None
    seed: Annotated[int, Field(gt=0)] | None = None
    display_name: Name | None = None
    status: Literal["active", "withdrawn"] | None = None


class TeamFeeBill(In):
    bill_to_client_id: UUID


class CompetitionTeamOut(Out):
    id: UUID
    competition_id: UUID
    division_id: UUID
    team_id: UUID
    name: str
    seed: int | None
    display_name: str | None
    status: str
    fee_status: str
    fee_client_id: UUID | None
    invoice_id: UUID | None = None


class TeamGenerate(In):
    count: Annotated[int, Field(ge=1, le=64)]
    name_prefix: Annotated[str, Field(min_length=1, max_length=60)] = "Team"
    division_id: UUID | None = None


class TeamCopy(In):
    source_competition_id: UUID
    competition_team_ids: Annotated[list[UUID], Field(max_length=128)] | None = None
    includes_rosters: bool = False


class Seeding(In):
    competition_team_ids: Annotated[list[UUID], Field(min_length=1, max_length=128)]


class RosterEntryCreate(In):
    client_id: UUID | None = None
    first_name: Name | None = None
    last_name: Name | None = None
    role: Literal["player", "captain", "coach", "manager"] = "player"
    jersey_number: Annotated[str, Field(max_length=10)] | None = None
    position: Annotated[str, Field(max_length=40)] | None = None


class RosterEntryUpdate(In):
    client_id: UUID | None = None
    role: Literal["player", "captain", "coach", "manager"] | None = None
    jersey_number: Annotated[str, Field(max_length=10)] | None = None
    position: Annotated[str, Field(max_length=40)] | None = None
    status: Literal["active", "removed"] | None = None


class LeagueRosterEntryOut(Out):
    id: UUID
    competition_team_id: UUID
    client_id: UUID | None
    name: str
    role: str
    jersey_number: str | None
    position: str | None
    origin: str
    status: str


# --- standings --------------------------------------------------------------------------------------------------


class LeagueStandingOut(Out):
    id: UUID
    competition_team_id: UUID
    division_id: UUID
    team_name: str
    rank: int
    games_played: int
    wins: int
    losses: int
    ties: int
    overtime_losses: int
    forfeits: int
    defaults: int
    goals_for: int
    goals_against: int
    goal_difference: int
    win_pct: Decimal
    bonus_points: Decimal
    adjustment_points: Decimal
    adjustment_reason: str | None
    points: Decimal
    sportsmanship_avg: Decimal | None
    is_over_discipline_cap: bool


class StandingAdjust(In):
    adjustment_points: Annotated[Decimal, Field(ge=-1000, le=1000, max_digits=7, decimal_places=2)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]


# --- schedule runs ----------------------------------------------------------------------------------------------

_BYE = Literal["hidden", "occupy_slot", "fold_last_round", "rotate_extra_game"]


class TimeWindow(In):
    weekday: Annotated[int, Field(ge=1, le=7)]
    starts_at: Wall
    ends_at: Wall
    resource_id: UUID


class ScheduleRunCreate(In):
    location_id: UUID
    competition_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]
    resource_ids: Annotated[list[UUID], Field(min_length=1, max_length=50)]
    time_slots: Annotated[list[TimeWindow], Field(min_length=1, max_length=200)]
    starts_on: date
    ends_on: date
    blackout_dates: Annotated[list[date], Field(max_length=366)] = []
    game_length_min: Annotated[int, Field(gt=0, le=600)] | None = None
    rounds: Annotated[int, Field(ge=1, le=60)] | None = None
    bye_mode: _BYE = "hidden"
    removes_previous_games: bool = False


class ScheduleRunUpdate(In):
    resource_ids: Annotated[list[UUID], Field(min_length=1, max_length=50)] | None = None
    time_slots: Annotated[list[TimeWindow], Field(min_length=1, max_length=200)] | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    blackout_dates: Annotated[list[date], Field(max_length=366)] | None = None
    game_length_min: Annotated[int, Field(gt=0, le=600)] | None = None
    rounds: Annotated[int, Field(ge=1, le=60)] | None = None
    bye_mode: _BYE | None = None
    removes_previous_games: bool | None = None
    wizard_step: Annotated[int, Field(ge=1, le=7)] | None = None


class ScheduleRunOut(Out):
    id: UUID
    location_id: UUID
    kind: str
    state: str
    wizard_step: int
    competition_ids: list[UUID]
    resource_ids: list[UUID]
    time_slots: list[dict]
    starts_on: date
    ends_on: date | None
    blackout_dates: list[date]
    game_length_min: int
    rounds: int | None
    bye_mode: str
    removes_previous_games: bool
    stats: dict | None
    committed_at: datetime | None


# --- games ------------------------------------------------------------------------------------------------------

Label = Annotated[str, Field(max_length=100)]


class GameCreate(In):
    competition_id: UUID
    division_id: UUID | None = None
    home_team_id: UUID | None = None
    away_team_id: UUID | None = None
    home_label: Label | None = None
    away_label: Label | None = None
    resource_id: UUID | None = None
    starts_at: datetime | None = None
    length_min: Annotated[int, Field(gt=0, le=600)] | None = None
    game_type: Literal["regular", "post_season"] = "regular"
    round_label: Label | None = None
    notes: Text | None = None


class GameUpdate(In):
    home_team_id: UUID | None = None
    away_team_id: UUID | None = None
    home_label: Label | None = None
    away_label: Label | None = None
    game_type: Literal["regular", "post_season"] | None = None
    round_label: Label | None = None
    notes: Text | None = None
    version: int | None = None


class GameReschedule(In):
    resource_id: UUID
    starts_at: datetime
    length_min: Annotated[int, Field(gt=0, le=600)] | None = None


class GamePostpone(In):
    resource_id: UUID | None = None
    starts_at: datetime | None = None


class GameOut(Out):
    id: UUID
    location_id: UUID
    competition_id: UUID
    division_id: UUID | None
    schedule_run_id: UUID | None
    home_team_id: UUID | None
    away_team_id: UUID | None
    home_name: str | None
    away_name: str | None
    home_label: str | None
    away_label: str | None
    booking_id: UUID | None
    resource_id: UUID | None
    starts_at: datetime | None
    ends_at: datetime | None
    length_min: int
    status: str
    game_type: str
    round_no: int | None
    round_label: str | None
    is_bye: bool
    conflict_note: dict | None
    notes: str | None
    home_score: int | None = None
    away_score: int | None = None
    version: int


class GameSideIn(In):
    score: Annotated[int, Field(ge=0, le=10_000)] | None = None
    participation: Literal["full", "default", "forfeit"] = "full"
    went_to_overtime: bool = False
    bonus_points: Annotated[Decimal, Field(ge=-100, le=100, max_digits=5, decimal_places=2)] = Decimal(0)
    sportsmanship: Annotated[Decimal, Field(ge=0, le=99, max_digits=4, decimal_places=2)] | None = None


class GameResultPut(In):
    home: GameSideIn
    away: GameSideIn


class GameSideOut(Out):
    competition_team_id: UUID
    score: int | None
    participation: str
    went_to_overtime: bool
    bonus_points: Decimal
    sportsmanship: Decimal | None
    outcome: str


class GameResultOut(Out):
    game_id: UUID
    status: str
    home: GameSideOut | None
    away: GameSideOut | None
    recorded_at: datetime | None


# --- officials --------------------------------------------------------------------------------------------------


class OfficialCreate(In):
    location_id: UUID
    first_name: Name
    last_name: Name
    email: Email | None = None
    phone: Annotated[str, Field(max_length=40)] | None = None
    staff_user_id: UUID | None = None
    sport_ids: Annotated[list[UUID], Field(max_length=50)] = []
    age_group_ids: Annotated[list[UUID], Field(max_length=50)] = []


class OfficialUpdate(In):
    first_name: Name | None = None
    last_name: Name | None = None
    email: Email | None = None
    phone: Annotated[str, Field(max_length=40)] | None = None
    staff_user_id: UUID | None = None
    sport_ids: Annotated[list[UUID], Field(max_length=50)] | None = None
    age_group_ids: Annotated[list[UUID], Field(max_length=50)] | None = None
    is_active: bool | None = None


class OfficialOut(Out):
    id: UUID
    location_id: UUID
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    staff_user_id: UUID | None
    sport_ids: list[UUID]
    age_group_ids: list[UUID]
    is_active: bool


class Assignment(In):
    official_id: UUID
    role: Literal["referee", "assistant", "scorekeeper", "other"] = "referee"


class GameOfficialsPut(In):
    assignments: Annotated[list[Assignment], Field(max_length=10)]


class GameOfficialOut(Out):
    id: UUID
    game_id: UUID
    official_id: UUID
    role: str
    name: str


# --- brackets ---------------------------------------------------------------------------------------------------


class BracketGenerate(In):
    name: Name = "Playoffs"
    bracket_type: Literal["single_elimination", "double_elimination", "three_games_guaranteed"]
    seed_source: Literal["seeds", "standings", "manual"]
    competition_team_ids: Annotated[list[UUID], Field(max_length=128)] | None = None
    division_id: UUID | None = None
    has_third_place_game: bool = False


class BracketSlotUpdate(In):
    home_team_id: UUID | None = None
    away_team_id: UUID | None = None
    resource_id: UUID | None = None
    starts_at: datetime | None = None


class BracketSlotOut(Out):
    id: UUID
    side: str
    round_no: int
    round_name: str
    position: int
    game_id: UUID | None
    home_seed: int | None
    away_seed: int | None
    home_team_id: UUID | None
    away_team_id: UUID | None
    home_source_slot_id: UUID | None
    home_source_outcome: str | None
    away_source_slot_id: UUID | None
    away_source_outcome: str | None
    is_bye: bool
    winner_competition_team_id: UUID | None


class BracketOut(Out):
    id: UUID
    competition_id: UUID
    division_id: UUID | None
    name: str
    bracket_type: str
    size: int
    has_third_place_game: bool
    status: str
    slots: list[BracketSlotOut]


# --- public (anonymous) -----------------------------------------------------------------------------------------


class PublicCompetitionOut(Out):
    id: UUID
    location_id: UUID
    kind: str
    format: str
    name: str
    sport_name: str
    status: str
    starts_on: date
    ends_on: date | None
    division_label: str | None
    team_fee_text: str | None
    more_info: str | None
    rules_text: str | None
    registration_url: str | None


class PublicGameOut(Out):
    id: UUID
    starts_at: datetime | None
    ends_at: datetime | None
    venue: str | None
    status: str
    round_label: str | None
    home_name: str | None
    away_name: str | None
    home_score: int | None
    away_score: int | None


class PublicStandingOut(Out):
    division_name: str
    rank: int
    team_name: str
    games_played: int
    wins: int
    losses: int
    ties: int
    goals_for: int
    goals_against: int
    goal_difference: int
    win_pct: Decimal
    points: Decimal
