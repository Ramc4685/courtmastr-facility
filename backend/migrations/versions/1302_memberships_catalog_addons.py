"""memberships: pre-defined billing items as plan and contract add-ons (MEM-04), and the `addon_item`
schedule rows they bill through.

Revision ID: 1302
Revises: 1301
"""

import sqlalchemy as sa
from alembic import op

revision = "1302"
down_revision = "1301"


def upgrade() -> None:
    op.add_column("billing_schedule_period", sa.Column("catalog_item_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_billing_schedule_period_catalog_item_id"),
        "billing_schedule_period",
        ["tenant_id", "catalog_item_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_billing_schedule_period_catalog_item_id_catalog_item"),
        "billing_schedule_period",
        "catalog_item",
        ["tenant_id", "catalog_item_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.add_column("membership_contract_addon", sa.Column("catalog_item_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_membership_contract_addon_catalog_item_id"),
        "membership_contract_addon",
        ["tenant_id", "catalog_item_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_membership_contract_addon_catalog_item_id_catalog_item"),
        "membership_contract_addon",
        "catalog_item",
        ["tenant_id", "catalog_item_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.add_column("membership_plan_addon", sa.Column("catalog_item_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_membership_plan_addon_catalog_item_id"),
        "membership_plan_addon",
        ["tenant_id", "catalog_item_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_membership_plan_addon_catalog_item_id_catalog_item"),
        "membership_plan_addon",
        "catalog_item",
        ["tenant_id", "catalog_item_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    for table in ("membership_plan_addon", "membership_contract_addon"):
        op.drop_constraint(op.f(f"ck_{table}_target"), table, type_="check")
        op.create_check_constraint(
            "target",
            table,
            "(addon_kind = 'package_plan') = (package_plan_id IS NOT NULL) "
            "AND (addon_kind = 'catalog_item') = (catalog_item_id IS NOT NULL)",
        )
    op.create_check_constraint(
        "addon_item", "billing_schedule_period", "(kind = 'addon_item') = (catalog_item_id IS NOT NULL)"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_billing_schedule_period_addon_item"), "billing_schedule_period", type_="check")
    for table in ("membership_plan_addon", "membership_contract_addon"):
        op.drop_constraint(op.f(f"ck_{table}_target"), table, type_="check")
        op.create_check_constraint("target", table, "(addon_kind = 'package_plan') = (package_plan_id IS NOT NULL)")
    op.drop_constraint(
        op.f("fk_membership_plan_addon_catalog_item_id_catalog_item"), "membership_plan_addon", type_="foreignkey"
    )
    op.drop_index(op.f("ix_membership_plan_addon_catalog_item_id"), table_name="membership_plan_addon")
    op.drop_column("membership_plan_addon", "catalog_item_id")
    op.drop_constraint(
        op.f("fk_membership_contract_addon_catalog_item_id_catalog_item"),
        "membership_contract_addon",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_membership_contract_addon_catalog_item_id"), table_name="membership_contract_addon")
    op.drop_column("membership_contract_addon", "catalog_item_id")
    op.drop_constraint(
        op.f("fk_billing_schedule_period_catalog_item_id_catalog_item"), "billing_schedule_period", type_="foreignkey"
    )
    op.drop_index(op.f("ix_billing_schedule_period_catalog_item_id"), table_name="billing_schedule_period")
    op.drop_column("billing_schedule_period", "catalog_item_id")
