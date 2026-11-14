"""access: a held entry code is a row (`entry_code_hold`), not text in a building event's detail (security review:
erasure rewrote that text and the parser then failed for the whole tenant). Existing `age-not-confirmed` events
are copied into holds once, only where the detail is well formed and the booking and client still exist; the
events stay as display text.

Revision ID: 1980
Revises: 1979
"""

import sqlalchemy as sa
from alembic import op

from app.core.db.rls import enable_rls

revision = "1980"
down_revision = "1979"

_READ = ("entry_code_hold", "building_event", "booking", "client", "entry_code")
UUID_RE = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def upgrade() -> None:
    op.create_table(
        "entry_code_hold",
        sa.Column("id", sa.Uuid(), server_default=sa.text("app.uuid_v7()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("reason IN ('age-not-confirmed')", name=op.f("ck_entry_code_hold_reason")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "booking_id"],
            ["booking.tenant_id", "booking.id"],
            name=op.f("fk_entry_code_hold_booking_id_booking"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["tenant_id", "client_id"],
            ["client.tenant_id", "client.id"],
            name=op.f("fk_entry_code_hold_client_id_client"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["location.tenant_id", "location.id"],
            name=op.f("fk_entry_code_hold_location_id_location"),
            ondelete="RESTRICT",
        ),  # fmt: skip
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name=op.f("fk_entry_code_hold_tenant_id_tenant"), ondelete="RESTRICT"
        ),  # fmt: skip
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entry_code_hold")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_entry_code_hold_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "booking_id", "client_id", name="uq_entry_code_hold"),
    )
    op.create_index(op.f("ix_entry_code_hold_booking_id"), "entry_code_hold", ["tenant_id", "booking_id"])
    op.create_index(op.f("ix_entry_code_hold_client_id"), "entry_code_hold", ["tenant_id", "client_id"])
    op.create_index("ix_entry_code_hold_location", "entry_code_hold", ["tenant_id", "location_id"])
    enable_rls("entry_code_hold")
    # the owner copies existing holds across tenants once (as 1705); FORCE comes back right after
    for table in _READ:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        INSERT INTO entry_code_hold (tenant_id, location_id, booking_id, client_id, reason, created_at)
        SELECT DISTINCT ON (e.tenant_id, m[1]::uuid, m[2]::uuid)
               e.tenant_id, e.location_id, m[1]::uuid, m[2]::uuid, 'age-not-confirmed', e.occurred_at
        FROM building_event e
        CROSS JOIN LATERAL regexp_match(e.detail, '^age-not-confirmed:booking:({UUID_RE}):client:({UUID_RE})$') AS m
        JOIN booking bk ON bk.tenant_id = e.tenant_id AND bk.id = m[1]::uuid
        JOIN client c ON c.tenant_id = e.tenant_id AND c.id = m[2]::uuid
        WHERE e.kind = 'code_withheld' AND m IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM entry_code ec WHERE ec.tenant_id = e.tenant_id AND ec.booking_id = m[1]::uuid
                          AND ec.client_id = m[2]::uuid AND ec.status = 'active')
        ORDER BY e.tenant_id, m[1]::uuid, m[2]::uuid, e.occurred_at
    """)
    for table in _READ:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("entry_code_hold")
