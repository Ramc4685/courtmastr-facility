"""Phase 14 chip B2, the public league site: options and facility info, links, gallery, sponsors, news, classes,
public teams, players and brackets, the TV board, and moderated classifieds and pickup games."""

import threading
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import passwords, system_principal
from app.core.db.session import tenant_session
from app.modules import clients
from app.modules.leagues import site, subject
from app.modules.leagues.models import BracketSlot, Game, LeaguePost, LeagueSite
from app.modules.leagues.tests.test_leagues import get, league, post, score, staff
from app.modules.platform.models import Identity
from app.modules.scheduling.tests.helpers import API, DAY, at, facility, ok
from conftest import PASSWORD, add_staff, login, new_client, png_bytes

SITE = {"is_enabled": True, "title": "Club leagues", "accent_color": "#1a7f5a", "shows_classifieds": True,
        "shows_pickup_games": True}  # fmt: skip


def _public(tenant) -> dict:
    return {"X-Tenant-Slug": tenant.slug}


def _enable(client, owner, **extra) -> dict:
    return ok(client.put(f"{API}/league-site", headers=owner, json=SITE | extra), 200)


def _portal(client, tenant, owner, location) -> tuple[dict, dict]:
    email = f"site-{uuid4().hex[:8]}@example.com"
    person = new_client(client, owner, location, primary_email=email)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(kind="client", email=email, status="active", email_verified_at=clock.now(),
                            password_hash=passwords.hash_password(PASSWORD))  # fmt: skip
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, UUID(person["id"]), identity.id)
    return person, login(client, tenant, email, audience="client")


def test_site_options_gate_every_section(client, owner, tenant, f):
    public = _public(tenant)
    assert get(client, owner, "/league-site")["is_enabled"] is False  # defaults before the first save
    assert client.get(f"{API}/public/league-site", headers=public).status_code == 404
    saved = _enable(client, owner, shows_links=False)
    assert saved["title"] == "Club leagues" and saved["board_refresh_sec"] == 60
    shown = get(client, public, "/public/league-site")
    assert any(x["id"] == f.location and x["name"] for x in shown["facilities"])
    post(client, owner, "/league-links", {"title": "Rules", "url": "https://example.com/rules"})
    assert client.get(f"{API}/public/league-site/links", headers=public).status_code == 404  # section off
    _enable(client, owner)
    assert [x["title"] for x in get(client, public, "/public/league-site/links")] == ["Rules"]
    bad = client.put(f"{API}/league-site", headers=owner, json=SITE | {"accent_color": "red"})
    assert bad.status_code == 422
    # tenant-wide: a manager limited to one location may not change the site
    manager = staff(client, tenant, "manager", f)
    assert client.put(f"{API}/league-site", headers=manager, json=SITE).status_code == 403
    with tenant_session(tenant.id) as session:
        actions = session.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "league_site")).all()
    assert actions.count("leagues.public_site.manage") == 2


