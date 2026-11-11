"""Wave 1 hardening, batch space: S-01 (docs/security/wave1-hardening-spec.md section 5)."""

from app.modules.programs.tests.test_sessions import class_of, counts, enroll, people
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import add_staff, login


def test_waitlist_is_not_a_free_seat(client, owner, tenant):
    f = facility(client, owner)
    seat = class_of(client, owner, f, 1, allows_free_booking=False)
    a, b = people(client, owner, f, 2)
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    first = ok(enroll(client, owner, seat, a))
    entry = ok(client.post(f"{API}/waitlist-entries", headers=desk, json={"session_id": seat, "client_id": b}))
    # The freed seat is not handed to the queue: the entry has no package and the automatic path has no free_book.
    ok(client.post(f"{API}/enrollments/{first['id']}/cancel", headers=desk, json={}), 200)
    assert counts(tenant, seat) == (0, 0)
    denied = client.post(f"{API}/waitlist-entries/{entry['id']}/promote", headers=desk)
    assert denied.status_code == 403 and denied.json()["required"] == "scheduling.enrollment.free_book"
    assert counts(tenant, seat) == (0, 0)
    assert ok(client.post(f"{API}/waitlist-entries/{entry['id']}/promote", headers=owner), 200)["status"] == "promoted"
    assert counts(tenant, seat) == (1, 1)
