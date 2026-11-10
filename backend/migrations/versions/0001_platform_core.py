"""platform core: kernel (extensions, app schema, RLS functions) and every platform table of build module 1.

Generated from the models, then completed by hand: the preamble, enable_rls() per table and the grants.

Revision ID: 0001
Revises: 
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "0001"
down_revision = None

TENANT_TABLES = (
    "tenant_domain", "location", "facility_hours", "identity", "staff_user", "user_location_access",
    "auth_token", "auth_session", "role", "role_permission", "user_permission_override",
    "outbox_event", "processed_event", "idempotency_key",
)
APPEND_ONLY_TABLES = ("audit_event",)


def upgrade() -> None:
    # Every new tenant-owned table must call enable_rls("<table>") (append_only=True for ledgers and logs).
    # --- kernel -----------------------------------------------------------------------------------------
    for extension in ("btree_gist", "citext", "pg_trgm"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    # Unset or '' (a pooled connection after its first transaction) yields NULL, so the policy fails closed.
    op.execute(
        "CREATE FUNCTION app.current_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$"
    )
    # UUIDv7 column default so raw SQL seeds work; the application normally supplies ids (app.core.ids).
    op.execute(
        "CREATE FUNCTION app.uuid_v7() RETURNS uuid LANGUAGE sql VOLATILE AS $$ "
        "SELECT encode(set_bit(set_bit(overlay(uuid_send(gen_random_uuid()) placing "
        "substring(int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3) FROM 1 FOR 6), "
        "52, 1), 53, 1), 'hex')::uuid $$"
    )
    op.execute("GRANT USAGE ON SCHEMA app TO fh_app, fh_platform")
    op.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO fh_app, fh_platform")

    # --- tables -----------------------------------------------------------------------------------------
    op.create_table('subscription_plan',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscription_plan')),
    sa.UniqueConstraint('code', name='uq_subscription_plan_code')
    )
    op.create_table('tenant',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('slug', postgresql.CITEXT(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), server_default=sa.text("'USD'"), nullable=False),
    sa.Column('default_time_zone', sa.Text(), nullable=False),
    sa.Column('locale', sa.Text(), server_default=sa.text("'en-US'"), nullable=False),
    sa.Column('subscription_plan_id', sa.Uuid(), nullable=True),
    sa.Column('billing_cycle', sa.Text(), nullable=True),
    sa.Column('trial_ends_on', sa.Date(), nullable=True),
    sa.Column('staff_mfa_policy', sa.Text(), server_default=sa.text("'privileged'"), nullable=False),
    sa.Column('platform_billing_ref', sa.Text(), nullable=True),
    sa.Column('billing_locked_through_on', sa.Date(), nullable=True),
    sa.Column('email_sending_state', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_listed_in_app_directory', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('app_directory_name', sa.Text(), nullable=True),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("billing_cycle IN ('monthly', 'annual')", name=op.f('ck_tenant_billing_cycle')),
    sa.CheckConstraint("email_sending_state IN ('active', 'marketing_paused', 'suspended')", name=op.f('ck_tenant_email_sending_state')),
    sa.CheckConstraint("staff_mfa_policy IN ('optional', 'privileged', 'all')", name=op.f('ck_tenant_staff_mfa_policy')),
    sa.CheckConstraint("status IN ('active', 'suspended', 'closed')", name=op.f('ck_tenant_status')),
    sa.ForeignKeyConstraint(['subscription_plan_id'], ['subscription_plan.id'], name=op.f('fk_tenant_subscription_plan_id_subscription_plan'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenant')),
    sa.UniqueConstraint('slug', name='uq_tenant_slug')
    )
    op.create_table('idempotency_key',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('request_hash', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=True),
    sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_idempotency_key_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_idempotency_key')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_idempotency_key_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'scope', 'key', name='uq_idempotency_key_tenant_scope_key')
    )
    op.create_index('ix_idempotency_key_expiry', 'idempotency_key', ['expires_at'], unique=False)
    op.create_table('identity',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('email', postgresql.CITEXT(), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('password_hash', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'invited'"), nullable=False),
    sa.Column('merged_into_identity_id', sa.Uuid(), nullable=True),
    sa.Column('failed_attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('locked_until_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_sign_in_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('staff', 'client')", name=op.f('ck_identity_kind')),
    sa.CheckConstraint("status IN ('invited', 'active', 'disabled', 'merged')", name=op.f('ck_identity_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'merged_into_identity_id'], ['identity.tenant_id', 'identity.id'], name=op.f('fk_identity_merged_into_identity_id_identity'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_identity_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_identity')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_identity_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'kind', 'email', name='uq_identity_kind_email')
    )
    op.create_index(op.f('ix_identity_merged_into_identity_id'), 'identity', ['tenant_id', 'merged_into_identity_id'], unique=False)
    op.create_table('location',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('slug', postgresql.CITEXT(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('public_name', sa.Text(), nullable=False),
    sa.Column('address_line1', sa.Text(), nullable=True),
    sa.Column('address_line2', sa.Text(), nullable=True),
    sa.Column('city', sa.Text(), nullable=True),
    sa.Column('region', sa.Text(), nullable=True),
    sa.Column('postal_code', sa.Text(), nullable=True),
    sa.Column('country_code', sa.CHAR(length=2), nullable=True),
    sa.Column('phone', sa.Text(), nullable=True),
    sa.Column('email', postgresql.CITEXT(), nullable=True),
    sa.Column('alert_email', postgresql.CITEXT(), nullable=True),
    sa.Column('website_url', sa.Text(), nullable=True),
    sa.Column('time_zone', sa.Text(), nullable=False),
    sa.Column('membership_renewal_run_time', sa.Time(), server_default=sa.text("'01:00'"), nullable=False),
    sa.Column('package_renewal_run_time', sa.Time(), server_default=sa.text("'01:30'"), nullable=False),
    sa.Column('autopay_run_time', sa.Time(), server_default=sa.text("'06:00'"), nullable=False),
    sa.Column('decline_email_mode', sa.Text(), server_default=sa.text("'digest'"), nullable=False),
    sa.Column('time_clock_rounding', sa.Text(), server_default=sa.text("'none'"), nullable=False),
    sa.Column('time_clock_rounding_min', sa.SmallInteger(), server_default=sa.text('15'), nullable=False),
    sa.Column('is_time_clock_network_restricted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('accepted_card_brands', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('is_gdpr_mode', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("decline_email_mode IN ('digest', 'per_decline')", name=op.f('ck_location_decline_email_mode')),
    sa.CheckConstraint("status IN ('active', 'inactive')", name=op.f('ck_location_status')),
    sa.CheckConstraint("time_clock_rounding IN ('none', 'up', 'down')", name=op.f('ck_location_time_clock_rounding')),
    sa.CheckConstraint('time_clock_rounding_min IN (5, 6, 10, 15, 30)', name=op.f('ck_location_time_clock_rounding_min')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_location_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_location')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_location_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'name', name='uq_location_name'),
    sa.UniqueConstraint('tenant_id', 'slug', name='uq_location_slug')
    )
    op.create_table('outbox_event',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('aggregate_type', sa.Text(), nullable=False),
    sa.Column('aggregate_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_outbox_event_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox_event')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_outbox_event_tenant_id_id'))
    )
    op.create_index('ix_outbox_event_aggregate', 'outbox_event', ['tenant_id', 'aggregate_type', 'aggregate_id'], unique=False)
    op.create_index('ix_outbox_event_unpublished', 'outbox_event', ['occurred_at'], unique=False, postgresql_where=sa.text('published_at IS NULL'))
    op.create_table('processed_event',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('consumer_name', sa.Text(), nullable=False),
    sa.Column('event_id', sa.Uuid(), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_processed_event_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_processed_event')),
    sa.UniqueConstraint('tenant_id', 'consumer_name', 'event_id', name='uq_processed_event'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_processed_event_tenant_id_id'))
    )
    op.create_table('role',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', postgresql.CITEXT(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_system', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('system_key', sa.Text(), nullable=True),
    sa.Column('cloned_from_role_id', sa.Uuid(), nullable=True),
    sa.Column('default_ip_policy', sa.Text(), server_default=sa.text("'any'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("default_ip_policy IN ('any', 'facility_networks')", name=op.f('ck_role_default_ip_policy')),
    sa.CheckConstraint('(system_key IS NOT NULL) = is_system', name=op.f('ck_role_system')),
    sa.ForeignKeyConstraint(['tenant_id', 'cloned_from_role_id'], ['role.tenant_id', 'role.id'], name=op.f('fk_role_cloned_from_role_id_role'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_role_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_role_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'name', name='uq_role_name')
    )
    op.create_index(op.f('ix_role_cloned_from_role_id'), 'role', ['tenant_id', 'cloned_from_role_id'], unique=False)
    op.create_index('uq_role_system_key', 'role', ['tenant_id', 'system_key'], unique=True, postgresql_where=sa.text('system_key IS NOT NULL'))
    op.create_table('tenant_domain',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('host', postgresql.CITEXT(), nullable=False),
    sa.Column('kind', sa.Text(), server_default=sa.text("'subdomain'"), nullable=False),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('subdomain', 'custom')", name=op.f('ck_tenant_domain_kind')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_tenant_domain_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenant_domain')),
    sa.UniqueConstraint('host', name='uq_tenant_domain_host'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_tenant_domain_tenant_id_id'))
    )
    op.create_index('uq_tenant_domain_primary', 'tenant_domain', ['tenant_id'], unique=True, postgresql_where=sa.text('is_primary'))
    op.create_table('audit_event',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_type', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('actor_label', sa.Text(), nullable=False),
    sa.Column('on_behalf_of_client_id', sa.Uuid(), nullable=True),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('entity_type', sa.Text(), nullable=False),
    sa.Column('entity_id', sa.Uuid(), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('request_id', sa.Text(), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('auth_session_id', sa.Uuid(), nullable=True),
    sa.Column('impersonator_ref', sa.Text(), nullable=True),
    sa.Column('retain_until_on', sa.Date(), nullable=False),
    sa.CheckConstraint("actor_type IN ('staff', 'client', 'api_key', 'kiosk', 'system')", name=op.f('ck_audit_event_actor_type')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_audit_event_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_audit_event_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_event')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_audit_event_tenant_id_id'))
    )
    op.create_index('ix_audit_event_actor', 'audit_event', ['tenant_id', 'actor_id', 'id'], unique=False)
    op.create_index('ix_audit_event_entity', 'audit_event', ['tenant_id', 'entity_type', 'entity_id', 'id'], unique=False)
    op.create_index(op.f('ix_audit_event_location_id'), 'audit_event', ['tenant_id', 'location_id'], unique=False)
    op.create_index('ix_audit_event_retention', 'audit_event', ['retain_until_on'], unique=False)
    op.create_table('auth_token',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('identity_id', sa.Uuid(), nullable=True),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("purpose IN ('magic_link', 'password_reset', 'invite', 'email_verify', 'email_change', 'relationship_confirm')", name=op.f('ck_auth_token_purpose')),
    sa.ForeignKeyConstraint(['tenant_id', 'identity_id'], ['identity.tenant_id', 'identity.id'], name=op.f('fk_auth_token_identity_id_identity'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_auth_token_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_token')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_auth_token_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'token_hash', name='uq_auth_token_hash')
    )
    op.create_index('ix_auth_token_pending', 'auth_token', ['tenant_id', 'identity_id', 'purpose'], unique=False, postgresql_where=sa.text('consumed_at IS NULL'))
    op.create_table('facility_hours',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('weekday', sa.SmallInteger(), nullable=False),
    sa.Column('opens_time', sa.Time(), nullable=True),
    sa.Column('closes_time', sa.Time(), nullable=True),
    sa.Column('is_closed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('is_closed OR (opens_time IS NOT NULL AND closes_time IS NOT NULL AND closes_time > opens_time)', name=op.f('ck_facility_hours_window')),
    sa.CheckConstraint('weekday BETWEEN 1 AND 7', name=op.f('ck_facility_hours_weekday')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_facility_hours_location_id_location'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_facility_hours_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_facility_hours')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_facility_hours_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'location_id', 'weekday', name='uq_facility_hours')
    )
    op.create_table('role_permission',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('permission_key', sa.Text(), nullable=False),
    sa.Column('subject_type', sa.Text(), nullable=True),
    sa.Column('subject_id', sa.Uuid(), nullable=True),
    sa.Column('is_allowed', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('subject_id IS NULL OR subject_type IS NOT NULL', name=op.f('ck_role_permission_subject')),
    sa.ForeignKeyConstraint(['tenant_id', 'role_id'], ['role.tenant_id', 'role.id'], name=op.f('fk_role_permission_role_id_role'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_role_permission_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role_permission')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_role_permission_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'role_id', 'permission_key', 'subject_id', name='uq_role_permission', postgresql_nulls_not_distinct=True)
    )
    op.create_table('staff_user',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('identity_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('first_name', sa.Text(), nullable=False),
    sa.Column('last_name', sa.Text(), nullable=False),
    sa.Column('mobile_phone', sa.Text(), nullable=True),
    sa.Column('linked_resource_id', sa.Uuid(), nullable=True),
    sa.Column('is_attendance_notified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('ip_policy', sa.Text(), server_default=sa.text("'any'"), nullable=False),
    sa.Column('has_all_location_access', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_system_support', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('access_expires_on', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('preferences', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("ip_policy IN ('any', 'facility_networks')", name=op.f('ck_staff_user_ip_policy')),
    sa.ForeignKeyConstraint(['tenant_id', 'identity_id'], ['identity.tenant_id', 'identity.id'], name=op.f('fk_staff_user_identity_id_identity'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'role_id'], ['role.tenant_id', 'role.id'], name=op.f('fk_staff_user_role_id_role'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_staff_user_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_staff_user')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_staff_user_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'identity_id', name='uq_staff_user_identity')
    )
    op.create_index(op.f('ix_staff_user_linked_resource_id'), 'staff_user', ['tenant_id', 'linked_resource_id'], unique=False)
    op.create_index(op.f('ix_staff_user_role_id'), 'staff_user', ['tenant_id', 'role_id'], unique=False)
    op.create_table('auth_session',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('identity_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('access_token_hash', sa.Text(), nullable=False),
    sa.Column('access_expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('refresh_token_hash', sa.Text(), nullable=True),
    sa.Column('previous_refresh_token_hash', sa.Text(), nullable=True),
    sa.Column('refresh_rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('idle_expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('absolute_expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('mfa_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('elevated_until_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('impersonator_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('target_client_id', sa.Uuid(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_reason', sa.Text(), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'impersonation') = (impersonator_staff_user_id IS NOT NULL)", name=op.f('ck_auth_session_impersonation')),
    sa.CheckConstraint("kind IN ('web', 'mobile', 'impersonation')", name=op.f('ck_auth_session_kind')),
    sa.CheckConstraint("revoked_reason IN ('sign_out', 'rotation_reuse', 'password_reset', 'admin', 'expired', 'disabled')", name=op.f('ck_auth_session_revoked_reason')),
    sa.ForeignKeyConstraint(['tenant_id', 'identity_id'], ['identity.tenant_id', 'identity.id'], name=op.f('fk_auth_session_identity_id_identity'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'impersonator_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_auth_session_impersonator_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_auth_session_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_session')),
    sa.UniqueConstraint('tenant_id', 'access_token_hash', name='uq_auth_session_access'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_auth_session_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'refresh_token_hash', name='uq_auth_session_refresh')
    )
    op.create_index(op.f('ix_auth_session_impersonator_staff_user_id'), 'auth_session', ['tenant_id', 'impersonator_staff_user_id'], unique=False)
    op.create_index('ix_auth_session_live', 'auth_session', ['tenant_id', 'identity_id'], unique=False, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_index('ix_auth_session_previous_refresh', 'auth_session', ['tenant_id', 'previous_refresh_token_hash'], unique=False, postgresql_where=sa.text('previous_refresh_token_hash IS NOT NULL'))
    op.create_index('ix_auth_session_purge', 'auth_session', ['absolute_expires_at'], unique=False)
    op.create_table('user_location_access',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_user_location_access_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_user_location_access_staff_user_id_staff_user'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_user_location_access_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_location_access')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_user_location_access_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'staff_user_id', 'location_id', name='uq_user_location_access')
    )
    op.create_index(op.f('ix_user_location_access_location_id'), 'user_location_access', ['tenant_id', 'location_id'], unique=False)
    op.create_index('uq_user_location_access_primary', 'user_location_access', ['tenant_id', 'staff_user_id'], unique=True, postgresql_where=sa.text('is_primary'))
    op.create_table('user_permission_override',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('permission_key', sa.Text(), nullable=False),
    sa.Column('subject_type', sa.Text(), nullable=True),
    sa.Column('subject_id', sa.Uuid(), nullable=True),
    sa.Column('is_allowed', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_user_permission_override_staff_user_id_staff_user'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_user_permission_override_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_permission_override')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_user_permission_override_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'staff_user_id', 'permission_key', 'subject_id', name='uq_user_permission_override', postgresql_nulls_not_distinct=True)
    )

    # --- row-level security and grants (overview 3.4, ADR 0001 section 3) -----------------------------
    for table in TENANT_TABLES:
        enable_rls(table)
    for table in APPEND_ONLY_TABLES:
        enable_rls(table, append_only=True)
    # tenant has no tenant_id: its own id is the tenant. fh_app may read and update only its own row;
    # rows are inserted by fh_platform during provisioning.
    enable_rls("tenant", tenant_column="id", grants="SELECT, UPDATE")
    op.execute("GRANT SELECT ON subscription_plan TO fh_app")
    op.execute("GRANT SELECT ON alembic_version TO fh_app")  # readiness compares it with the code's head
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant, subscription_plan TO fh_platform")
    op.execute("GRANT SELECT, INSERT, DELETE ON tenant_domain TO fh_platform")
    op.execute("GRANT SELECT, UPDATE, DELETE ON outbox_event TO fh_platform")  # relay and purge


def downgrade() -> None:
    for table in (*APPEND_ONLY_TABLES, *reversed(TENANT_TABLES), "tenant", "subscription_plan"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION app.uuid_v7()")
    op.execute("DROP FUNCTION app.current_tenant_id()")
    op.execute("DROP SCHEMA app")
