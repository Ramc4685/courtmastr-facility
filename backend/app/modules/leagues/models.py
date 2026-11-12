"""leagues tables (docs/architecture/data-model-programs.md section 2), P0 subset. Deviations from the data
model are listed in README.md: run inputs and official qualifications are arrays, bracket rounds are columns of
`bracket_slot`, `official` and `competition` gain the columns their P0 commands need."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Date, Index, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, TSTZRANGE, ExcludeConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JsonDict, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk


class Kind(StrEnum):
    LEAGUE = "league"
    TOURNAMENT = "tournament"


class Format(StrEnum):
    ROUND_ROBIN = "round_robin"
    POOL_PLAY = "pool_play"
    SINGLE_ELIMINATION = "single_elimination"
    DOUBLE_ELIMINATION = "double_elimination"
    THREE_GAMES_GUARANTEED = "three_games_guaranteed"
    LADDER = "ladder"


class CompetitionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class DivisionKind(StrEnum):
    DIVISION = "division"
    POOL = "pool"


class EntryStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class FeeStatus(StrEnum):
    NONE = "none"
    UNBILLED = "unbilled"
    BILLED = "billed"


class RosterRole(StrEnum):
    PLAYER = "player"
    CAPTAIN = "captain"
    COACH = "coach"
    MANAGER = "manager"


class RosterOrigin(StrEnum):
    ENROLLMENT = "enrollment"
    ROSTER_INVITE = "roster_invite"
    MANUAL = "manual"
    COPIED = "copied"


class RosterStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class OfficialRole(StrEnum):
    REFEREE = "referee"
    ASSISTANT = "assistant"
    SCOREKEEPER = "scorekeeper"
    OTHER = "other"


class RunKind(StrEnum):
    ROUND_ROBIN = "round_robin"
    POOL_PLAY = "pool_play"
    BRACKET = "bracket"


class RunState(StrEnum):
    DRAFT = "draft"
    GENERATING = "generating"
    PREVIEWED = "previewed"
    COMMITTING = "committing"
    COMMITTED = "committed"
    FAILED = "failed"
    DISCARDED = "discarded"


class ByeMode(StrEnum):
    HIDDEN = "hidden"
    OCCUPY_SLOT = "occupy_slot"
    FOLD_LAST_ROUND = "fold_last_round"
    ROTATE_EXTRA_GAME = "rotate_extra_game"


class GameStatus(StrEnum):
    PROPOSED = "proposed"
    SCHEDULED = "scheduled"
    PLAYED = "played"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    UNSCHEDULABLE = "unschedulable"
    BYE = "bye"


class GameType(StrEnum):
    REGULAR = "regular"
    POST_SEASON = "post_season"


class Side(StrEnum):
    HOME = "home"
    AWAY = "away"


class Participation(StrEnum):
    FULL = "full"
    DEFAULT = "default"
    FORFEIT = "forfeit"


class BracketType(StrEnum):
    SINGLE_ELIMINATION = "single_elimination"
    DOUBLE_ELIMINATION = "double_elimination"
    THREE_GAMES_GUARANTEED = "three_games_guaranteed"


class BracketStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    COMPLETED = "completed"


class BracketSide(StrEnum):
    WINNERS = "winners"
    LOSERS = "losers"
    FINAL = "final"
    CONSOLATION = "consolation"


def _points(default: str) -> Mapped[Decimal]:
    return mapped_column(Numeric(5, 2), server_default=text(default), info={"audit": "value"})


def _ids() -> Mapped[list[UUID]]:
    return mapped_column(ARRAY(PgUUID(as_uuid=True)), server_default=text("'{}'"))


DEFAULT_COLUMNS = [{"metric": m} for m in ("GP", "W", "L", "T", "GF", "GA", "PTS", "GD", "WP")]
DEFAULT_SORT = [{"metric": m, "direction": "desc"} for m in ("PTS", "WP", "GD", "GF")]


class _Scoring:
    """Points per outcome and standings layout: defaults on a sport, snapshotted into a competition."""

    points_win: Mapped[Decimal] = _points("2")
    points_tie: Mapped[Decimal] = _points("1")
    points_loss: Mapped[Decimal] = _points("0")
    points_overtime_loss: Mapped[Decimal] = _points("0")
    points_forfeit_win: Mapped[Decimal] = _points("2")
    points_forfeit_loss: Mapped[Decimal] = _points("0")
    points_default_loss: Mapped[Decimal] = _points("0")
    forfeit_score_for: Mapped[int] = mapped_column(server_default=text("0"))
    tracks_sportsmanship: Mapped[bool] = mapped_column(server_default=text("false"))
    standings_columns: Mapped[list] = mapped_column(JsonDict, server_default=text("'[]'"))
    standings_sort: Mapped[list] = mapped_column(JsonDict, server_default=text("'[]'"))


class Sport(_Scoring, TenantOwned, Timestamps, Base):
    __tablename__ = "sport"
    __table_args__ = tenant_args(
        Index("uq_sport_name", "tenant_id", text("lower(name)"), unique=True),
        CheckConstraint("default_game_length_min > 0", name="game_length"),
    )

    name: Mapped[str] = mapped_column(info={"audit": "value"})
    default_game_length_min: Mapped[int] = mapped_column(server_default=text("60"), info={"audit": "value"})
    default_team_fee_minor: Mapped[int | None] = mapped_column(info={"audit": "value"})
    fees_text: Mapped[str | None]
    rules_text: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class AgeGroup(TenantOwned, Timestamps, Base):
    __tablename__ = "age_group"
    __table_args__ = tenant_args(
        Index("uq_age_group_name", "tenant_id", text("lower(name)"), unique=True),
        CheckConstraint("min_age IS NULL OR max_age IS NULL OR max_age >= min_age", name="ages"),
    )

    name: Mapped[str] = mapped_column(info={"audit": "value"})
    min_age: Mapped[int | None] = mapped_column(info={"audit": "value"})
    max_age: Mapped[int | None] = mapped_column(info={"audit": "value"})
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Season(TenantOwned, Timestamps, Base):
    __tablename__ = "season"
    __table_args__ = tenant_args(
        Index("uq_season_name", "tenant_id", text("lower(name)"), unique=True),
        CheckConstraint("starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on", name="dates"),
    )

    name: Mapped[str] = mapped_column(info={"audit": "value"})
    starts_on: Mapped[date | None] = mapped_column(info={"audit": "value"})
    ends_on: Mapped[date | None] = mapped_column(info={"audit": "value"})
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Competition(_Scoring, TenantOwned, Timestamps, Base):
    """One league or tournament. `team_fee_minor` and `revenue_category_id` are our addition: the registration
    fee charged per team through billing (README, assumptions)."""

    __tablename__ = "competition"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("sport_id", "sport"),
        *tfk("age_group_id", "age_group"),
        *tfk("season_id", "season"),
        *tfk("revenue_category_id", "revenue_category"),
        *tfk("program_group_id", "program_group"),
        enum_check("kind", Kind),
        enum_check("format", Format),
        enum_check("status", CompetitionStatus),
        CheckConstraint("kind <> 'league' OR format IN ('round_robin', 'ladder')", name="league_format"),
        CheckConstraint("ladder_challenge_range IS NULL OR ladder_challenge_range > 0", name="ladder_range"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="dates"),
        CheckConstraint("game_length_min > 0", name="game_length"),
        CheckConstraint("team_fee_minor IS NULL OR team_fee_minor >= 0", name="team_fee"),
        Index("ix_competition_list", "tenant_id", "location_id", "kind", "status", "id"),
    )

    location_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    format: Mapped[str] = enum_column()
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    sport_id: Mapped[UUID]
    age_group_id: Mapped[UUID | None]
    season_id: Mapped[UUID | None]
    division_label: Mapped[str | None] = mapped_column(info={"audit": "value"})
    starts_on: Mapped[date] = mapped_column(info={"audit": "value"})
    ends_on: Mapped[date | None] = mapped_column(info={"audit": "value"})
    game_length_min: Mapped[int] = mapped_column(info={"audit": "value"})
    status: Mapped[str] = enum_column(server_default=text("'draft'"))
    is_public: Mapped[bool] = mapped_column(server_default=text("true"))
    shows_roster_publicly: Mapped[bool] = mapped_column(server_default=text("true"))
    max_defaults: Mapped[int | None] = mapped_column(info={"audit": "value"})
    max_forfeits: Mapped[int | None] = mapped_column(info={"audit": "value"})
    min_sportsmanship: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), info={"audit": "value"})
    team_fee_text: Mapped[str | None]
    more_info: Mapped[str | None]
    rules_text: Mapped[str | None]
    registration_url: Mapped[str | None]
    color: Mapped[str | None] = mapped_column(info={"audit": "value"})
    team_fee_minor: Mapped[int | None] = mapped_column(info={"audit": "value"})
    revenue_category_id: Mapped[UUID | None]
    program_group_id: Mapped[UUID | None]  # REG-14: the program group this competition was published from
    ladder_challenge_range: Mapped[int | None] = mapped_column(info={"audit": "value"})  # LGE-28, rungs up


class Division(TenantOwned, Timestamps, Base):
    __tablename__ = "division"
    __table_args__ = tenant_args(
        *tfk("competition_id", "competition", ondelete="CASCADE", index=False),
        enum_check("kind", DivisionKind),
        Index("uq_division_competition_name", "tenant_id", "competition_id", text("lower(name)"), unique=True),
    )

    competition_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    kind: Mapped[str] = enum_column(server_default=text("'division'"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class Team(TenantOwned, Timestamps, Base):
    __tablename__ = "team"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("captain_client_id", "client"),
        Index("ix_team_name", "tenant_id", "location_id", "name"),
    )

    location_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    captain_client_id: Mapped[UUID | None] = mapped_column(info={"audit": "flag"})
    color: Mapped[str | None] = mapped_column(info={"audit": "value"})
    is_placeholder: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class CompetitionTeam(TenantOwned, Timestamps, Base):
    """A team's entry in a competition. `fee_status` and `fee_client_id` are our addition (team registration
    fee, README)."""

    __tablename__ = "competition_team"
    __table_args__ = tenant_args(
        *tfk("competition_id", "competition", ondelete="CASCADE", index=False),
        *tfk("division_id", "division"),
        *tfk("team_id", "team"),
        *tfk("fee_client_id", "client"),
        enum_check("status", EntryStatus),
        enum_check("fee_status", FeeStatus),
        UniqueConstraint("tenant_id", "competition_id", "team_id", name="uq_competition_team_team"),
        UniqueConstraint(
            "tenant_id", "competition_id", "seed", name="uq_competition_team_seed", deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("seed IS NULL OR seed > 0", name="seed"),
        CheckConstraint("(fee_status = 'billed') = (fee_client_id IS NOT NULL)", name="fee"),
    )  # fmt: skip

    competition_id: Mapped[UUID]
    division_id: Mapped[UUID]
    team_id: Mapped[UUID]
    seed: Mapped[int | None] = mapped_column(info={"audit": "value"})
    display_name: Mapped[str | None] = mapped_column(info={"audit": "value"})
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    fee_status: Mapped[str] = enum_column(server_default=text("'none'"))
    fee_client_id: Mapped[UUID | None] = mapped_column(info={"audit": "flag"})


class RosterEntry(TenantOwned, Timestamps, Base):
    __tablename__ = "roster_entry"
    __table_args__ = tenant_args(
        *tfk("competition_team_id", "competition_team", ondelete="CASCADE"),
        *tfk("client_id", "client"),
        enum_check("role", RosterRole),
        enum_check("origin", RosterOrigin),
        enum_check("status", RosterStatus),
        CheckConstraint(
            "client_id IS NOT NULL OR (first_name IS NOT NULL AND last_name IS NOT NULL)", name="person"
        ),
        Index(
            "uq_roster_entry_team_client", "tenant_id", "competition_team_id", "client_id", unique=True,
            postgresql_where=text("client_id IS NOT NULL AND status = 'active'"),
        ),
    )  # fmt: skip

    competition_team_id: Mapped[UUID]
    client_id: Mapped[UUID | None] = mapped_column(info={"audit": "flag"})
    first_name: Mapped[str | None] = mapped_column(info={"audit": "flag"})
    last_name: Mapped[str | None] = mapped_column(info={"audit": "flag"})
    role: Mapped[str] = enum_column(server_default=text("'player'"))
    jersey_number: Mapped[str | None] = mapped_column(info={"audit": "value"})
    position: Mapped[str | None] = mapped_column(info={"audit": "value"})
    origin: Mapped[str] = enum_column(server_default=text("'manual'"))
    status: Mapped[str] = enum_column(server_default=text("'active'"))


class Official(TenantOwned, Timestamps, Base):
    """A referee or scorekeeper. `location_id` follows the API (the key is location-scoped); qualifications are
    id arrays validated on write (README)."""

    __tablename__ = "official"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("staff_user_id", "staff_user", index=False),
        Index(
            "uq_official_staff_user", "tenant_id", "staff_user_id", unique=True,
            postgresql_where=text("staff_user_id IS NOT NULL"),
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    first_name: Mapped[str] = mapped_column(info={"audit": "flag"})
    last_name: Mapped[str] = mapped_column(info={"audit": "flag"})
    email: Mapped[str | None] = mapped_column(info={"audit": "flag"})
    phone: Mapped[str | None] = mapped_column(info={"audit": "flag"})
    staff_user_id: Mapped[UUID | None]
    sport_ids: Mapped[list[UUID]] = _ids()
    age_group_ids: Mapped[list[UUID]] = _ids()
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ScheduleRun(TenantOwned, Timestamps, Base):
    """A persisted generator run. Competition, resource and weekly-slot inputs are columns, not child tables
    (README); every id in them went through a scoped loader on write."""

    __tablename__ = "schedule_run"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("created_by_staff_user_id", "staff_user"),
        enum_check("kind", RunKind),
        enum_check("state", RunState),
        enum_check("bye_mode", ByeMode),
        CheckConstraint("game_length_min > 0", name="game_length"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="dates"),
        Index(
            "ix_schedule_run_open", "tenant_id", "location_id", "state", "id",
            postgresql_where=text("state NOT IN ('committed', 'discarded')"),
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    kind: Mapped[str] = enum_column(server_default=text("'round_robin'"))
    state: Mapped[str] = enum_column(server_default=text("'draft'"))
    wizard_step: Mapped[int] = mapped_column(server_default=text("1"))
    competition_ids: Mapped[list[UUID]] = _ids()
    resource_ids: Mapped[list[UUID]] = _ids()
    time_slots: Mapped[list] = mapped_column(JsonDict, server_default=text("'[]'"))
    starts_on: Mapped[date] = mapped_column(info={"audit": "value"})
    ends_on: Mapped[date | None] = mapped_column(info={"audit": "value"})
    excluded_dates: Mapped[list[date]] = mapped_column(ARRAY(Date), server_default=text("'{}'"))
    game_length_min: Mapped[int] = mapped_column(info={"audit": "value"})
    rounds: Mapped[int | None] = mapped_column(info={"audit": "value"})
    bye_mode: Mapped[str] = enum_column(server_default=text("'hidden'"))
    removes_previous_games: Mapped[bool] = mapped_column(server_default=text("false"))
    result_stats: Mapped[dict | None] = mapped_column(JsonDict)
    progress: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))  # LGE-08 job cursor
    created_by_staff_user_id: Mapped[UUID | None]
    committed_at: Mapped[datetime | None]


class Game(TenantOwned, Timestamps, Base):
    __tablename__ = "game"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("competition_id", "competition", index=False),
        *tfk("division_id", "division"),
        *tfk("schedule_run_id", "schedule_run"),
        *tfk("home_team_id", "competition_team", index=False),
        *tfk("away_team_id", "competition_team", index=False),
        *tfk("booking_id", "booking", index=False),
        *tfk("resource_id", "resource", index=False),
        *tfk("venue_id", "venue"),
        enum_check("status", GameStatus),
        enum_check("game_type", GameType),
        CheckConstraint(
            "status <> 'scheduled' OR (booking_id IS NOT NULL AND starts_at IS NOT NULL AND resource_id IS NOT NULL)",
            name="scheduled",
        ),
        CheckConstraint("home_team_id IS DISTINCT FROM away_team_id OR home_team_id IS NULL", name="sides"),
        CheckConstraint("is_bye = (status = 'bye')", name="bye"),
        CheckConstraint("length_min > 0", name="length"),
        Index("uq_game_booking", "tenant_id", "booking_id", unique=True, postgresql_where=text("booking_id IS NOT NULL")),
        Index("ix_game_competition_time", "tenant_id", "competition_id", "starts_at", "id"),
        Index("ix_game_resource_time", "tenant_id", "resource_id", "starts_at"),
        Index("ix_game_home_team", "tenant_id", "home_team_id", "starts_at"),
        Index("ix_game_away_team", "tenant_id", "away_team_id", "starts_at"),
        Index(
            "ix_game_day", "tenant_id", "location_id", "starts_at",
            postgresql_where=text("status IN ('scheduled', 'played', 'postponed')"),
        ),
    )  # fmt: skip

    location_id: Mapped[UUID]
    competition_id: Mapped[UUID]
    division_id: Mapped[UUID | None]
    schedule_run_id: Mapped[UUID | None]
    home_team_id: Mapped[UUID | None] = mapped_column(info={"audit": "value"})
    away_team_id: Mapped[UUID | None] = mapped_column(info={"audit": "value"})
    home_label: Mapped[str | None] = mapped_column(info={"audit": "value"})
    away_label: Mapped[str | None] = mapped_column(info={"audit": "value"})
    booking_id: Mapped[UUID | None]
    resource_id: Mapped[UUID | None] = mapped_column(info={"audit": "value"})
    venue_id: Mapped[UUID | None] = mapped_column(info={"audit": "value"})
    starts_at: Mapped[datetime | None] = mapped_column(info={"audit": "value"})
    ends_at: Mapped[datetime | None] = mapped_column(info={"audit": "value"})
    length_min: Mapped[int] = mapped_column(info={"audit": "value"})
    status: Mapped[str] = enum_column()
    game_type: Mapped[str] = enum_column(server_default=text("'regular'"))
    round_no: Mapped[int | None]
    round_label: Mapped[str | None] = mapped_column(info={"audit": "value"})
    is_bye: Mapped[bool] = mapped_column(server_default=text("false"))
    conflict_note: Mapped[dict | None] = mapped_column(JsonDict)
    notes: Mapped[str | None]
    version: Mapped[int] = mapped_column(server_default=text("1"))
    ladder_swapped: Mapped[bool] = mapped_column(server_default=text("false"))  # LGE-28: the result swapped rungs


class GameOfficial(TenantOwned, Timestamps, Base):
    __tablename__ = "game_official"
    __table_args__ = tenant_args(
        *tfk("game_id", "game", ondelete="CASCADE", index=False),
        *tfk("official_id", "official"),
        enum_check("role", OfficialRole),
        UniqueConstraint("tenant_id", "game_id", "official_id", name="uq_game_official_game_official"),
        ExcludeConstraint(
            ("tenant_id", "="), ("official_id", "="), ("during", "&&"), name="ex_game_official_overlap", using="gist"
        ),
        CheckConstraint("NOT isempty(during)", name="during"),
    )

    game_id: Mapped[UUID]
    official_id: Mapped[UUID]
    role: Mapped[str] = enum_column(server_default=text("'referee'"))
    during: Mapped[Any] = mapped_column(TSTZRANGE)


class GameResult(TenantOwned, Timestamps, Base):
    __tablename__ = "game_result"
    __table_args__ = tenant_args(
        *tfk("game_id", "game", ondelete="CASCADE", index=False),
        *tfk("competition_team_id", "competition_team"),
        *tfk("recorded_by_staff_user_id", "staff_user"),
        enum_check("side", Side),
        enum_check("participation", Participation),
        UniqueConstraint("tenant_id", "game_id", "side", name="uq_game_result_game_side"),
        UniqueConstraint("tenant_id", "game_id", "competition_team_id", name="uq_game_result_game_team"),
        CheckConstraint("score IS NULL OR score >= 0", name="score"),
    )

    game_id: Mapped[UUID]
    competition_team_id: Mapped[UUID]
    side: Mapped[str] = enum_column()
    score: Mapped[int | None] = mapped_column(info={"audit": "value"})
    went_to_overtime: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    participation: Mapped[str] = enum_column(server_default=text("'full'"))
    sportsmanship: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), info={"audit": "value"})
    bonus_points: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"), info={"audit": "value"})
    recorded_by_staff_user_id: Mapped[UUID | None]
    recorded_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Standing(TenantOwned, Timestamps, Base):
    """Derived: rebuilt for a whole competition whenever a result changes. `adjustment_points` and
    `adjustment_reason` are the manual part (LGE-06) and survive rebuilds."""

    __tablename__ = "standing"
    __table_args__ = tenant_args(
        *tfk("competition_id", "competition", ondelete="CASCADE"),
        *tfk("division_id", "division", index=False),
        *tfk("competition_team_id", "competition_team", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "competition_team_id", name="uq_standing_competition_team"),
        Index("ix_standing_division_rank", "tenant_id", "division_id", "rank"),
    )

    competition_id: Mapped[UUID]
    division_id: Mapped[UUID]
    competition_team_id: Mapped[UUID]
    games_played: Mapped[int] = mapped_column(server_default=text("0"))
    wins: Mapped[int] = mapped_column(server_default=text("0"))
    losses: Mapped[int] = mapped_column(server_default=text("0"))
    ties: Mapped[int] = mapped_column(server_default=text("0"))
    overtime_losses: Mapped[int] = mapped_column(server_default=text("0"))
    forfeits: Mapped[int] = mapped_column(server_default=text("0"))
    defaults: Mapped[int] = mapped_column(server_default=text("0"))
    goals_for: Mapped[int] = mapped_column(server_default=text("0"))
    goals_against: Mapped[int] = mapped_column(server_default=text("0"))
    bonus_points: Mapped[Decimal] = mapped_column(Numeric(7, 2), server_default=text("0"))
    adjustment_points: Mapped[Decimal] = mapped_column(Numeric(7, 2), server_default=text("0"), info={"audit": "value"})
    adjustment_reason: Mapped[str | None]
    points: Mapped[Decimal] = mapped_column(Numeric(8, 2), server_default=text("0"))
    sportsmanship_avg: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    rank: Mapped[int] = mapped_column(server_default=text("0"))
    is_over_discipline_cap: Mapped[bool] = mapped_column(server_default=text("false"))
    computed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Bracket(TenantOwned, Timestamps, Base):
    __tablename__ = "bracket"
    __table_args__ = tenant_args(
        *tfk("competition_id", "competition", ondelete="CASCADE"),
        *tfk("division_id", "division"),
        enum_check("bracket_type", BracketType),
        enum_check("status", BracketStatus),
        CheckConstraint(
            "size IN (2, 4, 8, 16, 32, 64, 128) AND (bracket_type <> 'three_games_guaranteed' OR size = 8)",
            name="size",
        ),
    )

    competition_id: Mapped[UUID]
    division_id: Mapped[UUID | None]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    bracket_type: Mapped[str] = enum_column()
    size: Mapped[int] = mapped_column(info={"audit": "value"})
    has_third_place_game: Mapped[bool] = mapped_column(server_default=text("false"))
    has_reset_game: Mapped[bool] = mapped_column(server_default=text("false"))  # double elimination
    status: Mapped[str] = enum_column(server_default=text("'draft'"))


class BracketSlot(TenantOwned, Timestamps, Base):
    """One match node. `side`, `round_no` and `round_name` stand in for the data model's `bracket_round`."""

    __tablename__ = "bracket_slot"
    __table_args__ = tenant_args(
        *tfk("bracket_id", "bracket", ondelete="CASCADE", index=False),
        *tfk("game_id", "game", index=False),
        *tfk("home_source_slot_id", "bracket_slot"),
        *tfk("away_source_slot_id", "bracket_slot"),
        *tfk("home_team_id", "competition_team"),
        *tfk("away_team_id", "competition_team"),
        *tfk("winner_competition_team_id", "competition_team"),
        enum_check("side", BracketSide),
        UniqueConstraint("tenant_id", "bracket_id", "side", "round_no", "position", name="uq_bracket_slot_position"),
        Index("uq_bracket_slot_game", "tenant_id", "game_id", unique=True, postgresql_where=text("game_id IS NOT NULL")),
        CheckConstraint(
            "home_source_outcome IS NULL OR home_source_outcome IN ('winner', 'loser')", name="home_source_outcome"
        ),
        CheckConstraint(
            "away_source_outcome IS NULL OR away_source_outcome IN ('winner', 'loser')", name="away_source_outcome"
        ),
    )  # fmt: skip

    bracket_id: Mapped[UUID]
    side: Mapped[str] = enum_column(server_default=text("'winners'"))
    round_no: Mapped[int]
    round_name: Mapped[str] = mapped_column(info={"audit": "value"})
    position: Mapped[int]
    game_id: Mapped[UUID | None]
    home_seed: Mapped[int | None]
    away_seed: Mapped[int | None]
    home_team_id: Mapped[UUID | None] = mapped_column(info={"audit": "value"})
    away_team_id: Mapped[UUID | None] = mapped_column(info={"audit": "value"})
    home_source_slot_id: Mapped[UUID | None]
    home_source_outcome: Mapped[str | None]
    away_source_slot_id: Mapped[UUID | None]
    away_source_outcome: Mapped[str | None]
    is_bye: Mapped[bool] = mapped_column(server_default=text("false"))
    winner_competition_team_id: Mapped[UUID | None]


