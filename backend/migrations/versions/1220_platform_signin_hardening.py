"""platform S1 sign-in hardening: stored CSRF token, windowed and doubling lockout, staff IP allow-list.

auth_session.csrf_token_hash: SHA-256 of the per-session synchroniser token (security-baseline 5.3).
identity.failed_window_started_at, identity.lockout_count: 10 failures in 15 minutes lock password sign-in,
each lockout twice as long as the last up to a cap (baseline 5.1).
tenant.staff_ip_allowlist: tenant-wide staff CIDR allow-list (PLT-07); empty means no restriction.

Revision ID: 1220
Revises: 0953
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "1220"
down_revision = "0953"


def upgrade() -> None:
    op.add_column("auth_session", sa.Column("csrf_token_hash", sa.String(), nullable=True))
    op.add_column("identity", sa.Column("failed_window_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("identity", sa.Column("lockout_count", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column(
        "tenant",
        sa.Column(
            "staff_ip_allowlist", postgresql.ARRAY(postgresql.CIDR()), server_default=sa.text("'{}'"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant", "staff_ip_allowlist")
    op.drop_column("identity", "lockout_count")
    op.drop_column("identity", "failed_window_started_at")
    op.drop_column("auth_session", "csrf_token_hash")
