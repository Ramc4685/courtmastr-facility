"""access: kiosk visit tokens and identification by possession (CHK-05; owner decisions 2026-11-13, question 15).
A single-use server-side token binds the reservation page to one admitted check-in on one device; the credential a
kiosk lookup matched is kept so a scanned card counts as possession; and a location switch for whether a visit found
by name may book free sessions.

Written by hand in the shape autogenerate produces; enable_rls() for the new table.

Revision ID: 1962
Revises: 1961
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls

revision = "1962"
down_revision = "1961"


def upgrade() -> None:
    op.create_table(
        "kiosk_visit",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kiosk_device_id", sa.Uuid(), nullable=False),
        sa.Column("check_in_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "check_in_id"], ["check_in.tenant_id", "check_in.id"],
            name=op.f("fk_kiosk_visit_check_in_id_check_in"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "kiosk_device_id"], ["kiosk_device.tenant_id", "kiosk_device.id"],
            name=op.f("fk_kiosk_visit_kiosk_device_id_kiosk_device"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_kiosk_visit_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kiosk_visit")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_kiosk_visit_tenant_id_id")),
    )  # fmt: skip
    op.create_index(op.f("ix_kiosk_visit_check_in_id"), "kiosk_visit", ["tenant_id", "check_in_id"], unique=False)
    op.create_index(
        op.f("ix_kiosk_visit_kiosk_device_id"), "kiosk_visit", ["tenant_id", "kiosk_device_id"], unique=False
    )
    op.create_index("uq_kiosk_visit_token", "kiosk_visit", ["tenant_id", "token_hash"], unique=True)
    enable_rls("kiosk_visit")
    op.add_column("kiosk_match", sa.Column("credential_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_kiosk_match_credential_id_credential"), "kiosk_match", "credential",
        ["tenant_id", "credential_id"], ["tenant_id", "id"], ondelete="RESTRICT",
    )  # fmt: skip
    op.create_index(op.f("ix_kiosk_match_credential_id"), "kiosk_match", ["tenant_id", "credential_id"], unique=False)
    op.add_column(
        "kiosk_settings",
        sa.Column("is_name_search_booking_allowed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("kiosk_settings", "is_name_search_booking_allowed")
    op.drop_index(op.f("ix_kiosk_match_credential_id"), table_name="kiosk_match")
    op.drop_constraint(op.f("fk_kiosk_match_credential_id_credential"), "kiosk_match", type_="foreignkey")
    op.drop_column("kiosk_match", "credential_id")
    op.drop_table("kiosk_visit")
