"""Building control (CHK-15, CHK-16) on real PostgreSQL with the simulated controller: devices and their gates,
entry codes per booking (issue, email, reissue, revoke, refusals), the door verify endpoint (allow, deny,
lockout, check-in), staff and member unlocks, court lights computed from holds, overrides, the activity log and
the reconciliation line."""

import time
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.adapters.building_control import SimulatedBuildingControl
from app.core import clock, crypto
from app.core.audit import AuditEvent
from app.core.auth import passwords, system_principal
from app.core.db import tenant_session
from app.core.settings import get_settings
from app.modules import clients, scheduling
from app.modules.access import building, handlers, jobs
from app.modules.access.models import BuildingEvent, CheckIn, EntryCode, EntryCodeHold
from app.modules.platform.models import Identity, Location
from app.modules.scheduling.models import Session
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


@pytest.fixture(autouse=True)
def quick_verify(monkeypatch):
    """Real delays are 0.4 s to 5 s; tests keep the shape at a hundredth (the timing test sets its own floor)."""
    monkeypatch.setattr(building, "EVAL_FLOOR_SECONDS", 0.0)
    monkeypatch.setattr(building, "DOOR_DELAYS", (0.0, 0.01, 0.02, 0.04, 0.05))


@pytest.fixture
def b(client, tenant, owner, sim):
    f = facility(client, owner)
    f.tenant = tenant
    f.person = adult(client, owner, f.location)
    door = ok(client.post(f"{API}/door-devices", headers=owner,
                          json={"location_id": f.location, "name": "Front door", "device_ref": "door-front",
                                "is_entrance": True}))  # fmt: skip
    assert door["credential"].startswith("fhb_") and "token_hash" not in door
    f.door, f.device = door["id"], {"Authorization": f"Bearer {door['credential']}"}
    zone = lambda name, ref, ids: ok(client.post(f"{API}/lighting-zones", headers=owner, json={  # noqa: E731
        "location_id": f.location, "name": name, "zone_ref": ref, "resource_ids": ids}))["id"]  # fmt: skip
    f.court_zone, f.half_zone = zone("Court 1", "relay-1", [f.court]), zone("Court 1A", "relay-2", [f.half_a])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        site = session.get(Location, UUID(f.location))
        site.alert_email, site.phone = "ops@example.com", "+1 309 555 0100"
    return f


def adult(client, owner, location: str, *, confirmed: bool = True, **fields) -> dict:
    """A client a door code may go to: a birth date over the minor age that staff confirmed once (ID seen);
    `confirmed=False`: a self-declared adult whose code is held."""
    body = {"primary_email": f"p-{uuid4().hex[:6]}@example.com", "birth_on": "1990-01-01"} | fields
    person = new_client(client, owner, location, **body)
    if confirmed:
        ok(client.post(f"{API}/clients/{person['id']}/age-confirmation", headers=owner, json={}), 200)
    return person


def book(f, start: float, end: float, *, resources=None, kind="rental", buffer_min: int | None = None,
         holder: str | None = None) -> str:  # fmt: skip
    """A confirmed booking through scheduling's internal create (rentals are not importable from access)."""
    with tenant_session(f.tenant.id, actor=system_principal("tests")) as session:
        row = scheduling.service.create_booking(
            session, location_id=UUID(f.location), kind=kind, starts_at=at(start), ends_at=at(end),
            resource_ids=[UUID(r) for r in resources or [f.court]],
            client_id=None if kind == "session" else UUID(holder or f.person["id"]),
            reservation_type_id=UUID(f.type) if kind == "session" else None,
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
    assert client.post(f"{API}/door/verify", headers=b.device, json={"code": "12345678"}).status_code == 401
    b.device = {"Authorization": f"Bearer {fresh['credential']}"}
    assert verify(client, b, "12345678") == {"result": "deny", "unlock_seconds": 0}
    ok(client.patch(f"{API}/door-devices/{b.door}", headers=owner, json={"is_active": False}), 200)
    assert client.post(f"{API}/door/verify", headers=b.device, json={"code": "12345678"}).status_code == 401


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


def test_a_session_code_is_its_persons_and_dies_with_the_enrolment(client, tenant, owner, b, mailbox):
    """Each participant has their own code; cancelling the enrolment is refused at the door at once (before any
    handler runs) and the handler revokes it. A participant's code checks that participant in."""
    other = adult(client, owner, b.location)
    with clock.freeze(at(9)):
        lesson = book(b, 10, 11, kind="session", resources=[b.court2])
    seat = scalar(tenant, select(Session.id).where(Session.booking_id == UUID(lesson)))
    mine, theirs = (
        ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": str(seat), "client_id": p["id"]}))
        for p in (b.person, other)
    )
    with clock.freeze(at(9)):
        sync(b, lesson)
        by_person = {str(c.client_id): clear(b, c) for c in codes(b, lesson)}
    assert set(by_person) == {b.person["id"], other["id"]} and len(set(by_person.values())) == 2
    ok(client.post(f"{API}/enrollments/{mine['id']}/cancel", headers=owner, json={}), 200)
    with clock.freeze(at(9.8)):
        assert verify(client, b, by_person[b.person["id"]])["result"] == "deny"
        assert details_of(b, "entry_denied")[-1] == "not_entitled"
        assert verify(client, b, by_person[other["id"]])["result"] == "allow"
        assert scalar(tenant, select(CheckIn.client_id).where(CheckIn.channel == "door")) == UUID(other["id"])
        handlers.on_enrollment_ended.fn(str(tenant.id), str(uuid4()), {
            "enrollment_id": mine["id"], "session_id": str(seat), "client_id": b.person["id"],
            "cancel_kind": "staff_removed"})  # fmt: skip
        statuses = {str(c.client_id): (c.status, c.revoke_reason) for c in codes(b, lesson)}
    assert statuses == {b.person["id"]: ("revoked", "not_entitled"), other["id"]: ("active", None)}
    assert theirs


def test_merging_two_records_with_codes_on_one_session_keeps_the_survivors_code(client, tenant, owner, b):
    """Duplicate records both enrolled on one session each hold a code; the merge revokes the loser's instead of
    tripping uq_entry_code_booking, and the survivor's code keeps working."""
    dup = adult(client, owner, b.location, first_name=b.person["first_name"], last_name=b.person["last_name"])
    with clock.freeze(at(9)):
        lesson = book(b, 10, 11, kind="session", resources=[b.court2])
    seat = scalar(tenant, select(Session.id).where(Session.booking_id == UUID(lesson)))
    for p in (b.person, dup):
        ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": str(seat), "client_id": p["id"]}))
    with clock.freeze(at(9)):
        sync(b, lesson)
        kept = clear(b, next(c for c in codes(b, lesson) if str(c.client_id) == b.person["id"]))
    ok(client.post(f"{API}/clients/{b.person['id']}/merge", headers=owner,
                   json={"merged_client_ids": [dup["id"]]}), 200)  # fmt: skip
    rows = {(str(c.client_id), c.status, c.revoke_reason) for c in codes(b, lesson)}
    assert rows == {(b.person["id"], "active", None), (b.person["id"], "revoked", "merged")}
    with clock.freeze(at(9.8)):
        assert verify(client, b, kept)["result"] == "allow"


def test_a_moved_booking_fails_its_old_code_at_once_and_a_failed_payment_revokes(client, b):
    with clock.freeze(at(9.8)):
        booking = book(b, 10, 11)
        sync(b, booking)
        code = clear(b, codes(b, booking)[0])
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            row = scheduling.service.get_booking(session, UUID(booking))
            scheduling.service.reschedule_booking(session, row, starts_at=at(12), ends_at=at(13))
        assert verify(client, b, code)["result"] == "deny"  # the live booking's window, not the stored one
        assert details_of(b, "entry_denied")[-1] == "rescheduled"
        sync(b, booking)
        fresh = codes(b, booking)[-1]
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            session.execute(building.EntryCode.__table__.update().values(valid_from_at=at(9.5), valid_until_at=at(12))
                            .where(building.EntryCode.id == fresh.id))  # fmt: skip
        assert verify(client, b, clear(b, fresh))["result"] == "deny"  # a stored window that drifted is refused
        handlers.on_payment_changed.fn(str(b.tenant.id), str(uuid4()), {"payment_id": str(uuid4()),
                                       "client_id": b.person["id"]})  # fmt: skip
        assert codes(b, booking)[-1].status == "active"  # nothing owed: the code stands
        category = ok(client.post(f"{API}/revenue-categories", headers=login(client, b.tenant, b.tenant.owner_email),
                                  json={"code": "FEE", "label": "Fees"}))  # fmt: skip
        ok(client.post(f"{API}/charges", headers=login(client, b.tenant, b.tenant.owner_email), json={
            "client_id": b.person["id"], "location_id": b.location, "description": "Court hire",
            "unit_price_minor": 4000, "revenue_category_id": category["id"]}))  # fmt: skip
        handlers.on_payment_changed.fn(str(b.tenant.id), str(uuid4()), {"payment_id": str(uuid4()),
                                       "client_id": b.person["id"]})  # fmt: skip
        assert (codes(b, booking)[-1].status, codes(b, booking)[-1].revoke_reason) == ("revoked", "refused")


def test_codes_never_go_to_a_minor_or_someone_of_unknown_age(client, tenant, owner, b, mailbox):
    """Rentals held by a minor or a dateless client get no code (logged once); on a session, an adult gets their
    own, a minor's goes to their adult guardian, and a minor with no adult guardian's goes to nobody."""
    dateless = adult(client, owner, b.location, confirmed=False, birth_on=None)
    child = adult(client, owner, b.location, confirmed=False, birth_on="2020-01-01")
    lone_child = adult(client, owner, b.location, confirmed=False, birth_on="2019-01-01")
    parent = adult(client, owner, b.location)
    kinds_of = {t["code"]: t["id"] for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200)}
    ok(client.post(f"{API}/clients/{parent['id']}/relationships", headers=owner,
                   json={"other_client_id": child["id"], "relationship_type_id": kinds_of["guardian_of"]}))  # fmt: skip
    with clock.freeze(at(9)):
        rental = book(b, 10, 11, holder=dateless["id"])
        tick(b)
        tick(b)
        assert codes(b, rental) == [] and kinds(b).count("code_withheld") == 1
        lesson = book(b, 12, 13, kind="session", resources=[b.court2])
    seat = scalar(tenant, select(Session.id).where(Session.booking_id == UUID(lesson)))
    for person in (b.person, child, lone_child):
        ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": str(seat), "client_id": person["id"]}))
    mailbox.clear()
    with clock.freeze(at(9)):
        sync(b, lesson)
        to = sorted(m.to for m in mailbox)
    assert to == sorted([b.person["primary_email"], parent["primary_email"]])
    assert child["primary_email"] not in to and lone_child["primary_email"] not in to
    with clock.freeze(at(9)):  # the portal shows a code only to a caller of known adult age
        held = book(b, 14, 15)
        sync(b, held)
        member = portal(client, tenant, b.person)
        listed = ok(client.get(f"{API}/portal/entry-codes", headers=member), 200)["data"]
        assert sorted(c["booking_id"] for c in listed) == sorted([lesson, held])  # their session and their rental
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:
            clients.service.get(session, UUID(b.person["id"])).birth_on = None
        assert ok(client.get(f"{API}/portal/entry-codes", headers=member), 200)["data"] == []
        assert client.post(f"{API}/portal/bookings/{held}/door-unlock", headers=member).status_code == 404


