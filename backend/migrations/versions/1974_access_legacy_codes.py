"""access: retire codes issued before eight digits (building control review). Every active code is revoked
(`superseded`); the minute tick issues each entitled person a new eight-digit code and emails it to them (or their
adult guardians), as for any booking without a code.

Revision ID: 1974
Revises: 1973
"""

from alembic import op

revision = "1974"
down_revision = "1973"


def upgrade() -> None:
    # The owner is subject to forced RLS like everyone else; lift it for this one update (as 1705 does).
    op.execute("ALTER TABLE entry_code NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE entry_code SET status = 'revoked', revoked_at = now(), revoke_reason = 'superseded'"
        " WHERE status = 'active'"
    )
    op.execute("ALTER TABLE entry_code FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    pass  # revoked codes stay revoked; the tick has issued their replacements
