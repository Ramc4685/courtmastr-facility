"""Building control (CHK-15, CHK-16) on real PostgreSQL with the simulated controller: devices and their gates,
entry codes per booking (issue, email, reissue, revoke, refusals), the door verify endpoint (allow, deny,
lockout, check-in), staff and member unlocks, court lights computed from holds, overrides, the activity log and
the reconciliation line."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.adapters.building_control import SimulatedBuildingControl
from app.core import clock, crypto
from app.core.audit import AuditEvent
from app.core.auth import passwords, system_principal
from app.core.db import tenant_session
from app.core.settings import get_settings
from app.modules import clients, scheduling
from app.modules.access import building, handlers, jobs
from app.modules.access.models import BuildingEvent, CheckIn, EntryCode
from app.modules.platform.models import Identity, Location
from app.modules.scheduling.tests.helpers import API, DAY, facility, ok
from app.ports import building_control
from conftest import PASSWORD, add_staff, login, new_client, scalar


def at(hours: float):
    return DAY + timedelta(hours=hours)


@pytest.fixture
def sim():
    controller = building_control.current()
    assert isinstance(controller, SimulatedBuildingControl)
    controller.reset()
    yield controller
    controller.reset()


@pytest.fixture
def b(client, tenant, owner, sim):
    f = facility(client, owner)
    f.tenant = tenant
    f.person = new_client(client, owner, f.location, primary_email=f"pat-{uuid4().hex[:6]}@example.com")
    door = ok(client.post(f"{API}/door-devices", headers=owner,
                          json={"location_id": f.location, "name": "Front door", "device_ref": "door-front"}))  # fmt: skip
    assert door["credential"].startswith("fhb_") and "token_hash" not in door
    f.door, f.device = door["id"], {"Authorization": f"Bearer {door['credential']}"}
    zone = lambda name, ref, ids: ok(client.post(f"{API}/lighting-zones", headers=owner, json={  # noqa: E731
        "location_id": f.location, "name": name, "zone_ref": ref, "resource_ids": ids}))["id"]  # fmt: skip
    f.court_zone, f.half_zone = zone("Court 1", "relay-1", [f.court]), zone("Court 1A", "relay-2", [f.half_a])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        site = session.get(Location, UUID(f.location))
        site.alert_email, site.phone = "ops@example.com", "+1 309 555 0100"
    return f


def book(f, start: float, end: float, *, resources=None, kind="rental", buffer_min: int | None = None) -> str:
    """A confirmed booking through scheduling's internal create (rentals are not importable from access)."""
    with tenant_session(f.tenant.id, actor=system_principal("tests")) as session:
        row = scheduling.service.create_booking(
            session, location_id=UUID(f.location), kind=kind, starts_at=at(start), ends_at=at(end),
            resource_ids=[UUID(r) for r in resources or [f.court]], client_id=UUID(f.person["id"]),
            block_kind="unavailable" if kind == "block" else None, buffer_before_min=buffer_min,
            buffer_after_min=buffer_min,
        )  # fmt: skip
        return str(row.id)


def sync(f, booking_id: str) -> None:
    with tenant_session(f.tenant.id, actor=system_principal("tests")) as session:
        building.sync_booking_code(session, UUID(booking_id))


def tick(f) -> None:
    jobs.run_building_control.fn(str(f.tenant.id))


def codes(f, booking_id: str) -> list[EntryCode]:
    with tenant_session(f.tenant.id, actor=system_principal("tests")) as session:
        rows = session.scalars(select(EntryCode).where(EntryCode.booking_id == UUID(booking_id)).order_by(EntryCode.id))
        return [session.expunge(r) or r for r in rows.all()]


def clear(f, row: EntryCode) -> str:
    return crypto.decrypt(row.code_ciphertext, f.tenant.id)


def verify(client, f, code: str) -> dict:
    return ok(client.post(f"{API}/door/verify", headers=f.device, json={"code": code}), 200)


def portal(client, tenant, person) -> dict:
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(kind="client", email=person["primary_email"], status="active",
                            email_verified_at=clock.now(), password_hash=passwords.hash_password(PASSWORD))  # fmt: skip
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, person["id"], identity.id)
    return portal_login(client, tenant, person)


