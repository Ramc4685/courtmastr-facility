"""Age confirmation (owner decision 2026-11-13, "Staff confirm once"): every online path that creates a client
needs a birth date the person declares true; a self-typed date is always flagged until staff confirm it once."""

from uuid import uuid4

import pytest
from sqlalchemy import update

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.clients.models import Client
from app.modules.engagement.tests.test_portal_entry import SIGNUPS, public, settings
from app.modules.programs.tests.test_checkout import online as online_program
from app.modules.programs.tests.test_guest_checkout import GUEST, allow_guests, guest_clients, keyed, start
from app.modules.rentals.tests.test_rentals import portal_client
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import link_token, new_client

ADULT = "1990-01-02"
CHILD = "2021-03-01"


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def staff_view(client, owner, client_id: str) -> dict:
    return ok(client.get(f"{API}/clients/{client_id}", headers=owner), 200)


def flagged(tenant, client_id) -> bool:
    with tenant_session(tenant.id) as session:
        return session.get(Client, client_id).is_birth_on_unverified


def dependant(client, portal, **extra):
    parent_of = next(t for t in ok(client.get(f"{API}/portal/relationship-types", headers=portal), 200)
                     if t["code"] == "parent_of")  # fmt: skip
    body = {"relationship_type_id": parent_of["id"], "first_name": "Kit", "last_name": "Pat", "birth_on": CHILD}
    return client.post(f"{API}/portal/dependents", headers=portal, json=body | extra)


# --- item 1: a declared birth date at every sign-up path ----------------------------------------------------------


def test_signup_needs_a_declared_birth_date_and_the_date_waits_for_staff(client, owner, tenant, f, mailbox):
    ok(settings(client, owner, f, allows_self_signup=True), 200)
    email = f"n-{uuid4().hex[:8]}@example.com"
    body = {"location_id": f.location, "email": email, "first_name": "Nia", "last_name": "Newcomer"}
    for short in (body, body | {"birth_on": ADULT}, body | {"birth_on": ADULT, "birth_on_declared": False}):
        assert client.post(SIGNUPS, headers=public(tenant), json=short).status_code == 422
    declared = body | {"birth_on": ADULT, "birth_on_declared": True}
    assert client.post(SIGNUPS, headers=public(tenant), json=declared).status_code == 202
    ok(client.post(f"{SIGNUPS}/confirm", headers=public(tenant), json={"token": link_token(mailbox[-1])}), 200)
    [found] = ok(client.get(f"{API}/clients", headers=owner, params={"q": email}), 200)["data"]
    seen = staff_view(client, owner, found["id"])
    assert (seen["birth_on"], seen["is_birth_on_unverified"]) == (ADULT, True)


def test_guest_checkout_needs_the_declaration_and_flags_every_client_it_creates(client, owner, tenant, f):
    camp, fee = online_program(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    email = f"g-{uuid4().hex[:6]}@example.com"
    assert start(client, tenant, f, camp, fee, email, declared=None).status_code == 422
    cart = ok(start(client, tenant, f, camp, fee, email))
    ok(client.post(f"{GUEST}/{cart['id']}/confirm", headers=keyed(public(tenant)),
                   json={"guest_token": cart["guest_token"], "method_token": "tok_card_ok"}), 200)  # fmt: skip
    created = guest_clients(tenant, email)
    assert len(created) == 2 and all(flagged(tenant, c) for c in created)  # the payer and the child


def test_a_portal_dependant_needs_the_declaration_and_the_parent_cannot_change_the_date(client, owner, tenant, f):
    _, portal = portal_client(client, owner, tenant, f)
    assert dependant(client, portal).status_code == 422
    kid = ok(dependant(client, portal, birth_on_declared=True), 201)
    assert staff_view(client, owner, kid["id"])["is_birth_on_unverified"] is True
    moved = client.patch(f"{API}/portal/clients/{kid['id']}", headers=portal, json={"birth_on": "2011-03-01"})
    assert (moved.status_code, moved.json()["code"]) == (422, "field-locked")  # they ask staff


def test_merge_carries_the_flag_with_a_backfilled_birth_date(client, owner, tenant, f):
    survivor = new_client(client, owner, f.location)["id"]
    loser = new_client(client, owner, f.location, birth_on=ADULT)["id"]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(Client).where(Client.id == loser).values(is_birth_on_unverified=True))
    merged = ok(client.post(f"{API}/clients/{survivor}/merge", headers=owner, json={"merged_client_ids": [loser]}), 200)
    assert (merged["birth_on"], merged["is_birth_on_unverified"]) == (ADULT, True)


def test_a_staff_entered_date_on_a_staff_record_counts_as_confirmed(client, owner, f):
    seen = new_client(client, owner, f.location, birth_on=ADULT)
    assert seen["is_birth_on_unverified"] is False
