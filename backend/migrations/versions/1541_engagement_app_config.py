"""engagement: the member app configuration (APP-01, APP-02, APP-04, APP-05, APP-18), one row per tenant.

fh_platform may read app_config and portal_settings: the shared-app directory (searchAppDirectory) is the one
cross-tenant read, served by core.db.platform.search_app_directory (read only, listing fields only).

Revision ID: 1541
Revises: 1521
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1541"
down_revision = "1521"


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.Text(), server_default=sa.text("'shared'"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("app_name", sa.Text(), nullable=True),
        sa.Column("is_listed_in_directory", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("directory_name", sa.Text(), nullable=True),
        sa.Column("card_number_mode", sa.Text(), server_default=sa.text("'auto_generate'"), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("home_screen", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("schedule", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("mode IN ('shared', 'branded')", name=op.f("ck_app_config_mode")),
        sa.CheckConstraint(
            "card_number_mode IN ('auto_generate', 'manual_entry')", name=op.f("ck_app_config_card_number_mode")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_app_config_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_config")),
        sa.UniqueConstraint("tenant_id", name="uq_app_config_tenant"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_app_config_tenant_id_id")),
    )
    enable_rls("app_config")
    op.execute("GRANT SELECT ON app_config, portal_settings TO fh_platform")
    # Column grants only: the directory shows a city and the tenant logo, nothing else of these tables.
    op.execute("GRANT SELECT (tenant_id, id, city) ON location TO fh_platform")
    op.execute("GRANT SELECT (tenant_id, location_id, file_id) ON logo TO fh_platform")
    op.execute("GRANT SELECT (tenant_id, id, object_key) ON stored_file TO fh_platform")


def downgrade() -> None:
    op.execute("REVOKE SELECT (tenant_id, id, object_key) ON stored_file FROM fh_platform")
    op.execute("REVOKE SELECT (tenant_id, location_id, file_id) ON logo FROM fh_platform")
    op.execute("REVOKE SELECT (tenant_id, id, city) ON location FROM fh_platform")
    op.execute("REVOKE SELECT ON app_config, portal_settings FROM fh_platform")
    op.drop_table("app_config")
