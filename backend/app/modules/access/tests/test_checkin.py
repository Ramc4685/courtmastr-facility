"""Check-in end to end: staff window and profile (CHK-01, CHK-03), credentials (CHK-11, CHK-14), the log
(CHK-18, CHK-19), the kiosk (CHK-05, CHK-06) and portal app cards (CHK-13). Each route's security rule has a
case: both gates, out-of-scope 404, body location ids 422, portal reach through can_act_for."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import passwords, system_principal
from app.core.db import tenant_session
from app.modules import clients
from app.modules.access.domain import cards
from app.modules.access.models import CheckIn, Credential
from app.modules.platform.models import Identity
from conftest import PASSWORD, add_staff, login, make_tenant, new_client, populate, scalar

API = "/api/v1"


def ok(response, status=(200, 201)):
    assert response.status_code in ((status,) if isinstance(status, int) else status), response.text
    return response.json() if response.content else None


@pytest.fixture
def f(client, tenant, owner):
    loc = ok(client.post(f"{API}/locations", headers=owner,
                         json={"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}))["id"]  # fmt: skip
    other = ok(client.post(f"{API}/locations", headers=owner,
                           json={"name": "North", "time_zone": "America/Chicago", "country_code": "US"}))["id"]  # fmt: skip
    email, _ = add_staff(tenant, "front_desk", location_ids=[loc])
    person = new_client(client, owner, loc, first_name="Avery", last_name=f"Zephyr{uuid4().hex[:4]}")
    number = {"member_number": f"m{uuid4().hex[:6]}"}
    person = ok(client.post(f"{API}/clients/{person['id']}/member-number", headers=owner, json=number))
    return SimpleNamespace(loc=loc, other=other, desk=login(client, tenant, email), person=person)


def check_in(client, headers, body):
    return client.post(f"{API}/check-ins", headers=headers, json={"channel": "staff_window"} | body)


def test_staff_check_in_records_alerts_and_shows_in_the_log(client, tenant, owner, f):
    done = ok(check_in(client, f.desk, {"client_id": f.person["id"], "location_id": f.loc}), 201)
    row = done["check_in"]
    assert row["result"] == "granted" and row["identified_by"] == "client_record"
    assert {"code": "waiver_unsigned", "action": "sign_waiver"} in done["alerts"] and done["client"][
        "membership"
    ] is None
    assert ok(client.get(f"{API}/check-ins/{row['id']}", headers=f.desk))["id"] == row["id"]
    page = ok(client.get(f"{API}/check-ins?client_id={f.person['id']}", headers=f.desk))
    assert [r["id"] for r in page["data"]] == [row["id"]] and page["data"][0]["client_name"]
    assert ok(client.get(f"{API}/check-ins?location_id={f.other}", headers=owner))["data"] == []
    actions = scalar(tenant, select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == row["id"]))
    assert actions == 1
    dry = ok(client.post(f"{API}/check-ins/evaluate", headers=f.desk,
                         json={"client_id": f.person["id"], "location_id": f.loc}))  # fmt: skip
    assert dry["would_grant"] and not dry["would_consume_visit"]
    assert scalar(tenant, select(func.count()).select_from(CheckIn)) == 1  # the dry run wrote nothing
    # money detail needs access.checkin.read_full_details: the desk lacks it, the owner holds it
    assert done["client"]["balance_due_minor"] is None and dry["client"]["balance_due_minor"] is None
    full = ok(client.post(f"{API}/check-ins/evaluate", headers=owner,
                          json={"client_id": f.person["id"], "location_id": f.loc}))  # fmt: skip
    assert full["client"]["balance_due_minor"] == 0


def test_location_gates(client, tenant, owner, f):
    """A body location outside the caller's locations is 422; a check-in row there is 404 to them."""
    refused = check_in(client, f.desk, {"client_id": f.person["id"], "location_id": f.other})
    assert refused.status_code == 422 and refused.json()["errors"][0]["pointer"] == "/location_id"
    assert check_in(client, f.desk, {"client_id": f.person["id"], "location_id": str(uuid4())}).status_code == 422
    there = ok(check_in(client, owner, {"client_id": f.person["id"], "location_id": f.other}), 201)
    assert client.get(f"{API}/check-ins/{there['check_in']['id']}", headers=f.desk).status_code == 404
    seen = ok(client.get(f"{API}/check-ins", headers=f.desk))["data"]
    assert there["check_in"]["id"] not in [r["id"] for r in seen]
    bad = check_in(client, f.desk, {"location_id": f.loc})
    assert bad.status_code == 422  # neither client_id nor credential_value


