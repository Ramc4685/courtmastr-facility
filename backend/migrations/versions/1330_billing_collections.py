"""billing: collections tags and client profiles (BIL-20), the non-payment suspension setting (MEM-14, Q13).

Generated from the model, then completed by hand: enable_rls() and the setting's CHECK.

Revision ID: 1330
Revises: 1310
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1330"
down_revision = "1310"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "collections_tag",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_collections_tag_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collections_tag")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_collections_tag_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_collections_tag_name"),
    )
    enable_rls("collections_tag")
    op.create_table(
        "client_collections_profile",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("collections_tag_id", sa.Uuid(), nullable=False),
        sa.Column("placed_on", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_by_staff_user_id", sa.Uuid(), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "client_id"], ["client.tenant_id", "client.id"],
            name=op.f("fk_client_collections_profile_client_id_client"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collections_tag_id"], ["collections_tag.tenant_id", "collections_tag.id"],
            name=op.f("fk_client_collections_profile_collections_tag_id_collections_tag"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "updated_by_staff_user_id"], ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_client_collections_profile_updated_by_staff_user_id_staff_user"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_client_collections_profile_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_collections_profile")),
        sa.UniqueConstraint("tenant_id", "client_id", name="uq_client_collections_profile_client"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_client_collections_profile_tenant_id_id")),
    )  # fmt: skip
    op.create_index(
        op.f("ix_client_collections_profile_collections_tag_id"), "client_collections_profile",
        ["tenant_id", "collections_tag_id"],
    )  # fmt: skip
    op.create_index(
        op.f("ix_client_collections_profile_updated_by_staff_user_id"), "client_collections_profile",
        ["tenant_id", "updated_by_staff_user_id"],
    )  # fmt: skip
    enable_rls("client_collections_profile")
    op.add_column("billing_settings", sa.Column("membership_suspend_after_days", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_billing_settings_membership_suspend_after_days"), "billing_settings",
        "membership_suspend_after_days BETWEEN 1 AND 365",
    )  # fmt: skip


def downgrade() -> None:
    op.drop_constraint(op.f("ck_billing_settings_membership_suspend_after_days"), "billing_settings", type_="check")
    op.drop_column("billing_settings", "membership_suspend_after_days")
    op.drop_table("client_collections_profile")
    op.drop_table("collections_tag")
