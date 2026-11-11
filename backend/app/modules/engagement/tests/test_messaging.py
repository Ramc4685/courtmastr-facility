"""Build module 14: the consent-gated send path, campaigns and announcements, the public preference centre, the
portal inbox and devices, reminders, automations, staff alerts, settings and videos, and the data-subject side."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.auth import passwords, system_principal
from app.core.db.session import tenant_session
from app.modules import clients, engagement
from app.modules.engagement import subject
from app.modules.engagement.models import (
    Campaign,
    DeviceRegistration,
    InboxItem,
    Message,
    ScheduledNotification,
    Suppression,
)
from app.modules.platform.models import Identity
from conftest import add_staff, link_token, login, new_client, verify_email

API = "/api/v1"
SYSTEM = system_principal("tests")
svc = engagement.service
PW = "pw-long-enough-1"


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def refused(response, status: int, code: str | None = None):
    assert response.status_code == status, response.text
    if code:
        body = response.json()
        assert code in (body.get("code"), *(e.get("code") for e in body.get("errors", []))), response.text


@pytest.fixture
def site(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return ok(client.post(f"{API}/locations", headers=owner, json=body), 201)["id"]


def _person(client, owner, site, email, *, tenant, verified=True, opted_in=True, **fields):
    person = new_client(client, owner, site, primary_email=email, **fields)
    if verified:
        verify_email(tenant, person["id"], email)
    if opted_in:
        change = {"channel": "email", "address": email, "topic": "email_campaigns", "is_subscribed": True}
        body = {"changes": [change], "note": "Signed up at the desk"}
        ok(client.put(f"{API}/clients/{person['id']}/communication-preferences", headers=owner, json=body))
    return person


def _member(client, tenant, person) -> dict:
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        identity = Identity(
            kind="client", email=person["primary_email"], status="active", email_verified_at=clock.now()
        )
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, person["id"], identity.id)
        identity.password_hash = passwords.hash_password(PW)
    return login(client, tenant, person["primary_email"], PW, audience="client")


def _campaign(client, owner, site, ids, **extra):
    body = {"location_id": site, "name": "News", "subject": "Hello $first_name", "body_text": "News for $first_name.",
            "audience": {"sources": [{"kind": "client_ids", "ids": ids}]}} | extra  # fmt: skip
    return ok(client.post(f"{API}/campaigns", headers=owner, json=body), 201)


# --- the send gate ---------------------------------------------------------------------------------------------


def test_campaign_applies_every_consent_gate_and_counts_skips(client, tenant, owner, site, mailbox):
    good = _person(client, owner, site, "good@example.com", tenant=tenant)
    unverified = _person(client, owner, site, "unv@example.com", tenant=tenant, verified=False, opted_in=False)
    silent = _person(client, owner, site, "quiet@example.com", tenant=tenant, opted_in=False)
    blocked = _person(client, owner, site, "blocked@example.com", tenant=tenant)
    ok(client.post(f"{API}/suppressions", headers=owner, json={"address": "BLOCKED@example.com"}), 201)
    ids = [p["id"] for p in (good, unverified, silent, blocked)]
    campaign = _campaign(client, owner, site, ids)
    mailbox.clear()
    sent = ok(client.post(f"{API}/campaigns/{campaign['id']}/send", headers=owner))
    assert (sent["status"], sent["attempted_count"], sent["sent_count"]) == ("sent", 4, 1)
    stats = ok(client.get(f"{API}/campaigns/{campaign['id']}/stats", headers=owner))
    assert stats["suppressed_count"] == 1
    assert stats["unsubscribed_skip_count"] + stats["unverified_count"] == 2
    assert [m.to for m in mailbox] == ["good@example.com"]
    assert "Hello" in mailbox[0].subject and "/unsubscribe#token=" in mailbox[0].body  # the token is a fragment
    recipients = ok(client.get(f"{API}/campaigns/{campaign['id']}/recipients", headers=owner))["data"]
    assert {"suppressed", None} <= {r["skip_reason"] for r in recipients}
    refused(client.post(f"{API}/campaigns/{campaign['id']}/send", headers=owner), 409, "campaign-not-editable")
    history = ok(client.get(f"{API}/messages", headers=owner, params={"client_id": good["id"]}))["data"]
    assert [m["status"] for m in history if m["campaign_id"] == campaign["id"]] == ["sent"]


def test_one_click_unsubscribe_and_preference_centre(client, tenant, owner, site, mailbox):
    person = _person(client, owner, site, "fan@example.com", tenant=tenant)
    campaign = _campaign(client, owner, site, [person["id"]])
    mailbox.clear()
    ok(client.post(f"{API}/campaigns/{campaign['id']}/send", headers=owner))
    token = link_token(mailbox[-1])
    seen = ok(client.post(f"{API}/public/communication-preferences/lookup", json={"token": token}))
    assert seen["address"] == "fan@example.com" and all(i["address"] == "fan@example.com" for i in seen["data"])
    change = {"channel": "email", "address": "else@example.com", "topic": "email_campaigns", "is_subscribed": False}
    refused(client.put(f"{API}/public/communication-preferences", json={"token": token, "changes": [change]}), 422)
    own = change | {"address": "fan@example.com", "topic": "session_reminders"}
    done = ok(client.put(f"{API}/public/communication-preferences", json={"token": token, "changes": [own]}))
    assert not next(i for i in done["data"] if i["topic"] == "session_reminders")["is_subscribed"]
    first = ok(client.post(f"{API}/public/unsubscribe", json={"token": token}))
    assert first == {"topic": "email_campaigns", "unsubscribed": True, "changed": True}
    assert not ok(client.post(f"{API}/public/unsubscribe", json={"token": token}))["changed"]  # idempotent
    refused(client.post(f"{API}/public/unsubscribe", json={"token": "fhu_" + "x" * 30}), 404)
    assert ok(client.get(f"{API}/campaigns/{campaign['id']}/stats", headers=owner))["unsubscribed_count"] == 1
    again = _campaign(client, owner, site, [person["id"]])
    assert ok(client.post(f"{API}/campaigns/{again['id']}/send", headers=owner))["sent_count"] == 0


def test_direct_message_ignores_campaign_opt_out_but_not_suppression(client, tenant, owner, site, mailbox):
    person = _person(client, owner, site, "direct@example.com", tenant=tenant, opted_in=False)
    mailbox.clear()
    body = {"client_id": person["id"], "subject": "Hi $first_name", "body_text": "Your racket is here."}
    message = ok(client.post(f"{API}/messages", headers=owner, json=body), 201)
    assert message["status"] == "sent" and mailbox[-1].subject.startswith("Hi ")
    refused(
        client.post(f"{API}/messages", headers=owner, json=body | {"body_text": "$nope"}), 422, "unknown-merge-field"
    )
    ok(client.post(f"{API}/suppressions", headers=owner, json={"address": "direct@example.com"}), 201)
    skipped = ok(client.post(f"{API}/messages", headers=owner, json=body), 201)
    assert (skipped["status"], skipped["skip_reason"]) == ("skipped", "suppressed")
    assert ok(client.get(f"{API}/messages/{message['id']}", headers=owner))["body_text"] == "Your racket is here."


def test_bounce_suppresses_and_a_second_failure_after_release_is_permanent(client, tenant, owner, site):
    person = _person(client, owner, site, "bouncy@example.com", tenant=tenant)
    campaign = _campaign(client, owner, site, [person["id"]])
    ok(client.post(f"{API}/campaigns/{campaign['id']}/send", headers=owner))
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        message = session.scalar(select(Message).where(Message.campaign_id == campaign["id"]))
        message.provider_message_id = "p-1"
        session.flush()
        svc.record_delivery_event(session, "smtp", "p-1", "open")
        svc.record_delivery_event(session, "smtp", "p-1", "delivered")  # late: the status only moves forward
        assert svc.record_delivery_event(session, "smtp", "missing", "open") is None
        row = session.get(Campaign, campaign["id"])
        assert (row.delivered_count, row.opened_count) == (1, 1)
        svc.record_delivery_event(session, "smtp", "p-1", "bounce", "mailbox full")
    suppressions = ok(client.get(f"{API}/suppressions", headers=owner))["data"]
    suppression = next(s for s in suppressions if s["address"] == "bouncy@example.com")
    assert suppression["reason"] == "bounce"
    ok(client.post(f"{API}/suppressions/{suppression['id']}/release", headers=owner))
    refused(client.post(f"{API}/suppressions/{suppression['id']}/release", headers=owner), 409)
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        svc.suppress(session, "bouncy@example.com", "bounce")
        assert session.get(Suppression, suppression["id"]).is_permanent
    refused(client.post(f"{API}/suppressions/{suppression['id']}/release", headers=owner), 409, "suppression-permanent")


# --- templates, segments, campaigns ----------------------------------------------------------------------------


def test_templates_segments_and_campaign_lifecycle(client, tenant, owner, site, mailbox):
    refused(client.post(f"{API}/message-templates", headers=owner, json={"name": "X", "body_text": "$bad"}), 422)
    body = {"name": "Promo", "subject": "Hi", "body_text": "Hello $first_name"}
    template = ok(client.post(f"{API}/message-templates", headers=owner, json=body), 201)
    copy = ok(client.post(f"{API}/message-templates", headers=owner,
                          json={"name": "Promo 2", "copied_from_id": template["id"]}), 201)  # fmt: skip
    assert copy["body_text"] == "Hello $first_name"
    ok(client.patch(f"{API}/message-templates/{copy['id']}", headers=owner, json={"subject": "Hey"}))
    ok(client.delete(f"{API}/message-templates/{copy['id']}", headers=owner), 204)
    person = _person(client, owner, site, "seg@example.com", tenant=tenant, birth_on="1990-03-04")
    definition = {"sources": [{"kind": "all_clients"}], "filters": [{"kind": "birth_month", "months": [3]}]}
    segment = ok(client.post(f"{API}/segments", headers=owner, json={"name": "March", "definition": definition}), 201)
    ask = {"location_id": site, "segment_id": segment["id"]}
    preview = ok(client.post(f"{API}/segments/preview", headers=owner, json=ask))
    assert preview["count"] == 1 and preview["sample"][0]["client_id"] == person["id"]
    bad = {"location_id": site, "definition": {"sources": [{"kind": "tag"}]}}
    refused(client.post(f"{API}/segments/preview", headers=owner, json=bad), 422)
    campaign = ok(client.post(f"{API}/campaigns", headers=owner, json={
        "location_id": site, "name": "Birthday", "message_template_id": template["id"], "segment_id": segment["id"],
    }), 201)  # fmt: skip
    assert campaign["body_text"] == "Hello $first_name"
    refused(client.delete(f"{API}/segments/{segment['id']}", headers=owner), 409, "segment-in-use")
    mailbox.clear()
    ok(client.post(f"{API}/campaigns/{campaign['id']}/test", headers=owner))
    assert mailbox[-1].subject.startswith("[TEST]")
    now = {"scheduled_at": clock.now().isoformat()}
    refused(client.post(f"{API}/campaigns/{campaign['id']}/schedule", headers=owner, json=now), 422)
    later = {"scheduled_at": (clock.now() + timedelta(hours=1)).isoformat()}
    scheduled = ok(client.post(f"{API}/campaigns/{campaign['id']}/schedule", headers=owner, json=later))
    assert scheduled["status"] == "scheduled"
    edited = ok(client.patch(f"{API}/campaigns/{campaign['id']}", headers=owner, json={"name": "Edited"}))
    assert (edited["status"], edited["scheduled_at"]) == ("draft", None)  # an edit needs a fresh schedule
    ok(client.post(f"{API}/campaigns/{campaign['id']}/schedule", headers=owner, json=later))
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.send_due_campaigns(session) == 0
    with clock.freeze(clock.now() + timedelta(hours=2)), tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.send_due_campaigns(session) == 1
    assert ok(client.get(f"{API}/campaigns/{campaign['id']}", headers=owner))["status"] == "sent"
    draft = _campaign(client, owner, site, [person["id"]])
    ok(client.patch(f"{API}/campaigns/{draft['id']}", headers=owner, json={"name": "Renamed"}))
    ok(client.delete(f"{API}/campaigns/{draft['id']}", headers=owner), 204)
    listed = ok(client.get(f"{API}/campaigns", headers=owner, params={"status": "sent"}))["data"]
    assert [c["id"] for c in listed] == [campaign["id"]]


def test_an_api_key_creates_a_campaign_without_a_staff_sender(client, tenant, owner, site):
    scopes = ["engagement.campaign.read", "engagement.campaign.create"]
    key = ok(client.post(f"{API}/api-keys", headers=owner, json={"name": "CRM", "scopes": scopes}), 201)
    bearer = {"Authorization": f"Bearer {key['secret']}"}
    created = _campaign(client, bearer, site, [str(uuid4())])
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert session.get(Campaign, created["id"]).sender_staff_user_id is None


def test_announcement_reaches_the_portal_inbox_and_can_be_recalled(client, tenant, owner, site):
    person = _person(client, owner, site, "member@example.com", tenant=tenant)
    portal = _member(client, tenant, person)
    token = {"platform": "ios", "push_token": "tok-" + "a" * 20}
    device = ok(client.post(f"{API}/portal/devices", headers=portal, json=token), 201)
    notice = _campaign(client, owner, site, [person["id"]], channel="push", subject="Courts closed",
                       body_text="Closed at 6 today.", link_url="https://example.com/news")  # fmt: skip
    assert ok(client.post(f"{API}/campaigns/{notice['id']}/send", headers=owner))["inbox_count"] == 1
    inbox = ok(client.get(f"{API}/portal/inbox", headers=portal))["data"]
    assert [(i["title"], i["body"], i["read_at"]) for i in inbox] == [("Courts closed", "Closed at 6 today.", None)]
    assert ok(client.get(f"{API}/portal/inbox/unread-count", headers=portal)) == {"unread": 1}
    assert ok(client.post(f"{API}/portal/inbox/{inbox[0]['id']}/read", headers=portal))["read_at"]
    assert ok(client.get(f"{API}/portal/inbox/unread-count", headers=portal)) == {"unread": 0}
    with tenant_session(tenant.id) as session:  # no push provider is wired: the device send is logged as skipped
        statuses = session.scalars(select(Message.status).where(Message.campaign_id == notice["id"])).all()
        assert statuses == ["skipped"]
    stranger = _member(client, tenant, _person(client, owner, site, "other@example.com", tenant=tenant))
    refused(client.post(f"{API}/portal/inbox/{inbox[0]['id']}/read", headers=stranger), 404)
    refused(client.delete(f"{API}/portal/devices/{device['id']}", headers=stranger), 404)
    refused(client.post(f"{API}/portal/inbox/{inbox[0]['id']}/read", headers=owner), 404)  # staff are not members
    ok(client.post(f"{API}/campaigns/{notice['id']}/recall", headers=owner))
    assert ok(client.get(f"{API}/portal/inbox", headers=portal))["data"] == []
    refused(client.post(f"{API}/campaigns/{notice['id']}/recall", headers=owner), 409, "campaign-not-recallable")
    ok(client.delete(f"{API}/portal/devices/{device['id']}", headers=portal), 204)
    with tenant_session(tenant.id) as session:
        assert session.get(DeviceRegistration, device["id"]).revoked_at is not None


def test_household_inbox_shows_each_item_once_in_its_recipients_view(client, tenant, owner, site):
    """Known gap: a login holding a dependent's record saw a household announcement once per member, merged into
    one list. Each item belongs to one recipient; the dependent's shows only when acting for them."""
    parent = _person(client, owner, site, "parent@example.com", tenant=tenant, first_name="Pat")
    kid = new_client(client, owner, site, first_name="Kit")
    portal = _member(client, tenant, parent)
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        identity_id = session.scalar(select(Identity.id).where(Identity.email == "parent@example.com"))
        clients.service.link_identity(session, kid["id"], identity_id, is_primary=False)
    notice = _campaign(client, owner, site, [parent["id"], kid["id"]], channel="push", subject="Hi $first_name",
                       body_text="Closed at 6 today.")  # fmt: skip
    assert ok(client.post(f"{API}/campaigns/{notice['id']}/send", headers=owner))["inbox_count"] == 2
    own = ok(client.get(f"{API}/portal/inbox", headers=portal))["data"]
    assert [i["title"] for i in own] == ["Hi Pat"]
    assert ok(client.get(f"{API}/portal/inbox/unread-count", headers=portal)) == {"unread": 1}
    as_kid = {"client_id": kid["id"]}
    theirs = ok(client.get(f"{API}/portal/inbox", headers=portal, params=as_kid))["data"]
    assert [i["title"] for i in theirs] == ["Hi Kit"]
    ok(client.post(f"{API}/portal/inbox/{theirs[0]['id']}/read", headers=portal))
    assert ok(client.get(f"{API}/portal/inbox/unread-count", headers=portal, params=as_kid)) == {"unread": 0}
    assert ok(client.get(f"{API}/portal/inbox/unread-count", headers=portal)) == {"unread": 1}
    stranger = _member(client, tenant, _person(client, owner, site, "other@example.com", tenant=tenant))
    refused(client.get(f"{API}/portal/inbox", headers=stranger, params=as_kid), 404)
    refused(client.get(f"{API}/portal/inbox/unread-count", headers=stranger, params=as_kid), 404)
    refused(client.post(f"{API}/portal/inbox/{own[0]['id']}/read", headers=stranger), 404)


