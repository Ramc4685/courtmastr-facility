"""leagues through the API on real PostgreSQL: tenant-wide reference data, team fees billed through billing,
team generation and copy, rosters, the schedule generator booking courts through scheduling (a clash leaves a
game unschedulable), the game lifecycle, results and standings, officials, brackets, the public views and the
security rules (location scope, scoped body ids, separate keys for results, amendments and adjustments)."""

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.core.auth import Principal, system_principal
from app.core.db.session import tenant_session
from app.core.errors import NotFound, PermissionDenied
from app.modules.leagues import service
from app.modules.scheduling.tests.helpers import API, at, book, drain, facility, ok
from conftest import add_staff, login, new_client

WINDOW = {"weekday": 3, "starts_at": "18:00", "ends_at": "22:00"}  # Wednesdays, location-local


def post(client, headers, path, body, status=201):
    return ok(client.post(f"{API}{path}", headers=headers, json=body), status)


def get(client, headers, path):
    return ok(client.get(f"{API}{path}", headers=headers), 200)


def league(client, owner, f, *, activate=True, teams=0, **extra) -> dict:
    body = {
        "location_id": f.location, "kind": "league", "name": "Wednesday Futsal", "sport_id": f.sport["id"],
        "starts_on": "2031-05-01", "ends_on": "2031-06-30",
    } | extra  # fmt: skip
    row = post(client, owner, "/competitions", body)
    if activate:
        row = post(client, owner, f"/competitions/{row['id']}/activate", {}, 200)
    if teams:
        row["teams"] = post(client, owner, f"/competitions/{row['id']}/teams/generate", {"count": teams})
    return row


def run_body(f, competition_ids, **extra) -> dict:
    return {
        "location_id": f.location, "competition_ids": competition_ids, "resource_ids": [f.court],
        "time_slots": [WINDOW | {"resource_id": f.court}], "starts_on": "2031-05-05", "ends_on": "2031-06-30",
    } | extra  # fmt: skip


def generate(client, owner, run_id) -> dict:
    """Start the generator job (LGE-08), run it to the end, and return the run."""
    assert post(client, owner, f"/schedule-runs/{run_id}/generate", {}, 200)["state"] == "generating"
    drain()
    return get(client, owner, f"/schedule-runs/{run_id}")


def scheduled(client, owner, f, competition_id) -> list[dict]:
    run = post(client, owner, "/schedule-runs", run_body(f, [competition_id]))
    generate(client, owner, run["id"])
    post(client, owner, f"/schedule-runs/{run['id']}/commit", {}, 200)
    return get(client, owner, f"/schedule-runs/{run['id']}/games?status=scheduled")["data"]


def score(home, away) -> dict:
    return {"home": {"score": home}, "away": {"score": away}}


def staff(client, tenant, role, f) -> dict:
    email, _ = add_staff(tenant, role, location_ids=[f.location])
    return login(client, tenant, email)


def test_reference_data_is_tenant_wide_and_guarded(client, owner, tenant, f):
    manager = staff(client, tenant, "manager", f)
    assert client.post(f"{API}/sports", headers=manager, json={"name": "Hockey"}).status_code == 403
    assert client.post(f"{API}/sports", headers=owner, json={"name": "Futsal"}).status_code == 409
    season = post(client, owner, "/seasons", {"name": "Spring", "starts_on": "2031-04-01", "ends_on": "2031-06-30"})
    bad = client.post(
        f"{API}/seasons", headers=owner, json={"name": "X", "starts_on": "2031-06-01", "ends_on": "2031-01-01"}
    )
    assert bad.status_code == 422
    league(client, owner, f, season_id=season["id"])
    assert client.delete(f"{API}/sports/{f.sport['id']}", headers=owner).json()["code"] == "in-use"
    assert client.delete(f"{API}/seasons/{season['id']}", headers=owner).status_code == 409
    assert get(client, manager, "/sports")["data"][0]["name"] == "Futsal"  # managers read reference data


def test_competition_rules_and_lifecycle(client, owner, f):
    bad = client.post(f"{API}/competitions", headers=owner, json={
        "location_id": f.location, "kind": "league", "format": "single_elimination", "name": "X",
        "sport_id": f.sport["id"], "starts_on": "2031-05-01",
    })  # fmt: skip
    assert bad.status_code == 422
    row = league(client, owner, f, activate=False)
    assert row["status"] == "draft"
    divisions = get(client, owner, f"/competitions/{row['id']}/divisions")
    assert [d["name"] for d in divisions] == ["Main"]
    post(client, owner, f"/competitions/{row['id']}/activate", {}, 200)
    assert client.post(f"{API}/competitions/{row['id']}/activate", headers=owner, json={}).status_code == 409
    assert post(client, owner, f"/competitions/{row['id']}/complete", {}, 200)["status"] == "completed"
    assert post(client, owner, f"/competitions/{row['id']}/reopen", {}, 200)["status"] == "active"


