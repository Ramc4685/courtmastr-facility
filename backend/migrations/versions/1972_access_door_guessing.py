"""access: door guessing (building control review). The global keypad lockout goes (anyone could keep the building
locked); attempts are counted in Redis per door instead. A location threshold of wrong codes per hour alerts staff,
recorded as a `bad_code_alert` building event.

Revision ID: 1972
Revises: 1971
"""

import sqlalchemy as sa
from alembic import op

revision = "1972"
down_revision = "1971"

KINDS = (
    "'entry_granted', 'entry_denied', 'remote_unlock', 'member_unlock', 'light_on', 'light_off', 'override', "
    "'code_issued', 'code_revoked', 'command_failed', 'code_withheld'"
)


def upgrade() -> None:
    op.drop_column("door_device", "bad_code_count")
    op.drop_column("door_device", "locked_until_at")
    op.add_column(
        "access_settings",
        sa.Column("door_alert_bad_codes_per_hour", sa.Integer(), server_default=sa.text("20"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_access_settings_door_alert"), "access_settings", "door_alert_bad_codes_per_hour BETWEEN 1 AND 10000"
    )
    op.drop_constraint(op.f("ck_building_event_kind"), "building_event", type_="check")
    op.create_check_constraint(op.f("ck_building_event_kind"), "building_event", f"kind IN ({KINDS}, 'bad_code_alert')")


def downgrade() -> None:
    op.execute("DELETE FROM building_event WHERE kind = 'bad_code_alert'")
    op.drop_constraint(op.f("ck_building_event_kind"), "building_event", type_="check")
    op.create_check_constraint(op.f("ck_building_event_kind"), "building_event", f"kind IN ({KINDS})")
    op.drop_constraint(op.f("ck_access_settings_door_alert"), "access_settings", type_="check")
    op.drop_column("access_settings", "door_alert_bad_codes_per_hour")
    op.add_column("door_device", sa.Column("locked_until_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("door_device", sa.Column("bad_code_count", sa.Integer(), server_default=sa.text("0"), nullable=False))
