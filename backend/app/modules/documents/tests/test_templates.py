"""Templates and versions (DOC-01), bindings and requirements (DOC-08, DOC-14), settings and permissions."""

from uuid import uuid4

import pytest

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.documents import service
from app.modules.documents.tests.support import API, issue, ok, sign, signer, template
from conftest import add_staff, login, new_client


@pytest.fixture
def location_id(client, owner):
    from app.modules.documents.tests.support import location

    return location(client, owner)


def test_draft_is_sanitised_versioned_and_published(client, owner, location_id):
    created = ok(client.post(f"{API}/document-templates", headers=owner, json={"name": "Waiver"}), 201)
    assert (created["status"], created["current_version"], created["has_draft"]) == ("draft", None, False)
    url = f"{API}/document-templates/{created['id']}"
    hostile = (
        '<p onclick="x()">Hi <script>alert(1)</script><img src="https://e.example/x.png">'
        '<a href="javascript:alert(1)">bad</a> <a href="https://ok.example">good</a></p>'
    )
    draft = ok(client.put(f"{url}/draft", headers=owner, json={"body_html": hostile, "acceptance_text": "I agree."}))
    for banned in ("script", "onclick", "<img", "javascript:"):
        assert banned not in draft["body_html"]
    assert (
        'href="https://ok.example"' in draft["body_html"] and 'rel="noopener noreferrer nofollow"' in draft["body_html"]
    )
    assert draft["version_number"] == 1 and draft["signature_blocks"] == [{"role": "client", "label": "Signature"}]
    unknown = client.put(
        f"{url}/draft", headers=owner, json={"body_html": "<p>{{client.ssn}}</p>", "acceptance_text": "x"}
    )
    assert unknown.json()["code"] == "unknown-merge-field"
    empty = client.put(f"{url}/draft", headers=owner, json={"body_html": "<script>x</script>", "acceptance_text": "x"})
    assert empty.status_code == 422
    guardian_only = {"body_html": "<p>x</p>", "acceptance_text": "x", "signature_blocks": [{"role": "guardian"}]}
    assert client.put(f"{url}/draft", headers=owner, json=guardian_only).status_code == 422
    twice = {
        "body_html": "<p>x</p>",
        "acceptance_text": "x",
        "signature_blocks": [{"role": "client"}, {"role": "client"}],
    }
    assert client.put(f"{url}/draft", headers=owner, json=twice).status_code == 422
    published = ok(client.post(f"{url}/publish", headers=owner))
    assert published["status"] == "active" and published["current_version"]["version_number"] == 1
    assert client.post(f"{url}/publish", headers=owner).json()["code"] == "no-draft"

    # A document pins the version it was issued from; a new version leaves it untouched.
    person = new_client(client, owner, location_id)
    first = issue(client, owner, person, location_id, created["id"])
    ok(client.put(f"{url}/draft", headers=owner, json={"body_html": "<p>Version two</p>", "acceptance_text": "Yes."}))
    assert ok(client.get(url, headers=owner))["has_draft"] is True
    ok(client.post(f"{url}/publish", headers=owner))
    versions = ok(client.get(f"{url}/versions", headers=owner))["data"]
    assert [v["version_number"] for v in versions] == [2, 1]
    assert ok(client.get(f"{API}/client-documents/{first['id']}", headers=owner))["body_html"] == first["body_html"]
    second = issue(client, owner, person, location_id, created["id"])
    assert "Version two" in second["body_html"] and second["template_version_id"] != first["template_version_id"]


