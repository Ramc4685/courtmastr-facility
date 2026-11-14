"""billing: stored bulk actions from the billing-items workbench (BIL-02), run as a chunked job.

Revision ID: 1802
Revises: 1801
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1802"
down_revision = "1801"


def _common() -> list:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete="RESTRICT",
    )  # fmt: skip


def upgrade() -> None:
    t = "billing_bulk_action"
    op.create_table(
        t,
        *_common(),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("is_dry_run", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),  # fmt: skip
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("item_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("done_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("requested_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("request_hash", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "action IN ('create_invoices', 'reverse_charges', 'email_invoices', 'render_invoices', 'add_catalog_item')",
            name=op.f(f"ck_{t}_action"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'completed_with_errors')", name=op.f(f"ck_{t}_status")
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name=op.f(f"fk_{t}_tenant_id_tenant"), ondelete="RESTRICT"),
        _fk(t, "location_id", "location"),
        _fk(t, "requested_by_staff_user_id", "staff_user"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{t}")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f(f"uq_{t}_tenant_id_id")),
    )
    op.create_index("ix_billing_bulk_action_location_id", t, ["tenant_id", "location_id"])
    op.create_index("ix_billing_bulk_action_requested_by_staff_user_id", t, ["tenant_id", "requested_by_staff_user_id"])
    op.create_index(
        "uq_billing_bulk_action_key", t, ["tenant_id", "idempotency_key"], unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )  # fmt: skip
    i = "billing_bulk_action_item"
    op.create_table(
        i,
        *_common(),
        sa.Column("billing_bulk_action_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("group_client_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("result_type", sa.Text(), nullable=True),
        sa.Column("result_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.CheckConstraint("subject_type IN ('charge', 'invoice', 'client')", name=op.f(f"ck_{i}_subject_type")),
        sa.CheckConstraint("status IN ('pending', 'done', 'failed', 'skipped')", name=op.f(f"ck_{i}_status")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name=op.f(f"fk_{i}_tenant_id_tenant"), ondelete="RESTRICT"),
        _fk(i, "billing_bulk_action_id", "billing_bulk_action"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{i}")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f(f"uq_{i}_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "billing_bulk_action_id", "subject_id", name="uq_billing_bulk_action_item_subject"),
    )
    op.create_index("ix_billing_bulk_action_item_status", i, ["tenant_id", "billing_bulk_action_id", "status"])
    for table in (t, i):
        enable_rls(table)


def downgrade() -> None:
    op.drop_table("billing_bulk_action_item")
    op.drop_table("billing_bulk_action")
