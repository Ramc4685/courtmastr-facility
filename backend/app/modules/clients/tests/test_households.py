"""Households: relationship types, staff links, acting rights, portal invitations, dependents, link requests."""

from datetime import date
from uuid import UUID

import pytest

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import clients
from app.modules.platform.models import Identity
from conftest import PASSWORD, link_token, login, new_client

API = "/api/v1"


@pytest.fixture
def location_id(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return client.post(f"{API}/locations", headers=owner, json=body).json()["id"]


def _types(client, headers) -> dict:
    return {t["code"]: t for t in client.get(f"{API}/relationship-types", headers=headers).json()}


def _portal_login(client, tenant, owner, person, mailbox) -> dict:
    """Invite the client to the portal through staff and accept the emailed invitation."""
    invited = client.post(f"{API}/clients/{person['id']}/portal-access/invite", headers=owner, json={})
    assert invited.status_code == 200, invited.text
    assert invited.json()["data"][0]["status"] == "invited"
    token = link_token(mailbox[-1])
    accepted = client.post(f"{API}/auth/invitations/accept", json={"token": token, "new_password": PASSWORD})
    assert accepted.status_code == 200, accepted.text
    return login(client, tenant, person["primary_email"], audience="client")


def test_types_and_staff_relationships(client, tenant, owner, location_id):
    types = _types(client, owner)
    assert types["parent_of"]["inverse_label"] == "Child of" and types["spouse_of"]["inverse_label"] == "Spouse of"
    custom = client.post(f"{API}/relationship-types", headers=owner, json={"code": "coach_of", "label": "Coach of"})
    assert custom.status_code == 201
    bad_inverse = {"code": "x_of", "label": "X", "inverse_type_id": types["parent_of"]["id"]}
    assert client.post(f"{API}/relationship-types", headers=owner, json=bad_inverse).status_code == 422
    mom, kid = new_client(client, owner, location_id), new_client(client, owner, location_id)
    body = {"other_client_id": kid["id"], "relationship_type_id": types["parent_of"]["id"]}
    link = client.post(f"{API}/clients/{mom['id']}/relationships", headers=owner, json=body).json()
    assert (link["label"], link["direction"], link["acting_rights"]) == ("Parent of", "outgoing", "this_for_other")
    seen = client.get(f"{API}/clients/{kid['id']}/relationships", headers=owner).json()[0]
    assert (seen["label"], seen["direction"], seen["acting_rights"]) == ("Child of", "incoming", "other_for_this")
    again = client.post(f"{API}/clients/{kid['id']}/relationships", headers=owner,
                        json={"other_client_id": mom["id"], "relationship_type_id": types["sibling_of"]["id"]})  # fmt: skip
    assert again.json()["code"] == "relationship-exists"
    self_link = client.post(
        f"{API}/clients/{mom['id']}/relationships", headers=owner, json=body | {"other_client_id": mom["id"]}
    )
    assert self_link.status_code == 422
    ended = client.post(f"{API}/client-relationships/{link['id']}/end", headers=owner).json()
    assert ended["status"] == "ended"
    assert client.post(f"{API}/client-relationships/{link['id']}/end", headers=owner).status_code == 409


def test_can_act_for_rules(client, tenant, owner, location_id):
    types = _types(client, owner)
    mom = new_client(client, owner, location_id, primary_email="mom@example.com")
    kid = new_client(client, owner, location_id, birth_on=date(2018, 1, 1).isoformat())
    grown = new_client(client, owner, location_id, birth_on=date(1990, 1, 1).isoformat(), primary_email="g@example.com")
    spouse = new_client(client, owner, location_id)
    sibling = new_client(client, owner, location_id)
    for other, code in ((kid, "parent_of"), (grown, "parent_of"), (spouse, "spouse_of"), (sibling, "sibling_of")):
        client.post(f"{API}/clients/{mom['id']}/relationships", headers=owner,
                    json={"other_client_id": other["id"], "relationship_type_id": types[code]["id"]})  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        ids = {}
        for person in (mom, grown):
            identity = Identity(
                kind="client", email=person["primary_email"], status="active", email_verified_at=clock.now()
            )
            session.add(identity)
            session.flush()
            clients.service.link_identity(session, person["id"], identity.id)
            ids[person["id"]] = identity.id
        me = ids[mom["id"]]
        mom, kid, grown, spouse, sibling = ({"id": UUID(p["id"])} for p in (mom, kid, grown, spouse, sibling))
        ids = {UUID(k): v for k, v in ids.items()}
        act = clients.households.can_act_for
        assert act(session, me, mom["id"], "edit_profile") == "self"
        assert act(session, me, kid["id"], "edit_profile") == "guardian"
        assert act(session, me, grown["id"], "book") == "delegate"  # an adult with their own login
        assert act(session, me, grown["id"], "edit_profile") is None
        assert act(session, me, spouse["id"], "book") == "delegate"
        assert act(session, me, sibling["id"], "book") is None
        assert act(session, ids[grown["id"]], mom["id"], "book") is None  # child_of grants nothing
        assert set(clients.households.actable_client_ids(session, me)) == {
            mom["id"],
            kid["id"],
            grown["id"],
            spouse["id"],
        }


def test_portal_invite_profile_and_dependents(client, tenant, owner, location_id, mailbox):
    types = _types(client, owner)
    mom = new_client(client, owner, location_id, primary_email="mom@example.com")
    portal = _portal_login(client, tenant, owner, mom, mailbox)
    me = client.get(f"{API}/me", headers=portal).json()
    assert me["principal"]["client_ids"] == [mom["id"]]
    access = client.get(f"{API}/clients/{mom['id']}/portal-access", headers=owner).json()["data"]
    assert access[0]["status"] == "active" and access[0]["identity_status"] == "active"
    again = client.post(f"{API}/clients/{mom['id']}/portal-access/invite", headers=owner, json={})
    assert again.json()["code"] == "already-invited"

    kid = client.post(f"{API}/portal/dependents", headers=portal, json={
        "relationship_type_id": types["parent_of"]["id"], "first_name": "Kit", "last_name": "Mom",
        "email": "mom@example.com",
    })  # fmt: skip
    assert kid.status_code == 201, kid.text
    kid = kid.json()
    assert kid["authority"] == "manager" and kid["can_edit"]
    sibling_type = client.post(f"{API}/portal/dependents", headers=portal, json={
        "relationship_type_id": types["sibling_of"]["id"], "first_name": "No", "last_name": "Rights"})  # fmt: skip
    assert sibling_type.status_code == 422
    listed = client.get(f"{API}/portal/clients", headers=portal).json()["data"]
    assert [c["id"] for c in listed] == [mom["id"], kid["id"]]
    updated = client.patch(f"{API}/portal/clients/{kid['id']}", headers=portal, json={"city": "Normal"}).json()
    assert updated["city"] == "Normal"
    contacts = {"contacts": [{"name": "Grandma"}]}
    put = client.put(f"{API}/portal/clients/{kid['id']}/emergency-contacts", headers=portal, json=contacts)
    assert put.status_code == 200
    assert client.get(f"{API}/portal/clients/{kid['id']}/emergency-contacts", headers=portal).json() == put.json()
    # the parent's address on the child's record cannot become a second login for the child
    clash = client.post(f"{API}/clients/{kid['id']}/portal-access/invite", headers=owner, json={})
    assert clash.status_code in (200, 409)
    stranger = new_client(client, owner, location_id)
    assert client.get(f"{API}/portal/clients/{stranger['id']}", headers=portal).status_code == 404
    assert client.get(f"{API}/portal/clients/{mom['id']}", headers=owner).status_code == 404  # staff token
    assert len(client.get(f"{API}/portal/relationship-types", headers=portal).json()) >= 5
    revoked = client.post(f"{API}/clients/{mom['id']}/portal-access/revoke", headers=owner).json()["data"]
    assert {r["status"] for r in revoked} == {"revoked"}


def test_relationship_request_needs_the_other_holder_to_confirm(client, tenant, owner, location_id, mailbox):
    types = _types(client, owner)
    ann = new_client(client, owner, location_id, first_name="Ann", primary_email="ann@example.com")
    bob = new_client(client, owner, location_id, first_name="Bob", primary_email="bob@example.com")
    ann_portal = _portal_login(client, tenant, owner, ann, mailbox)
    _portal_login(client, tenant, owner, bob, mailbox)
    mailbox.clear()
    request = {"relationship_type_id": types["spouse_of"]["id"], "first_name": "Bob", "last_name": bob["last_name"],
               "email": "bob@example.com"}  # fmt: skip
    nobody = request | {"email": "nobody@example.com"}
    assert client.post(f"{API}/portal/relationships", headers=ann_portal, json=nobody).status_code == 202
    assert mailbox == []  # same answer, no email: the portal does not reveal who has an account
    assert client.post(f"{API}/portal/relationships", headers=ann_portal, json=request).status_code == 202
    assert [m.to for m in mailbox] == ["bob@example.com"]
    pending = client.get(f"{API}/portal/relationships", headers=ann_portal).json()["data"]
    assert pending[0]["status"] == "pending"
    token = link_token(mailbox[-1])
    decided = client.post(f"{API}/public/relationship-confirmations", json={"token": token, "decision": "accept"})
    assert decided.json() == {"status": "active"}
    assert (
        client.post(f"{API}/public/relationship-confirmations", json={"token": token, "decision": "accept"}).status_code
        == 404
    )
    ended = client.post(f"{API}/portal/relationships/{pending[0]['id']}/end", headers=ann_portal).json()
    assert ended["status"] == "ended"


def test_staff_approve_pending_request(client, tenant, owner, location_id, mailbox):
    types = _types(client, owner)
    ann = new_client(client, owner, location_id, first_name="Ann", primary_email="ann2@example.com")
    bob = new_client(client, owner, location_id, first_name="Bob", primary_email="bob2@example.com")
    ann_portal = _portal_login(client, tenant, owner, ann, mailbox)
    _portal_login(client, tenant, owner, bob, mailbox)
    request = {"relationship_type_id": types["parent_of"]["id"], "first_name": "Bob", "last_name": bob["last_name"],
               "email": "bob2@example.com"}  # fmt: skip
    client.post(f"{API}/portal/relationships", headers=ann_portal, json=request)
    pending = client.get(f"{API}/clients/{bob['id']}/relationships", headers=owner).json()[0]
    approved = client.post(f"{API}/client-relationships/{pending['id']}/approve", headers=owner).json()
    assert approved["status"] == "active"
    assert client.post(f"{API}/client-relationships/{pending['id']}/approve", headers=owner).status_code == 409