def test_campaigns_stay_inside_the_senders_locations(client, tenant, owner, site):
    west = {"name": "West", "time_zone": "America/Chicago", "country_code": "US"}
    other = ok(client.post(f"{API}/locations", headers=owner, json=west), 201)["id"]
    near = _person(client, owner, site, "near@example.com", tenant=tenant)
    far = _person(client, owner, other, "far@example.com", tenant=tenant)
    campaign = _campaign(client, owner, site, [near["id"], far["id"]])
    assert ok(client.post(f"{API}/campaigns/{campaign['id']}/send", headers=owner))["attempted_count"] == 1
    email, _ = add_staff(tenant, "manager", location_ids=[other])
    manager = login(client, tenant, email)
    refused(client.get(f"{API}/campaigns/{campaign['id']}", headers=manager), 404)
    refused(client.post(f"{API}/campaigns", headers=manager, json={"location_id": site, "name": "X"}), 404)
    assert ok(client.get(f"{API}/campaigns", headers=manager))["data"] == []
    desk_email, _ = add_staff(tenant, "front_desk", location_ids=[site])
    desk = login(client, tenant, desk_email)
    refused(client.post(f"{API}/campaigns", headers=desk, json={"location_id": site, "name": "X"}), 403)
    refused(client.post(f"{API}/suppressions", headers=desk, json={"address": "a@example.com"}), 403)


