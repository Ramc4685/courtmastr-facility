"""imports: import jobs and their per-row outcomes (Phase 8 I1: IMP-01, IMP-02, MEM-23)

Both tables are tenant data under forced RLS. A job keeps no cell values: rows are re-read from the stored source
file, and `import_job_row` keeps the row number, the hash of its natural key, the outcome and plain-words errors.

Revision ID: 1270
Revises: 1241 (chained after the phase branch head; the number is the chip's reserved range, not its order)
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = '1270'
down_revision = '1241'


def upgrade() -> None:
    op.create_table('import_job',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('source_file_id', sa.Uuid(), nullable=True),
    sa.Column('source_headers', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('date_format', sa.Text(), server_default=sa.text("'iso'"), nullable=False),
    sa.Column('column_mapping', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'new'"), nullable=False),
    sa.Column('submitted_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('total_row_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('valid_row_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('updated_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('skipped_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('error_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('progress', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('report_file_id', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('files_purged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("date_format IN ('iso', 'mdy', 'dmy')", name=op.f('ck_import_job_date_format')),
    sa.CheckConstraint("kind IN ('clients', 'memberships', 'balances', 'products')", name=op.f('ck_import_job_kind')),
    sa.CheckConstraint("status IN ('new', 'uploaded', 'validating', 'validated', 'needs_review', 'importing', 'completed', 'failed')", name=op.f('ck_import_job_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_import_job_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'report_file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_import_job_report_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'source_file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_import_job_source_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'submitted_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_import_job_submitted_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_import_job_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_job')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_import_job_tenant_id_id'))
    )
    op.create_index('ix_import_job_expiry', 'import_job', ['tenant_id', 'expires_at'], unique=False, postgresql_where=sa.text('files_purged_at IS NULL'))
    op.create_index(op.f('ix_import_job_location_id'), 'import_job', ['tenant_id', 'location_id'], unique=False)
    op.create_index(op.f('ix_import_job_source_file_id'), 'import_job', ['tenant_id', 'source_file_id'], unique=False)
    op.create_index('ix_import_job_status', 'import_job', ['tenant_id', 'status', 'id'], unique=False)
    op.create_index(op.f('ix_import_job_submitted_by_staff_user_id'), 'import_job', ['tenant_id', 'submitted_by_staff_user_id'], unique=False)
    op.create_table('import_job_row',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('import_job_id', sa.Uuid(), nullable=False),
    sa.Column('row_number', sa.Integer(), nullable=False),
    sa.Column('row_key', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('entity_type', sa.Text(), nullable=True),
    sa.Column('entity_id', sa.Uuid(), nullable=True),
    sa.Column('errors', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("entity_type IN ('client', 'membership_contract', 'charge', 'payment', 'product')", name=op.f('ck_import_job_row_entity_type')),
    sa.CheckConstraint("status IN ('valid', 'invalid', 'created', 'updated', 'skipped', 'failed')", name=op.f('ck_import_job_row_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'import_job_id'], ['import_job.tenant_id', 'import_job.id'], name=op.f('fk_import_job_row_import_job_id_import_job'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_import_job_row_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_job_row')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_import_job_row_tenant_id_id'))
    )
    op.create_index('ix_import_job_row_key', 'import_job_row', ['tenant_id', 'row_key'], unique=False)
    op.create_index('uq_import_job_row', 'import_job_row', ['tenant_id', 'import_job_id', 'row_number'], unique=True)
    enable_rls("import_job")
    enable_rls("import_job_row")


def downgrade() -> None:
    op.drop_index('uq_import_job_row', table_name='import_job_row')
    op.drop_index('ix_import_job_row_key', table_name='import_job_row')
    op.drop_table('import_job_row')
    op.drop_index(op.f('ix_import_job_submitted_by_staff_user_id'), table_name='import_job')
    op.drop_index('ix_import_job_status', table_name='import_job')
    op.drop_index(op.f('ix_import_job_source_file_id'), table_name='import_job')
    op.drop_index(op.f('ix_import_job_location_id'), table_name='import_job')
    op.drop_index('ix_import_job_expiry', table_name='import_job', postgresql_where=sa.text('files_purged_at IS NULL'))
    op.drop_table('import_job')
