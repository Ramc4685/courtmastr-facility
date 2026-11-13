"""Phase 14 chip B1, league depth, through the API: the chunked generator and its bye modes, venues and team
preferences, double elimination with a reset, three games guaranteed, pool crossover, ladders, scorekeepers,
formula stats, the team fee split, publishing a program group, the captain's portal roster and game cards."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import passwords, system_principal
from app.core.db.session import tenant_session
from app.modules import clients
from app.modules.leagues import service, subject
from app.modules.leagues.models import TeamFeeShare
from app.modules.leagues.tests.test_leagues import WINDOW, generate, get, league, post, run_body, score
from app.modules.platform.models import Identity
from app.modules.scheduling.tests.helpers import API, at, book, local, ok
from conftest import PASSWORD, add_staff, login, new_client


def put(client, headers, path, body, status=200):
    return ok(client.put(f"{API}{path}", headers=headers, json=body), status)


# --- the generator (LGE-08, LGE-09, LGE-10, RES-06) -------------------------------------------------------------


def test_generator_runs_one_competition_per_chunk_and_survives_a_crash(client, owner, tenant, f):
    a, b = league(client, owner, f, teams=4), league(client, owner, f, name="Second", teams=4)
    run = post(client, owner, "/schedule-runs", run_body(f, [a["id"], b["id"]]))
    started = post(client, owner, f"/schedule-runs/{run['id']}/generate", {}, 200)
    assert started["state"] == "generating" and started["progress"] == {"done": 0, "total": 2}
    run_id = UUID(run["id"])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert service.generate_schedule_chunk(session, run_id) is True  # first competition, committed
    with pytest.raises(RuntimeError), tenant_session(tenant.id, actor=system_principal("tests")) as session:
        service.generate_schedule_chunk(session, run_id)
        raise RuntimeError("worker died before commit")  # the second chunk rolls back
    assert get(client, owner, f"/schedule-runs/{run['id']}")["progress"] == {"done": 1, "total": 2}
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert service.generate_schedule_chunk(session, run_id) is False  # redelivered: resumes at the cursor
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert service.generate_schedule_chunk(session, run_id) is False  # a duplicate message is a no-op
    done = get(client, owner, f"/schedule-runs/{run['id']}")
    assert done["state"] == "previewed" and done["stats"]["games"] == 12
    games = get(client, owner, f"/schedule-runs/{run['id']}/games?limit=100")["data"]
    slots = [(g["resource_id"], g["starts_at"]) for g in games if g["starts_at"]]
    assert len(games) == 12 and len(slots) == len(set(slots))  # no slot used twice across the chunks


def test_a_dead_generator_marks_the_run_failed(client, owner, tenant, f):
    comp = league(client, owner, f, teams=2)
    run = post(client, owner, "/schedule-runs", run_body(f, [comp["id"]]))
    post(client, owner, f"/schedule-runs/{run['id']}/generate", {}, 200)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        service.fail_schedule_run(session, UUID(run["id"]))
    assert get(client, owner, f"/schedule-runs/{run['id']}")["state"] == "failed"
    assert generate(client, owner, run["id"])["state"] == "previewed"  # a failed run generates again


# Five teams: fold drops round five into two of the four earlier byes; rotate gives every bye an extra game.
@pytest.mark.parametrize(
    ("mode", "games", "byes", "rounds"), [("fold_last_round", 10, 2, 4), ("rotate_extra_game", 15, 0, 5)]
)
def test_odd_field_bye_modes(client, owner, f, mode, games, byes, rounds):
    comp = league(client, owner, f, teams=5)
    windows = [WINDOW | {"resource_id": f.court}, WINDOW | {"resource_id": f.court2}]
    body = run_body(f, [comp["id"]], bye_mode=mode, resource_ids=[f.court, f.court2], time_slots=windows)
    run = post(client, owner, "/schedule-runs", body)
    stats = generate(client, owner, run["id"])["stats"]
    assert (stats["games"], stats["byes"]) == (games, byes)
    played = get(client, owner, f"/schedule-runs/{run['id']}/games?limit=100")["data"]
    assert len({g["round_no"] for g in played}) == rounds


def test_venue_windows_book_every_court_and_preferences_are_checked(client, owner, f):
    body = {"location_id": f.location, "name": "Twin", "resource_ids": [f.court, f.court2]}
    venue = post(client, owner, "/league-venues", body)
    stranger = client.post(
        f"{API}/league-venues", headers=owner, json=body | {"name": "X", "resource_ids": [str(uuid4())]}
    )
    assert stranger.status_code == 422
    assert [v["id"] for v in get(client, owner, f"/league-venues?location_id={f.location}")["data"]] == [venue["id"]]
    comp = league(client, owner, f, teams=2)
    home = comp["teams"][0]["id"]
    put(client, owner, f"/competition-teams/{home}/preferences",
        {"preferences": [{"kind": "time", "value": "20:00-21:00", "wants": True}]})  # fmt: skip
    wrong = client.put(f"{API}/competition-teams/{home}/preferences", headers=owner,
                       json={"preferences": [{"kind": "weekday", "value": "9"}]})  # fmt: skip
    assert wrong.status_code == 422 and wrong.json()["errors"][0]["pointer"] == "/preferences/0/value"
    assert get(client, owner, f"/competition-teams/{home}/preferences")[0]["value"] == "20:00-21:00"
    court = [{"kind": "resource", "value": f.court, "wants": True}, {"kind": "resource", "value": venue["id"]}]
    assert len(put(client, owner, f"/competition-teams/{home}/preferences", {"preferences": court})) == 2
    put(client, owner, f"/competition-teams/{home}/preferences",
        {"preferences": [{"kind": "time", "value": "20:00-21:00", "wants": True}]})  # fmt: skip
    run = post(client, owner, "/schedule-runs",
               run_body(f, [comp["id"]], resource_ids=[], time_slots=[WINDOW | {"venue_id": venue["id"]}]))  # fmt: skip
    generate(client, owner, run["id"])
    post(client, owner, f"/schedule-runs/{run['id']}/commit", {}, 200)
    (game,) = get(client, owner, f"/schedule-runs/{run['id']}/games?status=scheduled")["data"]
    assert game["venue_id"] == venue["id"] and game["resource_id"] == f.court
    assert book(client, owner, f, [f.court2], game["starts_at"], game["ends_at"]).status_code == 409  # both held
    assert client.delete(f"{API}/league-venues/{venue['id']}", headers=owner).json()["code"] == "in-use"
    both = run_body(f, [comp["id"]], time_slots=[WINDOW | {"venue_id": venue["id"], "resource_id": f.court}])
    assert client.post(f"{API}/schedule-runs", headers=owner, json=both).status_code == 422


# --- brackets (LGE-11, LGE-12, LGE-13) --------------------------------------------------------------------------


def _slots(client, owner, bracket_id) -> dict:
    return {
        (s["side"], s["round_no"], s["position"]): s for s in get(client, owner, f"/brackets/{bracket_id}")["slots"]
    }


def _play(client, owner, f, slot: dict, result: dict, hour: float) -> None:
    ok(
        client.patch(
            f"{API}/bracket-slots/{slot['id']}", headers=owner, json={"resource_id": f.court, "starts_at": at(hour)}
        ),
        200,
    )
    put(client, owner, f"/games/{slot['game_id']}/result", result)


def test_double_elimination_with_a_reset_game(client, owner, f):
    comp = league(client, owner, f, kind="tournament", format="double_elimination", teams=4)
    bracket = post(client, owner, f"/competitions/{comp['id']}/brackets",
                   {"bracket_type": "double_elimination", "seed_source": "seeds", "has_reset_game": True})  # fmt: skip
    assert bracket["has_reset_game"]
    bid = bracket["id"]
    post(client, owner, f"/brackets/{bid}/publish", {}, 200)
    for hour in range(2, 40, 2):  # play every ready non-final slot, home wins, until both finalists are known
        ready = [s for k, s in sorted(_slots(client, owner, bid).items()) if k[0] != "final" and s["game_id"]
                 and s["home_team_id"] and s["away_team_id"] and not s["winner_competition_team_id"]]  # fmt: skip
        if not ready:
            break
        _play(client, owner, f, ready[0], score(2, 1), hour)
    s = _slots(client, owner, bid)
    final, reset = s[("final", 1, 1)], s[("final", 2, 1)]
    _play(client, owner, f, final, score(1, 2), 20)  # the losers' champion wins: the reset is on
    assert get(client, owner, f"/games/{reset['game_id']}")["status"] == "proposed"
    put(client, owner, f"/games/{final['game_id']}/result", score(3, 1))  # corrected: the winners' champion won
    assert _slots(client, owner, bid)[("final", 2, 1)]["winner_competition_team_id"] == final["home_team_id"]
    assert get(client, owner, f"/games/{reset['game_id']}")["status"] == "cancelled"
    assert client.delete(f"{API}/games/{final['game_id']}/result", headers=owner).status_code == 204
    assert get(client, owner, f"/games/{reset['game_id']}")["status"] == "proposed"


def test_three_games_guaranteed_and_pool_crossover(client, owner, f):
    eight = league(client, owner, f, kind="tournament", format="three_games_guaranteed", teams=8)
    tgg = post(client, owner, f"/competitions/{eight['id']}/brackets",
               {"bracket_type": "three_games_guaranteed", "seed_source": "seeds"})  # fmt: skip
    assert len(tgg["slots"]) == 12
    seven = league(client, owner, f, kind="tournament", format="three_games_guaranteed", teams=7)
    short = client.post(f"{API}/competitions/{seven['id']}/brackets", headers=owner,
                        json={"bracket_type": "three_games_guaranteed", "seed_source": "seeds"})  # fmt: skip
    assert short.status_code == 422

    pid = league(client, owner, f, kind="tournament", format="pool_play")["id"]
    pool_a = post(client, owner, f"/competitions/{pid}/divisions", {"name": "Pool A"})
    pool_b = post(client, owner, f"/competitions/{pid}/divisions", {"name": "Pool B"})
    teams = {}
    for pool, names in ((pool_a, ("A1", "A2")), (pool_b, ("B1", "B2"))):
        for name in names:
            teams[name] = post(
                client, owner, f"/competitions/{pid}/teams", {"team": {"name": name}, "division_id": pool["id"]}
            )["id"]
    for hour, (home, away) in ((2, ("A1", "A2")), (4, ("B1", "B2"))):
        game = post(client, owner, "/games", {"competition_id": pid, "home_team_id": teams[home], "away_team_id": teams[away],
                                              "resource_id": f.court, "starts_at": at(hour)})  # fmt: skip
        put(client, owner, f"/games/{game['id']}/result", score(3, 0))
    crossed = post(client, owner, f"/competitions/{pid}/brackets",
                   {"bracket_type": "single_elimination", "seed_source": "pools", "advance_per_pool": 2})  # fmt: skip
    pairs = {frozenset((s["home_team_id"], s["away_team_id"])) for s in crossed["slots"] if s["round_no"] == 1}
    assert pairs == {frozenset((teams["A1"], teams["B2"])), frozenset((teams["B1"], teams["A2"]))}


# --- ladder (LGE-28), scorekeepers (LGE-26), stats (LGE-07) -----------------------------------------------------


def _rungs(client, owner, competition_id) -> dict:
    return {
        r["competition_team_id"]: r["position"] for r in get(client, owner, f"/competitions/{competition_id}/ladder")
    }


def test_ladder_challenges_swap_rungs_and_corrections_swap_back(client, owner, f):
    comp = league(client, owner, f, format="ladder", teams=5, ladder_challenge_range=2)
    ids = [t["id"] for t in comp["teams"]]
    put(client, owner, f"/competitions/{comp['id']}/ladder", {"competition_team_ids": ids})
    far = client.post(f"{API}/competitions/{comp['id']}/ladder-challenges", headers=owner,
                      json={"challenger_id": ids[4], "defender_id": ids[0]})  # fmt: skip
    assert far.status_code == 422 and far.json()["code"] == "out-of-range"
    game = post(client, owner, f"/competitions/{comp['id']}/ladder-challenges",
                {"challenger_id": ids[3], "defender_id": ids[1], "resource_id": f.court, "starts_at": at(2)})  # fmt: skip
    assert game["home_team_id"] == ids[3] and game["status"] == "scheduled"
    put(client, owner, f"/games/{game['id']}/result", score(4, 2))
    rungs = _rungs(client, owner, comp["id"])
    assert (rungs[ids[3]], rungs[ids[1]]) == (2, 4)
    put(client, owner, f"/games/{game['id']}/result", score(1, 2))  # corrected: the defender held
    rungs = _rungs(client, owner, comp["id"])
    assert (rungs[ids[3]], rungs[ids[1]]) == (4, 2)
    post(
        client, owner, f"/competitions/{comp['id']}/ladder-challenges", {"challenger_id": ids[4], "defender_id": ids[2]}
    )
    post(
        client, owner, f"/competitions/{comp['id']}/ladder-challenges", {"challenger_id": ids[3], "defender_id": ids[2]}
    )
    seen, cursor = [], None  # keyset paging by start time also walks the games that have none
    while True:
        page = get(
            client,
            owner,
            f"/games?competition_id={comp['id']}&sort=starts_at&limit=1" + (f"&cursor={cursor}" if cursor else ""),
        )
        seen += [g["id"] for g in page["data"]]
        if not (cursor := page["page"]["next_cursor"]):
            break
    assert len(seen) == len(set(seen)) == 3
    other = league(client, owner, f, name="Other", teams=2)
    assert client.get(f"{API}/competitions/{other['id']}/ladder", headers=owner).json()["code"] == "not-a-ladder"


def test_scorekeepers_reach_only_their_competitions_and_stats_roll_up(client, owner, tenant, f):
    mine, other = league(client, owner, f, teams=2), league(client, owner, f, name="Other", teams=2)

    def game(comp, hour):
        return post(client, owner, "/games", {"competition_id": comp["id"], "resource_id": f.court, "starts_at": at(hour),
                                              "home_team_id": comp["teams"][0]["id"], "away_team_id": comp["teams"][1]["id"]})  # fmt: skip

    g1, g2 = game(mine, 2), game(other, 4)
    email, keeper_id = add_staff(tenant, "scorekeeper", location_ids=[f.location])
    keeper = login(client, tenant, email)
    _, elsewhere_id = add_staff(tenant, "scorekeeper", location_ids=[])
    candidates = {c["id"] for c in get(client, owner, f"/competitions/{mine['id']}/staff-candidates")}
    assert str(keeper_id) in candidates and str(elsewhere_id) not in candidates
    assert client.get(f"{API}/competitions/{mine['id']}/staff-candidates", headers=keeper).status_code == 403
    away = client.put(f"{API}/competitions/{mine['id']}/staff", headers=owner,
                      json={"staff": [{"staff_user_id": str(elsewhere_id)}]})  # fmt: skip
    assert away.status_code == 422
    bogus = client.put(
        f"{API}/competitions/{mine['id']}/staff", headers=owner, json={"staff": [{"staff_user_id": str(uuid4())}]}
    )
    assert bogus.status_code == 422
    put(client, owner, f"/competitions/{mine['id']}/staff", {"staff": [{"staff_user_id": str(keeper_id)}]})
    assert [g["id"] for g in get(client, keeper, "/games")["data"]] == [g1["id"]]
    assert client.get(f"{API}/games/{g2['id']}", headers=keeper).status_code == 404
    assert get(client, keeper, f"/games/{g1['id']}")["sport_id"] == f.sport["id"]
    assert get(client, keeper, f"/games/{g1['id']}")["competition_name"] == mine["name"]
    assert client.put(f"{API}/competitions/{mine['id']}/staff", headers=keeper, json={"staff": []}).status_code == 403

    table = post(client, owner, f"/sports/{f.sport['id']}/stat-tables", {"name": "Scoring"})
    goals = post(client, owner, f"/stat-tables/{table['id']}/stats", {"code": "G", "name": "Goals"})
    played = post(client, owner, f"/stat-tables/{table['id']}/stats", {"code": "GP", "name": "Games"})
    bad = client.post(f"{API}/stat-tables/{table['id']}/stats", headers=owner,
                      json={"code": "X", "name": "X", "kind": "formula", "formula": "G / Z"})  # fmt: skip
    assert bad.status_code == 422 and bad.json()["code"] == "invalid-formula"
    per_game = post(client, owner, f"/stat-tables/{table['id']}/stats",
                    {"code": "GPG", "name": "Goals per game", "kind": "formula", "formula": "G / GP", "decimal_places": 2})  # fmt: skip
    player = post(
        client, owner, f"/competition-teams/{mine['teams'][0]['id']}/roster", {"first_name": "Ana", "last_name": "Goal"}
    )
    line = {"roster_entry_id": player["id"]}
    put(client, keeper, f"/games/{g1['id']}/player-stats",
        {"stats": [line | {"stat_definition_id": goals["id"], "value": "3"}, line | {"stat_definition_id": played["id"], "value": "2"}]})  # fmt: skip
    assert client.put(f"{API}/games/{g2['id']}/player-stats", headers=keeper, json={"stats": []}).status_code == 404
    formula = {"stats": [line | {"stat_definition_id": per_game["id"], "value": "1"}]}
    assert client.put(f"{API}/games/{g1['id']}/player-stats", headers=owner, json=formula).status_code == 422
    (totals,) = get(client, keeper, f"/competitions/{mine['id']}/player-stats")
    assert totals["player_name"] == "Ana Goal"
    assert {k: float(v) for k, v in totals["stats"].items()} == {"G": 3, "GP": 2, "GPG": 1.5}
    rename = client.patch(f"{API}/stat-definitions/{goals['id']}", headers=owner, json={"code": "GOALS"})
    assert rename.status_code == 409 and rename.json()["code"] == "in-use"
    assert client.delete(f"{API}/stat-definitions/{goals['id']}", headers=owner).status_code == 409


# --- fee split (REG-26), publish a program group (REG-14), captain portal (REG-26) ------------------------------


def test_team_fee_split_bills_each_share_and_the_rest(client, owner, tenant, f):
    comp = league(client, owner, f, team_fee_minor=30000, revenue_category_id=f.category)
    entry = post(
        client,
        owner,
        f"/competitions/{comp['id']}/teams",
        {"team": {"name": "Splitters", "captain_client_id": f.person}},
    )
    other = new_client(client, owner, f.location)["id"]
    p1 = post(client, owner, f"/competition-teams/{entry['id']}/roster", {"client_id": f.person})
    p2 = post(client, owner, f"/competition-teams/{entry['id']}/roster", {"client_id": other})
    path = f"{API}/competition-teams/{entry['id']}/fee-shares"
    over = client.post(path, headers=owner, json={"shares": [{"roster_entry_id": p1["id"], "amount_minor": 40000}]})
    assert over.status_code == 422
    rest = client.post(path, headers=owner, json={"shares": [{"roster_entry_id": p1["id"], "amount_minor": 10000}]})
    assert rest.status_code == 422 and rest.json()["errors"][0]["pointer"] == "/bill_to_client_id"
    shares = post(client, owner, f"/competition-teams/{entry['id']}/fee-shares", {
        "shares": [{"roster_entry_id": p1["id"], "amount_minor": 10000}, {"roster_entry_id": p2["id"], "amount_minor": 10000}],
        "bill_to_client_id": f.person,
    })  # fmt: skip
    assert [s["amount_minor"] for s in shares] == [10000, 10000]
    team = next(t for t in get(client, owner, f"/competitions/{comp['id']}/teams") if t["id"] == entry["id"])
    assert team["fee_status"] == "billed"
    assert get(client, owner, f"/competitions/{comp['id']}")["team_fee_minor"] == 30000
    with tenant_session(tenant.id) as session:
        billed = session.scalars(select(AuditEvent.changes).where(AuditEvent.entity_id == UUID(entry["id"]))).all()
    assert {"fee_status": ["unbilled", "billed"]} in billed
    again = client.post(path, headers=owner, json={"shares": [{"roster_entry_id": p2["id"], "amount_minor": 1}]})
    assert again.status_code == 409

    # a merge moves a share to the survivor, unless the survivor already has one on that team
    third = UUID(new_client(client, owner, f.location)["id"])
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        subject._repoint(session, UUID(other), third)
        subject._repoint(session, third, UUID(f.person))
        held = {
            r.client_id
            for r in session.scalars(select(TeamFeeShare).where(TeamFeeShare.competition_team_id == UUID(entry["id"])))
        }
    assert held == {UUID(f.person), third}


def test_publish_a_program_group_as_a_league(client, owner, tenant, f):
    camp = ok(
        client.post(f"{API}/program-groups", headers=owner, json={"location_id": f.location, "name": "Youth league"})
    )
    reds = ok(client.post(f"{API}/program-groups", headers=owner,
                          json={"location_id": f.location, "parent_id": camp["id"], "name": "Reds"}))  # fmt: skip
    ok(
        client.post(
            f"{API}/program-groups",
            headers=owner,
            json={"location_id": f.location, "parent_id": camp["id"], "name": "Blues"},
        )
    )
    ok(client.post(f"{API}/enrollments", headers=owner, json={"program_group_id": reds["id"], "client_id": f.person}))
    under = ok(client.post(f"{API}/program-groups", headers=owner,
                           json={"location_id": f.location, "parent_id": reds["id"], "name": "Reds U10"}))  # fmt: skip
    deep = new_client(client, owner, f.location)["id"]
    ok(client.post(f"{API}/enrollments", headers=owner, json={"program_group_id": under["id"], "client_id": deep}))
    body = {"program_group_id": camp["id"], "kind": "league", "sport_id": f.sport["id"], "starts_on": "2031-05-01"}
    comp = post(client, owner, "/competitions/from-program-group", body)
    assert comp["name"] == "Youth league" and comp["program_group_id"] == camp["id"]
    teams = {t["name"]: t for t in get(client, owner, f"/competitions/{comp['id']}/teams")}
    assert set(teams) == {"Reds", "Blues"}
    roster = get(client, owner, f"/competition-teams/{teams['Reds']['id']}/roster")
    assert sorted((r["client_id"], r["origin"]) for r in roster) == sorted(
        [(f.person, "enrollment"), (deep, "enrollment")]
    )
    with tenant_session(tenant.id) as session:
        audited = set(session.scalars(select(AuditEvent.entity_id)))
        created = session.scalar(select(AuditEvent.changes).where(AuditEvent.entity_id == UUID(comp["id"])))
    assert created["program_group_id"] == [None, camp["id"]]
    assert {UUID(t["team_id"]) for t in teams.values()} | {UUID(r["id"]) for r in roster} <= audited
    leaf = client.post(
        f"{API}/competitions/from-program-group", headers=owner, json=body | {"program_group_id": reds["id"]}
    )
    assert leaf.status_code == 422


def _portal(client, tenant, owner, location) -> tuple[dict, dict]:
    email = f"cap-{uuid4().hex[:8]}@example.com"
    person = new_client(client, owner, location, primary_email=email)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(kind="client", email=email, status="active", email_verified_at=clock.now(),
                            password_hash=passwords.hash_password(PASSWORD))  # fmt: skip
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, UUID(person["id"]), identity.id)
    return person, login(client, tenant, email, audience="client")


def test_captain_manages_the_roster_in_the_portal(client, owner, tenant, f):
    captain, portal = _portal(client, tenant, owner, f.location)
    comp = league(client, owner, f)
    entry = post(
        client,
        owner,
        f"/competitions/{comp['id']}/teams",
        {"team": {"name": "Caps", "captain_client_id": captain["id"]}},
    )
    stranger = post(client, owner, f"/competitions/{comp['id']}/teams", {"team": {"name": "Others"}})
    assert get(client, portal, "/portal/league-teams") == [
        {
            "competition_team_id": entry["id"],
            "team_name": "Caps",
            "competition_name": comp["name"],
            "starts_on": "2031-05-01",
        }
    ]
    roster = f"/portal/league-teams/{entry['id']}/roster"
    walk_on = post(client, portal, roster, {"first_name": "Walk", "last_name": "On", "jersey_number": "9"})
    me = post(client, portal, roster, {"client_id": captain["id"]})
    assert set(walk_on) == {"id", "name", "role", "jersey_number"}  # the portal shape carries no staff fields
    assert client.post(f"{API}{roster}", headers=portal, json={"client_id": f.person}).status_code == 422  # not theirs
    assert client.get(f"{API}/portal/league-teams/{stranger['id']}/roster", headers=portal).status_code == 404
    assert client.delete(f"{API}/portal/league-roster-entries/{walk_on['id']}", headers=portal).status_code == 204
    assert [r["id"] for r in get(client, portal, roster)] == [me["id"]]


# --- game cards (LGE-16, RPT-36) --------------------------------------------------------------------------------


def test_game_cards_print_rosters_and_need_the_card_key(client, owner, tenant, f):
    comp = league(client, owner, f, teams=2)
    home, away = comp["teams"]
    post(
        client,
        owner,
        f"/competition-teams/{home['id']}/roster",
        {"first_name": "Rosa", "last_name": "Card", "jersey_number": "7"},
    )
    game = post(client, owner, "/games", {"competition_id": comp["id"], "home_team_id": home["id"], "away_team_id": away["id"],
                                          "resource_id": f.court, "starts_at": at(14)})  # fmt: skip
    card = client.get(f"{API}/games/{game['id']}/card", headers=owner)
    assert card.status_code == 200 and card.headers["content-type"] == "application/pdf"
    assert b"Rosa Card" in card.content
    blank = client.get(f"{API}/competitions/{comp['id']}/blank-game-card", headers=owner)
    assert blank.status_code == 200 and blank.content.startswith(b"%PDF")
    day = "2031-05-05"
    many = client.get(f"{API}/game-cards?sport_id={f.sport['id']}&from_on={day}&to_on={day}", headers=owner)
    assert many.status_code == 200 and b"Rosa Card" in many.content
    evening = post(client, owner, "/games", {"competition_id": comp["id"], "home_team_id": home["id"], "away_team_id": away["id"],
                                             "resource_id": f.court, "starts_at": local(f.zone, 2031, 5, 5, 19)})  # fmt: skip
    late = client.get(f"{API}/games/{evening['id']}/card", headers=owner).content  # 00:00 UTC the next day
    assert b"2031-05-05" in late and b"2031-05-06" not in late
    wide = client.get(f"{API}/game-cards?sport_id={f.sport['id']}&from_on=2031-01-01&to_on=2031-12-31", headers=owner)
    assert wide.status_code == 422
    email, _ = add_staff(tenant, "front_desk", location_ids=[f.location])
    assert client.get(f"{API}/games/{game['id']}/card", headers=login(client, tenant, email)).status_code == 403
    # a scorekeeper holds the card key but reaches only its assigned competitions
    email, _ = add_staff(tenant, "scorekeeper", location_ids=[f.location])
    keeper = login(client, tenant, email)
    assert client.get(f"{API}/games/{game['id']}/card", headers=keeper).status_code == 404
    assert client.get(f"{API}/competitions/{comp['id']}/blank-game-card", headers=keeper).status_code == 404
    theirs = client.get(f"{API}/game-cards?sport_id={f.sport['id']}&from_on={day}&to_on={day}", headers=keeper)
    assert theirs.status_code == 200 and b"Rosa Card" not in theirs.content
