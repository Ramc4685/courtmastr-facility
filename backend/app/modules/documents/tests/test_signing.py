"""Issuing, in-person signing with evidence, guardians, statuses, the waiver indicator, uploads and the PDF
(DOC-02, DOC-03, DOC-05, DOC-06, DOC-15)."""

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.documents import service
from app.modules.documents.models import ClientDocument, DocumentAcceptance
from app.modules.documents.tests.support import (
    API,
    born,
    issue,
    location,
    ok,
    png,
    png_b64,
    sign,
    signer,
    template,
    today,
)
from conftest import new_client, scalar


@pytest.fixture
def location_id(client, owner):
    return location(client, owner)


def _status(client, headers, client_id) -> dict:
    return ok(client.get(f"{API}/client-document-statuses?client_id[in]={client_id}", headers=headers))["data"][0]


def test_issue_merges_escaped_values_and_renders_a_pdf(client, owner, location_id):
    tpl = template(client, owner)
    person = new_client(client, owner, location_id, first_name="<b>Ann</b>")
    doc = issue(client, owner, person, location_id, tpl["id"])
    assert doc["status"] == "pending" and doc["required_roles"] == ["client"]
    assert "&lt;b&gt;Ann&lt;/b&gt;" in doc["body_html"] and "Main" in doc["body_html"]
    assert len(doc["content_sha256"]) == 64 and doc["rendered_file_id"]
    response = client.get(f"{API}/client-documents/{doc['id']}/file", headers=owner)
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert (
        response.headers["content-disposition"].startswith("attachment")
        and response.headers["x-content-type-options"] == "nosniff"
    )
    assert client.get(f"{API}/client-documents/{doc['id']}/file?variant=paper_scan", headers=owner).status_code == 404
    assert client.post(f"{API}/client-documents", headers=owner, json={
        "client_id": person["id"], "location_id": location_id, "acceptance_method": "checkbox"}).status_code == 422  # fmt: skip
    assert client.post(f"{API}/client-documents", headers=owner, json={
        "client_id": person["id"], "location_id": location_id, "template_id": tpl["id"],
        "acceptance_method": "email_link"}).status_code == 422  # fmt: skip


def test_in_person_signature_records_evidence(client, owner, location_id, tenant):
    tpl = template(client, owner, signature_validity_days=365)
    person = new_client(client, owner, location_id)
    doc = issue(client, owner, person, location_id, tpl["id"])
    assert sign(client, owner, doc | {"content_sha256": "0" * 64}).json()["code"] == "content-mismatch"
    assert sign(client, owner, doc, signer(typed_signature=" ")).status_code == 422
    assert sign(client, owner, doc, signer(method="drawn_signature")).status_code == 422
    assert sign(client, owner, doc, signer(method="drawn_signature", signature_png="@@notbase64")).status_code == 422
    assert sign(client, owner, doc, signer(role="guardian")).status_code == 422  # adult: no guardian block
    assert sign(client, owner, doc, signer(signer_client_id=str(uuid4()))).status_code == 422
    signed = ok(sign(client, owner, doc, signer(method="drawn_signature", signature_png=png_b64()),
                     user_agent="DeskTablet/1.0"))  # fmt: skip
    assert signed["status"] == "accepted" and signed["decided_at"]
    assert date.fromisoformat(signed["expires_on"]) >= today() + timedelta(days=364)
    [evidence] = signed["acceptances"]
    assert (
        evidence["method"] == "drawn_signature"
        and evidence["signature_file_id"]
        and evidence["witnessed_by_staff_user_id"]
    )
    row = scalar(tenant, select(DocumentAcceptance).where(DocumentAcceptance.client_document_id == doc["id"]))
    # ip comes from the request context; the test client's peer ("testclient") is not an address, so it is null here
    assert row.user_agent == "DeskTablet/1.0" and row.content_sha256 == doc["content_sha256"]
    assert sign(client, owner, doc).status_code == 409
    assert _status(client, owner, person["id"])["is_waiver_on_file"] is True
    pdf = client.get(f"{API}/client-documents/{doc['id']}/file", headers=owner).content
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000
    audited = scalar(tenant, select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == doc["id"]))
    assert audited >= 2  # issued, then signed


