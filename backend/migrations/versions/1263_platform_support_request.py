"""phase 8 T2 (ONB-03): support_request, a staff "Contact support" message. No grant change beyond enable_rls.

Revision ID: 1263
Revises: 1262
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls

revision = "1263"
down_revision = "1262"


def upgrade() -> None:
    op.create_table('support_request',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('requested_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('category', sa.Text(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('screenshot_file_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'open'"), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category IN ('question', 'problem', 'billing', 'import', 'feedback')", name=op.f('ck_support_request_category')),
    sa.CheckConstraint("status IN ('open', 'closed')", name=op.f('ck_support_request_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'requested_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_support_request_requested_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'screenshot_file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_support_request_screenshot_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_support_request_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_support_request')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_support_request_tenant_id_id'))
    )
    op.create_index('ix_support_request_mine', 'support_request', ['tenant_id', 'requested_by_staff_user_id', 'id'], unique=False)
    op.create_index(op.f('ix_support_request_screenshot_file_id'), 'support_request', ['tenant_id', 'screenshot_file_id'], unique=False)
    enable_rls("support_request")


def downgrade() -> None:
    op.drop_index(op.f('ix_support_request_screenshot_file_id'), table_name='support_request')
    op.drop_index('ix_support_request_mine', table_name='support_request')
    op.drop_table('support_request')

