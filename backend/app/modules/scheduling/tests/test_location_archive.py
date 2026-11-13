"""Scheduling's archive check on platform locations: no archiving while bookings or live holds lie ahead."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.scheduling import service
from app.modules.scheduling.tests.helpers import API, DAY, at, book, facility, ok


def test_a_location_with_future_bookings_cannot_be_archived(client, owner, monkeypatch):
    f = facility(client, owner)
    ok(book(client, owner, f, [f.court], at(10), at(11), kind="session"))
    archive = f"{API}/locations/{f.location}/archive"

    refused = client.post(archive, headers=owner)
    assert refused.status_code == 409 and refused.json()["code"] == "location-has-future-bookings"

    # The booking is now in the past (scheduling's clock only, so the session token stays valid).
    monkeypatch.setattr(service, "clock", SimpleNamespace(now=lambda: DAY + timedelta(days=1)))
    assert client.post(archive, headers=owner).status_code == 200


def test_a_cancelled_booking_does_not_block_archiving(client, owner):
    f = facility(client, owner)
    booking = ok(book(client, owner, f, [f.court], at(10), at(11), kind="session"))["booking"]
    ok(client.post(f"{API}/bookings/{booking['id']}/cancel", headers=owner, json={"version": 1}), 200)
    assert client.post(f"{API}/locations/{f.location}/archive", headers=owner).status_code == 200


def test_a_live_checkout_hold_blocks_archiving_until_it_expires(client, owner, tenant):
    f = facility(client, owner)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        held = service.create_booking(
            session, location_id=UUID(f.location), kind="rental", resource_ids=[UUID(f.court)],
            starts_at=DAY + timedelta(hours=10), ends_at=DAY + timedelta(hours=11), hold_minutes=10, created_via="portal",
        )  # fmt: skip
        assert held.status == "tentative"
    archive = f"{API}/locations/{f.location}/archive"
    refused = client.post(archive, headers=owner)
    assert refused.status_code == 409 and refused.json()["code"] == "location-has-future-bookings"
    with clock.freeze(clock.now() + timedelta(minutes=11)):  # the hold lapsed; nothing is held any more
        assert client.post(archive, headers=owner).status_code == 200


def test_a_future_closure_block_does_not_refuse_the_archive(client, owner):
    f = facility(client, owner)
    ok(book(client, owner, f, [f.court], at(10), at(11)))  # kind "block": staff time off the calendar, not a booking
    assert client.post(f"{API}/locations/{f.location}/archive", headers=owner).status_code == 200
