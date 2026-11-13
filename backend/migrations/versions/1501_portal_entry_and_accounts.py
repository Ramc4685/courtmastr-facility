"""Phase 11 chip A: portal entry and accounts. Brand colours on the tenant (SSP-14), portal menu, sign-up switch,
social links and redirects on portal settings (SSP-13, 05, 15, 07), public sign-ups (SSP-05), recorded terms
acknowledgments (SSP-14), and guest checkout for program groups (REG-12).

Written by hand to match the models; enable_rls() on both new tables.

Revision ID: 1501
Revises: 1441
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1501"
down_revision = "1441"

_CHANNELS_OLD = "channel IN ('staff', 'portal', 'public_link', 'mobile', 'api')"
_CHANNELS_NEW = "channel IN ('staff', 'portal', 'public_link', 'mobile', 'api', 'guest')"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _tenant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name=f"fk_{table}_tenant_id_tenant", ondelete="RESTRICT")


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", column], [f"{target}.tenant_id", f"{target}.id"],
        name=f"fk_{table}_{column}_{target}", ondelete="RESTRICT",
    )  # fmt: skip


def upgrade() -> None:
    op.add_column("tenant", sa.Column("brand_primary_color", sa.Text(), nullable=True))
    op.add_column("tenant", sa.Column("brand_accent_color", sa.Text(), nullable=True))
    op.create_check_constraint(op.f("ck_tenant_brand_primary_color"), "tenant", "brand_primary_color ~ '^#[0-9a-f]{6}$'")
    op.create_check_constraint(op.f("ck_tenant_brand_accent_color"), "tenant", "brand_accent_color ~ '^#[0-9a-f]{6}$'")

    jsonb = postgresql.JSONB(astext_type=sa.Text())
    for column in (
        sa.Column("allows_self_signup", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("menu", jsonb, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("social_links", jsonb, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("redirect_url", sa.Text(), nullable=True),
        sa.Column("group_redirect_urls", jsonb, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("redirect_domains", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    ):
        op.add_column("portal_settings", column)
    for name, sql in (
        ("menu", "jsonb_typeof(menu) = 'array'"),
        ("social_links", "jsonb_typeof(social_links) = 'object'"),
        ("group_redirect_urls", "jsonb_typeof(group_redirect_urls) = 'object'"),
        ("redirect_url", "redirect_url IS NULL OR redirect_url LIKE 'https://%'"),
    ):
        op.create_check_constraint(op.f(f"ck_portal_settings_{name}"), "portal_settings", sql)

    op.create_table(
        "portal_signup",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("phone_mobile", sa.Text(), nullable=True),
        sa.Column("birth_on", sa.Date(), nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        *_stamps(),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'superseded')", name=op.f("ck_portal_signup_status")),
        _fk("portal_signup", "location_id", "location"),
        _fk("portal_signup", "client_id", "client"),
        _tenant_fk("portal_signup"),
        sa.PrimaryKeyConstraint("id", name="pk_portal_signup"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_portal_signup_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "token_hash", name="uq_portal_signup_token_hash"),
    )
    op.create_index("ix_portal_signup_location_id", "portal_signup", ["tenant_id", "location_id"])
    op.create_index("ix_portal_signup_client_id", "portal_signup", ["tenant_id", "client_id"])
    op.create_index("ix_portal_signup_email", "portal_signup", ["tenant_id", "email"])
    enable_rls("portal_signup")

    op.create_table(
        "terms_acceptance",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("terms_version_id", sa.Text(), nullable=False),
        sa.Column("sale_kind", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        *_stamps(),
        sa.CheckConstraint(
            "sale_kind IN ('membership', 'package', 'program', 'rental')", name=op.f("ck_terms_acceptance_sale_kind")
        ),
        _fk("terms_acceptance", "client_id", "client"),
        _fk("terms_acceptance", "binding_id", "document_binding"),
        _tenant_fk("terms_acceptance"),
        sa.PrimaryKeyConstraint("id", name="pk_terms_acceptance"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_terms_acceptance_tenant_id_id"),
    )
    op.create_index("ix_terms_acceptance_client_id", "terms_acceptance", ["tenant_id", "client_id"])
    op.create_index("ix_terms_acceptance_binding_id", "terms_acceptance", ["tenant_id", "binding_id"])
    enable_rls("terms_acceptance")

    op.add_column(
        "registration_config",
        sa.Column("allows_guest_checkout", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("registration_checkout", sa.Column("guest_token_hash", sa.Text(), nullable=True))
    op.add_column("registration_checkout", sa.Column("guest_details", jsonb, nullable=True))
    op.drop_constraint(op.f("ck_registration_checkout_channel"), "registration_checkout", type_="check")
    op.create_check_constraint(op.f("ck_registration_checkout_channel"), "registration_checkout", _CHANNELS_NEW)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_registration_checkout_channel"), "registration_checkout", type_="check")
    op.create_check_constraint(op.f("ck_registration_checkout_channel"), "registration_checkout", _CHANNELS_OLD)
    op.drop_column("registration_checkout", "guest_details")
    op.drop_column("registration_checkout", "guest_token_hash")
    op.drop_column("registration_config", "allows_guest_checkout")
    op.drop_table("terms_acceptance")
    op.drop_table("portal_signup")
    for name in ("redirect_url", "group_redirect_urls", "social_links", "menu"):
        op.drop_constraint(op.f(f"ck_portal_settings_{name}"), "portal_settings", type_="check")
    for name in ("redirect_domains", "group_redirect_urls", "redirect_url", "social_links", "menu", "allows_self_signup"):
        op.drop_column("portal_settings", name)
    op.drop_constraint(op.f("ck_tenant_brand_accent_color"), "tenant", type_="check")
    op.drop_constraint(op.f("ck_tenant_brand_primary_color"), "tenant", type_="check")
    op.drop_column("tenant", "brand_accent_color")
    op.drop_column("tenant", "brand_primary_color")
