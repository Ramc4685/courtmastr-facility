"""Pre-defined item recurrence (BIL-14): pure domain logic."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.billing.domain import recurrence as r


def _monthly(start: date, count: int):
    return r.occurrences(start, kind="recurring", recurrence_unit="month", recurrence_every=1, recurrence_count=count)


def test_monthly_occurrences_step_from_the_anchor_and_clamp_to_month_end():
    got = _monthly(date(2026, 1, 31), 3)
    assert got == [
        (date(2026, 1, 31), date(2026, 2, 27)),
        (date(2026, 2, 28), date(2026, 3, 30)),
        (date(2026, 3, 31), date(2026, 4, 29)),
    ]
    assert r.term_end(got) == date(2026, 4, 29)


def test_every_two_weeks():
    got = r.occurrences(
        date(2026, 11, 2), kind="recurring", recurrence_unit="week", recurrence_every=2, recurrence_count=2
    )
    assert got == [(date(2026, 11, 2), date(2026, 11, 15)), (date(2026, 11, 16), date(2026, 11, 29))]


def test_one_off_with_and_without_a_length():
    assert r.occurrences(date(2026, 11, 1), kind="one_off") == [(date(2026, 11, 1), None)]
    assert r.occurrences(date(2026, 11, 1), kind="one_off", length_count=1, length_unit="year") == [
        (date(2026, 11, 1), date(2027, 10, 31))
    ]


def test_recurrence_is_bounded():
    with pytest.raises(ValueError):
        r.occurrences(
            date(2026, 1, 1), kind="recurring", recurrence_unit="day", recurrence_every=1, recurrence_count=367
        )


def test_renew_on_and_discount():
    assert r.renew_on(date(2026, 12, 31), 0) == date(2027, 1, 1)
    assert r.renew_on(date(2026, 12, 31), 7) == date(2026, 12, 25)
    assert r.renew_on(None, 7) is None
    assert r.discount(2999, Decimal("10"), None) == 300  # 299.9 rounds half-up once
    assert r.discount(1000, None, 1500) == 1000
    assert r.discount(1000, None, None) == 0
