"""memberships and packages (build module 5): data-model-people sections 3 and 4.

Generated from the models, then completed by hand: enable_rls() per table (credit_ledger_entry is append-only),
the exclusion constraints Alembic cannot see (one live contract per owner, no overlapping freezes or suspensions
on a contract) and the SECURITY DEFINER function the data model sanctions for re-pointing the append-only credit
ledger on a client merge.

Revision ID: 0203
Revises: 0202
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = '0203'
down_revision = '0202'

TENANT_TABLES = (
    "membership_settings", "package_settings", "membership_type", "package_plan", "membership_plan",
    "membership_plan_addon", "package_series", "membership_contract", "membership_contract_addon",
    "membership_freeze", "membership_share", "membership_suspension", "membership_visit",
    "billing_schedule_period", "client_package", "package_share",
)
EXCLUSIONS = (
    # One live membership per owner at a time; a future-dated successor may queue behind it. Deferred, because a
    # freeze moves a contract and its upcoming successor in one transaction.
    "ALTER TABLE membership_contract ADD CONSTRAINT ex_membership_contract_term_overlap EXCLUDE USING gist "
    "(tenant_id WITH =, owner_client_id WITH =, daterange(start_on, end_on, '[]') WITH &&) "
    "WHERE (status IN ('upcoming', 'active', 'frozen', 'suspended')) DEFERRABLE INITIALLY DEFERRED",
    "ALTER TABLE membership_freeze ADD CONSTRAINT ex_membership_freeze_overlap EXCLUDE USING gist "
    "(tenant_id WITH =, membership_contract_id WITH =, during WITH &&) WHERE (removed_at IS NULL)",
    "ALTER TABLE membership_suspension ADD CONSTRAINT ex_membership_suspension_overlap EXCLUDE USING gist "
    "(tenant_id WITH =, membership_contract_id WITH =, during WITH &&) WHERE (removed_at IS NULL)",
)
# credit_ledger_entry grants fh_app SELECT, INSERT only; this function, owned by fh_owner, is the one path that
# changes a row (merge). FORCE ROW LEVEL SECURITY keeps it inside the caller's tenant.
REPOINT_LEDGER = """
CREATE FUNCTION app.repoint_credit_ledger_client(p_from uuid, p_to uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE moved integer;
BEGIN
    UPDATE credit_ledger_entry SET client_id = p_to
     WHERE client_id = p_from AND tenant_id = app.current_tenant_id();
    GET DIAGNOSTICS moved = ROW_COUNT;
    RETURN moved;
END $$
"""


def upgrade() -> None:
    op.create_table('membership_settings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('is_remark_required_on_freeze', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_remark_required_on_suspend', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_remark_required_on_cancel', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('payment_method_capture', sa.Text(), server_default=sa.text("'optional'"), nullable=False),
    sa.Column('online_card_save_mode', sa.Text(), server_default=sa.text("'ask'"), nullable=False),
    sa.Column('billing_lead_days', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_daily_visit_limit_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('freeze_resume_invoice_mode', sa.Text(), server_default=sa.text("'per_period'"), nullable=False),
    sa.Column('is_addon_package_cancelled_with_contract', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("freeze_resume_invoice_mode IN ('per_period', 'single', 'deferred')", name=op.f('ck_membership_settings_freeze_resume_invoice_mode')),
    sa.CheckConstraint("online_card_save_mode IN ('always', 'when_nothing_due', 'ask')", name=op.f('ck_membership_settings_online_card_save_mode')),
    sa.CheckConstraint("payment_method_capture IN ('hidden', 'optional', 'required')", name=op.f('ck_membership_settings_payment_method_capture')),
    sa.CheckConstraint('billing_lead_days BETWEEN 0 AND 60', name=op.f('ck_membership_settings_billing_lead_days')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_settings_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_settings')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_settings_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', name='uq_membership_settings_tenant')
    )
    op.create_table('package_settings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('is_late_cancel_charged', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_no_show_charged', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_account_credit_applied_by_default', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('expiry_notice_days', sa.Integer(), server_default=sa.text('7'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('expiry_notice_days BETWEEN 0 AND 365', name=op.f('ck_package_settings_expiry_notice_days')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_package_settings_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_package_settings')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_package_settings_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', name='uq_package_settings_tenant')
    )
    op.create_table('membership_type',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_membership_type_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_type_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_type')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_type_tenant_id_id'))
    )
    op.create_index(op.f('ix_membership_type_revenue_category_id'), 'membership_type', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_index('uq_membership_type_name', 'membership_type', ['tenant_id', sa.literal_column('lower(name)')], unique=True)
    op.create_table('package_plan',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), server_default=sa.text("'standard'"), nullable=False),
    sa.Column('reservation_type_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('invoice_description', sa.Text(), nullable=True),
    sa.Column('internal_remarks', sa.Text(), nullable=True),
    sa.Column('session_mode', sa.Text(), nullable=False),
    sa.Column('session_count', sa.Integer(), nullable=True),
    sa.Column('min_session_count', sa.Integer(), nullable=True),
    sa.Column('max_session_count', sa.Integer(), nullable=True),
    sa.Column('pricing_category', sa.Text(), server_default=sa.text("'paid'"), nullable=False),
    sa.Column('is_complimentary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('fee_minor', sa.Integer(), nullable=True),
    sa.Column('fee_basis', sa.Text(), nullable=True),
    sa.Column('start_rule', sa.Text(), server_default=sa.text("'sale_date'"), nullable=False),
    sa.Column('fixed_start_on', sa.Date(), nullable=True),
    sa.Column('validity_count', sa.Integer(), nullable=True),
    sa.Column('validity_unit', sa.Text(), nullable=True),
    sa.Column('allows_booking_after_expiry', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('auto_renew_lead_count', sa.Integer(), nullable=True),
    sa.Column('auto_renew_lead_unit', sa.Text(), nullable=True),
    sa.Column('renewal_target', sa.Text(), server_default=sa.text("'same_terms'"), nullable=False),
    sa.Column('renews_as_plan_id', sa.Uuid(), nullable=True),
    sa.Column('renewal_threshold_count', sa.Integer(), nullable=True),
    sa.Column('is_auto_renew_on_threshold', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('share_mode', sa.Text(), server_default=sa.text("'none'"), nullable=False),
    sa.Column('recurrence_unit', sa.Text(), nullable=True),
    sa.Column('recurrence_interval_count', sa.Integer(), nullable=True),
    sa.Column('recurrence_occurrences_count', sa.Integer(), nullable=True),
    sa.Column('is_series_auto_renew', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('default_invoice_mode', sa.Text(), server_default=sa.text("'ask'"), nullable=False),
    sa.Column('is_autopay_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('online_sale_mode', sa.Text(), server_default=sa.text("'off'"), nullable=False),
    sa.Column('is_members_only_online', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_members_only_at_desk', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('discount_minor', sa.Integer(), nullable=True),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'recurring') = (recurrence_unit IS NOT NULL AND recurrence_interval_count >= 1 AND recurrence_occurrences_count >= 1) AND (kind <> 'recurring' OR session_mode <> 'range')", name=op.f('ck_package_plan_recurrence')),
    sa.CheckConstraint("(pricing_category = 'free' AND fee_minor IS NULL AND fee_basis IS NULL) OR (pricing_category = 'paid' AND fee_minor >= 0 AND fee_basis IS NOT NULL AND revenue_category_id IS NOT NULL)", name=op.f('ck_package_plan_pricing')),
    sa.CheckConstraint("(renewal_target = 'plan') = (renews_as_plan_id IS NOT NULL)", name=op.f('ck_package_plan_renewal')),
    sa.CheckConstraint("(session_mode = 'fixed') = (session_count IS NOT NULL) AND (session_mode = 'range') = (min_session_count IS NOT NULL AND max_session_count IS NOT NULL) AND (session_count IS NULL OR session_count >= 1) AND (min_session_count IS NULL OR (min_session_count >= 1 AND max_session_count >= min_session_count))", name=op.f('ck_package_plan_sessions')),
    sa.CheckConstraint("(start_rule = 'fixed_date') = (fixed_start_on IS NOT NULL)", name=op.f('ck_package_plan_start')),
    sa.CheckConstraint("auto_renew_lead_unit IN ('day', 'week', 'month', 'year')", name=op.f('ck_package_plan_auto_renew_lead_unit')),
    sa.CheckConstraint("default_invoice_mode IN ('ask', 'single', 'per_period', 'deferred')", name=op.f('ck_package_plan_default_invoice_mode')),
    sa.CheckConstraint("fee_basis IN ('per_session', 'per_package')", name=op.f('ck_package_plan_fee_basis')),
    sa.CheckConstraint("kind IN ('standard', 'recurring')", name=op.f('ck_package_plan_kind')),
    sa.CheckConstraint("online_sale_mode IN ('off', 'balance_allowed', 'paid_in_full')", name=op.f('ck_package_plan_online_sale_mode')),
    sa.CheckConstraint("pricing_category IN ('paid', 'free')", name=op.f('ck_package_plan_pricing_category')),
    sa.CheckConstraint("recurrence_unit IN ('day', 'week', 'month', 'year')", name=op.f('ck_package_plan_recurrence_unit')),
    sa.CheckConstraint("renewal_target IN ('same_terms', 'plan')", name=op.f('ck_package_plan_renewal_target')),
    sa.CheckConstraint("session_mode <> 'single' OR fee_basis IS NULL OR fee_basis = 'per_session'", name=op.f('ck_package_plan_single_basis')),
    sa.CheckConstraint("session_mode IN ('single', 'fixed', 'range', 'unlimited')", name=op.f('ck_package_plan_session_mode')),
    sa.CheckConstraint("share_mode IN ('none', 'all_related')", name=op.f('ck_package_plan_share_mode')),
    sa.CheckConstraint("start_rule IN ('sale_date', 'fixed_date')", name=op.f('ck_package_plan_start_rule')),
    sa.CheckConstraint("validity_unit IN ('day', 'week', 'month', 'year')", name=op.f('ck_package_plan_validity_unit')),
    sa.CheckConstraint('(auto_renew_lead_count IS NULL) = (auto_renew_lead_unit IS NULL) AND auto_renew_lead_count >= 0', name=op.f('ck_package_plan_auto_renew_lead')),
    sa.CheckConstraint('(validity_count IS NULL) = (validity_unit IS NULL) AND validity_count >= 1', name=op.f('ck_package_plan_validity')),
    sa.CheckConstraint('discount_pct BETWEEN 0 AND 100 AND discount_minor >= 0', name=op.f('ck_package_plan_discount_range')),
    sa.CheckConstraint('num_nonnulls(discount_pct, discount_minor) <= 1', name=op.f('ck_package_plan_discount')),
    sa.CheckConstraint('renewal_threshold_count >= 0', name=op.f('ck_package_plan_renewal_threshold_count')),
    sa.ForeignKeyConstraint(['tenant_id', 'renews_as_plan_id'], ['package_plan.tenant_id', 'package_plan.id'], name=op.f('fk_package_plan_renews_as_plan_id_package_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_package_plan_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_package_plan_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_package_plan')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_package_plan_tenant_id_id'))
    )
    op.create_index('ix_package_plan_online', 'package_plan', ['tenant_id'], unique=False, postgresql_where=sa.text("online_sale_mode <> 'off' AND is_active"))
    op.create_index(op.f('ix_package_plan_renews_as_plan_id'), 'package_plan', ['tenant_id', 'renews_as_plan_id'], unique=False)
    op.create_index('ix_package_plan_reservation_type', 'package_plan', ['tenant_id', 'reservation_type_id', 'is_active'], unique=False)
    op.create_index(op.f('ix_package_plan_revenue_category_id'), 'package_plan', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_table('membership_plan',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('membership_type_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('invoice_description', sa.String(length=100), nullable=True),
    sa.Column('fixed_start_on', sa.Date(), nullable=True),
    sa.Column('billing_interval_unit', sa.Text(), server_default=sa.text("'month'"), nullable=False),
    sa.Column('billing_interval_count', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('billing_occurrences_count', sa.Integer(), nullable=False),
    sa.Column('auto_renew_lead_count', sa.Integer(), nullable=True),
    sa.Column('auto_renew_lead_unit', sa.Text(), nullable=True),
    sa.Column('renewal_target', sa.Text(), server_default=sa.text("'same_terms'"), nullable=False),
    sa.Column('renews_as_plan_id', sa.Uuid(), nullable=True),
    sa.Column('max_visits_count', sa.Integer(), nullable=True),
    sa.Column('initiation_fee_minor', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('term_fee_minor', sa.Integer(), nullable=False),
    sa.Column('payment_due_day', sa.SmallInteger(), nullable=True),
    sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('discount_minor', sa.Integer(), nullable=True),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=True),
    sa.Column('default_invoice_mode', sa.Text(), server_default=sa.text("'ask'"), nullable=False),
    sa.Column('is_autopay_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_sold_online', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('proration_mode', sa.Text(), server_default=sa.text("'none'"), nullable=False),
    sa.Column('proration_tail', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(proration_mode = 'to_month_start') = (proration_tail IS NOT NULL)", name=op.f('ck_membership_plan_proration')),
    sa.CheckConstraint("(renewal_target = 'plan') = (renews_as_plan_id IS NOT NULL)", name=op.f('ck_membership_plan_renewal')),
    sa.CheckConstraint("auto_renew_lead_unit IN ('day', 'week', 'month', 'year')", name=op.f('ck_membership_plan_auto_renew_lead_unit')),
    sa.CheckConstraint("billing_interval_unit IN ('day', 'week', 'month', 'year')", name=op.f('ck_membership_plan_billing_interval_unit')),
    sa.CheckConstraint("default_invoice_mode IN ('ask', 'per_period', 'single')", name=op.f('ck_membership_plan_default_invoice_mode')),
    sa.CheckConstraint("proration_mode IN ('none', 'to_month_start', 'seller_choice')", name=op.f('ck_membership_plan_proration_mode')),
    sa.CheckConstraint("proration_tail IN ('extend_last', 'drop_last', 'prorate_last')", name=op.f('ck_membership_plan_proration_tail')),
    sa.CheckConstraint("renewal_target IN ('same_terms', 'plan')", name=op.f('ck_membership_plan_renewal_target')),
    sa.CheckConstraint('(auto_renew_lead_count IS NULL) = (auto_renew_lead_unit IS NULL) AND auto_renew_lead_count >= 0', name=op.f('ck_membership_plan_auto_renew_lead')),
    sa.CheckConstraint('billing_interval_count >= 1', name=op.f('ck_membership_plan_billing_interval_count')),
    sa.CheckConstraint('billing_occurrences_count >= 1', name=op.f('ck_membership_plan_billing_occurrences_count')),
    sa.CheckConstraint('discount_pct BETWEEN 0 AND 100 AND discount_minor >= 0', name=op.f('ck_membership_plan_discount_range')),
    sa.CheckConstraint('initiation_fee_minor >= 0', name=op.f('ck_membership_plan_initiation_fee_minor')),
    sa.CheckConstraint('max_visits_count >= 1', name=op.f('ck_membership_plan_max_visits_count')),
    sa.CheckConstraint('num_nonnulls(discount_pct, discount_minor) <= 1', name=op.f('ck_membership_plan_discount')),
    sa.CheckConstraint('payment_due_day BETWEEN 1 AND 31', name=op.f('ck_membership_plan_payment_due_day')),
    sa.CheckConstraint('term_fee_minor >= 0', name=op.f('ck_membership_plan_term_fee_minor')),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_type_id'], ['membership_type.tenant_id', 'membership_type.id'], name=op.f('fk_membership_plan_membership_type_id_membership_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'renews_as_plan_id'], ['membership_plan.tenant_id', 'membership_plan.id'], name=op.f('fk_membership_plan_renews_as_plan_id_membership_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_membership_plan_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_plan_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_plan')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_plan_tenant_id_id'))
    )
    op.create_index('ix_membership_plan_online', 'membership_plan', ['tenant_id'], unique=False, postgresql_where=sa.text('is_sold_online AND is_active'))
    op.create_index(op.f('ix_membership_plan_renews_as_plan_id'), 'membership_plan', ['tenant_id', 'renews_as_plan_id'], unique=False)
    op.create_index(op.f('ix_membership_plan_revenue_category_id'), 'membership_plan', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_index('ix_membership_plan_type', 'membership_plan', ['tenant_id', 'membership_type_id', 'sort_order'], unique=False)
    op.create_table('membership_plan_addon',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('membership_plan_id', sa.Uuid(), nullable=False),
    sa.Column('addon_kind', sa.Text(), nullable=False),
    sa.Column('package_plan_id', sa.Uuid(), nullable=True),
    sa.Column('quantity', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(addon_kind = 'package_plan') = (package_plan_id IS NOT NULL)", name=op.f('ck_membership_plan_addon_target')),
    sa.CheckConstraint("addon_kind IN ('package_plan', 'catalog_item')", name=op.f('ck_membership_plan_addon_addon_kind')),
    sa.CheckConstraint('quantity >= 1', name=op.f('ck_membership_plan_addon_quantity')),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_plan_id'], ['membership_plan.tenant_id', 'membership_plan.id'], name=op.f('fk_membership_plan_addon_membership_plan_id_membership_plan'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'package_plan_id'], ['package_plan.tenant_id', 'package_plan.id'], name=op.f('fk_membership_plan_addon_package_plan_id_package_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_plan_addon_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_plan_addon')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_plan_addon_tenant_id_id'))
    )
    op.create_index(op.f('ix_membership_plan_addon_membership_plan_id'), 'membership_plan_addon', ['tenant_id', 'membership_plan_id'], unique=False)
    op.create_index(op.f('ix_membership_plan_addon_package_plan_id'), 'membership_plan_addon', ['tenant_id', 'package_plan_id'], unique=False)
    op.create_table('package_series',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('owner_client_id', sa.Uuid(), nullable=False),
    sa.Column('package_plan_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('occurrences_total_count', sa.Integer(), nullable=False),
    sa.Column('occurrences_generated_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('next_period_start_on', sa.Date(), nullable=True),
    sa.Column('invoice_mode', sa.Text(), nullable=False),
    sa.Column('is_auto_renew', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("invoice_mode IN ('single', 'per_period', 'deferred')", name=op.f('ck_package_series_invoice_mode')),
    sa.CheckConstraint("status IN ('active', 'completed', 'cancelled')", name=op.f('ck_package_series_status')),
    sa.CheckConstraint('occurrences_generated_count <= occurrences_total_count', name=op.f('ck_package_series_occurrences')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_package_series_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'owner_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_package_series_owner_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'package_plan_id'], ['package_plan.tenant_id', 'package_plan.id'], name=op.f('fk_package_series_package_plan_id_package_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_package_series_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_package_series')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_package_series_tenant_id_id'))
    )
    op.create_index('ix_package_series_due', 'package_series', ['tenant_id', 'next_period_start_on'], unique=False, postgresql_where=sa.text("status = 'active'"))
    op.create_index(op.f('ix_package_series_location_id'), 'package_series', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_package_series_owner_client_id'), 'package_series', ['tenant_id', 'owner_client_id'], unique=False)
    op.create_index(op.f('ix_package_series_package_plan_id'), 'package_series', ['tenant_id', 'package_plan_id'], unique=False)
    op.create_table('membership_contract',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('owner_client_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('membership_plan_id', sa.Uuid(), nullable=True),
    sa.Column('membership_type_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('invoice_description', sa.String(length=100), nullable=True),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=False),
    sa.Column('start_on', sa.Date(), nullable=False),
    sa.Column('end_on', sa.Date(), nullable=False),
    sa.Column('original_end_on', sa.Date(), nullable=False),
    sa.Column('billing_interval_unit', sa.Text(), nullable=False),
    sa.Column('billing_interval_count', sa.Integer(), nullable=False),
    sa.Column('billing_occurrences_count', sa.Integer(), nullable=False),
    sa.Column('term_fee_minor', sa.Integer(), nullable=False),
    sa.Column('initiation_fee_minor', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('discount_minor', sa.Integer(), nullable=True),
    sa.Column('payment_due_day', sa.SmallInteger(), nullable=True),
    sa.Column('revenue_on', sa.Date(), nullable=True),
    sa.Column('max_visits_count', sa.Integer(), nullable=True),
    sa.Column('visits_used_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_autopay', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('invoice_mode', sa.Text(), nullable=False),
    sa.Column('is_prorated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('proration_tail', sa.Text(), nullable=True),
    sa.Column('is_auto_renew', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('auto_renew_lead_count', sa.Integer(), nullable=True),
    sa.Column('auto_renew_lead_unit', sa.Text(), nullable=True),
    sa.Column('renew_on', sa.Date(), nullable=True),
    sa.Column('renewal_target', sa.Text(), server_default=sa.text("'same_terms'"), nullable=False),
    sa.Column('renews_as_plan_id', sa.Uuid(), nullable=True),
    sa.Column('renewal_discount_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('renewal_discount_minor', sa.Integer(), nullable=True),
    sa.Column('renewal_description', sa.Text(), nullable=True),
    sa.Column('renewal_remark', sa.Text(), nullable=True),
    sa.Column('auto_renew_disabled_by', sa.Text(), nullable=True),
    sa.Column('auto_renew_disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('previous_contract_id', sa.Uuid(), nullable=True),
    sa.Column('sold_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('referred_by_client_id', sa.Uuid(), nullable=True),
    sa.Column('sales_channel', sa.Text(), server_default=sa.text("'staff'"), nullable=False),
    sa.Column('internal_notes', sa.Text(), nullable=True),
    sa.Column('client_document_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_on', sa.Date(), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('cancel_remarks', sa.Text(), nullable=True),
    sa.Column('cancelled_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_on_before_cancel', sa.Date(), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(renewal_target = 'plan') = (renews_as_plan_id IS NOT NULL)", name=op.f('ck_membership_contract_renewal')),
    sa.CheckConstraint("(status = 'cancelled') = (cancelled_on IS NOT NULL)", name=op.f('ck_membership_contract_cancelled_on')),
    sa.CheckConstraint("auto_renew_disabled_by IN ('staff', 'client', 'freeze')", name=op.f('ck_membership_contract_auto_renew_disabled_by')),
    sa.CheckConstraint("auto_renew_lead_unit IN ('day', 'week', 'month', 'year')", name=op.f('ck_membership_contract_auto_renew_lead_unit')),
    sa.CheckConstraint("billing_interval_unit IN ('day', 'week', 'month', 'year')", name=op.f('ck_membership_contract_billing_interval_unit')),
    sa.CheckConstraint("cancel_reason IN ('voluntary', 'upgrade', 'downgrade', 'administrative_error', 'other')", name=op.f('ck_membership_contract_cancel_reason')),
    sa.CheckConstraint("invoice_mode IN ('per_period', 'single', 'deferred', 'none')", name=op.f('ck_membership_contract_invoice_mode')),
    sa.CheckConstraint("proration_tail IN ('extend_last', 'drop_last', 'prorate_last')", name=op.f('ck_membership_contract_proration_tail')),
    sa.CheckConstraint("renewal_target IN ('same_terms', 'plan')", name=op.f('ck_membership_contract_renewal_target')),
    sa.CheckConstraint("sales_channel IN ('staff', 'portal', 'mobile', 'pos', 'api', 'renewal', 'import')", name=op.f('ck_membership_contract_sales_channel')),
    sa.CheckConstraint("status IN ('upcoming', 'active', 'frozen', 'suspended', 'expired', 'cancelled')", name=op.f('ck_membership_contract_status')),
    sa.CheckConstraint('end_on >= start_on', name=op.f('ck_membership_contract_term')),
    sa.CheckConstraint('num_nonnulls(discount_pct, discount_minor) <= 1', name=op.f('ck_membership_contract_discount')),
    sa.CheckConstraint('num_nonnulls(renewal_discount_pct, renewal_discount_minor) <= 1', name=op.f('ck_membership_contract_renewal_discount')),
    sa.CheckConstraint('term_fee_minor >= 0 AND initiation_fee_minor >= 0', name=op.f('ck_membership_contract_fees')),
    sa.CheckConstraint('visits_used_count >= 0', name=op.f('ck_membership_contract_visits')),
    sa.ForeignKeyConstraint(['tenant_id', 'cancelled_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_membership_contract_cancelled_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_document_id'], ['client_document.tenant_id', 'client_document.id'], name=op.f('fk_membership_contract_client_document_id_client_document'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_membership_contract_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_plan_id'], ['membership_plan.tenant_id', 'membership_plan.id'], name=op.f('fk_membership_contract_membership_plan_id_membership_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_type_id'], ['membership_type.tenant_id', 'membership_type.id'], name=op.f('fk_membership_contract_membership_type_id_membership_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'owner_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_membership_contract_owner_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'previous_contract_id'], ['membership_contract.tenant_id', 'membership_contract.id'], name=op.f('fk_membership_contract_previous_contract_id_membership_contract'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'referred_by_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_membership_contract_referred_by_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'renews_as_plan_id'], ['membership_plan.tenant_id', 'membership_plan.id'], name=op.f('fk_membership_contract_renews_as_plan_id_membership_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_membership_contract_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'sold_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_membership_contract_sold_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_contract_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_contract')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_contract_tenant_id_id'))
    )
    op.create_index(op.f('ix_membership_contract_cancelled_by_staff_user_id'), 'membership_contract', ['tenant_id', 'cancelled_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_membership_contract_client_document_id'), 'membership_contract', ['tenant_id', 'client_document_id'], unique=False)
    op.create_index('ix_membership_contract_end_due', 'membership_contract', ['tenant_id', 'end_on'], unique=False, postgresql_where=sa.text("status IN ('active', 'suspended')"))
    op.create_index('ix_membership_contract_location', 'membership_contract', ['tenant_id', 'location_id', 'status', 'id'], unique=False)
    op.create_index(op.f('ix_membership_contract_membership_plan_id'), 'membership_contract', ['tenant_id', 'membership_plan_id'], unique=False)
    op.create_index('ix_membership_contract_owner', 'membership_contract', ['tenant_id', 'owner_client_id', sa.literal_column('start_on DESC')], unique=False)
    op.create_index(op.f('ix_membership_contract_referred_by_client_id'), 'membership_contract', ['tenant_id', 'referred_by_client_id'], unique=False)
    op.create_index('ix_membership_contract_renew_due', 'membership_contract', ['tenant_id', 'renew_on'], unique=False, postgresql_where=sa.text("is_auto_renew AND status IN ('active', 'frozen', 'suspended')"))
    op.create_index(op.f('ix_membership_contract_renews_as_plan_id'), 'membership_contract', ['tenant_id', 'renews_as_plan_id'], unique=False)
    op.create_index(op.f('ix_membership_contract_revenue_category_id'), 'membership_contract', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_index(op.f('ix_membership_contract_sold_by_staff_user_id'), 'membership_contract', ['tenant_id', 'sold_by_staff_user_id'], unique=False)
    op.create_index('ix_membership_contract_start_due', 'membership_contract', ['tenant_id', 'start_on'], unique=False, postgresql_where=sa.text("status = 'upcoming'"))
    op.create_index('ix_membership_contract_status', 'membership_contract', ['tenant_id', 'status', 'end_on'], unique=False)
    op.create_index('ix_membership_contract_type', 'membership_contract', ['tenant_id', 'membership_type_id', 'status'], unique=False)
    op.create_index('uq_membership_contract_previous', 'membership_contract', ['tenant_id', 'previous_contract_id'], unique=True, postgresql_where=sa.text('previous_contract_id IS NOT NULL'))
    op.create_table('membership_contract_addon',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('membership_contract_id', sa.Uuid(), nullable=False),
    sa.Column('addon_kind', sa.Text(), nullable=False),
    sa.Column('package_plan_id', sa.Uuid(), nullable=True),
    sa.Column('quantity', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(addon_kind = 'package_plan') = (package_plan_id IS NOT NULL)", name=op.f('ck_membership_contract_addon_target')),
    sa.CheckConstraint("addon_kind IN ('package_plan', 'catalog_item')", name=op.f('ck_membership_contract_addon_addon_kind')),
    sa.CheckConstraint('quantity >= 1', name=op.f('ck_membership_contract_addon_quantity')),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_contract_id'], ['membership_contract.tenant_id', 'membership_contract.id'], name=op.f('fk_membership_contract_addon_membership_contract_id_membership_contract'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'package_plan_id'], ['package_plan.tenant_id', 'package_plan.id'], name=op.f('fk_membership_contract_addon_package_plan_id_package_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_contract_addon_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_contract_addon')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_contract_addon_tenant_id_id'))
    )
    op.create_index(op.f('ix_membership_contract_addon_membership_contract_id'), 'membership_contract_addon', ['tenant_id', 'membership_contract_id'], unique=False)
    op.create_index(op.f('ix_membership_contract_addon_package_plan_id'), 'membership_contract_addon', ['tenant_id', 'package_plan_id'], unique=False)
    op.create_table('membership_freeze',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('membership_contract_id', sa.Uuid(), nullable=False),
    sa.Column('during', postgresql.DATERANGE(), nullable=False),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('extended_days_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('resume_invoice_mode', sa.Text(), nullable=True),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('removed_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('removal_remarks', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("resume_invoice_mode IN ('per_period', 'single', 'deferred')", name=op.f('ck_membership_freeze_resume_invoice_mode')),
    sa.CheckConstraint('NOT isempty(during) AND lower(during) IS NOT NULL', name=op.f('ck_membership_freeze_during')),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_membership_freeze_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_contract_id'], ['membership_contract.tenant_id', 'membership_contract.id'], name=op.f('fk_membership_freeze_membership_contract_id_membership_contract'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'removed_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_membership_freeze_removed_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_freeze_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_freeze')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_freeze_tenant_id_id'))
    )
    op.create_index(op.f('ix_membership_freeze_created_by_staff_user_id'), 'membership_freeze', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_index('ix_membership_freeze_end_due', 'membership_freeze', ['tenant_id', sa.literal_column('upper(during)')], unique=False, postgresql_where=sa.text('removed_at IS NULL'))
    op.create_index(op.f('ix_membership_freeze_membership_contract_id'), 'membership_freeze', ['tenant_id', 'membership_contract_id'], unique=False)
    op.create_index(op.f('ix_membership_freeze_removed_by_staff_user_id'), 'membership_freeze', ['tenant_id', 'removed_by_staff_user_id'], unique=False)
    op.create_table('membership_share',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('membership_contract_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('origin', sa.Text(), server_default=sa.text("'manual'"), nullable=False),
    sa.Column('added_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("origin IN ('manual', 'carried_from_previous')", name=op.f('ck_membership_share_origin')),
    sa.ForeignKeyConstraint(['tenant_id', 'added_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_membership_share_added_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_membership_share_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_contract_id'], ['membership_contract.tenant_id', 'membership_contract.id'], name=op.f('fk_membership_share_membership_contract_id_membership_contract'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'revoked_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_membership_share_revoked_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_share_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_share')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_share_tenant_id_id'))
    )
    op.create_index(op.f('ix_membership_share_added_by_staff_user_id'), 'membership_share', ['tenant_id', 'added_by_staff_user_id'], unique=False)
    op.create_index('ix_membership_share_client', 'membership_share', ['tenant_id', 'client_id'], unique=False, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_index(op.f('ix_membership_share_membership_contract_id'), 'membership_share', ['tenant_id', 'membership_contract_id'], unique=False)
    op.create_index(op.f('ix_membership_share_revoked_by_staff_user_id'), 'membership_share', ['tenant_id', 'revoked_by_staff_user_id'], unique=False)
    op.create_index('uq_membership_share_active', 'membership_share', ['tenant_id', 'membership_contract_id', 'client_id'], unique=True, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('membership_suspension',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('membership_contract_id', sa.Uuid(), nullable=False),
    sa.Column('during', postgresql.DATERANGE(), nullable=False),
    sa.Column('fee_minor', sa.Integer(), nullable=True),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('removed_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('removal_remarks', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('NOT isempty(during) AND lower(during) IS NOT NULL', name=op.f('ck_membership_suspension_during')),
    sa.CheckConstraint('fee_minor > 0', name=op.f('ck_membership_suspension_fee_minor')),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_membership_suspension_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_contract_id'], ['membership_contract.tenant_id', 'membership_contract.id'], name=op.f('fk_membership_suspension_membership_contract_id_membership_contract'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'removed_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_membership_suspension_removed_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_suspension_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_suspension')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_suspension_tenant_id_id'))
    )
    op.create_index(op.f('ix_membership_suspension_created_by_staff_user_id'), 'membership_suspension', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_membership_suspension_membership_contract_id'), 'membership_suspension', ['tenant_id', 'membership_contract_id'], unique=False)
    op.create_index(op.f('ix_membership_suspension_removed_by_staff_user_id'), 'membership_suspension', ['tenant_id', 'removed_by_staff_user_id'], unique=False)
    op.create_table('membership_visit',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('membership_contract_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('check_in_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('visited_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('local_on', sa.Date(), nullable=False),
    sa.Column('is_counted', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_membership_visit_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_membership_visit_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_contract_id'], ['membership_contract.tenant_id', 'membership_contract.id'], name=op.f('fk_membership_visit_membership_contract_id_membership_contract'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_membership_visit_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_membership_visit')),
    sa.UniqueConstraint('tenant_id', 'check_in_id', name='uq_membership_visit_check_in'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_membership_visit_tenant_id_id'))
    )
    op.create_index(op.f('ix_membership_visit_client_id'), 'membership_visit', ['tenant_id', 'client_id'], unique=False)
    op.create_index('ix_membership_visit_contract_day', 'membership_visit', ['tenant_id', 'membership_contract_id', 'local_on'], unique=False)
    op.create_index(op.f('ix_membership_visit_location_id'), 'membership_visit', ['tenant_id', 'location_id'], unique=False)
    op.create_table('billing_schedule_period',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('membership_contract_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('sequence_number', sa.Integer(), nullable=False),
    sa.Column('service_during', postgresql.DATERANGE(), nullable=True),
    sa.Column('due_on', sa.Date(), nullable=False),
    sa.Column('bill_on', sa.Date(), nullable=False),
    sa.Column('revenue_on', sa.Date(), nullable=False),
    sa.Column('list_amount_minor', sa.Integer(), nullable=False),
    sa.Column('amount_minor', sa.Integer(), nullable=False),
    sa.Column('is_prorated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('suspension_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'scheduled'"), nullable=False),
    sa.Column('charge_id', sa.Uuid(), nullable=True),
    sa.Column('charge_sequence', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('billed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('withheld_by_freeze_id', sa.Uuid(), nullable=True),
    sa.Column('pre_freeze', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('cancelled_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'dues') <= (service_during IS NOT NULL)", name=op.f('ck_billing_schedule_period_service_during')),
    sa.CheckConstraint("(status = 'withheld') = (withheld_by_freeze_id IS NOT NULL)", name=op.f('ck_billing_schedule_period_withheld')),
    sa.CheckConstraint("cancelled_reason IN ('contract_cancelled', 'suspension_ended')", name=op.f('ck_billing_schedule_period_cancelled_reason')),
    sa.CheckConstraint("kind IN ('dues', 'initiation', 'suspension_fee', 'addon_item')", name=op.f('ck_billing_schedule_period_kind')),
    sa.CheckConstraint("status <> 'billed' OR charge_id IS NOT NULL", name=op.f('ck_billing_schedule_period_charge')),
    sa.CheckConstraint("status IN ('scheduled', 'billed', 'withheld', 'cancelled')", name=op.f('ck_billing_schedule_period_status')),
    sa.CheckConstraint('amount_minor >= 0', name=op.f('ck_billing_schedule_period_amount_minor')),
    sa.ForeignKeyConstraint(['tenant_id', 'charge_id'], ['charge.tenant_id', 'charge.id'], name=op.f('fk_billing_schedule_period_charge_id_charge'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'membership_contract_id'], ['membership_contract.tenant_id', 'membership_contract.id'], name=op.f('fk_billing_schedule_period_membership_contract_id_membership_contract'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'suspension_id'], ['membership_suspension.tenant_id', 'membership_suspension.id'], name=op.f('fk_billing_schedule_period_suspension_id_membership_suspension'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'withheld_by_freeze_id'], ['membership_freeze.tenant_id', 'membership_freeze.id'], name=op.f('fk_billing_schedule_period_withheld_by_freeze_id_membership_freeze'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_billing_schedule_period_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_schedule_period')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_billing_schedule_period_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'membership_contract_id', 'kind', 'sequence_number', name=op.f('uq_billing_schedule_period_tenant_id_membership_contract_id_kind_sequence_number'))
    )
    op.create_index('ix_billing_schedule_period_bill_due', 'billing_schedule_period', ['tenant_id', 'bill_on'], unique=False, postgresql_where=sa.text("status = 'scheduled'"))
    op.create_index('ix_billing_schedule_period_contract', 'billing_schedule_period', ['tenant_id', 'membership_contract_id', 'due_on'], unique=False)
    op.create_index('ix_billing_schedule_period_revenue', 'billing_schedule_period', ['tenant_id', 'revenue_on'], unique=False)
    op.create_index(op.f('ix_billing_schedule_period_suspension_id'), 'billing_schedule_period', ['tenant_id', 'suspension_id'], unique=False)
    op.create_index(op.f('ix_billing_schedule_period_withheld_by_freeze_id'), 'billing_schedule_period', ['tenant_id', 'withheld_by_freeze_id'], unique=False)
    op.create_index('uq_billing_schedule_period_charge', 'billing_schedule_period', ['tenant_id', 'charge_id'], unique=True, postgresql_where=sa.text('charge_id IS NOT NULL'))
    op.create_table('client_package',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('owner_client_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('package_plan_id', sa.Uuid(), nullable=True),
    sa.Column('package_series_id', sa.Uuid(), nullable=True),
    sa.Column('series_sequence_number', sa.Integer(), nullable=True),
    sa.Column('reservation_type_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('invoice_description', sa.Text(), nullable=True),
    sa.Column('internal_remarks', sa.Text(), nullable=True),
    sa.Column('is_unlimited', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('sessions_granted_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('sessions_reserved_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('sessions_consumed_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('sessions_forfeited_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('valid_during', postgresql.DATERANGE(), nullable=False),
    sa.Column('allows_booking_after_expiry', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('price_minor', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('fee_basis', sa.Text(), nullable=True),
    sa.Column('unit_price_minor', sa.Integer(), nullable=True),
    sa.Column('is_complimentary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=True),
    sa.Column('invoice_mode', sa.Text(), server_default=sa.text("'single'"), nullable=False),
    sa.Column('charge_id', sa.Uuid(), nullable=True),
    sa.Column('is_autopay', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('share_mode', sa.Text(), server_default=sa.text("'none'"), nullable=False),
    sa.Column('is_auto_renew', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('auto_renew_lead_count', sa.Integer(), nullable=True),
    sa.Column('auto_renew_lead_unit', sa.Text(), nullable=True),
    sa.Column('renew_on', sa.Date(), nullable=True),
    sa.Column('renewal_target', sa.Text(), server_default=sa.text("'same_terms'"), nullable=False),
    sa.Column('renews_as_plan_id', sa.Uuid(), nullable=True),
    sa.Column('renewal_threshold_count', sa.Integer(), nullable=True),
    sa.Column('is_auto_renew_on_threshold', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('renewal_flagged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('auto_renew_disabled_by', sa.Text(), nullable=True),
    sa.Column('previous_package_id', sa.Uuid(), nullable=True),
    sa.Column('source_contract_id', sa.Uuid(), nullable=True),
    sa.Column('source_contract_addon_id', sa.Uuid(), nullable=True),
    sa.Column('sold_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('sales_channel', sa.Text(), server_default=sa.text("'staff'"), nullable=False),
    sa.Column('client_document_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('removal_mode', sa.Text(), nullable=True),
    sa.Column('removed_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(renewal_target = 'plan') = (renews_as_plan_id IS NOT NULL)", name=op.f('ck_client_package_renewal')),
    sa.CheckConstraint("(status = 'removed') = (removed_at IS NOT NULL)", name=op.f('ck_client_package_removed')),
    sa.CheckConstraint("auto_renew_disabled_by IN ('staff', 'client')", name=op.f('ck_client_package_auto_renew_disabled_by')),
    sa.CheckConstraint("auto_renew_lead_unit IN ('day', 'week', 'month', 'year')", name=op.f('ck_client_package_auto_renew_lead_unit')),
    sa.CheckConstraint("fee_basis IN ('per_session', 'per_package')", name=op.f('ck_client_package_fee_basis')),
    sa.CheckConstraint("invoice_mode IN ('single', 'deferred', 'none')", name=op.f('ck_client_package_invoice_mode')),
    sa.CheckConstraint("removal_mode IN ('billing_reversed', 'billing_kept')", name=op.f('ck_client_package_removal_mode')),
    sa.CheckConstraint("renewal_target IN ('same_terms', 'plan')", name=op.f('ck_client_package_renewal_target')),
    sa.CheckConstraint("sales_channel IN ('staff', 'portal', 'mobile', 'pos', 'api', 'renewal', 'membership_addon', 'import')", name=op.f('ck_client_package_sales_channel')),
    sa.CheckConstraint("share_mode IN ('none', 'all_related', 'explicit')", name=op.f('ck_client_package_share_mode')),
    sa.CheckConstraint("status IN ('active', 'exhausted', 'expired', 'removed')", name=op.f('ck_client_package_status')),
    sa.CheckConstraint('NOT isempty(valid_during) AND lower(valid_during) IS NOT NULL', name=op.f('ck_client_package_valid')),
    sa.CheckConstraint('price_minor >= 0', name=op.f('ck_client_package_price_minor')),
    sa.CheckConstraint('sessions_reserved_count >= 0 AND sessions_consumed_count >= 0 AND sessions_forfeited_count >= 0 AND (is_unlimited OR sessions_granted_count - sessions_reserved_count - sessions_consumed_count - sessions_forfeited_count >= 0)', name=op.f('ck_client_package_balance')),
    sa.ForeignKeyConstraint(['tenant_id', 'charge_id'], ['charge.tenant_id', 'charge.id'], name=op.f('fk_client_package_charge_id_charge'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_document_id'], ['client_document.tenant_id', 'client_document.id'], name=op.f('fk_client_package_client_document_id_client_document'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_client_package_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'owner_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_package_owner_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'package_plan_id'], ['package_plan.tenant_id', 'package_plan.id'], name=op.f('fk_client_package_package_plan_id_package_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'package_series_id'], ['package_series.tenant_id', 'package_series.id'], name=op.f('fk_client_package_package_series_id_package_series'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'previous_package_id'], ['client_package.tenant_id', 'client_package.id'], name=op.f('fk_client_package_previous_package_id_client_package'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'removed_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_package_removed_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'renews_as_plan_id'], ['package_plan.tenant_id', 'package_plan.id'], name=op.f('fk_client_package_renews_as_plan_id_package_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_client_package_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'sold_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_package_sold_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'source_contract_addon_id'], ['membership_contract_addon.tenant_id', 'membership_contract_addon.id'], name=op.f('fk_client_package_source_contract_addon_id_membership_contract_addon'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'source_contract_id'], ['membership_contract.tenant_id', 'membership_contract.id'], name=op.f('fk_client_package_source_contract_id_membership_contract'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_package_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_package')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_package_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'package_series_id', 'series_sequence_number', name=op.f('uq_client_package_tenant_id_package_series_id_series_sequence_number'))
    )
    op.create_index(op.f('ix_client_package_charge_id'), 'client_package', ['tenant_id', 'charge_id'], unique=False)
    op.create_index(op.f('ix_client_package_client_document_id'), 'client_package', ['tenant_id', 'client_document_id'], unique=False)
    op.create_index('ix_client_package_contract', 'client_package', ['tenant_id', 'source_contract_id'], unique=False, postgresql_where=sa.text('source_contract_id IS NOT NULL'))
    op.create_index('ix_client_package_expiry_due', 'client_package', ['tenant_id', sa.literal_column('upper(valid_during)')], unique=False, postgresql_where=sa.text("status IN ('active', 'exhausted')"))
    op.create_index('ix_client_package_location', 'client_package', ['tenant_id', 'location_id', 'id'], unique=False)
    op.create_index('ix_client_package_owner', 'client_package', ['tenant_id', 'owner_client_id', 'status', 'id'], unique=False)
    op.create_index(op.f('ix_client_package_package_plan_id'), 'client_package', ['tenant_id', 'package_plan_id'], unique=False)
    op.create_index(op.f('ix_client_package_removed_by_staff_user_id'), 'client_package', ['tenant_id', 'removed_by_staff_user_id'], unique=False)
    op.create_index('ix_client_package_renew_due', 'client_package', ['tenant_id', 'renew_on'], unique=False, postgresql_where=sa.text("is_auto_renew AND status IN ('active', 'exhausted')"))
    op.create_index(op.f('ix_client_package_renews_as_plan_id'), 'client_package', ['tenant_id', 'renews_as_plan_id'], unique=False)
    op.create_index(op.f('ix_client_package_revenue_category_id'), 'client_package', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_index(op.f('ix_client_package_sold_by_staff_user_id'), 'client_package', ['tenant_id', 'sold_by_staff_user_id'], unique=False)
    op.create_index('ix_client_package_spendable', 'client_package', ['tenant_id', 'owner_client_id', 'reservation_type_id'], unique=False, postgresql_where=sa.text("status = 'active'"))
    op.create_index('uq_client_package_contract_addon', 'client_package', ['tenant_id', 'source_contract_addon_id'], unique=True, postgresql_where=sa.text('source_contract_addon_id IS NOT NULL'))
    op.create_index('uq_client_package_previous', 'client_package', ['tenant_id', 'previous_package_id'], unique=True, postgresql_where=sa.text('previous_package_id IS NOT NULL'))
    op.create_table('credit_ledger_entry',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_package_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('entry_type', sa.Text(), nullable=False),
    sa.Column('granted_delta', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('reserved_delta', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('consumed_delta', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('forfeited_delta', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('source_type', sa.Text(), nullable=True),
    sa.Column('source_id', sa.Uuid(), nullable=True),
    sa.Column('idempotency_key', sa.Text(), nullable=False),
    sa.Column('actor_type', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("CASE entry_type WHEN 'grant' THEN granted_delta > 0 AND reserved_delta = 0 AND consumed_delta = 0 AND forfeited_delta = 0 WHEN 'reserve' THEN granted_delta = 0 AND reserved_delta = 1 AND consumed_delta = 0 AND forfeited_delta = 0 WHEN 'release' THEN granted_delta = 0 AND reserved_delta = -1 AND consumed_delta = 0 AND forfeited_delta = 0 WHEN 'consume' THEN granted_delta = 0 AND reserved_delta = -1 AND consumed_delta = 1 AND forfeited_delta = 0 WHEN 'restore' THEN granted_delta = 0 AND reserved_delta = 0 AND consumed_delta = -1 AND forfeited_delta = 0 WHEN 'forfeit' THEN granted_delta = 0 AND reserved_delta = 0 AND consumed_delta = 0 AND forfeited_delta > 0 ELSE granted_delta <> 0 AND reserved_delta = 0 AND consumed_delta = 0 AND forfeited_delta = 0 END", name=op.f('ck_credit_ledger_entry_shape')),
    sa.CheckConstraint("actor_type IN ('staff', 'client', 'system')", name=op.f('ck_credit_ledger_entry_actor_type')),
    sa.CheckConstraint("entry_type IN ('grant', 'reserve', 'release', 'consume', 'restore', 'forfeit', 'adjust')", name=op.f('ck_credit_ledger_entry_entry_type')),
    sa.CheckConstraint("reason IN ('purchase', 'addon', 'renewal', 'booking', 'cancellation_early', 'cancellation_late', 'attendance', 'no_show', 'expiry', 'removal', 'staff_adjustment', 'merge')", name=op.f('ck_credit_ledger_entry_reason')),
    sa.CheckConstraint("source_type IN ('enrollment', 'booking')", name=op.f('ck_credit_ledger_entry_source_type')),
    sa.CheckConstraint('(source_type IS NULL) = (source_id IS NULL)', name=op.f('ck_credit_ledger_entry_source')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_credit_ledger_entry_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_package_id'], ['client_package.tenant_id', 'client_package.id'], name=op.f('fk_credit_ledger_entry_client_package_id_client_package'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_credit_ledger_entry_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_credit_ledger_entry')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_credit_ledger_entry_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'idempotency_key', name='uq_credit_ledger_entry_key')
    )
    op.create_index(op.f('ix_credit_ledger_entry_client_id'), 'credit_ledger_entry', ['tenant_id', 'client_id'], unique=False)
    op.create_index('ix_credit_ledger_entry_package', 'credit_ledger_entry', ['tenant_id', 'client_package_id', 'occurred_at'], unique=False)
    op.create_index('ix_credit_ledger_entry_source', 'credit_ledger_entry', ['tenant_id', 'source_type', 'source_id'], unique=False, postgresql_where=sa.text('source_id IS NOT NULL'))
    op.create_table('package_share',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_package_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('origin', sa.Text(), server_default=sa.text("'manual'"), nullable=False),
    sa.Column('added_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("origin IN ('manual', 'plan_preset', 'carried_from_previous')", name=op.f('ck_package_share_origin')),
    sa.ForeignKeyConstraint(['tenant_id', 'added_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_package_share_added_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_package_share_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_package_id'], ['client_package.tenant_id', 'client_package.id'], name=op.f('fk_package_share_client_package_id_client_package'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_package_share_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_package_share')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_package_share_tenant_id_id'))
    )
    op.create_index(op.f('ix_package_share_added_by_staff_user_id'), 'package_share', ['tenant_id', 'added_by_staff_user_id'], unique=False)
    op.create_index('ix_package_share_client', 'package_share', ['tenant_id', 'client_id'], unique=False, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_index(op.f('ix_package_share_client_package_id'), 'package_share', ['tenant_id', 'client_package_id'], unique=False)
    op.create_index('uq_package_share_active', 'package_share', ['tenant_id', 'client_package_id', 'client_id'], unique=True, postgresql_where=sa.text('revoked_at IS NULL'))
    for table in TENANT_TABLES:
        enable_rls(table)
    enable_rls("credit_ledger_entry", append_only=True)
    for statement in EXCLUSIONS:
        op.execute(statement)
    op.execute(REPOINT_LEDGER)
    op.execute("REVOKE ALL ON FUNCTION app.repoint_credit_ledger_client(uuid, uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.repoint_credit_ledger_client(uuid, uuid) TO fh_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.repoint_credit_ledger_client(uuid, uuid)")
    op.drop_index('uq_package_share_active', table_name='package_share', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index(op.f('ix_package_share_client_package_id'), table_name='package_share')
    op.drop_index('ix_package_share_client', table_name='package_share', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index(op.f('ix_package_share_added_by_staff_user_id'), table_name='package_share')
    op.drop_table('package_share')
    op.drop_index('ix_credit_ledger_entry_source', table_name='credit_ledger_entry', postgresql_where=sa.text('source_id IS NOT NULL'))
    op.drop_index('ix_credit_ledger_entry_package', table_name='credit_ledger_entry')
    op.drop_index(op.f('ix_credit_ledger_entry_client_id'), table_name='credit_ledger_entry')
    op.drop_table('credit_ledger_entry')
    op.drop_index('uq_client_package_previous', table_name='client_package', postgresql_where=sa.text('previous_package_id IS NOT NULL'))
    op.drop_index('uq_client_package_contract_addon', table_name='client_package', postgresql_where=sa.text('source_contract_addon_id IS NOT NULL'))
    op.drop_index('ix_client_package_spendable', table_name='client_package', postgresql_where=sa.text("status = 'active'"))
    op.drop_index(op.f('ix_client_package_sold_by_staff_user_id'), table_name='client_package')
    op.drop_index(op.f('ix_client_package_revenue_category_id'), table_name='client_package')
    op.drop_index(op.f('ix_client_package_renews_as_plan_id'), table_name='client_package')
    op.drop_index('ix_client_package_renew_due', table_name='client_package', postgresql_where=sa.text("is_auto_renew AND status IN ('active', 'exhausted')"))
    op.drop_index(op.f('ix_client_package_removed_by_staff_user_id'), table_name='client_package')
    op.drop_index(op.f('ix_client_package_package_plan_id'), table_name='client_package')
    op.drop_index('ix_client_package_owner', table_name='client_package')
    op.drop_index('ix_client_package_location', table_name='client_package')
    op.drop_index('ix_client_package_expiry_due', table_name='client_package', postgresql_where=sa.text("status IN ('active', 'exhausted')"))
    op.drop_index('ix_client_package_contract', table_name='client_package', postgresql_where=sa.text('source_contract_id IS NOT NULL'))
    op.drop_index(op.f('ix_client_package_client_document_id'), table_name='client_package')
    op.drop_index(op.f('ix_client_package_charge_id'), table_name='client_package')
    op.drop_table('client_package')
    op.drop_index('uq_billing_schedule_period_charge', table_name='billing_schedule_period', postgresql_where=sa.text('charge_id IS NOT NULL'))
    op.drop_index(op.f('ix_billing_schedule_period_withheld_by_freeze_id'), table_name='billing_schedule_period')
    op.drop_index(op.f('ix_billing_schedule_period_suspension_id'), table_name='billing_schedule_period')
    op.drop_index('ix_billing_schedule_period_revenue', table_name='billing_schedule_period')
    op.drop_index('ix_billing_schedule_period_contract', table_name='billing_schedule_period')
    op.drop_index('ix_billing_schedule_period_bill_due', table_name='billing_schedule_period', postgresql_where=sa.text("status = 'scheduled'"))
    op.drop_table('billing_schedule_period')
    op.drop_index(op.f('ix_membership_visit_location_id'), table_name='membership_visit')
    op.drop_index('ix_membership_visit_contract_day', table_name='membership_visit')
    op.drop_index(op.f('ix_membership_visit_client_id'), table_name='membership_visit')
    op.drop_table('membership_visit')
    op.drop_index(op.f('ix_membership_suspension_removed_by_staff_user_id'), table_name='membership_suspension')
    op.drop_index(op.f('ix_membership_suspension_membership_contract_id'), table_name='membership_suspension')
    op.drop_index(op.f('ix_membership_suspension_created_by_staff_user_id'), table_name='membership_suspension')
    op.drop_table('membership_suspension')
    op.drop_index('uq_membership_share_active', table_name='membership_share', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index(op.f('ix_membership_share_revoked_by_staff_user_id'), table_name='membership_share')
    op.drop_index(op.f('ix_membership_share_membership_contract_id'), table_name='membership_share')
    op.drop_index('ix_membership_share_client', table_name='membership_share', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index(op.f('ix_membership_share_added_by_staff_user_id'), table_name='membership_share')
    op.drop_table('membership_share')
    op.drop_index(op.f('ix_membership_freeze_removed_by_staff_user_id'), table_name='membership_freeze')
    op.drop_index(op.f('ix_membership_freeze_membership_contract_id'), table_name='membership_freeze')
    op.drop_index('ix_membership_freeze_end_due', table_name='membership_freeze', postgresql_where=sa.text('removed_at IS NULL'))
    op.drop_index(op.f('ix_membership_freeze_created_by_staff_user_id'), table_name='membership_freeze')
    op.drop_table('membership_freeze')
    op.drop_index(op.f('ix_membership_contract_addon_package_plan_id'), table_name='membership_contract_addon')
    op.drop_index(op.f('ix_membership_contract_addon_membership_contract_id'), table_name='membership_contract_addon')
    op.drop_table('membership_contract_addon')
    op.drop_index('uq_membership_contract_previous', table_name='membership_contract', postgresql_where=sa.text('previous_contract_id IS NOT NULL'))
    op.drop_index('ix_membership_contract_type', table_name='membership_contract')
    op.drop_index('ix_membership_contract_status', table_name='membership_contract')
    op.drop_index('ix_membership_contract_start_due', table_name='membership_contract', postgresql_where=sa.text("status = 'upcoming'"))
    op.drop_index(op.f('ix_membership_contract_sold_by_staff_user_id'), table_name='membership_contract')
    op.drop_index(op.f('ix_membership_contract_revenue_category_id'), table_name='membership_contract')
    op.drop_index(op.f('ix_membership_contract_renews_as_plan_id'), table_name='membership_contract')
    op.drop_index('ix_membership_contract_renew_due', table_name='membership_contract', postgresql_where=sa.text("is_auto_renew AND status IN ('active', 'frozen', 'suspended')"))
    op.drop_index(op.f('ix_membership_contract_referred_by_client_id'), table_name='membership_contract')
    op.drop_index('ix_membership_contract_owner', table_name='membership_contract')
    op.drop_index(op.f('ix_membership_contract_membership_plan_id'), table_name='membership_contract')
    op.drop_index('ix_membership_contract_location', table_name='membership_contract')
    op.drop_index('ix_membership_contract_end_due', table_name='membership_contract', postgresql_where=sa.text("status IN ('active', 'suspended')"))
    op.drop_index(op.f('ix_membership_contract_client_document_id'), table_name='membership_contract')
    op.drop_index(op.f('ix_membership_contract_cancelled_by_staff_user_id'), table_name='membership_contract')
    op.drop_table('membership_contract')
    op.drop_index(op.f('ix_package_series_package_plan_id'), table_name='package_series')
    op.drop_index(op.f('ix_package_series_owner_client_id'), table_name='package_series')
    op.drop_index(op.f('ix_package_series_location_id'), table_name='package_series')
    op.drop_index('ix_package_series_due', table_name='package_series', postgresql_where=sa.text("status = 'active'"))
    op.drop_table('package_series')
    op.drop_index(op.f('ix_membership_plan_addon_package_plan_id'), table_name='membership_plan_addon')
    op.drop_index(op.f('ix_membership_plan_addon_membership_plan_id'), table_name='membership_plan_addon')
    op.drop_table('membership_plan_addon')
    op.drop_index('ix_membership_plan_type', table_name='membership_plan')
    op.drop_index(op.f('ix_membership_plan_revenue_category_id'), table_name='membership_plan')
    op.drop_index(op.f('ix_membership_plan_renews_as_plan_id'), table_name='membership_plan')
    op.drop_index('ix_membership_plan_online', table_name='membership_plan', postgresql_where=sa.text('is_sold_online AND is_active'))
    op.drop_table('membership_plan')
    op.drop_index(op.f('ix_package_plan_revenue_category_id'), table_name='package_plan')
    op.drop_index('ix_package_plan_reservation_type', table_name='package_plan')
    op.drop_index(op.f('ix_package_plan_renews_as_plan_id'), table_name='package_plan')
    op.drop_index('ix_package_plan_online', table_name='package_plan', postgresql_where=sa.text("online_sale_mode <> 'off' AND is_active"))
    op.drop_table('package_plan')
    op.drop_index('uq_membership_type_name', table_name='membership_type')
    op.drop_index(op.f('ix_membership_type_revenue_category_id'), table_name='membership_type')
    op.drop_table('membership_type')
    op.drop_table('package_settings')
    op.drop_table('membership_settings')
