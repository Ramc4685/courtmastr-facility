"""resources lockers (RES-07..09): rooms, bulk lockers, terms, and padlocks whose combination is encrypted,
revealed only under its own key, and audited without the value."""

import hashlib
import json
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.core import crypto
from app.core.audit import AuditEvent
from app.core.db.session import tenant_session
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import add_staff, login


@pytest.fixture
def f(client, owner):
    f = facility(client, owner)
    f.room = ok(client.post(f"{API}/locker-rooms", headers=owner, json={"location_id": f.location, "name": "East"}))
    return f


def lockers(client, headers, f) -> list[dict]:
    page = ok(client.get(f"{API}/lockers", headers=headers, params={"locker_room_id": f.room["id"]}), 200)
    return sorted(page["data"], key=lambda r: r["number"])


def test_rooms_bulk_lockers_and_terms(client, owner, f):
    bulk = f"{API}/locker-rooms/{f.room['id']}/lockers/bulk"
    assert ok(client.post(bulk, headers=owner, json={"from_number": 1, "to_number": 3, "size_label": "Half"})) == {
        "created_count": 3, "skipped_count": 0,
    }  # fmt: skip
    assert ok(client.post(bulk, headers=owner, json={"from_number": 3, "to_number": 4})) == {
        "created_count": 1, "skipped_count": 1,
    }  # fmt: skip
    assert client.post(bulk, headers=owner, json={"from_number": 5, "to_number": 2}).status_code == 422
    assert client.post(bulk, headers=owner, json={"from_number": 1, "to_number": 600}).status_code == 422
    board = lockers(client, owner, f)
    assert [r["number"] for r in board] == [1, 2, 3, 4]
    assert {r["state"] for r in board} == {"available"} and board[0]["locker_room_name"] == "East"
    duplicate = client.post(f"{API}/locker-rooms", headers=owner, json={"location_id": f.location, "name": "East"})
    assert duplicate.status_code == 409
    renamed = ok(client.patch(f"{API}/locker-rooms/{f.room['id']}", headers=owner, json={"designation": "female"}), 200)
    assert renamed["designation"] == "female"
    ok(client.patch(f"{API}/locker-rooms/{f.room['id']}", headers=owner, json={"is_active": False}), 200)
    closed = client.post(bulk, headers=owner, json={"from_number": 9, "to_number": 9})
    assert closed.status_code == 409 and closed.json()["code"] == "locker-room-inactive"
    term = {"location_id": f.location, "name": "Fall", "starts_on": "2030-09-01", "ends_on": "2030-12-31"}
    created = ok(client.post(f"{API}/locker-terms", headers=owner, json=term | {"price_minor": 4000}))
    backwards = client.patch(f"{API}/locker-terms/{created['id']}", headers=owner, json={"ends_on": "2030-08-01"})
    assert backwards.status_code == 422
    listed = ok(client.get(f"{API}/locker-terms", headers=owner, params={"location_id": f.location}), 200)["data"]
    assert [(t["name"], t["price_minor"]) for t in listed] == [("Fall", 4000)]


