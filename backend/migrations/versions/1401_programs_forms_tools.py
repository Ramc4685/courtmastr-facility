"""programs: group classifiers, saved views, page settings and registration defaults (REG-03, REG-04, REG-06,
REG-11), and event forms with versions, inventory, submissions and answers (REG-15 to REG-24).

Revision ID: 1401
Revises: 1461
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1401"
down_revision = "1461"


_TABLES = (
    "program_classifier",
    "program_saved_view",
    "program_page_setting",
    "registration_default",
    "form",
    "form_version",
    "form_inventory",
    "form_submission",
    "form_answer",
)


def upgrade() -> None:
    op.create_table(
        "program_classifier",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('season', 'sport', 'age_division')", name=op.f("ck_program_classifier_kind")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_program_classifier_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_program_classifier")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_program_classifier_tenant_id_id")),
    )
    op.create_index(
        "uq_program_classifier_kind_title",
        "program_classifier",
        ["tenant_id", "kind", sa.literal_column("lower(title)")],
        unique=True,
    )
    op.create_table(
        "form",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=True),
        sa.Column("event_text", sa.Text(), nullable=True),
        sa.Column("event_starts_on", sa.Date(), nullable=True),
        sa.Column("event_ends_on", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_message", sa.Text(), nullable=True),
        sa.Column("confirmation_message", sa.Text(), nullable=True),
        sa.Column("is_template", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("copied_from_form_id", sa.Uuid(), nullable=True),
        sa.Column("revenue_category_id", sa.Uuid(), nullable=True),
        sa.Column("allows_coupons", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_waitlist", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("submitted_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("header_file_id", sa.Uuid(), nullable=True),
        sa.Column("theme", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'open', 'closed')", name=op.f("ck_form_status")),
        sa.CheckConstraint(
            "auto_close_at IS NULL OR opens_at IS NULL OR auto_close_at > opens_at", name=op.f("ck_form_window")
        ),
        sa.CheckConstraint("capacity IS NULL OR submitted_count <= capacity", name=op.f("ck_form_capacity")),
        sa.CheckConstraint(
            "event_ends_on IS NULL OR event_starts_on IS NULL OR event_ends_on >= event_starts_on",
            name=op.f("ck_form_span"),
        ),
        sa.CheckConstraint("submitted_count >= 0", name=op.f("ck_form_count")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "copied_from_form_id"],
            ["form.tenant_id", "form.id"],
            name=op.f("fk_form_copied_from_form_id_form"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "header_file_id"],
            ["stored_file.tenant_id", "stored_file.id"],
            name=op.f("fk_form_header_file_id_stored_file"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_form_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revenue_category_id"],
            ["revenue_category.tenant_id", "revenue_category.id"],
            name=op.f("fk_form_revenue_category_id_revenue_category"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_form_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_form_tenant_id_id")),
    )
    op.create_index(op.f("ix_form_copied_from_form_id"), "form", ["tenant_id", "copied_from_form_id"], unique=False)
    op.create_index(op.f("ix_form_header_file_id"), "form", ["tenant_id", "header_file_id"], unique=False)
    op.create_index("ix_form_list", "form", ["tenant_id", "location_id", "status", "id"], unique=False)
    op.create_index(op.f("ix_form_revenue_category_id"), "form", ["tenant_id", "revenue_category_id"], unique=False)
    op.create_table(
        "registration_default",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("payment_requirement", sa.Text(), server_default=sa.text("'immediate_card_payment'"), nullable=False),
        sa.Column("displays_openings", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("waitlist_mode", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("online_description", sa.Text(), nullable=True),
        sa.Column("confirmation_message", sa.Text(), nullable=True),
        sa.Column("closed_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "payment_requirement IN ('pay_later_allowed', 'immediate_card_payment', 'card_required_charge_optional', 'card_required_no_charge')",
            name=op.f("ck_registration_default_payment_requirement"),
        ),
        sa.CheckConstraint(
            "waitlist_mode IN ('disabled', 'manual', 'auto_promote')",
            name=op.f("ck_registration_default_waitlist_mode"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_registration_default_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_registration_default_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_default")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_registration_default_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "location_id", name="uq_registration_default_location"),
    )
    op.create_table(
        "form_inventory",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("limit_count", sa.Integer(), nullable=False),
        sa.Column("sold_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("sold_out_memo", sa.Text(), nullable=True),
        sa.Column("shows_count_publicly", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("limit_count >= 0", name=op.f("ck_form_inventory_limit")),
        sa.CheckConstraint("sold_count BETWEEN 0 AND limit_count", name=op.f("ck_form_inventory_sold")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "form_id"],
            ["form.tenant_id", "form.id"],
            name=op.f("fk_form_inventory_form_id_form"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_form_inventory_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_inventory")),
        sa.UniqueConstraint("tenant_id", "form_id", "item_key", name="uq_form_inventory_form_item"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_form_inventory_tenant_id_id")),
    )
    op.create_table(
        "form_version",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("schema", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("state IN ('draft', 'published', 'superseded')", name=op.f("ck_form_version_state")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "form_id"],
            ["form.tenant_id", "form.id"],
            name=op.f("fk_form_version_form_id_form"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "published_by_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_form_version_published_by_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_form_version_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_version")),
        sa.UniqueConstraint("tenant_id", "form_id", "version_no", name="uq_form_version_form_no"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_form_version_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_form_version_published_by_staff_user_id"),
        "form_version",
        ["tenant_id", "published_by_staff_user_id"],
        unique=False,
    )
    op.create_index(
        "uq_form_version_one_draft",
        "form_version",
        ["tenant_id", "form_id"],
        unique=True,
        postgresql_where=sa.text("state = 'draft'"),
    )
    op.create_index(
        "uq_form_version_one_published",
        "form_version",
        ["tenant_id", "form_id"],
        unique=True,
        postgresql_where=sa.text("state = 'published'"),
    )
    op.create_table(
        "program_page_setting",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("staff_user_id", sa.Uuid(), nullable=False),
        sa.Column("page_key", sa.Text(), nullable=False),
        sa.Column("settings", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "page_key IN ('program_list', 'member_grid')", name=op.f("ck_program_page_setting_page_key")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_program_page_setting_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_program_page_setting_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_program_page_setting")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_program_page_setting_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "staff_user_id", "page_key", name="uq_program_page_setting_page"),
    )
    op.create_table(
        "program_saved_view",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("staff_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("sort", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_program_saved_view_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_program_saved_view_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_program_saved_view")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_program_saved_view_tenant_id_id")),
    )
    op.create_index(
        "uq_program_saved_view_name",
        "program_saved_view",
        ["tenant_id", "staff_user_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "form_submission",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("form_version_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("confirmation_no", sa.Integer(), nullable=False),
        sa.Column("account_client_id", sa.Uuid(), nullable=True),
        sa.Column("registrant_client_id", sa.Uuid(), nullable=True),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("contact_name", sa.Text(), nullable=False),
        sa.Column("contact_email", sa.Text(), nullable=False),
        sa.Column("contact_phone", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_edited_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)", name=op.f("ck_form_submission_cancel")
        ),
        sa.CheckConstraint("channel IN ('portal', 'public_link')", name=op.f("ck_form_submission_channel")),
        sa.CheckConstraint(
            "status IN ('confirmed', 'waitlisted', 'cancelled')", name=op.f("ck_form_submission_status")
        ),
        sa.CheckConstraint("total_minor >= 0", name=op.f("ck_form_submission_total")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f("fk_form_submission_account_client_id_client"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "form_id"],
            ["form.tenant_id", "form.id"],
            name=op.f("fk_form_submission_form_id_form"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "form_version_id"],
            ["form_version.tenant_id", "form_version.id"],
            name=op.f("fk_form_submission_form_version_id_form_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["invoice.tenant_id", "invoice.id"],
            name=op.f("fk_form_submission_invoice_id_invoice"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "last_edited_by_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_form_submission_last_edited_by_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_form_submission_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "registrant_client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f("fk_form_submission_registrant_client_id_client"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_form_submission_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_submission")),
        sa.UniqueConstraint("tenant_id", "confirmation_no", name="uq_form_submission_confirmation_no"),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_form_submission_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_form_submission_account_client_id"),
        "form_submission",
        ["tenant_id", "account_client_id"],
        unique=False,
    )
    op.create_index(
        "ix_form_submission_form", "form_submission", ["tenant_id", "form_id", "status", "id"], unique=False
    )
    op.create_index(
        op.f("ix_form_submission_form_version_id"), "form_submission", ["tenant_id", "form_version_id"], unique=False
    )
    op.create_index(
        "uq_form_submission_public_email",
        "form_submission",
        ["tenant_id", "form_id", sa.text("lower(contact_email)")],
        unique=True,
        # Erased rows share one placeholder address (programs.forms.ERASED_EMAIL), so they stay out of the index.
        postgresql_where=sa.text(
            "status <> 'cancelled' AND channel = 'public_link' AND contact_email <> 'erased@invalid.example'"
        ),
    )
    op.create_index(op.f("ix_form_submission_invoice_id"), "form_submission", ["tenant_id", "invoice_id"], unique=False)
    op.create_index(
        op.f("ix_form_submission_last_edited_by_staff_user_id"),
        "form_submission",
        ["tenant_id", "last_edited_by_staff_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_form_submission_location_id"), "form_submission", ["tenant_id", "location_id"], unique=False
    )
    op.create_index(
        op.f("ix_form_submission_registrant_client_id"),
        "form_submission",
        ["tenant_id", "registrant_client_id"],
        unique=False,
    )
    op.create_table(
        "form_answer",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("form_submission_id", sa.Uuid(), nullable=False),
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("choice_key", sa.Text(), nullable=True),
        sa.Column("question_type", sa.Text(), nullable=False),
        sa.Column("text_value", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("charge_id", sa.Uuid(), nullable=True),
        sa.Column("stock_taken", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount_minor >= 0", name=op.f("ck_form_answer_amount")),
        sa.CheckConstraint("quantity IS NULL OR quantity > 0", name=op.f("ck_form_answer_quantity")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "charge_id"],
            ["charge.tenant_id", "charge.id"],
            name=op.f("fk_form_answer_charge_id_charge"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "form_id"],
            ["form.tenant_id", "form.id"],
            name=op.f("fk_form_answer_form_id_form"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "form_submission_id"],
            ["form_submission.tenant_id", "form_submission.id"],
            name=op.f("fk_form_answer_form_submission_id_form_submission"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_form_answer_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_answer")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_form_answer_tenant_id_id")),
    )
    op.create_index(op.f("ix_form_answer_charge_id"), "form_answer", ["tenant_id", "charge_id"], unique=False)
    op.create_index(
        op.f("ix_form_answer_form_submission_id"), "form_answer", ["tenant_id", "form_submission_id"], unique=False
    )
    op.create_index(
        "ix_form_answer_summary", "form_answer", ["tenant_id", "form_id", "item_key", "choice_key"], unique=False
    )
    op.add_column("program_group", sa.Column("season_classifier_id", sa.Uuid(), nullable=True))
    op.add_column("program_group", sa.Column("sport_classifier_id", sa.Uuid(), nullable=True))
    op.add_column("program_group", sa.Column("age_division_classifier_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_program_group_age_division_classifier_id"),
        "program_group",
        ["tenant_id", "age_division_classifier_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_program_group_season_classifier_id"),
        "program_group",
        ["tenant_id", "season_classifier_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_program_group_sport_classifier_id"),
        "program_group",
        ["tenant_id", "sport_classifier_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_program_group_age_division_classifier_id_program_classifier"),
        "program_group",
        "program_classifier",
        ["tenant_id", "age_division_classifier_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_program_group_season_classifier_id_program_classifier"),
        "program_group",
        "program_classifier",
        ["tenant_id", "season_classifier_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_program_group_sport_classifier_id_program_classifier"),
        "program_group",
        "program_classifier",
        ["tenant_id", "sport_classifier_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    for table in _TABLES:
        enable_rls(table)


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_program_group_sport_classifier_id_program_classifier"), "program_group", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_program_group_season_classifier_id_program_classifier"), "program_group", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_program_group_age_division_classifier_id_program_classifier"), "program_group", type_="foreignkey"
    )
    op.drop_index(op.f("ix_program_group_sport_classifier_id"), table_name="program_group")
    op.drop_index(op.f("ix_program_group_season_classifier_id"), table_name="program_group")
    op.drop_index(op.f("ix_program_group_age_division_classifier_id"), table_name="program_group")
    op.drop_column("program_group", "age_division_classifier_id")
    op.drop_column("program_group", "sport_classifier_id")
    op.drop_column("program_group", "season_classifier_id")
    op.drop_index("ix_form_answer_summary", table_name="form_answer")
    op.drop_index(op.f("ix_form_answer_form_submission_id"), table_name="form_answer")
    op.drop_index(op.f("ix_form_answer_charge_id"), table_name="form_answer")
    op.drop_table("form_answer")
    op.drop_index(op.f("ix_form_submission_registrant_client_id"), table_name="form_submission")
    op.drop_index(op.f("ix_form_submission_location_id"), table_name="form_submission")
    op.drop_index(op.f("ix_form_submission_last_edited_by_staff_user_id"), table_name="form_submission")
    op.drop_index(op.f("ix_form_submission_invoice_id"), table_name="form_submission")
    op.drop_index(op.f("ix_form_submission_form_version_id"), table_name="form_submission")
    op.drop_index("ix_form_submission_form", table_name="form_submission")
    op.drop_index("uq_form_submission_public_email", table_name="form_submission")
    op.drop_index(op.f("ix_form_submission_account_client_id"), table_name="form_submission")
    op.drop_table("form_submission")
    op.drop_index("uq_program_saved_view_name", table_name="program_saved_view")
    op.drop_table("program_saved_view")
    op.drop_table("program_page_setting")
    op.drop_index(
        "uq_form_version_one_published", table_name="form_version", postgresql_where=sa.text("state = 'published'")
    )
    op.drop_index("uq_form_version_one_draft", table_name="form_version", postgresql_where=sa.text("state = 'draft'"))
    op.drop_index(op.f("ix_form_version_published_by_staff_user_id"), table_name="form_version")
    op.drop_table("form_version")
    op.drop_table("form_inventory")
    op.drop_table("registration_default")
    op.drop_index(op.f("ix_form_revenue_category_id"), table_name="form")
    op.drop_index("ix_form_list", table_name="form")
    op.drop_index(op.f("ix_form_header_file_id"), table_name="form")
    op.drop_index(op.f("ix_form_copied_from_form_id"), table_name="form")
    op.drop_table("form")
    op.drop_index("uq_program_classifier_kind_title", table_name="program_classifier")
    op.drop_table("program_classifier")