def test_portal_and_delivery_follow_one_rule_for_a_childs_code(client, tenant, owner, b, mailbox):
    """Only the child's eligible guardian gets, lists or uses the child's code: not a delegate, a barred guardian,
    a household manager who is not a guardian, or another child holding a guardianship link."""
    from app.modules.clients.models import ClientPortalAccess

    child = adult(client, owner, b.location, confirmed=False, birth_on="2020-01-01")
    guardian, barred, delegate, manager = (adult(client, owner, b.location) for _ in range(4))
    kid = adult(client, owner, b.location, confirmed=False, birth_on="2018-01-01")
    types = {t["code"]: t["id"] for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200)}
    for person, kind in (
        (guardian, "guardian_of"),
        (barred, "guardian_of"),
        (delegate, "spouse_of"),
        (kid, "guardian_of"),
    ):
        ok(client.post(f"{API}/clients/{person['id']}/relationships", headers=owner,
                       json={"other_client_id": child["id"], "relationship_type_id": types[kind]}))  # fmt: skip
    ok(client.put(f"{API}/clients/{barred['id']}/access-mode", headers=owner,
                  json={"access_mode": "always_deny", "reason": "Barred"}), 200)  # fmt: skip
    with clock.freeze(at(9)):
        lesson = book(b, 10, 11, kind="session", resources=[b.court2])
    seat = scalar(tenant, select(Session.id).where(Session.booking_id == UUID(lesson)))
    ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": str(seat), "client_id": child["id"]}))
    mailbox.clear()
    with clock.freeze(at(9)):
        sync(b, lesson)
    assert [m.to for m in mailbox] == [guardian["primary_email"]]
    with clock.freeze(at(10.5)):
        logins = {name: portal(client, tenant, p) for name, p in
                  (("guardian", guardian), ("barred", barred), ("delegate", delegate), ("manager", manager), ("kid", kid))}  # fmt: skip
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:
            identity = session.scalar(select(ClientPortalAccess.identity_id).where(
                ClientPortalAccess.client_id == UUID(manager["id"])))  # fmt: skip
            session.add(ClientPortalAccess(identity_id=identity, client_id=UUID(child["id"]), is_primary=False,
                                           status="active"))  # fmt: skip
        for name, headers in logins.items():
            listed = ok(client.get(f"{API}/portal/entry-codes", headers=headers), 200)["data"]
            unlock = client.post(f"{API}/portal/bookings/{lesson}/door-unlock", headers=headers)
            if name == "guardian":
                assert [c["booking_id"] for c in listed] == [lesson] and unlock.status_code == 200
            else:
                assert listed == [] and unlock.status_code == 404, name


