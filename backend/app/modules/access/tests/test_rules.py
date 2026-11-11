"""Access rules govern entry (Phase 10 chip B): visit limits and visit counting (MEM-20), rule outcomes and client
access mode (CHK-08), time-of-day schedules in the location's zone (CHK-09), cross-location mappings (CHK-10),
check-in settings and field visibility (CHK-02), the minor age, and bookings marked arrived (owner questions
12, 21, 22). Real PostgreSQL as fh_app."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db import tenant_session
from app.modules import memberships, platform, scheduling
from app.modules.access import service, subject
from app.modules.access.domain.evaluate import Facts, evaluate, in_schedule
from app.modules.access.models import CheckInAttendance, ClientAccess
from app.modules.memberships.models import MembershipVisit
from app.modules.memberships.tests.support import contract, sale, world
from conftest import add_staff, login, new_client, scalar

API = "/api/v1"


def ok(response, status=(200, 201)):
    assert response.status_code in ((status,) if isinstance(status, int) else status), response.text
    return response.json() if response.content else None


def check_in(client, headers, body):
    return client.post(f"{API}/check-ins", headers=headers, json={"channel": "staff_window"} | body)


def granted(client, headers, body) -> dict:
    return ok(check_in(client, headers, body), 201)["check_in"]


@pytest.fixture
def m(client, tenant, owner):
    """A member with a two-visit membership at a Tokyo location (UTC+9, no DST), and a front-desk user."""
    w = world(client, owner, tenant, time_zone="Asia/Tokyo", max_visits_count=2)
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    email, _ = add_staff(tenant, "front_desk", location_ids=[w.location_id])
    return SimpleNamespace(
        loc=w.location_id, person=w.person, contract_id=sold["id"], type_id=w.plan["membership_type_id"],
        desk=login(client, tenant, email), body={"client_id": w.person["id"], "location_id": w.location_id}, w=w,
    )  # fmt: skip


@pytest.fixture
def tick(monkeypatch):
    """Moves the access clock past the ten-minute repeat window, so each check-in is a new entry."""
    state = {"at": clock.now()}

    def advance(minutes: int = 15) -> None:
        state["at"] += timedelta(minutes=minutes)
        monkeypatch.setattr(service, "clock", SimpleNamespace(now=lambda: state["at"]))

    return advance


def pair_kiosk(client, tenant, owner, location_id) -> None:
    device = ok(client.post(f"{API}/kiosk-devices", headers=owner, json={"location_id": location_id, "name": "Door"}))
    ok(
        client.post(
            f"{API}/kiosk/pair", headers={"X-Tenant-Slug": tenant.slug}, json={"pairing_code": device["pairing_code"]}
        )
    )


def match_token(client, m) -> str:
    return ok(client.post(f"{API}/kiosk/lookups", json={"last_name_prefix": m.person["last_name"][:5]}))["matches"][0][
        "match_token"
    ]


# --- pure decision -------------------------------------------------------------------------------------------


def test_decision_order_and_defaults():
    member = {"client_active": True, "membership_contract_id": uuid4()}
    used_up = evaluate(Facts(membership_reason="depleted", **member))
    assert (used_up.would_grant, used_up.denial_reason) == (False, "depleted")
    assert used_up.alerts == ["access_denied", "visits_depleted"] and not used_up.counts_visit
    assert evaluate(Facts(membership_reason="depleted", rules={"depleted": "allow"}, **member)).would_grant
    assert evaluate(Facts(membership_reason="daily_limit_reached", **member)).would_grant  # allowed by default
    assert evaluate(Facts(membership_reason="frozen", rules={"frozen": "allow"}, **member)).would_grant
    assert evaluate(Facts(membership_reason="frozen", access_mode="always_admit", **member)).would_grant
    assert evaluate(Facts(membership_reason=None, access_mode="always_deny", **member)).denial_reason == (
        "access_mode_deny"
    )
    disabled = Facts(client_active=False, membership_reason=None, access_mode="always_admit")
    assert evaluate(disabled).denial_reason == "client_disabled"
    assert evaluate(Facts(membership_reason=None, location_admits=False, **member)).denial_reason == "wrong_location"
    assert evaluate(Facts(membership_reason=None, schedule_open=False, **member)).denial_reason == "outside_schedule"
    # a non-member has no membership type: neither locations nor schedules apply
    assert evaluate(Facts(True, "none", location_admits=False, schedule_open=False)).would_grant


def test_in_schedule_boundaries():
    ranges = [(1, "06:00", "09:00"), (7, "22:00", "24:00")]
    assert in_schedule(ranges, 1, "06:00") and in_schedule(ranges, 1, "08:59") and not in_schedule(ranges, 1, "09:00")
    assert in_schedule(ranges, 7, "23:59") and not in_schedule(ranges, 2, "07:00")


# --- MEM-20: visits counted once, a used-up membership is denied, staff override ----------------------------


def test_visit_limit_counts_then_denies_and_override_records_an_uncounted_visit(client, tenant, owner, m, tick):
    for _ in range(2):
        tick()
        done = granted(client, m.desk, m.body)
        assert done["result"] == "granted" and done["is_visit_consumed"]
        assert done["membership_contract_id"] == m.contract_id
    assert contract(tenant, m.contract_id).visits_used_count == 2
    tick()
    denied = ok(check_in(client, m.desk, m.body), 201)
    assert denied["check_in"]["result"] == "denied" and denied["check_in"]["denial_reason"] == "depleted"
    assert {"code": "visits_depleted"} in denied["alerts"]
    override = m.body | {"override": True, "override_reason": "Pays a drop-in"}
    assert check_in(client, m.desk, override).status_code == 403  # access.checkin.override_denial
    admitted = granted(client, owner, override)
    assert admitted["result"] == "granted_override" and not admitted["is_visit_consumed"]
    assert contract(tenant, m.contract_id).visits_used_count == 2  # never counted past the cap
    visits = select(func.count()).select_from(MembershipVisit).where(MembershipVisit.client_id == m.person["id"])
    assert scalar(tenant, visits) == 3  # two counted, one recorded for the override; the denial wrote none


def test_record_visit_is_idempotent_on_the_check_in(client, tenant, owner, m):
    check_in_id = uuid4()
    args = {"client_id": m.person["id"], "check_in_id": check_in_id, "location_id": m.loc}
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        first = memberships.service.record_visit(session, **args)
        again = memberships.service.record_visit(session, **args)
    assert first == again and first["is_counted"]
    assert contract(tenant, m.contract_id).visits_used_count == 1


def test_kiosk_says_only_see_staff_when_visits_are_used_up(client, tenant, owner, m, tick):
    for _ in range(2):
        tick()
        granted(client, owner, m.body)
    tick()
    pair_kiosk(client, tenant, owner, m.loc)
    entered = ok(client.post(f"{API}/kiosk/check-ins", json={"match_token": match_token(client, m)}), 201)
    assert entered["status"] == "see_staff" and "denial_reason" not in entered  # no reasons at the kiosk
    assert entered["displayed_alert_codes"] == []  # owner: a refused client is told only to see staff


def test_a_repeat_entry_within_ten_minutes_counts_once(client, tenant, owner, m, tick):
    tick()
    assert granted(client, m.desk, m.body)["is_visit_consumed"]
    again = granted(client, m.desk, m.body)  # a double scan
    assert again["result"] == "granted" and not again["is_visit_consumed"]
    tick()
    pair_kiosk(client, tenant, owner, m.loc)
    kiosk = ok(client.post(f"{API}/kiosk/check-ins", json={"match_token": match_token(client, m)}), 201)
    assert kiosk["status"] == "admitted"  # the second, last visit
    window = granted(client, m.desk, m.body)  # kiosk, then the window: the pass is used up, but this is one entry
    assert window["result"] == "granted" and not window["is_visit_consumed"]
    assert contract(tenant, m.contract_id).visits_used_count == 2
    # One repeat per counted entry: a repeat neither anchors another nor restarts the window (a second person).
    tick(5)
    third = check_in(client, m.desk, m.body)
    assert third.status_code == 201 and third.json()["check_in"]["result"] == "denied"


def test_a_kiosk_match_token_works_once_and_names_no_client(client, tenant, owner, m):
    pair_kiosk(client, tenant, owner, m.loc)
    token = match_token(client, m)
    assert m.person["id"] not in token  # opaque, server-side
    ok(client.post(f"{API}/kiosk/check-ins", json={"match_token": token}), 201)
    replay = client.post(f"{API}/kiosk/check-ins", json={"match_token": token})
    assert replay.status_code == 422 and replay.json()["code"] == "match-token-expired"


def test_an_override_needs_a_reason(client, tenant, owner, m):
    blank = check_in(client, owner, m.body | {"override": True, "override_reason": "  "})
    assert blank.status_code == 422 and blank.json()["errors"][0]["pointer"] == "/override_reason"
    assert check_in(client, owner, m.body | {"override": True}).status_code == 422


def test_kiosk_is_revoked_after_five_wrong_exit_pins(client, tenant, owner, m):
    ok(client.put(f"{API}/kiosk-settings?location_id={m.loc}", headers=owner, json={"exit_pin": "246810"}))
    pair_kiosk(client, tenant, owner, m.loc)
    for _ in range(4):
        wrong = client.post(f"{API}/kiosk/exit", json={"staff_pin": "111111"})
        assert wrong.status_code == 422 and wrong.json()["code"] == "reauthentication-failed"
    assert client.get(f"{API}/kiosk/config").status_code == 200  # still paired after four
    assert client.post(f"{API}/kiosk/exit", json={"staff_pin": "111111"}).status_code == 422
    assert client.get(f"{API}/kiosk/config").status_code == 401  # the fifth failure revokes the device
    failed = select(AuditEvent).where(
        AuditEvent.action == "access.kiosk.launch", AuditEvent.reason == "exit-pin-failed"
    )
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        rows = session.scalars(failed).all()
        assert len(rows) == 5 and all("111111" not in str(r.changes) for r in rows)


def test_the_last_visit_shadowed_by_a_used_up_contract_is_found(client, tenant, owner, m):
    partner = new_client(client, owner, m.loc)  # owns a second pass and shares it with the member (no overlap rule)
    later = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(m.w, client_id=partner["id"])), 201)
    ok(
        client.post(
            f"{API}/membership-contracts/{later['id']}/shares", headers=owner, json={"client_id": m.person["id"]}
        ),
        201,
    )
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        first = memberships.service._get(session, memberships.models.MembershipContract, m.contract_id)
        first.visits_used_count = first.max_visits_count
        session.flush()
        standing = memberships.service.eligibility(session, m.person["id"])
    assert (str(standing["contract_id"]), standing["reason"]) == (later["id"], None)  # visits remaining wins


# --- CHK-08: rule outcomes and client access mode -----------------------------------------------------------


def test_rules_per_location_reset_to_defaults_and_need_their_key(client, tenant, owner, m):
    url = f"{API}/access-rules?location_id={m.loc}"
    listed = ok(client.get(url, headers=m.desk))["rules"]
    assert {r["condition"]: (r["outcome"], r["is_default"]) for r in listed}["depleted"] == ("deny", True)
    assert client.put(url, headers=m.desk, json={"rules": []}).status_code == 403
    allow = {"rules": [{"condition": "depleted", "outcome": "allow"}]}
    saved = ok(client.put(url, headers=owner, json=allow))["rules"]
    assert {r["condition"]: r["outcome"] for r in saved}["depleted"] == "allow"
    for _ in range(3):  # used up, but this location lets them in
        assert granted(client, m.desk, m.body)["result"] == "granted"
    back = ok(client.put(url, headers=owner, json={"rules": []}))["rules"]
    assert all(r["is_default"] for r in back)
    trail = select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "access.rule.manage")
    assert scalar(tenant, trail) == 2  # set, then reset
    assert client.get(f"{API}/access-rules?location_id={uuid4()}", headers=owner).status_code == 404


def test_client_access_mode_is_a_privileged_flag(client, tenant, owner, m):
    url = f"{API}/clients/{m.person['id']}/access-mode"
    assert ok(client.get(url, headers=m.desk))["access_mode"] == "normal"
    deny = {"access_mode": "always_deny", "reason": "Banned after an incident"}
    assert client.put(url, headers=m.desk, json=deny).status_code == 403
    assert client.put(url, headers=owner, json={"access_mode": "always_deny"}).status_code == 422  # reason required
    ok(client.put(url, headers=owner, json=deny))
    assert granted(client, m.desk, m.body)["denial_reason"] == "access_mode_deny"
    event = scalar(tenant, select(AuditEvent).where(AuditEvent.action == "access.client.set_access_mode"))
    assert event.reason == "Banned after an incident" and event.changes == {"access_mode": ["normal", "always_deny"]}
    ok(client.put(url, headers=owner, json={"access_mode": "always_admit", "reason": "Staff family"}))
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert service.access_mode(session, m.person["id"]) == "always_admit"
    with_rule = {"rules": [{"condition": "depleted", "outcome": "deny"}]}
    ok(client.put(f"{API}/access-rules?location_id={m.loc}", headers=owner, json=with_rule))
    for _ in range(3):  # always admit beats the used-up rule
        assert granted(client, m.desk, m.body)["result"] == "granted"
    assert client.get(f"{API}/clients/{uuid4()}/access-mode", headers=owner).status_code == 404


def test_access_mode_follows_merge_and_erasure(client, tenant, owner, m):
    other = new_client(client, owner, m.loc)
    mode = {"access_mode": "always_deny", "reason": "x"}
    ok(client.put(f"{API}/clients/{other['id']}/access-mode", headers=owner, json=mode))
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        subject._repoint(session, other["id"], m.person["id"])  # survivor had no row: it takes the loser's
        assert subject._export(session, m.person["id"])["access_mode"] == "always_deny"
    third = new_client(client, owner, m.loc)
    ok(client.put(f"{API}/clients/{third['id']}/access-mode", headers=owner, json=mode))
    ok(
        client.put(
            f"{API}/clients/{m.person['id']}/access-mode",
            headers=owner,
            json={"access_mode": "always_admit", "reason": "x"},
        )
    )
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        subject._repoint(session, third["id"], m.person["id"])  # survivor admits, loser is banned: the ban wins
        assert subject._export(session, m.person["id"])["access_mode"] == "always_deny"
        subject._erase(session, m.person["id"])
    assert scalar(tenant, select(func.count()).select_from(ClientAccess)) == 0


# --- CHK-09 and CHK-10: schedules in the location's zone, admitting locations --------------------------------


def test_schedule_is_evaluated_in_the_location_zone(client, tenant, owner, m, monkeypatch):
    early = {"name": "Early birds", "ranges": [{"weekday": 1, "starts_time": "06:00", "ends_time": "09:00"}]}
    assert client.post(f"{API}/access-schedules", headers=m.desk, json=early).status_code == 403
    schedule = ok(client.post(f"{API}/access-schedules", headers=owner, json=early), 201)
    assert client.post(f"{API}/access-schedules", headers=owner, json=early).status_code == 409  # same name
    across = {"ranges": [{"weekday": 1, "starts_time": "22:00", "ends_time": "02:00"}]}
    assert client.patch(f"{API}/access-schedules/{schedule['id']}", headers=owner, json=across).status_code == 422
    mapping = {"access_schedule_id": schedule["id"], "location_ids": []}
    ok(client.put(f"{API}/membership-types/{m.type_id}/access", headers=owner, json=mapping))
    evaluate_url = f"{API}/check-ins/evaluate"
    # Sunday 22:30 UTC is Monday 07:30 in Tokyo: inside; Monday 07:30 UTC is 16:30 in Tokyo: outside.
    monkeypatch.setattr(service, "clock", SimpleNamespace(now=lambda: datetime(2030, 5, 5, 22, 30, tzinfo=UTC)))
    assert ok(client.post(evaluate_url, headers=m.desk, json=m.body))["would_grant"]
    monkeypatch.setattr(service, "clock", SimpleNamespace(now=lambda: datetime(2030, 5, 6, 7, 30, tzinfo=UTC)))
    late = ok(client.post(evaluate_url, headers=m.desk, json=m.body))
    assert (late["would_grant"], late["denial_reason"]) == (False, "outside_schedule")
    ok(client.patch(f"{API}/access-schedules/{schedule['id']}", headers=owner, json={"is_active": False}))
    assert ok(client.post(evaluate_url, headers=m.desk, json=m.body))["would_grant"]  # inactive: unrestricted
    listed = ok(client.get(f"{API}/access-schedules", headers=m.desk))["data"]
    assert listed[0]["ranges"] == [{"weekday": 1, "starts_time": "06:00", "ends_time": "09:00"}]


def test_membership_admits_everywhere_until_locations_are_mapped(client, tenant, owner, m):
    def place(name):
        return ok(
            client.post(
                f"{API}/locations", headers=owner, json={"name": name, "time_zone": "Asia/Tokyo", "country_code": "JP"}
            ),
            201,
        )["id"]

    def admits(location_id) -> dict:
        return ok(
            client.post(
                f"{API}/check-ins/evaluate",
                headers=owner,
                json={"client_id": m.person["id"], "location_id": location_id},
            )
        )

    north, south = place("North"), place("South")
    assert admits(north)["would_grant"]  # no rows: every location, as before CHK-10
    url = f"{API}/membership-types/{m.type_id}/access"
    ok(client.put(url, headers=owner, json={"location_ids": [north]}))
    assert admits(north)["would_grant"] and admits(m.loc)["would_grant"]  # mapped, and where it was sold
    assert admits(south)["denial_reason"] == "wrong_location"  # rows restrict
    assert ok(client.get(f"{API}/membership-type-access", headers=m.desk))["data"][0]["location_ids"] == [north]
    assert client.put(f"{API}/membership-types/{uuid4()}/access", headers=owner, json={}).status_code == 404
    unknown = client.put(url, headers=owner, json={"location_ids": [str(uuid4())]})
    assert unknown.status_code == 422 and unknown.json()["errors"][0]["pointer"] == "/location_ids/0"
    assert client.put(url, headers=m.desk, json={}).status_code == 403


# --- CHK-02: settings and field visibility ------------------------------------------------------------------


def test_location_chooses_the_fields_staff_see_without_full_details(client, tenant, owner, m):
    card = ok(client.post(f"{API}/check-ins/evaluate", headers=m.desk, json=m.body))["client"]
    assert card["balance_due_minor"] is None and card["membership"]["visits_remaining_count"] is None  # defaults
    url = f"{API}/access-settings?location_id={m.loc}"
    assert client.put(url, headers=m.desk, json={"hidden_detail_fields": []}).status_code == 403
    assert client.put(url, headers=owner, json={"hidden_detail_fields": ["photo"]}).status_code == 422
    ok(client.put(url, headers=owner, json={"hidden_detail_fields": ["staff_notes"], "staff_late_minutes": 60}))
    card = ok(client.post(f"{API}/check-ins/evaluate", headers=m.desk, json=m.body))["client"]
    assert card["balance_due_minor"] is not None and card["membership"]["visits_remaining_count"] == 2
    assert card["staff_alerts"] == []
    assert ok(client.get(url, headers=m.desk))["staff_late_minutes"] == 60
    full = ok(client.post(f"{API}/check-ins/evaluate", headers=owner, json=m.body))["client"]
    assert full["membership"]["end_on"] is not None  # the owner holds read_full_details
    nulls = {"hidden_detail_fields": None, "staff_early_minutes": None, "staff_late_minutes": None}
    kept = ok(client.put(url, headers=owner, json=nulls))  # an explicit null leaves the value alone
    assert kept["hidden_detail_fields"] == ["staff_notes"] and kept["staff_late_minutes"] == 60


# --- owner questions 21 and 22 -------------------------------------------------------------------------------


def test_minor_age_is_the_tenant_setting(client, tenant, owner):
    def age() -> int:
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:
            return platform.service.minor_age(session)

    assert age() == 18
    ok(client.patch(f"{API}/tenant", headers=owner, json={"settings": {"minor_age": 5}}))
    assert age() == 5
    ok(client.patch(f"{API}/tenant", headers=owner, json={"settings": {"minor_age": "x"}}))
    assert age() == 18


def test_check_in_marks_court_bookings_arrived_once(client, tenant, owner, m, monkeypatch):
    booking_id, calls = uuid4(), []

    def bookings(session, **kwargs):
        calls.append(kwargs)
        return [booking_id]

    monkeypatch.setattr(scheduling.service, "client_bookings_starting", bookings)
    ok(client.put(f"{API}/access-settings?location_id={m.loc}", headers=owner, json={"staff_late_minutes": 60}))
    first = granted(client, m.desk, m.body)
    assert [(a["target_type"], a["target_id"]) for a in first["attended"]] == [("booking", str(booking_id))]
    now = clock.now()
    assert calls[0]["start"] < now - timedelta(minutes=179) and calls[0]["end"] < now + timedelta(minutes=61)
    assert granted(client, m.desk, m.body)["attended"] == []  # already marked by the first check-in
    marks = select(func.count()).select_from(CheckInAttendance).where(CheckInAttendance.target_type == "booking")
    assert scalar(tenant, marks) == 1


def test_client_bookings_starting_reads_confirmed_bookings_of_the_client(client, tenant, owner, m):
    group = ok(client.post(f"{API}/resource-groups", headers=owner, json={"location_id": m.loc, "name": "Courts"}))
    court = ok(
        client.post(
            f"{API}/resources",
            headers=owner,
            json={"location_id": m.loc, "resource_group_id": group["id"], "name": "Court 1"},
        )
    )
    other = new_client(client, owner, m.loc)
    now = clock.now().replace(second=0, microsecond=0)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:

        def rental(client_id, hours):
            return scheduling.service.create_booking(
                session, location_id=UUID(m.loc), kind="rental", starts_at=now + timedelta(hours=hours),
                ends_at=now + timedelta(hours=hours + 1), resource_ids=[UUID(court["id"])], client_id=UUID(client_id), title="Court",
            ).id  # fmt: skip

        mine, later, theirs = rental(m.person["id"], 1), rental(m.person["id"], 9), rental(other["id"], 3)
        found = scheduling.service.client_bookings_starting(
            session, client_id=UUID(m.person["id"]), location_id=UUID(m.loc), start=now - timedelta(hours=3), end=now + timedelta(hours=5)
        )  # fmt: skip
    assert found == [mine] and later not in found and theirs not in found


def test_schedule_follows_daylight_saving_in_the_location_zone(client, tenant, owner, monkeypatch):
    w = world(client, owner, tenant, time_zone="America/New_York")
    ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    early = {"name": "Mornings", "ranges": [{"weekday": 1, "starts_time": "06:00", "ends_time": "09:00"}]}
    schedule = ok(client.post(f"{API}/access-schedules", headers=owner, json=early), 201)
    url = f"{API}/membership-types/{w.plan['membership_type_id']}/access"
    ok(client.put(url, headers=owner, json={"access_schedule_id": schedule["id"], "location_ids": []}))
    body = {"client_id": w.person["id"], "location_id": w.location_id}

    def inside(at: datetime) -> bool:
        monkeypatch.setattr(service, "clock", SimpleNamespace(now=lambda: at))
        return ok(client.post(f"{API}/check-ins/evaluate", headers=owner, json=body))["would_grant"]

    # 13:30 UTC on a Monday: 08:30 EST before the change (inside), 09:30 EDT after it (outside).
    assert inside(datetime(2031, 3, 3, 13, 30, tzinfo=UTC)) and not inside(datetime(2031, 3, 10, 13, 30, tzinfo=UTC))
