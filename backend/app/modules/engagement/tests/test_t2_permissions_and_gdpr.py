"""Phase 8 T2 in engagement: the send-to-everyone gate (PLT-06) and GDPR mode's express-consent rule (PLT-16)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core import clock
from app.core.audit import AuditEvent
from app.core.db.session import tenant_session
from app.modules.engagement.models import CommunicationPreference, InboxItem, Message
from app.modules.engagement.tests.test_messaging import API, SYSTEM, _campaign, _person, ok, refused, svc
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
    filtered = _campaign(client, owner, site, [], audience=EVERYONE | {  # "non-members" can still be everyone
        "filters": [{"kind": "member", "is_member": False}]})  # fmt: skip
    refused(client.post(f"{API}/campaigns/{filtered['id']}/send", headers=manager), 403)
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


def test_a_segment_widened_to_everyone_after_scheduling_goes_back_to_draft(client, tenant, owner, site):
    manager = _without_send_all(client, tenant, owner)
    person = _person(client, owner, site, f"w@{tenant.slug}.example.com", tenant=tenant)
    narrow = {"name": "Few", "definition": {"sources": [{"kind": "client_ids", "ids": [person["id"]]}]}}
    segment = ok(client.post(f"{API}/segments", headers=owner, json=narrow), 201)
    campaign = _campaign(client, owner, site, [], audience=None, segment_id=segment["id"])
    later = {"scheduled_at": (clock.now() + timedelta(hours=1)).isoformat()}
    ok(client.post(f"{API}/campaigns/{campaign['id']}/schedule", headers=manager, json=later))
    ok(client.patch(f"{API}/segments/{segment['id']}", headers=owner, json={"definition": EVERYONE}))
    with clock.freeze(clock.now() + timedelta(hours=2)), tenant_session(tenant.id, actor=SYSTEM) as session:
        svc.send_due_campaigns(session)
    held = ok(client.get(f"{API}/campaigns/{campaign['id']}", headers=owner))
    assert (held["status"], held["hold_reason"], held["attempted_count"]) == ("draft", "send-all-required", 0)


def test_automation_mail_checks_consent_even_with_a_transactional_template(client, tenant, owner, site, mailbox):
    quiet = _person(client, owner, site, f"q@{tenant.slug}.example.com", tenant=tenant, opted_in=False)
    body = {"name": "Sneaky", "subject": "Deal", "body_text": "Buy now", "category": "transactional"}
    template = ok(client.post(f"{API}/message-templates", headers=owner, json=body), 201)
    for channel in ("email", "push"):
        ok(client.post(f"{API}/automation-rules", headers=owner, json={
            "name": f"On sign-up {channel}", "trigger_event_type": "clients.client.created", "channel": channel,
            "message_template_id": template["id"],
        }), 201)  # fmt: skip
    mailbox.clear()
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        svc.on_trigger(session, "clients.client.created", {"client_id": quiet["id"]})
        sent = session.scalar(
            select(Message).where(Message.client_id == quiet["id"], Message.message_template_id.is_not(None))
        )
        assert (sent.category, sent.skip_reason) == ("marketing", "unsubscribed")
        assert (
            session.scalar(select(func.count()).select_from(InboxItem).where(InboxItem.client_id == quiet["id"])) == 0
        )
    assert not mailbox


def test_switching_gdpr_off_keeps_ignored_implied_opt_ins_withdrawn(client, tenant, owner, site):
    email = f"i@{tenant.slug}.example.com"
    person = _person(client, owner, site, email, tenant=tenant, opted_in=False)
    change = {"channel": "email", "address": email, "topic": "email_campaigns", "is_subscribed": True}
    url = f"{API}/clients/{person['id']}/communication-preferences"
    ok(client.put(url, headers=owner, json={"changes": [change], "note": "Bought a pass", "basis": "implied_purchase"}))
    _gdpr(client, owner, True)
    _gdpr(client, owner, False)
    with tenant_session(tenant.id) as session:
        assert not svc.is_subscribed(session, person["id"], "email", "email_campaigns", email)
        event = session.scalars(select(AuditEvent).where(AuditEvent.action == "platform.security.manage")
                                .order_by(AuditEvent.occurred_at.desc())).first()  # fmt: skip
        assert event.changes["implied_consents_withdrawn"] == 1


def test_a_marketing_opt_in_without_consent_proof_is_not_express_in_gdpr_mode(client, tenant, owner, site):
    email = f"n@{tenant.slug}.example.com"
    person = _person(client, owner, site, email, tenant=tenant)
    _gdpr(client, owner, True)
    with tenant_session(tenant.id) as session:
        assert svc.is_subscribed(session, person["id"], "email", "email_campaigns", email)
        session.execute(update(CommunicationPreference).where(CommunicationPreference.client_id == person["id"])
                        .values(consent_event_id=None))  # fmt: skip
        assert not svc.is_subscribed(session, person["id"], "email", "email_campaigns", email)
