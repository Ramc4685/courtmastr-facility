from datetime import date
from decimal import Decimal

import pytest

from app.modules.assessments.domain import progress

D = Decimal


@pytest.mark.parametrize(("value", "places", "expected"), [
    (D("12.345"), 2, D("12.35")), (D("12.344"), 2, D("12.34")), (D("2.5"), 0, D("3")), (D("-2.5"), 0, D("-3")),
    (D("7"), 3, D("7.000")),
])  # fmt: skip
def test_values_round_half_up_to_the_field(value, places, expected):
    assert progress.rounded(value, places) == expected


@pytest.mark.parametrize(("direction", "expected"), [("higher", D(9)), ("lower", D(4)), ("none", None)])
def test_best_follows_the_better_direction(direction, expected):
    assert progress.best([D(5), D(9), D(4)], direction) == expected
    assert progress.best([], direction) is None


def test_summary_reads_a_newest_first_series():
    points = [(date(2031, 3, 1), D("21.5")), (date(2031, 2, 1), D(24)), (date(2031, 1, 1), D("25.0"))]
    assert progress.summary(points, "lower") == {
        "latest_value": D("21.5"), "first_value": D("25.0"), "change": D("-3.5"), "best_value": D("21.5")}  # fmt: skip
    assert progress.summary([], "higher")["latest_value"] is None
