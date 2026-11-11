"""programs session slice: enrolment, roster and attendance, the waitlist with FIFO auto-promotion, and
the last-seat race on real PostgreSQL."""

import threading
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.events import OutboxEvent
from app.main import app
from app.modules.programs import handlers, service
from app.modules.programs.models import Enrollment, WaitlistEntry
from app.modules.scheduling.models import Session
from app.modules.scheduling.tests.helpers import API, at, book, drain, facility, ok
from conftest import add_staff, login, new_client


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def class_of(client, owner, f, capacity: int, hour: float = 10, **session) -> str:
    booking = book(
        client, owner, f, [f.court], at(hour), at(hour + 1), kind="session", session={"capacity": capacity} | session
    )
    return ok(booking)["booking"]["session"]["id"]


def people(client, owner, f, count: int) -> list[str]:
    return [
        new_client(client, owner, f.location, first_name=f"P{i}", primary_email=f"p{i}-{uuid4().hex[:6]}@example.com")[
            "id"
        ]
        for i in range(count)
    ]


def enroll(client, headers, seat: str, person: str):
    return client.post(f"{API}/enrollments", headers=headers, json={"session_id": seat, "client_id": person})


def counts(tenant, seat: str) -> tuple[int, int]:
    with tenant_session(tenant.id) as session:
        row = session.get(Session, UUID(seat))
        enrolled = session.scalar(
            select(func.count()).where(Enrollment.session_id == row.id, Enrollment.status == "enrolled")
        )
        return row.booked_count, enrolled


def test_enrol_roster_attendance_and_removal(client, owner, f, tenant):
    seat = class_of(client, owner, f, 2)
    a, b, c = people(client, owner, f, 3)
    first = ok(enroll(client, owner, seat, a))
    assert (first["status"], first["pricing"], first["channel"], first["target_kind"]) == (
        "enrolled",
        "free",
        "staff",
        "session",
    )
    again = enroll(client, owner, seat, a)
    assert again.status_code == 409 and again.json()["code"] == "already-enrolled" and counts(tenant, seat) == (1, 1)
    second = ok(enroll(client, owner, seat, b))
    full = enroll(client, owner, seat, c)
    assert full.status_code == 409 and full.json()["code"] == "capacity-full" and counts(tenant, seat) == (2, 2)
    assert (
        enroll(client, owner, seat, str(uuid4())).status_code == 422
        and enroll(client, owner, str(uuid4()), a).status_code == 404
    )
    roster = ok(client.get(f"{API}/sessions/{seat}/roster", headers=owner), 200)
    assert (roster["capacity"], roster["booked_count"], roster["waiting_count"]) == (2, 2, 0)
    assert [(p["client_id"], p["attendance"], p["client_name"][:2]) for p in roster["participants"]] == [
        (a, "scheduled", "P0"),
        (b, "scheduled", "P1"),
    ]
    marks = {
        "marks": [
            {"enrollment_id": first["id"], "status": "attended"},
            {"enrollment_id": second["id"], "status": "no_show"},
        ]
    }
    marked = ok(client.put(f"{API}/sessions/{seat}/attendance", headers=owner, json=marks), 200)
    assert [p["attendance"] for p in marked["participants"]] == ["attended", "no_show"]
    ok(client.put(f"{API}/sessions/{seat}/attendance", headers=owner, json=marks), 200)  # idempotent
    changed = ok(
        client.put(
            f"{API}/sessions/{seat}/attendance",
            headers=owner,
            json={"marks": [{"enrollment_id": second["id"], "status": "excused"}]},
        ),
        200,
    )
    assert changed["participants"][1]["attendance"] == "excused"
    stranger = client.put(
        f"{API}/sessions/{seat}/attendance",
        headers=owner,
        json={"marks": [{"enrollment_id": str(uuid4()), "status": "attended"}]},
    )
    assert stranger.status_code == 422 and stranger.json()["errors"][0]["pointer"] == "/marks/0/enrollment_id"
    with tenant_session(tenant.id) as session:
        attended = session.scalar(select(func.count()).where(OutboxEvent.event_type == "programs.enrollment.attended"))
        audits = session.scalar(select(func.count()).where(AuditEvent.action == "scheduling.attendance.mark"))
    assert (attended, audits) == (1, 3)  # one event for the first move to attended; one audit per change
    removed = ok(
        client.post(
            f"{API}/enrollments/{second['id']}/cancel", headers=owner, json={"cancel_kind": "late", "reason": "Ill"}
        ),
        200,
    )
    assert (removed["status"], removed["cancel_kind"]) == ("cancelled", "late") and counts(tenant, seat) == (1, 1)
    assert (
        ok(client.post(f"{API}/enrollments/{second['id']}/cancel", headers=owner, json={}), 200)["cancel_kind"]
        == "late"
    )  # idempotent
    assert ok(enroll(client, owner, seat, b))["status"] == "enrolled"  # the seat is free and b may come back
    listed = ok(client.get(f"{API}/enrollments?session_id={seat}&status=enrolled", headers=owner), 200)["data"]
    assert {e["client_id"] for e in listed} == {a, b}
    assert ok(client.get(f"{API}/enrollments/{first['id']}", headers=owner), 200)["id"] == first["id"]


