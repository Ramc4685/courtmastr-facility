"""staff coach share: independent coaches' engagement, share rules, earnings ledger and payout statements, plus the
two read views the coach reports use (staff README "Coach revenue share").

`coach_earning` is append-only (SELECT, INSERT): a correction is a reversing line, never an update.

Revision ID: 2031
Revises: 1985
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls

revision = "2031"
down_revision = "1985"

_TABLES = ("coach_engagement", "coach_share_rule", "coach_payout", "coach_payout_line")
VIEWS = {
    # every earning line with its coach and where it stands: unpaid (on no payout or a draft), approved, or paid
    "rpt_coach_earning": """
        SELECT e.tenant_id, e.id AS coach_earning_id, e.location_id, e.staff_payee_id, sp.display_name AS coach_name,
               sp.resource_id AS coach_resource_id, sp.staff_user_id AS coach_staff_user_id, e.kind, e.earned_on, e.description, e.gross_minor,
               e.facility_share_minor, e.coach_share_minor, p.id AS coach_payout_id,
               coalesce(p.status, 'unpaid') AS payout_status, p.paid_on
        FROM coach_earning e
        JOIN staff_payee sp ON sp.tenant_id = e.tenant_id AND sp.id = e.staff_payee_id
        LEFT JOIN coach_payout_line pl ON pl.tenant_id = e.tenant_id AND pl.coach_earning_id = e.id
        LEFT JOIN coach_payout p ON p.tenant_id = pl.tenant_id AND p.id = pl.coach_payout_id""",
}


def upgrade() -> None:
    op.create_table(
        "coach_earning",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("staff_payee_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("earned_on", sa.Date(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("reservation_type_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("gross_minor", sa.Integer(), nullable=False),
        sa.Column("facility_share_minor", sa.Integer(), nullable=False),
        sa.Column("coach_share_minor", sa.Integer(), nullable=False),
        sa.Column("coach_share_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("court_fee_minor", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reverses_coach_earning_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(kind = 'reversal') = (reverses_coach_earning_id IS NOT NULL)", name=op.f("ck_coach_earning_reversal")
        ),
        sa.CheckConstraint(
            "kind <> 'adjustment' OR (reason IS NOT NULL AND btrim(reason) <> '' AND gross_minor = 0)",
            name=op.f("ck_coach_earning_adjustment"),
        ),
        sa.CheckConstraint(
            "kind = 'adjustment' OR (source_type IS NOT NULL AND source_id IS NOT NULL)",
            name=op.f("ck_coach_earning_source"),
        ),
        sa.CheckConstraint("kind IN ('lesson', 'reversal', 'adjustment')", name=op.f("ck_coach_earning_kind")),
        sa.CheckConstraint("source_type IN ('enrollment', 'booking')", name=op.f("ck_coach_earning_source_type")),
        sa.CheckConstraint(
            "gross_minor = facility_share_minor + coach_share_minor", name=op.f("ck_coach_earning_split")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_coach_earning_created_by_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_coach_earning_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reservation_type_id"],
            ["reservation_type.tenant_id", "reservation_type.id"],
            name=op.f("fk_coach_earning_reservation_type_id_reservation_type"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reverses_coach_earning_id"],
            ["coach_earning.tenant_id", "coach_earning.id"],
            name=op.f("fk_coach_earning_reverses_coach_earning_id_coach_earning"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "staff_payee_id"],
            ["staff_payee.tenant_id", "staff_payee.id"],
            name=op.f("fk_coach_earning_staff_payee_id_staff_payee"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_coach_earning_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coach_earning")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_coach_earning_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_coach_earning_created_by_staff_user_id"),
        "coach_earning",
        ["tenant_id", "created_by_staff_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_coach_earning_payee", "coach_earning", ["tenant_id", "staff_payee_id", "earned_on", "id"], unique=False
    )
    op.create_index(
        op.f("ix_coach_earning_reservation_type_id"),
        "coach_earning",
        ["tenant_id", "reservation_type_id"],
        unique=False,
    )
    op.create_index("ix_coach_earning_source", "coach_earning", ["tenant_id", "source_type", "source_id"], unique=False)
    op.create_index(
        "uq_coach_earning_reversal",
        "coach_earning",
        ["tenant_id", "reverses_coach_earning_id"],
        unique=True,
        postgresql_where=sa.text("reverses_coach_earning_id IS NOT NULL"),
    )
    op.create_table(
        "coach_engagement",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("staff_payee_id", sa.Uuid(), nullable=False),
        sa.Column("engagement", sa.Text(), nullable=False),
        sa.Column("effective_from_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("engagement IN ('employee', 'independent')", name=op.f("ck_coach_engagement_engagement")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "staff_payee_id"],
            ["staff_payee.tenant_id", "staff_payee.id"],
            name=op.f("fk_coach_engagement_staff_payee_id_staff_payee"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_coach_engagement_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coach_engagement")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_coach_engagement_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "staff_payee_id", "effective_from_on", name="uq_coach_engagement"),
    )
    op.create_table(
        "coach_payout",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("staff_payee_id", sa.Uuid(), nullable=False),
        sa.Column("period_starts_on", sa.Date(), nullable=False),
        sa.Column("period_ends_on", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("line_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("gross_minor", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("facility_share_minor", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("coach_share_minor", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("adjustment_minor", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("payment_method", sa.Text(), nullable=True),
        sa.Column("payment_reference", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(status = 'paid') = (paid_on IS NOT NULL AND payment_method IS NOT NULL)",
            name=op.f("ck_coach_payout_paid"),
        ),
        sa.CheckConstraint(
            "payment_method IN ('bank_transfer', 'cheque', 'other')", name=op.f("ck_coach_payout_payment_method")
        ),
        sa.CheckConstraint("status = 'draft' OR approved_at IS NOT NULL", name=op.f("ck_coach_payout_approved")),
        sa.CheckConstraint("status IN ('draft', 'approved', 'paid')", name=op.f("ck_coach_payout_status")),
        sa.CheckConstraint(
            "gross_minor = facility_share_minor + coach_share_minor", name=op.f("ck_coach_payout_split")
        ),
        sa.CheckConstraint("period_ends_on >= period_starts_on", name=op.f("ck_coach_payout_period")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approved_by_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_coach_payout_approved_by_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_coach_payout_created_by_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_coach_payout_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "paid_by_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_coach_payout_paid_by_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "staff_payee_id"],
            ["staff_payee.tenant_id", "staff_payee.id"],
            name=op.f("fk_coach_payout_staff_payee_id_staff_payee"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_coach_payout_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coach_payout")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_coach_payout_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_coach_payout_approved_by_staff_user_id"),
        "coach_payout",
        ["tenant_id", "approved_by_staff_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_coach_payout_created_by_staff_user_id"),
        "coach_payout",
        ["tenant_id", "created_by_staff_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_coach_payout_location", "coach_payout", ["tenant_id", "location_id", "period_ends_on", "id"], unique=False
    )
    op.create_index(
        op.f("ix_coach_payout_paid_by_staff_user_id"),
        "coach_payout",
        ["tenant_id", "paid_by_staff_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_coach_payout_staff_payee_id"), "coach_payout", ["tenant_id", "staff_payee_id"], unique=False
    )
    op.create_table(
        "coach_share_rule",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("staff_payee_id", sa.Uuid(), nullable=True),
        sa.Column("reservation_type_id", sa.Uuid(), nullable=True),
        sa.Column("effective_from_on", sa.Date(), nullable=False),
        sa.Column("coach_share_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("court_fee_minor", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("court_fee_basis", sa.Text(), server_default=sa.text("'session'"), nullable=False),
        sa.Column("court_fee_applies", sa.Text(), server_default=sa.text("'before_split'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "court_fee_applies IN ('before_split', 'after_split')", name=op.f("ck_coach_share_rule_court_fee_applies")
        ),
        sa.CheckConstraint("court_fee_basis IN ('session', 'hour')", name=op.f("ck_coach_share_rule_court_fee_basis")),
        sa.CheckConstraint(
            "coach_share_pct BETWEEN 0 AND 100 AND court_fee_minor >= 0", name=op.f("ck_coach_share_rule_amounts")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reservation_type_id"],
            ["reservation_type.tenant_id", "reservation_type.id"],
            name=op.f("fk_coach_share_rule_reservation_type_id_reservation_type"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "staff_payee_id"],
            ["staff_payee.tenant_id", "staff_payee.id"],
            name=op.f("fk_coach_share_rule_staff_payee_id_staff_payee"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_coach_share_rule_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coach_share_rule")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_coach_share_rule_tenant_id_id")),
        sa.UniqueConstraint(
            "tenant_id",
            "staff_payee_id",
            "reservation_type_id",
            "effective_from_on",
            name="uq_coach_share_rule",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_coach_share_rule_reservation_type_id"),
        "coach_share_rule",
        ["tenant_id", "reservation_type_id"],
        unique=False,
    )
    op.create_table(
        "coach_payout_line",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("coach_payout_id", sa.Uuid(), nullable=False),
        sa.Column("coach_earning_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "coach_earning_id"],
            ["coach_earning.tenant_id", "coach_earning.id"],
            name=op.f("fk_coach_payout_line_coach_earning_id_coach_earning"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "coach_payout_id"],
            ["coach_payout.tenant_id", "coach_payout.id"],
            name=op.f("fk_coach_payout_line_coach_payout_id_coach_payout"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_coach_payout_line_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coach_payout_line")),
        sa.UniqueConstraint("tenant_id", "coach_earning_id", name="uq_coach_payout_line_earning"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_coach_payout_line_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_coach_payout_line_coach_payout_id"),
        "coach_payout_line",
        ["tenant_id", "coach_payout_id"],
        unique=False,
    )
    op.add_column("staff_payee", sa.Column("tax_form_on_file_on", sa.Date(), nullable=True))
    enable_rls("coach_earning", append_only=True)
    for table in _TABLES:
        enable_rls(table)
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {sql}")
        op.execute(f"GRANT SELECT ON {name} TO fh_app")


def downgrade() -> None:
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW {name}")
    op.drop_column("staff_payee", "tax_form_on_file_on")
    op.drop_index(op.f("ix_coach_payout_line_coach_payout_id"), table_name="coach_payout_line")
    op.drop_table("coach_payout_line")
    op.drop_index(op.f("ix_coach_share_rule_reservation_type_id"), table_name="coach_share_rule")
    op.drop_table("coach_share_rule")
    op.drop_index(op.f("ix_coach_payout_staff_payee_id"), table_name="coach_payout")
    op.drop_index(op.f("ix_coach_payout_paid_by_staff_user_id"), table_name="coach_payout")
    op.drop_index("ix_coach_payout_location", table_name="coach_payout")
    op.drop_index(op.f("ix_coach_payout_created_by_staff_user_id"), table_name="coach_payout")
    op.drop_index(op.f("ix_coach_payout_approved_by_staff_user_id"), table_name="coach_payout")
    op.drop_table("coach_payout")
    op.drop_table("coach_engagement")
    op.drop_index(
        "uq_coach_earning_reversal",
        table_name="coach_earning",
        postgresql_where=sa.text("reverses_coach_earning_id IS NOT NULL"),
    )
    op.drop_index("ix_coach_earning_source", table_name="coach_earning")
    op.drop_index(op.f("ix_coach_earning_reservation_type_id"), table_name="coach_earning")
    op.drop_index("ix_coach_earning_payee", table_name="coach_earning")
    op.drop_index(op.f("ix_coach_earning_created_by_staff_user_id"), table_name="coach_earning")
    op.drop_table("coach_earning")
    # ### end Alembic commands ###
