"""Liveness and readiness (PLT-15): anonymous, no dependency detail beyond ok/failed, 503 when a dependency is down."""

from app.modules.platform import router as platform_router

API = "/api/v1"


def test_liveness_leaks_nothing(client):
    response = client.get(f"{API}/health/live")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_readiness_reports_ok_and_goes_red_when_redis_is_down(client, monkeypatch):
    ready = client.get(f"{API}/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["postgres"] == ready.json()["checks"]["redis"] == "ok"

    class Down:
        def ping(self):
            raise ConnectionError("redis host and password must not leak")

    monkeypatch.setattr(platform_router, "_redis", lambda: Down())
    red = client.get(f"{API}/health/ready")
    assert red.status_code == 503
    assert red.json() == {"status": "unavailable", "checks": {**ready.json()["checks"], "redis": "failed"}}
    assert "leak" not in red.text and "version" not in red.text
