"""access: entrance doors (building control review). The portal "open the door" opens only doors marked as the
location's entrance; doors registered before this revision are marked, so nothing changes for them.

Revision ID: 1977
Revises: 1976
"""

import sqlalchemy as sa
from alembic import op

revision = "1977"
down_revision = "1976"


def upgrade() -> None:
    op.add_column(
        "door_device", sa.Column("is_entrance", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.execute("ALTER TABLE door_device NO FORCE ROW LEVEL SECURITY")  # the owner backfills (as 1705)
    op.execute("UPDATE door_device SET is_entrance = true")
    op.execute("ALTER TABLE door_device FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_column("door_device", "is_entrance")