# --- reminders, automations, alerts ----------------------------------------------------------------------------


def test_reminders_are_queued_sent_once_and_cancelled_with_the_subject(client, tenant, owner, site, mailbox):
    person = _person(client, owner, site, "remind@example.com", tenant=tenant, opted_in=False)
    rule_body = {"location_id": site, "first_offset_minutes": 1440, "second_offset_minutes": 60}
    rule = ok(client.post(f"{API}/reminder-rules", headers=owner, json=rule_body), 201)
    refused(
        client.post(f"{API}/reminder-rules", headers=owner, json={"location_id": site}), 409, "reminder-rule-exists"
    )
    starts = clock.now() + timedelta(days=3)
    subject_id = uuid4()
    args = {"subject_type": "enrollment", "client_id": person["id"], "location_id": site, "starts_at": starts,
            "title": "Clinic"}  # fmt: skip
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.schedule_reminders(session, subject_id=subject_id, **args) == 2
        assert svc.schedule_reminders(session, subject_id=subject_id, **args) == 0
    mailbox.clear()
    with clock.freeze(starts - timedelta(hours=23)), tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.send_due_notifications(session) == 1
    assert len(mailbox) == 1 and "Clinic" in mailbox[0].subject
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.cancel_notifications(session, subject_type="enrollment", subject_id=subject_id) == 1
    with clock.freeze(starts - timedelta(minutes=30)), tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.send_due_notifications(session) == 0
    ok(client.patch(f"{API}/reminder-rules/{rule['id']}", headers=owner, json={"is_enabled": False}))
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.schedule_reminders(session, subject_id=uuid4(), **args) == 0
    ok(client.delete(f"{API}/reminder-rules/{rule['id']}", headers=owner), 204)


