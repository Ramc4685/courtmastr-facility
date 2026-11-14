"""leagues: set scoring. A sport or competition scores by points (the default, unchanged) or by sets (best of 1, 3
or 5, points to win a set, win-by margin, optional cap and deciding-set target); a result side keeps its points per
set and a standing the rally points of its played sets (points ratio).

Revision ID: 2001
Revises: 1965
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "2001"
down_revision = "1965"

SETS = (
    "scoring_mode = 'points' OR (sets_best_of IN (1, 3, 5) AND set_points_to BETWEEN 1 AND 99"
    " AND set_win_by BETWEEN 1 AND 5 AND (set_cap IS NULL OR set_cap > set_points_to)"
    " AND (deciding_set_points_to IS NULL OR deciding_set_points_to BETWEEN 1 AND 99))"
)


def upgrade() -> None:
    for table in ("sport", "competition"):
        op.add_column(table, sa.Column("scoring_mode", sa.Text(), server_default=sa.text("'points'"), nullable=False))
        op.add_column(table, sa.Column("sets_best_of", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("set_points_to", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("set_win_by", sa.Integer(), server_default=sa.text("2"), nullable=False))
        op.add_column(table, sa.Column("set_cap", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("deciding_set_points_to", sa.Integer(), nullable=True))
        op.create_check_constraint("scoring_mode", table, "scoring_mode IN ('points', 'sets')")
        op.create_check_constraint("sets", table, SETS)
    op.add_column(
        "game_result",
        sa.Column("set_scores", ARRAY(sa.Integer()), server_default=sa.text("'{}'"), nullable=False),
    )
    op.create_check_constraint("set_scores", "game_result", "cardinality(set_scores) <= 5 AND 0 <= ALL (set_scores)")
    for column in ("set_points_for", "set_points_against"):
        op.add_column("standing", sa.Column(column, sa.Integer(), server_default=sa.text("0"), nullable=False))


def downgrade() -> None:
    for column in ("set_points_against", "set_points_for"):
        op.drop_column("standing", column)
    op.drop_constraint("set_scores", "game_result", type_="check")
    op.drop_column("game_result", "set_scores")
    for table in ("competition", "sport"):
        op.drop_constraint("sets", table, type_="check")
        op.drop_constraint("scoring_mode", table, type_="check")
        for column in (
            "deciding_set_points_to",
            "set_cap",
            "set_win_by",
            "set_points_to",
            "sets_best_of",
            "scoring_mode",
        ):
            op.drop_column(table, column)
