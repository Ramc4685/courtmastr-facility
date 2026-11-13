"""QuickBooks Online (INT-07) behind the AccountingConnect port: one contract suite run against the simulated
adapter and the real one on httpx.MockTransport (never Intuit), then the connection flow end to end through
the API with the simulated adapter: OAuth round trip, sealed credentials, mappings, sync, retry, webhook."""

import json
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select, text

from app.adapters.accounting import (
    FakeAccounting,
    FakeQuickBooks,
    QuickBooksConnect,
    QuickBooksOnline,
    _webhook_signature,
)
from app.core import clock, crypto
from app.core.auth import system_principal
from app.core.db.platform import platform_engine
from app.core.db.session import tenant_session
from app.core.ids import new_id
from app.core.settings import get_settings
from app.modules.integrations import quickbooks
from app.modules.integrations.models import AccountingExport, ExternalConnection
from app.ports.accounting import Credentials
from conftest import add_staff, login, make_tenant, new_client

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
    if "/companyinfo/" in request.url.path:  # the token opens company 4620816365 only
        realm = request.url.path.rsplit("/", 1)[1]
        if realm != "4620816365" or request.headers["authorization"] != "Bearer at-2":
            return httpx.Response(403)
        return httpx.Response(200, json={"CompanyInfo": {"Id": realm, "CompanyName": "Sample"}})
    if request.url.path.endswith("/query"):
        entity = "Class" if "from Class" in request.url.params["query"] else "Account"
        return httpx.Response(200, json={"QueryResponse": {entity: [{"Id": "7", "Name": f"{entity} seven"}]}})
    return httpx.Response(404)


def _real() -> QuickBooksConnect:
    http = httpx.Client(base_url=QuickBooksOnline.BASE_URL, transport=httpx.MockTransport(_intuit))
    return QuickBooksConnect(client_id="cid", client_secret="secret", webhook_verifier="verifier", client=http)


ADAPTERS = {
    "fake": (FakeQuickBooks, FakeQuickBooks.WEBHOOK_SECRET, "fake-code.4620816365"),
    "real": (_real, "verifier", "ok"),
}


@pytest.mark.parametrize("name", ADAPTERS)
def test_accounting_connect_contract(name):
    make, secret, code = ADAPTERS[name]
    adapter = make()
    url = adapter.authorize_url(state="s.t", redirect_uri="https://app.example/cb")
    assert parse_qs(urlparse(url).query)["state"] == ["s.t"]
    creds = adapter.exchange_code(code=code, company_id="4620816365", redirect_uri="https://app.example/cb")
    assert creds.company_id == "4620816365" and creds.access_token and creds.expires_at > clock.now().timestamp()
    assert adapter.token_company_id(creds) == "4620816365"
    claimed = adapter.exchange_code(code=code, company_id="1111111111", redirect_uri="https://app.example/cb")
    assert adapter.token_company_id(claimed) is None  # a company the token was not issued for never verifies
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


def _query(authorize_url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()}


def _callback(client, headers, authorize_url: str, **override):
    """What the web callback page does, in the signed-in staff session: post back the provider's query."""
    query = _query(authorize_url) | override
    body = {"state": query["state"], "code": query.get("code") or None, "realm_id": query.get("realm_id"),
            "error": query.get("error")}  # fmt: skip
    return client.post(f"{API}/external-connections/oauth/callback", headers=headers, json=body)


def test_oauth_round_trip_activates_and_seals_credentials(client, tenant, owner, enabled):
    started = _connect(client, owner)
    assert started["status"] == "pending" and started["authorize_url"]
    realm = _query(started["authorize_url"])["realm_id"]  # the simulated provider mints a fresh company
    done = _callback(client, owner, started["authorize_url"])
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
    assert _callback(client, owner, started["authorize_url"]).status_code == 403  # a replayed state is refused


def test_forged_expired_and_refused_states(client, tenant, owner, enabled):
    started = _connect(client, owner)
    url = started["authorize_url"]
    state = _query(url)["state"]
    assert _callback(client, owner, url, state=state[:-4] + "AAAA").status_code == 403
    assert _callback(client, owner, url, state="nothex.x").status_code == 403
    # an expired state: the genuine payload with its expiry in the past (freezing the clock would end the session)
    payload = json.loads(crypto.decrypt(state.split(".", 1)[1], tenant.id)) | {"x": clock.now().timestamp() - 1}
    late = f"{tenant.id.hex}.{crypto.encrypt(json.dumps(payload), tenant.id)}"
    assert _callback(client, owner, url, state=late).status_code == 403
    refused = _callback(client, owner, url, error="access_denied", code="")
    assert refused.status_code == 200 and refused.json()["status"] == "error"
    assert client.get(f"{API}/external-connections/{started['id']}", headers=owner).json()["status"] == "error"


