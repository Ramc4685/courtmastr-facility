"""The pure pricing function (RNT-02): golden cases for rule precedence, bands, discounts, bases, grouping,
occurrence shares and the clock change. No database."""

from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.modules.rentals.domain.pricing import Occurrence, Rate, Rule, apply_discount, deposit_of, price, tax_of

CHI = ZoneInfo("America/Chicago")
COURT, COURT2 = uuid4(), uuid4()


def occ(index: int, day: int, start: float, end: float, resources=(COURT,), month: int = 5, year: int = 2031):
    def wall(hours: float) -> datetime:
        return datetime(year, month, day, int(hours), int(round((hours % 1) * 60)), tzinfo=CHI)

    return Occurrence(index, wall(start), wall(end), tuple(resources))


def evening(amount: int = 5000, order: int = 0, **extra) -> Rule:
    return Rule(
        id=uuid4(), kind="rate", sort_order=order, start_time=time(17), end_time=None, amount_minor=amount, **extra
    )


def test_base_rate_per_hour():
    [line] = price(Rate(None, "Std", 4000, "per_hour"), [occ(0, 5, 9, 10.5)])
    assert (line.quantity, line.unit_amount_minor, line.amount_minor) == (Decimal("1.50"), 4000, 6000)
    assert line.items == [(0, COURT, 6000)]


def test_band_splits_an_occurrence_and_lines_never_mix_prices():
    rate = Rate(None, "Std", 4000, "per_hour", rules=(evening(),))
    lines = price(rate, [occ(0, 5, 16, 18.5)])
    assert [(line.unit_amount_minor, line.quantity, line.amount_minor) for line in lines] == [
        (5000, Decimal("1.50"), 7500), (4000, Decimal("1.00"), 4000),
    ]  # fmt: skip
    assert lines[0].applied_rule_id == rate.rules[0].id and lines[1].applied_rule_id is None


def test_first_matching_rate_rule_by_sort_order_wins():
    weekend = Rule(id=uuid4(), kind="rate", sort_order=0, weekdays=(6, 7), amount_minor=6000)
    late = evening(5000, order=1)
    rate = Rate(None, "Std", 4000, "per_hour", rules=(late, weekend))  # given out of order on purpose
    [saturday_night] = price(rate, [occ(0, 10, 18, 19)])  # 2031-05-10 is a Saturday: weekend outranks evening
    assert saturday_night.unit_amount_minor == 6000 and saturday_night.applied_rule_id == weekend.id
    [monday_night] = price(rate, [occ(0, 5, 18, 19)])
    assert monday_night.unit_amount_minor == 5000


def test_date_range_and_membership_rules():
    season = Rule(id=uuid4(), kind="rate", starts_on=date(2031, 6, 1), ends_on=date(2031, 8, 31), amount_minor=3000)
    gold = uuid4()
    member = Rule(id=uuid4(), kind="rate", sort_order=-1, membership_type_id=gold, amount_minor=1000)
    rate = Rate(None, "Std", 4000, "per_hour", member_amount_minor=3500, rules=(season, member))
    assert price(rate, [occ(0, 5, 9, 10)])[0].unit_amount_minor == 4000
    assert price(rate, [occ(0, 5, 9, 10, month=7)])[0].unit_amount_minor == 3000
    member_line = price(rate, [occ(0, 5, 9, 10)], is_member=True)[0]
    assert member_line.unit_amount_minor == 3500 and member_line.is_member_price
    assert price(rate, [occ(0, 5, 9, 10)], is_member=True, member_types=frozenset({gold}))[0].unit_amount_minor == 1000


