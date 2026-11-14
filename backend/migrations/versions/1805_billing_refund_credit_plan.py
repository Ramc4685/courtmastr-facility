"""billing: the stored plan of an account-credit refund, so a retry replays the same legs (PAY-05).

Revision ID: 1805
Revises: 1804
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1805"
down_revision = "1804"


def upgrade() -> None:
    t = "refund_credit_plan"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("refund_batch_id", sa.Uuid(), nullable=False),
        sa.Column("legs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name=op.f(f"ck_{t}_amount_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f(f"fk_{t}_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f(f"fk_{t}_client_id_client"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f(f"uq_{t}_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_refund_credit_plan_key"),
    )
    op.create_index("ix_refund_credit_plan_client_id", t, ["tenant_id", "client_id"])
    enable_rls(t)


def downgrade() -> None:
    op.drop_table("refund_credit_plan")