# --- Phase 14 B1: league depth -----------------------------------------------------------------------------------


class Venue(TenantOwned, Timestamps, Base):
    """RES-06: a league venue mapped to one or more facility resources; a game at a venue books all of them."""

    __tablename__ = "venue"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        Index("uq_venue_name", "tenant_id", "location_id", text("lower(name)"), unique=True),
        CheckConstraint("cardinality(resource_ids) > 0", name="resources"),
    )

    location_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    description: Mapped[str | None]
    resource_ids: Mapped[list[UUID]] = _ids()
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class PreferenceKind(StrEnum):
    DATE = "date"
    WEEKDAY = "weekday"
    TIME = "time"
    RESOURCE = "resource"


class TeamPreference(TenantOwned, Timestamps, Base):
    """LGE-10: a soft scheduling wish of one team entry. `wants` false marks a date, weekday, time range or
    court the team cannot use; true one it prefers. `value` is an ISO date, an ISO weekday 1-7, 'HH:MM-HH:MM'
    or a resource id, validated on write."""

    __tablename__ = "team_preference"
    __table_args__ = tenant_args(
        *tfk("competition_team_id", "competition_team", ondelete="CASCADE"),
        enum_check("kind", PreferenceKind),
    )

    competition_team_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    value: Mapped[str] = mapped_column(info={"audit": "value"})
    wants: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    is_priority: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})


