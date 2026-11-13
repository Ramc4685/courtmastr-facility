"""billing: the refund row is committed before the processor is called (PAY-05, ADR 0003 section 8).

`refund.idempotency_key` finds the row again on a retry; status `initiated` means "written, processor not yet
answered", which a retry or the reconciliation sweep finishes.

Revision ID: 1801
Revises: 1562
"""

import sqlalchemy as sa
from alembic import op

revision = "1801"
down_revision = "1562"

_OLD = "status IN ('pending', 'succeeded', 'failed', 'cancelled')"
_NEW = "status IN ('initiated', 'pending', 'succeeded', 'failed', 'cancelled')"


def upgrade() -> None:
    op.add_column("refund", sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.create_index(
        "uq_refund_idempotency_key", "refund", ["tenant_id", "payment_id", "idempotency_key"], unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )  # fmt: skip
    op.create_index(
        "ix_refund_initiated", "refund", ["tenant_id", "created_at"], postgresql_where=sa.text("status = 'initiated'")
    )
    op.drop_constraint(op.f("ck_refund_status"), "refund", type_="check")
    op.create_check_constraint("status", "refund", _NEW)


def downgrade() -> None:
    op.execute("UPDATE refund SET status = 'cancelled' WHERE status = 'initiated'")
    op.drop_constraint(op.f("ck_refund_status"), "refund", type_="check")
    op.create_check_constraint("status", "refund", _OLD)
    op.drop_index("ix_refund_initiated", table_name="refund")
    op.drop_index("uq_refund_idempotency_key", table_name="refund")
    op.drop_column("refund", "idempotency_key")