def test_holds_are_rows_so_erasure_merge_and_bad_detail_text_never_break_them(client, tenant, owner, b, monkeypatch):
    """A held code is an `entry_code_hold` row, never parsed out of event text: erasing one held person leaves
    everyone else's holds, the portal and issue_held_codes working; a merge moves the hold; any detail text is safe."""
    from sqlalchemy import update

    from app.modules.access import subject
    from app.modules.scheduling.models import Booking

    monkeypatch.setattr(clients.service, "is_age_confirmed", lambda s, cid: False, raising=False)
    gone, kept, dup = (adult(client, owner, b.location) for _ in range(3))
    with clock.freeze(at(9)):
        mine, theirs, extra = book(b, 10, 11, holder=gone["id"]), book(b, 12, 13, holder=kept["id"]), \
            book(b, 14, 15, holder=dup["id"])  # fmt: skip
        tick(b)
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:
            building._event(session, UUID(b.location), "code_withheld", detail="age-not-confirmed:booking:x:client:")
            building._event(session, UUID(b.location), "code_withheld", detail="age-not-confirmed:" + "::" * 9)
            subject._repoint(session, dup["id"], kept["id"])  # a merge moves the hold (and scheduling, the booking)
            session.execute(
                update(Booking).where(Booking.client_id == UUID(dup["id"])).values(client_id=UUID(kept["id"]))
            )
        assert sorted(holds(b)) == sorted([(mine, gone["id"], "age-not-confirmed"),
                                           (theirs, kept["id"], "age-not-confirmed"),
                                           (extra, kept["id"], "age-not-confirmed")])  # fmt: skip
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:
            exported = subject._export(session, UUID(gone["id"]))
            assert [h["booking_id"] for h in exported["entry_code_holds"]] == [mine]
            subject._erase(session, UUID(gone["id"]))
        assert [h[1] for h in holds(b)] == [kept["id"], kept["id"]]
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:
            assert sorted(str(bk["id"]) for bk, _ in building._held(session)) == sorted([theirs, extra])
            building.issue_held_codes(session, UUID(kept["id"]))  # still unconfirmed: nothing issued, nothing raised
        member = portal(client, tenant, kept)
        listed = ok(client.get(f"{API}/portal/entry-codes", headers=member), 200)["data"]
        assert sorted(c["booking_id"] for c in listed) == sorted([theirs, extra])
        assert not any(gone["id"] in d for d in details_of(b, "code_withheld"))
    staff_view = ok(client.get(f"{API}/building-status?location_id={b.location}", headers=owner), 200)["held_codes"]
    assert sorted((h["booking_id"], h["client_id"], h["reason"]) for h in staff_view) == sorted(
        [(theirs, kept["id"], "age-not-confirmed"), (extra, kept["id"], "age-not-confirmed")])  # fmt: skip


def test_a_holder_who_stops_being_a_known_adult_loses_the_active_code(client, b):
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            clients.service.get(session, UUID(b.person["id"])).birth_on = None
        sync(b, booking)  # the window is unchanged, but the rule runs before that shortcut
    assert [(c.status, c.revoke_reason) for c in codes(b, booking)] == [("revoked", "not_known_adult")]


def holds(f) -> list[tuple[str, str, str]]:
    with tenant_session(f.tenant.id, actor=system_principal("tests")) as session:
        return [(str(h.booking_id), str(h.client_id), h.reason) for h in session.scalars(select(EntryCodeHold))]


def test_an_unconfirmed_adult_gets_no_code_until_staff_confirm_their_age_once(client, tenant, owner, b, mailbox):
    """Owner decision 2026-11-13, "staff confirm once": a self-declared adult books, but each code is held (one
    `code_withheld` row and one `entry_code_hold` per booking, a held line on the portal) and the person is told
    once, in clients' wording with the location phone; staff confirm (`clients.client.age_confirmed`) and every
    held code is issued and sent at once; the event handled twice changes nothing; later codes are self-service."""
    person = adult(client, owner, b.location, confirmed=False)
    me = person["id"]
    with clock.freeze(at(9)):
        first, second = book(b, 10, 11, holder=me), book(b, 12, 13, holder=me)
        mailbox.clear()
        tick(b)
        tick(b)
        assert codes(b, first) == [] and codes(b, second) == []
        shown = details_of(b, "code_withheld")  # display text for staff: the booking number, never the person
        assert len(shown) == 2 and all(d.startswith("age-not-confirmed:booking:") and me not in d for d in shown)
        assert sorted(holds(b)) == sorted((x, me, "age-not-confirmed") for x in (first, second))  # the record
        [told] = mailbox  # once per person, not once per booking or per tick
        assert clients.service.ENTRY_CODE_NOTICE in told.body and "+1 309 555 0100" in told.body
        member = portal(client, tenant, person)
        held = ok(client.get(f"{API}/portal/entry-codes", headers=member), 200)["data"]
        assert sorted(h["booking_id"] for h in held) == sorted([first, second])
        assert all(h["code"] is None and h["held_reason"] == "age-not-confirmed"
                   and h["message"].startswith(clients.service.ENTRY_CODE_NOTICE)
                   and "+1 309 555 0100" in h["message"] for h in held)  # fmt: skip
        assert client.post(f"{API}/portal/bookings/{first}/door-unlock", headers=member).status_code == 404
        mailbox.clear()
    ok(client.post(f"{API}/clients/{me}/age-confirmation", headers=owner, json={}), 200)  # staff saw the ID
    with clock.freeze(at(9)):
        member = portal_login(client, tenant, person)
        for _ in range(2):  # the outbox may deliver twice
            handlers.on_age_confirmed.fn(str(tenant.id), str(uuid4()), {"client_id": me})
        assert [c.status for c in codes(b, first) + codes(b, second)] == ["active", "active"]
        assert len(mailbox) == 2 and all("Your door code" in m.subject for m in mailbox)
        listed = ok(client.get(f"{API}/portal/entry-codes", headers=member), 200)["data"]
        assert all(c["code"] and c["held_reason"] is None for c in listed) and len(listed) == 2
        third = book(b, 14, 15, holder=me)
        sync(b, third)  # self-service from now on
        assert [c.status for c in codes(b, third)] == ["active"]
    assert len(details_of(b, "code_withheld")) == 2  # the third was never held
    assert holds(b) == []  # issued holds are gone
    activity = ok(client.get(f"{API}/building-events?kind=code_withheld", headers=owner), 200)["data"]  # staff view
    assert {e["detail"].split(":")[0] for e in activity} == {"age-not-confirmed"} and len(activity) == 2


def test_a_reset_confirmation_revokes_the_code_and_holds_it_again(client, tenant, owner, b, mailbox):
    """A confirmed date edited (or a merge) unconfirms the person and publishes no reverse event: the door refuses
    the code at once, the `clients.client.updated` handler revokes and holds it, and the tick would too."""
    me = b.person["id"]
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        [row] = codes(b, booking)
        digits = clear(b, row)
    with clock.freeze(at(10)):
        assert verify(client, b, digits)["result"] == "allow"
    edited = ok(client.patch(f"{API}/clients/{me}", headers=owner, json={"birth_on": "1991-02-02"}), 200)
    assert edited["age_confirmation_reset"] is True
    with clock.freeze(at(10.1)):
        assert verify(client, b, digits)["result"] == "deny"  # `_admit` re-reads the confirmation
        mailbox.clear()
        handlers.on_client_updated.fn(str(tenant.id), str(uuid4()), {"client_id": me})
        handlers.on_client_updated.fn(str(tenant.id), str(uuid4()), {"client_id": me})  # idempotent
        tick(b)
    assert [(c.status, c.revoke_reason) for c in codes(b, booking)] == [("revoked", "not_known_adult")]
    assert holds(b) == [(booking, me, "age-not-confirmed")]
    assert len(mailbox) == 1 and clients.service.ENTRY_CODE_NOTICE in mailbox[0].body


def test_the_tick_alone_catches_a_reset_confirmation(client, tenant, owner, b):
    me = b.person["id"]
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:  # a merge: no event at all
            clients.service._mark_age_unconfirmed(clients.service.get(session, UUID(me)))
        tick(b)
    assert [(c.status, c.revoke_reason) for c in codes(b, booking)] == [("revoked", "not_known_adult")]
    assert holds(b) == [(booking, me, "age-not-confirmed")]


