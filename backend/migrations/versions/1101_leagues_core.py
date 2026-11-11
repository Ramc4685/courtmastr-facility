"""build module 11: leagues. Sports, age groups, seasons, competitions (leagues and tournaments) and divisions,
teams and their competition entries with the team fee state, rosters, officials, schedule runs, games (each
holding its court through a scheduling booking), per-side results, standings, single-elimination brackets.
Deviations from data-model-programs section 2 (README): schedule-run inputs are arrays and JSON on the run,
official qualifications are uuid arrays, bracket rounds fold into bracket_slot.

Generated from the models, then completed by hand: enable_rls() per table.

Revision ID: 1101
Revises: 0401
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1101"
down_revision = "0401"

TENANT_TABLES = (
    "age_group",
    "season",
    "sport",
    "competition",
    "division",
    "bracket",
    "official",
    "schedule_run",
    "team",
    "competition_team",
    "game",
    "roster_entry",
    "standing",
    "bracket_slot",
    "game_official",
    "game_result",
)


def upgrade() -> None:
    op.create_table(
        "age_group",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("min_age", sa.Integer(), nullable=True),
        sa.Column("max_age", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("min_age IS NULL OR max_age IS NULL OR max_age >= min_age", name=op.f("ck_age_group_ages")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_age_group_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_age_group")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_age_group_tenant_id_id")),
    )
    op.create_index("uq_age_group_name", "age_group", ["tenant_id", sa.literal_column("lower(name)")], unique=True)
    op.create_table(
        "season",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on", name=op.f("ck_season_dates")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_season_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_season")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_season_tenant_id_id")),
    )
    op.create_index("uq_season_name", "season", ["tenant_id", sa.literal_column("lower(name)")], unique=True)
    op.create_table(
        "sport",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("default_game_length_min", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("default_team_fee_minor", sa.Integer(), nullable=True),
        sa.Column("fees_text", sa.Text(), nullable=True),
        sa.Column("rules_text", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("points_win", sa.Numeric(precision=5, scale=2), server_default=sa.text("2"), nullable=False),
        sa.Column("points_tie", sa.Numeric(precision=5, scale=2), server_default=sa.text("1"), nullable=False),
        sa.Column("points_loss", sa.Numeric(precision=5, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "points_overtime_loss", sa.Numeric(precision=5, scale=2), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("points_forfeit_win", sa.Numeric(precision=5, scale=2), server_default=sa.text("2"), nullable=False),
        sa.Column("points_forfeit_loss", sa.Numeric(precision=5, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("points_default_loss", sa.Numeric(precision=5, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("forfeit_score_for", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tracks_sportsmanship", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "standings_columns",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "standings_sort",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("default_game_length_min > 0", name=op.f("ck_sport_game_length")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_sport_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sport")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_sport_tenant_id_id")),
    )
    op.create_index("uq_sport_name", "sport", ["tenant_id", sa.literal_column("lower(name)")], unique=True)
    op.create_table(
        "competition",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sport_id", sa.Uuid(), nullable=False),
        sa.Column("age_group_id", sa.Uuid(), nullable=True),
        sa.Column("season_id", sa.Uuid(), nullable=True),
        sa.Column("division_label", sa.Text(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("game_length_min", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("shows_roster_publicly", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("max_defaults", sa.Integer(), nullable=True),
        sa.Column("max_forfeits", sa.Integer(), nullable=True),
        sa.Column("min_sportsmanship", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("team_fee_text", sa.Text(), nullable=True),
        sa.Column("more_info", sa.Text(), nullable=True),
        sa.Column("rules_text", sa.Text(), nullable=True),
        sa.Column("registration_url", sa.Text(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("team_fee_minor", sa.Integer(), nullable=True),
        sa.Column("revenue_category_id", sa.Uuid(), nullable=True),
        sa.Column("points_win", sa.Numeric(precision=5, scale=2), server_default=sa.text("2"), nullable=False),
        sa.Column("points_tie", sa.Numeric(precision=5, scale=2), server_default=sa.text("1"), nullable=False),
        sa.Column("points_loss", sa.Numeric(precision=5, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "points_overtime_loss", sa.Numeric(precision=5, scale=2), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("points_forfeit_win", sa.Numeric(precision=5, scale=2), server_default=sa.text("2"), nullable=False),
        sa.Column("points_forfeit_loss", sa.Numeric(precision=5, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("points_default_loss", sa.Numeric(precision=5, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("forfeit_score_for", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tracks_sportsmanship", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "standings_columns",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "standings_sort",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "format IN ('round_robin', 'pool_play', 'single_elimination', 'double_elimination', 'three_games_guaranteed')",
            name=op.f("ck_competition_format"),
        ),
        sa.CheckConstraint("kind <> 'league' OR format = 'round_robin'", name=op.f("ck_competition_league_format")),
        sa.CheckConstraint("kind IN ('league', 'tournament')", name=op.f("ck_competition_kind")),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'archived')", name=op.f("ck_competition_status")
        ),
        sa.CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name=op.f("ck_competition_dates")),
        sa.CheckConstraint("game_length_min > 0", name=op.f("ck_competition_game_length")),
        sa.CheckConstraint("team_fee_minor IS NULL OR team_fee_minor >= 0", name=op.f("ck_competition_team_fee")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "age_group_id"],
            ["age_group.tenant_id", "age_group.id"],
            name=op.f("fk_competition_age_group_id_age_group"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_competition_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revenue_category_id"],
            ["revenue_category.tenant_id", "revenue_category.id"],
            name=op.f("fk_competition_revenue_category_id_revenue_category"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "season_id"],
            ["season.tenant_id", "season.id"],
            name=op.f("fk_competition_season_id_season"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sport_id"],
            ["sport.tenant_id", "sport.id"],
            name=op.f("fk_competition_sport_id_sport"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_competition_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_competition")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_competition_tenant_id_id")),
    )
    op.create_index(op.f("ix_competition_age_group_id"), "competition", ["tenant_id", "age_group_id"], unique=False)
    op.create_index(
        "ix_competition_list", "competition", ["tenant_id", "location_id", "kind", "status", "id"], unique=False
    )
    op.create_index(
        op.f("ix_competition_revenue_category_id"), "competition", ["tenant_id", "revenue_category_id"], unique=False
    )
    op.create_index(op.f("ix_competition_season_id"), "competition", ["tenant_id", "season_id"], unique=False)
    op.create_index(op.f("ix_competition_sport_id"), "competition", ["tenant_id", "sport_id"], unique=False)
    op.create_table(
        "division",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("competition_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("'division'"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('division', 'pool')", name=op.f("ck_division_kind")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "competition_id"],
            ["competition.tenant_id", "competition.id"],
            name=op.f("fk_division_competition_id_competition"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_division_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_division")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_division_tenant_id_id")),
    )
    op.create_index(
        "uq_division_competition_name",
        "division",
        ["tenant_id", "competition_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "bracket",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("competition_id", sa.Uuid(), nullable=False),
        sa.Column("division_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("bracket_type", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("has_third_place_game", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "bracket_type IN ('single_elimination', 'double_elimination', 'three_games_guaranteed')",
            name=op.f("ck_bracket_bracket_type"),
        ),
        sa.CheckConstraint(
            "size IN (2, 4, 8, 16, 32, 64, 128) AND (bracket_type <> 'three_games_guaranteed' OR size = 8)",
            name=op.f("ck_bracket_size"),
        ),
        sa.CheckConstraint("status IN ('draft', 'published', 'completed')", name=op.f("ck_bracket_status")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "competition_id"],
            ["competition.tenant_id", "competition.id"],
            name=op.f("fk_bracket_competition_id_competition"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "division_id"],
            ["division.tenant_id", "division.id"],
            name=op.f("fk_bracket_division_id_division"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_bracket_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bracket")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_bracket_tenant_id_id")),
    )
    op.create_index(op.f("ix_bracket_competition_id"), "bracket", ["tenant_id", "competition_id"], unique=False)
    op.create_index(op.f("ix_bracket_division_id"), "bracket", ["tenant_id", "division_id"], unique=False)
    op.create_table(
        "official",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("sport_ids", postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("age_group_ids", postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_official_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_official_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_official_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_official")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_official_tenant_id_id")),
    )
    op.create_index(op.f("ix_official_location_id"), "official", ["tenant_id", "location_id"], unique=False)
    op.create_index(
        "uq_official_staff_user",
        "official",
        ["tenant_id", "staff_user_id"],
        unique=True,
        postgresql_where=sa.text("staff_user_id IS NOT NULL"),
    )
    op.create_table(
        "schedule_run",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), server_default=sa.text("'round_robin'"), nullable=False),
        sa.Column("state", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("wizard_step", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("competition_ids", postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("resource_ids", postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "time_slots",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("excluded_dates", postgresql.ARRAY(sa.Date()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("game_length_min", sa.Integer(), nullable=False),
        sa.Column("rounds", sa.Integer(), nullable=True),
        sa.Column("bye_mode", sa.Text(), server_default=sa.text("'hidden'"), nullable=False),
        sa.Column("removes_previous_games", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("result_stats", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "bye_mode IN ('hidden', 'occupy_slot', 'fold_last_round', 'rotate_extra_game')",
            name=op.f("ck_schedule_run_bye_mode"),
        ),
        sa.CheckConstraint("kind IN ('round_robin', 'pool_play', 'bracket')", name=op.f("ck_schedule_run_kind")),
        sa.CheckConstraint(
            "state IN ('draft', 'generating', 'previewed', 'committing', 'committed', 'failed', 'discarded')",
            name=op.f("ck_schedule_run_state"),
        ),
        sa.CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name=op.f("ck_schedule_run_dates")),
        sa.CheckConstraint("game_length_min > 0", name=op.f("ck_schedule_run_game_length")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_schedule_run_created_by_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_schedule_run_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_schedule_run_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_run")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_schedule_run_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_schedule_run_created_by_staff_user_id"),
        "schedule_run",
        ["tenant_id", "created_by_staff_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_schedule_run_open",
        "schedule_run",
        ["tenant_id", "location_id", "state", "id"],
        unique=False,
        postgresql_where=sa.text("state NOT IN ('committed', 'discarded')"),
    )
    op.create_table(
        "team",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("captain_client_id", sa.Uuid(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("is_placeholder", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "captain_client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f("fk_team_captain_client_id_client"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_team_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_team_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_team_tenant_id_id")),
    )
    op.create_index(op.f("ix_team_captain_client_id"), "team", ["tenant_id", "captain_client_id"], unique=False)
    op.create_index("ix_team_name", "team", ["tenant_id", "location_id", "name"], unique=False)
    op.create_table(
        "competition_team",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("competition_id", sa.Uuid(), nullable=False),
        sa.Column("division_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("fee_status", sa.Text(), server_default=sa.text("'none'"), nullable=False),
        sa.Column("fee_client_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(fee_status = 'billed') = (fee_client_id IS NOT NULL)", name=op.f("ck_competition_team_fee")
        ),
        sa.CheckConstraint("fee_status IN ('none', 'unbilled', 'billed')", name=op.f("ck_competition_team_fee_status")),
        sa.CheckConstraint("status IN ('active', 'withdrawn')", name=op.f("ck_competition_team_status")),
        sa.CheckConstraint("seed IS NULL OR seed > 0", name=op.f("ck_competition_team_seed")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "competition_id"],
            ["competition.tenant_id", "competition.id"],
            name=op.f("fk_competition_team_competition_id_competition"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "division_id"],
            ["division.tenant_id", "division.id"],
            name=op.f("fk_competition_team_division_id_division"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fee_client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f("fk_competition_team_fee_client_id_client"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "team_id"],
            ["team.tenant_id", "team.id"],
            name=op.f("fk_competition_team_team_id_team"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_competition_team_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_competition_team")),
        sa.UniqueConstraint(
            "tenant_id",
            "competition_id",
            "seed",
            deferrable=True,
            initially="DEFERRED",
            name="uq_competition_team_seed",
        ),
        sa.UniqueConstraint("tenant_id", "competition_id", "team_id", name="uq_competition_team_team"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_competition_team_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_competition_team_division_id"), "competition_team", ["tenant_id", "division_id"], unique=False
    )
    op.create_index(
        op.f("ix_competition_team_fee_client_id"), "competition_team", ["tenant_id", "fee_client_id"], unique=False
    )
    op.create_index(op.f("ix_competition_team_team_id"), "competition_team", ["tenant_id", "team_id"], unique=False)
    op.create_table(
        "game",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("competition_id", sa.Uuid(), nullable=False),
        sa.Column("division_id", sa.Uuid(), nullable=True),
        sa.Column("schedule_run_id", sa.Uuid(), nullable=True),
        sa.Column("home_team_id", sa.Uuid(), nullable=True),
        sa.Column("away_team_id", sa.Uuid(), nullable=True),
        sa.Column("home_label", sa.Text(), nullable=True),
        sa.Column("away_label", sa.Text(), nullable=True),
        sa.Column("booking_id", sa.Uuid(), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("length_min", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("game_type", sa.Text(), server_default=sa.text("'regular'"), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=True),
        sa.Column("round_label", sa.Text(), nullable=True),
        sa.Column("is_bye", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("conflict_note", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("game_type IN ('regular', 'post_season')", name=op.f("ck_game_game_type")),
        sa.CheckConstraint("is_bye = (status = 'bye')", name=op.f("ck_game_bye")),
        sa.CheckConstraint(
            "status <> 'scheduled' OR (booking_id IS NOT NULL AND starts_at IS NOT NULL AND resource_id IS NOT NULL)",
            name=op.f("ck_game_scheduled"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'scheduled', 'played', 'postponed', 'cancelled', 'unschedulable', 'bye')",
            name=op.f("ck_game_status"),
        ),
        sa.CheckConstraint(
            "home_team_id IS DISTINCT FROM away_team_id OR home_team_id IS NULL", name=op.f("ck_game_sides")
        ),
        sa.CheckConstraint("length_min > 0", name=op.f("ck_game_length")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "away_team_id"],
            ["competition_team.tenant_id", "competition_team.id"],
            name=op.f("fk_game_away_team_id_competition_team"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "booking_id"],
            ["booking.tenant_id", "booking.id"],
            name=op.f("fk_game_booking_id_booking"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "competition_id"],
            ["competition.tenant_id", "competition.id"],
            name=op.f("fk_game_competition_id_competition"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "division_id"],
            ["division.tenant_id", "division.id"],
            name=op.f("fk_game_division_id_division"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "home_team_id"],
            ["competition_team.tenant_id", "competition_team.id"],
            name=op.f("fk_game_home_team_id_competition_team"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_game_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name=op.f("fk_game_resource_id_resource"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "schedule_run_id"],
            ["schedule_run.tenant_id", "schedule_run.id"],
            name=op.f("fk_game_schedule_run_id_schedule_run"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_game_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_game")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_game_tenant_id_id")),
    )
    op.create_index("ix_game_away_team", "game", ["tenant_id", "away_team_id", "starts_at"], unique=False)
    op.create_index(
        "ix_game_competition_time", "game", ["tenant_id", "competition_id", "starts_at", "id"], unique=False
    )
    op.create_index(
        "ix_game_day",
        "game",
        ["tenant_id", "location_id", "starts_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('scheduled', 'played', 'postponed')"),
    )
    op.create_index(op.f("ix_game_division_id"), "game", ["tenant_id", "division_id"], unique=False)
    op.create_index("ix_game_home_team", "game", ["tenant_id", "home_team_id", "starts_at"], unique=False)
    op.create_index("ix_game_resource_time", "game", ["tenant_id", "resource_id", "starts_at"], unique=False)
    op.create_index(op.f("ix_game_schedule_run_id"), "game", ["tenant_id", "schedule_run_id"], unique=False)
    op.create_index(
        "uq_game_booking",
        "game",
        ["tenant_id", "booking_id"],
        unique=True,
        postgresql_where=sa.text("booking_id IS NOT NULL"),
    )
    op.create_table(
        "roster_entry",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("competition_team_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), server_default=sa.text("'player'"), nullable=False),
        sa.Column("jersey_number", sa.Text(), nullable=True),
        sa.Column("position", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "origin IN ('enrollment', 'roster_invite', 'manual', 'copied')", name=op.f("ck_roster_entry_origin")
        ),
        sa.CheckConstraint("role IN ('player', 'captain', 'coach', 'manager')", name=op.f("ck_roster_entry_role")),
        sa.CheckConstraint("status IN ('active', 'removed')", name=op.f("ck_roster_entry_status")),
        sa.CheckConstraint(
            "client_id IS NOT NULL OR (first_name IS NOT NULL AND last_name IS NOT NULL)",
            name=op.f("ck_roster_entry_person"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f("fk_roster_entry_client_id_client"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "competition_team_id"],
            ["competition_team.tenant_id", "competition_team.id"],
            name=op.f("fk_roster_entry_competition_team_id_competition_team"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_roster_entry_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roster_entry")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_roster_entry_tenant_id_id")),
    )
    op.create_index(op.f("ix_roster_entry_client_id"), "roster_entry", ["tenant_id", "client_id"], unique=False)
    op.create_index(
        op.f("ix_roster_entry_competition_team_id"), "roster_entry", ["tenant_id", "competition_team_id"], unique=False
    )
    op.create_index(
        "uq_roster_entry_team_client",
        "roster_entry",
        ["tenant_id", "competition_team_id", "client_id"],
        unique=True,
        postgresql_where=sa.text("client_id IS NOT NULL AND status = 'active'"),
    )
    op.create_table(
        "standing",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("competition_id", sa.Uuid(), nullable=False),
        sa.Column("division_id", sa.Uuid(), nullable=False),
        sa.Column("competition_team_id", sa.Uuid(), nullable=False),
        sa.Column("games_played", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("wins", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("losses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ties", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("overtime_losses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("forfeits", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("defaults", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("goals_for", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("goals_against", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("bonus_points", sa.Numeric(precision=7, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("adjustment_points", sa.Numeric(precision=7, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("adjustment_reason", sa.Text(), nullable=True),
        sa.Column("points", sa.Numeric(precision=8, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("sportsmanship_avg", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("rank", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_over_discipline_cap", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "competition_id"],
            ["competition.tenant_id", "competition.id"],
            name=op.f("fk_standing_competition_id_competition"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "competition_team_id"],
            ["competition_team.tenant_id", "competition_team.id"],
            name=op.f("fk_standing_competition_team_id_competition_team"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "division_id"],
            ["division.tenant_id", "division.id"],
            name=op.f("fk_standing_division_id_division"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_standing_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standing")),
        sa.UniqueConstraint("tenant_id", "competition_team_id", name="uq_standing_competition_team"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_standing_tenant_id_id")),
    )
    op.create_index(op.f("ix_standing_competition_id"), "standing", ["tenant_id", "competition_id"], unique=False)
    op.create_index("ix_standing_division_rank", "standing", ["tenant_id", "division_id", "rank"], unique=False)
    op.create_table(
        "bracket_slot",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("bracket_id", sa.Uuid(), nullable=False),
        sa.Column("side", sa.Text(), server_default=sa.text("'winners'"), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("round_name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=True),
        sa.Column("home_seed", sa.Integer(), nullable=True),
        sa.Column("away_seed", sa.Integer(), nullable=True),
        sa.Column("home_team_id", sa.Uuid(), nullable=True),
        sa.Column("away_team_id", sa.Uuid(), nullable=True),
        sa.Column("home_source_slot_id", sa.Uuid(), nullable=True),
        sa.Column("home_source_outcome", sa.Text(), nullable=True),
        sa.Column("away_source_slot_id", sa.Uuid(), nullable=True),
        sa.Column("away_source_outcome", sa.Text(), nullable=True),
        sa.Column("is_bye", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("winner_competition_team_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "away_source_outcome IS NULL OR away_source_outcome IN ('winner', 'loser')",
            name=op.f("ck_bracket_slot_away_source_outcome"),
        ),
        sa.CheckConstraint(
            "home_source_outcome IS NULL OR home_source_outcome IN ('winner', 'loser')",
            name=op.f("ck_bracket_slot_home_source_outcome"),
        ),
        sa.CheckConstraint("side IN ('winners', 'losers', 'final', 'consolation')", name=op.f("ck_bracket_slot_side")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "away_source_slot_id"],
            ["bracket_slot.tenant_id", "bracket_slot.id"],
            name=op.f("fk_bracket_slot_away_source_slot_id_bracket_slot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "away_team_id"],
            ["competition_team.tenant_id", "competition_team.id"],
            name=op.f("fk_bracket_slot_away_team_id_competition_team"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bracket_id"],
            ["bracket.tenant_id", "bracket.id"],
            name=op.f("fk_bracket_slot_bracket_id_bracket"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "game_id"],
            ["game.tenant_id", "game.id"],
            name=op.f("fk_bracket_slot_game_id_game"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "home_source_slot_id"],
            ["bracket_slot.tenant_id", "bracket_slot.id"],
            name=op.f("fk_bracket_slot_home_source_slot_id_bracket_slot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "home_team_id"],
            ["competition_team.tenant_id", "competition_team.id"],
            name=op.f("fk_bracket_slot_home_team_id_competition_team"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "winner_competition_team_id"],
            ["competition_team.tenant_id", "competition_team.id"],
            name=op.f("fk_bracket_slot_winner_competition_team_id_competition_team"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_bracket_slot_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bracket_slot")),
        sa.UniqueConstraint("tenant_id", "bracket_id", "side", "round_no", "position", name="uq_bracket_slot_position"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_bracket_slot_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_bracket_slot_away_source_slot_id"), "bracket_slot", ["tenant_id", "away_source_slot_id"], unique=False
    )
    op.create_index(op.f("ix_bracket_slot_away_team_id"), "bracket_slot", ["tenant_id", "away_team_id"], unique=False)
    op.create_index(
        op.f("ix_bracket_slot_home_source_slot_id"), "bracket_slot", ["tenant_id", "home_source_slot_id"], unique=False
    )
    op.create_index(op.f("ix_bracket_slot_home_team_id"), "bracket_slot", ["tenant_id", "home_team_id"], unique=False)
    op.create_index(
        op.f("ix_bracket_slot_winner_competition_team_id"),
        "bracket_slot",
        ["tenant_id", "winner_competition_team_id"],
        unique=False,
    )
    op.create_index(
        "uq_bracket_slot_game",
        "bracket_slot",
        ["tenant_id", "game_id"],
        unique=True,
        postgresql_where=sa.text("game_id IS NOT NULL"),
    )
    op.create_table(
        "game_official",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("official_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), server_default=sa.text("'referee'"), nullable=False),
        sa.Column("during", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        postgresql.ExcludeConstraint(
            (sa.column("tenant_id"), "="),
            (sa.column("official_id"), "="),
            (sa.column("during"), "&&"),
            using="gist",
            name="ex_game_official_overlap",
        ),
        sa.CheckConstraint(
            "role IN ('referee', 'assistant', 'scorekeeper', 'other')", name=op.f("ck_game_official_role")
        ),
        sa.CheckConstraint("NOT isempty(during)", name=op.f("ck_game_official_during")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "game_id"],
            ["game.tenant_id", "game.id"],
            name=op.f("fk_game_official_game_id_game"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "official_id"],
            ["official.tenant_id", "official.id"],
            name=op.f("fk_game_official_official_id_official"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_game_official_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_game_official")),
        sa.UniqueConstraint("tenant_id", "game_id", "official_id", name="uq_game_official_game_official"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_game_official_tenant_id_id")),
    )
    op.create_index(op.f("ix_game_official_official_id"), "game_official", ["tenant_id", "official_id"], unique=False)
    op.create_table(
        "game_result",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("competition_team_id", sa.Uuid(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("went_to_overtime", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("participation", sa.Text(), server_default=sa.text("'full'"), nullable=False),
        sa.Column("sportsmanship", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("bonus_points", sa.Numeric(precision=5, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("recorded_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "participation IN ('full', 'default', 'forfeit')", name=op.f("ck_game_result_participation")
        ),
        sa.CheckConstraint("side IN ('home', 'away')", name=op.f("ck_game_result_side")),
        sa.CheckConstraint("score IS NULL OR score >= 0", name=op.f("ck_game_result_score")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "competition_team_id"],
            ["competition_team.tenant_id", "competition_team.id"],
            name=op.f("fk_game_result_competition_team_id_competition_team"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "game_id"],
            ["game.tenant_id", "game.id"],
            name=op.f("fk_game_result_game_id_game"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recorded_by_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_game_result_recorded_by_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_game_result_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_game_result")),
        sa.UniqueConstraint("tenant_id", "game_id", "competition_team_id", name="uq_game_result_game_team"),
        sa.UniqueConstraint("tenant_id", "game_id", "side", name="uq_game_result_game_side"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_game_result_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_game_result_competition_team_id"), "game_result", ["tenant_id", "competition_team_id"], unique=False
    )
    op.create_index(
        op.f("ix_game_result_recorded_by_staff_user_id"),
        "game_result",
        ["tenant_id", "recorded_by_staff_user_id"],
        unique=False,
    )
    for table in TENANT_TABLES:
        enable_rls(table)


def downgrade() -> None:
    op.drop_index(op.f("ix_game_result_recorded_by_staff_user_id"), table_name="game_result")
    op.drop_index(op.f("ix_game_result_competition_team_id"), table_name="game_result")
    op.drop_table("game_result")
    op.drop_index(op.f("ix_game_official_official_id"), table_name="game_official")
    op.drop_table("game_official")
    op.drop_index("uq_bracket_slot_game", table_name="bracket_slot", postgresql_where=sa.text("game_id IS NOT NULL"))
    op.drop_index(op.f("ix_bracket_slot_winner_competition_team_id"), table_name="bracket_slot")
    op.drop_index(op.f("ix_bracket_slot_home_team_id"), table_name="bracket_slot")
    op.drop_index(op.f("ix_bracket_slot_home_source_slot_id"), table_name="bracket_slot")
    op.drop_index(op.f("ix_bracket_slot_away_team_id"), table_name="bracket_slot")
    op.drop_index(op.f("ix_bracket_slot_away_source_slot_id"), table_name="bracket_slot")
    op.drop_table("bracket_slot")
    op.drop_index("ix_standing_division_rank", table_name="standing")
    op.drop_index(op.f("ix_standing_competition_id"), table_name="standing")
    op.drop_table("standing")
    op.drop_index(
        "uq_roster_entry_team_client",
        table_name="roster_entry",
        postgresql_where=sa.text("client_id IS NOT NULL AND status = 'active'"),
    )
    op.drop_index(op.f("ix_roster_entry_competition_team_id"), table_name="roster_entry")
    op.drop_index(op.f("ix_roster_entry_client_id"), table_name="roster_entry")
    op.drop_table("roster_entry")
    op.drop_index("uq_game_booking", table_name="game", postgresql_where=sa.text("booking_id IS NOT NULL"))
    op.drop_index(op.f("ix_game_schedule_run_id"), table_name="game")
    op.drop_index("ix_game_resource_time", table_name="game")
    op.drop_index("ix_game_home_team", table_name="game")
    op.drop_index(op.f("ix_game_division_id"), table_name="game")
    op.drop_index(
        "ix_game_day", table_name="game", postgresql_where=sa.text("status IN ('scheduled', 'played', 'postponed')")
    )
    op.drop_index("ix_game_competition_time", table_name="game")
    op.drop_index("ix_game_away_team", table_name="game")
    op.drop_table("game")
    op.drop_index(op.f("ix_competition_team_team_id"), table_name="competition_team")
    op.drop_index(op.f("ix_competition_team_fee_client_id"), table_name="competition_team")
    op.drop_index(op.f("ix_competition_team_division_id"), table_name="competition_team")
    op.drop_table("competition_team")
    op.drop_index("ix_team_name", table_name="team")
    op.drop_index(op.f("ix_team_captain_client_id"), table_name="team")
    op.drop_table("team")
    op.drop_index(
        "ix_schedule_run_open",
        table_name="schedule_run",
        postgresql_where=sa.text("state NOT IN ('committed', 'discarded')"),
    )
    op.drop_index(op.f("ix_schedule_run_created_by_staff_user_id"), table_name="schedule_run")
    op.drop_table("schedule_run")
    op.drop_index(
        "uq_official_staff_user", table_name="official", postgresql_where=sa.text("staff_user_id IS NOT NULL")
    )
    op.drop_index(op.f("ix_official_location_id"), table_name="official")
    op.drop_table("official")
    op.drop_index(op.f("ix_bracket_division_id"), table_name="bracket")
    op.drop_index(op.f("ix_bracket_competition_id"), table_name="bracket")
    op.drop_table("bracket")
    op.drop_index("uq_division_competition_name", table_name="division")
    op.drop_table("division")
    op.drop_index(op.f("ix_competition_sport_id"), table_name="competition")
    op.drop_index(op.f("ix_competition_season_id"), table_name="competition")
    op.drop_index(op.f("ix_competition_revenue_category_id"), table_name="competition")
    op.drop_index("ix_competition_list", table_name="competition")
    op.drop_index(op.f("ix_competition_age_group_id"), table_name="competition")
    op.drop_table("competition")
    op.drop_index("uq_sport_name", table_name="sport")
    op.drop_table("sport")
    op.drop_index("uq_season_name", table_name="season")
    op.drop_table("season")
    op.drop_index("uq_age_group_name", table_name="age_group")
    op.drop_table("age_group")
