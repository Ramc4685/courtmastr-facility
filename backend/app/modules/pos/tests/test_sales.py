"""The register: cart, discounts, tenders, completion through billing, idempotency, concurrency, receipts."""

import threading
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.main import app as fastapi_app
from app.modules.pos import sales
from app.modules.pos.models import PosSale, StockMovement
from app.modules.pos.tests.conftest import API, add, cash_sale, complete, key, pay, start
from conftest import add_staff, login, scalar


def _stock(client, store, product_id=None) -> int:
    rows = client.get(f"{API}/products/{product_id or store.product_id}/stock", headers=store.owner).json()["data"]
    return next((r["on_hand_count"] for r in rows if r["location_id"] == store.location_id), 0)


def test_walk_in_cash_sale_posts_invoice_and_payment_through_billing(client, store):
    sale = start(store, store.front)
    assert sale["client_id"] is None and sale["status"] == "draft"
    sale = add(store, sale, store.front, sku="0001", quantity=2)  # barcode scan
    sale = add(store, sale, store.front, sku="W-1")  # the product ID also scans; same product merges
    assert len(sale["lines"]) == 1 and sale["lines"][0]["quantity"] == 3
    # 3 x 10.00 = 30.00; tax 8.25% = 2.475 -> 2.48 (half-up once at the line)
    assert (sale["subtotal_minor"], sale["tax_minor"], sale["total_minor"]) == (3000, 248, 3248)
    sale = pay(store, sale, headers=store.front)
    assert sale["remaining_minor"] == 0 and sale["tenders"][0]["status"] == "captured"
    done = complete(store, sale, store.front)
    assert done["status"] == "completed" and done["invoice_number"] and done["drawer_session_id"] == store.drawer_id
    assert done["lines"][0]["charge_id"]
    invoice = client.get(f"{API}/invoices/{done['invoice_id']}", headers=store.owner).json()
    assert invoice["bill_to_client_id"] is None and invoice["balance_minor"] == 0 and invoice["total_minor"] == 3248
    assert _stock(client, store) == 2
    drawer = client.get(f"{API}/drawer-sessions?register_id={store.register_id}", headers=store.owner).json()["data"]
    assert drawer[0]["cash_sales_minor"] == 3248 and drawer[0]["expected_cash_minor"] == 10000 + 3248


def test_completion_is_idempotent_and_replays(client, store):
    sale = start(store)
    sale = pay(store, add(store, sale, product_id=store.product_id))
    path = f"{API}/pos-sales/{sale['id']}/complete"
    same = {"Idempotency-Key": key()}
    first = client.post(path, headers=store.owner | same)
    replay = client.post(path, headers=store.owner | same)
    other_key = client.post(path, headers=store.owner | {"Idempotency-Key": key()})
    assert first.status_code == replay.status_code == other_key.status_code == 200
    assert first.json()["invoice_id"] == replay.json()["invoice_id"] == other_key.json()["invoice_id"]
    assert _stock(client, store) == 4  # one decrement only
    sales_movements = scalar(
        store.tenant, select(func.count()).select_from(StockMovement).where(StockMovement.kind == "sale")
    )
    assert sales_movements == 1
    assert client.post(path, headers=store.owner).status_code == 422  # the key is required


def test_tender_leg_is_idempotent_by_key(client, store):
    sale = add(store, start(store), product_id=store.product_id)
    body = {"tender": "payment", "tender_type_id": store.card, "amount_minor": 500,
            "provider_confirmation_token": "tok_card_ok"}  # fmt: skip
    headers = store.owner | {"Idempotency-Key": key()}
    one = client.post(f"{API}/pos-sales/{sale['id']}/tenders", headers=headers, json=body).json()
    two = client.post(f"{API}/pos-sales/{sale['id']}/tenders", headers=headers, json=body).json()
    assert len(one["tenders"]) == len(two["tenders"]) == 1 and two["tendered_minor"] == 500


