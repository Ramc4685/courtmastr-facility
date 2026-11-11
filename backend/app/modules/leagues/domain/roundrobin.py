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


def assign(rounds: list[list[tuple]], free: list[Slot], *, bye_takes_slot: bool = False) -> list[dict]:
    """Greedy placement, round by round: a round starts on a date after the previous round's last date and no
    team plays twice on one date. Returns {round_no, home, away, slot} per pair; slot is None when nothing fits
    (unschedulable) or for a bye that does not take a slot."""
    out = []
    queue = list(free)
    floor = None
    for round_no, pairs in enumerate(rounds, start=1):
        busy: dict[date, set] = {}
        last = None
        for home, away in pairs:
            if away is BYE and not bye_takes_slot:
                out.append({"round_no": round_no, "home": home, "away": away, "slot": None})
                continue
            teams = {home} if away is BYE else {home, away}
            chosen = None
            for index, slot in enumerate(queue):
                if (floor is None or slot.on >= floor) and not teams & busy.get(slot.on, set()):
                    chosen = queue.pop(index)
                    break
            if chosen is not None:
                busy.setdefault(chosen.on, set()).update(teams)
                last = chosen.on if last is None else max(last, chosen.on)
            out.append({"round_no": round_no, "home": home, "away": away, "slot": chosen})
        if last is not None:
            floor = last + timedelta(days=1)
    return out
