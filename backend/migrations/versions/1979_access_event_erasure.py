"""access: erasure scrubs a person's client id from building event details (code_withheld rows name the person).

Grant change, and why: fh_app gains EXECUTE on app.scrub_building_event_client(uuid) and nothing else; building_event
stays SELECT, INSERT for fh_app (append-only). The function is owned by fh_owner (SECURITY DEFINER) and only replaces
that id with 'erased' in `detail`, in the caller's tenant; it deletes nothing and touches no other column.

Revision ID: 1979
Revises: 1978
"""

from alembic import op

revision = "1979"
down_revision = "1978"

SCRUB = """
CREATE FUNCTION app.scrub_building_event_client(client uuid) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE done integer;
BEGIN
    UPDATE building_event SET detail = replace(detail, client::text, 'erased')
    WHERE tenant_id = app.current_tenant_id() AND strpos(detail, client::text) > 0;
    GET DIAGNOSTICS done = ROW_COUNT;
    RETURN done;
END $$
"""


def upgrade() -> None:
    op.execute(SCRUB)
    op.execute("REVOKE ALL ON FUNCTION app.scrub_building_event_client(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.scrub_building_event_client(uuid) TO fh_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.scrub_building_event_client(uuid)")