def test_decline_and_co_signer(client, owner, location_id):
    tpl = template(client, owner, blocks=[{"role": "client"}, {"role": "co_signer", "label": "Witness"}])
    person = new_client(client, owner, location_id)
    doc = issue(client, owner, person, location_id, tpl["id"])
    assert doc["required_roles"] == ["client", "co_signer"]
    assert ok(sign(client, owner, doc))["status"] == "pending"
    assert sign(client, owner, doc).json()["code"] == "already-exists"
    assert ok(sign(client, owner, doc, signer(role="co_signer", method="checkbox")))["status"] == "accepted"
    other = issue(client, owner, person, location_id, tpl["id"])
    assert ok(sign(client, owner, other, signer(decision="declined", method="checkbox")))["status"] == "declined"


def test_minor_needs_a_guardian(client, owner, location_id):
    tpl = template(client, owner)
    kid = new_client(client, owner, location_id, birth_on=born(10))
    doc = issue(client, owner, kid, location_id, tpl["id"])
    assert doc["requires_guardian"] and doc["required_roles"] == ["guardian"]
    assert ok(sign(client, owner, doc))["status"] == "pending"  # the minor's own signature is optional
    # No guardian on file: staff may witness a named guardian.
    assert ok(sign(client, owner, doc, signer(role="guardian", signer_name="Pat Parent")))["status"] == "accepted"

    parent = new_client(client, owner, location_id)
    types = {t["code"]: t for t in client.get(f"{API}/relationship-types", headers=owner).json()}
    ok(client.post(f"{API}/clients/{parent['id']}/relationships", headers=owner,
                   json={"other_client_id": kid["id"], "relationship_type_id": types["parent_of"]["id"]}), 201)  # fmt: skip
    second = issue(client, owner, kid, location_id, tpl["id"])
    assert sign(client, owner, second, signer(role="guardian")).json()["code"] == "guardian-required"
    assert sign(client, owner, second, signer(role="guardian", signer_client_id=kid["id"])).status_code == 422
    done = ok(sign(client, owner, second, signer(role="guardian", signer_client_id=parent["id"])))
    assert done["status"] == "accepted" and done["acceptances"][0]["signer_client_id"] == parent["id"]


def test_void_delete_restore_and_recovery_window(client, owner, location_id, tenant):
    tpl = template(client, owner)
    person = new_client(client, owner, location_id)
    doc = issue(client, owner, person, location_id, tpl["id"])
    ok(sign(client, owner, doc))
    assert client.delete(f"{API}/client-documents/{doc['id']}", headers=owner).status_code == 204
    assert _status(client, owner, person["id"])["is_waiver_on_file"] is False
    assert ok(client.get(f"{API}/client-documents?client_id={person['id']}", headers=owner))["data"] == []
    deleted = ok(client.get(f"{API}/client-documents?client_id={person['id']}&is_deleted=true", headers=owner))["data"]
    assert [d["id"] for d in deleted] == [doc["id"]]
    assert client.delete(f"{API}/client-documents/{doc['id']}", headers=owner).status_code == 404
    restored = ok(client.post(f"{API}/client-documents/{doc['id']}/restore", headers=owner))
    assert restored["deleted_at"] is None and _status(client, owner, person["id"])["is_waiver_on_file"] is True
    assert client.post(f"{API}/client-documents/{doc['id']}/restore", headers=owner).status_code == 409

    assert client.delete(f"{API}/client-documents/{doc['id']}", headers=owner).status_code == 204
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(ClientDocument).where(ClientDocument.id == doc["id"])
                        .values(deleted_at=clock.now() - timedelta(days=31)))  # fmt: skip
    assert client.post(f"{API}/client-documents/{doc['id']}/restore", headers=owner).json()["code"] == (
        "recovery-window-lapsed"
    )
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert service.run_sweeps(session)["voided"] == 1
        assert service.run_sweeps(session) == {"expired": 0, "voided": 0, "links_expired": 0}
    assert scalar(tenant, select(ClientDocument.status).where(ClientDocument.id == doc["id"])) == "voided"

    other = issue(client, owner, person, location_id, tpl["id"])
    voided = ok(client.post(f"{API}/client-documents/{other['id']}/void", headers=owner))
    assert voided["status"] == "voided"
    assert client.post(f"{API}/client-documents/{other['id']}/void", headers=owner).status_code == 409
    assert sign(client, owner, other).status_code == 409


