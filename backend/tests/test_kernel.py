"""Shared kernel: ids, clock, tenant_session, error rendering, idempotency, pagination, outbox, jobs."""

import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from dramatiq import Worker
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app import relay
from app.core import clock, events, idempotency
from app.core.audit import AuditEvent
from app.core.db import app_engine, tenant_session
from app.core.errors import Conflict, DomainError
from app.core.events import Event, OutboxEvent, handles
from app.core.ids import new_id
from app.core.jobs import broker, tenant_actor
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.main import app
from app.modules.platform.models import Location, Role
from conftest import login, make_tenant, scalar

API = "/api/v1"


# --- ids, clock, settings -----------------------------------------------------------------------------------


def test_uuid_v7_is_time_ordered_in_python_and_sql():
    ids = [new_id() for _ in range(200)]
    assert all(i.version == 7 and i.variant == "specified in RFC 4122" for i in ids)
    assert len(set(ids)) == 200
    with clock.freeze(datetime(2026, 1, 1, tzinfo=UTC)):
        assert clock.now() == datetime(2026, 1, 1, tzinfo=UTC)
    assert clock.now() > datetime(2026, 1, 1, tzinfo=UTC)
    first = new_id()
    time.sleep(0.002)
    assert first < new_id()  # millisecond prefix: later ids sort later
    with app_engine().connect() as conn:
        from_sql = UUID(str(conn.execute(text("SELECT app.uuid_v7()")).scalar()))
    assert from_sql.version == 7 and abs((from_sql.int >> 80) - (new_id().int >> 80)) < 5000  # same clock, within 5 s


def test_settings_carry_the_display_name_in_one_place(client):
    settings = get_settings()
    # Tests never touch a development database; a lane names its own test database (FH_TEST_DB_NAME).
    assert settings.env == "test" and settings.db.name == os.environ.get("FH_TEST_DB_NAME", "facilityhub_test")
    assert settings.app.display_name == "Courtmastr Facility"
    assert client.get(f"{API}/openapi.json").json()["info"]["title"] == "Courtmastr Facility API"
    assert "password" not in json.dumps(settings.model_dump()).lower().replace("password_", "")  # secrets stay in env


# --- tenant_session ----------------------------------------------------------------------------------------


def test_tenant_session_stamps_and_guards_tenant_id(tenant):
    other = make_tenant()
    with tenant_session(tenant.id) as session:
        role = Role(name="Stamped")
        session.add(role)
        session.flush()
        assert role.tenant_id == tenant.id and role.id.version == 7
        assert session.execute(text("SELECT app.current_tenant_id()")).scalar() == tenant.id
    with pytest.raises(RuntimeError, match="tenant_id other than the session's"), tenant_session(tenant.id) as session:
        session.add(Role(name="Smuggled", tenant_id=other.id))
    # Even raw SQL that names the wrong tenant is rejected by WITH CHECK.
    with pytest.raises(DBAPIError, match="row-level security"), tenant_session(tenant.id) as session:
        session.execute(text("INSERT INTO role (tenant_id, name) VALUES (:t, 'Raw')"), {"t": other.id})
    # A composite foreign key cannot point at another tenant's row, whatever RLS says.
    other_role = scalar(other, select(Role.id).limit(1))
    with pytest.raises(DBAPIError, match="fk_role_cloned_from_role_id_role"), tenant_session(tenant.id) as session:
        session.execute(
            text("INSERT INTO role (tenant_id, name, cloned_from_role_id) VALUES (:t, 'Cross', :r)"),
            {"t": tenant.id, "r": other_role},
        )


def test_tenant_setting_does_not_leak_across_pooled_connections(tenant):
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(Role)) == 8
    with app_engine().connect() as conn:  # very likely the same pooled connection
        assert conn.execute(text("SELECT app.current_tenant_id()")).scalar() is None
        assert conn.execute(text("SELECT count(*) FROM role")).scalar() == 0


def test_rollback_on_error(tenant):
    with pytest.raises(Conflict), tenant_session(tenant.id) as session:
        session.add(Role(name="Never"))
        session.flush()
        raise Conflict("stop")
    assert scalar(tenant, select(func.count()).select_from(Role).where(Role.name == "Never")) == 0


# --- error model -------------------------------------------------------------------------------------------


