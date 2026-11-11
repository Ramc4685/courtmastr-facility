"""pos x packages x billing x documents: a package sold at the till (POS-19, PKG-08) on the same invoice as
the retail lines, with the plan's required document still enforced."""

from app.modules.documents.tests.support import sign, template
from app.modules.memberships.tests.support import package_plan
from app.modules.pos.tests.conftest import API, add, complete, pay, start


def test_a_package_and_a_drink_sell_on_one_invoice(client, store):
    plan = package_plan(client, store.owner, store.tenant)  # 100.00, untaxed category
    walk_in = start(store)
    refused = client.post(f"{API}/pos-sales/{walk_in['id']}/lines", headers=store.owner,
                          json={"package_plan_id": plan["id"]})  # fmt: skip
    assert (refused.status_code, refused.json()["code"]) == (422, "client-required")
    client.post(f"{API}/pos-sales/{walk_in['id']}/abandon", headers=store.owner)

    sale = start(store, client_id=store.client_id)
    add(store, sale, sku="0001")
    sale = add(store, sale, package_plan_id=plan["id"])
    line = next(row for row in sale["lines"] if row["line_kind"] == "package")
    assert (line["unit_price_minor"], line["total_minor"], line["fulfilment_id"]) == (10000, 10000, None)
    sale = store.post(f"/pos-sales/{sale['id']}/discounts", {"source": "custom", "discount_pct": "10"})
    assert sale["discount_minor"] == 100  # 10% of the 10.00 drink: a package keeps its plan's price
    assert sale["total_minor"] == 10000 + 900 + 74  # drink 9.00 + 8.25% tax
    changed = client.patch(f"{API}/pos-sales/{sale['id']}/lines/{line['id']}", headers=store.owner,
                           json={"quantity": 2})  # fmt: skip
    assert changed.status_code == 422

    pay(store, sale)
    done = complete(store, sale)
    line = next(row for row in done["lines"] if row["line_kind"] == "package")
    package = client.get(f"{API}/client-packages/{line['fulfilment_id']}", headers=store.owner).json()
    assert (package["sales_channel"], package["sessions_granted_count"], package["status"]) == ("pos", 10, "active")
    invoice = client.get(f"{API}/invoices/{done['invoice_id']}", headers=store.owner).json()
    assert (invoice["total_minor"], invoice["balance_minor"], invoice["status"]) == (done["total_minor"], 0, "paid")
    assert complete(store, sale)["id"] == done["id"]  # a replay sells nothing twice
    owned = client.get(f"{API}/client-packages?client_id={store.client_id}", headers=store.owner).json()["data"]
    assert len(owned) == 1

    back = client.post(f"{API}/pos-sales/{done['id']}/returns", headers=store.owner | {"Idempotency-Key": "return-package-1"},
                       json={"lines": [{"pos_sale_line_id": line["id"], "quantity": 1}], "refund_mode": "cash"})  # fmt: skip
    assert back.status_code == 422  # a sold package is removed from the client's profile, not returned here


def test_the_plans_document_still_gates_the_sale_at_the_till(client, store):
    plan = package_plan(client, store.owner, store.tenant)
    waiver = template(client, store.owner)
    bound = client.put(f"{API}/document-bindings", headers=store.owner,
                       json={"scope_type": "package_plan", "scope_id": plan["id"], "template_id": waiver["id"],
                             "frequency": "every_purchase"})  # fmt: skip
    assert bound.status_code == 200, bound.text
    sale = add(store, start(store, client_id=store.client_id), sku="0001")
    sale = add(store, sale, package_plan_id=plan["id"])
    pay(store, sale)
    stopped = client.post(f"{API}/pos-sales/{sale['id']}/complete", headers=store.owner | {"Idempotency-Key": "complete-gated-1"},
                          json={})  # fmt: skip
    assert (stopped.status_code, stopped.json()["code"]) == (409, "document-required"), stopped.text
    assert client.get(f"{API}/pos-sales/{sale['id']}", headers=store.owner).json()["status"] == "draft"
    # the refusal commits the pending document and nothing else: no item was billed for the drink
    assert client.get(f"{API}/charges?client_id={store.client_id}", headers=store.owner).json()["data"] == []
    document = client.get(f"{API}/client-documents/{stopped.json()['document_id']}", headers=store.owner).json()
    assert sign(client, store.owner, document).status_code == 200
    done = complete(store, sale)
    assert done["status"] == "completed" and done["lines"][1]["fulfilment_id"]
