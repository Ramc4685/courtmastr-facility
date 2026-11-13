"""Calendar feeds (INT-08, SCH-19, STF-13, LGE-25, SSP-19) and the public schedule (SCH-20) on real PostgreSQL:
the URL token is shown once, stored hashed, revocable and kept out of the logs; content follows the owner's
current access; the public schedule shows seats and busy times, never names."""

import logging
from datetime import UTC, datetime

from app.core import clock
from app.core.auth import tokens
from app.core.db.session import tenant_session
from app.modules.integrations.domain import ical
from app.modules.integrations.models import CalendarFeed
from app.modules.integrations.tests.test_public_api import _member
from app.modules.scheduling.tests.helpers import API, book, facility, ok
from conftest import add_staff, login, new_client

WHEN = datetime(2031, 5, 1, 12, tzinfo=UTC)  # inside the ±90 day window of the test bookings


def _feed(client, headers, **body) -> dict:
    return ok(
        client.post(f"{API}/calendar-feeds", headers=headers, json={"kind": "staff_schedule", "name": "Mine"} | body)
    )


def _fetch(client, token: str):
    with clock.freeze(WHEN):
        return client.get(f"{API}/public/calendar-feeds/{token}")


def _session(
    client, owner, f, title="Clinic", start="2031-05-03T15:00:00Z", end="2031-05-03T16:00:00Z", resource=None, **extra
) -> dict:  # fmt: skip
    created = ok(book(client, owner, f, [resource or f.court], start, end, kind="session", title=title, **extra))
    return created.get("booking", created)


# --- iCalendar text ----------------------------------------------------------------------------------------


def test_ical_escapes_folds_and_uses_crlf():
    assert ical.escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    folded = ical.fold("SUMMARY:" + "é" * 60)
    assert all(len(line.encode()) <= 75 for line in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == "SUMMARY:" + "é" * 60
    text = ical.calendar("Mine", [ical.Event("u1", WHEN, WHEN, "Clinic", cancelled=True)], WHEN)
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20310501T120000Z" in text and "STATUS:CANCELLED" in text


# --- staff feeds -------------------------------------------------------------------------------------------


def test_staff_feed_token_is_shown_once_stored_hashed_and_serves_bookings(client, tenant, owner):
    f = facility(client, owner)
    _session(client, owner, f, title="Junior clinic")
    created = _feed(client, owner, location_id=f.location)
    token = created["url_token"]
    assert token.startswith("fhcal_")
    listed = ok(client.get(f"{API}/calendar-feeds", headers=owner), 200)["data"]
    assert [row["id"] for row in listed] == [created["id"]] and "url_token" not in listed[0]
    with tenant_session(tenant.id) as session:
        row = session.get(CalendarFeed, created["id"])
        assert row.token_hash == tokens.digest(token) and token not in (row.token_prefix + row.token_hash)

    response = _fetch(client, token)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Junior clinic" in response.text
    with tenant_session(tenant.id) as session:
        assert session.get(CalendarFeed, created["id"]).last_fetched_at is not None


def test_unknown_and_tampered_tokens_are_404(client, owner):
    token = _feed(client, owner)["url_token"]
    assert _fetch(client, token[:-2] + "xx").status_code == 404
    assert _fetch(client, "fhcal_nothex_x").status_code == 404
    assert _fetch(client, "garbage").status_code == 404


def test_disable_stops_the_url_and_re_enable_mints_a_new_one(client, owner):
    created = _feed(client, owner)
    old = created["url_token"]
    path = f"{API}/calendar-feeds/{created['id']}"
    disabled = ok(client.patch(path, headers=owner, json={"status": "disabled"}), 200)
    assert disabled["url_token"] is None and _fetch(client, old).status_code == 404
    enabled = ok(client.patch(path, headers=owner, json={"status": "active"}), 200)
    assert enabled["url_token"] and enabled["url_token"] != old
    assert _fetch(client, old).status_code == 404 and _fetch(client, enabled["url_token"]).status_code == 200
    assert client.delete(path, headers=owner).status_code == 204
    assert _fetch(client, enabled["url_token"]).status_code == 404


def test_feed_follows_the_owners_current_access(client, tenant, owner):
    """A front-desk user's feed shows their location's bookings; deactivating them stops the feed."""
    f = facility(client, owner)
    _session(client, owner, f, title="Desk visible")
    email, staff_user_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, email)
    token = _feed(client, desk)["url_token"]
    assert "SUMMARY:Desk visible" in _fetch(client, token).text
    other = facility(client, owner, "America/Denver")  # a location the desk user cannot see
    _session(client, owner, other, title="Elsewhere")
    assert "Elsewhere" not in _fetch(client, token).text
    assert client.post(f"{API}/staff-users/{staff_user_id}/deactivate", headers=owner, json={}).status_code == 200
    assert _fetch(client, token).status_code == 404


