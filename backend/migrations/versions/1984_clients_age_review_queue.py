"""clients: the staff queue of age checks (owner decision 2026-11-13): the earliest booking an unconfirmed person
made online, and when staff were told about their first one (one notice per person, never one per booking).

Revision ID: 1984
Revises: 1983
"""

import sqlalchemy as sa
from alembic import op

revision = "1984"
down_revision = "1983"


def upgrade() -> None:
    op.add_column("client", sa.Column("earliest_booking_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("client", sa.Column("age_review_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_client_age_review", "client", ["tenant_id", "home_location_id", "earliest_booking_at", "id"],
        postgresql_where=sa.text("is_birth_on_unverified"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_index("ix_client_age_review", table_name="client")
    op.drop_column("client", "age_review_notified_at")
    op.drop_column("client", "earliest_booking_at")
