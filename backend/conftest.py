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
    people = _populate_people(client, headers, tenant, location["id"], person["id"])
    documents = _populate_documents(client, headers, tenant, location["id"], person)
    return SimpleNamespace(
        tenant=tenant, headers=headers, location_id=location["id"], role_id=role["id"], staff_user_id=invited["id"],
        session_id=session_id, client_id=person["id"], charge_id=charge["id"], invoice_id=invoice["id"],
        payment_id=payment["id"], revenue_category_id=category_id, **people, **documents,
    )  # fmt: skip


def _populate_people(client, headers, tenant, location_id, person_id) -> dict:
    """Module 4 tables: client configuration, households, activity, merge, consent and a data subject request."""

    def call(method: str, path: str, body: dict | None = None) -> dict:
        response = client.request(method, f"/api/v1{path}", json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json() if response.content else {}

    category = call("POST", "/client-categories", {"name": "Gold"})
    referral = call("POST", "/referral-categories", {"name": "Friend"})
    tag = call("GET", "/tags")[0]
    field = call("POST", "/custom-fields", {"key": "shirt_size", "label": "Shirt size"})
    call("PUT", "/client-field-policies", {"policies": [
        {"field_key": "organization_name", "capture_context": "portal", "requirement": "hidden"}]})  # fmt: skip
    call("GET", "/client-settings")
    call("GET", f"/client-location-settings/{location_id}")
    call("PATCH", f"/clients/{person_id}", {
        "client_category_id": category["id"], "referral_category_id": referral["id"], "tag_ids": [tag["id"]],
        "custom_values": {"shirt_size": "M"}, "phone_mobile": "+15555550100",
    })  # fmt: skip
    call("PUT", f"/clients/{person_id}/emergency-contacts", {"contacts": [{"name": "Robin", "phone": "+15555550101"}]})
    parent_of = next(t for t in call("GET", "/relationship-types") if t["code"] == "parent_of")
    kid = new_client(client, headers, location_id, first_name="Kit")
    relationship = call("POST", f"/clients/{person_id}/relationships",
                        {"other_client_id": kid["id"], "relationship_type_id": parent_of["id"]})  # fmt: skip
    subject = call("POST", "/note-subjects", {"label": "Follow-up"})
    note = call("POST", f"/clients/{person_id}/notes", {"kind": "call", "note_subject_id": subject["id"], "body": "Hi"})
    task = call("POST", "/client-tasks", {"client_id": person_id, "subject_text": "Call back"})
    alert = call("POST", f"/clients/{person_id}/alerts", {"message": "Peanut allergy", "kind": "medical"})
    duplicate = new_client(client, headers, location_id, first_name="Kit", last_name=kid["last_name"])
    call("POST", f"/clients/{kid['id']}/merge", {"merged_client_ids": [duplicate["id"]]})
    call("PUT", f"/clients/{person_id}/communication-preferences", {
        "changes": [{"channel": "sms", "address": "+15555550100", "topic": "sms_marketing", "is_subscribed": True}],
        "basis": "express_written", "note": "Signed the desk form",
    })  # fmt: skip
    request = call("POST", "/data-subject-requests", {"client_id": person_id, "kind": "export"})
    email_id = call("GET", f"/clients/{person_id}")["emails"][0]["id"]
    return {
        "client_category_id": category["id"], "referral_category_id": referral["id"], "tag_id": tag["id"],
        "custom_field_id": field["id"], "relationship_type_id": parent_of["id"], "relationship_id": relationship["id"],
        "note_subject_id": subject["id"], "note_id": note["id"], "task_id": task["id"], "alert_id": alert["id"],
        "request_id": request["id"], "email_id": email_id, "kid_id": kid["id"],
    }  # fmt: skip


def verify_email(tenant, client_id, address: str) -> None:
    from sqlalchemy import update

    from app.modules.clients.models import ClientEmail

    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(
            update(ClientEmail)
            .where(ClientEmail.client_id == client_id, ClientEmail.email == address)
            .values(verified_at=clock.now())
        )


def _populate_documents(client, headers, tenant, location_id, person) -> dict:
    """Module 7 tables: settings, a published template with a binding, an accepted document (acceptance, status,
    rendered file) and a pending one sent by email (delivery)."""

    def call(method: str, path: str, body: dict | None = None) -> dict:
        response = client.request(method, f"/api/v1{path}", json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json() if response.content else {}

    call("PATCH", "/document-settings", {"email_link_ttl_hours": 72})
    template = call("POST", "/document-templates", {"name": "Liability waiver", "is_waiver": True})
    call("PUT", f"/document-templates/{template['id']}/draft",
         {"body_html": "<p>I, {{client.full_name}}, accept the risks.</p>", "acceptance_text": "I agree."})  # fmt: skip
    call("POST", f"/document-templates/{template['id']}/publish")
    binding = call("PUT", "/document-bindings",
                   {"scope_type": "membership_plan", "scope_id": str(uuid4()), "template_id": template["id"]})  # fmt: skip
    call("PATCH", f"/document-location-settings/{location_id}", {"is_consent_required": False})
    issue = {"client_id": person["id"], "location_id": location_id, "template_id": template["id"]}
    signed = call("POST", "/client-documents", issue | {"acceptance_method": "checkbox"})
    call("POST", f"/client-documents/{signed['id']}/acceptances", {"content_sha256": signed["content_sha256"], "signers": [
        {"decision": "accepted", "signer_role": "client", "signer_name": "Casey", "method": "typed_name",
         "typed_signature": "Casey"}]})  # fmt: skip
    verify_email(tenant, person["id"], person["primary_email"])
    pending = call("POST", "/client-documents",
                   issue | {"acceptance_method": "email_link", "recipient_emails": [person["primary_email"]]})  # fmt: skip
    return {"template_id": template["id"], "binding_id": binding["id"], "document_id": signed["id"],
            "pending_document_id": pending["id"]}  # fmt: skip


@pytest.fixture(scope="session")
def two_tenants():
    """Tenants A and B, each populated in every table: the reusable tenant-isolation fixture."""
    client = TestClient(fastapi_app)
    return populate(client, make_tenant()), populate(client, make_tenant("Asia/Kolkata"))
