"""phase 8 T2 review (PLT-06): campaign.is_send_all_granted records whether the scheduler held send_all, and
campaign.hold_reason says why the send job put a scheduled campaign back to draft. No grant change.

Revision ID: 1264
Revises: 1263
"""

import sqlalchemy as sa
from alembic import op

revision = "1264"
down_revision = "1263"


def upgrade() -> None:
    op.add_column("campaign", sa.Column("is_send_all_granted", sa.Boolean(), server_default=sa.text("false"),
                                        nullable=False))  # fmt: skip
    op.add_column("campaign", sa.Column("hold_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("campaign", "hold_reason")
    op.drop_column("campaign", "is_send_all_granted")
