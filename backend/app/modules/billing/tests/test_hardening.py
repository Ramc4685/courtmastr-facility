"""Wave 1 hardening, batch money (docs/security/wave1-hardening-spec.md section 3): money goes only where its
owner points it, and each move is checked at the location whose books it changes."""

import pytest
from sqlalchemy import update

from app.modules.billing.tests.test_billing import API, work
from app.modules.billing.tests.test_surface import Api, item
from app.modules.clients.models import ClientRelationship
from conftest import add_staff, login, new_client


@pytest.fixture
def api(client, shop):
    return Api(client, shop.owner)


def _cash(shop, client_id, amount, location_id=None, **over) -> dict:
    return {"client_id": str(client_id), "location_id": str(location_id or shop.location_id), "amount_minor": amount,
            "tender_kind": "cash"} | over  # fmt: skip


def _relate(api, parent_id, kid_id) -> None:
    parent_of = next(t for t in api("GET", "/relationship-types") if t["code"] == "parent_of")
    api("POST", f"/clients/{parent_id}/relationships", {"other_client_id": str(kid_id),
                                                       "relationship_type_id": parent_of["id"]}, 201)  # fmt: skip


def _set_link(shop, status) -> None:
    with work(shop.tenant) as session:
        session.execute(
            update(ClientRelationship).where(ClientRelationship.to_client_id == shop.client_id).values(status=status)
        )


def test_money_never_pays_a_strangers_item(client, api, shop):
    """M-01: allocate, take-with-allocations, take-with-invoice and credit apply against another client's item
    are 422 payer-mismatch; a parent paying a linked child's item still works."""
    stranger = new_client(client, shop.owner, shop.location_id)["id"]
    owed = api("POST", "/charges", item(shop), 201)["id"]  # 1083, the shop client's
    invoice = api("POST", "/invoices", {"charge_ids": [owed]}, 201)
    theirs = api("POST", "/payments", _cash(shop, stranger, 2000), 201)
    target = {"allocations": [{"charge_id": owed, "amount_minor": 500}]}

    api("POST", f"/payments/{theirs['id']}/allocations", target, 422, "payer-mismatch")
    api("POST", f"/payments/{theirs['id']}/allocations", {"invoice_id": invoice["id"]}, 422, "payer-mismatch")
    api("POST", "/payments", _cash(shop, stranger, 500) | target, 422, "payer-mismatch")
    api("POST", "/payments", _cash(shop, stranger, 500, invoice_id=invoice["id"]), 422, "payer-mismatch")
    api("POST", f"/clients/{stranger}/account-credit/apply", target, 422, "payer-mismatch")
    api("POST", f"/clients/{stranger}/account-credit/apply", {"invoice_id": invoice["id"]}, 422, "payer-mismatch")
    walk_in = {"location_id": str(shop.location_id), "amount_minor": 500, "tender_kind": "cash"}
    api("POST", "/payments", walk_in | target, 422)  # a walk-in payment settles only items with no client
    assert api("GET", f"/invoices/{invoice['id']}")["balance_minor"] == 1083

    _relate(api, stranger, shop.client_id)
    _set_link(shop, "pending")  # a request nobody accepted yet makes no payer
    api("POST", f"/payments/{theirs['id']}/allocations", target, 422, "payer-mismatch")
    _set_link(shop, "active")  # now the stranger is the shop client's parent
    applied = api("POST", f"/payments/{theirs['id']}/allocations", target)
    assert applied["unapplied_minor"] == 1500
    assert api("POST", "/payments", _cash(shop, stranger, 583, invoice_id=invoice["id"]), 201)["unapplied_minor"] == 0
    assert api("GET", f"/invoices/{invoice['id']}")["status"] == "paid"


def test_an_invoice_cannot_be_billed_to_a_stranger(client, api, shop):
    """M-06: the create path applies the same payer rule as reassign-payer, so autopay never charges a
    stranger's stored card."""
    stranger = new_client(client, shop.owner, shop.location_id)["id"]
    owed = api("POST", "/charges", item(shop), 201)["id"]
    body = {"charge_ids": [owed], "bill_to_client_id": stranger, "is_autopay": True}
    api("POST", "/invoices", body, 422, "payer-not-related")
    _relate(api, stranger, shop.client_id)
    _set_link(shop, "pending")
    api("POST", "/invoices", body, 422, "payer-not-related")
    _set_link(shop, "active")
    assert api("POST", "/invoices", body, 201)["bill_to_client_id"] == stranger


