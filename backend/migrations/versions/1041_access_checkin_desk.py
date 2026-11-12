"""access check-in desk (Phase 10 chip C): check-in stations and check-out (CHK-07), and ID card templates
(CHK-12, MEM-19).

Generated from the models, then completed by hand: enable_rls() per table, the check-out constraint.

Revision ID: 1041
Revises: 1022
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls

revision = "1041"
down_revision = "1091"

_OPEN = "checked_out_at IS NULL AND result <> 'denied'"


def upgrade() -> None:
    op.create_table(
        "check_in_station",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_check_in_station_location_id_location"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_check_in_station_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_check_in_station")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_check_in_station_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "location_id", "name", name="uq_check_in_station_name"),
    )
    op.create_table(
        "id_card_template",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "shown_fields", sa.ARRAY(sa.Text()), server_default=sa.text("'{name,membership_number}'"), nullable=False
        ),
        sa.Column("has_photo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "shown_fields <@ ARRAY['name', 'membership_number', 'membership_type', 'expires_on', 'date_of_birth']::text[]",
            name=op.f("ck_id_card_template_shown_fields"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_id_card_template_location_id_location"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_id_card_template_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_id_card_template")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_id_card_template_tenant_id_id")),
    )
    op.create_index(op.f("ix_id_card_template_location_id"), "id_card_template", ["tenant_id", "location_id"])
    op.create_index(
        "uq_id_card_template_default", "id_card_template", ["tenant_id", "location_id"], unique=True,
        postgresql_where=sa.text("is_default"), postgresql_nulls_not_distinct=True,
    )  # fmt: skip
    op.add_column("check_in", sa.Column("check_in_station_id", sa.Uuid(), nullable=True))
    op.add_column("check_in", sa.Column("checked_out_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_check_in_check_in_station_id"), "check_in", ["tenant_id", "check_in_station_id"])
    op.create_index(
        "ix_check_in_open", "check_in", ["tenant_id", "location_id", "local_on"], postgresql_where=sa.text(_OPEN)
    )
    op.create_foreign_key(
        op.f("fk_check_in_check_in_station_id_check_in_station"), "check_in", "check_in_station",
        ["tenant_id", "check_in_station_id"], ["tenant_id", "id"], ondelete="RESTRICT",
    )  # fmt: skip
    op.create_check_constraint(
        op.f("ck_check_in_out"), "check_in",
        "checked_out_at IS NULL OR (checked_out_at >= checked_in_at AND result <> 'denied')",
    )  # fmt: skip
    enable_rls("check_in_station")
    enable_rls("id_card_template")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_check_in_out"), "check_in", type_="check")
    op.drop_constraint(op.f("fk_check_in_check_in_station_id_check_in_station"), "check_in", type_="foreignkey")
    op.drop_index("ix_check_in_open", table_name="check_in")
    op.drop_index(op.f("ix_check_in_check_in_station_id"), table_name="check_in")
    op.drop_column("check_in", "checked_out_at")
    op.drop_column("check_in", "check_in_station_id")
    op.drop_table("id_card_template")
    op.drop_table("check_in_station")
