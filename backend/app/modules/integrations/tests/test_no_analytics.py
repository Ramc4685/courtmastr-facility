"""INT-13 dropped by owner decision 2026-11-13 (question 6): no third-party analytics connection and no anonymous
analytics config route (security-baseline V10)."""

from app.modules.scheduling.tests.helpers import API


def test_analytics_connections_and_config_are_gone(client, tenant, owner):
    body = {"provider": "google_analytics", "settings": {"measurement_id": "G-AB12CD34"}}
    assert client.post(f"{API}/external-connections", headers=owner, json=body).status_code == 422
    assert client.get(f"{API}/public/analytics-config", headers={"X-Tenant-Slug": tenant.slug}).status_code == 404
