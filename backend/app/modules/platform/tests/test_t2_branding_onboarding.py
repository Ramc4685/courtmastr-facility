"""Phase 8 T2: logos and their public URL (PLT-08), the setup checklist (ONB-01) and support requests (ONB-03)."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.db.session import tenant_session
from app.core.settings import get_settings
from app.modules.platform import files, retention
from app.modules.platform.models import StoredFile
from conftest import WEEK, add_staff, login, make_tenant, png_bytes

API = "/api/v1"


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def _image(headers):
    return headers | {"Content-Type": "image/png", "X-File-Name": "logo.png"}


def _path(url: str) -> str:
    return url.removeprefix(get_settings().app.web_base_url)


def _location(client, owner, **extra):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"} | extra
    return ok(client.post(f"{API}/locations", headers=owner, json=body), 201)["id"]


# --- logos (PLT-08) -------------------------------------------------------------------------------------------


def test_logos_upload_replace_remove_and_serve_publicly(client, tenant, owner):
    public = {"X-Tenant-Slug": tenant.slug}
    assert ok(client.get(f"{API}/public/branding", headers=public)) == {"tenant_logo_url": None, "locations": []}
    first = ok(client.put(f"{API}/branding/logo", headers=_image(owner), content=png_bytes()))["tenant_logo_url"]
    assert f"/t/{tenant.id}/public/" in first
    served = client.get(_path(first))  # anonymous: no tenant header, no bearer
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert (
        served.headers["cache-control"].startswith("public") and served.headers["x-content-type-options"] == "nosniff"
    )

    second = ok(client.put(f"{API}/branding/logo", headers=_image(owner), content=png_bytes((8, 8))))
    assert second["tenant_logo_url"] != first
    assert client.get(_path(first)).status_code == 404  # the replaced file is purged
    location_id = _location(client, owner)
    shown = ok(client.put(f"{API}/locations/{location_id}/logo", headers=_image(owner), content=png_bytes()))
    assert [row["location_id"] for row in shown["locations"]] == [location_id]
    assert ok(client.get(f"{API}/public/branding", headers=public)) == shown

    gone = ok(client.delete(f"{API}/branding/logo", headers=owner))
    assert gone["tenant_logo_url"] is None and client.get(_path(second["tenant_logo_url"])).status_code == 404
    assert client.delete(f"{API}/branding/logo", headers=owner).status_code == 404


def test_logo_rules_and_the_public_route_serves_logos_only(client, tenant, owner):
    bad = client.put(f"{API}/branding/logo", headers=owner | {"Content-Type": "image/png"}, content=b"%PDF-1.4 x")
    assert bad.status_code == 422 and bad.json()["code"] == "file-type-mismatch"
    with tenant_session(tenant.id) as session, pytest.raises(ValueError):
        files.store(session, png_bytes(), purpose="support_screenshot", content_type=files.PNG,
                    uploaded_by=("system", None), public=True)  # fmt: skip
    with tenant_session(tenant.id) as session:
        private = files.store(session, b"%PDF-1.4 x", purpose="tests.private", content_type=files.PDF,
                              uploaded_by=("system", None))  # fmt: skip
        key = private.object_key
    assert client.get(f"{API}/public/objects/{key}").status_code == 404
    forged = key.replace(f"t/{tenant.id}/", f"t/{tenant.id}/public/")
    assert client.get(f"{API}/public/objects/{forged}").status_code == 404
    assert client.get(f"{API}/public/objects/t/not-a-uuid/public/x").status_code == 404


def test_logo_gates_and_tenant_scope(client, tenant, owner):
    email, _ = add_staff(tenant, "front_desk", all_locations=True)
    desk = login(client, tenant, email)
    assert client.put(f"{API}/branding/logo", headers=_image(desk), content=png_bytes()).status_code == 403
    url = ok(client.put(f"{API}/branding/logo", headers=_image(owner), content=png_bytes()))["tenant_logo_url"]
    other = make_tenant()
    location_id = _location(client, owner)
    stranger = login(client, other)
    assert client.put(f"{API}/locations/{location_id}/logo", headers=_image(stranger),
                      content=png_bytes()).status_code == 404  # fmt: skip
    moved = _path(url).replace(str(tenant.id), str(other.id))  # the other tenant's prefix finds nothing
    assert client.get(moved).status_code == 404
    with tenant_session(other.id) as session:
        assert session.scalar(select(StoredFile.id).where(StoredFile.purpose == "tenant_logo")) is None


# --- setup checklist (ONB-01) ---------------------------------------------------------------------------------


def _steps(client, headers) -> dict:
    body = ok(client.get(f"{API}/onboarding/checklist", headers=headers))
    return {s["key"]: s["is_done"] for s in body["steps"]} | {"_dismissed": body["is_dismissed"]}


def test_checklist_is_computed_from_real_data(client, tenant, owner):
    steps = _steps(client, owner)
    assert {k for k, done in steps.items() if done} == set()  # a brand-new account has done nothing
    assert list(steps)[:-1] == ["location", "hours", "resources", "staff", "payments", "offer", "branding"]
    location_id = _location(client, owner, address_line1="1 Court St")
    ok(client.put(f"{API}/locations/{location_id}/facility-hours", headers=owner, json={"days": WEEK}))
    add_staff(tenant, "front_desk", all_locations=True)
    ok(client.put(f"{API}/branding/logo", headers=_image(owner), content=png_bytes()))
    done = _steps(client, owner)
    assert {k for k, v in done.items() if v} == {"location", "hours", "staff", "branding"}


def test_checklist_dismissal_is_per_user_and_gated(client, tenant, owner):
    ok(client.put(f"{API}/onboarding/checklist/dismissal", headers=owner, json={"is_dismissed": True}))
    assert _steps(client, owner)["_dismissed"]
    email, _ = add_staff(tenant, "admin", all_locations=True)
    admin = login(client, tenant, email)
    assert not _steps(client, admin)["_dismissed"]
    email, _ = add_staff(tenant, "front_desk", all_locations=True)
    assert client.get(f"{API}/onboarding/checklist", headers=login(client, tenant, email)).status_code == 403
    ok(client.put(f"{API}/onboarding/checklist/dismissal", headers=owner, json={"is_dismissed": False}))
    assert not _steps(client, owner)["_dismissed"]


# --- support requests (ONB-03) --------------------------------------------------------------------------------


def test_support_request_is_emailed_to_the_operator_and_visible_to_its_sender_only(client, tenant, owner, mailbox):
    shot = ok(client.put(f"{API}/support-requests/screenshot", headers=_image(owner), content=png_bytes()), 201)
    body = {"category": "problem", "message": "The calendar will not load", "screenshot_file_id": shot["id"]}
    request = ok(client.post(f"{API}/support-requests", headers=owner, json=body), 201)
    assert request["status"] == "open" and request["screenshot_file_id"] == shot["id"]
    message = mailbox[-1]
    assert message.to == get_settings().support.operator_email
    assert tenant.slug in message.subject and "The calendar will not load" in message.body
    assert "Screenshot stored: yes" in message.body

    email, _ = add_staff(tenant, "manager", all_locations=True)
    desk = login(client, tenant, email)
    assert ok(client.get(f"{API}/support-requests", headers=desk))["data"] == []
    assert client.get(f"{API}/support-requests/{request['id']}", headers=desk).status_code == 404
    reuse = client.post(f"{API}/support-requests", headers=desk, json=body)  # someone else's screenshot
    assert reuse.status_code == 422, reuse.text
    mine = ok(client.post(f"{API}/support-requests", headers=desk, json={"category": "question", "message": "?"}), 201)
    assert [r["id"] for r in ok(client.get(f"{API}/support-requests", headers=desk))["data"]] == [mine["id"]]

    front_desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    assert client.get(f"{API}/support-requests", headers=front_desk).status_code == 403  # Owner, Admin, Manager

    closed = ok(client.post(f"{API}/support-requests/{request['id']}/close", headers=owner))
    assert closed["status"] == "closed" and closed["closed_at"]
    again = client.post(f"{API}/support-requests/{request['id']}/close", headers=owner)
    assert again.status_code == 409 and again.json()["code"] == "invalid-state-transition"


def test_support_requests_are_rate_limited_per_staff_user(client, tenant, owner, monkeypatch):
    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setitem(cfg.buckets, "support-request", cfg.buckets["support-request"].model_copy(update={"limit": 2}))
    body = {"category": "question", "message": "?"}
    codes = [client.post(f"{API}/support-requests", headers=owner, json=body).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    shot = client.put(f"{API}/support-requests/screenshot", headers=_image(owner), content=png_bytes())
    assert shot.status_code == 429
    email, _ = add_staff(tenant, "manager", all_locations=True)  # another staff user has their own bucket
    ok(client.post(f"{API}/support-requests", headers=login(client, tenant, email), json=body), 201)


def test_an_unattached_support_screenshot_is_purged_after_a_day(client, tenant, owner):
    loose = ok(client.put(f"{API}/support-requests/screenshot", headers=_image(owner), content=png_bytes()), 201)
    kept = ok(client.put(f"{API}/support-requests/screenshot", headers=_image(owner), content=png_bytes()), 201)
    ok(client.post(f"{API}/support-requests", headers=owner,
                   json={"category": "question", "message": "?", "screenshot_file_id": kept["id"]}), 201)  # fmt: skip
    with tenant_session(tenant.id) as session:
        assert retention.purge(session)["support_screenshot"] == 0  # under a day old
    with clock.freeze(clock.now() + timedelta(days=2)), tenant_session(tenant.id) as session:
        assert retention.purge(session)["support_screenshot"] == 1
        assert session.get(StoredFile, loose["id"]).status == "purged"
        assert session.get(StoredFile, kept["id"]).status == "ready"
