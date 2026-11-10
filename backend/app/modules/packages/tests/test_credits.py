"""The session-credit ledger (PKG-12, PKG-14): its life cycle and idempotency, the cache against the entries,
concurrency on the last credit, the scheduling event interface with synthetic events, and membership add-ons
(MEM-04) driven by memberships events."""

import threading
from datetime import date
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core import events
from app.core.errors import Conflict
from app.core.events import Event, OutboxEvent
from app.modules import memberships
from app.modules.memberships.tests.support import (
    API,
    SYSTEM,
    at,
    charges,
    deliver_events,
    event_types,
    membership_plan,
    ok,
    package_plan,
    refused,
    sale,
    tx,
    world,
)
from app.modules.packages import handlers, service
from app.modules.packages.models import ClientPackage, CreditLedgerEntry
from app.modules.packages.tests.test_packages import ledger, pack, package, reserve, sell_at, settle
from conftest import new_client

D = date


@pytest.fixture
def w(client, tenant, owner):
    return world(client, owner, tenant)


def _sold(w, client, owner, **plan_fields) -> ClientPackage:
    plan = package_plan(client, owner, w.tenant, **plan_fields)
    return package(w.tenant, ok(client.post(f"{API}/client-packages", headers=owner, json=pack(w, plan)), 201)["id"])


def _counts(pkg: ClientPackage) -> tuple[int, int, int, int, int]:
    return (pkg.sessions_granted_count, pkg.sessions_reserved_count, pkg.sessions_consumed_count,
            pkg.sessions_forfeited_count, service.available(pkg))  # fmt: skip


def _cache_matches_ledger(tenant, package_id) -> bool:
    """The nightly reconciliation's assertion: the four counters equal the sums of the append-only entries."""
    e = CreditLedgerEntry
    with tx(tenant) as session:
        sums = session.execute(
            select(func.coalesce(func.sum(e.granted_delta), 0), func.coalesce(func.sum(e.reserved_delta), 0),
                   func.coalesce(func.sum(e.consumed_delta), 0), func.coalesce(func.sum(e.forfeited_delta), 0))
            .where(e.client_package_id == package_id)
        ).one()  # fmt: skip
        pkg = session.get(ClientPackage, package_id)
        return tuple(int(v) for v in sums) == _counts(pkg)[:4]


# --- life cycle --------------------------------------------------------------------------------------------------