def test_padlock_combination_is_encrypted_revealed_and_audited(client, owner, f, tenant):
    ok(client.post(f"{API}/locker-rooms/{f.room['id']}/lockers/bulk", headers=owner, json={"from_number": 1, "to_number": 1}))  # fmt: skip
    lock = ok(client.post(f"{API}/padlocks", headers=owner, json={"location_id": f.location, "number": "A-7", "combination": "10-20-30"}))  # fmt: skip
    assert "combination" not in lock and "combination_encrypted" not in lock
    with tenant_session(tenant.id) as session:
        stored = session.execute(
            text("SELECT combination_encrypted FROM padlock WHERE id = :i"), {"i": lock["id"]}
        ).scalar()
    assert "10-20-30" not in str(stored)
    again = client.post(f"{API}/padlocks", headers=owner, json={"location_id": f.location, "number": "A-7", "combination": "1"})  # fmt: skip
    assert again.status_code == 409
    locker = lockers(client, owner, f)[0]
    fitted = ok(client.patch(f"{API}/lockers/{locker['id']}", headers=owner, json={"padlock_id": lock["id"]}), 200)
    assert fitted["padlock_number"] == "A-7"
    ok(client.patch(f"{API}/padlocks/{lock['id']}", headers=owner, json={"combination": "40-50-60"}), 200)
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    assert ok(client.post(f"{API}/padlocks/{lock['id']}/reveal", headers=desk), 200)["combination"] == "40-50-60"
    coach = login(client, tenant, add_staff(tenant, "coach", location_ids=[f.location])[0])
    assert client.post(f"{API}/padlocks/{lock['id']}/reveal", headers=coach).status_code == 403
    assert client.post(f"{API}/padlocks", headers=desk, json={"location_id": f.location, "number": "B", "combination": "1"}).status_code == 403  # fmt: skip
    with tenant_session(tenant.id) as session:
        trail = session.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == UUID(lock["id"])).order_by(AuditEvent.occurred_at)
        ).all()
    assert [a.action for a in trail] == [
        "resources.padlock.manage", "resources.padlock.manage", "resources.padlock.reveal_combination",
    ]  # fmt: skip
    assert all("40-50-60" not in str(a.changes) and "10-20-30" not in str(a.changes) for a in trail)
    assert client.delete(f"{API}/padlocks/{lock['id']}", headers=owner).status_code == 204
    assert lockers(client, owner, f)[0]["padlock_id"] is None
    assert client.post(f"{API}/padlocks/{lock['id']}/reveal", headers=owner).status_code == 404
    reused = client.post(f"{API}/padlocks", headers=owner, json={"location_id": f.location, "number": "A-7", "combination": "2"})  # fmt: skip
    assert reused.status_code == 201  # the number frees up once the padlock is deleted


def test_reveal_response_is_never_stored_or_replayed(client, owner, f, tenant):
    """A secret response is not kept in idempotency_key (plaintext at rest) and a replayed key gets 409, not the
    combination; the stored request hash is keyed, so it cannot be brute-forced back to a short combination."""
    body = json.dumps({"location_id": f.location, "number": "C-1", "combination": "1-2-3"}).encode()
    create = owner | {"Idempotency-Key": "pad-create-1", "Content-Type": "application/json"}
    lock = ok(client.post(f"{API}/padlocks", headers=create, content=body))
    reveal = f"{API}/padlocks/{lock['id']}/reveal"
    keyed = owner | {"Idempotency-Key": "reveal-once-1"}
    assert ok(client.post(reveal, headers=keyed), 200)["combination"] == "1-2-3"
    replay = client.post(reveal, headers=keyed)
    assert replay.status_code == 409 and replay.json()["code"] == "response-not-stored"
    assert "1-2-3" not in replay.text
    with tenant_session(tenant.id) as session:
        rows = session.execute(text(
            "SELECT key, response_body::text, request_hash FROM idempotency_key WHERE key IN ('reveal-once-1', 'pad-create-1')"
        )).all()  # fmt: skip
    stored = {key: (response, digest) for key, response, digest in rows}
    assert stored["reveal-once-1"][0] in (None, "null")  # JSONB None is stored as JSON null
    raw = b"POST/api/v1/padlocks" + body
    assert stored["pad-create-1"][1] == crypto.mac_bytes(raw) != hashlib.sha256(raw).hexdigest()


def test_padlock_must_match_the_locker_location(client, owner, f):
    ok(client.post(f"{API}/locker-rooms/{f.room['id']}/lockers/bulk", headers=owner, json={"from_number": 1, "to_number": 1}))  # fmt: skip
    other = facility(client, owner, "America/New_York")
    lock = ok(client.post(f"{API}/padlocks", headers=owner, json={"location_id": other.location, "number": "Z", "combination": "9"}))  # fmt: skip
    bad = client.patch(
        f"{API}/lockers/{lockers(client, owner, f)[0]['id']}", headers=owner, json={"padlock_id": lock["id"]}
    )
    assert bad.status_code == 422
