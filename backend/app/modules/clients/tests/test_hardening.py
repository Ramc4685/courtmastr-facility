"""Wave 1 hardening, batch people: P-01 to P-07 (docs/security/wave1-hardening-spec.md section 4)."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.auth import Principal, system_principal
from app.core.db.session import tenant_session
from app.core.errors import NotFound, ValidationFailed
from app.modules import clients
from app.modules.clients.models import ClientMerge, ClientPortalAccess
from app.modules.platform import privacy
from conftest import PASSWORD, add_staff, link_token, login, new_client

API = "/api/v1"


@pytest.fixture
def location_id(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return client.post(f"{API}/locations", headers=owner, json=body).json()["id"]


def _own(tenant, *keys, staff_user_id=None) -> Principal:
    return Principal(kind="staff", tenant_id=tenant.id, staff_user_id=staff_user_id or uuid4(),
                     permissions=dict.fromkeys(keys, "own"))  # fmt: skip


def _types(client, headers) -> dict:
    return {t["code"]: t for t in client.get(f"{API}/relationship-types", headers=headers).json()}


def _portal(client, tenant, owner, person, mailbox) -> dict:
    assert client.post(f"{API}/clients/{person['id']}/portal-access/invite", headers=owner, json={}).status_code == 200
    token = link_token(mailbox[-1])
    client.post(f"{API}/auth/invitations/accept", json={"token": token, "new_password": PASSWORD})
    return login(client, tenant, person["primary_email"], audience="client")


def _born(years: int) -> str:
    return str(clock.now().date() - timedelta(days=365 * years + years // 4 + 5))


def test_every_client_command_goes_through_the_loader(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    caller = _own(tenant, "clients.client.disable", "clients.client.assign_owner")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        for command in (clients.service.disable_client, clients.service.enable_client):
            with pytest.raises(NotFound):
                command(session, caller, person["id"])
        with pytest.raises(NotFound):
            clients.service.assign_owners(session, caller, person["id"], {"default_trainer_staff_user_id": None})


def test_tasks_respect_client_reach(client, tenant, owner, location_id):
    email, coach_id = add_staff(tenant, "coach", location_ids=[location_id])
    coach = login(client, tenant, email)
    stranger = new_client(client, owner, location_id)
    refused = client.post(f"{API}/client-tasks", headers=coach, json={"client_id": stranger["id"], "subject_text": "x"})
    assert refused.status_code == 422 and refused.json()["errors"][0]["pointer"] == "/client_id"
    mine = new_client(client, owner, location_id)
    client.put(
        f"{API}/clients/{mine['id']}/owners", headers=owner, json={"default_trainer_staff_user_id": str(coach_id)}
    )
    task = client.post(f"{API}/client-tasks", headers=coach, json={"client_id": mine["id"], "subject_text": "x"})
    assert task.status_code == 201, task.text
    handed = client.patch(f"{API}/client-tasks/{task.json()['id']}", headers=coach,
                          json={"assignee_staff_user_id": str(tenant.owner_id)})  # fmt: skip
    assert handed.status_code == 422 and handed.json()["errors"][0]["pointer"] == "/assignee_staff_user_id"


def test_relationship_commands_check_both_parties(client, tenant, owner, location_id):
    types = _types(client, owner)
    a, b = new_client(client, owner, location_id), new_client(client, owner, location_id)
    rel = client.post(f"{API}/clients/{a['id']}/relationships", headers=owner,
                      json={"other_client_id": b["id"], "relationship_type_id": types["sibling_of"]["id"]}).json()  # fmt: skip
    _, coach_id = add_staff(tenant, "coach", location_ids=[location_id])
    caller = _own(tenant, "clients.relationship.manage", "clients.client.read", staff_user_id=coach_id)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        clients.service.get(session, a["id"]).default_trainer_staff_user_id = caller.staff_user_id
        session.flush()
        with pytest.raises(ValidationFailed) as refused:
            clients.households.create_relationship(
                session, caller, a["id"], {"other_client_id": b["id"], "relationship_type_id": types["spouse_of"]["id"]}
            )
        assert refused.value.extra["errors"][0]["pointer"] == "/other_client_id"
        for command in (clients.households.approve_relationship, clients.households.end_relationship):
            with pytest.raises(NotFound):
                command(session, caller, rel["id"])


def test_guardianship_of_a_minor_needs_staff(client, tenant, owner, location_id, mailbox):
    types = _types(client, owner)
    stranger = new_client(client, owner, location_id, first_name="Sam", primary_email="sam@example.com")
    minor = new_client(
        client, owner, location_id, first_name="Kim", primary_email="kim@example.com", birth_on=_born(15)
    )
    stranger_portal = _portal(client, tenant, owner, stranger, mailbox)
    minor_portal = _portal(client, tenant, owner, minor, mailbox)
    mailbox.clear()
    request = {"relationship_type_id": types["guardian_of"]["id"], "first_name": "Kim", "last_name": minor["last_name"],
               "email": "kim@example.com"}  # fmt: skip
    assert client.post(f"{API}/portal/relationships", headers=stranger_portal, json=request).status_code == 202
    assert mailbox == []  # no confirmation link goes to the minor
    [pending] = client.get(f"{API}/portal/relationships", headers=stranger_portal).json()["data"]
    assert pending["status"] == "pending"
    assert client.get(f"{API}/portal/clients/{minor['id']}", headers=stranger_portal).status_code == 404
    approved = client.post(f"{API}/client-relationships/{pending['id']}/approve", headers=owner)
    assert approved.json()["status"] == "active"
    # the minor cannot end a real guardian's link either
    ended = client.post(f"{API}/portal/relationships/{pending['id']}/end", headers=minor_portal)
    assert (ended.status_code, ended.json()["code"]) == (409, "staff-approval-required")
    # a token minted before the fix cannot be used to accept
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        rel = session.get(clients.models.ClientRelationship, pending["id"])
        rel.status = "pending"
        raw, rel.confirmation_token_hash = clients.households.tokens.mint("fhr", tenant.id)
        rel.confirmation_expires_at = clock.now() + timedelta(days=1)
    decided = client.post(f"{API}/public/relationship-confirmations", json={"token": raw, "decision": "accept"})
    assert (decided.status_code, decided.json()["code"]) == (409, "staff-approval-required")


def test_portal_cannot_change_a_recorded_birth_date(client, tenant, owner, location_id, mailbox):
    minor = new_client(client, owner, location_id, primary_email="teen@example.com", birth_on=_born(15))
    portal = _portal(client, tenant, owner, minor, mailbox)
    url = f"{API}/portal/clients/{minor['id']}"
    changed = client.patch(url, headers=portal, json={"birth_on": "1990-01-01"})
    assert changed.status_code == 422 and changed.json()["errors"][0]["code"] == "field-locked"
    assert client.patch(url, headers=portal, json={"birth_on": None}).status_code == 422
    assert client.patch(url, headers=portal, json={"birth_on": minor["birth_on"], "city": "Normal"}).status_code == 200
    blank = new_client(client, owner, location_id, primary_email="blank@example.com")
    blank_portal = _portal(client, tenant, owner, blank, mailbox)
    set_once = client.patch(
        f"{API}/portal/clients/{blank['id']}", headers=blank_portal, json={"birth_on": "1990-01-01"}
    )
    assert set_once.status_code == 200 and set_once.json()["birth_on"] == "1990-01-01"


def test_merge_never_carries_acting_rights(client, tenant, owner, location_id, mailbox):
    types = _types(client, owner)
    born = date(2015, 3, 3).isoformat()
    victim = new_client(client, owner, location_id, first_name="Vic", last_name="Ray", birth_on=born,
                        primary_email="vic@example.com")  # fmt: skip
    attacker = new_client(client, owner, location_id, first_name="Ann", primary_email="ann@example.com")
    portal = _portal(client, tenant, owner, attacker, mailbox)
    fake = client.post(f"{API}/portal/dependents", headers=portal, json={
        "relationship_type_id": types["parent_of"]["id"], "first_name": "Vic", "last_name": "Ray", "birth_on": born,
        "email": "vic@example.com", "birth_on_declared": True}).json()  # fmt: skip
    # an unverified address typed into a portal-created record is not a reason to pair it
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        reasons = clients.merge._reasons(
            session, clients.service.get(session, victim["id"]), clients.service.get(session, fake["id"])
        )
        assert reasons == ["same_birth_date"]
    # the reversed pair: the portal record may not survive and absorb the real one
    reversed_pair = {"merged_client_ids": [victim["id"]]}
    check = client.post(f"{API}/clients/{fake['id']}/merge-precheck", headers=owner, json=reversed_pair).json()
    assert (check["can_merge"], [b["code"] for b in check["blockers"]]) == (False, ["survivor-portal-created"])
    refused = client.post(f"{API}/clients/{fake['id']}/merge", headers=owner, json=reversed_pair)
    assert (refused.status_code, refused.json()["code"]) == (409, "merge-blocked")
    check = client.post(f"{API}/clients/{victim['id']}/merge-precheck", headers=owner,
                        json={"merged_client_ids": [fake["id"]]}).json()  # fmt: skip
    assert sorted(i["kind"] for i in check["review"]) == ["portal_access", "relationship"]
    merged = client.post(f"{API}/clients/{victim['id']}/merge", headers=owner, json={"merged_client_ids": [fake["id"]]})
    assert merged.status_code == 200, merged.text
    assert client.get(f"{API}/portal/clients/{victim['id']}", headers=portal).status_code == 404
    assert [c["id"] for c in client.get(f"{API}/portal/clients", headers=portal).json()["data"]] == [attacker["id"]]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        rows = session.scalars(select(ClientPortalAccess).where(ClientPortalAccess.client_id == victim["id"])).all()
        assert rows == []


def test_merge_of_two_portal_records_keeps_guardians_apart(client, tenant, owner, location_id, mailbox):
    """Backlog 29: two portal-created records with different guardians; neither guardian may gain the other's."""
    types = _types(client, owner)
    born = date(2016, 4, 4).isoformat()
    child = {
        "relationship_type_id": types["parent_of"]["id"],
        "first_name": "Sam",
        "last_name": "Lee",
        "birth_on": born,
        "birth_on_declared": True,
    }
    mum = new_client(client, owner, location_id, first_name="Mia", primary_email="mia@example.com")
    stranger = new_client(client, owner, location_id, first_name="Rex", primary_email="rex@example.com")
    real = client.post(f"{API}/portal/dependents", headers=_portal(client, tenant, owner, mum, mailbox), json=child)
    fake = client.post(
        f"{API}/portal/dependents", headers=_portal(client, tenant, owner, stranger, mailbox), json=child
    )
    real, fake = real.json(), fake.json()
    body = {"merged_client_ids": [real["id"]]}
    check = client.post(f"{API}/clients/{fake['id']}/merge-precheck", headers=owner, json=body).json()
    assert check["can_merge"] is False and "survivor-has-other-managers" in {b["code"] for b in check["blockers"]}
    refused = client.post(f"{API}/clients/{fake['id']}/merge", headers=owner, json=body)
    assert (refused.status_code, refused.json()["code"]) == (409, "merge-blocked")