def test_discount_rules_add_up_and_are_capped_at_the_unit():
    pct = Rule(id=uuid4(), kind="discount", weekdays=(1,), discount_pct=Decimal("10"))
    fixed = Rule(id=uuid4(), kind="discount", discount_minor=500)
    [line] = price(Rate(None, "Std", 4000, "per_hour", rules=(pct, fixed)), [occ(0, 5, 9, 11)])
    assert (line.discount_minor, line.amount_minor) == (1800, 6200)  # (400 + 500) per hour, two hours
    huge = Rule(id=uuid4(), kind="discount", discount_minor=9999)
    assert price(Rate(None, "Std", 4000, "per_hour", rules=(huge,)), [occ(0, 5, 9, 10)])[0].amount_minor == 0


def test_per_resource_multiplies_and_once_does_not():
    two = [occ(0, 5, 9, 10, resources=(COURT, COURT2))]
    each = price(Rate(None, "Std", 2500, "per_occurrence", multi_resource_mode="per_resource"), two)
    once = price(Rate(None, "Std", 2500, "per_occurrence", multi_resource_mode="once"), two)
    assert sum(line.amount_minor for line in each) == 5000 and sum(line.amount_minor for line in once) == 2500
    split = price(Rate(None, "Std", 2500, "per_occurrence", line_grouping="per_resource"), two)
    assert [line.resource_id for line in split] == sorted([COURT, COURT2], key=str)


def test_flat_is_one_line_for_the_whole_request_shared_by_every_occurrence():
    occurrences = [occ(i, 5 + 7 * i, 9, 10) for i in range(3)]
    [line] = price(Rate(None, "Tournament", 10000, "flat", line_grouping="per_occurrence"), occurrences)
    assert line.amount_minor == 10000 and [share for _, _, share in line.items] == [3334, 3333, 3333]


def test_combined_line_shares_add_up_to_the_line_and_grouping_can_be_overridden():
    occurrences = [occ(i, 5 + 7 * i, 9, 10) for i in range(3)]
    rate = Rate(None, "Std", 1000, "per_hour")
    [line] = price(rate, occurrences)
    assert line.amount_minor == 3000 and sum(share for _, _, share in line.items) == 3000
    apply_discount([line], 1001)
    assert line.amount_minor == 1999 and sum(share for _, _, share in line.items) == 1999
    assert len(price(rate, occurrences, grouping="per_occurrence")) == 3


def test_deterministic():
    rate = Rate(
        None, "Std", 4000, "per_hour", rules=(evening(), Rule(id=uuid4(), kind="discount", discount_pct=Decimal("7.5")))
    )
    occurrences = [occ(i, 5 + i, 16.25, 19) for i in range(4)]
    assert price(rate, occurrences) == price(rate, list(reversed(occurrences)))


def test_spring_forward_counts_real_time():
    # 2031-03-09 02:00 does not exist in Chicago: 01:00 to 03:00 local is one real hour.
    [line] = price(Rate(None, "Std", 4000, "per_hour"), [occ(0, 9, 1, 3, month=3)])
    assert line.quantity == Decimal("1.00") and line.amount_minor == 4000


def test_overnight_band_cuts_at_midnight():
    rate = Rate(None, "Std", 4000, "per_hour", rules=(evening(),))
    start = datetime(2031, 5, 5, 23, tzinfo=CHI)
    lines = price(rate, [Occurrence(0, start, start.replace(day=6, hour=1), (COURT,))])
    assert sorted((line.unit_amount_minor, line.quantity) for line in lines) == [
        (4000, Decimal("1.00")),
        (5000, Decimal("1.00")),
    ]


def test_discount_beyond_the_total_is_refused_and_money_helpers():
    [line] = price(Rate(None, "Std", 1000, "per_occurrence"), [occ(0, 5, 9, 10)])
    with pytest.raises(ValueError):
        apply_discount([line], 1001)
    assert tax_of(1000, [Decimal("0.0825"), Decimal("0.01")]) == 83 + 10
    assert deposit_of(10001, Decimal("25")) == 2500 and deposit_of(10000, None) == 0
    assert price(Rate(None, "Std", 1000, "per_hour"), []) == []
