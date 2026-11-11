"""Standings computation (LGE-06): per-side results folded into one row per team entry, then ranked by the
competition's ordered tie-breaks. Pure: inputs are plain dicts, so the rule is testable without a database."""

from decimal import Decimal

_ZERO = Decimal(0)
_GAVE_UP = ("forfeit", "default")


def _blank(team_id) -> dict:
    return {
        "competition_team_id": team_id, "games_played": 0, "wins": 0, "losses": 0, "ties": 0,
        "overtime_losses": 0, "forfeits": 0, "defaults": 0, "goals_for": 0, "goals_against": 0,
        "bonus_points": _ZERO, "points": _ZERO, "marks": [],
    }  # fmt: skip


def outcome(mine: dict, theirs: dict) -> str:
    """'win' | 'loss' | 'tie' | 'overtime_loss' | 'forfeit_win' | 'forfeit_loss' | 'default_loss' |
    'double_forfeit' from two sides {score, participation, went_to_overtime}."""
    if mine["participation"] in _GAVE_UP and theirs["participation"] in _GAVE_UP:
        return "double_forfeit"
    if mine["participation"] in _GAVE_UP:
        return f"{mine['participation']}_loss"
    if theirs["participation"] in _GAVE_UP:
        return "forfeit_win"
    a, b = mine["score"] or 0, theirs["score"] or 0
    if a == b:
        return "tie"
    if a > b:
        return "win"
    return "overtime_loss" if mine["went_to_overtime"] else "loss"


def winner(home: dict, away: dict) -> str | None:
    """'home', 'away' or None (a tie or a double forfeit): what a bracket advances."""
    kind = outcome(home, away)
    if kind in ("win", "forfeit_win"):
        return "home"
    if kind in ("tie", "double_forfeit"):
        return None
    return "away"


def _points_for(kind: str, scoring: dict) -> Decimal:
    return Decimal(scoring[{
        "win": "points_win", "tie": "points_tie", "loss": "points_loss", "overtime_loss": "points_overtime_loss",
        "forfeit_win": "points_forfeit_win", "forfeit_loss": "points_forfeit_loss",
        "default_loss": "points_default_loss", "double_forfeit": "points_forfeit_loss",
    }[kind]])  # fmt: skip


def metric(row: dict, name: str):
    gp = row["games_played"]
    return {
        "GP": gp,
        "W": row["wins"],
        "L": row["losses"],
        "T": row["ties"],
        "OTL": row["overtime_losses"],
        "FF": row["forfeits"],
        "GF": row["goals_for"],
        "GA": row["goals_against"],
        "GD": row["goals_for"] - row["goals_against"],
        "PTS": row["points"],
        "BP": row["bonus_points"],
        "WP": Decimal(row["wins"] * 2 + row["ties"]) / (2 * gp) if gp else _ZERO,
        "SPT": row.get("sportsmanship_avg") or _ZERO,
    }.get(name, 0)


def _scores(kind: str, mine: dict, theirs: dict, forfeit_score: int) -> tuple[int, int]:
    if kind == "forfeit_win":
        return forfeit_score, 0
    if kind == "double_forfeit":
        return 0, 0
    if kind in ("forfeit_loss", "default_loss"):
        return 0, forfeit_score
    return mine["score"] or 0, theirs["score"] or 0


def compute(team_ids: list, games: list[dict], scoring: dict, sort: list[dict], adjustments: dict) -> list[dict]:
    """`games` are [{home: side, away: side}] for played games, each side {competition_team_id, score,
    participation, went_to_overtime, bonus_points, sportsmanship}. `adjustments` maps a team id to manual
    points. Returns rows ranked 1..n by `sort` (ordered {metric, direction}; 'H2H' compares the points two
    teams took off each other), then by team id for a stable order."""
    rows = {team_id: _blank(team_id) for team_id in team_ids}
    head_to_head: dict[tuple, Decimal] = {}
    for game in games:
        for mine, theirs in ((game["home"], game["away"]), (game["away"], game["home"])):
            row = rows.get(mine["competition_team_id"])
            if row is None:
                continue
            kind = outcome(mine, theirs)
            row["games_played"] += 1
            key = {"win": "wins", "forfeit_win": "wins", "tie": "ties"}.get(kind, "losses")
            row[key] += 1
            row["overtime_losses"] += kind == "overtime_loss"
            row["forfeits"] += mine["participation"] == "forfeit"
            row["defaults"] += mine["participation"] == "default"
            score_for, score_against = _scores(kind, mine, theirs, scoring["forfeit_score_for"])
            row["goals_for"] += score_for
            row["goals_against"] += score_against
            bonus = Decimal(mine.get("bonus_points") or 0)
            earned = _points_for(kind, scoring)
            row["bonus_points"] += bonus
            row["points"] += earned + bonus
            pair = (mine["competition_team_id"], theirs["competition_team_id"])
            head_to_head[pair] = head_to_head.get(pair, _ZERO) + earned
            if mine.get("sportsmanship") is not None:
                row["marks"].append(Decimal(mine["sportsmanship"]))
    for team_id, row in rows.items():
        row["points"] += Decimal(adjustments.get(team_id) or 0)
        marks = row.pop("marks")
        row["sportsmanship_avg"] = (sum(marks) / len(marks)).quantize(Decimal("0.01")) if marks else None

    def order(group: list[dict], keys: list[dict]) -> list[dict]:
        """Split the group by the first key, then order each tie by the rest. 'H2H' is a mini-table: the
        points a team took off the others still tied with it, which stays transitive for three-way ties."""
        if len(group) < 2 or not keys:
            return sorted(group, key=lambda r: str(r["competition_team_id"]))
        key, rest = keys[0], keys[1:]
        tied = {r["competition_team_id"] for r in group}
        if key["metric"] == "H2H":
            value = lambda r: sum(  # noqa: E731
                (head_to_head.get((r["competition_team_id"], o), _ZERO) for o in tied), _ZERO
            )
        else:
            value = lambda r: metric(r, key["metric"])  # noqa: E731
        buckets: dict = {}
        for row in group:
            buckets.setdefault(value(row), []).append(row)
        ranked = sorted(buckets, reverse=key.get("direction") != "asc")
        return [row for v in ranked for row in order(buckets[v], rest)]

    ordered = order(list(rows.values()), list(sort))
    for rank, row in enumerate(ordered, start=1):
        row["rank"] = rank
    return ordered
