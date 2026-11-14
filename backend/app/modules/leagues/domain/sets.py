"""Set scoring (badminton, volleyball, pickleball): when a set is finished and who won the match. Pure.

A format is a dict with `sets_best_of` (1, 3 or 5), `set_points_to`, `set_win_by`, `set_cap` (None or the score
that ends a set however close) and `deciding_set_points_to` (None or the target of the last possible set). Errors
are ValueError with a sentence the service turns into a 422."""


def need(best_of: int) -> int:
    return best_of // 2 + 1


def complete(a: int, b: int, target: int, win_by: int, cap: int | None) -> bool:
    """A finished set: the winner reached the target with the margin and not a point more than needed, or hit
    the cap from deuce (30-29 in badminton; 30-5 or 30-27 cannot happen)."""
    won, lost = max(a, b), min(a, b)
    if won == lost or (cap is not None and cap > target and won > cap):
        return False
    if cap is not None and cap > target and won == cap:
        return lost >= cap - win_by
    return won == (target if lost <= target - win_by else lost + win_by)


def sets_won(fmt: dict, home: list[int], away: list[int]) -> tuple[int, int]:
    """Sets won by each side from the per-set points, checked in order: every set finished, no set after the
    match was decided, and the match decided."""
    if len(home) != len(away):
        raise ValueError("Both sides need the same number of sets.")
    if not home:
        raise ValueError("Enter at least one set.")
    best_of, needed = fmt["sets_best_of"], need(fmt["sets_best_of"])
    won = [0, 0]
    for number, (a, b) in enumerate(zip(home, away, strict=True), start=1):
        if max(won) == needed:
            raise ValueError(f"Set {number} is extra: the match was already won.")
        target = fmt["deciding_set_points_to"] if number == best_of and fmt["deciding_set_points_to"] else None
        if not complete(a, b, target or fmt["set_points_to"], fmt["set_win_by"], fmt["set_cap"]):
            raise ValueError(f"Set {number} ({a}-{b}) is not a finished set.")
        won[0 if a > b else 1] += 1
    if max(won) < needed:
        raise ValueError(f"The match is not finished: a side needs {needed} sets.")
    return won[0], won[1]


def check_sets_won(fmt: dict, home: int, away: int) -> None:
    """A result given as sets won only (no per-set points): one side has exactly the sets needed."""
    needed = need(fmt["sets_best_of"])
    if sorted((home, away))[1] != needed or min(home, away) >= needed:
        raise ValueError(f"A finished match has one side on {needed} sets and the other on fewer.")


def line(home: list[int], away: list[int]) -> str | None:
    """'21-18, 19-21, 21-15' from the home side's view; None when no sets were entered."""
    return ", ".join(f"{a}-{b}" for a, b in zip(home, away, strict=False)) or None
