"""engagement: member app content (Phase 11 C2): app_content (APP-07, APP-14), location_contact (APP-08, APP-09)
and app_inquiry, the staff inbox for trial pass requests (APP-12) and in-app feedback (APP-10).

Revision ID: 1561
Revises: 1541
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1561"
down_revision = "1541"


def upgrade() -> None:
    op.create_table(
        "app_content",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("link_url", sa.Text(), nullable=True),
        sa.Column("image_file_id", sa.Uuid(), nullable=True),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('news', 'info_page', 'announcement', 'promotion', 'gallery')", name=op.f("ck_app_content_kind")
        ),
        sa.CheckConstraint("link_url IS NULL OR link_url LIKE 'https://%%'", name=op.f("ck_app_content_link_url")),
        sa.CheckConstraint("char_length(body_text) <= 10000", name=op.f("ck_app_content_body_text")),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 120", name=op.f("ck_app_content_title")),
        sa.CheckConstraint("expires_at IS NULL OR expires_at > publish_at", name=op.f("ck_app_content_window")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "image_file_id"],
            ["stored_file.tenant_id", "stored_file.id"],
            name=op.f("fk_app_content_image_file_id_stored_file"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_app_content_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_app_content_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_content")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_app_content_tenant_id_id")),
    )
    op.create_index(op.f("ix_app_content_image_file_id"), "app_content", ["tenant_id", "image_file_id"], unique=False)
    op.create_index(op.f("ix_app_content_location_id"), "app_content", ["tenant_id", "location_id"], unique=False)
    op.create_index("ix_app_content_publish", "app_content", ["tenant_id", "publish_at", "id"], unique=False)
    op.create_table(
        "location_contact",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('department', 'service')", name=op.f("ck_location_contact_kind")),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name=op.f("ck_location_contact_name")),
        sa.CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name=op.f("ck_location_contact_reachable")),
        sa.CheckConstraint("phone IS NULL OR char_length(phone) <= 40", name=op.f("ck_location_contact_phone")),
        sa.CheckConstraint("role IS NULL OR char_length(role) <= 80", name=op.f("ck_location_contact_role")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_location_contact_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_location_contact_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_location_contact")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_location_contact_tenant_id_id")),
    )
    op.create_index(
        op.f("ix_location_contact_location_id"), "location_contact", ["tenant_id", "location_id"], unique=False
    )
    op.create_table(
        "app_inquiry",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("contact_name", sa.Text(), nullable=False),
        sa.Column("contact_email", postgresql.CITEXT(), nullable=True),
        sa.Column("contact_phone", sa.Text(), nullable=True),
        sa.Column("interest", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'new'"), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handled_by_staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind = 'feedback' OR client_id IS NULL", name=op.f("ck_app_inquiry_client")),
        sa.CheckConstraint("kind = 'feedback' OR contact_email IS NOT NULL", name=op.f("ck_app_inquiry_contact_email")),
        sa.CheckConstraint("kind IN ('trial', 'feedback')", name=op.f("ck_app_inquiry_kind")),
        sa.CheckConstraint(
            "rating IS NULL OR (kind = 'feedback' AND rating BETWEEN 1 AND 5)", name=op.f("ck_app_inquiry_rating")
        ),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'closed', 'converted')", name=op.f("ck_app_inquiry_status")
        ),
        sa.CheckConstraint("char_length(message) <= 2000", name=op.f("ck_app_inquiry_message")),
        sa.CheckConstraint("interest IS NULL OR char_length(interest) <= 120", name=op.f("ck_app_inquiry_interest")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f("fk_app_inquiry_client_id_client"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "handled_by_staff_user_id"],
            ["staff_user.tenant_id", "staff_user.id"],
            name=op.f("fk_app_inquiry_handled_by_staff_user_id_staff_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_app_inquiry_location_id_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_app_inquiry_tenant_id_tenant"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_inquiry")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_app_inquiry_tenant_id_id")),
    )
    op.create_index(op.f("ix_app_inquiry_client_id"), "app_inquiry", ["tenant_id", "client_id"], unique=False)
    op.create_index(
        op.f("ix_app_inquiry_handled_by_staff_user_id"),
        "app_inquiry",
        ["tenant_id", "handled_by_staff_user_id"],
        unique=False,
    )
    op.create_index("ix_app_inquiry_inbox", "app_inquiry", ["tenant_id", "location_id", "status", "id"], unique=False)
    for table in ("app_content", "location_contact", "app_inquiry"):
        enable_rls(table)


def downgrade() -> None:
    op.drop_index("ix_app_inquiry_inbox", table_name="app_inquiry")
    op.drop_index(op.f("ix_app_inquiry_handled_by_staff_user_id"), table_name="app_inquiry")
    op.drop_index(op.f("ix_app_inquiry_client_id"), table_name="app_inquiry")
    op.drop_table("app_inquiry")
    op.drop_index(op.f("ix_location_contact_location_id"), table_name="location_contact")
    op.drop_table("location_contact")
    op.drop_index("ix_app_content_publish", table_name="app_content")
    op.drop_index(op.f("ix_app_content_location_id"), table_name="app_content")
    op.drop_index(op.f("ix_app_content_image_file_id"), table_name="app_content")
    op.drop_table("app_content")
