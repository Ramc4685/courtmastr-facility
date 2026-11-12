"""platform S3 review fix: auth_token.purpose gains oidc_link (a first OIDC sign-in, confirmed by email).

Revision ID: 1241
Revises: 1240
"""

from alembic import op

revision = "1241"
down_revision = "1240"

_PURPOSES = (
    "'magic_link', 'password_reset', 'invite', 'email_verify', 'email_change', 'relationship_confirm', 'mfa_challenge', "
    "'oidc_state'"
)


def _purposes(condition: str) -> None:
    op.drop_constraint(op.f("ck_auth_token_purpose"), "auth_token", type_="check")
    op.create_check_constraint("purpose", "auth_token", condition)


def upgrade() -> None:
    _purposes(f"purpose IN ({_PURPOSES}, 'oidc_link')")


def downgrade() -> None:
    op.execute("DELETE FROM auth_token WHERE purpose = 'oidc_link'")
    _purposes(f"purpose IN ({_PURPOSES})")
