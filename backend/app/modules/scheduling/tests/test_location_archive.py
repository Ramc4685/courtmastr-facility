"""Scheduling's archive check on platform locations: no archiving while confirmed bookings lie ahead."""

from datetime import timedelta
from types import SimpleNamespace

from app.modules.scheduling import service
from app.modules.scheduling.tests.helpers import API, DAY, at, book, facility, ok


def test_a_location_with_future_bookings_cannot_be_archived(client, owner, monkeypatch):
    f = facility(client, owner)
    ok(book(client, owner, f, [f.court], at(10), at(11)))
    archive = f"{API}/locations/{f.location}/archive"

    refused = client.post(archive, headers=owner)
    assert refused.status_code == 409 and refused.json()["code"] == "location-has-future-bookings"

    # The booking is now in the past (scheduling's clock only, so the session token stays valid).
    monkeypatch.setattr(service, "clock", SimpleNamespace(now=lambda: DAY + timedelta(days=1)))
    assert client.post(archive, headers=owner).status_code == 200


def test_a_cancelled_booking_does_not_block_archiving(client, owner):
    f = facility(client, owner)
    booking = ok(book(client, owner, f, [f.court], at(10), at(11)))["booking"]
    ok(client.post(f"{API}/bookings/{booking['id']}/cancel", headers=owner, json={"version": 1}), 200)
    assert client.post(f"{API}/locations/{f.location}/archive", headers=owner).status_code == 200
