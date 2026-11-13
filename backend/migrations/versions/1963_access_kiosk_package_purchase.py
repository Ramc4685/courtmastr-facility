"""access: kiosk package purchase (CHK-05, CHK-06; owner decisions 2026-11-13, question 15, card on file only).
The location's switch, the package page timeout, and `check_in.identified_by = signed_card` for a verified app QR or
wallet-pass payload, the only identification that may charge the card on file.

Written by hand in the shape autogenerate produces.

Revision ID: 1963
Revises: 1962
"""

import sqlalchemy as sa
from alembic import op

revision = "1963"
down_revision = "1962"


def upgrade() -> None:
    op.add_column(
        "kiosk_settings",
        sa.Column("is_package_purchase_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "kiosk_settings",
        sa.Column("package_timeout_seconds", sa.Integer(), server_default=sa.text("60"), nullable=False),
    )
    op.create_check_constraint("package_timeout", "kiosk_settings", "package_timeout_seconds BETWEEN 3 AND 300")
    op.drop_constraint(op.f("ck_check_in_identified_by"), "check_in", type_="check")
    op.create_check_constraint(
        "identified_by", "check_in", "identified_by IN ('credential', 'signed_card', 'name_search', 'client_record')"
    )


def downgrade() -> None:
    op.execute("UPDATE check_in SET identified_by = 'credential' WHERE identified_by = 'signed_card'")
    op.drop_constraint(op.f("ck_check_in_identified_by"), "check_in", type_="check")
    op.create_check_constraint(
        "identified_by", "check_in", "identified_by IN ('credential', 'name_search', 'client_record')"
    )
    op.drop_constraint(op.f("ck_kiosk_settings_package_timeout"), "kiosk_settings", type_="check")
    op.drop_column("kiosk_settings", "package_timeout_seconds")
    op.drop_column("kiosk_settings", "is_package_purchase_enabled")
