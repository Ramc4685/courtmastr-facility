"""rentals: a renewal waiting on the plan's waiver lapses after `rental_plan.renewal_wait_days` (default 14).

Revision ID: 1965
Revises: 1964
"""

import sqlalchemy as sa
from alembic import op

revision = "1965"
down_revision = "1964"


def upgrade() -> None:
    op.add_column(
        "rental_plan", sa.Column("renewal_wait_days", sa.SmallInteger(), server_default=sa.text("14"), nullable=False)
    )
    op.create_check_constraint("renewal_wait_days", "rental_plan", "renewal_wait_days BETWEEN 1 AND 90")


def downgrade() -> None:
    op.drop_constraint("renewal_wait_days", "rental_plan", type_="check")
    op.drop_column("rental_plan", "renewal_wait_days")
