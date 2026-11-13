"""Client profile: emails and double opt-in, field policy, custom fields, categories, tags, views, disable,
member numbers, owners and own reach, emergency contacts, import."""

from datetime import date

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import clients
from app.modules.clients.models import ClientPortalAccess
from app.modules.platform.models import Identity
from conftest import add_staff, link_token, login, new_client

API = "/api/v1"


@pytest.fixture
def location_id(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return client.post(f"{API}/locations", headers=owner, json=body).json()["id"]


def test_emails_replace_atomically_and_verify_by_link(client, tenant, owner, location_id, mailbox):
    person = new_client(client, owner, location_id, primary_email="Pat@Example.com")
    assert person["primary_email"] == "pat@example.com"
    assert [m.to for m in mailbox] == ["pat@example.com"]
    token = link_token(mailbox[-1])
    emails = [{"email": "work@example.com", "is_primary": True}, {"email": "pat@example.com", "label": "home"}]
    updated = client.patch(f"{API}/clients/{person['id']}", headers=owner, json={"emails": emails}).json()
    assert updated["primary_email"] == "work@example.com"
    assert [(e["email"], e["is_primary"]) for e in updated["emails"]] == [
        ("work@example.com", True), ("pat@example.com", False)
    ]  # fmt: skip
    confirmed = client.post(f"{API}/public/email-verifications/confirm", json={"token": token})
    assert confirmed.status_code == 200 and confirmed.json()["verified_at"]
    assert client.post(f"{API}/public/email-verifications/confirm", json={"token": token}).status_code == 404
    pat = next(e for e in client.get(f"{API}/clients/{person['id']}", headers=owner).json()["emails"] if e["label"])
    again = client.post(f"{API}/clients/{person['id']}/emails/{pat['id']}/send-verification", headers=owner)
    assert again.json()["code"] == "already-verified"
    work = next(e for e in updated["emails"] if e["is_primary"])
    resend = client.post(f"{API}/clients/{person['id']}/emails/{work['id']}/send-verification", headers=owner)
    assert resend.status_code == 429  # one per minute; the first went out on create
    duplicate = [{"email": "a@example.com"}, {"email": "A@example.com"}]
    bad = client.patch(f"{API}/clients/{person['id']}", headers=owner, json={"emails": duplicate})
    assert bad.status_code == 422


def test_field_policy_applies_per_capture_context(client, tenant, owner, location_id):
    policies = [
        {"field_key": "phone_mobile", "capture_context": "staff", "requirement": "required"},
        {"field_key": "organization_name", "capture_context": "staff", "requirement": "hidden"},
    ]
    assert client.put(f"{API}/client-field-policies", headers=owner, json={"policies": policies}).status_code == 200
    body = {"first_name": "A", "last_name": "B", "home_location_id": location_id}
    missing = client.post(f"{API}/clients", headers=owner, json=body).json()
    assert missing["errors"][0]["code"] == "field-required"
    hidden = client.post(f"{API}/clients", headers=owner, json=body | {"phone_mobile": "+13125550100",
                                                                        "organization_name": "X"}).json()  # fmt: skip
    assert hidden["errors"][0]["code"] == "field-hidden"
    assert client.post(f"{API}/clients", headers=owner, json=body | {"phone_mobile": "+13125550100"}).status_code == 201
    locked = [{"field_key": "first_name", "capture_context": "staff", "requirement": "optional"}]
    response = client.put(f"{API}/client-field-policies", headers=owner, json={"policies": locked}).json()
    assert response["errors"][0]["code"] == "field-locked"
    cells = client.get(f"{API}/client-field-policies", headers=owner).json()["policies"]
    assert {
        "field_key": "phone_mobile",
        "capture_context": "staff",
        "requirement": "required",
        "is_locked": False,
    } in cells


def test_custom_fields_validate_and_merge(client, tenant, owner, location_id):
    choice = {"key": "level", "label": "Level", "data_type": "choice", "choices": ["Novice", "Pro"]}
    assert client.post(f"{API}/custom-fields", headers=owner, json=choice).status_code == 201
    no_choices = client.post(f"{API}/custom-fields", headers=owner, json=choice | {"key": "x", "choices": None})
    assert no_choices.status_code == 422
    client.post(f"{API}/custom-fields", headers=owner, json={"key": "joined", "label": "Joined", "data_type": "date"})
    person = new_client(client, owner, location_id, custom_values={"level": "Pro"})
    assert person["custom_values"] == {"level": "Pro"}
    url = f"{API}/clients/{person['id']}"
    assert client.patch(url, headers=owner, json={"custom_values": {"level": "Elite"}}).status_code == 422
    assert client.patch(url, headers=owner, json={"custom_values": {"joined": "2026-02-30"}}).status_code == 422
    assert client.patch(url, headers=owner, json={"custom_values": {"nope": 1}}).status_code == 422
    merged = client.patch(url, headers=owner, json={"custom_values": {"joined": "2026-02-01", "level": None}}).json()
    assert merged["custom_values"] == {"joined": "2026-02-01"}


def test_only_text_custom_fields_are_scanned_for_card_numbers(client, tenant, owner, location_id):
    """A text custom field is free text; a number field (a fob or legacy id typed as a number) is not scanned."""
    for key, data_type in (("remarks_x", "text"), ("fob", "number")):
        body = {"key": key, "label": key, "data_type": data_type}
        assert client.post(f"{API}/custom-fields", headers=owner, json=body).status_code == 201
    person = new_client(client, owner, location_id)
    url = f"{API}/clients/{person['id']}"
    refused = client.patch(url, headers=owner, json={"custom_values": {"remarks_x": "card 4111 1111 1111 1111"}})
    assert refused.status_code == 422 and refused.json()["code"] == "card-data-not-allowed"
    assert refused.json()["errors"][0]["pointer"] == "/custom_values/remarks_x" and "4111" not in refused.text
    kept = client.patch(url, headers=owner, json={"custom_values": {"fob": 4111111111111111, "remarks_x": "Locker 12"}})
    assert kept.status_code == 200, kept.text


def test_categories_tags_and_counts(client, tenant, owner, location_id):
    gold = client.post(f"{API}/client-categories", headers=owner, json={"name": "Gold"}).json()
    tags = client.get(f"{API}/tags", headers=owner).json()
    assert {"Tennis", "Winter"} <= {t["label"] for t in tags}
    mine = client.post(f"{API}/tags", headers=owner, json={"label": "VIP"}).json()
    person = new_client(client, owner, location_id, client_category_id=gold["id"], tag_ids=[mine["id"]])
    assert person["tag_ids"] == [mine["id"]]
    counts = {c["name"]: c["client_count"] for c in client.get(f"{API}/client-categories", headers=owner).json()}
    assert counts == {"Gold": 1}
    in_use = client.delete(f"{API}/client-categories/{gold['id']}", headers=owner)
    assert in_use.json()["code"] == "in-use"
    client.patch(f"{API}/client-categories/{gold['id']}", headers=owner, json={"is_active": False})
    inactive = client.post(f"{API}/clients", headers=owner, json={
        "first_name": "A", "last_name": "B", "home_location_id": location_id, "client_category_id": gold["id"]})  # fmt: skip
    assert inactive.status_code == 422
    spare = client.post(f"{API}/referral-categories", headers=owner, json={"name": "Flyer"}).json()
    assert client.delete(f"{API}/referral-categories/{spare['id']}", headers=owner).status_code == 204
    tagged = client.get(f"{API}/clients", headers=owner, params={"tag_id": mine["id"]}).json()["data"]
    assert [c["id"] for c in tagged] == [person["id"]]


def test_views_search_and_recent(client, tenant, owner, location_id):
    month = clock.now().month
    born = date(2000, month, 15).isoformat()
    ada = new_client(client, owner, location_id, first_name="Ada", last_name="Byron", birth_on=born,
                     phone_mobile="+13125550199", primary_email="ada@example.com")  # fmt: skip
    twin = new_client(client, owner, location_id, first_name="Ada", last_name="Byron", birth_on=born)
    other = new_client(client, owner, location_id, first_name="Zed", last_name="Zulu")

    def ids(**params):
        return {c["id"] for c in client.get(f"{API}/clients", headers=owner, params=params).json()["data"]}

    assert ids(view="birthdays_this_month") == {ada["id"], twin["id"]}
    assert ids(view="duplicates") == {ada["id"], twin["id"]}
    assert other["id"] in ids(view="no_category")
    assert ids(q="5550199") == {ada["id"]}
    assert ids(q="ADA@EXAMPLE") == {ada["id"]}
    client.get(f"{API}/clients/{other['id']}", headers=owner)
    listed = client.get(f"{API}/clients", headers=owner, params={"view": "recent"}).json()["data"]
    assert [c["id"] for c in listed] == [other["id"]]
    assert client.get(f"{API}/clients", headers=owner, params={"view": "nope"}).status_code == 422
    client.post(f"{API}/clients/{other['id']}/disable", headers=owner)
    assert ids(view="disabled") == {other["id"]}


def test_disable_revokes_portal_access_and_enable_restores_it(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id, primary_email="sam@example.com")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(kind="client", email="sam@example.com", status="active", email_verified_at=clock.now())
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, person["id"], identity.id)
        identity_id = identity.id
    disabled = client.post(f"{API}/clients/{person['id']}/disable", headers=owner).json()
    assert disabled["status"] == "disabled"
    assert client.post(f"{API}/clients/{person['id']}/disable", headers=owner).status_code == 409
    with tenant_session(tenant.id) as session:
        assert session.get(Identity, identity_id).status == "disabled"
    assert client.post(f"{API}/clients/{person['id']}/enable", headers=owner).json()["status"] == "active"
    with tenant_session(tenant.id) as session:
        assert session.get(Identity, identity_id).status == "active"
        row = session.scalar(select(ClientPortalAccess).where(ClientPortalAccess.identity_id == identity_id))
        assert row.status == "active"


