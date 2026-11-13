"""access: a code revoke the controller has not confirmed stays due (building control review); the tick retries it
until it is confirmed. Partial index: only due rows are read.

Revision ID: 1978
Revises: 1977
"""

import sqlalchemy as sa
from alembic import op

revision = "1978"
down_revision = "1977"


def upgrade() -> None:
    op.add_column("entry_code", sa.Column("revoke_due", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.create_index(
        "ix_entry_code_revoke_due",
        "entry_code",
        ["tenant_id", "location_id"],
        unique=False,
        postgresql_where=sa.text("revoke_due"),
    )


def downgrade() -> None:
    op.drop_index("ix_entry_code_revoke_due", table_name="entry_code", postgresql_where=sa.text("revoke_due"))
    op.drop_column("entry_code", "revoke_due")