def test_links_news_photos_and_sponsors(client, owner, tenant, f):
    public = _public(tenant)
    _enable(client, owner)
    link = post(client, owner, "/league-links", {"title": "Old", "url": "https://example.com"})
    assert (
        ok(client.patch(f"{API}/league-links/{link['id']}", headers=owner, json={"title": "New"}), 200)["title"]
        == "New"
    )
    assert client.post(f"{API}/league-links", headers=owner, json={"title": "X", "url": "ftp://x"}).status_code == 422
    ok(client.delete(f"{API}/league-links/{link['id']}", headers=owner), 204)

    draft = post(client, owner, "/league-news", {"title": "Draft", "body": "Not yet."})
    live = post(client, owner, "/league-news", {"title": "Opening night", "body": "Games start.",
                                                "published_at": "2020-01-01T00:00:00Z", "is_pinned": True})  # fmt: skip
    later = post(
        client, owner, "/league-news", {"title": "Later", "body": "Soon.", "published_at": "2099-01-01T00:00:00Z"}
    )
    assert [s["title"] for s in get(client, public, "/public/league-site/news")] == ["Opening night"]
    for hidden in (draft, later):
        assert client.get(f"{API}/public/league-site/news/{hidden['id']}", headers=public).status_code == 404
    assert get(client, public, f"/public/league-site/news/{live['id']}")["body"] == "Games start."
    assert len(get(client, owner, "/league-news")["data"]) == 3

    image = owner | {"Content-Type": "image/png"}
    card = client.post(f"{API}/league-photos?caption=4111 1111 1111 1111", headers=image, content=png_bytes())
    assert (card.status_code, card.json()["code"]) == (422, "card-data-not-allowed")  # query text is stored too
    assert card.json()["errors"][0]["pointer"] == "/caption"
    photo = ok(client.post(f"{API}/league-photos?caption=Final&album=2031", headers=image, content=png_bytes()))
    hidden_photo = ok(client.post(f"{API}/league-photos", headers=image, content=png_bytes()))
    ok(client.patch(f"{API}/league-photos/{hidden_photo['id']}", headers=owner, json={"is_published": False}), 200)
    gallery = get(client, public, "/public/league-site/photos")
    assert [p["id"] for p in gallery] == [photo["id"]] and gallery[0]["caption"] == "Final"
    shown = client.get(f"{API}/public/league-site/photos/{photo['id']}/image", headers=public)
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/png"
    assert client.get(f"{API}/public/league-site/photos/{hidden_photo['id']}/image", headers=public).status_code == 404
    assert client.post(f"{API}/league-photos", headers=image, content=b"hello").status_code == 422
    _enable(client, owner, shows_gallery=False)  # a section switched off hides its files by id too
    assert client.get(f"{API}/public/league-site/photos/{photo['id']}/image", headers=public).status_code == 404
    _enable(client, owner)
    ok(client.delete(f"{API}/league-photos/{photo['id']}", headers=owner), 204)
    assert client.get(f"{API}/public/league-site/photos/{photo['id']}/image", headers=public).status_code == 404

    sponsor = post(client, owner, "/league-sponsors", {"name": "Corner Cafe", "url": "https://cafe.example"})
    post(client, owner, "/league-sponsors", {"name": "Old Sponsor", "ends_on": "2020-01-01"})
    ok(client.put(f"{API}/league-sponsors/{sponsor['id']}/logo", headers=image, content=png_bytes()), 200)
    listed = get(client, public, "/public/league-site/sponsors")
    assert [s["name"] for s in listed] == ["Corner Cafe"] and listed[0]["has_logo"]
    assert client.get(f"{API}/public/league-site/sponsors/{sponsor['id']}/logo", headers=public).status_code == 200
    _enable(client, owner, shows_sponsors=False)
    assert client.get(f"{API}/public/league-site/sponsors/{sponsor['id']}/logo", headers=public).status_code == 404
    _enable(client, owner)
    backwards = client.patch(f"{API}/league-sponsors/{sponsor['id']}", headers=owner,
                             json={"starts_on": "2031-02-01", "ends_on": "2031-01-01"})  # fmt: skip
    assert backwards.status_code == 422
    ok(client.delete(f"{API}/league-sponsors/{sponsor['id']}", headers=owner), 204)
    assert client.get(f"{API}/public/league-site/sponsors/{sponsor['id']}/logo", headers=public).status_code == 404