def test_free_booking_needs_the_flag_or_the_override(client, owner, f, tenant):
    seat = class_of(client, owner, f, 5, allows_free_booking=False)
    a, b = people(client, owner, f, 2)
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    denied = enroll(client, desk, seat, a)
    assert denied.status_code == 403 and denied.json()["required"] == "scheduling.enrollment.free_book"
    assert enroll(client, owner, seat, a).status_code == 201  # a manager-level override (CLS-05)
    ok(client.patch(f"{API}/sessions/{seat}", headers=owner, json={"allows_free_booking": True}), 200)
    assert enroll(client, desk, seat, b).status_code == 201
    viewer = login(client, tenant, add_staff(tenant, "view_only", location_ids=[f.location])[0])
    assert enroll(client, viewer, seat, b).status_code == 403
    assert client.get(f"{API}/sessions/{seat}/roster", headers=viewer).status_code == 200
    assert (
        client.put(
            f"{API}/sessions/{seat}/attendance",
            headers=viewer,
            json={"marks": [{"enrollment_id": str(uuid4()), "status": "attended"}]},
        ).status_code
        == 403
    )
    first = ok(client.get(f"{API}/enrollments?session_id={seat}", headers=owner), 200)["data"][0]["id"]
    no_show = {"marks": [{"enrollment_id": first, "status": "no_show"}]}
    assert (
        client.put(f"{API}/sessions/{seat}/attendance", headers=desk, json=no_show).status_code == 403
    )  # an exception mark
    assert (
        client.put(
            f"{API}/sessions/{seat}/attendance",
            headers=desk,
            json={"marks": [{"enrollment_id": first, "status": "attended"}]},
        ).status_code
        == 200
    )
    elsewhere = login(client, tenant, add_staff(tenant, "manager", location_ids=[])[0])
    assert client.get(f"{API}/sessions/{seat}/roster", headers=elsewhere).status_code == 404  # another location


def test_waitlist_is_fifo_and_promotes_when_a_seat_frees(client, owner, f, tenant, mailbox):
    seat = class_of(client, owner, f, 1)
    a, b, c, d = people(client, owner, f, 4)
    has_space = client.post(f"{API}/waitlist-entries", headers=owner, json={"session_id": seat, "client_id": a})
    assert has_space.status_code == 409 and has_space.json()["code"] == "session-has-space"
    first = ok(enroll(client, owner, seat, a))
    assert (
        client.post(f"{API}/waitlist-entries", headers=owner, json={"session_id": seat, "client_id": a}).json()["code"]
        == "already-enrolled"
    )

    def wait(person, **extra):
        return client.post(
            f"{API}/waitlist-entries", headers=owner, json={"session_id": seat, "client_id": person} | extra
        )  # noqa: E731

    manual = ok(wait(d, mode="manual"))
    queued_b, queued_c = ok(wait(b)), ok(wait(c))
    assert (manual["position"], queued_b["position"], queued_c["position"]) == (1, 2, 3)
    assert wait(b).json()["code"] == "already-exists"
    assert [
        e["client_id"] for e in ok(client.get(f"{API}/waitlist-entries?session_id={seat}", headers=owner), 200)
    ] == [d, b, c]
    assert ok(client.get(f"{API}/sessions/{seat}/roster", headers=owner), 200)["waiting_count"] == 3
    # The seat frees: the first auto entry (b) is promoted in the same transaction; the manual one waits.
    ok(client.post(f"{API}/enrollments/{first['id']}/cancel", headers=owner, json={}), 200)
    roster = ok(client.get(f"{API}/sessions/{seat}/roster", headers=owner), 200)
    assert [p["client_id"] for p in roster["participants"]] == [b] and roster["participants"][0][
        "channel"
    ] == "waitlist"
    assert (roster["booked_count"], roster["waiting_count"]) == (1, 2)
    # new clients with an address also get the clients module's "confirm your email" message
    assert len([m for m in mailbox if "place opened up" in m.subject]) == 1
    with tenant_session(tenant.id) as session:
        entry = session.get(WaitlistEntry, UUID(queued_b["id"]))
        assert entry.status == "promoted" and entry.promoted_enrollment_id is not None
        assert session.scalar(select(func.count()).where(OutboxEvent.event_type == "programs.waitlist.promoted")) == 1
    # Staff promotion of the manual entry needs a seat; raising capacity promotes the queue through the event.
    full = client.post(f"{API}/waitlist-entries/{manual['id']}/promote", headers=owner)
    assert full.status_code == 409 and full.json()["code"] == "capacity-full"
    ok(client.post(f"{API}/sessions/capacity-changes", headers=owner, json={"session_ids": [seat], "capacity": 2}), 200)
    with tenant_session(tenant.id) as session:
        event = session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "scheduling.session.capacity_changed")
        ).scalar_one()
    handlers.promote_on_capacity_raise.send(str(tenant.id), str(event.id), event.payload)
    handlers.promote_on_capacity_raise.send(str(tenant.id), str(event.id), event.payload)  # redelivered
    drain()
    assert counts(tenant, seat) == (2, 2)
    assert {
        p["client_id"] for p in ok(client.get(f"{API}/sessions/{seat}/roster", headers=owner), 200)["participants"]
    } == {b, c}
    ok(client.post(f"{API}/sessions/capacity-changes", headers=owner, json={"session_ids": [seat], "capacity": 3}), 200)
    assert ok(client.post(f"{API}/waitlist-entries/{manual['id']}/promote", headers=owner), 200)["status"] == "promoted"
    assert client.post(f"{API}/waitlist-entries/{manual['id']}/promote", headers=owner).status_code == 409
    assert counts(tenant, seat) == (3, 3)
    e = ok(wait(a))
    assert client.delete(f"{API}/waitlist-entries/{e['id']}", headers=owner).status_code == 204
    assert client.delete(f"{API}/waitlist-entries/{e['id']}", headers=owner).status_code == 204
    assert ok(client.get(f"{API}/waitlist-entries?session_id={seat}", headers=owner), 200) == []