def test_a_failed_code_email_is_retried_by_the_tick_and_marked_only_once_handed_off(b, mailbox, monkeypatch):
    from app.ports import email

    real_send, down = email._provider.send, [True]

    def send(message):
        if down[0]:
            raise ConnectionError("smtp down")
        real_send(message)

    monkeypatch.setattr(email._provider, "send", send)
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        [row] = codes(b, booking)
        assert row.notified_at is None and mailbox == []  # queued, never handed off
        tick(b)
        assert codes(b, booking)[0].notified_at is None  # still down: retried, still not marked
        down[0] = False
        tick(b)
        [row] = codes(b, booking)
        assert row.notified_at is not None and len(mailbox) == 1 and clear(b, row) in mailbox[0].body
        tick(b)
        assert len(mailbox) == 1  # handed off once: never sent again
    with clock.freeze(at(12)):
        down[0] = True
        late = book(b, 12.25, 12.5)  # its window closes at 12:40
        sync(b, late)
    with clock.freeze(at(13)):
        down[0] = False
        tick(b)  # the window has passed: no point sending it now
        assert len(mailbox) == 1


def test_the_code_email_names_the_end_date_when_the_window_crosses_midnight(b, mailbox):
    import re

    stamp = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d\d \w{3} \d\d:\d\d")
    with clock.freeze(at(8)):
        sync(b, book(b, 10, 11))
        sync(b, book(b, 12, 36))  # a day and a night: the window ends on another local date
    same_day, overnight = (m.body for m in mailbox[-2:])
    assert len(stamp.findall(same_day)) == 1 and len(stamp.findall(overnight)) == 2


def test_a_changed_holder_loses_the_code_and_the_new_holder_gets_one(client, owner, b, mailbox):
    """No route changes a booking's holder today (a client merge moves the code with the person); if one ever
    does, the tick revokes the old holder's code and issues and sends the new holder's within a minute."""
    other = adult(client, owner, b.location)
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            session.execute(text("UPDATE booking SET client_id = :c WHERE id = :b"), {"c": other["id"], "b": booking})
        tick(b)
        old, new = codes(b, booking)
        assert (old.status, old.revoke_reason, str(new.client_id)) == ("revoked", "not_entitled", other["id"])
        assert [m.to for m in mailbox][-1] == other["primary_email"]


def test_blocks_get_no_code_and_far_bookings_wait_for_the_horizon(b, mailbox):
    with clock.freeze(at(9)):
        block = book(b, 10, 11, kind="block")
        later = book(b, 24 * 9, 24 * 9 + 1)  # nine days out: beyond the seven-day horizon
        tick(b)
        assert codes(b, block) == [] and codes(b, later) == []
    with clock.freeze(at(24 * 3)):
        tick(b)  # the tick catches it up once it is inside the horizon
        assert [c.status for c in codes(b, later)] == ["active"] and mailbox


def test_a_code_expires_at_its_window_end_and_the_tick_reads_only_open_codes(client, b, monkeypatch):
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
    with clock.freeze(at(11) + timedelta(minutes=11)):  # the window closed at 11:10
        tick(b)
        [row] = codes(b, booking)
        assert (row.status, row.code_ciphertext, row.revoked_at) == ("expired", None, None)
        trail = scalar(b.tenant, select(AuditEvent.changes).where(AuditEvent.action == "access.entry_code.expire"))
        assert trail == {"status": ["active", "expired"]}  # the sealed code is cleared, never audited
        listed = ok(client.get(f"{API}/portal/entry-codes", headers=portal(client, b.tenant, b.person)), 200)["data"]
        assert listed == []
    synced = []
    monkeypatch.setattr(building, "sync_booking_code", lambda s, booking_id, view=None: synced.append(booking_id))
    with clock.freeze(at(24 * 3)):  # the booking is out of the schedule window; its spent code is not re-read
        tick(b)
    assert UUID(booking) not in synced
    index = scalar(b.tenant, select(text("indexdef")).select_from(text("pg_indexes")).where(
        text("indexname = 'ix_entry_code_open'")))  # fmt: skip
    assert "valid_until_at" in index and "status = 'active'" in index


def test_spent_codes_and_old_building_events_are_purged_after_retention(b):
    """The purge function keeps its own floor at the database's clock, so this test runs in real time: the
    spent booking happened more than RETENTION ago, the fresh one is tomorrow."""
    from datetime import UTC, datetime

    from app.modules.platform import retention

    hours = lambda when: (when - DAY).total_seconds() / 3600  # noqa: E731
    then = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0) - building.RETENTION - timedelta(days=3)
    with clock.freeze(then):
        spent = book(b, hours(then) + 1, hours(then) + 2)
        sync(b, spent)
    with clock.freeze(then + timedelta(hours=3)):
        tick(b)
    now = datetime.now(UTC)
    tomorrow = now.replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
    fresh = book(b, hours(tomorrow), hours(tomorrow) + 1)
    sync(b, fresh)
    with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
        gone = retention.purge(session)
    assert gone["building_event"] >= 1 and gone["entry_code"] == 1
    assert codes(b, spent) == [] and [c.status for c in codes(b, fresh)] == ["active"]
    with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
        assert (
            session.scalar(select(BuildingEvent.id).where(BuildingEvent.occurred_at < now - building.RETENTION)) is None
        )
        assert session.scalar(select(BuildingEvent.id).where(BuildingEvent.kind == "code_issued"))


def test_the_app_role_cannot_purge_a_recent_building_event_or_pass_a_bad_batch(client, owner, b):
    """app.purge_building_event is SECURITY DEFINER: whatever cutoff the caller passes, nothing younger than the
    retention period goes, and a non-positive or oversized batch is refused."""
    from sqlalchemy.exc import DBAPIError

    ok(client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={"reason": "Delivery"}))
    before = events_count(b)
    with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
        far = session.execute(text("SELECT app.purge_building_event(now() + interval '1 day', 100)")).scalar_one()
    assert far == 0 and events_count(b) == before
    for batch in (0, -1, 50_001):
        with pytest.raises(DBAPIError), tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            session.execute(text("SELECT app.purge_building_event(now(), :n)"), {"n": batch})


def test_merge_export_and_erasure_cover_entry_codes(client, owner, b, sim):
    from app.modules.access import subject

    other = adult(client, owner, b.location)
    with clock.freeze(at(9)):
        mine, theirs = book(b, 10, 11), book(b, 12, 13, holder=other["id"])
        sync(b, mine)
        sync(b, theirs)
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            subject._repoint(session, other["id"], b.person["id"])
        assert {str(c.client_id) for c in codes(b, mine) + codes(b, theirs)} == {b.person["id"]}
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            exported = subject._export(session, UUID(b.person["id"]))
            assert len(exported["entry_codes"]) == 2 and "code" not in exported["entry_codes"][0]
            assert {"valid_from_at", "valid_until_at", "status"} <= set(exported["entry_codes"][0])
            building._event(session, UUID(b.location), "code_withheld",
                            detail=f"not_known_adult:booking:7:client:{b.person['id']}")  # fmt: skip
            erased = subject._erase(session, UUID(b.person["id"]))
        assert erased["revoked_entry_codes"] == 2 and "entry_code" in subject._TABLES
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:  # nothing leads back to them
            details = session.scalars(select(BuildingEvent.detail).where(BuildingEvent.detail.is_not(None))).all()
            assert details and not any(b.person["id"] in d for d in details)
            assert "not_known_adult:booking:7:client:erased" in details
            trail = session.scalars(select(AuditEvent.changes).where(AuditEvent.action.in_(
                ("access.entry_code.revoke", "access.entry_code.erase")))).all()  # fmt: skip
            assert trail and not any(b.person["id"] in str(c) for c in trail)
            assert all(c.get("client_unlinked") is True for c in trail if "revoke_reason" in c and "erased" in str(c))
        for row in codes(b, mine) + codes(b, theirs):
            assert (row.status, row.revoke_reason, row.code_ciphertext, row.client_id) == (
                "revoked",
                "erased",
                None,
                None,
            )
        assert ("revoke_code", "door-front", str(row.id)) in sim.calls


