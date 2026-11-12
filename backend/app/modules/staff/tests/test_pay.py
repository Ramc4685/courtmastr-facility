"""staff pay arithmetic: anchors, proration, half-up rounding, rule specificity, effective-dated rates."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.modules.staff.domain import pay


def _rate(**fields):
    base = {"pay_basis": "per_session", "rate_60_minor": 6000, "rate_45_minor": 4500, "rate_30_minor": 3300,
            "non_training_rate_minor": None, "comp_session_rate_minor": None}  # fmt: skip
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


def _kinds(lines):
    return [(line["kind"], line["quantity"], line["amount_minor"]) for line in lines]


def test_session_lines_per_session_and_per_attendee():
    assert pay.session_lines(_rate(), None, 60, 3) == [{"kind": "session", "quantity": Decimal(1), "rate_minor": 6000,
                                                        "amount_minor": 6000}]  # fmt: skip
    assert _kinds(pay.session_lines(_rate(pay_basis="per_attendee"), None, 30, 3)) == [("session", 3, 9900)]


def test_empty_session_pays_non_training_only_when_set():
    assert pay.session_lines(_rate(), _rate(), 60, 0) == []
    nt = _rate(non_training_rate_minor=1200)
    assert _kinds(pay.session_lines(nt, nt, 90, 0)) == [("non_training", Decimal("1.5"), 1800)]
    assert pay.session_lines(_rate(rate_60_minor=0), None, 60, 2) == []


def test_override_row_takes_non_training_and_comp_rates_from_the_default_row():
    default = _full(non_training_rate_minor=1200)
    override = _full(rate_60_minor=9000, non_training_rate_minor=None, comp_session_rate_minor=0)
    assert _kinds(pay.session_lines(override, default, 60, 0)) == [("non_training", 1, 1200)]
    assert _kinds(pay.session_lines(override, default, 60, 1, comp_attendees=1)) == [("comp_session", 1, 2500)]
    assert _kinds(pay.session_lines(override, default, 60, 1)) == [("session", 1, 9000)]


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


def _full(**fields):
    return _rate(**({"comp_session_rate_minor": 2500, "floor_rate_minor": 1800,
                     "program_instruction_rate_minor": 4000} | fields))  # fmt: skip


def test_comp_attendees_pay_the_comp_rate_and_paid_ones_the_normal_rate():
    each = _full(pay_basis="per_attendee")
    assert _kinds(pay.session_lines(each, each, 60, 3, comp_attendees=1)) == [("comp_session", 1, 2500),
                                                                              ("session", 2, 12000)]  # fmt: skip
    assert _kinds(pay.session_lines(each, each, 60, 2, comp_attendees=2)) == [("comp_session", 2, 5000)]
    once = _full()  # per session: the comp rate only when every attendee came on a complimentary credit
    assert _kinds(pay.session_lines(once, once, 60, 2, comp_attendees=2)) == [("comp_session", 1, 2500)]
    assert _kinds(pay.session_lines(once, once, 60, 2, comp_attendees=1)) == [("session", 1, 6000)]
    assert pay.session_lines(once, once, 60, 0, comp_attendees=0) == []  # nobody came: no non-training rate set
    plain = _full(comp_session_rate_minor=0)
    assert _kinds(pay.session_lines(plain, plain, 60, 1, comp_attendees=1)) == [("session", 1, 6000)]


def test_floor_shift_pays_hourly_and_instruction_block_pays_flat():
    floor = pay.block_line(_full(), "floor_shift", 90)
    assert (floor["kind"], floor["amount_minor"]) == ("floor", 2700)
    assert pay.block_line(_full(floor_rate_minor=1001), "floor_shift", 1)["amount_minor"] == 17  # 16.68 up
    flat = pay.block_line(_full(), "instruction", 15)
    assert (flat["kind"], flat["amount_minor"]) == ("program_instruction", 4000)
    assert pay.block_line(_full(), "unpaid", 60) is None
    assert pay.block_line(_full(floor_rate_minor=None, program_instruction_rate_minor=0), "instruction", 60) is None
    assert pay.block_line(_full(floor_rate_minor=None), "floor_shift", 60) is None


def test_pay_rate_is_the_service_row_then_membership_row_then_default():
    default, service, member = object(), object(), object()
    rates = {(None, None): default, ("svc", None): service, (None, "gold"): member}
    assert pay.pick_pay_rate(rates, "svc", "gold") is service
    assert pay.pick_pay_rate(rates, "other", "gold") is member
    assert pay.pick_pay_rate(rates, "other", None) is default
    assert pay.pick_pay_rate({}, "svc", "gold") is None


def test_trained_hours_bonus_threshold_met_exactly_and_zero_time():
    assert pay.trained_hours_bonus(600, 600, 5000) == 5000  # exactly at the threshold
    assert pay.trained_hours_bonus(599, 600, 5000) == 0
    assert pay.trained_hours_bonus(0, 0, 5000) == 0  # a zero threshold does not pay for no training


def test_off_hours_minutes_clip_to_the_window_and_the_weekday():
    mon = datetime(2030, 3, 4, 17, 30, tzinfo=UTC)  # a Monday
    window = dict(zone=UTC, weekdays=[0, 1], from_minute=18 * 60, to_minute=1440)
    assert pay.off_hours_minutes(mon, mon + timedelta(minutes=60), **window) == 30
    assert pay.off_hours_minutes(mon.replace(hour=19), mon.replace(hour=20), **window) == 60
    assert pay.off_hours_minutes(mon.replace(hour=23), mon.replace(hour=23) + timedelta(hours=2), **window) == 30
    assert pay.off_hours_minutes(mon.replace(hour=9), mon.replace(hour=10), **window) == 0
    assert pay.off_hours_minutes(mon + timedelta(days=2), mon + timedelta(days=2, hours=2), **window) == 0  # Wed
    # After midnight the next day's window counts: Monday 23:30 to Tuesday 01:30 against 00:00 to 02:00 on Tuesday.
    early = dict(zone=UTC, weekdays=[1], from_minute=0, to_minute=120)
    assert pay.off_hours_minutes(mon.replace(hour=23), mon.replace(hour=23) + timedelta(hours=2), **early) == 90
    assert pay.off_hours_bonus(45, 1000) == 750
    assert pay.off_hours_bonus(0, 1000) == 0


def test_off_hours_minutes_count_real_time_across_spring_forward():
    chicago = ZoneInfo("America/Chicago")
    starts = datetime(2031, 3, 9, 1, 0, tzinfo=chicago)  # Sunday, clocks jump from 02:00 to 03:00
    ends = datetime(2031, 3, 9, 4, 0, tzinfo=chicago)  # three wall-clock hours, two real ones
    window = dict(zone=chicago, weekdays=[6], from_minute=0, to_minute=1440)
    assert pay.off_hours_minutes(starts.astimezone(UTC), ends.astimezone(UTC), **window) == 120
    late = dict(zone=chicago, weekdays=[5], from_minute=22 * 60, to_minute=1440)  # Saturday 23:00 to Sunday 01:00
    assert pay.off_hours_minutes(datetime(2031, 3, 8, 23, tzinfo=chicago), starts, **late) == 60


def test_shift_variance_clips_entries_and_ignores_open_ones():
    start = datetime(2030, 3, 4, 14, 0, tzinfo=UTC)
    end = start + timedelta(hours=8)
    hour = timedelta(hours=1)
    none = pay.shift_variance(start, end, [])
    assert (none["scheduled_minutes"], none["worked_minutes"], none["variance_minutes"]) == (480, 0, -480)
    assert none["first_in_at"] is None
    split = pay.shift_variance(start, end, [(start - hour, start + 3 * hour), (start + 4 * hour, end + hour),
                                            (start + 5 * hour, None)])  # fmt: skip
    assert (split["worked_minutes"], split["variance_minutes"]) == (180 + 240, -60)
    assert (split["first_in_at"], split["last_out_at"]) == (start, end)
    assert pay.shift_variance(start, end, [(start - 2 * hour, start - hour)])["worked_minutes"] == 0