def test_team_fee_is_billed_once_through_billing(client, owner, f):
    paid = league(client, owner, f, team_fee_minor=30000, revenue_category_id=f.category)
    entry = post(client, owner, f"/competitions/{paid['id']}/teams",
                 {"team": {"name": "Strikers", "captain_client_id": f.person}, "bill_to_client_id": f.person})  # fmt: skip
    assert entry["fee_status"] == "billed" and entry["fee_client_id"] == f.person
    invoice = get(client, owner, f"/invoices/{entry['invoice_id']}")
    assert invoice["total_minor"] == 30000
    again = client.post(
        f"{API}/competition-teams/{entry['id']}/bill", headers=owner, json={"bill_to_client_id": f.person}
    )
    assert again.status_code == 409 and again.json()["code"] == "fee-not-due"
    later = post(client, owner, f"/competitions/{paid['id']}/teams", {"team": {"name": "Rovers"}})
    assert later["fee_status"] == "unbilled"
    post(client, owner, f"/competition-teams/{later['id']}/roster", {"client_id": f.person})  # a rostered payer
    billed = post(client, owner, f"/competition-teams/{later['id']}/bill", {"bill_to_client_id": f.person}, 200)
    assert billed["fee_status"] == "billed" and billed["invoice_id"]
    free = league(client, owner, f, name="Free league")
    no_fee = client.post(f"{API}/competitions/{free['id']}/teams", headers=owner,
                         json={"team": {"name": "X"}, "bill_to_client_id": f.person})  # fmt: skip
    assert no_fee.status_code == 422
    assert post(client, owner, f"/competitions/{free['id']}/teams", {"team": {"name": "Y"}})["fee_status"] == "none"


def test_generate_copy_and_seeding(client, owner, f):
    first = league(client, owner, f, teams=4)
    teams = first["teams"]
    assert [t["name"] for t in teams] == ["Team 1", "Team 2", "Team 3", "Team 4"]
    post(client, owner, f"/competition-teams/{teams[0]['id']}/roster", {"first_name": "Pat", "last_name": "Lee"})
    second = league(client, owner, f, name="Summer Futsal")
    copied = post(client, owner, f"/competitions/{second['id']}/teams/copy",
                  {"source_competition_id": first["id"], "includes_rosters": True})  # fmt: skip
    assert sorted(c["team_id"] for c in copied) == sorted(t["team_id"] for t in teams)
    copy_of_first = next(c for c in copied if c["team_id"] == teams[0]["team_id"])
    assert [r["name"] for r in get(client, owner, f"/competition-teams/{copy_of_first['id']}/roster")] == ["Pat Lee"]
    same = client.post(f"{API}/competitions/{first['id']}/teams/copy", headers=owner,
                       json={"source_competition_id": first["id"]})  # fmt: skip
    assert same.status_code == 422
    order = [t["id"] for t in reversed(teams)]
    seeded = ok(client.put(f"{API}/competitions/{first['id']}/seeding", headers=owner,
                           json={"competition_team_ids": order}), 200)  # fmt: skip
    assert [(s["id"], s["seed"]) for s in seeded] == [(i, n) for n, i in enumerate(order, start=1)]
    twice = client.put(f"{API}/competitions/{first['id']}/seeding", headers=owner,
                       json={"competition_team_ids": [order[0], order[0]]})  # fmt: skip
    assert twice.status_code == 422


def test_roster_places(client, owner, tenant, f):
    entry = league(client, owner, f, teams=1)["teams"][0]
    path = f"/competition-teams/{entry['id']}/roster"
    captain = post(client, owner, path, {"client_id": f.person, "role": "captain", "jersey_number": "9"})
    assert captain["role"] == "captain" and captain["origin"] == "manual"
    assert client.post(f"{API}{path}", headers=owner, json={"client_id": f.person}).status_code == 409
    assert client.post(f"{API}{path}", headers=owner, json={"first_name": "Solo"}).status_code == 422
    desk = staff(client, tenant, "front_desk", f)
    walk_in = post(client, desk, path, {"first_name": "Walk", "last_name": "In"})
    assert client.delete(f"{API}/roster-entries/{walk_in['id']}", headers=desk).status_code == 204
    assert {r["name"]: r["status"] for r in get(client, owner, path)}["Walk In"] == "removed"
    found = get(client, owner, f"/roster-entries?client_id={f.person}")["data"]
    assert [r["id"] for r in found] == [captain["id"]]