def test_merge_never_hands_a_signed_in_record_to_another_guardian(client, tenant, owner, location_id, mailbox):
    """A loser with its own portal login and no managers is still held: a guardian of the survivor may not gain it."""
    types = _types(client, owner)
    mum = new_client(client, owner, location_id, first_name="Mo", primary_email="mo@example.com")
    kid = new_client(client, owner, location_id, first_name="Jo", last_name="Fox")
    linked = client.post(f"{API}/clients/{mum['id']}/relationships", headers=owner,
                         json={"other_client_id": kid["id"], "relationship_type_id": types["parent_of"]["id"]})  # fmt: skip
    assert linked.status_code == 201, linked.text
    adult = new_client(client, owner, location_id, first_name="Jo", last_name="Fox", primary_email="jo@example.com")
    _portal(client, tenant, owner, adult, mailbox)
    body = {"merged_client_ids": [adult["id"]]}
    refused = client.post(f"{API}/clients/{kid['id']}/merge", headers=owner, json=body)
    assert (refused.status_code, refused.json()["code"]) == (409, "merge-blocked"), refused.text
    # a desk duplicate nobody signs in to or acts for still merges
    desk = new_client(client, owner, location_id, first_name="Jo", last_name="Fox")
    merged = client.post(f"{API}/clients/{kid['id']}/merge", headers=owner, json={"merged_client_ids": [desk["id"]]})
    assert merged.status_code == 200, merged.text


def test_merge_log_holds_no_personal_values(client, tenant, owner, location_id):
    keep = new_client(client, owner, location_id, first_name="Lee", last_name="Ray")
    lose = new_client(client, owner, location_id, first_name="Lee", last_name="Ray", birth_on="1980-02-02",
                      phone_mobile="+13125550199", member_number="SECRET-7", city="Peoria")  # fmt: skip
    merged = client.post(f"{API}/clients/{keep['id']}/merge", headers=owner, json={"merged_client_ids": [lose["id"]]})
    assert merged.status_code == 200, merged.text
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        privacy.HANDLERS["clients"].erase(session, keep["id"])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        [row] = session.scalars(select(ClientMerge).where(ClientMerge.merged_client_id == lose["id"])).all()
        assert set(row.backfilled_fields.values()) == {True}
        assert {"birth_on", "phone_mobile", "member_number", "city"} <= set(row.backfilled_fields)
        stored = repr(row.backfilled_fields)
        assert not any(v in stored for v in ("1980-02-02", "+13125550199", "SECRET-7", "Peoria"))
