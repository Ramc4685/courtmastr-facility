"""engagement W2-08: a push token is unique among live device registrations only, so registering a token that
another login holds revokes that row and adds a new one instead of reassigning it.

Revision ID: 0802
Revises: 0952
"""
import sqlalchemy as sa
from alembic import op

revision = "0802"
down_revision = "0952"


def upgrade() -> None:
    op.drop_constraint("uq_device_registration_push_token", "device_registration", type_="unique")
    op.create_index(
        "uq_device_registration_push_token", "device_registration", ["tenant_id", "push_token"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_device_registration_push_token", table_name="device_registration")
    op.create_unique_constraint(
        "uq_device_registration_push_token", "device_registration", ["tenant_id", "push_token"]
    )
