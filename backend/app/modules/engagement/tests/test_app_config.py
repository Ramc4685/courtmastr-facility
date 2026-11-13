"""Member app configuration (APP-01, APP-02, APP-04, APP-05, APP-18): staff get and put, the public bootstrap,
the shared-app directory, and the schedule flags applied to the portal session listing."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.audit import AuditEvent
from app.core.events import OutboxEvent
from app.modules.engagement.domain import app_config as rules
from app.modules.programs.tests.test_checkout import member
from app.modules.programs.tests.test_selfservice import SOON, listing, policy, soon
from app.modules.programs.tests.test_sessions import enroll, people
from app.modules.scheduling.tests.helpers import facility
from conftest import add_staff, login, make_tenant, scalar

API = "/api/v1"
LAYOUT = {"tiles": [{"type": "book", "caption": "Book a court", "style": "large"}, {"type": "card"}],
          "design": {"columns": 1, "corners": "square"}}  # fmt: skip


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def test_defaults_until_saved_then_put_replaces_and_is_audited(client, tenant, owner):
    first = ok(client.get(f"{API}/app-config", headers=owner))
    assert (first["is_enabled"], first["home_screen"]) == (False, None)
    assert first["tile_types"] == list(rules.TILE_TYPES) and first["features"]["booking"] is True
    body = {"is_enabled": True, "app_name": " Courtside ", "home_screen": LAYOUT,
            "schedule": {"shows_spots_left": False, "days_ahead": 14}}  # fmt: skip
    saved = ok(client.put(f"{API}/app-config", headers=owner, json=body))
    assert saved["app_name"] == "Courtside" and "theme" not in saved
    assert saved["home_screen"]["tiles"][1] == {"type": "card", "caption": None, "style": "small"}
    assert saved["schedule"] == {"shows_spots_left": False, "shows_full_sessions": True, "days_ahead": 14}
    # PUT replaces: what is left out returns to its default.
    again = ok(client.put(f"{API}/app-config", headers=owner, json={"is_enabled": True}))
    assert (again["app_name"], again["home_screen"], again["schedule"]["days_ahead"]) == (None, None, None)
    audited = select(AuditEvent.id).where(AuditEvent.action == "engagement.app_content.manage",
                                          AuditEvent.entity_type == "app_config").limit(1)  # fmt: skip
    assert scalar(tenant, audited)
    assert scalar(
        tenant, select(OutboxEvent.id).where(OutboxEvent.event_type == "engagement.app_config.updated").limit(1)
    )


@pytest.mark.parametrize(
    ("body", "pointer"),
    [
        ({"home_screen": {"tiles": [{"type": "weather"}]}}, "/home_screen/tiles/0/type"),
        ({"home_screen": {"tiles": [{"type": "book", "caption": "<b>Hi</b>"}]}}, "/home_screen/tiles/0/caption"),
        ({"home_screen": {"tiles": [], "design": {"columns": 3}}}, "columns"),
    ],
)
def test_invalid_config_is_refused_with_a_pointer(client, owner, body, pointer):
    response = client.put(f"{API}/app-config", headers=owner, json=body)
    assert response.status_code == 422, response.text
    assert pointer in response.text


def test_writes_need_the_key_at_every_location(client, tenant, owner):
    site = facility(client, owner)
    manager = login(client, tenant, add_staff(tenant, "manager", location_ids=[site.location])[0])
    assert client.get(f"{API}/app-config", headers=manager).status_code == 200
    assert client.put(f"{API}/app-config", headers=manager, json={"is_enabled": True}).status_code == 403
    desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    assert client.get(f"{API}/app-config", headers=desk).status_code == 403


def test_public_bootstrap_keeps_bundled_theme_until_switched_on(client, tenant, owner):
    public = {"X-Tenant-Slug": tenant.slug}
    ok(client.put(f"{API}/app-config", headers=owner, json={"home_screen": LAYOUT}))
    off = ok(client.get(f"{API}/public/app-config", headers=public))
    assert (off["home_screen"], off["app_name"]) == (None, off["portal"]["facility_name"])
    assert not any(off["theme"].values())
    body = {"is_enabled": True, "app_name": "Club App", "home_screen": LAYOUT}
    ok(client.put(f"{API}/app-config", headers=owner, json=body))
    on = ok(client.get(f"{API}/public/app-config", headers=public))
    # Colours come from the tenant branding (one source with the portal), not from the app config.
    assert set(on["theme"]) == {"primary", "accent"}
    assert (on["app_name"], on["home_screen"]["design"]["columns"]) == ("Club App", 1)
    assert on["tenant_id"] == str(tenant.id) and "locations" in on["portal"]
    assert client.get(f"{API}/public/app-config", headers={"X-Tenant-Slug": "no-such-club"}).status_code == 404


def _listed(client, owner, name: str, *, portal_public=True, listed=True) -> None:
    site = facility(client, owner)
    portal = {"is_enabled": True, "is_public": portal_public}
    ok(client.put(f"{API}/locations/{site.location}/portal-settings", headers=owner, json=portal))
    body = {"is_enabled": True, "is_listed_in_directory": listed, "directory_name": name}
    ok(client.put(f"{API}/app-config", headers=owner, json=body))


def test_directory_lists_only_listed_tenants_with_a_public_portal(client, tenant, owner):
    word = f"Zq{uuid4().hex[:8]}"
    _listed(client, owner, f"{word} Racquet Club")
    hidden_tenant = make_tenant()
    _listed(client, login(client, hidden_tenant), f"{word} Hidden", portal_public=False)
    unlisted_tenant = make_tenant()
    _listed(client, login(client, unlisted_tenant), f"{word} Unlisted", listed=False)
    found = ok(client.get(f"{API}/public/app-directory", params={"q": word.lower()}))["data"]
    assert [(e["name"], e["slug"]) for e in found] == [(f"{word} Racquet Club", tenant.slug)]
    assert set(found[0]) == {"tenant_id", "slug", "name", "city", "icon_url", "host"}
    by_word = ok(client.get(f"{API}/public/app-directory", params={"q": "racquet", "limit": 20}))["data"]
    assert by_word and all("racquet" in e["name"].lower() for e in by_word)
    # LIKE metacharacters are literal; one-letter queries are refused.
    assert ok(client.get(f"{API}/public/app-directory", params={"q": "%%"}))["data"] == []
    assert client.get(f"{API}/public/app-directory", params={"q": "z"}).status_code == 422
    # The cross-tenant read enforces its own bounds too, whoever calls it.
    from app.core.db import platform as platform_db

    assert platform_db.search_app_directory(" z ", 5) == []
    assert len(platform_db.search_app_directory("racquet", 500)) <= 20


def test_schedule_flags_narrow_the_portal_listing(client, tenant, owner, mailbox):
    f = facility(client, owner)
    policy(client, owner, f)
    seat, full = soon(client, owner, f, 4), soon(client, owner, f, 1, 13)
    (taken,) = people(client, owner, f, 1)
    ok(enroll(client, owner, full, taken), 201)
    _person, portal = member(client, tenant, owner, f, mailbox)
    row = listing(client, portal, seat)
    assert row["spots_left"] == 4 and row["time_zone"] == "America/Chicago"
    flags = {"shows_spots_left": False, "shows_full_sessions": False}
    ok(client.put(f"{API}/app-config", headers=owner, json={"schedule": flags}))
    assert listing(client, portal, seat)["spots_left"] is None
    shown = {r["session_id"] for r in ok(client.get(f"{API}/portal/session-listings", headers=portal))}
    assert full not in shown and seat in shown
    ok(client.put(f"{API}/app-config", headers=owner, json={"schedule": {"days_ahead": 1}}))  # SOON is 3 days out
    assert seat not in {r["session_id"] for r in ok(client.get(f"{API}/portal/session-listings", headers=portal))}


def test_present_listing_rules():
    item = {"starts_at": SOON, "reason": "full", "spots_left": 0}
    schedule = dict(rules.DEFAULT_SCHEDULE)
    assert rules.present_listing(item, schedule, None) == item
    assert rules.present_listing(item, schedule | {"shows_full_sessions": False}, None) is None
    assert rules.present_listing(item, schedule, SOON - timedelta(hours=1)) is None
    assert rules.present_listing(item, schedule | {"shows_spots_left": False}, None)["spots_left"] is None
    with pytest.raises(rules.Invalid):
        rules.clean_schedule({"days_ahead": 0})
    with pytest.raises(rules.Invalid):
        rules.clean_home_screen({"tiles": [{"type": "book"}] * 13})
    assert rules.clean_features({"booking": False})["purchases"] is True