def test_errors_are_problem_json(client, tenant, owner):
    missing = client.get(f"{API}/nope")
    assert missing.status_code == 404 and missing.headers["content-type"] == "application/problem+json"
    body = missing.json()
    assert body == {
        "type": "/problems/not-found",
        "title": "Not found",
        "status": 404,
        "code": "not-found",
        "instance": f"{API}/nope",
        "trace_id": body["trace_id"],
    }
    assert missing.headers["x-request-id"] == body["trace_id"]
    assert client.delete(f"{API}/tenant", headers=owner).json()["code"] == "method-not-allowed"
    invalid = client.post(f"{API}/locations", headers=owner, json={"name": "", "time_zone": 5}).json()
    assert invalid["code"] == "validation-failed" and invalid["status"] == 422
    assert {e["pointer"] for e in invalid["errors"]} == {"/name", "/time_zone", "/country_code"}
    assert client.get(f"{API}/locations/not-a-uuid", headers=owner).json()["errors"][0]["pointer"] == "/location_id"
    assert (
        client.get(f"{API}/tenant", headers={**owner, "X-Request-ID": "<script>"}).headers["x-request-id"] != "<script>"
    )


def test_unexpected_errors_carry_only_a_trace_id(tenant, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.modules.platform import service

    quiet = TestClient(app, raise_server_exceptions=False)
    headers = login(quiet, tenant)
    monkeypatch.setattr(service, "get_tenant", lambda session: 1 / 0)
    body = quiet.get(f"{API}/tenant", headers=headers).json()
    assert body["status"] == 500 and body["code"] == "internal-error" and "detail" not in body and body["trace_id"]
    assert DomainError("x").status == 400


# --- idempotency -------------------------------------------------------------------------------------------


def test_idempotent_replay(client, tenant, owner):
    headers = {**owner, "Idempotency-Key": "create-main-1"}
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    first = client.post(f"{API}/locations", headers=headers, json=body)
    replay = client.post(f"{API}/locations", headers=headers, json=body)
    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json() and replay.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in first.headers
    assert scalar(tenant, select(func.count()).select_from(Location)) == 1  # exactly one side effect
    assert (
        scalar(
            tenant, select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "platform.location.create")
        )
        == 1
    )

    reused = client.post(f"{API}/locations", headers=headers, json={**body, "name": "Other"})
    assert reused.status_code == 422 and reused.json()["code"] == "idempotency-key-reused"
    # The key is scoped to the principal and route: another route may reuse the same string.
    assert client.post(f"{API}/roles", headers=headers, json={"name": "Scoped"}).status_code == 201
    # Without the header nothing is remembered.
    assert client.post(f"{API}/locations", headers=owner, json=body).status_code == 409


def test_failed_request_releases_the_key(client, tenant, owner):
    headers = {**owner, "Idempotency-Key": "retry-me"}
    bad = client.post(
        f"{API}/locations", headers=headers, json={"name": "Main", "time_zone": "Not/AZone", "country_code": "US"}
    )
    assert bad.status_code == 422  # failed in the service, rolled back
    good = client.post(
        f"{API}/locations", headers=headers, json={"name": "Main", "time_zone": "UTC", "country_code": "US"}
    )
    assert good.status_code == 201 and "idempotent-replayed" not in good.headers


def test_concurrent_duplicate_is_request_in_progress(client, tenant, owner):
    body = {"name": "Main", "time_zone": "UTC", "country_code": "US"}
    headers = {**owner, "Idempotency-Key": "in-flight"}
    assert client.post(f"{API}/locations", headers=headers, json=body).status_code == 201
    row = scalar(tenant, select(idempotency.IdempotencyKey))
    assert row.scope == f"{tenant.owner_id}:/locations" and row.status == "completed" and row.response_status == 201
    with tenant_session(tenant.id) as session:  # put the claim back to "the first request is still running"
        session.execute(text("UPDATE idempotency_key SET status = 'in_progress'"))
    duplicate = client.post(f"{API}/locations", headers=headers, json=body)
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "request-in-progress"
    body["name"] = "Second"
    # Two truly concurrent calls: one succeeds, the other is a replay or an in-progress conflict; one row.
    results = []

    def call():
        return results.append(
            client.post(f"{API}/locations", headers={**owner, "Idempotency-Key": "race"}, json=body).status_code
        )

    threads = [threading.Thread(target=call) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) in ([201, 201], [201, 409])
    assert scalar(tenant, select(func.count()).select_from(Location)) == 2
    # Keys live 24 hours; after that the same key is a new request (here it re-runs into the duplicate name).
    with clock.freeze(clock.now() + timedelta(hours=25)):
        later = {**login(client, tenant), "Idempotency-Key": "race"}
        assert client.post(f"{API}/locations", headers=later, json=body).json()["code"] == "already-exists"


# --- pagination, filtering, sorting ------------------------------------------------------------------------


