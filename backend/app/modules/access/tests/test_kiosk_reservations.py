"""The kiosk reservation page, booking from it and auto-book (CHK-05, CHK-06; owner decisions 2026-11-13, question
15). Booking runs the portal's rules for the client the kiosk identified: the kiosk adds no bypass. A visit found by
name books only what consumes nothing; spending a package needs a card or the app's code (possession)."""

import secrets
import threading
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db import tenant_session
from app.main import app as fastapi_app
from app.modules import clients
from app.modules.access.domain import cards
from app.modules.access.models import CheckIn, Credential, KioskDevice
from app.modules.access.tests.test_checkin import _pair, ok
from app.modules.memberships.tests.support import API, package_plan, world
from app.modules.programs.models import Enrollment
from conftest import new_client, scalar


def soon(client, owner, loc: str, minutes: int, *, free: bool = True, capacity: int = 5) -> SimpleNamespace:
    """A confirmed, self-bookable session at `loc` starting `minutes` from now, on its own type and resource."""
    tag = uuid4().hex[:6]
    rtype = ok(client.post(f"{API}/reservation-types", headers=owner, json={
        "location_id": loc, "name": f"Class {tag}", "default_capacity": capacity, "default_allows_free_booking": free,
    }), 201)  # fmt: skip
    group = ok(client.post(f"{API}/resource-groups", headers=owner, json={"location_id": loc, "name": f"G {tag}"}), 201)
    room = ok(client.post(f"{API}/resources", headers=owner,
                          json={"location_id": loc, "resource_group_id": group["id"], "name": f"Room {tag}"}), 201)  # fmt: skip
    starts = (clock.now() + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
    booking = ok(client.post(f"{API}/bookings", headers=owner, json={
        "location_id": loc, "kind": "session", "reservation_type_id": rtype["id"], "starts_at": starts.isoformat(),
        "ends_at": (starts + timedelta(hours=1)).isoformat(), "resources": [{"resource_id": room["id"], "role": "primary"}],
    }), 201)  # fmt: skip
    return SimpleNamespace(id=booking["booking"]["session"]["id"], type_id=rtype["id"])


@pytest.fixture
def k(client, tenant, owner):
    w = world(client, owner, tenant)
    person = new_client(client, owner, w.location_id, first_name="Robin", last_name=f"Kiosk{uuid4().hex[:6]}")
    _pair(client, tenant, owner, w.location_id)
    return SimpleNamespace(loc=w.location_id, person=person, tenant=tenant)


def enter(client, person, card: str | None = None, *, typed: bool = False) -> dict:
    """Self check-in found by name, by scanning `card` (possession), or by typing `card` into a lookup (not)."""
    if card and not typed:
        return ok(client.post(f"{API}/kiosk/check-ins", json={"card_payload": card}), 201)
    body = {"credential_value": card} if card else {"last_name_prefix": person["last_name"]}
    found = ok(client.post(f"{API}/kiosk/lookups", json=body))["matches"]
    return ok(client.post(f"{API}/kiosk/check-ins", json={"match_token": found[0]["match_token"]}), 201)


def app_qr(tenant, person) -> str:
    """The rotating QR of an app card issued to `person`: the one value that proves possession at the kiosk."""
    secret = secrets.token_bytes(32)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        row = Credential(client_id=person["id"], kind="app_card", value=f"APP{secrets.token_hex(8).upper()}",
                         source="app_issued", secret_ciphertext=secret, issued_at=clock.now())  # fmt: skip
        session.add(row)
        session.flush()
        seed = cards.seed(row.id, secret)
    return cards.qr_text(seed, clock.now())


def card_of(client, owner, person) -> str:
    value = f"KC-{uuid4().hex[:8]}"
    ok(
        client.post(
            f"{API}/clients/{person['id']}/credentials", headers=owner, json={"kind": "barcode", "value": value}
        ),
        201,
    )
    return value


def book(client, visit: dict, session_id, key: str | None = None):
    """Book from the page `visit` (a check-in or booking result): its check-in and its current visit token."""
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"{API}/kiosk/check-ins/{visit['check_in_id']}/attendances", headers=headers,
                       json={"target_type": "session", "target_id": session_id, "visit_token": visit["visit_token"]})  # fmt: skip