def portal_login(client, tenant, person) -> dict:
    return login(client, tenant, person["primary_email"], audience="client")


def kinds(f) -> list[str]:
    with tenant_session(f.tenant.id, actor=system_principal("tests")) as session:
        return list(session.scalars(select(BuildingEvent.kind).order_by(BuildingEvent.id)))


# --- devices ---------------------------------------------------------------------------------------------------


def test_device_gates_and_scope(client, tenant, owner, b):
    other = ok(client.post(f"{API}/locations", headers=owner,
                           json={"name": "North", "time_zone": "America/Chicago", "country_code": "US"}))["id"]  # fmt: skip
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[b.location])[0])
    manager = login(client, tenant, add_staff(tenant, "manager", location_ids=[b.location])[0])
    north = login(client, tenant, add_staff(tenant, "manager", location_ids=[other])[0])
    body = {"location_id": b.location, "name": "Side door", "device_ref": "door-side"}
    assert client.post(f"{API}/door-devices", headers=manager, json=body).status_code == 403  # Admin only
    assert client.post(f"{API}/door-devices/{b.door}/unlock", headers=desk, json={"reason": "x"}).status_code == 403
    assert client.post(f"{API}/door-devices/{b.door}/unlock", headers=north, json={"reason": "x"}).status_code == 404
    assert ok(client.get(f"{API}/door-devices?location_id={b.location}", headers=desk), 200)["data"][0]["id"] == b.door
    assert client.get(f"{API}/door-devices?location_id={b.location}", headers=north).status_code == 404
    zones = ok(client.get(f"{API}/lighting-zones?location_id={b.location}", headers=desk), 200)["data"]
    assert {z["name"]: z["resource_ids"] for z in zones} == {"Court 1": [b.court], "Court 1A": [b.half_a]}
    stray = {"location_id": b.location, "name": "Wrong", "zone_ref": "relay-9", "resource_ids": [str(uuid4())]}
    refused = client.post(f"{API}/lighting-zones", headers=owner, json=stray)
    assert refused.status_code == 422 and "/resource_ids" in refused.text
    # a rotated credential retires the old one at once; a retired door has none
    fresh = ok(client.post(f"{API}/door-devices/{b.door}/credential", headers=owner))
    assert client.post(f"{API}/door/verify", headers=b.device, json={"code": "123456"}).status_code == 401
    b.device = {"Authorization": f"Bearer {fresh['credential']}"}
    assert verify(client, b, "123456") == {"result": "deny", "unlock_seconds": 0}
    ok(client.patch(f"{API}/door-devices/{b.door}", headers=owner, json={"is_active": False}), 200)
    assert client.post(f"{API}/door/verify", headers=b.device, json={"code": "123456"}).status_code == 401


# --- entry codes -----------------------------------------------------------------------------------------------


def test_code_is_issued_once_emailed_and_never_audited_in_clear(client, b, sim, mailbox):
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        sync(b, booking)  # idempotent: the same window keeps the same code, nothing is sent again
        [row] = codes(b, booking)
        code = clear(b, row)
        assert (row.valid_from_at, row.valid_until_at) == (
            at(10) - timedelta(minutes=15),
            at(11) + timedelta(minutes=10),
        )
        assert row.code_hash != code and code not in row.code_hash and row.notified_at and row.pushed_at
        [mail] = [m for m in mailbox if m.to == b.person["primary_email"]]
        assert code in mail.body and "door code" in mail.subject and "+1 309 555 0100" in mail.body
        assert ("push_code", "door-front", str(row.id)) in sim.calls and code not in str(sim.calls)
        trail = scalar(b.tenant, select(AuditEvent.changes).where(AuditEvent.action == "access.entry_code.issue"))
        assert trail["code"] is True and code not in str(trail)
        listed = ok(client.get(f"{API}/portal/entry-codes", headers=portal(client, b.tenant, b.person)), 200)["data"]
        assert [(c["code"], c["is_open_now"], c["location_phone"]) for c in listed] == [
            (code, False, "+1 309 555 0100")
        ]


