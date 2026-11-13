"""access: entry codes retire (building control review). A code whose window has ended becomes `expired` and its
sealed copy is cleared; the tick reads only open or upcoming codes through a partial index. Building events and
spent codes are purged after the access retention period.

Grant change, and why: fh_app gains EXECUTE on app.purge_building_event(timestamptz, integer) and nothing else;
building_event stays SELECT, INSERT for fh_app (append-only, as audit_event with app.purge_audit_event in 1210).
The function is owned by fh_owner (SECURITY DEFINER) and deletes at most `batch` rows older than `cutoff` in the
caller's tenant.

Revision ID: 1976
Revises: 1975
"""

import sqlalchemy as sa
from alembic import op

revision = "1976"
down_revision = "1975"

PURGE_BUILDING_EVENT = """
CREATE FUNCTION app.purge_building_event(cutoff timestamptz, batch integer) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE gone integer;
BEGIN
    DELETE FROM building_event WHERE id IN (
        SELECT id FROM building_event WHERE occurred_at < cutoff AND tenant_id = app.current_tenant_id()
        ORDER BY occurred_at LIMIT batch
    );
    GET DIAGNOSTICS gone = ROW_COUNT;
    RETURN gone;
END $$
"""


def upgrade() -> None:
    op.drop_constraint(op.f("ck_entry_code_status"), "entry_code", type_="check")
    op.create_check_constraint(op.f("ck_entry_code_status"), "entry_code", "status IN ('active', 'revoked', 'expired')")
    op.alter_column("entry_code", "code_ciphertext", existing_type=sa.Text(), nullable=True)
    op.execute("ALTER TABLE entry_code NO FORCE ROW LEVEL SECURITY")  # the owner backfills past codes (as 1705)
    op.execute(
        "UPDATE entry_code SET status = 'expired', code_ciphertext = NULL WHERE status = 'active' AND valid_until_at <= now()"
    )
    op.execute("UPDATE entry_code SET code_ciphertext = NULL WHERE status = 'revoked'")
    op.execute("ALTER TABLE entry_code FORCE ROW LEVEL SECURITY")
    op.create_check_constraint(
        op.f("ck_entry_code_sealed"), "entry_code", "status <> 'active' OR code_ciphertext IS NOT NULL"
    )
    op.create_index(
        "ix_entry_code_open",
        "entry_code",
        ["tenant_id", "location_id", "valid_until_at"],
        unique=False,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.execute(PURGE_BUILDING_EVENT)
    op.execute("REVOKE ALL ON FUNCTION app.purge_building_event(timestamptz, integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.purge_building_event(timestamptz, integer) TO fh_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.purge_building_event(timestamptz, integer)")
    op.drop_index("ix_entry_code_open", table_name="entry_code", postgresql_where=sa.text("status = 'active'"))
    op.drop_constraint(op.f("ck_entry_code_sealed"), "entry_code", type_="check")
    op.execute("ALTER TABLE entry_code NO FORCE ROW LEVEL SECURITY")
    # the sealed copies are gone; spent codes are never decrypted, so an empty placeholder keeps the log's links
    op.execute("UPDATE entry_code SET status = 'revoked', revoked_at = coalesce(revoked_at, valid_until_at),"
               " revoke_reason = coalesce(revoke_reason, 'expired') WHERE status = 'expired'")  # fmt: skip
    op.execute("UPDATE entry_code SET code_ciphertext = '' WHERE code_ciphertext IS NULL")
    op.execute("ALTER TABLE entry_code FORCE ROW LEVEL SECURITY")
    op.alter_column("entry_code", "code_ciphertext", existing_type=sa.Text(), nullable=False)
    op.drop_constraint(op.f("ck_entry_code_status"), "entry_code", type_="check")
    op.create_check_constraint(op.f("ck_entry_code_status"), "entry_code", "status IN ('active', 'revoked')")
