"""Client photo (CLI-12) and note attachments (CLI-09), through the API on the real database."""

import threading
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.errors import Conflict
from app.modules.clients import files
from app.modules.clients.models import Client, ClientNoteAttachment
from app.modules.platform import privacy
from app.modules.platform.models import StoredFile
from conftest import add_staff, login, make_tenant, new_client, png_bytes, scalar

API = "/api/v1"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
SENTINEL = "zqxfilesentinel"


@pytest.fixture
def location_id(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return client.post(f"{API}/locations", headers=owner, json=body).json()["id"]


def _put_photo(client, headers, client_id, data, kind="image/png"):
    return client.put(f"{API}/clients/{client_id}/photo", headers=headers | {"Content-Type": kind}, content=data)


def _note(client, headers, client_id) -> str:
    body = {"kind": "call", "subject_text": "Call", "body": "Asked about lessons"}
    return client.post(f"{API}/clients/{client_id}/notes", headers=headers, json=body).json()["id"]


def _attach(client, headers, note_id, data=PDF, kind="application/pdf", name="waiver scan.pdf"):
    headers = headers | {"Content-Type": kind, "X-File-Name": name}
    return client.post(f"{API}/client-notes/{note_id}/attachments", headers=headers, content=data)


def test_photo_upload_replace_and_remove(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    url = f"{API}/clients/{person['id']}/photo"
    assert client.get(url, headers=owner).status_code == 404
    first = _put_photo(client, owner, person["id"], png_bytes())
    assert first.status_code == 200 and first.json()["photo_file_id"]
    got = client.get(url, headers=owner)
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff" and got.content.startswith(b"\x89PNG")
    listed = client.get(f"{API}/clients", headers=owner).json()["data"]
    assert listed[0]["photo_file_id"] == first.json()["photo_file_id"]

    jpeg_png = png_bytes((8, 8))
    replaced = _put_photo(client, owner, person["id"], jpeg_png)
    assert replaced.json()["photo_file_id"] != first.json()["photo_file_id"]
    assert client.delete(url, headers=owner).status_code == 204
    assert client.get(url, headers=owner).status_code == 404
    assert client.delete(url, headers=owner).status_code == 404
    with tenant_session(tenant.id) as session:
        changes = session.scalars(select(AuditEvent.changes).where(
            AuditEvent.entity_id == person["id"], AuditEvent.action == "clients.client.update")).all()  # fmt: skip
    assert len(changes) == 3 and all(c["photo_file_id"] is True for c in changes)  # flag only, never the id


@pytest.mark.parametrize(
    ("data", "kind", "code"),
    [
        (b"not an image at all", "image/png", "file-type-mismatch"),
        (b"<html><script>alert(1)</script></html>", "image/jpeg", "file-type-mismatch"),  # HTML named .jpg
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml", "file-type-mismatch"),
        (PDF, "application/pdf", "file-type-mismatch"),  # a PDF is no photo
        (b"", "image/png", "file-empty"),
        # over api.max_body_bytes: refused before the route (413) until Phase 8 lists the route in UPLOAD_PATHS
        (b"\x89PNG\r\n\x1a\n" + b"0" * 5_242_881, "image/png", "payload-too-large"),
    ],
)
def test_photo_refuses_what_is_not_a_small_image(client, owner, location_id, data, kind, code):
    person = new_client(client, owner, location_id)
    response = _put_photo(client, owner, person["id"], data, kind)
    assert response.status_code in (413, 422) and response.json()["code"] == code


def test_photo_needs_the_key_and_the_reach(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    _put_photo(client, owner, person["id"], png_bytes())
    viewer = login(client, tenant, add_staff(tenant, "view_only", location_ids=[location_id])[0])
    assert _put_photo(client, viewer, person["id"], png_bytes()).status_code == 403
    coach = login(client, tenant, add_staff(tenant, "coach", location_ids=[location_id])[0])
    assert client.get(f"{API}/clients/{person['id']}/photo", headers=coach).status_code == 404  # not their client
    assert _put_photo(client, coach, person["id"], png_bytes()).status_code == 404


def test_a_file_of_another_purpose_is_not_a_photo(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    note_id = _note(client, owner, person["id"])
    _attach(client, owner, note_id, png_bytes(), "image/png")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        row = session.scalars(select(ClientNoteAttachment)).one()
        session.get(Client, person["id"]).photo_file_id = row.stored_file_id
    assert client.get(f"{API}/clients/{person['id']}/photo", headers=owner).status_code == 404


def test_attachments_upload_list_download_and_remove(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    note_id = _note(client, owner, person["id"])
    added = _attach(client, owner, note_id)
    assert added.status_code == 201, added.text
    item = added.json()
    assert item["content_type"] == "application/pdf" and item["file_name"] == "waiver scan.pdf"
    url = f"{API}/client-notes/{note_id}/attachments"
    assert [a["id"] for a in client.get(url, headers=owner).json()] == [item["id"]]
    got = client.get(f"{url}/{item['id']}", headers=owner)
    assert got.status_code == 200 and got.content == PDF
    assert got.headers["content-disposition"].startswith("attachment;")
    with tenant_session(tenant.id) as session:
        stored = session.get(StoredFile, session.get(ClientNoteAttachment, item["id"]).stored_file_id)
        assert stored.purpose == "client_attachment" and "waiver" not in stored.object_key
    assert (
        _attach(client, owner, note_id, b"<html></html>", "image/jpeg", "x.jpg").json()["code"] == "file-type-mismatch"
    )
    for _ in range(4):
        _attach(client, owner, note_id)
    assert _attach(client, owner, note_id).json()["code"] == "too-many-attachments"
    assert client.delete(f"{url}/{item['id']}", headers=owner).status_code == 204
    assert client.get(f"{url}/{item['id']}", headers=owner).status_code == 404
    assert len(client.get(url, headers=owner).json()) == 4
    assert client.delete(f"{API}/client-notes/{note_id}", headers=owner).status_code == 204  # cascades the links
    assert scalar(tenant, select(ClientNoteAttachment.id)) is None


def test_attachments_follow_the_note_reach(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    note_id = _note(client, owner, person["id"])
    item = _attach(client, owner, note_id).json()
    url = f"{API}/client-notes/{note_id}/attachments"
    league = login(client, tenant, add_staff(tenant, "league_admin", location_ids=[location_id])[0])
    assert client.get(url, headers=league).status_code == 403  # no clients.activity.read
    coach = login(client, tenant, add_staff(tenant, "coach", location_ids=[location_id])[0])
    assert client.get(url, headers=coach).status_code == 404  # the client is outside the coach's reach
    assert client.get(f"{url}/{item['id']}", headers=coach).status_code == 404
    assert _attach(client, coach, note_id).status_code == 404


def test_cross_client_and_cross_tenant_file_ids_are_404(client, tenant, owner, location_id):
    a, b = new_client(client, owner, location_id), new_client(client, owner, location_id, first_name="Other")
    note_a, note_b = _note(client, owner, a["id"]), _note(client, owner, b["id"])
    item_b = _attach(client, owner, note_b).json()
    assert client.get(f"{API}/client-notes/{note_a}/attachments/{item_b['id']}", headers=owner).status_code == 404
    assert client.delete(f"{API}/client-notes/{note_a}/attachments/{item_b['id']}", headers=owner).status_code == 404
    other = make_tenant()
    other_owner = login(client, other)
    assert client.get(f"{API}/client-notes/{note_b}/attachments/{item_b['id']}", headers=other_owner).status_code == 404
    assert client.get(f"{API}/clients/{b['id']}/photo", headers=other_owner).status_code == 404


def test_merge_keeps_or_takes_the_photo_and_moves_attachments(client, tenant, owner, location_id):
    survivor = new_client(client, owner, location_id, first_name="Sam")
    loser = new_client(client, owner, location_id, first_name="Sammy", last_name=survivor["last_name"])
    photo = _put_photo(client, owner, loser["id"], png_bytes()).json()["photo_file_id"]
    note_id = _note(client, owner, loser["id"])
    item = _attach(client, owner, note_id).json()
    merged = client.post(f"{API}/clients/{survivor['id']}/merge", headers=owner,
                         json={"merged_client_ids": [loser["id"]]})  # fmt: skip
    assert merged.status_code == 200 and merged.json()["photo_file_id"] == photo  # survivor had none: takes it
    assert client.get(f"{API}/client-notes/{note_id}/attachments/{item['id']}", headers=owner).status_code == 200

    keeper = new_client(client, owner, location_id, first_name="Kim")
    own = _put_photo(client, owner, keeper["id"], png_bytes()).json()["photo_file_id"]
    dupe = new_client(client, owner, location_id, first_name="Kimmy", last_name=keeper["last_name"])
    _put_photo(client, owner, dupe["id"], png_bytes((6, 6)))
    kept = client.post(f"{API}/clients/{keeper['id']}/merge", headers=owner, json={"merged_client_ids": [dupe["id"]]})
    assert kept.json()["photo_file_id"] == own  # survivor keeps its own


def test_erasure_nulls_the_photo_and_purges_the_file_rows(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    photo = _put_photo(client, owner, person["id"], png_bytes()).json()["photo_file_id"]
    _attach(client, owner, _note(client, owner, person["id"]), name=f"{SENTINEL} medical.pdf")
    with tenant_session(tenant.id) as session:
        attached = session.scalar(select(ClientNoteAttachment.stored_file_id))
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        privacy.HANDLERS["clients"].erase(session, person["id"])
    with tenant_session(tenant.id) as session:
        assert session.get(Client, person["id"]).photo_file_id is None
        assert session.scalar(select(ClientNoteAttachment.id)) is None
        rows = session.scalars(select(StoredFile).where(StoredFile.id.in_([photo, attached]))).all()
        assert [(r.status, r.original_name) for r in rows] == [("purged", None)] * 2
        assert session.scalar(select(StoredFile.id).where(StoredFile.original_name.ilike(f"%{SENTINEL}%"))) is None
    assert client.get(f"{API}/clients/{person['id']}/photo", headers=owner).status_code == 404


def test_export_lists_note_attachments(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    _attach(client, owner, _note(client, owner, person["id"]))
    body = {"client_id": person["id"], "kind": "export"}
    export = client.post(f"{API}/data-subject-requests", headers=owner, json=body).json()
    bundle = client.get(f"{API}/data-subject-requests/{export['id']}", headers=owner).json()["bundle"]
    [note] = bundle["clients"][person["id"]]["notes"]
    assert note["attachments"] == [
        {"file_name": "waiver scan.pdf", "content_type": "application/pdf", "size_bytes": len(PDF)}
    ]


def test_photo_of_an_erased_client_cannot_be_removed(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    _put_photo(client, owner, person["id"], png_bytes())
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.get(Client, person["id"]).erased_at = clock.now()  # a live photo on an erased record: refuse edits
    response = client.delete(f"{API}/clients/{person['id']}/photo", headers=owner)
    assert response.status_code == 409


def test_concurrent_uploads_respect_the_per_note_cap(client, tenant, owner, location_id):
    """The second upload waits on the note lock held by the first, then sees the cap reached."""
    note_id = UUID(_note(client, owner, new_client(client, owner, location_id)["id"]))
    for _ in range(files.MAX_ATTACHMENTS_PER_NOTE - 1):
        _attach(client, owner, str(note_id))
    system = system_principal("tests")
    outcome = {}

    def second() -> None:
        try:
            with tenant_session(tenant.id, actor=system) as session:
                files.add_attachment(session, system, note_id, PDF, "application/pdf", "b.pdf")
            outcome["second"] = "added"
        except Conflict:
            outcome["second"] = "refused"

    with tenant_session(tenant.id, actor=system) as session:
        files.add_attachment(session, system, note_id, PDF, "application/pdf", "a.pdf")
        racer = threading.Thread(target=second)
        racer.start()
        racer.join(timeout=1.5)  # blocked on the lock until this transaction commits
    racer.join(timeout=15)
    assert outcome == {"second": "refused"}
    assert len(client.get(f"{API}/client-notes/{note_id}/attachments", headers=owner).json()) == 5