def test_reschedule_reissues_and_cancel_revokes_through_the_handlers(b, sim, mailbox):
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        first = codes(b, booking)[0]
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            row = scheduling.service.get_booking(session, UUID(booking))
            scheduling.service.reschedule_booking(session, row, starts_at=at(12), ends_at=at(13))
        handlers.on_booking_rescheduled.fn(str(b.tenant.id), str(uuid4()), {"booking_id": booking})
        old, new = codes(b, booking)
        assert (old.id, old.status, old.revoke_reason) == (first.id, "revoked", "rescheduled")
        assert new.status == "active" and new.valid_from_at == at(12) - timedelta(minutes=15)
        assert ("revoke_code", "door-front", str(old.id)) in sim.calls and len(mailbox) == 2
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            scheduling.service.cancel_booking(session, scheduling.service.get_booking(session, UUID(booking)))
        handlers.on_booking_cancelled.fn(str(b.tenant.id), str(uuid4()), {"booking_id": booking})
        assert [(c.status, c.revoke_reason) for c in codes(b, booking)] == [
            ("revoked", "rescheduled"),
            ("revoked", "cancelled"),
        ]


def test_blocks_get_no_code_and_far_bookings_wait_for_the_horizon(b, mailbox):
    with clock.freeze(at(9)):
        block = book(b, 10, 11, kind="block")
        later = book(b, 24 * 9, 24 * 9 + 1)  # nine days out: beyond the seven-day horizon
        tick(b)
        assert codes(b, block) == [] and codes(b, later) == []
    with clock.freeze(at(24 * 3)):
        tick(b)  # the tick catches it up once it is inside the horizon
        assert [c.status for c in codes(b, later)] == ["active"] and mailbox


# --- the door --------------------------------------------------------------------------------------------------


def test_verify_allows_in_window_writes_a_door_check_in_and_locks_after_bad_codes(client, b):
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        code = clear(b, codes(b, booking)[0])
        assert verify(client, b, code) == {"result": "deny", "unlock_seconds": 0}  # before the window
    with clock.freeze(at(9.8)):
        assert verify(client, b, code) == {"result": "allow", "unlock_seconds": 5}
        check_in = scalar(b.tenant, select(CheckIn).where(CheckIn.client_id == UUID(b.person["id"])))
        assert (check_in.channel, check_in.result) == ("door", "granted")
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            assert verify(client, b, wrong)["result"] == "deny"
        assert verify(client, b, code)["result"] == "deny"  # the keypad is locked for five minutes
    with clock.freeze(at(9.8) + timedelta(minutes=6)):
        assert verify(client, b, code)["result"] == "allow"
    details = scalar(b.tenant, select(BuildingEvent.detail).where(BuildingEvent.kind == "entry_denied")
                     .order_by(BuildingEvent.id.desc()).limit(1))  # fmt: skip
    assert details == "keypad_locked"
    assert code not in str(
        scalar(b.tenant, select(AuditEvent.changes).where(AuditEvent.action == "access.door.verify"))
    )


def test_check_in_evaluation_refuses_blocked_and_unpaid_holders(client, tenant, owner, b, mailbox):
    category = ok(client.post(f"{API}/revenue-categories", headers=owner, json={"code": "FEE", "label": "Fees"}))
    ok(client.post(f"{API}/charges", headers=owner, json={
        "client_id": b.person["id"], "location_id": b.location, "description": "Court hire",
        "unit_price_minor": 4000, "revenue_category_id": category["id"]}))  # fmt: skip
    with clock.freeze(at(9.8)):
        owner = login(client, tenant, tenant.owner_email)  # a session minted before the frozen 2031 has expired
        booking = book(b, 10, 11)
        sync(b, booking)
        code = clear(b, codes(b, booking)[0])
        assert mailbox == [] and codes(b, booking)[0].notified_at is None  # an unpaid holder is not sent the code
        assert verify(client, b, code)["result"] == "deny"
        ok(client.put(f"{API}/access-settings?location_id={b.location}", headers=owner,
                      json={"requires_paid_entry": False}), 200)  # fmt: skip
        assert verify(client, b, code)["result"] == "allow"
        ok(client.put(f"{API}/clients/{b.person['id']}/access-mode", headers=owner,
                      json={"access_mode": "always_deny", "reason": "Banned"}), 200)  # fmt: skip
        assert verify(client, b, code)["result"] == "deny"
    assert kinds(b).count("entry_denied") == 2


