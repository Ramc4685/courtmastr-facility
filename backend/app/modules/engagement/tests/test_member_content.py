"""Phase 11 C2: member app content (APP-07, APP-14), location contacts (APP-08, APP-09), the trial request and
feedback inbox (APP-10, APP-12)."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.events import OutboxEvent
from app.core.settings import get_settings
from app.modules.clients.models import Client
from app.modules.engagement.models import AppInquiry
from app.modules.platform import privacy, retention
from app.modules.programs.tests.test_checkout import member
from app.modules.scheduling.tests.helpers import facility
from conftest import add_staff, login, new_client, png_bytes, scalar

API = "/api/v1"
TRIALS = f"{API}/public/trial-requests"


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def code(response) -> tuple[int, str | None]:
    return response.status_code, response.json().get("code")


def iso(delta: timedelta) -> str:
    return (clock.now() + delta).isoformat()


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def open_portal(client, owner, location_id, **body) -> None:
    url = f"{API}/locations/{location_id}/portal-settings"
    ok(client.put(url, headers=owner, json={"is_enabled": True, "is_public": True} | body))


def new_content(client, owner, **body) -> dict:
    data = {"kind": "news", "title": "Open day", "body_text": "Come along: https://example.com/open",
            "publish_at": iso(-timedelta(hours=1))} | body  # fmt: skip
    return ok(client.post(f"{API}/app-contents", headers=owner, json=data), 201)


def trial(client, tenant, location_id, email=None, **extra):
    body = {"location_id": str(location_id), "name": "Tess Trial", "email": email or f"t-{uuid4().hex[:8]}@example.com",
            "interest": "Pickleball"} | extra  # fmt: skip
    return client.post(TRIALS, headers={"X-Tenant-Slug": tenant.slug}, json=body)


def inquiries(tenant, **where) -> list[AppInquiry]:
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        stmt = select(AppInquiry).filter_by(**where)
        rows = list(session.scalars(stmt))
        session.expunge_all()
        return rows


# --- content -------------------------------------------------------------------------------------------------


def test_portal_sees_published_unexpired_items_tenant_wide_plus_its_location(client, tenant, owner, f, mailbox):
    other = ok(client.post(f"{API}/locations", headers=owner,
                           json={"name": "Annex", "time_zone": "America/Chicago", "country_code": "US"}), 201)["id"]  # fmt: skip
    everywhere = new_content(client, owner, title="Everywhere")
    here = new_content(client, owner, title="Here", location_id=f.location, kind="promotion")
    new_content(client, owner, title="Annex only", location_id=other)
    new_content(client, owner, title="Later", publish_at=iso(timedelta(days=1)))
    new_content(client, owner, title="Gone", publish_at=iso(-timedelta(days=2)), expires_at=iso(-timedelta(days=1)))
    _, portal = member(client, tenant, owner, f, mailbox)

    titles = lambda **params: {r["title"] for r in ok(client.get(f"{API}/portal/app-contents", headers=portal,  # noqa: E731
                                                                 params=params))["data"]}  # fmt: skip
    assert titles() == {"Everywhere"}
    assert titles(location_id=f.location) == {"Everywhere", "Here"}
    assert titles(location_id=f.location, kind="promotion") == {"Here"}
    assert "version" not in ok(client.get(f"{API}/portal/app-contents", headers=portal))["data"][0]

    staff = ok(client.get(f"{API}/app-contents", headers=owner, params={"location_id": f.location}))["data"]
    assert [r["id"] for r in staff] == [here["id"]]
    assert len(ok(client.get(f"{API}/app-contents", headers=owner))["data"]) == 5
    assert client.get(f"{API}/portal/app-contents", headers=owner).status_code == 404  # staff are not a portal client
    assert everywhere["location_id"] is None


def test_plain_text_only_https_links_and_a_sane_window(client, owner):
    for body in ({"body_text": "Hi <b>there</b>"}, {"body_text": "</p>"}, {"title": "<!-- x -->"},
                 {"body_text": "<script>alert(1)</script>"}):  # fmt: skip
        refused = client.post(f"{API}/app-contents", headers=owner, json={
            "kind": "news", "title": "T", "publish_at": iso(timedelta())} | body)  # fmt: skip
        assert code(refused) == (422, "html-not-allowed"), body
    fine = new_content(client, owner, body_text="Scores: 3 < 4 and 5 > 2")
    assert fine["body_text"] == "Scores: 3 < 4 and 5 > 2"
    insecure = client.post(f"{API}/app-contents", headers=owner, json={
        "kind": "news", "title": "T", "publish_at": iso(timedelta()), "link_url": "http://example.com"})  # fmt: skip
    assert insecure.status_code == 422
    backwards = client.post(f"{API}/app-contents", headers=owner, json={
        "kind": "news", "title": "T", "publish_at": iso(timedelta()), "expires_at": iso(-timedelta(hours=1))})  # fmt: skip
    assert code(backwards) == (422, "invalid-window")

    url = f"{API}/app-contents/{fine['id']}"
    assert code(client.patch(url, headers=owner, json={"body_text": "<i>x</i>"})) == (422, "html-not-allowed")
    changed = ok(client.patch(url, headers=owner, json={"title": "Renamed", "version": fine["version"],
                                                        "link_url": "https://example.com/x"}))  # fmt: skip
    assert (changed["title"], changed["version"]) == ("Renamed", fine["version"] + 1)
    stale = client.patch(url, headers=owner, json={"title": "Again", "version": fine["version"]})
    assert code(stale) == (409, "version-conflict")


def test_image_goes_through_files_and_the_portal_reads_it(client, tenant, owner, f, mailbox):
    item = new_content(client, owner, kind="gallery", title="Finals night")
    url = f"{API}/app-contents/{item['id']}/image"
    wrong = client.put(url, headers=owner | {"Content-Type": "image/jpeg"}, content=png_bytes())
    assert code(wrong) == (422, "file-type-mismatch")
    set_ = ok(client.put(url, headers=owner | {"Content-Type": "image/png"}, content=png_bytes()))
    assert set_["has_image"] is True
    _, portal = member(client, tenant, owner, f, mailbox)
    image = client.get(f"{API}/portal/app-contents/{item['id']}/image", headers=portal)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")

    assert client.delete(url, headers=owner).status_code == 204
    assert client.delete(url, headers=owner).status_code == 204  # idempotent
    assert client.get(f"{API}/portal/app-contents/{item['id']}/image", headers=portal).status_code == 404
    hidden = new_content(client, owner, title="Later", publish_at=iso(timedelta(days=1)))
    ok(client.put(f"{API}/app-contents/{hidden['id']}/image", headers=owner | {"Content-Type": "image/png"},
                  content=png_bytes()))  # fmt: skip
    assert client.get(f"{API}/portal/app-contents/{hidden['id']}/image", headers=portal).status_code == 404
    assert client.delete(f"{API}/app-contents/{hidden['id']}", headers=owner).status_code == 204


# --- contacts ------------------------------------------------------------------------------------------------


def test_contacts_need_a_phone_or_email_and_are_public_only_for_an_open_portal(client, tenant, owner, f):
    url = f"{API}/location-contacts"
    base = {"location_id": f.location, "kind": "department", "name": "Front desk"}
    assert code(client.post(url, headers=owner, json=base)) == (422, "contact-unreachable")
    desk = ok(client.post(url, headers=owner, json=base | {"phone": "+1 555 0100", "role": "Bookings"}), 201)
    ok(client.post(url, headers=owner, json=base | {"kind": "service", "name": "Physio", "email": "physio@example.com"}),
       201)  # fmt: skip
    cleared = client.patch(f"{url}/{desk['id']}", headers=owner, json={"phone": None})
    assert code(cleared) == (422, "contact-unreachable")
    assert len(ok(client.get(url, headers=owner, params={"kind": "service"}))["data"]) == 1

    public = f"{API}/public/location-contacts"
    slug = {"X-Tenant-Slug": tenant.slug}
    assert ok(client.get(public, headers=slug, params={"location_id": f.location}))["data"] == []
    open_portal(client, owner, f.location)
    shown = ok(client.get(public, headers=slug, params={"location_id": f.location}))["data"]
    assert [c["name"] for c in shown] == ["Front desk", "Physio"] and "sort_order" not in shown[0]
    open_portal(client, owner, f.location, is_public=False)
    assert ok(client.get(public, headers=slug, params={"location_id": f.location}))["data"] == []


# --- trial requests and feedback -----------------------------------------------------------------------------


def test_trial_request_answers_alike_creates_no_client_and_reaches_the_inbox(client, tenant, owner, f):
    clients_before = scalar(tenant, select(func.count()).select_from(Client))
    closed = trial(client, tenant, f.location)  # the portal is not open yet: nothing stored
    unknown = trial(client, tenant, uuid4())
    open_portal(client, owner, f.location)
    stored = trial(client, tenant, f.location, email="Tess@Example.com", message="Weekday mornings")
    assert closed.status_code == unknown.status_code == stored.status_code == 202
    assert closed.content == unknown.content == stored.content == b""
    rows = inquiries(tenant, kind="trial")
    assert [(r.contact_email, r.client_id, r.status) for r in rows] == [("tess@example.com", None, "new")]
    assert scalar(tenant, select(func.count()).select_from(Client)) == clients_before
    events = scalar(tenant, select(func.count()).select_from(OutboxEvent)
                    .where(OutboxEvent.event_type == "engagement.app_inquiry.received"))  # fmt: skip
    assert events == 1
    changes = scalar(tenant, select(AuditEvent.changes).where(AuditEvent.action == "engagement.app_inquiry.receive"))
    assert changes["contact_email"] is True and changes["message"] is True  # PII as flags only

    inbox = ok(client.get(f"{API}/app-inquiries", headers=owner, params={"kind": "trial"}))["data"]
    assert inbox[0]["contact_name"] == "Tess Trial"
    moved = ok(client.patch(f"{API}/app-inquiries/{inbox[0]['id']}", headers=owner, json={"status": "converted"}))
    assert moved["status"] == "converted" and moved["handled_at"] and moved["handled_by_staff_user_id"]
    back = ok(client.patch(f"{API}/app-inquiries/{inbox[0]['id']}", headers=owner, json={"status": "new"}))
    assert (back["handled_at"], back["handled_by_staff_user_id"]) == (None, None)
    assert len(ok(client.get(f"{API}/app-inquiries", headers=owner, params={"status": "new"}))["data"]) == 1


def test_trial_requests_are_rate_limited(client, tenant, owner, f, monkeypatch):
    open_portal(client, owner, f.location)
    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setitem(cfg.buckets, "trial-request", cfg.buckets["trial-request"].model_copy(update={"limit": 1}))
    email = f"t-{uuid4().hex[:8]}@example.com"
    assert trial(client, tenant, f.location, email).status_code == 202
    limited = trial(client, tenant, f.location, email.upper())
    assert code(limited) == (429, "rate-limited")
    assert len(inquiries(tenant, kind="trial")) == 1


def test_feedback_is_for_own_clients_only(client, tenant, owner, f, mailbox):
    person, portal = member(client, tenant, owner, f, mailbox)
    url = f"{API}/portal/feedback"
    sent = ok(client.post(url, headers=portal, json={"client_id": person["id"], "message": "Love it", "rating": 5}),
              201)  # fmt: skip
    assert list(sent) == ["id"]
    row = inquiries(tenant, kind="feedback")[0]
    assert (str(row.client_id), str(row.location_id), row.rating, row.status) == (person["id"], f.location, 5, "new")
    stranger = new_client(client, owner, f.location)
    refused = client.post(url, headers=portal, json={"client_id": stranger["id"], "message": "Hi"})
    assert code(refused) == (404, "not-found")
    assert client.post(url, headers=owner, json={"client_id": person["id"], "message": "Hi"}).status_code == 404
    assert (
        client.post(url, headers=portal, json={"client_id": person["id"], "message": "x", "rating": 6}).status_code
        == 422
    )
    listed = ok(client.get(f"{API}/app-inquiries", headers=owner, params={"kind": "feedback"}))["data"]
    assert listed[0]["message"] == "Love it" and listed[0]["client_id"] == person["id"]


def test_feedback_goes_only_to_a_location_the_client_can_see(client, tenant, owner, f, mailbox):
    """The client's home location, or a location whose portal is on and public; any other is 422."""
    person, portal = member(client, tenant, owner, f, mailbox)
    url = f"{API}/portal/feedback"
    hidden = facility(client, owner, "America/New_York")
    body = {"client_id": person["id"], "message": "Hello", "location_id": hidden.location}
    assert code(client.post(url, headers=portal, json=body)) == (422, "validation-failed")
    open_portal(client, owner, hidden.location)
    ok(client.post(url, headers=portal, json=body), 201)
    ok(client.post(url, headers=portal, json=body | {"location_id": f.location}), 201)  # home, portal not public
    assert {str(r.location_id) for r in inquiries(tenant, kind="feedback")} == {hidden.location, f.location}