def test_automation_sends_on_its_trigger_and_stops_on_an_exit_event(client, tenant, owner, site, mailbox):
    person = _person(client, owner, site, "auto@example.com", tenant=tenant)
    body = {"name": "Moved up", "subject": "You are in", "body_text": "Hi $first_name"}
    template = ok(client.post(f"{API}/message-templates", headers=owner, json=body), 201)
    bad = {"name": "Bad", "trigger_event_type": "nope", "message_template_id": template["id"]}
    refused(client.post(f"{API}/automation-rules", headers=owner, json=bad), 422, "unknown-trigger")
    now_rule = ok(client.post(f"{API}/automation-rules", headers=owner, json={
        "name": "Promoted", "trigger_event_type": "programs.waitlist.promoted", "message_template_id": template["id"],
    }), 201)  # fmt: skip
    later = ok(client.post(f"{API}/automation-rules", headers=owner, json={
        "name": "Follow-up", "trigger_event_type": "clients.client.created", "message_template_id": template["id"],
        "delay_minutes": 60, "exit_event_types": ["memberships.contract.activated"],
    }), 201)  # fmt: skip
    payload = {"client_id": person["id"], "session_id": str(uuid4()), "enrollment_id": str(uuid4()),
               "waitlist_entry_id": str(uuid4())}  # fmt: skip
    mailbox.clear()
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.on_trigger(session, "programs.waitlist.promoted", payload) == 1
        assert svc.on_trigger(session, "programs.waitlist.promoted", payload) == 0  # the same event twice
        assert svc.on_trigger(session, "clients.client.created", {"client_id": person["id"]}) == 1
    assert [m.subject for m in mailbox] == ["You are in"]
    opted_out = _person(client, owner, site, "noauto@example.com", tenant=tenant, opted_in=False)
    mailbox.clear()
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        svc.on_trigger(session, "programs.waitlist.promoted", payload | {"client_id": opted_out["id"]})
        sent = session.scalar(
            select(Message).where(Message.client_id == opted_out["id"], Message.category == "marketing")
        )
        assert (sent.category, sent.skip_reason) == ("marketing", "unsubscribed")  # automations honour consent
    assert not mailbox
    activated = {"client_id": person["id"], "contract_id": str(uuid4())}
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        svc.on_trigger(session, "memberships.contract.activated", activated)
        queued = session.scalar(
            select(ScheduledNotification).where(ScheduledNotification.automation_rule_id == later["id"])
        )
        assert queued.status == "cancelled"
    rules = ok(client.get(f"{API}/automation-rules", headers=owner))["data"]
    assert {r["id"] for r in rules} == {now_rule["id"], later["id"]}
    ok(client.patch(f"{API}/automation-rules/{now_rule['id']}", headers=owner, json={"is_enabled": False}))
    ok(client.delete(f"{API}/automation-rules/{later['id']}", headers=owner), 204)