def test_public_teams_players_stats_and_brackets(client, owner, tenant, f):
    public = _public(tenant)
    comp = league(client, owner, f, kind="tournament", format="single_elimination", teams=3)
    post(client, owner, f"/competition-teams/{comp['teams'][0]['id']}/roster", {"client_id": f.person})
    teams = get(client, public, f"/public/competitions/{comp['id']}/teams")
    assert len(teams) == 3 and all(t["players"] is None for t in teams)  # default off: many players are minors
    assert client.get(f"{API}/public/competitions/{comp['id']}/player-stats", headers=public).status_code == 404
    ok(client.patch(f"{API}/competitions/{comp['id']}", headers=owner, json={"show_players": True}), 200)
    named = get(client, public, f"/public/competitions/{comp['id']}/teams")
    assert any(t["players"] for t in named)
    table = post(client, owner, f"/sports/{f.sport['id']}/stat-tables", {"name": "Scoring"})
    goals = post(client, owner, f"/stat-tables/{table['id']}/stats", {"code": "G", "name": "Goals"})
    ana = post(client, owner, f"/competition-teams/{comp['teams'][0]['id']}/roster",
               {"first_name": "Ana", "last_name": "Goal"})  # fmt: skip
    game = post(client, owner, "/games", {"competition_id": comp["id"], "home_team_id": comp["teams"][0]["id"],
                                          "away_team_id": comp["teams"][1]["id"], "resource_id": f.court,
                                          "starts_at": at(18)})  # fmt: skip
    ok(client.put(f"{API}/games/{game['id']}/player-stats", headers=owner, json={"stats": [
        {"roster_entry_id": ana["id"], "stat_definition_id": goals["id"], "value": "2"}]}), 200)  # fmt: skip
    (row,) = get(client, public, f"/public/competitions/{comp['id']}/player-stats")
    assert row["player_name"] == "Ana Goal" and row["team_name"] == comp["teams"][0]["name"]
    assert float(row["stats"]["G"]) == 2
    ok(client.delete(f"{API}/roster-entries/{ana['id']}", headers=owner), 204)
    assert get(client, public, f"/public/competitions/{comp['id']}/player-stats") == []  # removed: no longer named
    assert get(client, owner, f"/competitions/{comp['id']}/player-stats")  # staff keep the history
    bea = post(client, owner, f"/competition-teams/{comp['teams'][1]['id']}/roster",
               {"first_name": "Bea", "last_name": "Away"})  # fmt: skip
    ok(client.put(f"{API}/games/{game['id']}/player-stats", headers=owner, json={"stats": [
        {"roster_entry_id": bea["id"], "stat_definition_id": goals["id"], "value": "1"}]}), 200)  # fmt: skip
    assert [r["player_name"] for r in get(client, public, f"/public/competitions/{comp['id']}/player-stats")] == [
        "Bea Away"]  # fmt: skip
    ok(client.patch(f"{API}/competition-teams/{comp['teams'][1]['id']}", headers=owner, json={"status": "withdrawn"}),
       200)  # fmt: skip
    assert get(client, public, f"/public/competitions/{comp['id']}/player-stats") == []  # a withdrawn team's too

    seeds = [t["id"] for t in comp["teams"]]
    ok(client.put(f"{API}/competitions/{comp['id']}/seeding", headers=owner, json={"competition_team_ids": seeds}), 200)
    bracket = post(client, owner, f"/competitions/{comp['id']}/brackets",
                   {"bracket_type": "single_elimination", "seed_source": "seeds"})  # fmt: skip
    assert get(client, public, f"/public/competitions/{comp['id']}/brackets") == []  # draft stays hidden
    post(client, owner, f"/brackets/{bracket['id']}/publish", {}, 200)
    shown = get(client, public, f"/public/competitions/{comp['id']}/brackets")
    assert len(shown) == 1 and shown[0]["slots"]
    assert not {"game_id", "home_team_id", "winner_competition_team_id"} & set(shown[0]["slots"][0])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        slot = session.scalar(select(BracketSlot).where(BracketSlot.game_id.is_not(None)).limit(1))
        session.get(Game, slot.game_id).status = "proposed"  # not on the public schedule
        session.get(Game, slot.game_id).starts_at = DAY
        where = (slot.round_no, slot.position)
    again = get(client, public, f"/public/competitions/{comp['id']}/brackets")[0]["slots"]
    assert next(x for x in again if (x["round_no"], x["position"]) == where)["starts_at"] is None


