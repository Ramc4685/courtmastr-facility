"""DOC-11: an issued membership agreement bound to its contract, shown on it, and kept on erasure as signed
waivers are."""

from uuid import UUID

from app.core.db import tenant_session
from app.modules.documents import service as documents
from app.modules.documents.tests.support import issue, sign, template
from app.modules.memberships import service
from app.modules.memberships.tests.support import API, SYSTEM, contract, ok, refused, sale, world
from conftest import new_client


def test_bind_shows_the_agreement_and_erasure_keeps_both(client, owner, tenant):
    w = world(client, owner, tenant)
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    agreement = issue(client, owner, w.person, w.location_id, template(client, owner, is_waiver=False)["id"])
    ok(sign(client, owner, agreement))
    url = f"{API}/membership-contracts/{sold['id']}/agreement"

    bound = ok(client.put(url, headers=owner, json={"client_document_id": agreement["id"]}))
    assert bound["client_document_id"] == agreement["id"] and bound["version"] == sold["version"] + 1
    assert (
        ok(client.put(url, headers=owner, json={"client_document_id": agreement["id"]}))["version"] == bound["version"]
    )
    shown = ok(client.get(f"{API}/membership-contracts/{sold['id']}", headers=owner))
    assert shown["client_document_id"] == agreement["id"]

    with tenant_session(tenant.id, actor=SYSTEM) as session:
        documents._erase(session, UUID(w.person["id"]))
        service._erase(session, UUID(w.person["id"]))
    assert contract(tenant, sold["id"]).client_document_id == UUID(agreement["id"])
    assert ok(client.get(f"{API}/client-documents/{agreement['id']}", headers=owner))["status"] == "accepted"


def test_only_a_live_document_of_the_owner_binds(client, owner, tenant):
    w = world(client, owner, tenant)
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    tpl = template(client, owner, is_waiver=False)["id"]
    url = f"{API}/membership-contracts/{sold['id']}/agreement"
    someone_else = issue(client, owner, new_client(client, owner, w.location_id), w.location_id, tpl)
    refused(client.put(url, headers=owner, json={"client_document_id": someone_else["id"]}), 422, "validation-failed")
    voided = issue(client, owner, w.person, w.location_id, tpl)
    ok(client.post(f"{API}/client-documents/{voided['id']}/void", headers=owner, json={"reason": "Wrong one"}))
    refused(client.put(url, headers=owner, json={"client_document_id": voided["id"]}), 422, "validation-failed")
