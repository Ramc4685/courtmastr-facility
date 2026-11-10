"""Shared fixtures. Tests run against the real PostgreSQL from Compose, connected as fh_app (never the
owner: that would bypass nothing here, but superuser would), on the facilityhub_test database."""

import os

os.environ["FH_ENV"] = "test"  # must precede every app import: selects config/app.test.yaml

from types import SimpleNamespace  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import clock  # noqa: E402
from app.core.auth import passwords, system_principal  # noqa: E402
from app.core.db.session import tenant_session  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.modules.platform import service, staff  # noqa: E402
from app.modules.platform.models import Identity, StaffUser, UserLocationAccess  # noqa: E402
from app.ports import email  # noqa: E402

PASSWORD = "correct-horse-battery"
WEEK = [{"weekday": d, "opens_time": "08:00", "closes_time": "20:00", "is_closed": False} for d in range(1, 8)]


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    command.upgrade(Config(os.path.join(os.path.dirname(__file__), "alembic.ini")), "head")


@pytest.fixture
def client():
    return TestClient(fastapi_app)


@pytest.fixture
def mailbox():
    """Messages sent through the email port (in-memory adapter), newest last."""
    sent = email._provider.sent
    sent.clear()
    return sent


def link_token(message) -> str:
    return message.body.split("#token=")[1].split()[0].split("&")[0]


def make_tenant(time_zone: str = "America/Chicago") -> SimpleNamespace:
    slug = f"t-{uuid4().hex[:12]}"
    owner_email = f"owner@{slug}.example.com"
    created = service.onboard_tenant(
        name=f"Club {slug}", slug=slug, default_time_zone=time_zone, owner_email=owner_email,
        owner_first_name="Olive", owner_last_name="Owner", owner_password=PASSWORD,
    )  # fmt: skip
    return SimpleNamespace(
        id=created["tenant_id"], slug=slug, owner_email=owner_email, owner_id=created["owner_staff_user_id"]
    )


def add_staff(tenant, role_key: str, *, location_ids=(), all_locations: bool = False, password: str | None = PASSWORD):
    """A staff user with a system role, created straight in the database. Returns (email, staff_user_id)."""
    email_address = f"{role_key}-{uuid4().hex[:8]}@{tenant.slug}.example.com"
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        role = staff.ensure_system_roles(session)[role_key]
        identity = Identity(
            kind="staff", email=email_address, status="active", email_verified_at=clock.now(),
            password_hash=passwords.hash_password(password) if password else None,
        )  # fmt: skip
        session.add(identity)
        session.flush()
        user = StaffUser(
            identity_id=identity.id, role_id=role.id, first_name=role_key.title(), last_name="Tester",
            has_all_location_access=all_locations,
        )  # fmt: skip
        session.add(user)
        session.flush()
        for index, location_id in enumerate(location_ids):
            session.add(UserLocationAccess(staff_user_id=user.id, location_id=location_id, is_primary=index == 0))
        return email_address, user.id