def test_competition_filters(client, owner, tenant, f):
    public = _public(tenant)
    soccer = post(client, owner, "/sports", {"name": "Soccer", "default_game_length_min": 90})
    league(client, owner, f, name="Futsal Nights")
    league(client, owner, f, name="Spring Soccer", sport_id=soccer["id"])
    by_sport = get(client, public, f"/public/competitions?sport_id={soccer['id']}")
    assert [c["name"] for c in by_sport] == ["Spring Soccer"]
    assert [c["name"] for c in get(client, public, "/public/competitions?q=nights")] == ["Futsal Nights"]
    assert get(client, public, "/public/competitions?kind=tournament") == []
    assert client.get(f"{API}/public/competitions?kind=other", headers=public).status_code == 422


def test_tv_board_shows_todays_public_games_at_one_location(client, owner, tenant, f):
    comp = league(client, owner, f, teams=2)
    body = {
        "competition_id": comp["id"],
        "home_team_id": comp["teams"][0]["id"],
        "away_team_id": comp["teams"][1]["id"],
    }
    today = post(client, owner, "/games", body | {"resource_id": f.court, "starts_at": at(18)})  # 13:00 in Chicago
    post(client, owner, "/games", body | {"resource_id": f.court, "starts_at": at(30)})  # tomorrow, local
    ok(client.put(f"{API}/games/{today['id']}/result", headers=owner, json=score(3, 1)), 200)
    with clock.freeze(DAY + timedelta(hours=27)):  # 03:00 UTC on 6 May, still 22:00 on 5 May in Chicago
        board = get(client, _public(tenant), f"/public/locations/{f.location}/league-board")
    assert board["on_date"] == "2031-05-05" and board["refresh_sec"] == 60
    assert [(g["competition_name"], g["home_score"]) for g in board["games"]] == [("Wednesday Futsal", 3)]
    assert client.get(f"{API}/public/locations/{uuid4()}/league-board", headers=_public(tenant)).status_code == 404


def test_posts_are_moderated_expire_and_relay_contact(client, owner, tenant, f, mailbox):
    public = _public(tenant)
    _enable(client, owner)
    poster, portal = _portal(client, tenant, owner, f.location)
    _, other = _portal(client, tenant, owner, f.location)
    classified = post(client, portal, "/portal/league-posts", {
        "kind": "classified", "location_id": f.location, "category": "player_wanted", "sport_id": f.sport["id"],
        "title": "Keeper wanted", "body": "Our Sunday side needs a keeper.",
    })  # fmt: skip
    assert classified["status"] == "pending"
    no_time = client.post(f"{API}/portal/league-posts", headers=portal,
                          json={"kind": "pickup", "location_id": f.location, "title": "Pickup", "body": "Anyone free?"})  # fmt: skip
    assert no_time.status_code == 422
    future = (clock.now() + timedelta(days=2)).isoformat()
    pickup = post(client, portal, "/portal/league-posts", {"kind": "pickup", "location_id": f.location,
                                                           "title": "Pickup futsal", "body": "Need four more.",
                                                           "starts_at": future, "players_needed": 4})  # fmt: skip
    assert get(client, public, "/public/league-site/posts?kind=classified") == []  # not yet approved

    queue = get(client, owner, "/league-posts?status=pending")["data"]
    assert {p["id"] for p in queue} >= {classified["id"], pickup["id"]} and queue[0]["client_name"]
    assert post(client, owner, f"/league-posts/{classified['id']}/approve", {}, 200)["status"] == "approved"
    again = client.post(f"{API}/league-posts/{classified['id']}/approve", headers=owner, json={})
    assert again.status_code == 409 and again.json()["code"] == "post-not-pending"
    post(client, owner, f"/league-posts/{pickup['id']}/reject", {"reason": "Duplicate"}, 200)
    shown = get(client, public, "/public/league-site/posts?kind=classified")
    assert [p["title"] for p in shown] == ["Keeper wanted"]
    assert not {"client_id", "client_name", "email", "status"} & set(shown[0])
    assert get(client, public, "/public/league-site/posts?kind=pickup") == []

    mailbox.clear()
    ok(client.post(f"{API}/portal/league-posts/{classified['id']}/contact", headers=other,
                   json={"message": "I can play in goal on Sundays."}), 204)  # fmt: skip
    assert mailbox[-1].to == poster["primary_email"] and "I can play in goal" in mailbox[-1].body
    own = client.post(
        f"{API}/portal/league-posts/{classified['id']}/contact", headers=portal, json={"message": "Me, myself."}
    )
    assert own.status_code == 404
    assert {p["status"] for p in get(client, portal, "/portal/league-posts")} == {"approved", "rejected"}

    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        row = session.get(LeaguePost, UUID(classified["id"]))
        assert row.expires_at - row.created_at >= timedelta(days=30)
        row.expires_at = clock.now() - timedelta(minutes=1)  # age it; freezing the clock would end the session
    assert get(client, public, "/public/league-site/posts?kind=classified") == []
    assert "expired" in {p["status"] for p in get(client, portal, "/portal/league-posts")}
    ok(client.post(f"{API}/portal/league-posts/{classified['id']}/withdraw", headers=portal, json={}), 204)
    assert get(client, public, "/public/league-site/posts?kind=classified") == []


