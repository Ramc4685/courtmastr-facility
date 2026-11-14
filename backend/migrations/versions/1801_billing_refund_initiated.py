"""billing: the refund row is committed before the processor is called (PAY-05, ADR 0003 section 8).

`refund.idempotency_key` finds the row again on a retry; status `initiated` means "written, processor not yet
answered", which a retry or the reconciliation sweep finishes.

Revision ID: 1801
Revises: 1980
"""

import sqlalchemy as sa
from alembic import op

revision = "1801"
down_revision = "1980"

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


def count_initiated(bind) -> int:
    """Every tenant's `initiated` refunds. The owner is subject to forced RLS like everyone else and sees no tenant
    rows (count 0 always), so lift it for this one read, as 1705 does for its backfill."""
    bind.execute(sa.text("ALTER TABLE refund NO FORCE ROW LEVEL SECURITY"))
    try:
        return bind.execute(sa.text("SELECT count(*) FROM refund WHERE status = 'initiated'")).scalar() or 0
    finally:
        bind.execute(sa.text("ALTER TABLE refund FORCE ROW LEVEL SECURITY"))


def downgrade() -> None:
    # An `initiated` refund may already have been paid out by the processor: cancelling it would lose that money
    # from the books. Let the sweep finish every one first.
    left = count_initiated(op.get_bind())
    if left:
        raise RuntimeError(f"{left} refund(s) are still `initiated`; run the billing sweep before downgrading.")
    op.drop_constraint(op.f("ck_refund_status"), "refund", type_="check")
    op.create_check_constraint("status", "refund", _OLD)
    op.drop_index("ix_refund_initiated", table_name="refund")
    op.drop_index("uq_refund_idempotency_key", table_name="refund")
    op.drop_column("refund", "idempotency_key")