def test_a_feed_for_a_location_outside_your_scope_is_404(client, tenant, owner):
    f, other = facility(client, owner), facility(client, owner, "America/Denver")
    email, _ = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, email)
    refused = client.post(
        f"{API}/calendar-feeds",
        headers=desk,
        json={"kind": "staff_schedule", "name": "X", "location_id": other.location},
    )
    assert refused.status_code == 404


def test_revoke_any_disables_but_never_edits_someone_elses_feed(client, tenant, owner):
    f = facility(client, owner)
    email, _ = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, email)
    feed = _feed(client, desk, location_id=f.location)
    path = f"{API}/calendar-feeds/{feed['id']}"
    # Another desk user neither sees nor touches it.
    peer_email, _ = add_staff(tenant, "front_desk", location_ids=[f.location])
    peer = login(client, tenant, peer_email)
    assert client.patch(path, headers=peer, json={"status": "disabled"}).status_code == 404
    # A manager holding revoke_any sees it, may disable it, may not rename or re-enable it.
    manager_email, _ = add_staff(tenant, "manager", location_ids=[f.location])
    manager = login(client, tenant, manager_email)
    assert feed["id"] in {row["id"] for row in ok(client.get(f"{API}/calendar-feeds", headers=manager), 200)["data"]}
    assert client.patch(path, headers=manager, json={"name": "Mine now"}).status_code == 403
    assert ok(client.patch(path, headers=manager, json={"status": "disabled"}), 200)["status"] == "disabled"
    assert client.patch(path, headers=manager, json={"status": "active"}).status_code == 403
    assert _fetch(client, feed["url_token"]).status_code == 404


def test_staff_feed_shows_the_owners_shifts_in_the_window_only(client, tenant, owner):
    f = facility(client, owner)
    email, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, email)
    ids = []
    for start, end in (
        ("2031-05-03T14:00:00Z", "2031-05-03T22:00:00Z"),
        ("2030-01-03T14:00:00Z", "2030-01-03T22:00:00Z"),
    ):
        body = {"staff_user_id": str(desk_id), "location_id": f.location, "starts_at": start, "ends_at": end}
        ids.append(ok(client.post(f"{API}/shifts", headers=owner, json=body))["id"])
    ok(client.post(f"{API}/shifts/publish", headers=owner, json={"shift_ids": ids}), 200)
    text = _fetch(client, _feed(client, desk, include_shifts=True)["url_token"]).text
    assert f"UID:shift-{ids[0]}@courtmastr" in text and ids[1] not in text  # the 2030 shift is history
    assert "LAST-MODIFIED:" in text


def test_team_feed_shows_that_teams_games(client, tenant, owner):
    from app.modules.leagues.tests.test_leagues import league

    f = facility(client, owner)
    f.sport = ok(client.post(f"{API}/sports", headers=owner, json={"name": "Futsal", "default_game_length_min": 60}))
    mine = league(client, owner, f, teams=3, starts_on="2031-01-01", ends_on="2031-12-31")
    other = league(client, owner, f, name="Other league", teams=2)

    def game(comp: dict, home: int, away: int, resource: str, start: str) -> str:
        body = {"competition_id": comp["id"], "home_team_id": comp["teams"][home]["id"],
                "away_team_id": comp["teams"][away]["id"], "resource_id": resource, "starts_at": start}  # fmt: skip
        return ok(client.post(f"{API}/games", headers=owner, json=body))["id"]

    ours = game(mine, 0, 1, f.court, "2031-05-03T15:00:00Z")
    theirs = game(mine, 1, 2, f.court, "2031-05-03T18:00:00Z")  # same league, without the team
    game(other, 0, 1, f.court2, "2031-05-03T15:00:00Z")  # another league
    game(mine, 0, 2, f.court, "2031-09-15T15:00:00Z")  # past WHEN + 90 days
    game(mine, 0, 2, f.court, "2031-01-15T15:00:00Z")  # before WHEN - 90 days
    team = mine["teams"][0]["id"]
    text = _fetch(
        client, _feed(client, owner, kind="team_schedule", name="Team", competition_team_id=team)["url_token"]
    ).text
    assert f"UID:game-{ours}@courtmastr" in text and "LAST-MODIFIED:" in text
    assert theirs not in text and text.count("BEGIN:VEVENT") == 1  # the team's games outside ±90 days are left out


