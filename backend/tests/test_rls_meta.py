"""Meta-tests over the SQLAlchemy metadata and pg_catalog (overview section 5, ADR 0001 section 8).

A new table that forgets tenant_id, the composite keys or enable_rls() fails here, not in review.
"""

import pytest
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, text

from app.core.db import Base, app_engine
from app.core.db.base import GLOBAL_TABLES

TENANT_TABLES = sorted(set(Base.metadata.tables) - GLOBAL_TABLES)
# Tables that are never updated may omit updated_at (overview 3.4).
NO_UPDATED_AT = {
    "audit_event", "outbox_event", "processed_event", "idempotency_key", "ledger_transaction", "ledger_entry",
    "billing_notice", "stock_movement", "client_merge", "consent_event", "document_acceptance", "credit_ledger_entry",
    "rental_plan_ledger_entry",
}  # fmt: skip
# SELECT and INSERT only: the grant model, not code review, keeps logs and the ledger immutable.
APPEND_ONLY = {
    "audit_event", "ledger_transaction", "ledger_entry", "billing_notice", "stock_movement", "client_merge",
    "consent_event", "document_acceptance", "credit_ledger_entry", "rental_plan_ledger_entry",
}  # fmt: skip


def _catalog(sql: str, **params):
    with app_engine().connect() as conn:
        return conn.execute(text(sql), params).all()


def test_database_and_metadata_list_the_same_tables():
    in_db = {r[0] for r in _catalog("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert in_db - {"alembic_version"} == set(Base.metadata.tables)


@pytest.mark.parametrize("name", TENANT_TABLES)
def test_tenant_table_shape(name):
    table = Base.metadata.tables[name]
    assert "tenant_id" in table.c and not table.c.tenant_id.nullable
    assert [c.name for c in table.primary_key] == ["id"]
    uniques = [tuple(c.name for c in u.columns) for u in table.constraints if isinstance(u, UniqueConstraint)]
    assert ("tenant_id", "id") in uniques
    for fk in (c for c in table.constraints if isinstance(c, ForeignKeyConstraint)):
        if fk.referred_table.name not in GLOBAL_TABLES:
            # A single-column FK would let a bug attach tenant B's row to tenant A (FK checks bypass RLS).
            assert fk.column_keys[0] == "tenant_id", f"{fk.name} is not composite"
            assert [e.column.name for e in fk.elements] == ["tenant_id", "id"]
    assert ("updated_at" in table.c) == (name not in NO_UPDATED_AT)


@pytest.mark.parametrize("name", [*TENANT_TABLES, "tenant"])
def test_rls_enabled_forced_and_policy_present(name):
    enabled, forced = _catalog("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :n", n=name)[0]
    assert enabled and forced
    policies = _catalog(
        "SELECT policyname, cmd, permissive, qual, with_check FROM pg_policies WHERE tablename = :n", n=name
    )
    assert len(policies) == 1  # one permissive policy for all commands, nothing else
    policy = policies[0]
    assert (policy.policyname, policy.cmd, policy.permissive) == ("tenant_isolation", "ALL", "PERMISSIVE")
    assert "app.current_tenant_id()" in policy.qual and "app.current_tenant_id()" in policy.with_check


def test_app_role_cannot_bypass_rls_and_owns_nothing():
    role = _catalog("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user")[0]
    assert _catalog("SELECT current_user")[0][0] == "fh_app"
    assert not role.rolbypassrls and not role.rolsuper
    assert _catalog("SELECT count(*) FROM pg_tables WHERE tableowner = 'fh_app'")[0][0] == 0
    owner = _catalog("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'fh_owner'")[0]
    assert not owner.rolbypassrls and not owner.rolsuper  # FORCE keeps even the owner inside the policy


def test_app_role_grants():
    def privileges(table: str) -> set[str]:
        rows = _catalog(
            "SELECT privilege_type FROM information_schema.role_table_grants WHERE grantee = 'fh_app' AND table_name = :t",
            t=table,
        )
        return {r[0] for r in rows}

    for name in APPEND_ONLY:
        assert privileges(name) == {"SELECT", "INSERT"}, name
    assert privileges("tenant") == {"SELECT", "UPDATE"}  # provisioning is fh_platform's job
    assert privileges("subscription_plan") == {"SELECT"}
    for name in set(TENANT_TABLES) - APPEND_ONLY:
        assert privileges(name) == {"SELECT", "INSERT", "UPDATE", "DELETE"}, name
