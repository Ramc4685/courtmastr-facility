"""phase 8 T2 (IMP-04): tenant_export, the tenant-wide data export bundle built by a chunked job. No grant
change beyond enable_rls.

Revision ID: 1262
Revises: 1261
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = "1262"
down_revision = "1261"


def upgrade() -> None:
    op.create_table('tenant_export',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('requested_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('progress', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('partial', sa.LargeBinary(), nullable=True),
    sa.Column('file_id', sa.Uuid(), nullable=True),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'expired')", name=op.f('ck_tenant_export_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_tenant_export_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'requested_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_tenant_export_requested_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_tenant_export_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenant_export')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_tenant_export_tenant_id_id'))
    )
    op.create_index(op.f('ix_tenant_export_file_id'), 'tenant_export', ['tenant_id', 'file_id'], unique=False)
    enable_rls("tenant_export")


def downgrade() -> None:
    op.drop_index(op.f('ix_tenant_export_file_id'), table_name='tenant_export')
    op.drop_table('tenant_export')

