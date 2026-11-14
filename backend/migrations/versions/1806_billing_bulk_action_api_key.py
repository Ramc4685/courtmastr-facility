"""billing: a bulk action remembers the API key that started it (BIL-02).

Its job re-authorizes the key at every chunk, so revoking the key stops the rest of the job.

Revision ID: 1806
Revises: 1805
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "1806"
down_revision = "1805"


def upgrade() -> None:
    op.add_column("billing_bulk_action", sa.Column("requested_by_api_key_id", UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column("billing_bulk_action", "requested_by_api_key_id")
