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
        identity_id = identity.id
        tax = billing.service.create_tax(
            session, code="ST", label="Sales tax", rate=Decimal("0.0825"), effective_from_on=date(2020, 1, 1)
        )
        category = billing.service.create_revenue_category(session, code="RENT", label="Rentals", tax_ids=[tax.id])
        category_id, tax_id = str(category.id), str(tax.id)

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
    people = _populate_people(client, headers, tenant, location["id"], person["id"])
    documents = _populate_documents(client, headers, tenant, location["id"], person)
    space = _populate_space(client, tenant, headers, post, location["id"], person["id"])
    people |= _populate_memberships(
        client, headers, tenant, location["id"], person["id"], people["kid_id"], category_id,
        space["reservation_type_id"],
    )  # fmt: skip
    space |= _populate_rentals(
        client, headers, post, location["id"], person["id"], space["resource_id"], category_id, tax_id
    )
    space |= _populate_engagement(client, tenant, post, location["id"], person["id"], identity_id)
    return SimpleNamespace(
        tenant=tenant, headers=headers, location_id=location["id"], role_id=role["id"], staff_user_id=invited["id"],
        session_id=session_id, client_id=person["id"], charge_id=charge["id"], invoice_id=invoice["id"],
        payment_id=payment["id"], revenue_category_id=category_id, tax_id=tax_id, **billing_ids, **people, **documents, **space,
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


def _populate_engagement(client, tenant, post, location_id, person_id, identity_id) -> dict:
    """Build module 14: every messaging table, mostly through its own routes."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.modules.engagement.models import DeviceRegistration, InboxItem, ScheduledNotification

    template = post("/message-templates", {"name": "Welcome", "subject": "Hi $first_name", "body_text": "Welcome."})
    everyone = {"sources": [{"kind": "client_ids", "ids": [person_id]}]}
    segment = post("/segments", {"name": "Just Casey", "definition": everyone})
    email_campaign = post("/campaigns", {"location_id": location_id, "name": "News", "subject": "News",
                                         "body_text": "Hello $first_name", "segment_id": segment["id"]})  # fmt: skip
    post(f"/campaigns/{email_campaign['id']}/send", {})
    push = post("/campaigns", {"location_id": location_id, "channel": "push", "name": "Closed", "subject": "Closed",
                               "body_text": "Courts close early today.", "audience": everyone})  # fmt: skip
    post(f"/campaigns/{push['id']}/send", {})
    message = post("/messages", {"client_id": person_id, "subject": "Your booking", "body_text": "See you."})
    suppression = post("/suppressions", {"address": f"bounced@{tenant.slug}.example.com"})
    reminder = post("/reminder-rules", {"location_id": location_id, "first_offset_minutes": 1440})
    route = post("/notification-routes", {"location_id": location_id, "alert_kind": "payment_declined",
                                          "emails": [f"desk@{tenant.slug}.example.com"]})  # fmt: skip
    automation = post("/automation-rules", {"name": "Welcome new", "trigger_event_type": "clients.client.created",
                                            "location_id": location_id,
                                            "message_template_id": template["id"], "delay_minutes": 60})  # fmt: skip
    response = client.put(f"/api/v1/locations/{location_id}/portal-settings", headers=login(client, tenant),
                          json={"is_enabled": True, "is_public": True, "welcome_text": "Welcome"})  # fmt: skip
    assert response.status_code == 200, response.text
    video = post("/videos", {"location_id": location_id, "title": "Warm-up", "url": "https://www.youtube.com/watch?v=abc",
                             "is_published": True})  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        device = DeviceRegistration(identity_id=identity_id, client_id=person_id, location_id=location_id,
                                    platform="ios", push_token=f"tok-{uuid4().hex}")  # fmt: skip
        session.add(device)
        later = clock.now() + timedelta(days=2)
        session.add(ScheduledNotification(
            location_id=location_id, kind="session_reminder", reminder_no=1, subject_type="booking",
            subject_id=uuid4(), client_id=person_id, subject_starts_at=later, send_at=later - timedelta(days=1),
            dedupe_key=f"populate:{uuid4().hex}",
        ))  # fmt: skip
        session.flush()
        inbox_item_id = session.scalar(select(InboxItem.id).where(InboxItem.campaign_id == push["id"]))
        device_id = device.id
    return {
        "message_template_id": template["id"], "segment_id": segment["id"], "campaign_id": email_campaign["id"],
        "message_id": message["id"], "suppression_id": suppression["id"], "reminder_rule_id": reminder["id"],
        "notification_route_id": route["id"], "automation_rule_id": automation["id"], "video_id": video["id"],
        "inbox_item_id": str(inbox_item_id), "device_registration_id": str(device_id),
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


def _populate_memberships(
    client, headers, tenant, location_id, person_id, kid_id, category_id, reservation_type_id
) -> dict:
    """Module 5 tables: a membership plan with a bundled package plan, a sold contract with its schedule, a
    future freeze and suspension, a share and a counted visit; a sold package with a share, and a recurring one
    (series). Every row of memberships and packages for the generated isolation tests."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from app.modules import memberships

    def call(method: str, path: str, body: dict | None = None) -> dict:
        response = client.request(method, f"/api/v1{path}", json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json() if response.content else {}

    today = clock.now().astimezone(ZoneInfo("America/Chicago")).date()
    day = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    pack = {"reservation_type_id": reservation_type_id, "session_mode": "fixed", "fee_basis": "per_package",
            "revenue_category_id": category_id}  # fmt: skip
    package_plan = call("POST", "/package-plans", pack | {
        "name": "Ten lessons", "session_count": 10, "fee_minor": 10000, "validity_count": 6, "validity_unit": "month"})  # fmt: skip
    monthly = call("POST", "/package-plans", pack | {
        "name": "Four a month", "kind": "recurring", "session_count": 4, "fee_minor": 4000, "recurrence_unit": "month",
        "recurrence_interval_count": 1, "recurrence_occurrences_count": 3})  # fmt: skip
    kind = call("POST", "/membership-types", {"name": "Adult", "revenue_category_id": category_id})
    plan = call("POST", "/membership-plans", {
        "membership_type_id": kind["id"], "name": "Monthly", "billing_occurrences_count": 12, "term_fee_minor": 5000,
        "auto_renew_lead_count": 30, "auto_renew_lead_unit": "day"})  # fmt: skip
    call("PUT", f"/membership-plans/{plan['id']}/addons", {"addons": [{"package_plan_id": package_plan["id"]}]})
    call("PATCH", "/membership-settings", {"billing_lead_days": 0})
    call("PATCH", "/package-settings", {"expiry_notice_days": 7})
    sale = {"client_id": person_id, "location_id": location_id}
    contract = call("POST", "/membership-contracts", sale | {"membership_plan_id": plan["id"]})
    url = f"/membership-contracts/{contract['id']}"
    share = call("POST", f"{url}/shares", {"client_id": kid_id})
    freeze = call("POST", f"{url}/freezes", {"start_on": day(40), "end_on": day(50)})
    suspension = call("POST", f"{url}/suspensions", {"start_on": day(100), "end_on": day(110), "fee_minor": 500})
    period = next(p for p in call("GET", f"{url}/billing-schedule") if p["status"] == "scheduled")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        memberships.service.record_visit(session, client_id=person_id, check_in_id=uuid4(), location_id=location_id)
    package = call("POST", "/client-packages", sale | {"package_plan_id": package_plan["id"]})
    package_share = call("POST", f"/client-packages/{package['id']}/shares", {"client_id": kid_id})
    recurring = call("POST", "/client-packages", sale | {"package_plan_id": monthly["id"]})
    return {
        "membership_type_id": kind["id"], "membership_plan_id": plan["id"], "contract_id": contract["id"],
        "membership_share_id": share["id"], "freeze_id": freeze["id"], "suspension_id": suspension["id"],
        "period_id": period["id"], "package_plan_id": package_plan["id"], "package_id": package["id"],
        "package_share_id": package_share["id"], "series_id": recurring["package_series_id"],
    }  # fmt: skip


def _populate_space(client, tenant, headers, post, location_id, client_id) -> dict:
    """Build module 2: a row in every resources, scheduling and programs-slice table. Returns the ids the
    generated isolation tests substitute into paths (`/resources/{resource_id}` needs `resource_id`)."""
    group = post("/resource-groups", {"location_id": location_id, "name": "Courts"})
    court = post("/resources", {"location_id": location_id, "resource_group_id": group["id"], "name": "Court 1"})
    post(
        "/resources",
        {"location_id": location_id, "resource_group_id": group["id"], "name": "Court 1A", "parent_id": court["id"]},
    )
    coach = post(
        "/resources",
        {"location_id": location_id, "resource_group_id": group["id"], "name": "Coach Kim", "kind": "trainer"},
    )
    put = client.put(f"/api/v1/resources/{coach['id']}/links", headers=headers, json={"to_resource_ids": [court["id"]]})
    assert put.status_code == 200, put.text
    window = post(f"/resources/{coach['id']}/availability-windows", {
        "starts_on": "2030-01-01", "weekdays": [1, 3], "start_time": "09:00", "end_time": "12:00",
    })  # fmt: skip
    category = post("/reservation-categories", {"location_id": location_id, "name": "Classes"})
    rtype = post("/reservation-types", {
        "location_id": location_id, "name": "Clinic", "default_capacity": 1, "default_allows_free_booking": True,
        "reservation_category_id": category["id"], "color": "#3366cc",
    })  # fmt: skip
    blackout = post("/blackouts", {
        "location_id": location_id, "name": "New Year", "starts_at": "2031-01-01T06:00:00Z", "ends_at": "2031-01-02T06:00:00Z",
    })  # fmt: skip
    booking = {
        "location_id": location_id, "kind": "session", "reservation_type_id": rtype["id"],
        "starts_at": "2030-03-04T15:00:00Z", "ends_at": "2030-03-04T16:00:00Z",
        "resources": [{"resource_id": coach["id"], "role": "primary"}],
        "recurrence": {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 3},
    }  # fmt: skip
    created = post("/bookings", booking)
    # A pass above 50 occurrences leaves its job handle (booking_series_run); no worker runs in tests.
    long_pass = client.post(
        f"/api/v1/booking-series/{created['booking_series_id']}/rules", headers=headers,
        json={"start_on": "2030-06-01", "start_time": "06:00", "end_time": "07:00",
              "rule": {"pattern": "daily", "range_type": "count", "occurrence_limit": 51}},
    )  # fmt: skip
    assert long_pass.status_code == 202, long_pass.text
    long_pass = long_pass.json()
    seat = created["booking"]["session"]["id"]
    enrollment = post("/enrollments", {"session_id": seat, "client_id": client_id})
    marked = client.put(
        f"/api/v1/sessions/{seat}/attendance", headers=headers,
        json={"marks": [{"enrollment_id": enrollment["id"], "status": "attended"}]},
    )  # fmt: skip
    assert marked.status_code == 200, marked.text
    other = new_client(client, headers, location_id)
    waiting = post("/waitlist-entries", {"session_id": seat, "client_id": other["id"]})
    series = client.get(f"/api/v1/booking-series/{created['booking_series_id']}", headers=headers).json()
    return {
        "resource_group_id": group["id"], "resource_id": court["id"], "trainer_resource_id": coach["id"],
        "availability_window_id": window["id"], "reservation_category_id": category["id"],
        "reservation_type_id": rtype["id"], "blackout_id": blackout["id"], "booking_id": created["booking"]["id"],
        "booking_series_id": created["booking_series_id"], "rule_id": series["rules"][0]["id"],
        "run_id": long_pass["status_url"].rsplit("/", 1)[1], "schedule_session_id": seat,
        "enrollment_id": enrollment["id"], "waitlist_entry_id": waiting["id"],
    }  # fmt: skip


def _populate_rentals(client, headers, post, location_id, client_id, court_id, category_id, tax_id) -> dict:
    """Build module 3: a row in every rentals table (type, rate with tax and rule, a billed rental with a
    party, a plan allowed on the type, its sale and a plan-covered rental)."""
    rtype = post("/rental-types", {
        "location_id": location_id, "name": "Court hire", "revenue_category_id": category_id, "resource_ids": [court_id],
    })  # fmt: skip
    rate = post(f"/rental-types/{rtype['id']}/rates", {
        "name": "Standard", "amount_minor": 4000, "basis": "per_hour", "tax_ids": [tax_id],
        "rules": [{"kind": "rate", "name": "Evening", "start_time": "17:00", "end_time": "24:00", "amount_minor": 5000}],
    })  # fmt: skip
    plan = post("/rental-plans", {
        "location_id": location_id, "name": "Ten hours", "rental_type_id": rtype["id"], "model": "per_hour",
        "quantity": "10", "price_minor": 30000, "revenue_category_id": category_id,
    })  # fmt: skip
    put = client.patch(f"/api/v1/rental-types/{rtype['id']}", headers=headers, json={"rental_plan_ids": [plan["id"]]})
    assert put.status_code == 200, put.text
    other = new_client(client, headers, location_id)
    rental = post("/rentals", {
        "location_id": location_id, "rental_type_id": rtype["id"], "client_id": client_id,
        "parties": [{"client_id": other["id"]}], "resources": [{"resource_id": court_id}],
        "starts_at": "2030-03-05T18:00:00Z", "ends_at": "2030-03-05T19:00:00Z",
        "charge": {"decision": "bill", "rental_rate_id": rate["id"]},
    }, key=f"populate-rental-{uuid4().hex}")  # fmt: skip
    purchase = post(
        "/rental-plan-purchases",
        {"rental_plan_id": plan["id"], "client_id": client_id},
        key=f"populate-plan-{uuid4().hex}",
    )
    post("/rentals", {
        "location_id": location_id, "rental_type_id": rtype["id"], "client_id": client_id,
        "resources": [{"resource_id": court_id}], "starts_at": "2030-03-06T18:00:00Z", "ends_at": "2030-03-06T19:00:00Z",
        "charge": {"decision": "plan", "rental_plan_purchase_id": purchase["id"]},
    }, key=f"populate-covered-{uuid4().hex}")  # fmt: skip
    return {
        "rental_type_id": rtype["id"],
        "rental_rate_id": rate["id"],
        "rental_id": rental["rental"]["id"],
        "rental_plan_id": plan["id"],
        "purchase_id": purchase["id"],
    }


@pytest.fixture(scope="session")
def two_tenants():
    """Tenants A and B, each populated in every table: the reusable tenant-isolation fixture."""
    client = TestClient(fastapi_app)
    return populate(client, make_tenant()), populate(client, make_tenant("Asia/Kolkata"))
