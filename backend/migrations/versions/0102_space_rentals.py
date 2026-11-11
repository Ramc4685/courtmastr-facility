"""build module 3 (lane space): rentals. Rental types (with their resource and plan allow-lists), rates with
rules and default taxes, rental occurrences and their priced charge lines, rental plans with purchases and the
append-only balance ledger, and the read models rpt_rental_booking and rpt_rental_plan_sale.
`rental_plan_share` and `locker_lease` are not created (RNT-10, RNT-17, RNT-18 are not built; see README).

Generated from the models, then completed by hand: plain types, the deferred FK of the type/rate cycle,
enable_rls() per table and the views.

Revision ID: 0102
Revises: 0101
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "0102"
down_revision = "0101"

TENANT_TABLES = (
    "rental_type", "rental_plan", "rental_rate", "rental_rate_rule", "rental_rate_tax", "rental_type_rental_plan",
    "rental_type_resource", "rental_booking_charge", "rental_plan_purchase", "rental_booking",
    "rental_booking_charge_item", "rental_party",
)
VIEWS = {
    "rpt_rental_booking": """
        SELECT rb.tenant_id, rb.id AS rental_booking_id, rb.location_id, rb.booking_id, rb.rental_type_id,
               rt.name AS rental_type_name, rt.revenue_category_id, rb.charge_state, rb.booked_via, rb.starts_at,
               rb.ends_at, rb.cancelled_at, round(extract(epoch FROM rb.ends_at - rb.starts_at) / 3600.0, 2) AS hours
        FROM rental_booking rb JOIN rental_type rt ON rt.tenant_id = rb.tenant_id AND rt.id = rb.rental_type_id""",
    "rpt_rental_plan_sale": """
        SELECT p.tenant_id, p.id AS rental_plan_purchase_id, p.location_id, p.client_id, p.rental_plan_id,
               rp.name AS rental_plan_name, p.price_minor, p.sold_via, (p.created_at AT TIME ZONE l.time_zone)::date
               AS sold_on, p.status, p.quantity_total, p.balance, p.charge_id
        FROM rental_plan_purchase p
        JOIN rental_plan rp ON rp.tenant_id = p.tenant_id AND rp.id = p.rental_plan_id
        JOIN location l ON l.tenant_id = p.tenant_id AND l.id = p.location_id""",
}


def upgrade() -> None:
    op.create_table('rental_type',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=False),
    sa.Column('color', sa.Text(), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('buffer_before_min', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('buffer_after_min', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('access', sa.Text(), server_default=sa.text("'staff_only'"), nullable=False),
    sa.Column('online_rental_rate_id', sa.Uuid(), nullable=True),
    sa.Column('eligibility', sa.Text(), server_default=sa.text("'everyone'"), nullable=False),
    sa.Column('online_payment_mode', sa.Text(), server_default=sa.text("'pay_in_full'"), nullable=False),
    sa.Column('min_lead_min', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('default_length_min', sa.Integer(), nullable=True),
    sa.Column('min_length_min', sa.Integer(), server_default=sa.text('60'), nullable=False),
    sa.Column('max_length_min', sa.Integer(), nullable=True),
    sa.Column('slot_granularity_min', sa.SmallInteger(), server_default=sa.text('60'), nullable=False),
    sa.Column('online_description', sa.Text(), nullable=True),
    sa.Column('deposit_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('cancel_cutoff_hours', sa.Integer(), nullable=True),
    sa.Column('late_cancel_fee_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("access = 'staff_only' OR online_rental_rate_id IS NOT NULL", name=op.f('ck_rental_type_online_rate')),
    sa.CheckConstraint("access IN ('staff_only', 'self_service')", name=op.f('ck_rental_type_access')),
    sa.CheckConstraint("color IS NULL OR color ~ '^#[0-9a-f]{6}$'", name=op.f('ck_rental_type_color')),
    sa.CheckConstraint("eligibility IN ('everyone', 'active_members', 'paid_up_members')", name=op.f('ck_rental_type_eligibility')),
    sa.CheckConstraint("online_payment_mode IN ('pay_in_full', 'pay_later')", name=op.f('ck_rental_type_online_payment_mode')),
    sa.CheckConstraint('(cancel_cutoff_hours IS NULL OR cancel_cutoff_hours > 0) AND (late_cancel_fee_pct IS NULL OR (cancel_cutoff_hours IS NOT NULL AND late_cancel_fee_pct > 0 AND late_cancel_fee_pct <= 100))', name=op.f('ck_rental_type_cancel_policy')),
    sa.CheckConstraint('buffer_before_min BETWEEN 0 AND 240 AND buffer_after_min BETWEEN 0 AND 240', name=op.f('ck_rental_type_buffers')),
    sa.CheckConstraint('deposit_pct IS NULL OR (deposit_pct > 0 AND deposit_pct <= 100)', name=op.f('ck_rental_type_deposit')),
    sa.CheckConstraint('min_lead_min >= 0', name=op.f('ck_rental_type_lead')),
    sa.CheckConstraint('min_length_min > 0 AND (max_length_min IS NULL OR max_length_min >= min_length_min) AND (default_length_min IS NULL OR default_length_min >= min_length_min)', name=op.f('ck_rental_type_lengths')),
    sa.CheckConstraint('slot_granularity_min IN (15, 30, 60)', name=op.f('ck_rental_type_granularity')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_rental_type_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_rental_type_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_type_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_type')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_type_tenant_id_id'))
    )
    op.create_index(op.f('ix_rental_type_location_id'), 'rental_type', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_rental_type_revenue_category_id'), 'rental_type', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_index('uq_rental_type_name', 'rental_type', ['tenant_id', 'location_id', 'name'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('rental_plan',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('rental_type_id', sa.Uuid(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('is_unlimited', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('price_minor', sa.Integer(), nullable=False),
    sa.Column('member_price_minor', sa.Integer(), nullable=True),
    sa.Column('is_flat_rate', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=False),
    sa.Column('internal_description', sa.Text(), nullable=True),
    sa.Column('client_description', sa.Text(), nullable=True),
    sa.Column('is_members_only', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_sold_online', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('start_mode', sa.Text(), server_default=sa.text("'sale_date'"), nullable=False),
    sa.Column('fixed_starts_on', sa.Date(), nullable=True),
    sa.Column('validity_days', sa.Integer(), nullable=True),
    sa.Column('fixed_expires_on', sa.Date(), nullable=True),
    sa.Column('is_auto_renew', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_autopay_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('default_invoice_routing', sa.Text(), server_default=sa.text("'new_single'"), nullable=False),
    sa.Column('is_shareable', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(start_mode = 'fixed_date') = (fixed_starts_on IS NOT NULL)", name=op.f('ck_rental_plan_start')),
    sa.CheckConstraint("default_invoice_routing IN ('new_single', 'new_per_line', 'date_based', 'existing_open', 'cart')", name=op.f('ck_rental_plan_default_invoice_routing')),
    sa.CheckConstraint("default_invoice_routing NOT IN ('date_based', 'existing_open')", name=op.f('ck_rental_plan_routing')),
    sa.CheckConstraint("model IN ('per_hour', 'per_occurrence')", name=op.f('ck_rental_plan_model')),
    sa.CheckConstraint("start_mode IN ('sale_date', 'fixed_date')", name=op.f('ck_rental_plan_start_mode')),
    sa.CheckConstraint("status IN ('active', 'archived')", name=op.f('ck_rental_plan_status')),
    sa.CheckConstraint('NOT is_auto_renew OR validity_days IS NOT NULL', name=op.f('ck_rental_plan_renew')),
    sa.CheckConstraint('is_flat_rate OR NOT is_unlimited', name=op.f('ck_rental_plan_unit_price')),
    sa.CheckConstraint('is_unlimited = (quantity IS NULL) AND (quantity IS NULL OR quantity > 0)', name=op.f('ck_rental_plan_quantity')),
    sa.CheckConstraint('num_nonnulls(validity_days, fixed_expires_on) <= 1', name=op.f('ck_rental_plan_expiry')),
    sa.CheckConstraint('price_minor >= 0 AND (member_price_minor IS NULL OR member_price_minor >= 0)', name=op.f('ck_rental_plan_price')),
    sa.CheckConstraint('validity_days IS NULL OR validity_days > 0', name=op.f('ck_rental_plan_validity')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_rental_plan_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_type_id'], ['rental_type.tenant_id', 'rental_type.id'], name=op.f('fk_rental_plan_rental_type_id_rental_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_rental_plan_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_plan_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_plan')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_plan_tenant_id_id'))
    )
    op.create_index(op.f('ix_rental_plan_location_id'), 'rental_plan', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_rental_plan_rental_type_id'), 'rental_plan', ['tenant_id', 'rental_type_id'], unique=False)
    op.create_index(op.f('ix_rental_plan_revenue_category_id'), 'rental_plan', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_index('uq_rental_plan_name', 'rental_plan', ['tenant_id', 'location_id', 'name'], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_table('rental_rate',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('rental_type_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('internal_note', sa.Text(), nullable=True),
    sa.Column('amount_minor', sa.Integer(), nullable=False),
    sa.Column('member_amount_minor', sa.Integer(), nullable=True),
    sa.Column('basis', sa.Text(), nullable=False),
    sa.Column('multi_resource_mode', sa.Text(), server_default=sa.text("'per_resource'"), nullable=False),
    sa.Column('line_grouping', sa.Text(), server_default=sa.text("'combined'"), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("basis IN ('per_hour', 'per_occurrence', 'flat')", name=op.f('ck_rental_rate_basis')),
    sa.CheckConstraint("line_grouping IN ('combined', 'per_resource', 'per_occurrence', 'per_resource_occurrence')", name=op.f('ck_rental_rate_line_grouping')),
    sa.CheckConstraint("multi_resource_mode IN ('once', 'per_resource')", name=op.f('ck_rental_rate_multi_resource_mode')),
    sa.CheckConstraint('amount_minor >= 0 AND (member_amount_minor IS NULL OR member_amount_minor >= 0)', name=op.f('ck_rental_rate_amounts')),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_type_id'], ['rental_type.tenant_id', 'rental_type.id'], name=op.f('fk_rental_rate_rental_type_id_rental_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_rate_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_rate')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_rate_tenant_id_id'))
    )
    op.create_index('uq_rental_rate_name', 'rental_rate', ['tenant_id', 'rental_type_id', 'name'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_foreign_key(op.f('fk_rental_type_online_rental_rate_id_rental_rate'), 'rental_type', 'rental_rate', ['tenant_id', 'online_rental_rate_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_table('rental_rate_rule',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('rental_rate_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=True),
    sa.Column('end_time', sa.Time(), nullable=True),
    sa.Column('starts_on', sa.Date(), nullable=True),
    sa.Column('ends_on', sa.Date(), nullable=True),
    sa.Column('weekdays', postgresql.ARRAY(sa.SmallInteger()), nullable=True),
    sa.Column('membership_type_id', sa.Uuid(), nullable=True),
    sa.Column('amount_minor', sa.Integer(), nullable=True),
    sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('discount_minor', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'rate' AND amount_minor >= 0 AND discount_pct IS NULL AND discount_minor IS NULL) OR (kind = 'discount' AND amount_minor IS NULL AND num_nonnulls(discount_pct, discount_minor) = 1 AND (discount_pct IS NULL OR (discount_pct > 0 AND discount_pct <= 100)) AND (discount_minor IS NULL OR discount_minor > 0))", name=op.f('ck_rental_rate_rule_value')),
    sa.CheckConstraint("kind IN ('rate', 'discount')", name=op.f('ck_rental_rate_rule_kind')),
    sa.CheckConstraint('(start_time IS NULL) = (end_time IS NULL) AND (start_time IS NULL OR end_time > start_time)', name=op.f('ck_rental_rate_rule_band')),
    sa.CheckConstraint('starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on', name=op.f('ck_rental_rate_rule_dates')),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_rate_id'], ['rental_rate.tenant_id', 'rental_rate.id'], name=op.f('fk_rental_rate_rule_rental_rate_id_rental_rate'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_rate_rule_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_rate_rule')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_rate_rule_tenant_id_id'))
    )
    op.create_index('ix_rental_rate_rule_order', 'rental_rate_rule', ['tenant_id', 'rental_rate_id', 'sort_order'], unique=False)
    op.create_table('rental_rate_tax',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('rental_rate_id', sa.Uuid(), nullable=False),
    sa.Column('tax_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_rate_id'], ['rental_rate.tenant_id', 'rental_rate.id'], name=op.f('fk_rental_rate_tax_rental_rate_id_rental_rate'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'tax_id'], ['tax.tenant_id', 'tax.id'], name=op.f('fk_rental_rate_tax_tax_id_tax'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_rate_tax_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_rate_tax')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_rate_tax_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'rental_rate_id', 'tax_id', name='uq_rental_rate_tax')
    )
    op.create_index(op.f('ix_rental_rate_tax_tax_id'), 'rental_rate_tax', ['tenant_id', 'tax_id'], unique=False)
    op.create_table('rental_type_rental_plan',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('rental_type_id', sa.Uuid(), nullable=False),
    sa.Column('rental_plan_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_plan_id'], ['rental_plan.tenant_id', 'rental_plan.id'], name=op.f('fk_rental_type_rental_plan_rental_plan_id_rental_plan'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_type_id'], ['rental_type.tenant_id', 'rental_type.id'], name=op.f('fk_rental_type_rental_plan_rental_type_id_rental_type'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_type_rental_plan_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_type_rental_plan')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_type_rental_plan_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'rental_type_id', 'rental_plan_id', name='uq_rental_type_rental_plan')
    )
    op.create_index(op.f('ix_rental_type_rental_plan_rental_plan_id'), 'rental_type_rental_plan', ['tenant_id', 'rental_plan_id'], unique=False)
    op.create_table('rental_type_resource',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('rental_type_id', sa.Uuid(), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_type_id'], ['rental_type.tenant_id', 'rental_type.id'], name=op.f('fk_rental_type_resource_rental_type_id_rental_type'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'resource_id'], ['resource.tenant_id', 'resource.id'], name=op.f('fk_rental_type_resource_resource_id_resource'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_type_resource_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_type_resource')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_type_resource_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'rental_type_id', 'resource_id', name='uq_rental_type_resource')
    )
    op.create_index(op.f('ix_rental_type_resource_resource_id'), 'rental_type_resource', ['tenant_id', 'resource_id'], unique=False)
    op.create_table('rental_booking_charge',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('rental_rate_id', sa.Uuid(), nullable=True),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('basis', sa.Text(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('unit_amount_minor', sa.Integer(), nullable=False),
    sa.Column('discount_minor', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('amount_minor', sa.Integer(), nullable=False),
    sa.Column('revenue_on', sa.Date(), nullable=False),
    sa.Column('invoice_routing', sa.Text(), nullable=False),
    sa.Column('routing_period', sa.Text(), nullable=True),
    sa.Column('charge_id', sa.Uuid(), nullable=False),
    sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(invoice_routing = 'date_based') = (routing_period IS NOT NULL)", name=op.f('ck_rental_booking_charge_period')),
    sa.CheckConstraint("basis IN ('per_hour', 'per_occurrence', 'flat')", name=op.f('ck_rental_booking_charge_basis')),
    sa.CheckConstraint("invoice_routing IN ('new_single', 'new_per_line', 'date_based', 'existing_open', 'cart')", name=op.f('ck_rental_booking_charge_invoice_routing')),
    sa.CheckConstraint("routing_period IN ('week', 'month')", name=op.f('ck_rental_booking_charge_routing_period')),
    sa.CheckConstraint('unit_amount_minor >= 0 AND discount_minor >= 0 AND amount_minor >= 0', name=op.f('ck_rental_booking_charge_amounts')),
    sa.ForeignKeyConstraint(['tenant_id', 'charge_id'], ['charge.tenant_id', 'charge.id'], name=op.f('fk_rental_booking_charge_charge_id_charge'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_rental_booking_charge_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_rental_booking_charge_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_rate_id'], ['rental_rate.tenant_id', 'rental_rate.id'], name=op.f('fk_rental_booking_charge_rental_rate_id_rental_rate'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_booking_charge_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_booking_charge')),
    sa.UniqueConstraint('tenant_id', 'charge_id', name='uq_rental_booking_charge_charge'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_booking_charge_tenant_id_id'))
    )
    op.create_index('ix_rental_booking_charge_client', 'rental_booking_charge', ['tenant_id', 'client_id', 'id'], unique=False)
    op.create_index(op.f('ix_rental_booking_charge_location_id'), 'rental_booking_charge', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_rental_booking_charge_rental_rate_id'), 'rental_booking_charge', ['tenant_id', 'rental_rate_id'], unique=False)
    op.create_table('rental_plan_purchase',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('rental_plan_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('quantity_total', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('balance', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('price_minor', sa.Integer(), nullable=False),
    sa.Column('charge_id', sa.Uuid(), nullable=True),
    sa.Column('sold_via', sa.Text(), nullable=False),
    sa.Column('sold_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('starts_on', sa.Date(), nullable=False),
    sa.Column('expires_on', sa.Date(), nullable=True),
    sa.Column('is_auto_renew', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('renewed_from_purchase_id', sa.Uuid(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_mode', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'cancelled') = (cancelled_at IS NOT NULL)", name=op.f('ck_rental_plan_purchase_cancel')),
    sa.CheckConstraint("cancel_mode IN ('reverse_billing', 'keep_billing')", name=op.f('ck_rental_plan_purchase_cancel_mode')),
    sa.CheckConstraint("model IN ('per_hour', 'per_occurrence')", name=op.f('ck_rental_plan_purchase_model')),
    sa.CheckConstraint("sold_via IN ('staff', 'portal', 'mobile')", name=op.f('ck_rental_plan_purchase_sold_via')),
    sa.CheckConstraint("status IN ('pending', 'active', 'expired', 'cancelled')", name=op.f('ck_rental_plan_purchase_status')),
    sa.CheckConstraint('balance IS NULL OR balance >= 0', name=op.f('ck_rental_plan_purchase_balance')),
    sa.CheckConstraint('price_minor >= 0', name=op.f('ck_rental_plan_purchase_price')),
    sa.ForeignKeyConstraint(['tenant_id', 'charge_id'], ['charge.tenant_id', 'charge.id'], name=op.f('fk_rental_plan_purchase_charge_id_charge'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_rental_plan_purchase_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_rental_plan_purchase_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'renewed_from_purchase_id'], ['rental_plan_purchase.tenant_id', 'rental_plan_purchase.id'], name=op.f('fk_rental_plan_purchase_renewed_from_purchase_id_rental_plan_purchase'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_plan_id'], ['rental_plan.tenant_id', 'rental_plan.id'], name=op.f('fk_rental_plan_purchase_rental_plan_id_rental_plan'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'sold_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_rental_plan_purchase_sold_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_plan_purchase_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_plan_purchase')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_plan_purchase_tenant_id_id'))
    )
    op.create_index(op.f('ix_rental_plan_purchase_charge_id'), 'rental_plan_purchase', ['tenant_id', 'charge_id'], unique=False)
    op.create_index('ix_rental_plan_purchase_client', 'rental_plan_purchase', ['tenant_id', 'client_id', 'status'], unique=False)
    op.create_index('ix_rental_plan_purchase_due', 'rental_plan_purchase', ['tenant_id', 'location_id', 'expires_on'], unique=False, postgresql_where=sa.text("status = 'active'"))
    op.create_index(op.f('ix_rental_plan_purchase_rental_plan_id'), 'rental_plan_purchase', ['tenant_id', 'rental_plan_id'], unique=False)
    op.create_index(op.f('ix_rental_plan_purchase_sold_by_staff_user_id'), 'rental_plan_purchase', ['tenant_id', 'sold_by_staff_user_id'], unique=False)
    op.create_index('uq_rental_plan_purchase_successor', 'rental_plan_purchase', ['tenant_id', 'renewed_from_purchase_id'], unique=True, postgresql_where=sa.text('renewed_from_purchase_id IS NOT NULL'))
    op.create_table('rental_booking',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('booking_id', sa.Uuid(), nullable=False),
    sa.Column('rental_type_id', sa.Uuid(), nullable=False),
    sa.Column('charge_state', sa.Text(), server_default=sa.text("'unbilled'"), nullable=False),
    sa.Column('booked_via', sa.Text(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_on_public_schedule', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("booked_via IN ('staff', 'portal', 'mobile', 'api')", name=op.f('ck_rental_booking_booked_via')),
    sa.CheckConstraint("charge_state IN ('unbilled', 'no_charge', 'billed', 'plan_covered')", name=op.f('ck_rental_booking_charge_state')),
    sa.ForeignKeyConstraint(['tenant_id', 'booking_id'], ['booking.tenant_id', 'booking.id'], name=op.f('fk_rental_booking_booking_id_booking'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_rental_booking_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_type_id'], ['rental_type.tenant_id', 'rental_type.id'], name=op.f('fk_rental_booking_rental_type_id_rental_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_booking_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_booking')),
    sa.UniqueConstraint('tenant_id', 'booking_id', name='uq_rental_booking_booking'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_booking_tenant_id_id'))
    )
    op.create_index('ix_rental_booking_location', 'rental_booking', ['tenant_id', 'location_id', 'starts_at', 'id'], unique=False)
    op.create_index('ix_rental_booking_type', 'rental_booking', ['tenant_id', 'rental_type_id', 'starts_at'], unique=False)
    op.create_index('ix_rental_booking_unbilled', 'rental_booking', ['tenant_id', 'location_id', 'starts_at'], unique=False, postgresql_where=sa.text("charge_state = 'unbilled' AND cancelled_at IS NULL"))
    op.create_table('rental_booking_charge_item',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('rental_booking_charge_id', sa.Uuid(), nullable=False),
    sa.Column('rental_booking_id', sa.Uuid(), nullable=False),
    sa.Column('resource_id', sa.Uuid(), nullable=True),
    sa.Column('amount_minor', sa.Integer(), nullable=False),
    sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount_minor >= 0', name=op.f('ck_rental_booking_charge_item_amount')),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_booking_charge_id'], ['rental_booking_charge.tenant_id', 'rental_booking_charge.id'], name=op.f('fk_rental_booking_charge_item_rental_booking_charge_id_rental_booking_charge'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_booking_id'], ['rental_booking.tenant_id', 'rental_booking.id'], name=op.f('fk_rental_booking_charge_item_rental_booking_id_rental_booking'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'resource_id'], ['resource.tenant_id', 'resource.id'], name=op.f('fk_rental_booking_charge_item_resource_id_resource'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_booking_charge_item_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_booking_charge_item')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_booking_charge_item_tenant_id_id'))
    )
    op.create_index('ix_rental_booking_charge_item_booking', 'rental_booking_charge_item', ['tenant_id', 'rental_booking_id'], unique=False)
    op.create_index(op.f('ix_rental_booking_charge_item_resource_id'), 'rental_booking_charge_item', ['tenant_id', 'resource_id'], unique=False)
    op.create_index('uq_rental_booking_charge_item', 'rental_booking_charge_item', ['tenant_id', 'rental_booking_charge_id', 'rental_booking_id', 'resource_id'], unique=True, postgresql_nulls_not_distinct=True)
    op.create_table('rental_party',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('rental_booking_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('is_charged', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_rental_party_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_booking_id'], ['rental_booking.tenant_id', 'rental_booking.id'], name=op.f('fk_rental_party_rental_booking_id_rental_booking'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_party_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_party')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_party_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'rental_booking_id', 'client_id', name='uq_rental_party')
    )
    op.create_index(op.f('ix_rental_party_client_id'), 'rental_party', ['tenant_id', 'client_id'], unique=False)
    op.create_table('rental_plan_ledger_entry',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('rental_plan_purchase_id', sa.Uuid(), nullable=False),
    sa.Column('entry_type', sa.Text(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('balance_after', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('rental_booking_id', sa.Uuid(), nullable=True),
    sa.Column('used_by_client_id', sa.Uuid(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(entry_type IN ('grant', 'credit') AND quantity >= 0) OR (entry_type IN ('debit', 'expire') AND quantity <= 0) OR entry_type = 'adjust'", name=op.f('ck_rental_plan_ledger_entry_sign')),
    sa.CheckConstraint("entry_type IN ('grant', 'debit', 'credit', 'expire', 'adjust')", name=op.f('ck_rental_plan_ledger_entry_entry_type')),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_booking_id'], ['rental_booking.tenant_id', 'rental_booking.id'], name=op.f('fk_rental_plan_ledger_entry_rental_booking_id_rental_booking'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'rental_plan_purchase_id'], ['rental_plan_purchase.tenant_id', 'rental_plan_purchase.id'], name=op.f('fk_rental_plan_ledger_entry_rental_plan_purchase_id_rental_plan_purchase'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'used_by_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_rental_plan_ledger_entry_used_by_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_rental_plan_ledger_entry_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rental_plan_ledger_entry')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_rental_plan_ledger_entry_tenant_id_id'))
    )
    op.create_index('ix_rental_plan_ledger_entry_purchase', 'rental_plan_ledger_entry', ['tenant_id', 'rental_plan_purchase_id', 'id'], unique=False)
    op.create_index(op.f('ix_rental_plan_ledger_entry_used_by_client_id'), 'rental_plan_ledger_entry', ['tenant_id', 'used_by_client_id'], unique=False)
    op.create_index('uq_rental_plan_ledger_entry_booking', 'rental_plan_ledger_entry', ['tenant_id', 'rental_booking_id', 'entry_type'], unique=True, postgresql_where=sa.text('rental_booking_id IS NOT NULL'))
    for table in TENANT_TABLES:
        enable_rls(table)
    enable_rls("rental_plan_ledger_entry", append_only=True)
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {sql}")
        op.execute(f"GRANT SELECT ON {name} TO fh_app")


def downgrade() -> None:
    for name in VIEWS:
        op.execute(f"DROP VIEW {name}")
    op.drop_constraint(op.f('fk_rental_type_online_rental_rate_id_rental_rate'), 'rental_type', type_='foreignkey')
    op.drop_index('uq_rental_plan_ledger_entry_booking', table_name='rental_plan_ledger_entry', postgresql_where=sa.text('rental_booking_id IS NOT NULL'))
    op.drop_index(op.f('ix_rental_plan_ledger_entry_used_by_client_id'), table_name='rental_plan_ledger_entry')
    op.drop_index('ix_rental_plan_ledger_entry_purchase', table_name='rental_plan_ledger_entry')
    op.drop_table('rental_plan_ledger_entry')
    op.drop_index(op.f('ix_rental_party_client_id'), table_name='rental_party')
    op.drop_table('rental_party')
    op.drop_index('uq_rental_booking_charge_item', table_name='rental_booking_charge_item', postgresql_nulls_not_distinct=True)
    op.drop_index(op.f('ix_rental_booking_charge_item_resource_id'), table_name='rental_booking_charge_item')
    op.drop_index('ix_rental_booking_charge_item_booking', table_name='rental_booking_charge_item')
    op.drop_table('rental_booking_charge_item')
    op.drop_index('ix_rental_booking_unbilled', table_name='rental_booking', postgresql_where=sa.text("charge_state = 'unbilled' AND cancelled_at IS NULL"))
    op.drop_index('ix_rental_booking_type', table_name='rental_booking')
    op.drop_index('ix_rental_booking_location', table_name='rental_booking')
    op.drop_table('rental_booking')
    op.drop_index('uq_rental_plan_purchase_successor', table_name='rental_plan_purchase', postgresql_where=sa.text('renewed_from_purchase_id IS NOT NULL'))
    op.drop_index(op.f('ix_rental_plan_purchase_sold_by_staff_user_id'), table_name='rental_plan_purchase')
    op.drop_index(op.f('ix_rental_plan_purchase_rental_plan_id'), table_name='rental_plan_purchase')
    op.drop_index('ix_rental_plan_purchase_due', table_name='rental_plan_purchase', postgresql_where=sa.text("status = 'active'"))
    op.drop_index('ix_rental_plan_purchase_client', table_name='rental_plan_purchase')
    op.drop_index(op.f('ix_rental_plan_purchase_charge_id'), table_name='rental_plan_purchase')
    op.drop_table('rental_plan_purchase')
    op.drop_index(op.f('ix_rental_booking_charge_rental_rate_id'), table_name='rental_booking_charge')
    op.drop_index(op.f('ix_rental_booking_charge_location_id'), table_name='rental_booking_charge')
    op.drop_index('ix_rental_booking_charge_client', table_name='rental_booking_charge')
    op.drop_table('rental_booking_charge')
    op.drop_index(op.f('ix_rental_type_resource_resource_id'), table_name='rental_type_resource')
    op.drop_table('rental_type_resource')
    op.drop_index(op.f('ix_rental_type_rental_plan_rental_plan_id'), table_name='rental_type_rental_plan')
    op.drop_table('rental_type_rental_plan')
    op.drop_index(op.f('ix_rental_rate_tax_tax_id'), table_name='rental_rate_tax')
    op.drop_table('rental_rate_tax')
    op.drop_index('ix_rental_rate_rule_order', table_name='rental_rate_rule')
    op.drop_table('rental_rate_rule')
    op.drop_index('uq_rental_rate_name', table_name='rental_rate', postgresql_where=sa.text('is_active'))
    op.drop_table('rental_rate')
    op.drop_index('uq_rental_plan_name', table_name='rental_plan', postgresql_where=sa.text("status = 'active'"))
    op.drop_index(op.f('ix_rental_plan_revenue_category_id'), table_name='rental_plan')
    op.drop_index(op.f('ix_rental_plan_rental_type_id'), table_name='rental_plan')
    op.drop_index(op.f('ix_rental_plan_location_id'), table_name='rental_plan')
    op.drop_table('rental_plan')
    op.drop_index('uq_rental_type_name', table_name='rental_type', postgresql_where=sa.text('is_active'))
    op.drop_index(op.f('ix_rental_type_revenue_category_id'), table_name='rental_type')
    op.drop_index(op.f('ix_rental_type_location_id'), table_name='rental_type')
    op.drop_table('rental_type')
