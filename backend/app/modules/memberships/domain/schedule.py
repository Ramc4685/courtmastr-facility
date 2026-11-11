"""Pure membership arithmetic (ADR 0005 sections 2 to 6): calendar stepping, the billing schedule with
proration, re-dating after a freeze, the date-derived status and the pro-rata credit. No database, no clock.

Dates are location-local. A period covers the half-open range [starts_on, ends_on); a contract's `end_on` is its
last day, inclusive.
"""

from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.core.dates import add_interval

TAILS = ("extend_last", "drop_last", "prorate_last")


def prorate(amount_minor: int, days: int, of_days: int) -> int:
    """amount * days / of_days, rounded half-up once (overview 3.6)."""
    return (2 * amount_minor * days + of_days) // (2 * of_days)


def discounted(amount_minor: int, pct: Decimal | None, minor: int | None) -> int:
    """A per-period discount: a percentage (half-up) or a flat amount capped at the period amount."""
    if pct is not None:
        return amount_minor - int((Decimal(amount_minor) * pct / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return max(amount_minor - (minor or 0), 0)


@dataclass(frozen=True)
class Terms:
    start_on: date
    unit: str  # day | week | month | year
    interval: int
    occurrences: int
    fee_minor: int
    initiation_fee_minor: int = 0
    payment_due_day: int | None = None
    discount_pct: Decimal | None = None
    discount_minor: int | None = None
    proration_tail: str | None = None  # None = not prorated; otherwise one of TAILS


@dataclass(frozen=True)
class Period:
    kind: str  # dues | initiation | addon_item
    sequence_number: int
    starts_on: date | None
    ends_on: date | None  # exclusive
    due_on: date
    list_amount_minor: int
    amount_minor: int
    is_prorated: bool = False
    catalog_item_id: UUID | None = None  # addon_item rows: the billing pre-defined item (MEM-04)
    description: str | None = None
    revenue_category_id: UUID | None = None


def due_date(starts_on: date, payment_due_day: int | None) -> date:
    """The period start, or the first occurrence of the plan's due day on or after it (clamped to month end)."""
    if payment_due_day is None:
        return starts_on

    def in_month(first: date) -> date:
        return first.replace(day=min(payment_due_day, monthrange(first.year, first.month)[1]))

    due = in_month(starts_on)
    return due if due >= starts_on else in_month(add_interval(starts_on.replace(day=1), "month", 1))


def build_schedule(terms: Terms) -> tuple[list[Period], date]:
    """The whole receivable schedule of one term and its last day.

    Not prorated: `occurrences` full periods stepping from the start date. Prorated to the month start (only
    when the start is not already the 1st): a stub from the start to the 1st of the next month priced at
    fee * stub days / days of the full period that ends on that 1st, then full periods from the 1st; the tail
    rule decides the last one (extend_last: all `occurrences` full periods, a longer term; drop_last: one fewer,
    a shorter term; prorate_last: one fewer plus a final stub, so the term keeps its nominal length).
    """

    def step(anchor: date, n: int) -> date:
        return add_interval(anchor, terms.unit, terms.interval * n)

    def full(anchor: date, count: int) -> list[tuple[date, date, int, bool]]:
        return [(step(anchor, i), step(anchor, i + 1), terms.fee_minor, False) for i in range(count)]

    if terms.proration_tail is None or terms.start_on.day == 1:
        rows = full(terms.start_on, terms.occurrences)
    else:
        anchor = add_interval(terms.start_on.replace(day=1), "month", 1)
        stub = prorate(terms.fee_minor, (anchor - terms.start_on).days, (anchor - step(anchor, -1)).days)
        count = terms.occurrences if terms.proration_tail == "extend_last" else terms.occurrences - 1
        rows = [(terms.start_on, anchor, stub, True), *full(anchor, count)]
        last, end = step(anchor, count), step(terms.start_on, terms.occurrences)
        if terms.proration_tail == "prorate_last" and end > last:
            rows.append((last, end, prorate(terms.fee_minor, (end - last).days, (step(last, 1) - last).days), True))

    periods = [
        Period(
            "dues", number, starts, ends, due_date(starts, terms.payment_due_day), terms.fee_minor,
            discounted(amount, terms.discount_pct, terms.discount_minor), prorated,
        )
        for number, (starts, ends, amount, prorated) in enumerate(rows, start=1)
    ]  # fmt: skip
    if terms.initiation_fee_minor:
        fee = terms.initiation_fee_minor
        periods.insert(0, Period("initiation", 1, None, None, terms.start_on, fee, fee))
    return periods, rows[-1][1] - timedelta(days=1)


def redate_after_freeze(rows: list[Period], resume_on: date, unit: str, interval: int) -> list[Period]:
    """Re-date the periods a freeze withheld, given as they stood before it: the first is due on the resume
    date and the rest step by cadence from there (no realignment to the 1st, MEM-13). Rows that shared a due
    date (dues and its suspension fee) stay together. Amounts never change: a freeze moves time, not money."""
    slots = sorted({row.due_on for row in rows})
    out = []
    for row in rows:
        k = slots.index(row.due_on)
        starts = add_interval(resume_on, unit, interval * k)
        if row.starts_on is None:
            out.append(replace(row, due_on=starts))
            continue
        ends = (
            starts + (row.ends_on - row.starts_on)
            if row.is_prorated
            else add_interval(resume_on, unit, interval * (k + 1))
        )
        out.append(replace(row, due_on=starts, starts_on=starts, ends_on=ends))
    return out


Span = tuple[date, date | None]  # [first day, day after the last) with None = open-ended


def covers(spans: list[Span], on: date) -> bool:
    return any(lower <= on and (upper is None or on < upper) for lower, upper in spans)


def effective_status(
    stored: str, start_on: date, end_on: date, freezes: list[Span], suspensions: list[Span], on: date, *,
    is_gated: bool = False,
) -> str:  # fmt: skip
    """What the contract is on a date, whatever the daily job has or has not done yet. Entitlement checks use
    this, and the job converges the stored status to it. A frozen contract never expires; `is_gated` is an
    unmet activation gate (a contract document still to be accepted)."""
    if stored in ("cancelled", "expired"):
        return stored
    if on < start_on or (stored == "upcoming" and is_gated):
        return "upcoming"
    if covers(freezes, on):
        return "frozen"
    if on > end_on:
        return "expired"
    return "suspended" if covers(suspensions, on) else "active"


def unused_credit(amount_minor: int, starts_on: date, ends_on: date, last_day: date) -> int:
    """The pro-rata value of the days of [starts_on, ends_on) that fall after `last_day` (a cancel's effective
    date): the credit proposed to staff, never applied automatically (MEM-16)."""
    unused = (ends_on - max(last_day + timedelta(days=1), starts_on)).days
    return prorate(amount_minor, max(unused, 0), (ends_on - starts_on).days)


def renew_on(end_on: date, lead_count: int | None, lead_unit: str | None) -> date | None:
    """The day the renewal job creates the successor: the lead before the last day. None = never renews."""
    return None if lead_count is None or lead_unit is None else add_interval(end_on, lead_unit, -lead_count)