def test_disabled_client_is_denied_and_override_needs_its_own_key(client, tenant, owner, f):
    ok(client.post(f"{API}/clients/{f.person['id']}/disable", headers=owner, json={"reason": "Left"}))
    denied = ok(check_in(client, f.desk, {"client_id": f.person["id"], "location_id": f.loc}), 201)
    assert denied["check_in"]["result"] == "denied" and denied["check_in"]["denial_reason"] == "client_disabled"
    body = {"client_id": f.person["id"], "location_id": f.loc, "override": True, "override_reason": "Manager ok"}
    assert check_in(client, f.desk, body).status_code == 403
    allowed = ok(check_in(client, owner, body), 201)["check_in"]
    assert allowed["result"] == "granted_override" and allowed["override_by_staff_user_id"]


def test_credentials_resolve_assign_revoke(client, tenant, owner, f):
    url = f"{API}/clients/{f.person['id']}/credentials"
    made = ok(client.post(url, headers=f.desk, json={"kind": "barcode", "value": " ab-123 ", "source": "scanned"}), 201)
    assert made["value"] == "AB-123" and made["source"] == "scanned"
    clash = client.post(url, headers=f.desk, json={"kind": "rfid", "value": "ab-123"})
    assert clash.status_code == 409
    generated = ok(client.post(url, headers=f.desk, json={"kind": "rfid", "generate": True}), 201)
    assert len(generated["value"]) == 10 and generated["source"] == "generated"
    assert client.post(url, headers=f.desk, json={"kind": "rfid"}).status_code == 422
    match = ok(client.post(f"{API}/credentials/resolve", headers=f.desk, json={"value": "ab-123"}))
    assert match["client_id"] == f.person["id"] and match["kind"] == "barcode"
    unknown = client.post(f"{API}/credentials/resolve", headers=f.desk, json={"value": "nope"})
    assert unknown.status_code == 404 and unknown.json()["code"] == "credential-not-found"
    scanned = ok(check_in(client, f.desk, {"credential_value": "AB-123", "location_id": f.loc}), 201)["check_in"]
    assert scanned["identified_by"] == "credential" and scanned["credential_id"] == made["id"]
    listed = ok(client.get(url, headers=f.desk))["data"]
    assert {c["value"] for c in listed} >= {"AB-123", generated["value"]}
    assert listed[0]["kind"] == "membership_number" and listed[0]["is_primary"]
    by_number = ok(check_in(client, f.desk, {"credential_value": listed[0]["value"], "location_id": f.loc}), 201)
    assert by_number["check_in"]["credential_id"] is None
    revoked = ok(client.post(f"{API}/credentials/{made['id']}/revoke", headers=f.desk))
    assert revoked["status"] == "revoked"
    assert client.post(f"{API}/credentials/resolve", headers=f.desk, json={"value": "AB-123"}).status_code == 404
    again = ok(client.post(url, headers=f.desk, json={"kind": "barcode", "value": "AB-123"}), 201)  # value is free
    assert again["id"] != made["id"]


def _session_near_now(client, owner, ids):
    """An extra client enrolled in the next session after populate()'s first that still has a seat."""
    from app.modules import scheduling
    from app.modules.scheduling.models import Session

    kid = new_client(client, owner, ids.location_id)
    with tenant_session(ids.tenant.id) as session:
        first = scheduling.service.get_session(session, ids.schedule_session_id)
        open_ids = session.scalars(select(Session.id).where(Session.booked_count < Session.capacity))
        views = [scheduling.service.get_session(session, i) for i in open_ids]
    seat = min((v for v in views if v["starts_at"] > first["starts_at"] and v["status"] == "confirmed"),
               key=lambda v: v["starts_at"])  # fmt: skip
    body = {"session_id": str(seat["id"]), "client_id": kid["id"]}
    ok(client.post(f"{API}/enrollments", headers=owner, json=body))
    return kid, seat


