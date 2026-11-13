"""clients: staff confirm a self-declared birth date once (owner decision 2026-11-13, "Staff confirm once").

Records who confirmed and when; nothing about the document seen. Birth dates already on records created online
(sign-up, guest checkout, portal dependants) before 1982 are flagged too, so they also wait for staff.

Revision ID: 1983
Revises: 1982
"""

import sqlalchemy as sa
from alembic import op

revision = "1983"
down_revision = "1982"


def upgrade() -> None:
    op.add_column("client", sa.Column("age_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("client", sa.Column("age_confirmed_by_staff_user_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_client_age_confirmed_by_staff_user_id"), "client",
                    ["tenant_id", "age_confirmed_by_staff_user_id"])  # fmt: skip
    op.create_foreign_key(
        op.f("fk_client_age_confirmed_by_staff_user_id_staff_user"), "client", "staff_user",
        ["tenant_id", "age_confirmed_by_staff_user_id"], ["tenant_id", "id"], ondelete="RESTRICT",
    )  # fmt: skip
    # The owner is subject to forced RLS like everyone else; lift it for this one backfill (as 1331 does).
    op.execute("ALTER TABLE client NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE client SET is_birth_on_unverified = true WHERE birth_on IS NOT NULL "
        "AND created_via IN ('portal', 'registration') AND NOT is_birth_on_unverified"
    )
    op.execute("ALTER TABLE client FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_client_age_confirmed_by_staff_user_id_staff_user"), "client", type_="foreignkey"
    )
    op.drop_index(op.f("ix_client_age_confirmed_by_staff_user_id"), table_name="client")
    op.drop_column("client", "age_confirmed_by_staff_user_id")
    op.drop_column("client", "age_confirmed_at")