def give_package(client, owner, tenant, k, type_id) -> None:
    plan = package_plan(client, owner, tenant, reservation_type_id=type_id)
    ok(client.post(f"{API}/client-packages", headers=owner,
                   json={"client_id": k.person["id"], "location_id": k.loc, "package_plan_id": plan["id"]}), 201)  # fmt: skip


def pricing(tenant, session_id):
    return scalar(tenant, select(Enrollment.pricing).where(Enrollment.session_id == UUID(session_id)))


def test_the_reservation_page_lists_and_books_by_the_portal_rules(client, tenant, owner, k):
    now_free = soon(client, owner, k.loc, 30)
    paid = soon(client, owner, k.loc, 90, free=False)
    later = soon(client, owner, k.loc, 300)  # beyond the default visible range of four hours
    entered = enter(client, k.person, app_qr(tenant, k.person))
    listed = {s["target_id"]: s for s in entered["sessions"]}
    assert set(listed) == {now_free.id, paid.id}
    assert listed[now_free.id]["is_bookable"] and not listed[paid.id]["is_bookable"]  # needs a package
    assert set(listed[paid.id]) == {
        "target_type",
        "target_id",
        "title",
        "starts_at",
        "ends_at",
        "is_booked",
        "is_bookable",
    }

    refused = book(client, entered, paid.id)
    assert refused.status_code == 409 and refused.json()["code"] == "no-entitlement"
    outside = book(client, entered, later.id)  # a refusal rolls back, so the token stays for another choice
    assert outside.status_code == 422 and outside.json()["code"] == "outside-check-in-window"
    done = ok(book(client, entered, now_free.id, "kiosk-book-1"))
    assert [a["session_id"] for a in done["attended"]] == [now_free.id]  # starts inside the early window: marked
    assert next(s for s in done["sessions"] if s["target_id"] == now_free.id)["is_booked"]
    replay = book(client, entered, now_free.id, "kiosk-book-1")  # the answer carries a token: never stored
    assert replay.status_code == 409 and replay.json()["code"] == "response-not-stored"
    again = ok(book(client, done, now_free.id))  # a place already held is a check-in to it, not a refusal
    done = again
    channel = scalar(tenant, select(Enrollment.channel).where(Enrollment.session_id == UUID(now_free.id)))
    assert channel == "kiosk"
    actions = scalar(tenant, select(func.array_agg(AuditEvent.action)).where(
        AuditEvent.entity_id == UUID(entered["check_in_id"])
    ))  # fmt: skip
    assert sorted(actions) == ["access.checkin.create", "scheduling.enrollment.create"]  # a booking is not a check-in

    # A package covering the paid session's type makes it bookable; it books against the package, not marked yet.
    give_package(client, owner, tenant, k, paid.type_id)
    booked = ok(book(client, done, paid.id))
    assert paid.id not in [a["session_id"] for a in booked["attended"]]
    assert next(s for s in booked["sessions"] if s["target_id"] == paid.id)["is_booked"]


