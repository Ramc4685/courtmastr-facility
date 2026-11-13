"""INT-13 dropped by owner decision 2026-11-13 (question 6): no third-party analytics connection and no anonymous
analytics config route (security-baseline V10)."""

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from app.core.db.session import tenant_session
from app.modules.integrations.models import ExternalConnection
from app.modules.scheduling.tests.helpers import API

ALEMBIC = Config(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "alembic.ini"))


def test_analytics_connections_and_config_are_gone(client, tenant, owner):
    body = {"provider": "google_analytics", "settings": {"measurement_id": "G-AB12CD34"}}
    assert client.post(f"{API}/external-connections", headers=owner, json=body).status_code == 422
    assert client.get(f"{API}/public/analytics-config", headers={"X-Tenant-Slug": tenant.slug}).status_code == 404


def test_migration_1951_removes_existing_analytics_connections(tenant):
    """The owner is subject to forced RLS: the delete must see every tenant's rows, or the new CHECK fails."""
    command.downgrade(ALEMBIC, "1562")
    try:
        with tenant_session(tenant.id) as session:
            session.execute(text("INSERT INTO external_connection (tenant_id, id, provider, settings) "
                                 "VALUES (:t, gen_random_uuid(), 'google_analytics', '{}')"), {"t": tenant.id})  # fmt: skip
    finally:
        command.upgrade(ALEMBIC, "head")
    with tenant_session(tenant.id) as session:
        left = select(func.count()).where(ExternalConnection.provider == "google_analytics")
        assert session.scalar(left) == 0
