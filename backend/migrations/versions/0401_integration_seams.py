"""integration seams between the lanes: packages point at a real reservation type, and a POS cart line can
sell a package (POS-19).

Generated from the models, then completed by hand (the two CHECKs on pos_sale_line). No new table.

A database seeded before this revision holds package plans whose reservation type was a placeholder id (the
scheduling tables did not exist in that lane): the foreign key cannot be created over them. Those are
development databases; recreate them (`make lane-db` after dropping) rather than patching rows here.

Revision ID: 0401
Revises: 0102
"""
import sqlalchemy as sa
from alembic import op

revision = "0401"
down_revision = "0102"

_TARGET = "(line_kind = 'product') = (product_id IS NOT NULL) AND (line_kind = 'equipment') = (equipment_item_id IS NOT NULL)"


def upgrade() -> None:
    for table in ("client_package", "package_plan"):
        op.create_foreign_key(
            op.f(f"fk_{table}_reservation_type_id_reservation_type"), table, "reservation_type",
            ["tenant_id", "reservation_type_id"], ["tenant_id", "id"], ondelete="RESTRICT",
        )  # fmt: skip
    op.add_column("pos_sale_line", sa.Column("package_plan_id", sa.Uuid(), nullable=True))
    op.add_column("pos_sale_line", sa.Column("fulfilment_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_pos_sale_line_package_plan_id"), "pos_sale_line", ["tenant_id", "package_plan_id"])
    op.create_foreign_key(
        op.f("fk_pos_sale_line_package_plan_id_package_plan"), "pos_sale_line", "package_plan",
        ["tenant_id", "package_plan_id"], ["tenant_id", "id"], ondelete="RESTRICT",
    )  # fmt: skip
    op.drop_constraint(op.f("ck_pos_sale_line_line_kind"), "pos_sale_line", type_="check")
    op.drop_constraint(op.f("ck_pos_sale_line_target"), "pos_sale_line", type_="check")
    op.create_check_constraint(
        op.f("ck_pos_sale_line_line_kind"), "pos_sale_line", "line_kind IN ('product', 'equipment', 'package')"
    )
    op.create_check_constraint(
        op.f("ck_pos_sale_line_target"), "pos_sale_line",
        f"{_TARGET} AND (line_kind = 'package') = (package_plan_id IS NOT NULL)",
    )  # fmt: skip


def downgrade() -> None:
    op.execute("DELETE FROM pos_sale_line WHERE line_kind = 'package'")
    op.drop_constraint(op.f("ck_pos_sale_line_target"), "pos_sale_line", type_="check")
    op.drop_constraint(op.f("ck_pos_sale_line_line_kind"), "pos_sale_line", type_="check")
    op.create_check_constraint(op.f("ck_pos_sale_line_line_kind"), "pos_sale_line", "line_kind IN ('product', 'equipment')")
    op.create_check_constraint(op.f("ck_pos_sale_line_target"), "pos_sale_line", _TARGET)
    op.drop_constraint(op.f("fk_pos_sale_line_package_plan_id_package_plan"), "pos_sale_line", type_="foreignkey")
    op.drop_index(op.f("ix_pos_sale_line_package_plan_id"), table_name="pos_sale_line")
    op.drop_column("pos_sale_line", "fulfilment_id")
    op.drop_column("pos_sale_line", "package_plan_id")
    for table in ("package_plan", "client_package"):
        op.drop_constraint(op.f(f"fk_{table}_reservation_type_id_reservation_type"), table, type_="foreignkey")
