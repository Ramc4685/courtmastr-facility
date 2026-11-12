"""Tenant isolation, proven through raw SQL as fh_app and through the API (definition of done).

`two_tenants` gives A and B a row in every tenant-owned table; a table added later joins these generated
tests automatically and fails until the fixture populates it.
"""

import re
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import app_engine, tenant_session
from app.main import app
from conftest import WEEK
from tests.test_rls_meta import TENANT_TABLES


def _count(tenant_id, sql: str, **params) -> int:
    with tenant_session(tenant_id) as session:
        return session.execute(text(sql), params).scalar()


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_no_cross_tenant_read(two_tenants, table):
    a, b = (t.tenant.id for t in two_tenants)
    assert _count(a, f"SELECT count(*) FROM {table}") > 0, "fixture must populate every table"
    assert _count(b, f"SELECT count(*) FROM {table}") > 0
    assert _count(a, f"SELECT count(*) FROM {table} WHERE tenant_id = :b", b=b) == 0
    assert _count(a, f"SELECT count(*) FROM {table} WHERE tenant_id <> :a", a=a) == 0


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_no_cross_tenant_write(two_tenants, table):
    a, b = (t.tenant.id for t in two_tenants)
    before = _count(b, f"SELECT count(*) FROM {table}")
    for statement in (
        f"UPDATE {table} SET tenant_id = tenant_id WHERE tenant_id = :b",
        f"DELETE FROM {table} WHERE tenant_id = :b",
    ):
        try:
            with tenant_session(a) as session:
                assert session.execute(text(statement), {"b": b}).rowcount == 0  # B's rows are invisible
        except DBAPIError as exc:
            assert "permission denied" in str(exc)  # append-only tables refuse the verb outright
    # Take one of A's own rows, give it a new id and B's tenant_id, and try to insert it.
    with tenant_session(a) as session:  # generated columns (search keys) cannot be inserted
        columns = ", ".join(session.scalars(text(
            "SELECT quote_ident(column_name) FROM information_schema.columns "
            "WHERE table_name = :t AND is_generated = 'NEVER' ORDER BY ordinal_position"
        ), {"t": table}))  # fmt: skip
    forged = (
        f"INSERT INTO {table} ({columns}) SELECT {columns} FROM jsonb_populate_record(NULL::{table}, "
        f"(SELECT to_jsonb(r) || jsonb_build_object('id', app.uuid_v7(), 'tenant_id', CAST(:b AS uuid)) "
        f"FROM {table} r LIMIT 1))"
    )
    with pytest.raises(DBAPIError, match="row-level security"), tenant_session(a) as session:
        session.execute(text(forged), {"b": b})
    assert _count(b, f"SELECT count(*) FROM {table}") == before


@pytest.mark.parametrize("table", [*TENANT_TABLES, "tenant"])
def test_no_tenant_context_sees_nothing(two_tenants, table):
    """Fail closed: a connection that never set app.tenant_id reads zero rows."""
    with app_engine().connect() as conn:
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
        conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))  # what a pooled connection reverts to
        assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_tenant_row_is_private(two_tenants):
    a, b = (t.tenant.id for t in two_tenants)
    assert _count(a, "SELECT count(*) FROM tenant") == 1
    with tenant_session(a) as session:
        assert session.execute(text("UPDATE tenant SET name = 'hijacked' WHERE id = :b"), {"b": b}).rowcount == 0
    with pytest.raises(DBAPIError, match="permission denied"), tenant_session(a) as session:
        session.execute(text("INSERT INTO tenant (name, slug, default_time_zone) VALUES ('x', 'x-forged', 'UTC')"))


# --- API ---------------------------------------------------------------------------------------------------

