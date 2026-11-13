"""QuickBooks Online (INT-07) behind the AccountingConnect port: one contract suite run against the simulated
adapter and the real one on httpx.MockTransport (never Intuit), then the connection flow end to end through
the API with the simulated adapter: OAuth round trip, sealed credentials, mappings, sync, retry, webhook."""

import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.adapters.accounting import FakeQuickBooks, QuickBooksConnect, QuickBooksOnline, _webhook_signature
from app.core import clock
from app.core.db.platform import platform_engine
from app.core.db.session import tenant_session
from app.core.ids import new_id
from app.core.settings import get_settings
from app.modules.integrations.models import ExternalConnection
from app.ports.accounting import Credentials

API = "/api/v1"
CREDS = Credentials("at-1", "rt-1", 2_000_000_000, "4620816365")


def _intuit(request: httpx.Request) -> httpx.Response:
    """A stand-in for Intuit's token, revoke and query endpoints, shaped like their public documentation."""
    if request.url.path.endswith("/tokens/bearer"):
        form = parse_qs(request.content.decode())
        assert request.headers["authorization"].startswith("Basic ")
        if form.get("code") == ["bad"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600})
    if request.url.path.endswith("/tokens/revoke"):
        return httpx.Response(200)
    if request.url.path.endswith("/query"):
        entity = "Class" if "from Class" in request.url.params["query"] else "Account"
        return httpx.Response(200, json={"QueryResponse": {entity: [{"Id": "7", "Name": f"{entity} seven"}]}})
    return httpx.Response(404)


def _real() -> QuickBooksConnect:
    http = httpx.Client(base_url=QuickBooksOnline.BASE_URL, transport=httpx.MockTransport(_intuit))
    return QuickBooksConnect(client_id="cid", client_secret="secret", webhook_verifier="verifier", client=http)


ADAPTERS = {"fake": (FakeQuickBooks, FakeQuickBooks.WEBHOOK_SECRET, "fake-code"), "real": (_real, "verifier", "ok")}


@pytest.mark.parametrize("name", ADAPTERS)
def test_accounting_connect_contract(name):
    make, secret, code = ADAPTERS[name]
    adapter = make()
    url = adapter.authorize_url(state="s.t", redirect_uri="https://app.example/cb")
    assert parse_qs(urlparse(url).query)["state"] == ["s.t"]
    creds = adapter.exchange_code(code=code, company_id="4620816365", redirect_uri="https://app.example/cb")
    assert creds.company_id == "4620816365" and creds.access_token and creds.expires_at > clock.now().timestamp()
    refreshed = adapter.refresh(creds)
    assert refreshed.access_token and refreshed.company_id == creds.company_id
    assert adapter.revoke(creds) is None
    options = adapter.list_options(creds)
    assert {o.kind for o in options} == {"account", "class"} and all(o.id and o.name for o in options)
    body = b'{"eventNotifications": []}'
    assert adapter.verify_webhook(body, _webhook_signature(secret, body))
    assert not adapter.verify_webhook(body, _webhook_signature("other", body)) and not adapter.verify_webhook(body, "")
    assert hasattr(adapter.journal_poster(creds), "post_journal")


@pytest.mark.parametrize("name", ADAPTERS)
def test_a_refused_code_raises(name):
    make, _, _ = ADAPTERS[name]
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        make().exchange_code(code="bad", company_id="1", redirect_uri="https://app.example/cb")


def test_real_authorize_url_names_the_accounting_scope_and_redirect():
    query = parse_qs(urlparse(_real().authorize_url(state="x", redirect_uri="https://app.example/cb")).query)
    assert query["scope"] == ["com.intuit.quickbooks.accounting"] and query["redirect_uri"] == [
        "https://app.example/cb"
    ]
    assert query["response_type"] == ["code"] and query["client_id"] == ["cid"]


# --- the connection flow through the API (simulated adapter) -----------------------------------------------


