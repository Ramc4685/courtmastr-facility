"""clients (phase 10 chip F): client photo (CLI-12) and note attachments (CLI-09) on stored_file.

Revision ID: 1091
Revises: 1022
"""
import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls


revision = '1091'
down_revision = '1022'


def upgrade() -> None:
    op.add_column('client', sa.Column('photo_file_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_client_photo_file_id'), 'client', ['tenant_id', 'photo_file_id'], unique=False)
    op.create_foreign_key(op.f('fk_client_photo_file_id_stored_file'), 'client', 'stored_file', ['tenant_id', 'photo_file_id'], ['tenant_id', 'id'], ondelete='RESTRICT')
    op.create_table('client_note_attachment',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('client_note_id', sa.Uuid(), nullable=False),
    sa.Column('stored_file_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'client_note_id'], ['client_note.tenant_id', 'client_note.id'], name=op.f('fk_client_note_attachment_client_note_id_client_note'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'stored_file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_client_note_attachment_stored_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_client_note_attachment_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_client_note_attachment')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_client_note_attachment_tenant_id_id'))
    )
    op.create_index(op.f('ix_client_note_attachment_client_note_id'), 'client_note_attachment', ['tenant_id', 'client_note_id'], unique=False)
    op.create_index(op.f('ix_client_note_attachment_stored_file_id'), 'client_note_attachment', ['tenant_id', 'stored_file_id'], unique=False)
    enable_rls('client_note_attachment')


def downgrade() -> None:
    op.drop_table('client_note_attachment')
    op.drop_constraint(op.f('fk_client_photo_file_id_stored_file'), 'client', type_='foreignkey')
    op.drop_index(op.f('ix_client_photo_file_id'), table_name='client')
    op.drop_column('client', 'photo_file_id')