def test_schedule_generator_books_courts_and_reports_clashes(client, owner, f):
    comp = league(client, owner, f, teams=4)
    run = post(client, owner, "/schedule-runs", run_body(f, [comp["id"]], blackout_dates=["2031-05-07"]))
    assert client.post(f"{API}/schedule-runs/{run['id']}/commit", headers=owner, json={}).status_code == 409
    preview = generate(client, owner, run["id"])
    assert preview["state"] == "previewed" and preview["stats"]["games"] == 6
    assert preview["progress"] == {"done": 1, "total": 1}
    games = get(client, owner, f"/schedule-runs/{run['id']}/games")["data"]
    assert {g["status"] for g in games} == {"proposed"} and all(g["booking_id"] is None for g in games)
    assert all(not g["starts_at"].startswith("2031-05-07") for g in games)  # the blackout date is skipped
    first = min(games, key=lambda g: g["starts_at"])
    ok(book(client, owner, f, [f.court], first["starts_at"], first["ends_at"]))  # someone takes that court first
    committed = post(client, owner, f"/schedule-runs/{run['id']}/commit", {}, 200)
    assert committed["state"] == "committed" and committed["stats"]["booked"] == 5
    after = {g["id"]: g for g in get(client, owner, f"/schedule-runs/{run['id']}/games")["data"]}
    assert after[first["id"]]["status"] == "unschedulable"
    assert after[first["id"]]["conflict_note"]["reason"] == "booking-conflict"
    assert "is already held by booking #" in after[first["id"]]["conflict_note"]["detail"]  # staff see what was in the way
    booked = [g for g in after.values() if g["status"] == "scheduled"]
    assert len(booked) == 5 and all(g["booking_id"] for g in booked)
    clash = book(client, owner, f, [f.court], booked[0]["starts_at"], booked[0]["ends_at"])
    assert clash.status_code == 409  # the game's hold is a real scheduling hold


def test_game_lifecycle(client, owner, f):
    comp = league(client, owner, f, teams=2)
    home, away = (t["id"] for t in comp["teams"])
    body = {"competition_id": comp["id"], "home_team_id": home, "away_team_id": away}
    game = post(client, owner, "/games", body | {"resource_id": f.court, "starts_at": at(1)})
    assert game["status"] == "scheduled" and game["booking_id"]
    clash = client.post(f"{API}/games", headers=owner, json=body | {"resource_id": f.half_a, "starts_at": at(1.5)})
    assert clash.status_code == 409 and clash.json()["code"] == "booking-conflict"
    itself = client.post(f"{API}/games", headers=owner, json=body | {"away_team_id": home})
    assert itself.status_code == 422
    waiting = post(client, owner, "/games", body | {"home_label": "TBD"} | {"home_team_id": None})
    assert waiting["status"] == "proposed" and waiting["booking_id"] is None
    stale = client.patch(f"{API}/games/{game['id']}", headers=owner, json={"notes": "x", "version": 0})
    assert stale.status_code == 409 and stale.json()["code"] == "version-mismatch"
    moved = post(client, owner, f"/games/{game['id']}/reschedule", {"resource_id": f.court2, "starts_at": at(3)}, 200)
    assert moved["resource_id"] == f.court2 and moved["booking_id"] == game["booking_id"]
    ok(book(client, owner, f, [f.court], at(1), at(2)))  # the old slot is free again
    postponed = post(client, owner, f"/games/{game['id']}/postpone", {}, 200)
    assert postponed["status"] == "postponed" and postponed["booking_id"] is None
    ok(book(client, owner, f, [f.court2], at(3), at(4)))  # postponing released the court
    back = post(client, owner, f"/games/{game['id']}/reschedule", {"resource_id": f.court2, "starts_at": at(5)}, 200)
    assert back["status"] == "scheduled"
    cancelled = post(client, owner, f"/games/{game['id']}/cancel", {}, 200)
    assert cancelled["status"] == "cancelled" and cancelled["booking_id"] is None
    assert client.post(f"{API}/games/{game['id']}/reschedule", headers=owner,
                       json={"resource_id": f.court2, "starts_at": at(7)}).status_code == 409  # fmt: skip


