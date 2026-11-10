"""RLS policy template. Every table-creating migration calls enable_rls(); the meta-test checks it did."""

from alembic import op


def enable_rls(
    table: str, *, append_only: bool = False, tenant_column: str = "tenant_id", grants: str | None = None
) -> None:
    grants = grants or ("SELECT, INSERT" if append_only else "SELECT, INSERT, UPDATE, DELETE")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    # FORCE keeps the policy on for the table owner too, so owner-rights code paths fail closed.
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({tenant_column} = (SELECT app.current_tenant_id())) "
        f"WITH CHECK ({tenant_column} = (SELECT app.current_tenant_id()))"
    )
    op.execute(f"GRANT {grants} ON {table} TO fh_app")
