"""integrations (Phase 15): `google_analytics` connection provider (INT-13), the tenant's measurement id and the
domains its registration pages link with.

Revision ID: 1704
Revises: 1703
"""

from alembic import op

revision = "1704"
down_revision = "1703"

_OLD = "'quickbooks_online', 'accounting_file', 'zoom'"


def upgrade() -> None:
    op.drop_constraint("provider", "external_connection", type_="check")
    op.create_check_constraint(
        "provider", "external_connection",
        f"provider IN ({_OLD}, 'google_analytics')",
    )  # fmt: skip


def downgrade() -> None:
    op.execute("DELETE FROM external_connection WHERE provider = 'google_analytics'")
    op.drop_constraint("provider", "external_connection", type_="check")
    op.create_check_constraint("provider", "external_connection", f"provider IN ({_OLD})")
