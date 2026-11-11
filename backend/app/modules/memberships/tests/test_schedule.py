"""The pure schedule arithmetic (ADR 0005 sections 2 to 6): calendar stepping, proration by tail rule, due dates,
discounts, re-dating after a freeze, the date-derived status and the cancel credit."""

from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise, product

import pytest

from app.modules.memberships.domain.schedule import (
    TAILS,
    Period,
    Terms,
    add_interval,
    build_schedule,
    discounted,
    due_date,
    effective_status,
    prorate,
    redate_after_freeze,
    renew_on,
    unused_credit,
)

D = date


@pytest.mark.parametrize(
    ("anchor", "unit", "count", "expected"),
    [
        (D(2025, 1, 31), "month", 1, D(2025, 2, 28)),
        (D(2024, 1, 31), "month", 1, D(2024, 2, 29)),  # leap year
        (D(2025, 1, 31), "month", 2, D(2025, 3, 31)),  # steps from the anchor: back on the 31st, no drift
        (D(2025, 1, 31), "month", 3, D(2025, 4, 30)),
        (D(2025, 11, 30), "month", 3, D(2026, 2, 28)),  # across the year end
        (D(2025, 3, 31), "month", -1, D(2025, 2, 28)),
        (D(2025, 1, 15), "month", -1, D(2024, 12, 15)),
        (D(2024, 2, 29), "year", 1, D(2025, 2, 28)),
        (D(2024, 2, 29), "year", 4, D(2028, 2, 29)),
        (D(2025, 1, 1), "week", 2, D(2025, 1, 15)),
        (D(2025, 12, 31), "day", 1, D(2026, 1, 1)),
    ],
)
def test_add_interval_clamps_to_month_end_without_drifting(anchor, unit, count, expected):
    assert add_interval(anchor, unit, count) == expected


@pytest.mark.parametrize(
    ("amount", "days", "of", "expected"),
    [(3100, 17, 31, 1700), (1000, 17, 31, 548), (999, 1, 2, 500), (1, 1, 2, 1), (1, 1, 3, 0), (5000, 0, 30, 0), (5000, 30, 30, 5000)],
)  # fmt: skip
def test_prorate_rounds_half_up_once(amount, days, of, expected):
    assert prorate(amount, days, of) == expected


def test_discount_is_a_percentage_or_a_capped_flat_amount():
    assert discounted(3333, Decimal("10"), None) == 3000  # 333.3 rounds to 333
    assert discounted(1000, Decimal("12.5"), None) == 875
    assert discounted(1005, Decimal("50"), None) == 502  # 502.5 off rounds half-up to 503
    assert discounted(1000, None, 250) == 750
    assert discounted(100, None, 250) == 0
    assert discounted(1000, None, None) == 1000


@pytest.mark.parametrize(
    ("starts", "due_day", "expected"),
    [
        (D(2025, 1, 20), None, D(2025, 1, 20)),
        (D(2025, 1, 10), 15, D(2025, 1, 15)),
        (D(2025, 1, 20), 15, D(2025, 2, 15)),  # never before the period starts
        (D(2025, 2, 1), 31, D(2025, 2, 28)),  # clamped to the month end
        (D(2025, 12, 20), 5, D(2026, 1, 5)),
        (D(2025, 3, 15), 15, D(2025, 3, 15)),
    ],
)
def test_due_date_is_the_first_due_day_on_or_after_the_period_start(starts, due_day, expected):
    assert due_date(starts, due_day) == expected


def _monthly(start: date, tail: str | None, occurrences: int = 12, fee: int = 3100, **extra) -> Terms:
    return Terms(start, "month", 1, occurrences, fee, proration_tail=tail, **extra)


def test_unprorated_schedule_bills_on_the_start_day_and_survives_short_months():
    periods, end_on = build_schedule(_monthly(D(2025, 1, 31), None))
    assert [p.starts_on for p in periods[:4]] == [D(2025, 1, 31), D(2025, 2, 28), D(2025, 3, 31), D(2025, 4, 30)]
    assert len(periods) == 12 and end_on == D(2026, 1, 30)
    assert sum(p.amount_minor for p in periods) == 12 * 3100 and not any(p.is_prorated for p in periods)
    assert [p.sequence_number for p in periods] == list(range(1, 13)) and all(p.due_on == p.starts_on for p in periods)