def login(client, tenant, email_address: str | None = None, password: str = PASSWORD, audience: str = "staff") -> dict:
    """Bearer headers for a signed-in principal (mobile-style session, so no CSRF dance)."""
    response = client.post(
        "/api/v1/auth/sign-in",
        headers={"X-Tenant-Slug": tenant.slug},
        json={
            "email": email_address or tenant.owner_email,
            "password": password,
            "client_kind": "mobile",
            "audience": audience,
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def role_id(tenant, system_key: str):
    with tenant_session(tenant.id) as session:
        return staff.ensure_system_roles(session)[system_key].id


def scalar(tenant, stmt):
    with tenant_session(tenant.id) as session:
        return session.scalar(stmt)


@pytest.fixture
def tenant():
    return make_tenant()


@pytest.fixture
def owner(client, tenant):
    return login(client, tenant)


def new_client(client, headers, location_id, **fields) -> dict:
    """A client created through the API. `fields` override the defaults (first_name, primary_email, ...)."""
    body = {"first_name": "Casey", "last_name": f"Client-{uuid4().hex[:6]}", "home_location_id": str(location_id)}
    response = client.post("/api/v1/clients", headers=headers, json=body | fields)
    assert response.status_code == 201, response.text
    return response.json()


def populate(client, tenant) -> SimpleNamespace:
    """Give a tenant at least one row in every tenant-owned table, through the API where one exists."""
    from datetime import date
    from decimal import Decimal

    from app.core.events import ProcessedEvent
    from app.modules import billing, clients

    headers = login(client, tenant)
    location = client.post(
        "/api/v1/locations", headers={**headers, "Idempotency-Key": "populate-1"},
        json={"name": "Main", "time_zone": "America/Chicago", "country_code": "US"},
    ).json()  # fmt: skip
    role = client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": "Desk Lead", "clone_from_role_id": str(role_id(tenant, "manager"))},
    ).json()
    invited = client.post(
        "/api/v1/staff-users", headers=headers,
        json={"email": f"new@{tenant.slug}.example.com", "first_name": "New", "last_name": "Person",
              "role_id": role["id"], "location_ids": [location["id"]], "primary_location_id": location["id"]},
    ).json()  # fmt: skip
    grants = {"grants": [{"permission_key": "platform.audit.export", "is_allowed": True}]}
    assert (
        client.put(
            f"/api/v1/staff-users/{invited['id']}/permission-overrides", headers=headers, json=grants
        ).status_code
        == 200
    )
    with tenant_session(tenant.id) as session:
        session.add(ProcessedEvent(consumer_name="tests.populate", event_id=uuid4()))
    session_id = client.get("/api/v1/auth/session", headers=headers).json()["id"]

    # clients skeleton and billing kernel: a taxed charge, invoiced, paid by card with an overpayment that is
    # then refunded, which touches every billing table including both ledger tables.
    person = new_client(client, headers, location["id"], primary_email=f"casey@{tenant.slug}.example.com")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(kind="client", email=person["primary_email"], status="active")
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, person["id"], identity.id)
        tax = billing.service.create_tax(
            session, code="ST", label="Sales tax", rate=Decimal("0.0825"), effective_from_on=date(2020, 1, 1)
        )
        category = billing.service.create_revenue_category(session, code="RENT", label="Rentals", tax_ids=[tax.id])
        category_id = str(category.id)
        tax_id = str(tax.id)

    def post(path: str, body: dict, key: str | None = None) -> dict:
        response = client.post(f"/api/v1{path}", json=body, headers=headers | ({"Idempotency-Key": key} if key else {}))
        assert response.status_code in (200, 201), response.text
        return response.json()

    charge = post("/charges", {
        "client_id": person["id"], "location_id": location["id"], "description": "Court hire",
        "unit_price_minor": 2000, "revenue_category_id": category_id,
    })  # fmt: skip
    invoice = post("/invoices", {"charge_ids": [charge["id"]]})
    payment = post("/payments", {
        "client_id": person["id"], "location_id": location["id"], "amount_minor": charge["total_minor"] + 500,
        "tender_kind": "card", "method_token": "tok_card_ok", "invoice_id": invoice["id"],
    }, key=f"populate-pay-{uuid4().hex}")  # fmt: skip
    post(
        f"/payments/{payment['id']}/refunds", {"amount_minor": 500, "reason": "Overpaid"}, key=f"populate-{uuid4().hex}"
    )
    billing_ids = _populate_billing(client, headers, post, person, location, category_id, tax_id, payment)
    billing_ids |= _populate_pos(client, headers, post, person, location, category_id, tax_id)
    return SimpleNamespace(
        tenant=tenant, headers=headers, location_id=location["id"], role_id=role["id"], staff_user_id=invited["id"],
        session_id=session_id, client_id=person["id"], charge_id=charge["id"], invoice_id=invoice["id"],
        payment_id=payment["id"], revenue_category_id=category_id, tax_id=tax_id, **billing_ids,
    )  # fmt: skip


