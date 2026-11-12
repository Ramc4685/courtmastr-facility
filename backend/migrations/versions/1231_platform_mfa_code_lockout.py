"""platform: a separate lockout for wrong second-factor codes; recovery codes become keyed HMACs

Phase 8 S2 review follow-up. Wrong codes count on mfa_factor instead of identity, so wrong passwords no longer
lock the second factor. Recovery codes switch from bare SHA-256 to core.crypto.mac; the old digests cannot be
converted, so existing recovery codes are deleted (development data only: S2 has not shipped). Users regenerate.

Revision ID: 1231
Revises: 1230
"""

import sqlalchemy as sa
from alembic import op

revision = '1231'
down_revision = '1230'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('mfa_factor', sa.Column('failed_attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('mfa_factor', sa.Column('failed_window_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mfa_factor', sa.Column('locked_until_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mfa_factor', sa.Column('lockout_count', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.execute('DELETE FROM mfa_recovery_code')


def downgrade() -> None:
    op.execute('DELETE FROM mfa_recovery_code')  # keyed codes cannot be checked by the older bare-digest code
    op.drop_column('mfa_factor', 'lockout_count')
    op.drop_column('mfa_factor', 'locked_until_at')
    op.drop_column('mfa_factor', 'failed_window_started_at')
    op.drop_column('mfa_factor', 'failed_attempt_count')
