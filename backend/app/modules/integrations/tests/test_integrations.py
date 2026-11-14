"""integrations: API keys, webhook subscriptions and deliveries, the SSRF guard, signatures, the accounting
export and adapters. Real PostgreSQL; the network is mocked except in the local-receiver end-to-end test."""

import hashlib
import http.server
import importlib
import json
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from unittest import mock
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from dramatiq import Worker
from sqlalchemy import select, text, update

from app import relay
from app.adapters.accounting import FakeAccounting, JsonFileAccounting, QuickBooksOnline
from app.core import clock, crypto, networks
from app.core.auth import CATALOGUE, Principal, system_principal, system_role_grants
from app.core.db.session import tenant_session
from app.core.jobs import broker
from app.core.settings import get_settings
from app.modules.integrations import auth, service, transport
from app.modules.integrations.catalogue import CATALOGUE as EVENTS
from app.modules.integrations.domain import journal
from app.modules.integrations.domain import webhooks as rules
from app.modules.integrations.models import AdapterCommandLog, ApiKey, WebhookDelivery, WebhookEndpoint
from app.ports.accounting import Journal, JournalLine
from conftest import PUBLIC_IP, add_staff, login, new_client, scalar

API = "/api/v1"


@pytest.fixture(autouse=True)
def _quiet_endpoints(tenant):
    """Leave no active endpoint behind: a later broker drain would fan events out to it and wait on retries."""
    yield
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(WebhookEndpoint).values(status="paused"))
    # A delivery retry is a delayed message minutes out in the shared stub broker; any later drain would wait for it.
    broker.flush_all()