def test_split_tender_decline_keeps_earlier_leg(client, store):
    sale = add(store, start(store), product_id=store.product_id, quantity=2)  # 2165
    sale = pay(store, sale, 1000)
    declined = client.post(
        f"{API}/pos-sales/{sale['id']}/tenders", headers=store.owner | {"Idempotency-Key": key()},
        json={"tender": "payment", "tender_type_id": store.card, "amount_minor": 1165,
              "provider_confirmation_token": "tok_card_declined"},
    )  # fmt: skip
    assert declined.status_code == 402 and declined.json()["code"] == "payment-declined"
    sale = client.get(f"{API}/pos-sales/{sale['id']}", headers=store.owner).json()
    assert [t["status"] for t in sale["tenders"]] == ["captured", "failed"] and sale["remaining_minor"] == 1165
    early = client.post(f"{API}/pos-sales/{sale['id']}/complete", headers=store.owner | {"Idempotency-Key": key()})
    assert early.status_code == 409 and early.json()["code"] == "tender-total-mismatch"
    sale = pay(store, sale, tender_type_id=store.card, provider_confirmation_token="tok_card_ok")
    done = complete(store, sale)
    assert done["status"] == "completed" and done["tendered_minor"] == 2165
    too_much = client.post(
        f"{API}/pos-sales/{sale['id']}/tenders", headers=store.owner | {"Idempotency-Key": key()},
        json={"tender": "pay_later", "amount_minor": 1},
    )  # fmt: skip
    assert too_much.status_code == 409  # the sale is closed


def test_unknown_provider_answer_is_pending_then_resolved_by_retry(client, store):
    sale = add(store, start(store), product_id=store.product_id)
    body = {"tender": "payment", "tender_type_id": store.card, "amount_minor": sale["total_minor"],
            "provider_confirmation_token": "tok_card_unknown"}  # fmt: skip
    headers = store.owner | {"Idempotency-Key": key()}
    first = client.post(f"{API}/pos-sales/{sale['id']}/tenders", headers=headers, json=body)
    assert first.status_code == 503 and first.json()["code"] == "provider-unavailable"
    pending = client.get(f"{API}/pos-sales/{sale['id']}", headers=store.owner).json()
    assert pending["tenders"][0]["status"] == "pending"
    blocked = client.post(f"{API}/pos-sales/{sale['id']}/complete", headers=store.owner | {"Idempotency-Key": key()})
    assert blocked.status_code == 409
    retry = client.post(f"{API}/pos-sales/{sale['id']}/tenders", headers=headers, json=body)
    assert retry.status_code == 200  # same key: the provider is asked again and the charge did go through
    assert [t["status"] for t in retry.json()["tenders"]] == ["captured"] and retry.json()["remaining_minor"] == 0
    assert complete(store, retry.json())["status"] == "completed"


def test_pay_later_and_account_credit_need_a_client(client, store):
    sale = add(store, start(store), product_id=store.product_id)
    for tender in ("pay_later", "account_credit"):
        response = client.post(
            f"{API}/pos-sales/{sale['id']}/tenders", headers=store.owner | {"Idempotency-Key": key()},
            json={"tender": tender, "amount_minor": 100},
        )  # fmt: skip
        assert response.status_code == 422 and response.json()["code"] == "client-required"
    sale = client.patch(f"{API}/pos-sales/{sale['id']}", headers=store.owner,
                        json={"version": sale["version"], "client_id": store.client_id}).json()  # fmt: skip
    no_credit = client.post(
        f"{API}/pos-sales/{sale['id']}/tenders", headers=store.owner | {"Idempotency-Key": key()},
        json={"tender": "account_credit", "amount_minor": 100},
    )  # fmt: skip
    assert no_credit.status_code == 422 and no_credit.json()["code"] == "insufficient-credit"
    sale = pay(store, sale, 500)
    sale = pay(store, sale, tender="pay_later")
    done = complete(store, sale)
    invoice = client.get(f"{API}/invoices/{done['invoice_id']}", headers=store.owner).json()
    assert invoice["bill_to_client_id"] == store.client_id and invoice["balance_minor"] == done["total_minor"] - 500


