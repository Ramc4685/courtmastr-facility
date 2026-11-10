"""Tenant isolation, proven through raw SQL as fh_app and through the API (definition of done).

`two_tenants` gives A and B a row in every tenant-owned table; a table added later joins these generated
tests automatically and fails until the fixture populates it.
"""

import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import app_engine, tenant_session
from app.main import app
from conftest import WEEK
from tests.test_rls_meta import TENANT_TABLES


def _count(tenant_id, sql: str, **params) -> int:
    with tenant_session(tenant_id) as session:
        return session.execute(text(sql), params).scalar()


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_no_cross_tenant_read(two_tenants, table):
    a, b = (t.tenant.id for t in two_tenants)
    assert _count(a, f"SELECT count(*) FROM {table}") > 0, "fixture must populate every table"
    assert _count(b, f"SELECT count(*) FROM {table}") > 0
    assert _count(a, f"SELECT count(*) FROM {table} WHERE tenant_id = :b", b=b) == 0
    assert _count(a, f"SELECT count(*) FROM {table} WHERE tenant_id <> :a", a=a) == 0


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_no_cross_tenant_write(two_tenants, table):
    a, b = (t.tenant.id for t in two_tenants)
    before = _count(b, f"SELECT count(*) FROM {table}")
    for statement in (
        f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :b",
        f"DELETE FROM {table} WHERE tenant_id = :b",
    ):
        try:
            with tenant_session(a) as session:
                assert session.execute(text(statement), {"b": b}).rowcount == 0  # B's rows are invisible
        except DBAPIError as exc:
            assert "permission denied" in str(exc)  # append-only tables refuse the verb outright
    # Take one of A's own rows, give it a new id and B's tenant_id, and try to insert it.
    forged = (
        f"INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table}, to_jsonb(r) || "
        f"jsonb_build_object('id', app.uuid_v7(), 'tenant_id', CAST(:b AS uuid)))).* FROM {table} r LIMIT 1"
    )
    with pytest.raises(DBAPIError, match="row-level security"), tenant_session(a) as session:
        session.execute(text(forged), {"b": b})
    assert _count(b, f"SELECT count(*) FROM {table}") == before


@pytest.mark.parametrize("table", [*TENANT_TABLES, "tenant"])
def test_no_tenant_context_sees_nothing(two_tenants, table):
    """Fail closed: a connection that never set app.tenant_id reads zero rows."""
    with app_engine().connect() as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
        conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))  # what a pooled connection reverts to
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_tenant_row_is_private(two_tenants):
    a, b = (t.tenant.id for t in two_tenants)
    assert _count(a, "SELECT count(*) FROM tenant") == 1
    with tenant_session(a) as session:
        assert session.execute(text("UPDATE tenant SET name = 'hijacked' WHERE id = :b"), {"b": b}).rowcount == 0
    with pytest.raises(DBAPIError, match="permission denied"), tenant_session(a) as session:
        session.execute(text("INSERT INTO tenant (name, slug, default_time_zone) VALUES ('x', 'x-forged', 'UTC')"))


# --- API ---------------------------------------------------------------------------------------------------

_BODIES = {
    "updateLocation": {"name": "Renamed"},
    "replaceFacilityHours": {"days": WEEK},
    "updateStaffUser": {"first_name": "Renamed"},
    "assignStaffRole": "role",
    "assignStaffLocations": {"has_all_location_access": True},
    "replaceStaffPermissionOverrides": {"grants": []},
    "updateRole": {"name": "Renamed"},
    "replaceRolePermissions": {"grants": []},
}
# Generated from the OpenAPI document, so a new route with an id parameter is tested without being listed.
_ID_ROUTES = [
    (method.upper(), path, operation["operationId"])
    for path, operations in app.openapi()["paths"].items()
    if "{" in path
    for method, operation in operations.items()
]


@pytest.mark.parametrize(("method", "path", "name"), _ID_ROUTES, ids=[f"{m} {p}" for m, p, _ in _ID_ROUTES])
def test_api_foreign_tenant_id_is_404(client, two_tenants, method, path, name):
    """Every route with an id parameter, called with A's token and B's id: 404, never 403 or data."""
    a, b = two_tenants
    url = re.sub(r"\{(\w+)_id\}", lambda m: str(getattr(b, f"{m[1]}_id")), path)
    body = _BODIES.get(name)
    if body == "role":
        body = {"role_id": a.role_id}  # A's own role, so only the path id is foreign
    response = client.request(method, url, headers=a.headers, json=body)
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not-found"


def test_every_id_route_is_covered():
    assert len(_ID_ROUTES) >= 21
    assert {name for _, _, name in _ID_ROUTES if name.startswith(("update", "replace", "assign"))} == set(_BODIES)


@pytest.mark.parametrize("path", ["/locations", "/staff-users", "/roles", "/audit-events?limit=200", "/auth/sessions"])
def test_api_lists_never_include_the_other_tenant(client, two_tenants, path):
    a, b = two_tenants
    payload = client.get(f"/api/v1{path}", headers=a.headers).json()
    rows = payload["data"] if isinstance(payload, dict) else payload
    assert rows
    ids = {row["id"] for row in rows}
    assert not ids & {b.location_id, b.staff_user_id, b.role_id, b.session_id}
    theirs = client.get(f"/api/v1{path}", headers=b.headers).json()
    theirs = theirs["data"] if isinstance(theirs, dict) else theirs
    assert not ids & {row["id"] for row in theirs}


def test_api_write_with_foreign_reference_is_rejected(client, two_tenants):
    """A body that points at B's role or location cannot attach it to A's data."""
    a, b = two_tenants
    invite = {"email": "x@a.example.com", "first_name": "X", "last_name": "Y", "role_id": b.role_id}
    assert client.post("/api/v1/staff-users", headers=a.headers, json=invite).status_code == 422
    assign = {"has_all_location_access": False, "location_ids": [b.location_id]}
    assert (
        client.put(f"/api/v1/staff-users/{a.staff_user_id}/locations", headers=a.headers, json=assign).status_code
        == 422
    )


def test_token_is_bound_to_its_tenant_host(client, two_tenants):
    a, b = two_tenants
    response = client.get("/api/v1/me", headers={**a.headers, "Host": f"{b.tenant.slug}.localhost"})
    assert response.status_code == 401
    assert client.get("/api/v1/me", headers={**a.headers, "Host": f"{a.tenant.slug}.localhost"}).status_code == 200