def test_expiry_sweep_and_override(client, owner, location_id, tenant):
    tpl = template(client, owner, signature_validity_days=30)
    person = new_client(client, owner, location_id)
    doc = issue(client, owner, person, location_id, tpl["id"])
    ok(sign(client, owner, doc))
    assert _status(client, owner, person["id"])["waiver_valid_until_on"]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(ClientDocument).where(ClientDocument.id == doc["id"])
                        .values(expires_on=today() - timedelta(days=2)))  # fmt: skip
        service.refresh_status(session, UUID(person["id"]))  # as if signed 32 days ago
        assert service.status_for(session, [UUID(person["id"])])[UUID(person["id"])]["waiver_valid_until_on"]
        assert service.has_valid_waiver(session, UUID(person["id"])) is False  # the date test applies before the sweep
        session.flush()
    assert service.sweep_documents.fn(str(tenant.id))["expired"] == 1  # the queued actor, run inline
    assert ok(client.get(f"{API}/client-documents/{doc['id']}", headers=owner))["status"] == "expired"
    status = _status(client, owner, person["id"])
    assert status["is_waiver_on_file"] is False and status["waiver_valid_until_on"] is None

    url = f"{API}/client-document-statuses/{person['id']}/waiver-override"
    set_ = ok(client.put(url, headers=owner, json={"waiver_override": "on_file", "note": "Paper copy in the binder"}))
    assert set_["is_waiver_on_file"] is True and set_["waiver_override_note"] == "Paper copy in the binder"
    assert client.delete(url, headers=owner).status_code == 204
    assert client.delete(url, headers=owner).status_code == 204  # idempotent
    assert _status(client, owner, person["id"])["is_waiver_on_file"] is False
    renewed = issue(client, owner, person, location_id, tpl["id"])  # renewal is a fresh issue of the current version
    ok(sign(client, owner, renewed))
    assert _status(client, owner, person["id"])["is_waiver_on_file"] is True
    assert client.get(f"{API}/client-document-statuses?client_id[in]=nope", headers=owner).status_code == 422
    assert client.get(f"{API}/client-document-statuses?client_id[in]={uuid4()}", headers=owner).json()["data"] == []


def test_paper_upload_to_a_profile(client, owner, location_id):
    person = new_client(client, owner, location_id)
    doc = issue(client, owner, person, location_id, None, method="paper", title="Signed medical form")
    assert doc["status"] == "pending" and doc["rendered_file_id"] is None
    url = f"{API}/client-documents/{doc['id']}/paper-scan"
    bad = client.put(url, headers=owner | {"Content-Type": "application/pdf"}, content=b"not a pdf at all")
    assert bad.json()["code"] == "file-type-mismatch"
    assert client.put(url, headers=owner | {"Content-Type": "image/png"}, content=b"").json()["code"] == "file-empty"
    scan = png((800, 1000))
    uploaded = ok(
        client.put(url, headers=owner | {"Content-Type": "image/png", "X-File-Name": "form.png"}, content=scan)
    )
    assert (
        uploaded["status"] == "accepted"
        and uploaded["is_paper_signed"]
        and uploaded["acceptances"][0]["method"] == "paper"
    )
    got = client.get(f"{API}/client-documents/{doc['id']}/file?variant=paper_scan", headers=owner)
    assert (
        got.status_code == 200
        and got.content.startswith(b"\x89PNG")
        and "form.png" in got.headers["content-disposition"]
    )
    again = ok(client.put(url, headers=owner | {"Content-Type": "image/png"}, content=scan))  # replace the copy
    assert len(again["acceptances"]) == 1
    cleared = ok(client.delete(url, headers=owner))
    assert cleared["status"] == "pending" and cleared["is_paper_signed"] is False
    assert client.delete(url, headers=owner).status_code == 409


def test_large_upload_passes_the_body_limit_only_on_the_upload_route(client, owner, location_id):
    person = new_client(client, owner, location_id)
    doc = issue(client, owner, person, location_id, None, method="paper", title="Big scan")
    payload = b"%PDF-1.4\n" + b"0" * 1_200_000
    response = client.put(f"{API}/client-documents/{doc['id']}/paper-scan",
                          headers=owner | {"Content-Type": "application/pdf"}, content=payload)  # fmt: skip
    assert response.status_code != 413
    too_big = client.post(f"{API}/document-templates", headers=owner | {"Content-Type": "application/json"},
                          content=b'{"name": "' + b"x" * 1_200_000 + b'"}')  # fmt: skip
    assert too_big.status_code == 413