def test_a_name_search_visit_books_only_what_consumes_nothing(client, tenant, owner, k):
    free = soon(client, owner, k.loc, 30)
    paid = soon(client, owner, k.loc, 60, free=False)
    give_package(client, owner, tenant, k, paid.type_id)  # a card holder could spend it here
    entered = enter(client, k.person)
    listed = {s["target_id"]: s for s in entered["sessions"]}
    assert listed[free.id]["is_bookable"] and not listed[paid.id]["is_bookable"]
    refused = book(client, entered, paid.id)  # a direct call is refused like the page, and says nothing more
    assert refused.status_code == 409 and refused.json()["code"] == "see-staff"
    assert "package" not in refused.text.lower()
    assert pricing(tenant, paid.id) is None
    done = ok(book(client, entered, free.id))
    assert pricing(tenant, free.id) == "free"
    assert not any(s["is_booked"] for s in done["sessions"])  # a name alone does not show the client's places

    # The same client scanning their card may spend the package.
    carded = enter(client, k.person, app_qr(tenant, k.person))
    assert next(s for s in carded["sessions"] if s["target_id"] == paid.id)["is_bookable"]
    ok(book(client, carded, paid.id))
    assert pricing(tenant, paid.id) == "entitlement"

    # The location can stop name-search booking altogether.
    other = soon(client, owner, k.loc, 45)
    url = f"{API}/kiosk-settings?location_id={k.loc}"
    assert (
        ok(client.put(url, headers=owner, json={"is_name_search_booking_allowed": False}))[
            "is_name_search_booking_allowed"
        ]
        is False
    )
    named = enter(client, k.person)
    assert not any(s["is_bookable"] for s in named["sessions"])
    off = book(client, named, other.id)
    assert off.status_code == 409 and off.json()["code"] == "see-staff"
    assert pricing(tenant, other.id) is None


def test_a_visit_token_is_single_use_device_bound_and_short_lived(client, tenant, owner, k, monkeypatch):
    first, second, third = (soon(client, owner, k.loc, m) for m in (20, 40, 50))
    entered = enter(client, k.person)
    assert book(client, {**entered, "check_in_id": str(uuid4())}, first.id).status_code == 404
    assert book(client, {**entered, "visit_token": "forged"}, first.id).status_code == 404
    done = ok(book(client, entered, first.id))
    assert book(client, entered, second.id).status_code == 404  # spent by the first booking
    assert done["visit_token"] and done["visit_token"] != entered["visit_token"]

    ended = client.post(f"{API}/kiosk/visits/end", json={"check_in_id": done["check_in_id"]})  # back at the start
    assert ended.status_code == 204
    assert book(client, done, second.id).status_code == 404

    entered = enter(client, k.person)
    enter(client, k.person)  # the next check-in on this kiosk ends the previous visit too
    assert book(client, entered, second.id).status_code == 404

    entered = enter(client, k.person)
    _pair(client, tenant, owner, k.loc)  # this browser is now another device
    assert book(client, entered, second.id).status_code == 404

    entered = enter(client, k.person)
    from app.modules.access import kiosk

    later = clock.now() + timedelta(seconds=10 + 30 + 6)  # past both screens' default timeouts and the grace
    monkeypatch.setattr(kiosk, "clock", SimpleNamespace(now=lambda: later))
    assert book(client, entered, third.id).status_code == 404


def test_booking_attempts_are_rate_limited_per_kiosk(client, tenant, owner, k, monkeypatch):
    from app.core.settings import get_settings
    from app.modules.access import router

    seat = soon(client, owner, k.loc, 30, free=False)
    entered = enter(client, k.person)
    monkeypatch.setattr(get_settings().rate_limit, "enabled", True)
    frozen = clock.now()  # one fixed minute window: the loop must not straddle a minute boundary
    monkeypatch.setattr(router, "clock", SimpleNamespace(now=lambda: frozen))
    codes = [book(client, entered, seat.id).status_code for _ in range(router.KIOSK_BOOKINGS_PER_MINUTE + 1)]
    assert codes[:-1] == [409] * router.KIOSK_BOOKINGS_PER_MINUTE and codes[-1] == 429


def test_a_client_who_must_see_staff_gets_no_reservation_page(client, tenant, owner, k):
    soon(client, owner, k.loc, 30)
    ok(client.put(f"{API}/clients/{k.person['id']}/access-mode", headers=owner,
                  json={"access_mode": "always_deny", "reason": "Test"}))  # fmt: skip
    entered = enter(client, k.person, card_of(client, owner, k.person))
    assert entered["status"] == "see_staff" and entered["sessions"] == [] and entered["visit_token"] is None


