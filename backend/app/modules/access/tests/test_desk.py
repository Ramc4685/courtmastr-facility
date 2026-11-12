"""The check-in desk end to end (phase 10 chip C): remediation at the window (CHK-21), booking a session from a
check-in (CHK-04), stations, check-out and occupancy (CHK-07), ID card templates and the member card (CHK-12,
MEM-19). Each command has its refusals, a caller without the key and a caller outside the location."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db import tenant_session
from app.modules.access import desk
from app.modules.access.models import CheckIn
from conftest import add_staff, login, new_client, png_bytes, scalar

API = "/api/v1"


def ok(response, status=(200, 201)):
    assert response.status_code in ((status,) if isinstance(status, int) else status), response.text
    return response.json() if response.content else None


@pytest.fixture
def f(client, tenant, owner):
    def loc(name):
        body = {"name": name, "time_zone": "America/Chicago", "country_code": "US"}
        return ok(client.post(f"{API}/locations", headers=owner, json=body))["id"]

    main, north = loc("Main"), loc("North")
    desk_email, _ = add_staff(tenant, "front_desk", location_ids=[main])
    north_email, _ = add_staff(tenant, "admin", location_ids=[north])
    coach_email, _ = add_staff(tenant, "coach", location_ids=[main])
    person = new_client(client, owner, main, first_name="Robin", last_name=f"Quill{uuid4().hex[:4]}")
    number = {"member_number": f"M{uuid4().hex[:6].upper()}"}
    person = ok(client.post(f"{API}/clients/{person['id']}/member-number", headers=owner, json=number))
    return SimpleNamespace(
        loc=main, north=north, person=person, desk=login(client, tenant, desk_email),
        outsider=login(client, tenant, north_email), coach=login(client, tenant, coach_email),
    )  # fmt: skip


def check_in(client, headers, f, **extra):
    body = {"client_id": f.person["id"], "location_id": f.loc, "channel": "staff_window"} | extra
    return ok(client.post(f"{API}/check-ins", headers=headers, json=body), 201)


def evaluate(client, headers, f):
    body = {"client_id": f.person["id"], "location_id": f.loc}
    return ok(client.post(f"{API}/check-ins/evaluate", headers=headers, json=body))


def codes(decision) -> dict:
    return {a["code"]: a["action"] for a in decision["alerts"]}


# --- CHK-21 ----------------------------------------------------------------------------------------------------


def test_payment_and_signature_at_the_window_clear_the_alerts(client, owner, f):
    """The desk takes the balance through billing's route, applies it, and collects the waiver through
    documents' routes; the re-evaluated status card has neither alert."""
    category = ok(client.post(f"{API}/revenue-categories", headers=owner, json={"code": "DESK", "label": "Desk"}))
    charge = ok(client.post(f"{API}/charges", headers=owner, json={
        "client_id": f.person["id"], "location_id": f.loc, "description": "Guest fee", "unit_price_minor": 1500,
        "revenue_category_id": category["id"]}))  # fmt: skip
    before = codes(evaluate(client, f.desk, f))
    assert before["balance_due"] == "take_payment" and before["waiver_unsigned"] == "sign_waiver"

    pay = {"client_id": f.person["id"], "location_id": f.loc, "amount_minor": charge["total_minor"],
           "tender_kind": "card", "method_token": "tok_card_ok"}  # fmt: skip
    ok(client.post(f"{API}/payments", headers=f.desk | {"Idempotency-Key": f"desk-{uuid4().hex}"}, json=pay), 201)
    ok(client.post(f"{API}/clients/{f.person['id']}/account-credit/apply", headers=f.desk, json={}))
    assert "balance_due" not in codes(evaluate(client, f.desk, f))

    template = ok(client.post(f"{API}/document-templates", headers=owner, json={"name": "Waiver", "is_waiver": True}))
    ok(client.put(f"{API}/document-templates/{template['id']}/draft", headers=owner,
                  json={"body_html": "<p>I accept the risks.</p>", "acceptance_text": "I agree."}))  # fmt: skip
    ok(client.post(f"{API}/document-templates/{template['id']}/publish", headers=owner))
    ok(client.patch(f"{API}/document-location-settings/{f.loc}", headers=owner, json={"is_consent_required": False}))
    doc = ok(client.post(f"{API}/client-documents", headers=f.desk, json={
        "client_id": f.person["id"], "location_id": f.loc, "template_id": template["id"],
        "acceptance_method": "checkbox"}))  # fmt: skip
    ok(client.post(f"{API}/client-documents/{doc['id']}/acceptances", headers=f.desk, json={
        "content_sha256": doc["content_sha256"], "signers": [{"decision": "accepted", "signer_role": "client",
        "signer_name": "Robin", "method": "typed_name", "typed_signature": "Robin"}]}))  # fmt: skip
    after = evaluate(client, f.desk, f)
    assert not {"balance_due", "waiver_unsigned"} & set(codes(after)) and after["client"]["is_waiver_on_file"]


