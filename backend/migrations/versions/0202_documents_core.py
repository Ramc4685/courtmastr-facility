"""documents core (build module 7): data-model-people section 2 and platform stored_file (data-model-core 2.2).

Generated from the models, then completed by hand: enable_rls() per table (document_acceptance is append-only),
the circular document_template -> document_template_version foreign key added after both tables exist, and the
SECURITY DEFINER function the data model sanctions for re-pointing the append-only evidence on merge (A7).

Revision ID: 0202
Revises: 0201
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = '0202'
down_revision = '0201'

TENANT_TABLES = (
    "stored_file", "document_settings", "document_template", "document_template_version", "document_binding",
    "document_location_settings", "client_document", "client_document_status", "document_delivery",
)
# document_acceptance grants fh_app SELECT, INSERT only; this function, owned by fh_owner, is the one path that
# changes a row (merge). FORCE ROW LEVEL SECURITY keeps it inside the caller's tenant.
REPOINT_ACCEPTANCE = """
CREATE FUNCTION app.repoint_document_acceptance(p_from uuid, p_to uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE moved integer;
BEGIN
    UPDATE document_acceptance SET signer_client_id = p_to
     WHERE signer_client_id = p_from AND tenant_id = app.current_tenant_id();
    GET DIAGNOSTICS moved = ROW_COUNT;
    RETURN moved;
END $$
"""


def upgrade() -> None:
    op.create_table('document_settings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('email_link_ttl_hours', sa.Integer(), server_default=sa.text('48'), nullable=False),
    sa.Column('deleted_recovery_days', sa.Integer(), server_default=sa.text('30'), nullable=False),
    sa.Column('is_staff_notified_on_decision', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_waiver_required_for_check_in', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_waiver_required_for_booking', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('deleted_recovery_days BETWEEN 1 AND 365', name=op.f('ck_document_settings_deleted_recovery_days')),
    sa.CheckConstraint('email_link_ttl_hours BETWEEN 1 AND 720', name=op.f('ck_document_settings_email_link_ttl_hours')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_document_settings_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_settings')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_document_settings_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', name='uq_document_settings_tenant')
    )
    op.create_table('document_template',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), server_default=sa.text("'agreement'"), nullable=False),
    sa.Column('is_waiver', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('signature_validity_days', sa.Integer(), nullable=True),
    sa.Column('requires_guardian_for_minors', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('minor_age_years', sa.SmallInteger(), server_default=sa.text('18'), nullable=False),
    sa.Column('current_version_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'draft'"), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('agreement', 'consent')", name=op.f('ck_document_template_kind')),
    sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name=op.f('ck_document_template_status')),
    sa.CheckConstraint('minor_age_years BETWEEN 1 AND 25', name=op.f('ck_document_template_minor_age_years')),
    sa.CheckConstraint('signature_validity_days > 0', name=op.f('ck_document_template_signature_validity_days')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_document_template_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_template')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_document_template_tenant_id_id'))
    )
    op.create_index('ix_document_template_current_version_id', 'document_template', ['tenant_id', 'current_version_id'], unique=False)
    op.create_index('uq_document_template_active_consent', 'document_template', ['tenant_id'], unique=True, postgresql_where=sa.text("kind = 'consent' AND status = 'active'"))
    op.create_index('uq_document_template_name', 'document_template', ['tenant_id', sa.literal_column('lower(name)')], unique=True, postgresql_where=sa.text("status <> 'archived'"))
    op.create_table('stored_file',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('object_key', sa.Text(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('content_type', sa.Text(), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.Text(), nullable=True),
    sa.Column('original_name', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('uploaded_by_type', sa.Text(), nullable=False),
    sa.Column('uploaded_by_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'ready', 'purged')", name=op.f('ck_stored_file_status')),
    sa.CheckConstraint("uploaded_by_type IN ('staff', 'client', 'api_key', 'system')", name=op.f('ck_stored_file_uploaded_by_type')),
    sa.CheckConstraint('size_bytes >= 0', name=op.f('ck_stored_file_size_bytes')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_stored_file_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stored_file')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_stored_file_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'object_key', name=op.f('uq_stored_file_tenant_id_object_key'))
    )
    op.create_table('document_binding',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('scope_type', sa.Text(), nullable=False),
    sa.Column('scope_id', sa.Uuid(), nullable=True),
    sa.Column('template_id', sa.Uuid(), nullable=True),
    sa.Column('custom_text', sa.Text(), nullable=True),
    sa.Column('frequency', sa.Text(), server_default=sa.text("'every_purchase'"), nullable=False),
    sa.Column('is_enforced_online', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_enforced_at_desk', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(scope_type IN ('program_default', 'portal_terms')) = (scope_id IS NULL)", name=op.f('ck_document_binding_scope')),
    sa.CheckConstraint("frequency IN ('first_purchase', 'every_purchase')", name=op.f('ck_document_binding_frequency')),
    sa.CheckConstraint("scope_type IN ('membership_plan', 'package_plan', 'program_group', 'program_default', 'rental_plan', 'portal_terms')", name=op.f('ck_document_binding_scope_type')),
    sa.CheckConstraint('num_nonnulls(template_id, custom_text) = 1', name=op.f('ck_document_binding_content')),
    sa.ForeignKeyConstraint(['tenant_id', 'template_id'], ['document_template.tenant_id', 'document_template.id'], name=op.f('fk_document_binding_template_id_document_template'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_document_binding_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_binding')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_document_binding_tenant_id_id'))
    )
    op.create_index(op.f('ix_document_binding_template_id'), 'document_binding', ['tenant_id', 'template_id'], unique=False)
    op.create_index('uq_document_binding_scope', 'document_binding', ['tenant_id', 'scope_type', sa.literal_column("coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)")], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('document_location_settings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('is_consent_required', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_document_location_settings_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_document_location_settings_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_location_settings')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_document_location_settings_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'location_id', name=op.f('uq_document_location_settings_tenant_id_location_id'))
    )
    op.create_table('document_template_version',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('template_id', sa.Uuid(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('body_html', sa.Text(), nullable=False),
    sa.Column('acceptance_text', sa.Text(), nullable=False),
    sa.Column('body_sha256', sa.Text(), nullable=False),
    sa.Column('signature_blocks', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('sanitizer_version', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('change_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(signature_blocks) = 'array'", name=op.f('ck_document_template_version_signature_blocks')),
    sa.CheckConstraint('char_length(acceptance_text) BETWEEN 1 AND 1000', name=op.f('ck_document_template_version_acceptance_text')),
    sa.ForeignKeyConstraint(['tenant_id', 'published_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_document_template_version_published_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'template_id'], ['document_template.tenant_id', 'document_template.id'], name=op.f('fk_document_template_version_template_id_document_template'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_document_template_version_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_template_version')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_document_template_version_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'template_id', 'version_number', name=op.f('uq_document_template_version_tenant_id_template_id_version_number'))
    )
    op.create_index(op.f('ix_document_template_version_published_by_staff_user_id'), 'document_template_version', ['tenant_id', 'published_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_document_template_version_template_id'), 'document_template_version', ['tenant_id', 'template_id'], unique=False)
    op.create_index('uq_document_template_version_draft', 'document_template_version', ['tenant_id', 'template_id'], unique=True, postgresql_where=sa.text('published_at IS NULL'))
    op.create_table('client_document',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('template_id', sa.Uuid(), nullable=True),
    sa.Column('template_version_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('origin', sa.Text(), server_default=sa.text("'manual'"), nullable=False),
    sa.Column('binding_id', sa.Uuid(), nullable=True),
    sa.Column('source_context', sa.Text(), nullable=True),
    sa.Column('source_type', sa.Text(), nullable=True),
    sa.Column('source_id', sa.Uuid(), nullable=True),
    sa.Column('acceptance_method', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('issued_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_on', sa.Date(), nullable=True),
    sa.Column('requires_guardian', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('body_html', sa.Text(), nullable=False),
    sa.Column('acceptance_text', sa.Text(), nullable=False),
    sa.Column('signature_blocks', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('rendered_file_id', sa.Uuid(), nullable=True),
    sa.Column('content_sha256', sa.Text(), nullable=False),
    sa.Column('paper_scan_file_id', sa.Uuid(), nullable=True),
    sa.Column('is_paper_signed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status IN ('accepted', 'declined')) <= (decided_at IS NOT NULL)", name=op.f('ck_client_document_decided_at')),
    sa.CheckConstraint("acceptance_method IN ('paper', 'checkbox', 'drawn_signature', 'email_link')", name=op.f('ck_client_document_acceptance_method')),
    sa.CheckConstraint("jsonb_typeof(signature_blocks) = 'array'", name=op.f('ck_client_document_signature_blocks')),
    sa.CheckConstraint("origin IN ('manual', 'sale', 'registration', 'bulk_send', 'consent', 'external_provider', 'import')", name=op.f('ck_client_document_origin')),
    sa.CheckConstraint("status IN ('pending', 'accepted', 'declined', 'expired', 'voided')", name=op.f('ck_client_document_status')),
    sa.CheckConstraint('num_nonnulls(source_context, source_type, source_id) IN (0, 3)', name=op.f('ck_client_document_source')),
    sa.ForeignKeyConstraint(['tenant_id', 'binding_id'], ['document_binding.tenant_id', 'document_binding.id'], name=op.f('fk_client_document_binding_id_document_binding'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_document_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'deleted_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_document_deleted_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'issued_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_document_issued_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_client_document_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'paper_scan_file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_client_document_paper_scan_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'rendered_file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_client_document_rendered_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'template_id'], ['document_template.tenant_id', 'document_template.id'], name=op.f('fk_client_document_template_id_document_template'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'template_version_id'], ['document_template_version.tenant_id', 'document_template_version.id'], name=op.f('fk_client_document_template_version_id_document_template_version'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_document_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_document')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_document_tenant_id_id'))
    )
    op.create_index(op.f('ix_client_document_binding_id'), 'client_document', ['tenant_id', 'binding_id'], unique=False)
    op.create_index('ix_client_document_client', 'client_document', ['tenant_id', 'client_id', 'id'], unique=False)
    op.create_index('ix_client_document_deleted', 'client_document', ['tenant_id', 'deleted_at'], unique=False, postgresql_where=sa.text('deleted_at IS NOT NULL'))
    op.create_index(op.f('ix_client_document_deleted_by_staff_user_id'), 'client_document', ['tenant_id', 'deleted_by_staff_user_id'], unique=False)
    op.create_index('ix_client_document_expiry', 'client_document', ['tenant_id', 'expires_on'], unique=False, postgresql_where=sa.text("status = 'accepted' AND expires_on IS NOT NULL"))
    op.create_index('ix_client_document_history', 'client_document', ['tenant_id', 'location_id', sa.literal_column('issued_at DESC')], unique=False)
    op.create_index(op.f('ix_client_document_issued_by_staff_user_id'), 'client_document', ['tenant_id', 'issued_by_staff_user_id'], unique=False)
    op.create_index(op.f('ix_client_document_paper_scan_file_id'), 'client_document', ['tenant_id', 'paper_scan_file_id'], unique=False)
    op.create_index('ix_client_document_pending', 'client_document', ['tenant_id', 'issued_at'], unique=False, postgresql_where=sa.text("status = 'pending' AND deleted_at IS NULL"))
    op.create_index(op.f('ix_client_document_rendered_file_id'), 'client_document', ['tenant_id', 'rendered_file_id'], unique=False)
    op.create_index('ix_client_document_template_client', 'client_document', ['tenant_id', 'template_id', 'client_id'], unique=False)
    op.create_index(op.f('ix_client_document_template_version_id'), 'client_document', ['tenant_id', 'template_version_id'], unique=False)
    op.create_index('uq_client_document_source', 'client_document', ['tenant_id', 'source_context', 'source_type', 'source_id', sa.literal_column("coalesce(template_id, '00000000-0000-0000-0000-000000000000'::uuid)")], unique=True, postgresql_where=sa.text("source_id IS NOT NULL AND status <> 'voided' AND deleted_at IS NULL"))
    op.create_table('client_document_status',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('has_waiver', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('waiver_valid_until_on', sa.Date(), nullable=True),
    sa.Column('waiver_override', sa.Text(), nullable=True),
    sa.Column('waiver_override_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('waiver_override_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('waiver_override_note', sa.Text(), nullable=True),
    sa.Column('consent_document_id', sa.Uuid(), nullable=True),
    sa.Column('consent_accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("waiver_override IN ('on_file', 'not_on_file')", name=op.f('ck_client_document_status_waiver_override')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_client_document_status_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'consent_document_id'], ['client_document.tenant_id', 'client_document.id'], name=op.f('fk_client_document_status_consent_document_id_client_document'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'waiver_override_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_client_document_status_waiver_override_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_document_status_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_document_status')),
    sa.UniqueConstraint('tenant_id', 'client_id', name='uq_client_document_status_client'),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_document_status_tenant_id_id'))
    )
    op.create_index(op.f('ix_client_document_status_consent_document_id'), 'client_document_status', ['tenant_id', 'consent_document_id'], unique=False)
    op.create_index(op.f('ix_client_document_status_waiver_override_by_staff_user_id'), 'client_document_status', ['tenant_id', 'waiver_override_by_staff_user_id'], unique=False)
    op.create_table('document_delivery',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_document_id', sa.Uuid(), nullable=False),
    sa.Column('recipient_emails', sa.ARRAY(sa.Text()), nullable=False),
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('sent_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outcome', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("outcome IN ('pending', 'accepted', 'declined', 'expired', 'superseded')", name=op.f('ck_document_delivery_outcome')),
    sa.CheckConstraint('cardinality(recipient_emails) >= 1', name=op.f('ck_document_delivery_recipient_emails')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_document_id'], ['client_document.tenant_id', 'client_document.id'], name=op.f('fk_document_delivery_client_document_id_client_document'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'sent_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_document_delivery_sent_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_document_delivery_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_delivery')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_document_delivery_tenant_id_id'))
    )
    op.create_index(op.f('ix_document_delivery_client_document_id'), 'document_delivery', ['tenant_id', 'client_document_id'], unique=False)
    op.create_index('ix_document_delivery_expiry', 'document_delivery', ['tenant_id', 'expires_at'], unique=False, postgresql_where=sa.text("outcome = 'pending'"))
    op.create_index(op.f('ix_document_delivery_sent_by_staff_user_id'), 'document_delivery', ['tenant_id', 'sent_by_staff_user_id'], unique=False)
    op.create_index('uq_document_delivery_token', 'document_delivery', ['tenant_id', 'token_hash'], unique=True)
    op.create_table('document_acceptance',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_document_id', sa.Uuid(), nullable=False),
    sa.Column('decision', sa.Text(), nullable=False),
    sa.Column('signer_role', sa.Text(), nullable=False),
    sa.Column('signer_client_id', sa.Uuid(), nullable=True),
    sa.Column('signer_name', sa.Text(), nullable=False),
    sa.Column('method', sa.Text(), nullable=False),
    sa.Column('typed_signature', sa.Text(), nullable=True),
    sa.Column('signature_file_id', sa.Uuid(), nullable=True),
    sa.Column('delivery_id', sa.Uuid(), nullable=True),
    sa.Column('witnessed_by_staff_user_id', sa.Uuid(), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('content_sha256', sa.Text(), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("decision IN ('accepted', 'declined')", name=op.f('ck_document_acceptance_decision')),
    sa.CheckConstraint("method <> 'drawn_signature' OR signature_file_id IS NOT NULL", name=op.f('ck_document_acceptance_drawn')),
    sa.CheckConstraint("method IN ('paper', 'checkbox', 'drawn_signature', 'typed_name')", name=op.f('ck_document_acceptance_method')),
    sa.CheckConstraint("signer_role IN ('client', 'guardian', 'co_signer')", name=op.f('ck_document_acceptance_signer_role')),
    sa.ForeignKeyConstraint(['tenant_id', 'client_document_id'], ['client_document.tenant_id', 'client_document.id'], name=op.f('fk_document_acceptance_client_document_id_client_document'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'delivery_id'], ['document_delivery.tenant_id', 'document_delivery.id'], name=op.f('fk_document_acceptance_delivery_id_document_delivery'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'signature_file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_document_acceptance_signature_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'signer_client_id'], ['client.tenant_id', 'client.id'], name=op.f('fk_document_acceptance_signer_client_id_client'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'witnessed_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_document_acceptance_witnessed_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_document_acceptance_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_acceptance')),
    sa.UniqueConstraint('tenant_id', 'client_document_id', 'signer_role', name=op.f('uq_document_acceptance_tenant_id_client_document_id_signer_role')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_document_acceptance_tenant_id_id'))
    )
    op.create_index(op.f('ix_document_acceptance_delivery_id'), 'document_acceptance', ['tenant_id', 'delivery_id'], unique=False)
    op.create_index(op.f('ix_document_acceptance_signature_file_id'), 'document_acceptance', ['tenant_id', 'signature_file_id'], unique=False)
    op.create_index(op.f('ix_document_acceptance_signer_client_id'), 'document_acceptance', ['tenant_id', 'signer_client_id'], unique=False)
    op.create_index(op.f('ix_document_acceptance_witnessed_by_staff_user_id'), 'document_acceptance', ['tenant_id', 'witnessed_by_staff_user_id'], unique=False)
    op.create_foreign_key(
        'fk_document_template_current_version', 'document_template',
        'document_template_version', ['tenant_id', 'current_version_id'], ['tenant_id', 'id'], ondelete='RESTRICT',
        deferrable=True, initially='DEFERRED',
    )
    for table in TENANT_TABLES:
        enable_rls(table)
    enable_rls("document_acceptance", append_only=True)
    op.execute(REPOINT_ACCEPTANCE)
    op.execute("REVOKE ALL ON FUNCTION app.repoint_document_acceptance(uuid, uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.repoint_document_acceptance(uuid, uuid) TO fh_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.repoint_document_acceptance(uuid, uuid)")
    op.drop_constraint('fk_document_template_current_version', 'document_template')
    op.drop_index(op.f('ix_document_acceptance_witnessed_by_staff_user_id'), table_name='document_acceptance')
    op.drop_index(op.f('ix_document_acceptance_signer_client_id'), table_name='document_acceptance')
    op.drop_index(op.f('ix_document_acceptance_signature_file_id'), table_name='document_acceptance')
    op.drop_index(op.f('ix_document_acceptance_delivery_id'), table_name='document_acceptance')
    op.drop_table('document_acceptance')
    op.drop_index('uq_document_delivery_token', table_name='document_delivery')
    op.drop_index(op.f('ix_document_delivery_sent_by_staff_user_id'), table_name='document_delivery')
    op.drop_index('ix_document_delivery_expiry', table_name='document_delivery', postgresql_where=sa.text("outcome = 'pending'"))
    op.drop_index(op.f('ix_document_delivery_client_document_id'), table_name='document_delivery')
    op.drop_table('document_delivery')
    op.drop_index(op.f('ix_client_document_status_waiver_override_by_staff_user_id'), table_name='client_document_status')
    op.drop_index(op.f('ix_client_document_status_consent_document_id'), table_name='client_document_status')
    op.drop_table('client_document_status')
    op.drop_index('uq_client_document_source', table_name='client_document', postgresql_where=sa.text("source_id IS NOT NULL AND status <> 'voided' AND deleted_at IS NULL"))
    op.drop_index(op.f('ix_client_document_template_version_id'), table_name='client_document')
    op.drop_index('ix_client_document_template_client', table_name='client_document')
    op.drop_index(op.f('ix_client_document_rendered_file_id'), table_name='client_document')
    op.drop_index('ix_client_document_pending', table_name='client_document', postgresql_where=sa.text("status = 'pending' AND deleted_at IS NULL"))
    op.drop_index(op.f('ix_client_document_paper_scan_file_id'), table_name='client_document')
    op.drop_index(op.f('ix_client_document_issued_by_staff_user_id'), table_name='client_document')
    op.drop_index('ix_client_document_history', table_name='client_document')
    op.drop_index('ix_client_document_expiry', table_name='client_document', postgresql_where=sa.text("status = 'accepted' AND expires_on IS NOT NULL"))
    op.drop_index(op.f('ix_client_document_deleted_by_staff_user_id'), table_name='client_document')
    op.drop_index('ix_client_document_deleted', table_name='client_document', postgresql_where=sa.text('deleted_at IS NOT NULL'))
    op.drop_index('ix_client_document_client', table_name='client_document')
    op.drop_index(op.f('ix_client_document_binding_id'), table_name='client_document')
    op.drop_table('client_document')
    op.drop_index('uq_document_template_version_draft', table_name='document_template_version', postgresql_where=sa.text('published_at IS NULL'))
    op.drop_index(op.f('ix_document_template_version_template_id'), table_name='document_template_version')
    op.drop_index(op.f('ix_document_template_version_published_by_staff_user_id'), table_name='document_template_version')
    op.drop_table('document_template_version')
    op.drop_table('document_location_settings')
    op.drop_index('uq_document_binding_scope', table_name='document_binding', postgresql_where=sa.text('is_active'))
    op.drop_index(op.f('ix_document_binding_template_id'), table_name='document_binding')
    op.drop_table('document_binding')
    op.drop_table('stored_file')
    op.drop_index('uq_document_template_name', table_name='document_template', postgresql_where=sa.text("status <> 'archived'"))
    op.drop_index('uq_document_template_active_consent', table_name='document_template', postgresql_where=sa.text("kind = 'consent' AND status = 'active'"))
    op.drop_index('ix_document_template_current_version_id', table_name='document_template')
    op.drop_table('document_template')
    op.drop_table('document_settings')
