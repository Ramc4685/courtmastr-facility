"""integrations (Phase 15): strip API-key scopes outside the key allow-list (`service.KEY_CONTEXTS` and
`service.KEY_PERMISSIONS`).

Flagged scopes were never grantable, so only the context or the single key matters; both lists are frozen here
as of this revision.
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
_KEYS = (
    "engagement.app_content.manage", "engagement.campaign.create", "engagement.campaign.edit",
    "engagement.campaign.read", "engagement.campaign.send", "engagement.message.send_direct",
    "engagement.push.send",
)  # fmt: skip
_ALLOWED = "ARRAY[" + ", ".join(f"'{c}'" for c in _CONTEXTS) + "]"
_ALLOWED_KEYS = "ARRAY[" + ", ".join(f"'{k}'" for k in _KEYS) + "]"
_KEEP = f"split_part(s, '.', 1) = ANY ({_ALLOWED}) OR s = ANY ({_ALLOWED_KEYS})"
STRIP = (
    f"UPDATE api_key SET scopes = ARRAY(SELECT s FROM unnest(scopes) AS s WHERE {_KEEP}) "
    f"WHERE NOT scopes <@ ARRAY(SELECT s FROM unnest(scopes) AS s WHERE {_KEEP})"
)


def upgrade() -> None:
    # The owner is subject to forced RLS like everyone else; lift it for this one backfill (as 1331 does).
    op.execute("ALTER TABLE api_key NO FORCE ROW LEVEL SECURITY")
    op.execute(STRIP)
    op.execute("ALTER TABLE api_key FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    pass  # stripped scopes are not restored
