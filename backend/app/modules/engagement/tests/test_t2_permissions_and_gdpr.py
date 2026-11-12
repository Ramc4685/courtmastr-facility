"""Phase 8 T2 in engagement: the send-to-everyone gate (PLT-06) and GDPR mode's express-consent rule (PLT-16)."""

import pytest

from app.core.db.session import tenant_session
from app.modules.engagement.tests.test_messaging import API, _campaign, _person, ok, refused, svc
from conftest import add_staff, login

EVERYONE = {"sources": [{"kind": "all_clients"}]}


@pytest.fixture
def site(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return ok(client.post(f"{API}/locations", headers=owner, json=body), 201)["id"]


def _without_send_all(client, tenant, owner):
    email, staff_user_id = add_staff(tenant, "manager", all_locations=True)
    grants = {"grants": [{"permission_key": "engagement.campaign.send_all", "is_allowed": False}]}
    ok(client.put(f"{API}/staff-users/{staff_user_id}/permission-overrides", headers=owner, json=grants))
    return login(client, tenant, email)


def test_sending_to_every_client_needs_send_all_but_a_segment_does_not(client, tenant, owner, site):
    person = _person(client, owner, site, f"a@{tenant.slug}.example.com", tenant=tenant)
    manager = _without_send_all(client, tenant, owner)
    everyone = _campaign(client, owner, site, [], audience=EVERYONE)
    refused(client.post(f"{API}/campaigns/{everyone['id']}/send", headers=manager), 403)
    later = {"scheduled_at": "2031-01-01T10:00:00Z"}
    refused(client.post(f"{API}/campaigns/{everyone['id']}/schedule", headers=manager, json=later), 403)
    filtered = _campaign(client, owner, site, [], audience=EVERYONE | {
        "filters": [{"kind": "member", "is_member": False}]})  # fmt: skip
    assert ok(client.post(f"{API}/campaigns/{filtered['id']}/send", headers=manager))["status"] == "sent"
    chosen = _campaign(client, owner, site, [person["id"]])
    assert ok(client.post(f"{API}/campaigns/{chosen['id']}/send", headers=manager))["status"] == "sent"
    assert ok(client.post(f"{API}/campaigns/{everyone['id']}/send", headers=owner))["status"] == "sent"


def _gdpr(client, owner, on: bool) -> None:
    ok(client.put(f"{API}/privacy-settings", headers=owner, json={"is_gdpr_mode": on}))


def test_gdpr_mode_refuses_implied_marketing_consent_and_ignores_earlier_implied_opt_ins(
    client, tenant, owner, site, mailbox
):
    email = f"b@{tenant.slug}.example.com"
    person = _person(client, owner, site, email, tenant=tenant, opted_in=False)
    change = {"channel": "email", "address": email, "topic": "email_campaigns", "is_subscribed": True}
    implied = {"changes": [change], "note": "Bought a pass", "basis": "implied_purchase"}
    url = f"{API}/clients/{person['id']}/communication-preferences"
    ok(client.put(url, headers=owner, json=implied))  # recorded before GDPR mode
    with tenant_session(tenant.id) as session:
        assert svc.is_subscribed(session, person["id"], "email", "email_campaigns", email)

    _gdpr(client, owner, True)
    with tenant_session(tenant.id) as session:
        assert not svc.is_subscribed(session, person["id"], "email", "email_campaigns", email)
        assert svc.is_subscribed(session, person["id"], "email", "session_reminders", email)  # service topics stay
    campaign = _campaign(client, owner, site, [person["id"]])
    assert ok(client.post(f"{API}/campaigns/{campaign['id']}/send", headers=owner))["sent_count"] == 0

    refused(client.put(url, headers=owner, json=implied), 422, "express-consent-required")
    ok(client.put(url, headers=owner, json=implied | {"basis": "express_written", "note": "Signed the form"}))
    with tenant_session(tenant.id) as session:
        assert svc.is_subscribed(session, person["id"], "email", "email_campaigns", email)
    again = _campaign(client, owner, site, [person["id"]])
    assert ok(client.post(f"{API}/campaigns/{again['id']}/send", headers=owner))["sent_count"] == 1

    _gdpr(client, owner, False)
    ok(client.put(url, headers=owner, json=implied))  # outside GDPR mode the implied basis is accepted again