def test_staff_remote_unlock_is_audited_and_a_dead_controller_is_409(client, owner, b, sim):
    event = ok(client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={"reason": "Card reader down"}))
    assert event["kind"] == "remote_unlock" and ("unlock", "door-front", 5) in sim.calls
    audit_row = scalar(b.tenant, select(AuditEvent).where(AuditEvent.action == "access.door.unlock"))
    assert audit_row.reason == "Card reader down"
    assert client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={}).status_code == 422
    sim.fail("unlock", kind="timeout")
    dead = client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={"reason": "Again"})
    assert dead.status_code == 409 and dead.json()["code"] == "device-unavailable"
    assert kinds(b)[-1] == "command_failed"  # the failure is kept although the request failed


def test_member_opens_the_door_from_the_portal_inside_the_window_only(client, tenant, owner, b, sim):
    other = new_client(client, owner, b.location, primary_email=f"s-{uuid4().hex[:6]}@example.com")
    with clock.freeze(at(9)):
        member, stranger = portal(client, tenant, b.person), portal(client, tenant, other)
        booking = book(b, 10, 11)
        sync(b, booking)
        early = client.post(f"{API}/portal/bookings/{booking}/door-unlock", headers=member)
        assert (
            early.status_code == 409
            and early.json()["code"] == "entry-refused"
            and "555 0100" in early.json()["detail"]
        )
    with clock.freeze(at(10.5)):
        member, stranger = portal_login(client, tenant, b.person), portal_login(client, tenant, other)
        assert client.post(f"{API}/portal/bookings/{booking}/door-unlock", headers=stranger).status_code == 404
        opened = ok(client.post(f"{API}/portal/bookings/{booking}/door-unlock", headers=member), 200)
        assert opened["result"] == "allow" and ("unlock", "door-front", 5) in sim.calls
    assert "member_unlock" in kinds(b)


# --- lights ----------------------------------------------------------------------------------------------------


def test_lights_follow_holds_without_flicker_and_light_child_zones(b, sim):
    first, second = book(b, 10, 11), book(b, 11, 12)  # back to back on the whole court
    half = book(b, 13, 14, resources=[b.half_a])
    for hours, court, half_lit in ((9.95, True, True), (11, True, True), (12.2, False, False), (13, False, True)):
        with clock.freeze(at(hours)):
            tick(b)
            assert (sim.zones.get("relay-1"), sim.zones.get("relay-2")) == (court, half_lit), hours
    switched = [c for c in sim.calls if c[0] == "set_zone"]
    # on once at 9:57 (both zones: the court's hold covers its halves), off once after the run-on, Court 1A on again
    assert switched == [("set_zone", "relay-1", True), ("set_zone", "relay-2", True), ("set_zone", "relay-1", False),
                        ("set_zone", "relay-2", False), ("set_zone", "relay-2", True)]  # fmt: skip
    with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
        scheduling.service.cancel_booking(session, scheduling.service.get_booking(session, UUID(half)))
    with clock.freeze(at(13.1)):
        tick(b)  # a cancelled booking is corrected on the next tick
        assert sim.zones["relay-2"] is False
    assert first and second


def test_lights_follow_the_booked_time_not_the_changeover_buffer(b, sim):
    book(b, 10, 11, resources=[b.half_a], buffer_min=10)  # the hold covers 9:50 to 11:10
    for hours, lit in ((9.85, False), (9.95, True), (11.05, True), (11.1, False)):  # lead-in and run-on: 5 minutes
        with clock.freeze(at(hours)):
            tick(b)
            assert sim.zones.get("relay-2") is lit, hours