def test_auto_book_takes_the_earliest_bookable_session_once(client, tenant, owner, k):
    first = soon(client, owner, k.loc, 20)
    soon(client, owner, k.loc, 45)
    soon(client, owner, k.loc, 10, free=False)  # earlier, but needs a package: skipped
    ok(client.put(f"{API}/kiosk-settings?location_id={k.loc}", headers=owner,
                  json={"is_auto_book": True, "visible_range_minutes": 120, "reservation_timeout_seconds": 20}))  # fmt: skip
    card = app_qr(tenant, k.person)
    entered = enter(client, k.person, card)
    assert [a["session_id"] for a in entered["attended"]] == [first.id]
    assert [s["target_id"] for s in entered["sessions"] if s["is_booked"]] == [first.id]
    row = scalar(tenant, select(CheckIn).where(CheckIn.id == UUID(entered["check_in_id"])))
    assert row.result == "granted" and row.identified_by == "credential"
    again = enter(client, k.person, card)  # a place is already held: nothing more is booked
    assert [s["target_id"] for s in again["sessions"] if s["is_booked"]] == [first.id]
    assert client.put(f"{API}/kiosk-settings?location_id={k.loc}", headers=owner,
                      json={"reservation_timeout_seconds": 1}).status_code == 422  # fmt: skip


def test_auto_book_on_a_name_search_skips_a_session_that_would_spend_a_package(client, tenant, owner, k):
    paid = soon(client, owner, k.loc, 10, free=False)
    free = soon(client, owner, k.loc, 25)
    give_package(client, owner, tenant, k, paid.type_id)
    ok(client.put(f"{API}/kiosk-settings?location_id={k.loc}", headers=owner, json={"is_auto_book": True}))
    entered = enter(client, k.person)
    assert [a["session_id"] for a in entered["attended"]] == [free.id]
    assert pricing(tenant, paid.id) is None


def test_auto_book_on_an_app_card_never_spends_a_package(client, tenant, owner, k):
    """Auto-book books only what consumes nothing: a credit is spent only when the person picks the session."""
    paid = soon(client, owner, k.loc, 10, free=False)  # earliest, and the package would cover it
    free = soon(client, owner, k.loc, 25)
    give_package(client, owner, tenant, k, paid.type_id)
    ok(client.put(f"{API}/kiosk-settings?location_id={k.loc}", headers=owner, json={"is_auto_book": True}))
    entered = enter(client, k.person, app_qr(tenant, k.person))  # possession, and still nothing spent
    assert [a["session_id"] for a in entered["attended"]] == [free.id]
    assert pricing(tenant, paid.id) is None  # nothing booked against the package
    assert {s["target_id"]: s["is_bookable"] for s in entered["sessions"]}[paid.id]  # still the person's choice


