"""Wave 1 hardening, batch space: S-07 (docs/security/wave1-hardening-spec.md section 5)."""

from conftest import add_staff, login

API = "/api/v1"


def test_limited_editor_cannot_remove_foreign_locations(client, owner, tenant):
    body = {"time_zone": "UTC", "country_code": "US"}
    a, b = (client.post(f"{API}/locations", headers=owner, json=body | {"name": n}).json()["id"] for n in "AB")
    admin = login(client, tenant, add_staff(tenant, "admin", location_ids=[a])[0])
    _, colleague = add_staff(tenant, "front_desk", location_ids=[b, a])  # primary at B
    url = f"{API}/staff-users/{colleague}/locations"
    # Emptying the set removes only what the editor reaches (A); B, outside its say, stays.
    kept = client.put(url, headers=admin, json={"has_all_location_access": False, "location_ids": []})
    assert kept.status_code == 200, kept.text
    assert (kept.json()["location_ids"], kept.json()["primary_location_id"]) == ([b], b)
    moved = client.put(url, headers=admin, json={"has_all_location_access": False, "primary_location_id": a})
    assert sorted(moved.json()["location_ids"]) == sorted([a, b]) and moved.json()["primary_location_id"] == a
    # Someone with every location cannot be narrowed by a limited editor.
    _, everywhere = add_staff(tenant, "front_desk", all_locations=True)
    refused = client.put(
        f"{API}/staff-users/{everywhere}/locations", headers=admin,
        json={"has_all_location_access": False, "location_ids": [a]},
    )  # fmt: skip
    assert (refused.status_code, refused.json()["code"]) == (403, "self-escalation")


def test_an_int4_overflow_is_a_422_not_a_500(client, owner):
    body = {"time_zone": "UTC", "country_code": "US", "name": "Big", "sort_order": 2**31}
    bounded = client.post(f"{API}/locations", headers=owner, json=body)
    assert (bounded.status_code, bounded.json()["code"]) == (422, "validation-failed"), bounded.text
    location_id = client.post(f"{API}/locations", headers=owner, json=body | {"sort_order": 1}).json()["id"]
    # Fields without a schema bound fall to the central net: Postgres 22003 (out of range) is a 422.
    group = {"location_id": location_id, "name": "Courts", "sort_order": 2**31}
    netted = client.post(f"{API}/resource-groups", headers=owner, json=group)
    assert (netted.status_code, netted.json()["code"]) == (422, "validation-failed"), netted.text