def test_update_archive_restore_and_names(client, owner):
    tpl = template(client, owner, name="Release form", signature_validity_days=365)
    url = f"{API}/document-templates/{tpl['id']}"
    assert client.post(f"{API}/document-templates", headers=owner, json={"name": "release FORM"}).json()["code"] == (
        "already-exists"
    )
    updated = ok(client.patch(url, headers=owner, json={"description": "Annual", "name": None}))
    assert updated["description"] == "Annual" and updated["name"] == "Release form"
    binding = ok(client.put(f"{API}/document-bindings", headers=owner,
                            json={"scope_type": "package_plan", "scope_id": str(uuid4()), "template_id": tpl["id"]}))  # fmt: skip
    assert client.post(f"{url}/archive", headers=owner).json()["code"] == "in-use"
    assert client.delete(f"{API}/document-bindings/{binding['id']}", headers=owner).status_code == 204
    archived = ok(client.post(f"{url}/archive", headers=owner))
    assert archived["status"] == "archived"
    assert client.post(f"{url}/archive", headers=owner).status_code == 409
    assert (
        client.put(f"{url}/draft", headers=owner, json={"body_html": "<p>x</p>", "acceptance_text": "x"}).status_code
        == 409
    )
    assert client.post(f"{url}/publish", headers=owner).status_code == 409
    assert ok(client.post(f"{url}/restore", headers=owner))["status"] == "active"
    assert client.post(f"{url}/restore", headers=owner).status_code == 409
    listed = ok(client.get(f"{API}/document-templates?is_waiver=true&q=release", headers=owner))["data"]
    assert [t["id"] for t in listed] == [tpl["id"]]
    assert client.get(f"{API}/document-templates/{uuid4()}", headers=owner).status_code == 404


def test_one_active_consent_template(client, owner, location_id):
    template(client, owner, kind="consent", is_waiver=False)
    second = ok(
        client.post(f"{API}/document-templates", headers=owner, json={"name": "Consent 2", "kind": "consent"}), 201
    )
    url = f"{API}/document-templates/{second['id']}"
    ok(client.put(f"{url}/draft", headers=owner, json={"body_html": "<p>x</p>", "acceptance_text": "x"}))
    assert client.post(f"{url}/publish", headers=owner).json()["code"] == "consent-template-active"


def test_settings_and_location_settings(client, owner, location_id):
    assert ok(client.get(f"{API}/document-settings", headers=owner))["deleted_recovery_days"] == 30
    changed = ok(client.patch(f"{API}/document-settings", headers=owner, json={"email_link_ttl_hours": 24}))
    assert changed["email_link_ttl_hours"] == 24
    url = f"{API}/document-location-settings/{location_id}"
    assert ok(client.get(url, headers=owner))["is_consent_required"] is False
    assert (
        client.patch(url, headers=owner, json={"is_consent_required": True}).json()["code"]
        == "consent-template-missing"
    )
    template(client, owner, kind="consent", is_waiver=False)
    assert ok(client.patch(url, headers=owner, json={"is_consent_required": True}))["is_consent_required"] is True
    assert client.get(f"{API}/document-location-settings/{uuid4()}", headers=owner).status_code == 404


def test_bindings_and_requirements(client, owner, location_id, tenant):
    tpl = template(client, owner)
    person = new_client(client, owner, location_id)
    plan = str(uuid4())
    bad = client.put(
        f"{API}/document-bindings", headers=owner, json={"scope_type": "membership_plan", "scope_id": plan}
    )
    assert bad.status_code == 422
    assert client.put(f"{API}/document-bindings", headers=owner,
                      json={"scope_type": "membership_plan", "template_id": tpl["id"]}).status_code == 422  # fmt: skip
    assert client.put(f"{API}/document-bindings", headers=owner,
                      json={"scope_type": "membership_plan", "scope_id": plan, "template_id": str(uuid4())}).status_code == 422  # fmt: skip
    binding = ok(client.put(f"{API}/document-bindings", headers=owner,
                            json={"scope_type": "membership_plan", "scope_id": plan, "template_id": tpl["id"]}))  # fmt: skip
    again = ok(client.put(f"{API}/document-bindings", headers=owner, json={
        "scope_type": "membership_plan", "scope_id": plan, "template_id": tpl["id"], "is_enforced_at_desk": False}))  # fmt: skip
    assert again["id"] == binding["id"] and again["is_enforced_at_desk"] is False
    assert [b["id"] for b in ok(client.get(f"{API}/document-bindings?scope_id={plan}", headers=owner))["data"]] == [
        binding["id"]
    ]
    url = f"{API}/document-requirements?scope_type=membership_plan&scope_id={plan}&client_id={person['id']}"
    [req] = ok(client.get(url, headers=owner))["requirements"]
    assert (req["is_satisfied"], req["is_blocking"], req["pending_document_id"]) == (False, False, None)
    none = f"{API}/document-requirements?scope_type=rental_plan&scope_id={plan}&client_id={person['id']}"
    assert ok(client.get(none, headers=owner))["requirements"] == []

    # The selling context's internal calls: issue the pending document, then consume the acceptance.
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        doc = service.ensure_pending(session, binding["id"], person["id"], location_id)
        assert service.ensure_pending(session, binding["id"], person["id"], location_id).id == doc.id
        doc_id, sha = str(doc.id), doc.content_sha256
    ok(sign(client, owner, {"id": doc_id, "content_sha256": sha}))
    [req] = ok(client.get(url, headers=owner))["requirements"]
    assert req["is_satisfied"] and req["satisfied_by_document_id"] == doc_id

    # every_purchase: an acceptance used by one sale does not satisfy the next.
    ok(client.put(f"{API}/document-bindings", headers=owner, json={
        "scope_type": "membership_plan", "scope_id": plan, "template_id": tpl["id"], "frequency": "every_purchase"}))  # fmt: skip
    sale = ("billing", "invoice", uuid4())
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert service.requirements_for(session, "membership_plan", plan, person["id"])[0]["is_satisfied"]
        service.consume(session, [doc_id], sale)
        service.consume(session, [doc_id], ("billing", "invoice", uuid4()))  # already consumed: unchanged
        assert not service.requirements_for(session, "membership_plan", plan, person["id"])[0]["is_satisfied"]
        assert service.requirements_for(session, "membership_plan", plan, person["id"], source=sale)[0]["is_satisfied"]
    by_source = ok(client.get(f"{API}/client-documents?source_id={sale[2]}", headers=owner))["data"]
    assert [d["id"] for d in by_source] == [doc_id]


