"""Builders shared by the resources, scheduling and programs tests: a small facility made through the API."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from dramatiq import Worker

from app.core.jobs import broker

API = "/api/v1"
DAY = datetime(2031, 5, 5, tzinfo=UTC)  # a Monday, far from any DST change


def at(hour: float, day: datetime = DAY) -> str:
    return (day + timedelta(hours=hour)).isoformat().replace("+00:00", "Z")


def local(zone: str, year: int, month: int, day: int, hour: int, minute: int = 0) -> str:
    return (
        datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(zone))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def ok(response, status: int = 201) -> dict:
    assert response.status_code == status, response.text
    return response.json() if response.content else {}


def facility(client, headers, time_zone: str = "America/Chicago") -> SimpleNamespace:
    """Court 1 split into halves A and B (A has a quarter A1), Court 2, a trainer and a typed class."""
    post = lambda path, body: ok(client.post(f"{API}{path}", headers=headers, json=body))  # noqa: E731
    location = post("/locations", {"name": f"Site {time_zone}", "time_zone": time_zone, "country_code": "US"})["id"]
    group = post("/resource-groups", {"location_id": location, "name": "Courts"})["id"]

    def resource(name: str, **extra) -> str:
        return post("/resources", {"location_id": location, "resource_group_id": group, "name": name} | extra)["id"]

    court = resource("Court 1")
    half_a, half_b = resource("Court 1A", parent_id=court), resource("Court 1B", parent_id=court)
    quarter = resource("Court 1A-1", parent_id=half_a)
    rtype = post(
        "/reservation-types",
        {
            "location_id": location,
            "name": "Clinic",
            "default_capacity": 4,
            "default_allows_free_booking": True,
            "color": "#22aa66",
        },
    )["id"]
    return SimpleNamespace(
        location=location, group=group, court=court, half_a=half_a, half_b=half_b, quarter=quarter,
        court2=resource("Court 2"), coach=resource("Coach Kim", kind="trainer"), type=rtype, zone=time_zone,
    )  # fmt: skip


def booking_body(f, resources: list[str], start: str, end: str, **extra) -> dict:
    body = {
        "location_id": f.location, "kind": "block", "block_kind": "unavailable", "starts_at": start, "ends_at": end,
        "resources": [{"resource_id": r} for r in resources],
    }  # fmt: skip
    if extra.get("kind") == "session":
        body.pop("block_kind")
        body["reservation_type_id"] = f.type
    return body | extra


def book(client, headers, f, resources: list[str], start: str, end: str, **extra):
    return client.post(f"{API}/bookings", headers=headers, json=booking_body(f, resources, start, end, **extra))


def drain() -> None:
    """Run the in-memory broker until every queued job, and the jobs they enqueue, are done."""
    worker = Worker(broker, worker_timeout=100)
    worker.start()
    try:
        broker.join("default")
        worker.join()
    finally:
        worker.stop()
