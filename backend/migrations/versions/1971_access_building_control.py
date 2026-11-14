"""access: building control (CHK-15, CHK-16). Door devices, lighting zones and the resources that light them, entry
codes per booking, the building activity log, and the location settings for code windows and light timing.

Revision ID: 1971
Revises: 1985
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls

revision = "1971"
down_revision = "1985"


def upgrade() -> None:
    op.create_table(
        "door_device",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("device_ref", sa.Text(), nullable=False),
        sa.Column("unlock_seconds", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=True),
        sa.Column("bad_code_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("unlock_seconds BETWEEN 1 AND 60", name=op.f("ck_door_device_unlock_seconds")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_door_device_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_door_device_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_door_device")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_door_device_tenant_id_id")),
    )
    op.create_index(op.f("ix_door_device_location_id"), "door_device", ["tenant_id", "location_id"], unique=False)
    op.create_index("uq_door_device_token", "door_device", ["tenant_id", "token_hash"], unique=True)
    op.create_table(
        "lighting_zone",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("zone_ref", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("override_is_on", sa.Boolean(), nullable=True),
        sa.Column("override_until_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("commanded_is_on", sa.Boolean(), nullable=True),
        sa.Column("commanded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(override_is_on IS NULL) = (override_until_at IS NULL)", name=op.f("ck_lighting_zone_override")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_lighting_zone_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_lighting_zone_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lighting_zone")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_lighting_zone_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "location_id", "name", name="uq_lighting_zone_name"),
    )
    op.create_index(op.f("ix_lighting_zone_location_id"), "lighting_zone", ["tenant_id", "location_id"], unique=False)
    op.create_table(
        "lighting_zone_resource",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lighting_zone_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lighting_zone_id"],
            ["lighting_zone.tenant_id", "lighting_zone.id"],
            name=op.f("fk_lighting_zone_resource_lighting_zone_id_lighting_zone"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["resource.tenant_id", "resource.id"],
            name=op.f("fk_lighting_zone_resource_resource_id_resource"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_lighting_zone_resource_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lighting_zone_resource")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_lighting_zone_resource_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "lighting_zone_id", "resource_id", name="uq_lighting_zone_resource"),
    )
    op.create_index(
        op.f("ix_lighting_zone_resource_resource_id"),
        "lighting_zone_resource",
        ["tenant_id", "resource_id"],
        unique=False,
    )
    op.create_table(
        "entry_code",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("code_ciphertext", sa.Text(), nullable=False),
        sa.Column("valid_from_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name=op.f("ck_entry_code_revoked")),
        sa.CheckConstraint("status IN ('active', 'revoked')", name=op.f("ck_entry_code_status")),
        sa.CheckConstraint("valid_until_at > valid_from_at", name=op.f("ck_entry_code_window")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "booking_id"],
            ["booking.tenant_id", "booking.id"],
            name=op.f("fk_entry_code_booking_id_booking"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_entry_code_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_entry_code_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entry_code")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_entry_code_tenant_id_id")),
    )
    op.create_index(op.f("ix_entry_code_booking_id"), "entry_code", ["tenant_id", "booking_id"], unique=False)
    op.create_index(
        "uq_entry_code_active",
        "entry_code",
        ["tenant_id", "location_id", "code_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_entry_code_booking",
        "entry_code",
        ["tenant_id", "booking_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "building_event",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_on", sa.Date(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("door_device_id", sa.Uuid(), nullable=True),
        sa.Column("lighting_zone_id", sa.Uuid(), nullable=True),
        sa.Column("entry_code_id", sa.Uuid(), nullable=True),
        sa.Column("check_in_id", sa.Uuid(), nullable=True),
        sa.Column("staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('entry_granted', 'entry_denied', 'remote_unlock', 'member_unlock', 'light_on', 'light_off', 'override', 'code_issued', 'code_revoked', 'command_failed', 'code_withheld')",
            name=op.f("ck_building_event_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "check_in_id"],
            ["check_in.tenant_id", "check_in.id"],
            name=op.f("fk_building_event_check_in_id_check_in"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "door_device_id"],
            ["door_device.tenant_id", "door_device.id"],
            name=op.f("fk_building_event_door_device_id_door_device"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "entry_code_id"],
            ["entry_code.tenant_id", "entry_code.id"],
            name=op.f("fk_building_event_entry_code_id_entry_code"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lighting_zone_id"],
            ["lighting_zone.tenant_id", "lighting_zone.id"],
            name=op.f("fk_building_event_lighting_zone_id_lighting_zone"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_building_event_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_building_event_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_building_event_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_building_event")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_building_event_tenant_id_id")),
    )
    op.create_index(op.f("ix_building_event_check_in_id"), "building_event", ["tenant_id", "check_in_id"], unique=False)
    op.create_index(
        op.f("ix_building_event_door_device_id"), "building_event", ["tenant_id", "door_device_id"], unique=False
    )
    op.create_index(
        op.f("ix_building_event_entry_code_id"), "building_event", ["tenant_id", "entry_code_id"], unique=False
    )
    op.create_index(
        op.f("ix_building_event_lighting_zone_id"), "building_event", ["tenant_id", "lighting_zone_id"], unique=False
    )
    op.create_index(
        "ix_building_event_recent",
        "building_event",
        ["tenant_id", "location_id", sa.literal_column("occurred_at DESC"), sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_index(
        op.f("ix_building_event_staff_user_id"), "building_event", ["tenant_id", "staff_user_id"], unique=False
    )
    op.add_column(
        "access_settings", sa.Column("entry_code_early_min", sa.Integer(), server_default=sa.text("15"), nullable=False)
    )
    op.add_column(
        "access_settings", sa.Column("entry_code_grace_min", sa.Integer(), server_default=sa.text("10"), nullable=False)
    )
    op.add_column(
        "access_settings", sa.Column("light_lead_in_min", sa.Integer(), server_default=sa.text("5"), nullable=False)
    )
    op.add_column(
        "access_settings", sa.Column("light_run_on_min", sa.Integer(), server_default=sa.text("5"), nullable=False)
    )
    op.add_column(
        "access_settings",
        sa.Column("requires_paid_entry", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_access_settings_building"),
        "access_settings",
        "entry_code_early_min BETWEEN 0 AND 240 AND entry_code_grace_min BETWEEN 0 AND 240"
        " AND light_lead_in_min BETWEEN 0 AND 120 AND light_run_on_min BETWEEN 0 AND 120",
    )
    for table in ("door_device", "lighting_zone", "lighting_zone_resource", "entry_code"):
        enable_rls(table)
    enable_rls("building_event", append_only=True)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_access_settings_building"), "access_settings", type_="check")
    op.drop_column("access_settings", "requires_paid_entry")
    op.drop_column("access_settings", "light_run_on_min")
    op.drop_column("access_settings", "light_lead_in_min")
    op.drop_column("access_settings", "entry_code_grace_min")
    op.drop_column("access_settings", "entry_code_early_min")
    op.drop_index(op.f("ix_building_event_staff_user_id"), table_name="building_event")
    op.drop_index("ix_building_event_recent", table_name="building_event")
    op.drop_index(op.f("ix_building_event_lighting_zone_id"), table_name="building_event")
    op.drop_index(op.f("ix_building_event_entry_code_id"), table_name="building_event")
    op.drop_index(op.f("ix_building_event_door_device_id"), table_name="building_event")
    op.drop_index(op.f("ix_building_event_check_in_id"), table_name="building_event")
    op.drop_table("building_event")
    op.drop_index("uq_entry_code_booking", table_name="entry_code", postgresql_where=sa.text("status = 'active'"))
    op.drop_index("uq_entry_code_active", table_name="entry_code", postgresql_where=sa.text("status = 'active'"))
    op.drop_index(op.f("ix_entry_code_booking_id"), table_name="entry_code")
    op.drop_table("entry_code")
    op.drop_index(op.f("ix_lighting_zone_resource_resource_id"), table_name="lighting_zone_resource")
    op.drop_table("lighting_zone_resource")
    op.drop_index(op.f("ix_lighting_zone_location_id"), table_name="lighting_zone")
    op.drop_table("lighting_zone")
    op.drop_index("uq_door_device_token", table_name="door_device")
    op.drop_index(op.f("ix_door_device_location_id"), table_name="door_device")
    op.drop_table("door_device")
