"""Wave 1 hardening, batch space: S-05 (docs/security/wave1-hardening-spec.md section 5). S-06 is proven by
the generated guard in tests/test_portal_schemas.py."""

from app.modules.rentals.tests.test_rentals import f, rent, weekly  # noqa: F401  (f is a fixture)
from app.modules.scheduling.tests.helpers import API, ok
from conftest import add_staff, login


def test_extend_stays_on_the_types_resources(client, owner, tenant, f):  # noqa: F811
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    rental = ok(rent(client, owner, f, 15, 16, recurrence=weekly(2)))["rental"]["id"]
    url = f"{API}/rentals/{rental}/extensions"
    body = {"start_on": "2031-06-02", "start_time": "10:00", "end_time": "11:00", "rule": weekly(1)}
    for resource in (f.half_b, f.coach):  # in the location, not offered by the rental type
        refused = client.post(url, headers=desk, json=body | {"resources": [{"resource_id": resource}]})
        assert (refused.status_code, refused.json()["code"]) == (422, "resource-not-allowed")
    denied = client.post(url, headers=desk, json=body | {"override_policy": True})
    assert denied.status_code == 403 and denied.json()["required"] == "scheduling.booking.override_policy"
    extended = ok(client.post(url, headers=desk, json=body | {"resources": [{"resource_id": f.court2}]}))
    assert extended["created_count"] == 1
