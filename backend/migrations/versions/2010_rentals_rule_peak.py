"""rentals: a price rule can mark its band as peak (`rental_rate_rule.is_peak`), the owner's own peak hours.

Existing rules keep the meaning the court-use report gave them: a time-banded rate rule that charges more than its
rate's base price is marked peak; everything else is not.

Revision ID: 2010
Revises: 1965
"""

import sqlalchemy as sa
from alembic import op

revision = "2010"
down_revision = "1965"


def upgrade() -> None:
    op.add_column(
        "rental_rate_rule", sa.Column("is_peak", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    # the owner is subject to forced RLS like everyone else; lift it for this one backfill (as 1331 does)
    for table in ("rental_rate_rule", "rental_rate"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("""
        UPDATE rental_rate_rule u SET is_peak = true FROM rental_rate rr
        WHERE rr.tenant_id = u.tenant_id AND rr.id = u.rental_rate_id
          AND u.kind = 'rate' AND u.start_time IS NOT NULL AND u.amount_minor > rr.amount_minor""")
    for table in ("rental_rate_rule", "rental_rate"):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_column("rental_rate_rule", "is_peak")