# --- the door --------------------------------------------------------------------------------------------------


def wrong_for(code: str) -> str:
    return "00000000" if code != "00000000" else "11111111"


def details_of(f, kind: str) -> list[str]:
    with tenant_session(f.tenant.id, actor=system_principal("tests")) as session:
        return list(session.scalars(select(BuildingEvent.detail).where(BuildingEvent.kind == kind)
                                    .order_by(BuildingEvent.id)))  # fmt: skip


def events_count(f) -> int:
    return len(kinds(f))


def test_verify_allows_in_window_writes_a_door_check_in_and_never_locks_everyone_out(client, b):
    """Eight digits; wrong codes only slow the door down: a valid code is admitted while wrong codes keep coming."""
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        code = clear(b, codes(b, booking)[0])
        assert len(code) == 8 and code.isdigit()
        assert verify(client, b, code) == {"result": "deny", "unlock_seconds": 0}  # before the window
    with clock.freeze(at(9.8)):
        assert verify(client, b, code) == {"result": "allow", "unlock_seconds": 5}
        check_in = scalar(b.tenant, select(CheckIn).where(CheckIn.client_id == UUID(b.person["id"])))
        assert (check_in.channel, check_in.result) == ("door", "granted")
        import time

        for _ in range(20):
            assert verify(client, b, wrong_for(code))["result"] == "deny"
            began = time.monotonic()
            assert verify(client, b, code)["result"] == "allow"  # at the ceiling delay, still admitted
            assert time.monotonic() - began < building.DOOR_DELAYS[-1] + 3.0  # slack for a loaded test machine
    assert code not in str(
        scalar(b.tenant, select(AuditEvent.changes).where(AuditEvent.action == "access.door.verify"))
    )


def delay_at(location) -> float:
    import asyncio

    return asyncio.run(building.door_delay(location))


def test_wrong_codes_raise_the_delay_which_decays(client, b):
    with clock.freeze(at(9.8)):
        location = UUID(b.location)  # the delay is the location's: a code opens every door there
        assert delay_at(location) == building.DOOR_DELAYS[0]
        for n in range(1, 4):
            verify(client, b, f"{n:08d}")
            assert delay_at(location) == building.DOOR_DELAYS[n]
        for n in range(4, 9):
            verify(client, b, f"{n:08d}")
        assert delay_at(location) == building.DOOR_DELAYS[-1]  # the ceiling
    with clock.freeze(at(9.8) + building.DOOR_BAD_WINDOW + timedelta(seconds=1)):
        assert delay_at(location) == building.DOOR_DELAYS[0]  # wrong codes stopped: back to the floor


def test_a_live_code_outside_its_window_raises_the_delay_like_an_unknown_one(client, b):
    """Every deny counts, so the next wait does not tell a real code tried early from a guess; an allow never does,
    and only unknown codes count toward the staff alert."""
    with clock.freeze(at(8)):
        booking = book(b, 10, 11)
        sync(b, booking)
        code = clear(b, codes(b, booking)[0])
        location = UUID(b.location)
        assert verify(client, b, code)["result"] == "deny"  # before the window
        assert delay_at(location) == building.DOOR_DELAYS[1]
        assert verify(client, b, wrong_for(code))["result"] == "deny"
        assert delay_at(location) == building.DOOR_DELAYS[2]
    with clock.freeze(at(9.8)):
        assert verify(client, b, code)["result"] == "allow"
        assert verify(client, b, code)["result"] == "allow"
        assert delay_at(location) == building.DOOR_DELAYS[0]  # the earlier denies decayed; success adds nothing