def test_reserve_consume_release_and_restore_are_idempotent_per_booking(w, client, owner):
    pkg, person = _sold(w, client, owner, session_count=3), w.person["id"]
    first, second, third = uuid4(), uuid4(), uuid4()
    held = reserve(w.tenant, pkg.id, person, first)
    assert (held.entry_type, held.reason, held.reserved_delta, held.idempotency_key) == (
        "reserve",
        "booking",
        1,
        f"booking:{first}:reserve:1",
    )
    assert reserve(w.tenant, pkg.id, person, first) is None  # the same booking again: nothing happens
    assert _counts(package(w.tenant, pkg.id)) == (3, 1, 0, 0, 2)

    used = settle(w.tenant, first, "attended")
    assert (used.entry_type, used.reserved_delta, used.consumed_delta, used.reason) == ("consume", -1, 1, "attendance")
    assert settle(w.tenant, first, "attended") is None and settle(w.tenant, first, "early_cancel") is None
    assert reserve(w.tenant, pkg.id, person, first) is None  # consumed bookings do not reserve again
    assert _counts(package(w.tenant, pkg.id)) == (3, 0, 1, 0, 2)

    with tx(w.tenant) as session:  # the mark was wrong: the credit comes back
        back = service.restore_credit(session, source_type="booking", source_id=first)
        assert (
            back.entry_type == "restore"
            and service.restore_credit(session, source_type="booking", source_id=first) is None
        )
        assert service.restore_credit(session, source_type="booking", source_id=uuid4()) is None
    assert _counts(package(w.tenant, pkg.id)) == (3, 0, 0, 0, 3)
    assert reserve(w.tenant, pkg.id, person, first).idempotency_key == f"booking:{first}:reserve:4"  # booked again

    reserve(w.tenant, pkg.id, person, second)
    released = settle(w.tenant, second, "early_cancel")
    assert (released.entry_type, released.reason, released.reserved_delta) == ("release", "cancellation_early", -1)
    assert settle(w.tenant, uuid4(), "attended") is None  # a booking that never used a package
    assert event_types(w.tenant, pkg.id) == [
        "packages.package.sold",
        "packages.credit.consumed",
        "packages.credit.restored",
    ]

    other = _sold(w, client, owner)
    reserve(w.tenant, pkg.id, person, third)
    with pytest.raises(Conflict) as elsewhere:
        reserve(w.tenant, other.id, person, third)
    assert elsewhere.value.code == "credit-already-reserved"
    with pytest.raises(Conflict) as wrong_type:
        reserve(w.tenant, pkg.id, person, reservation_type_id=uuid4())
    assert wrong_type.value.code == "package-wrong-type"
    assert reserve(w.tenant, pkg.id, person, reservation_type_id=pkg.reservation_type_id) is not None
    assert _cache_matches_ledger(w.tenant, pkg.id) and _counts(package(w.tenant, pkg.id)) == (3, 3, 0, 0, 0)
    page = ok(client.get(f"{API}/client-packages/{pkg.id}/ledger?entry_type=reserve", headers=owner))["data"]
    assert len(page) == 5 and {e["source_type"] for e in page} == {"booking"}


def test_late_cancel_and_no_show_follow_the_package_settings(w, client, owner):
    pkg, person = _sold(w, client, owner, session_count=6), w.person["id"]

    def outcome(kind: str) -> str:
        booking = uuid4()
        reserve(w.tenant, pkg.id, person, booking)
        return settle(w.tenant, booking, kind).entry_type

    assert (outcome("late_cancel"), outcome("no_show")) == ("consume", "consume")  # the defaults charge both
    ok(
        client.patch(
            f"{API}/package-settings",
            headers=owner,
            json={"is_late_cancel_charged": False, "is_no_show_charged": False},
        )
    )
    assert (outcome("late_cancel"), outcome("no_show"), outcome("early_cancel")) == ("release", "release", "release")
    assert [e.reason for e in ledger(w.tenant, pkg.id) if e.entry_type != "reserve"] == [
        "purchase", "cancellation_late", "no_show", "cancellation_late", "no_show", "cancellation_early"]  # fmt: skip
    assert _counts(package(w.tenant, pkg.id)) == (6, 0, 2, 0, 4)


def test_exhaustion_status_and_manual_adjustments(w, client, owner):
    pkg, person = _sold(w, client, owner, session_count=2), w.person["id"]
    last = uuid4()
    reserve(w.tenant, pkg.id, person)
    reserve(w.tenant, pkg.id, person, last)
    assert (
        package(w.tenant, pkg.id).status == "exhausted"
        and event_types(w.tenant, pkg.id)[-1] == "packages.package.exhausted"
    )
    with pytest.raises(Conflict) as empty:
        reserve(w.tenant, pkg.id, person)
    assert empty.value.code == "package-exhausted"
    settle(w.tenant, last, "early_cancel")
    assert package(w.tenant, pkg.id).status == "active"  # a returned credit reopens the package

    url = f"{API}/client-packages/{pkg.id}/credit-adjustments"
    more = ok(client.post(url, headers=owner, json={"delta": 3, "note": "Goodwill after a cancelled class"}))
    assert (more["sessions_granted_count"], more["sessions_available_count"]) == (5, 4)
    refused(client.post(url, headers=owner, json={"delta": -5, "note": "Too many"}), 409, "package-exhausted")
    assert client.post(url, headers=owner, json={"delta": 0, "note": "x"}).status_code == 422
    assert client.post(url, headers=owner, json={"delta": 1}).status_code == 422  # a note is required
    less = ok(client.post(url, headers=owner, json={"delta": -4, "note": "Entered twice"}))
    assert (less["sessions_available_count"], less["status"]) == (0, "exhausted")
    adjusted = [e for e in ledger(w.tenant, pkg.id) if e.entry_type == "adjust"]
    assert [(e.granted_delta, e.reason, e.actor_type) for e in adjusted] == [
        (3, "staff_adjustment", "staff"),
        (-4, "staff_adjustment", "staff"),
    ]
    assert _cache_matches_ledger(w.tenant, pkg.id)

    unlimited = _sold(w, client, owner, session_mode="unlimited", session_count=None)
    for _ in range(3):
        reserve(w.tenant, unlimited.id, person)
    assert (
        _counts(package(w.tenant, unlimited.id)) == (0, 3, 0, 0, -3)
        and package(w.tenant, unlimited.id).status == "active"
    )
    refused(client.post(f"{API}/client-packages/{unlimited.id}/credit-adjustments", headers=owner, json={"delta": 1, "note": "x"}),
            409, "invalid-state-transition")  # fmt: skip


