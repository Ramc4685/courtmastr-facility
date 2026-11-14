"""access: an entry code belongs to one person (building control review). A session's participants each get their
own code, so ending one enrolment revokes one code and the door checks that person in. A rental's code is its
holder's. Codes from before this revision get their booking's holder; a session's shared code is revoked.

Revision ID: 1973
Revises: 1972
"""

import sqlalchemy as sa
from alembic import op

revision = "1973"
down_revision = "1972"


def _owner_reads(tables: tuple[str, ...], force: bool) -> None:
    """The owner is subject to forced RLS like everyone else; lift it for one backfill (as 1705 does)."""
    for table in tables:
        op.execute(f"ALTER TABLE {table} {'' if force else 'NO '}FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.add_column("entry_code", sa.Column("client_id", sa.Uuid(), nullable=True))
    _owner_reads(("entry_code", "booking"), force=False)
    op.execute(
        "UPDATE entry_code e SET client_id = b.client_id FROM booking b"
        " WHERE b.tenant_id = e.tenant_id AND b.id = e.booking_id"
    )
    op.execute(
        "UPDATE entry_code SET status = 'revoked', revoked_at = now(), revoke_reason = 'superseded'"
        " WHERE client_id IS NULL AND status = 'active'"
    )
    _owner_reads(("entry_code", "booking"), force=True)
    op.create_foreign_key(
        op.f("fk_entry_code_client_id_client"),
        "entry_code",
        "client",
        ["tenant_id", "client_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_entry_code_client_id"), "entry_code", ["tenant_id", "client_id"], unique=False)
    op.create_check_constraint(
        op.f("ck_entry_code_person"), "entry_code", "status <> 'active' OR client_id IS NOT NULL"
    )
    op.drop_index("uq_entry_code_booking", table_name="entry_code", postgresql_where=sa.text("status = 'active'"))
    op.create_index(
        "uq_entry_code_booking",
        "entry_code",
        ["tenant_id", "booking_id", "client_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_entry_code_booking", table_name="entry_code", postgresql_where=sa.text("status = 'active'"))
    _owner_reads(("entry_code",), force=False)
    op.execute(
        "UPDATE entry_code e SET status = 'revoked', revoked_at = now(), revoke_reason = 'superseded'"
        " WHERE status = 'active' AND EXISTS (SELECT 1 FROM entry_code o WHERE o.tenant_id = e.tenant_id"
        " AND o.booking_id = e.booking_id AND o.status = 'active' AND o.id < e.id)"
    )
    _owner_reads(("entry_code",), force=True)
    op.create_index(
        "uq_entry_code_booking",
        "entry_code",
        ["tenant_id", "booking_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_constraint(op.f("ck_entry_code_person"), "entry_code", type_="check")
    op.drop_index(op.f("ix_entry_code_client_id"), table_name="entry_code")
    op.drop_constraint(op.f("fk_entry_code_client_id_client"), "entry_code", type_="foreignkey")
    op.drop_column("entry_code", "client_id")