def test_results_standings_and_their_keys(client, owner, tenant, f):
    comp = league(client, owner, f, teams=3)
    games = scheduled(client, owner, f, comp["id"])
    first = games[0]
    keeper_email, keeper_id = add_staff(tenant, "scorekeeper", location_ids=[f.location])
    keeper = login(client, tenant, keeper_email)
    assert client.put(f"{API}/games/{first['id']}/result", headers=keeper, json=score(1, 0)).status_code == 404
    ok(client.put(f"{API}/competitions/{comp['id']}/staff", headers=owner,
                  json={"staff": [{"staff_user_id": str(keeper_id)}]}), 200)  # fmt: skip  # LGE-26: now assigned
    manager = staff(client, tenant, "manager", f)
    no_sport = client.put(f"{API}/games/{first['id']}/result", headers=keeper,
                          json={"home": {"score": 1, "sportsmanship": 4}, "away": {"score": 0}})  # fmt: skip
    assert no_sport.status_code == 422
    missing = client.put(f"{API}/games/{first['id']}/result", headers=keeper, json={"home": {}, "away": {"score": 1}})
    assert missing.status_code == 422
    result = ok(client.put(f"{API}/games/{first['id']}/result", headers=keeper, json=score(3, 1)), 200)
    assert result["home"]["score"] == 3
    assert client.post(f"{API}/games", headers=keeper, json={"competition_id": comp["id"]}).status_code == 403
    assert first["id"] in [g["id"] for g in get(client, keeper, f"/games?competition_id={comp['id']}")["data"]]
    assert get(client, keeper, f"/games/{first['id']}")["status"] == "played"
    table = get(client, owner, f"/competitions/{comp['id']}/standings")
    winner = next(s for s in table if s["competition_team_id"] == first["home_team_id"])
    assert (winner["rank"], winner["wins"], winner["points"], winner["goal_difference"]) == (
        1,
        1,
        "2.00",
        2,
    )  # the default sport scores a win 2
    loser = next(s for s in table if s["competition_team_id"] == first["away_team_id"])
    assert client.patch(f"{API}/standings/{loser['id']}", headers=manager,
                        json={"adjustment_points": 5, "reason": "Appeal"}).status_code == 403  # fmt: skip
    adjusted = ok(client.patch(f"{API}/standings/{loser['id']}", headers=owner,
                               json={"adjustment_points": 5, "reason": "Appeal"}), 200)  # fmt: skip
    assert adjusted["points"] == "5.00" and adjusted["rank"] == 1
    recomputed = post(client, owner, f"/competitions/{comp['id']}/standings/recompute", {}, 200)
    assert next(s for s in recomputed if s["id"] == loser["id"])["adjustment_points"] == "5.00"
    assert client.delete(f"{API}/games/{first['id']}/result", headers=manager).status_code == 403
    assert client.delete(f"{API}/games/{first['id']}/result", headers=owner).status_code == 204
    assert get(client, owner, f"/games/{first['id']}")["status"] == "scheduled"
    table = get(client, owner, f"/competitions/{comp['id']}/standings")
    assert all(s["games_played"] == 0 for s in table)
    forfeit = ok(client.put(f"{API}/games/{first['id']}/result", headers=owner, json={
        "home": {"participation": "forfeit"}, "away": {"score": None}}), 200)  # fmt: skip
    assert forfeit["home"]["participation"] == "forfeit"
    table = {s["competition_team_id"]: s for s in get(client, owner, f"/competitions/{comp['id']}/standings")}
    assert table[first["home_team_id"]]["forfeits"] == 1 and table[first["away_team_id"]]["wins"] == 1