def test_post_limit_scope_and_erasure(client, owner, tenant, f):
    _enable(client, owner)
    poster, portal = _portal(client, tenant, owner, f.location)
    body = {"kind": "classified", "location_id": f.location, "title": "Team wanted", "body": "Looking for a team."}
    ids = [post(client, portal, "/portal/league-posts", body)["id"] for _ in range(5)]
    over = client.post(f"{API}/portal/league-posts", headers=portal, json=body)
    assert over.status_code == 409 and over.json()["code"] == "post-limit"
    other = facility(client, owner, "America/New_York")
    email, _ = add_staff(tenant, "manager", location_ids=[other.location])
    elsewhere = login(client, tenant, email)
    assert client.post(f"{API}/league-posts/{ids[0]}/approve", headers=elsewhere, json={}).status_code == 404
    assert get(client, elsewhere, "/league-posts")["data"] == []
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert subject._erase(session, UUID(poster["id"]))["deleted_league_posts"] == 5
        assert session.scalar(select(LeaguePost).where(LeaguePost.client_id == UUID(poster["id"]))) is None


def test_classes_come_from_portal_published_programs(client, owner, tenant, f):
    public = _public(tenant)
    _enable(client, owner)
    clinic = post(client, owner, "/program-groups", {"location_id": f.location, "name": "Junior clinic",
                                                    "kind": "clinic", "ends_on": "2031-05-05"})  # fmt: skip
    post(client, owner, "/program-groups", {"location_id": f.location, "name": "Unpublished camp", "kind": "camp"})
    closed = post(client, owner, "/program-groups", {"location_id": f.location, "name": "Closed camp", "kind": "camp",
                                                     "description": "Staff notes", "price_minor": 5000})  # fmt: skip
    ok(client.put(f"{API}/program-groups/{closed['id']}/registration-config", headers=owner,
                  json={"is_enabled": True, "payment_requirement": "pay_later_allowed"}), 200)  # fmt: skip
    ok(client.post(f"{API}/program-groups/{closed['id']}/publish", headers=owner), 200)
    ok(
        client.put(
            f"{API}/program-groups/{closed['id']}/registration-config",
            headers=owner,
            json={"is_enabled": False, "payment_requirement": "pay_later_allowed"},
        ),
        200,
    )  # online sign-up off
    ok(client.put(f"{API}/program-groups/{clinic['id']}/registration-config", headers=owner,
                  json={"is_enabled": True, "payment_requirement": "pay_later_allowed"}), 200)  # fmt: skip
    ok(client.post(f"{API}/program-groups/{clinic['id']}/publish", headers=owner), 200)
    listed = get(client, public, "/public/league-site/classes")
    assert [(c["name"], c["kind"], c["is_open"]) for c in listed] == [("Junior clinic", "clinic", True)]
    assert "price_minor" not in listed[0] and listed[0]["description"] is None  # staff description stays private
    with clock.freeze(DAY + timedelta(hours=27)):  # 6 May in UTC, still the last day in Chicago
        assert [c["name"] for c in get(client, public, "/public/league-site/classes")] == ["Junior clinic"]
    with clock.freeze(DAY + timedelta(hours=30)):  # 01:00 on 6 May in Chicago: over
        assert get(client, public, "/public/league-site/classes") == []
    _enable(client, owner, shows_classes=False)
    assert client.get(f"{API}/public/league-site/classes", headers=public).status_code == 404