def test_no_auto_promotion_inside_the_cutoff_and_cancelled_sessions_close_everything(client, owner, f, tenant):
    seat = class_of(client, owner, f, 1)
    a, b = people(client, owner, f, 2)
    first = ok(enroll(client, owner, seat, a))
    ok(client.post(f"{API}/waitlist-entries", headers=owner, json={"session_id": seat, "client_id": b}))
    start = clock.now().replace(year=2031, month=5, day=5, hour=10, minute=0, second=0, microsecond=0)
    with clock.freeze(start - timedelta(minutes=30)):  # sign in again: the owner's token is from "years ago"
        ok(client.post(f"{API}/enrollments/{first['id']}/cancel", headers=login(client, tenant), json={}), 200)
    assert counts(tenant, seat) == (0, 0)  # 30 minutes before the start: staff promote by hand
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert service.promote_waitlist(session, UUID(seat)) == 1 and service.promote_waitlist(session, UUID(seat)) == 0
    booking = ok(client.get(f"{API}/sessions/{seat}", headers=owner), 200)["booking_id"]
    ok(
        client.post(
            f"{API}/enrollments", headers=owner, json={"session_id": class_of(client, owner, f, 1, 14), "client_id": a}
        )
    )
    ok(client.post(f"{API}/waitlist-entries", headers=owner, json={"session_id": seat, "client_id": a}))
    ok(client.post(f"{API}/bookings/{booking}/cancel", headers=owner, json={"version": 1}), 200)
    with tenant_session(tenant.id) as session:
        event = session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "scheduling.session.cancelled")
        ).scalar_one()
    handlers.cancel_enrollments_of_cancelled_session.send(str(tenant.id), str(event.id), event.payload)
    drain()
    with tenant_session(tenant.id) as session:
        kinds = set(
            session.scalars(
                select(Enrollment.cancel_kind).where(
                    Enrollment.session_id == UUID(seat), Enrollment.status == "cancelled"
                )
            )
        )
        waiting = set(session.scalars(select(WaitlistEntry.status).where(WaitlistEntry.session_id == UUID(seat))))
    assert "session_cancelled" in kinds and waiting == {"promoted", "expired"} and counts(tenant, seat) == (0, 0)
    assert enroll(client, owner, seat, b).json()["code"] == "session-not-bookable"


def test_last_seats_race_exactly_capacity_wins(client, owner, f, tenant):
    """Twelve clients go for three seats at once: three enrolments, nine capacity-full, counter exact."""
    seat = class_of(client, owner, f, 3)
    racers, results, barrier = people(client, owner, f, 12), [], threading.Barrier(12)

    def attempt(person: str) -> None:
        barrier.wait(10)
        with TestClient(app) as racer:
            results.append(enroll(racer, owner, seat, person))

    threads = [threading.Thread(target=attempt, args=(p,)) for p in racers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    codes = sorted(r.status_code for r in results)
    assert codes == [201] * 3 + [409] * 9 and {r.json()["code"] for r in results if r.status_code == 409} == {
        "capacity-full"
    }
    assert counts(tenant, seat) == (3, 3)