def test_window_payment_follows_billing_gates(client, owner, f):
    """The money goes only to its client, and only with billing's own key, wherever the window sends it."""
    other = new_client(client, owner, f.loc)
    category = ok(client.post(f"{API}/revenue-categories", headers=owner, json={"code": "DSK2", "label": "Desk"}))
    charge = ok(client.post(f"{API}/charges", headers=owner, json={
        "client_id": other["id"], "location_id": f.loc, "description": "Fee", "unit_price_minor": 900,
        "revenue_category_id": category["id"]}))  # fmt: skip
    invoice = ok(client.post(f"{API}/invoices", headers=owner, json={"charge_ids": [charge["id"]]}))
    pay = {"client_id": f.person["id"], "location_id": f.loc, "amount_minor": 900, "tender_kind": "card",
           "method_token": "tok_card_ok", "invoice_id": invoice["id"]}  # fmt: skip
    mismatch = client.post(f"{API}/payments", headers=f.desk | {"Idempotency-Key": f"mm-{uuid4().hex}"}, json=pay)
    assert 400 <= mismatch.status_code < 500 and mismatch.status_code != 404, mismatch.text
    pay.pop("invoice_id")
    refused = client.post(f"{API}/payments", headers=f.coach | {"Idempotency-Key": f"co-{uuid4().hex}"}, json=pay)
    assert refused.status_code in (403, 404)


# --- CHK-07 ----------------------------------------------------------------------------------------------------


def test_stations_check_out_and_occupancy(client, tenant, owner, f):
    station = ok(
        client.post(f"{API}/check-in-stations", headers=owner, json={"location_id": f.loc, "name": "Pool"}), 201
    )
    assert client.post(f"{API}/check-in-stations", headers=owner,
                       json={"location_id": f.loc, "name": "Pool"}).status_code == 409  # fmt: skip
    assert client.post(f"{API}/check-in-stations", headers=f.desk,
                       json={"location_id": f.loc, "name": "Gym"}).status_code == 403  # fmt: skip
    assert client.patch(f"{API}/check-in-stations/{station['id']}", headers=f.outsider,
                        json={"name": "X"}).status_code == 404  # fmt: skip
    listed = ok(client.get(f"{API}/check-in-stations?location_id={f.loc}", headers=f.desk))["data"]
    assert [s["name"] for s in listed] == ["Pool"]
    assert client.get(f"{API}/check-in-stations?location_id={f.loc}", headers=f.outsider).status_code == 404

    done = check_in(client, f.desk, f, check_in_station_id=station["id"])["check_in"]
    assert done["check_in_station_id"] == station["id"] and done["checked_out_at"] is None
    repeat = check_in(client, f.desk, f)["check_in"]  # a second scan, same visit, no station
    room = ok(client.get(f"{API}/occupancy?location_id={f.loc}", headers=f.desk))
    assert room["count"] == 1 and room["present"][0]["check_in_id"] == repeat["id"]
    assert room["by_station"] == [{"check_in_station_id": None, "station_name": None, "count": 1}]
    assert client.get(f"{API}/occupancy?location_id={f.loc}", headers=f.outsider).status_code == 404
    assert client.get(f"{API}/occupancy?location_id={f.loc}", headers=f.coach).status_code == 403

    ok(client.patch(f"{API}/check-in-stations/{station['id']}", headers=owner, json={"is_active": False}))
    inactive = client.post(f"{API}/check-ins", headers=f.desk, json={
        "client_id": f.person["id"], "location_id": f.loc, "channel": "staff_window",
        "check_in_station_id": station["id"]})  # fmt: skip
    assert inactive.status_code == 422 and inactive.json()["errors"][0]["pointer"] == "/check_in_station_id"

    assert client.post(f"{API}/check-ins/{done['id']}/check-out", headers=f.outsider).status_code == 404
    assert client.post(f"{API}/check-ins/{done['id']}/check-out", headers=f.coach).status_code == 403
    early = (clock.now() - timedelta(days=1)).isoformat()
    bad = client.post(f"{API}/check-ins/{done['id']}/check-out", headers=f.desk, json={"checked_out_at": early})
    assert bad.status_code == 422
    out = ok(client.post(f"{API}/check-ins/{done['id']}/check-out", headers=f.desk))
    assert out["checked_out_at"] is not None
    assert ok(client.get(f"{API}/check-ins/{repeat['id']}", headers=f.desk))["checked_out_at"] is not None
    assert ok(client.get(f"{API}/occupancy?location_id={f.loc}", headers=f.desk))["count"] == 0
    again = client.post(f"{API}/check-ins/{done['id']}/check-out", headers=f.desk)
    assert again.status_code == 409 and again.json()["code"] == "already-checked-out"
    # no is_open filter on the list: "who is in" is the occupancy read, which knows the location's today
    assert client.get(f"{API}/check-ins?location_id={f.loc}&is_open=true", headers=f.desk).status_code == 400


