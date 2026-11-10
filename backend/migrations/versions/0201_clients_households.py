"""clients households (build module 4): the rest of data-model-people section 1, the engagement consent slice
(communication_preference, consent_event) and platform data_subject_request.

Generated from the models, then completed by hand: enable_rls() per table (consent_event and client_merge are
append-only), the new check constraints on the existing `client` table, the email trigram index, and the two
SECURITY DEFINER functions the data model sanctions for append-only tables (amendment A7): re-pointing
consent_event on merge and erasing it.

Revision ID: 0201
Revises: 0002 (the integrator re-points this to the previous lane's last revision)
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = '0201'
down_revision = '0002'

TENANT_TABLES = (
    "client_category", "client_field_policy", "client_settings", "custom_field", "note_subject",
    "referral_category", "relationship_type", "tag", "client_location_settings", "client_alert", "client_email",
    "client_emergency_contact", "client_note", "client_recent_view", "client_relationship", "client_tag",
    "client_task", "data_subject_request", "communication_preference",
)
APPEND_ONLY_TABLES = ("client_merge", "consent_event")
# New checks on the existing table (autogenerate does not see check constraints on an altered table).
CLIENT_CHECKS = {
    "phone_home": "phone_home ~ '^\\+[1-9][0-9]{6,14}$'",
    "phone_work": "phone_work ~ '^\\+[1-9][0-9]{6,14}$'",
    "gender": "gender IN ('female', 'male', 'non_binary', 'undisclosed')",
    "created_via": "created_via IN ('staff', 'portal', 'registration', 'kiosk', 'api', 'import', 'provider')",
    "merged": "merged_into_id IS NULL OR (status = 'disabled' AND merged_into_id <> id)",
    "custom_values": "jsonb_typeof(custom_values) = 'object'",
    "discount_pct": "discount_pct BETWEEN 0 AND 100",
    "country_code": "country_code ~ '^[A-Z]{2}$'",
}
# consent_event grants fh_app SELECT, INSERT only. These two functions, owned by fh_owner, are the only paths
# that change existing rows; FORCE ROW LEVEL SECURITY keeps them inside the caller's tenant.
REPOINT_CONSENT = """
CREATE FUNCTION app.repoint_consent_event(p_from uuid, p_to uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE moved integer;
BEGIN
    UPDATE consent_event SET client_id = p_to WHERE client_id = p_from AND tenant_id = app.current_tenant_id();
    GET DIAGNOSTICS moved = ROW_COUNT;
    RETURN moved;
END $$
"""
# Erasure (security-baseline 4.3): opt-ins go; opt-outs stay with the address hashed, so a suppression holds.
ERASE_CONSENT = """
CREATE FUNCTION app.erase_consent_event(p_client uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE kept integer;
BEGIN
    DELETE FROM consent_event WHERE client_id = p_client AND kind = 'opt_in' AND tenant_id = app.current_tenant_id();
    UPDATE consent_event
       SET address = CASE WHEN address IS NULL THEN NULL ELSE encode(sha256(lower(address::text)::bytea), 'hex') END,
           note = CASE WHEN note IS NULL THEN NULL ELSE '[erased]' END, ip = NULL
     WHERE client_id = p_client AND tenant_id = app.current_tenant_id();
    GET DIAGNOSTICS kept = ROW_COUNT;
    RETURN kept;
END $$
"""


def upgrade() -> None:
    op.create_table('client_category',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_category_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_category')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_category_tenant_id_id'))
    )
    op.create_index('uq_client_category_name', 'client_category', ['tenant_id', sa.literal_column('lower(name)')], unique=True)
    op.create_table('client_field_policy',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('field_key', sa.Text(), nullable=False),
    sa.Column('capture_context', sa.Text(), nullable=False),
    sa.Column('requirement', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("capture_context IN ('staff', 'registration', 'portal')", name=op.f('ck_client_field_policy_capture_context')),
    sa.CheckConstraint("requirement IN ('hidden', 'optional', 'required')", name=op.f('ck_client_field_policy_requirement')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_field_policy_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_field_policy')),
    sa.UniqueConstraint('tenant_id', 'field_key', 'capture_context', name='uq_client_field_policy_field_context'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_field_policy_tenant_id_id'))
    )
    op.create_table('client_settings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('default_gender', sa.Text(), nullable=True),
    sa.Column('is_member_number_auto_generated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('member_number_trigger', sa.Text(), server_default=sa.text("'membership_sold'"), nullable=False),
    sa.Column('member_number_prefix', sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column('is_verification_email_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_own_clients_scope_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("default_gender IN ('female', 'male', 'non_binary', 'undisclosed')", name=op.f('ck_client_settings_default_gender')),
    sa.CheckConstraint("member_number_trigger IN ('client_created', 'membership_sold')", name=op.f('ck_client_settings_member_number_trigger')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_settings_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_settings')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_settings_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', name='uq_client_settings_tenant')
    )
    op.create_table('custom_field',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('data_type', sa.Text(), server_default=sa.text("'text'"), nullable=False),
    sa.Column('choices', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(data_type = 'choice') = (choices IS NOT NULL)", name=op.f('ck_custom_field_choices')),
    sa.CheckConstraint("data_type IN ('text', 'number', 'date', 'boolean', 'choice')", name=op.f('ck_custom_field_data_type')),
    sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,39}$'", name=op.f('ck_custom_field_key')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_custom_field_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_custom_field')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_custom_field_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'key', name='uq_custom_field_key')
    )
    op.create_table('note_subject',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_note_subject_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_note_subject')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_note_subject_tenant_id_id'))
    )
    op.create_index('uq_note_subject_label', 'note_subject', ['tenant_id', sa.literal_column('lower(label)')], unique=True)
    op.create_table('referral_category',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_referral_category_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_referral_category')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_referral_category_tenant_id_id'))
    )
    op.create_index('uq_referral_category_name', 'referral_category', ['tenant_id', sa.literal_column('lower(name)')], unique=True)
    op.create_table('relationship_type',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('inverse_type_id', sa.Uuid(), nullable=True),
    sa.Column('grants_acting_rights', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_guardianship', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_portal_selectable', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_system', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'inverse_type_id'], ['relationship_type.tenant_id', 'relationship_type.id'], name=op.f('fk_relationship_type_inverse_type_id_relationship_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_relationship_type_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_relationship_type')),
    sa.UniqueConstraint('tenant_id', 'code', name='uq_relationship_type_code'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_relationship_type_tenant_id_id'))
    )
    op.create_index(op.f('ix_relationship_type_inverse_type_id'), 'relationship_type', ['tenant_id', 'inverse_type_id'], unique=False)
    op.create_table('tag',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('sport', 'season', 'custom')", name=op.f('ck_tag_kind')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_tag_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tag')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_tag_tenant_id_id'))
    )
    op.create_index('uq_tag_kind_label', 'tag', ['tenant_id', 'kind', sa.literal_column('lower(label)')], unique=True)
    op.create_table('client_location_settings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('is_portal_photo_edit_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_client_location_settings_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_location_settings_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_location_settings')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_location_settings_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'location_id', name='uq_client_location_settings_location')
    )
    op.create_table('client_alert',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), server_default=sa.text("'general'"), nullable=False),
    sa.Column('severity', sa.Text(), server_default=sa.text("'info'"), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('shows_on_profile', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('shows_on_check_in', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('shows_on_booking', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('starts_on', sa.Date(), nullable=True),
    sa.Column('ends_on', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('general', 'medical', 'injury', 'conduct')", name=op.f('ck_client_alert_kind')),
    sa.CheckConstraint("severity IN ('info', 'warning', 'critical')", name=op.f('ck_client_alert_severity')),
    sa.CheckConstraint('ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on', name=op.f('ck_client_alert_dates')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_alert_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'created_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_alert_created_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_alert_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_alert')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_alert_tenant_id_id'))
    )
    op.create_index('ix_client_alert_client_active', 'client_alert', ['tenant_id', 'client_id'], unique=False, postgresql_where=sa.text('is_active'))
    op.create_index(op.f('ix_client_alert_created_by_staff_user_id'), 'client_alert', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_table('client_email',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('email', postgresql.CITEXT(), nullable=False),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('verification_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verification_token_hash', sa.Text(), nullable=True),
    sa.Column('verification_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("email ~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$'", name=op.f('ck_client_email_email')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_email_client_id_client'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_email_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_email')),
    sa.UniqueConstraint('tenant_id', 'client_id', 'email', name='uq_client_email_client_email'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_email_tenant_id_id'))
    )
    op.create_index('ix_client_email_email', 'client_email', ['tenant_id', 'email'], unique=False)
    op.execute("CREATE INDEX ix_client_email_trgm ON client_email USING gin ((email::text) gin_trgm_ops)")
    op.create_index('uq_client_email_primary', 'client_email', ['tenant_id', 'client_id'], unique=True, postgresql_where=sa.text('is_primary'))
    op.create_index('uq_client_email_token', 'client_email', ['tenant_id', 'verification_token_hash'], unique=True, postgresql_where=sa.text('verification_token_hash IS NOT NULL'))
    op.create_table('client_emergency_contact',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('relationship_label', sa.Text(), nullable=True),
    sa.Column('phone', sa.Text(), nullable=True),
    sa.Column('phone_alt', sa.Text(), nullable=True),
    sa.Column('email', postgresql.CITEXT(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('position >= 1', name=op.f('ck_client_emergency_contact_position')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_emergency_contact_client_id_client'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_emergency_contact_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_emergency_contact')),
    sa.UniqueConstraint('tenant_id', 'client_id', 'position', name='uq_client_emergency_contact_position'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_emergency_contact_tenant_id_id'))
    )
    op.create_table('client_merge',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('survivor_client_id', sa.Uuid(), nullable=False),
    sa.Column('merged_client_id', sa.Uuid(), nullable=False),
    sa.Column('performed_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('performed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('backfilled_fields', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('precheck', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'merged_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_merge_merged_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'performed_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_merge_performed_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'survivor_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_merge_survivor_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_merge_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_merge')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_merge_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'merged_client_id', name='uq_client_merge_merged')
    )
    op.create_index(op.f('ix_client_merge_performed_by_staff_user_id'), 'client_merge', ['tenant_id', 'performed_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_client_merge_survivor_client_id'), 'client_merge', ['tenant_id', 'survivor_client_id'], unique=False)
    op.create_table('client_note',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('note_subject_id', sa.Uuid(), nullable=True),
    sa.Column('subject_text', sa.Text(), nullable=True),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('call', 'email', 'task', 'other')", name=op.f('ck_client_note_kind')),
    sa.CheckConstraint('num_nonnulls(note_subject_id, subject_text) = 1', name=op.f('ck_client_note_subject')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_note_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_client_note_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'note_subject_id'], ['note_subject.tenant_id', 'note_subject.id'], name=op.f('fk_client_note_note_subject_id_note_subject'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_note_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_note_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_note')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_note_tenant_id_id'))
    )
    op.create_index('ix_client_note_client', 'client_note', ['tenant_id', 'client_id', sa.literal_column('occurred_at DESC')], unique=False)
    op.create_index(op.f('ix_client_note_location_id'), 'client_note', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_client_note_note_subject_id'), 'client_note', ['tenant_id', 'note_subject_id'], unique=False)
    op.create_index(op.f('ix_client_note_staff_user_id'), 'client_note', ['tenant_id', 'staff_user_id'], unique=False)
    op.create_table('client_recent_view',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('viewed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_recent_view_client_id_client'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_recent_view_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_recent_view_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_recent_view')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_recent_view_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'staff_user_id', 'client_id', name='uq_client_recent_view_user_client')
    )
    op.create_index(op.f('ix_client_recent_view_client_id'), 'client_recent_view', ['tenant_id', 'client_id'], unique=False)
    op.create_index('ix_client_recent_view_user', 'client_recent_view', ['tenant_id', 'staff_user_id', sa.literal_column('viewed_at DESC')], unique=False)
    op.create_table('client_relationship',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('from_client_id', sa.Uuid(), nullable=False),
    sa.Column('to_client_id', sa.Uuid(), nullable=False),
    sa.Column('relationship_type_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column('created_via', sa.Text(), server_default=sa.text("'staff'"), nullable=False),
    sa.Column('requested_by_identity_id', sa.Uuid(), nullable=True),
    sa.Column('confirmation_token_hash', sa.Text(), nullable=True),
    sa.Column('confirmation_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("created_via IN ('staff', 'portal', 'registration', 'provider', 'import')", name=op.f('ck_client_relationship_created_via')),
    sa.CheckConstraint("status IN ('pending', 'active', 'declined', 'ended')", name=op.f('ck_client_relationship_status')),
    sa.CheckConstraint('from_client_id <> to_client_id', name=op.f('ck_client_relationship_distinct')),
    sa.ForeignKeyConstraint(['tenant_id', 'from_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_relationship_from_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'relationship_type_id'], ['relationship_type.tenant_id', 'relationship_type.id'], name=op.f('fk_client_relationship_relationship_type_id_relationship_type'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'requested_by_identity_id'], ['identity.tenant_id', 'identity.id'], name=op.f('fk_client_relationship_requested_by_identity_id_identity'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'to_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_relationship_to_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_relationship_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_relationship')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_relationship_tenant_id_id'))
    )
    op.create_index('ix_client_relationship_from', 'client_relationship', ['tenant_id', 'from_client_id', 'status'], unique=False)
    op.create_index(op.f('ix_client_relationship_relationship_type_id'), 'client_relationship', ['tenant_id', 'relationship_type_id'], unique=False)
    op.create_index(op.f('ix_client_relationship_requested_by_identity_id'), 'client_relationship', ['tenant_id', 'requested_by_identity_id'], unique=False)
    op.create_index('ix_client_relationship_to', 'client_relationship', ['tenant_id', 'to_client_id', 'status'], unique=False)
    op.create_index('uq_client_relationship_pair', 'client_relationship', ['tenant_id', sa.literal_column('least(from_client_id, to_client_id)'), sa.literal_column('greatest(from_client_id, to_client_id)')], unique=True, postgresql_where=sa.text("status IN ('pending', 'active')"))
    op.create_index('uq_client_relationship_token', 'client_relationship', ['tenant_id', 'confirmation_token_hash'], unique=True, postgresql_where=sa.text('confirmation_token_hash IS NOT NULL'))
    op.create_table('client_tag',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('tag_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_tag_client_id_client'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'tag_id'], ['tag.tenant_id', 'tag.id'], name=op.f('fk_client_tag_tag_id_tag'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_tag_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_tag')),
    sa.UniqueConstraint('tenant_id', 'client_id', 'tag_id', name='uq_client_tag_client_tag'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_tag_tenant_id_id'))
    )
    op.create_index('ix_client_tag_tag', 'client_tag', ['tenant_id', 'tag_id', 'client_id'], unique=False)
    op.create_table('client_task',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('note_subject_id', sa.Uuid(), nullable=True),
    sa.Column('subject_text', sa.Text(), nullable=True),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('assignee_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'open'"), nullable=False),
    sa.Column('due_on', sa.Date(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('has_email_reminder', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'done') = (completed_at IS NOT NULL)", name=op.f('ck_client_task_completed')),
    sa.CheckConstraint("status IN ('open', 'in_progress', 'done', 'cancelled')", name=op.f('ck_client_task_status')),
    sa.CheckConstraint('num_nonnulls(note_subject_id, subject_text) = 1', name=op.f('ck_client_task_subject')),
    sa.ForeignKeyConstraint(['tenant_id', 'assignee_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_task_assignee_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_task_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'completed_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_task_completed_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'note_subject_id'], ['note_subject.tenant_id', 'note_subject.id'], name=op.f('fk_client_task_note_subject_id_note_subject'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_task_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_task')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_task_tenant_id_id'))
    )
    op.create_index('ix_client_task_assignee_open', 'client_task', ['tenant_id', 'assignee_staff_user_id', 'due_on'], unique=False, postgresql_where=sa.text("status IN ('open', 'in_progress')"))
    op.create_index('ix_client_task_client', 'client_task', ['tenant_id', 'client_id', 'id'], unique=False)
    op.create_index(op.f('ix_client_task_completed_by_staff_user_id'), 'client_task', ['tenant_id', 'completed_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_client_task_note_subject_id'), 'client_task', ['tenant_id', 'note_subject_id'], unique=False)
    op.create_table('consent_event',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('address', postgresql.CITEXT(), nullable=True),
    sa.Column('topic', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('basis', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('actor_type', sa.Text(), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("actor_type <> 'staff' OR note IS NOT NULL", name=op.f('ck_consent_event_note')),
    sa.CheckConstraint("actor_type IN ('client', 'staff', 'system')", name=op.f('ck_consent_event_actor_type')),
    sa.CheckConstraint("basis IN ('express', 'express_written', 'express_verbal', 'implied_purchase', 'implied_inquiry')", name=op.f('ck_consent_event_basis')),
    sa.CheckConstraint("channel IN ('email', 'sms', 'push')", name=op.f('ck_consent_event_channel')),
    sa.CheckConstraint("kind IN ('opt_in', 'opt_out')", name=op.f('ck_consent_event_kind')),
    sa.CheckConstraint("source IN ('verification_step', 'preference_center', 'one_click', 'staff', 'sms_keyword', 'import', 'portal')", name=op.f('ck_consent_event_source')),
    sa.CheckConstraint("topic IN ('session_reminders', 'card_expiration', 'email_campaigns', 'sms_marketing', 'push_announcements', 'league_alerts')", name=op.f('ck_consent_event_topic')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_consent_event_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_consent_event_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consent_event')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_consent_event_tenant_id_id'))
    )
    op.create_index('ix_consent_event_subject', 'consent_event', ['tenant_id', 'client_id', 'channel', 'address', 'topic', sa.literal_column('occurred_at DESC')], unique=False)
    op.create_table('data_subject_request',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'requested'"), nullable=False),
    sa.Column('requested_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('blockers', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('is_blocker_override', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('handler_results', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind <> 'erasure' OR status IN ('requested', 'blocked', 'rejected') OR confirmed_at IS NOT NULL", name=op.f('ck_data_subject_request_confirm')),
    sa.CheckConstraint("kind IN ('export', 'erasure')", name=op.f('ck_data_subject_request_kind')),
    sa.CheckConstraint("status IN ('requested', 'blocked', 'processing', 'completed', 'rejected', 'failed')", name=op.f('ck_data_subject_request_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_data_subject_request_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'requested_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_data_subject_request_requested_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_data_subject_request_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_data_subject_request')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_data_subject_request_tenant_id_id'))
    )
    op.create_index(op.f('ix_data_subject_request_client_id'), 'data_subject_request', ['tenant_id', 'client_id'], unique=False)
    op.create_index(op.f('ix_data_subject_request_requested_by_staff_user_id'), 'data_subject_request', ['tenant_id', 'requested_by_staff_user_id'], unique=False)
    op.create_table('communication_preference',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.Text(), nullable=False),
    sa.Column('address', postgresql.CITEXT(), nullable=True),
    sa.Column('topic', sa.Text(), nullable=False),
    sa.Column('is_subscribed', sa.Boolean(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('changed_by_actor_type', sa.Text(), nullable=False),
    sa.Column('changed_by_actor_id', sa.Uuid(), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('consent_event_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("changed_by_actor_type IN ('client', 'staff', 'system')", name=op.f('ck_communication_preference_changed_by_actor_type')),
    sa.CheckConstraint("channel IN ('email', 'sms', 'push')", name=op.f('ck_communication_preference_channel')),
    sa.CheckConstraint("source IN ('verification_step', 'preference_center', 'one_click', 'staff', 'sms_keyword', 'import', 'portal')", name=op.f('ck_communication_preference_source')),
    sa.CheckConstraint("topic IN ('session_reminders', 'card_expiration', 'email_campaigns', 'sms_marketing', 'push_announcements', 'league_alerts')", name=op.f('ck_communication_preference_topic')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_communication_preference_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'consent_event_id'], ['consent_event.tenant_id', 'consent_event.id'], name=op.f('fk_communication_preference_consent_event_id_consent_event'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_communication_preference_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_communication_preference')),
    sa.UniqueConstraint('tenant_id', 'client_id', 'channel', 'address', 'topic', name='uq_communication_preference', postgresql_nulls_not_distinct=True),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_communication_preference_tenant_id_id'))
    )
    op.create_index(op.f('ix_communication_preference_consent_event_id'), 'communication_preference', ['tenant_id', 'consent_event_id'], unique=False)
    op.add_column('client', sa.Column('preferred_name', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('gender', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('birth_on', sa.Date(), nullable=True))
    op.add_column('client', sa.Column('organization_name', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('phone_home', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('phone_work', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('address_line1', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('address_line2', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('city', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('region', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('postal_code', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('country_code', sa.CHAR(length=2), nullable=True))
    op.add_column('client', sa.Column('client_category_id', sa.Uuid(), nullable=True))
    op.add_column('client', sa.Column('referral_category_id', sa.Uuid(), nullable=True))
    op.add_column('client', sa.Column('referral_source', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('default_trainer_staff_user_id', sa.Uuid(), nullable=True))
    op.add_column('client', sa.Column('default_salesperson_staff_user_id', sa.Uuid(), nullable=True))
    op.add_column('client', sa.Column('custom_values', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False))
    op.add_column('client', sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False))
    op.add_column('client', sa.Column('comments', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('medical_notes', sa.Text(), nullable=True))
    op.add_column('client', sa.Column('disabled_by_staff_user_id', sa.Uuid(), nullable=True))
    op.add_column('client', sa.Column('merged_into_id', sa.Uuid(), nullable=True))
    op.add_column('client', sa.Column('merged_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('client', sa.Column('erased_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('client', sa.Column('created_via', sa.Text(), server_default=sa.text("'staff'"), nullable=False))
    op.add_column('client', sa.Column('created_by_staff_user_id', sa.Uuid(), nullable=True))
    op.add_column('client', sa.Column('updated_by_staff_user_id', sa.Uuid(), nullable=True))
    op.add_column('client', sa.Column('phone_digits', sa.Text(), sa.Computed("regexp_replace(coalesce(phone_mobile,'') || ' ' || coalesce(phone_home,'') || ' ' || coalesce(phone_work,''), '[^0-9 ]', '', 'g')", persisted=True), nullable=True))
    op.add_column('client', sa.Column('search_text', sa.Text(), sa.Computed("lower(first_name || ' ' || last_name || ' ' || coalesce(preferred_name,'') || ' ' || coalesce(primary_email::text,'') || ' ' || coalesce(member_number::text,''))", persisted=True), nullable=True))
    op.add_column('client', sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False))
    op.create_index('ix_client_birthday', 'client', ['tenant_id', sa.literal_column('(extract(month FROM birth_on))'), sa.literal_column('(extract(day FROM birth_on))')], unique=False)
    op.create_index('ix_client_category', 'client', ['tenant_id', 'client_category_id', 'id'], unique=False)
    op.create_index(op.f('ix_client_created_by_staff_user_id'), 'client', ['tenant_id', 'created_by_staff_user_id'], unique=False)
    op.create_index('ix_client_default_salesperson', 'client', ['tenant_id', 'default_salesperson_staff_user_id'], unique=False, postgresql_where=sa.text('default_salesperson_staff_user_id IS NOT NULL'))
    op.create_index('ix_client_default_trainer', 'client', ['tenant_id', 'default_trainer_staff_user_id'], unique=False, postgresql_where=sa.text('default_trainer_staff_user_id IS NOT NULL'))
    op.create_index(op.f('ix_client_disabled_by_staff_user_id'), 'client', ['tenant_id', 'disabled_by_staff_user_id'], unique=False)
    op.create_index('ix_client_duplicate_key', 'client', ['tenant_id', sa.literal_column('lower(last_name)'), 'birth_on'], unique=False)
    op.create_index('ix_client_merged_into', 'client', ['tenant_id', 'merged_into_id'], unique=False, postgresql_where=sa.text('merged_into_id IS NOT NULL'))
    op.create_index('ix_client_phone_digits', 'client', ['phone_digits'], unique=False, postgresql_using='gin', postgresql_ops={'phone_digits': 'gin_trgm_ops'})
    op.create_index(op.f('ix_client_referral_category_id'), 'client', ['tenant_id', 'referral_category_id'], unique=False)
    op.create_index('ix_client_search_text', 'client', ['search_text'], unique=False, postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})
    op.create_index(op.f('ix_client_updated_by_staff_user_id'), 'client', ['tenant_id', 'updated_by_staff_user_id'], unique=False)
    op.create_foreign_key(op.f('fk_client_default_trainer_staff_user_id_staff_user'), 'client', 'staff_user', ['tenant_id', 'default_trainer_staff_user_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_client_created_by_staff_user_id_staff_user'), 'client', 'staff_user', ['tenant_id', 'created_by_staff_user_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_client_disabled_by_staff_user_id_staff_user'), 'client', 'staff_user', ['tenant_id', 'disabled_by_staff_user_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_client_merged_into_id_client'), 'client', 'client', ['tenant_id', 'merged_into_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_client_referral_category_id_referral_category'), 'client', 'referral_category', ['tenant_id', 'referral_category_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_client_updated_by_staff_user_id_staff_user'), 'client', 'staff_user', ['tenant_id', 'updated_by_staff_user_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_client_default_salesperson_staff_user_id_staff_user'), 'client', 'staff_user', ['tenant_id', 'default_salesperson_staff_user_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_client_client_category_id_client_category'), 'client', 'client_category', ['tenant_id', 'client_category_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    for name, condition in CLIENT_CHECKS.items():
        op.create_check_constraint(op.f(f"ck_client_{name}"), "client", condition)

    for table in TENANT_TABLES:
        enable_rls(table)
    for table in APPEND_ONLY_TABLES:
        enable_rls(table, append_only=True)
    op.execute(REPOINT_CONSENT)
    op.execute(ERASE_CONSENT)
    for fn in ("app.repoint_consent_event(uuid, uuid)", "app.erase_consent_event(uuid)"):
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO fh_app")
    # Back-fill: the skeleton kept only client.primary_email; it becomes the denormalised copy of one
    # client_email row. The owner is subject to FORCE RLS, so lift it for this one statement.
    for table in ("client", "client_email"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO client_email (tenant_id, client_id, email, is_primary) "
        "SELECT tenant_id, id, lower(primary_email), true FROM client WHERE primary_email IS NOT NULL"
    )
    op.execute("UPDATE client SET primary_email = lower(primary_email) WHERE primary_email IS NOT NULL")
    for table in ("client", "client_email"):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.erase_consent_event(uuid)")
    op.execute("DROP FUNCTION app.repoint_consent_event(uuid, uuid)")
    op.drop_constraint(op.f('fk_client_client_category_id_client_category'), 'client', type_='foreignkey')
    op.drop_constraint(op.f('fk_client_default_salesperson_staff_user_id_staff_user'), 'client', type_='foreignkey')
    op.drop_constraint(op.f('fk_client_updated_by_staff_user_id_staff_user'), 'client', type_='foreignkey')
    op.drop_constraint(op.f('fk_client_referral_category_id_referral_category'), 'client', type_='foreignkey')
    op.drop_constraint(op.f('fk_client_merged_into_id_client'), 'client', type_='foreignkey')
    op.drop_constraint(op.f('fk_client_disabled_by_staff_user_id_staff_user'), 'client', type_='foreignkey')
    op.drop_constraint(op.f('fk_client_created_by_staff_user_id_staff_user'), 'client', type_='foreignkey')
    op.drop_constraint(op.f('fk_client_default_trainer_staff_user_id_staff_user'), 'client', type_='foreignkey')
    op.drop_index(op.f('ix_client_updated_by_staff_user_id'), table_name='client')
    op.drop_index('ix_client_search_text', table_name='client', postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_client_referral_category_id'), table_name='client')
    op.drop_index('ix_client_phone_digits', table_name='client', postgresql_using='gin', postgresql_ops={'phone_digits': 'gin_trgm_ops'})
    op.drop_index('ix_client_merged_into', table_name='client', postgresql_where=sa.text('merged_into_id IS NOT NULL'))
    op.drop_index('ix_client_duplicate_key', table_name='client')
    op.drop_index(op.f('ix_client_disabled_by_staff_user_id'), table_name='client')
    op.drop_index('ix_client_default_trainer', table_name='client', postgresql_where=sa.text('default_trainer_staff_user_id IS NOT NULL'))
    op.drop_index('ix_client_default_salesperson', table_name='client', postgresql_where=sa.text('default_salesperson_staff_user_id IS NOT NULL'))
    op.drop_index(op.f('ix_client_created_by_staff_user_id'), table_name='client')
    op.drop_index('ix_client_category', table_name='client')
    op.drop_index('ix_client_birthday', table_name='client')
    op.drop_column('client', 'version')
    op.drop_column('client', 'search_text')
    op.drop_column('client', 'phone_digits')
    op.drop_column('client', 'updated_by_staff_user_id')
    op.drop_column('client', 'created_by_staff_user_id')
    op.drop_column('client', 'created_via')
    op.drop_column('client', 'erased_at')
    op.drop_column('client', 'merged_at')
    op.drop_column('client', 'merged_into_id')
    op.drop_column('client', 'disabled_by_staff_user_id')
    op.drop_column('client', 'medical_notes')
    op.drop_column('client', 'comments')
    op.drop_column('client', 'discount_pct')
    op.drop_column('client', 'custom_values')
    op.drop_column('client', 'default_salesperson_staff_user_id')
    op.drop_column('client', 'default_trainer_staff_user_id')
    op.drop_column('client', 'referral_source')
    op.drop_column('client', 'referral_category_id')
    op.drop_column('client', 'client_category_id')
    op.drop_column('client', 'country_code')
    op.drop_column('client', 'postal_code')
    op.drop_column('client', 'region')
    op.drop_column('client', 'city')
    op.drop_column('client', 'address_line2')
    op.drop_column('client', 'address_line1')
    op.drop_column('client', 'phone_work')
    op.drop_column('client', 'phone_home')
    op.drop_column('client', 'organization_name')
    op.drop_column('client', 'birth_on')
    op.drop_column('client', 'gender')
    op.drop_column('client', 'preferred_name')
    op.drop_index(op.f('ix_communication_preference_consent_event_id'), table_name='communication_preference')
    op.drop_table('communication_preference')
    op.drop_index(op.f('ix_data_subject_request_requested_by_staff_user_id'), table_name='data_subject_request')
    op.drop_index(op.f('ix_data_subject_request_client_id'), table_name='data_subject_request')
    op.drop_table('data_subject_request')
    op.drop_index('ix_consent_event_subject', table_name='consent_event')
    op.drop_table('consent_event')
    op.drop_index(op.f('ix_client_task_note_subject_id'), table_name='client_task')
    op.drop_index(op.f('ix_client_task_completed_by_staff_user_id'), table_name='client_task')
    op.drop_index('ix_client_task_client', table_name='client_task')
    op.drop_index('ix_client_task_assignee_open', table_name='client_task', postgresql_where=sa.text("status IN ('open', 'in_progress')"))
    op.drop_table('client_task')
    op.drop_index('ix_client_tag_tag', table_name='client_tag')
    op.drop_table('client_tag')
    op.drop_index('uq_client_relationship_token', table_name='client_relationship', postgresql_where=sa.text('confirmation_token_hash IS NOT NULL'))
    op.drop_index('uq_client_relationship_pair', table_name='client_relationship', postgresql_where=sa.text("status IN ('pending', 'active')"))
    op.drop_index('ix_client_relationship_to', table_name='client_relationship')
    op.drop_index(op.f('ix_client_relationship_requested_by_identity_id'), table_name='client_relationship')
    op.drop_index(op.f('ix_client_relationship_relationship_type_id'), table_name='client_relationship')
    op.drop_index('ix_client_relationship_from', table_name='client_relationship')
    op.drop_table('client_relationship')
    op.drop_index('ix_client_recent_view_user', table_name='client_recent_view')
    op.drop_index(op.f('ix_client_recent_view_client_id'), table_name='client_recent_view')
    op.drop_table('client_recent_view')
    op.drop_index(op.f('ix_client_note_staff_user_id'), table_name='client_note')
    op.drop_index(op.f('ix_client_note_note_subject_id'), table_name='client_note')
    op.drop_index(op.f('ix_client_note_location_id'), table_name='client_note')
    op.drop_index('ix_client_note_client', table_name='client_note')
    op.drop_table('client_note')
    op.drop_index(op.f('ix_client_merge_survivor_client_id'), table_name='client_merge')
    op.drop_index(op.f('ix_client_merge_performed_by_staff_user_id'), table_name='client_merge')
    op.drop_table('client_merge')
    op.drop_table('client_emergency_contact')
    op.drop_index('uq_client_email_token', table_name='client_email', postgresql_where=sa.text('verification_token_hash IS NOT NULL'))
    op.drop_index('uq_client_email_primary', table_name='client_email', postgresql_where=sa.text('is_primary'))
    op.drop_index('ix_client_email_trgm', table_name='client_email')
    op.drop_index('ix_client_email_email', table_name='client_email')
    op.drop_table('client_email')
    op.drop_index(op.f('ix_client_alert_created_by_staff_user_id'), table_name='client_alert')
    op.drop_index('ix_client_alert_client_active', table_name='client_alert', postgresql_where=sa.text('is_active'))
    op.drop_table('client_alert')
    op.drop_table('client_location_settings')
    op.drop_index('uq_tag_kind_label', table_name='tag')
    op.drop_table('tag')
    op.drop_index(op.f('ix_relationship_type_inverse_type_id'), table_name='relationship_type')
    op.drop_table('relationship_type')
    op.drop_index('uq_referral_category_name', table_name='referral_category')
    op.drop_table('referral_category')
    op.drop_index('uq_note_subject_label', table_name='note_subject')
    op.drop_table('note_subject')
    op.drop_table('custom_field')
    op.drop_table('client_settings')
    op.drop_table('client_field_policy')
    op.drop_index('uq_client_category_name', table_name='client_category')
    op.drop_table('client_category')
