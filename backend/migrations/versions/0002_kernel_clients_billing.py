"""kernel slices ahead of their modules (overview section 6): platform.tenant_counter, the clients skeleton
(client, client_portal_access) and the billing kernel (catalogue, receivables, payments, immutable ledger).

Generated from the models, then completed by hand: enable_rls() per table, the append-only grants and the
deferred balance trigger on the ledger.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "0002"
down_revision = "0001"

TENANT_TABLES = (
    "revenue_category",
    "tax",
    "tenant_counter",
    "tender_type",
    "client",
    "provider_account",
    "revenue_category_tax",
    "tax_rate",
    "client_portal_access",
    "invoice",
    "payment",
    "charge",
    "refund",
    "charge_tax",
    "payment_allocation",
)
APPEND_ONLY_TABLES = ("ledger_transaction", "ledger_entry")  # SELECT, INSERT only: no code path can rewrite money


def upgrade() -> None:
    op.create_table('ledger_transaction',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('source_type', sa.Text(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('effective_on', sa.Date(), nullable=False),
    sa.Column('posted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('reverses_transaction_id', sa.Uuid(), nullable=True),
    sa.Column('actor_type', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint("actor_type IN ('staff', 'client', 'api_key', 'kiosk', 'system')", name=op.f('ck_ledger_transaction_actor_type')),
    sa.CheckConstraint("kind IN ('charge_posted', 'payment_settled', 'allocation_applied', 'allocation_released', 'refund_succeeded', 'refund_returned', 'payment_voided', 'dispute_opened', 'dispute_won', 'dispute_lost', 'correction')", name=op.f('ck_ledger_transaction_kind')),
    sa.CheckConstraint("source_type IN ('charge', 'payment', 'payment_allocation', 'refund', 'dispute')", name=op.f('ck_ledger_transaction_source_type')),
    sa.ForeignKeyConstraint(['tenant_id', 'reverses_transaction_id'], ['ledger_transaction.tenant_id', 'ledger_transaction.id'], name=op.f('fk_ledger_transaction_reverses_transaction_id_ledger_transaction'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_ledger_transaction_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ledger_transaction')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_ledger_transaction_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'kind', 'source_type', 'source_id', name='uq_ledger_transaction_source')
    )
    op.create_index(op.f('ix_ledger_transaction_reverses_transaction_id'), 'ledger_transaction', ['tenant_id', 'reverses_transaction_id'], unique=False)
    op.create_table('revenue_category',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('code', postgresql.CITEXT(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('system_key', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('parent_id <> id', name=op.f('ck_revenue_category_not_self')),
    sa.ForeignKeyConstraint(['tenant_id', 'parent_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_revenue_category_parent_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_revenue_category_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_revenue_category')),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_revenue_category_code'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_revenue_category_tenant_id_id'))
    )
    op.create_index(op.f('ix_revenue_category_parent_id'), 'revenue_category', ['tenant_id', 'parent_id'], unique=False)
    op.create_index('uq_revenue_category_system_key', 'revenue_category', ['tenant_id', 'system_key'], unique=True, postgresql_where=sa.text('system_key IS NOT NULL'))
    op.create_table('tax',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('code', postgresql.CITEXT(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('deactivated_on', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('is_active OR deactivated_on IS NOT NULL', name=op.f('ck_tax_deactivated')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_tax_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tax')),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_tax_code'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_tax_tenant_id_id'))
    )
    op.create_table('tenant_counter',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('counter_key', sa.Text(), nullable=False),
    sa.Column('next_value', sa.BigInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_tenant_counter_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenant_counter')),
    sa.UniqueConstraint('tenant_id', 'counter_key', name='uq_tenant_counter'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_tenant_counter_tenant_id_id'))
    )
    op.create_table('tender_type',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('is_processed', sa.Boolean(), nullable=False),
    sa.Column('is_optional', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("is_processed = (kind IN ('card', 'bank_debit'))", name=op.f('ck_tender_type_processed')),
    sa.CheckConstraint("kind IN ('card', 'bank_debit', 'cash', 'cheque', 'bank_transfer', 'gift_card', 'external', 'other')", name=op.f('ck_tender_type_kind')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_tender_type_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tender_type')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_tender_type_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'label', name='uq_tender_type_label')
    )
    op.create_index('uq_tender_type_kind_single', 'tender_type', ['tenant_id', 'kind'], unique=True, postgresql_where=sa.text("kind NOT IN ('external', 'other')"))
    op.create_table('client',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('first_name', sa.Text(), nullable=False),
    sa.Column('last_name', sa.Text(), nullable=False),
    sa.Column('phone_mobile', sa.Text(), nullable=True),
    sa.Column('home_location_id', sa.Uuid(), nullable=False),
    sa.Column('primary_email', postgresql.CITEXT(), nullable=True),
    sa.Column('member_number', postgresql.CITEXT(), nullable=True),
    sa.Column('member_number_source', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(member_number IS NULL AND member_number_source IS NULL) OR (member_number IS NOT NULL AND member_number_source IN ('generated', 'manual', 'scanned'))", name=op.f('ck_client_member_number_source')),
    sa.CheckConstraint("(status = 'disabled') = (disabled_at IS NOT NULL)", name=op.f('ck_client_disabled')),
    sa.CheckConstraint("btrim(first_name) <> ''", name=op.f('ck_client_first_name')),
    sa.CheckConstraint("btrim(last_name) <> ''", name=op.f('ck_client_last_name')),
    sa.CheckConstraint("phone_mobile ~ '^\\+[1-9][0-9]{6,14}$'", name=op.f('ck_client_phone_mobile')),
    sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f('ck_client_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'home_location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_client_home_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_tenant_id_id'))
    )
    op.create_index(op.f('ix_client_home_location_id'), 'client', ['tenant_id', 'home_location_id'], unique=False)
    op.create_index('ix_client_name', 'client', ['tenant_id', sa.literal_column('lower(last_name)'), sa.literal_column('lower(first_name)'), 'id'], unique=False)
    op.create_index('ix_client_status', 'client', ['tenant_id', 'status', 'id'], unique=False)
    op.create_index('uq_client_tenant_id_member_number', 'client', ['tenant_id', 'member_number'], unique=True, postgresql_where=sa.text('member_number IS NOT NULL'))
    op.create_table('provider_account',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('provider_account_ref', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('has_card', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('has_bank_debit', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('has_wallets', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_payouts_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('requirements_due', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('stripe', 'fake')", name=op.f('ck_provider_account_provider')),
    sa.CheckConstraint("status IN ('pending', 'restricted', 'active', 'disabled')", name=op.f('ck_provider_account_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_provider_account_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_provider_account_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_account')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_provider_account_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'provider', 'provider_account_ref', name='uq_provider_account_ref')
    )
    op.create_index(op.f('ix_provider_account_location_id'), 'provider_account', ['tenant_id', 'location_id'], unique=False)
    op.create_index('uq_provider_account_scope', 'provider_account', ['tenant_id', 'location_id'], unique=True, postgresql_where=sa.text("status <> 'disabled'"), postgresql_nulls_not_distinct=True)
    op.create_table('revenue_category_tax',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=False),
    sa.Column('tax_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_revenue_category_tax_revenue_category_id_revenue_category'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'tax_id'], ['tax.tenant_id', 'tax.id'], name=op.f('fk_revenue_category_tax_tax_id_tax'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_revenue_category_tax_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_revenue_category_tax')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_revenue_category_tax_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'revenue_category_id', 'tax_id', name='uq_revenue_category_tax')
    )
    op.create_index(op.f('ix_revenue_category_tax_tax_id'), 'revenue_category_tax', ['tenant_id', 'tax_id'], unique=False)
    op.create_table('tax_rate',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('tax_id', sa.Uuid(), nullable=False),
    sa.Column('rate', sa.Numeric(precision=7, scale=6), nullable=False),
    sa.Column('effective_from_on', sa.Date(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('rate >= 0 AND rate < 1', name=op.f('ck_tax_rate_rate')),
    sa.ForeignKeyConstraint(['tenant_id', 'tax_id'], ['tax.tenant_id', 'tax.id'], name=op.f('fk_tax_rate_tax_id_tax'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_tax_rate_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tax_rate')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_tax_rate_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'tax_id', 'effective_from_on', name='uq_tax_rate_tax_id_effective_from_on')
    )
    op.create_table('client_portal_access',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('identity_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'invited'"), nullable=False),
    sa.Column('invited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('invited_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('invited', 'active', 'revoked')", name=op.f('ck_client_portal_access_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_portal_access_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'identity_id'], ['identity.tenant_id', 'identity.id'], name=op.f('fk_client_portal_access_identity_id_identity'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'invited_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_portal_access_invited_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_portal_access_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_portal_access')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_portal_access_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'identity_id', 'client_id', name='uq_client_portal_access_identity_client')
    )
    op.create_index(op.f('ix_client_portal_access_client_id'), 'client_portal_access', ['tenant_id', 'client_id'], unique=False)
    op.create_index(op.f('ix_client_portal_access_identity_id'), 'client_portal_access', ['tenant_id', 'identity_id'], unique=False)
    op.create_index(op.f('ix_client_portal_access_invited_by_staff_user_id'), 'client_portal_access', ['tenant_id', 'invited_by_staff_user_id'], unique=False)
    op.create_index('uq_client_portal_access_primary', 'client_portal_access', ['tenant_id', 'client_id'], unique=True, postgresql_where=sa.text("is_primary AND status <> 'revoked'"))
    op.create_table('invoice',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.BigInteger(), nullable=False),
    sa.Column('bill_to_client_id', sa.Uuid(), nullable=True),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('invoice_on', sa.Date(), nullable=False),
    sa.Column('due_on', sa.Date(), nullable=False),
    sa.Column('is_autopay', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'open'"), nullable=False),
    sa.Column('total_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('balance_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('past_due_since_on', sa.Date(), nullable=True),
    sa.Column('dunning_state', sa.Text(), server_default=sa.text("'none'"), nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('next_attempt_on', sa.Date(), nullable=True),
    sa.Column('comments', sa.Text(), nullable=True),
    sa.Column('organization_name', sa.Text(), nullable=True),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('voided_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('void_reason', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("bill_to_client_id IS NOT NULL OR origin = 'pos'", name=op.f('ck_invoice_bill_to')),
    sa.CheckConstraint("dunning_state IN ('none', 'retrying', 'awaiting_method', 'exhausted')", name=op.f('ck_invoice_dunning_state')),
    sa.CheckConstraint("origin IN ('staff', 'portal', 'pos', 'kiosk', 'api', 'system')", name=op.f('ck_invoice_origin')),
    sa.CheckConstraint("status IN ('open', 'payment_pending', 'partially_paid', 'paid', 'voided')", name=op.f('ck_invoice_status')),
    sa.CheckConstraint('due_on >= invoice_on', name=op.f('ck_invoice_due')),
    sa.ForeignKeyConstraint(['tenant_id', 'bill_to_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_invoice_bill_to_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_invoice_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_invoice_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'voided_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_invoice_voided_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_invoice_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_invoice_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'number', name='uq_invoice_number')
    )
    op.create_index('ix_invoice_bill_to_client_id', 'invoice', ['tenant_id', 'bill_to_client_id', sa.literal_column('invoice_on DESC'), sa.literal_column('id DESC')], unique=False)
    op.create_index(op.f('ix_invoice_created_by_staff_user_id'), 'invoice', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_invoice_location_id'), 'invoice', ['tenant_id', 'location_id'], unique=False)
    op.create_index('ix_invoice_payable', 'invoice', ['tenant_id', 'bill_to_client_id', 'due_on', 'id'], unique=False, postgresql_where=sa.text("status IN ('open', 'payment_pending', 'partially_paid')"))
    op.create_index(op.f('ix_invoice_voided_by_staff_user_id'), 'invoice', ['tenant_id', 'voided_by_staff_user_id'], unique=False)
    op.create_table('payment',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('receipt_number', sa.BigInteger(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=True),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('tender_type_id', sa.Uuid(), nullable=False),
    sa.Column('tender_kind', sa.Text(), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'initiated'"), nullable=False),
    sa.Column('origin', sa.Text(), nullable=False),
    sa.Column('provider_account_id', sa.Uuid(), nullable=True),
    sa.Column('provider_payment_ref', sa.Text(), nullable=True),
    sa.Column('card_brand', sa.Text(), nullable=True),
    sa.Column('card_last4', sa.Text(), nullable=True),
    sa.Column('card_funding', sa.Text(), nullable=True),
    sa.Column('wallet', sa.Text(), nullable=True),
    sa.Column('external_reference', sa.Text(), nullable=True),
    sa.Column('memo', sa.Text(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_category', sa.Text(), nullable=True),
    sa.Column('failure_message', sa.Text(), nullable=True),
    sa.Column('unapplied_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('refunded_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('taken_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('voided_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('void_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(provider_account_id IS NOT NULL) = (tender_kind IN ('card', 'bank_debit'))", name=op.f('ck_payment_provider')),
    sa.CheckConstraint("client_id IS NOT NULL OR origin = 'pos'", name=op.f('ck_payment_client')),
    sa.CheckConstraint("origin IN ('staff', 'portal', 'pos', 'kiosk', 'autopay', 'api')", name=op.f('ck_payment_origin')),
    sa.CheckConstraint("status <> 'voided' OR (void_reason IS NOT NULL AND provider_account_id IS NULL)", name=op.f('ck_payment_void')),
    sa.CheckConstraint("status IN ('initiated', 'requires_action', 'processing', 'succeeded', 'failed', 'unknown', 'cancelled', 'disputed', 'charged_back', 'voided')", name=op.f('ck_payment_status')),
    sa.CheckConstraint("tender_kind IN ('card', 'bank_debit', 'cash', 'cheque', 'bank_transfer', 'gift_card', 'external', 'other')", name=op.f('ck_payment_tender_kind')),
    sa.CheckConstraint('amount_minor > 0', name=op.f('ck_payment_amount')),
    sa.CheckConstraint('unapplied_minor >= 0 AND refunded_minor BETWEEN 0 AND amount_minor', name=op.f('ck_payment_remainder')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_payment_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_payment_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'provider_account_id'], ['provider_account.tenant_id', 'provider_account.id'], name=op.f('fk_payment_provider_account_id_provider_account'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'taken_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_payment_taken_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'tender_type_id'], ['tender_type.tenant_id', 'tender_type.id'], name=op.f('fk_payment_tender_type_id_tender_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'voided_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_payment_voided_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_payment_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_payment_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'receipt_number', name='uq_payment_receipt_number')
    )
    op.create_index('ix_payment_client_id', 'payment', ['tenant_id', 'client_id', sa.literal_column('received_at DESC'), sa.literal_column('id DESC')], unique=False)
    op.create_index('ix_payment_credit', 'payment', ['tenant_id', 'client_id', 'received_at'], unique=False, postgresql_where=sa.text("status = 'succeeded' AND unapplied_minor > 0"))
    op.create_index('ix_payment_location_id', 'payment', ['tenant_id', 'location_id', 'received_at'], unique=False)
    op.create_index(op.f('ix_payment_provider_account_id'), 'payment', ['tenant_id', 'provider_account_id'], unique=False)
    op.create_index(op.f('ix_payment_taken_by_staff_user_id'), 'payment', ['tenant_id', 'taken_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_payment_tender_type_id'), 'payment', ['tenant_id', 'tender_type_id'], unique=False)
    op.create_index('ix_payment_unsettled', 'payment', ['tenant_id', 'status', 'received_at'], unique=False, postgresql_where=sa.text("status IN ('initiated', 'unknown', 'requires_action', 'processing')"))
    op.create_index(op.f('ix_payment_voided_by_staff_user_id'), 'payment', ['tenant_id', 'voided_by_staff_user_id'], unique=False)
    op.create_index('uq_payment_provider_ref', 'payment', ['tenant_id', 'provider_account_id', 'provider_payment_ref'], unique=True, postgresql_where=sa.text('provider_payment_ref IS NOT NULL'))
    op.create_table('charge',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=True),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('invoice_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.Text(), server_default=sa.text("'standard'"), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('source_context', sa.Text(), nullable=False),
    sa.Column('source_type', sa.Text(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('source_line_no', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('additional_description', sa.Text(), nullable=True),
    sa.Column('internal_remarks', sa.Text(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=12, scale=3), server_default=sa.text('1'), nullable=False),
    sa.Column('unit_price_minor', sa.BigInteger(), nullable=False),
    sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('discount_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('net_minor', sa.BigInteger(), nullable=False),
    sa.Column('tax_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('total_minor', sa.BigInteger(), nullable=False),
    sa.Column('applied_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('bill_on', sa.Date(), nullable=False),
    sa.Column('revenue_on', sa.Date(), nullable=False),
    sa.Column('service_starts_on', sa.Date(), nullable=True),
    sa.Column('service_ends_on', sa.Date(), nullable=True),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=False),
    sa.Column('reverses_charge_id', sa.Uuid(), nullable=True),
    sa.Column('adjusts_charge_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('voided_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind <> 'reversal' AND status <> 'voided') OR reason IS NOT NULL", name=op.f('ck_charge_reason')),
    sa.CheckConstraint("(kind = 'reversal') = (reverses_charge_id IS NOT NULL) AND (kind = 'adjustment') = (adjusts_charge_id IS NOT NULL)", name=op.f('ck_charge_link')),
    sa.CheckConstraint("client_id IS NOT NULL OR source_context = 'pos'", name=op.f('ck_charge_client')),
    sa.CheckConstraint("kind IN ('adjustment', 'reversal') OR net_minor >= 0", name=op.f('ck_charge_sign')),
    sa.CheckConstraint("kind IN ('standard', 'adjustment', 'reversal', 'surcharge')", name=op.f('ck_charge_kind')),
    sa.CheckConstraint("status IN ('active', 'reversed', 'voided')", name=op.f('ck_charge_status')),
    sa.CheckConstraint('applied_minor BETWEEN LEAST(total_minor, 0) AND GREATEST(total_minor, 0)', name=op.f('ck_charge_applied')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_charge_quantity')),
    sa.CheckConstraint('service_ends_on IS NULL OR service_ends_on >= service_starts_on', name=op.f('ck_charge_service_period')),
    sa.CheckConstraint('total_minor = net_minor + tax_minor', name=op.f('ck_charge_total')),
    sa.ForeignKeyConstraint(['tenant_id', 'adjusts_charge_id'], ['charge.tenant_id', 'charge.id'], name=op.f('fk_charge_adjusts_charge_id_charge'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_charge_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_charge_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'invoice_id'], ['invoice.tenant_id', 'invoice.id'], name=op.f('fk_charge_invoice_id_invoice'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_charge_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_charge_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'reverses_charge_id'], ['charge.tenant_id', 'charge.id'], name=op.f('fk_charge_reverses_charge_id_charge'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'voided_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_charge_voided_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_charge_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_charge')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_charge_tenant_id_id'))
    )
    op.create_index(op.f('ix_charge_adjusts_charge_id'), 'charge', ['tenant_id', 'adjusts_charge_id'], unique=False)
    op.create_index('ix_charge_client_id', 'charge', ['tenant_id', 'client_id', sa.literal_column('bill_on DESC'), sa.literal_column('id DESC')], unique=False)
    op.create_index(op.f('ix_charge_created_by_staff_user_id'), 'charge', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_charge_invoice_id'), 'charge', ['tenant_id', 'invoice_id'], unique=False)
    op.create_index(op.f('ix_charge_location_id'), 'charge', ['tenant_id', 'location_id'], unique=False)
    op.create_index('ix_charge_open', 'charge', ['tenant_id', 'client_id', 'bill_on', 'id'], unique=False, postgresql_where=sa.text("status = 'active' AND applied_minor < total_minor"))
    op.create_index(op.f('ix_charge_revenue_category_id'), 'charge', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_index('ix_charge_revenue_on', 'charge', ['tenant_id', 'revenue_on', 'revenue_category_id'], unique=False)
    op.create_index('ix_charge_source', 'charge', ['tenant_id', 'source_context', 'source_type', 'source_id'], unique=False)
    op.create_index('ix_charge_uninvoiced', 'charge', ['tenant_id', 'location_id', 'id'], unique=False, postgresql_where=sa.text("invoice_id IS NULL AND status = 'active'"))
    op.create_index('ix_charge_uninvoiced_creator', 'charge', ['tenant_id', 'created_by_staff_user_id', 'id'], unique=False, postgresql_where=sa.text("invoice_id IS NULL AND status = 'active'"))
    op.create_index(op.f('ix_charge_voided_by_staff_user_id'), 'charge', ['tenant_id', 'voided_by_staff_user_id'], unique=False)
    op.create_index('uq_charge_origin', 'charge', ['tenant_id', 'source_context', 'source_type', 'source_id', 'source_line_no'], unique=True, postgresql_where=sa.text("kind = 'standard'"))
    op.create_index('uq_charge_reverses_charge_id', 'charge', ['tenant_id', 'reverses_charge_id'], unique=True, postgresql_where=sa.text('reverses_charge_id IS NOT NULL'))
    op.create_table('refund',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payment_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=True),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('method', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('provider_refund_ref', sa.Text(), nullable=True),
    sa.Column('refund_on', sa.Date(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('comments', sa.Text(), nullable=True),
    sa.Column('refund_batch_id', sa.Uuid(), nullable=True),
    sa.Column('failure_message', sa.Text(), nullable=True),
    sa.Column('issued_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("method IN ('original', 'external')", name=op.f('ck_refund_method')),
    sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed', 'cancelled')", name=op.f('ck_refund_status')),
    sa.CheckConstraint('amount_minor > 0', name=op.f('ck_refund_amount')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_refund_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'issued_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_refund_issued_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_refund_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'payment_id'], ['payment.tenant_id', 'payment.id'], name=op.f('fk_refund_payment_id_payment'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_refund_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refund')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_refund_tenant_id_id'))
    )
    op.create_index('ix_refund_batch', 'refund', ['tenant_id', 'refund_batch_id'], unique=False, postgresql_where=sa.text('refund_batch_id IS NOT NULL'))
    op.create_index(op.f('ix_refund_client_id'), 'refund', ['tenant_id', 'client_id'], unique=False)
    op.create_index(op.f('ix_refund_issued_by_staff_user_id'), 'refund', ['tenant_id', 'issued_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_refund_location_id'), 'refund', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_refund_payment_id'), 'refund', ['tenant_id', 'payment_id'], unique=False)
    op.create_index('ix_refund_pending', 'refund', ['tenant_id', 'created_at'], unique=False, postgresql_where=sa.text("status = 'pending'"))
    op.create_index('uq_refund_provider_ref', 'refund', ['tenant_id', 'provider_refund_ref'], unique=True, postgresql_where=sa.text('provider_refund_ref IS NOT NULL'))
    op.create_table('charge_tax',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('charge_id', sa.Uuid(), nullable=False),
    sa.Column('tax_id', sa.Uuid(), nullable=False),
    sa.Column('rate', sa.Numeric(precision=7, scale=6), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('is_excluded', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'charge_id'], ['charge.tenant_id', 'charge.id'], name=op.f('fk_charge_tax_charge_id_charge'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'tax_id'], ['tax.tenant_id', 'tax.id'], name=op.f('fk_charge_tax_tax_id_tax'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_charge_tax_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_charge_tax')),
    sa.UniqueConstraint('tenant_id', 'charge_id', 'tax_id', name='uq_charge_tax'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_charge_tax_tenant_id_id'))
    )
    op.create_index(op.f('ix_charge_tax_tax_id'), 'charge_tax', ['tenant_id', 'tax_id'], unique=False)
    op.create_table('ledger_entry',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('ledger_transaction_id', sa.Uuid(), nullable=False),
    sa.Column('account', sa.Text(), nullable=False),
    sa.Column('debit_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('credit_minor', sa.BigInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('effective_on', sa.Date(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=True),
    sa.Column('revenue_category_id', sa.Uuid(), nullable=True),
    sa.Column('tax_id', sa.Uuid(), nullable=True),
    sa.Column('charge_id', sa.Uuid(), nullable=True),
    sa.Column('payment_id', sa.Uuid(), nullable=True),
    sa.CheckConstraint("(account <> 'revenue' OR revenue_category_id IS NOT NULL) AND (account <> 'tax_payable' OR tax_id IS NOT NULL)", name=op.f('ck_ledger_entry_dimension')),
    sa.CheckConstraint("account IN ('receivable', 'revenue', 'tax_payable', 'funds_received', 'client_credit', 'disputed_funds')", name=op.f('ck_ledger_entry_account')),
    sa.CheckConstraint('debit_minor >= 0 AND credit_minor >= 0 AND (debit_minor = 0) <> (credit_minor = 0)', name=op.f('ck_ledger_entry_one_side')),
    sa.ForeignKeyConstraint(['tenant_id', 'charge_id'], ['charge.tenant_id', 'charge.id'], name=op.f('fk_ledger_entry_charge_id_charge'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_ledger_entry_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'ledger_transaction_id'], ['ledger_transaction.tenant_id', 'ledger_transaction.id'], name=op.f('fk_ledger_entry_ledger_transaction_id_ledger_transaction'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_ledger_entry_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'payment_id'], ['payment.tenant_id', 'payment.id'], name=op.f('fk_ledger_entry_payment_id_payment'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'revenue_category_id'], ['revenue_category.tenant_id', 'revenue_category.id'], name=op.f('fk_ledger_entry_revenue_category_id_revenue_category'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'tax_id'], ['tax.tenant_id', 'tax.id'], name=op.f('fk_ledger_entry_tax_id_tax'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_ledger_entry_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ledger_entry')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_ledger_entry_tenant_id_id'))
    )
    op.create_index('ix_ledger_entry_account', 'ledger_entry', ['tenant_id', 'account', 'effective_on'], unique=False)
    op.create_index(op.f('ix_ledger_entry_charge_id'), 'ledger_entry', ['tenant_id', 'charge_id'], unique=False)
    op.create_index('ix_ledger_entry_client_id', 'ledger_entry', ['tenant_id', 'client_id', 'account'], unique=False)
    op.create_index(op.f('ix_ledger_entry_ledger_transaction_id'), 'ledger_entry', ['tenant_id', 'ledger_transaction_id'], unique=False)
    op.create_index('ix_ledger_entry_location_id', 'ledger_entry', ['tenant_id', 'location_id', 'effective_on'], unique=False)
    op.create_index(op.f('ix_ledger_entry_payment_id'), 'ledger_entry', ['tenant_id', 'payment_id'], unique=False)
    op.create_index(op.f('ix_ledger_entry_revenue_category_id'), 'ledger_entry', ['tenant_id', 'revenue_category_id'], unique=False)
    op.create_index(op.f('ix_ledger_entry_tax_id'), 'ledger_entry', ['tenant_id', 'tax_id'], unique=False)
    op.create_table('payment_allocation',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('payment_id', sa.Uuid(), nullable=False),
    sa.Column('charge_id', sa.Uuid(), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('release_reason', sa.Text(), nullable=True),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'released') = (released_at IS NOT NULL AND release_reason IS NOT NULL)", name=op.f('ck_payment_allocation_release')),
    sa.CheckConstraint("release_reason IN ('unapplied', 'charge_reversed', 'charge_adjusted', 'payment_voided', 'payment_failed', 'dispute_opened', 'invoice_voided')", name=op.f('ck_payment_allocation_release_reason')),
    sa.CheckConstraint("status IN ('provisional', 'applied', 'released')", name=op.f('ck_payment_allocation_status')),
    sa.CheckConstraint('amount_minor > 0', name=op.f('ck_payment_allocation_amount')),
    sa.ForeignKeyConstraint(['tenant_id', 'charge_id'], ['charge.tenant_id', 'charge.id'], name=op.f('fk_payment_allocation_charge_id_charge'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_payment_allocation_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'payment_id'], ['payment.tenant_id', 'payment.id'], name=op.f('fk_payment_allocation_payment_id_payment'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_payment_allocation_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_allocation')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_payment_allocation_tenant_id_id'))
    )
    op.create_index(op.f('ix_payment_allocation_charge_id'), 'payment_allocation', ['tenant_id', 'charge_id'], unique=False)
    op.create_index(op.f('ix_payment_allocation_created_by_staff_user_id'), 'payment_allocation', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_index('ix_payment_allocation_live', 'payment_allocation', ['tenant_id', 'charge_id'], unique=False, postgresql_where=sa.text("status <> 'released'"))
    op.create_index('ix_payment_allocation_live_payment', 'payment_allocation', ['tenant_id', 'payment_id'], unique=False, postgresql_where=sa.text("status <> 'released'"))
    op.create_index(op.f('ix_payment_allocation_payment_id'), 'payment_allocation', ['tenant_id', 'payment_id'], unique=False)

    for table in TENANT_TABLES:
        enable_rls(table)
    for table in APPEND_ONLY_TABLES:
        enable_rls(table, append_only=True)

    # Every ledger transaction balances and has at least two lines (overview 3.6). Deferred to commit, because
    # the header and its lines are inserted one after another. Runs as the inserting role, inside its RLS.
    op.execute(
        """
        CREATE FUNCTION app.check_ledger_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            tx uuid := coalesce((to_jsonb(NEW) ->> 'ledger_transaction_id')::uuid, NEW.id);
            debits bigint;
            credits bigint;
            line_count integer;
        BEGIN
            SELECT coalesce(sum(debit_minor), 0), coalesce(sum(credit_minor), 0), count(*)
              INTO debits, credits, line_count
              FROM public.ledger_entry WHERE ledger_transaction_id = tx AND tenant_id = NEW.tenant_id;
            IF debits <> credits OR line_count < 2 THEN
                RAISE EXCEPTION 'ledger transaction %% is not balanced (debit %%, credit %%, lines %%)',
                    tx, debits, credits, line_count
                    USING ERRCODE = 'check_violation', CONSTRAINT = 'ct_ledger_transaction_balanced';
            END IF;
            RETURN NULL;
        END $$
        """.replace("%%", "%")
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE CONSTRAINT TRIGGER ct_ledger_transaction_balanced AFTER INSERT ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_ledger_balanced()"
        )


def downgrade() -> None:
    for table in (*reversed(APPEND_ONLY_TABLES), *reversed(TENANT_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION app.check_ledger_balanced()")