def test_officials_need_qualifications_and_cannot_double_book(client, owner, f):
    comp = league(client, owner, f, teams=4)
    a, b, c, d = (t["id"] for t in comp["teams"])
    g1 = post(client, owner, "/games", {"competition_id": comp["id"], "home_team_id": a, "away_team_id": b,
                                        "resource_id": f.court, "starts_at": at(1)})  # fmt: skip
    g2 = post(client, owner, "/games", {"competition_id": comp["id"], "home_team_id": c, "away_team_id": d,
                                        "resource_id": f.court2, "starts_at": at(1.5)})  # fmt: skip
    hockey = post(client, owner, "/sports", {"name": "Hockey"})
    wrong = post(client, owner, "/officials", {"location_id": f.location, "first_name": "Ann", "last_name": "Ice",
                                               "sport_ids": [hockey["id"]]})  # fmt: skip
    refused = client.put(f"{API}/games/{g1['id']}/officials", headers=owner,
                         json={"assignments": [{"official_id": wrong["id"]}]})  # fmt: skip
    assert refused.status_code == 422 and refused.json()["code"] == "official-not-qualified"
    ref = post(client, owner, "/officials", {"location_id": f.location, "first_name": "Rob", "last_name": "Ref",
                                             "sport_ids": [f.sport["id"]]})  # fmt: skip
    assigned = ok(client.put(f"{API}/games/{g1['id']}/officials", headers=owner,
                             json={"assignments": [{"official_id": ref["id"]}]}), 200)  # fmt: skip
    assert [a["name"] for a in assigned] == ["Rob Ref"]
    overlap = client.put(f"{API}/games/{g2['id']}/officials", headers=owner,
                         json={"assignments": [{"official_id": ref["id"]}]})  # fmt: skip
    assert overlap.status_code == 409 and overlap.json()["code"] == "official-conflict"
    post(client, owner, f"/games/{g1['id']}/reschedule", {"resource_id": f.court, "starts_at": at(4)}, 200)
    ok(client.put(f"{API}/games/{g2['id']}/officials", headers=owner,
                  json={"assignments": [{"official_id": ref["id"]}]}), 200)  # fmt: skip  # the range followed the game


def test_single_elimination_bracket(client, owner, f):
    comp = league(client, owner, f, kind="tournament", format="single_elimination", teams=3)
    seeds = [t["id"] for t in comp["teams"]]
    ok(client.put(f"{API}/competitions/{comp['id']}/seeding", headers=owner, json={"competition_team_ids": seeds}), 200)
    bracket = post(client, owner, f"/competitions/{comp['id']}/brackets",
                   {"bracket_type": "single_elimination", "seed_source": "seeds"})  # fmt: skip
    assert bracket["size"] == 4
    first_round = [s for s in bracket["slots"] if s["round_no"] == 1]
    bye = next(s for s in first_round if s["is_bye"])
    assert bye["home_seed"] == 1 and bye["winner_competition_team_id"] == seeds[0]
    final = next(s for s in bracket["slots"] if s["round_name"] == "Final")
    assert seeds[0] in (final["home_team_id"], final["away_team_id"])  # the bye advanced at once
    published = post(client, owner, f"/brackets/{bracket['id']}/publish", {}, 200)
    semi = next(s for s in published["slots"] if s["round_no"] == 1 and not s["is_bye"])
    final_game = get(
        client, owner, f"/games/{next(s for s in published['slots'] if s['round_name'] == 'Final')['game_id']}"
    )
    assert final_game["game_type"] == "post_season" and "Winner of" in (
        final_game["home_label"] or final_game["away_label"]
    )
    ok(client.patch(f"{API}/bracket-slots/{semi['id']}", headers=owner,
                    json={"resource_id": f.court, "starts_at": at(1)}), 200)  # fmt: skip
    tie = client.put(f"{API}/games/{semi['game_id']}/result", headers=owner, json=score(2, 2))
    assert tie.status_code == 422 and tie.json()["code"] == "bracket-needs-winner"
    ok(client.put(f"{API}/games/{semi['game_id']}/result", headers=owner, json=score(0, 1)), 200)
    final = next(s for s in get(client, owner, f"/brackets/{bracket['id']}")["slots"] if s["round_name"] == "Final")
    assert {final["home_team_id"], final["away_team_id"]} == {seeds[0], semi["away_team_id"]}
    assert client.post(f"{API}/brackets/{bracket['id']}/publish", headers=owner, json={}).status_code == 409


def test_public_schedule_and_standings(client, owner, tenant, f):
    public = {"X-Tenant-Slug": tenant.slug}
    shown = league(client, owner, f, teams=2, is_public=True, team_fee_minor=1000, revenue_category_id=f.category)
    hidden = league(client, owner, f, name="Private", is_public=False)
    draft = league(client, owner, f, name="Draft", is_public=True, activate=False)
    games = scheduled(client, owner, f, shown["id"])
    ok(client.put(f"{API}/games/{games[0]['id']}/result", headers=owner, json=score(2, 0)), 200)
    listed = ok(client.get(f"{API}/public/competitions", headers=public), 200)
    assert [c["id"] for c in listed] == [shown["id"]]
    assert {"team_fee_minor", "revenue_category_id", "fee_status"}.isdisjoint(listed[0])
    for row in (hidden, draft):
        assert client.get(f"{API}/public/competitions/{row['id']}", headers=public).status_code == 404
    played = ok(client.get(f"{API}/public/competitions/{shown['id']}/games", headers=public), 200)
    assert {"booking_id", "conflict_note", "notes", "resource_id"}.isdisjoint(played[0])
    assert any(g["home_score"] == 2 for g in played)
    table = ok(client.get(f"{API}/public/competitions/{shown['id']}/standings", headers=public), 200)
    assert table[0]["rank"] == 1 and "adjustment_reason" not in table[0]
    other = {"X-Tenant-Slug": "no-such-club"}
    assert client.get(f"{API}/public/competitions/{shown['id']}", headers=other).status_code == 404


