"""Wave 1 hardening, batch space: S-02 to S-04 (docs/security/wave1-hardening-spec.md section 5)."""

from uuid import UUID

from sqlalchemy import select

from app.core.db.session import tenant_session
from app.modules.scheduling.models import Booking, BookingSeriesRule
from app.modules.scheduling.tests.helpers import API, at, book, facility, ok
from conftest import add_staff, login

FREE = "scheduling.enrollment.free_book"


def _rule(**extra) -> dict:
    return {"pattern": "daily", "range_type": "count", "occurrence_limit": 2} | extra


def test_free_booking_flag_needs_free_book(client, owner, tenant):
    f = facility(client, owner)
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    closed = {"capacity": 4, "allows_free_booking": False}
    # create
    denied = book(client, desk, f, [f.court], at(9), at(10), kind="session", session={"allows_free_booking": True})
    assert denied.status_code == 403 and denied.json()["required"] == FREE
    seat = ok(book(client, desk, f, [f.court], at(9), at(10), kind="session", session=closed))["booking"]["session"]
    # update_session; re-sending a value that is already false stays allowed
    url = f"{API}/sessions/{seat['id']}"
    assert client.patch(url, headers=desk, json={"allows_free_booking": True}).json()["required"] == FREE
    ok(client.patch(url, headers=desk, json={"allows_free_booking": False, "is_self_bookable": True}), 200)
    # mass edit of a series
    series = ok(book(client, desk, f, [f.court2], at(11), at(12), kind="session", session=closed, recurrence=_rule()))
    edit = {"scope": {"mode": "all"}, "patch": {"session": {"allows_free_booking": True}}}
    edits = f"{API}/booking-series/{series['booking_series_id']}/edits"
    assert client.post(edits, headers=desk, json=edit).json()["required"] == FREE
    ok(client.post(edits, headers=owner, json=edit), 200)
    assert ok(client.patch(url, headers=owner, json={"allows_free_booking": True}), 200)["allows_free_booking"]


def test_added_pass_does_not_inherit_override(client, owner, tenant):
    f = facility(client, owner)
    _, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, _)
    series = ok(
        book(client, owner, f, [f.court], at(9), at(10), kind="session", recurrence=_rule(), override_policy=True)
    )["booking_series_id"]
    add = {"start_on": "2031-06-02", "start_time": "09:00", "end_time": "10:00", "rule": _rule()}
    url = f"{API}/booking-series/{series}/rules"
    denied = client.post(url, headers=desk, json=add | {"override_policy": True})
    assert denied.status_code == 403 and denied.json()["required"] == "scheduling.booking.override_policy"
    ok(client.post(url, headers=desk, json=add))
    with tenant_session(tenant.id) as session:
        added = session.scalars(
            select(BookingSeriesRule).where(BookingSeriesRule.booking_series_id == UUID(series))
            .order_by(BookingSeriesRule.sequence)
        ).all()[-1]  # fmt: skip
        assert (added.template["override_policy"], added.template["created_by_staff_user_id"]) == (False, str(desk_id))
        rows = session.scalars(select(Booking).where(Booking.booking_series_id == UUID(series))).all()
        assert sorted(b.created_by_staff_user_id == desk_id for b in rows) == [False, False, True, True]


def test_tenant_wide_settings_need_every_location(client, owner, tenant):
    f = facility(client, owner)
    manager = login(client, tenant, add_staff(tenant, "manager", location_ids=[f.location])[0])
    url = f"{API}/scheduling-settings"
    denied = client.patch(url, headers=manager, json={"calendar_slot_min": 30})
    assert denied.status_code == 403 and denied.json()["required"] == "platform.location.update"
    ok(client.patch(f"{url}?location_id={f.location}", headers=manager, json={"calendar_slot_min": 30}), 200)
    assert ok(client.patch(url, headers=owner, json={"calendar_slot_min": 15}), 200)["calendar_slot_min"] == 15