def test_the_ledger_is_append_only_and_the_database_guards_the_balance(w, client, owner):
    pkg = _sold(w, client, owner, session_count=1)
    for statement in ("UPDATE credit_ledger_entry SET note = 'edited'", "DELETE FROM credit_ledger_entry"):
        with pytest.raises(DBAPIError, match="permission denied"), tx(w.tenant) as session:
            session.execute(text(statement))
    # the CHECK is the last line of defence should code ever skip the lock: it maps to 409 package-exhausted
    with pytest.raises(IntegrityError, match="ck_client_package_balance"), tx(w.tenant) as session:
        session.execute(text("UPDATE client_package SET sessions_reserved_count = 2 WHERE id = :id"), {"id": pkg.id})
    with pytest.raises(IntegrityError, match="ck_credit_ledger_entry_shape"), tx(w.tenant) as session:
        session.add(CreditLedgerEntry(client_package_id=pkg.id, client_id=pkg.owner_client_id, entry_type="reserve",
                                      reason="booking", reserved_delta=2, idempotency_key=uuid4().hex, actor_type="system"))  # fmt: skip
    key = ledger(w.tenant, pkg.id)[0].idempotency_key
    with pytest.raises(IntegrityError, match="uq_credit_ledger_entry_key"), tx(w.tenant) as session:
        session.add(CreditLedgerEntry(client_package_id=pkg.id, client_id=pkg.owner_client_id, entry_type="grant",
                                      reason="purchase", granted_delta=1, idempotency_key=key, actor_type="system"))  # fmt: skip


# --- concurrency -------------------------------------------------------------------------------------------------


def _race(count: int, work) -> list:
    barrier, outcomes = threading.Barrier(count), []

    def run(index: int) -> None:
        barrier.wait()
        try:
            outcomes.append(work(index))
        except Conflict as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def test_bookings_racing_for_the_last_credits_never_oversell(w, client, owner):
    pkg, person = _sold(w, client, owner, session_count=3), w.person["id"]
    outcomes = _race(10, lambda index: reserve(w.tenant, pkg.id, person).entry_type)
    assert sorted(outcomes) == ["package-exhausted"] * 7 + ["reserve"] * 3
    after = package(w.tenant, pkg.id)
    assert _counts(after) == (3, 3, 0, 0, 0) and after.status == "exhausted"
    assert len(ledger(w.tenant, pkg.id)) == 4 and _cache_matches_ledger(w.tenant, pkg.id)


