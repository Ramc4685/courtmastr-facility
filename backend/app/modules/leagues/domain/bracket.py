"""Single-elimination bracket layout (LGE-12): a seeded first round with byes for the top seeds, then winner
feeds round by round, plus an optional third-place game fed by the semi-final losers. Pure."""


def size_for(teams: int) -> int:
    size = 2
    while size < teams:
        size *= 2
    return size


def seed_order(size: int) -> list[int]:
    """Standard bracket order: seed 1 meets seed `size`, and seeds 1 and 2 can only meet in the final."""
    order = [1]
    while len(order) < size:
        total = len(order) * 2 + 1
        order = [seed for top in order for seed in (top, total - top)]
    return order


def round_name(round_no: int, rounds: int) -> str:
    return {0: "Final", 1: "Semi-final", 2: "Quarter-final"}.get(rounds - round_no, f"Round {round_no}")


def single_elimination(teams: int, *, third_place: bool = False) -> tuple[int, list[dict]]:
    """(size, slots). A slot is {side, round_no, position, round_name, home_seed, away_seed, home_source,
    away_source, is_bye}; a source is (side, round_no, position, 'winner' | 'loser') of an earlier slot. A
    first-round slot whose lower seed is above `teams` is a bye: the higher seed advances without a game."""
    if teams < 2:
        raise ValueError("A bracket needs at least two teams.")
    size = size_for(teams)
    rounds = size.bit_length() - 1
    order = seed_order(size)
    blank = {"home_seed": None, "away_seed": None, "home_source": None, "away_source": None, "is_bye": False}
    slots = []
    for position in range(size // 2):
        home, away = order[2 * position], order[2 * position + 1]
        slots.append(blank | {
            "side": "winners", "round_no": 1, "position": position + 1, "round_name": round_name(1, rounds),
            "home_seed": home, "away_seed": None if away > teams else away, "is_bye": away > teams,
        })  # fmt: skip
    for round_no in range(2, rounds + 1):
        for position in range(size // 2**round_no):
            slots.append(blank | {
                "side": "winners", "round_no": round_no, "position": position + 1,
                "round_name": round_name(round_no, rounds),
                "home_source": ("winners", round_no - 1, 2 * position + 1, "winner"),
                "away_source": ("winners", round_no - 1, 2 * position + 2, "winner"),
            })  # fmt: skip
    if third_place and rounds >= 2:
        slots.append(blank | {
            "side": "consolation", "round_no": rounds, "position": 1, "round_name": "Third place",
            "home_source": ("winners", rounds - 1, 1, "loser"), "away_source": ("winners", rounds - 1, 2, "loser"),
        })  # fmt: skip
    return size, slots


def _key(slot: dict) -> tuple:
    return (slot["side"], slot["round_no"], slot["position"])


_DEAD = "dead"


def _collapse(slots: list[dict]) -> list[dict]:
    """Drop the losers-bracket games byes leave empty. A first-round bye has no loser, so a slot fed by it has one
    team at most: with none it disappears, with one it passes that team straight on (its dependants are rewired
    to the live source). Slots come in feeding order, so each source is resolved before it is used."""
    byes = {_key(s) for s in slots if s["is_bye"]}
    dead: set = set()
    alias: dict = {}
    out = []
    for slot in slots:
        if slot["is_bye"]:
            out.append(slot)
            continue
        sources = {}
        for side in ("home", "away"):
            source = slot[f"{side}_source"]
            if source is not None:
                key, outcome = source[:3], source[3]
                if key in dead or (key in byes and outcome == "loser"):
                    source = _DEAD
                elif key in alias:
                    source = alias[key]
            sources[side] = source
        live = [s for s in sources.values() if s != _DEAD]
        if not live:
            dead.add(_key(slot))
        elif len(live) == 1 and _DEAD in sources.values():
            alias[_key(slot)] = live[0]
        else:
            out.append(slot | {"home_source": sources["home"], "away_source": sources["away"]})
    return out


def double_elimination(teams: int, *, reset: bool = False) -> tuple[int, list[dict]]:
    """(size, slots) for a double-elimination bracket (LGE-12). The winners side is the single-elimination
    layout. Losers rounds alternate: an odd round pairs the survivors, an even round meets them with the teams
    dropping from the next winners round, in reverse order (AB/BA crossover, so first-round opponents do not
    meet again at once). The grand final is the winners champion against the losers champion; the optional reset
    game is played only when the losers champion wins it (the service decides). Byes are collapsed."""
    if teams < 3:
        raise ValueError("Double elimination needs at least three teams.")
    size, winners = single_elimination(teams)
    rounds = size.bit_length() - 1
    for slot in winners:
        slot["round_name"] = f"Winners {slot['round_name'].lower()}"
    blank = {"home_seed": None, "away_seed": None, "is_bye": False}
    losers = []
    count = size // 4
    for k in range(1, rounds):
        minor, major = 2 * k - 1, 2 * k
        last = k == rounds - 1
        for position in range(1, count + 1):
            if k == 1:
                home, away = ("winners", 1, 2 * position - 1, "loser"), ("winners", 1, 2 * position, "loser")
            else:
                home = ("losers", minor - 1, 2 * position - 1, "winner")
                away = ("losers", minor - 1, 2 * position, "winner")
            losers.append(blank | {
                "side": "losers", "round_no": minor, "position": position, "round_name": f"Losers round {minor}",
                "home_source": home, "away_source": away,
            })  # fmt: skip
        for position in range(1, count + 1):
            losers.append(blank | {
                "side": "losers", "round_no": major, "position": position,
                "round_name": "Losers final" if last else f"Losers round {major}",
                "home_source": ("losers", minor, position, "winner"),
                "away_source": ("winners", k + 1, count + 1 - position, "loser"),
            })  # fmt: skip
        count //= 2
    final = [blank | {
        "side": "final", "round_no": 1, "position": 1, "round_name": "Grand final",
        "home_source": ("winners", rounds, 1, "winner"), "away_source": ("losers", 2 * (rounds - 1), 1, "winner"),
    }]  # fmt: skip
    if reset:
        final.append(blank | {
            "side": "final", "round_no": 2, "position": 1, "round_name": "Grand final reset",
            "home_source": ("final", 1, 1, "winner"), "away_source": ("final", 1, 1, "loser"),
        })  # fmt: skip
    # losers rounds interleave with winners rounds in play, but each losers slot only reads earlier slots
    ordered = winners + sorted(losers, key=lambda s: (s["round_no"], s["position"])) + final
    return size, _collapse(ordered)


def three_games_guaranteed(teams: int) -> tuple[int, list[dict]]:
    """(8, slots) for the 8-team three-games-guaranteed format (LGE-13): every team plays three games. Round 1
    by seed; winners meet winners and losers meet losers in round 2; round 3 places every team: final, third,
    fifth and seventh place."""
    if teams != 8:
        raise ValueError("Three games guaranteed needs exactly eight teams.")
    order = seed_order(8)
    blank = {"home_seed": None, "away_seed": None, "home_source": None, "away_source": None, "is_bye": False}
    slots = [
        blank | {"side": "winners", "round_no": 1, "position": p + 1, "round_name": "Round 1",
                 "home_seed": order[2 * p], "away_seed": order[2 * p + 1]}
        for p in range(4)
    ]  # fmt: skip

    def game(side, round_no, position, name, home, away) -> dict:
        return blank | {
            "side": side, "round_no": round_no, "position": position, "round_name": name, "home_source": home,
            "away_source": away,
        }  # fmt: skip

    w1 = [("winners", 1, p, outcome) for outcome in ("winner", "loser") for p in (1, 2, 3, 4)]
    slots += [
        game("winners", 2, 1, "Semi-final", w1[0], w1[1]),
        game("winners", 2, 2, "Semi-final", w1[2], w1[3]),
        game("consolation", 2, 1, "Consolation semi-final", w1[4], w1[5]),
        game("consolation", 2, 2, "Consolation semi-final", w1[6], w1[7]),
        game("winners", 3, 1, "Final", ("winners", 2, 1, "winner"), ("winners", 2, 2, "winner")),
        game("consolation", 3, 1, "Third place", ("winners", 2, 1, "loser"), ("winners", 2, 2, "loser")),
        game("consolation", 3, 2, "Fifth place", ("consolation", 2, 1, "winner"), ("consolation", 2, 2, "winner")),
        game("consolation", 3, 3, "Seventh place", ("consolation", 2, 1, "loser"), ("consolation", 2, 2, "loser")),
    ]
    return 8, slots
