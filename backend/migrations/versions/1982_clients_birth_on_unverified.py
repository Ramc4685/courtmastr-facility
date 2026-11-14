"""clients: flag a birth date first entered through the portal until staff confirm it (rentals minors rule).

Revision ID: 1982
Revises: 1981
"""

import sqlalchemy as sa
from alembic import op

revision = "1982"
down_revision = "1981"


def upgrade() -> None:
    op.add_column(
        "client", sa.Column("is_birth_on_unverified", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("client", "is_birth_on_unverified")
