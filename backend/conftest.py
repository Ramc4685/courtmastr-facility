"""Shared fixtures. Tests run against the real PostgreSQL from Compose, connected as fh_app (never the
owner: that would bypass nothing here, but superuser would), on the facilityhub_test database."""

import os

os.environ["FH_ENV"] = "test"  # must precede every app import: selects config/app.test.yaml

from types import SimpleNamespace  # noqa: E402
from uuid import UUID, uuid4  # noqa: E402

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
from app.ports import email, payment_provider  # noqa: E402

PASSWORD = "correct-horse-battery"
PUBLIC_IP = "93.184.215.14"  # a globally routable address the webhook SSRF guard accepts (tests never connect)
WEEK = [{"weekday": d, "opens_time": "08:00", "closes_time": "20:00", "is_closed": False} for d in range(1, 8)]


@pytest.fixture(scope="session", autouse=True)
def _own_rate_limit_keys():
    """Parallel lanes share one Redis and the tests share documentation IPs: keep each run's buckets apart."""
    from app.core import ratelimit

    ratelimit.PREFIX = f"rl-test-{uuid4().hex[:8]}"


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    command.upgrade(Config(os.path.join(os.path.dirname(__file__), "alembic.ini")), "head")


@pytest.fixture
def client():
    return TestClient(fastapi_app)