def _location(client, headers, name: str = "Main") -> str:
    body = {"name": f"{name} {uuid4().hex[:6]}", "time_zone": "America/Chicago", "country_code": "US"}
    response = client.post(f"{API}/locations", headers=headers | {"Idempotency-Key": uuid4().hex}, json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _key(client, headers, status: int = 201, **body):
    response = client.post(f"{API}/api-keys", headers=headers, json={"name": "Partner"} | body)
    assert response.status_code == status, response.text
    return response.json()


def _bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


def _endpoint(client, headers, types=("clients.client.created",), status: int = 201, url="https://hooks.invalid/x"):
    with mock.patch.object(transport, "resolve", return_value=[PUBLIC_IP]):
        response = client.post(
            f"{API}/webhook-endpoints", headers=headers, json={"url": url, "event_types": list(types)}
        )
    assert response.status_code == status, response.text
    return response.json()


def _system(tenant):
    return tenant_session(tenant.id, actor=system_principal("tests"))


# --- API keys ----------------------------------------------------------------------------------------------


def test_key_secret_is_shown_once_and_stored_hashed(client, tenant, owner):
    created = _key(client, owner, scopes=["clients.client.read"])
    secret = created["secret"]
    assert secret.startswith(f"fhk_{UUID(str(tenant.id)).hex}_")
    assert created["key_prefix"] == secret.split("_", 2)[2][:12]
    listed = client.get(f"{API}/api-keys", headers=owner).json()["data"]
    assert [row["id"] for row in listed] == [created["id"]] and "secret" not in listed[0]
    row = scalar(tenant, select(ApiKey).where(ApiKey.id == UUID(created["id"])))
    assert row.secret_hash == hashlib.sha256(secret.encode()).hexdigest()
    audit = scalar(tenant, text("SELECT changes::text FROM audit_event WHERE action = 'integrations.api_key.create'"))
    assert secret not in audit and row.secret_hash not in audit


def test_key_calls_staff_routes_within_its_scopes(client, tenant, owner):
    location = _location(client, owner)
    new_client(client, owner, location)
    h = _bearer(_key(client, owner, scopes=["clients.client.read"])["secret"])
    assert client.get(f"{API}/clients", headers=h).json()["data"]
    locations = client.get(f"{API}/locations", headers=h)  # keyless staff route: outside every scope (W2-02)
    assert (locations.status_code, locations.json()["code"]) == (403, "api-key-not-allowed")
    assert client.get(f"{API}/charges", headers=h).status_code == 403  # not in its scopes
    me = client.get(f"{API}/me", headers=h)
    assert (me.status_code, me.json()["code"]) == (403, "api-key-not-allowed")
    assert (
        client.post(f"{API}/api-keys", headers=h, json={"name": "x", "scopes": ["clients.client.read"]}).status_code
        == 403
    )
    assert client.get(f"{API}/clients", headers=_bearer("fhk_" + "0" * 32 + "_nope")).status_code == 401
    assert scalar(tenant, select(ApiKey.last_used_at)) is not None


def test_rotation_keeps_the_old_secret_for_the_grace_period_and_revocation_stops_it(client, tenant, owner):
    key = _key(client, owner, scopes=["clients.client.read"])
    old = key["secret"]
    new = client.post(f"{API}/api-keys/{key['id']}/rotate", headers=owner, json={}).json()["secret"]
    assert old != new
    for secret in (old, new):
        assert client.get(f"{API}/clients", headers=_bearer(secret)).status_code == 200
    with clock.freeze(clock.now() + timedelta(hours=25)):
        assert client.get(f"{API}/clients", headers=_bearer(old)).status_code == 401
        assert client.get(f"{API}/clients", headers=_bearer(new)).status_code == 200
    newest = client.post(f"{API}/api-keys/{key['id']}/rotate", headers=owner, json={"grace_minutes": 0}).json()
    assert client.get(f"{API}/clients", headers=_bearer(new)).status_code == 401
    assert client.get(f"{API}/clients", headers=_bearer(newest["secret"])).status_code == 200
    assert client.delete(f"{API}/api-keys/{key['id']}", headers=owner).status_code == 204
    assert client.get(f"{API}/clients", headers=_bearer(newest["secret"])).status_code == 401
    assert client.post(f"{API}/api-keys/{key['id']}/rotate", headers=owner, json={}).status_code == 409


def test_expired_key_is_refused(client, owner):
    soon = (clock.now() + timedelta(hours=1)).isoformat()
    key = _key(client, owner, scopes=["clients.client.read"], expires_at=soon)
    with clock.freeze(clock.now() + timedelta(hours=2)):
        assert client.get(f"{API}/clients", headers=_bearer(key["secret"])).status_code == 401
    past = (clock.now() - timedelta(hours=1)).isoformat()
    _key(client, owner, 422, scopes=["clients.client.read"], expires_at=past)


@pytest.mark.parametrize(
    "scope",
    [
        "platform.audit.read",
        "platform.audit.export",
        "platform.staff_user.read",
        "integrations.sync.run",
        "reporting.report_schedule.manage",
        "reporting.dashboard.read",
        "engagement.portal_settings.manage",
        "engagement.inbox.reply",
        "engagement.sms_campaign.send",
        "engagement.campaign.send_all",
        "engagement.suppression.manage",
        "engagement.notification_rule.manage",
        "engagement.automation.manage",
    ],  # fmt: skip
)
def test_keys_hold_only_the_documented_api_resources(client, owner, scope):
    """The allow-list: audit, the staff directory, the accounting sync and person-bound reporting stay with
    people. A key cannot hold report_schedule.manage, so it never lists schedules or their recipients."""
    assert scope in CATALOGUE
    refused = _key(client, owner, 422, scopes=[scope], confirm_sensitive_scopes=True)
    assert refused["code"] == "scope-not-grantable"


# The whole key-grantable set, pinned: a new permission, or a change to the allow-list, fails here until someone
# decides whether a machine may hold it. Counts per context; the keys a listed context withholds, by name.
_GRANTABLE_COUNTS = {
    "access": 11, "assessments": 5, "billing": 38, "clients": 16, "documents": 6, "engagement": 7, "leagues": 15,
    "memberships": 13, "packages": 10, "pos": 14, "programs": 12, "rentals": 11, "resources": 4, "scheduling": 21,
}  # fmt: skip
_WITHHELD_IN_LISTED_CONTEXTS = {
    "access.kiosk.manage", "access.device.manage", "billing.tax.manage", "billing.settings.manage",
    "billing.provider.manage", "pos.terminal.manage", "resources.padlock.reveal_combination",
    "rentals.portal_setting.manage", "clients.client.confirm_age", "clients.client.confirm_ages",
    "rentals.booking.override_minor",
}  # fmt: skip
_ENGAGEMENT = {
    "engagement.app_content.manage", "engagement.campaign.create", "engagement.campaign.edit",
    "engagement.campaign.read", "engagement.campaign.send", "engagement.message.send_direct", "engagement.push.send",
}  # fmt: skip


def test_the_key_grantable_set_is_pinned():
    grantable = {k for k, p in CATALOGUE.items() if service.grantable_to_key(p)}
    assert Counter(CATALOGUE[k].context for k in grantable) == _GRANTABLE_COUNTS
    listed = {k for k, p in CATALOGUE.items() if p.context in _GRANTABLE_COUNTS and p.context != "engagement"}
    assert grantable == (listed - _WITHHELD_IN_LISTED_CONTEXTS) | _ENGAGEMENT
    assert {p.context for p in CATALOGUE.values()} - set(_GRANTABLE_COUNTS) == {
        "integrations", "platform", "reporting", "staff"}  # fmt: skip


def test_a_key_can_neither_be_given_nor_use_the_rental_portal_switch(client, tenant, owner):
    assert _key(client, owner, 422, scopes=["rentals.portal_setting.manage"])["code"] == "scope-not-grantable"
    key = _key(client, owner, scopes=["rentals.booking.create"])
    with _system(tenant) as session:  # stored another way: an old row, a manual fix, a restore
        session.execute(update(ApiKey).values(scopes=["rentals.booking.create", "rentals.portal_setting.manage"]))
    with _system(tenant) as session:
        assert set(auth.authenticate(session, key["secret"]).permissions) == {"rentals.booking.create"}
    settings = f"{API}/locations/{_location(client, owner)}/rental-portal-settings"
    assert client.get(settings, headers=owner).status_code == 200
    assert client.get(settings, headers=_bearer(key["secret"])).status_code == 403


def test_a_stored_scope_off_the_allow_list_never_reaches_the_key_and_the_migration_strips_it(client, tenant, owner):
    key = _key(client, owner, scopes=["clients.client.read"])
    with _system(tenant) as session:  # written another way: an old row, a manual fix, a restore
        stored = ["clients.client.read", "engagement.campaign.read", "engagement.inbox.reply", "platform.audit.read"]
        session.execute(update(ApiKey).values(scopes=stored))
    h = _bearer(key["secret"])
    assert client.get(f"{API}/clients", headers=h).status_code == 200
    assert client.get(f"{API}/audit-events", headers=h).status_code == 403
    kept = ["clients.client.read", "engagement.campaign.read"]
    with _system(tenant) as session:
        assert set(auth.authenticate(session, key["secret"]).permissions) == set(kept)
        session.execute(
            text(importlib.import_module("migrations.versions.1705_integrations_key_scope_allow_list").STRIP)
        )
        assert session.scalar(select(ApiKey.scopes)) == kept


def test_scopes_are_bounded_by_the_catalogue_the_rules_and_the_creator(client, tenant, owner):
    assert _key(client, owner, 422, scopes=["integrations.api_key.manage"])["code"] == "scope-not-grantable"
    assert _key(client, owner, 422, scopes=["nope.nope.nope"])["code"] == "validation-failed"
    money = next(k for k, p in CATALOGUE.items() if "$" in p.flags and service.grantable_to_key(p))
    assert _key(client, owner, 422, scopes=[money])["code"] == "confirmation-required"
    _key(client, owner, scopes=[money], confirm_sensitive_scopes=True)
    for key, permission in CATALOGUE.items():  # rbac-matrix section 11
        flags = set(permission.flags)
        if flags & {"A", "I", "G", "K", "OO", "OD", "+"} or (key.startswith("staff.") and "W" in flags):
            assert not service.grantable_to_key(permission), key

    # A location-limited admin: keys must name locations inside theirs, and only those keys are visible to them.
    mine, other = _location(client, owner), _location(client, owner, "Other")
    email, _ = add_staff(tenant, "admin", location_ids=[mine])
    limited = login(client, tenant, email)
    _key(client, limited, 422, scopes=["clients.client.read"])
    _key(client, limited, 422, scopes=["clients.client.read"], location_ids=[other])
    theirs = _key(client, limited, scopes=["clients.client.read"], location_ids=[mine])
    beyond = [k for k, p in CATALOGUE.items() if service.grantable_to_key(p) and k not in system_role_grants("admin")]
    if beyond:
        refused = _key(client, limited, 403, scopes=[beyond[0]], location_ids=[mine], confirm_sensitive_scopes=True)
        assert refused["code"] == "scope-exceeds-creator"
    wide = _key(client, owner, scopes=["clients.client.read"])
    assert {r["id"] for r in client.get(f"{API}/api-keys", headers=limited).json()["data"]} == {theirs["id"]}
    assert client.delete(f"{API}/api-keys/{wide['id']}", headers=limited).status_code == 404


def test_key_principal_is_the_creator_narrowed():
    l1, l2, l3 = uuid4(), uuid4(), uuid4()
    creator = Principal(
        kind="staff",
        staff_user_id=uuid4(),
        permissions={"clients.client.read": "all", "billing.charge.read": "own", "platform.audit.read": "all"},
        location_ids=frozenset({l1, l2}),
    )
    scopes = ["clients.client.read", "rentals.rental.read", "platform.audit.read"]  # not held; off the allow-list
    key = ApiKey(id=uuid4(), name="k", scopes=scopes, location_ids=[l2, l3])
    principal = auth._bounded(creator, key)
    assert principal.kind == "api_key" and principal.api_key_id == key.id and principal.staff_user_id is None
    assert dict(principal.permissions) == {"clients.client.read": "all"} and principal.location_ids == {l2}
    assert principal.actor_id == key.id
    key.location_ids = None
    assert auth._bounded(creator, key).location_ids == {l1, l2}
    assert auth._bounded(Principal(kind="staff", permissions={}), key).location_ids is None


def test_key_stops_when_its_creator_is_deactivated(client, tenant, owner):
    email, staff_user_id = add_staff(tenant, "admin", all_locations=True)
    h = _bearer(_key(client, login(client, tenant, email), scopes=["clients.client.read"])["secret"])
    assert client.get(f"{API}/clients", headers=h).status_code == 200
    assert client.post(f"{API}/staff-users/{staff_user_id}/deactivate", headers=owner).status_code == 200
    assert client.get(f"{API}/clients", headers=h).status_code == 401


# --- SSRF guard --------------------------------------------------------------------------------------------

BLOCKED = [
    "127.0.0.1", "::1", "0.0.0.0", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "fe80::1",
    "fd00::1", "100.64.0.1", "224.0.0.1", "203.0.113.5", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
    # W2-04: IPv6 forms embedding IPv4 (NAT64, IPv4-compatible, 6to4, Teredo), public targets included
    "64:ff9b::a00:1", "64:ff9b::7f00:1", "64:ff9b::808:808", "::a00:1", "::7f00:1", "::808:808",
    "2002:a00:1::1", "2002:808:808::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2",
]  # fmt: skip


@pytest.mark.parametrize("address", BLOCKED)
def test_blocked_address_classes(address):
    assert networks.blocked_reason(address) is not None


@pytest.mark.parametrize("address", [PUBLIC_IP, "2606:4700:4700::1111", "8.8.8.8"])
def test_public_addresses_pass(address):
    assert networks.blocked_reason(address) is None


def test_loopback_only_when_the_dev_switch_allows_it():
    assert networks.blocked_reason("127.0.0.1", allow_loopback=True) is None
    assert networks.blocked_reason("10.0.0.1", allow_loopback=True) == "private"


@pytest.mark.parametrize(
    ("url", "addresses"),
    [
        ("http://hooks.invalid/x", [PUBLIC_IP]),  # https required outside dev
        ("https://user:pw@hooks.invalid/x", [PUBLIC_IP]),  # credentials in the URL
        ("https://hooks.invalid/x", [PUBLIC_IP, "10.0.0.1"]),  # any private answer refuses the host
        ("https://hooks.invalid/x", ["169.254.169.254"]),  # cloud metadata
        ("https://hooks.invalid/x", []),
    ],
)
def test_check_refuses_unsafe_urls(url, addresses):
    with mock.patch.object(transport, "resolve", return_value=addresses), pytest.raises(transport.UrlNotAllowed):
        transport.check(url)


def test_endpoint_with_internal_url_is_refused(client, owner):
    with mock.patch.object(transport, "resolve", return_value=["169.254.169.254"]):
        response = client.post(
            f"{API}/webhook-endpoints", headers=owner, json={"url": "https://meta.invalid/", "event_types": ["*"]}
        )
    assert (response.status_code, response.json()["code"]) == (422, "url-not-allowed")


def test_dns_rebinding_after_save_is_caught_at_send_time(client, tenant, owner):
    endpoint = _endpoint(client, owner)
    with mock.patch.object(service, "_enqueue"), _system(tenant) as session:
        (delivery_id,) = service.fan_out(
            session, uuid4(), {"type": "clients.client.created", "client_id": str(uuid4())}
        )
    with (
        mock.patch.object(transport, "resolve", return_value=["127.0.0.1"]),
        mock.patch.object(transport, "send") as send,
        _system(tenant) as session,
    ):
        assert service.attempt_delivery(session, delivery_id) is not None  # scheduled for a retry
        row = session.get(WebhookDelivery, delivery_id)
        assert row.last_error.startswith("url-not-allowed") and row.webhook_endpoint_id == UUID(endpoint["id"])
    send.assert_not_called()


# --- signatures --------------------------------------------------------------------------------------------


def test_signature_verification():
    body = b'{"id":"1"}'
    header = rules.signature_header(["whsec_a"], 1_000, body)
    assert header.startswith("t=1000,v1=")
    assert rules.verify("whsec_a", header, body, now=1_000)
    assert not rules.verify("whsec_b", header, body, now=1_000)
    assert not rules.verify("whsec_a", header, body + b" ", now=1_000)
    assert not rules.verify("whsec_a", header, body, now=1_000 + rules.SIGNATURE_TOLERANCE_SEC + 1)
    both = rules.signature_header(["whsec_new", "whsec_old"], 1_000, body)
    assert rules.verify("whsec_new", both, body, now=1_000) and rules.verify("whsec_old", both, body, now=1_000)


def test_secret_is_encrypted_and_rotation_signs_with_both(client, tenant, owner):
    endpoint = _endpoint(client, owner)
    rotated = client.post(f"{API}/webhook-endpoints/{endpoint['id']}/rotate-secret", headers=owner).json()
    assert rotated["secret"] != endpoint["secret"] and rotated["previous_secret_expires_at"]
    with _system(tenant) as session:
        row = session.get(WebhookEndpoint, UUID(endpoint["id"]))
        assert rotated["secret"] not in row.secret_ciphertext
        assert service._signing_secrets(row, tenant.id) == [rotated["secret"], endpoint["secret"]]
    with clock.freeze(clock.now() + timedelta(hours=25)), _system(tenant) as session:
        assert service._signing_secrets(session.get(WebhookEndpoint, UUID(endpoint["id"])), tenant.id) == [
            rotated["secret"]
        ]
    assert "secret" not in client.get(f"{API}/webhook-endpoints/{endpoint['id']}", headers=owner).json()


def test_crypto_binds_ciphertext_to_its_tenant():
    a, b = uuid4(), uuid4()
    sealed = crypto.encrypt("whsec_x", a)
    assert crypto.decrypt(sealed, a) == "whsec_x"
    with pytest.raises(InvalidTag):
        crypto.decrypt(sealed, b)


# --- subscriptions -----------------------------------------------------------------------------------------


def test_star_expands_and_types_follow_the_subscriber(client, tenant, owner):
    everything = _endpoint(client, owner, types=["*"])
    assert everything["event_types"] == sorted(EVENTS)
    location = _location(client, owner)
    email, _ = add_staff(tenant, "admin", location_ids=[location])
    limited = login(client, tenant, email)
    types = {t["type"]: t["allowed"] for t in client.get(f"{API}/webhook-event-types", headers=limited).json()}
    assert types["clients.client.created"] and not types["billing.charge.created"]  # no locator for charges
    assert _endpoint(client, limited, types=["*"], status=403)["code"] == "event-permission-denied"
    assert _endpoint(client, limited, types=["billing.charge.created"], status=403)["code"] == "event-permission-denied"
    assert _endpoint(client, owner, types=["nope.nope.nope"], status=422)["code"] == "validation-failed"
    theirs = _endpoint(client, limited)
    listed = client.get(f"{API}/webhook-endpoints", headers=limited).json()["data"]
    assert [row["id"] for row in listed] == [theirs["id"]]  # a limited admin handles only their own endpoints
    assert client.get(f"{API}/webhook-endpoints/{everything['id']}", headers=limited).status_code == 404


def test_repointing_an_endpoint_needs_its_events_read_permissions(client, tenant, owner):
    """A webhook manager without billing reads must not redirect the owner's billing feed to their own URL."""
    endpoint = _endpoint(client, owner, types=["billing.charge.created"])
    _, staff_user_id = add_staff(tenant, "admin", all_locations=True)
    narrow = Principal(kind="staff", staff_user_id=staff_user_id, permissions={"integrations.webhook.manage": "all"})
    with _system(tenant) as session, pytest.raises(service.PermissionDenied):
        service.update_webhook_endpoint(session, narrow, UUID(endpoint["id"]), {"url": "https://evil.invalid/"})
    with mock.patch.object(transport, "resolve", return_value=[PUBLIC_IP]):
        moved = client.patch(
            f"{API}/webhook-endpoints/{endpoint['id']}", headers=owner, json={"url": "https://new.invalid/"}
        )
    assert moved.status_code == 200 and moved.json()["url"] == "https://new.invalid/"
    assert moved.json()["created_by_staff_user_id"] == str(tenant.owner_id)  # rebound to whoever repointed it


def test_location_limited_subscriber_only_receives_its_locations(client, tenant, owner):
    mine, other = _location(client, owner), _location(client, owner, "Other")
    email, _ = add_staff(tenant, "admin", location_ids=[mine])
    _endpoint(client, login(client, tenant, email))
    here, there = new_client(client, owner, mine), new_client(client, owner, other)
    with mock.patch.object(service, "_enqueue"), _system(tenant) as session:
        assert service.fan_out(session, uuid4(), {"type": "clients.client.created", "client_id": there["id"]}) == []
        assert len(service.fan_out(session, uuid4(), {"type": "clients.client.created", "client_id": here["id"]})) == 1


def test_fan_out_is_idempotent_and_ignores_unknown_types(client, tenant, owner):
    _endpoint(client, owner)
    event_id, payload = uuid4(), {"type": "clients.client.created", "client_id": str(uuid4())}
    with mock.patch.object(service, "_enqueue"), _system(tenant) as session:
        assert len(service.fan_out(session, event_id, payload)) == 1
        assert service.fan_out(session, event_id, payload) == []  # the outbox redelivered the same event
        assert service.fan_out(session, uuid4(), {"type": "identity.locked"}) == []


def test_deactivated_creator_disables_the_endpoint(client, tenant, owner, mailbox):
    email, staff_user_id = add_staff(tenant, "admin", all_locations=True)
    endpoint = _endpoint(client, login(client, tenant, email))
    assert client.post(f"{API}/staff-users/{staff_user_id}/deactivate", headers=owner).status_code == 200
    with mock.patch.object(service, "_enqueue"), _system(tenant) as session:
        service.reevaluate_creator(session, staff_user_id)  # what the deactivation handler runs
        row = session.get(WebhookEndpoint, UUID(endpoint["id"]))
        assert (row.status, row.disabled_reason) == ("disabled", "creator-inactive")
        assert service.fan_out(session, uuid4(), {"type": "clients.client.created", "client_id": str(uuid4())}) == []


def test_queued_retries_stop_when_the_creator_loses_access(client, tenant, owner):
    email, staff_user_id = add_staff(tenant, "admin", all_locations=True)
    _endpoint(client, login(client, tenant, email))
    delivery_id = _pending(tenant)
    assert client.post(f"{API}/staff-users/{staff_user_id}/deactivate", headers=owner).status_code == 200
    delay, send = _deliver(tenant, delivery_id, transport.Response(200, 5, "ok"))
    assert delay is None and send.call_count == 0
    assert _row(tenant, WebhookDelivery, delivery_id).status == "abandoned"


def test_rotation_rebinds_the_key_to_the_rotator(client, tenant, owner):
    key = _key(client, owner, scopes=["clients.client.read"])
    email, staff_user_id = add_staff(tenant, "admin", all_locations=True)
    rotated = client.post(f"{API}/api-keys/{key['id']}/rotate", headers=login(client, tenant, email), json={})
    assert rotated.status_code == 200 and rotated.json()["created_by_staff_user_id"] == str(staff_user_id)
    assert rotated.json()["previous_valid_until"] is None  # a new owner gets no grace period for the old secret
    assert client.get(f"{API}/clients", headers=_bearer(key["secret"])).status_code == 401
    assert client.get(f"{API}/clients", headers=_bearer(rotated.json()["secret"])).status_code == 200


# --- delivery ----------------------------------------------------------------------------------------------


def _deliver(tenant, delivery_id, response):
    with (
        mock.patch.object(transport, "resolve", return_value=[PUBLIC_IP]),
        mock.patch.object(transport, "send", return_value=response) as send,
        _system(tenant) as session,
    ):
        return service.attempt_delivery(session, delivery_id), send


def _pending(tenant, created: timedelta = timedelta(0)):
    with mock.patch.object(service, "_enqueue"), _system(tenant) as session:
        (delivery_id,) = service.fan_out(
            session, uuid4(), {"type": "clients.client.created", "client_id": str(uuid4())}
        )
        if created:
            session.execute(
                update(WebhookDelivery)
                .where(WebhookDelivery.id == delivery_id)
                .values(created_at=clock.now() - created)
            )
    return delivery_id


def _row(tenant, model, row_id):
    with _system(tenant) as session:
        row = session.get(model, row_id)
        session.expunge(row)
        return row


def test_retries_follow_the_schedule_then_fail(client, tenant, owner):
    endpoint = _endpoint(client, owner)
    delivery_id = _pending(tenant)
    delays = [_deliver(tenant, delivery_id, transport.Response(500, 5, "boom"))[0] for _ in range(rules.MAX_ATTEMPTS)]
    for got, expected in zip(delays, rules.RETRY_DELAYS, strict=False):
        assert expected * 0.9 <= got <= expected * 1.1
    assert delays[-1] is None
    row = _row(tenant, WebhookDelivery, delivery_id)
    assert (row.status, row.attempt_count, row.last_error) == ("failed", 8, "HTTP 500: boom")
    hook = _row(tenant, WebhookEndpoint, UUID(endpoint["id"]))
    assert (hook.status, hook.failure_count) == ("active", 1)


def test_success_resets_failures_and_a_second_attempt_is_a_no_op(client, tenant, owner):
    endpoint = _endpoint(client, owner)
    with _system(tenant) as session:
        session.execute(update(WebhookEndpoint).values(failure_count=3))
    delivery_id = _pending(tenant)
    delay, send = _deliver(tenant, delivery_id, transport.Response(200, 5, "ok"))
    assert delay is None and send.call_count == 1
    headers = send.call_args.args[1]
    body = send.call_args.args[2]
    assert rules.verify(endpoint["secret"], headers["FH-Signature"], body, now=int(time.time()))
    assert json.loads(body)["type"] == "clients.client.created" and headers["FH-Event-Id"] == json.loads(body)["id"]
    assert _row(tenant, WebhookDelivery, delivery_id).status == "delivered"
    hook = _row(tenant, WebhookEndpoint, UUID(endpoint["id"]))
    assert hook.failure_count == 0 and hook.last_success_at
    again, send = _deliver(tenant, delivery_id, transport.Response(200, 5, "ok"))
    assert again is None and send.call_count == 0


def test_sustained_failure_disables_and_notifies(client, tenant, owner, mailbox):
    endpoint = _endpoint(client, owner)
    with _system(tenant) as session:
        session.execute(update(WebhookEndpoint).values(failure_count=rules.DISABLE_AFTER_FAILED_DELIVERIES - 1))
    delivery_id, waiting = _pending(tenant), _pending(tenant)
    for _ in range(rules.MAX_ATTEMPTS):
        _deliver(tenant, delivery_id, transport.Response(503, 5, ""))
    hook = _row(tenant, WebhookEndpoint, UUID(endpoint["id"]))
    assert (hook.status, hook.disabled_reason) == ("disabled", "sustained-failure")
    assert _row(tenant, WebhookDelivery, waiting).status == "abandoned"
    assert any(m.to == tenant.owner_email and "disabled" in m.subject for m in mailbox)
    event = scalar(tenant, text("SELECT event_type FROM outbox_event WHERE event_type LIKE 'integrations.%'"))
    assert event == "integrations.webhook_endpoint.disabled"
    # Re-enable through the API, then replay the failed delivery with the same event id.
    patched = client.patch(f"{API}/webhook-endpoints/{endpoint['id']}", headers=owner, json={"status": "active"}).json()
    assert (patched["status"], patched["failure_count"], patched["disabled_reason"]) == ("active", 0, None)
    with mock.patch.object(service, "_enqueue"):
        replayed = client.post(f"{API}/webhook-deliveries/{delivery_id}/replay", headers=owner)
        assert (replayed.status_code, replayed.json()["status"], replayed.json()["attempt_count"]) == (
            202,
            "pending",
            0,
        )
        assert client.post(f"{API}/webhook-deliveries/{delivery_id}/replay", headers=owner).status_code == 409


def test_gone_disables_at_once(client, tenant, owner):
    endpoint = _endpoint(client, owner)
    delay, _ = _deliver(tenant, _pending(tenant), transport.Response(410, 5, ""))
    assert delay is None
    assert _row(tenant, WebhookEndpoint, UUID(endpoint["id"])).disabled_reason == "gone"


def test_five_silent_days_disable(client, tenant, owner):
    endpoint = _endpoint(client, owner)
    _deliver(tenant, _pending(tenant, created=timedelta(days=6)), transport.Response(500, 5, ""))
    assert _row(tenant, WebhookEndpoint, UUID(endpoint["id"])).disabled_reason == "no-success-for-5-days"


def test_paused_endpoint_abandons_pending_deliveries(client, tenant, owner):
    endpoint = _endpoint(client, owner)
    delivery_id = _pending(tenant)
    client.patch(f"{API}/webhook-endpoints/{endpoint['id']}", headers=owner, json={"status": "paused"})
    delay, send = _deliver(tenant, delivery_id, transport.Response(200, 5, ""))
    assert delay is None and send.call_count == 0
    assert _row(tenant, WebhookDelivery, delivery_id).status == "abandoned"


def test_test_ping_and_delivery_log(client, tenant, owner):
    endpoint = _endpoint(client, owner)
    with (
        mock.patch.object(transport, "resolve", return_value=[PUBLIC_IP]),
        mock.patch.object(transport, "send", return_value=transport.Response(200, 7, "ok")),
    ):
        ping = client.post(f"{API}/webhook-endpoints/{endpoint['id']}/test", headers=owner)
    assert (ping.status_code, ping.json()["status"], ping.json()["event_type"]) == (
        202,
        "delivered",
        "integrations.webhook.tested",
    )
    assert client.post(f"{API}/webhook-deliveries/{ping.json()['id']}/replay", headers=owner).status_code == 409
    with mock.patch.object(service, "_enqueue"), _system(tenant) as session:
        payload = {"type": "clients.client.created", "client_id": str(uuid4()), "note": "private words"}
        (delivery_id,) = service.fan_out(session, uuid4(), payload)
    detail = client.get(f"{API}/webhook-deliveries/{delivery_id}", headers=owner).json()
    assert (
        detail["payload_preview"]["note"] == "[redacted]"
        and detail["payload_preview"]["client_id"] == payload["client_id"]
    )
    failed = client.get(f"{API}/webhook-deliveries?status[in]=pending,failed", headers=owner).json()["data"]
    assert [row["id"] for row in failed] == [str(delivery_id)]


def test_webhook_reaches_a_local_receiver_signed(client, tenant, owner, monkeypatch):
    """End to end: a platform event, the outbox relay, the fan-out and delivery jobs, a real HTTP receiver."""
    received: list[tuple[dict, bytes]] = []

    class Receiver(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append((dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(get_settings().integrations, "webhook_allow_localhost", True)
    real_resolve, real_enqueue = transport.resolve, service._enqueue
    # Other tests' leftover events reach their (now paused) endpoints only; any retry is dropped, not delayed.
    monkeypatch.setattr(transport, "resolve", lambda h, p: real_resolve(h, p) if h == "127.0.0.1" else ["10.0.0.1"])
    monkeypatch.setattr(service, "_enqueue", lambda s, d, delay=None: None if delay else real_enqueue(s, d))
    try:
        url = f"http://127.0.0.1:{server.server_port}/hook"
        response = client.post(
            f"{API}/webhook-endpoints", headers=owner, json={"url": url, "event_types": ["clients.client.created"]}
        )
        assert response.status_code == 201, response.text
        endpoint = response.json()
        person = new_client(client, owner, _location(client, owner))
        broker.flush_all()
        while relay.relay_once():
            pass
        worker = Worker(broker, worker_timeout=100)
        worker.start()
        try:
            broker.join(
                "default", fail_fast=True, timeout=300_000
            )  # the fan-out enqueues the delivery job on the same queue
            worker.join()
        finally:
            worker.stop()
    finally:
        server.shutdown()
    mine = [(h, b) for h, b in received if json.loads(b)["data"].get("client_id") == person["id"]]
    assert len(mine) == 1
    headers, body = mine[0]
    assert headers["FH-Event-Type"] == "clients.client.created"
    assert rules.verify(endpoint["secret"], headers["FH-Signature"], body, now=int(time.time()))
    log = client.get(f"{API}/webhook-deliveries?webhook_endpoint_id={endpoint['id']}", headers=owner).json()["data"]
    assert [(row["status"], row["last_response_status"]) for row in log] == [("delivered", 200)]


# --- accounting export and adapters ------------------------------------------------------------------------


def test_journal_nets_and_refuses_unbalanced_days():
    lines = journal.build(
        [("receivable", 1000, 0), ("revenue:r", 0, 900), ("tax_payable:t", 0, 100), ("receivable", 0, 0)]
    )
    assert [(line.posting_key, line.debit_minor, line.credit_minor) for line in lines] == [
        ("receivable", 1000, 0), ("revenue:r", 0, 900), ("tax_payable:t", 0, 100),
    ]  # fmt: skip
    assert journal.build([("receivable", 500, 500)]) == []
    with pytest.raises(journal.UnbalancedJournal):
        journal.build([("receivable", 1000, 0), ("revenue:r", 0, 999)])


def test_accounting_export_posts_a_day_once(client, tenant, owner, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().integrations, "accounting_file_dir", str(tmp_path))
    location = _location(client, owner)
    person = new_client(client, owner, location)
    charge = {"client_id": person["id"], "location_id": location, "description": "Court", "unit_price_minor": 2500}
    with clock.freeze(clock.now() - timedelta(days=2)):  # only a finished day can be exported
        assert client.post(f"{API}/charges", headers=owner, json=charge).status_code == 201
    business_on = scalar(tenant, text(f"SELECT max(effective_on) FROM ledger_entry WHERE location_id = '{location}'"))
    connection = client.post(
        f"{API}/external-connections", headers=owner, json={"provider": "accounting_file", "location_id": location}
    ).json()
    run = {"external_connection_id": connection["id"], "location_id": location, "business_on": business_on.isoformat()}
    first = client.post(f"{API}/accounting-exports", headers=owner, json=run).json()
    assert first["status"] == "posted", first
    lines = first["totals"]["lines"]
    assert sum(line["debit_minor"] for line in lines) == sum(line["credit_minor"] for line in lines) > 0
    written = json.loads((tmp_path / first["external_id"]).read_text())
    assert written["doc_number"] == first["doc_number"] and written["doc_number"].endswith(
        business_on.strftime("%Y%m%d")
    )
    again = client.post(f"{API}/accounting-exports", headers=owner, json=run).json()
    assert (again["id"], again["attempt_count"]) == (first["id"], 1)
    empty = client.post(f"{API}/accounting-exports", headers=owner, json=run | {"business_on": "2001-01-01"}).json()
    assert empty["status"] == "skipped"
    other = _location(client, owner, "Other")
    assert client.post(f"{API}/accounting-exports", headers=owner, json=run | {"location_id": other}).status_code == 422
    quickbooks = client.post(f"{API}/external-connections", headers=owner, json={"provider": "quickbooks_online"})
    assert (quickbooks.status_code, quickbooks.json()["code"]) == (422, "provider-not-configured")


def test_accounting_export_refuses_the_locations_unfinished_day(client, owner):
    location = _location(client, owner)
    connection = client.post(
        f"{API}/external-connections", headers=owner, json={"provider": "accounting_file", "location_id": location}
    ).json()
    run = {"external_connection_id": connection["id"], "location_id": location}
    with clock.freeze(datetime(2026, 3, 10, 2, 0, tzinfo=UTC)):  # UTC is on the 10th; Chicago is on the 9th, 8pm
        today = client.post(f"{API}/accounting-exports", headers=owner, json=run | {"business_on": "2026-03-09"})
        assert today.status_code == 422, today.text
        done = client.post(f"{API}/accounting-exports", headers=owner, json=run | {"business_on": "2026-03-08"})
        assert done.json()["status"] == "skipped", done.text


def test_simulated_accounting_is_refused_outside_dev_and_test(client, tenant, owner, monkeypatch):
    from app.modules.integrations.models import ExternalConnection

    monkeypatch.setattr(get_settings(), "env", "production")
    with tenant_session(tenant.id) as session:
        row = ExternalConnection(provider="quickbooks_online", status="active", settings={})
        with pytest.raises(Exception, match="not configured"):
            service._accounting_adapter(session, row)


def test_quickbooks_adapter_posts_an_idempotent_journal_entry():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"JournalEntry": {"Id": "77"}})

    http = httpx.Client(base_url=QuickBooksOnline.BASE_URL, transport=httpx.MockTransport(handler))
    adapter = QuickBooksOnline(realm_id="123", access_token="test-token", client=http)
    entry = Journal("FH-MAIN-20260101", "2026-01-01", "USD", "memo", [
        JournalLine("1", 1000, 0, description="receivable"), JournalLine("4", 0, 1000, class_ref="9"),
    ])  # fmt: skip
    assert adapter.post_journal(entry, request_id="t:qbo_je:1") == "77"
    request = seen[0]
    assert request.url.path == "/v3/company/123/journalentry" and request.url.params["requestid"] == "t:qbo_je:1"
    body = json.loads(request.content)
    assert [line["JournalEntryLineDetail"]["PostingType"] for line in body["Line"]] == ["Debit", "Credit"]
    assert body["Line"][0]["Amount"] == "10.00" and body["Line"][1]["JournalEntryLineDetail"]["ClassRef"] == {
        "value": "9"
    }


def test_simulated_adapters_leave_a_command_log(client, tenant, owner):
    location = _location(client, owner)
    with _system(tenant) as session:
        real = JsonFileAccounting("unused")
        assert service.adapter_for(session, real, "accounting") is real
        fake = service.adapter_for(session, FakeAccounting(), "accounting", UUID(location))
        assert fake.post_journal(Journal("D", "2026-01-01", "USD", "m"), request_id="r:qbo_je:5") == "fake-je-5"
        meeting = service.video_meetings(session, UUID(location)).create_meeting(
            topic="Clinic", starts_at=clock.now(), minutes=30, host_user_id="h"
        )
        assert meeting.join_url.startswith("https://video.invalid/")
    rows = client.get(f"{API}/adapter-commands", headers=owner).json()["data"]
    assert {(row["port"], row["command"]) for row in rows} == {
        ("accounting", "post_journal"),
        ("video_meeting", "create_meeting"),
    }
    assert scalar(tenant, select(AdapterCommandLog.arguments).where(AdapterCommandLog.command == "post_journal")) == {
        "request_id": "r:qbo_je:5"
    }


def test_directory_reports_each_port_truthfully(client, owner):
    location = _location(client, owner)
    ports = {row["port"]: row for row in client.get(f"{API}/integration-adapters", headers=owner).json()}
    assert ports["accounting"]["status"] == "simulated" and ports["video_meeting"]["status"] == "not_configured"
    assert ports["door_controller"]["status"] == "not_configured" and ports["payment_provider"]["status"] == "simulated"
    client.post(
        f"{API}/external-connections", headers=owner, json={"provider": "accounting_file", "location_id": location}
    )
    ports = {row["port"]: row for row in client.get(f"{API}/integration-adapters", headers=owner).json()}
    assert (ports["accounting"]["status"], ports["accounting"]["adapter"]) == ("connected", "accounting_file")