def test_member_numbers_versions_and_owners(client, tenant, owner, location_id):
    settings = {"is_member_number_auto_generated": True, "member_number_trigger": "client_created",
                "member_number_prefix": "CM-"}  # fmt: skip
    assert client.patch(f"{API}/client-settings", headers=owner, json=settings).status_code == 200
    first, second = (new_client(client, owner, location_id) for _ in range(2))
    assert (first["member_number"], second["member_number"]) == ("CM-1", "CM-2")
    url = f"{API}/clients/{first['id']}"
    scanned = client.post(f"{url}/member-number", headers=owner, json={"member_number": "X9", "source": "scanned"})
    assert scanned.json()["member_number_source"] == "scanned"
    taken = client.post(f"{API}/clients/{second['id']}/member-number", headers=owner, json={"member_number": "X9"})
    assert taken.status_code == 409
    stale = client.patch(url, headers=owner, json={"first_name": "B", "version": first["version"]})
    assert stale.json()["code"] == "version-conflict"
    email, coach_id = add_staff(tenant, "coach", location_ids=[location_id])
    coach = login(client, tenant, email)
    assert client.get(url, headers=coach).status_code == 404
    owned = client.put(f"{url}/owners", headers=owner, json={"default_trainer_staff_user_id": str(coach_id)})
    assert owned.status_code == 200
    assert client.get(url, headers=coach).status_code == 200
    assert [c["id"] for c in client.get(f"{API}/clients", headers=coach).json()["data"]] == [first["id"]]
    assert client.patch(url, headers=coach, json={"city": "Peoria"}).status_code == 200
    assert client.get(f"{API}/clients/{second['id']}", headers=coach).status_code == 404
    unknown = client.put(f"{url}/owners", headers=owner, json={"default_trainer_staff_user_id": first["id"]})
    assert unknown.status_code == 422


def test_emergency_contacts_and_import(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    contacts = {"contacts": [{"name": "Robin", "phone": "+13125550101"}, {"name": "Jo"}]}
    url = f"{API}/clients/{person['id']}/emergency-contacts"
    assert [c["position"] for c in client.put(url, headers=owner, json=contacts).json()["contacts"]] == [1, 2]
    assert len(client.get(url, headers=owner).json()["contacts"]) == 2
    with tenant_session(tenant.id, actor=system_principal("import")) as session:
        row = {"first_name": "Imp", "last_name": "Orted", "home_location_id": location_id,
               "primary_email": "imp@example.com", "member_number": "IMP-1"}  # fmt: skip
        created, is_new = clients.service.import_client(session, row)
        again, is_new_again = clients.service.import_client(session, row | {"city": "Normal"})
        by_email, _ = clients.service.import_client(session, row | {"member_number": None, "region": "IL"})
        assert is_new and not is_new_again and again.id == created.id == by_email.id
        assert again.city == "Normal" and again.created_via == "import"
        assert clients.service.resolve(session, created.id).id == created.id
        assert clients.service.ensure_member_number(session, created.id) == "IMP-1"