def test_the_callback_completes_only_for_the_staff_user_who_started_it(client, tenant, owner, enabled):
    started = _connect(client, owner)
    email, _ = add_staff(tenant, "owner")
    colleague = login(client, tenant, email)
    stolen = _callback(client, colleague, started["authorize_url"])  # a link planted on someone else (CSRF)
    assert (stolen.status_code, stolen.json()["code"]) == (403, "state-invalid")
    assert _callback(client, {}, started["authorize_url"]).status_code == 401
    assert _callback(client, owner, started["authorize_url"]).json()["status"] == "connected"


def test_a_company_the_token_does_not_open_is_refused(client, owner, enabled):
    started = _connect(client, owner)
    other_realm = str(int(_query(started["authorize_url"])["realm_id"]) + 1)
    done = _callback(client, owner, started["authorize_url"], realm_id=other_realm)
    assert done.json()["status"] == "error"
    connection = client.get(f"{API}/external-connections/{started['id']}", headers=owner).json()
    assert (connection["status"], connection["last_error"], connection["external_account_id"]) == (
        "error",
        "realm-mismatch",
        None,
    )
    assert _callback(client, owner, started["authorize_url"], realm_id="12ab").status_code == 422


def test_an_abandoned_or_failed_consent_never_blocks_a_new_attempt(client, owner, enabled):
    abandoned = _connect(client, owner)  # the owner closed the provider's consent page
    retried = _connect(client, owner)
    assert retried["id"] == abandoned["id"] and retried["status"] == "pending"
    failed = _callback(client, owner, retried["authorize_url"], realm_id="1111111111")
    assert client.get(f"{API}/external-connections/{retried['id']}", headers=owner).json()["status"] == "error", (
        failed.text
    )
    again = _connect(client, owner)
    assert again["id"] == retried["id"] and again["status"] == "pending"
    done = _callback(client, owner, again["authorize_url"])
    assert done.json()["status"] == "connected", done.text
    taken = client.post(f"{API}/external-connections", headers=owner, json={"provider": "quickbooks_online"})
    assert taken.status_code == 409  # an active connection still holds the slot


def test_a_takeover_kills_the_earlier_starters_link(client, tenant, owner, enabled):
    first = _connect(client, owner)
    email, _ = add_staff(tenant, "owner")
    colleague = login(client, tenant, email)
    second = _connect(client, colleague)
    assert second["id"] == first["id"]
    old = _callback(client, owner, first["authorize_url"])
    assert (old.status_code, old.json()["code"]) == (403, "state-invalid")
    assert _callback(client, colleague, second["authorize_url"]).json()["status"] == "connected"


def test_a_company_routed_to_another_tenant_is_refused(client, owner, enabled):
    first = _connect(client, owner)
    assert _callback(client, owner, first["authorize_url"]).json()["status"] == "connected"
    realm = _query(first["authorize_url"])["realm_id"]
    rival_tenant = make_tenant()
    rival = login(client, rival_tenant)
    started = _connect(client, rival)
    # the rival somehow holds a genuine code for the same company: the platform lookup still refuses it
    taken = _callback(client, rival, started["authorize_url"], code=f"fake-code.{realm}", realm_id=realm)
    assert (taken.status_code, taken.json()["code"]) == (409, "account-in-use")
    assert client.get(f"{API}/external-connections/{started['id']}", headers=rival).json()["status"] == "pending"
    # once the first tenant disconnects, its claim is released and the rival can connect the company
    assert client.post(f"{API}/external-connections/{first['id']}/disconnect", headers=owner).status_code == 200
    again = _callback(client, rival, started["authorize_url"], code=f"fake-code.{realm}", realm_id=realm)
    assert again.status_code == 200 and again.json()["status"] == "connected", again.text


def test_the_simulated_adapter_is_refused_outside_dev_and_test(client, owner, enabled, monkeypatch):
    started = _connect(client, owner)  # started in test, then the environment is not dev or test any more
    monkeypatch.setattr(get_settings(), "env", "production")
    refused = _callback(client, owner, started["authorize_url"])
    assert (refused.status_code, refused.json()["code"]) == (422, "provider-not-configured")
    fresh = login(client, make_tenant())  # starting a new connection is refused as well
    again = client.post(f"{API}/external-connections", headers=fresh, json={"provider": "quickbooks_online"})
    assert (again.status_code, again.json()["code"]) == (422, "provider-not-configured")


