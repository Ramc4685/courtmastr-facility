"""phase 8 T2 (PLT-16): tenant.is_gdpr_mode, the switch for the stricter privacy defaults. No grant change.

Revision ID: 1261
Revises: 1260
"""

import sqlalchemy as sa
from alembic import op

revision = "1261"
down_revision = "1260"


def upgrade() -> None:
    op.add_column('tenant', sa.Column('is_gdpr_mode', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    op.drop_column('tenant', 'is_gdpr_mode')

