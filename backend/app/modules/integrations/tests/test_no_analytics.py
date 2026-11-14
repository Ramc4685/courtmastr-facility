"""INT-13 dropped by owner decision 2026-11-13 (question 6): no third-party analytics connection and no anonymous
analytics config route (security-baseline V10)."""

import importlib.util
import os

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.core.db import Base
from app.core.settings import get_settings
from app.modules.scheduling.tests.helpers import API

_1951 = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "migrations", "versions",
                     "1951_integrations_drop_analytics_provider.py")  # fmt: skip


def test_analytics_connections_and_config_are_gone(client, tenant, owner):
    body = {"provider": "google_analytics", "settings": {"measurement_id": "G-AB12CD34"}}
    assert client.post(f"{API}/external-connections", headers=owner, json=body).status_code == 422
    assert client.get(f"{API}/public/analytics-config", headers={"X-Tenant-Slug": tenant.slug}).status_code == 404


def test_migration_1951_removes_existing_analytics_connections(tenant):
    """The owner is subject to forced RLS: the delete must see every tenant's rows, or the new CHECK fails.

    Runs 1951's own downgrade and upgrade in one owner transaction that is rolled back: the shared test database is
    never walked down the history (a later migration's guard may rightly refuse that), and other tests see nothing."""
    spec = importlib.util.spec_from_file_location("m1951", _1951)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(get_settings().db_url("owner"))
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})):
                migration.downgrade()
                connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant.id)})
                connection.execute(text("INSERT INTO external_connection (tenant_id, id, provider, settings) "
                                        "VALUES (:t, gen_random_uuid(), 'google_analytics', '{}')"), {"t": tenant.id})  # fmt: skip
                connection.execute(text("SELECT set_config('app.tenant_id', '', true)"))
                migration.upgrade()
            connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant.id)})
            left = "SELECT count(*) FROM external_connection WHERE provider = 'google_analytics'"
            assert connection.scalar(text(left)) == 0
        finally:
            transaction.rollback()
    engine.dispose()