def test_a_visit_not_checked_out_ends_at_midnight(client, tenant, owner, f):
    done = check_in(client, f.desk, f)["check_in"]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(CheckIn).where(CheckIn.id == done["id"]).values(
            local_on=CheckIn.local_on - 1, checked_in_at=CheckIn.checked_in_at - timedelta(days=1)))  # fmt: skip
    assert ok(client.get(f"{API}/occupancy?location_id={f.loc}", headers=f.desk))["count"] == 0
    ended = client.post(f"{API}/check-ins/{done['id']}/check-out", headers=f.desk)
    assert ended.status_code == 409 and ended.json()["code"] == "visit-ended"


# --- CHK-04 ----------------------------------------------------------------------------------------------------


def _session_soon(client, owner, location_id, hours=1) -> str:
    tag = uuid4().hex[:6]
    group = ok(
        client.post(f"{API}/resource-groups", headers=owner, json={"location_id": location_id, "name": f"G{tag}"})
    )
    room = ok(client.post(f"{API}/resources", headers=owner,
                          json={"location_id": location_id, "resource_group_id": group["id"], "name": f"R{tag}"}))  # fmt: skip
    rtype = ok(client.post(f"{API}/reservation-types", headers=owner, json={
        "location_id": location_id, "name": f"Spin {tag}", "default_capacity": 10, "default_allows_free_booking": True}))  # fmt: skip
    start = (clock.now() + timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
    booking = ok(client.post(f"{API}/bookings", headers=owner, json={
        "location_id": location_id, "kind": "session", "reservation_type_id": rtype["id"],
        "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat(),
        "resources": [{"resource_id": room["id"], "role": "primary"}]}))  # fmt: skip
    return booking["booking"]["session"]["id"]


def test_book_a_session_from_the_check_in(client, tenant, owner, f):
    seat = _session_soon(client, owner, f.loc)
    later = _session_soon(client, owner, f.loc, hours=30)
    done = check_in(client, f.desk, f)["check_in"]
    url = f"{API}/check-ins/{done['id']}/attendances"
    assert client.post(url, headers=f.outsider, json={"session_id": seat}).status_code == 404
    assert client.post(url, headers=f.desk, json={"session_id": later}).status_code == 422
    assert client.post(url, headers=f.desk, json={"session_id": str(uuid4())}).status_code == 422
    booked = ok(client.post(url, headers=f.desk, json={"session_id": seat}), 201)
    mine = [a for a in booked["attended"] if a["session_id"] == seat]
    assert len(mine) == 1 and mine[0]["was_auto_booked"] and mine[0]["target_type"] == "enrollment"
    twice = client.post(url, headers=f.desk, json={"session_id": seat})
    assert twice.status_code == 409  # programs' own rule: already enrolled
    elsewhere = _session_soon(client, owner, f.north)
    assert client.post(url, headers=f.desk, json={"session_id": elsewhere}).status_code == 422

    denied_client = new_client(client, owner, f.loc)
    ok(client.post(f"{API}/clients/{denied_client['id']}/disable", headers=owner, json={"reason": "Left"}))
    denied = ok(client.post(f"{API}/check-ins", headers=f.desk, json={
        "client_id": denied_client["id"], "location_id": f.loc, "channel": "staff_window"}), 201)["check_in"]  # fmt: skip
    refused = client.post(f"{API}/check-ins/{denied['id']}/attendances", headers=f.desk, json={"session_id": seat})
    assert refused.status_code == 409 and refused.json()["code"] == "check-in-denied"


def test_booking_needs_the_enrollment_key(client, tenant, owner, f):
    seat = _session_soon(client, owner, f.loc)
    done = check_in(client, f.desk, f)["check_in"]
    email, staff_id = add_staff(tenant, "front_desk", location_ids=[f.loc])
    deny = {"grants": [{"permission_key": "scheduling.enrollment.create", "is_allowed": False}]}
    ok(client.put(f"{API}/staff-users/{staff_id}/permission-overrides", headers=owner, json=deny))
    clerk = login(client, tenant, email)
    refused = client.post(f"{API}/check-ins/{done['id']}/attendances", headers=clerk, json={"session_id": seat})
    assert refused.status_code == 403


# --- CHK-12, MEM-19 --------------------------------------------------------------------------------------------


def test_id_card_templates_and_the_member_card(client, tenant, owner, f):
    built_in = ok(client.get(f"{API}/clients/{f.person['id']}/id-card?location_id={f.loc}", headers=f.desk))
    assert built_in["template"]["id"] is None and built_in["code_value"] == f.person["member_number"]
    assert built_in["photo_url"] is None  # no photo yet: the card prints the placeholder
    put = client.put(f"{API}/clients/{f.person['id']}/photo", headers=owner | {"Content-Type": "image/png"},
                     content=png_bytes())  # fmt: skip
    assert put.status_code == 200
    with_photo = ok(client.get(f"{API}/clients/{f.person['id']}/id-card?location_id={f.loc}", headers=f.desk))
    assert with_photo["photo_url"] == f"/api/v1/clients/{f.person['id']}/photo"
    assert client.delete(f"{API}/clients/{f.person['id']}/photo", headers=owner).status_code in (200, 204)
    assert [x["field"] for x in built_in["fields"]] == ["name", "membership_number"]

    body = {"location_id": f.loc, "name": "Main card", "shown_fields": ["date_of_birth", "name"], "is_default": True}
    assert client.post(f"{API}/id-card-templates", headers=f.desk, json=body).status_code == 403
    assert client.post(f"{API}/id-card-templates", headers=f.outsider, json=body).status_code == 404
    bad = client.post(f"{API}/id-card-templates", headers=owner, json=body | {"shown_fields": ["css"]})
    assert bad.status_code == 422
    card = ok(client.post(f"{API}/id-card-templates", headers=owner, json=body), 201)
    assert card["shown_fields"] == ["name", "date_of_birth"]  # one order on every card
    tenant_wide = {"location_id": None, "name": "All", "shown_fields": ["name"], "is_default": True}
    assert client.post(f"{API}/id-card-templates", headers=f.outsider, json=tenant_wide).status_code == 403
    ok(client.post(f"{API}/id-card-templates", headers=owner, json=tenant_wide), 201)
    second = ok(client.post(f"{API}/id-card-templates", headers=owner, json=body | {"name": "Main 2"}), 201)
    assert ok(client.get(f"{API}/id-card-templates", headers=owner))["data"] and second["is_default"]
    names = {t["name"]: t for t in ok(client.get(f"{API}/id-card-templates", headers=owner))["data"]}
    assert not names["Main card"]["is_default"]  # a new default replaces the old one at the same scope
    seen = ok(client.get(f"{API}/id-card-templates", headers=f.outsider))["data"]
    assert [t["name"] for t in seen] == ["All"]  # another location's templates stay out of reach
    assert client.patch(f"{API}/id-card-templates/{card['id']}", headers=f.outsider,
                        json={"name": "X"}).status_code == 404  # fmt: skip

    printed = ok(client.get(f"{API}/clients/{f.person['id']}/id-card?location_id={f.loc}", headers=f.desk))
    assert printed["template"]["id"] == second["id"] and printed["photo_url"] is None
    by_id = ok(client.get(f"{API}/clients/{f.person['id']}/id-card?id_card_template_id={card['id']}", headers=f.desk))
    assert [x["field"] for x in by_id["fields"]] == ["name", "date_of_birth"]
    assert client.get(f"{API}/clients/{f.person['id']}/id-card?id_card_template_id={card['id']}",
                      headers=f.coach).status_code == 403  # fmt: skip
    assert client.get(f"{API}/clients/{f.person['id']}/id-card?location_id={f.loc}",
                      headers=f.outsider).status_code == 404  # fmt: skip


# --- review follow-ups -----------------------------------------------------------------------------------------


def deny(client, owner, tenant, role, location_id, *keys):
    """A staff user of `role` at `location_id` with `keys` taken away by an override."""
    email, staff_id = add_staff(tenant, role, location_ids=[location_id])
    grants = {"grants": [{"permission_key": k, "is_allowed": False} for k in keys]}
    ok(client.put(f"{API}/staff-users/{staff_id}/permission-overrides", headers=owner, json=grants))
    return login(client, tenant, email)


def test_member_card_hides_what_the_caller_may_not_see(client, tenant, owner, f):
    ok(client.patch(f"{API}/clients/{f.person['id']}", headers=owner, json={"birth_on": "1990-05-01"}))
    category = ok(client.post(f"{API}/revenue-categories", headers=owner, json={"code": "MCARD", "label": "Cards"}))
    kind = ok(client.post(f"{API}/membership-types", headers=owner,
                          json={"name": "Card", "revenue_category_id": category["id"]}))  # fmt: skip
    plan = ok(client.post(f"{API}/membership-plans", headers=owner, json={
        "membership_type_id": kind["id"], "name": "Annual", "billing_occurrences_count": 12, "term_fee_minor": 1000}))  # fmt: skip
    ok(client.post(f"{API}/membership-contracts", headers=owner,
                   json={"client_id": f.person["id"], "location_id": f.loc, "membership_plan_id": plan["id"]}))  # fmt: skip
    body = {
        "location_id": f.loc,
        "name": "Full",
        "shown_fields": ["name", "date_of_birth", "expires_on"],
        "is_default": True,
    }
    ok(client.post(f"{API}/id-card-templates", headers=owner, json=body), 201)
    url = f"{API}/clients/{f.person['id']}/id-card?location_id={f.loc}"

    def card(headers):
        return {x["field"]: x["value"] for x in ok(client.get(url, headers=headers))["fields"]}

    full = card(owner)
    assert full["date_of_birth"] == "1990-05-01" and full["expires_on"]
    # the front desk reads sensitive fields but not full details, and the location hides membership dates
    seen = card(f.desk)
    assert seen["date_of_birth"] == "1990-05-01" and seen["expires_on"] is None
    blind = deny(client, owner, tenant, "front_desk", f.loc, "clients.client.read_sensitive")
    assert card(blind)["date_of_birth"] is None
    ok(client.put(f"{API}/access-settings?location_id={f.loc}", headers=owner, json={"hidden_detail_fields": []}))
    assert card(f.desk)["expires_on"] == full["expires_on"]


def test_occupancy_caps_the_list_but_not_the_counts(client, owner, f, monkeypatch):
    other = new_client(client, owner, f.loc)
    check_in(client, f.desk, f)
    ok(client.post(f"{API}/check-ins", headers=f.desk, json={
        "client_id": other["id"], "location_id": f.loc, "channel": "staff_window"}), 201)  # fmt: skip
    monkeypatch.setattr(desk, "OCCUPANCY_LIMIT", 1)
    room = ok(client.get(f"{API}/occupancy?location_id={f.loc}", headers=f.desk))
    assert room["count"] == 2 and room["by_station"][0]["count"] == 2
    assert len(room["present"]) == 1 and room["present"][0]["client_id"] == other["id"] and room["is_capped"]
    assert room["present"][0]["client_name"] == f"{other['first_name']} {other['last_name']}"


def test_check_out_time_must_be_aware_and_not_in_the_future(client, f):
    done = check_in(client, f.desk, f)["check_in"]
    url = f"{API}/check-ins/{done['id']}/check-out"
    naive = client.post(url, headers=f.desk, json={"checked_out_at": "2026-01-01T10:00:00"})
    assert naive.status_code == 422, naive.text
    later = (clock.now() + timedelta(hours=1)).isoformat()
    assert client.post(url, headers=f.desk, json={"checked_out_at": later}).status_code == 422


def test_check_out_and_station_refusals(client, owner, f):
    gone = new_client(client, owner, f.loc)
    ok(client.post(f"{API}/clients/{gone['id']}/disable", headers=owner, json={"reason": "Left"}))
    denied = ok(client.post(f"{API}/check-ins", headers=f.desk, json={
        "client_id": gone["id"], "location_id": f.loc, "channel": "staff_window"}), 201)["check_in"]  # fmt: skip
    refused = client.post(f"{API}/check-ins/{denied['id']}/check-out", headers=f.desk)
    assert refused.status_code == 409 and refused.json()["code"] == "check-in-denied"
    north = ok(client.post(f"{API}/check-in-stations", headers=owner,
                           json={"location_id": f.north, "name": "North desk"}), 201)  # fmt: skip
    wrong = client.post(f"{API}/check-ins", headers=f.desk, json={
        "client_id": f.person["id"], "location_id": f.loc, "channel": "staff_window", "check_in_station_id": north["id"]})  # fmt: skip
    assert wrong.status_code == 422 and wrong.json()["errors"][0]["pointer"] == "/check_in_station_id"


def test_booking_refuses_a_closed_or_past_visit(client, tenant, owner, f):
    seat = _session_soon(client, owner, f.loc)
    done = check_in(client, f.desk, f)["check_in"]
    ok(client.post(f"{API}/check-ins/{done['id']}/check-out", headers=f.desk))
    closed = client.post(f"{API}/check-ins/{done['id']}/attendances", headers=f.desk, json={"session_id": seat})
    assert closed.status_code == 409 and closed.json()["code"] == "already-checked-out"
    old = check_in(client, f.desk, f)["check_in"]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(CheckIn).where(CheckIn.id == old["id"]).values(
            local_on=CheckIn.local_on - 1, checked_in_at=CheckIn.checked_in_at - timedelta(days=1)))  # fmt: skip
    past = client.post(f"{API}/check-ins/{old['id']}/attendances", headers=f.desk, json={"session_id": seat})
    assert past.status_code == 409 and past.json()["code"] == "visit-ended"


