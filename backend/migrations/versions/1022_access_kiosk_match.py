"""access review fixes (Phase 10 chip B): single-use opaque kiosk match tokens, and a per-device count of wrong
kiosk exit PINs (the fifth revokes the device).

Written by hand in the shape autogenerate produces; enable_rls() for the new table.

Revision ID: 1022
Revises: 1021
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls

revision = "1022"
down_revision = "1021"


def upgrade() -> None:
    op.create_table(
        "kiosk_match",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kiosk_device_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f("fk_kiosk_match_client_id_client"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "kiosk_device_id"],
            ["kiosk_device.tenant_id", "kiosk_device.id"],
            name=op.f("fk_kiosk_match_kiosk_device_id_kiosk_device"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_kiosk_match_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kiosk_match")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_kiosk_match_tenant_id_id")),
    )
    op.create_index(op.f("ix_kiosk_match_client_id"), "kiosk_match", ["tenant_id", "client_id"], unique=False)
    op.create_index(op.f("ix_kiosk_match_kiosk_device_id"), "kiosk_match", ["tenant_id", "kiosk_device_id"], unique=False)
    op.create_index("uq_kiosk_match_token", "kiosk_match", ["tenant_id", "token_hash"], unique=True)
    op.add_column(
        "kiosk_device",
        sa.Column("exit_pin_failure_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    enable_rls("kiosk_match")


def downgrade() -> None:
    op.drop_column("kiosk_device", "exit_pin_failure_count")
    op.drop_table("kiosk_match")