class StatTable(TenantOwned, Timestamps, Base):
    """LGE-07: a named group of player stats for a sport (tenant-wide, like sports)."""

    __tablename__ = "stat_table"
    __table_args__ = tenant_args(
        *tfk("sport_id", "sport", ondelete="CASCADE"),
        Index("uq_stat_table_name", "tenant_id", "sport_id", text("lower(name)"), unique=True),
    )

    sport_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class StatKind(StrEnum):
    ENTRY = "entry"
    FORMULA = "formula"


class StatDefinition(TenantOwned, Timestamps, Base):
    """One stat. `code` names it in formulas (unique per sport); a formula stat is computed, never entered."""

    __tablename__ = "stat_definition"
    __table_args__ = tenant_args(
        *tfk("stat_table_id", "stat_table", ondelete="CASCADE"),
        *tfk("sport_id", "sport", index=False),
        enum_check("kind", StatKind),
        UniqueConstraint("tenant_id", "sport_id", "code", name="uq_stat_definition_code"),
        CheckConstraint("(kind = 'formula') = (formula IS NOT NULL)", name="formula"),
        CheckConstraint("decimal_places BETWEEN 0 AND 4", name="decimal_places"),
    )

    stat_table_id: Mapped[UUID]
    sport_id: Mapped[UUID]
    code: Mapped[str] = mapped_column(info={"audit": "value"})
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    kind: Mapped[str] = enum_column(server_default=text("'entry'"))
    formula: Mapped[str | None] = mapped_column(info={"audit": "value"})
    decimal_places: Mapped[int] = mapped_column(server_default=text("0"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class PlayerStat(TenantOwned, Timestamps, Base):
    """One entered stat value for one roster place in one game."""

    __tablename__ = "player_stat"
    __table_args__ = tenant_args(
        *tfk("game_id", "game", ondelete="CASCADE", index=False),
        *tfk("roster_entry_id", "roster_entry", ondelete="CASCADE"),
        *tfk("stat_definition_id", "stat_definition", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "game_id", "roster_entry_id", "stat_definition_id", name="uq_player_stat"),
    )

    game_id: Mapped[UUID]
    roster_entry_id: Mapped[UUID]
    stat_definition_id: Mapped[UUID]
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2), info={"audit": "value"})


