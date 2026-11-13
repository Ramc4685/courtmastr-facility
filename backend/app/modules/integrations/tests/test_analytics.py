"""Analytics on registration pages (INT-13): a tenant-wide measurement id with linked domains, validated, editable,
and read anonymously by the portal only while the connection is active."""

from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import login, make_tenant


def _connect(client, headers, **settings):
    body = {"provider": "google_analytics", "settings": {"measurement_id": "g-ab12cd34", **settings}}
    return client.post(f"{API}/external-connections", headers=headers, json=body)


def test_the_portal_reads_the_tag_only_while_it_is_connected(client, tenant, owner):
    public = {"X-Tenant-Slug": tenant.slug}
    url = f"{API}/public/analytics-config"
    assert client.get(url, headers=public).status_code == 404
    row = ok(_connect(client, owner, linked_domains="Club.Example.com, shop.example.com"))
    assert (row["status"], row["external_account_id"]) == ("active", "G-AB12CD34")
    config = ok(client.get(url, headers=public), 200)
    assert config == {"measurement_id": "G-AB12CD34", "linked_domains": ["club.example.com", "shop.example.com"]}

    patched = client.patch(f"{API}/external-connections/{row['id']}", headers=owner,
                           json={"settings": {"linked_domains": None, "measurement_id": "G-ZZ99ZZ99"}})  # fmt: skip
    assert patched.status_code == 200, patched.text
    assert ok(client.get(url, headers=public), 200) == {"measurement_id": "G-ZZ99ZZ99", "linked_domains": []}

    other = make_tenant()
    assert client.get(url, headers={"X-Tenant-Slug": other.slug}).status_code == 404  # never another tenant's tag
    ok(client.post(f"{API}/external-connections/{row['id']}/disconnect", headers=owner), 200)
    assert client.get(url, headers=public).status_code == 404
    late = client.patch(f"{API}/external-connections/{row['id']}", headers=owner,
                        json={"settings": {"measurement_id": "G-AB12CD34"}})  # fmt: skip
    assert late.status_code == 409


def test_settings_are_validated_and_analytics_is_tenant_wide(client, owner):
    f = facility(client, owner)
    bad_id = client.post(f"{API}/external-connections", headers=owner,
                         json={"provider": "google_analytics", "settings": {"measurement_id": "UA-1234-1"}})  # fmt: skip
    assert bad_id.status_code == 422
    assert _connect(client, owner, linked_domains="not a host").status_code == 422
    assert _connect(client, owner, tracker="x").status_code == 422
    assert _connect(client, owner, linked_domains=",".join(f"d{i}.example.com" for i in range(11))).status_code == 422
    scoped = client.post(f"{API}/external-connections", headers=owner, json={
        "provider": "google_analytics", "location_id": f.location, "settings": {"measurement_id": "G-AB12CD34"}})  # fmt: skip
    assert scoped.status_code == 422
    ok(_connect(client, owner))
    rival = login(client, make_tenant())
    assert _connect(client, rival).status_code == 201  # a measurement id is public; two tenants may share one