def test_staff_alerts_follow_the_route(client, tenant, owner, site, mailbox):
    email, staff_id = add_staff(tenant, "manager", location_ids=[site])
    stranger = {"location_id": site, "alert_kind": "payment_declined", "staff_user_ids": [str(uuid4())]}
    refused(client.post(f"{API}/notification-routes", headers=owner, json=stranger), 422)
    route = ok(client.post(f"{API}/notification-routes", headers=owner, json={
        "location_id": site, "alert_kind": "payment_declined", "staff_user_ids": [str(staff_id)],
        "emails": ["desk@example.com"],
    }), 201)  # fmt: skip
    twice = {"location_id": site, "alert_kind": "payment_declined"}
    refused(client.post(f"{API}/notification-routes", headers=owner, json=twice), 409)
    mailbox.clear()
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.alert_staff(session, site, "payment_declined", "Declined", "A card was declined.", dedupe="p1") == 2
        svc.alert_staff(session, site, "payment_declined", "Declined", "A card was declined.", dedupe="p1")
        assert svc.alert_staff(session, site, "portal_action", "x", "y", dedupe="p1") == 0
    assert sorted(m.to for m in mailbox) == sorted([email, "desk@example.com"])
    ok(client.patch(f"{API}/notification-routes/{route['id']}", headers=owner, json={"is_enabled": False}))
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert svc.alert_staff(session, site, "payment_declined", "Declined", "Again.", dedupe="p2") == 0


