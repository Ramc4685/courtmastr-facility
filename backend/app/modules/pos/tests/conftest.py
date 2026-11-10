"""Fixtures for the pos tests: a stocked shop with a register, an open drawer, a client and staff logins."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import billing
from conftest import add_staff, login, new_client

API = "/api/v1"


@pytest.fixture
def store(client, tenant, owner):
    """Location (America/Chicago), a client, an 8.25% sales tax on the Retail category, one product with 5 in
    stock, a register with an open drawer (float 100.00), and the cash and card tender type ids."""

    def post(path: str, body: dict, headers=owner, key: str | None = None, status=(200, 201)):
        response = client.post(f"{API}{path}", json=body, headers=headers | ({"Idempotency-Key": key} if key else {}))
        assert response.status_code in status, response.text
        return response.json()

    location = post("/locations", {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"})["id"]
    person = new_client(client, owner, location, primary_email=f"buyer@{tenant.slug}.example.com")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        tax = billing.service.create_tax(
            session, code="ST", label="Sales tax", rate=Decimal("0.0825"), effective_from_on=date(2020, 1, 1)
        )
        retail = billing.service.create_revenue_category(session, code="RETAIL", label="Retail", tax_ids=[tax.id])
        tax_id, retail_id = str(tax.id), str(retail.id)
    category = post("/product-categories", {"name": "Drinks", "revenue_category_id": retail_id})
    product = post("/products", {
        "product_category_id": category["id"], "name": "Water", "product_code": "W-1", "sku": "0001",
        "unit_price_minor": 1000, "reorder_level": 2, "cost_minor": 400,
    })  # fmt: skip
    post("/stock-movements", {"product_id": product["id"], "location_id": location, "kind": "adjustment",
                              "quantity_delta": 5, "reason": "new_stock"})  # fmt: skip
    register = post("/registers", {"location_id": location, "name": "Desk 1"})
    drawer = post(f"/registers/{register['id']}/drawer-sessions", {"opening_float_minor": 10000})
    tenders = client.get(f"{API}/tender-types", headers=owner).json()
    front_email, front_id = add_staff(tenant, "front_desk", location_ids=[location])
    manager_email, _ = add_staff(tenant, "manager", location_ids=[location])
    return SimpleNamespace(
        tenant=tenant, owner=owner, post=post, location_id=location, client_id=person["id"], tax_id=tax_id,
        retail_id=retail_id, category_id=category["id"], product_id=product["id"], register_id=register["id"],
        drawer_id=drawer["id"], cash=next(t["id"] for t in tenders if t["kind"] == "cash"),
        card=next(t["id"] for t in tenders if t["kind"] == "card"), front=login(client, tenant, front_email),
        front_id=str(front_id), manager=login(client, tenant, manager_email),
    )  # fmt: skip


def key() -> str:
    return f"pos-{uuid4().hex}"


def start(store, headers=None, **body) -> dict:
    return store.post("/pos-sales", {"register_id": store.register_id} | body, headers=headers or store.owner)


def add(store, sale, headers=None, **body) -> dict:
    return store.post(f"/pos-sales/{sale['id']}/lines", body, headers=headers or store.owner)


def pay(store, sale, amount=None, headers=None, tender="payment", **body) -> dict:
    body = {"tender": tender, "amount_minor": amount if amount is not None else sale["remaining_minor"]} | body
    if tender == "payment" and "tender_type_id" not in body and "payment_method_id" not in body:
        body["tender_type_id"] = store.cash
    return store.post(f"/pos-sales/{sale['id']}/tenders", body, headers=headers or store.owner, key=key())


def complete(store, sale, headers=None) -> dict:
    return store.post(f"/pos-sales/{sale['id']}/complete", {}, headers=headers or store.owner, key=key())


def cash_sale(store, quantity=1, headers=None, **sale_body) -> dict:
    sale = start(store, headers, **sale_body)
    sale = add(store, sale, headers, product_id=store.product_id, quantity=quantity)
    sale = pay(store, sale, headers=headers)
    return complete(store, sale, headers)