@pytest.fixture
def five_locations(client, tenant, owner):
    for index, name in enumerate(["Echo", "Alpha", "Delta", "Bravo", "Charlie"]):
        body = {"name": name, "time_zone": "UTC", "country_code": "US", "sort_order": index % 2}
        assert client.post(f"{API}/locations", headers=owner, json=body).status_code == 201
    return owner


def _walk(client, headers, query: str) -> list[dict]:
    rows, cursor, pages = [], None, 0
    while True:
        page = client.get(f"{API}/locations?{query}" + (f"&cursor={cursor}" if cursor else ""), headers=headers).json()
        rows += page["data"]
        pages += 1
        cursor = page["page"]["next_cursor"]
        assert page["page"]["has_more"] == (cursor is not None)
        if cursor is None:
            return rows, pages


def test_keyset_pagination(client, five_locations):
    rows, pages = _walk(client, five_locations, "limit=2&sort=name")
    assert [r["name"] for r in rows] == ["Alpha", "Bravo", "Charlie", "Delta", "Echo"] and pages == 3
    rows, _ = _walk(client, five_locations, "limit=2&sort=-name")
    assert [r["name"] for r in rows] == ["Echo", "Delta", "Charlie", "Bravo", "Alpha"]
    # Mixed directions with ties: sort_order descending, then name ascending, id as the final tiebreaker.
    rows, _ = _walk(client, five_locations, "limit=1&sort=-sort_order,name")
    assert [(r["sort_order"], r["name"]) for r in rows] == [
        (1, "Alpha"),
        (1, "Bravo"),
        (0, "Charlie"),
        (0, "Delta"),
        (0, "Echo"),
    ]
    default, _ = _walk(client, five_locations, "limit=2")  # default sort: sort_order, name
    assert [r["name"] for r in default] == ["Charlie", "Delta", "Echo", "Alpha", "Bravo"]
    by_created, _ = _walk(client, five_locations, "limit=2&sort=created_at")
    assert [r["name"] for r in by_created] == ["Echo", "Alpha", "Delta", "Bravo", "Charlie"]

    first = client.get(f"{API}/locations?limit=2&include=total", headers=five_locations).json()
    assert first["page"] == {"next_cursor": first["page"]["next_cursor"], "has_more": True, "total": 5}
    assert client.get(f"{API}/locations?limit=2", headers=five_locations).json()["page"]["total"] is None
    everything = client.get(f"{API}/locations", headers=five_locations).json()
    assert (
        len(everything["data"]) == 5
        and everything["page"]["next_cursor"] is None
        and everything["page"]["has_more"] is False
    )


def test_pages_are_stable_under_inserts(client, five_locations):
    first = client.get(f"{API}/locations?limit=2&sort=name", headers=five_locations).json()
    client.post(
        f"{API}/locations", headers=five_locations, json={"name": "Aardvark", "time_zone": "UTC", "country_code": "US"}
    )
    second = client.get(
        f"{API}/locations?limit=2&sort=name&cursor={first['page']['next_cursor']}", headers=five_locations
    ).json()
    assert [r["name"] for r in second["data"]] == ["Charlie", "Delta"]  # offset paging would repeat Bravo


def test_list_parameter_validation(client, five_locations):
    def get(query):
        response = client.get(f"{API}/locations?{query}", headers=five_locations)
        return response.status_code, response.json().get("code")

    assert get("limit=0") == (422, "validation-failed") and get("limit=201") == (422, "validation-failed")
    assert get("colour=red") == (400, "bad-request")  # unknown parameters are rejected, not ignored
    assert get("status[like]=act") == (400, "bad-request")
    assert get("sort=time_zone") == (400, "bad-request")
    assert get("cursor=not-a-cursor") == (400, "bad-request")
    name_cursor = client.get(f"{API}/locations?limit=1&sort=name", headers=five_locations).json()["page"]["next_cursor"]
    assert get(f"limit=1&sort=sort_order,name&cursor={name_cursor}") == (400, "bad-request")  # cursor from another sort
    assert get("status[in]=active,inactive")[0] == 200 and get("status[ne]=active")[0] == 200
    assert client.get(f"{API}/locations?status[ne]=active", headers=five_locations).json()["data"] == []