def test_team_feed_needs_a_league_key(client, tenant, owner):
    f = facility(client, owner)
    email, _ = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, email)
    body = {"kind": "team_schedule", "name": "Team", "competition_team_id": "00000000-0000-7000-8000-000000000000"}
    assert client.post(f"{API}/calendar-feeds", headers=desk, json=body).status_code == 403
    assert (
        client.post(f"{API}/calendar-feeds", headers=owner, json=body | {"competition_team_id": None}).status_code
        == 422
    )


def test_the_token_never_reaches_the_access_log(client, owner, caplog):
    token = _feed(client, owner)["url_token"]
    with caplog.at_level(logging.INFO):
        assert _fetch(client, token).status_code == 200
        assert _fetch(client, token + "x").status_code == 404
    paths = [getattr(r, "path", "") for r in caplog.records if r.getMessage() == "request"]
    assert paths and all(token not in p and "[redacted]" in p for p in paths if "/public/" in p)
    server = [r for r in caplog.records if not r.name.startswith("httpx")]  # httpx is the test client's own log
    assert all(token not in r.getMessage() and token not in str(r.__dict__) for r in server)


def test_api_keys_cannot_mint_feeds(client, owner):
    key = client.post(f"{API}/api-keys", headers=owner, json={"name": "K", "scopes": ["clients.client.read"]}).json()
    refused = client.post(
        f"{API}/calendar-feeds", headers={"Authorization": f"Bearer {key['secret']}"},
        json={"kind": "staff_schedule", "name": "X"},
    )  # fmt: skip
    assert refused.status_code == 403


# --- member feeds ------------------------------------------------------------------------------------------


def test_member_feed_shows_enrolled_sessions_and_stops_with_the_identity(client, tenant, owner):
    from app.modules.platform.models import Identity

    f = facility(client, owner)
    client_id, member = _member(client, tenant, owner)
    seat = _session(client, owner, f, title="Coach note", public_title="Kids clinic")["session"]["id"]
    internal = _session(client, owner, f, title="Staff only name", start="2031-05-05T15:00:00Z",
                        end="2031-05-05T16:00:00Z")["session"]["id"]  # fmt: skip
    _session(client, owner, f, title="Not mine", start="2031-05-04T15:00:00Z", end="2031-05-04T16:00:00Z")
    for session_id in (seat, internal):
        ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": session_id, "client_id": client_id}))
    created = ok(client.post(f"{API}/portal/calendar-feeds", headers=member, json={}))
    assert set(created) == {"id", "name", "last_fetched_at", "created_at", "url_token"}  # the portal shape only
    text = _fetch(client, created["url_token"]).text
    assert "SUMMARY:Kids clinic" in text and "SUMMARY:Session" in text and "Not mine" not in text
    assert text.count("LAST-MODIFIED:") == 2
    assert "Coach note" not in text and "Staff only name" not in text  # internal titles never reach a member
    staff_only = client.post(f"{API}/calendar-feeds", headers=member, json={"kind": "staff_schedule", "name": "X"})
    assert staff_only.status_code == 403
    with tenant_session(tenant.id) as session:
        feed = session.get(CalendarFeed, created["id"])
        assert feed.kind == "member_schedule"
        identity = feed.owner_identity_id
        session.get(Identity, identity).status = "disabled"
    assert _fetch(client, created["url_token"]).status_code == 404


def test_a_member_rotates_or_revokes_their_feed(client, tenant, owner):
    _, member = _member(client, tenant, owner)
    first = ok(client.post(f"{API}/portal/calendar-feeds", headers=member, json={}))
    second = ok(client.post(f"{API}/portal/calendar-feeds", headers=member, json={}))
    assert _fetch(client, first["url_token"]).status_code == 404  # a new feed retires the old address
    assert _fetch(client, second["url_token"]).status_code == 200
    with tenant_session(tenant.id) as session:
        assert session.query(CalendarFeed).filter(CalendarFeed.owner_identity_id.is_not(None)).count() == 1
    assert client.delete(f"{API}/portal/calendar-feeds", headers=member).status_code == 204
    assert _fetch(client, second["url_token"]).status_code == 404
    assert client.delete(f"{API}/portal/calendar-feeds", headers=owner).status_code == 403  # members only