def test_location_scope_and_scoped_body_ids(client, owner, tenant, f):
    there = facility(client, owner, "America/New_York")
    comp = league(client, owner, f, teams=2)
    elsewhere = staff(client, tenant, "manager", there)
    for path in (f"/competitions/{comp['id']}", f"/competition-teams/{comp['teams'][0]['id']}/roster"):
        assert client.get(f"{API}{path}", headers=elsewhere).status_code == 404
    assert client.post(f"{API}/competitions/{comp['id']}/teams/generate", headers=elsewhere,
                       json={"count": 1}).status_code == 404  # fmt: skip
    foreign_court = client.post(f"{API}/schedule-runs", headers=owner,
                                json=run_body(f, [comp["id"]], resource_ids=[there.court],
                                              time_slots=[WINDOW | {"resource_id": there.court}]))  # fmt: skip
    assert foreign_court.status_code == 422
    foreign_team = post(client, owner, "/teams", {"location_id": there.location, "name": "Visitors"})
    moved = client.post(f"{API}/competitions/{comp['id']}/teams", headers=owner, json={"team_id": foreign_team["id"]})
    assert moved.status_code == 422
    stranger = new_client(client, owner, there.location)["id"]
    assert client.post(f"{API}/competition-teams/{comp['teams'][0]['id']}/roster", headers=elsewhere,
                       json={"client_id": stranger}).status_code == 404  # fmt: skip
    away_ref = post(
        client, owner, "/officials", {"location_id": there.location, "first_name": "Far", "last_name": "Ref"}
    )
    game = post(client, owner, "/games", {"competition_id": comp["id"], "home_team_id": comp["teams"][0]["id"],
                                          "away_team_id": comp["teams"][1]["id"]})  # fmt: skip
    assert client.post(f"{API}/games/{game['id']}/reschedule", headers=owner,
                       json={"resource_id": there.court, "starts_at": at(1)}).status_code == 422  # fmt: skip
    post(client, owner, f"/games/{game['id']}/reschedule", {"resource_id": f.court, "starts_at": at(1)}, 200)
    far = client.put(f"{API}/games/{game['id']}/officials", headers=owner,
                     json={"assignments": [{"official_id": away_ref["id"]}]})  # fmt: skip
    assert far.status_code == 422