def test_one_booking_delivered_many_times_at_once_reserves_once(w, client, owner):
    pkg, person, booking = _sold(w, client, owner, session_count=5), w.person["id"], uuid4()
    outcomes = _race(8, lambda index: getattr(reserve(w.tenant, pkg.id, person, booking), "entry_type", None))
    assert sorted(map(str, outcomes)) == ["None"] * 7 + ["reserve"]
    assert _counts(package(w.tenant, pkg.id)) == (5, 1, 0, 0, 4)
    settled = _race(6, lambda index: getattr(settle(w.tenant, booking, "attended"), "entry_type", None))
    assert sorted(map(str, settled)) == ["None"] * 5 + ["consume"]
    assert _counts(package(w.tenant, pkg.id)) == (5, 0, 1, 0, 4) and _cache_matches_ledger(w.tenant, pkg.id)


def test_mixed_concurrent_traffic_keeps_cache_and_ledger_equal(w, client, owner):
    pkg, person = _sold(w, client, owner, session_count=6), w.person["id"]
    held = [uuid4() for _ in range(4)]
    for booking in held:
        reserve(w.tenant, pkg.id, person, booking)

    def work(index: int):
        if index < 4:  # four bookings settle while eight more fight for what is left and what comes back
            return settle(w.tenant, held[index], "attended" if index % 2 else "early_cancel").entry_type
        return reserve(w.tenant, pkg.id, person).entry_type

    outcomes = _race(12, work)
    after = package(w.tenant, pkg.id)
    assert outcomes.count("consume") == 2 and outcomes.count("release") == 2
    assert 2 <= outcomes.count("reserve") <= 4 and outcomes.count("reserve") + outcomes.count("package-exhausted") == 8
    assert after.sessions_consumed_count == 2 and after.sessions_reserved_count == outcomes.count("reserve")
    assert service.available(after) >= 0 and _cache_matches_ledger(w.tenant, pkg.id)


# --- the scheduling interface, with synthetic events -------------------------------------------------------------


class _BookingEvent(Event):
    aggregate_type: ClassVar[str] = "booking"
    type: str
    booking_id: UUID
    client_id: UUID | None = None
    client_package_id: UUID | None = None
    starts_on: date | None = None
    reservation_type_id: UUID | None = None
    is_late: bool | None = None
    outcome: str | None = None


def _publish(tenant, kind: str, booking_id: UUID, **fields) -> None:
    with tx(tenant) as session:
        events.publish(
            session, _BookingEvent(type=f"scheduling.booking.{kind}", booking_id=booking_id, **fields), booking_id
        )
    deliver_events()


def test_booking_events_move_credits_through_the_outbox(w, client, owner):
    pkg = _sold(w, client, owner, session_count=4)
    person = UUID(w.person["id"])
    attended, late, missed, unpaid = uuid4(), uuid4(), uuid4(), uuid4()
    for booking in (attended, late, missed):
        _publish(
            w.tenant,
            "created",
            booking,
            client_id=person,
            client_package_id=pkg.id,
            reservation_type_id=pkg.reservation_type_id,
        )
    _publish(w.tenant, "created", unpaid, client_id=person)  # a booking no package pays for
    assert _counts(package(w.tenant, pkg.id)) == (4, 3, 0, 0, 1)
    _publish(w.tenant, "completed", attended, outcome="attended")
    _publish(w.tenant, "cancelled", late, is_late=True)
    _publish(w.tenant, "completed", missed, outcome="no_show")
    _publish(w.tenant, "cancelled", unpaid)
    assert _counts(package(w.tenant, pkg.id)) == (4, 0, 3, 0, 1)  # late cancel and no-show are charged by default
    reasons = [e.reason for e in ledger(w.tenant, pkg.id) if e.entry_type == "consume"]
    assert sorted(reasons) == ["attendance", "cancellation_late", "no_show"]
    assert {e.actor_type for e in ledger(w.tenant, pkg.id) if e.source_id} == {"system"}

    early = uuid4()
    _publish(w.tenant, "created", early, client_id=person, client_package_id=pkg.id)
    _publish(w.tenant, "cancelled", early)
    assert _counts(package(w.tenant, pkg.id)) == (4, 0, 3, 0, 1) and _cache_matches_ledger(w.tenant, pkg.id)

    # a redelivered event is skipped by the handler's processed_event row, and the service is idempotent anyway
    with tx(w.tenant) as session:
        event = session.scalars(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == attended).order_by(OutboxEvent.id)
        ).first()
    before = len(ledger(w.tenant, pkg.id))
    for _ in range(2):
        handlers.on_booking_created.fn(str(w.tenant.id), str(event.id), event.payload)
    with tx(w.tenant) as session:
        service.booking_created(session, event.payload)
    assert len(ledger(w.tenant, pkg.id)) == before


