"""The public API platform (INT-01) and its resources (INT-02 to INT-06, CLI-21, MEM-22, PKG-16, BIL-23, LGE-27,
SSP-19): what a key reaches is generated from the routes, every read resource answers a key holding its scope,
scope and location bounds hold, the rate limits bite, and the member realm is the portal, never a key."""

from uuid import uuid4

import pytest

from app.core import clock
from app.core.auth import passwords, system_principal
from app.core.db.session import tenant_session
from app.core.settings import get_settings
from app.main import app
from app.modules import billing, clients
from app.modules.integrations import reference
from app.modules.platform.models import Identity
from conftest import PASSWORD, login, new_client

API = "/api/v1"


def _doc() -> dict:
    return app.openapi()


def _key(client, owner, scopes, location_ids=None) -> dict:
    body = {"name": f"Partner {uuid4().hex[:4]}", "scopes": sorted(scopes), "confirm_sensitive_scopes": True}
    if location_ids is not None:
        body["location_ids"] = location_ids
    response = client.post(f"{API}/api-keys", headers=owner, json=body)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['secret']}"}


def _location(client, owner) -> str:
    body = {"name": f"Annex {uuid4().hex[:6]}", "time_zone": "America/Chicago", "country_code": "US"}
    response = client.post(f"{API}/locations", headers=owner | {"Idempotency-Key": uuid4().hex}, json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _invoice(client, owner, tenant, location_id) -> dict:
    person = new_client(client, owner, location_id)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        category = billing.service.create_revenue_category(session, code=f"R{uuid4().hex[:5]}", label="Rentals")
        category_id = str(category.id)
    charge = client.post(f"{API}/charges", headers=owner, json={
        "client_id": person["id"], "location_id": location_id, "description": "Court hire",
        "unit_price_minor": 2000, "revenue_category_id": category_id,
    })  # fmt: skip
    assert charge.status_code == 201, charge.text
    invoice = client.post(f"{API}/invoices", headers=owner, json={"charge_ids": [charge.json()["id"]]})
    assert invoice.status_code == 201, invoice.text
    return invoice.json() | {"client_id": person["id"]}


# --- generated reference -----------------------------------------------------------------------------------


def test_the_document_marks_what_a_key_may_call():
    paths = _doc()["paths"]
    assert "clients.client.read" in paths[f"{API}/clients"]["get"]["x-api-key-scopes"]
    assert "x-api-key-scopes" not in paths[f"{API}/me"]["get"]  # acts as a person
    assert "x-api-key-scopes" not in paths[f"{API}/api-keys"]["post"]  # minting needs a person and step-up
    assert "x-api-key-scopes" not in paths[f"{API}/portal/invoices"]["get"]  # the member realm


def test_api_reference_lists_key_operations(client, owner):
    response = client.get(f"{API}/api-reference", headers=owner)
    assert response.status_code == 200, response.text
    rows = {(r["method"], r["path"]): r for r in response.json()}
    assert rows[("GET", f"{API}/invoices")]["scopes"] == ["billing.invoice.read"]
    assert ("GET", f"{API}/me") not in rows
    key = _key(client, owner, ["clients.client.read"])
    assert client.get(f"{API}/api-reference", headers=key).status_code == 403  # minting scope never on a key


# --- every read resource answers a key ---------------------------------------------------------------------

_LIST_SKIP = {f"{API}/api-reference"}  # needs api_key.manage, which no key can hold
# Reads about "me" behind a key-gated router: the service needs a person, so a key is refused there by design.
_SELF_ROUTES = {f"{API}/time-entries/current", f"{API}/report-runs", f"{API}/saved-reports", f"{API}/export-jobs"}


def _list_reads() -> dict[str, list[str]]:
    return {
        path: item["get"]["x-api-key-scopes"]
        for path, item in _doc()["paths"].items()
        if "{" not in path and "get" in item and item["get"].get("x-api-key-scopes") and path not in _LIST_SKIP
    }


def test_a_key_reaches_every_list_resource_with_its_scope_and_none_without(client, tenant, owner):
    """INT-02, INT-03, INT-04, INT-06 and the P1 resource rows: one generated pass over every key-callable list."""
    reads = _list_reads()
    assert len(reads) > 50
    scopes = sorted({scopes[0] for scopes in reads.values()})
    keys = {}
    for start in range(0, len(scopes), 200):
        chunk = scopes[start : start + 200]
        key = _key(client, owner, chunk)
        keys |= {scope: key for scope in chunk}
    narrow = _key(client, owner, ["clients.client.read"])
    failures = []
    for path, needed in reads.items():
        answer = client.get(path, headers=keys[needed[0]])
        if answer.status_code in (401, 403, 500) and path not in _SELF_ROUTES:
            failures.append((path, answer.status_code, answer.json().get("code")))
        if "clients.client.read" not in needed:
            denied = client.get(path, headers=narrow)
            assert denied.status_code == 403, (path, denied.status_code)
    assert failures == [], "\n".join(map(str, failures))


@pytest.mark.parametrize(
    ("feature", "path", "scope"),
    [
        ("INT-02 CLI-21", "/clients", "clients.client.read"),
        ("INT-02 MEM-22", "/membership-contracts", None),
        ("INT-04", "/bookings", None),
        ("INT-04", "/sessions", None),
        ("INT-04 PKG-16", "/client-packages", None),
        ("INT-03 BIL-23", "/invoices", "billing.invoice.read"),
        ("INT-03", "/payments", "billing.payment.read"),
        ("INT-06", "/pos-sales", None),
        ("INT-06 LGE-27", "/games", None),
        ("INT-06 LGE-27", "/competitions", None),
    ],
)
def test_named_resources_are_in_the_public_api(feature, path, scope):
    scopes = _doc()["paths"][f"{API}{path}"]["get"].get("x-api-key-scopes")
    assert scopes, feature
    assert scope is None or scope in scopes


def test_records_outside_the_keys_locations_are_not_found(client, tenant, owner):
    main, annex = _location(client, owner), _location(client, owner)
    created = client.post(f"{API}/program-groups", headers=owner, json={"location_id": main, "name": "Camp"})
    assert created.status_code == 201, created.text
    group = created.json()
    reads = ["programs.registration.read"]
    inside, outside = _key(client, owner, reads, [main]), _key(client, owner, reads, [annex])
    assert client.get(f"{API}/program-groups/{group['id']}", headers=inside).status_code == 200
    assert client.get(f"{API}/program-groups/{group['id']}", headers=outside).status_code == 404
    listed = client.get(f"{API}/program-groups", headers=outside).json()["data"]
    assert group["id"] not in [row["id"] for row in listed]


def test_marking_an_invoice_paid_with_a_key_is_idempotent(client, tenant, owner):
    """BIL-23 "set paid": a record-only external payment, required Idempotency-Key, replay-safe."""
    location = _location(client, owner)
    invoice = _invoice(client, owner, tenant, location)
    key = _key(client, owner, ["billing.payment.take", "billing.invoice.read"])
    url = f"{API}/invoices/{invoice['id']}/mark-paid"
    assert client.post(url, headers=key, json={}).status_code == 422  # the key is required on money routes
    idem = key | {"Idempotency-Key": uuid4().hex}
    first = client.post(url, headers=idem, json={"external_reference": "PO-1"})
    assert first.status_code == 201, first.text
    again = client.post(url, headers=idem, json={"external_reference": "PO-1"})
    assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert client.get(f"{API}/invoices/{invoice['id']}", headers=key).json()["balance_minor"] == 0


# --- rate limits -------------------------------------------------------------------------------------------


@pytest.fixture
def limits(monkeypatch):
    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    return cfg


def test_per_key_limit_refuses_with_retry_after(client, owner, limits, monkeypatch):
    monkeypatch.setattr(limits, "api_per_minute", 2)
    key = _key(client, owner, ["clients.client.read"])
    assert [client.get(f"{API}/clients", headers=key).status_code for _ in range(2)] == [200, 200]
    refused = client.get(f"{API}/clients", headers=key)
    assert refused.status_code == 429 and refused.json()["code"] == "rate-limited"
    assert refused.headers["Retry-After"] == "60"
    assert client.get(f"{API}/clients", headers=_key(client, owner, ["clients.client.read"])).status_code == 200


def test_tenant_ceiling_counts_every_key(client, owner, limits, monkeypatch):
    bucket = limits.buckets["api-tenant"]
    monkeypatch.setattr(bucket, "limit", 3)
    first, second = _key(client, owner, ["clients.client.read"]), _key(client, owner, ["clients.client.read"])
    codes = [client.get(f"{API}/clients", headers=key).status_code for key in (first, second, first)]
    assert codes == [200, 200, 200]
    refused = client.get(f"{API}/clients", headers=second)
    assert refused.status_code == 429 and "RateLimit-Limit" in refused.headers
    assert client.get(f"{API}/clients", headers=owner).status_code == 200  # people are not counted


# --- realms ------------------------------------------------------------------------------------------------


def _member(client, tenant, owner) -> tuple[str, dict]:
    person = new_client(client, owner, _location(client, owner), primary_email=f"m-{uuid4().hex[:6]}@example.com")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(
            kind="client", email=person["primary_email"], status="active", email_verified_at=clock.now(),
            password_hash=passwords.hash_password(PASSWORD),
        )  # fmt: skip
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, person["id"], identity.id)
    return person["id"], login(client, tenant, person["primary_email"], audience="client")


@pytest.mark.parametrize("path", ["/portal/client-packages", "/portal/membership-contracts", "/portal/invoices"])
def test_member_realm_is_the_portal_with_a_client_token(client, tenant, owner, path):
    """INT-05, SSP-19, PKG-16, MEM-22: a member's own data through a client bearer token; keys never get in."""
    _, member = _member(client, tenant, owner)
    assert client.get(f"{API}{path}", headers=member).status_code == 200
    key = _key(client, owner, ["clients.client.read", "billing.invoice.read"])
    refused = client.get(f"{API}{path}", headers=key)
    assert refused.status_code == 403 and refused.json()["code"] == "api-key-not-allowed"


def test_a_member_token_does_not_reach_back_office_resources(client, tenant, owner):
    _, member = _member(client, tenant, owner)
    assert client.get(f"{API}/clients", headers=member).status_code == 403


def test_key_scopes_follow_the_route_gate():
    route = next(r for path, r in reference._walk(app.routes) if path == f"{API}/clients" and "GET" in r.methods)
    assert reference.key_scopes(route) == ["clients.client.read"]
