"""Cross-cutting security guards (security-baseline sections 5 and 15). They are generated from the router
table and pg_catalog, so a new module is covered without being listed here."""

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.api import TxRoute
from app.core.auth.deps import current_ctx
from app.core.db import app_engine, platform
from app.core.db.base import GLOBAL_TABLES
from app.core.settings import get_settings
from app.main import app
from conftest import PASSWORD
from tests.test_rls_meta import TENANT_TABLES

API = "/api/v1"
# Routes reachable without a session. Adding one is a deliberate act: list it here in the same change.
ANONYMOUS = {
    "/health/live", "/health/ready", "/public/locations", "/operator/tenants",
    "/auth/sign-in", "/auth/magic-links", "/auth/magic-links/consume", "/auth/password-resets",
    "/auth/password-resets/consume", "/auth/invitations/accept", "/auth/refresh",
    "/webhooks/{provider}",  # authenticated by the provider's signature, not a session
    # authenticated by the paired device's kiosk cookie (pairing: the single-use code), not a session
    "/kiosk/pair", "/kiosk/config", "/kiosk/lookups", "/kiosk/check-ins", "/kiosk/exit",
}  # fmt: skip


def _walk(routes, prefix: str = "", inherited: frozenset = frozenset()):
    """(full path, route, dependency callables). FastAPI keeps include_router() lazy, so descend by hand."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route, inherited | _dependencies(route.dependant)
        elif hasattr(route, "original_router"):
            ctx = route.include_context
            calls = frozenset(d.dependency for d in ctx.dependencies or ())
            yield from _walk(route.original_router.routes, prefix + ctx.prefix, inherited | calls)


def _dependencies(dependant) -> frozenset:
    found = {dependant.call}
    for sub in dependant.dependencies:
        found |= _dependencies(sub)
    return frozenset(found)


ROUTES = list(_walk(app.routes))


def test_the_route_walk_sees_the_whole_api():
    operations = sum(len(methods) for methods in app.openapi()["paths"].values())
    assert sum(len(route.methods) for _, route, _ in ROUTES) == operations > 40


@pytest.mark.parametrize(("path", "route", "calls"), ROUTES, ids=[f"{sorted(r.methods)[0]} {p}" for p, r, _ in ROUTES])
def test_every_route_authenticates_unless_listed_as_anonymous(path, route, calls):
    path = path.removeprefix(API)
    if path.startswith("/public/") or path in ANONYMOUS:
        assert current_ctx not in calls
    else:
        assert current_ctx in calls, "no auth dependency: use require() or current_ctx"
    # TxRoute carries the request transaction and the cross-site check; only the operator route opts out.
    assert isinstance(route, TxRoute) or path.startswith("/operator/")


def test_cross_site_unsafe_requests_are_refused(client, tenant):
    """Browsers send Origin on cross-origin POSTs; ours must match the host or the configured web app."""
    url = f"{API}/auth/sign-in"
    body = {"email": tenant.owner_email, "password": PASSWORD}
    slug = {"X-Tenant-Slug": tenant.slug}

    for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
        denied = client.post(url, json=body, headers=slug | headers)
        assert denied.status_code == 403 and denied.json()["code"] == "csrf-failed", headers
    own_host = client.post(
        url, json=body, headers=slug | {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    )
    assert own_host.status_code == 200
    assert client.post(url, json=body, headers=slug | {"Origin": get_settings().app.web_base_url}).status_code == 200

    # The refresh cookie is not covered by the session-bound CSRF token, so this check is its only guard.
    assert client.post(f"{API}/auth/refresh", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(f"{API}/auth/refresh").status_code == 200
    # Safe methods and bearer callers are exempt.
    assert client.get(f"{API}/me", headers={"Origin": "https://evil.example"}).status_code == 200


def test_cookie_secure_is_mandatory_outside_dev_and_test(monkeypatch):
    monkeypatch.setenv("FH_ENV", "prod")  # no prod overlay exists, so the dev default (false) would apply
    with pytest.raises(RuntimeError, match="cookie_secure"):
        get_settings.__wrapped__()


def test_tenant_resolution_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(platform, "_CACHE_MAX", 3)
    for n in range(10):
        assert platform.resolve_tenant(host=f"unknown-{n}.example") is None
    assert len(platform._resolved) <= 3


# --- pg_catalog: what the database really holds, not what the models say -----------------------------------


def _catalog(sql: str) -> list:
    with app_engine().connect() as conn:
        return conn.execute(text(sql)).all()


def test_every_tenant_foreign_key_is_composite_in_the_database():
    single = _catalog(
        "SELECT c.conname FROM pg_constraint c WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace "
        f"AND c.confrelid::regclass::text NOT IN ({', '.join(repr(t) for t in sorted(GLOBAL_TABLES))}) "
        "AND NOT EXISTS (SELECT 1 FROM unnest(c.conkey) k JOIN pg_attribute a "
        "ON a.attrelid = c.conrelid AND a.attnum = k WHERE a.attname = 'tenant_id')"
    )
    assert single == []


def test_unique_indexes_on_tenant_tables_lead_with_tenant_id():
    """T1: a uniqueness error can never reveal that a value exists in another tenant."""
    rows = _catalog(
        "SELECT i.indexrelid::regclass::text, t.relname FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0] "
        "WHERE i.indisunique AND NOT i.indisprimary AND t.relnamespace = 'public'::regnamespace "
        "AND a.attname <> 'tenant_id'"
    )
    offenders = {name for name, table in rows if table in TENANT_TABLES}
    assert offenders == {"uq_tenant_domain_host"}  # a host maps to one tenant platform-wide, by design


def test_force_rls_holds_even_for_the_table_owner(two_tenants):
    """FORCE ROW LEVEL SECURITY: the migration role owns the tables and still reads nothing without a tenant."""
    owner = create_engine(get_settings().db_url("owner"))
    with owner.connect() as conn:
        assert conn.execute(text("SELECT current_user")).scalar() == "fh_owner"
        for table in (*TENANT_TABLES, "tenant"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
    owner.dispose()


def test_platform_role_reaches_only_its_grant_list():
    """T7: the BYPASSRLS role is as narrow as overview 3.4 says."""
    granted = {
        r[0]
        for r in _catalog(
            "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' "
            "AND has_table_privilege('fh_platform', oid, 'SELECT, INSERT, UPDATE, DELETE')"
        )
    }
    assert granted == {
        "tenant", "tenant_domain", "subscription_plan", "outbox_event",
        "provider_account_lookup", "inbound_webhook_event",  # global webhook routing tables (overview 3.1)
    }  # fmt: skip
    with pytest.raises(DBAPIError, match="permission denied"), platform.platform_engine().connect() as conn:
        conn.execute(text("SELECT count(*) FROM identity"))


@pytest.mark.parametrize("key", ["x' OR status:'succeeded", "a b", "k" * 256, ""])
def test_idempotency_keys_are_plain_tokens(client, owner, key):
    """The key reaches provider queries (Stripe Search) and logs: only [A-Za-z0-9_.:-]{1,255} is accepted."""
    response = client.post(f"{API}/locations", headers=owner | {"Idempotency-Key": key}, json={})
    assert response.status_code == 422 and "idempotency-key" in response.text.lower(), response.text


def _keyless(calls) -> bool:
    """Signed-in routes whose only gates are a bare require() or current_ctx: they name no permission key."""
    gates = [c for c in calls if hasattr(c, "keys") and hasattr(c, "accepts_api_key")]
    return current_ctx in calls and not any(gate.keys for gate in gates)


KEYLESS = [(p, r) for p, r, calls in ROUTES if _keyless(calls)]


@pytest.mark.parametrize(("path", "route"), KEYLESS, ids=[f"{sorted(r.methods)[0]} {p}" for p, r in KEYLESS])
def test_api_keys_cannot_call_keyless_routes(client, path, route):
    """W2-02: an API key's scopes are permission keys, so a route that names none is outside every key. The
    refusal comes from current_ctx before the token is even looked up, so a well-formed fake secret proves it."""
    url = path.replace("{", "").replace("}", "")  # path parameters never parse: the gate runs first
    response = client.request(sorted(route.methods)[0], url, headers={"Authorization": "Bearer fhk_" + "0" * 32 + "_x"})
    assert (response.status_code, response.json()["code"]) == (403, "api-key-not-allowed")


def test_keyless_guard_sees_the_known_configuration_reads():
    paths = {p.removeprefix(API) for p, _ in KEYLESS}
    assert {"/locations", "/me", "/taxes", "/coupons"} <= paths