def test_a_booking_the_package_cannot_pay_is_reported_back_not_dropped(w, client, owner):
    pkg = _sold(w, client, owner, session_count=1)
    person, stranger = UUID(w.person["id"]), UUID(new_client(client, owner, w.location_id)["id"])
    reserve(w.tenant, pkg.id, person)
    for booking, who, code in ((uuid4(), person, "package-exhausted"), (uuid4(), stranger, "package-not-shared")):
        _publish(w.tenant, "created", booking, client_id=who, client_package_id=pkg.id)
        with tx(w.tenant) as session:
            failed = session.scalars(select(OutboxEvent.payload).where(
                OutboxEvent.event_type == "packages.credit.reservation_failed", OutboxEvent.aggregate_id == pkg.id)).all()  # fmt: skip
        mine = [f for f in failed if f["source_id"] == str(booking)]
        assert [(f["code"], f["client_id"]) for f in mine] == [(code, str(who))]
    assert _counts(package(w.tenant, pkg.id)) == (1, 1, 0, 0, 0)


# --- membership add-ons (MEM-04) ---------------------------------------------------------------------------------


def test_bundled_package_is_granted_once_follows_the_membership_and_goes_with_it(w, client, owner):
    lessons = package_plan(client, owner, w.tenant, session_count=4, auto_renew_lead_count=None)
    plan = membership_plan(client, owner, w.tenant)
    with_addon = ok(client.put(f"{API}/membership-plans/{plan['id']}/addons", headers=owner,
                               json={"addons": [{"package_plan_id": lessons["id"], "quantity": 2}]}))  # fmt: skip
    assert [(a["package_plan_id"], a["quantity"]) for a in with_addon["addons"]] == [(lessons["id"], 2)]
    assert client.put(f"{API}/membership-plans/{plan['id']}/addons", headers=owner,
                      json={"addons": [{"package_plan_id": str(uuid4())}]}).status_code == 422  # fmt: skip
    w.plan = plan
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    deliver_events()  # memberships.contract.activated reaches the packages handler
    granted = ok(client.get(f"{API}/client-packages?source_contract_id={sold['id']}", headers=owner))["data"]
    assert len(granted) == 1
    bundled = granted[0]
    assert (bundled["sessions_granted_count"], bundled["price_minor"], bundled["invoice_mode"], bundled["sales_channel"]) == (
        8, 0, "none", "membership_addon")  # fmt: skip
    assert bundled["charge_id"] is None and [c.source_context for c in charges(w.tenant, w.person["id"])] == [
        "memberships"
    ]
    assert ledger(w.tenant, bundled["id"])[0].reason == "addon"
    with tx(w.tenant) as session:
        assert service.grant_contract_addons(session, UUID(sold["id"])) == 0  # already granted: nothing to do
    assert len(ok(client.get(f"{API}/client-packages?source_contract_id={sold['id']}", headers=owner))["data"]) == 1

    person = w.person["id"]
    assert reserve(w.tenant, UUID(bundled["id"]), person) is not None
    ok(client.post(f"{API}/membership-contracts/{sold['id']}/suspensions", headers=owner), 201)
    with pytest.raises(Conflict) as suspended:  # the reference's possible defect, U-295: ours refuses
        reserve(w.tenant, UUID(bundled["id"]), person)
    assert suspended.value.code == "membership-not-active"
    with tx(w.tenant) as session:
        assert service.spendable_packages(session, UUID(person)) == []
        assert memberships.service.status_of(session, UUID(sold["id"])) == "suspended"

    ok(client.post(f"{API}/membership-contracts/{sold['id']}/cancel", headers=owner, json={"reason": "voluntary"}))
    deliver_events()
    gone = ok(client.get(f"{API}/client-packages/{bundled['id']}", headers=owner))
    assert (gone["status"], gone["removal_mode"], gone["sessions_reserved_count"]) == ("removed", "billing_kept", 0)

    keeper = world(client, owner, w.tenant)
    keeper.plan = plan
    kept = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(keeper)), 201)
    deliver_events()
    ok(client.post(f"{API}/membership-contracts/{kept['id']}/cancel", headers=owner,
                   json={"reason": "voluntary", "cancel_bundled_packages": False}))  # fmt: skip
    deliver_events()
    left = ok(client.get(f"{API}/client-packages?source_contract_id={kept['id']}", headers=owner))["data"]
    assert [p["status"] for p in left] == ["active"]  # the cancel dialog said to leave it


