"""Registration baskets (REG-09, 10, 12): held places, one invoice, documents before confirm, the portal paying
through secure_online_checkout as the strictest program asks, ownership by identity, and hold expiry."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.documents.tests.support import template
from app.modules.programs import checkout
from app.modules.programs.models import RegistrationCheckout
from app.modules.programs.tests.test_groups import fee_of, group_of, program
from app.modules.programs.tests.test_sessions import people
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import PASSWORD, link_token, login, new_client

PORTAL = "portal/registration-checkouts"
STAFF = "registration-checkouts"


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def basket(client, headers, f, path: str = STAFF, **body) -> dict:
    return ok(client.post(f"{API}/{path}", headers=headers, json={"location_id": f.location} | body))


def add(client, headers, basket_id: str, group: str, person: str, path: str = STAFF, **extra):
    body = {"program_group_id": group, "client_id": person} | extra
    return client.post(f"{API}/{path}/{basket_id}/items", headers=headers, json=body)


def online(client, owner, f, requirement: str = "pay_later_allowed", **fields) -> tuple[dict, dict]:
    """A published program open online with one online fee."""
    camp = program(client, owner, f, **fields)
    fee = fee_of(client, owner, camp["id"], 9000)
    body = {"is_enabled": True, "payment_requirement": requirement}
    ok(client.put(f"{API}/program-groups/{camp['id']}/registration-config", headers=owner, json=body), 200)
    ok(client.post(f"{API}/program-groups/{camp['id']}/publish", headers=owner), 200)
    return camp, fee


def member(client, tenant, owner, f, mailbox) -> tuple[dict, dict]:
    person = new_client(client, owner, f.location, primary_email=f"m-{uuid4().hex[:8]}@example.com")
    assert client.post(f"{API}/clients/{person['id']}/portal-access/invite", headers=owner, json={}).status_code == 200
    client.post(f"{API}/auth/invitations/accept", json={"token": link_token(mailbox[-1]), "new_password": PASSWORD})
    return person, login(client, tenant, person["primary_email"], audience="client")


def keyed(headers: dict) -> dict:
    return headers | {"Idempotency-Key": f"k-{uuid4().hex}"}


def test_staff_basket_holds_places_and_bills_one_invoice(client, owner, f):
    camp, clinic = program(client, owner, f, capacity=1), program(client, owner, f, name="Clinic")
    fee = fee_of(client, owner, camp["id"], 10000)
    a, b, payer = people(client, owner, f, 3)
    cart = basket(client, owner, f)
    cart = ok(add(client, owner, cart["id"], camp["id"], a, program_fee_id=fee["id"]), 200)
    assert cart["items"][0]["status"] == "pending" and group_of(client, owner, camp["id"])["enrolled_count"] == 1
    full = add(client, owner, cart["id"], camp["id"], b, program_fee_id=fee["id"])  # the hold takes the only place
    assert (full.status_code, full.json()["code"]) == (409, "capacity-full")
    cart = ok(add(client, owner, cart["id"], clinic["id"], b), 200)
    assert cart["total_minor"] == 10000 and len(cart["items"]) == 2

    item = cart["items"][1]["id"]
    assert len(ok(client.delete(f"{API}/{STAFF}/{cart['id']}/items/{item}", headers=owner), 200)["items"]) == 1
    done = ok(client.post(f"{API}/{STAFF}/{cart['id']}/confirm", headers=owner), 200)
    assert done["status"] == "completed" and done["invoice_id"] and done["items"][0]["status"] == "enrolled"
    again = client.post(f"{API}/{STAFF}/{cart['id']}/confirm", headers=owner)
    assert (again.status_code, again.json()["code"]) == (409, "checkout-closed")

    stranger = basket(client, owner, f, payer_client_id=payer)  # money goes where its owner points it
    refused = add(client, owner, stranger["id"], clinic["id"], a)
    assert (refused.status_code, refused.json()["code"]) == (422, "payer-not-related")


def test_documents_block_confirm_until_accepted(client, owner, f):
    camp = program(client, owner, f)
    tpl = template(client, owner)
    body = {"scope_type": "program_group", "scope_id": camp["id"], "template_id": tpl["id"]}
    assert client.put(f"{API}/document-bindings", headers=owner, json=body).status_code in (200, 201)
    (kid,) = people(client, owner, f, 1)
    cart = basket(client, owner, f)
    cart = ok(add(client, owner, cart["id"], camp["id"], kid), 200)
    assert [d["client_id"] for d in cart["missing_documents"]] == [kid]
    blocked = client.post(f"{API}/{STAFF}/{cart['id']}/confirm", headers=owner)
    assert (blocked.status_code, blocked.json()["code"]) == (409, "document-required")
    assert ok(client.get(f"{API}/{STAFF}/{cart['id']}", headers=owner), 200)["status"] == "open"


def test_abandon_and_expiry_release_the_held_places(client, owner, tenant, f):
    camp = program(client, owner, f, capacity=2)
    a, b = people(client, owner, f, 2)
    first, second = basket(client, owner, f), basket(client, owner, f)
    ok(add(client, owner, first["id"], camp["id"], a), 200)
    ok(add(client, owner, second["id"], camp["id"], b), 200)
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 2
    gone = ok(client.post(f"{API}/{STAFF}/{first['id']}/abandon", headers=owner), 200)
    assert gone["status"] == "abandoned" and group_of(client, owner, camp["id"])["enrolled_count"] == 1

    with tenant_session(tenant.id) as session:
        session.get(RegistrationCheckout, UUID(second["id"])).expires_at = clock.now() - timedelta(minutes=1)
    late = add(client, owner, second["id"], camp["id"], a)
    assert (late.status_code, late.json()["code"]) == (409, "checkout-expired")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert checkout.expire_holds(session) == 1
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 0
    assert ok(client.get(f"{API}/{STAFF}/{second['id']}", headers=owner), 200)["status"] == "expired"


def test_portal_pays_as_the_strictest_program_asks(client, owner, tenant, f, mailbox):
    later, later_fee = online(client, owner, f)
    now, now_fee = online(client, owner, f, "immediate_card_payment", name="Paid now")
    person, portal = member(client, tenant, owner, f, mailbox)
    cart = basket(client, portal, f, PORTAL)
    ok(add(client, portal, cart["id"], later["id"], person["id"], PORTAL, program_fee_id=later_fee["id"]), 200)
    cart = ok(add(client, portal, cart["id"], now["id"], person["id"], PORTAL, program_fee_id=now_fee["id"]), 200)
    assert cart["total_minor"] == 18000

    confirm = f"{API}/{PORTAL}/{cart['id']}/confirm"
    refused = client.post(confirm, headers=keyed(portal), json={"pay_later": True})
    assert (refused.status_code, refused.json()["code"]) == (422, "pay-now-required")
    declined = client.post(confirm, headers=keyed(portal), json={"method_token": "tok_card_declined"})
    assert declined.status_code in (402, 409), declined.text
    assert ok(client.get(f"{API}/{PORTAL}/{cart['id']}", headers=portal), 200)["status"] == "open"  # rolled back
    paid = ok(client.post(confirm, headers=keyed(portal), json={"method_token": "tok_card_ok"}), 200)
    assert paid["status"] == "completed" and paid["invoice_id"]
    assert group_of(client, owner, now["id"])["enrolled_count"] == 1


def test_portal_pay_later_and_ownership(client, owner, tenant, f, mailbox):
    camp, fee = online(client, owner, f)
    person, portal = member(client, tenant, owner, f, mailbox)
    other, _ = member(client, tenant, owner, f, mailbox)
    cart = basket(client, portal, f, PORTAL)
    foreign = add(client, portal, cart["id"], camp["id"], other["id"], PORTAL)  # not someone this login buys for
    assert foreign.status_code == 404
    cart = ok(add(client, portal, cart["id"], camp["id"], person["id"], PORTAL, program_fee_id=fee["id"]), 200)

    _, intruder = member(client, tenant, owner, f, mailbox)
    assert client.get(f"{API}/{PORTAL}/{cart['id']}", headers=intruder).status_code == 404
    assert client.get(f"{API}/{STAFF}/{cart['id']}", headers=owner).status_code == 404  # not a staff basket
    staff_cart = basket(client, owner, f)
    assert client.get(f"{API}/{PORTAL}/{staff_cart['id']}", headers=portal).status_code == 404

    unlisted = program(client, owner, f, name="Unpublished")
    assert add(client, portal, cart["id"], unlisted["id"], person["id"], PORTAL).status_code == 404
    confirm = client.post(f"{API}/{PORTAL}/{cart['id']}/confirm", headers=keyed(portal), json={"pay_later": True})
    assert ok(confirm, 200)["status"] == "completed"
    invoices = ok(client.get(f"{API}/invoices?bill_to_client_id={person['id']}", headers=owner), 200)["data"]
    assert [i["total_minor"] for i in invoices] == [9000]


def test_public_listing_shows_published_programs_only(client, owner, tenant, f):
    camp, _ = online(client, owner, f)
    program(client, owner, f, name="Private")
    public = {"X-Tenant-Slug": tenant.slug}
    listed = ok(client.get(f"{API}/public/program-groups?location_id={f.location}", headers=public), 200)
    assert [g["id"] for g in listed] == [camp["id"]]
    ok(client.post(f"{API}/program-groups/{camp['id']}/unpublish", headers=owner), 200)
    assert client.get(f"{API}/public/program-groups/{camp['id']}", headers=public).status_code == 404


def test_portal_group_waitlist_needs_a_full_program_and_a_fee_and_is_not_auto_promoted(
    client, owner, tenant, f, mailbox
):
    camp, fee = online(client, owner, f, capacity=1, waitlist_mode="auto_promote")
    (holder,) = people(client, owner, f, 1)
    person, portal = member(client, tenant, owner, f, mailbox)
    join = f"{API}/portal/waitlist-entries"
    body = {"client_id": person["id"], "program_group_id": camp["id"]}
    early = client.post(join, headers=portal, json=body | {"program_fee_id": fee["id"]})
    assert (early.status_code, early.json()["code"]) == (409, "session-has-space")
    place = ok(
        client.post(
            f"{API}/enrollments",
            headers=owner,
            json={"program_group_id": camp["id"], "client_id": holder, "program_fee_ids": [fee["id"]]},
        )
    )
    feeless = client.post(join, headers=portal, json=body)
    assert (feeless.status_code, feeless.json()["code"]) == (422, "fee-required")
    entry = ok(client.post(join, headers=portal, json=body | {"program_fee_id": fee["id"]}))
    ok(client.post(f"{API}/enrollments/{place['id']}/cancel", headers=owner, json={}), 200)
    waiting = ok(client.get(join, headers=portal), 200)
    assert [(e["id"], e["status"]) for e in waiting] == [(entry["id"], "waiting")]  # staff promote it by hand
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 0
