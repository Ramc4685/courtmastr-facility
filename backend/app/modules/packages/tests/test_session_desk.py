"""PKG-12 at the desk: sell a package inline, then book every linked session of a series with it, or register a
client into one session with it (speed register). The sale is packages.sell through the staff route and bills
through billing; the places hold credits through programs, as the screens drive them."""

from app.modules.memberships.tests.support import category, open_balance
from app.modules.programs.tests.test_sessions import people
from app.modules.scheduling.tests.helpers import API, at, facility, ok
from conftest import add_staff, login


def test_inline_sale_then_book_all_linked_and_speed_register(client, owner, tenant):
    f = facility(client, owner)
    plan = ok(client.post(f"{API}/package-plans", headers=owner, json={
        "reservation_type_id": f.type, "name": "Five lessons", "session_mode": "fixed", "session_count": 5,
        "fee_minor": 5000, "fee_basis": "per_package", "revenue_category_id": category(tenant, "PACK"),
    }))  # fmt: skip
    series = ok(client.post(f"{API}/bookings", headers=owner, json={
        "location_id": f.location, "kind": "session", "reservation_type_id": f.type, "starts_at": at(10),
        "ends_at": at(11), "resources": [{"resource_id": f.court2}], "session": {"capacity": 4},
        "recurrence": {"pattern": "weekly", "weekdays": [1], "range_type": "count", "occurrence_limit": 3},
    }))["booking"]["session"]["id"]  # fmt: skip
    a, b = people(client, owner, f, 2)
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])

    def sell(person: str, **extra) -> dict:
        body = {"client_id": person, "location_id": f.location, "package_plan_id": plan["id"]} | extra
        sold = client.post(f"{API}/client-packages", headers=desk, json=body)
        assert sold.status_code == 201, sold.text
        return sold.json()

    pack = sell(a, payment={"amount_minor": 5000, "tender_kind": "cash"})
    batch = ok(client.post(f"{API}/enrollments/batch", headers=desk, json={
        "client_id": a, "session_id": series, "booked_scope": "all_linked", "client_package_id": pack["id"],
    }), 200)  # fmt: skip
    assert len(batch["enrolled"]) == 3 and batch["skipped"] == []
    held = ok(client.get(f"{API}/client-packages/{pack['id']}", headers=desk), 200)
    assert (held["sessions_reserved_count"], held["sessions_available_count"]) == (3, 2)
    assert open_balance(tenant, a) == 0

    unpaid = sell(b)  # billed, not paid: the charge stays open on the client
    place = client.post(f"{API}/enrollments", headers=desk, json={
        "client_id": b, "session_id": series, "client_package_id": unpaid["id"], "program_fee_ids": [],
    })  # fmt: skip
    assert place.status_code == 201, place.text
    assert ok(client.get(f"{API}/client-packages/{unpaid['id']}", headers=desk), 200)["sessions_reserved_count"] == 1
    assert open_balance(tenant, b) == 5000

    elsewhere = facility(client, owner, "America/New_York")
    outsider = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[elsewhere.location])[0])
    body = {"client_id": b, "location_id": f.location, "package_plan_id": plan["id"]}
    assert client.post(f"{API}/client-packages", headers=outsider, json=body).status_code in (403, 404, 422)
