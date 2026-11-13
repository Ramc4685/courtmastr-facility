"""Catalogue, stock, drawer sessions, equipment rental, returns and the POS reports."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import update

from app.core import clock
from app.core.db.session import tenant_session
from app.modules.pos.models import EquipmentLoan
from app.modules.pos.tests.conftest import API, add, cash_sale, complete, key, pay, start
from conftest import add_staff, login


def _stock(client, store, location_id=None) -> int:
    rows = client.get(f"{API}/products/{store.product_id}/stock", headers=store.owner).json()["data"]
    return next((r["on_hand_count"] for r in rows if r["location_id"] == (location_id or store.location_id)), 0)


def _today():
    return clock.now().astimezone(ZoneInfo("America/Chicago")).date()  # the store's location, not UTC


# --- catalogue ------------------------------------------------------------------------------------------------


def test_catalogue_crud_uniqueness_and_cost_visibility(client, store):
    brand = store.post("/product-brands", {"name": "Acme"})
    supplier = store.post("/product-suppliers", {"name": "Wholesale Co", "email": "orders@example.com"})
    child = store.post("/product-categories", {"name": "Sparkling", "parent_id": store.category_id})
    cycle = client.patch(f"{API}/product-categories/{store.category_id}", headers=store.owner,
                         json={"parent_id": child["id"]})  # fmt: skip
    assert cycle.status_code == 409 and cycle.json()["code"] == "category-cycle"
    dup = client.post(f"{API}/product-brands", headers=store.owner, json={"name": "Acme"})
    assert dup.status_code == 409 and dup.json()["code"] == "already-exists"
    taxed = store.post("/products", {
        "product_category_id": child["id"], "product_brand_id": brand["id"], "product_supplier_id": supplier["id"],
        "name": "Soda", "product_code": "S-1", "sku": "0002", "unit_price_minor": 250, "cost_minor": 100,
        "units_per_sale": 6, "tax_ids": [store.tax_id],
    })  # fmt: skip
    assert taxed["tax_ids"] == [store.tax_id] and taxed["units_per_sale"] == 6
    same_sku = client.post(f"{API}/products", headers=store.owner, json={
        "product_category_id": child["id"], "name": "Other", "product_code": "O-1", "sku": "0002",
        "unit_price_minor": 1})  # fmt: skip
    assert same_sku.status_code == 409
    renamed = client.patch(f"{API}/products/{taxed['id']}", headers=store.owner, json={"name": "Soda 6-pack"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Soda 6-pack"
    by_scan = client.get(f"{API}/products?sku=0002", headers=store.front).json()["data"]
    assert [p["id"] for p in by_scan] == [taxed["id"]] and by_scan[0].get("cost_minor") is None  # cost hidden
    searched = client.get(f"{API}/products?q=soda", headers=store.owner).json()["data"]
    assert searched[0]["cost_minor"] == 100
    reorder = client.post(f"{API}/product-categories/reorder", headers=store.owner,
                          json={"ordered_ids": [store.category_id, store.category_id]})  # fmt: skip
    assert reorder.status_code == 422
    preset = client.post(f"{API}/discount-presets", headers=store.owner,
                         json={"name": "Both", "discount_pct": "5", "discount_minor": 100})  # fmt: skip
    assert preset.status_code == 422
    assert client.post(f"{API}/products", headers=store.front, json={}).status_code in (403, 422)


def test_register_favorites_and_settings_override(client, store):
    favs = client.put(f"{API}/registers/{store.register_id}/favorites", headers=store.owner,
                      json={"product_ids": [store.product_id], "is_favorites_enabled": True}).json()  # fmt: skip
    assert favs["favorite_product_ids"] == [store.product_id] and favs["is_favorites_enabled"]
    tenant_wide = client.get(f"{API}/pos-settings", headers=store.owner).json()
    assert tenant_wide["is_override"] is False
    local = client.put(f"{API}/pos-settings?location_id={store.location_id}", headers=store.owner,
                       json={"is_auto_print_receipt": True}).json()  # fmt: skip
    assert local["is_override"] and local["is_auto_print_receipt"]
    assert client.get(f"{API}/pos-settings", headers=store.owner).json()["is_auto_print_receipt"] is False
    assert (
        client.put(f"{API}/pos-settings", headers=store.front, json={"is_auto_print_receipt": True}).status_code == 403
    )


# --- stock ----------------------------------------------------------------------------------------------------


def test_adjustments_set_counts_transfers_and_reorder(client, store):
    west = store.post("/locations", {"name": "West", "time_zone": "America/Denver", "country_code": "US"})["id"]
    zero = client.post(f"{API}/stock-movements", headers=store.owner, json={
        "product_id": store.product_id, "location_id": store.location_id, "kind": "adjustment", "quantity_delta": 0,
        "reason": "other"})  # fmt: skip
    assert zero.status_code == 422
    store.post("/stock-movements", {"product_id": store.product_id, "location_id": store.location_id,
                                    "kind": "adjustment", "quantity_delta": -1, "reason": "discrepancy",
                                    "comment": "broken bottle"})  # fmt: skip
    assert _stock(client, store) == 4
    store.post("/stock-transfers", {"product_id": store.product_id, "from_location_id": store.location_id,
                                    "to_location_id": west, "quantity": 3})  # fmt: skip
    assert (_stock(client, store), _stock(client, store, west)) == (1, 3)
    short = client.post(f"{API}/stock-transfers", headers=store.owner, json={
        "product_id": store.product_id, "from_location_id": store.location_id, "to_location_id": west,
        "quantity": 5})  # fmt: skip
    assert short.status_code == 409 and short.json()["code"] == "insufficient-stock"
    same = client.post(f"{API}/stock-transfers", headers=store.owner, json={
        "product_id": store.product_id, "from_location_id": west, "to_location_id": west, "quantity": 1})  # fmt: skip
    assert same.status_code == 422
    counted = store.post("/stock-movements", {"product_id": store.product_id, "location_id": west, "kind": "set",
                                              "set_to_count": 7, "reason": "discrepancy"})  # fmt: skip
    assert counted["quantity_delta"] == 4 and counted["resulting_count"] == 7
    moves = client.get(f"{API}/stock-movements?product_id={store.product_id}", headers=store.owner).json()["data"]
    assert {"adjustment", "transfer_out", "transfer_in", "set"} <= {m["kind"] for m in moves}
    below = client.get(f"{API}/products?location_id={store.location_id}&is_below_reorder_level=true",
                       headers=store.owner).json()["data"]  # fmt: skip
    assert [p["id"] for p in below] == [store.product_id]
    reorder = client.get(f"{API}/pos-reports/reorder?location_id={store.location_id}", headers=store.owner).json()
    assert reorder["data"][0]["product_id"] == store.product_id and reorder["data"][0]["on_hand_count"] == 1
    untracked = store.post(
        "/products",
        {
            "product_category_id": store.category_id,
            "name": "Gift wrap",
            "product_code": "G-1",
            "unit_price_minor": 100,
            "is_stock_tracked": False,
        },
    )
    refused = client.post(f"{API}/stock-movements", headers=store.owner, json={
        "product_id": untracked["id"], "location_id": store.location_id, "kind": "adjustment", "quantity_delta": 1,
        "reason": "new_stock"})  # fmt: skip
    assert refused.status_code == 409 and refused.json()["code"] == "product-not-stock-tracked"


# --- drawer ---------------------------------------------------------------------------------------------------


def test_drawer_close_variance_reconcile_and_no_sale(client, store):
    again = client.post(f"{API}/registers/{store.register_id}/drawer-sessions", headers=store.owner,
                        json={"opening_float_minor": 0})  # fmt: skip
    assert again.status_code == 409 and again.json()["code"] == "drawer-already-open"
    done = cash_sale(store)  # 10.83 cash
    no_sale = client.post(f"{API}/registers/{store.register_id}/open-drawer", headers=store.front,
                          json={"reason": "change for a twenty"})  # fmt: skip
    assert no_sale.status_code == 403  # front desk lacks pos.drawer.open_no_sale
    no_sale = client.post(f"{API}/registers/{store.register_id}/open-drawer", headers=store.manager,
                          json={"reason": "change for a twenty"})  # fmt: skip
    assert no_sale.status_code == 204
    early = client.post(f"{API}/drawer-sessions/{store.drawer_id}/reconcile", headers=store.owner, json={})
    assert early.status_code == 409
    draft = pay(store, add(store, start(store), product_id=store.product_id))
    busy = client.post(f"{API}/drawer-sessions/{store.drawer_id}/close", headers=store.owner,
                       json={"counted_cash_minor": 0})  # fmt: skip
    assert busy.status_code == 409 and busy.json()["code"] == "open-draft-sale"
    complete(store, draft)
    expected = 10000 + 2 * done["total_minor"]
    closed = client.post(f"{API}/drawer-sessions/{store.drawer_id}/close", headers=store.front,
                         json={"counted_cash_minor": expected - 150, "note": "short"}).json()  # fmt: skip
    assert closed["status"] == "closed" and closed["expected_cash_minor"] == expected
    assert closed["variance_minor"] == -150
    denied = client.post(f"{API}/drawer-sessions/{store.drawer_id}/reconcile", headers=store.front, json={})
    assert denied.status_code == 403
    reconciled = client.post(f"{API}/drawer-sessions/{store.drawer_id}/reconcile", headers=store.manager,
                             json={"note": "found coins"}).json()  # fmt: skip
    assert reconciled["reconciled_at"] and reconciled["reconcile_note"] == "found coins"
    twice = client.post(f"{API}/drawer-sessions/{store.drawer_id}/reconcile", headers=store.manager, json={})
    assert twice.status_code == 409
    daily = client.get(f"{API}/pos-reports/daily-register?location_id={store.location_id}&on={_today()}",
                       headers=store.owner).json()  # fmt: skip
    row = daily["registers"][0]
    assert row["sale_count"] == 2 and row["drawer_sessions"][0]["variance_minor"] == -150


# --- equipment ------------------------------------------------------------------------------------------------


def _equipment(store, **fields):
    category = store.post("/equipment-categories", {"name": f"Rackets {fields.get('asset_code', 'R')}"})
    return store.post("/equipment-items", {
        "equipment_category_id": category["id"], "location_id": store.location_id, "name": "Racket",
        "asset_code": "R-1", "rental_fee_minor": 500, "rental_days": 1, "return_time": "18:00",
        "late_fee_minor": 300, "replacement_fee_minor": 8000, "unit_count": 2,
    } | fields)  # fmt: skip


def test_equipment_rental_needs_client_and_availability(client, store):
    item = _equipment(store)
    sale = start(store)
    walk_in = client.post(f"{API}/pos-sales/{sale['id']}/lines", headers=store.owner,
                          json={"equipment_item_id": item["id"]})  # fmt: skip
    assert walk_in.status_code == 422 and walk_in.json()["code"] == "client-required"
    client.post(f"{API}/pos-sales/{sale['id']}/abandon", headers=store.owner)
    sale = start(store, client_id=store.client_id)
    too_many = client.post(f"{API}/pos-sales/{sale['id']}/lines", headers=store.owner,
                           json={"equipment_item_id": item["id"], "quantity": 3})  # fmt: skip
    assert too_many.status_code == 409 and too_many.json()["code"] == "equipment-unavailable"
    sale = add(store, sale, equipment_item_id=item["id"])
    assert sale["lines"][0]["line_kind"] == "equipment" and sale["lines"][0]["unit_price_minor"] == 500
    done = complete(store, pay(store, sale))
    loans = client.get(f"{API}/equipment-loans?client_id={store.client_id}", headers=store.owner).json()["data"]
    assert len(loans) == 1 and loans[0]["status"] == "open" and loans[0]["pos_sale_line_id"] == done["lines"][0]["id"]
    assert client.get(f"{API}/equipment-items/{item['id']}", headers=store.owner).json()["available_count"] == 1
    no_return = client.post(f"{API}/pos-sales/{done['id']}/returns", headers=store.owner | {"Idempotency-Key": key()}, json={
        "lines": [{"pos_sale_line_id": done["lines"][0]["id"], "quantity": 1}], "refund_mode": "cash"})  # fmt: skip
    assert no_return.status_code == 422
    moving = client.patch(f"{API}/equipment-items/{item['id']}", headers=store.owner,
                          json={"location_id": store.post("/locations", {"name": "Annex", "time_zone": "UTC",
                                                                         "country_code": "US"})["id"]})  # fmt: skip
    assert moving.status_code == 409 and moving.json()["code"] == "equipment-on-loan"


def test_late_return_with_confirmed_fees_and_lost_units(client, store):
    item = _equipment(store)
    done = complete(store, pay(store, add(store, start(store, client_id=store.client_id),
                                           equipment_item_id=item["id"], quantity=2)))  # fmt: skip
    loan = client.get(f"{API}/equipment-loans?client_id={store.client_id}", headers=store.owner).json()["data"][0]
    assert loan["quantity"] == 2 and done["status"] == "completed"
    with tenant_session(store.tenant.id) as session:  # it fell due three days and an hour ago
        session.execute(update(EquipmentLoan).where(EquipmentLoan.id == loan["id"])
                        .values(due_at=clock.now() - timedelta(days=3, hours=1)))  # fmt: skip
    quote = client.get(f"{API}/equipment-loans/{loan['id']}/return-quote", headers=store.owner).json()
    assert quote["is_late"] and quote["days_late"] == 4 and quote["proposed_late_fee_minor"] == 4 * 300 * 2
    lost_quote = client.get(f"{API}/equipment-loans/{loan['id']}/return-quote?outcome=lost", headers=store.owner).json()
    assert lost_quote["proposed_replacement_fee_minor"] == 8000 * 2
    no_condition = client.post(f"{API}/equipment-loans/{loan['id']}/return", headers=store.owner,
                               json={"outcome": "returned"})  # fmt: skip
    assert no_condition.status_code == 422
    viewer_email, _ = add_staff(store.tenant, "view_only", location_ids=[store.location_id])
    viewer = login(client, store.tenant, viewer_email)
    assert client.post(f"{API}/equipment-loans/{loan['id']}/return", headers=viewer,
                       json={"outcome": "lost"}).status_code == 403  # fmt: skip
    returned = client.post(
        f"{API}/equipment-loans/{loan['id']}/return",
        headers=store.owner,
        json={"outcome": "lost", "late_fee_minor": 1000, "replacement_fee_minor": 12000},
    ).json()
    assert returned["status"] == "lost" and returned["late_fee_charge_id"] and returned["replacement_fee_charge_id"]


def test_returned_damaged_with_fees_posts_uninvoiced_charges(client, store):
    item = _equipment(store, unit_count=1)
    complete(store, pay(store, add(store, start(store, client_id=store.client_id), equipment_item_id=item["id"])))
    loan = client.get(f"{API}/equipment-loans?client_id={store.client_id}", headers=store.owner).json()["data"][0]
    assert loan["is_overdue"] is False
    returned = client.post(f"{API}/equipment-loans/{loan['id']}/return", headers=store.owner, json={
        "outcome": "returned", "return_condition": "damaged", "replacement_fee_minor": 2500, "note": "cracked frame",
    }).json()  # fmt: skip
    assert returned["status"] == "returned" and returned["return_condition"] == "damaged"
    charge = client.get(f"{API}/charges/{returned['replacement_fee_charge_id']}", headers=store.owner).json()
    assert charge["total_minor"] == 2500 and charge["invoice_id"] is None and charge["client_id"] == store.client_id
    again = client.post(f"{API}/equipment-loans/{loan['id']}/return", headers=store.owner,
                        json={"outcome": "returned", "return_condition": "good"})  # fmt: skip
    assert again.status_code == 409
    assert client.get(f"{API}/equipment-items/{item['id']}", headers=store.owner).json()["available_count"] == 1
    lost_item = _equipment(store, asset_code="R-9", unit_count=1)
    complete(store, pay(store, add(store, start(store, client_id=store.client_id), equipment_item_id=lost_item["id"])))
    open_loan = next(loan for loan in client.get(f"{API}/equipment-loans?status=open", headers=store.owner)
                     .json()["data"] if loan["equipment_item_id"] == lost_item["id"])  # fmt: skip
    client.post(f"{API}/equipment-loans/{open_loan['id']}/return", headers=store.owner, json={"outcome": "lost"})
    gone = client.get(f"{API}/equipment-items/{lost_item['id']}", headers=store.owner).json()
    assert gone["is_active"] is False and gone["on_loan_count"] == 0


# --- returns --------------------------------------------------------------------------------------------------


def test_partial_then_full_return_refunds_cash_and_restocks(client, store):
    done = cash_sale(store, quantity=3)  # 3248
    line = done["lines"][0]["id"]
    denied = client.post(f"{API}/pos-sales/{done['id']}/returns", headers=store.front | {"Idempotency-Key": key()}, json={
        "lines": [{"pos_sale_line_id": line, "quantity": 1}], "refund_mode": "cash"})  # fmt: skip
    assert denied.status_code == 403  # refunding money needs billing.refund.create
    over = client.post(f"{API}/pos-sales/{done['id']}/returns", headers=store.owner | {"Idempotency-Key": key()}, json={
        "lines": [{"pos_sale_line_id": line, "quantity": 4}], "refund_mode": "cash"})  # fmt: skip
    assert over.status_code == 422 and over.json()["errors"][0]["code"] == "return-exceeds-sold"
    first = store.post(f"/pos-sales/{done['id']}/returns", {"lines": [{"pos_sale_line_id": line, "quantity": 1}],
                                                            "refund_mode": "cash", "reason": "flat"}, key=key())  # fmt: skip
    assert first["amount_minor"] == 1083 and first["cash_refunded_minor"] == 1083 and _stock(client, store) == 3
    second = store.post(f"/pos-sales/{done['id']}/returns", {
        "lines": [{"pos_sale_line_id": line, "quantity": 2, "is_restocked": False}], "refund_mode": "cash"},
        key=key())  # fmt: skip
    assert first["amount_minor"] + second["amount_minor"] == 3248 and _stock(client, store) == 3
    sale = client.get(f"{API}/pos-sales/{done['id']}", headers=store.owner).json()
    assert sale["return_state"] == "full" and sale["lines"][0]["returned_quantity"] == 3
    invoice = client.get(f"{API}/invoices/{done['invoice_id']}", headers=store.owner).json()
    assert invoice["total_minor"] == 0
    drawer = client.get(f"{API}/drawer-sessions?register_id={store.register_id}", headers=store.owner).json()["data"][0]
    assert drawer["cash_refunds_minor"] == 3248
    report = client.get(f"{API}/pos-reports/returns?from_on={_today()}&to_on={_today()}", headers=store.owner).json()
    assert len(report["data"]) == 2 and sum(r["amount_minor"] for r in report["data"]) == 3248
    void = client.post(
        f"{API}/pos-sales/{done['id']}/void", headers=store.owner | {"Idempotency-Key": key()}, json={"reason": "again"}
    )
    assert void.status_code == 409 and void.json()["code"] == "already-returned"


def test_card_sale_refunds_to_the_card_and_void_returns_everything(client, store):
    sale = add(store, start(store), product_id=store.product_id, quantity=2)
    sale = pay(store, sale, 1000)
    sale = pay(store, sale, tender_type_id=store.card, provider_confirmation_token="tok_card_ok")
    done = complete(store, sale)
    card_payment = next(t["payment_id"] for t in done["tenders"] if t["tender_kind"] == "card")
    voided = client.post(
        f"{API}/pos-sales/{done['id']}/void",
        headers=store.owner | {"Idempotency-Key": key()},
        json={"reason": "wrong items"},
    )
    assert voided.status_code == 201, voided.text
    body = voided.json()
    assert body["amount_minor"] == done["total_minor"] and body["refunded_minor"] == done["total_minor"]
    card = client.get(f"{API}/payments/{card_payment}", headers=store.owner).json()
    assert card["refunded_minor"] == card["amount_minor"]  # newest leg first: the card goes back in full
    assert body["cash_refunded_minor"] == done["total_minor"] - card["amount_minor"]
    assert _stock(client, store) == 5


def test_account_credit_refund_needs_a_client_and_leaves_credit(client, store):
    walk_in = cash_sale(store)
    refused = client.post(f"{API}/pos-sales/{walk_in['id']}/returns", headers=store.manager | {"Idempotency-Key": key()}, json={
        "lines": [{"pos_sale_line_id": walk_in["lines"][0]["id"], "quantity": 1}],
        "refund_mode": "account_credit"})  # fmt: skip
    assert refused.status_code == 422 and refused.json()["errors"][0]["code"] == "client-required"
    member = cash_sale(store, client_id=store.client_id)
    credited = store.post(f"/pos-sales/{member['id']}/returns", {
        "lines": [{"pos_sale_line_id": member["lines"][0]["id"], "quantity": 1}], "refund_mode": "account_credit",
    }, headers=store.manager, key=key())  # fmt: skip
    assert credited["refunded_minor"] == 0 and credited["cash_refunded_minor"] == 0
    payments = client.get(f"{API}/payments?client_id={store.client_id}", headers=store.owner).json()["data"]
    assert sum(p["unapplied_minor"] for p in payments) == member["total_minor"]


def test_coupon_released_when_the_sale_is_fully_returned(client, store):
    store.post("/coupons", {"name": "Once", "code": "ONCE", "starts_at": "2020-01-01T00:00:00Z",
                            "discount_minor": 100, "limit_per_client": 1})  # fmt: skip
    sale = add(store, start(store, client_id=store.client_id), product_id=store.product_id)
    sale = store.post(f"/pos-sales/{sale['id']}/discounts", {"source": "coupon", "coupon_code": "ONCE"})
    done = complete(store, pay(store, sale))
    store.post(f"/pos-sales/{done['id']}/void", {"reason": "mistake"}, key=key())
    reuse = add(store, start(store, client_id=store.client_id), product_id=store.product_id)
    reused = client.post(f"{API}/pos-sales/{reuse['id']}/discounts", headers=store.owner,
                         json={"source": "coupon", "coupon_code": "ONCE"})  # fmt: skip
    assert reused.status_code == 200 and reused.json()["discount_minor"] == 100


# --- reports --------------------------------------------------------------------------------------------------


def test_sales_report_groupings_and_bounds(client, store):
    cash_sale(store, headers=store.front)
    cash_sale(store, quantity=2)
    base = f"{API}/pos-reports/sales?from_on={_today()}&to_on={_today()}"
    by_employee = client.get(f"{base}&group_by=employee", headers=store.owner).json()["data"]
    assert sorted(r["quantity"] for r in by_employee) == [1, 2] and all(r["label"] for r in by_employee)
    by_category = client.get(f"{base}&group_by=category", headers=store.owner).json()["data"]
    assert by_category[0]["label"] == "Drinks" and by_category[0]["quantity"] == 3
    assert by_category[0]["total_minor"] == 1083 + 2165
    for group in ("supplier", "brand", "product", "register"):
        assert client.get(f"{base}&group_by={group}", headers=store.owner).status_code == 200
    bad = client.get(f"{base}&group_by=colour", headers=store.owner)
    assert bad.status_code == 422
    too_long = client.get(f"{API}/pos-reports/sales?group_by=product&from_on=2020-01-01&to_on=2022-01-01",
                          headers=store.owner)  # fmt: skip
    assert too_long.status_code == 422
    viewer_email, _ = add_staff(store.tenant, "view_only", location_ids=[store.location_id])
    assert client.get(f"{base}&group_by=product", headers=login(client, store.tenant, viewer_email)).status_code == 403
    # Owner decisions 2026-11-13, question 14: the reports need reporting.pos.run, which front desk does not hold
    # although it reads sales (pos.sale.read); a manager does.
    desk_email, _ = add_staff(store.tenant, "front_desk", location_ids=[store.location_id])
    desk = login(client, store.tenant, desk_email)
    assert client.get(f"{API}/pos-sales", headers=desk).status_code == 200
    for path in (
        f"{base}&group_by=product",
        f"{API}/pos-reports/daily-register?location_id={store.location_id}&on={_today()}",
        f"{API}/pos-reports/reorder?location_id={store.location_id}",
        f"{API}/pos-reports/returns?from_on={_today()}&to_on={_today()}",
    ):
        assert client.get(path, headers=desk).status_code == 403, path
    manager_email, _ = add_staff(store.tenant, "manager", location_ids=[store.location_id])
    assert client.get(f"{base}&group_by=product", headers=login(client, store.tenant, manager_email)).status_code == 200