def test_a_visit_token_cannot_be_spent_twice_concurrently(client, tenant, owner, k):
    """Two taps at once with different Idempotency-Keys: the token is spent by exactly one of them."""
    one, two = soon(client, owner, k.loc, 30), soon(client, owner, k.loc, 60)
    entered = enter(client, k.person)
    barrier, codes = threading.Barrier(2), []

    def tap(session_id):
        with TestClient(fastapi_app, cookies=client.cookies) as own:
            barrier.wait()
            codes.append(book(own, entered, session_id, uuid4().hex).status_code)

    threads = [threading.Thread(target=tap, args=(s.id,)) for s in (one, two)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == [200, 404]
    booked = scalar(tenant, select(func.count()).select_from(Enrollment).where(
        Enrollment.client_id == UUID(k.person["id"]), Enrollment.session_id.in_([UUID(one.id), UUID(two.id)])))  # fmt: skip
    assert booked == 1


def test_a_static_card_value_is_never_possession(client, tenant, owner, k):
    """A barcode or fob number is a static value anyone can copy: typed, or sent as a scan (the tablet is the
    client, so how a value arrived proves nothing), it checks in like a name and never spends a package. Only a
    verified app-card QR (or an active wallet pass) does."""
    paid = soon(client, owner, k.loc, 30, free=False)
    give_package(client, owner, tenant, k, paid.type_id)
    card = card_of(client, owner, k.person)
    for typed in (True, False):  # typed into a lookup; sent as a scan
        visit = enter(client, k.person, card, typed=typed)
        assert not next(s for s in visit["sessions"] if s["target_id"] == paid.id)["is_bookable"]
        refused = book(client, visit, paid.id)
        assert refused.status_code == 409 and refused.json()["code"] == "see-staff"
        assert pricing(tenant, paid.id) is None
    ok(book(client, enter(client, k.person, app_qr(tenant, k.person)), paid.id))
    assert pricing(tenant, paid.id) == "entitlement"


def _device_id(tenant) -> UUID:
    return scalar(tenant, select(KioskDevice.id).order_by(KioskDevice.created_at.desc()).limit(1))


def test_unknown_values_lock_the_kiosk_even_between_known_ones(client, tenant, owner, k, monkeypatch):
    """N unknown values within the window lock value reads, whatever resolved in between: a known card between
    guesses does not reset the count."""
    from app.modules.access import service

    card = card_of(client, owner, k.person)
    for n in range(service.KIOSK_UNKNOWN_VALUES):
        assert ok(client.post(f"{API}/kiosk/lookups", json={"credential_value": card}))["matches"]  # known
        if n % 2:
            assert ok(client.post(f"{API}/kiosk/lookups", json={"credential_value": f"NOPE{n}"}))["matches"] == []
        else:  # a refused scan counts too
            assert client.post(f"{API}/kiosk/check-ins", json={"card_payload": f"NOPE{n}"}).status_code == 422
    locked = client.post(f"{API}/kiosk/check-ins", json={"card_payload": card})  # even a real card waits
    assert locked.status_code == 429 and locked.json()["code"] == "kiosk-locked-out"
    assert client.post(f"{API}/kiosk/lookups", json={"credential_value": card}).status_code == 429
    assert ok(client.post(f"{API}/kiosk/lookups", json={"last_name_prefix": k.person["last_name"]}))["matches"]

    later = clock.now() + service.KIOSK_UNKNOWN_WINDOW + timedelta(seconds=1)
    monkeypatch.setattr(service, "clock", SimpleNamespace(now=lambda: later))
    assert ok(client.post(f"{API}/kiosk/lookups", json={"credential_value": card}))["matches"]
    assert (
        ok(client.post(f"{API}/kiosk/lookups", json={"credential_value": "NOPE"}))["matches"] == []
    )  # old ones aged out
    assert ok(client.post(f"{API}/kiosk/lookups", json={"credential_value": card}))["matches"]


def test_concurrent_unknown_values_are_all_counted(client, tenant, owner, k):
    """20 unknown values at once: every one the kiosk evaluated is counted (no lost updates) and the device locks."""
    from app.modules.access import service

    barrier, codes = threading.Barrier(20), []

    def guess(n):
        with TestClient(fastapi_app, cookies=client.cookies) as own:
            barrier.wait()
            codes.append(own.post(f"{API}/kiosk/lookups", json={"credential_value": f"NOPE{n}"}).status_code)

    threads = [threading.Thread(target=guess, args=(n,)) for n in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert set(codes) <= {200, 429}
    assert service.unknown_value_count(_device_id(tenant)) == codes.count(200) >= service.KIOSK_UNKNOWN_VALUES
    locked = client.post(f"{API}/kiosk/lookups", json={"credential_value": "NOPE"})
    assert locked.status_code == 429 and locked.json()["code"] == "kiosk-locked-out"


def _digital(tenant, person, kind: str, value: str, secret: bytes | None = None) -> UUID:
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        row = Credential(client_id=person["id"], kind=kind, value=value, source="app_issued",
                         secret_ciphertext=secret, issued_at=clock.now())  # fmt: skip
        session.add(row)
        session.flush()
        return row.id


def test_only_a_verified_digital_scan_is_possession(client, tenant, owner, k):
    """Possession comes from how the value verified, not from the credential's kind: an app card's static number
    or a wallet pass's stored hash sent as a plain value does not resolve at all. The rotating QR and the live
    wallet token do. A physical fob checks in like a name (see test_a_static_card_value_is_never_possession)."""
    from app.modules.access import service

    paid = soon(client, owner, k.loc, 30, free=False)
    give_package(client, owner, tenant, k, paid.type_id)
    secret, static = secrets.token_bytes(32), f"APP{secrets.token_hex(8).upper()}"
    card_id = _digital(tenant, k.person, "app_card", static, secret)
    token = service.WALLET_PREFIX + secrets.token_hex(20).upper()
    _digital(tenant, k.person, "wallet_pass", service._wallet_value(token))
    for value in (static, service._wallet_value(token)):
        assert ok(client.post(f"{API}/kiosk/lookups", json={"credential_value": value}))["matches"] == []  # typed
        scanned = client.post(f"{API}/kiosk/check-ins", json={"card_payload": value})
        assert scanned.status_code == 422 and scanned.json()["code"] == "card-invalid"
    for value in (cards.qr_text(cards.seed(card_id, secret), clock.now()), token):
        visit = enter(client, k.person, value)
        assert next(s for s in visit["sessions"] if s["target_id"] == paid.id)["is_bookable"]


class _DownRedis:
    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise redis.RedisError("down")

        return fail


def test_the_lockout_fails_closed_when_redis_is_down(client, tenant, owner, k, monkeypatch):
    """No counter, no value reads: a Redis outage must not lift the brute-force limit. Name search still works."""
    from app.modules.access import service

    card = card_of(client, owner, k.person)
    monkeypatch.setattr(service, "_redis", lambda: _DownRedis())
    for body in ({"credential_value": card}, {"credential_value": "NOPE"}):
        refused = client.post(f"{API}/kiosk/lookups", json=body)
        assert refused.status_code == 429 and refused.json()["code"] == "kiosk-locked-out"
    scanned = client.post(f"{API}/kiosk/check-ins", json={"card_payload": card})
    assert scanned.status_code == 429 and scanned.json()["code"] == "kiosk-locked-out"
    assert enter(client, k.person)["status"] == "admitted"  # found by name


def _places(tenant, k, session_id) -> list[str]:
    return list(scalar(tenant, select(func.array_agg(Enrollment.status)).where(
        Enrollment.client_id == UUID(k.person["id"]), Enrollment.session_id == UUID(session_id))) or [])  # fmt: skip


def test_a_name_visit_booking_a_place_already_held_checks_in_to_it(client, tenant, owner, k):
    seat = soon(client, owner, k.loc, 30)
    ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": seat.id, "client_id": k.person["id"]}), 201)
    entered = enter(client, k.person)  # by name: the page does not show the place it holds
    done = book(client, entered, seat.id)
    assert done.status_code == 200, done.text  # not see-staff, never a server error
    assert _places(tenant, k, seat.id) == ["enrolled"]  # nothing new booked


def test_auto_book_meeting_a_pending_place_still_checks_in(client, tenant, owner, k):
    seat = soon(client, owner, k.loc, 20)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.add(Enrollment(
            location_id=UUID(k.loc), client_id=UUID(k.person["id"]), session_id=UUID(seat.id), status="pending",
            pricing="free", channel="portal", enrolled_at=clock.now(), hold_expires_at=clock.now() + timedelta(minutes=15),
        ))  # fmt: skip
    ok(client.put(f"{API}/kiosk-settings?location_id={k.loc}", headers=owner, json={"is_auto_book": True}))
    entered = enter(client, k.person, app_qr(tenant, k.person))
    assert entered["status"] == "admitted" and entered["visit_token"]
    assert scalar(tenant, select(CheckIn.result).where(CheckIn.id == UUID(entered["check_in_id"]))) == "granted"
    assert _places(tenant, k, seat.id) == ["pending"]  # the checkout hold is left as it was


def test_the_same_scan_on_two_kiosks_books_one_place_and_checks_in_twice(client, tenant, owner, k):
    seat = soon(client, owner, k.loc, 20)
    ok(client.put(f"{API}/kiosk-settings?location_id={k.loc}", headers=owner, json={"is_auto_book": True}))
    card = card_of(client, owner, k.person)
    kiosks = [client, TestClient(fastapi_app)]
    _pair(kiosks[1], tenant, owner, k.loc)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:  # first-use seeding, not raced here
        clients.households.ensure_relationship_types(session)
    barrier, codes = threading.Barrier(2), []

    def scan(kiosk):
        barrier.wait()
        answer = kiosk.post(f"{API}/kiosk/check-ins", json={"card_payload": card})
        codes.append((answer.status_code, answer.text if answer.status_code != 201 else ""))

    threads = [threading.Thread(target=scan, args=(kiosk,)) for kiosk in kiosks]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [c for c, _ in codes] == [201, 201], codes
    assert _places(tenant, k, seat.id) == ["enrolled"]


def test_a_kiosk_spend_at_the_renewal_threshold_defers_the_sale_to_the_daily_run(client, tenant, owner, k):
    """Nothing at the kiosk charges: a credit spent there that reaches the auto-renew threshold leaves the sale to
    the scheduled renewal run, which makes it by the normal path."""
    from app.modules.billing.models import Invoice
    from app.modules.packages import service as packages_service
    from app.modules.packages.models import ClientPackage

    paid = soon(client, owner, k.loc, 30, free=False)
    plan = package_plan(client, owner, tenant, reservation_type_id=paid.type_id, session_count=2,
                        renewal_threshold_count=1, is_auto_renew_on_threshold=True)  # fmt: skip
    ok(client.post(f"{API}/client-packages", headers=owner,
                   json={"client_id": k.person["id"], "location_id": k.loc, "package_plan_id": plan["id"]}), 201)  # fmt: skip
    mine = select(func.count()).select_from(Invoice).where(Invoice.bill_to_client_id == UUID(k.person["id"]))
    packs = select(func.count()).select_from(ClientPackage).where(ClientPackage.owner_client_id == UUID(k.person["id"]))
    invoices = scalar(tenant, mine)
    ok(book(client, enter(client, k.person, app_qr(tenant, k.person)), paid.id))
    assert pricing(tenant, paid.id) == "entitlement"  # one credit spent: one left, at the threshold
    assert (scalar(tenant, mine), scalar(tenant, packs)) == (invoices, 1)  # no successor sold, nothing invoiced
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert packages_service.run_daily(session)["renewed"] == 1
    assert (scalar(tenant, mine), scalar(tenant, packs)) == (invoices + 1, 2)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert packages_service.run_daily(session)["renewed"] == 0  # once


def test_ending_an_old_visit_never_ends_a_newer_one(client, tenant, owner, k):
    """A new scan's check-in and the old screen's late `visits/end` race: the end names the visit it ends."""
    seat = soon(client, owner, k.loc, 30)
    old = enter(client, k.person)
    new = enter(client, k.person)  # the next check-in already ended the old visit on the server
    assert client.post(f"{API}/kiosk/visits/end").status_code == 422  # the visit must be named
    assert client.post(f"{API}/kiosk/visits/end", json={"check_in_id": old["check_in_id"]}).status_code == 204
    ok(book(client, new, seat.id))  # the newer visit's token still works