def test_staff_and_team_feeds_outlive_a_member_rotating_or_revoking_theirs(client, tenant, owner):
    from app.modules.leagues.tests.test_leagues import league

    f = facility(client, owner)
    f.sport = ok(client.post(f"{API}/sports", headers=owner, json={"name": "Futsal", "default_game_length_min": 60}))
    team = league(client, owner, f, teams=2)["teams"][0]["id"]
    staff = _feed(client, owner)["url_token"]
    squad = _feed(client, owner, kind="team_schedule", name="Team", competition_team_id=team)["url_token"]
    _, member = _member(client, tenant, owner)
    for step in ("create", "rotate", "revoke"):
        if step == "revoke":
            assert client.delete(f"{API}/portal/calendar-feeds", headers=member).status_code == 204
        else:
            ok(client.post(f"{API}/portal/calendar-feeds", headers=member, json={}))
        assert (_fetch(client, staff).status_code, _fetch(client, squad).status_code) == (200, 200), step


def test_a_member_lists_only_their_own_live_feed(client, tenant, owner):
    path = f"{API}/portal/calendar-feeds"
    _, member = _member(client, tenant, owner)
    _, neighbour = _member(client, tenant, owner)
    assert ok(client.get(path, headers=member), 200) == []
    ok(client.post(path, headers=member, json={}))
    mine = ok(client.post(path, headers=member, json={"name": "Family"}))
    ok(client.post(path, headers=neighbour, json={}))
    _feed(client, owner)  # a staff feed is never a member's
    listed = ok(client.get(path, headers=member), 200)
    assert [(row["id"], row["name"]) for row in listed] == [(mine["id"], "Family")]  # the rotated one is gone
    assert "url_token" not in listed[0]
    assert client.delete(path, headers=member).status_code == 204
    assert ok(client.get(path, headers=member), 200) == []
    assert len(ok(client.get(path, headers=neighbour), 200)) == 1
    assert client.get(path, headers=owner).status_code == 403  # members only


def test_the_per_ip_feed_bucket_refuses_once_spent(client, owner, monkeypatch):
    from app.core.settings import get_settings

    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setitem(
        cfg.buckets, "calendar-feed-ip", cfg.buckets["calendar-feed-ip"].model_copy(update={"limit": 2})
    )
    token = _feed(client, owner)["url_token"]
    with clock.freeze(datetime(2031, 5, 2, 9, 30, 5, tzinfo=UTC)):  # one fixed window, no other test's
        codes = [client.get(f"{API}/public/calendar-feeds/{token}").status_code for _ in range(3)]
        unknown = client.get(f"{API}/public/calendar-feeds/fhcal_nothex_x")
    assert codes == [200, 200, 429]
    assert unknown.status_code == 429 and unknown.json()["code"] == "rate-limited"  # counted before the lookup


def test_calendar_app_methods_never_log_the_token(client, owner, caplog):
    token = _feed(client, owner)["url_token"]
    url = f"{API}/public/calendar-feeds/{token}"
    with caplog.at_level(logging.INFO), clock.freeze(WHEN):
        head = client.head(url)
        assert head.status_code == 200 and head.content == b""
        assert head.headers["content-type"].startswith("text/calendar")
        assert client.options(url).status_code == 204
        assert client.request("PROPFIND", url).status_code == 404
        for method in ("POST", "PUT", "DELETE", "PATCH", "REPORT", "PROPPATCH", "MKCALENDAR", "TRACE", "LOCK"):
            refused = client.request(method, url)
            assert refused.status_code == 405 and refused.headers["allow"] == "GET, HEAD, OPTIONS", method
    server = [r for r in caplog.records if not r.name.startswith("httpx")]
    assert server and all(token not in r.getMessage() and token not in str(r.__dict__) for r in server)


def test_a_suspended_tenants_feeds_stop(client, tenant, owner):
    from sqlalchemy import text as sql

    from app.core.db.platform import platform_engine

    token = _feed(client, owner)["url_token"]
    with platform_engine().begin() as conn:
        conn.execute(sql("UPDATE tenant SET status = 'suspended' WHERE id = :id"), {"id": tenant.id})
    try:
        assert _fetch(client, token).status_code == 404
    finally:
        with platform_engine().begin() as conn:
            conn.execute(sql("UPDATE tenant SET status = 'active' WHERE id = :id"), {"id": tenant.id})


def test_ical_stamps_are_stable_and_carry_last_modified():
    changed = datetime(2031, 4, 1, 9, tzinfo=UTC)
    event = ical.Event("u1", WHEN, WHEN, "Clinic", updated_at=changed)
    first, later = (
        ical.calendar("Mine", [event], WHEN),
        ical.calendar("Mine", [event], datetime(2031, 6, 1, tzinfo=UTC)),
    )
    assert first == later and "DTSTAMP:20310401T090000Z" in first and "LAST-MODIFIED:20310401T090000Z" in first


# --- public schedule ---------------------------------------------------------------------------------------


