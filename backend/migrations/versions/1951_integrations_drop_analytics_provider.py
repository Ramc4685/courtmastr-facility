"""integrations: drop the `google_analytics` connection provider (INT-13) that 1704 added. Owner decision
2026-11-13 (question 6): no third-party analytics; any such connection is removed.

Revision ID: 1951
Revises: 1705
"""

from alembic import op

revision = "1951"
down_revision = "1705"

_KEPT = "'quickbooks_online', 'accounting_file', 'zoom'"


def upgrade() -> None:
    op.execute("DELETE FROM external_connection WHERE provider = 'google_analytics'")
    op.drop_constraint("provider", "external_connection", type_="check")
    op.create_check_constraint("provider", "external_connection", f"provider IN ({_KEPT})")


def downgrade() -> None:
    op.drop_constraint("provider", "external_connection", type_="check")
    op.create_check_constraint("provider", "external_connection", f"provider IN ({_KEPT}, 'google_analytics')")