def test_proration_tails_from_a_mid_month_start():
    """Fee 3100 in a 31-day month is 100 a day: the stub from the 15th to the 1st is 17 days."""
    start = D(2025, 1, 15)
    extend, extend_end = build_schedule(_monthly(start, "extend_last"))
    assert (extend[0].starts_on, extend[0].ends_on, extend[0].amount_minor, extend[0].is_prorated) == (
        start, D(2025, 2, 1), 1700, True)  # fmt: skip
    assert len(extend) == 13 and extend_end == D(2026, 1, 31)  # all twelve full periods: a longer term
    assert sum(p.amount_minor for p in extend) == 1700 + 12 * 3100
    assert [p.starts_on.day for p in extend[1:]] == [1] * 12

    drop, drop_end = build_schedule(_monthly(start, "drop_last"))
    assert len(drop) == 12 and drop_end == D(2025, 12, 31)  # one full period fewer: a shorter term
    assert sum(p.amount_minor for p in drop) == 1700 + 11 * 3100

    both, both_end = build_schedule(_monthly(start, "prorate_last"))
    assert len(both) == 13 and both_end == D(2026, 1, 14)  # the nominal twelve months exactly
    assert (both[-1].starts_on, both[-1].ends_on, both[-1].amount_minor, both[-1].is_prorated) == (
        D(2026, 1, 1), D(2026, 1, 15), 1400, True)  # fmt: skip
    assert sum(p.amount_minor for p in both) == 12 * 3100  # two stubs make one whole month here


@pytest.mark.parametrize(
    ("start", "fee", "stub"),
    [
        (D(2024, 2, 10), 2900, 2000),  # leap February: 20 of 29 days
        (D(2025, 2, 10), 2800, 1900),  # 19 of 28 days
        (D(2025, 4, 30), 3000, 100),  # one day of 30
        (D(2025, 12, 2), 3100, 3000),  # 30 of 31, the stub crosses the year end
        (D(2025, 6, 16), 9999, 4999),  # 15 of 30 = 4999.5 half-up... on the integer product: 4999.5 -> 5000
    ],
)
def test_stub_divides_by_the_actual_days_of_the_month(start, fee, stub):
    periods, _ = build_schedule(_monthly(start, "extend_last", fee=fee))
    expected = 5000 if fee == 9999 else stub
    assert periods[0].amount_minor == expected and periods[1].starts_on.day == 1


def test_a_start_on_the_first_is_never_prorated():
    for tail in TAILS:
        periods, end_on = build_schedule(_monthly(D(2025, 3, 1), tail))
        assert len(periods) == 12 and end_on == D(2026, 2, 28) and not any(p.is_prorated for p in periods)


def test_proration_of_quarterly_and_yearly_plans_uses_the_full_period_before_the_anchor():
    quarterly, end_on = build_schedule(Terms(D(2025, 2, 15), "month", 3, 4, 9000, proration_tail="extend_last"))
    # anchor 1 March; the quarter that ends there is 1 Dec to 1 Mar = 90 days; the stub is 14 days
    assert quarterly[0].amount_minor == prorate(9000, 14, 90) == 1400
    assert [p.starts_on for p in quarterly[1:]] == [D(2025, 3, 1), D(2025, 6, 1), D(2025, 9, 1), D(2025, 12, 1)]
    assert end_on == D(2026, 2, 28)
    yearly, end_on = build_schedule(Terms(D(2025, 7, 17), "year", 1, 1, 36500, proration_tail="prorate_last"))
    assert [(p.starts_on, p.ends_on) for p in yearly] == [
        (D(2025, 7, 17), D(2025, 8, 1)),
        (D(2025, 8, 1), D(2026, 7, 17)),
    ]
    assert yearly[0].amount_minor == prorate(36500, 15, 365) == 1500 and end_on == D(2026, 7, 16)
    assert yearly[1].amount_minor == prorate(36500, 350, 365) == 35000