def _populate_billing(client, headers, post, person, location, category_id, tax_id, payment) -> dict:
    """Build module 8: one row in every billing table it added, and the ids its routes take."""

    def get(path: str):
        response = client.get(f"/api/v1{path}", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    def key() -> str:
        return f"populate-{uuid4().hex}"

    item = {"client_id": person["id"], "location_id": location["id"], "description": "Clinic", "unit_price_minor": 5000}
    assert client.put("/api/v1/billing-settings", headers=headers, json={}).status_code == 200
    coupon = post("/coupons", {"name": "Welcome", "code": "WELCOME", "starts_at": "2020-01-01T00:00:00Z",
                               "discount_pct": "10"})  # fmt: skip
    method = post(f"/clients/{person['id']}/payment-methods", {"method_token": "tok_card_ok"})  # + provider_customer
    due = post("/charges", item | {"coupon_code": "WELCOME"})  # + coupon_redemption
    autopay_invoice = post("/invoices", {"charge_ids": [due["id"]], "is_autopay": True})  # + payment_schedule
    run = post("/autopay-runs", {"location_id": location["id"]}, key=key())["run"]  # + autopay_attempt
    attempt = get(f"/autopay-attempts?autopay_run_id={run['id']}")["data"][0]
    assert attempt["status"] == "succeeded", attempt
    unpaid = post("/invoices", {"charge_ids": [post("/charges", item)["id"]]})
    post(f"/invoices/{unpaid['id']}/deliveries", {})  # billing_document_delivery + invoice_pay_link
    declined = post("/payments", {  # a decline writes the billing_notice
        "client_id": person["id"], "location_id": location["id"], "amount_minor": 100, "tender_kind": "card",
        "method_token": "tok_card_declined",
    }, key=key())  # fmt: skip
    assert declined["status"] == "failed"
    return {
        "tax_rate_id": get(f"/taxes/{tax_id}")["rates"][0]["id"], "tender_type_id": get("/tender-types")[0]["id"],
        "coupon_id": coupon["id"], "payment_method_id": method["id"], "autopay_run_id": run["id"],
        "autopay_attempt_id": attempt["id"], "provider_account_id": get("/provider-accounts")[0]["id"],
        "payment_allocation_id": payment["allocations"][0]["id"], "unpaid_invoice_id": unpaid["id"],
        "autopay_invoice_id": autopay_invoice["id"],
    }  # fmt: skip


def _populate_pos(client, headers, post, person, location, category_id, tax_id) -> dict:
    """Build module 9: one row in every pos table, and the ids its routes take."""

    def key() -> str:
        return f"populate-{uuid4().hex}"

    assert client.put("/api/v1/pos-settings", headers=headers, json={}).status_code == 200
    category = post("/product-categories", {"name": "Drinks", "revenue_category_id": category_id, "tax_ids": [tax_id]})
    brand = post("/product-brands", {"name": "Fizz"})
    supplier = post("/product-suppliers", {"name": "Wholesale Co"})
    product = post("/products", {
        "product_category_id": category["id"], "product_brand_id": brand["id"], "product_supplier_id": supplier["id"],
        "name": "Water", "product_code": "W-1", "sku": "0001", "unit_price_minor": 250, "reorder_level": 2,
        "is_tax_inherited": False, "tax_ids": [tax_id],
    })  # fmt: skip
    post("/stock-movements", {"product_id": product["id"], "location_id": location["id"], "kind": "adjustment",
                              "quantity_delta": 10, "reason": "new_stock"})  # fmt: skip
    register = post("/registers", {"location_id": location["id"], "name": "Front desk"})
    response = client.put(f"/api/v1/registers/{register['id']}/favorites", headers=headers,
                          json={"product_ids": [product["id"]], "is_favorites_enabled": True})  # fmt: skip
    assert response.status_code == 200, response.text
    drawer = post(f"/registers/{register['id']}/drawer-sessions", {"opening_float_minor": 10000})
    preset = post("/discount-presets", {"name": "Staff", "discount_pct": "10"})
    gear = post("/equipment-categories", {"name": "Rackets"})
    item = post("/equipment-items", {
        "equipment_category_id": gear["id"], "location_id": location["id"], "name": "Racket", "asset_code": "R-1",
        "rental_fee_minor": 500, "late_fee_minor": 100, "replacement_fee_minor": 5000, "unit_count": 3,
    })  # fmt: skip
    sale = post("/pos-sales", {"register_id": register["id"], "client_id": person["id"]})
    sale = post(f"/pos-sales/{sale['id']}/lines", {"sku": "0001", "quantity": 2})
    sale = post(f"/pos-sales/{sale['id']}/lines", {"equipment_item_id": item["id"]})
    sale = post(f"/pos-sales/{sale['id']}/discounts", {"source": "preset", "discount_preset_id": preset["id"]})
    cash = next(t for t in client.get("/api/v1/tender-types", headers=headers).json() if t["kind"] == "cash")
    sale = post(f"/pos-sales/{sale['id']}/tenders", {"tender": "payment", "tender_type_id": cash["id"],
                                                     "amount_minor": sale["total_minor"]}, key=key())  # fmt: skip
    sale = post(f"/pos-sales/{sale['id']}/complete", {}, key=key())
    assert sale["status"] == "completed", sale
    receipt = client.post(
        f"/api/v1/pos-sales/{sale['id']}/receipt-deliveries", headers=headers, json={"channel": "print"}
    )
    assert receipt.status_code == 202, receipt.text
    product_line = next(line for line in sale["lines"] if line["line_kind"] == "product")
    pos_return = post(f"/pos-sales/{sale['id']}/returns", {
        "lines": [{"pos_sale_line_id": product_line["id"], "quantity": 1}], "refund_mode": "cash",
    }, key=key())  # fmt: skip
    loan = client.get(f"/api/v1/equipment-loans?client_id={person['id']}", headers=headers).json()["data"][0]
    return {
        "product_category_id": category["id"], "product_brand_id": brand["id"], "product_supplier_id": supplier["id"],
        "product_id": product["id"], "register_id": register["id"], "drawer_session_id": drawer["id"],
        "discount_preset_id": preset["id"], "equipment_category_id": gear["id"], "equipment_item_id": item["id"],
        "equipment_loan_id": loan["id"], "pos_sale_id": sale["id"], "pos_sale_line_id": product_line["id"],
        "pos_sale_discount_id": sale["discounts"][0]["id"], "pos_sale_tender_id": sale["tenders"][0]["id"],
        "pos_return_id": pos_return["id"],
    }  # fmt: skip


@pytest.fixture(scope="session")
def two_tenants():
    """Tenants A and B, each populated in every table: the reusable tenant-isolation fixture."""
    client = TestClient(fastapi_app)
    return populate(client, make_tenant()), populate(client, make_tenant("Asia/Kolkata"))