def test_return_url_must_be_on_this_app(client, owner, enabled):
    body = {"provider": "quickbooks_online", "return_url": "https://evil.example/landing"}
    assert client.post(f"{API}/external-connections", headers=owner, json=body).status_code == 422


def _chicago_today():
    return clock.now().astimezone(ZoneInfo("America/Chicago")).date()


def _job_session(tenant):
    return tenant_session(tenant.id, actor=system_principal("sync_accounting_job"))  # as tenant_actor opens it


def _drain_sync(tenant, connection_id: str) -> dict:
    """Run the queued sync's chunks the way the worker does: each chunk in its own committed transaction."""
    while True:
        with _job_session(tenant) as session:
            more = quickbooks.sync_chunk(session, UUID(connection_id))
        if not more:
            break
    with tenant_session(tenant.id) as session:
        job = session.get(ExternalConnection, UUID(connection_id)).settings["sync"]
    return {"status": job["status"], "counts": job["counts"]}


def _exports(tenant, connection_id: str) -> dict:
    with tenant_session(tenant.id) as session:
        rows = session.scalars(select(AccountingExport).where(
            AccountingExport.external_connection_id == UUID(connection_id))).all()  # fmt: skip
        return {row.business_on: (row.status, row.last_error, row.totals) for row in rows}


def _charge_on(client, owner, location: str, person: str, day: date, minor: int) -> None:
    """A charge booked on `day` at the location (noon, Chicago)."""
    noon = datetime.combine(day, time(12), ZoneInfo("America/Chicago"))
    charge = {"client_id": person, "location_id": location, "description": "Court", "unit_price_minor": minor}
    with clock.freeze(noon.astimezone(UTC)):
        assert client.post(f"{API}/charges", headers=owner, json=charge).status_code == 201


@pytest.fixture
def poster(monkeypatch):
    """Every journal the simulated poster receives, with its request id; `fail_on` makes a day's post raise."""
    seen: list = []
    fail_on: set[str] = set()

    def post(self, entry, *, request_id):
        seen.append((entry, request_id))
        if entry.business_on in fail_on:
            raise RuntimeError("provider unavailable")
        return f"je-{request_id[:8]}"

    monkeypatch.setattr(FakeAccounting, "post_journal", post)
    return SimpleNamespace(seen=seen, fail_on=fail_on)


def test_sync_posts_lines_with_classes_and_a_failed_day_retries_once(client, tenant, owner, enabled, poster):
    started = _connect(client, owner)
    _callback(client, owner, started["authorize_url"])
    base, ident = f"{API}/external-connections/{started['id']}", started["id"]
    location = _location(client, owner)
    person = new_client(client, owner, location)["id"]
    today = _chicago_today()
    first, second = today - timedelta(days=3), today - timedelta(days=2)
    _charge_on(client, owner, location, person, first, 2500)
    _charge_on(client, owner, location, person, second, 4000)
    run = {"from": str(first), "to": str(second), "location_id": location}

    # only the receivable is mapped: an unmapped revenue key fails each day, and nothing is posted
    receivable = [{"kind": "ledger_account", "local_key": "receivable", "external_id": "12"}]
    client.put(f"{base}/sync-mappings", headers=owner, json={"mappings": receivable})
    assert client.post(f"{base}/sync", headers=owner, json=run).status_code == 202
    assert _drain_sync(tenant, ident)["counts"] == {"failed": 2}
    failed = _exports(tenant, ident)
    assert {status for status, _, _ in failed.values()} == {"failed"} and poster.seen == []
    revenue = failed[first][1].rsplit(" ", 1)[1]  # "No QuickBooks account mapped for revenue:..."
    assert revenue.startswith("revenue:")

    mapped = receivable + [
        {"kind": "revenue_account", "local_key": revenue, "external_id": "4"},
        {"kind": "revenue_class", "local_key": revenue, "external_id": "100"},
    ]
    assert client.put(f"{base}/sync-mappings", headers=owner, json={"mappings": mapped}).status_code == 200
    # a retry over the range: the later day fails at the provider, the earlier one posts and stays posted
    poster.fail_on.add(second.isoformat())
    assert client.post(f"{base}/sync", headers=owner, json=run | {"retries_failed": True}).status_code == 202
    assert _drain_sync(tenant, ident)["counts"] == {"posted": 1, "failed": 1}
    entry, request_id = poster.seen[0]
    assert {(line.account_ref, line.debit_minor, line.credit_minor, line.class_ref) for line in entry.lines} == {
        ("12", 2500, 0, None), ("4", 0, 2500, "100"),
    }  # fmt: skip
    assert request_id == str(uuid5(NAMESPACE_URL, f"qbo_je:{ident}:{location}:{first.isoformat()}"))

    poster.fail_on.clear()
    assert client.post(f"{base}/sync", headers=owner, json=run | {"retries_failed": True}).status_code == 202
    assert _drain_sync(tenant, ident)["counts"] == {"posted": 2}  # the posted day is not attempted again
    posted_days = [entry.business_on for entry, _ in poster.seen]
    assert posted_days.count(first.isoformat()) == 1 and posted_days.count(second.isoformat()) == 2
    assert {status for status, _, _ in _exports(tenant, ident).values()} == {"posted"}