def test_check_in_marks_attendance_inside_the_window(client, monkeypatch):
    ids = populate(client, make_tenant())
    kid, seat = _session_near_now(client, ids.headers, ids)
    starts = seat["starts_at"]
    from app.modules.access import service  # its clock only: the session token must not expire

    monkeypatch.setattr(service, "clock", SimpleNamespace(now=lambda: starts - timedelta(hours=10)))
    far = ok(check_in(client, ids.headers, {"client_id": kid["id"], "location_id": ids.location_id}), 201)
    assert far["check_in"]["attended"] == []
    monkeypatch.setattr(service, "clock", SimpleNamespace(now=lambda: starts - timedelta(minutes=30)))
    near = ok(check_in(client, ids.headers, {"client_id": kid["id"], "location_id": ids.location_id}), 201)
    assert [a["session_id"] for a in near["check_in"]["attended"]] == [str(seat["id"])]
    again = ok(check_in(client, ids.headers, {"client_id": kid["id"], "location_id": ids.location_id}), 201)
    assert again["check_in"]["attended"] == []  # already marked


# --- kiosk ---------------------------------------------------------------------------------------------------


def _pair(client, tenant, owner, loc):
    code = ok(client.post(f"{API}/kiosk-devices", headers=owner, json={"location_id": loc, "name": "Door"}), 201)
    paired = client.post(f"{API}/kiosk/pair", headers={"X-Tenant-Slug": tenant.slug},
                         json={"pairing_code": code["pairing_code"].lower()})  # fmt: skip
    return code, paired


def test_kiosk_pairing_lookup_check_in_and_exit(client, tenant, owner, f):
    assert client.get(f"{API}/kiosk/config").status_code == 401
    code, paired = _pair(client, tenant, owner, f.loc)
    assert paired.status_code == 200 and paired.json()["location_name"] == "Main"
    cookie = paired.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1/kiosk" in cookie
    reuse = client.post(f"{API}/kiosk/pair", headers={"X-Tenant-Slug": tenant.slug},
                        json={"pairing_code": code["pairing_code"]})  # fmt: skip
    assert reuse.status_code == 422  # single use
    assert ok(client.get(f"{API}/kiosk/config"))["kiosk_device_id"] == code["kiosk_device_id"]
    kid = new_client(client, owner, f.loc, first_name="Kid", last_name=f.person["last_name"],
                     birth_on="2020-01-01")  # fmt: skip
    found = ok(client.post(f"{API}/kiosk/lookups", json={"last_name_prefix": f.person["last_name"][:5]}))["matches"]
    assert [(m["first_name"], m["last_initial"]) for m in found] == [("Avery", "Z")]  # the minor is not listed
    assert set(found[0]) == {"match_token", "first_name", "last_initial"}
    assert ok(client.post(f"{API}/kiosk/lookups", json={"last_name_prefix": "%%%"}))["matches"] == []
    entered = ok(client.post(f"{API}/kiosk/check-ins", json={"match_token": found[0]["match_token"]}), 201)
    assert entered["status"] == "admitted" and entered["first_name"] == "Avery"
    assert "balance_minor" not in entered and entered["displayed_alert_codes"] == []
    row = scalar(tenant, select(CheckIn).where(CheckIn.id == entered["check_in_id"]))
    assert row.channel == "kiosk" and row.identified_by == "name_search"
    tampered = found[0]["match_token"][:-2] + "00"
    assert client.post(f"{API}/kiosk/check-ins", json={"match_token": tampered}).status_code == 422
    assert client.post(f"{API}/kiosk/check-ins", json={"match_token": kid["id"]}).status_code == 422  # no forging
    unset = client.post(f"{API}/kiosk/exit", json={"staff_pin": "123456"})
    assert unset.status_code == 409 and unset.json()["code"] == "exit-pin-not-set"  # owner question 20
    ok(client.put(f"{API}/kiosk-settings?location_id={f.loc}", headers=owner, json={"exit_pin": "246810"}))
    wrong = client.post(f"{API}/kiosk/exit", json={"staff_pin": "000000"})
    assert wrong.status_code == 422 and wrong.json()["code"] == "reauthentication-failed"
    assert ok(client.get(f"{API}/kiosk/config"))["settings"]["has_exit_pin"]  # still paired after a wrong PIN
    assert client.post(f"{API}/kiosk/exit", json={"staff_pin": "246810"}).status_code == 204
    assert client.get(f"{API}/kiosk/config").status_code == 401