def test_paginate_filter_operators(tenant):
    """The comparison operators, directly against the helper."""
    with tenant_session(tenant.id) as session:
        fields = {"created_at": Role.created_at, "is_system": Role.is_system, "id": Role.id}

        def run(**filters):
            return paginate(
                session,
                select(Role),
                ListQuery(filters=filters),
                id_column=Role.id,
                sort_fields={},
                filter_fields=fields,
            )["data"]

        assert len(run(**{"is_system": "true"})) == 8 and run(**{"is_system": "false"}) == []
        assert (
            len(run(**{"created_at[lte]": "2999-01-01T00:00:00Z"})) == 8
            and run(**{"created_at[gt]": "2999-01-01T00:00:00Z"}) == []
        )
        assert len(run(**{"created_at[lt]": "2999-01-01"})) == 8
        some = run()[0].id
        assert [r.id for r in run(**{"id": str(some)})] == [some] and len(run(**{"id[ne]": str(some)})) == 7
        for bad in ({"is_system": "maybe"}, {"id": "nope"}, {"created_at[gte]": "soon"}):
            with pytest.raises(DomainError):
                run(**bad)


# --- outbox, relay, jobs -----------------------------------------------------------------------------------


class ThingHappened(Event):
    aggregate_type = "thing"
    type: str = "tests.thing.happened"
    thing_id: UUID


_seen: list[tuple[UUID, str]] = []


@handles("tests.thing.happened")
def _on_thing(session, payload):
    _seen.append((session.info["tenant_id"], payload["thing_id"]))
    # Proves the handler runs inside tenant_session as a system actor.
    assert session.info["actor"].kind == "system" and session.execute(text("SELECT count(*) FROM tenant")).scalar() == 1


@tenant_actor
def _count_roles(session, minimum):
    assert session.scalar(select(func.count()).select_from(Role)) >= minimum
    _seen.append((session.info["tenant_id"], "counted"))


def _drain():
    worker = Worker(broker, worker_timeout=100)
    worker.start()
    try:
        broker.join("default")
        worker.join()
    finally:
        worker.stop()


def test_outbox_rolled_back_transaction_leaves_no_event(tenant):
    thing = uuid4()
    with pytest.raises(Conflict), tenant_session(tenant.id) as session:
        events.publish(session, ThingHappened(thing_id=thing), thing)
        session.flush()
        raise Conflict("abort")
    assert scalar(tenant, select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == thing)) == 0


def test_outbox_delivers_committed_events_once_per_handler(tenant):
    _seen.clear()
    thing = uuid4()
    with tenant_session(tenant.id) as session:
        events.publish(session, ThingHappened(thing_id=thing), thing)
    row = scalar(tenant, select(OutboxEvent).where(OutboxEvent.aggregate_id == thing))
    assert row.published_at is None and row.payload == {
        "type": "tests.thing.happened",
        "schema_version": 1,
        "thing_id": str(thing),
    }
    assert relay.relay_once() >= 1
    while relay.relay_once():  # batches of 200; other tests leave events behind
        pass
    _drain()
    assert _seen == [(tenant.id, str(thing))]
    published = scalar(tenant, select(OutboxEvent).where(OutboxEvent.aggregate_id == thing))
    assert published.published_at is not None and published.attempts == 1
    # At-least-once delivery: the same message again has no second effect.
    _on_thing.send(str(tenant.id), str(row.id), row.payload)
    _drain()
    assert _seen == [(tenant.id, str(thing))]


def test_tenant_actor_runs_inside_the_tenant(tenant):
    _seen.clear()
    _count_roles.send(str(tenant.id), 8)
    _drain()
    assert _seen == [(tenant.id, "counted")]
    assert _count_roles.actor_name == "_count_roles"


def test_platform_events_reach_the_outbox(client, tenant, owner):
    client.post(f"{API}/locations", headers=owner, json={"name": "Main", "time_zone": "UTC", "country_code": "US"})
    with tenant_session(tenant.id) as session:
        types = set(session.scalars(select(OutboxEvent.event_type)))
    assert types == {"platform.tenant.created", "platform.location.created"}


def test_openapi_document(client):
    spec = client.get(f"{API}/openapi.json").json()
    assert spec["openapi"].startswith("3.1")
    operations = {
        op["operationId"]: (method, path) for path, ops in spec["paths"].items() for method, op in ops.items()
    }
    assert operations["signIn"] == ("post", f"{API}/auth/sign-in") and operations["listAuditEvents"] == (
        "get",
        f"{API}/audit-events",
    )
    assert len(operations) >= 47
    # SameSite=Lax means every state-changing route must be non-GET; GETs here are reads by name.
    assert all(name.startswith(("get", "list")) for name, (method, _) in operations.items() if method == "get")


def test_committed_openapi_snapshot_is_current():
    """backend/openapi.json feeds the web client's generated types; `make openapi` after any API change."""
    snapshot = json.loads((Path(__file__).resolve().parents[1] / "openapi.json").read_text())
    assert snapshot == json.loads(json.dumps(app.openapi())), "run `make openapi` and `make web-api`"
