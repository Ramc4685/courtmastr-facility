"""rentals: the reason a staff member gave for booking a court in a minor's name (pilot minors rule).

Revision ID: 1981
Revises: 1965
"""

import sqlalchemy as sa
from alembic import op

revision = "1981"
down_revision = "1965"


def upgrade() -> None:
    op.add_column("rental_booking", sa.Column("minor_override_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("rental_booking", "minor_override_reason")
