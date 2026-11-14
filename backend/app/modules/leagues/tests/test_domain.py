"""The pure league rules: round-robin pairing, bye modes and slot placement with preferences, standings with
tie-breaks, bracket layouts (single, double elimination, three games guaranteed), formula stats and set scoring."""

import json
from collections import Counter
from datetime import date, time
from decimal import Decimal
from itertools import combinations
from pathlib import Path

import pytest

from app.modules.leagues.domain import bracket, formula, roundrobin, sets, standings
from app.modules.leagues.models import DEFAULT_SORT

SCORING = {
    "points_win": 3, "points_tie": 1, "points_loss": 0, "points_overtime_loss": 1, "points_forfeit_win": 3,
    "points_forfeit_loss": 0, "points_default_loss": -1, "forfeit_score_for": 5,
}  # fmt: skip


@pytest.mark.parametrize("n", [2, 3, 4, 5, 8, 9])
def test_round_robin_meets_everyone_once_with_balanced_home_away(n):
    teams = list(range(n))
    rounds = roundrobin.pairings(teams)
    assert len(rounds) == (n if n % 2 else n - 1)
    games = [pair for r in rounds for pair in r if pair[1] is not None]
    assert Counter(frozenset(p) for p in games) == Counter(frozenset(p) for p in combinations(teams, 2))
    for r in rounds:  # nobody plays twice in a round; an odd field gives exactly one bye per round
        seen = [t for pair in r for t in pair if t is not None]
        assert len(seen) == len(set(seen))
        assert sum(pair[1] is None for pair in r) == n % 2
    home, away = Counter(h for h, _ in games), Counter(a for _, a in games)
    assert all(abs(home[t] - away[t]) <= 1 for t in teams)


def test_double_round_robin_swaps_home_and_away():
    rounds = roundrobin.pairings(["a", "b", "c", "d"], rounds=6)
    games = [p for r in rounds for p in r]
    assert Counter(games) == Counter({p: 1 for p in games})  # every ordered pair once
    assert len(games) == 12 and roundrobin.pairings(["a"]) == []


def test_slots_cut_windows_and_skip_excluded_dates():
    windows = [{"weekday": 3, "starts_at": "18:00", "ends_at": "20:30", "resource_id": "c1"},
               {"weekday": 3, "starts_at": "18:00", "ends_at": "19:00", "resource_id": "c2"}]  # fmt: skip
    out = roundrobin.slots(date(2031, 5, 5), date(2031, 5, 21), windows, 60, frozenset({date(2031, 5, 14)}))
    assert {s.on for s in out} == {date(2031, 5, 7), date(2031, 5, 21)}
    first_day = [s for s in out if s.on == date(2031, 5, 7)]
    assert [(s.start, s.resource_id) for s in first_day] == [
        (time(18), "c1"), (time(18), "c2"), (time(19), "c1")]  # fmt: skip


def test_assign_keeps_rounds_in_order_one_game_per_team_per_day():
    rounds = roundrobin.pairings(["a", "b", "c", "d", "e"])
    windows = [{"weekday": 3, "starts_at": "18:00", "ends_at": "22:00", "resource_id": "c1"}]
    free = roundrobin.slots(date(2031, 5, 5), date(2031, 6, 30), windows, 60)
    placed = roundrobin.assign(rounds, free)
    byes = [p for p in placed if p["away"] is None]
    assert len(byes) == 5 and all(p["slot"] is None for p in byes)
    games = [p for p in placed if p["away"] is not None]
    assert all(p["slot"] for p in games)
    by_round = {}
    for p in games:
        by_round.setdefault(p["round_no"], set()).add(p["slot"].on)
    days = [sorted(by_round[r]) for r in sorted(by_round)]
    assert all(a[-1] < b[0] for a, b in zip(days, days[1:], strict=False))
    occupied = roundrobin.assign(rounds, free, bye_takes_slot=True)
    assert all(p["slot"] for p in occupied)
    assert free == roundrobin.slots(date(2031, 5, 5), date(2031, 6, 30), windows, 60)  # input untouched
    starved = roundrobin.assign(rounds, free[:3])
    # three slots on one evening: round 1 takes two, later rounds may not reuse round 1's date
    assert sum(p["slot"] is None and p["away"] is not None for p in starved) == 8


