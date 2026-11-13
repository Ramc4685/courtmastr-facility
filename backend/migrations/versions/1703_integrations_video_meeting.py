"""integrations (Phase 15): video_meeting, the online meeting of a session (INT-09, SSP-18, CLS-08). Join URL,
host start URL and passcode are sealed with the tenant's data key.

Revision ID: 1703
Revises: 1702
"""
import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls


revision = '1703'
down_revision = '1702'


def upgrade() -> None:
    # Every new tenant-owned table must call enable_rls("<table>") (append_only=True for ledgers and logs).
    op.create_table('video_meeting',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'scheduled'"), nullable=False),
    sa.Column('external_connection_id', sa.Uuid(), nullable=True),
    sa.Column('external_meeting_id', sa.Text(), nullable=True),
    sa.Column('join_url_ciphertext', sa.Text(), nullable=False),
    sa.Column('host_start_url_ciphertext', sa.Text(), nullable=True),
    sa.Column('passcode_ciphertext', sa.Text(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(provider = 'zoom') = (external_connection_id IS NOT NULL)", name=op.f('ck_video_meeting_connection')),
    sa.CheckConstraint("provider IN ('manual', 'zoom')", name=op.f('ck_video_meeting_provider')),
    sa.CheckConstraint("status IN ('scheduled', 'failed')", name=op.f('ck_video_meeting_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'external_connection_id'], ['external_connection.tenant_id', 'external_connection.id'], name=op.f('fk_video_meeting_external_connection_id_external_connection'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'location_id'], ['location.tenant_id', 'location.id'], name=op.f('fk_video_meeting_location_id_location'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'session_id'], ['session.tenant_id', 'session.id'], name=op.f('fk_video_meeting_session_id_session'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_video_meeting_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_video_meeting')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_video_meeting_tenant_id_id')),
    sa.UniqueConstraint('tenant_id', 'session_id', name=op.f('uq_video_meeting_tenant_id_session_id'))
    )
    op.create_index(op.f('ix_video_meeting_external_connection_id'), 'video_meeting', ['tenant_id', 'external_connection_id'], unique=False)
    op.create_index(op.f('ix_video_meeting_location_id'), 'video_meeting', ['tenant_id', 'location_id'], unique=False)
    enable_rls("video_meeting")


def downgrade() -> None:
    op.drop_index(op.f('ix_video_meeting_location_id'), table_name='video_meeting')
    op.drop_index(op.f('ix_video_meeting_external_connection_id'), table_name='video_meeting')
    op.drop_table('video_meeting')