def test_fifty_concurrent_wrong_codes_are_mostly_refused_unevaluated_and_alert_at_most_once(
    client, b, mailbox, monkeypatch
):
    """Verifies are serialised per door with a short queue: a flood beyond it is answered deny at once with no
    database work past authentication, no event and no audit row."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(building, "DOOR_DELAYS", (1.5,) * 5)  # the flood lands inside the first turn
    with clock.freeze(at(9.8)):
        before = len(details_of(b, "entry_denied"))
        with ThreadPoolExecutor(max_workers=8) as pool:
            answers = list(pool.map(lambda i: verify(client, b, f"{i:08d}")["result"], range(50)))
    assert answers == ["deny"] * 50
    assert len(details_of(b, "entry_denied")) - before <= building.DOOR_QUEUE + 1  # at most the queue was evaluated
    assert len(details_of(b, "bad_code_alert")) <= 1 and sum("wrong codes" in m.subject for m in mailbox) <= 1


def test_the_flood_path_and_a_short_code_touch_no_database_past_authentication(client, b, monkeypatch):
    from app.core import ratelimit
    from app.modules.access import router

    with clock.freeze(at(9.8)):
        before = events_count(b)

        def no_database(*args, **kwargs):
            raise AssertionError("the request session was opened")

        monkeypatch.setattr(router, "request_session", no_database)
        assert verify(client, b, "123456") == {"result": "deny", "unlock_seconds": 0}  # not CODE_DIGITS long
        ratelimit._redis().set(f"{ratelimit.PREFIX}:door-queue:{b.door}", building.DOOR_QUEUE + 1, ex=60)
        assert verify(client, b, "12345678") == {"result": "deny", "unlock_seconds": 0}  # the queue is full
        monkeypatch.undo()
    assert events_count(b) == before


def test_an_unknown_credential_is_401_at_once_with_no_row(client, b, monkeypatch):
    import time

    from app.modules.access import router

    monkeypatch.setattr(building, "DOOR_DELAYS", (2.0,) * 5)
    before = events_count(b)
    monkeypatch.setattr(router, "request_session", lambda *a, **k: (_ for _ in ()).throw(AssertionError("session")))
    began = time.monotonic()
    bogus = {"Authorization": f"Bearer fhb_{b.tenant.id}_{'x' * 40}"}
    assert client.post(f"{API}/door/verify", headers=bogus, json={"code": "12345678"}).status_code == 401
    assert time.monotonic() - began < 1.0 and events_count(b) == before


def test_a_flood_on_one_door_slows_but_never_denies_another_door(client, owner, b, monkeypatch):
    """The queue and turn are per door (door A's full queue never refuses door B); the wrong-code delay is per
    location (guessing at A slows B too), and a valid code at B is still admitted within the ceiling."""
    import time

    from app.core import ratelimit

    side = ok(client.post(f"{API}/door-devices", headers=owner,
                          json={"location_id": b.location, "name": "Side door", "device_ref": "door-side"}))  # fmt: skip
    monkeypatch.setattr(building, "DOOR_DELAYS", (0.0, 0.5, 1.0, 1.5, 2.0))
    with clock.freeze(at(9.8)):
        booking = book(b, 10, 11)
        sync(b, booking)
        code = clear(b, codes(b, booking)[0])
        for n in range(1, 4):
            verify(client, b, f"{n:08d}")  # the location climbs to 1.5 s
        ratelimit._redis().set(f"{ratelimit.PREFIX}:door-queue:{b.door}", building.DOOR_QUEUE + 1, ex=60)
        assert verify(client, b, code)["result"] == "deny"  # door A's queue is full
        began = time.monotonic()
        other = {"Authorization": f"Bearer {side['credential']}"}
        answer = ok(client.post(f"{API}/door/verify", headers=other, json={"code": code}), 200)
        took = time.monotonic() - began
    assert answer["result"] == "allow" and 1.5 <= took < building.DOOR_DELAYS[-1] + 3.0


def test_the_event_loop_keeps_running_while_verifies_wait(b, monkeypatch):
    import asyncio

    monkeypatch.setattr(building, "DOOR_DELAYS", (0.5,) * 5)

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        running = asyncio.create_task(ticker())

        async def one():
            ticket = await building.door_enter(UUID(b.door), UUID(b.location))
            await building.door_leave(ticket)
            return ticket is not None

        admitted = await asyncio.gather(one(), one())  # the second waits for the first's turn (BLPOP)
        running.cancel()
        return admitted, ticks

    admitted, ticks = asyncio.run(scenario())
    assert admitted == [True, True] and ticks >= 25  # ~1 s of waiting, the loop never blocked


def test_the_ip_bucket_only_ever_applies_to_unknown_credentials(client, b, monkeypatch):
    from app.core import ratelimit

    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setitem(cfg.buckets, "door-auth", cfg.buckets["door-auth"].model_copy(update={"limit": 1}))
    counted = []
    real_hit = ratelimit.hit
    monkeypatch.setattr(ratelimit, "hit", lambda *a, **k: counted.append(a[0]) or real_hit(*a, **k))
    for _ in range(3):  # a valid credential never touches the bucket
        assert verify(client, b, "12345678")["result"] == "deny"
    assert counted == []
    bogus = {"Authorization": f"Bearer fhb_{b.tenant.id}_{'x' * 40}"}
    assert client.post(f"{API}/door/verify", headers=bogus, json={"code": "12345678"}).status_code == 401
    before = events_count(b)
    for _ in range(3):  # the address is now far over the limit
        assert client.post(f"{API}/door/verify", headers=bogus, json={"code": "12345678"}).status_code == 429
    assert events_count(b) == before
    assert verify(client, b, "12345678")["result"] == "deny"  # the real lock behind the same address is served
    assert events_count(b) == before + 1


def test_no_connection_is_held_while_a_verify_waits(client, b, monkeypatch):
    import threading
    import time

    from app.core.db import app_engine

    monkeypatch.setattr(building, "DOOR_DELAYS", (1.0,) * 5)
    pool = app_engine().pool
    with clock.freeze(at(9.8)):
        baseline = pool.checkedout()
        waiting = threading.Thread(target=lambda: verify(client, b, "12345678"))
        waiting.start()
        time.sleep(0.5)  # inside the one-second wait
        assert pool.checkedout() == baseline
        waiting.join()


def test_limiter_down_denies_and_verify_takes_constant_time(client, b, monkeypatch):
    import time

    import redis

    from app.core import ratelimit

    with clock.freeze(at(9.8)):
        booking = book(b, 10, 11)
        sync(b, booking)
        code = clear(b, codes(b, booking)[0])
        monkeypatch.setattr(building, "EVAL_FLOOR_SECONDS", 0.3)
        for value in (code, wrong_for(code)):  # matched and unknown both take the evaluation floor
            began = time.monotonic()
            with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
                building.verify_code(session, session.get(building.DoorDevice, UUID(b.door)), value)
            assert time.monotonic() - began >= 0.3

        class Down:
            def __getattr__(self, name):
                raise redis.ConnectionError("down")

        before = events_count(b)
        monkeypatch.setattr(ratelimit, "_redis", lambda: Down())
        monkeypatch.setattr(building, "_aredis", lambda: Down())
        assert verify(client, b, code) == {"result": "deny", "unlock_seconds": 0}  # fail closed
    assert events_count(b) == before


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


def test_remote_unlock_needs_a_recent_step_up_and_api_keys_never_open_doors_or_hold_lights(client, tenant, b, sim):
    from app.core.auth.permissions import CATALOGUE
    from app.modules.integrations import service as integrations

    stale = login(client, tenant, elevated=False)
    refused = client.post(f"{API}/door-devices/{b.door}/unlock", headers=stale, json={"reason": "Phone call"})
    assert refused.status_code == 403 and refused.json()["code"] == "step-up-required"
    assert not [c for c in sim.calls if c[0] == "unlock"]
    assert "+" in CATALOGUE["access.door.unlock"].flags
    for key in ("access.door.unlock", "access.lighting.override"):
        assert key in integrations.KEY_WITHHELD and not integrations.grantable_to_key(CATALOGUE[key])


def door_check_ins(f) -> int:
    with tenant_session(f.tenant.id, actor=system_principal("tests")) as session:
        return len(session.scalars(select(CheckIn.id).where(CheckIn.channel == "door")).all())


def test_a_hung_staff_unlock_is_bounded_recorded_as_unknown_and_staff_are_told(client, owner, b, sim, monkeypatch):
    """The adapter gets what is left of the deadline as its own timeout; a call still in flight at the deadline may
    yet open the door, so the outcome is `unknown` (never `unlocked: false`) and the 409 says so."""
    monkeypatch.setattr(building, "DEVICE_TIMEOUT", 0.2)
    sim.fail("unlock", kind="hang")  # a stuck controller: sleeps a second, ignoring its timeout
    began = time.monotonic()
    dead = client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={"reason": "Phone call"})
    assert dead.status_code == 409 and time.monotonic() - began < 0.9
    assert dead.json()["code"] == "device-outcome-unknown" and "may have opened" in dead.json()["detail"]
    assert len(sim.timeouts) == 1 and 0 < sim.timeouts[0] <= 0.2
    trail = scalar(b.tenant, select(AuditEvent).where(AuditEvent.action == "access.door.unlock"))
    assert trail.reason == "Phone call" and trail.changes == {"unlocked": "unknown"}
    assert details_of(b, "command_failed") == ["unlock:unknown"]


def test_an_unlock_that_starts_after_its_deadline_never_reaches_the_adapter(client, owner, b, sim, monkeypatch):
    """A worker that only gets going after the caller gave up must not open the door later."""
    import concurrent.futures

    monkeypatch.setattr(building, "DEVICE_TIMEOUT", 0.1)
    real = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    class Late:  # every call starts 0.3 s late: after its 0.1 s deadline
        def submit(self, fn, *args):
            return real.submit(lambda: (time.sleep(0.3), fn(*args))[1])

    monkeypatch.setattr(building, "_DEVICE_POOL", Late())
    dead = client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={"reason": "Phone call"})
    assert dead.status_code == 409 and dead.json()["code"] == "device-unavailable"
    real.shutdown(wait=True)  # the late worker has run by now
    assert not [c for c in sim.calls if c[0] == "unlock"]
    trail = scalar(b.tenant, select(AuditEvent).where(AuditEvent.action == "access.door.unlock"))
    assert trail.changes == {"unlocked": False}


def test_with_every_device_worker_busy_an_unlock_is_refused_at_once(client, owner, b, sim, monkeypatch):
    import threading

    full = threading.BoundedSemaphore(1)
    full.acquire()
    monkeypatch.setattr(building, "_DEVICE_FREE", full)
    began = time.monotonic()
    busy = client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={"reason": "Phone call"})
    assert busy.status_code == 409 and busy.json()["code"] == "device-busy" and time.monotonic() - began < 0.5
    assert not [c for c in sim.calls if c[0] == "unlock"]
    full.release()
    assert ok(client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={"reason": "Again"}))


def test_member_unlock_opens_only_entrance_doors_and_records_the_entry_after_the_unlock(
    client, tenant, owner, b, sim, monkeypatch
):
    monkeypatch.setattr(get_settings().rate_limit, "enabled", True)
    add = lambda name, ref, entrance: ok(client.post(f"{API}/door-devices", headers=owner, json={  # noqa: E731
        "location_id": b.location, "name": name, "device_ref": ref, "is_entrance": entrance}))["id"]  # fmt: skip
    lobby, side = add("Lobby", "door-lobby", True), add("Fire exit", "door-side", False)
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
    with clock.freeze(at(10.5)):
        member = portal(client, tenant, b.person)
        sim.fail("unlock", times=2)  # both entrances fail: refused, nothing recorded as an entry, still audited
        dead = client.post(f"{API}/portal/bookings/{booking}/door-unlock", headers=member)
        assert dead.status_code == 409 and dead.json()["code"] == "device-unavailable" and door_check_ins(b) == 0
        trail = scalar(b.tenant, select(AuditEvent.changes).where(AuditEvent.action == "access.door.member_unlock"))
        assert trail == {"unlocked": False, "doors": {b.door: False, lobby: False}}
        sim.calls.clear()
        sim.fail("unlock")  # the front door fails, the lobby opens: allowed, one entry, per-door results kept
        opened = ok(client.post(f"{API}/portal/bookings/{booking}/door-unlock", headers=member), 200)
        assert opened["result"] == "allow" and door_check_ins(b) == 1
        assert sorted(c[1] for c in sim.calls if c[0] == "unlock") == ["door-front", "door-lobby"]
        assert all(c[1] != "door-side" for c in sim.calls) and side
        trails = scalar(b.tenant, select(AuditEvent.changes).where(AuditEvent.action == "access.door.member_unlock")
                        .order_by(AuditEvent.id.desc()).limit(1))  # fmt: skip
        assert trails["unlocked"] is True and sorted(trails["doors"].values()) == [False, True]  # one each
        codes_seen = [client.post(f"{API}/portal/bookings/{booking}/door-unlock", headers=member).status_code
                      for _ in range(8)]  # fmt: skip
        assert 429 in codes_seen  # the member path is rate limited per identity


# --- lights ----------------------------------------------------------------------------------------------------


def test_every_controller_call_names_its_tenant_and_location(client, owner, b, sim):
    with clock.freeze(at(9.95)):
        booking = book(b, 10, 11)
        sync(b, booking)
        cancel(b, booking)
        tick(b)
        tick(b)  # the second asks the controller what it shows
    ok(client.post(f"{API}/door-devices/{b.door}/unlock", headers=owner, json={"reason": "Phone call"}))
    ops = {scope[0] for scope in sim.scopes}
    assert {"push_code", "revoke_code", "set_zone", "read_zone", "unlock"} <= ops
    assert {scope[1:3] for scope in sim.scopes} == {(str(b.tenant.id), b.location)}


def test_lights_follow_holds_without_flicker_and_light_child_zones(b, sim):
    first, second = book(b, 10, 11), book(b, 11, 12)  # back to back on the whole court
    half = book(b, 13, 14, resources=[b.half_a])
    for hours, court, half_lit in ((9.95, True, True), (11, True, True), (12.2, False, False), (13, True, True)):
        with clock.freeze(at(hours)):
            tick(b)
            assert (sim.zones.get("relay-1"), sim.zones.get("relay-2")) == (court, half_lit), hours
    switched = [c for c in sim.calls if c[0] == "set_zone"]
    # on once at 9:57 (both zones: the court's hold covers its halves), off once after the run-on, then both on
    # again for the half court: the parent court's zone watches what lies below it
    assert switched == [("set_zone", "relay-1", True), ("set_zone", "relay-2", True), ("set_zone", "relay-1", False),
                        ("set_zone", "relay-2", False), ("set_zone", "relay-1", True),
                        ("set_zone", "relay-2", True)]  # fmt: skip
    with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
        scheduling.service.cancel_booking(session, scheduling.service.get_booking(session, UUID(half)))
    with clock.freeze(at(13.1)):
        tick(b)  # a cancelled booking is corrected on the next tick
        assert sim.zones["relay-2"] is False
    assert first and second


def test_the_request_log_never_holds_a_door_code_or_the_device_credential(client, b, caplog):
    """The code rides in the body and the credential in a header; the request log records the path only, and
    neither appears in it (core.api `_loggable_path` needs no prefix for these routes)."""
    import logging

    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        [row] = codes(b, booking)
    digits, credential = clear(b, row), b.device["Authorization"].split()[1]
    with caplog.at_level(logging.INFO, logger="app.request"), clock.freeze(at(10)):
        verify(client, b, digits)
        verify(client, b, "00000000")
    logged = [r for r in caplog.records if r.name == "app.request"]
    assert logged and all(r.path == f"{API}/door/verify" for r in logged)
    text = " ".join(f"{r.getMessage()} {vars(r)}" for r in logged)
    assert digits not in text and credential not in text and "00000000" not in text


def test_a_league_night_block_stays_dark_and_the_games_carved_out_of_it_light(b, sim):
    """A league night (main's shape: an unavailable block whose source is the competition) holds the courts but
    is nobody playing: no lights. Each of the competition's games takes its slot out of the night (`gives_way`)
    and lights its court."""
    night = ("leagues", "competition", uuid4())
    with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
        common = {"location_id": UUID(b.location), "resource_ids": [UUID(b.court)], "created_via": "staff"}
        scheduling.service.create_booking(session, kind="block", block_kind="unavailable", starts_at=at(18),
                                          ends_at=at(22), include_linked=False, buffer_before_min=0,
                                          buffer_after_min=0, source=night, **common)  # fmt: skip
        scheduling.service.create_booking(session, kind="game", starts_at=at(19), ends_at=at(20), gives_way=night,
                                          source=("leagues", "game", uuid4()), **common)  # fmt: skip
    for hours, lit in ((18.5, False), (19.5, True), (21, False)):
        with clock.freeze(at(hours)):
            tick(b)
            assert bool(sim.zones.get("relay-1")) is lit, hours


def test_a_quarter_court_booking_lights_the_zones_mapped_to_its_ancestors(b, sim):
    """Split courts: holds land on the booked resource and below, never above; zones mapped to the parent court
    and to the half both light for a booking on the quarter."""
    book(b, 10, 11, resources=[b.quarter])
    with clock.freeze(at(10.5)):
        tick(b)
        assert (sim.zones.get("relay-1"), sim.zones.get("relay-2")) == (True, True)


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
        assert ("set_zone", "relay-1", True) in sim.calls[-3:]
    with clock.freeze(at(10.5)):
        tick(b)  # the override ran out: the court goes back to its bookings (none)
        assert sim.zones["relay-1"] is False
    reason = scalar(tenant, select(AuditEvent.reason).where(AuditEvent.action == "access.lighting.override"))
    assert reason == "Cleaning"


def test_forcing_lights_off_on_a_court_in_play_needs_a_confirmed_reason_and_holds_at_most_a_day(client, owner, b, sim):
    book(b, 10, 11)
    url = f"{API}/lighting-zones/{b.court_zone}/override"
    with clock.freeze(at(10.5)):
        owner = login(client, b.tenant, b.tenant.owner_email)
        off = {"is_on": False, "until_at": at(12).isoformat(), "reason": "Leak"}
        assert client.put(url, headers=owner, json={**off, "reason": None}).status_code == 422  # reason required
        assert client.put(url, headers=owner, json={**off, "until_at": at(10.5 + 25).isoformat()}).status_code == 422
        refused = client.put(url, headers=owner, json=off)
        assert refused.status_code == 409 and refused.json()["code"] == "booking-in-progress"
        assert (
            ok(client.put(url, headers=owner, json={**off, "confirm_in_progress": True}), 200)["override_is_on"]
            is False
        )


def test_a_court_in_play_stays_lit_for_the_run_on_when_its_booking_is_cancelled(b, sim):
    booking = book(b, 10, 11)
    with clock.freeze(at(10.5)):
        tick(b)
        assert sim.zones["relay-1"] is True
    with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
        scheduling.service.cancel_booking(session, scheduling.service.get_booking(session, UUID(booking)))
    for minutes, lit in ((0, True), (1, True), (4, True), (6, False)):
        with clock.freeze(at(10.5) + timedelta(minutes=minutes, seconds=30)):
            tick(b)
            assert sim.zones["relay-1"] is lit, minutes


def test_a_controller_that_lost_power_is_told_again(b, sim, monkeypatch):
    book(b, 10, 12)
    with clock.freeze(at(10)):
        tick(b)
    sim.zones["relay-1"] = False  # the controller rebooted dark and says so
    with clock.freeze(at(10) + timedelta(minutes=1)):
        tick(b)
        assert sim.zones["relay-1"] is True
    monkeypatch.setattr(sim, "read_zone", lambda *_: None)  # one that cannot tell: re-asserted every five minutes
    sim.zones.clear()
    with clock.freeze(at(10) + timedelta(minutes=3)):
        tick(b)
        assert "relay-1" not in sim.zones
    with clock.freeze(at(10) + timedelta(minutes=6, seconds=30)):
        tick(b)
        assert sim.zones["relay-1"] is True


def cancel(f, booking: str) -> None:
    with tenant_session(f.tenant.id, actor=system_principal("tests")) as session:
        scheduling.service.cancel_booking(session, scheduling.service.get_booking(session, UUID(booking)))
    handlers.on_booking_cancelled.fn(str(f.tenant.id), str(uuid4()), {"booking_id": booking})


def test_a_failed_revoke_is_retried_by_the_tick_until_the_controller_confirms(b, sim):
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        sync(b, booking)
        sim.fail("revoke_code", times=2)
        cancel(b, booking)
        [row] = codes(b, booking)
        assert (row.status, row.revoke_due) == ("revoked", True)
        tick(b)
        assert codes(b, booking)[0].revoke_due is True  # still refused: still due
        tick(b)
        assert codes(b, booking)[0].revoke_due is False  # confirmed
        tick(b)
        assert [c for c in sim.calls if c[0] == "revoke_code"] == [("revoke_code", "door-front", str(row.id))] * 3
        assert details_of(b, "command_failed") == ["revoke_code"]  # one row, not one per retry


def test_a_partly_pushed_code_is_revoked_at_every_door(client, owner, b, sim):
    ok(client.post(f"{API}/door-devices", headers=owner,
                   json={"location_id": b.location, "name": "Lobby", "device_ref": "door-lobby"}))  # fmt: skip
    with clock.freeze(at(9)):
        sim.fail("push_code")  # the first door refuses, the second takes it
        booking = book(b, 10, 11)
        sync(b, booking)
        [row] = codes(b, booking)
        assert row.pushed_at is None and len([c for c in sim.calls if c[0] == "push_code"]) == 2
        cancel(b, booking)
        assert sorted(c[1] for c in sim.calls if c[0] == "revoke_code") == ["door-front", "door-lobby"]


def test_without_an_adapter_each_zone_and_door_shows_one_not_configured_state(client, owner, b, monkeypatch):
    monkeypatch.setattr(building_control, "_controller", None)
    with clock.freeze(at(9.9)):
        booking = book(b, 10, 11)
        for _ in range(3):
            tick(b)
        assert details_of(b, "command_failed") == [] and [c.status for c in codes(b, booking)] == ["active"]
    status = ok(client.get(f"{API}/building-status?location_id={b.location}", headers=owner), 200)  # real clock
    assert status["adapter"] == "none"
    assert {z["sync_state"] for z in status["zones"]} == {"adapter_not_configured"}
    assert {d["sync_state"] for d in status["doors"]} == {"adapter_not_configured"}


def test_a_failing_lights_step_never_rolls_back_the_codes_step(b, sim, monkeypatch):
    def broken(session, location_id):
        raise RuntimeError("lights step blew up")

    monkeypatch.setattr(building, "reconcile_lights", broken)
    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        tick(b)  # does not raise: one step's failure is logged and the next tick tries again
        assert [c.status for c in codes(b, booking)] == ["active"]


def test_a_tick_skips_codes_another_tick_is_syncing_and_races_never_fail(b, sim):
    import threading

    with clock.freeze(at(9)):
        booking = book(b, 10, 11)
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as other:
            assert building._codes_lock(other, UUID(b.location))  # another tick holds this location's codes
            tick(b)  # skips the codes step, still runs the lights, raises nothing
            assert codes(b, booking) == []
        tick(b)
        assert [c.status for c in codes(b, booking)] == ["active"]
        late = book(b, 12, 13)
        started, errors = threading.Barrier(2), []

        def handler():  # an event handler syncing the same booking while the tick does
            try:
                with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
                    started.wait()
                    building.sync_booking_code(session, UUID(late))
                    time.sleep(0.3)  # commit after the tick's insert has to wait on the unique index
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=handler)
        thread.start()
        started.wait()
        time.sleep(0.1)
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            building.sync_booking_code(session, UUID(late))
        thread.join()
        assert errors == [] and [c.status for c in codes(b, late)] == ["active"]


def test_override_waits_for_the_zone_row_lock(client, owner, b, sim):
    import threading

    held = threading.Event()

    def hold():
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            session.execute(text("SELECT id FROM lighting_zone WHERE id = :z FOR UPDATE"), {"z": b.court_zone})
            held.set()
            time.sleep(0.5)

    thread = threading.Thread(target=hold)
    thread.start()
    held.wait()
    began = time.monotonic()
    ok(client.put(f"{API}/lighting-zones/{b.court_zone}/override", headers=owner, json={"is_on": None}), 200)
    thread.join()
    assert time.monotonic() - began >= 0.4


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


def test_one_failing_booking_never_rolls_back_the_ticks_other_codes_or_reaches_a_keypad(b, sim, mailbox, monkeypatch):
    """Each booking syncs under its own savepoint; controller calls and code emails run only after commit, so the
    failing booking's rolled-back code is never pushed nor sent, and the others still are."""
    with clock.freeze(at(9)):
        good, bad = book(b, 10, 11), book(b, 12, 13)
        real = building.deliver_code_to

        def flaky(session, row, client_id):
            if str(row.booking_id) == bad:
                raise RuntimeError("boom")
            return real(session, row, client_id)

        monkeypatch.setattr(building, "deliver_code_to", flaky)
        tick(b)
        [kept] = codes(b, good)
        assert codes(b, bad) == [] and kept.pushed_at is not None
        assert [c for c in sim.calls if c[0] == "push_code"] == [("push_code", "door-front", str(kept.id))]
        assert len(mailbox) == 1
        monkeypatch.setattr(building, "deliver_code_to", real)
        sim.calls.clear()
        with tenant_session(b.tenant.id, actor=system_principal("tests")) as session:
            building.sync_booking_code(session, UUID(bad))
            assert sim.calls == []  # nothing reaches the controller before the commit
        assert [c[0] for c in sim.calls] == ["push_code"]