def test_maintenance_paths(client, owner, f):
    comp = league(client, owner, f, teams=3, activate=False)
    cid, (a, b, c) = comp["id"], comp["teams"]
    patch = lambda path, body, status=200: ok(client.patch(f"{API}{path}", headers=owner, json=body), status)  # noqa: E731
    delete = lambda path: client.delete(f"{API}{path}", headers=owner)  # noqa: E731
    assert patch(f"/competitions/{cid}", {"name": "Renamed", "tracks_sportsmanship": True})["name"] == "Renamed"
    main = get(client, owner, f"/competitions/{cid}/divisions")[0]
    assert delete(f"/divisions/{main['id']}").status_code == 409  # it holds the teams
    north = post(client, owner, f"/competitions/{cid}/divisions", {"name": "North"})
    assert patch(f"/divisions/{north['id']}", {"name": "North A"})["name"] == "North A"
    moved = patch(f"/competition-teams/{a['id']}", {"division_id": north["id"], "display_name": "A-side"})
    assert moved["division_id"] == north["id"] and moved["display_name"] == "A-side"
    patch(f"/competition-teams/{a['id']}", {"division_id": main["id"]})
    assert delete(f"/divisions/{north['id']}").status_code == 204
    renamed = patch(f"/teams/{c['team_id']}", {"name": "Comets", "captain_client_id": f.person})
    assert renamed["name"] == "Comets" and renamed["is_placeholder"] is False
    assert delete(f"/teams/{c['team_id']}").status_code == 409  # entered in a competition
    assert delete(f"/competition-teams/{c['id']}").status_code == 204
    assert delete(f"/teams/{c['team_id']}").status_code == 204
    loose = post(client, owner, "/teams", {"location_id": f.location, "name": "Loose"})
    assert get(client, owner, f"/teams?location_id={f.location}")["data"]
    assert delete(f"/teams/{loose['id']}").status_code == 204
    place = post(client, owner, f"/competition-teams/{a['id']}/roster", {"first_name": "Al", "last_name": "Ink"})
    assert patch(f"/roster-entries/{place['id']}", {"jersey_number": "7", "position": "GK"})["jersey_number"] == "7"
    ref = post(client, owner, "/officials", {"location_id": f.location, "first_name": "Ed", "last_name": "Ref"})
    assert patch(f"/officials/{ref['id']}", {"sport_ids": [f.sport["id"]], "is_active": False})["is_active"] is False
    assert get(client, owner, f"/officials?location_id={f.location}")["data"]
    assert delete(f"/officials/{ref['id']}").status_code == 204
    post(client, owner, f"/competitions/{cid}/activate", {}, 200)
    game = post(client, owner, "/games", {"competition_id": cid, "home_team_id": a["id"], "away_label": "TBD"})
    updated = patch(
        f"/games/{game['id']}", {"away_team_id": b["id"], "notes": "Bring bibs", "version": game["version"]}
    )
    assert updated["away_name"] == b["name"] and updated["notes"] == "Bring bibs"
    assert [g["id"] for g in get(client, owner, f"/games?competition_id={cid}&status=proposed")["data"]] == [game["id"]]
    assert ok(client.get(f"{API}/games/{game['id']}/officials", headers=owner), 200) == []
    run = post(client, owner, "/schedule-runs", run_body(f, [cid]))
    assert patch(f"/schedule-runs/{run['id']}", {"rounds": 6, "wizard_step": 3})["rounds"] == 6
    generate(client, owner, run["id"])
    assert get(client, owner, f"/schedule-runs?location_id={f.location}")["data"][0]["id"] == run["id"]
    assert (
        get(client, owner, f"/schedule-runs/{run['id']}")["stats"]["games"] == 6
    )  # 6 explicit rounds: the pair meets 6 times
    discarded = post(client, owner, f"/schedule-runs/{run['id']}/discard", {}, 200)
    assert discarded["state"] == "discarded" and not get(client, owner, f"/schedule-runs/{run['id']}/games")["data"]
    bracket = post(client, owner, f"/competitions/{cid}/brackets", {"bracket_type": "single_elimination",
                                                                     "seed_source": "manual",
                                                                     "competition_team_ids": [a["id"], b["id"]]})  # fmt: skip
    final = bracket["slots"][0]
    swapped = patch(f"/bracket-slots/{final['id']}", {"home_team_id": b["id"], "away_team_id": a["id"]})
    assert swapped["home_team_id"] == b["id"]
    assert [x["id"] for x in get(client, owner, f"/competitions/{cid}/brackets")] == [bracket["id"]]
    assert delete(f"/brackets/{bracket['id']}").status_code == 204
    assert delete(f"/competitions/{cid}").status_code == 204
    assert client.get(f"{API}/competitions/{cid}", headers=owner).status_code == 404


def test_games_follow_their_booking(client, owner, tenant, f):
    from datetime import datetime, timedelta
    from uuid import UUID

    from app.modules import scheduling
    from app.modules.leagues import service

    comp = league(client, owner, f, teams=2)
    home, away = (t["id"] for t in comp["teams"])
    game = post(client, owner, "/games", {"competition_id": comp["id"], "home_team_id": home, "away_team_id": away,
                                          "resource_id": f.court, "starts_at": at(1)})  # fmt: skip
    later = datetime.fromisoformat(at(6))
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        booking = scheduling.service.get_booking(session, game["booking_id"])
        scheduling.service.reschedule_booking(
            session, booking, starts_at=later, ends_at=later + timedelta(minutes=90), resource_ids=[UUID(f.court2)]
        )
        service.on_booking_rescheduled(session, booking.id)
        service.on_booking_rescheduled(session, booking.id)  # idempotent
    moved = get(client, owner, f"/games/{game['id']}")
    assert (moved["resource_id"], moved["length_min"]) == (f.court2, 90) and moved["starts_at"].startswith(
        "2031-05-05T06"
    )
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        booking = scheduling.service.get_booking(session, game["booking_id"])
        scheduling.service.cancel_booking(session, booking)
        service.on_booking_cancelled(session, booking.id)
        service.on_booking_cancelled(session, booking.id)
    assert get(client, owner, f"/games/{game['id']}")["status"] == "cancelled"


# --- wave 2 hardening (docs/status/security-wave2.md) ------------------------------------------------------


