"""Location scope, generated from the router table (wave 1 hardening 0.5): an admin limited to another
location gets 404 on every location-bound staff route, never data, never 403.

A route is location-bound when its first path id names a location-owned row (the `location` table, or a table
with a `location_id` column) and its router key is location-scoped, or it has no key (configuration reads).
Client-following (`C`) and tenant-wide (`T`) routes are not location-bound by design (rbac-matrix 3.1); they
are pinned in a reviewed snapshot instead, so a key that changes scope or a new such route is a visible diff.
"""

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.auth import CATALOGUE, Scope
from app.core.db.base import Base
from app.main import app
from conftest import add_staff, login, make_tenant, populate
from tests.known_open import LOCATION_SCOPE, param
from tests.test_isolation import _ID_ROUTES, body_for
from tests.test_security import ROUTES

# Path id name -> table, where the table is not simply named after the id.
_TABLES = {
    "alert": "client_alert", "binding": "document_binding", "checkout": "registration_checkout", "contract": "membership_contract",
    "document": "client_document", "freeze": "membership_freeze",
    "note": "client_note", "package": "client_package", "period": "billing_schedule_period",
    "purchase": "rental_plan_purchase", "relationship": "client_relationship", "rental": "rental_booking",
    "request": "data_subject_request", "schedule_session": "session", "session": "auth_session",
    "series": "package_series", "suspension": "membership_suspension", "task": "client_task",
    "template": "document_template",
}  # fmt: skip
# Writes under the client-following billing.payment.take that post to another location's books (M-04).
LOCATION_BOUND_WRITES = {"markInvoicePaid", "cancelPayment", "confirmPayment"}
# Reviewed: id routes whose key is client-following or tenant-wide, so a limited admin may reach them anywhere.
# Backlog 18: billing.invoice.read/send and billing.payment.read stay client-following (spec section 6).
CLIENT_OR_TENANT_ROUTES = {
    "client": set("""
        applyAccountCredit attachPaymentMethod clearClientDocumentPaperSigned clearWaiverOverride
        createSetupIntent getAccountCredit getAutopayRun getCharge getClientBillingSummary
        getClientDocument getClientDocumentFile getClientPackage getClientStatement
        getDocumentLocationSettings getDocumentTemplate getInvoice getInvoiceDocument getMembershipContract
        getMembershipPlan getPackagePlan getPackageSeries getPayment getPaymentSchedule getReceipt
        listClientDocumentDeliveries listClientPackageLedger listClientPaymentMethods listInvoiceDeliveries
        listMembershipBillingSchedule listMembershipContractHistory listMembershipFreezes listMembershipShares
        listMembershipSuspensions listMembershipVisits listPackageShares removePaymentMethod
        sendClientDocument sendInvoice sendReceipt setWaiverOverride submitClientDocumentAcceptance
        updatePaymentMethod uploadClientDocumentPaperScan verifyBankAccount
        getAssessmentResult updateAssessmentResult
        assignCredential revokeClientAppCards revokeCredential
    """.split()),
    "tenant": set("""
        addTaxRate releaseSuppression approveClientRelationship archiveDocumentTemplate archiveLocation assignClientMemberNumber
        assignClientOwners assignStaffLocations assignStaffRole confirmDataSubjectRequest createClientAlert
        createClientNote createClientRelationship createOnboardingLink createRentalRate
        deactivateDocumentBinding deactivateStaffUser deleteClientCategory deleteClientNote deleteCoupon
        deleteNoteSubject deleteReferralCategory deleteRentalPlan deleteRole deleteTaxRate disableClient
        disconnectProviderAccount duplicateMembershipPlan enableClient endClientRelationship getClient
        getClientCommunicationPreferences getClientEmergencyContacts getClientLocationSettings
        getClientPortalAccess getClientTimeline getDataSubjectRequest getRole getStaffUser
        getStaffUserPermissions inviteClientToPortal listClientAlerts listClientNotes listClientRelationships
        listCouponRedemptions listDocumentTemplateVersions mergeClients precheckClientMerge
        publishDocumentTemplate putClientCommunicationPreferences reactivateStaffUser
        replaceClientEmergencyContacts replaceMembershipPlanAddons replaceRolePermissions
        replaceStaffPermissionOverrides resendStaffInvitation resetStaffCredentials resetStaffPermissions
        restoreDocumentTemplate revokeClientPortalAccess saveDocumentTemplateDraft sendClientEmailVerification
        updateClient updateClientAlert updateClientCategory updateClientLocationSettings updateClientNote
        updateClientTask updateCoupon updateCustomField updateDiscountPreset updateDocumentLocationSettings
        updateDocumentTemplate updateEquipmentCategory updateEquipmentItem updateMembershipPlan
        updateMembershipType updateNoteSubject updatePackagePlan updateProduct updateProductBrand
        updateProductCategory updateProductSupplier updateReferralCategory updateRelationshipType
        updateRentalPlan updateRentalRate updateRentalType updateReservationCategory updateReservationType
        updateRevenueCategory updateRole updateStaffUser updateTag updateTax updateTaxRate updateTenderType
        addStaffHourlyRate deleteStaffHourlyRate getCommissionRules listPayRates listStaffHourlyRates
        putCommissionRules putDefaultPayRate putPayRateOverride putMembershipPayRate deletePayRateOverride
        deleteMembershipPayRate listBonusRules putBonusRules
        listReservationTypeGrants replaceReservationTypeGrants
        createAssessmentField updateAssessmentField updateAssessmentTemplate
    """.split())
    # Integrations (module 16): T keys; the service limits a location-bound admin to their own endpoints and to
    # keys inside their locations, and disconnect authorizes on the connection's location_id.
    | set("""
        deleteWebhookEndpoint disconnectExternalConnection getWebhookDelivery getWebhookEndpoint
        replayWebhookDelivery revokeApiKey rotateApiKey rotateWebhookSecret testWebhookEndpoint
        updateWebhookEndpoint
    """.split()),
}  # fmt: skip

