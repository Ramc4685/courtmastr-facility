"""billing: a bulk action item keeps the amount it was priced at (BIL-02).

A run that names the dry run it previewed (`preview_id`) is refused when any subject's amount changed since.

Revision ID: 1804
Revises: 1803
"""

import sqlalchemy as sa
from alembic import op

revision = "1804"
down_revision = "1803"


def upgrade() -> None:
    op.add_column("billing_bulk_action_item", sa.Column("amount_minor", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("billing_bulk_action_item", "amount_minor")
