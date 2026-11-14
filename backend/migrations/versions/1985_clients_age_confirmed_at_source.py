"""clients: `age_confirmed_at` is the one source of truth for a confirmed age, and the location staff were told at.

Drops `is_birth_on_unverified` (a date with no `age_confirmed_at` is unconfirmed, whoever wrote it), moves the queue
index to that condition, and records `age_review_location_id`: the booking location the one staff notice went to,
whose staff may then confirm without moving the client's home location.

Revision ID: 1985
Revises: 1984
"""

import sqlalchemy as sa
from alembic import op

revision = "1985"
down_revision = "1984"


def upgrade() -> None:
    op.drop_index("ix_client_age_review", table_name="client")
    op.drop_column("client", "is_birth_on_unverified")
    op.create_index(
        "ix_client_age_review", "client", ["tenant_id", "home_location_id", "earliest_booking_at", "id"],
        postgresql_where=sa.text("birth_on IS NOT NULL AND age_confirmed_at IS NULL"),
    )  # fmt: skip
    op.add_column("client", sa.Column("age_review_location_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_client_age_review_location_id"), "client", ["tenant_id", "age_review_location_id"])
    op.create_foreign_key(
        op.f("fk_client_age_review_location_id_location"), "client", "location",
        ["tenant_id", "age_review_location_id"], ["tenant_id", "id"], ondelete="RESTRICT",
    )  # fmt: skip


def downgrade() -> None:
    op.drop_constraint(op.f("fk_client_age_review_location_id_location"), "client", type_="foreignkey")
    op.drop_index(op.f("ix_client_age_review_location_id"), table_name="client")
    op.drop_column("client", "age_review_location_id")
    op.drop_index("ix_client_age_review", table_name="client")
    op.add_column(
        "client", sa.Column("is_birth_on_unverified", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.execute("ALTER TABLE client NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE client SET is_birth_on_unverified = true WHERE birth_on IS NOT NULL AND age_confirmed_at IS NULL"
    )
    op.execute("ALTER TABLE client FORCE ROW LEVEL SECURITY")
    op.create_index(
        "ix_client_age_review", "client", ["tenant_id", "home_location_id", "earliest_booking_at", "id"],
        postgresql_where=sa.text("is_birth_on_unverified"),
    )  # fmt: skip