def test_a_rolled_back_day_reposts_with_the_same_request_id_and_rotated_tokens_survive(
    client, tenant, owner, enabled, poster
):
    started = _connect(client, owner)
    _callback(client, owner, started["authorize_url"])
    base, ident = f"{API}/external-connections/{started['id']}", started["id"]
    location = _location(client, owner)
    person = new_client(client, owner, location)["id"]
    day = _chicago_today() - timedelta(days=2)
    _charge_on(client, owner, location, person, day, 1500)
    client.put(f"{base}/sync-mappings", headers=owner, json={"mappings": [
        {"kind": "ledger_account", "local_key": "receivable", "external_id": "12"}]})  # fmt: skip
    client.patch(base, headers=owner, json={"settings": {"default_income_account": "4"}})
    with tenant_session(tenant.id) as session:  # the access token is due for refresh
        row = session.get(ExternalConnection, UUID(ident))
        quickbooks._seal(row, Credentials("at-old", "rt-old", clock.now().timestamp(), "4620816365"), tenant.id)
    run = {"from": str(day), "to": str(day), "location_id": location}
    assert client.post(f"{base}/sync", headers=owner, json=run).status_code == 202

    with _job_session(tenant) as session:  # chunk one rotates the tokens and commits nothing else
        assert quickbooks.sync_chunk(session, UUID(ident)) is True
    with pytest.raises(RuntimeError), _job_session(tenant) as session:  # chunk two posts, then rolls back
        assert quickbooks.sync_chunk(session, UUID(ident)) is False
        raise RuntimeError("worker died after the provider call")
    assert _exports(tenant, ident) == {}
    assert _drain_sync(tenant, ident)["counts"] == {"completed_with_warnings": 1}

    assert len(poster.seen) == 2 and poster.seen[0][1] == poster.seen[1][1]  # the provider dedupes on it
    with tenant_session(tenant.id) as session:
        row = session.get(ExternalConnection, UUID(ident))
        assert quickbooks.credentials(session, row).access_token == "at-old+"


def test_mappings_settings_sync_retry_and_disconnect(client, tenant, owner, enabled):
    started = _connect(client, owner)
    _callback(client, owner, started["authorize_url"])
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
    today = _chicago_today()
    run = {"from": str(today - timedelta(days=3)), "to": str(today - timedelta(days=1)), "location_id": location}
    synced = client.post(f"{base}/sync", headers=owner, json=run)
    assert synced.status_code == 202, synced.text
    assert synced.json()["status"] == "running"
    busy = client.post(f"{base}/sync", headers=owner, json=run)
    assert (busy.status_code, busy.json()["code"]) == (409, "sync-in-progress")
    assert _drain_sync(tenant, started["id"]) == {"status": "completed", "counts": {"skipped": 3}}
    assert client.post(f"{base}/sync", headers=owner, json=run).status_code == 202
    assert _drain_sync(tenant, started["id"])["counts"] == {"skipped": 3}  # idempotent per day
    too_long = run | {"from": str(today - timedelta(days=40))}
    assert client.post(f"{base}/sync", headers=owner, json=too_long).status_code == 422
    unfinished = run | {"to": str(today)}  # the location's own today, whatever the UTC date is
    assert client.post(f"{base}/sync", headers=owner, json=unfinished).status_code == 422
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
    _callback(client, owner, started["authorize_url"])
    base = f"{API}/external-connections/{started['id']}"
    clash = {"mappings": [{"kind": "ledger_account", "local_key": "k", "external_id": "1"},
                          {"kind": "tax_account", "local_key": "k", "external_id": "2"}]}  # fmt: skip
    assert client.put(f"{base}/sync-mappings", headers=owner, json=clash).status_code == 422