@pytest.fixture
def enabled(monkeypatch):
    for name in ("FH_QUICKBOOKS_CLIENT_ID", "FH_QUICKBOOKS_CLIENT_SECRET", "FH_QUICKBOOKS_WEBHOOK_VERIFIER"):
        monkeypatch.delenv(name, raising=False)  # the simulated adapter, whatever the shell has set
    monkeypatch.setattr(get_settings().integrations, "quickbooks_enabled", True)


def _location(client, owner) -> str:
    body = {"name": "QBO site", "time_zone": "America/Chicago", "country_code": "US"}
    return client.post(f"{API}/locations", headers=owner | {"Idempotency-Key": "qbo-loc"}, json=body).json()["id"]


def _connect(client, owner) -> dict:
    started = client.post(f"{API}/external-connections", headers=owner, json={"provider": "quickbooks_online"})
    assert started.status_code == 201, started.text
    return started.json()


def _callback(client, authorize_url: str, **override):
    """What the web callback page does: post back what the provider put in the query."""
    query = {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()} | override
    body = {"state": query["state"], "code": query.get("code") or None, "realm_id": query.get("realm_id"),
            "error": query.get("error")}  # fmt: skip
    return client.post(f"{API}/external-connections/oauth/callback", json=body)


def test_oauth_round_trip_activates_and_seals_credentials(client, tenant, owner, enabled):
    started = _connect(client, owner)
    assert started["status"] == "pending" and started["authorize_url"]
    realm = str(new_id().int % 10**15)  # unique per run: the platform lookup outlives the test tenant
    done = _callback(client, started["authorize_url"], realm_id=realm)
    assert done.status_code == 200 and done.json()["status"] == "connected", done.text
    assert done.json()["return_url"].startswith(get_settings().app.web_base_url)
    connection = client.get(f"{API}/external-connections/{started['id']}", headers=owner).json()
    assert connection["status"] == "active" and connection["external_account_id"] == realm
    with tenant_session(tenant.id) as session:
        sealed = session.get(ExternalConnection, UUID(started["id"])).credentials_ciphertext
    assert sealed and "fake-at" not in sealed
    with platform_engine().connect() as conn:
        routed = conn.execute(
            text("SELECT tenant_id FROM provider_account_lookup WHERE provider = 'quickbooks_online' "
                 "AND provider_account_ref = :r"), {"r": realm}
        ).scalar()  # fmt: skip
    assert routed == tenant.id
    assert _callback(client, started["authorize_url"]).status_code == 403  # a used state never works twice


