"""Guest checkout for program groups (REG-12): off by default, a new card only, always new clients, the guest token
as the only key, and blocking documents refuse guests."""

from uuid import uuid4

import pytest

from app.modules.documents.tests.support import template
from app.modules.programs.tests.test_checkout import online
from app.modules.programs.tests.test_groups import group_of
from app.modules.scheduling.tests.helpers import API, facility, ok

GUEST = f"{API}/public/guest-checkouts"


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def public(tenant) -> dict:
    return {"X-Tenant-Slug": tenant.slug}


def keyed(headers: dict) -> dict:
    return headers | {"Idempotency-Key": f"k-{uuid4().hex}"}


def allow_guests(client, owner, group_id: str):
    body = {"is_enabled": True, "payment_requirement": "immediate_card_payment", "allows_guest_checkout": True}
    ok(client.put(f"{API}/program-groups/{group_id}/registration-config", headers=owner, json=body), 200)


def start(client, tenant, f, camp, fee, email="guest@example.com"):
    body = {"location_id": f.location, "payer": {"first_name": "Gale", "last_name": "Guest", "email": email, "birth_on": "1985-02-03"},
            "participants": [{"first_name": "Kit", "last_name": "Guest", "birth_on": "2015-04-01"}],
            "items": [{"program_group_id": camp["id"], "program_fee_id": fee["id"], "participant": 0}]}  # fmt: skip
    return client.post(GUEST, headers=public(tenant), json=body)


def test_guest_checkout_is_off_by_default(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    assert start(client, tenant, f, camp, fee).status_code == 404


def test_guest_pays_by_new_card_and_gets_new_clients_every_time(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    cart = ok(start(client, tenant, f, camp, fee))
    token, confirm = cart["guest_token"], f"{GUEST}/{cart['id']}/confirm"
    assert token and cart["total_minor"] == 9000

    wrong = client.post(confirm, headers=keyed(public(tenant)),
                        json={"guest_token": "fhg_" + "x" * 40, "method_token": "tok_card_ok"})  # fmt: skip
    assert wrong.status_code == 404
    declined = client.post(confirm, headers=keyed(public(tenant)),
                           json={"guest_token": token, "method_token": "tok_card_declined"})  # fmt: skip
    assert declined.status_code in (402, 409), declined.text
    paid = ok(client.post(confirm, headers=keyed(public(tenant)),
                          json={"guest_token": token, "method_token": "tok_card_ok"}), 200)  # fmt: skip
    assert paid["status"] == "completed" and group_of(client, owner, camp["id"])["enrolled_count"] == 1
    assert "guest_token" not in paid or paid["guest_token"] is None

    ok(start(client, tenant, f, camp, fee))  # the same email again: never matched to the first payer
    found = ok(client.get(f"{API}/clients", headers=owner, params={"q": "guest@example.com"}), 200)["data"]
    assert [c["first_name"] for c in found].count("Gale") == 2  # two payers; each child shares its payer's email


def test_abandon_releases_the_place(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    cart = ok(start(client, tenant, f, camp, fee))
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 1
    gone = client.post(
        f"{GUEST}/{cart['id']}/abandon", headers=public(tenant), json={"guest_token": cart["guest_token"]}
    )
    assert ok(gone, 200)["status"] == "abandoned" and group_of(client, owner, camp["id"])["enrolled_count"] == 0


def test_blocking_documents_refuse_guests(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    body = {"scope_type": "program_group", "scope_id": camp["id"], "template_id": template(client, owner)["id"]}
    assert client.put(f"{API}/document-bindings", headers=owner, json=body).status_code in (200, 201)
    refused = start(client, tenant, f, camp, fee)
    assert (refused.status_code, refused.json()["code"]) == (409, "guest-documents-required")