def test_program_default_and_custom_text_terms(client, owner, location_id, tenant):
    person = new_client(client, owner, location_id)
    ok(client.put(f"{API}/document-bindings", headers=owner,
                  json={"scope_type": "program_default", "custom_text": "Be kind <b>always</b>."}))  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        [req] = service.requirements_for(session, "program_group", uuid4(), person["id"], online=True)
        assert req["title"] == "Terms and conditions" and req["is_blocking"]
        doc = service.ensure_pending(session, req["binding_id"], person["id"], location_id)
        assert "Be kind" in doc.body_html and doc.template_id is None
    assert client.get(f"{API}/public/portal-terms", headers={"X-Tenant-Slug": tenant.slug}).status_code == 404
    ok(
        client.put(
            f"{API}/document-bindings", headers=owner, json={"scope_type": "portal_terms", "custom_text": "Play fair."}
        )
    )
    terms = ok(client.get(f"{API}/public/portal-terms", headers={"X-Tenant-Slug": tenant.slug}))
    assert terms.pop("terms_version_id")  # SSP-14: what the buyer saw, sent back with each portal sale
    assert terms == {"title": "Terms and conditions", "body_html": "<p>Play fair.</p>"}
    tpl = template(client, owner)
    ok(
        client.put(
            f"{API}/document-bindings", headers=owner, json={"scope_type": "portal_terms", "template_id": tpl["id"]}
        )
    )
    assert ok(client.get(f"{API}/public/portal-terms", headers={"X-Tenant-Slug": tenant.slug}))["title"] == tpl["name"]


def test_permissions_follow_the_matrix(client, owner, tenant, location_id):
    tpl = template(client, owner)
    person = new_client(client, owner, location_id)
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[location_id])[0])
    coach = login(client, tenant, add_staff(tenant, "coach", location_ids=[location_id])[0])
    assert client.post(f"{API}/document-templates", headers=desk, json={"name": "X"}).status_code == 403
    assert client.get(f"{API}/document-templates", headers=desk).status_code == 200
    doc = issue(client, desk, person, location_id, tpl["id"])
    assert sign(client, desk, doc).status_code == 200
    assert client.post(f"{API}/client-documents/{doc['id']}/void", headers=desk).status_code == 403
    assert client.get(f"{API}/document-templates", headers=coach).status_code == 403
    # A coach reads documents of their own clients only: this client is not theirs.
    assert client.get(f"{API}/client-documents/{doc['id']}", headers=coach).status_code == 404
    assert ok(client.get(f"{API}/client-documents", headers=coach))["data"] == []
    assert sign(client, coach, doc, signer()).status_code == 403