def test_kiosk_settings_gate_lookups_and_alerts(client, tenant, owner, f):
    url = f"{API}/kiosk-settings?location_id={f.loc}"
    assert ok(client.get(url, headers=f.desk))["lookup_method"] == "both"
    assert client.put(url, headers=f.desk, json={"lookup_method": "membership_number"}).status_code == 403
    saved = ok(client.put(url, headers=owner, json={"lookup_method": "membership_number",
                                                    "displayed_alert_codes": ["waiver_unsigned"]}))  # fmt: skip
    assert saved["lookup_method"] == "membership_number"
    assert client.put(url, headers=owner, json={"late_window_minutes": 5000}).status_code == 422
    assert client.get(f"{API}/kiosk-settings?location_id={f.other}", headers=f.desk).status_code == 404
    _pair(client, tenant, owner, f.loc)
    by_name = client.post(f"{API}/kiosk/lookups", json={"last_name_prefix": "Zep"})
    assert by_name.status_code == 422 and by_name.json()["code"] == "lookup-method-disabled"
    number = ok(client.get(f"{API}/clients/{f.person['id']}/credentials", headers=f.desk))["data"][0]["value"]
    found = ok(client.post(f"{API}/kiosk/lookups", json={"credential_value": number}))["matches"]
    assert len(found) == 1
    assert ok(client.post(f"{API}/kiosk/lookups", json={"credential_value": "unknown"}))["matches"] == []
    entered = ok(client.post(f"{API}/kiosk/check-ins", json={"match_token": found[0]["match_token"]},
                             headers={"Idempotency-Key": "kiosk-1"}), 201)  # fmt: skip
    assert entered["displayed_alert_codes"] == ["waiver_unsigned"]
    replay = client.post(f"{API}/kiosk/check-ins", json={"match_token": found[0]["match_token"]},
                         headers={"Idempotency-Key": "kiosk-1"})  # fmt: skip
    assert (
        replay.headers.get("idempotent-replayed") == "true" and replay.json()["check_in_id"] == entered["check_in_id"]
    )


def test_kiosk_devices_are_managed_per_location(client, tenant, owner, f):
    code, _ = _pair(client, tenant, owner, f.loc)
    device = code["kiosk_device_id"]
    assert (
        client.post(f"{API}/kiosk-devices", headers=f.desk, json={"location_id": f.loc, "name": "x"}).status_code == 403
    )
    fresh = ok(client.post(f"{API}/kiosk-devices/{device}/pairing-codes", headers=f.desk), 201)
    assert len(fresh["pairing_code"]) == 8
    listed = ok(client.get(f"{API}/kiosk-devices", headers=owner))["data"]
    assert listed[0]["status"] == "active"
    ok(client.post(f"{API}/kiosk-devices/{device}/revoke", headers=owner))
    assert client.get(f"{API}/kiosk/config").status_code == 401  # the revoked device's cookie stops working
    assert client.post(f"{API}/kiosk-devices/{device}/pairing-codes", headers=owner).status_code == 409
    north = ok(client.post(f"{API}/kiosk-devices", headers=owner, json={"location_id": f.other, "name": "N"}), 201)
    assert (
        client.post(f"{API}/kiosk-devices/{north['kiosk_device_id']}/pairing-codes", headers=f.desk).status_code == 404
    )
    expired = client.post(
        f"{API}/kiosk/pair", headers={"X-Tenant-Slug": tenant.slug}, json={"pairing_code": "ZZZZZZZZ"}
    )
    assert expired.status_code == 422


# --- portal app cards ----------------------------------------------------------------------------------------


def _portal(client, tenant, owner, loc):
    person = new_client(client, owner, loc, primary_email=f"pat-{uuid4().hex[:6]}@example.com")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(
            kind="client", email=person["primary_email"], status="active", email_verified_at=clock.now(),
            password_hash=passwords.hash_password(PASSWORD),
        )  # fmt: skip
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, person["id"], identity.id)
    return person, login(client, tenant, person["primary_email"], audience="client")