# --- portal settings and videos --------------------------------------------------------------------------------


def test_portal_settings_public_config_and_videos(client, tenant, owner, site):
    first = ok(client.get(f"{API}/locations/{site}/portal-settings", headers=owner))
    assert first["slug"] == "main" and not first["is_enabled"]
    put = {"is_enabled": True, "is_public": True, "welcome_text": "Hi", "terms_text": "Rules v1"}
    saved = ok(client.put(f"{API}/locations/{site}/portal-settings", headers=owner, json=put))
    bumped = ok(client.put(f"{API}/locations/{site}/portal-settings", headers=owner, json={"terms_text": "Rules v2"}))
    assert bumped["terms_version"] == (saved["terms_version"] or 1) + 1
    public = ok(client.get(f"{API}/public/portal-config", headers={"X-Tenant-Slug": tenant.slug}))
    assert [loc["welcome_text"] for loc in public["locations"]] == ["Hi"]
    insecure = {"location_id": site, "title": "X", "url": "http://evil.example.com/v"}
    refused(client.post(f"{API}/videos", headers=owner, json=insecure), 422, "video-host-not-allowed")
    shown = {"location_id": site, "title": "Warm-up", "url": "https://vimeo.com/123", "is_published": True}
    video = ok(client.post(f"{API}/videos", headers=owner, json=shown), 201)
    draft = {"location_id": site, "title": "Draft", "url": "https://vimeo.com/456"}
    hidden = ok(client.post(f"{API}/videos", headers=owner, json=draft), 201)
    portal = _member(client, tenant, _person(client, owner, site, "watch@example.com", tenant=tenant, opted_in=False))
    assert [v["id"] for v in ok(client.get(f"{API}/portal/videos", headers=portal))["data"]] == [video["id"]]
    ok(client.patch(f"{API}/videos/{hidden['id']}", headers=owner, json={"is_published": True}))
    assert len(ok(client.get(f"{API}/videos", headers=owner))["data"]) == 2
    ok(client.delete(f"{API}/videos/{hidden['id']}", headers=owner), 204)


