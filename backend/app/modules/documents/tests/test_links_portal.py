"""Emailed single-use links (DOC-04), the portal (SSP-20), consent (DOC-09), merge and erasure handlers."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.documents import service
from app.modules.documents.models import ClientDocument, ClientDocumentStatus, DocumentAcceptance, DocumentDelivery
from app.modules.documents.tests.support import API, born, issue, location, ok, png_b64, sign, template
from conftest import PASSWORD, link_token, login, new_client, scalar, verify_email


@pytest.fixture
def location_id(client, owner):
    return location(client, owner)


def _decide(client, token, view, decision="accepted", **extra):
    body = {"token": token, "decision": decision, "content_sha256": view["content_sha256"], "signer_name": "Ann Lee",
            "typed_signature": "Ann Lee"} | extra  # fmt: skip
    return client.post(f"{API}/public/document-deliveries/decision", json=body, headers={"User-Agent": "Phone/2"})


def test_emailed_link_is_single_use_and_superseded(client, owner, location_id, tenant, mailbox):
    tpl = template(client, owner)
    person = new_client(client, owner, location_id, primary_email=f"ann@{tenant.slug}.example.com")
    doc = issue(client, owner, person, location_id, tpl["id"])
    send = f"{API}/client-documents/{doc['id']}/deliveries"
    to = {"recipient_emails": [person["primary_email"]]}
    assert client.post(send, headers=owner, json=to).json()["code"] == "email-not-verified"
    verify_email(tenant, person["id"], person["primary_email"])
    first = ok(client.post(send, headers=owner, json=to), 201)
    assert first["outcome"] == "pending"
    old = link_token(mailbox[-1])
    assert "/sign#token=" in mailbox[-1].body and "?token" not in mailbox[-1].body
    ok(client.post(send, headers=owner, json=to), 201)
    token = link_token(mailbox[-1])
    opened = client.post(f"{API}/public/document-deliveries/open", json={"token": old})
    assert (opened.status_code, opened.json()["code"]) == (410, "token-superseded")
    view = ok(client.post(f"{API}/public/document-deliveries/open", json={"token": token}))
    assert (
        view["title"] == tpl["name"] and view["client_display_name"].startswith("Casey") and view["status"] == "pending"
    )
    assert _decide(client, token, view | {"content_sha256": "0" * 64}).json()["code"] == "content-mismatch"
    decided = ok(_decide(client, token, view, signature_png=png_b64()))
    assert decided["status"] == "accepted"
    again = client.post(f"{API}/public/document-deliveries/open", json={"token": token})
    assert (again.status_code, again.json()["code"]) == (410, "token-expired")
    deliveries = ok(client.get(send, headers=owner))["data"]
    assert [d["outcome"] for d in deliveries] == ["accepted", "superseded"] and deliveries[0]["opened_at"]
    stored = ok(client.get(f"{API}/client-documents/{doc['id']}", headers=owner))
    assert (
        stored["acceptances"][0]["method"] == "drawn_signature"
        and stored["acceptances"][0]["witnessed_by_staff_user_id"] is None
    )
    row = scalar(tenant, select(DocumentAcceptance).where(DocumentAcceptance.client_document_id == doc["id"]))
    assert row.user_agent == "Phone/2" and row.delivery_id is not None
    assert client.post(send, headers=owner, json=to).status_code == 409  # no longer pending

    bogus = client.post(f"{API}/public/document-deliveries/open", json={"token": "fhd_" + "x" * 40})
    assert bogus.status_code == 404
    unknown = client.post(f"{API}/public/document-deliveries/open", json={"token": token[:-4] + "abcd"})
    assert unknown.json()["code"] == "token-invalid"


def test_link_expiry_decline_and_guardian(client, owner, location_id, tenant, mailbox):
    tpl = template(client, owner)
    kid = new_client(client, owner, location_id, birth_on=born(9))
    parent = new_client(client, owner, location_id, primary_email=f"pat@{tenant.slug}.example.com")
    verify_email(tenant, parent["id"], parent["primary_email"])
    types = {t["code"]: t for t in client.get(f"{API}/relationship-types", headers=owner).json()}
    ok(client.post(f"{API}/clients/{parent['id']}/relationships", headers=owner,
                   json={"other_client_id": kid["id"], "relationship_type_id": types["parent_of"]["id"]}), 201)  # fmt: skip
    doc = issue(
        client, owner, kid, location_id, tpl["id"], method="email_link", recipient_emails=[parent["primary_email"]]
    )
    token = link_token(mailbox[-1])
    view = ok(client.post(f"{API}/public/document-deliveries/open", json={"token": token}))
    assert view["requires_guardian"] is True
    decided = ok(_decide(client, token, view, signer_role="guardian"))
    assert decided["status"] == "accepted"
    evidence = ok(client.get(f"{API}/client-documents/{doc['id']}", headers=owner))["acceptances"][0]
    assert (evidence["signer_role"], evidence["signer_client_id"]) == ("guardian", parent["id"])

    second = issue(
        client, owner, kid, location_id, tpl["id"], method="email_link", recipient_emails=[parent["primary_email"]]
    )
    token = link_token(mailbox[-1])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(DocumentDelivery).where(DocumentDelivery.client_document_id == second["id"])
                        .values(expires_at=clock.now() - timedelta(minutes=1)))  # fmt: skip
    assert client.post(f"{API}/public/document-deliveries/open", json={"token": token}).status_code == 410
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert service.run_sweeps(session)["links_expired"] == 1

    third = issue(
        client, owner, kid, location_id, tpl["id"], method="email_link", recipient_emails=[parent["primary_email"]]
    )
    token = link_token(mailbox[-1])
    view = ok(client.post(f"{API}/public/document-deliveries/open", json={"token": token}))
    assert ok(_decide(client, token, view, decision="declined", signer_role="guardian"))["status"] == "declined"
    assert ok(client.get(f"{API}/client-documents/{third['id']}", headers=owner))["status"] == "declined"


def _portal(client, tenant, owner, person, mailbox) -> dict:
    ok(client.post(f"{API}/clients/{person['id']}/portal-access/invite", headers=owner, json={}))
    token = link_token(mailbox[-1])
    ok(client.post(f"{API}/auth/invitations/accept", json={"token": token, "new_password": PASSWORD}))
    return login(client, tenant, person["primary_email"], audience="client")


def test_portal_lists_signs_and_acts_for_a_dependent(client, owner, location_id, tenant, mailbox):
    tpl = template(client, owner)
    me = new_client(client, owner, location_id, primary_email=f"me@{tenant.slug}.example.com")
    stranger = new_client(client, owner, location_id)
    mine = issue(client, owner, me, location_id, tpl["id"])
    theirs = issue(client, owner, stranger, location_id, tpl["id"])
    portal = _portal(client, tenant, owner, me, mailbox)
    listed = ok(client.get(f"{API}/portal/client-documents", headers=portal))["data"]
    assert [d["id"] for d in listed] == [mine["id"]]
    assert client.get(f"{API}/portal/client-documents/{theirs['id']}", headers=portal).status_code == 404
    assert client.get(f"{API}/portal/client-documents?client_id={stranger['id']}", headers=portal).status_code == 404
    assert client.get(f"{API}/portal/client-documents", headers=owner).status_code == 404  # staff are not portal users
    body = {"content_sha256": mine["content_sha256"], "signers": [
        {"decision": "accepted", "signer_role": "client", "signer_name": "Me", "method": "checkbox"}]}  # fmt: skip
    url = f"{API}/portal/client-documents/{mine['id']}/acceptances"
    forged = {**body, "signers": [body["signers"][0] | {"signer_client_id": stranger["id"]}]}
    assert client.post(url, headers=portal, json=forged).status_code == 422
    signed = ok(client.post(url, headers=portal, json=body))
    assert signed["status"] == "accepted" and signed["acceptances"][0]["witnessed_by_staff_user_id"] is None
    pdf = client.get(f"{API}/portal/client-documents/{mine['id']}/file", headers=portal)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    types = {t["code"]: t for t in client.get(f"{API}/portal/relationship-types", headers=portal).json()}
    kid = ok(client.post(f"{API}/portal/dependents", headers=portal, json={
        "relationship_type_id": types["parent_of"]["id"], "first_name": "Kit", "last_name": "Me",
        "birth_on": born(8)}), 201)  # fmt: skip
    plan = "0190e000-0000-7000-8000-000000000001"
    ok(client.put(f"{API}/document-bindings", headers=owner,
                  json={"scope_type": "membership_plan", "scope_id": plan, "template_id": tpl["id"]}))  # fmt: skip
    reqs = f"{API}/portal/document-requirements?scope_type=membership_plan&scope_id={plan}&client_id={kid['id']}"
    [req] = ok(client.get(reqs, headers=portal))["requirements"]
    assert req["pending_document_id"] and req["requires_guardian"] and not req["is_satisfied"]
    assert ok(client.get(reqs, headers=portal))["requirements"][0]["pending_document_id"] == req["pending_document_id"]
    pending = ok(
        client.get(f"{API}/portal/client-documents/{req['pending_document_id']}?client_id={kid['id']}", headers=portal)
    )
    as_guardian = {"content_sha256": pending["content_sha256"], "signers": [
        {"decision": "accepted", "signer_role": "guardian", "signer_name": "Me", "method": "typed_name",
         "typed_signature": "Me"}]}  # fmt: skip
    done = ok(client.post(f"{API}/portal/client-documents/{pending['id']}/acceptances?client_id={kid['id']}",
                          headers=portal, json=as_guardian))  # fmt: skip
    assert done["status"] == "accepted" and done["acceptances"][0]["signer_client_id"] == me["id"]
    assert ok(client.get(reqs, headers=portal))["requirements"][0]["is_satisfied"] is True


def test_portal_consent(client, owner, location_id, tenant, mailbox):
    me = new_client(client, owner, location_id, primary_email=f"c@{tenant.slug}.example.com")
    portal = _portal(client, tenant, owner, me, mailbox)
    assert ok(client.get(f"{API}/portal/consent", headers=portal)) == {
        "is_consent_required": False, "is_consent_missing": False, "pending_document_id": None}  # fmt: skip
    template(client, owner, kind="consent", is_waiver=False)
    ok(
        client.patch(
            f"{API}/document-location-settings/{location_id}", headers=owner, json={"is_consent_required": True}
        )
    )
    state = ok(client.get(f"{API}/portal/consent", headers=portal))
    assert state["is_consent_missing"] and state["pending_document_id"]
    assert (
        ok(client.get(f"{API}/portal/consent", headers=portal))["pending_document_id"] == state["pending_document_id"]
    )
    doc = ok(client.get(f"{API}/portal/client-documents/{state['pending_document_id']}", headers=portal))
    assert doc["origin"] == "consent"
    ok(client.post(f"{API}/portal/client-documents/{doc['id']}/acceptances", headers=portal, json={
        "content_sha256": doc["content_sha256"],
        "signers": [{"decision": "accepted", "signer_role": "client", "signer_name": "C", "method": "checkbox"}]}))  # fmt: skip
    after = ok(client.get(f"{API}/portal/consent", headers=portal))
    assert after["is_consent_missing"] is False
    status = ok(client.get(f"{API}/client-document-statuses?client_id[in]={me['id']}", headers=owner))["data"][0]
    assert status["consent_accepted_at"] and status["is_consent_missing"] is False


def test_merge_moves_documents_and_erase_keeps_signed_evidence(client, owner, location_id, tenant):
    tpl = template(client, owner)
    keep = new_client(client, owner, location_id, first_name="Jo", last_name="Same")
    dup = new_client(client, owner, location_id, first_name="Jo", last_name="Same")
    signed = issue(client, owner, dup, location_id, tpl["id"])
    ok(sign(client, owner, signed))
    ok(client.put(f"{API}/client-document-statuses/{keep['id']}/waiver-override", headers=owner,
                  json={"waiver_override": "not_on_file"}))  # fmt: skip
    ok(client.post(f"{API}/clients/{keep['id']}/merge", headers=owner, json={"merged_client_ids": [dup["id"]]}))
    moved = ok(client.get(f"{API}/client-documents/{signed['id']}", headers=owner))
    assert moved["client_id"] == keep["id"]
    statuses = scalar(tenant, select(ClientDocumentStatus.client_id).where(ClientDocumentStatus.client_id == dup["id"]))
    assert statuses is None
    status = ok(client.get(f"{API}/client-document-statuses?client_id[in]={keep['id']}", headers=owner))["data"][0]
    assert status["waiver_override"] == "not_on_file"

    pending = issue(client, owner, keep, location_id, tpl["id"])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        exported = service._export(session, keep["id"])
        assert len(exported["documents"]) == 2
        result = service._erase(session, keep["id"])
    assert result == {"retained_signed_documents": 1, "voided_pending_documents": 1}
    assert scalar(tenant, select(ClientDocument.status).where(ClientDocument.id == pending["id"])) == "voided"
    assert scalar(tenant, select(ClientDocument.status).where(ClientDocument.id == signed["id"])) == "accepted"