def side(team, score, participation="full", overtime=False, **extra):
    return {"competition_team_id": team, "score": score, "participation": participation,
            "went_to_overtime": overtime} | extra  # fmt: skip


def test_outcomes_and_bracket_winner():
    assert standings.outcome(side(1, 2), side(2, 1)) == "win"
    assert standings.outcome(side(1, 1, overtime=True), side(2, 2)) == "overtime_loss"
    assert standings.outcome(side(1, 2), side(2, 2)) == "tie"
    assert standings.outcome(side(1, None, "forfeit"), side(2, None)) == "forfeit_loss"
    assert standings.outcome(side(1, None, "default"), side(2, None, "forfeit")) == "double_forfeit"
    assert standings.outcome(side(1, None), side(2, None, "default")) == "forfeit_win"
    assert standings.winner(side(1, 0), side(2, 4)) == "away"
    assert standings.winner(side(1, 2), side(2, 2)) is None


def test_standings_points_goals_forfeits_and_ranking():
    games = [
        {"home": side("a", 3, bonus_points=1), "away": side("b", 1)},
        {"home": side("b", 2, sportsmanship=4), "away": side("c", 2, sportsmanship=Decimal("3.5"))},
        {"home": side("c", None), "away": side("a", None, "forfeit")},
        {"home": side("b", 1, overtime=True), "away": side("a", 2)},
    ]
    rows = {
        r["competition_team_id"]: r for r in standings.compute(["a", "b", "c"], games, SCORING, DEFAULT_SORT, {"c": -2})
    }
    a, b, c = rows["a"], rows["b"], rows["c"]
    assert (a["wins"], a["losses"], a["forfeits"], a["points"]) == (2, 1, 1, Decimal(7))  # 3+1 bonus + 3 + 0
    assert (b["ties"], b["overtime_losses"], b["points"]) == (1, 1, Decimal(2))
    assert (c["wins"], c["ties"], c["goals_for"], c["points"]) == (1, 1, 7, Decimal(2))  # 3 + 1 - 2 adjustment
    assert c["sportsmanship_avg"] == Decimal("3.50") and a["sportsmanship_avg"] is None
    assert [a["rank"], b["rank"] + c["rank"]] == [1, 5]
    assert standings.metric(a, "WP") == Decimal(4) / 6 and standings.metric(a, "nope") == 0


def test_head_to_head_breaks_a_points_tie():
    games = [{"home": side("x", 1), "away": side("y", 0)}, {"home": side("y", 5), "away": side("z", 0)},
             {"home": side("z", 1), "away": side("x", 0)}]  # fmt: skip
    sort = [{"metric": "PTS"}, {"metric": "H2H"}, {"metric": "GA", "direction": "asc"}]
    ranked = [r["competition_team_id"] for r in standings.compute(["x", "y", "z"], games, SCORING, sort, {})]
    assert ranked == ["x", "y", "z"]  # a 3-way cycle ties the mini-table; GA (1, 1, 5) then id decide
    two = [{"home": side("p", 6), "away": side("r", 0)}, {"home": side("q", 1), "away": side("p", 0)},
           {"home": side("r", 0), "away": side("q", 0)}, {"home": side("r", 1), "away": side("p", 1)}]  # fmt: skip
    sort = [{"metric": "PTS"}, {"metric": "H2H"}, {"metric": "GD"}]
    ranked = [r["competition_team_id"] for r in standings.compute(["p", "q", "r"], two, SCORING, sort, {})]
    assert ranked == ["q", "p", "r"]  # p and q on 4: q beat p, so H2H wins over p's better goal difference


@pytest.mark.parametrize(("teams", "size", "byes"), [(2, 2, 0), (3, 4, 1), (6, 8, 2), (8, 8, 0)])
def test_single_elimination_layout(teams, size, byes):
    got_size, slots = bracket.single_elimination(teams, third_place=True)
    assert got_size == size
    first = [s for s in slots if s["round_no"] == 1 and s["side"] == "winners"]
    assert sum(s["is_bye"] for s in first) == byes
    assert sorted(s for slot in first for s in (slot["home_seed"], slot["away_seed"]) if s) == list(range(1, teams + 1))
    assert all(s["home_seed"] <= byes for s in first if s["is_bye"])  # the top seeds get the byes
    final = [s for s in slots if s["round_name"] == "Final"]
    assert len(final) == 1
    third = [s for s in slots if s["side"] == "consolation"]
    assert len(third) == (1 if size >= 4 else 0)
    if third:
        assert third[0]["home_source"][3] == "loser"
    assert bracket.seed_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    with pytest.raises(ValueError):
        bracket.single_elimination(1)


