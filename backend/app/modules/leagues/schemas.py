"""leagues request and response models (docs/api/openapi-programs.yaml, tag leagues). Where the YAML and the data
model disagree the data model wins (README). Public models are separate classes and carry no staff fields."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.core.schemas import In, Int4, Out, Page

__all__ = ["Page"]

Name = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(max_length=4000)]
Points = Annotated[Decimal, Field(ge=-100, le=100, max_digits=5, decimal_places=2)]
Wall = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Color = Annotated[str, Field(pattern=r"^#[0-9a-f]{6}$")]
Metric = Literal[
    "GP", "W", "L", "T", "GF", "GA", "PTS", "GD", "WP", "OTL", "FF", "BP", "SPT", "H2H", "SW", "SL", "SR", "PR"
]  # SW, SL: sets won and lost; SR: set ratio; PR: points ratio over played sets (sets competitions)
SetPoints = Annotated[int, Field(ge=1, le=99)]
Email = Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
# int4 columns: a larger number overflowed Postgres (a 500)
Fee = Annotated[int, Field(ge=0, le=2_147_483_647)]


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
    scoring_mode: Literal["points", "sets"] | None = None
    sets_best_of: Literal[1, 3, 5] | None = None
    set_points_to: SetPoints | None = None
    set_win_by: Annotated[int, Field(ge=1, le=5)] | None = None
    set_cap: SetPoints | None = None  # the score that ends a set however close (badminton 30)
    deciding_set_points_to: SetPoints | None = None  # the last possible set's target (volleyball 15)


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
    scoring_mode: str
    sets_best_of: int | None
    set_points_to: int | None
    set_win_by: int
    set_cap: int | None
    deciding_set_points_to: int | None


# --- reference lists --------------------------------------------------------------------------------------------


class SportCreate(_ScoringIn):
    name: Name
    default_game_length_min: Annotated[int, Field(gt=0, le=600)] = 60
    default_team_fee_minor: Fee | None = None
    fees_text: Text | None = None
    rules_text: Text | None = None
    is_active: bool = True


class SportUpdate(_ScoringIn):
    name: Name | None = None
    default_game_length_min: Annotated[int, Field(gt=0, le=600)] | None = None
    default_team_fee_minor: Fee | None = None
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
    sort_order: Int4 | None = None
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
_FORMAT = Literal[
    "round_robin", "pool_play", "single_elimination", "double_elimination", "three_games_guaranteed", "ladder"
]


class _CompetitionFields(_ScoringIn):
    age_group_id: UUID | None = None
    season_id: UUID | None = None
    division_label: Annotated[str, Field(max_length=100)] | None = None
    ends_on: date | None = None
    game_length_min: Annotated[int, Field(gt=0, le=600)] | None = None
    is_public: bool | None = None
    show_players: bool | None = None  # B2: player names and stats on the public site; default off (minors)
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
    ladder_challenge_range: Annotated[int, Field(ge=1, le=20)] | None = None


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
    show_players: bool
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
    ladder_challenge_range: int | None = None
    program_group_id: UUID | None = None
    created_at: datetime


class DivisionWrite(In):
    name: Name | None = None
    kind: Literal["division", "pool"] | None = None
    sort_order: Int4 | None = None


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
    set_points_for: int = 0  # rally points of played sets, sets competitions only
    set_points_against: int = 0
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
    resource_id: UUID | None = None  # a court, or
    venue_id: UUID | None = None  # a league venue holding all its courts (RES-06)


class ScheduleRunCreate(In):
    location_id: UUID
    competition_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]
    resource_ids: Annotated[list[UUID], Field(max_length=50)] = []
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
    progress: dict
    committed_at: datetime | None


# --- games ------------------------------------------------------------------------------------------------------

Label = Annotated[str, Field(max_length=100)]


class LeagueNightIn(In):
    resource_ids: Annotated[list[UUID], Field(min_length=1, max_length=50)]
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    notes: Text | None = None


class LeagueNightOut(Out):
    booking_id: UUID
    competition_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    resource_ids: list[UUID]


class GameCreate(In):
    competition_id: UUID
    division_id: UUID | None = None
    home_team_id: UUID | None = None
    away_team_id: UUID | None = None
    home_label: Label | None = None
    away_label: Label | None = None
    resource_id: UUID | None = None
    venue_id: UUID | None = None
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
    resource_id: UUID | None = None
    venue_id: UUID | None = None
    starts_at: datetime
    length_min: Annotated[int, Field(gt=0, le=600)] | None = None


class GamePostpone(In):
    resource_id: UUID | None = None
    venue_id: UUID | None = None
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
    venue_id: UUID | None = None
    competition_name: str | None = None
    sport_id: UUID | None = None
    ladder_swapped: bool = False
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
    set_scores: str | None = None  # '21-18, 19-21, 21-15' from the home side, sets competitions
    sets_best_of: int | None = None  # set when the competition scores by sets: the score dialog's set rows
    version: int


class GameSideIn(In):
    score: Annotated[int, Field(ge=0, le=10_000)] | None = None  # sets won, derived when `sets` is given
    sets: Annotated[list[Annotated[int, Field(ge=0, le=99)]], Field(max_length=5)] | None = None
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
    sets: list[int] = []
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
    seed_source: Literal["seeds", "standings", "manual", "pools"]
    competition_team_ids: Annotated[list[UUID], Field(max_length=128)] | None = None
    division_id: UUID | None = None
    has_third_place_game: bool = False
    has_reset_game: bool = False  # double elimination: a second grand final if the losers champion wins the first
    advance_per_pool: Annotated[int, Field(ge=1, le=16)] | None = None  # seed_source pools: top N of each division


class BracketSlotUpdate(In):
    home_team_id: UUID | None = None
    away_team_id: UUID | None = None
    resource_id: UUID | None = None
    venue_id: UUID | None = None
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
    has_reset_game: bool
    status: str
    slots: list[BracketSlotOut]


# --- venues, preferences, staff, ladder (RES-06, LGE-10, LGE-26, LGE-28) ----------------------------------------

Ids = Annotated[list[UUID], Field(min_length=1, max_length=20)]


class VenueCreate(In):
    location_id: UUID
    name: Name
    description: Text | None = None
    resource_ids: Ids
    is_active: bool = True


class VenueUpdate(In):
    name: Name | None = None
    description: Text | None = None
    resource_ids: Ids | None = None
    is_active: bool | None = None


class VenueOut(Out):
    id: UUID
    location_id: UUID
    name: str
    description: str | None
    resource_ids: list[UUID]
    is_active: bool


class TeamPreferenceIn(In):
    kind: Literal["date", "weekday", "time", "resource"]
    value: Annotated[str, Field(min_length=1, max_length=40)]  # YYYY-MM-DD, 1-7, HH:MM-HH:MM, court or venue id
    wants: bool = False  # True: prefers it; False: cannot play then
    is_priority: bool = False


class TeamPreferencesPut(In):
    preferences: Annotated[list[TeamPreferenceIn], Field(max_length=50)]


class TeamPreferenceOut(Out):
    id: UUID
    competition_team_id: UUID
    kind: str
    value: str
    wants: bool
    is_priority: bool


class StaffMemberIn(In):
    staff_user_id: UUID
    role: Literal["league_admin", "scorekeeper"] = "scorekeeper"


class CompetitionStaffPut(In):
    staff: Annotated[list[StaffMemberIn], Field(max_length=50)]


class CompetitionStaffOut(Out):
    id: UUID
    competition_id: UUID
    staff_user_id: UUID
    role: str


class StaffCandidateOut(Out):
    id: UUID
    name: str


class LadderPut(In):
    competition_team_ids: Annotated[list[UUID], Field(max_length=200)]


class LadderRungOut(Out):
    competition_team_id: UUID
    position: int
    team_name: str | None


class LadderChallengeCreate(In):
    challenger_id: UUID
    defender_id: UUID
    resource_id: UUID | None = None
    venue_id: UUID | None = None
    starts_at: datetime | None = None
    notes: Text | None = None


# --- stats (LGE-07) ---------------------------------------------------------------------------------------------

Code = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,19}$")]
Formula = Annotated[str, Field(min_length=1, max_length=200)]


class StatTableWrite(In):
    name: Name
    sort_order: Annotated[int, Field(ge=0, le=1000)] = 0


class StatTableUpdate(In):
    name: Name | None = None
    sort_order: Annotated[int, Field(ge=0, le=1000)] | None = None


class StatDefinitionCreate(In):
    code: Code
    name: Name
    kind: Literal["entry", "formula"] = "entry"
    formula: Formula | None = None
    decimal_places: Annotated[int, Field(ge=0, le=4)] = 0
    sort_order: Annotated[int, Field(ge=0, le=1000)] = 0


class StatDefinitionUpdate(In):
    code: Code | None = None
    name: Name | None = None
    formula: Formula | None = None
    decimal_places: Annotated[int, Field(ge=0, le=4)] | None = None
    sort_order: Annotated[int, Field(ge=0, le=1000)] | None = None


class StatDefinitionOut(Out):
    id: UUID
    stat_table_id: UUID
    sport_id: UUID
    code: str
    name: str
    kind: str
    formula: str | None
    decimal_places: int
    sort_order: int


class StatTableOut(Out):
    id: UUID
    sport_id: UUID
    name: str
    sort_order: int
    stats: list[StatDefinitionOut]


class PlayerStatIn(In):
    roster_entry_id: UUID
    stat_definition_id: UUID
    value: Annotated[Decimal, Field(ge=0, le=99_999_999, max_digits=10, decimal_places=2)]


class PlayerStatsPut(In):
    stats: Annotated[list[PlayerStatIn], Field(max_length=2000)]


class PlayerStatOut(Out):
    id: UUID
    game_id: UUID
    roster_entry_id: UUID
    stat_definition_id: UUID
    value: Decimal


class PlayerTotalsOut(Out):
    roster_entry_id: UUID
    competition_team_id: UUID
    player_name: str
    stats: dict[str, Decimal | None]


# --- team fee split, publish from a program group (REG-26, REG-14) ----------------------------------------------


class FeeShareIn(In):
    roster_entry_id: UUID
    amount_minor: Annotated[int, Field(gt=0, le=100_000_000)]


class TeamFeeSplit(In):
    shares: Annotated[list[FeeShareIn], Field(min_length=1, max_length=50)]
    bill_to_client_id: UUID | None = None  # pays whatever the shares leave


class TeamFeeShareOut(Out):
    id: UUID
    competition_team_id: UUID
    roster_entry_id: UUID | None
    client_id: UUID
    amount_minor: int
    charge_id: UUID | None


class ProgramGroupPublish(In):
    program_group_id: UUID
    kind: _KIND
    format: _FORMAT = "round_robin"
    name: Name | None = None
    sport_id: UUID
    starts_on: date
    ends_on: date | None = None
    include_players: bool = True


# --- captain portal (REG-26): portal-only shapes ----------------------------------------------------------------


class PortalLeagueTeamOut(Out):
    competition_team_id: UUID
    team_name: str
    competition_name: str
    starts_on: date


class PortalRosterEntryCreate(In):
    client_id: UUID | None = None
    first_name: Name | None = None
    last_name: Name | None = None
    jersey_number: Annotated[str, Field(max_length=10)] | None = None


class PortalRosterEntryOut(Out):
    id: UUID
    name: str
    role: str
    jersey_number: str | None


# --- public (anonymous) -----------------------------------------------------------------------------------------


class PublicCompetitionOut(Out):
    id: UUID
    location_id: UUID
    kind: str
    format: str
    name: str
    sport_id: UUID
    sport_name: str
    season_id: UUID | None
    show_players: bool
    scoring_mode: str = "points"
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
    set_scores: str | None = None


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


# --- public league site (Phase 14 B2) ---------------------------------------------------------------------------

Url = Annotated[str, Field(max_length=500, pattern=r"^https?://\S+$")]
Short = Annotated[str, Field(min_length=1, max_length=100)]
LongText = Annotated[str, Field(min_length=1, max_length=20000)]


class LeagueSiteIn(In):
    """PUT replaces the whole options set (LGE-19, PLT-12)."""

    is_enabled: bool = False
    title: Name = "Leagues"
    tagline: Annotated[str, Field(max_length=300)] | None = None
    about_text: Text | None = None
    accent_color: Color | None = None
    shows_facility_info: bool = True
    shows_classes: bool = True
    shows_news: bool = True
    shows_gallery: bool = True
    shows_sponsors: bool = True
    shows_links: bool = True
    shows_classifieds: bool = False
    shows_pickup_games: bool = False
    board_refresh_sec: Annotated[int, Field(ge=15, le=600)] = 60


class LeagueSiteOut(Out):
    is_enabled: bool
    title: str
    tagline: str | None
    about_text: str | None
    accent_color: str | None
    shows_facility_info: bool
    shows_classes: bool
    shows_news: bool
    shows_gallery: bool
    shows_sponsors: bool
    shows_links: bool
    shows_classifieds: bool
    shows_pickup_games: bool
    board_refresh_sec: int


class PublicFacilityOut(Out):
    id: UUID
    name: str
    address_line1: str | None
    address_line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    phone: str | None
    email: str | None
    website_url: str | None


class PublicLeagueSiteOut(LeagueSiteOut):
    facilities: list[PublicFacilityOut]


class LeagueLinkCreate(In):
    title: Name
    url: Url
    category: Short | None = None
    sort_order: Annotated[int, Field(ge=0, le=9999)] = 0


class LeagueLinkUpdate(In):
    title: Name | None = None
    url: Url | None = None
    category: Short | None = None
    sort_order: Annotated[int, Field(ge=0, le=9999)] | None = None


class LeagueLinkOut(Out):
    id: UUID
    title: str
    url: str
    category: str | None
    sort_order: int


class PublicLeagueLinkOut(Out):
    title: str
    url: str
    category: str | None


class LeaguePhotoUpdate(In):
    caption: Annotated[str, Field(max_length=300)] | None = None
    album: Short | None = None
    sort_order: Annotated[int, Field(ge=0, le=9999)] | None = None
    is_published: bool | None = None


class LeaguePhotoOut(Out):
    id: UUID
    caption: str | None
    album: str | None
    sort_order: int
    is_published: bool


class PublicLeaguePhotoOut(Out):
    id: UUID
    caption: str | None
    album: str | None


class LeagueSponsorCreate(In):
    name: Name
    url: Url | None = None
    blurb: Annotated[str, Field(max_length=500)] | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    sort_order: Annotated[int, Field(ge=0, le=9999)] = 0
    is_active: bool = True


class LeagueSponsorUpdate(In):
    name: Name | None = None
    url: Url | None = None
    blurb: Annotated[str, Field(max_length=500)] | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    sort_order: Annotated[int, Field(ge=0, le=9999)] | None = None
    is_active: bool | None = None


class LeagueSponsorOut(Out):
    id: UUID
    name: str
    url: str | None
    blurb: str | None
    starts_on: date | None
    ends_on: date | None
    sort_order: int
    is_active: bool
    has_logo: bool


class PublicLeagueSponsorOut(Out):
    id: UUID
    name: str
    url: str | None
    blurb: str | None
    has_logo: bool


class LeagueNewsCreate(In):
    title: Name
    summary: Annotated[str, Field(max_length=500)] | None = None
    body: LongText
    published_at: datetime | None = None
    is_pinned: bool = False


class LeagueNewsUpdate(In):
    title: Name | None = None
    summary: Annotated[str, Field(max_length=500)] | None = None
    body: LongText | None = None
    published_at: datetime | None = None
    is_pinned: bool | None = None


class LeagueNewsOut(Out):
    id: UUID
    title: str
    summary: str | None
    body: str
    published_at: datetime | None
    is_pinned: bool
    created_at: datetime


class PublicLeagueNewsOut(Out):
    id: UUID
    title: str
    summary: str | None
    body: str
    published_at: datetime
    is_pinned: bool


class PublicClassOut(Out):
    id: UUID
    location_name: str
    kind: str
    name: str
    description: str | None
    starts_on: date | None
    ends_on: date | None
    is_open: bool
    spots_left: int | None


class PublicTeamOut(Out):
    name: str
    division_name: str | None
    players: list[str] | None


class PublicPlayerStatOut(Out):
    player_name: str
    team_name: str
    stats: dict[str, Decimal | None]


class PublicBracketSlotOut(Out):
    side: str
    round_no: int
    round_name: str
    position: int
    home_seed: int | None
    away_seed: int | None
    home_name: str | None
    away_name: str | None
    home_score: int | None
    away_score: int | None
    set_scores: str | None = None
    starts_at: datetime | None
    is_bye: bool
    winner: Literal["home", "away"] | None


class PublicBracketOut(Out):
    name: str
    bracket_type: str
    status: str
    slots: list[PublicBracketSlotOut]


class BoardGameOut(Out):
    starts_at: datetime | None
    competition_name: str
    venue: str | None
    status: str
    home_name: str | None
    away_name: str | None
    home_score: int | None
    away_score: int | None
    set_scores: str | None = None


class PublicBoardOut(Out):
    location_name: str
    time_zone: str
    on_date: date
    refresh_sec: int
    generated_at: datetime
    games: list[BoardGameOut]


_POST_KIND = Literal["classified", "pickup"]
_POST_CATEGORY = Literal["player_wanted", "team_wanted", "coach_wanted", "other"]


class LeaguePostCreate(In):
    kind: _POST_KIND
    location_id: UUID
    category: _POST_CATEGORY = "other"
    sport_id: UUID | None = None
    title: Annotated[str, Field(min_length=3, max_length=120)]
    body: Annotated[str, Field(min_length=10, max_length=2000)]
    starts_at: AwareDatetime | None = None
    skill_level: Annotated[str, Field(max_length=60)] | None = None
    players_needed: Annotated[int, Field(ge=1, le=50)] | None = None


class PublicLeaguePostOut(Out):
    id: UUID
    kind: str
    category: str
    location_name: str
    sport_name: str | None
    title: str
    body: str
    starts_at: datetime | None
    skill_level: str | None
    players_needed: int | None
    posted_at: datetime
    expires_at: datetime


class PortalLeaguePostOut(PublicLeaguePostOut):
    status: str


class LeaguePostOut(PublicLeaguePostOut):
    location_id: UUID
    status: str
    client_name: str
    moderated_at: datetime | None
    reject_reason: str | None


class LeaguePostReject(In):
    reason: Annotated[str, Field(max_length=500)] | None = None


class LeaguePostContact(In):
    message: Annotated[str, Field(min_length=10, max_length=2000)]
