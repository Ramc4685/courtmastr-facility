"""GDPR export and erasure (with the sentinel scan), and communication preferences with the consent log."""

import pytest
from sqlalchemy import String, Text, select, text

from app.core import clock
from app.core.auth import passwords, system_principal
from app.core.db import Base
from app.core.db.base import GLOBAL_TABLES
from app.core.db.session import tenant_session
from app.modules import billing, clients, engagement
from app.modules.clients.models import ClientEmail
from app.modules.engagement.models import ConsentEvent
from app.modules.platform.models import Identity
from conftest import link_token, login, new_client

API = "/api/v1"
SENTINEL = "zqxsentinel"


@pytest.fixture
def location_id(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return client.post(f"{API}/locations", headers=owner, json=body).json()["id"]


def _verify_all(tenant, client_id):
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        for row in session.scalars(select(ClientEmail).where(ClientEmail.client_id == client_id)):
            row.verified_at = clock.now()


def test_preferences_defaults_double_opt_in_and_log(client, tenant, owner, location_id, mailbox):
    person = new_client(client, owner, location_id, primary_email="pref@example.com", phone_mobile="+13125550123")
    url = f"{API}/clients/{person['id']}/communication-preferences"
    matrix = {(p["channel"], p["topic"]): p for p in client.get(url, headers=owner).json()["data"]}
    assert (
        matrix[("email", "session_reminders")]["is_subscribed"] and matrix[("email", "session_reminders")]["is_default"]
    )
    assert not matrix[("email", "email_campaigns")]["is_subscribed"]
    opt_in = {"changes": [{"channel": "email", "address": "pref@example.com", "topic": "email_campaigns",
                           "is_subscribed": True}], "note": "Asked at the desk"}  # fmt: skip
    assert client.put(url, headers=owner, json=opt_in | {"note": None}).status_code == 422  # staff must say how
    assert client.put(url, headers=owner, json=opt_in).json()["errors"][0]["code"] == "email-unverified"
    client.post(f"{API}/public/email-verifications/confirm", json={"token": link_token(mailbox[-1])})
    done = {(p["channel"], p["topic"]): p for p in client.put(url, headers=owner, json=opt_in).json()["data"]}
    assert (
        done[("email", "email_campaigns")]["is_subscribed"] and done[("email", "email_campaigns")]["source"] == "staff"
    )
    wrong_topic = {"changes": [{"channel": "sms", "address": "+13125550123", "topic": "email_campaigns",
                                "is_subscribed": True}], "note": "x"}  # fmt: skip
    assert client.put(url, headers=owner, json=wrong_topic).status_code == 422
    stranger = {"changes": [{"channel": "sms", "address": "+13125550999", "topic": "sms_marketing",
                             "is_subscribed": True}], "note": "x"}  # fmt: skip
    assert client.put(url, headers=owner, json=stranger).status_code == 422
    with tenant_session(tenant.id) as session:
        gate = engagement.service.is_subscribed
        assert gate(session, person["id"], "email", "email_campaigns", "PREF@example.com")
        assert not gate(session, person["id"], "sms", "sms_marketing", "+13125550123")
        assert gate(session, person["id"], "push", "league_alerts")
        assert session.scalar(select(ConsentEvent.basis).where(ConsentEvent.client_id == person["id"])) == "express"


def test_portal_preferences_follow_can_act_for(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id, primary_email="me@example.com")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(kind="client", email="me@example.com", status="active", email_verified_at=clock.now())
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, person["id"], identity.id)
        identity.password_hash = passwords.hash_password("pw-long-enough-1")
    portal = login(client, tenant, "me@example.com", "pw-long-enough-1", audience="client")
    url = f"{API}/portal/clients/{person['id']}/communication-preferences"
    assert client.get(url, headers=portal).status_code == 200
    body = {"changes": [{"channel": "push", "topic": "push_announcements", "is_subscribed": True}]}
    changed = {(p["channel"], p["topic"]): p for p in client.put(url, headers=portal, json=body).json()["data"]}
    assert changed[("push", "push_announcements")]["source"] == "portal"
    other = new_client(client, owner, location_id)
    assert (
        client.get(f"{API}/portal/clients/{other['id']}/communication-preferences", headers=portal).status_code == 404
    )


