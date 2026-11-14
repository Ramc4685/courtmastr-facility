"""access: lights never cut on players (building control review). `lighting_zone.lit_until_at` keeps a zone lit
for the run-on after the last minute a booking wanted it, so a booking moved or cancelled mid-play does not cut the
lights at once.

Revision ID: 1975
Revises: 1974
"""

import sqlalchemy as sa
from alembic import op

revision = "1975"
down_revision = "1974"


def upgrade() -> None:
    op.add_column("lighting_zone", sa.Column("lit_until_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("lighting_zone", "lit_until_at")