def test_a_failing_zone_is_retried_then_staff_are_alerted(b, sim, mailbox):
    book(b, 10, 11)
    sim.fail("set_zone", times=6)  # both zones fail on three ticks
    with clock.freeze(at(10)):
        for _ in range(3):
            tick(b)
        assert (
            sim.zones == {} and sum("not responding" in m.subject for m in mailbox) == 2
        )  # one per zone, at the third
        tick(b)
        tick(b)
        assert sim.zones == {"relay-1": True, "relay-2": True}
    assert kinds(b).count("command_failed") == 6 and sum("not responding" in m.subject for m in mailbox) == 2


def test_override_holds_a_zone_and_status_shows_the_reconciliation(client, tenant, owner, b, sim):
    email = add_staff(tenant, "manager", location_ids=[b.location])[0]
    with clock.freeze(at(9)):
        manager = login(client, tenant, email)
        too_far = {"is_on": True, "until_at": at(24 * 8).isoformat(), "reason": "Tournament"}
        assert (
            client.put(f"{API}/lighting-zones/{b.court_zone}/override", headers=manager, json=too_far).status_code
            == 422
        )
        hold = {"is_on": True, "until_at": at(10).isoformat(), "reason": "Cleaning"}
        zone = ok(client.put(f"{API}/lighting-zones/{b.court_zone}/override", headers=manager, json=hold), 200)
        assert zone["override_is_on"] is True and sim.zones == {"relay-1": True}
        status = ok(client.get(f"{API}/building-status?location_id={b.location}", headers=manager), 200)
        lines = {z["name"]: (z["should_be_on"], z["reason"], z["is_in_sync"]) for z in status["zones"]}
        assert lines == {"Court 1": (True, "override", True), "Court 1A": (False, "idle", False)}  # never commanded yet
        assert status["adapter"] == "simulated" and status["doors"][0]["id"] == b.door
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:  # someone flips it at the wall
            session.execute(building.LightingZone.__table__.update().values(commanded_is_on=False))
        drift = ok(client.get(f"{API}/building-status?location_id={b.location}", headers=manager), 200)
        assert not next(z for z in drift["zones"] if z["name"] == "Court 1")["is_in_sync"]
        tick(b)  # the next tick repairs it
        assert sim.calls[-1] == ("set_zone", "relay-1", True)
    with clock.freeze(at(10.5)):
        tick(b)  # the override ran out: the court goes back to its bookings (none)
        assert sim.zones["relay-1"] is False
    reason = scalar(tenant, select(AuditEvent.reason).where(AuditEvent.action == "access.lighting.override"))
    assert reason == "Cleaning"


def test_activity_lists_by_day_and_kind(client, tenant, owner, b):
    ok(client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={"reason": "Delivery"}))
    page = ok(client.get(f"{API}/building-events?location_id={b.location}&kind=remote_unlock", headers=owner), 200)
    assert [e["kind"] for e in page["data"]] == ["remote_unlock"] and page["data"][0]["staff_user_id"]
    day = page["data"][0]["local_on"]
    assert len(ok(client.get(f"{API}/building-events?local_on={day}", headers=owner), 200)["data"]) == 1
    assert ok(client.get(f"{API}/building-events?local_on=2020-01-01", headers=owner), 200)["data"] == []


def test_simulated_adapter_is_refused_outside_dev_and_test(monkeypatch, tmp_path, deploy_secrets):
    config = (Path(__file__).resolve().parents[5] / "config" / "app.yaml").read_text()
    (tmp_path / "app.yaml").write_text(config.replace("cookie_secure: false", "cookie_secure: true"))
    base = "email: {log_links: false}\npayments: {provider: none}\nstorage: {scanner: clamd}\napi: {exposed_directly: true}\n"
    (tmp_path / "app.prod.yaml").write_text(base + "building_control: {adapter: simulated}\n")
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", "prod")
    monkeypatch.setenv("FH_PAYMENTS_PROVIDER", "")
    with pytest.raises(RuntimeError, match="building_control.adapter"):
        get_settings.__wrapped__()
    (tmp_path / "app.prod.yaml").write_text(base)
    assert get_settings.__wrapped__().building_control.adapter == "none"
