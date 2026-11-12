"""memberships: automatic suspension for non-payment (MEM-14) and the plan's autopay default left to billing
(BIL-17: plan, then the billing setting for the sales channel).

Plans whose default was `false` become null: the staff setting defaults to off and the portal always sold
autopay, so every sale resolves as before until a tenant changes its billing settings.

Revision ID: 1331
Revises: 1330
"""

import sqlalchemy as sa
from alembic import op

revision = "1331"
down_revision = "1330"


def upgrade() -> None:
    op.alter_column("membership_plan", "is_autopay_default", nullable=True, server_default=None)
    op.execute("UPDATE membership_plan SET is_autopay_default = NULL WHERE NOT is_autopay_default")
    op.add_column("membership_suspension", sa.Column("past_due_invoice_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_membership_suspension_past_due_invoice_id_invoice"), "membership_suspension", "invoice",
        ["tenant_id", "past_due_invoice_id"], ["tenant_id", "id"], ondelete="RESTRICT",
    )  # fmt: skip
    op.create_index(
        "uq_membership_suspension_past_due", "membership_suspension",
        ["tenant_id", "membership_contract_id", "past_due_invoice_id"], unique=True,
        postgresql_where=sa.text("past_due_invoice_id IS NOT NULL"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_index("uq_membership_suspension_past_due", table_name="membership_suspension")
    op.drop_constraint(
        op.f("fk_membership_suspension_past_due_invoice_id_invoice"), "membership_suspension", type_="foreignkey"
    )
    op.drop_column("membership_suspension", "past_due_invoice_id")
    op.execute("UPDATE membership_plan SET is_autopay_default = false WHERE is_autopay_default IS NULL")
    op.alter_column("membership_plan", "is_autopay_default", nullable=False, server_default=sa.text("false"))
