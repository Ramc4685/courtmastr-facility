"""Pure pay arithmetic for payroll runs (STF-02 to STF-06, STF-10, STF-15). Money is integer minor units,
rounded half-up once per line (ADR 0003). No database access: the service gathers the facts."""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta, tzinfo
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


def session_lines(rate: Any, default: Any, minutes: int, attendees: int, comp_attendees: int = 0) -> list[dict]:
    """The pay lines for one completed trainer session under the chosen pay-rate row (`default` is the payee's
    default row, possibly the same row, or None).

    A session nobody attended pays the default row's flat non-training hourly rate when one is set. An attendee
    whose credit came from a complimentary package is a comp attendee: `per_attendee` pays the flat comp rate per
    comp attendee and the prorated rate per other attendee; `per_session` pays the comp rate once only when every
    attendee is a comp attendee, else the prorated rate once. A row with no comp rate takes the default row's;
    with neither, comp attendees are paid as normal."""
    if attendees == 0:
        nt = default.non_training_rate_minor if default is not None else None
        if not nt:
            return []
        return [{"kind": "non_training", "quantity": Decimal(minutes) / 60, "rate_minor": nt,
                 "amount_minor": per_hour(nt, minutes)}]  # fmt: skip
    comp_rate = rate.comp_session_rate_minor or (default.comp_session_rate_minor if default is not None else 0)
    comp = min(comp_attendees, attendees) if comp_rate else 0
    if rate.pay_basis == "per_attendee":
        comp_count, paid_count = comp, attendees - comp
    else:
        comp_count, paid_count = (1, 0) if comp == attendees else (0, 1)
    lines = []
    if comp_count:
        lines.append({"kind": "comp_session", "quantity": Decimal(comp_count), "rate_minor": comp_rate,
                      "amount_minor": comp_rate * comp_count})  # fmt: skip
    rates = {60: rate.rate_60_minor, 45: rate.rate_45_minor, 30: rate.rate_30_minor}
    anchor, base = anchored_rate(rates, minutes)
    each = prorated(base, anchor, minutes)
    if paid_count and each:
        lines.append({"kind": "session", "quantity": Decimal(paid_count), "rate_minor": each,
                      "amount_minor": each * paid_count})  # fmt: skip
    return lines


def block_line(rate: Any, block_kind: str, minutes: int) -> dict | None:
    """Pay for a trainer's time block: a floor shift pays the hourly floor rate, a flat activity (an instruction
    block) pays the flat per-block rate whatever its length. Unpaid and unavailable blocks earn nothing."""
    if block_kind == "floor_shift" and rate.floor_rate_minor:
        return {"kind": "floor", "quantity": Decimal(minutes) / 60, "rate_minor": rate.floor_rate_minor,
                "amount_minor": per_hour(rate.floor_rate_minor, minutes)}  # fmt: skip
    if block_kind == "instruction" and rate.program_instruction_rate_minor:
        return {"kind": "program_instruction", "quantity": Decimal(1),
                "rate_minor": rate.program_instruction_rate_minor,
                "amount_minor": rate.program_instruction_rate_minor}  # fmt: skip
    return None


def pick_pay_rate(rates: dict[tuple[Any, Any], Any], reservation_type_id: Any, membership_type_id: Any) -> Any | None:
    """The pay-rate row for a session, keyed (reservation type, membership type): the service's own row, then the
    client's membership-type row, then the payee's default row."""
    return (
        (rates.get((reservation_type_id, None)) if reservation_type_id is not None else None)
        or (rates.get((None, membership_type_id)) if membership_type_id is not None else None)
        or rates.get((None, None))
    )


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


def trained_hours_bonus(trained_minutes: int, threshold_minutes: int, amount_minor: int) -> int:
    """A flat bonus once trained time in the period reaches the threshold; meeting it exactly earns it."""
    return amount_minor if trained_minutes > 0 and trained_minutes >= threshold_minutes else 0


def _wall(day: date, minute: int, zone: tzinfo) -> datetime:
    """`minute` minutes after local midnight of `day` as an aware instant (1440 is the next midnight)."""
    return datetime.combine(day + timedelta(days=minute // 1440), time(minute % 1440 // 60, minute % 60), zone)


def off_hours_minutes(
    starts: datetime, ends: datetime, zone: tzinfo, weekdays: Sequence[int], from_minute: int, to_minute: int
) -> int:
    """Real minutes of a session (aware instants) inside the off-hours window of each local calendar day it
    touches in `zone`, on the listed weekdays (Monday 0). The window is minutes after local midnight, `to_minute`
    up to 1440. Elapsed time is measured in UTC, so a daylight-saving change counts the time that really passed."""
    lo_utc, hi_utc = starts.astimezone(UTC), ends.astimezone(UTC)
    day, last = starts.astimezone(zone).date(), ends.astimezone(zone).date()
    total = 0
    while day <= last:
        if day.weekday() in weekdays:
            a = max(lo_utc, _wall(day, from_minute, zone).astimezone(UTC))
            b = min(hi_utc, _wall(day, to_minute, zone).astimezone(UTC))
            total += max(0, int((b - a).total_seconds() // 60))
        day += timedelta(days=1)
    return total


def overlap_minutes(starts: datetime, ends: datetime, spans: Iterable[tuple[datetime, datetime]]) -> int:
    """Minutes of [starts, ends) covered by any of `spans`, each minute once even where spans overlap each other."""
    total, reach = 0, starts
    for a, b in sorted(spans):
        a, b = max(a, reach), min(b, ends)
        if b > a:
            total += int((b - a).total_seconds() // 60)
            reach = b
    return total


def off_hours_bonus(minutes: int, rate_minor: int) -> int:
    """The off-hours bonus is an extra hourly rate over the minutes inside the window."""
    return per_hour(rate_minor, minutes)


def shift_variance(starts: datetime, ends: datetime, entries: Iterable[tuple[datetime, datetime | None]]) -> dict:
    """Published shift against the employee's time entries: scheduled minutes, minutes worked inside the shift
    (entries clipped to it; an open entry counts nothing) and the difference."""
    scheduled = int((ends - starts).total_seconds() // 60)
    worked = 0
    first = last = None
    for entry_in, entry_out in entries:
        if entry_out is None:
            continue
        lo, hi = max(starts, entry_in), min(ends, entry_out)
        if hi > lo:
            worked += int((hi - lo).total_seconds() // 60)
            first = lo if first is None else min(first, lo)
            last = hi if last is None else max(last, hi)
    return {"scheduled_minutes": scheduled, "worked_minutes": worked, "variance_minutes": worked - scheduled,
            "first_in_at": first, "last_out_at": last}  # fmt: skip