_BODIES = {
    "updateLocation": {"name": "Renamed"},
    "updateCatalogItem": {"description": "Renamed"},
    "sellCatalogItem": lambda ids: {"client_id": ids.client_id},
    "cancelCatalogItemSale": {"reason": "Mistake"},
    "createImportJobDryRun": {},
    "updateSavedReport": {"name": "Renamed"},
    # access rules (phase 10 chip B)
    "setClientAccessMode": {"access_mode": "always_admit", "reason": "Isolation"},
    "updateAccessSchedule": {"name": "Renamed"},
    "putMembershipTypeAccess": {"access_schedule_id": None, "location_ids": []},
    # check-in desk (phase 10 chip C)
    "updateCheckInStation": {"name": "Renamed"},
    "updateIdCardTemplate": {"name": "Renamed"},
    "createCheckInAttendance": lambda a: {"session_id": a.schedule_session_id},
    "replaceFacilityHours": {"days": WEEK},
    "updateStaffUser": {"first_name": "Renamed"},
    "assignStaffRole": "role",
    "assignStaffLocations": {"has_all_location_access": True},
    "replaceStaffPermissionOverrides": {"grants": []},
    "updateRole": {"name": "Renamed"},
    "replaceRolePermissions": {"grants": []},
    "reverseCharge": {"reason": "Mistake"},
    "allocatePayment": {},
    "createRefund": {"amount_minor": 1, "reason": "Mistake"},
    # billing (build module 8). A callable gets tenant A's ids, so only the path id is foreign.
    "updateRevenueCategory": {"label": "Renamed"},
    "updateTax": {"label": "Renamed"},
    "addTaxRate": {"rate": "0.05", "effective_from_on": "2031-01-01"},
    "updateTaxRate": {"rate": "0.05"},
    "updateTenderType": {"label": "Renamed"},
    "updateCoupon": {"name": "Renamed"},
    "updateCharge": {"description": "Renamed"},
    "voidCharge": {"reason": "Mistake"},
    "updateInvoice": {"comments": "Note"},
    "addInvoiceCharges": lambda a: {"charge_ids": [a.charge_id]},
    "moveInvoiceCharge": lambda a: {"target_invoice_id": a.invoice_id},
    "voidInvoice": {"reason": "Mistake"},
    "reassignInvoicePayer": lambda a: {"bill_to_client_id": a.client_id},
    "markInvoicePaid": {},
    "putPaymentSchedule": {"instalments": [{"due_on": "2031-01-01", "amount_minor": 1}]},
    "generatePaymentSchedule": {"start_on": "2031-01-01", "count": 2},
    "sendInvoice": {},
    "voidPayment": {"reason": "Mistake"},
    "sendReceipt": {},
    "applyAccountCredit": {},
    "refundAccountCredit": {"amount_minor": 1, "reason": "Mistake"},
    "sendClientStatement": {"from_on": "2026-01-01", "to_on": "2026-02-01"},
    "resendStatementBatch": {},
    "attachPaymentMethod": {"method_token": "tok_card_ok"},
    "createSetupIntent": {},
    "updatePaymentMethod": {"is_autopay": True},
    "verifyBankAccount": {"amounts": [32, 45]},
    "updatePortalPaymentMethod": {"is_autopay": True},
    "confirmPortalPayment": lambda a: {"invoice_ids": [str(a.invoice_id)]},
    # pos (build module 9)
    "updateRegister": {"name": "Renamed"},
    "putRegisterFavorites": {"product_ids": []},
    "openDrawerSession": {"opening_float_minor": 0},
    "closeDrawerSession": {"counted_cash_minor": 0},
    "reconcileDrawerSession": {},
    "openDrawerNoSale": {"reason": "Change"},
    "updateProductCategory": {"name": "Renamed"},
    "updateProductBrand": {"name": "Renamed"},
    "updateProductSupplier": {"name": "Renamed"},
    "updateProduct": {"name": "Renamed"},
    "updateDiscountPreset": {"name": "Renamed"},
    "updateEquipmentCategory": {"name": "Renamed"},
    "updateEquipmentItem": {"name": "Renamed"},
    "returnEquipment": {"outcome": "lost"},
    "updatePosSale": {"version": 1},
    "createPosSaleQuickClient": {"version": 1, "first_name": "Iso", "last_name": "Probe"},
    "addPosSaleLine": lambda a: {"product_id": a.product_id},
    "updatePosSaleLine": {"quantity": 1},
    "addPosSaleDiscount": {"source": "custom", "discount_minor": 1},
    "addPosSaleTender": {"tender": "pay_later", "amount_minor": 1},
    "sendPosReceipt": {"channel": "print"},
    "createPosReturn": lambda a: {"lines": [{"pos_sale_line_id": a.pos_sale_line_id, "quantity": 1}]},
    "voidPosSale": {"reason": "Mistake"},
    # clients (module 4)
    "updateClient": {"first_name": "Renamed"},
    "replaceClientEmergencyContacts": {"contacts": []},
    "assignClientMemberNumber": {},
    "assignClientOwners": {},
    "updateClientCategory": {"name": "Renamed"},
    "updateReferralCategory": {"name": "Renamed"},
    "updateTag": {"label": "Renamed"},
    "updateCustomField": {"label": "Renamed"},
    "updateClientLocationSettings": {"is_portal_photo_edit_enabled": True},
    "updateRelationshipType": {"label": "Renamed"},
    "createClientRelationship": "relationship",
    "inviteClientToPortal": {},
    "portalUpdateClient": {"city": "Elsewhere"},
    "portalReplaceEmergencyContacts": {"contacts": []},
    "updateNoteSubject": {"label": "Renamed"},
    "createClientNote": {"kind": "call", "subject_text": "Hi"},
    "updateClientNote": {"body": "Renamed"},
    "updateClientTask": {"body": "Renamed"},
    "createClientAlert": {"message": "Hi"},
    "updateClientAlert": {"message": "Renamed"},
    "precheckClientMerge": "merge",
    "mergeClients": "merge",
    "putClientCommunicationPreferences": "preferences",
    "putPortalCommunicationPreferences": {
        "changes": [{"channel": "push", "topic": "league_alerts", "is_subscribed": True}]
    },
    "confirmDataSubjectRequest": {"confirmation": "ERASE"},
    # documents (module 7)
    "updateDocumentTemplate": {"name": "Renamed"},
    "saveDocumentTemplateDraft": {"body_html": "<p>x</p>", "acceptance_text": "I agree."},
    "submitClientDocumentAcceptance": "acceptance",
    "portalSubmitAcceptance": "acceptance",
    "sendClientDocument": {"recipient_emails": ["x@example.com"]},
    "setWaiverOverride": {"waiver_override": "on_file"},
    "updateDocumentLocationSettings": {"is_consent_required": False},
    # memberships and packages (module 5)
    "updateMembershipType": {"name": "Renamed"},
    "updateMembershipPlan": {"name": "Renamed"},
    "replaceMembershipPlanAddons": {"addons": []},
    "updateMembershipContract": {"internal_notes": "Renamed"},
    "setMembershipContractSoldBy": {"sold_by_staff_user_id": None},
    "repriceMembershipContract": {"term_fee_minor": 100},
    "updateBillingSchedulePeriod": {"amount_minor": 100},
    "updateMembershipFreeze": {"remarks": "Renamed"},
    "updateMembershipSuspension": {"remarks": "Renamed"},
    "cancelMembershipContract": {"reason": "voluntary"},
    "addMembershipShare": "share",
    "adjustMembershipVisits": {"delta": 1, "reason": "Recount"},
    "updatePackagePlan": {"name": "Renamed"},
    "updateClientPackage": {"internal_remarks": "Renamed"},
    "adjustClientPackageCredits": {"delta": 1, "note": "Recount"},
    "addPackageShare": "share",
    "removeClientPackage": {"removal_mode": "billing_kept"},
    "updateResourceGroup": {"name": "Renamed"},
    "updateResource": {"name": "Renamed"},
    "replaceResourceLinks": {"to_resource_ids": []},
    "createAvailabilityWindow": {
        "starts_on": "2030-01-01",
        "weekdays": [1],
        "start_time": "09:00",
        "end_time": "10:00",
    },
    "updateAvailabilityWindow": {"note": "Renamed"},
    "updateReservationCategory": {"name": "Renamed"},
    "updateReservationType": {"name": "Renamed"},
    "updateBlackout": {"name": "Renamed"},
    "updateBooking": {"title": "Renamed", "version": 1},
    "rescheduleBooking": {"starts_at": "2030-03-04T17:00:00Z", "ends_at": "2030-03-04T18:00:00Z", "version": 1},
    "cancelBooking": {"version": 1},
    "addBookingSeriesRule": {
        "start_on": "2030-09-02",
        "start_time": "09:00",
        "end_time": "10:00",
        "rule": {"pattern": "single", "range_type": "count", "occurrence_limit": 1},
    },
    "editBookingSeries": {"scope": {"mode": "all"}, "patch": {"title": "Renamed"}},
    "cancelBookingSeries": {"scope": {"mode": "all"}},
    "updateBookingSeriesRule": {
        "start_on": "2031-01-01",
        "start_time": "06:00",
        "end_time": "07:00",
        "rule": {"pattern": "daily", "range_type": "count", "occurrence_limit": 1},
    },
    "replaceReservationTypeGrants": {"staff_user_ids": []},
    "updateSlotOffer": {"title": "Renamed"},
    "bookSlotOfferSlot": {"starts_at": "2030-01-02T15:30:00Z"},
    "updateSession": {"is_self_bookable": False},
    "cancelEnrollment": {},
    "rebookEnrollment": lambda ids: {"session_id": ids.schedule_session_id},
    "sendSessionRosterMessage": {"subject": "Hi", "body_html": "Hello"},
    "updateProgramGroup": {"name": "Renamed"},
    "addProgramSessions": lambda ids: {"session_ids": [ids.schedule_session_id]},
    "createProgramGroupFee": {"description": "X", "amount_minor": 100},
    "updateProgramFee": {"description": "Renamed"},
    "putRegistrationConfig": {"is_enabled": True},
    "addRegistrationCheckoutItem": lambda ids: {"program_group_id": ids.program_group_id, "client_id": ids.client_id},
    "addPortalRegistrationCheckoutItem": lambda ids: {
        "program_group_id": ids.program_group_id,
        "client_id": ids.client_id,
    },
    "confirmPortalRegistrationCheckout": {},
    "claimPortalWaitlistOffer": {},
    "putDefaultSessionBookingPolicy": {
        "listing_mode": "bookable",
        "requires_active_membership": False,
        "visible_range_days": 30,
        "hides_full_sessions": False,
        "booking_cutoff_minutes": 0,
        "allows_self_cancel": True,
        "cancel_notice_minutes": 0,
        "waitlist_mode": "auto_promote",
    },
    "putSessionBookingPolicyOverride": {},
    "putSessionAttendance": {
        "marks": [{"enrollment_id": "00000000-0000-7000-8000-000000000000", "status": "attended"}]
    },
    "updateRentalType": {"name": "Renamed"},
    "createRentalRate": {"name": "Other", "amount_minor": 100, "basis": "per_hour"},
    "updateRentalRate": {"name": "Renamed"},
    "cancelRental": {},
    "extendRental": {
        "start_on": "2030-09-03",
        "start_time": "09:00",
        "end_time": "10:00",
        "rule": {"pattern": "single", "range_type": "count", "occurrence_limit": 1},
    },
    "setRentalPublicSchedule": {"is_on_public_schedule": True},
    "confirmPortalRental": {"provider_payment_token": "tok_card_ok"},
    "updateRentalPlan": {"name": "Renamed"},
    "cancelRentalPlanPurchase": {"cancel_mode": "keep_billing", "reason": "Mistake"},
    # staff (build module 12)
    "updateStaffPayee": {"display_name": "Renamed"},
    "putDefaultPayRate": {"pay_basis": "per_session"},
    "putCommissionRules": {"rules": []},
    "putPayRateOverride": {"pay_basis": "per_session"},
    "putMembershipPayRate": {"pay_basis": "per_session"},
    "putBonusRules": {"rules": []},
    "updateJobClassification": {"name": "Renamed"},
    "addStaffHourlyRate": lambda ids: {
        "job_classification_id": ids.job_classification_id,
        "rate_minor": 1,
        "effective_from_on": "2031-01-01",
    },
    "updateTimeEntry": {"edit_reason": "Fix"},
    "voidTimeEntry": {"edit_reason": "Mistake"},
    "updateShift": {"note": "Renamed"},
    "updatePayStatement": {"additional_income_minor": 0},
    "assignSessionInstructor": {"staff_payee_id": None},
    "updateAssessmentTemplate": {"sort_order": 1},
    "createAssessmentField": {"name": "Body fat"},
    "updateAssessmentField": {"sort_order": 1},
    "updateAssessmentResult": {"note": "Rechecked"},
    # engagement (build module 14)
    "updateMessageTemplate": {"name": "Renamed"},
    "updateSegment": {"name": "Renamed"},
    "updateCampaign": {"name": "Renamed"},
    "scheduleCampaign": {"scheduled_at": "2031-01-01T00:00:00Z"},
    "updateReminderRule": {"is_enabled": True},
    "updateNotificationRoute": {"is_enabled": True},
    "updateAutomationRule": {"is_enabled": True},
    "putPortalSettings": {"welcome_text": "Hi"},
    "updateVideo": {"title": "Renamed"},
    "assignCredential": {"kind": "barcode", "generate": True},
    "revokeClientAppCards": {"kind": "app_card"},
    # leagues (build module 11)
    "updateSport": {"name": "Renamed"},
    "updateAgeGroup": {"name": "Renamed"},
    "updateSeason": {"name": "Renamed"},
    "updateCompetition": {"name": "Renamed"},
    "createDivision": {"name": "North"},
    "updateDivision": {"name": "Renamed"},
    "updateTeam": {"name": "Renamed"},
    "addCompetitionTeam": {"team": {"name": "Other"}},
    "generateCompetitionTeams": {"count": 1},
    "copyCompetitionTeams": lambda ids: {"source_competition_id": ids.competition_id},
    "putCompetitionSeeding": lambda ids: {"competition_team_ids": [ids.competition_team_id]},
    "updateCompetitionTeam": {"display_name": "Renamed"},
    "billCompetitionTeam": lambda ids: {"bill_to_client_id": ids.client_id},
    "addRosterEntry": {"first_name": "Walk", "last_name": "On"},
    "updateRosterEntry": {"position": "Keeper"},
    "adjustStanding": {"adjustment_points": "-1", "reason": "Late"},
    "updateScheduleRun": {"rounds": 2},
    "updateGame": {"notes": "Renamed"},
    "rescheduleGame": lambda ids: {"resource_id": ids.resource_id, "starts_at": "2031-07-02T23:00:00Z"},
    "postponeGame": {},
    "putGameResult": {"home": {"score": 1}, "away": {"score": 0}},
    "updateOfficial": {"first_name": "Renamed"},
    "putGameOfficials": lambda ids: {"assignments": [{"official_id": ids.official_id}]},
    "generateBracket": {"bracket_type": "single_elimination", "seed_source": "seeds"},
    "updateBracketSlot": {},
    # leagues depth (Phase 14 chip B1)
    "updateVenue": {"name": "Renamed"},
    "replaceTeamPreferences": {"preferences": []},
    "replaceCompetitionStaff": {"staff": []},
    "replaceLadder": {"competition_team_ids": []},
    "createLadderChallenge": lambda ids: {
        "challenger_id": ids.competition_team_id,
        "defender_id": ids.competition_team_id,
    },
    "createStatTable": {"name": "Other"},
    "updateStatTable": {"name": "Renamed"},
    "createStatDefinition": {"code": "A", "name": "Assists"},
    "updateStatDefinition": {"name": "Renamed"},
    "replaceGamePlayerStats": {"stats": []},
    "splitTeamFee": lambda ids: {"shares": [{"roster_entry_id": ids.roster_entry_id, "amount_minor": 1}]},
    "createPortalRosterEntry": {"first_name": "Walk", "last_name": "On"},
    # integrations (module 16)
    "rotateApiKey": {},
    "updateWebhookEndpoint": {"description": "Renamed"},
    # platform OIDC (Phase 8 S3)
    "updateIdentityProvider": {"display_name": "Renamed"},
}
_ACCEPTANCE = {"content_sha256": "0" * 64, "signers": [
    {"decision": "accepted", "signer_role": "client", "signer_name": "X", "method": "checkbox"}]}  # fmt: skip
