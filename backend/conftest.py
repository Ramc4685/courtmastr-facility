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
PUBLIC_IP = "93.184.215.14"  # a globally routable address the webhook SSRF guard accepts (tests never connect)
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

    # integrations: a key, an endpoint (its URL resolves to a public address without touching DNS), a delivery,
    # an accounting connection with one exported day, and one simulated adapter call.
    from unittest import mock

    from app.modules import integrations
    from app.modules.integrations.models import WebhookDelivery

    api_key = post("/api-keys", {"name": "Partner", "scopes": ["clients.client.read"]})
    with mock.patch("app.modules.integrations.transport.resolve", return_value=[PUBLIC_IP]):
        endpoint = post(
            "/webhook-endpoints", {"url": "https://hooks.invalid/fh", "event_types": ["clients.client.created"]}
        )
    # Paused, so draining the broker in other tests never fans events out to it (failed sends retry with delays).
    assert (
        client.patch(
            f"/api/v1/webhook-endpoints/{endpoint['id']}", headers=headers, json={"status": "paused"}
        ).status_code
        == 200
    )
    connection = post("/external-connections", {"provider": "accounting_file", "location_id": location["id"]})
    post("/accounting-exports", {
        "external_connection_id": connection["id"], "location_id": location["id"], "business_on": "2020-01-01",
    })  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        delivery = WebhookDelivery(
            webhook_endpoint_id=endpoint["id"], event_id=uuid4(), event_type="clients.client.created",
            payload={"type": "clients.client.created", "client_id": person["id"]}, status="delivered",
        )  # fmt: skip
        session.add(delivery)
        integrations.service.video_meetings(session, location["id"]).delete_meeting("populate")
        session.flush()
        delivery_id = str(delivery.id)
    return SimpleNamespace(
        tenant=tenant, headers=headers, location_id=location["id"], role_id=role["id"], staff_user_id=invited["id"],
        session_id=session_id, client_id=person["id"], charge_id=charge["id"], invoice_id=invoice["id"],
        payment_id=payment["id"], revenue_category_id=category_id, api_key_id=api_key["id"],
        webhook_endpoint_id=endpoint["id"], webhook_delivery_id=delivery_id, external_connection_id=connection["id"],
    )  # fmt: skip


@pytest.fixture(scope="session")
def two_tenants():
    """Tenants A and B, each populated in every table: the reusable tenant-isolation fixture."""
    client = TestClient(fastapi_app)
    return populate(client, make_tenant()), populate(client, make_tenant("Asia/Kolkata"))
