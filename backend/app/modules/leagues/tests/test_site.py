"""Phase 14 chip B2, the public league site: options and facility info, links, gallery, sponsors, news, classes,
public teams, players and brackets, the TV board, and moderated classifieds and pickup games."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import passwords, system_principal
from app.core.db.session import tenant_session
from app.modules import clients
from app.modules.leagues import subject
from app.modules.leagues.models import LeaguePost
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
    photo = ok(client.post(f"{API}/league-photos?caption=Final&album=2031", headers=image, content=png_bytes()))
    hidden_photo = ok(client.post(f"{API}/league-photos", headers=image, content=png_bytes()))
    ok(client.patch(f"{API}/league-photos/{hidden_photo['id']}", headers=owner, json={"is_published": False}), 200)
    gallery = get(client, public, "/public/league-site/photos")
    assert [p["id"] for p in gallery] == [photo["id"]] and gallery[0]["caption"] == "Final"
    shown = client.get(f"{API}/public/league-site/photos/{photo['id']}/image", headers=public)
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/png"
    assert client.get(f"{API}/public/league-site/photos/{hidden_photo['id']}/image", headers=public).status_code == 404
    assert client.post(f"{API}/league-photos", headers=image, content=b"hello").status_code == 422
    ok(client.delete(f"{API}/league-photos/{photo['id']}", headers=owner), 204)
    assert client.get(f"{API}/public/league-site/photos/{photo['id']}/image", headers=public).status_code == 404

    sponsor = post(client, owner, "/league-sponsors", {"name": "Corner Cafe", "url": "https://cafe.example"})
    post(client, owner, "/league-sponsors", {"name": "Old Sponsor", "ends_on": "2020-01-01"})
    ok(client.put(f"{API}/league-sponsors/{sponsor['id']}/logo", headers=image, content=png_bytes()), 200)
    listed = get(client, public, "/public/league-site/sponsors")
    assert [s["name"] for s in listed] == ["Corner Cafe"] and listed[0]["has_logo"]
    assert client.get(f"{API}/public/league-site/sponsors/{sponsor['id']}/logo", headers=public).status_code == 200
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
    assert isinstance(get(client, public, f"/public/competitions/{comp['id']}/player-stats"), list)

    seeds = [t["id"] for t in comp["teams"]]
    ok(client.put(f"{API}/competitions/{comp['id']}/seeding", headers=owner, json={"competition_team_ids": seeds}), 200)
    bracket = post(client, owner, f"/competitions/{comp['id']}/brackets",
                   {"bracket_type": "single_elimination", "seed_source": "seeds"})  # fmt: skip
    assert get(client, public, f"/public/competitions/{comp['id']}/brackets") == []  # draft stays hidden
    post(client, owner, f"/brackets/{bracket['id']}/publish", {}, 200)
    shown = get(client, public, f"/public/competitions/{comp['id']}/brackets")
    assert len(shown) == 1 and shown[0]["slots"]
    assert not {"game_id", "home_team_id", "winner_competition_team_id"} & set(shown[0]["slots"][0])


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
    with clock.freeze(DAY + timedelta(hours=20)):  # 15:00 on 5 May in Chicago
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
    assert own.status_code in (404, 409)
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
    clinic = post(
        client, owner, "/program-groups", {"location_id": f.location, "name": "Junior clinic", "kind": "clinic"}
    )
    post(client, owner, "/program-groups", {"location_id": f.location, "name": "Unpublished camp", "kind": "camp"})
    ok(client.put(f"{API}/program-groups/{clinic['id']}/registration-config", headers=owner,
                  json={"is_enabled": True, "payment_requirement": "pay_later_allowed"}), 200)  # fmt: skip
    ok(client.post(f"{API}/program-groups/{clinic['id']}/publish", headers=owner), 200)
    listed = get(client, public, "/public/league-site/classes")
    assert [(c["name"], c["kind"], c["is_open"]) for c in listed] == [("Junior clinic", "clinic", True)]
    _enable(client, owner, shows_classes=False)
    assert client.get(f"{API}/public/league-site/classes", headers=public).status_code == 404