class StaffRole(StrEnum):
    LEAGUE_ADMIN = "league_admin"
    SCOREKEEPER = "scorekeeper"


class CompetitionStaff(TenantOwned, Timestamps, Base):
    """LGE-26, PLT-11: a staff user assigned to one competition. A scorekeeper-only caller (result key without
    the game key) reaches only the competitions they are assigned to."""

    __tablename__ = "competition_staff"
    __table_args__ = tenant_args(
        *tfk("competition_id", "competition", ondelete="CASCADE", index=False),
        *tfk("staff_user_id", "staff_user"),
        enum_check("role", StaffRole),
        UniqueConstraint("tenant_id", "competition_id", "staff_user_id", name="uq_competition_staff_user"),
    )

    competition_id: Mapped[UUID]
    staff_user_id: Mapped[UUID]
    role: Mapped[str] = enum_column(server_default=text("'scorekeeper'"))


class LadderPosition(TenantOwned, Timestamps, Base):
    """LGE-28: one rung of a ladder competition; 1 is the top. Swapped when a challenger wins."""

    __tablename__ = "ladder_position"
    __table_args__ = tenant_args(
        *tfk("competition_id", "competition", ondelete="CASCADE", index=False),
        *tfk("competition_team_id", "competition_team", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "competition_team_id", name="uq_ladder_position_team"),
        UniqueConstraint(
            "tenant_id", "competition_id", "position", name="uq_ladder_position_rung", deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("position > 0", name="position"),
    )  # fmt: skip

    competition_id: Mapped[UUID]
    competition_team_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(info={"audit": "value"})


class TeamFeeShare(TenantOwned, Timestamps, Base):
    """REG-26: a part of a team fee assigned to one rostered player and charged to them through billing."""

    __tablename__ = "team_fee_share"
    __table_args__ = tenant_args(
        *tfk("competition_team_id", "competition_team", ondelete="CASCADE", index=False),
        *tfk("roster_entry_id", "roster_entry"),
        *tfk("client_id", "client"),
        *tfk("charge_id", "charge"),
        UniqueConstraint("tenant_id", "competition_team_id", "client_id", name="uq_team_fee_share_client"),
        CheckConstraint("amount_minor > 0", name="amount"),
    )

    competition_team_id: Mapped[UUID]
    roster_entry_id: Mapped[UUID | None]
    client_id: Mapped[UUID] = mapped_column(info={"audit": "flag"})
    amount_minor: Mapped[int] = mapped_column(BigInteger, info={"audit": "value"})
    charge_id: Mapped[UUID | None]
