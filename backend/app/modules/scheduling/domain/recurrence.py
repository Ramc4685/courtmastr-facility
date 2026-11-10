"""Recurrence and local-time arithmetic: pure functions over naive wall times (ADR 0004 sections 6 and 10).

A series is expanded in the location's wall time and each occurrence is localised on its own, so a weekly
18:00 class stays at 18:00 across both DST changes. A nonexistent wall time moves forward to the next valid
instant; an ambiguous one takes its first occurrence (overview 3.7).
"""

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

HORIZON_DAYS = 3 * 366  # a pass may not reach further than three years from its first candidate
_MINUTE = timedelta(minutes=1)


class RuleError(ValueError):
    """The rule is not expandable as given; `code` is the API problem code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class Rule:
    pattern: str  # single | daily | weekly | monthly_by_date | monthly_by_weekday | yearly
    start_on: date
    interval_count: int = 1
    weekdays: tuple[int, ...] = ()  # ISO, 1 = Monday
    month_week: int | None = None  # 1..5 or -1 (last)
    range_type: str = "count"  # count | until
    occurrence_limit: int | None = None
    until_on: date | None = None


def _add_months(year: int, month: int, count: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + count
    return index // 12, index % 12 + 1


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date | None:
    days = [
        d for d in range(1, calendar.monthrange(year, month)[1] + 1) if date(year, month, d).isoweekday() == weekday
    ]
    if nth == -1:
        return date(year, month, days[-1])
    return date(year, month, days[nth - 1]) if nth <= len(days) else None


def _candidates(rule: Rule):
    """(date, is_occurrence) in order, without end: the caller stops the iteration."""
    start, step = rule.start_on, rule.interval_count
    if rule.pattern == "daily":
        day = start
        while True:
            yield day, not rule.weekdays or day.isoweekday() in rule.weekdays
            day += timedelta(days=step if not rule.weekdays else 1)
    elif rule.pattern == "weekly":
        monday = start - timedelta(days=start.isoweekday() - 1)
        while True:
            for weekday in sorted(rule.weekdays or (start.isoweekday(),)):
                day = monday + timedelta(days=weekday - 1)
                if day >= start:
                    yield day, True
            monday += timedelta(weeks=step)
    elif rule.pattern in ("monthly_by_date", "monthly_by_weekday", "yearly"):
        months, count = (12 if rule.pattern == "yearly" else 1) * step, 0
        while True:
            year, month = _add_months(start.year, start.month, count * months)
            count += 1
            if rule.pattern == "monthly_by_weekday":
                weekday = rule.weekdays[0] if rule.weekdays else start.isoweekday()
                day = _nth_weekday(year, month, weekday, rule.month_week or (start.day - 1) // 7 + 1)
            else:  # a month without the day (the 31st, 29 February) is skipped, as RFC 5545 does
                day = date(year, month, start.day) if start.day <= calendar.monthrange(year, month)[1] else None
            # A skipped month still reports its first day, so the caller's end checks see time passing.
            yield (day, True) if day is not None and day >= start else (date(year, month, 1), False)
    else:
        raise RuleError("validation-failed", f"Unknown pattern {rule.pattern}.")


def expand(rule: Rule, max_count: int) -> list[date]:
    """Local dates of every occurrence of one pass. Raises RuleError when the pass is longer than max_count
    or reaches past the three-year horizon."""
    if rule.pattern == "single":
        return [rule.start_on]
    if rule.interval_count < 1:
        raise RuleError("validation-failed", "interval_count must be at least 1.")
    if rule.range_type == "count":
        if not rule.occurrence_limit or rule.occurrence_limit < 1:
            raise RuleError("validation-failed", "occurrence_limit is required for a count range.")
        if rule.occurrence_limit > max_count:
            raise RuleError("series-too-long", f"A series is at most {max_count} occurrences.")
    elif rule.until_on is None or rule.until_on < rule.start_on:
        raise RuleError("validation-failed", "until_on must be on or after the first date.")
    horizon = rule.start_on + timedelta(days=HORIZON_DAYS)
    if rule.range_type == "until" and rule.until_on > horizon:
        raise RuleError("series-too-long", "A series may not reach further than three years.")
    dates: list[date] = []
    for day, is_occurrence in _candidates(rule):
        if rule.range_type == "until" and day > rule.until_on:
            break
        if day > horizon:
            raise RuleError("series-too-long", "A series may not reach further than three years.")
        if not is_occurrence:
            continue
        dates.append(day)
        if rule.range_type == "count" and len(dates) == rule.occurrence_limit:
            break
        if len(dates) > max_count:
            raise RuleError("series-too-long", f"A series is at most {max_count} occurrences.")
    return dates


def parse_wall(value: str | time) -> tuple[time, int]:
    """'HH:MM' -> (time, extra days); '24:00' is midnight at the end of the day."""
    if isinstance(value, time):
        return value, 0
    hours, minutes = (int(part) for part in value[:5].split(":"))
    return (time(0, minutes), 1) if hours == 24 else (time(hours, minutes), 0)


def localize(day: date, wall: time, zone: ZoneInfo) -> datetime:
    """The UTC instant of a local wall time. Gap: the next valid instant. Fold: the first occurrence."""
    naive = datetime.combine(day, wall)
    instant = naive.replace(tzinfo=zone).astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) == naive:
        return instant
    after = instant.astimezone(zone).utcoffset()  # the wall time does not exist: walk back to the transition
    while (instant - _MINUTE).astimezone(zone).utcoffset() == after:
        instant -= _MINUTE
    return instant


def local_parts(instant: datetime, zone: ZoneInfo) -> tuple[date, time]:
    local = instant.astimezone(zone)
    return local.date(), local.time().replace(tzinfo=None)


def span(day: date, start: time, duration_min: int, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Start and end instants of an occurrence that starts at a wall time and lasts a nominal duration. Both
    ends are resolved as wall times; when that collapses the range (both in a DST gap) the end is start plus
    the duration."""
    starts_at = localize(day, start, zone)
    end_naive = datetime.combine(day, start) + timedelta(minutes=duration_min)
    ends_at = localize(end_naive.date(), end_naive.time(), zone)
    if ends_at <= starts_at:
        ends_at = starts_at + timedelta(minutes=duration_min)
    return starts_at, ends_at


def nominal_minutes(start: time, end: time, end_day_offset: int = 0) -> int:
    base = date(2000, 1, 1)
    delta = datetime.combine(base + timedelta(days=end_day_offset), end) - datetime.combine(base, start)
    return int(delta.total_seconds() // 60)