def test_public_schedule_is_off_until_published_and_shows_no_names(client, tenant, owner):
    f = facility(client, owner)
    person = new_client(client, owner, f.location, first_name="Secret", last_name="Person")
    _session(client, owner, f, title="Coach note", public_title="Open clinic")
    _session(client, owner, f, title="Staff only name", start="2031-05-03T19:00:00Z", end="2031-05-03T20:00:00Z")
    _session(client, owner, f, title="Private group", public_title="Unpublished", start="2031-05-03T21:00:00Z",
             end="2031-05-03T22:00:00Z", resource=f.half_b, session={"is_self_bookable": False})  # fmt: skip
    ok(book(client, owner, f, [f.court2], "2031-05-03T17:00:00Z", "2031-05-03T18:00:00Z", title=f"Hire {person['id']}"))
    slug = {"X-Tenant-Slug": tenant.slug}
    url = f"{API}/public/schedule?location_id={f.location}"
    with clock.freeze(datetime(2031, 5, 2, 12, tzinfo=UTC)):
        assert client.get(url, headers=slug).status_code == 404
    settings = f"{API}/public-schedule-settings"
    assert ok(client.get(f"{settings}?location_id={f.location}", headers=owner), 200)["is_enabled"] is False
    ok(
        client.patch(settings, headers=owner, json={"location_id": f.location, "is_enabled": True, "show_busy": True}),
        200,
    )
    with clock.freeze(datetime(2031, 5, 2, 12, tzinfo=UTC)):
        response = client.get(url, headers=slug)
    assert response.status_code == 200, response.text
    body = response.json()
    # Only published sessions, public title or the fixed label; the unpublished one is just a nameless busy block.
    assert [s["title"] for s in body["sessions"]] == ["Open clinic", "Session"]
    assert body["sessions"][0]["seats_left"] == 4
    assert {b["resource_id"] for b in body["busy"]} >= {f.court2, f.half_b}
    for hidden in ("Secret", person["id"], "Coach note", "Staff only name", "Private group", "Unpublished"):
        assert hidden not in response.text
    assert response.headers["cache-control"].startswith("public") and response.headers["vary"] == "X-Tenant-Slug"


def test_public_schedule_follows_the_portal_listing_rule(client, tenant, owner):
    from app.modules.programs.tests.test_selfservice import POLICY

    f = facility(client, owner)
    seat = _session(client, owner, f, public_title="Open clinic", session={"capacity": 1})["session"]["id"]
    settings = {"location_id": f.location, "is_enabled": True}
    ok(client.patch(f"{API}/public-schedule-settings", headers=owner, json=settings), 200)
    slug, url = {"X-Tenant-Slug": tenant.slug}, f"{API}/public/schedule?location_id={f.location}"

    def titles(**policy) -> list[str]:
        put = client.put(f"{API}/locations/{f.location}/session-booking-policy", headers=owner, json=POLICY | policy)
        ok(put, 200)
        with clock.freeze(datetime(2031, 5, 2, 12, tzinfo=UTC)):  # the session starts 27 hours later
            return [s["title"] for s in ok(client.get(url, headers=slug), 200)["sessions"]]

    assert titles() == ["Open clinic"]
    assert titles(listing_mode="hidden") == []
    assert titles(listing_mode="unlisted") == []
    assert titles(visible_range_days=1) == []  # beyond the visible range
    person = new_client(client, owner, f.location)
    ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": seat, "client_id": person["id"]}))
    assert titles() == ["Open clinic"]  # full, shown as full
    assert titles(hides_full_sessions=True) == []


def test_public_busy_times_stay_at_their_location(client, tenant, owner):
    f, other = facility(client, owner), facility(client, owner, "America/Denver")
    ok(book(client, owner, other, [other.court], "2031-05-03T17:00:00Z", "2031-05-03T18:00:00Z", title="Elsewhere"))
    body = {"location_id": f.location, "is_enabled": True, "show_busy": True}
    ok(client.patch(f"{API}/public-schedule-settings", headers=owner, json=body), 200)
    with clock.freeze(datetime(2031, 5, 2, 12, tzinfo=UTC)):
        answer = client.get(f"{API}/public/schedule?location_id={f.location}", headers={"X-Tenant-Slug": tenant.slug})
    assert ok(answer, 200)["busy"] == []


def test_public_schedule_settings_need_their_key(client, tenant, owner):
    f = facility(client, owner)
    email, _ = add_staff(tenant, "front_desk", location_ids=[f.location])
    desk = login(client, tenant, email)
    assert client.get(f"{API}/public-schedule-settings?location_id={f.location}", headers=desk).status_code == 403
