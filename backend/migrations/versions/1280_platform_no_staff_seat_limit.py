"""phase 8 S4: staff seats are not metered (owner decision). Drops the `staff_users` limit from the plans.

Data only. Operator override rows for the key are kept (the catalogue ignores unknown keys), so turning the
meter back on restores them. Downgrade puts the 1250 numbers back.

Revision ID: 1280
Revises: 1263
"""

import sqlalchemy as sa
from alembic import op

revision = "1280"
down_revision = "1264"

_PLAN_LIMITS = {"essentials": 5, "growth": 15}  # as seeded by 1250


def upgrade() -> None:
    op.execute("UPDATE subscription_plan SET limits = limits - 'staff_users' WHERE limits ? 'staff_users'")


def downgrade() -> None:
    for code, seats in _PLAN_LIMITS.items():
        op.execute(
            sa.text(
                "UPDATE subscription_plan SET limits = limits || jsonb_build_object('staff_users', :seats) "
                "WHERE code = :code"
            ).bindparams(code=code, seats=seats)
        )
