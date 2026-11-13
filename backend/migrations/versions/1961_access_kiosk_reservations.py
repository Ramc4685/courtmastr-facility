"""access: the kiosk reservation page (CHK-05, CHK-06; owner decisions 2026-11-13, question 15): how far ahead
sessions are listed, auto-book, and the reservation page timeout.

Written by hand in the shape autogenerate produces.

Revision ID: 1961
Revises: 1951
"""

import sqlalchemy as sa
from alembic import op

revision = "1961"
down_revision = "1951"


def upgrade() -> None:
    op.add_column(
        "kiosk_settings",
        sa.Column("visible_range_minutes", sa.Integer(), server_default=sa.text("240"), nullable=False),
    )
    op.add_column(
        "kiosk_settings", sa.Column("is_auto_book", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column(
        "kiosk_settings",
        sa.Column("reservation_timeout_seconds", sa.Integer(), server_default=sa.text("30"), nullable=False),
    )
    op.create_check_constraint("visible_range", "kiosk_settings", "visible_range_minutes BETWEEN 0 AND 1440")
    op.create_check_constraint("reservation_timeout", "kiosk_settings", "reservation_timeout_seconds BETWEEN 3 AND 300")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_kiosk_settings_reservation_timeout"), "kiosk_settings", type_="check")
    op.drop_constraint(op.f("ck_kiosk_settings_visible_range"), "kiosk_settings", type_="check")
    op.drop_column("kiosk_settings", "reservation_timeout_seconds")
    op.drop_column("kiosk_settings", "is_auto_book")
    op.drop_column("kiosk_settings", "visible_range_minutes")
