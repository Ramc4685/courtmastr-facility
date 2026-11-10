"""Payment schedules (BIL-06): pure functions. An instalment is (due_on, amount_minor); amounts are integer
minor units and always sum exactly to the total (largest-remainder split, overview 3.6)."""

from calendar import monthrange
from datetime import date, timedelta

UNITS = ("day", "week", "half_month", "month", "year")
MAX_INSTALMENTS = 120
Instalment = tuple[date, int]


def split(total: int, parts: int) -> list[int]:
    """`total` in `parts` near-equal integer amounts, the remainder going to the earliest ones."""
    base, extra = divmod(total, parts)
    return [base + (1 if index < extra else 0) for index in range(parts)]


def split_by_weight(total: int, weights: list[int]) -> list[int]:
    """`total` shared in proportion to `weights` by largest remainder, so the shares sum to `total` exactly
    (a coupon's amount off a sale, spread over its lines)."""
    whole = sum(weights)
    if whole <= 0:
        return [0] * len(weights)
    shares = [total * weight // whole for weight in weights]
    by_remainder = sorted(range(len(weights)), key=lambda i: (-(total * weights[i] % whole), i))
    for index in by_remainder[: total - sum(shares)]:
        shares[index] += 1
    return shares


def _add_months(start: date, months: int, day: int | None = None) -> date:
    year, month = divmod(start.year * 12 + start.month - 1 + months, 12)
    return date(year, month + 1, min(day or start.day, monthrange(year, month + 1)[1]))


def due_dates(start_on: date, every: int, unit: str, count: int) -> list[date]:
    """`count` dates from `start_on`, one every `every` units. Month arithmetic keeps the start's day of month
    and clamps it to the month's length (31 Jan + 1 month = 28 or 29 Feb, then 31 Mar). A half month
    alternates the start day and that day plus 15, clamped the same way (our rule; the reference has none)."""
    if unit not in UNITS or every < 1 or not 1 <= count <= MAX_INSTALMENTS:
        raise ValueError("unsupported schedule")
    if unit in ("day", "week"):
        step = timedelta(days=every * (7 if unit == "week" else 1))
        return [start_on + step * index for index in range(count)]
    if unit == "half_month":
        return [
            _add_months(start_on, (index * every) // 2, start_on.day + (15 if (index * every) % 2 else 0))
            for index in range(count)
        ]
    months = every * (12 if unit == "year" else 1)
    return [_add_months(start_on, months * index) for index in range(count)]


def generate(total: int, start_on: date, every: int, unit: str, count: int) -> list[Instalment]:
    """An equal-instalment plan for `total`. A zero total is one zero row."""
    if total <= 0:
        return [(start_on, 0)]
    count = min(count, total)  # never a zero instalment
    return list(zip(due_dates(start_on, every, unit, count), split(total, count), strict=True))


def cover(amounts: list[int], applied: int) -> list[int]:
    """Pour the money applied to an invoice over its instalments in due order: how much of each is covered."""
    covered = []
    for amount in amounts:
        take = min(amount, max(applied, 0))
        covered.append(take)
        applied -= take
    return covered


def rebalance(rows: list[Instalment], total: int, applied: int, today: date) -> list[Instalment]:
    """Make a plan sum to a changed invoice total (ADR 0003 section 3): a decrease is taken from the last
    instalment backwards, never below what is already covered while later money exists; an increase goes on
    the last uncovered instalment, or on a new one due today when every instalment is covered. Rows left at
    zero are dropped, except that an empty plan becomes one row."""
    total = max(total, 0)
    rows = sorted(rows)
    difference = total - sum(amount for _, amount in rows)
    if not rows:
        return [(today, total)]
    if difference > 0:
        covered = cover([amount for _, amount in rows], applied)
        open_rows = [i for i, (_, amount) in enumerate(rows) if covered[i] < amount]
        if open_rows:
            due_on, amount = rows[open_rows[-1]]
            rows[open_rows[-1]] = (due_on, amount + difference)
        else:
            rows.append((max(today, rows[-1][0]), difference))
    else:
        for index in range(len(rows) - 1, -1, -1):
            due_on, amount = rows[index]
            take = min(amount, -difference)
            rows[index] = (due_on, amount - take)
            difference += take
    kept = [row for row in rows if row[1] > 0]
    return kept or [(rows[0][0], 0)]