# --- Phase 14 chip B1 ------------------------------------------------------------------------------------------


def _games(rounds):
    return [p for r in rounds for p in r if p[1] is not roundrobin.BYE]


@pytest.mark.parametrize("n", [3, 5, 7])
def test_fold_last_round_plays_everyone_once_in_one_round_less(n):
    rounds = roundrobin.pairings(list(range(n)))
    folded = roundrobin.fold_last_round(rounds)
    assert len(folded) == len(rounds) - 1
    pairs = Counter(frozenset(p[:2]) for p in _games(folded))
    assert pairs == Counter(frozenset(p) for p in combinations(range(n), 2))  # nothing lost, nothing doubled
    assert any(len(p) == 3 for p in _games(folded))  # the folded games are doubleheaders
    assert roundrobin.fold_last_round(roundrobin.pairings([1, 2, 3, 4])) == roundrobin.pairings([1, 2, 3, 4])


def test_rotate_extra_games_gives_the_bye_team_a_game_and_spreads_extras():
    rounds = roundrobin.rotate_extra_games(roundrobin.pairings(list(range(5))))
    assert all(p[1] is not roundrobin.BYE for r in rounds for p in r)  # nobody sits out
    extras = Counter(t for r in rounds for p in r if len(p) == 3 for t in p[:2])
    assert set(extras) == set(range(5)) and max(extras.values()) - min(extras.values()) <= 1


def test_assign_prefers_wanted_slots_and_avoids_unavailable_ones():
    day = date(2031, 5, 7)
    free = [roundrobin.Slot(day, time(18), "c1"), roundrobin.Slot(day, time(19), "c1"),
            roundrobin.Slot(day, time(20), "c1")]  # fmt: skip
    rounds = [[("a", "b")]]
    assert roundrobin.assign(rounds, free)[0]["slot"].start == time(18)  # no preferences: first fit
    prefs = {"a": [{"kind": "time", "value": "18:00-19:30", "wants": False}],
             "b": [{"kind": "time", "value": "20:00-21:00", "wants": True, "is_priority": True}]}  # fmt: skip
    assert roundrobin.assign(rounds, list(free), prefs=prefs)[0]["slot"].start == time(20)
    weekday = {"a": [{"kind": "weekday", "value": "3", "wants": False}]}
    assert roundrobin.score(free[0], {"a"}, weekday) == -10  # 2031-05-07 is a Wednesday
    assert roundrobin.score(free[0], {"a"}, {"a": [{"kind": "resource", "value": "c1", "wants": True}]}) == 1
    assert roundrobin.score(free[0], {"a"}, {"a": [{"kind": "date", "value": "2031-05-07", "wants": True}]}) == 1


def test_assign_places_a_doubleheader_without_overlap():
    day = date(2031, 5, 7)
    free = [roundrobin.Slot(day, time(18), "c1"), roundrobin.Slot(day, time(18), "c2"),
            roundrobin.Slot(day, time(19), "c1")]  # fmt: skip
    placed = roundrobin.assign([[("a", "b"), ("a", "c", True)]], free, length_min=60)
    assert placed[0]["slot"].start == time(18) and placed[1]["slot"].start == time(19) and placed[1]["double"]


