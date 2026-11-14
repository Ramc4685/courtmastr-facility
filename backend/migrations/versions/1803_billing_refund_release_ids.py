"""billing: a release-then-refund keeps the allocations it releases on its `initiated` row (PAY-05).

If the request dies after the processor refunded, the sweep re-applies that release before posting the refund,
so the payment's remainder can never go negative.

Revision ID: 1803
Revises: 1802
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "1803"
down_revision = "1802"


def upgrade() -> None:
    op.add_column("refund", sa.Column("release_allocation_ids", ARRAY(UUID(as_uuid=True)), nullable=True))


def downgrade() -> None:
    op.drop_column("refund", "release_allocation_ids")
