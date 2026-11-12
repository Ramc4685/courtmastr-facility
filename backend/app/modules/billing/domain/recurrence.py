"""Pre-defined items (BIL-14), pure: the occurrences one sale expands into, its term end, its renewal date
and the per-occurrence discount. No database, no clock."""

from datetime import date, timedelta
from decimal import Decimal

from app.core.dates import add_interval
from app.modules.billing.domain.money import round_half_up

_DAY = timedelta(days=1)
MAX_OCCURRENCES = 366


def occurrences(
    starts_on: date,
    *,
    kind: str,
    length_count: int | None = None,
    length_unit: str | None = None,
    recurrence_unit: str | None = None,
    recurrence_every: int | None = None,
    recurrence_count: int | None = None,
) -> list[tuple[date, date | None]]:
    """(first day, last day) per occurrence. A one-off is one occurrence, open-ended without a length. Each
    recurring occurrence steps from the start date itself, so a term anchored on the 31st never drifts."""
    if kind == "one_off":
        if length_count is None:
            return [(starts_on, None)]
        return [(starts_on, add_interval(starts_on, length_unit, length_count) - _DAY)]
    if not 1 <= recurrence_count <= MAX_OCCURRENCES or recurrence_every < 1:
        raise ValueError("recurrence out of range")
    step, unit = recurrence_every, recurrence_unit
    return [
        (add_interval(starts_on, unit, step * i), add_interval(starts_on, unit, step * (i + 1)) - _DAY)
        for i in range(recurrence_count)
    ]


def term_end(periods: list[tuple[date, date | None]]) -> date | None:
    return periods[-1][1]


def renew_on(ends_on: date | None, lead_days: int) -> date | None:
    """The renewal job's due day: the day after the term, less the lead."""
    return None if ends_on is None else ends_on + _DAY - timedelta(days=lead_days)


def discount(fee_minor: int, discount_pct: Decimal | None, discount_minor: int | None) -> int:
    """Per occurrence, never more than the fee. A percentage rounds half-up once, on the line."""
    if discount_minor is not None:
        return min(discount_minor, fee_minor)
    if discount_pct is not None:
        return min(round_half_up(Decimal(fee_minor) * Decimal(discount_pct) / 100), fee_minor)
    return 0
