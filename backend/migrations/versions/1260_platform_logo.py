"""phase 8 T2 (PLT-08): logo, the tenant's and each location's logo image (a stored file under the public
prefix). No grant change beyond enable_rls.

Revision ID: 1260
Revises: 1250
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls

revision = "1260"
down_revision = "1250"


def upgrade() -> None:
    op.create_table('logo',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('file_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_logo_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_logo_location_id_location'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_logo_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_logo')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_logo_tenant_id_id'))
    )
    op.create_index(op.f('ix_logo_file_id'), 'logo', ['tenant_id', 'file_id'], unique=False)
    op.create_index('uq_logo_location', 'logo', ['tenant_id', 'location_id'], unique=True, postgresql_where=sa.text('location_id IS NOT NULL'))
    op.create_index('uq_logo_tenant', 'logo', ['tenant_id'], unique=True, postgresql_where=sa.text('location_id IS NULL'))
    enable_rls("logo")


def downgrade() -> None:
    op.drop_index('uq_logo_tenant', table_name='logo', postgresql_where=sa.text('location_id IS NULL'))
    op.drop_index('uq_logo_location', table_name='logo', postgresql_where=sa.text('location_id IS NOT NULL'))
    op.drop_index(op.f('ix_logo_file_id'), table_name='logo')
    op.drop_table('logo')

