"""platform: subscription plans and tenant entitlements (Phase 8 T1: PLT-14, PLT-09, PLT-13)

The plan catalogue stays where 0001 put it: the global `subscription_plan` table (no RLS, fh_app SELECT only,
written here as fh_owner). It gains `features` and `limits`, and this migration upserts our three tiers, so
every environment has the same catalogue. `tenant_entitlement` is tenant data under forced RLS.

No backfill of `tenant.subscription_plan_id`: as fh_owner under FORCE ROW LEVEL SECURITY no tenant row is
visible here. A tenant without a plan resolves to `entitlements.default_plan` from config (`complete`), which
keeps today's behaviour. Downgrade keeps the plan rows, since tenants may reference them.

Revision ID: 1250
Revises: 1231
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = '1250'
down_revision = '1231'

# Our own tiers and numbers (assumption for the owner to confirm); a missing limit key is unlimited.
PLANS = [
    ("essentials", "Essentials", "{}", '{"locations": 1, "staff_users": 5, "clients": 500}'),
    ("growth", "Growth", "{api_access}", '{"locations": 3, "staff_users": 15, "clients": 2000, "app_users": 500}'),
    ("complete", "Complete", "{api_access,branded_app}", "{}"),
]


def upgrade() -> None:
    op.create_table('tenant_entitlement',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('limit_value', sa.Integer(), nullable=True),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('starts_on', sa.Date(), nullable=False),
    sa.Column('ends_on', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('addon', 'promo', 'flag', 'manual')", name=op.f('ck_tenant_entitlement_source')),
    sa.CheckConstraint('ends_on IS NULL OR ends_on >= starts_on', name=op.f('ck_tenant_entitlement_dates')),
    sa.CheckConstraint('limit_value IS NULL OR limit_value >= 0', name=op.f('ck_tenant_entitlement_limit_value')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_tenant_entitlement_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenant_entitlement')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_tenant_entitlement_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'key', 'source', 'starts_on', name='uq_tenant_entitlement')
    )
    enable_rls("tenant_entitlement")
    op.add_column('subscription_plan', sa.Column('features', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False))
    op.add_column('subscription_plan', sa.Column('limits', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False))
    for code, name, features, limits in PLANS:
        op.execute(
            sa.text(
                "INSERT INTO subscription_plan (code, name, features, limits) "
                "VALUES (:code, :name, CAST(:features AS text[]), CAST(:limits AS jsonb)) "
                "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, features = EXCLUDED.features, "
                "limits = EXCLUDED.limits, is_active = true"
            ).bindparams(code=code, name=name, features=features, limits=limits)
        )


def downgrade() -> None:
    op.drop_column('subscription_plan', 'limits')
    op.drop_column('subscription_plan', 'features')
    op.drop_table('tenant_entitlement')
