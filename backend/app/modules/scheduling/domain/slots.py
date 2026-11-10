"""Free-time arithmetic for the availability read (ADR 0004 section 7): pure functions over instants."""

from datetime import date, datetime, timedelta

Interval = tuple[datetime, datetime]


def window_fires_on(day: date, starts_on: date, ends_on: date | None, weekdays: list[int], interval_weeks: int) -> bool:
    """Does a weekly availability rule apply on a local date? Weeks count from the ISO week of starts_on."""
    if day < starts_on or (ends_on is not None and day > ends_on) or day.isoweekday() not in weekdays:
        return False
    first_monday = starts_on - timedelta(days=starts_on.isoweekday() - 1)
    return ((day - first_monday).days // 7) % interval_weeks == 0


def merge(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract(open_: list[Interval], busy: list[Interval], min_minutes: int = 1) -> list[Interval]:
    """Open time minus busy time, as merged intervals of at least min_minutes."""
    free: list[Interval] = []
    busy = merge(busy)
    for start, end in merge(open_):
        cursor = start
        for busy_start, busy_end in busy:
            if busy_end <= cursor or busy_start >= end:
                continue
            if busy_start > cursor:
                free.append((cursor, busy_start))
            cursor = max(cursor, busy_end)
        if cursor < end:
            free.append((cursor, end))
    return [(s, e) for s, e in free if (e - s) >= timedelta(minutes=min_minutes)]
