"""staff pay arithmetic: anchors, proration, half-up rounding, rule specificity, effective-dated rates."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.modules.staff.domain import pay


def _rate(**fields):
    base = {"pay_basis": "per_session", "rate_60_minor": 6000, "rate_45_minor": 4500, "rate_30_minor": 3300,
            "non_training_rate_minor": None}  # fmt: skip
    return SimpleNamespace(**(base | fields))


def test_anchor_is_nearest_and_longer_on_a_tie():
    rates = {60: 1, 45: 2, 30: 3}
    assert pay.anchored_rate(rates, 60) == (60, 1)
    assert pay.anchored_rate(rates, 50) == (45, 2)
    assert pay.anchored_rate(rates, 52) == (45, 2)
    assert pay.anchored_rate(rates, 53) == (60, 1)  # 7 from 60, 8 from 45
    assert pay.anchored_rate(rates, 37) == (30, 3)
    assert pay.anchored_rate(rates, 38) == (45, 2)  # 7 from 45, 8 from 30
    assert pay.anchored_rate(rates, 90) == (60, 1)


def test_proration_rounds_half_up_once():
    assert pay.prorated(4500, 45, 50) == 5000
    assert pay.prorated(3333, 60, 90) == 5000  # 4999.5 rounds up
    assert pay.per_hour(1500, 50) == 1250
    assert pay.per_hour(1, 30) == 1  # 0.5 rounds up
    assert pay.half_up(Decimal("2.5")) == 3 and pay.half_up(Decimal("-2.5")) == -3


def test_session_line_per_session_and_per_attendee():
    assert pay.session_line(_rate(), 60, 3) == {"kind": "session", "quantity": Decimal(1), "rate_minor": 6000,
                                                "amount_minor": 6000}  # fmt: skip
    line = pay.session_line(_rate(pay_basis="per_attendee"), 30, 3)
    assert line["quantity"] == 3 and line["amount_minor"] == 9900


def test_empty_session_pays_non_training_only_when_set():
    assert pay.session_line(_rate(), 60, 0) is None
    line = pay.session_line(_rate(non_training_rate_minor=1200), 90, 0)
    assert line["kind"] == "non_training" and line["amount_minor"] == 1800
    assert pay.session_line(_rate(rate_60_minor=0), 60, 2) is None


def test_commission_and_rule_specificity():
    assert pay.commission(10050, Decimal("10"), 0) == 1005
    assert pay.commission(1005, Decimal("10"), 250) == 351  # 100.5 -> 101, plus flat
    default = SimpleNamespace(applies_to="package_sale", reservation_type_id=None)
    typed = SimpleNamespace(applies_to="package_sale", reservation_type_id="clinic")
    other = SimpleNamespace(applies_to="membership_sale", reservation_type_id=None)
    rules = [default, typed, other]
    assert pay.pick_rule(rules, "package_sale", reservation_type_id="clinic") is typed
    assert pay.pick_rule(rules, "package_sale", reservation_type_id="tennis") is default
    assert pay.pick_rule([other], "package_sale", reservation_type_id=None) is None


def test_rate_on_takes_the_latest_start_on_or_before_the_day():
    rates = [(date(2031, 1, 1), 1500), (date(2031, 6, 1), 1700)]
    assert pay.rate_on(rates, date(2030, 12, 31)) is None
    assert pay.rate_on(rates, date(2031, 5, 31)) == 1500
    assert pay.rate_on(rates, date(2031, 6, 1)) == 1700
