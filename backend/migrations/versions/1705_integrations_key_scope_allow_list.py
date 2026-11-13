"""integrations (Phase 15): strip API-key scopes outside the key allow-list (`service.KEY_CONTEXTS`).

Flagged scopes were never grantable, so only the context matters; the list is frozen here as of this revision.
Authentication filters scopes through the allow-list as well, so this only tidies stored rows. Not reversible.

Revision ID: 1705
Revises: 1704
"""

from alembic import op

revision = "1705"
down_revision = "1704"

_CONTEXTS = (
    "access", "assessments", "billing", "clients", "documents", "leagues", "memberships", "packages", "pos",
    "programs", "rentals", "resources", "scheduling",
)  # fmt: skip
_ALLOWED = "ARRAY[" + ", ".join(f"'{c}'" for c in _CONTEXTS) + "]"
STRIP = (
    "UPDATE api_key SET scopes = ARRAY(SELECT s FROM unnest(scopes) AS s "
    f"WHERE split_part(s, '.', 1) = ANY ({_ALLOWED})) "
    f"WHERE NOT scopes <@ ARRAY(SELECT s FROM unnest(scopes) AS s WHERE split_part(s, '.', 1) = ANY ({_ALLOWED}))"
)


def upgrade() -> None:
    # The owner is subject to forced RLS like everyone else; lift it for this one backfill (as 1331 does).
    op.execute("ALTER TABLE api_key NO FORCE ROW LEVEL SECURITY")
    op.execute(STRIP)
    op.execute("ALTER TABLE api_key FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    pass  # stripped scopes are not restored
