"""billing module 8: settings, coupons, payment schedules, stored methods, autopay, notices, document
delivery, pay links, and the two global tables that route provider webhooks to a tenant.

Generated from the models, then completed by hand: enable_rls() per table, grants for the global tables, the
SECURITY DEFINER lookup writer, the deferred "instalments sum to the invoice total" trigger and the backfill
of one default instalment per existing invoice.

Revision ID: 0301
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "0301"
down_revision = "0002"

TENANT_TABLES = (
    "coupon", "autopay_run", "billing_settings", "payment_method", "provider_customer", "coupon_redemption",
    "payment_schedule", "autopay_attempt", "billing_document_delivery", "invoice_pay_link",
)  # fmt: skip
BACKFILLED = ("invoice", "provider_account", "payment_schedule")  # read by the owner below, so RLS is lifted for the statement


def upgrade() -> None:
    # Every new tenant-owned table must call enable_rls("<table>") (append_only=True for ledgers and logs).
    op.create_table('coupon',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('code', postgresql.CITEXT(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('discount_minor', sa.BigInteger(), nullable=True),
    sa.Column('limit_per_client', sa.Integer(), nullable=True),
    sa.Column('is_portal_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('ends_at IS NULL OR ends_at > starts_at', name=op.f('ck_coupon_window')),
    sa.CheckConstraint('num_nonnulls(discount_pct, discount_minor) = 1 AND COALESCE(discount_pct, 1) > 0 AND COALESCE(discount_pct, 1) <= 100 AND COALESCE(discount_minor, 1) > 0', name=op.f('ck_coupon_discount')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_coupon_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_coupon')),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_coupon_code'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_coupon_tenant_id_id'))
    )
    op.create_table('inbound_webhook_event',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('provider_event_id', sa.Text(), nullable=False),
    sa.Column('provider_account_id', sa.Text(), nullable=True),
    sa.Column('tenant_id', sa.Uuid(), nullable=True),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'received'"), nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_inbound_webhook_event_tenant_id_tenant'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inbound_webhook_event')),
    sa.UniqueConstraint('provider', 'provider_event_id', name='uq_inbound_webhook_event_provider_event')
    )
    op.create_index('ix_inbound_webhook_event_work', 'inbound_webhook_event', ['received_at'], unique=False, postgresql_where=sa.text("status IN ('received', 'failed')"))
    op.create_table('provider_account_lookup',
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('provider_account_ref', sa.Text(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_provider_account_lookup_tenant_id_tenant'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('provider', 'provider_account_ref', name=op.f('pk_provider_account_lookup'))
    )
    op.create_table('autopay_run',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('business_on', sa.Date(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'running'"), nullable=False),
    sa.Column('selected_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('succeeded_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('failed_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('collected_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('running', 'completed', 'completed_with_errors')", name=op.f('ck_autopay_run_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_autopay_run_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_autopay_run_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_autopay_run')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_autopay_run_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'location_id', 'business_on', name='uq_autopay_run')
    )
    op.create_table('billing_settings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('is_membership_autopay_default_staff', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_membership_autopay_default_portal', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('save_card_default', sa.Text(), server_default=sa.text("'ask'"), nullable=False),
    sa.Column('card_expiry_notice_days', postgresql.ARRAY(sa.Integer()), server_default=sa.text("'{60,30}'"), nullable=False),
    sa.Column('card_expiry_notice_scope', sa.Text(), server_default=sa.text("'autopay_methods'"), nullable=False),
    sa.Column('decline_notice_scope', sa.Text(), server_default=sa.text("'all_payments'"), nullable=False),
    sa.Column('decline_alert_email', postgresql.CITEXT(), nullable=True),
    sa.Column('decline_alert_mode', sa.Text(), server_default=sa.text("'per_event'"), nullable=False),
    sa.Column('autopay_retry_offset_days', postgresql.ARRAY(sa.Integer()), server_default=sa.text("'{3,5,7}'"), nullable=False),
    sa.Column('due_reminder_offset_days', postgresql.ARRAY(sa.Integer()), server_default=sa.text("'{-3}'"), nullable=False),
    sa.Column('is_portal_blocked_when_past_due', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('invoice_email_subject', sa.Text(), server_default=sa.text("'Invoice {invoice_number}'"), nullable=False),
    sa.Column('invoice_footer', sa.Text(), nullable=True),
    sa.Column('receipt_footer', sa.Text(), nullable=True),
    sa.Column('statement_email_subject', sa.Text(), nullable=True),
    sa.Column('statement_email_body', sa.Text(), nullable=True),
    sa.Column('statement_footer', sa.Text(), nullable=True),
    sa.Column('is_program_description_on_invoice', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('program_description_source', sa.Text(), server_default=sa.text("'group'"), nullable=False),
    sa.Column('bill_to_fields', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{name,address}'"), nullable=False),
    sa.Column('package_invoice_sessions', sa.Text(), server_default=sa.text("'all'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("card_expiry_notice_scope IN ('all_methods', 'autopay_methods')", name=op.f('ck_billing_settings_card_expiry_notice_scope')),
    sa.CheckConstraint("decline_alert_mode IN ('per_event', 'daily_digest')", name=op.f('ck_billing_settings_decline_alert_mode')),
    sa.CheckConstraint("decline_notice_scope IN ('off', 'all_payments', 'autopay_payments')", name=op.f('ck_billing_settings_decline_notice_scope')),
    sa.CheckConstraint("package_invoice_sessions IN ('all', 'attended', 'none')", name=op.f('ck_billing_settings_package_invoice_sessions')),
    sa.CheckConstraint("program_description_source IN ('group', 'subgroup')", name=op.f('ck_billing_settings_program_description_source')),
    sa.CheckConstraint("save_card_default IN ('never', 'ask', 'always')", name=op.f('ck_billing_settings_save_card_default')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_billing_settings_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_billing_settings_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_settings')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_billing_settings_tenant_id_id'))
    )
    op.create_index('uq_billing_settings_location', 'billing_settings', ['tenant_id', 'location_id'], unique=True, postgresql_nulls_not_distinct=True)
    op.create_table('billing_notice',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('subject_type', sa.Text(), nullable=False),
    sa.Column('subject_id', sa.Uuid(), nullable=False),
    sa.Column('dedupe_key', sa.Text(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=True),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('due_reminder', 'past_due_reminder', 'final_notice', 'payment_declined', 'authentication_required', 'method_expiring', 'staff_decline_alert', 'staff_decline_digest')", name=op.f('ck_billing_notice_kind')),
    sa.CheckConstraint("subject_type IN ('invoice', 'payment', 'payment_method', 'location')", name=op.f('ck_billing_notice_subject_type')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_billing_notice_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_billing_notice_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_billing_notice_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_notice')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_billing_notice_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'kind', 'subject_type', 'subject_id', 'dedupe_key', name='uq_billing_notice')
    )
    op.create_index(op.f('ix_billing_notice_client_id'), 'billing_notice', ['tenant_id', 'client_id'], unique=False)
    op.create_index(op.f('ix_billing_notice_location_id'), 'billing_notice', ['tenant_id', 'location_id'], unique=False)
    op.create_table('payment_method',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('provider_account_id', sa.Uuid(), nullable=False),
    sa.Column('provider_method_ref', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('brand', sa.Text(), nullable=True),
    sa.Column('last4', sa.Text(), nullable=False),
    sa.Column('exp_month', sa.SmallInteger(), nullable=True),
    sa.Column('exp_year', sa.SmallInteger(), nullable=True),
    sa.Column('funding', sa.Text(), nullable=True),
    sa.Column('wallet', sa.Text(), nullable=True),
    sa.Column('is_autopay', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('suspended_on', sa.Date(), nullable=True),
    sa.Column('mandate_ref', sa.Text(), nullable=True),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'card') = (exp_month IS NOT NULL AND exp_year IS NOT NULL) AND (exp_month IS NULL OR exp_month BETWEEN 1 AND 12)", name=op.f('ck_payment_method_expiry')),
    sa.CheckConstraint("kind IN ('card', 'bank_account')", name=op.f('ck_payment_method_kind')),
    sa.CheckConstraint("status IN ('pending_verification', 'active', 'suspended', 'removed')", name=op.f('ck_payment_method_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_payment_method_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'provider_account_id'], ['provider_account.tenant_id', 'provider_account.id'], name=op.f('fk_payment_method_provider_account_id_provider_account'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_payment_method_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_method')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_payment_method_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'provider_account_id', 'provider_method_ref', name='uq_payment_method_ref')
    )
    op.create_index(op.f('ix_payment_method_client_id'), 'payment_method', ['tenant_id', 'client_id'], unique=False)
    op.create_index('ix_payment_method_expiry', 'payment_method', ['tenant_id', 'exp_year', 'exp_month'], unique=False, postgresql_where=sa.text("kind = 'card' AND status = 'active'"))
    op.create_index('uq_payment_method_autopay', 'payment_method', ['tenant_id', 'client_id'], unique=True, postgresql_where=sa.text("is_autopay AND status = 'active'"))
    op.create_table('provider_customer',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('provider_account_id', sa.Uuid(), nullable=False),
    sa.Column('provider_customer_ref', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_provider_customer_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'provider_account_id'], ['provider_account.tenant_id', 'provider_account.id'], name=op.f('fk_provider_customer_provider_account_id_provider_account'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_provider_customer_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_customer')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_provider_customer_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'provider_account_id', 'client_id', name='uq_provider_customer')
    )
    op.create_index(op.f('ix_provider_customer_client_id'), 'provider_customer', ['tenant_id', 'client_id'], unique=False)
    op.create_table('coupon_redemption',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('coupon_id', sa.Uuid(), nullable=False),
    sa.Column('redeemer_client_id', sa.Uuid(), nullable=True),
    sa.Column('redemption_key', sa.Text(), nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=True),
    sa.Column('discount_minor', sa.BigInteger(), nullable=False),
    sa.Column('redeemed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'coupon_id'], ['coupon.tenant_id', 'coupon.id'], name=op.f('fk_coupon_redemption_coupon_id_coupon'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'invoice_id'], ['invoice.tenant_id', 'invoice.id'], name=op.f('fk_coupon_redemption_invoice_id_invoice'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'redeemer_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_coupon_redemption_redeemer_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_coupon_redemption_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_coupon_redemption')),
    sa.UniqueConstraint('tenant_id', 'coupon_id', 'redemption_key', name='uq_coupon_redemption_key'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_coupon_redemption_tenant_id_id'))
    )
    op.create_index(op.f('ix_coupon_redemption_invoice_id'), 'coupon_redemption', ['tenant_id', 'invoice_id'], unique=False)
    op.create_index(op.f('ix_coupon_redemption_redeemer_client_id'), 'coupon_redemption', ['tenant_id', 'redeemer_client_id'], unique=False)
    op.create_table('payment_schedule',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('due_on', sa.Date(), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('covered_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount_minor >= 0', name=op.f('ck_payment_schedule_amount')),
    sa.CheckConstraint('covered_minor BETWEEN 0 AND amount_minor', name=op.f('ck_payment_schedule_covered')),
    sa.ForeignKeyConstraint(['tenant_id', 'invoice_id'], ['invoice.tenant_id', 'invoice.id'], name=op.f('fk_payment_schedule_invoice_id_invoice'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_payment_schedule_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_schedule')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_payment_schedule_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'invoice_id', 'seq', name='uq_payment_schedule_seq')
    )
    op.create_index('ix_payment_schedule_due', 'payment_schedule', ['tenant_id', 'due_on'], unique=False, postgresql_where=sa.text('covered_minor < amount_minor'))
    op.create_table('autopay_attempt',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('autopay_run_id', sa.Uuid(), nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=False),
    sa.Column('attempt_no', sa.Integer(), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('credit_applied_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('payment_method_id', sa.Uuid(), nullable=True),
    sa.Column('payment_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('failure_category', sa.Text(), nullable=True),
    sa.Column('failure_message', sa.Text(), nullable=True),
    sa.Column('error_cleared_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_cleared_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'succeeded', 'processing', 'failed', 'skipped')", name=op.f('ck_autopay_attempt_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'autopay_run_id'], ['autopay_run.tenant_id', 'autopay_run.id'], name=op.f('fk_autopay_attempt_autopay_run_id_autopay_run'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'error_cleared_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_autopay_attempt_error_cleared_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'invoice_id'], ['invoice.tenant_id', 'invoice.id'], name=op.f('fk_autopay_attempt_invoice_id_invoice'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'payment_id'], ['payment.tenant_id', 'payment.id'], name=op.f('fk_autopay_attempt_payment_id_payment'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'payment_method_id'], ['payment_method.tenant_id', 'payment_method.id'], name=op.f('fk_autopay_attempt_payment_method_id_payment_method'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_autopay_attempt_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_autopay_attempt')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_autopay_attempt_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'invoice_id', 'attempt_no', name='uq_autopay_attempt')
    )
    op.create_index(op.f('ix_autopay_attempt_autopay_run_id'), 'autopay_attempt', ['tenant_id', 'autopay_run_id'], unique=False)
    op.create_index(op.f('ix_autopay_attempt_error_cleared_by_staff_user_id'), 'autopay_attempt', ['tenant_id', 'error_cleared_by_staff_user_id'], unique=False)
    op.create_index('ix_autopay_attempt_errors', 'autopay_attempt', ['tenant_id', sa.literal_column('created_at DESC')], unique=False, postgresql_where=sa.text("status = 'failed' AND error_cleared_at IS NULL"))
    op.create_index(op.f('ix_autopay_attempt_payment_method_id'), 'autopay_attempt', ['tenant_id', 'payment_method_id'], unique=False)
    op.create_index('uq_autopay_attempt_payment', 'autopay_attempt', ['tenant_id', 'payment_id'], unique=True, postgresql_where=sa.text('payment_id IS NOT NULL'))
    op.create_table('billing_document_delivery',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('document_kind', sa.Text(), nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=True),
    sa.Column('payment_id', sa.Uuid(), nullable=True),
    sa.Column('client_id', sa.Uuid(), nullable=True),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('to_email', postgresql.CITEXT(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('failure_message', sa.Text(), nullable=True),
    sa.Column('requested_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(document_kind = 'invoice') = (invoice_id IS NOT NULL) AND (document_kind = 'receipt') = (payment_id IS NOT NULL) AND (document_kind <> 'statement' OR client_id IS NOT NULL)", name=op.f('ck_billing_document_delivery_subject')),
    sa.CheckConstraint("channel <> 'email' OR to_email IS NOT NULL", name=op.f('ck_billing_document_delivery_to_email')),
    sa.CheckConstraint("channel IN ('email', 'print', 'download')", name=op.f('ck_billing_document_delivery_channel')),
    sa.CheckConstraint("document_kind IN ('invoice', 'receipt', 'statement')", name=op.f('ck_billing_document_delivery_document_kind')),
    sa.CheckConstraint("status IN ('queued', 'sent', 'failed')", name=op.f('ck_billing_document_delivery_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_billing_document_delivery_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'invoice_id'], ['invoice.tenant_id', 'invoice.id'], name=op.f('fk_billing_document_delivery_invoice_id_invoice'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'payment_id'], ['payment.tenant_id', 'payment.id'], name=op.f('fk_billing_document_delivery_payment_id_payment'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'requested_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_billing_document_delivery_requested_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_billing_document_delivery_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_document_delivery')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_billing_document_delivery_tenant_id_id'))
    )
    op.create_index(op.f('ix_billing_document_delivery_client_id'), 'billing_document_delivery', ['tenant_id', 'client_id'], unique=False)
    op.create_index(op.f('ix_billing_document_delivery_invoice_id'), 'billing_document_delivery', ['tenant_id', 'invoice_id'], unique=False)
    op.create_index(op.f('ix_billing_document_delivery_payment_id'), 'billing_document_delivery', ['tenant_id', 'payment_id'], unique=False)
    op.create_index(op.f('ix_billing_document_delivery_requested_by_staff_user_id'), 'billing_document_delivery', ['tenant_id', 'requested_by_staff_user_id'], unique=False)
    op.create_table('invoice_pay_link',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('payment_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'invoice_id'], ['invoice.tenant_id', 'invoice.id'], name=op.f('fk_invoice_pay_link_invoice_id_invoice'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'payment_id'], ['payment.tenant_id', 'payment.id'], name=op.f('fk_invoice_pay_link_payment_id_payment'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_invoice_pay_link_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice_pay_link')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_invoice_pay_link_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'token_hash', name='uq_invoice_pay_link_token_hash')
    )
    op.create_index(op.f('ix_invoice_pay_link_invoice_id'), 'invoice_pay_link', ['tenant_id', 'invoice_id'], unique=False)
    op.create_index(op.f('ix_invoice_pay_link_payment_id'), 'invoice_pay_link', ['tenant_id', 'payment_id'], unique=False)
    op.add_column('charge', sa.Column('coupon_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_charge_coupon_id'), 'charge', ['tenant_id', 'coupon_id'], unique=False)
    op.create_foreign_key(op.f('fk_charge_coupon_id_coupon'), 'charge', 'coupon', ['tenant_id', 'coupon_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_index('ix_invoice_autopay_due', 'invoice', ['tenant_id', 'location_id', 'due_on'], unique=False, postgresql_where=sa.text("is_autopay AND balance_minor > 0 AND status <> 'voided'"))
    op.create_index('ix_invoice_past_due', 'invoice', ['tenant_id', 'location_id', 'past_due_since_on'], unique=False, postgresql_where=sa.text('past_due_since_on IS NOT NULL'))
    op.add_column('payment', sa.Column('payment_method_id', sa.Uuid(), nullable=True))
    op.add_column('payment', sa.Column('idempotency_key', sa.Text(), nullable=True))
    op.create_index(op.f('ix_payment_payment_method_id'), 'payment', ['tenant_id', 'payment_method_id'], unique=False)
    op.create_index('uq_payment_idempotency_key', 'payment', ['tenant_id', 'idempotency_key'], unique=True, postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.create_foreign_key(op.f('fk_payment_payment_method_id_payment_method'), 'payment', 'payment_method', ['tenant_id', 'payment_method_id'], ['tenant_id', 'id'], ondelete='RESTRICT')

    for table in TENANT_TABLES:
        enable_rls(table)
    enable_rls("billing_notice", append_only=True)

    # Global tables (overview 3.1): no RLS, reachable only by fh_platform. fh_app writes the lookup through
    # the SECURITY DEFINER function, which can only ever name the caller's own tenant.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON inbound_webhook_event, provider_account_lookup TO fh_platform")
    op.execute(
        """
        CREATE FUNCTION app.register_provider_account(p_provider text, p_ref text) RETURNS void
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            INSERT INTO public.provider_account_lookup (provider, provider_account_ref, tenant_id)
            VALUES (p_provider, p_ref, app.current_tenant_id())
            ON CONFLICT (provider, provider_account_ref) DO NOTHING
        $$
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION app.register_provider_account(text, text) TO fh_app")

    for table in BACKFILLED:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO provider_account_lookup (provider, provider_account_ref, tenant_id) "
        "SELECT provider, provider_account_ref, tenant_id FROM provider_account ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO payment_schedule (tenant_id, invoice_id, seq, due_on, amount_minor, covered_minor) "
        "SELECT tenant_id, id, 1, due_on, GREATEST(total_minor, 0), "
        "LEAST(GREATEST(total_minor - balance_minor, 0), GREATEST(total_minor, 0)) FROM invoice"
    )
    for table in BACKFILLED:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # BIL-06: for a non-voided invoice the instalments sum to its total and none is due before the invoice
    # date. Deferred, so the service may change the total and rebalance in any order inside one transaction.
    op.execute(
        """
        CREATE FUNCTION app.check_payment_schedule_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            inv uuid; tenant uuid; total bigint; started date; state text; planned bigint; first_due date;
        BEGIN
            IF TG_TABLE_NAME = 'invoice' THEN
                inv := NEW.id; tenant := NEW.tenant_id;
            ELSIF TG_OP = 'DELETE' THEN
                inv := OLD.invoice_id; tenant := OLD.tenant_id;
            ELSE
                inv := NEW.invoice_id; tenant := NEW.tenant_id;
            END IF;
            SELECT total_minor, invoice_on, status INTO total, started, state
              FROM public.invoice WHERE id = inv AND tenant_id = tenant;
            IF NOT FOUND OR state = 'voided' THEN RETURN NULL; END IF;
            SELECT COALESCE(sum(amount_minor), 0), min(due_on) INTO planned, first_due
              FROM public.payment_schedule WHERE invoice_id = inv AND tenant_id = tenant;
            IF planned <> GREATEST(total, 0) OR first_due < started THEN
                RAISE EXCEPTION 'payment schedule of invoice %% is not balanced (planned %%, total %%)',
                    inv, planned, total
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'ct_payment_schedule_balanced';
            END IF;
            RETURN NULL;
        END $$
        """.replace("%%", "%")
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ct_payment_schedule_balanced AFTER INSERT OR UPDATE OR DELETE ON payment_schedule "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_payment_schedule_balanced()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER ct_payment_schedule_balanced AFTER UPDATE OF total_minor, invoice_on ON invoice "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_payment_schedule_balanced()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER ct_payment_schedule_balanced ON invoice")
    op.execute("DROP FUNCTION app.register_provider_account(text, text)")
    op.drop_constraint(op.f('fk_payment_payment_method_id_payment_method'), 'payment', type_='foreignkey')
    op.drop_index('uq_payment_idempotency_key', table_name='payment', postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.drop_index(op.f('ix_payment_payment_method_id'), table_name='payment')
    op.drop_column('payment', 'idempotency_key')
    op.drop_column('payment', 'payment_method_id')
    op.drop_index('ix_invoice_past_due', table_name='invoice', postgresql_where=sa.text('past_due_since_on IS NOT NULL'))
    op.drop_index('ix_invoice_autopay_due', table_name='invoice', postgresql_where=sa.text("is_autopay AND balance_minor > 0 AND status <> 'voided'"))
    op.drop_constraint(op.f('fk_charge_coupon_id_coupon'), 'charge', type_='foreignkey')
    op.drop_index(op.f('ix_charge_coupon_id'), table_name='charge')
    op.drop_column('charge', 'coupon_id')
    op.drop_index(op.f('ix_invoice_pay_link_payment_id'), table_name='invoice_pay_link')
    op.drop_index(op.f('ix_invoice_pay_link_invoice_id'), table_name='invoice_pay_link')
    op.drop_table('invoice_pay_link')
    op.drop_index(op.f('ix_billing_document_delivery_requested_by_staff_user_id'), table_name='billing_document_delivery')
    op.drop_index(op.f('ix_billing_document_delivery_payment_id'), table_name='billing_document_delivery')
    op.drop_index(op.f('ix_billing_document_delivery_invoice_id'), table_name='billing_document_delivery')
    op.drop_index(op.f('ix_billing_document_delivery_client_id'), table_name='billing_document_delivery')
    op.drop_table('billing_document_delivery')
    op.drop_index('uq_autopay_attempt_payment', table_name='autopay_attempt', postgresql_where=sa.text('payment_id IS NOT NULL'))
    op.drop_index(op.f('ix_autopay_attempt_payment_method_id'), table_name='autopay_attempt')
    op.drop_index('ix_autopay_attempt_errors', table_name='autopay_attempt', postgresql_where=sa.text("status = 'failed' AND error_cleared_at IS NULL"))
    op.drop_index(op.f('ix_autopay_attempt_error_cleared_by_staff_user_id'), table_name='autopay_attempt')
    op.drop_index(op.f('ix_autopay_attempt_autopay_run_id'), table_name='autopay_attempt')
    op.drop_table('autopay_attempt')
    op.drop_index('ix_payment_schedule_due', table_name='payment_schedule', postgresql_where=sa.text('covered_minor < amount_minor'))
    op.drop_table('payment_schedule')
    op.drop_index(op.f('ix_coupon_redemption_redeemer_client_id'), table_name='coupon_redemption')
    op.drop_index(op.f('ix_coupon_redemption_invoice_id'), table_name='coupon_redemption')
    op.drop_table('coupon_redemption')
    op.drop_index(op.f('ix_provider_customer_client_id'), table_name='provider_customer')
    op.drop_table('provider_customer')
    op.drop_index('uq_payment_method_autopay', table_name='payment_method', postgresql_where=sa.text("is_autopay AND status = 'active'"))
    op.drop_index('ix_payment_method_expiry', table_name='payment_method', postgresql_where=sa.text("kind = 'card' AND status = 'active'"))
    op.drop_index(op.f('ix_payment_method_client_id'), table_name='payment_method')
    op.drop_table('payment_method')
    op.drop_index(op.f('ix_billing_notice_location_id'), table_name='billing_notice')
    op.drop_index(op.f('ix_billing_notice_client_id'), table_name='billing_notice')
    op.drop_table('billing_notice')
    op.drop_index('uq_billing_settings_location', table_name='billing_settings', postgresql_nulls_not_distinct=True)
    op.drop_table('billing_settings')
    op.drop_table('autopay_run')
    op.drop_table('provider_account_lookup')
    op.drop_index('ix_inbound_webhook_event_work', table_name='inbound_webhook_event', postgresql_where=sa.text("status IN ('received', 'failed')"))
    op.drop_table('inbound_webhook_event')
    op.drop_table('coupon')
    op.execute("DROP FUNCTION app.check_payment_schedule_balanced()")
