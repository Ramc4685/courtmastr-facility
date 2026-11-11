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
