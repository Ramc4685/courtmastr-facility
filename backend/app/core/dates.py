"""Calendar stepping shared by every context that sells something with a term (overview 3.7)."""

from calendar import monthrange
from datetime import date, timedelta


def add_interval(anchor: date, unit: str, count: int) -> date:
    """anchor + count units (day | week | month | year; count may be negative). Months and years step from the
    anchor's own day, clamped to the month end, so a term anchored on the 31st bills 28/29 Feb and then 31 Mar
    (never drifting to the 28th)."""
    if unit == "day":
        return anchor + timedelta(days=count)
    if unit == "week":
        return anchor + timedelta(weeks=count)
    year, month = divmod(anchor.year * 12 + anchor.month - 1 + count * (12 if unit == "year" else 1), 12)
    return date(year, month + 1, min(anchor.day, monthrange(year, month + 1)[1]))