@pytest.fixture
def deploy_secrets(monkeypatch):
    """Generated-looking secrets for tests that build settings for a non-dev environment (FH_DATA_KEY and
    FH_OPERATOR_TOKEN must not be dev or example values there)."""
    import base64

    monkeypatch.setenv("FH_DATA_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("FH_OPERATOR_TOKEN", "t" * 40)


@pytest.fixture
def mailbox():
    """Messages sent through the email port (in-memory adapter), newest last."""
    sent = email._provider.sent
    sent.clear()
    return sent


def link_token(message) -> str:
    return message.body.split("#token=")[1].split()[0].split("&")[0]


def make_tenant(time_zone: str = "America/Chicago", mfa_policy: str = "optional") -> SimpleNamespace:
    """A fresh tenant. MFA is optional by default so tests sign in with a password alone; the MFA tests pass
    mfa_policy="privileged" (the product default) or "all"."""
    from app.modules.platform.models import Tenant

    slug = f"t-{uuid4().hex[:12]}"
    owner_email = f"owner@{slug}.example.com"
    created = service.onboard_tenant(
        name=f"Club {slug}", slug=slug, default_time_zone=time_zone, owner_email=owner_email,
        owner_first_name="Olive", owner_last_name="Owner", owner_password=PASSWORD,
    )  # fmt: skip
    with tenant_session(created["tenant_id"]) as session:
        session.get(Tenant, created["tenant_id"]).staff_mfa_policy = mfa_policy
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


def login(
    client, tenant, email_address: str | None = None, password: str = PASSWORD, audience: str = "staff",
    *, elevated: bool = True,
) -> dict:  # fmt: skip
    """Bearer headers for a signed-in principal (mobile-style session, so no CSRF dance). A password sign-in is
    a fresh re-authentication, so the session satisfies `+` keys for 10 minutes; elevated=False clears that."""
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
    token = response.json()["access_token"]
    if not elevated:
        drop_elevation(tenant, token)
    return {"Authorization": f"Bearer {token}"}


def totp(secret: str, steps: int = 0) -> str:
    """The TOTP code for `secret` at the (frozen) clock, `steps` 30-second steps away."""
    import pyotp

    return pyotp.TOTP(secret).at(int(clock.now().timestamp()) + 30 * steps)


def finish_enrolment(client, challenge: dict) -> tuple[dict, str]:
    """Walk a forced enrolment from a 202 sign-in challenge: new secret, first code. (session body, secret)."""
    assert challenge["enrolment_required"], challenge
    started = client.post("/api/v1/auth/mfa/enrolment", json={"mfa_token": challenge["mfa_token"]})
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    done = client.post("/api/v1/auth/mfa/verify", json={"mfa_token": challenge["mfa_token"], "code": totp(secret)})
    assert done.status_code == 200, done.text
    return done.json(), secret


def drop_elevation(tenant, access_token: str) -> None:
    """End a session's step-up window, as if its re-authentication were more than 10 minutes old."""
    from sqlalchemy import update

    from app.core.auth import tokens
    from app.modules.platform.models import AuthSession

    with tenant_session(tenant.id) as session:
        session.execute(
            update(AuthSession)
            .where(AuthSession.access_token_hash == tokens.digest(access_token))
            .values(elevated_until_at=None)
        )


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
    from app.modules.platform.models import FailedJob

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
        session.add(FailedJob(actor_name="tests.populate", queue="default", message_id=str(uuid4()), args=[],
                              error_class="RuntimeError", attempts=1))  # fmt: skip
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
        assert response.status_code in (200, 201, 202), response.text
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
    disputed = post("/payments", {  # + dispute: a settled card payment the payer then disputes
        "client_id": person["id"], "location_id": location["id"], "amount_minor": 300, "tender_kind": "card",
        "method_token": "tok_card_ok",
    }, key=f"populate-{uuid4().hex}")  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        paid = session.get(billing.models.Payment, disputed["id"])
        account = session.get(billing.models.ProviderAccount, paid.provider_account_id)
        ref = payment_provider.get("fake").open_dispute(paid.provider_payment_ref)
        billing_ids["dispute_id"] = str(billing.service.sync_dispute(session, account, ref).id)
    people = _populate_people(client, headers, tenant, location["id"], person["id"])
    people |= _populate_client_files(client, headers, person["id"], people["note_id"])
    documents = _populate_documents(client, headers, tenant, location["id"], person)
    space = _populate_space(client, tenant, headers, post, location["id"], person["id"])
    people |= _populate_memberships(
        client, headers, tenant, location["id"], person["id"], people["kid_id"], category_id,
        space["reservation_type_id"],
    )  # fmt: skip
    space |= _populate_rentals(
        client, headers, post, location["id"], person["id"], space["resource_id"], category_id, tax_id
    )
    space |= _populate_staff(client, headers, post, location["id"], invited["id"], space["trainer_resource_id"])
    space |= _populate_slots(client, headers, post, location["id"], invited["id"], space)
    space |= _populate_assessments(client, headers, post, location["id"], person["id"])
    space |= _populate_share_link(tenant, person["id"])
    space |= _populate_programs(client, headers, post, location["id"], person["id"], space, category_id)
    space |= _populate_access(client, headers, post, tenant, location["id"], person["id"], space)
    space |= _populate_access_rules(client, headers, post, location["id"], person["id"], people["membership_type_id"])
    _populate_pos_desk(client, headers, post, tenant, location["id"], billing_ids["product_category_id"])
    space |= _populate_engagement(client, tenant, post, location["id"], person["id"], identity_id)
    leagues = _populate_leagues(client, headers, post, location["id"], person["id"], space["resource_id"], category_id)
    integration = _populate_integrations(client, headers, tenant, post, location, person)
    reporting = _populate_reporting(post, location["id"])
    reporting |= _populate_imports(client, headers, tenant, location["id"])
    return SimpleNamespace(
        tenant=tenant, headers=headers, location_id=location["id"], role_id=role["id"], staff_user_id=invited["id"],
        session_id=session_id, client_id=person["id"], charge_id=charge["id"], invoice_id=invoice["id"],
        payment_id=payment["id"], revenue_category_id=category_id, tax_id=tax_id, **billing_ids, **people, **documents, **space,
        **leagues,
        **integration, **reporting,
        **_populate_files(tenant),
        **_populate_mfa(tenant),
        **_populate_oidc(tenant),
        **_populate_entitlements(tenant),
        **_populate_t2(client, headers, tenant, location["id"]),
    )  # fmt: skip


def _populate_entitlements(tenant) -> dict:
    """An add-on row that changes nothing (the default plan already has the feature) (Phase 8 T1)."""
    from app.modules.platform import entitlements

    detail = entitlements.add_entitlement(tenant.id, {"key": "branded_app", "source": "addon"})
    return {"entitlement_id": detail["overrides"][0].id}


def _populate_t2(client, headers, tenant, location_id) -> dict:
    """Logos, a support request and a tenant export row (Phase 8 T2)."""
    from sqlalchemy import select

    from app.modules.platform.models import TenantExport

    image = headers | {"Content-Type": "image/png", "X-File-Name": "logo.png"}
    for path in ("/api/v1/branding/logo", f"/api/v1/locations/{location_id}/logo"):
        assert client.put(path, headers=image, content=png_bytes()).status_code == 200
    request = client.post("/api/v1/support-requests", headers=headers, json={"category": "question", "message": "Hi"})
    assert request.status_code == 201, request.text
    with tenant_session(tenant.id) as session:
        owner_id = session.scalar(select(StaffUser.id).order_by(StaffUser.created_at).limit(1))
        export = TenantExport(requested_by_staff_user_id=owner_id, status="failed", error="populate")
        session.add(export)
        session.flush()
        export_id = export.id
    return {"support_request_id": request.json()["id"], "tenant_export_id": export_id}


def _populate_mfa(tenant) -> dict:
    """A staff member with a confirmed TOTP factor and recovery codes (Phase 8 S2)."""
    from sqlalchemy import select

    from app.modules.platform import mfa

    email_address, staff_user_id = add_staff(tenant, "front_desk", all_locations=True)
    with tenant_session(tenant.id) as session:
        identity = session.scalar(select(Identity).where(Identity.email == email_address))
        mfa.start_enrolment(session, identity)
        mfa.factor(session, identity.id).confirmed_at = clock.now()
        mfa.new_recovery_codes(session, identity.id)
    return {"mfa_staff_user_id": staff_user_id}


def _populate_oidc(tenant) -> dict:
    """An OIDC provider and the owner's link to it (Phase 8 S3); straight in the database, no discovery fetch."""
    from sqlalchemy import select

    from app.core import crypto
    from app.modules.platform.models import ExternalLogin, IdentityProviderConfig

    with tenant_session(tenant.id) as session:
        provider = IdentityProviderConfig(
            preset="generic", display_name="Club SSO", issuer_url="https://idp.example.com", client_id="populate",
            client_secret_encrypted=crypto.encrypt("populate-secret", tenant.id),
        )  # fmt: skip
        session.add(provider)
        owner = session.scalar(select(Identity).where(Identity.email == tenant.owner_email))
        session.add(ExternalLogin(identity_id=owner.id, issuer=provider.issuer_url, subject="populate-subject"))
        session.flush()
        return {"identity_provider_id": provider.id}


def _populate_files(tenant) -> dict:
    """A ready stored file, for the signed download route (Phase 8 K1)."""
    from app.modules.platform import files

    with tenant_session(tenant.id) as session:
        row = files.store(session, b"%PDF-1.4 populate", purpose="tests.populate", content_type=files.PDF,
                          uploaded_by=("system", None))  # fmt: skip
    return {"tenant_id": tenant.id, "file_id": row.id}


def _populate_imports(client, headers, tenant, location_id) -> dict:
    """Phase 8 I1: a clients import job with its uploaded file, checked once (rows and an error report)."""
    from app.modules import imports

    job = client.post("/api/v1/import-jobs", headers=headers, json={"kind": "clients", "location_id": location_id})
    job_id = job.json()["id"]
    csv = b"first_name,last_name,email\r\nImport,Person,imported@example.com\r\nNo,Email,not-an-email\r\n"
    url = f"/api/v1/import-jobs/{job_id}/source"
    assert client.put(url, headers=headers | {"Content-Type": "text/csv"}, content=csv).status_code == 200
    assert client.post(f"/api/v1/import-jobs/{job_id}/dry-runs", headers=headers, json={}).status_code == 202
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert imports.service.run_chunk(session, UUID(job_id)) is False
    return {"import_job_id": job_id}


def _populate_reporting(post, location_id) -> dict:
    """Build module 15: a saved report, one run of it, and a (queued) CSV export of that run."""
    params = {"location_ids": [location_id], "from_on": "2020-01-01", "to_on": "2020-12-31"}
    saved = post("/saved-reports", {"report_key": "deposits", "name": "Deposits 2020", "params": params})
    run = post("/report-runs", {"report_key": "deposits", "saved_report_id": saved["id"]})
    export = post("/export-jobs", {"report_run_id": run["id"], "format": "csv"})
    return {"saved_report_id": saved["id"], "report_run_id": run["id"], "export_job_id": export["id"]}


def _populate_share_link(tenant, client_id) -> dict:
    """Phase 11 B (FIT-05): a progress share link. Portal-only to create, so written directly."""
    from datetime import UTC, datetime, timedelta

    from app.modules.assessments.models import ProgressShareLink

    with tenant_session(tenant.id) as session:
        expires = datetime.now(UTC) + timedelta(days=7)
        link = ProgressShareLink(client_id=client_id, token_hash=uuid4().hex, expires_at=expires)
        session.add(link)
        session.flush()
        return {"progress_share_link_id": str(link.id)}


def _populate_assessments(client, headers, post, location_id, client_id) -> dict:
    """Build module 13: a category with one field, a recorded result with its value, and the settings row."""
    template = post("/assessment-templates", {"name": "Body composition"})
    field = post(f"/assessment-templates/{template['id']}/fields",
                 {"name": "Weight", "decimal_places": 1, "unit_label": "kg", "better_direction": "lower"})  # fmt: skip
    result = post("/assessment-results", {"client_id": client_id, "location_id": location_id,
                                          "recorded_at": "2031-01-06T15:00:00Z",
                                          "values": [{"assessment_field_id": field["id"], "value": "80.25"}]})  # fmt: skip
    response = client.patch("/api/v1/assessment-settings", headers=headers, json={"is_portal_sharing_enabled": True})
    assert response.status_code == 200, response.text
    return {"assessment_template_id": template["id"], "assessment_field_id": field["id"],
            "assessment_result_id": result["id"]}  # fmt: skip


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
    from datetime import timedelta

    from app.core import clock

    today = clock.now().date()
    batch = post("/statement-batches", {  # statement_batch + statement_recipient (+ its stored PDF)
        "location_id": location["id"], "period_from_on": str(today - timedelta(days=200)),
        "period_to_on": str(today + timedelta(days=100)),
    })  # fmt: skip
    assert batch["recipient_count"] >= 1, batch
    catalog_item = post("/catalog-items", {"location_id": location["id"], "kind": "one_off", "description": "Locker",
                                           "fee_minor": 1000, "revenue_category_id": category_id})  # fmt: skip
    catalog_sale = post(f"/catalog-items/{catalog_item['id']}/sales", {"client_id": person["id"]}, key=key())
    tag = post("/collections-tags", {"name": "Payment plan"})  # collections_tag + client_collections_profile
    profile = client.put(f"/api/v1/clients/{person['id']}/collections-profile", headers=headers,
                         json={"collections_tag_id": tag["id"]})  # fmt: skip
    assert profile.status_code == 200, profile.text
    return {
        "collections_tag_id": tag["id"],
        "statement_batch_id": batch["id"],
        "tax_rate_id": get(f"/taxes/{tax_id}")["rates"][0]["id"], "tender_type_id": get("/tender-types")[0]["id"],
        "coupon_id": coupon["id"], "payment_method_id": method["id"], "autopay_run_id": run["id"],
        "autopay_attempt_id": attempt["id"], "provider_account_id": get("/provider-accounts")[0]["id"],
        "payment_allocation_id": payment["allocations"][0]["id"], "unpaid_invoice_id": unpaid["id"],
        "autopay_invoice_id": autopay_invoice["id"], "catalog_item_id": catalog_item["id"],
        "catalog_item_sale_id": catalog_sale["id"],
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


def png_bytes(size: tuple[int, int] = (4, 4)) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(out, "PNG")
    return out.getvalue()


def _populate_client_files(client, headers, person_id, note_id) -> dict:
    """Phase 10 chip F: a client photo and one note attachment (client_note_attachment, stored_file)."""
    png = headers | {"Content-Type": "image/png"}
    assert client.put(f"/api/v1/clients/{person_id}/photo", headers=png, content=png_bytes()).status_code == 200
    attachment = client.post(f"/api/v1/client-notes/{note_id}/attachments", headers=png, content=png_bytes())
    assert attachment.status_code == 201, attachment.text
    return {"attachment_id": attachment.json()["id"]}


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


def _populate_slots(client, headers, post, location_id, staff_user_id, space) -> dict:
    """Phase 10 chip A: a slot offer on the coach's window with an extra resource and one taken slot (a session
    with slot_offer_id), and a reservation type restricted to one staff user (reservation_type_grant)."""
    lesson = post("/reservation-types", {"location_id": location_id, "name": "Private lesson", "default_capacity": 1})
    granted = client.put(
        f"/api/v1/reservation-types/{lesson['id']}/grants", headers=headers, json={"staff_user_ids": [staff_user_id]}
    )
    assert granted.status_code == 200, granted.text
    offer = post("/slot-offers", {
        "availability_window_id": space["availability_window_id"], "reservation_type_id": lesson["id"], "slot_min": 30,
        "additional_resource_ids": [space["resource_id"]],
    })  # fmt: skip
    post(f"/slot-offers/{offer['id']}/slots", {"starts_at": "2030-01-02T15:00:00Z"})
    return {"slot_offer_id": offer["id"]}


def _populate_programs(client, headers, post, location_id, client_id, space, category_id) -> dict:
    """Build module 6: a program with a subgroup, a fee, online registration (published), a linked session, a
    registration (charged and invoiced), a group waitlist entry, a basket holding a place, and booking policies."""
    program = post("/program-groups", {
        "location_id": location_id, "name": "Summer Camp", "kind": "camp", "capacity": 1, "waitlist_mode": "manual",
        "revenue_category_id": category_id,
    })  # fmt: skip
    post("/program-groups", {"parent_id": program["id"], "name": "Week 1"})
    fee = post(f"/program-groups/{program['id']}/fees", {"description": "Camp fee", "amount_minor": 15000})
    post("/program-fees", {"location_id": location_id, "description": "Late pickup", "amount_minor": 1000})
    config = client.put(
        f"/api/v1/program-groups/{program['id']}/registration-config", headers=headers,
        json={"is_enabled": True, "payment_requirement": "pay_later_allowed"},
    )  # fmt: skip
    assert config.status_code == 200, config.text
    post(f"/program-groups/{program['id']}/publish", {})
    bookings = client.get(f"/api/v1/bookings?booking_series_id={space['booking_series_id']}", headers=headers).json()
    linked = next(b["session"]["id"] for b in bookings["data"] if b["session"]["id"] != space["schedule_session_id"])
    post(f"/program-groups/{program['id']}/sessions", {"session_ids": [linked]})
    gone = post("/program-groups", {"location_id": location_id, "name": "Old Camp"})
    assert client.delete(f"/api/v1/program-groups/{gone['id']}", headers=headers).status_code == 204
    post("/enrollments", {"program_group_id": program["id"], "client_id": client_id, "program_fee_ids": [fee["id"]]})
    post(
        "/waitlist-entries",
        {"program_group_id": program["id"], "client_id": new_client(client, headers, location_id)["id"],
         "program_fee_id": fee["id"]},
    )  # fmt: skip
    open_program = post("/program-groups", {"location_id": location_id, "name": "Clinic Series"})
    basket = post("/registration-checkouts", {"location_id": location_id})
    basket = post(f"/registration-checkouts/{basket['id']}/items", {
        "program_group_id": open_program["id"], "client_id": new_client(client, headers, location_id)["id"],
    })  # fmt: skip
    policy = {
        "listing_mode": "bookable", "requires_active_membership": False, "visible_range_days": 60,
        "hides_full_sessions": False, "booking_cutoff_minutes": 60, "allows_self_cancel": True,
        "cancel_notice_minutes": 720, "waitlist_mode": "open_offer",
    }  # fmt: skip
    for path, body in (
        (f"/locations/{location_id}/session-booking-policy", policy),
        (f"/reservation-types/{space['reservation_type_id']}/session-booking-policy", {"booking_cutoff_minutes": 0}),
    ):
        put = client.put(f"/api/v1{path}", headers=headers, json=body)
        assert put.status_code == 200, put.text
    return {
        "program_group_id": program["id"], "program_fee_id": fee["id"], "checkout_id": basket["id"],
        "item_id": basket["items"][0]["id"], "linked_session_id": linked, "deleted_program_group_id": gone["id"],
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
    settings = {"is_online_enabled": True, "min_lead_min": 60, "max_length_min": 240, "horizon_days": 60}
    put = client.put(f"/api/v1/locations/{location_id}/rental-portal-settings", headers=headers, json=settings)
    assert put.status_code == 200, put.text  # Phase 11 B (SSP-04)
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


def _populate_staff(client, headers, post, location_id, staff_user_id, trainer_resource_id) -> dict:
    """Build module 12: a row in every staff table. The invited user works an hourly job; the seeded trainer
    resource gets a payee with session pay; the same user sells on commission. A run then pays the hours."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    def put(path: str, body: dict) -> dict:
        response = client.put(f"/api/v1{path}", json=body, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    today = clock.now().astimezone(ZoneInfo("America/Chicago")).date()
    job = post("/job-classifications", {"name": "Front desk"})
    rate = post(f"/staff-users/{staff_user_id}/hourly-rates", {
        "job_classification_id": job["id"], "rate_minor": 1500, "effective_from_on": "2020-01-01"})  # fmt: skip
    put("/staff-settings", {"pay_period": "biweekly"})
    worked = clock.now() - timedelta(days=3)
    entry = post("/time-entries", {
        "staff_user_id": staff_user_id, "location_id": location_id, "job_classification_id": job["id"],
        "clock_in_at": worked.isoformat(), "clock_out_at": (worked + timedelta(hours=2)).isoformat(),
        "edit_reason": "Forgot to punch",
    })  # fmt: skip
    shift = post("/shifts", {"staff_user_id": staff_user_id, "location_id": location_id, "job_classification_id": job["id"],
                             "starts_at": "2030-03-04T14:00:00Z", "ends_at": "2030-03-04T22:00:00Z"})  # fmt: skip
    trainer = post("/staff-payees", {"kind": "trainer", "display_name": "Coach Kim", "location_id": location_id,
                                     "resource_id": trainer_resource_id})  # fmt: skip
    put(f"/staff-payees/{trainer['id']}/pay-rates/default", {"pay_basis": "per_session", "rate_60_minor": 3000})
    put(f"/staff-payees/{trainer['id']}/bonus-rules",
        {"rules": [{"kind": "trained_hours", "threshold_minutes": 600, "amount_minor": 5000}]})  # fmt: skip
    seller = post("/staff-payees", {"kind": "salesperson", "display_name": "New Person", "location_id": location_id,
                                    "staff_user_id": staff_user_id})  # fmt: skip
    put(
        f"/staff-payees/{seller['id']}/commission-rules",
        {"rules": [{"applies_to": "package_sale", "commission_pct": "10"}]},
    )
    run = post("/payroll-runs", {"location_id": location_id, "period_starts_on": (today - timedelta(days=13)).isoformat(),
                                 "period_ends_on": today.isoformat()})  # fmt: skip
    statement = client.get(f"/api/v1/payroll-runs/{run['id']}/statements", headers=headers).json()["data"][0]
    return {
        "job_classification_id": job["id"], "staff_hourly_rate_id": rate["id"], "time_entry_id": entry["id"],
        "shift_id": shift["id"], "staff_payee_id": trainer["id"], "salesperson_payee_id": seller["id"],
        "payroll_run_id": run["id"], "pay_statement_id": statement["id"],
    }  # fmt: skip


def _populate_leagues(client, headers, post, location_id, client_id, court_id, category_id) -> dict:
    """Build module 11: a row in every leagues table. A fee-paying league with four teams (one billed), a
    roster place, an official, a committed schedule run (booked games), a result (standings) with the official
    assigned, and a draft bracket."""
    sport = post("/sports", {"name": "Futsal", "default_game_length_min": 60})
    age = post("/age-groups", {"name": "Adult", "min_age": 18})
    season = post("/seasons", {"name": "Spring 2031", "starts_on": "2031-04-01", "ends_on": "2031-06-30"})
    league = post("/competitions", {
        "location_id": location_id, "kind": "league", "name": "Wednesday Futsal", "sport_id": sport["id"],
        "age_group_id": age["id"], "season_id": season["id"], "starts_on": "2031-04-01", "ends_on": "2031-06-30",
        "is_public": True, "team_fee_minor": 30000, "revenue_category_id": category_id,
    })  # fmt: skip
    cid = league["id"]
    post(f"/competitions/{cid}/activate", {})
    first = post(
        f"/competitions/{cid}/teams",
        {"team": {"name": "Strikers", "captain_client_id": client_id}, "bill_to_client_id": client_id},
    )
    post(f"/competitions/{cid}/teams/generate", {"count": 3})
    roster = post(f"/competition-teams/{first['id']}/roster", {"client_id": client_id, "role": "captain"})
    official = post("/officials", {
        "location_id": location_id, "first_name": "Ref", "last_name": "One", "sport_ids": [sport["id"]],
        "age_group_ids": [age["id"]],
    })  # fmt: skip
    run = post("/schedule-runs", {
        "location_id": location_id, "competition_ids": [cid], "resource_ids": [court_id],
        "time_slots": [{"weekday": 3, "starts_at": "18:00", "ends_at": "22:00", "resource_id": court_id}],
        "starts_on": "2031-04-02", "ends_on": "2031-06-25",
    })  # fmt: skip
    post(f"/schedule-runs/{run['id']}/generate", {})
    post(f"/schedule-runs/{run['id']}/commit", {})
    games = client.get(f"/api/v1/schedule-runs/{run['id']}/games?status=scheduled", headers=headers).json()["data"]
    game = games[0]
    put = client.put(f"/api/v1/games/{game['id']}/officials", headers=headers,
                     json={"assignments": [{"official_id": official["id"]}]})  # fmt: skip
    assert put.status_code == 200, put.text
    put = client.put(f"/api/v1/games/{game['id']}/result", headers=headers,
                     json={"home": {"score": 3}, "away": {"score": 1}})  # fmt: skip
    assert put.status_code == 200, put.text
    standing = client.get(f"/api/v1/competitions/{cid}/standings", headers=headers).json()[0]
    bracket = post(f"/competitions/{cid}/brackets", {"bracket_type": "single_elimination", "seed_source": "seeds"})
    division = client.get(f"/api/v1/competitions/{cid}/divisions", headers=headers).json()[0]
    return {
        "sport_id": sport["id"], "age_group_id": age["id"], "season_id": season["id"], "competition_id": cid,
        "division_id": division["id"], "team_id": first["team_id"], "competition_team_id": first["id"],
        "roster_entry_id": roster["id"], "official_id": official["id"], "schedule_run_id": run["id"],
        "game_id": game["id"], "standing_id": standing["id"], "bracket_id": bracket["id"],
        "bracket_slot_id": bracket["slots"][0]["id"],
    }  # fmt: skip


@pytest.fixture(scope="session")
def two_tenants():
    """Tenants A and B, each populated in every table: the reusable tenant-isolation fixture."""
    client = TestClient(fastapi_app)
    return populate(client, make_tenant()), populate(client, make_tenant("Asia/Kolkata"))


def _populate_access(client, headers, post, tenant, location_id, client_id, space) -> dict:
    """Module 10: a barcode, a staff check-in (its attendance row by hand: no session starts near now), kiosk
    settings and a registered kiosk device."""
    from app.modules.access.models import CheckInAttendance, KioskMatch

    credential = post(f"/clients/{client_id}/credentials", {"kind": "barcode", "value": f"POP-{uuid4().hex[:8]}"})
    checked = post("/check-ins", {"client_id": client_id, "location_id": location_id, "channel": "staff_window"})
    response = client.put(
        f"/api/v1/kiosk-settings?location_id={location_id}", headers=headers, json={"welcome_message": "Hi"}
    )
    assert response.status_code == 200, response.text
    device = post("/kiosk-devices", {"location_id": location_id, "name": "Front door"})
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.add(CheckInAttendance(
            check_in_id=checked["check_in"]["id"], target_id=space["enrollment_id"],
            session_id=space["schedule_session_id"],
        ))  # fmt: skip
        session.add(KioskMatch(
            kiosk_device_id=device["kiosk_device_id"], client_id=client_id, token_hash=f"pop-{uuid4().hex}",
            expires_at=clock.now(),
        ))  # fmt: skip
    # check-in desk (phase 10 chip C): a station and a location's ID card template
    station = post("/check-in-stations", {"location_id": location_id, "name": "Main desk"})
    card = post("/id-card-templates", {"location_id": location_id, "name": "Member card",
                                       "shown_fields": ["name", "membership_number"], "is_default": True})  # fmt: skip
    return {
        "credential_id": credential["id"], "check_in_id": checked["check_in"]["id"],
        "kiosk_device_id": device["kiosk_device_id"], "check_in_station_id": station["id"],
        "id_card_template_id": card["id"],
    }  # fmt: skip


def _populate_pos_desk(client, headers, post, tenant, location_id, product_category_id) -> None:
    """Phase 10 chip E: a location footer and alert email, a product below its reorder level, one digest row."""
    body = {"receipt_footer": "Thanks!", "low_stock_alert_email": "stock@example.com"}
    assert client.put(f"/api/v1/pos-settings?location_id={location_id}", headers=headers, json=body).status_code == 200
    low = post("/products", {"product_category_id": product_category_id, "name": "Grip tape", "product_code": "GT-1", "unit_price_minor": 300,
                             "reorder_level": 5})  # fmt: skip
    post("/stock-movements", {"product_id": low["id"], "location_id": location_id, "kind": "adjustment",
                              "quantity_delta": 1, "reason": "new_stock"})  # fmt: skip
    from app.modules.pos import inventory

    with tenant_session(tenant.id, actor=system_principal("populate")) as session:
        assert inventory.send_low_stock_digests(session) == 1


def _populate_access_rules(client, headers, post, location_id, client_id, membership_type_id) -> dict:
    """Phase 10 chip B: check-in settings, one rule, a client access mode, an always-open schedule mapped to the
    membership type with its own location, and a kiosk exit PIN. None of it changes a decision."""
    put = lambda path, body: client.put(f"/api/v1{path}", headers=headers, json=body)  # noqa: E731
    for path, body in (
        (f"/access-settings?location_id={location_id}", {"staff_early_minutes": 180}),
        (
            f"/access-rules?location_id={location_id}",
            {"rules": [{"condition": "over_daily_limit", "outcome": "allow"}]},
        ),
        (f"/clients/{client_id}/access-mode", {"access_mode": "normal", "reason": "Populate"}),
        (f"/kiosk-settings?location_id={location_id}", {"exit_pin": "246810"}),
    ):
        assert put(path, body).status_code == 200, path
    week = [{"weekday": d, "starts_time": "00:00", "ends_time": "24:00"} for d in range(1, 8)]
    schedule = post("/access-schedules", {"name": "Always open", "ranges": week})
    body = {"access_schedule_id": schedule["id"], "location_ids": [location_id]}
    assert put(f"/membership-types/{membership_type_id}/access", body).status_code == 200
    return {"access_schedule_id": schedule["id"]}


def _populate_integrations(client, headers, tenant, post, location, person) -> dict:
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
    return {
        "api_key_id": api_key["id"], "webhook_endpoint_id": endpoint["id"], "webhook_delivery_id": delivery_id,
        "external_connection_id": connection["id"],
    }  # fmt: skip