def test_export_bundle_and_erasure_with_sentinel_scan(client, tenant, owner, location_id, mailbox):
    s = SENTINEL
    person = new_client(
        client, owner, location_id, first_name=f"{s}first", last_name=f"{s}last", preferred_name=f"{s}pref",
        primary_email=f"{s}@example.com", phone_mobile="+13125550177", address_line1=f"{s} street",
        city=f"{s}ville", comments=f"{s} comment", medical_notes=f"{s} asthma", organization_name=f"{s} inc",
        member_number=f"{s}-1",
    )  # fmt: skip
    pid = person["id"]
    _verify_all(tenant, pid)
    client.put(f"{API}/clients/{pid}/emergency-contacts", headers=owner, json={"contacts": [{"name": f"{s} mum"}]})
    client.post(
        f"{API}/clients/{pid}/notes", headers=owner, json={"kind": "call", "subject_text": f"{s} subj", "body": s}
    )
    client.post(f"{API}/clients/{pid}/alerts", headers=owner, json={"message": f"{s} alert"})
    client.post(f"{API}/client-tasks", headers=owner, json={"client_id": pid, "subject_text": f"{s} task"})
    prefs = {"note": "form", "changes": [
        {"channel": "email", "address": f"{s}@example.com", "topic": "email_campaigns", "is_subscribed": True},
        {"channel": "email", "address": f"{s}@example.com", "topic": "league_alerts", "is_subscribed": False}]}  # fmt: skip
    assert client.put(f"{API}/clients/{pid}/communication-preferences", headers=owner, json=prefs).status_code == 200
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        category = billing.service.create_revenue_category(session, code="GEN", label="General", tax_ids=[])
    charge = client.post(f"{API}/charges", headers=owner, json={
        "client_id": pid, "location_id": location_id, "description": "Lesson", "unit_price_minor": 1000,
        "revenue_category_id": str(category.id)})  # fmt: skip
    assert charge.status_code == 201, charge.text

    export = client.post(
        f"{API}/data-subject-requests", headers=owner, json={"client_id": pid, "kind": "export"}
    ).json()
    assert export["status"] == "completed"
    bundle = client.get(f"{API}/data-subject-requests/{export['id']}", headers=owner).json()["bundle"]
    assert bundle["clients"][pid]["profile"]["medical_notes"] == f"{s} asthma"
    assert len(bundle["engagement"]["consent_events"]) == 2

    no_reason = client.post(f"{API}/data-subject-requests", headers=owner, json={"client_id": pid, "kind": "erasure"})
    assert no_reason.status_code == 422
    erase = client.post(f"{API}/data-subject-requests", headers=owner,
                        json={"client_id": pid, "kind": "erasure", "reason": "Asked by email"}).json()  # fmt: skip
    # billing blocks the erasure while the lesson is unpaid; staff may override, and the ledger is kept anyway
    assert erase["status"] == "blocked"
    assert [(b["context"], b["code"]) for b in erase["blockers"]] == [("billing", "open-balance")]
    url = f"{API}/data-subject-requests/{erase['id']}/confirm"
    assert client.post(url, headers=owner, json={"confirmation": "erase"}).status_code == 422
    assert client.post(url, headers=owner, json={"confirmation": "ERASE"}).json()["code"] == "erasure-blocked"
    done = client.post(url, headers=owner, json={"confirmation": "ERASE", "is_blocker_override": True}).json()
    assert done["status"] == "completed" and done["handler_results"]["clients"]["client_note"] == 1
    assert client.post(url, headers=owner, json={"confirmation": "ERASE"}).status_code == 409
    erased = client.get(f"{API}/clients/{pid}", headers=owner).json()
    assert (erased["first_name"], erased["status"], erased["primary_email"]) == ("Erased", "disabled", None)
    assert client.post(f"{API}/data-subject-requests", headers=owner,
                       json={"client_id": pid, "kind": "export"}).json()["code"] == "already-erased"  # fmt: skip
    assert client.get(f"{API}/data-subject-requests/{export['id']}", headers=owner).json()["bundle"] is None
    with tenant_session(tenant.id) as session:
        hits = []
        for table in Base.metadata.sorted_tables:
            if table.name in ("audit_event", "outbox_event", *GLOBAL_TABLES) or "tenant_id" not in table.c:
                continue
            for column in table.c:
                if isinstance(column.type, String | Text) and not column.computed:
                    found = session.execute(
                        text(f"SELECT count(*) FROM {table.name} WHERE {column.name}::text ILIKE :p"), {"p": f"%{s}%"}
                    ).scalar()
                    if found:
                        hits.append(f"{table.name}.{column.name}")
        assert hits == []  # no personal data left anywhere outside the audit trail (append-only, redacted diffs)
        kept = session.scalars(select(ConsentEvent).where(ConsentEvent.client_id == pid)).all()
        assert [e.kind for e in kept] == ["opt_out"] and len(kept[0].address) == 64  # hashed proof of opt-out
        charges = session.execute(text("SELECT count(*) FROM charge WHERE client_id = :c"), {"c": pid}).scalar()
        assert charges == 1  # the ledger is retained
