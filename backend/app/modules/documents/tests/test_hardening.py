"""Wave 1 hardening, batch people: P-08 to P-10 (docs/security/wave1-hardening-spec.md section 4)."""

import pytest
from sqlalchemy import select

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.documents.models import ClientDocument, DocumentAcceptance
from app.modules.documents.tests.support import API, born, issue, location, ok, png, sign, signer, template
from conftest import PASSWORD, add_staff, link_token, login, new_client, verify_email


@pytest.fixture
def location_id(client, owner):
    return location(client, owner)


def _evidence(tenant, doc_id) -> tuple[str, list]:
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        doc = session.get(ClientDocument, doc_id)
        rows = session.scalars(select(DocumentAcceptance.id).where(DocumentAcceptance.client_document_id == doc_id))
        return doc.content_sha256, sorted(rows)


def test_bulk_status_respects_reach(client, tenant, owner, location_id):
    email, coach_id = add_staff(tenant, "coach", location_ids=[location_id])
    coach = login(client, tenant, email)
    mine, theirs = new_client(client, owner, location_id), new_client(client, owner, location_id)
    client.put(
        f"{API}/clients/{mine['id']}/owners", headers=owner, json={"default_trainer_staff_user_id": str(coach_id)}
    )
    tpl = template(client, owner)
    for person in (mine, theirs):
        ok(sign(client, owner, issue(client, owner, person, location_id, tpl["id"])))
    url = f"{API}/client-document-statuses?client_id[in]={mine['id']},{theirs['id']}"
    assert [s["client_id"] for s in ok(client.get(url, headers=coach))["data"]] == [mine["id"]]
    assert len(ok(client.get(url, headers=owner))["data"]) == 2


def test_decided_evidence_is_immutable(client, tenant, owner, location_id):
    email, _ = add_staff(tenant, "front_desk", location_ids=[location_id])
    desk = login(client, tenant, email)
    person = new_client(client, owner, location_id)
    doc = issue(client, owner, person, location_id, None, method="paper", title="Signed form")
    url = f"{API}/client-documents/{doc['id']}/paper-scan"
    png_type = {"Content-Type": "image/png"}
    ok(client.put(url, headers=desk | png_type, content=png((300, 300))))  # pending: the desk collects it
    before = _evidence(tenant, doc["id"])
    replaced = client.put(url, headers=desk | png_type, content=png((400, 400)))
    assert replaced.status_code in (403, 409)
    assert client.delete(url, headers=desk).status_code in (403, 409)
    assert _evidence(tenant, doc["id"]) == before
    # a void-level user may replace the copy, and the hash still describes the signed file
    swapped = ok(client.put(url, headers=owner | png_type, content=png((500, 500))))
    assert swapped["status"] == "accepted" and _evidence(tenant, doc["id"]) == before


def test_signer_role_is_derived_not_chosen(client, tenant, owner, location_id, mailbox):
    tpl = template(client, owner)
    parent = new_client(client, owner, location_id, primary_email=f"pat@{tenant.slug}.example.com")
    verify_email(tenant, parent["id"], parent["primary_email"])
    adult = new_client(client, owner, location_id)
    types = {t["code"]: t for t in client.get(f"{API}/relationship-types", headers=owner).json()}
    ok(client.post(f"{API}/clients/{parent['id']}/relationships", headers=owner,
                   json={"other_client_id": adult["id"], "relationship_type_id": types["parent_of"]["id"]}), 201)  # fmt: skip
    # a link to the guardian's address never signs as the client
    issue(client, owner, adult, location_id, tpl["id"], method="email_link", recipient_emails=[parent["primary_email"]])
    token = link_token(mailbox[-1])
    view = ok(client.post(f"{API}/public/document-deliveries/open", json={"token": token}))
    body = {"token": token, "decision": "accepted", "content_sha256": view["content_sha256"], "signer_name": "Pat",
            "typed_signature": "Pat", "signer_role": "client"}  # fmt: skip
    refused = client.post(f"{API}/public/document-deliveries/decision", json=body)
    assert refused.status_code == 422 and refused.json()["errors"][0]["pointer"] == "/signer_role"

    # in the portal, signing someone else's document is only ever as their guardian
    ok(client.post(f"{API}/clients/{parent['id']}/portal-access/invite", headers=owner, json={}))
    ok(client.post(f"{API}/auth/invitations/accept", json={"token": link_token(mailbox[-1]), "new_password": PASSWORD}))
    portal = login(client, tenant, parent["primary_email"], audience="client")
    kid = ok(client.post(f"{API}/portal/dependents", headers=portal, json={
        "relationship_type_id": types["parent_of"]["id"], "first_name": "Kit", "last_name": "Pat",
        "birth_on": born(8)}), 201)  # fmt: skip
    doc = issue(client, owner, kid, location_id, tpl["id"])
    url = f"{API}/portal/client-documents/{doc['id']}/acceptances?client_id={kid['id']}"
    as_client = {"content_sha256": doc["content_sha256"], "signers": [signer("client")]}
    assert client.post(url, headers=portal, json=as_client).status_code == 422
    done = ok(
        client.post(
            url, headers=portal, json={"content_sha256": doc["content_sha256"], "signers": [signer("guardian")]}
        )
    )
    assert done["status"] == "accepted" and done["acceptances"][0]["signer_role"] == "guardian"