def test_post_rules_expiry_time_zone_and_switches(client, owner, tenant, f):
    _enable(client, owner)
    _, portal = _portal(client, tenant, owner, f.location)
    starts = clock.now().replace(microsecond=0) + timedelta(days=2)
    pickup = {"kind": "pickup", "location_id": f.location, "title": "Pickup futsal", "body": "Need four more."}
    naive = client.post(f"{API}/portal/league-posts", headers=portal,
                        json=pickup | {"starts_at": starts.replace(tzinfo=None).isoformat()})  # fmt: skip
    assert naive.status_code == 422
    game = post(client, portal, "/portal/league-posts", pickup | {"starts_at": starts.isoformat()})
    assert datetime.fromisoformat(game["expires_at"]) == starts  # a game comes down once it starts

    classified = {
        "kind": "classified",
        "location_id": f.location,
        "title": "Team wanted",
        "body": "Looking for a team.",
    }
    stale = post(client, portal, "/portal/league-posts", classified)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.get(LeaguePost, UUID(stale["id"])).expires_at = clock.now() - timedelta(minutes=1)
    late = client.post(f"{API}/league-posts/{stale['id']}/approve", headers=owner, json={})
    assert late.status_code == 409 and late.json()["code"] == "post-expired"

    live = post(client, portal, "/portal/league-posts", classified)
    post(client, owner, f"/league-posts/{live['id']}/approve", {}, 200)
    _, other = _portal(client, tenant, owner, f.location)
    _enable(client, owner, shows_classifieds=False)
    assert client.post(f"{API}/portal/league-posts", headers=portal, json=classified).status_code == 404
    contact = client.post(
        f"{API}/portal/league-posts/{live['id']}/contact", headers=other, json={"message": "Is the spot still open?"}
    )
    assert contact.status_code == 404
    post(client, portal, "/portal/league-posts", pickup | {"starts_at": starts.isoformat()})  # its own switch is on


def test_post_limit_holds_under_parallel_submissions(client, owner, tenant, f):
    _enable(client, owner)
    poster, portal = _portal(client, tenant, owner, f.location)
    body = {"kind": "classified", "location_id": f.location, "title": "Team wanted", "body": "Looking for a team."}
    ids = [post(client, portal, "/portal/league-posts", body)["id"] for _ in range(5)]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.get(LeaguePost, UUID(ids[0])).status = "withdrawn"  # four live
    result: dict = {}
    racer = threading.Thread(target=lambda: result.update(r=client.post(f"{API}/portal/league-posts", headers=portal,
                                                                        json=body)))  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        site._xact_lock(
            session, f"league-post:{poster['id']}"
        )  # a parallel submission, mid-way through adding the fifth
        session.get(LeaguePost, UUID(ids[0])).status = "pending"
        session.flush()
        racer.start()
        racer.join(timeout=1.5)
        assert racer.is_alive()  # waits for the lock instead of counting four
    racer.join(timeout=15)
    assert result["r"].status_code == 409 and result["r"].json()["code"] == "post-limit"


def test_first_site_save_waits_instead_of_colliding(client, owner, tenant, f):
    result: dict = {}
    racer = threading.Thread(target=lambda: result.update(r=client.put(f"{API}/league-site", headers=owner, json=SITE)))
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        site._xact_lock(session, "league-site")  # a parallel first save, mid-way through its insert
        session.add(LeagueSite(**SITE | {"title": "First"}))
        session.flush()
        racer.start()
        racer.join(timeout=1.5)
        assert racer.is_alive()
    racer.join(timeout=15)
    assert result["r"].status_code == 200 and result["r"].json()["title"] == SITE["title"]