# --- merge and erasure -----------------------------------------------------------------------------------------


def test_merge_moves_the_log_and_erasure_clears_it(client, tenant, owner, site):
    person = _person(client, owner, site, "gone@example.com", tenant=tenant)
    survivor = _person(client, owner, site, "keep@example.com", tenant=tenant)
    _member(client, tenant, survivor)
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        identity_id = session.scalar(select(Identity.id).where(Identity.email == "keep@example.com"))
        session.add(DeviceRegistration(identity_id=identity_id, client_id=survivor["id"], location_id=site,
                                       platform="ios", push_token="tok-erase"))  # fmt: skip
    notice = _campaign(
        client, owner, site, [person["id"], survivor["id"]], channel="push", subject="Hi", body_text="Hi"
    )
    ok(client.post(f"{API}/campaigns/{notice['id']}/send", headers=owner))
    direct = {"client_id": person["id"], "subject": "S", "body_text": "B"}
    ok(client.post(f"{API}/messages", headers=owner, json=direct), 201)
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert subject._export(session, person["id"])["messages"]
        subject._repoint(session, person["id"], survivor["id"])
        count = select(func.count()).select_from(InboxItem).where(InboxItem.client_id == survivor["id"])
        assert session.scalar(count) == 1  # the loser's copy of the same announcement is dropped
        assert not session.scalar(select(func.count()).select_from(Message).where(Message.client_id == person["id"]))
        result = subject._erase(session, survivor["id"])
        assert result["inbox_deleted"] == 1 and result["messages_cleared"] >= 1
        assert result["devices_deleted"] == 1  # the device's message rows are detached first
        assert session.scalar(select(Message.to_address).where(Message.client_id == survivor["id"]).limit(1)) is None