def test_one_occurrence_plans_with_each_tail():
    start = D(2025, 1, 15)
    assert [len(build_schedule(_monthly(start, tail, occurrences=1))[0]) for tail in TAILS] == [2, 1, 2]
    assert build_schedule(_monthly(start, "drop_last", occurrences=1))[1] == D(2025, 1, 31)
    assert build_schedule(_monthly(start, "prorate_last", occurrences=1))[1] == D(2025, 2, 14)


def test_initiation_fee_discount_and_due_day():
    terms = _monthly(
        D(2025, 1, 15), "extend_last", occurrences=3, initiation_fee_minor=5000, payment_due_day=5,
        discount_pct=Decimal("10"),
    )  # fmt: skip
    periods, _ = build_schedule(terms)
    first, stub, full = periods[0], periods[1], periods[2]
    assert (first.kind, first.amount_minor, first.due_on, first.starts_on) == ("initiation", 5000, D(2025, 1, 15), None)
    assert (stub.list_amount_minor, stub.amount_minor) == (3100, 1530)  # 1700 less 10 percent
    assert stub.due_on == D(2025, 2, 5) and full.due_on == D(2025, 2, 5) and full.amount_minor == 2790
    flat, _ = build_schedule(_monthly(D(2025, 1, 1), None, occurrences=2, discount_minor=100))
    assert [p.amount_minor for p in flat] == [3000, 3000]


def test_schedule_invariants_hold_for_every_start_cadence_and_tail():
    """Property test: periods tile [start, end] with no gap or overlap, sequence numbers run 1..n, only the first
    and last can be prorated, a prorated amount never exceeds the fee, and the term length follows the tail."""
    starts = [D(2023, 1, 1) + timedelta(days=11 * n) for n in range(100)]  # every day of month, leap year included
    cases = 0
    for start, (unit, interval), occurrences, tail in product(
        starts, (("month", 1), ("month", 3), ("year", 1)), (1, 2, 12), (None, *TAILS)
    ):
        periods, end_on = build_schedule(Terms(start, unit, interval, occurrences, 9973, proration_tail=tail))
        assert periods[0].starts_on == start and periods[-1].ends_on == end_on + timedelta(days=1)
        assert all(a.ends_on == b.starts_on and a.starts_on < a.ends_on for a, b in pairwise(periods))
        assert [p.sequence_number for p in periods] == list(range(1, len(periods) + 1))
        assert all(0 <= p.amount_minor <= 9973 for p in periods)
        assert all(p.amount_minor == 9973 for p in periods if not p.is_prorated)
        assert not any(p.is_prorated for p in periods[1:-1])
        stubbed = tail is not None and start.day != 1
        anchor = add_interval(start.replace(day=1), "month", 1)
        full = [p for p in periods if not p.is_prorated]
        if not stubbed:
            assert len(periods) == occurrences and end_on == add_interval(
                start, unit, interval * occurrences
            ) - timedelta(days=1)
        elif tail == "extend_last":
            assert len(full) == occurrences and end_on == add_interval(
                anchor, unit, interval * occurrences
            ) - timedelta(days=1)
        elif tail == "drop_last":
            assert len(full) == occurrences - 1 and end_on == add_interval(
                anchor, unit, interval * (occurrences - 1)
            ) - timedelta(days=1)
        else:
            assert len(full) == occurrences - 1 and end_on == add_interval(
                start, unit, interval * occurrences
            ) - timedelta(days=1)
        cases += 1
    assert cases == 100 * 3 * 3 * 4


def test_weekly_and_daily_cadences():
    weekly, end_on = build_schedule(Terms(D(2025, 3, 3), "week", 2, 3, 500))
    assert [p.starts_on for p in weekly] == [D(2025, 3, 3), D(2025, 3, 17), D(2025, 3, 31)] and end_on == D(2025, 4, 13)
    one, end_on = build_schedule(Terms(D(2025, 3, 3), "day", 10, 1, 500))  # an edited end date: one period of N days
    assert (one[0].starts_on, one[0].ends_on, end_on) == (D(2025, 3, 3), D(2025, 3, 13), D(2025, 3, 12))