@pytest.mark.parametrize(("teams", "slots"), [(3, 5), (4, 6), (8, 14), (13, 27), (16, 30)])
def test_double_elimination_layout(teams, slots):
    size, layout = bracket.double_elimination(teams, reset=False)
    keys = {(s["side"], s["round_no"], s["position"]) for s in layout}
    assert len(layout) == slots and len(keys) == len(layout)
    for slot in layout:  # every source points at an earlier slot that exists
        for side in ("home", "away"):
            source = slot[f"{side}_source"]
            assert source is None or source[:3] in keys
    final = [s for s in layout if s["side"] == "final"]
    assert [s["round_name"] for s in final] == ["Grand final"]
    played = [s for s in layout if not s["is_bye"]]
    assert len(played) == 2 * teams - 2  # every team but the champion loses twice, the grand final included
    _, with_reset = bracket.double_elimination(teams, reset=True)
    assert with_reset[-1]["round_name"] == "Grand final reset" and len(with_reset) == slots + 1
    with pytest.raises(ValueError):
        bracket.double_elimination(2)


def test_three_games_guaranteed_gives_every_team_three_games():
    size, layout = bracket.three_games_guaranteed(8)
    assert size == 8 and len(layout) == 12
    assert [s["round_name"] for s in layout if s["round_no"] == 3] == [
        "Final", "Third place", "Fifth place", "Seventh place"
    ]  # fmt: skip
    with pytest.raises(ValueError):
        bracket.three_games_guaranteed(6)


def test_formula_parses_validates_and_evaluates_without_eval():
    tree = formula.validate("(G + A) / GP * 100", {"G", "A", "GP"})
    assert formula.names(tree) == {"G", "A", "GP"}
    assert formula.evaluate(tree, {"G": Decimal(3), "A": Decimal(1), "GP": Decimal(8)}) == Decimal(50)
    assert formula.evaluate(tree, {"G": Decimal(3)}) is None  # GP is 0: blank, not a crash
    assert formula.evaluate(formula.parse("-G + 2 * 3"), {"G": Decimal(1)}) == Decimal(5)
    for bad, message in [("G +", "ends too early"), ("(G A", "not closed"), ("G ** 2", "Unexpected"),
                         ("__import__('os')", "Unexpected"), ("G; A", "Unexpected character"), ("", "empty"),
                         ("X + 1", "Unknown stat: X"), ("G" + "+G" * 150, "at most"), ("(" * 40 + "G" + ")" * 40, "deeply")]:  # fmt: skip
        with pytest.raises(formula.FormulaError, match=message):
            formula.validate(bad, {"G", "A"})


# --- set scoring (badminton, volleyball, pickleball) --------------------------------------------------------------

BADMINTON = {"sets_best_of": 3, "set_points_to": 21, "set_win_by": 2, "set_cap": 30, "deciding_set_points_to": None}
VOLLEYBALL = {"sets_best_of": 5, "set_points_to": 25, "set_win_by": 2, "set_cap": None, "deciding_set_points_to": 15}


@pytest.mark.parametrize("a, b, fmt, legal", [
    (21, 19, BADMINTON, True), (21, 20, BADMINTON, False), (22, 20, BADMINTON, True), (23, 20, BADMINTON, False),
    (29, 27, BADMINTON, True), (30, 29, BADMINTON, True), (30, 28, BADMINTON, True), (31, 29, BADMINTON, False),
    (20, 18, BADMINTON, False), (18, 21, BADMINTON, True), (21, 21, BADMINTON, False), (21, 0, BADMINTON, True),
    (25, 23, VOLLEYBALL, True), (31, 29, VOLLEYBALL, True), (25, 24, VOLLEYBALL, False), (15, 13, VOLLEYBALL, False),
])  # fmt: skip
def test_a_set_is_complete_only_at_a_legal_score(a, b, fmt, legal):
    assert sets.complete(a, b, fmt["set_points_to"], fmt["set_win_by"], fmt["set_cap"]) is legal


def test_a_match_ends_when_one_side_has_the_sets_it_needs():
    assert sets.sets_won(BADMINTON, [21, 18, 21], [19, 21, 15]) == (2, 1)
    assert sets.sets_won(BADMINTON, [21, 21], [10, 12]) == (2, 0)
    assert sets.sets_won(VOLLEYBALL, [25, 20, 25, 13, 15], [20, 25, 22, 25, 11]) == (3, 2)  # deciding set to 15
    assert sets.sets_won(VOLLEYBALL | {"sets_best_of": 3}, [25, 20, 15], [20, 25, 10]) == (2, 1)
    for home, away, message in [
        ([21, 21, 21], [10, 12, 5], "already won"),  # an extra set after the match was decided
        ([21, 18], [19, 21], "not finished"),
        ([21], [19, 21], "same number"),
        ([21, 20], [19, 23], "not a finished set"),  # 23-20 overshoots the win-by-two at 22
        ([], [], "at least one set"),
    ]:
        with pytest.raises(ValueError, match=message):
            sets.sets_won(BADMINTON, home, away)
    with pytest.raises(ValueError, match="not a finished set"):
        sets.sets_won(VOLLEYBALL, [25, 20, 25, 13, 25], [20, 25, 22, 25, 20])  # the fifth set is played to 15