def test_account_credit_leg_spends_existing_credit(client, store):
    paid = store.post("/payments", {"client_id": store.client_id, "location_id": store.location_id,
                                    "amount_minor": 5000, "tender_kind": "cash"}, key=key())  # fmt: skip
    assert paid["unapplied_minor"] == 5000
    sale = add(store, start(store, client_id=store.client_id), product_id=store.product_id)
    sale = pay(store, sale, tender="account_credit")
    done = complete(store, sale)
    invoice = client.get(f"{API}/invoices/{done['invoice_id']}", headers=store.owner).json()
    assert invoice["balance_minor"] == 0
    payment = client.get(f"{API}/payments/{paid['id']}", headers=store.owner).json()
    assert payment["unapplied_minor"] == 5000 - done["total_minor"]


def test_price_override_needs_permission_and_shows_on_receipt(client, store):
    sale = add(store, start(store, store.front), store.front, product_id=store.product_id)
    line = sale["lines"][0]
    denied = client.patch(f"{API}/pos-sales/{sale['id']}/lines/{line['id']}", headers=store.front,
                          json={"unit_price_minor": 800})  # fmt: skip
    assert denied.status_code == 403
    quantity = client.patch(f"{API}/pos-sales/{sale['id']}/lines/{line['id']}", headers=store.front,
                            json={"quantity": 2})  # fmt: skip
    assert quantity.status_code == 200 and quantity.json()["lines"][0]["quantity"] == 2
    sale = client.patch(f"{API}/pos-sales/{sale['id']}/lines/{line['id']}", headers=store.manager,
                        json={"unit_price_minor": 800}).json()  # fmt: skip
    assert sale["lines"][0]["price_overridden_by_staff_user_id"] and sale["subtotal_minor"] == 1600
    done = complete(store, pay(store, sale))
    receipt = client.get(f"{API}/pos-sales/{done['id']}/receipt", headers=store.owner).json()
    assert receipt["lines"][0]["override_minor"] == 400 and receipt["lines"][0]["list_unit_price_minor"] == 1000
    assert "Water" in receipt["html"]


def test_discounts_preset_custom_and_line_scope(client, store):
    second = store.post("/products", {"product_category_id": store.category_id, "name": "Juice", "product_code": "J-1",
                                      "unit_price_minor": 2000, "is_stock_tracked": False})  # fmt: skip
    preset = store.post("/discount-presets", {"name": "Ten", "discount_pct": "10"})
    sale = add(store, start(store, store.front), store.front, product_id=store.product_id)
    sale = add(store, sale, store.front, product_id=second["id"])
    juice = next(line["id"] for line in sale["lines"] if line["product_id"] == second["id"])
    sale = store.post(f"/pos-sales/{sale['id']}/discounts", {"source": "preset", "discount_preset_id": preset["id"],
                                                             "scope": "lines", "line_ids": [juice]},
                      headers=store.front)  # fmt: skip
    assert sale["discount_minor"] == 200 and sale["discounts"][0]["line_ids"] == [juice]
    custom = client.post(f"{API}/pos-sales/{sale['id']}/discounts", headers=store.front,
                         json={"source": "custom", "discount_minor": 100})  # fmt: skip
    assert custom.status_code == 403  # custom needs billing.discount.apply_custom
    too_big = client.post(f"{API}/pos-sales/{sale['id']}/discounts", headers=store.manager,
                          json={"source": "custom", "discount_minor": 99999})  # fmt: skip
    assert too_big.status_code == 422 and too_big.json()["code"] == "discount-exceeds-total"
    sale = store.post(f"/pos-sales/{sale['id']}/discounts", {"source": "custom", "discount_minor": 280},
                      headers=store.manager)  # fmt: skip
    # 1000 + 2000 - 200 (10% juice) - 280 spread 1000:1800 -> 100 / 180
    assert sale["discount_minor"] == 480
    nets = sorted(line["net_minor"] for line in sale["lines"])
    assert nets == [900, 1620]
    removed = client.delete(f"{API}/pos-sales/{sale['id']}/discounts/{sale['discounts'][-1]['id']}",
                            headers=store.front)  # fmt: skip
    assert removed.status_code == 204
    done = complete(store, pay(store, client.get(f"{API}/pos-sales/{sale['id']}", headers=store.owner).json()))
    charges = client.get(f"{API}/charges?invoice_id={done['invoice_id']}", headers=store.owner).json()["data"]
    assert sum(c["discount_minor"] for c in charges) == 200