_PREFERENCES = {"changes": [{"channel": "push", "topic": "league_alerts", "is_subscribed": True}], "note": "x"}
# Generated from the OpenAPI document, so a new route with an id parameter is tested without being listed.
_ID_ROUTES = [
    (method.upper(), path, operation["operationId"])
    for path, operations in app.openapi()["paths"].items()
    if "{" in path
    for method, operation in operations.items()
]


def body_for(name: str, ids):
    """The request body for an id route, with any id it carries taken from `ids` (a populate() namespace)."""
    body = _BODIES.get(name)
    if body == "role":
        body = {"role_id": ids.role_id}
    elif body == "relationship":
        body = {"other_client_id": ids.kid_id, "relationship_type_id": ids.relationship_type_id}
    elif body == "merge":
        body = {"merged_client_ids": [ids.kid_id]}
    elif body == "preferences":
        body = _PREFERENCES
    elif body == "acceptance":
        body = _ACCEPTANCE
    elif body == "share":
        body = {"client_id": ids.kid_id}
    return body(ids) if callable(body) else body


@pytest.mark.parametrize(("method", "path", "name"), _ID_ROUTES, ids=[f"{m} {p}" for m, p, _ in _ID_ROUTES])
def test_api_foreign_tenant_id_is_404(client, two_tenants, method, path, name):
    """Every route with an id parameter, called with A's token and B's id: 404, never 403 or data."""
    a, b = two_tenants
    url = re.sub(r"\{(\w+)_id\}", lambda m: str(getattr(b, f"{m[1]}_id")), path)
    body = body_for(name, a)  # A's own ids in the body, so only the path id is foreign
    headers = a.headers | {"Idempotency-Key": f"iso-{name}-key"}
    if "/public/" in path:  # anonymous routes take the tenant from the host or X-Tenant-Slug, not the token
        headers |= {"X-Tenant-Slug": a.tenant.slug}
    response = client.request(method, url, headers=headers, json=body)
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not-found"


