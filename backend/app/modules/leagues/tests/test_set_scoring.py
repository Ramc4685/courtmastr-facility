"""Set scoring through the API: a sport's sets format snapshotted into a competition, per-set results checked
against it (sets won become the score), forfeits, standings by set and points ratio, and set scores on the staff
games, the public schedule and the TV board. A points competition is untouched."""

from app.modules.leagues.tests.test_leagues import get, league, post, scheduled, score
from app.modules.scheduling.tests.helpers import API, ok

BADMINTON = {
    "scoring_mode": "sets", "sets_best_of": 3, "set_points_to": 21, "set_win_by": 2, "set_cap": 30,
    "forfeit_score_for": 2, "standings_sort": [{"metric": "PTS"}, {"metric": "SR"}, {"metric": "PR"}],
}  # fmt: skip


def put(client, headers, game_id, body):
    return client.put(f"{API}/games/{game_id}/result", headers=headers, json=body)


def test_sets_format_is_checked_and_snapshotted(client, owner, f):
    bad = client.post(f"{API}/sports", headers=owner, json={"name": "Squash", "scoring_mode": "sets"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/sets_best_of"
    capped = client.post(f"{API}/sports", headers=owner, json={"name": "Squash"} | BADMINTON | {"set_cap": 21})
    assert capped.status_code == 422
    sport = post(client, owner, "/sports", {"name": "Badminton"} | BADMINTON)
    assert (sport["scoring_mode"], sport["sets_best_of"], sport["set_cap"]) == ("sets", 3, 30)
    f.sport = sport
    comp = league(client, owner, f, activate=False)
    assert (comp["scoring_mode"], comp["set_points_to"], comp["deciding_set_points_to"]) == ("sets", 21, None)
    # editable per competition: volleyball to 25, best of 5, deciding set to 15, no cap
    volley = {"sets_best_of": 5, "set_points_to": 25, "set_cap": None, "deciding_set_points_to": 15}
    edited = ok(client.patch(f"{API}/competitions/{comp['id']}", headers=owner, json=volley), 200)
    assert (edited["sets_best_of"], edited["set_cap"], edited["deciding_set_points_to"]) == (5, None, 15)
    assert client.patch(f"{API}/competitions/{comp['id']}", headers=owner, json={"sets_best_of": 4}).status_code == 422


def test_set_results_validate_derive_the_score_and_rank_by_ratio(client, owner, tenant, f):
    f.sport = post(client, owner, "/sports", {"name": "Badminton"} | BADMINTON)
    comp = league(client, owner, f, teams=4)
    games = scheduled(client, owner, f, comp["id"])
    first, second, third = games[0], games[1], games[2]
    for body, message in [
        ({"home": {"sets": [21, 21, 21]}, "away": {"sets": [10, 12, 5]}}, "already won"),
        ({"home": {"sets": [21, 18]}, "away": {"sets": [19, 21]}}, "not finished"),
        ({"home": {"sets": [21, 20]}, "away": {"sets": [19, 23]}}, "not a finished set"),
        ({"home": {"sets": [31, 21]}, "away": {"sets": [29, 10]}}, "not a finished set"),  # past the cap of 30
        ({"home": {"score": 2, "sets": [21, 21]}, "away": {"score": 1, "sets": [10, 12]}}, "sets won"),
        (score(2, 2), "finished match"),
    ]:
        response = put(client, owner, first["id"], body)
        assert response.status_code == 422 and response.json()["code"] == "invalid-set-score", body
        assert message in response.json()["detail"], response.json()
    result = ok(put(client, owner, first["id"], {"home": {"sets": [21, 19, 21]}, "away": {"sets": [18, 21, 15]}}), 200)
    assert (result["home"]["score"], result["away"]["score"], result["home"]["outcome"]) == (2, 1, "win")
    assert result["home"]["sets"] == [21, 19, 21] and result["away"]["sets"] == [18, 21, 15]
    ok(put(client, owner, second["id"], {"home": {"sets": [30, 21]}, "away": {"sets": [29, 5]}}), 200)
    ok(put(client, owner, third["id"], score(0, 2)), 200)  # sets won alone, no per-set points
    rows = get(client, owner, f"/competitions/{comp['id']}/standings")
    assert sum(r["goals_for"] for r in rows) == sum(r["goals_against"] for r in rows) == 2 + 1 + 2 + 0 + 0 + 2
    assert sum(r["set_points_for"] for r in rows) == 61 + 54 + 51 + 34  # the sets-won-only game adds no points
    assert [r["rank"] for r in rows] == [1, 2, 3, 4]
    # a forfeit takes no sets; the winner gets the competition's forfeit score (2 sets)
    with_sets = {"home": {"participation": "forfeit", "sets": [21]}, "away": {"sets": [10]}}
    assert put(client, owner, first["id"], with_sets).status_code == 422
    forfeit = ok(put(client, owner, first["id"], {"home": {"participation": "forfeit"}, "away": {}}), 200)
    assert forfeit["away"]["outcome"] == "forfeit_win" and forfeit["home"]["sets"] == []
    ok(put(client, owner, first["id"], {"home": {"sets": [21, 19, 21]}, "away": {"sets": [18, 21, 15]}}), 200)
    # the score line shows on the staff games and the public schedule (the board and brackets use the same view)
    staff_game = next(
        g for g in get(client, owner, f"/games?competition_id={comp['id']}")["data"] if g["id"] == first["id"]
    )
    assert staff_game["set_scores"] == "21-18, 19-21, 21-15" and staff_game["sets_best_of"] == 3
    public = get(client, {"X-Tenant-Slug": tenant.slug}, f"/public/competitions/{comp['id']}/games")
    line = next(g for g in public if g["id"] == first["id"])
    assert line["set_scores"] == "21-18, 19-21, 21-15" and line["home_score"] == 2
    assert get(client, {"X-Tenant-Slug": tenant.slug}, f"/public/competitions/{comp['id']}")["scoring_mode"] == "sets"


def test_a_points_competition_refuses_sets_and_keeps_its_rows(client, owner, f):
    comp = league(client, owner, f, teams=4)
    assert comp["scoring_mode"] == "points" and comp["sets_best_of"] is None
    game = scheduled(client, owner, f, comp["id"])[0]
    refused = put(client, owner, game["id"], {"home": {"score": 2, "sets": [21]}, "away": {"score": 1, "sets": [10]}})
    assert refused.status_code == 422
    result = ok(put(client, owner, game["id"], score(3, 1)), 200)
    assert result["home"]["sets"] == [] and result["home"]["outcome"] == "win"
    row = get(client, owner, f"/competitions/{comp['id']}/standings")[0]
    assert (row["points"], row["goals_for"], row["set_points_for"]) in (("2.00", 3, 0), ("2", 3, 0))
    staff_game = next(
        g for g in get(client, owner, f"/games?competition_id={comp['id']}")["data"] if g["id"] == game["id"]
    )
    assert staff_game["set_scores"] is None and staff_game["sets_best_of"] is None
