"""Pure arithmetic for independent coaches' revenue share (staff README "Coach revenue share").

Money is integer minor units. A lesson's value rounds down (an exception to the half-up rule, ADR 0003), so a
package's lessons never add up to more than its net; the court fee and the split round half-up once, and the
facility's share is always the gross minus the coach's, so the two shares sum to the gross by construction.
"""

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_HUNDRED = Decimal(100)


def half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def lesson_value(net_minor: int, sold: int, number: int = 1) -> int:
    """The gross of a package's `number`th lesson: the package's net price (after discounts and refunds, before tax)
    per credit granted at sale, rounded down so the lessons never add up to more than the net (the remainder, under
    a cent a lesson, stays the facility's). Lessons past the sold count (credits added later) are worth 0."""
    if sold <= 0 or net_minor <= 0 or not 1 <= number <= sold:
        return 0
    return net_minor // sold


def court_fee(fee_minor: int, basis: str, minutes: int) -> int:
    """The facility's court fee for one lesson: flat per session, or per hour prorated to the lesson length."""
    return fee_minor if basis == "session" else half_up(Decimal(fee_minor) * minutes / 60)


def split(gross: int, pct: Decimal, fee: int = 0, applies: str = "before_split") -> tuple[int, int]:
    """(facility_share, coach_share) of one lesson. `before_split`: the fee comes off the price and the rest is
    split; `after_split`: the price is split and the fee comes off the coach's part. The coach never goes below
    zero on a lesson, and a negative gross (a reversal) splits by the same rule with the signs flipped."""
    sign, amount = (-1, -gross) if gross < 0 else (1, gross)
    if applies == "before_split":
        coach = half_up(Decimal(max(amount - fee, 0)) * pct / _HUNDRED)
    else:
        coach = max(half_up(Decimal(amount) * pct / _HUNDRED) - fee, 0)
    coach = min(coach, amount)
    return sign * (amount - coach), sign * coach


def in_force(rows: Sequence[tuple[date, object]], on: date):
    """The value of the latest (effective_from_on, value) row on or before `on`, else None."""
    best = None
    for start, value in sorted(rows, key=lambda r: r[0]):
        if start <= on:
            best = value
    return best


def pick_rule(rules: list, payee_id, reservation_type_id, on: date):
    """Most specific share rule in force on a day: coach and type, coach, type, then the tenant default."""
    for key in ((payee_id, reservation_type_id), (payee_id, None), (None, reservation_type_id), (None, None)):
        found = in_force([(r.effective_from_on, r) for r in rules
                          if (r.staff_payee_id, r.reservation_type_id) == key], on)  # fmt: skip
        if found is not None:
            return found
    return None