def test_every_id_route_is_covered():
    assert len(_ID_ROUTES) >= 28
    assert {name for _, _, name in _ID_ROUTES if name.startswith(("update", "replace", "assign"))} <= set(_BODIES)
    assert set(_BODIES) <= {name for _, _, name in _ID_ROUTES}


@pytest.mark.parametrize(
    "path",
    [
        "/locations", "/staff-users", "/roles", "/audit-events?limit=200", "/auth/sessions", "/clients", "/charges",
        "/invoices", "/payments", "/revenue-categories", "/ledger-entries",
        "/taxes", "/coupons", "/payment-methods", "/autopay-runs", "/autopay-attempts", "/refunds",
        "/billing-notices", "/billing-history",
        "/registers", "/products", "/product-categories", "/pos-sales", "/drawer-sessions", "/stock-movements",
        "/equipment-items", "/equipment-loans", "/discount-presets",
        "/client-categories", "/tags",
        "/note-subjects", "/client-tasks", "/data-subject-requests", "/relationship-types", "/custom-fields",
        "/membership-types", "/membership-plans", "/membership-contracts", "/package-plans", "/client-packages",
        "/package-series",
        "/api-keys", "/webhook-endpoints", "/webhook-deliveries", "/external-connections", "/accounting-exports",
        "/adapter-commands", "/import-jobs",
    ],
)  # fmt: skip
def test_api_lists_never_include_the_other_tenant(client, two_tenants, path):
    a, b = two_tenants
    payload = client.get(f"/api/v1{path}", headers=a.headers).json()
    rows = payload["data"] if isinstance(payload, dict) else payload
    assert rows
    ids = {row["id"] for row in rows}
    assert not ids & {
        b.location_id, b.staff_user_id, b.role_id, b.session_id, b.client_id, b.charge_id, b.invoice_id,
        b.payment_id, b.revenue_category_id, b.client_category_id, b.tag_id, b.note_subject_id, b.task_id,
        b.request_id, b.relationship_type_id, b.custom_field_id, b.template_id, b.binding_id, b.document_id,
        b.pending_document_id, b.membership_type_id, b.membership_plan_id, b.contract_id, b.package_plan_id,
        b.package_id, b.series_id, b.api_key_id, b.webhook_endpoint_id, b.webhook_delivery_id,
        b.external_connection_id,
    }  # fmt: skip
    theirs = client.get(f"/api/v1{path}", headers=b.headers).json()
    theirs = theirs["data"] if isinstance(theirs, dict) else theirs
    assert not ids & {row["id"] for row in theirs}


