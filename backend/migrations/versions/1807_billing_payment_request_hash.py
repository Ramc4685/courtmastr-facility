"""billing: a payment remembers a digest of the request that created it (Phase 9 orphans).

A retry under the same Idempotency-Key with another amount, payer, payment method or invoice set is refused
before the processor is called, instead of reaching it with the same key and other parameters.

Revision ID: 1807
Revises: 1806
"""

import sqlalchemy as sa
from alembic import op

revision = "1807"
down_revision = "1806"


def upgrade() -> None:
    op.add_column("payment", sa.Column("request_hash", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("payment", "request_hash")
