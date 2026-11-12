"""billing: tender_type.system_key (Phase 8 I1 review round 2)

Marks the internal tender opening credits from a CSV import are booked on ('opening_balance') structurally rather
than by its editable label. Set only by billing; such a row is read-only and never offered as a choice.

Revision ID: 1272
Revises: 1271
"""

import sqlalchemy as sa
from alembic import op

revision = "1272"
down_revision = "1271"


def upgrade() -> None:
    op.add_column("tender_type", sa.Column("system_key", sa.Text(), nullable=True))
    op.create_index(
        "uq_tender_type_system_key",
        "tender_type",
        ["tenant_id", "system_key"],
        unique=True,
        postgresql_where=sa.text("system_key IS NOT NULL"),
    )
    op.create_check_constraint(
        op.f("ck_tender_type_system_key"),
        "tender_type",
        "system_key IS NULL OR (system_key = 'opening_balance' AND kind = 'external')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_tender_type_system_key"), "tender_type", type_="check")
    op.drop_index("uq_tender_type_system_key", table_name="tender_type")
    op.drop_column("tender_type", "system_key")