def test_feedback_is_rate_limited(client, tenant, owner, f, mailbox, monkeypatch):
    person, portal = member(client, tenant, owner, f, mailbox)
    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setitem(cfg.buckets, "portal-feedback", cfg.buckets["portal-feedback"].model_copy(update={"limit": 1}))
    url, body = f"{API}/portal/feedback", {"client_id": person["id"], "message": "One"}
    ok(client.post(url, headers=portal, json=body), 201)
    assert code(client.post(url, headers=portal, json=body)) == (429, "rate-limited")


def test_feedback_fails_closed_when_the_limiter_is_down(client, tenant, owner, f, mailbox, monkeypatch):
    """Like the app directory: without Redis to count, feedback is refused rather than taken unmetered."""
    import redis

    from app.core import ratelimit

    person, portal = member(client, tenant, owner, f, mailbox)
    monkeypatch.setattr(get_settings().rate_limit, "enabled", True)
    down = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    monkeypatch.setattr(ratelimit, "_redis", lambda: down)
    refused = client.post(f"{API}/portal/feedback", headers=portal, json={"client_id": person["id"], "message": "Hi"})
    assert code(refused) == (503, "rate-limit-unavailable")
    assert [r for r in inquiries(tenant, kind="feedback") if str(r.client_id) == person["id"]] == []


