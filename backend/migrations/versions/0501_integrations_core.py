"""integrations core (build module 16): api_key, webhook_endpoint, webhook_delivery, external_connection,
accounting_export and the append-only adapter_command_log.

Generated from the models, then completed by hand: enable_rls() per table.
Revision id 05xx is this module's range so parallel lanes do not collide; rebase down_revision on merge.

Revision ID: 0501
Revises: 0401
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = '0501'
down_revision = '0401'

TENANT_TABLES = (
    "api_key", "webhook_endpoint", "webhook_delivery", "external_connection", "accounting_export",
)  # fmt: skip
APPEND_ONLY_TABLES = ("adapter_command_log",)


def upgrade() -> None:
    op.create_table('adapter_command_log',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('port', sa.Text(), nullable=False),
    sa.Column('adapter', sa.Text(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('command', sa.Text(), nullable=False),
    sa.Column('arguments', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('outcome', sa.Text(), server_default=sa.text("'ok'"), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("outcome IN ('ok', 'simulated_failure')", name=op.f('ck_adapter_command_log_outcome')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_adapter_command_log_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_adapter_command_log_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_adapter_command_log')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_adapter_command_log_tenant_id_id'))
    )
    op.create_index(op.f('ix_adapter_command_log_location_id'), 'adapter_command_log', ['tenant_id', 'location_id'], unique=False)
    op.create_index('ix_adapter_command_log_occurred_at', 'adapter_command_log', ['tenant_id', 'occurred_at'], unique=False)
    op.create_table('api_key',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('key_prefix', sa.Text(), nullable=False),
    sa.Column('secret_hash', sa.Text(), nullable=False),
    sa.Column('previous_key_prefix', sa.Text(), nullable=True),
    sa.Column('previous_secret_hash', sa.Text(), nullable=True),
    sa.Column('previous_valid_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('scopes', postgresql.ARRAY(sa.Text()), nullable=False),
    sa.Column('location_ids', postgresql.ARRAY(sa.Uuid()), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'revoked')", name=op.f('ck_api_key_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_api_key_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_api_key_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_api_key')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_api_key_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'key_prefix', name=op.f('uq_api_key_tenant_id_key_prefix'))
    )
    op.create_index(op.f('ix_api_key_created_by_staff_user_id'), 'api_key', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_index('ix_api_key_previous_key_prefix', 'api_key', ['tenant_id', 'previous_key_prefix'], unique=False)
    op.create_table('external_connection',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('external_account_id', sa.Text(), nullable=True),
    sa.Column('external_account_name', sa.Text(), nullable=True),
    sa.Column('credentials_ciphertext', sa.Text(), nullable=True),
    sa.Column('settings', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('connected_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provider IN ('quickbooks_online', 'accounting_file', 'zoom')", name=op.f('ck_external_connection_provider')),
    sa.CheckConstraint("status IN ('pending', 'active', 'error', 'disconnected')", name=op.f('ck_external_connection_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'connected_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_external_connection_connected_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_external_connection_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_external_connection_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_external_connection')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_external_connection_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'provider', 'location_id', name='uq_external_connection', postgresql_nulls_not_distinct=True)
    )
    op.create_index(op.f('ix_external_connection_connected_by_staff_user_id'), 'external_connection', ['tenant_id', 'connected_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_external_connection_location_id'), 'external_connection', ['tenant_id', 'location_id'], unique=False)
    op.create_table('webhook_endpoint',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('event_types', postgresql.ARRAY(sa.Text()), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('secret_ciphertext', sa.Text(), nullable=False),
    sa.Column('previous_secret_ciphertext', sa.Text(), nullable=True),
    sa.Column('previous_secret_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('disabled_reason', sa.Text(), nullable=True),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'paused', 'disabled')", name=op.f('ck_webhook_endpoint_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_webhook_endpoint_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_webhook_endpoint_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_endpoint')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_webhook_endpoint_tenant_id_id'))
    )
    op.create_index('ix_webhook_endpoint_active', 'webhook_endpoint', ['tenant_id'], unique=False, postgresql_where=sa.text("status = 'active'"))
    op.create_index(op.f('ix_webhook_endpoint_created_by_staff_user_id'), 'webhook_endpoint', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_table('accounting_export',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('external_connection_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('business_on', sa.Date(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('totals', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('external_id', sa.Text(), nullable=True),
    sa.Column('doc_number', sa.Text(), nullable=True),
    sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'posted', 'completed_with_warnings', 'failed', 'skipped')", name=op.f('ck_accounting_export_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'external_connection_id'], ['external_connection.tenant_id', 'external_connection.id'], name=op.f('fk_accounting_export_external_connection_id_external_connection'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_accounting_export_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_accounting_export_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_accounting_export')),
    sa.UniqueConstraint('tenant_id', 'external_connection_id', 'location_id', 'business_on', name='uq_accounting_export_day'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_accounting_export_tenant_id_id'))
    )
    op.create_index(op.f('ix_accounting_export_external_connection_id'), 'accounting_export', ['tenant_id', 'external_connection_id'], unique=False)
    op.create_index(op.f('ix_accounting_export_location_id'), 'accounting_export', ['tenant_id', 'location_id'], unique=False)
    op.create_table('webhook_delivery',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('webhook_endpoint_id', sa.Uuid(), nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_response_status', sa.Integer(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('last_duration_ms', sa.Integer(), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'delivered', 'failed', 'abandoned')", name=op.f('ck_webhook_delivery_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'webhook_endpoint_id'], ['webhook_endpoint.tenant_id', 'webhook_endpoint.id'], name=op.f('fk_webhook_delivery_webhook_endpoint_id_webhook_endpoint'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_webhook_delivery_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_delivery')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_webhook_delivery_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'webhook_endpoint_id', 'event_id', name='uq_webhook_delivery_endpoint_event')
    )
    op.create_index('ix_webhook_delivery_due', 'webhook_delivery', ['tenant_id', 'next_attempt_at'], unique=False, postgresql_where=sa.text("status = 'pending'"))
    op.create_index(op.f('ix_webhook_delivery_webhook_endpoint_id'), 'webhook_delivery', ['tenant_id', 'webhook_endpoint_id'], unique=False)

    for table in TENANT_TABLES:
        enable_rls(table)
    for table in APPEND_ONLY_TABLES:
        enable_rls(table, append_only=True)


def downgrade() -> None:
    for table in ("webhook_delivery", "accounting_export", *APPEND_ONLY_TABLES, *TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