def test_booking_marks_only_the_session_booked(client, owner, f):
    seat = _session_soon(client, owner, f.loc)
    twin = _session_soon(client, owner, f.loc)  # starts at the same instant
    done = check_in(client, f.desk, f)["check_in"]
    ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": twin, "client_id": f.person["id"]}), 201)
    booked = ok(
        client.post(f"{API}/check-ins/{done['id']}/attendances", headers=f.desk, json={"session_id": seat}), 201
    )
    assert [a["session_id"] for a in booked["attended"]] == [seat]


def test_booking_respects_the_coach_s_own_reach(client, owner, f):
    """A coach books only into sessions they run; this one has no trainer, so it is outside their reach."""
    seat = _session_soon(client, owner, f.loc)
    done = check_in(client, f.desk, f)["check_in"]
    refused = client.post(f"{API}/check-ins/{done['id']}/attendances", headers=f.coach, json={"session_id": seat})
    assert refused.status_code in (403, 404), refused.text


def test_template_defaults_are_audited_and_tenant_wide_needs_every_location(client, tenant, owner, f):
    body = {"location_id": f.loc, "name": "First", "shown_fields": ["name"], "is_default": True}
    first = ok(client.post(f"{API}/id-card-templates", headers=owner, json=body), 201)

    def audits():
        return scalar(tenant, select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == first["id"]))

    before = audits()
    ok(client.post(f"{API}/id-card-templates", headers=owner, json=body | {"name": "Second"}), 201)
    assert audits() == before + 1  # the old default's change is recorded
    everywhere = ok(client.post(f"{API}/id-card-templates", headers=owner,
                                json={"location_id": None, "name": "All", "shown_fields": ["name"]}), 201)  # fmt: skip
    email, _ = add_staff(tenant, "manager", location_ids=[f.loc])
    manager = login(client, tenant, email)
    assert client.patch(f"{API}/id-card-templates/{everywhere['id']}", headers=manager,
                        json={"name": "Mine"}).status_code == 403  # fmt: skip
