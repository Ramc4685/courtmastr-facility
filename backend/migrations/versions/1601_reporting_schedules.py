"""phase 12 chip A: scheduled delivery of saved reports (RPT-01, ADR 0010 section 7 as amended), and the
export_job flag that emails the requester a sign-in link when a scheduled export is stored.

Generated from the model, then completed by hand: enable_rls() and the wall-time column type.

Revision ID: 1601
Revises: 1331
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1601"
down_revision = "1401"


def upgrade() -> None:
    op.create_table(
        "report_schedule",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("saved_report_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("owner_staff_user_id", sa.Uuid(), nullable=False),
        sa.Column("frequency", sa.Text(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("month_day", sa.Integer(), nullable=True),
        sa.Column("send_time", sa.Time(), nullable=False),
        sa.Column("format", sa.Text(), server_default=sa.text("'csv'"), nullable=False),
        sa.Column("includes_details", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("recipient_staff_user_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_run_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(frequency = 'monthly') = (month_day IS NOT NULL)", name=op.f("ck_report_schedule_month_day")
        ),
        sa.CheckConstraint("(frequency = 'weekly') = (weekday IS NOT NULL)", name=op.f("ck_report_schedule_weekday")),
        sa.CheckConstraint("format IN ('csv', 'xlsx', 'pdf')", name=op.f("ck_report_schedule_format")),
        sa.CheckConstraint("frequency IN ('daily', 'weekly', 'monthly')", name=op.f("ck_report_schedule_frequency")),
        sa.CheckConstraint(
            "cardinality(recipient_staff_user_ids) BETWEEN 1 AND 20", name=op.f("ck_report_schedule_recipients")
        ),
        sa.CheckConstraint("month_day BETWEEN 1 AND 28", name=op.f("ck_report_schedule_month_day_range")),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name=op.f("ck_report_schedule_weekday_range")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_report_schedule_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_report_schedule_owner_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "saved_report_id"],
            ["saved_report.tenant_id", "saved_report.id"],
            name=op.f("fk_report_schedule_saved_report_id_saved_report"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_report_schedule_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_schedule")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_report_schedule_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_report_schedule_saved_report_id"), "report_schedule", ["tenant_id", "saved_report_id"], unique=False
    )
    enable_rls("report_schedule")
    op.add_column(
        "export_job", sa.Column("notify_on_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("export_job", "notify_on_complete")
    op.drop_index(op.f("ix_report_schedule_saved_report_id"), table_name="report_schedule")
    op.drop_table("report_schedule")
