"""pos desk edges (Phase 10 chip E): a per-location receipt footer on pos_settings (POS-14) and one row per
location per local day the low-stock digest was emailed (POS-22).

Written by hand in the shape autogenerate produces; enable_rls() for the new table.

Revision ID: 1081
Revises: 1022
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1081"
down_revision = "1041"


def upgrade() -> None:
    op.add_column("pos_settings", sa.Column("receipt_footer", sa.Text(), nullable=True))
    op.create_table(
        "pos_low_stock_digest",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("local_on", sa.Date(), nullable=False),
        sa.Column("sent_to", postgresql.CITEXT(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_pos_low_stock_digest_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_pos_low_stock_digest_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pos_low_stock_digest")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_pos_low_stock_digest_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "location_id", "local_on", name="uq_pos_low_stock_digest_day"),
    )
    enable_rls("pos_low_stock_digest")


def downgrade() -> None:
    op.drop_table("pos_low_stock_digest")
    op.drop_column("pos_settings", "receipt_footer")
