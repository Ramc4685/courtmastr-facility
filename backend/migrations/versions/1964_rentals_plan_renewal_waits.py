"""rentals: an auto-renewal that waits on the plan's waiver (ADR 0013; review 2026-11-13).

`rental_plan_purchase.renewal_waits_since`: set when a renewal finds no valid acceptance of the plan's waiver
(every_purchase, a lapsed signature, or a purchase that predates the binding), cleared when it renews.

Revision ID: 1964
Revises: 1962
"""

import sqlalchemy as sa
from alembic import op

revision = "1964"
down_revision = "1962"


def upgrade() -> None:
    op.add_column("rental_plan_purchase", sa.Column("renewal_waits_since", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("rental_plan_purchase", "renewal_waits_since")