def test_api_write_with_foreign_reference_is_rejected(client, two_tenants):
    """A body that points at B's role or location cannot attach it to A's data."""
    a, b = two_tenants
    invite = {"email": "x@a.example.com", "first_name": "X", "last_name": "Y", "role_id": b.role_id}
    assert client.post("/api/v1/staff-users", headers=a.headers, json=invite).status_code == 422
    assign = {"has_all_location_access": False, "location_ids": [b.location_id]}
    assert (
        client.put(f"/api/v1/staff-users/{a.staff_user_id}/locations", headers=a.headers, json=assign).status_code
        == 422
    )

    # clients and billing: every body field that carries an id.
    def post(path: str, body: dict, index: int = 0):
        key = {"Idempotency-Key": f"iso-foreign-{index}-{uuid4().hex}"}
        return client.post(f"/api/v1{path}", headers=a.headers | key, json=body)

    person = {"first_name": "X", "last_name": "Y", "home_location_id": a.location_id}
    charge = {"client_id": a.client_id, "location_id": a.location_id, "description": "X", "unit_price_minor": 100}
    payment = {"client_id": a.client_id, "location_id": a.location_id, "amount_minor": 100, "tender_kind": "cash"}
    fresh = post("/charges", charge).json()["id"]  # A's own, still uninvoiced
    document = {"client_id": a.client_id, "location_id": a.location_id, "template_id": a.template_id,
                "acceptance_method": "checkbox"}  # fmt: skip
    membership = {"client_id": a.kid_id, "location_id": a.location_id, "membership_plan_id": a.membership_plan_id}
    package = {"client_id": a.client_id, "location_id": a.location_id, "package_plan_id": a.package_plan_id}
    for index, (path, body) in enumerate((
        ("/clients", person | {"home_location_id": b.location_id}),
        ("/charges", charge | {"client_id": b.client_id}),
        ("/charges", charge | {"location_id": b.location_id}),
        ("/charges", charge | {"revenue_category_id": b.revenue_category_id}),
        ("/invoices", {"charge_ids": [b.charge_id]}),
        ("/invoices", {"charge_ids": [fresh], "bill_to_client_id": b.client_id}),
        ("/payments", payment | {"client_id": b.client_id}),
        ("/payments", payment | {"location_id": b.location_id}),
        ("/payments", payment | {"invoice_id": b.invoice_id}),
        ("/payments", payment | {"allocations": [{"charge_id": b.charge_id, "amount_minor": 1}]}),
        (f"/payments/{a.payment_id}/allocations", {"invoice_id": b.invoice_id}),
        (f"/payments/{a.payment_id}/allocations", {"allocations": [{"charge_id": b.charge_id, "amount_minor": 1}]}),
        ("/registers", {"location_id": b.location_id, "name": "X"}),
        ("/pos-sales", {"register_id": b.register_id}),
        ("/stock-movements", {"product_id": b.product_id, "location_id": a.location_id, "kind": "adjustment",
                              "quantity_delta": 1, "reason": "other"}),
        ("/products", {"product_category_id": b.product_category_id, "name": "X", "product_code": "X-iso",
                       "unit_price_minor": 1}),
        ("/equipment-items", {"equipment_category_id": a.equipment_category_id, "location_id": b.location_id,
                              "name": "X", "asset_code": "X-iso"}),
        ("/clients", person | {"client_category_id": b.client_category_id}),
        ("/clients", person | {"tag_ids": [b.tag_id]}),
        (f"/clients/{a.client_id}/relationships", {"other_client_id": b.client_id, "relationship_type_id": a.relationship_type_id}),
        (f"/clients/{a.client_id}/relationships", {"other_client_id": a.kid_id, "relationship_type_id": b.relationship_type_id}),
        ("/client-tasks", {"client_id": b.client_id, "subject_text": "x"}),
        ("/client-tasks", {"client_id": a.client_id, "subject_text": "x", "assignee_staff_user_id": b.staff_user_id}),
        (f"/clients/{a.client_id}/notes", {"kind": "call", "note_subject_id": b.note_subject_id}),
        (f"/clients/{a.client_id}/merge-precheck", {"merged_client_ids": [b.client_id]}),
        ("/data-subject-requests", {"client_id": b.client_id, "kind": "export"}),
        ("/client-documents", document | {"client_id": b.client_id}),
        ("/client-documents", document | {"location_id": b.location_id}),
        ("/client-documents", document | {"template_id": b.template_id}),
        ("/membership-types", {"name": "X", "revenue_category_id": b.revenue_category_id}),
        ("/membership-plans", {"membership_type_id": b.membership_type_id, "name": "X", "billing_occurrences_count": 1, "term_fee_minor": 1}),
        ("/membership-contracts", membership | {"client_id": b.client_id}),
        ("/membership-contracts", membership | {"location_id": b.location_id}),
        ("/membership-contracts", membership | {"membership_plan_id": b.membership_plan_id}),
        ("/membership-contracts", membership | {"referred_by_client_id": b.client_id}),
        ("/membership-contracts", membership | {"sold_by_staff_user_id": b.staff_user_id}),
        ("/membership-contracts", membership | {"share_client_ids": [b.client_id]}),
        (f"/membership-contracts/{a.contract_id}/shares", {"client_id": b.client_id}),
        (f"/membership-contracts/{a.contract_id}/renew", {"renews_as_plan_id": b.membership_plan_id}),
        ("/client-packages", package | {"client_id": b.client_id}),
        ("/client-packages", package | {"location_id": b.location_id}),
        ("/client-packages", package | {"package_plan_id": b.package_plan_id}),
        ("/client-packages", package | {"sold_by_staff_user_id": b.staff_user_id}),
        ("/client-packages/complimentary", package | {"package_plan_id": b.package_plan_id}),
        (f"/client-packages/{a.package_id}/shares", {"client_id": b.client_id}),
        ("/api-keys", {"name": "X", "scopes": ["clients.client.read"], "location_ids": [b.location_id]}),
        ("/external-connections", {"provider": "accounting_file", "location_id": b.location_id}),
        ("/accounting-exports", {
            "external_connection_id": a.external_connection_id, "location_id": b.location_id, "business_on": "2020-01-02",
        }),
        ("/report-runs", {"report_key": "deposits", "saved_report_id": b.saved_report_id}),
        ("/export-jobs", {"report_run_id": b.report_run_id}),
    )):  # fmt: skip
        response = post(path, body, index)
        assert (response.status_code, response.json()["code"]) == (422, "validation-failed"), (
            path,
            body,
            response.text,
        )
    foreign_binding = {"scope_type": "program_default", "template_id": b.template_id}
    assert client.put("/api/v1/document-bindings", headers=a.headers, json=foreign_binding).status_code == 422
    # A's location with B's connection: the connection id itself is not found.
    foreign = {
        "external_connection_id": b.external_connection_id,
        "location_id": a.location_id,
        "business_on": "2020-01-02",
    }
    assert post("/accounting-exports", foreign, 99).status_code == 404


def test_token_is_bound_to_its_tenant_host(client, two_tenants):
    a, b = two_tenants
    response = client.get("/api/v1/me", headers={**a.headers, "Host": f"{b.tenant.slug}.localhost"})
    assert response.status_code == 401
    assert client.get("/api/v1/me", headers={**a.headers, "Host": f"{a.tenant.slug}.localhost"}).status_code == 200