def test_reallocate_checks_each_target_location(client, api, shop, desk):
    """M-02: a manager limited to West moves a West payment only onto West's books, and must name the targets."""
    west_payment = api("POST", "/payments", _cash(shop, shop.client_id, 3000, desk.west), 201)
    main_item = api("POST", "/charges", item(shop), 201)["id"]
    west_item = api("POST", "/charges", item(shop, location_id=desk.west), 201)["id"]
    main_invoice = api("POST", "/invoices", {"charge_ids": [main_item]}, 201)
    path = f"/payments/{west_payment['id']}/allocations"
    to = lambda charge_id: {"allocations": [{"charge_id": charge_id, "amount_minor": 100}]}  # noqa: E731

    api("POST", path, to(main_item), 404, headers=desk.west_manager)
    api("POST", path, {"invoice_id": main_invoice["id"]}, 404, headers=desk.west_manager)
    api("POST", path, {}, 422, headers=desk.west_manager)  # "oldest first" could reach any location
    assert api("POST", path, to(west_item), headers=desk.west_manager)["unapplied_minor"] == 2900
    assert api("POST", path, to(main_item))["unapplied_minor"] == 2800  # the owner reaches both


def test_credit_refund_stays_inside_the_callers_locations(api, shop, desk):
    """M-03: credit sitting on a Main payment cannot be refunded by a manager limited to West."""
    api("POST", "/payments", _cash(shop, shop.client_id, 1000), 201)
    path = f"/clients/{shop.client_id}/account-credit/refund"
    body = {"amount_minor": 400, "reason": "Moving away"}
    api("POST", path, body, 422, "refund-exceeds-unapplied", headers=desk.west_manager)
    api("POST", "/payments", _cash(shop, shop.client_id, 300, desk.west), 201)
    api("POST", path, body, 422, "refund-exceeds-unapplied", headers=desk.west_manager)  # only 300 in reach
    refunds = api("POST", path, body | {"amount_minor": 300}, 201, headers=desk.west_manager)["refunds"]
    assert [r["amount_minor"] for r in refunds] == [300]
    assert [r["amount_minor"] for r in api("POST", path, body, 201)["refunds"]] == [400]  # the owner draws on Main


def test_sending_a_receipt_needs_the_send_key(client, api, shop):
    """M-05: reading payments is not enough to email a receipt to an address of one's choosing."""
    email, user_id = add_staff(shop.tenant, "front_desk", location_ids=[shop.location_id])
    deny = {"grants": [{"permission_key": "billing.invoice.send", "is_allowed": False}]}
    api("PUT", f"/staff-users/{user_id}/permission-overrides", deny)
    reader = login(client, shop.tenant, email)
    payment = api("POST", "/payments", _cash(shop, shop.client_id, 500), 201)
    assert api("GET", f"/payments/{payment['id']}/receipt", headers=reader)["payment_id"] == payment["id"]
    send = {"channel": "email", "to_email": "anyone@example.com"}
    api("POST", f"/payments/{payment['id']}/receipt-deliveries", send, 403, headers=reader)
    assert api("POST", f"/payments/{payment['id']}/receipt-deliveries", send, 201)["document_kind"] == "receipt"


def test_the_pay_link_refuses_a_key_that_could_steer_a_provider_query(client, shop):
    """M-07: the anonymous pay-link route validates the Idempotency-Key before anything reaches the provider."""
    body = {"token": "not-a-real-token-but-long-enough", "method_token": "tok_card_ok"}
    for bad in ("x' OR status:'succeeded", "has space-in-it", "q" * 256):
        sent = client.post(f"{API}/public/invoice-links/payments", json=body,
                           headers={"X-Tenant-Slug": shop.tenant.slug, "Idempotency-Key": bad})  # fmt: skip
        assert sent.status_code == 422, sent.text
    plain = client.post(f"{API}/public/invoice-links/payments", json=body,
                        headers={"X-Tenant-Slug": shop.tenant.slug, "Idempotency-Key": "plain-key-0001"})  # fmt: skip
    assert plain.status_code != 422  # the same body with a plain key gets as far as the link check