def test_redate_after_freeze_restarts_on_the_resume_date_and_never_changes_money():
    before, _ = build_schedule(_monthly(D(2025, 1, 15), "prorate_last", occurrences=4))
    withheld = [*before[2:], Period("suspension_fee", 1, None, None, before[3].due_on, 700, 700)]
    after = redate_after_freeze(withheld, D(2025, 3, 20), "month", 1)
    dues = [p for p in after if p.kind == "dues"]
    assert [p.due_on for p in dues] == [D(2025, 3, 20), D(2025, 4, 20), D(2025, 5, 20)]  # no realignment to the 1st
    assert [(p.starts_on, p.ends_on) for p in dues[:2]] == [
        (D(2025, 3, 20), D(2025, 4, 20)),
        (D(2025, 4, 20), D(2025, 5, 20)),
    ]
    assert (dues[2].ends_on - dues[2].starts_on).days == 14 and dues[2].is_prorated  # the final stub keeps its length
    assert after[-1].due_on == D(2025, 4, 20)  # the fee stays beside the dues it was billed with
    assert sum(p.amount_minor for p in after) == sum(p.amount_minor for p in withheld)
    assert redate_after_freeze([], D(2025, 3, 20), "month", 1) == []


@pytest.mark.parametrize(
    ("stored", "on", "freezes", "suspensions", "gated", "expected"),
    [
        ("upcoming", D(2025, 1, 31), [], [], False, "upcoming"),
        ("upcoming", D(2025, 2, 1), [], [], False, "active"),  # the job is late: the date decides
        ("upcoming", D(2025, 2, 1), [], [], True, "upcoming"),  # document not accepted yet
        ("active", D(2025, 2, 1), [], [], True, "active"),  # a gate only holds a contract that never started
        ("active", D(2025, 3, 10), [(D(2025, 3, 10), D(2025, 3, 20))], [], False, "frozen"),
        ("active", D(2025, 3, 20), [(D(2025, 3, 10), D(2025, 3, 20))], [], False, "active"),  # upper bound is exclusive
        ("frozen", D(2026, 6, 1), [(D(2025, 3, 10), None)], [], False, "frozen"),  # a frozen contract never expires
        ("active", D(2025, 4, 1), [], [(D(2025, 4, 1), None)], False, "suspended"),
        ("suspended", D(2026, 2, 1), [], [(D(2025, 4, 1), None)], False, "expired"),
        ("active", D(2026, 1, 31), [], [], False, "active"),  # the last day is inclusive
        ("active", D(2026, 2, 1), [], [], False, "expired"),
        ("cancelled", D(2025, 6, 1), [], [], False, "cancelled"),
        ("expired", D(2025, 6, 1), [], [], False, "expired"),
    ],
)
def test_effective_status_follows_the_dates(stored, on, freezes, suspensions, gated, expected):
    got = effective_status(stored, D(2025, 2, 1), D(2026, 1, 31), freezes, suspensions, on, is_gated=gated)
    assert got == expected


def test_unused_credit_is_the_pro_rata_value_of_the_days_after_the_last_day():
    january = (D(2025, 1, 1), D(2025, 2, 1))
    assert unused_credit(3100, *january, D(2025, 1, 10)) == 2100
    assert unused_credit(3100, *january, D(2025, 1, 31)) == 0
    assert unused_credit(3100, *january, D(2024, 12, 31)) == 3100  # cancelled before the period began
    assert unused_credit(3100, *january, D(2025, 3, 1)) == 0
    assert unused_credit(1000, D(2025, 2, 1), D(2025, 3, 1), D(2025, 2, 14)) == 500


def test_renew_on_is_the_lead_before_the_last_day():
    assert renew_on(D(2025, 12, 31), 30, "day") == D(2025, 12, 1)
    assert renew_on(D(2025, 3, 31), 1, "month") == D(2025, 2, 28)
    assert renew_on(D(2025, 12, 31), 0, "day") == D(2025, 12, 31)
    assert renew_on(D(2025, 12, 31), None, None) is None