def test_a_bundled_package_renews_from_its_own_plan_at_the_plan_price(w, client, owner):
    lessons = package_plan(client, owner, w.tenant, session_count=4, validity_count=1, validity_unit="month",
                           auto_renew_lead_count=0, auto_renew_lead_unit="day")  # fmt: skip
    w.plan = membership_plan(client, owner, w.tenant)
    ok(
        client.put(
            f"{API}/membership-plans/{w.plan['id']}/addons",
            headers=owner,
            json={"addons": [{"package_plan_id": lessons["id"]}]},
        )
    )
    with at(D(2025, 1, 10)), tx(w.tenant) as session:
        sold = memberships.service.sell_contract(session, SYSTEM, {
            "client_id": UUID(w.person["id"]), "location_id": UUID(w.location_id), "membership_plan_id": UUID(w.plan["id"])})  # fmt: skip
        assert service.grant_contract_addons(session, sold["id"]) == 1
        first = session.scalars(select(ClientPackage).where(ClientPackage.source_contract_id == sold["id"])).one()
    assert (first.price_minor, first.renew_on, first.is_auto_renew) == (0, D(2025, 2, 9), True)
    with at(D(2025, 2, 9)), tx(w.tenant) as session:
        assert service.run_daily(session)["renewed"] == 1
        second = service._successor(session, first.id)
    assert (second.price_minor, second.invoice_mode, second.source_contract_id, second.valid_during.lower) == (
        10000, "single", None, D(2025, 2, 10))  # fmt: skip


# --- the daily job as an actor -----------------------------------------------------------------------------------


def test_daily_actor_is_idempotent_and_isolates_failures(w, client, owner):
    plan = package_plan(
        client,
        owner,
        w.tenant,
        validity_count=1,
        validity_unit="week",
        auto_renew_lead_count=0,
        auto_renew_lead_unit="day",
    )
    good = sell_at(w, plan, D(2025, 1, 6))
    other = world(client, owner, w.tenant)
    bad = sell_at(other, plan, D(2025, 1, 6))
    ok(client.post(f"{API}/clients/{other.person['id']}/disable", headers=owner))  # its renewal cannot be billed
    with at(D(2025, 1, 12)):
        first = service.run_package_day.fn(str(w.tenant.id))
        again = service.run_package_day.fn(str(w.tenant.id))
    assert (first["renewed"], first["expired"], [f["id"] for f in first["failed"]]) == (1, 0, [str(bad.id)])
    assert (again["renewed"], again["expired"], len(again["failed"])) == (0, 0, 1)
    with at(D(2025, 1, 13)):
        assert service.run_package_day.fn(str(w.tenant.id))["expired"] == 2
        assert service.run_package_day.fn(str(w.tenant.id))["expired"] == 0
    with tx(w.tenant) as session:
        assert service._successor(session, good.id) is not None and service._successor(session, bad.id) is None