def _principal(tenant, reach: str, *keys) -> Principal:
    return Principal(kind="staff", tenant_id=tenant.id, staff_user_id=uuid4(), permissions=dict.fromkeys(keys, reach))


def test_w2_01_team_fee_payer_must_belong_to_the_team(client, owner, tenant, f):
    paid = league(client, owner, f, team_fee_minor=30000, revenue_category_id=f.category)
    captain = new_client(client, owner, f.location)["id"]
    hawks = {"team": {"name": "Hawks", "captain_client_id": captain}}
    entry = post(client, owner, f"/competitions/{paid['id']}/teams", hawks)
    url = f"{API}/competition-teams/{entry['id']}/bill"
    stranger = client.post(url, headers=owner, json={"bill_to_client_id": f.person})
    assert stranger.status_code == 422 and stranger.json()["errors"][0]["pointer"] == "/bill_to_client_id"
    on_add = client.post(f"{API}/competitions/{paid['id']}/teams", headers=owner,
                         json={"team": {"name": "Owls"}, "bill_to_client_id": f.person})  # fmt: skip
    assert on_add.status_code == 422
    billed = post(client, owner, f"/competition-teams/{entry['id']}/bill", {"bill_to_client_id": captain}, 200)
    assert billed["fee_status"] == "billed"
    # A payer outside the caller's client reach is 404, never a 422 that confirms the client exists.
    later = post(client, owner, f"/competitions/{paid['id']}/teams", {"team": {"name": "Larks"}})
    own = _principal(tenant, "own", service.TEAMS)
    with tenant_session(tenant.id, actor=own) as session, pytest.raises(NotFound):
        service.bill_competition_team(session, own, UUID(later["id"]), {"bill_to_client_id": UUID(f.person)})


def test_w2_06_roster_and_captain_clients_go_through_the_scoped_loader(client, owner, tenant, f):
    comp = league(client, owner, f, teams=1)
    roster, teams = _principal(tenant, "own", service.ROSTER), _principal(tenant, "own", service.TEAMS)
    with tenant_session(tenant.id, actor=roster) as session:
        with pytest.raises(NotFound):
            service.add_roster_entry(
                session, roster, UUID(comp["teams"][0]["id"]), {"client_id": UUID(f.person), "role": "player"}
            )
        with pytest.raises(NotFound):
            service.create_team(
                session, teams, {"location_id": UUID(f.location), "name": "Ghosts", "captain_client_id": UUID(f.person)}
            )


def test_w2_07_bracket_booking_needs_the_games_key_and_copied_rosters_the_roster_key(client, owner, tenant, f):
    comp = league(client, owner, f, kind="tournament", format="single_elimination", teams=2)
    bracket = post(client, owner, f"/competitions/{comp['id']}/brackets",
                   {"bracket_type": "single_elimination", "seed_source": "seeds"})  # fmt: skip
    published = post(client, owner, f"/brackets/{bracket['id']}/publish", {}, 200)
    slot = next(s for s in published["slots"] if s["game_id"])
    post(client, owner, f"/competition-teams/{comp['teams'][0]['id']}/roster", {"client_id": f.person})
    target = league(client, owner, f, name="Next season")
    generate_only = _principal(tenant, "all", service.GENERATE)
    teams_only = _principal(tenant, "all", service.TEAMS)
    with tenant_session(tenant.id, actor=generate_only) as session:
        with pytest.raises(PermissionDenied):
            service.update_bracket_slot(
                session,
                generate_only,
                UUID(slot["id"]),
                {"resource_id": UUID(f.court), "starts_at": datetime.fromisoformat(at(1))},
            )
        with pytest.raises(PermissionDenied):
            service.copy_competition_teams(
                session, teams_only, UUID(target["id"]),
                {"source_competition_id": UUID(comp["id"]), "includes_rosters": True},
            )  # fmt: skip
        narrow = Principal(
            kind="staff", tenant_id=tenant.id, staff_user_id=uuid4(),
            permissions={service.TEAMS: "all", service.ROSTER: "own"},
        )  # fmt: skip
    # A copied roster client is loaded like a hand-added one; the raise rolls the whole copy back.
    with pytest.raises(NotFound), tenant_session(tenant.id, actor=narrow) as session:
        service.copy_competition_teams(
            session, narrow, UUID(target["id"]), {"source_competition_id": UUID(comp["id"]), "includes_rosters": True}
        )
    copied = ok(client.post(f"{API}/competitions/{target['id']}/teams/copy", headers=owner,
                            json={"source_competition_id": comp["id"], "includes_rosters": True}), 201)  # fmt: skip
    assert len(copied) == 2