def test_trial_requests_are_purged_after_180_days_or_90_after_closing(client, tenant, owner, f):
    open_portal(client, owner, f.location)
    names = {}
    for label in ("old", "fresh", "closed_long_ago", "closed_lately"):
        email = f"{label}-{uuid4().hex[:6]}@example.com"
        trial(client, tenant, f.location, email)
        names[label] = email
    now = clock.now()
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        rows = {r.contact_email: r for r in session.scalars(select(AppInquiry).where(AppInquiry.kind == "trial"))}
        rows[names["old"]].created_at = now - timedelta(days=181)
        rows[names["fresh"]].created_at = now - timedelta(days=179)
        for label, days in (("closed_long_ago", 91), ("closed_lately", 89)):
            rows[names[label]].status, rows[names[label]].handled_at = "closed", now - timedelta(days=days)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert retention._PURGERS["engagement_trial_inquiry"](session) == 2
    left = {r.contact_email for r in inquiries(tenant, kind="trial")}
    assert left == {names["fresh"], names["closed_lately"]}


def test_merge_moves_feedback_and_erasure_blanks_it(client, tenant, owner, f, mailbox):
    person, portal = member(client, tenant, owner, f, mailbox)
    ok(client.post(f"{API}/portal/feedback", headers=portal, json={"client_id": person["id"], "message": "Cold showers"}),
       201)  # fmt: skip
    survivor = new_client(client, owner, f.location)
    ok(client.post(f"{API}/clients/{survivor['id']}/merge", headers=owner,
                   json={"merged_client_ids": [person["id"]]}))  # fmt: skip
    row = inquiries(tenant, kind="feedback")[0]
    assert str(row.client_id) == survivor["id"]

    handler = privacy.HANDLERS["engagement_app_inquiry"]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert handler.export(session, row.client_id)["app_feedback"][0]["message"] == "Cold showers"
        assert handler.erase(session, row.client_id) == {"app_feedback_cleared": 1}
    erased = inquiries(tenant, kind="feedback")[0]
    assert (erased.contact_name, erased.message, erased.contact_email) == ("", "", None)


