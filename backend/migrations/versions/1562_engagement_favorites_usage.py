"""engagement: client favourites (Phase 11 C2, APP-13) and anonymous daily app usage counts (APP-17).

Revision ID: 1562
Revises: 1561
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls

revision = "1562"
down_revision = "1561"


def upgrade() -> None:
    op.create_table(
        "client_favorite",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('reservation_type', 'program_group')", name=op.f("ck_client_favorite_kind")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f("fk_client_favorite_client_id_client"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_client_favorite_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_favorite")),
        sa.UniqueConstraint("tenant_id", "client_id", "kind", "target_id", name="uq_client_favorite_target"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_client_favorite_tenant_id_id")),
    )
    op.create_table(
        "app_usage_day",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('screen', 'action')", name=op.f("ck_app_usage_day_kind")),
        sa.CheckConstraint("name ~ '^[a-z0-9_.-]{1,60}$'", name=op.f("ck_app_usage_day_name")),
        sa.CheckConstraint("count >= 0", name=op.f("ck_app_usage_day_count")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_app_usage_day_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_usage_day")),
        sa.UniqueConstraint("tenant_id", "day", "kind", "name", name="uq_app_usage_day_key"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_app_usage_day_tenant_id_id")),
    )
    for table in ("client_favorite", "app_usage_day"):
        enable_rls(table)


def downgrade() -> None:
    op.drop_table("app_usage_day")
    op.drop_table("client_favorite")
