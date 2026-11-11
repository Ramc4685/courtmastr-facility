"""Pure pay arithmetic for payroll runs (STF-02, STF-05, STF-06, STF-10). Money is integer minor units,
rounded half-up once per line (ADR 0003). No database access: the service gathers the facts."""

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_ANCHORS = (60, 45, 30)


def half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def anchored_rate(rates: dict[int, int], minutes: int) -> tuple[int, int]:
    """(anchor minutes, rate) for a session length: the nearest of 60/45/30, the longer one on a tie."""
    anchor = min(_ANCHORS, key=lambda a: (abs(a - minutes), -a))
    return anchor, rates[anchor]


def prorated(rate_minor: int, anchor: int, minutes: int) -> int:
    """A rate set for `anchor` minutes, scaled to the session's real length."""
    return half_up(Decimal(rate_minor) * minutes / anchor)


def per_hour(rate_minor: int, minutes: int) -> int:
    return half_up(Decimal(rate_minor) * minutes / 60)


def session_line(rate: Any, minutes: int, attendees: int) -> dict | None:
    """The pay line for one completed trainer session under a pay-rate row, or None when it earns nothing.

    A session nobody attended pays the flat non-training hourly rate when one is set (and nothing otherwise);
    `per_attendee` pays the prorated rate once per attendee, `per_session` once."""
    if attendees == 0:
        if not rate.non_training_rate_minor:
            return None
        return {"kind": "non_training", "quantity": Decimal(minutes) / 60, "rate_minor": rate.non_training_rate_minor,
                "amount_minor": per_hour(rate.non_training_rate_minor, minutes)}  # fmt: skip
    rates = {60: rate.rate_60_minor, 45: rate.rate_45_minor, 30: rate.rate_30_minor}
    anchor, base = anchored_rate(rates, minutes)
    each = prorated(base, anchor, minutes)
    quantity = attendees if rate.pay_basis == "per_attendee" else 1
    if each * quantity == 0:
        return None
    return {"kind": "session", "quantity": Decimal(quantity), "rate_minor": each, "amount_minor": each * quantity}


def commission(base_minor: int, pct: Decimal, flat_minor: int) -> int:
    return half_up(Decimal(base_minor) * pct / 100) + flat_minor


def pick_rule(rules: Iterable[Any], applies_to: str, **target: Any) -> Any | None:
    """The most specific commission rule: one naming the sale's type wins over the payee's default row."""
    default = None
    for rule in rules:
        if rule.applies_to != applies_to:
            continue
        keyed = {key: getattr(rule, key) for key in target}
        if all(value is None for value in keyed.values()):
            default = rule
        elif all(keyed[key] == target[key] for key in target if keyed[key] is not None):
            return rule
    return default


def rate_on(rates: Sequence[tuple[date, int]], day: date) -> int | None:
    """The effective-dated hourly rate in force on `day` (latest start on or before it)."""
    best = None
    for starts_on, rate_minor in rates:
        if starts_on <= day and (best is None or starts_on > best[0]):
            best = (starts_on, rate_minor)
    return None if best is None else best[1]