# --- both permission gates -----------------------------------------------------------------------------------


def test_permission_gates_and_location_scope(client, tenant, owner, f):
    open_portal(client, owner, f.location)
    trial(client, tenant, f.location)
    shared = new_content(client, owner, title="Everywhere")
    local = new_content(client, owner, title="Here", location_id=f.location)
    contact = ok(client.post(f"{API}/location-contacts", headers=owner, json={
        "location_id": f.location, "kind": "department", "name": "Desk", "phone": "1"}), 201)  # fmt: skip
    inquiry = ok(client.get(f"{API}/app-inquiries", headers=owner))["data"][0]

    desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    for method, path in (("GET", "/app-contents"), ("GET", "/location-contacts"), ("GET", "/app-inquiries"),
                         ("PATCH", f"/app-inquiries/{inquiry['id']}")):  # fmt: skip
        assert client.request(method, f"{API}{path}", headers=desk, json={"status": "closed"}).status_code == 403

    other = ok(client.post(f"{API}/locations", headers=owner,
                           json={"name": "Annex", "time_zone": "America/Chicago", "country_code": "US"}), 201)["id"]  # fmt: skip
    outsider = login(client, tenant, add_staff(tenant, "admin", location_ids=[other])[0])
    for method, path in (("PATCH", f"/app-contents/{local['id']}"), ("PATCH", f"/location-contacts/{contact['id']}"),
                         ("GET", f"/location-contacts/{contact['id']}"),
                         ("PATCH", f"/app-inquiries/{inquiry['id']}")):  # fmt: skip
        response = client.request(method, f"{API}{path}", headers=outsider, json={"status": "closed"} if
                                  "inquir" in path else {})  # fmt: skip
        assert code(response) == (404, "not-found"), path
    seen = {r["title"] for r in ok(client.get(f"{API}/app-contents", headers=outsider))["data"]}
    assert seen == {"Everywhere"}  # tenant-wide rows are listed, other locations' are not
    tenant_wide = client.patch(f"{API}/app-contents/{shared['id']}", headers=outsider, json={"title": "Mine"})
    assert tenant_wide.status_code == 403  # a tenant-wide row needs the key at every location
    assert client.post(f"{API}/app-contents", headers=outsider, json={
        "kind": "news", "title": "T", "publish_at": iso(timedelta())}).status_code == 403  # fmt: skip
    assert ok(client.get(f"{API}/app-inquiries", headers=outsider))["data"] == []
    assert ok(client.get(f"{API}/location-contacts", headers=outsider))["data"] == []
