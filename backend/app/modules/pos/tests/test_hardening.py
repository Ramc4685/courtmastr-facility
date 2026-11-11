"""Wave 1 hardening, batch money (M-11): each register tender checks its own billing key, the attached client
is loaded through the reach-aware loader, and another client's stored card is refused."""

import pytest

from app.modules.pos.tests.conftest import API, add, key, start
from conftest import add_staff, login, new_client


def _tender(client, store, sale, headers, **body):
    return client.post(f"{API}/pos-sales/{sale['id']}/tenders", headers=headers | {"Idempotency-Key": key()}, json=body)


@pytest.mark.parametrize(
    ("denied", "body"),
    [
        ("billing.payment.take", {"tender": "payment", "amount_minor": 100}),
        ("billing.credit.apply", {"tender": "account_credit", "amount_minor": 100}),
        ("billing.invoice.create", {"tender": "pay_later", "amount_minor": 100}),
    ],
)
def test_each_tender_needs_its_billing_key(client, store, denied, body):
    email, user_id = add_staff(store.tenant, "front_desk", location_ids=[store.location_id])
    deny = {"grants": [{"permission_key": denied, "is_allowed": False}]}
    assert (
        client.put(f"{API}/staff-users/{user_id}/permission-overrides", headers=store.owner, json=deny).status_code
        == 200
    )
    cashier = login(client, store.tenant, email)
    store.post("/payments", {"client_id": store.client_id, "location_id": store.location_id, "amount_minor": 500,
                             "tender_kind": "cash"}, key=key())  # some credit on account  # fmt: skip
    sale = add(store, start(store, cashier, client_id=store.client_id), cashier, product_id=store.product_id)
    body = body | ({"tender_type_id": store.cash} if body["tender"] == "payment" else {})
    refused = _tender(client, store, sale, cashier, **body)
    assert (refused.status_code, refused.json()["code"]) == (403, "permission-denied"), refused.text
    assert _tender(client, store, sale, store.front, **body).status_code == 200  # the plain front desk may


def test_the_attached_client_must_be_in_reach(client, store):
    """A coach given the register still reaches only their own clients: anyone else reads as unknown."""
    email, user_id = add_staff(store.tenant, "coach", location_ids=[store.location_id])
    allow = {"grants": [{"permission_key": "pos.sale.create", "is_allowed": True}]}
    assert (
        client.put(f"{API}/staff-users/{user_id}/permission-overrides", headers=store.owner, json=allow).status_code
        == 200
    )
    coach = login(client, store.tenant, email)
    stranger = new_client(client, store.owner, store.location_id)["id"]
    body = {"register_id": store.register_id, "client_id": stranger}
    created = client.post(f"{API}/pos-sales", headers=coach, json=body)
    assert (created.status_code, created.json()["errors"][0]["pointer"]) == (422, "/client_id"), created.text
    sale = start(store, coach)
    patch = {"client_id": stranger, "version": sale["version"]}
    moved = client.patch(f"{API}/pos-sales/{sale['id']}", headers=coach, json=patch)
    assert (moved.status_code, moved.json()["errors"][0]["pointer"]) == (422, "/client_id"), moved.text
    moved = client.patch(f"{API}/pos-sales/{sale['id']}", headers=store.front, json=patch)
    assert moved.status_code == 200, moved.text  # the front desk reaches every client


def test_another_clients_stored_card_is_refused(client, store):
    other = new_client(client, store.owner, store.location_id)["id"]
    card = store.post(f"/clients/{other}/payment-methods", {"method_token": "tok_card_ok"})
    sale = add(store, start(store, client_id=store.client_id), product_id=store.product_id)
    refused = _tender(client, store, sale, store.owner, tender="payment", amount_minor=100,
                      payment_method_id=card["id"])  # fmt: skip
    assert (refused.status_code, refused.json()["code"]) == (422, "payment-method-not-usable"), refused.text