def test_sets_won_alone_must_be_a_finished_match():
    sets.check_sets_won(BADMINTON, 2, 1)
    sets.check_sets_won(VOLLEYBALL, 0, 3)
    for home, away in [(2, 2), (1, 1), (3, 0), (1, 0)]:
        with pytest.raises(ValueError):
            sets.check_sets_won(BADMINTON, home, away)


def test_set_line_reads_from_the_home_side():
    assert sets.line([21, 19, 21], [18, 21, 15]) == "21-18, 19-21, 21-15"
    assert sets.line([], []) is None


def _sets_side(team, won, scores):
    return side(team, won, set_scores=scores)


def test_sets_standings_count_sets_and_rally_points_and_rank_by_ratio():
    scoring = SCORING | {"scoring_mode": "sets", "forfeit_score_for": 2}
    games = [
        {"home": _sets_side("a", 2, [21, 21]), "away": _sets_side("b", 0, [15, 19])},
        {"home": _sets_side("b", 2, [21, 19, 21]), "away": _sets_side("c", 1, [10, 21, 12])},
        {"home": _sets_side("c", 2, [21, 22]), "away": _sets_side("a", 0, [19, 20])},
        {"home": side("a", None), "away": side("c", None, "forfeit")},
    ]
    sort = [{"metric": "PTS"}, {"metric": "SR"}, {"metric": "PR"}]
    rows = {r["competition_team_id"]: r for r in standings.compute(["a", "b", "c"], games, scoring, sort, {})}
    a, b, c = rows["a"], rows["b"], rows["c"]
    assert (a["goals_for"], a["goals_against"]) == (4, 2)  # sets won and lost; the forfeit counts as 2-0
    assert (a["set_points_for"], a["set_points_against"]) == (81, 77)  # rally points from played sets only
    assert standings.metric(a, "SW") == 4 and standings.metric(a, "SL") == 2
    assert standings.metric(a, "SR") == 2 and standings.metric(b, "PR") == Decimal(95) / 85
    assert standings.metric(standings._blank("z") | {"goals_for": 3}, "SR") > 1000  # no set lost ranks first
    assert [a["rank"], b["rank"], c["rank"]] == [1, 3, 2]  # b and c on 3 points: c's set ratio 3/4 beats 2/3


def test_points_standings_are_unchanged_by_set_scoring():
    """The golden file was written by the points-only compute before set scoring existed; a points competition
    must produce exactly the same rows, with no new fields."""
    golden = json.loads((Path(__file__).parent / "points_standings_golden.json").read_text())
    teams = ["t1", "t2", "t3", "t4", "t5", "t6"]
    games = [
        {"home": side("t1", 4), "away": side("t2", 2)},
        {"home": side("t3", 1), "away": side("t4", 1, sportsmanship=Decimal("4.5"))},
        {"home": side("t5", 2, overtime=True), "away": side("t6", 3)},
        {"home": side("t2", None, "forfeit"), "away": side("t3", None)},
        {"home": side("t4", None, "default"), "away": side("t5", None, "forfeit")},
        {"home": side("t6", 0, bonus_points=Decimal("0.5")), "away": side("t1", 0)},
        {"home": side("t1", 2, sportsmanship=3), "away": side("t3", 5)},
    ]
    sorts = (DEFAULT_SORT, [{"metric": "PTS"}, {"metric": "H2H"}, {"metric": "GA", "direction": "asc"}])
    for scoring in (SCORING, SCORING | {"scoring_mode": "points"}):
        got = [
            [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items()}
             for r in standings.compute(teams, games, scoring, sort, {"t2": Decimal("1.5")})]
            for sort in sorts
        ]  # fmt: skip
        assert got == golden