def test_group_enrollment_events_without_a_session_are_handled(tenant):
    """Programs publishes group enrollments and promotions with program_group_id, not session_id."""
    from app.modules.engagement import handlers

    ids = {"client_id": str(uuid4()), "enrollment_id": str(uuid4()), "program_group_id": str(uuid4())}
    promoted = {"type": "programs.waitlist.promoted", "waitlist_entry_id": str(uuid4()), **ids}
    # Called as the worker would: tenant id, event id, payload. A KeyError here once stalled every queue drain.
    handlers.on_enrollment_created(str(tenant.id), str(uuid4()), {"type": "programs.enrollment.created", **ids})
    handlers.on_waitlist_promoted(str(tenant.id), str(uuid4()), promoted)


def test_w2_08_a_push_token_on_another_login_is_revoked_never_reassigned(client, tenant, owner, site):
    first = _member(client, tenant, _person(client, owner, site, "first@example.com", tenant=tenant))
    second = _member(client, tenant, _person(client, owner, site, "second@example.com", tenant=tenant))
    token = {"platform": "android", "push_token": "tok-" + "b" * 20}
    mine = ok(client.post(f"{API}/portal/devices", headers=first, json=token), 201)
    again = ok(client.post(f"{API}/portal/devices", headers=first, json=token), 201)
    assert again["id"] == mine["id"]  # the same login re-registering keeps its row
    theirs = ok(client.post(f"{API}/portal/devices", headers=second, json=token), 201)
    assert theirs["id"] != mine["id"]
    with tenant_session(tenant.id) as session:
        old, new = session.get(DeviceRegistration, mine["id"]), session.get(DeviceRegistration, theirs["id"])
        assert old.revoked_at is not None and old.identity_id != new.identity_id and old.client_id != new.client_id
    refused(client.delete(f"{API}/portal/devices/{theirs['id']}", headers=first), 404)
