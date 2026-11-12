"""Round-robin pairing (circle method) and slot assignment for the schedule generator (LGE-08, LGE-09).

Pure functions: no database, no clock. Times are location-local wall times; the service converts to UTC.
"""

from collections.abc import Hashable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

BYE = None


def pairings(teams: list[Hashable], rounds: int | None = None) -> list[list[tuple]]:
    """Rounds of (home, away) pairs. An odd field gets a BYE placeholder, so each round has one pair written
    (team, None). More rounds than one cycle (n-1) repeat it with home and away swapped (double round robin).
    Berger rule: the fixed team alternates home and away by round, every other pair keeps its rotation order,
    which leaves each team's home and away counts at most one apart."""
    field = list(teams)
    if len(field) < 2:
        return []
    if len(field) % 2:
        field.append(BYE)
    n = len(field)
    cycle = n - 1
    out = []
    rotation = field[:]
    for r in range(rounds or cycle):
        if r and r % cycle == 0:
            rotation = field[:]
        pairs = []
        for i in range(n // 2):
            a, b = rotation[i], rotation[n - 1 - i]
            home_first = i > 0 or (r % cycle) % 2 == 0
            if (r // cycle) % 2:
                home_first = not home_first
            pair = (a, b) if home_first else (b, a)
            if pair[0] is BYE:
                pair = (pair[1], BYE)
            pairs.append(pair)
        out.append(pairs)
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return out


@dataclass(frozen=True)
class Slot:
    on: date
    start: time
    resource_id: Hashable


def _wall(value) -> time:
    return value if isinstance(value, time) else time.fromisoformat(value)


def slots(
    starts_on: date, ends_on: date, windows: list[dict], length_min: int, excluded: frozenset = frozenset()
) -> list[Slot]:
    """Every bookable slot: for each date in range whose ISO weekday has a window, the window is cut into
    back-to-back games of `length_min` on its resource. Windows are {weekday, starts_at, ends_at, resource_id}
    with wall times 'HH:MM'. Ordered by date and start time, then window order (the venue column order)."""
    out = []
    day = starts_on
    while day <= ends_on:
        if day not in excluded:
            for window in windows:
                if window["weekday"] != day.isoweekday():
                    continue
                cursor = datetime.combine(day, _wall(window["starts_at"]))
                end = datetime.combine(day, _wall(window["ends_at"]))
                while cursor + timedelta(minutes=length_min) <= end:
                    out.append(Slot(day, cursor.time(), window["resource_id"]))
                    cursor += timedelta(minutes=length_min)
        day += timedelta(days=1)
    return sorted(out, key=lambda s: (s.on, s.start))


def fold_last_round(rounds: list[list[tuple]]) -> list[list[tuple]]:
    """LGE-09 "fold": an odd field's last round is dropped and each of its games moves into the earlier round
    where one of its teams had the bye, so the season is one round shorter. The other team plays twice that
    round (a doubleheader, marked by a third element True). An even field has no bye and is left as it is."""
    if len(rounds) < 2:
        return rounds
    *head, last = [list(r) for r in rounds]
    games = [p for p in last if p[1] is not BYE]
    if len(games) == len(last):
        return rounds
    for home, away, *_ in games:
        for round_ in head:
            bye = next((p for p in round_ if p[1] is BYE and p[0] in (home, away)), None)
            if bye is not None:
                round_[round_.index(bye)] = (home, away, True)
                break
    return head


def rotate_extra_games(rounds: list[list[tuple]]) -> list[list[tuple]]:
    """LGE-09 "rotate": the team with the bye gets an extra game against a team already playing that round,
    picked in rotation (fewest extra games so far, then not yet met as an extra), so extras spread evenly. The
    opponent plays twice (doubleheader). Counts per team are uneven by one at most when the cycle is cut short."""
    extras: dict = {}
    met: set = set()
    out = []
    for round_ in rounds:
        round_ = list(round_)
        playing = [t for p in round_ if p[1] is not BYE for t in p[:2]]
        for index, pair in enumerate(round_):
            if pair[1] is not BYE or not playing:
                continue
            idle = pair[0]
            opponent = min(playing, key=lambda t: (extras.get(t, 0), frozenset((idle, t)) in met))
            extras[opponent] = extras.get(opponent, 0) + 1
            met.add(frozenset((idle, opponent)))
            round_[index] = (idle, opponent, True)
        out.append(round_)
    return out


def _matches(pref: dict, slot: Slot) -> bool:
    kind, value = pref["kind"], pref["value"]
    if kind == "date":
        return value == slot.on.isoformat()
    if kind == "weekday":
        return int(value) == slot.on.isoweekday()
    if kind == "time":
        start, end = value.split("-")
        return _wall(start) <= slot.start < _wall(end)
    return value == str(slot.resource_id)


def score(slot: Slot, teams: set, prefs: dict) -> int:
    """LGE-10, soft: each matching preference of either team adds its weight (2 when priority, else 1) when the
    team wants it, and takes ten times that when the team cannot play then. Higher is better; 0 is neutral."""
    total = 0
    for team in teams:
        for pref in prefs.get(team, ()):
            if _matches(pref, slot):
                weight = 2 if pref.get("is_priority") else 1
                total += weight if pref.get("wants") else -10 * weight
    return total


def _overlaps(slot: Slot, starts: set, length_min: int) -> bool:
    here = datetime.combine(slot.on, slot.start)
    return any(abs((here - datetime.combine(slot.on, other)).total_seconds()) < length_min * 60 for other in starts)


def assign(
    rounds: list[list[tuple]],
    free: list[Slot],
    *,
    bye_takes_slot: bool = False,
    prefs: dict | None = None,
    length_min: int = 0,
) -> list[dict]:
    """Greedy placement, round by round: a round starts on a date after the previous round's last date and no
    team plays twice on one date, except in a doubleheader pair (third element True), whose second game must not
    overlap the first. Among the slots that fit, the best preference score wins, then the earliest. Returns
    {round_no, home, away, slot} per pair; slot is None when nothing fits (unschedulable) or for a bye that does
    not take a slot."""
    prefs = prefs or {}
    out = []
    queue = list(free)
    floor = None
    for round_no, pairs in enumerate(rounds, start=1):
        busy: dict[date, dict] = {}
        last = None
        for home, away, *double in pairs:
            if away is BYE and not bye_takes_slot:
                out.append({"round_no": round_no, "home": home, "away": away, "slot": None})
                continue
            teams = {home} if away is BYE else {home, away}
            best = None
            for index, slot in enumerate(queue):
                if floor is not None and slot.on < floor:
                    continue
                day = busy.get(slot.on, {})
                if double:
                    if any(_overlaps(slot, day.get(t, set()), length_min) for t in teams):
                        continue
                elif teams & day.keys():
                    continue
                points = score(slot, teams, prefs) if prefs else 0
                if best is None or points > best[0]:
                    best = (points, index)
                if not prefs:
                    break
            chosen = queue.pop(best[1]) if best is not None else None
            if chosen is not None:
                for team in teams:
                    busy.setdefault(chosen.on, {}).setdefault(team, set()).add(chosen.start)
                last = chosen.on if last is None else max(last, chosen.on)
            out.append({"round_no": round_no, "home": home, "away": away, "slot": chosen, "double": bool(double)})
        if last is not None:
            floor = last + timedelta(days=1)
    return out