def test_product_default_discount_applies_automatically(client, store):
    product = store.post("/products", {"product_category_id": store.category_id, "name": "Promo", "product_code": "P-1",
                                       "unit_price_minor": 1000, "default_discount_pct": "25",
                                       "is_stock_tracked": False})  # fmt: skip
    sale = add(store, start(store), product_id=product["id"])
    assert sale["discount_minor"] == 250 and sale["discounts"][0]["source"] == "product_default"
    blocked = client.delete(f"{API}/pos-sales/{sale['id']}/discounts/{sale['discounts'][0]['id']}", headers=store.owner)
    assert blocked.status_code == 409


def test_coupon_applies_last_and_is_redeemed_at_completion(client, store):
    store.post("/coupons", {"name": "Five off", "code": "FIVE", "starts_at": "2020-01-01T00:00:00Z",
                            "discount_minor": 500})  # fmt: skip
    sale = add(store, start(store), product_id=store.product_id, quantity=2)
    bad = client.post(f"{API}/pos-sales/{sale['id']}/discounts", headers=store.owner,
                      json={"source": "coupon", "coupon_code": "NOPE"})  # fmt: skip
    assert bad.status_code == 422 and bad.json()["code"] == "coupon-not-found"
    sale = store.post(f"/pos-sales/{sale['id']}/discounts", {"source": "coupon", "coupon_code": "five"})
    assert sale["discount_minor"] == 500 and sale["coupon_code"] == "five"
    again = client.post(f"{API}/pos-sales/{sale['id']}/discounts", headers=store.owner,
                        json={"source": "coupon", "coupon_code": "FIVE"})  # fmt: skip
    assert again.status_code == 409 and again.json()["code"] == "coupon-already-applied"
    done = complete(store, pay(store, sale))
    coupon = client.get(f"{API}/coupons?q=FIVE", headers=store.owner).json()["data"][0]
    redemptions = client.get(f"{API}/coupons/{coupon['id']}/redemptions", headers=store.owner).json()
    assert len(redemptions) == 1 and redemptions[0]["discount_minor"] == 500
    today = clock.now().date()
    report = client.get(f"{API}/pos-reports/sales?group_by=coupon&from_on={today - timedelta(days=1)}"
                        f"&to_on={today + timedelta(days=1)}", headers=store.owner).json()  # fmt: skip
    assert report["data"][0]["coupon_discount_minor"] == 500 and report["data"][0]["total_minor"] == done["total_minor"]


def test_stock_guard_and_negative_setting(client, store):
    sale = start(store)
    over = client.post(f"{API}/pos-sales/{sale['id']}/lines", headers=store.owner,
                       json={"product_id": store.product_id, "quantity": 6})  # fmt: skip
    assert over.status_code == 409 and over.json()["code"] == "insufficient-stock"
    client.put(f"{API}/pos-settings?location_id={store.location_id}", headers=store.owner,
               json={"is_negative_stock_allowed": True})  # fmt: skip
    sale = add(store, sale, product_id=store.product_id, quantity=7)
    complete(store, pay(store, sale))
    assert _stock(client, store) == -2


def _ready_sale(store, client_obj) -> dict:
    sale = add(store, start(store), product_id=store.product_id)
    return pay(store, sale)