def test_app_cards_for_self_and_household_scan_at_the_kiosk(client, tenant, owner, f):
    parent, portal = _portal(client, tenant, owner, f.loc)
    issued = ok(client.post(f"{API}/portal/app-cards", headers=portal,
                            json={"client_id": parent["id"], "device_label": "Phone"}), 201)  # fmt: skip
    assert issued["card_payload"].startswith(issued["credential_id"])
    # A stranger's card is out of reach; the staff principal cannot use portal card routes.
    stranger = client.post(f"{API}/portal/app-cards", headers=portal, json={"client_id": f.person["id"]})
    assert stranger.status_code == 404
    assert client.delete(f"{API}/portal/app-cards/{issued['credential_id']}", headers=owner).status_code == 404
    # A parent acts for a child (households.can_act_for).
    kid = new_client(client, owner, f.loc, first_name="Kit")
    types = {t["code"]: t["id"] for t in ok(client.get(f"{API}/relationship-types", headers=owner))}
    ok(client.post(f"{API}/clients/{parent['id']}/relationships", headers=owner,
                   json={"other_client_id": kid["id"], "relationship_type_id": types["parent_of"]}))  # fmt: skip
    kid_card = ok(client.post(f"{API}/portal/app-cards", headers=portal, json={"client_id": kid["id"]}), 201)
    mine = ok(client.get(f"{API}/portal/app-cards", headers=portal))["data"]
    assert {c["client_id"] for c in mine} == {parent["id"], kid["id"]}
    assert "card_payload" not in mine[0]
    # The rotating QR admits at the kiosk; once revoked it does not.
    _pair(client, tenant, owner, f.loc)
    qr = cards.qr_text(kid_card["card_payload"], clock.now())
    entered = ok(client.post(f"{API}/kiosk/check-ins", json={"card_payload": qr}), 201)
    assert entered["first_name"] == "Kit"
    staff_scan = ok(check_in(client, f.desk, {"credential_value": qr, "location_id": f.loc}), 201)
    assert staff_scan["check_in"]["credential_id"] == kid_card["credential_id"]
    assert client.post(f"{API}/kiosk/check-ins", json={"card_payload": "fhq.junk"}).status_code == 422
    stale = cards.qr_text(kid_card["card_payload"], clock.now() - timedelta(minutes=5))
    assert client.post(f"{API}/kiosk/check-ins", json={"card_payload": stale}).status_code == 404
    assert client.delete(f"{API}/portal/app-cards/{kid_card['credential_id']}", headers=portal).status_code == 204
    assert client.post(f"{API}/kiosk/check-ins", json={"card_payload": qr}).status_code == 404
    wiped = scalar(tenant, select(Credential.secret_ciphertext).where(Credential.id == kid_card["credential_id"]))
    assert wiped is None
    # A second card for the same device replaces the first; staff can clear every card.
    again = ok(client.post(f"{API}/portal/app-cards", headers=portal,
                           json={"client_id": parent["id"], "device_label": "Phone"}), 201)  # fmt: skip
    assert len(ok(client.get(f"{API}/portal/app-cards?client_id={parent['id']}", headers=portal))["data"]) == 1
    url = f"{API}/clients/{parent['id']}/credentials/revoke-all"
    assert client.post(url, headers=f.desk, json={"kind": "app_card"}).status_code == 204
    assert ok(client.get(f"{API}/portal/app-cards", headers=portal))["data"] == []
    listed = ok(client.get(f"{API}/clients/{parent['id']}/credentials", headers=f.desk))["data"]
    assert all(c["value"].startswith("•") for c in listed if c["kind"] == "app_card")
    assert again["credential_id"] in {c["id"] for c in listed}


def test_merge_and_erasure_handlers(client, tenant, owner, f):
    from app.modules.access import subject

    other = new_client(client, owner, f.loc)
    ok(client.post(f"{API}/clients/{other['id']}/credentials", headers=owner, json={"kind": "barcode", "value": "M-1"}))
    ok(check_in(client, owner, {"client_id": other["id"], "location_id": f.loc}), 201)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        subject._repoint(session, other["id"], f.person["id"])
        exported = subject._export(session, f.person["id"])
        assert len(exported["check_ins"]) == 1 and exported["credentials"][0]["kind"] == "barcode"
        erased = subject._erase(session, f.person["id"])
    assert erased == {"retained_check_ins": 1, "revoked_credentials": 1}