# The voidClientDocument case runs first and voids populate()'s signed document, which then cannot be deleted.
_PATH_IDS = {
    "deleteClientDocument": {"document_id": "pending_document_id"},
    "restoreProgramGroup": {"program_group_id": "deleted_program_group_id"},
    "removeProgramSession": {"schedule_session_id": "linked_session_id"},
}
_OPERATION = {(method, path): name for method, path, name in _ID_ROUTES}


def _keys(calls) -> tuple[str, ...] | None:
    """The router keys of a staff route (require() exposes them), or None for a route that is not staff."""
    found = [call.keys for call in calls if isinstance(getattr(call, "keys", None), tuple)]
    return tuple(key for keys in found for key in keys) if found else None


def _table(name: str):
    table = Base.metadata.tables.get(_TABLES.get(name, name))
    assert table is not None, f"path id {{{name}_id}} names no table: add it to _TABLES"
    return table


def _staff_id_routes():
    for path, route, calls in ROUTES:
        keys = _keys(calls)
        if keys is None or "{" not in path:
            continue
        for method in sorted(route.methods):
            yield method, path, _OPERATION[(method, path)], keys


def _location_bound(path: str, name: str, keys: tuple[str, ...]) -> bool:
    if name in LOCATION_BOUND_WRITES:
        return True
    match = re.search(r"\{(\w+)_id\}", path)
    if match is None:
        return False  # a code key ({report_key}), not a row
    table = _table(match[1])
    owned = table.name == "location" or "location_id" in table.c
    return owned and (not keys or any(CATALOGUE[key].scope == Scope.LOCATION for key in keys))


def _scope_of(keys: tuple[str, ...]) -> str:
    return "/".join(sorted({CATALOGUE[key].scope.value for key in keys}))


_ALL = list(_staff_id_routes())
# Deletes last: the owner's call really runs, and a deleted row would turn later calls on it into a 404.
_BOUND = sorted(((m, p, n) for m, p, n, k in _ALL if _location_bound(p, n, k)), key=lambda row: row[0] == "DELETE")


@pytest.fixture(scope="module")
def scoped():
    """A populated tenant (rows at location Main), a second location, and an admin limited to that one."""
    client = TestClient(app)
    ids = populate(client, make_tenant())
    other = client.post(
        "/api/v1/locations", headers=ids.headers,
        json={"name": "Elsewhere", "time_zone": "America/Chicago", "country_code": "US"},
    ).json()["id"]  # fmt: skip
    email, _ = add_staff(ids.tenant, "admin", location_ids=[other])
    return SimpleNamespace(client=client, ids=ids, outsider=login(client, ids.tenant, email))


@pytest.mark.parametrize(("method", "path", "name"), [param(n, m, p, n, known=LOCATION_SCOPE) for m, p, n in _BOUND])
def test_other_location_admin_gets_404(scoped, method, path, name):
    ids = scoped.ids
    names = _PATH_IDS.get(name, {})
    url = re.sub(r"\{(\w+_id)\}", lambda m: str(getattr(ids, names.get(m[1], m[1]))), path)
    body = body_for(name, ids)

    def call(headers, tag):
        key = {"Idempotency-Key": f"scope-{tag}-{name}"}
        return scoped.client.request(method, url, headers=headers | key, json=body)

    refused = call(scoped.outsider, "out")
    assert (refused.status_code, refused.json().get("code")) == (404, "not-found"), refused.text
    allowed = call(ids.headers, "own")
    assert allowed.status_code != 404, f"the owner gets 404 too, so the fixture is wrong: {allowed.text}"


def test_every_staff_id_route_resolves_and_some_are_location_bound():
    assert len(_BOUND) > 40
    assert LOCATION_BOUND_WRITES <= {n for _, _, n in _BOUND}
    assert set(LOCATION_SCOPE) <= {n for _, _, n in _BOUND}, "a known-open entry names no location-bound route"


def test_client_following_and_tenant_wide_routes_are_reviewed():
    """Routes whose key is `C` or `T`: reachable from any location by design. A diff here is a review."""
    found: dict[str, set[str]] = {}
    for _, _, name, keys in _ALL:
        if keys and name not in LOCATION_BOUND_WRITES and all(CATALOGUE[k].scope != Scope.LOCATION for k in keys):
            found.setdefault(_scope_of(keys), set()).add(name)
    assert found == CLIENT_OR_TENANT_ROUTES