def test_concurrent_sales_of_the_last_unit_never_go_negative(client, store):
    """Two registers each hold a paid cart for the last unit; completing both at once sells it once."""
    store.post("/stock-movements", {"product_id": store.product_id, "location_id": store.location_id, "kind": "set",
                                    "set_to_count": 1, "reason": "discrepancy"})  # fmt: skip
    second = store.post("/registers", {"location_id": store.location_id, "name": "Desk 2"})
    store.post(f"/registers/{second['id']}/drawer-sessions", {"opening_float_minor": 0})
    one = pay(store, add(store, start(store), product_id=store.product_id))
    two = pay(store, add(store, start(store, register_id=second["id"]), product_id=store.product_id))
    barrier, results = threading.Barrier(2), {}

    def finish(sale):
        with TestClient(fastapi_app) as own:
            barrier.wait()
            response = own.post(f"{API}/pos-sales/{sale['id']}/complete",
                                headers=store.owner | {"Idempotency-Key": key()})  # fmt: skip
            results[sale["id"]] = (response.status_code, response.json().get("code"))

    threads = [threading.Thread(target=finish, args=(sale,)) for sale in (one, two)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(code for code, _ in results.values()) == [200, 409]
    assert "insufficient-stock" in {c for _, c in results.values()}
    assert _stock(client, store) == 0
    loser = next(sid for sid, (code, _) in results.items() if code == 409)
    assert client.get(f"{API}/pos-sales/{loser}", headers=store.owner).json()["status"] == "draft"


def test_concurrent_sales_go_negative_when_allowed(client, store):
    client.put(f"{API}/pos-settings?location_id={store.location_id}", headers=store.owner,
               json={"is_negative_stock_allowed": True})  # fmt: skip
    store.post("/stock-movements", {"product_id": store.product_id, "location_id": store.location_id, "kind": "set",
                                    "set_to_count": 1, "reason": "discrepancy"})  # fmt: skip
    second = store.post("/registers", {"location_id": store.location_id, "name": "Desk 2"})
    store.post(f"/registers/{second['id']}/drawer-sessions", {"opening_float_minor": 0})
    one = pay(store, add(store, start(store), product_id=store.product_id))
    two = pay(store, add(store, start(store, register_id=second["id"]), product_id=store.product_id))
    barrier, codes = threading.Barrier(2), []

    def finish(sale):
        with TestClient(fastapi_app) as own:
            barrier.wait()
            codes.append(own.post(f"{API}/pos-sales/{sale['id']}/complete",
                                  headers=store.owner | {"Idempotency-Key": key()}).status_code)  # fmt: skip

    threads = [threading.Thread(target=finish, args=(sale,)) for sale in (one, two)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert codes == [200, 200] and _stock(client, store) == -1


def test_cart_rules(client, store):
    sale = start(store)
    duplicate = client.post(f"{API}/pos-sales", headers=store.owner, json={"register_id": store.register_id})
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "draft-sale-exists"
    both = client.post(f"{API}/pos-sales/{sale['id']}/lines", headers=store.owner,
                       json={"product_id": store.product_id, "sku": "0001"})  # fmt: skip
    assert both.status_code == 422
    unknown = client.post(f"{API}/pos-sales/{sale['id']}/lines", headers=store.owner, json={"sku": "nope"})
    assert unknown.status_code == 422 and unknown.json()["code"] == "product-not-found"
    empty = client.post(f"{API}/pos-sales/{sale['id']}/complete", headers=store.owner | {"Idempotency-Key": key()})
    assert empty.status_code == 422
    stale = client.patch(f"{API}/pos-sales/{sale['id']}", headers=store.owner, json={"version": 999, "note": "x"})
    assert stale.status_code == 409 and stale.json()["code"] == "version-conflict"
    sale = add(store, sale, product_id=store.product_id)
    removed = client.delete(f"{API}/pos-sales/{sale['id']}/lines/{sale['lines'][0]['id']}", headers=store.owner)
    assert removed.status_code == 204
    sale = pay(store, add(store, sale, product_id=store.product_id))
    refused = client.post(f"{API}/pos-sales/{sale['id']}/abandon", headers=store.owner)
    assert refused.status_code == 409 and refused.json()["code"] == "captured-tenders-exist"
    detach = client.patch(f"{API}/pos-sales/{sale['id']}", headers=store.owner,
                          json={"version": sale["version"], "client_id": store.client_id})  # fmt: skip
    assert detach.status_code == 409
    sale = client.delete(f"{API}/pos-sales/{sale['id']}/tenders/{sale['tenders'][0]['id']}", headers=store.owner).json()
    assert sale["tenders"][0]["status"] == "removed" and sale["remaining_minor"] == sale["total_minor"]
    abandoned = client.post(f"{API}/pos-sales/{sale['id']}/abandon", headers=store.owner)
    assert abandoned.status_code == 200 and abandoned.json()["status"] == "abandoned"
    assert start(store)["status"] == "draft"  # the register is free again


def test_removing_a_card_leg_refunds_it(client, store):
    sale = add(store, start(store), product_id=store.product_id)
    sale = pay(store, sale, tender_type_id=store.card, provider_confirmation_token="tok_card_ok")
    payment_id = sale["tenders"][0]["payment_id"]
    denied = client.delete(f"{API}/pos-sales/{sale['id']}/tenders/{sale['tenders'][0]['id']}", headers=store.front)
    assert denied.status_code == 403  # refunding needs billing.refund.create
    sale = client.delete(f"{API}/pos-sales/{sale['id']}/tenders/{sale['tenders'][0]['id']}", headers=store.owner).json()
    assert sale["tenders"][0]["status"] == "removed"
    payment = client.get(f"{API}/payments/{payment_id}", headers=store.owner).json()
    assert payment["refunded_minor"] == payment["amount_minor"]


def test_register_session_and_drawer_requirement(client, store):
    session = client.get(f"{API}/registers/{store.register_id}/session", headers=store.front).json()
    assert session["register"]["id"] == store.register_id and session["drawer_session"]["id"] == store.drawer_id
    assert session["can_override_price"] is False and session["draft_sale_id"] is None
    assert {t["kind"] for t in session["tender_types"]} >= {"cash", "card"}
    managed = client.get(f"{API}/registers/{store.register_id}/session", headers=store.manager).json()
    assert managed["can_override_price"] and managed["can_apply_custom_discount"]
    other = store.post("/registers", {"location_id": store.location_id, "name": "No drawer"})
    client.put(f"{API}/pos-settings", headers=store.owner, json={"is_drawer_session_required": True})
    needs = client.post(f"{API}/pos-sales", headers=store.owner, json={"register_id": other["id"]})
    assert needs.status_code == 409 and needs.json()["code"] == "drawer-session-required"


def test_network_allow_list_guards_the_register(client, store):
    bad = client.put(f"{API}/pos-settings?location_id={store.location_id}", headers=store.owner,
                     json={"allowed_networks": ["not-an-ip"]})  # fmt: skip
    assert bad.status_code == 422
    settings = client.put(f"{API}/pos-settings?location_id={store.location_id}", headers=store.owner,
                          json={"allowed_networks": ["10.0.0.0/8"]}).json()  # fmt: skip
    assert settings["allowed_networks"] == ["10.0.0.0/8"] and settings["is_override"]
    blocked = client.get(f"{API}/registers/{store.register_id}/session", headers=store.owner)
    assert blocked.status_code == 403 and blocked.json()["code"] == "network-not-allowed"
    assert (
        client.post(f"{API}/pos-sales", headers=store.owner, json={"register_id": store.register_id}).status_code == 403
    )
    client.put(f"{API}/pos-settings?location_id={store.location_id}", headers=store.owner,
               json={"allowed_networks": []})  # fmt: skip
    assert client.get(f"{API}/registers/{store.register_id}/session", headers=store.owner).status_code == 200


def test_receipt_print_email_footer_and_resend_permission(client, store, mailbox):
    client.put(f"{API}/billing-settings", headers=store.owner, json={"receipt_footer": "Thanks for visiting"})
    done = cash_sale(store, headers=store.front)
    receipt = client.get(f"{API}/pos-sales/{done['id']}/receipt", headers=store.front).json()
    assert receipt["footer"] == "Thanks for visiting" and receipt["header"]["number"] == done["invoice_number"]
    printed = client.post(f"{API}/pos-sales/{done['id']}/receipt-deliveries", headers=store.front,
                          json={"channel": "print"})  # fmt: skip
    assert printed.status_code == 202 and printed.json()["status"] == "sent"
    emailed = client.post(f"{API}/pos-sales/{done['id']}/receipt-deliveries", headers=store.front,
                          json={"channel": "email", "to_email": "walkin@example.com"})  # fmt: skip
    assert emailed.status_code == 202
    assert mailbox[-1].to == "walkin@example.com" and "Thanks for visiting" in mailbox[-1].body
    no_address = client.post(f"{API}/pos-sales/{done['id']}/receipt-deliveries", headers=store.front,
                             json={"channel": "email"})  # fmt: skip
    assert no_address.status_code == 422
    other_email, _ = add_staff(store.tenant, "view_only", location_ids=[store.location_id])
    other = login(client, store.tenant, other_email)
    resend = client.post(f"{API}/pos-sales/{done['id']}/receipt-deliveries", headers=other, json={"channel": "print"})
    assert resend.status_code == 403  # not the cashier and no pos.receipt.resend
    client.put(f"{API}/pos-settings", headers=store.owner, json={"is_email_receipt_enabled": False})
    off = client.post(f"{API}/pos-sales/{done['id']}/receipt-deliveries", headers=store.owner,
                      json={"channel": "email", "to_email": "x@example.com"})  # fmt: skip
    assert off.status_code == 409 and off.json()["code"] == "email-receipt-disabled"
    draft = start(store)
    assert client.get(f"{API}/pos-sales/{draft['id']}/receipt", headers=store.owner).status_code == 409


def test_history_search_and_permissions(client, store):
    done = cash_sale(store, client_id=store.client_id)
    by_number = client.get(f"{API}/pos-sales?invoice_number={done['invoice_number']}", headers=store.owner).json()
    assert [s["id"] for s in by_number["data"]] == [done["id"]]
    by_client = client.get(f"{API}/pos-sales?client_id={store.client_id}", headers=store.front).json()
    assert by_client["data"][0]["id"] == done["id"]
    viewer_email, _ = add_staff(store.tenant, "view_only", location_ids=[store.location_id])
    viewer = login(client, store.tenant, viewer_email)
    assert client.post(f"{API}/pos-sales", headers=viewer, json={"register_id": store.register_id}).status_code == 403
    west = store.post("/locations", {"name": "West", "time_zone": "UTC", "country_code": "US"})["id"]
    west_email, _ = add_staff(store.tenant, "manager", location_ids=[west])
    west_manager = login(client, store.tenant, west_email)
    assert client.get(f"{API}/pos-sales/{done['id']}", headers=west_manager).status_code == 404
    assert client.get(f"{API}/registers/{store.register_id}/session", headers=west_manager).status_code == 404


def test_abandon_stale_drafts_skips_drafts_with_money(client, store):
    idle = add(store, start(store), product_id=store.product_id)
    second = store.post("/registers", {"location_id": store.location_id, "name": "Desk 2"})
    store.post(f"/registers/{second['id']}/drawer-sessions", {"opening_float_minor": 0})
    paid = pay(store, add(store, start(store, register_id=second["id"]), product_id=store.product_id))
    with tenant_session(store.tenant.id, actor=system_principal("tests")) as session:
        assert sales.abandon_stale_drafts(session, idle=timedelta(0)) == 1
    with tenant_session(store.tenant.id) as session:
        assert session.get(PosSale, idle["id"]).status == "abandoned"
        assert session.get(PosSale, paid["id"]).status == "draft"
    with tenant_session(store.tenant.id, actor=system_principal("tests")) as session:
        assert sales.abandon_stale_drafts(session, idle=timedelta(hours=1)) == 0
