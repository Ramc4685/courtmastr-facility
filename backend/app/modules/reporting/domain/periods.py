"""Relative date presets (ADR 0010 section 7): a saved report keeps `period`, and each run resolves it against
"today" at the location, so "last month" stays last month. Pure functions; the caller supplies today."""

from datetime import date, timedelta

PERIODS = ("today", "yesterday", "this_week", "last_week", "this_month", "last_month", "this_quarter", "this_year",
           "last_year", "last_30_days")  # fmt: skip
MAX_DAYS = 366


def resolve(period: str, today: date) -> tuple[date, date]:
    """Inclusive (from, to) for a preset. Weeks start on Monday."""
    if period == "today":
        return today, today
    if period == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if period in ("this_week", "last_week"):
        monday = today - timedelta(days=today.weekday()) - timedelta(weeks=period == "last_week")
        return monday, monday + timedelta(days=6)
    if period == "this_month":
        return today.replace(day=1), _month_end(today)
    if period == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if period == "this_quarter":
        start = today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1)
        return start, _month_end(start.replace(month=start.month + 2))
    if period == "this_year":
        return today.replace(month=1, day=1), today.replace(month=12, day=31)
    if period == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if period == "last_30_days":
        return today - timedelta(days=29), today
    raise ValueError(f"unknown period {period}")


def _month_end(day: date) -> date:
    following = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return following - timedelta(days=1)


BUCKETS = ("current_minor", "days_1_30_minor", "days_31_60_minor", "days_61_90_minor", "days_over_90_minor")


def aging_bucket(days_past_due: int) -> str:
    """Receivables bucket for a balance `days_past_due` days after its due date (0 or less is current)."""
    for limit, bucket in ((0, BUCKETS[0]), (30, BUCKETS[1]), (60, BUCKETS[2]), (90, BUCKETS[3])):
        if days_past_due <= limit:
            return bucket
    return BUCKETS[4]