def test_forged_expired_and_refused_states(client, owner, enabled):
    started = _connect(client, owner)
    url = started["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    assert _callback(client, url, state=state[:-4] + "AAAA").status_code == 403
    assert _callback(client, url, state="nothex.x").status_code == 403
    with clock.freeze(clock.now() + timedelta(minutes=11)):
        assert _callback(client, url).status_code == 403
    refused = _callback(client, url, error="access_denied", code="")
    assert refused.status_code == 200 and refused.json()["status"] == "error"
    assert client.get(f"{API}/external-connections/{started['id']}", headers=owner).json()["status"] == "error"


def test_return_url_must_be_on_this_app(client, owner, enabled):
    body = {"provider": "quickbooks_online", "return_url": "https://evil.example/landing"}
    assert client.post(f"{API}/external-connections", headers=owner, json=body).status_code == 422


def test_mappings_settings_sync_retry_and_disconnect(client, owner, enabled):
    started = _connect(client, owner)
    _callback(client, started["authorize_url"])
    base = f"{API}/external-connections/{started['id']}"
    mappings = client.get(f"{base}/sync-mappings", headers=owner).json()
    assert {"id": "4", "name": "Sales of Product Income"} in mappings["external_options"]["accounts"]
    body = {"mappings": [
        {"kind": "ledger_account", "local_key": "receivable", "external_id": "12"},
        {"kind": "revenue_class", "local_key": "revenue:default", "external_id": "100"},
    ]}  # fmt: skip
    saved = client.put(f"{base}/sync-mappings", headers=owner, json=body)
    assert saved.status_code == 200 and len(saved.json()["mappings"]) == 2
    dup = {"mappings": body["mappings"] + body["mappings"][:1]}
    assert client.put(f"{base}/sync-mappings", headers=owner, json=dup).status_code == 422

    patched = client.patch(base, headers=owner, json={"settings": {"auto_sync": True, "sync_from": "2026-01-01"}})
    assert patched.status_code == 200
    assert client.patch(base, headers=owner, json={"settings": {"account_map": "x"}}).status_code == 422

    location = _location(client, owner)
    today = clock.now().date()
    run = {"from": str(today - timedelta(days=3)), "to": str(today - timedelta(days=1)), "location_id": location}
    synced = client.post(f"{base}/sync", headers=owner, json=run)
    assert synced.status_code == 202, synced.text
    assert sum(synced.json()["counts"].values()) == 3
    again = client.post(f"{base}/sync", headers=owner, json=run).json()
    assert again["counts"] == synced.json()["counts"]  # idempotent per day
    too_long = run | {"from": str(today - timedelta(days=40))}
    assert client.post(f"{base}/sync", headers=owner, json=too_long).status_code == 422
    export = client.get(f"{API}/accounting-exports?external_connection_id={started['id']}", headers=owner).json()
    assert client.post(f"{API}/accounting-exports/{export['data'][0]['id']}/retry", headers=owner).status_code == 409

    assert client.post(f"{base}/disconnect", headers=owner).json()["status"] == "disconnected"
    assert client.post(f"{base}/disconnect", headers=owner).status_code == 409
    assert client.post(f"{base}/sync", headers=owner, json=run).status_code == 409


def test_webhook_is_verified_and_stored_once(client, enabled):
    realm = str(new_id().int % 10**15)  # a fresh body each run: the inbound log is platform-wide
    body = json.dumps({"eventNotifications": [{"realmId": realm, "dataChangeEvent": {"entities": []}}]}).encode()
    signature = _webhook_signature(FakeQuickBooks.WEBHOOK_SECRET, body)
    url = f"{API}/webhooks/quickbooks"
    assert client.post(url, content=body, headers={"intuit-signature": "bad"}).status_code == 401
    first = client.post(url, content=body, headers={"intuit-signature": signature, "content-type": "application/json"})
    assert first.status_code == 200 and first.json() == {"stored": 1}
    assert client.post(url, content=body, headers={"intuit-signature": signature}).json() == {"stored": 0}


def test_quickbooks_stays_refused_while_switched_off(client, owner):
    refused = client.post(f"{API}/external-connections", headers=owner, json={"provider": "quickbooks_online"})
    assert (refused.status_code, refused.json()["code"]) == (422, "provider-not-configured")
    body = b'{"eventNotifications": []}'
    signed = {"intuit-signature": _webhook_signature(FakeQuickBooks.WEBHOOK_SECRET, body)}
    assert client.post(f"{API}/webhooks/quickbooks", content=body, headers=signed).status_code == 401


def test_the_simulated_secret_verifies_nothing_outside_dev_and_test(client, enabled, monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "production")
    body = b'{"eventNotifications": []}'
    signed = {"intuit-signature": _webhook_signature(FakeQuickBooks.WEBHOOK_SECRET, body)}
    assert client.post(f"{API}/webhooks/quickbooks", content=body, headers=signed).status_code == 401


def test_pending_connection_is_not_connected_and_keys_map_once_across_kinds(client, owner, enabled):
    started = _connect(client, owner)
    assert started["connected_at"] is None
    _callback(client, started["authorize_url"], realm_id=str(new_id().int % 10**15))
    base = f"{API}/external-connections/{started['id']}"
    clash = {"mappings": [{"kind": "ledger_account", "local_key": "k", "external_id": "1"},
                          {"kind": "tax_account", "local_key": "k", "external_id": "2"}]}  # fmt: skip
    assert client.put(f"{base}/sync-mappings", headers=owner, json=clash).status_code == 422
