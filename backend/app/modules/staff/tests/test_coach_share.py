"""Coach revenue share (staff README "Coach revenue share"): engagement, share rules, the earnings ledger that
follows the lesson money through events, payout statements, the coach's own view and the payroll split."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.db.session import tenant_session
from app.modules.memberships.tests.support import deliver_events, package_plan
from app.modules.scheduling.tests.helpers import API, DAY, at, book, facility, ok
from app.modules.staff.domain import share
from app.modules.staff.models import CoachEarning
from conftest import add_staff, login, new_client, scalar

# --- pure arithmetic ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("gross", "pct", "fee", "applies", "expected"), [
    (5000, Decimal(70), 0, "before_split", (1500, 3500)),
    (4999, Decimal(70), 0, "before_split", (1500, 3499)),  # 3499.3 rounds once, half-up; shares sum to the gross
    (5000, Decimal("33.33"), 0, "before_split", (3333, 1667)),  # 1666.5 rounds half-up to 1667
    (5000, Decimal(70), 1000, "before_split", (2200, 2800)),  # the court fee first, then 70% of 4000
    (5000, Decimal(70), 1000, "after_split", (2500, 2500)),  # 70% of 5000, less the fee
    (5000, Decimal(10), 1000, "after_split", (5000, 0)),  # the coach never goes below zero
    (-5000, Decimal(70), 0, "before_split", (-1500, -3500)),  # a reversal splits the same way, signs flipped
])  # fmt: skip
def test_split_rounds_once_and_always_sums_to_the_gross(gross, pct, fee, applies, expected):
    facility_share, coach_share = share.split(gross, pct, fee, applies)
    assert facility_share + coach_share == gross
    assert (facility_share, coach_share) == expected


def test_lesson_value_court_fee_and_labels():
    assert share.lesson_value(22500, 5) == 4500 and share.lesson_value(10000, 3) == 3333
    assert share.lesson_value(0, 5) == 0 and share.lesson_value(5000, 0) == 0  # refunded, or unlimited
    assert share.lesson_value(10000, 10, 11) == 0  # a credit added after the sale is worth nothing to the split
    assert share.court_fee(1200, "session", 90) == 1200 and share.court_fee(1200, "hour", 90) == 1800
    assert share.client_label("Ana", "Ruiz", False) == "Lesson with Ana R."
    assert share.client_label("Tom", "Ruiz", True) == "Junior lesson"  # a minor is never named
    assert share.client_label(None, None, False) == "Lesson"


@pytest.mark.parametrize("sold", range(1, 13))
def test_a_packages_recognised_lessons_never_add_up_to_more_than_its_net(sold):
    """However many credits are spent (added credits included), the lessons' gross never exceeds the net."""
    for net in (*range(0, 400, 7), 9999, 10000, 20000, 22500, 50000):
        assert sum(share.lesson_value(net, sold, n) for n in range(1, 3 * sold + 1)) <= net


def test_rule_precedence_and_effective_dates():
    def rule(payee, kind, on, pct):
        return SimpleNamespace(
            staff_payee_id=payee, reservation_type_id=kind, effective_from_on=on, coach_share_pct=pct
        )

    jan, jun = date(2031, 1, 1), date(2031, 6, 1)
    rules = [rule(None, None, jan, 50), rule(None, "t", jan, 55), rule("c", None, jan, 60), rule("c", "t", jun, 70)]
    assert share.pick_rule(rules, "c", "t", date(2031, 5, 1)).coach_share_pct == 60  # coach-and-type starts in June
    assert share.pick_rule(rules, "c", "t", jun).coach_share_pct == 70
    assert share.pick_rule(rules, "x", "t", jun).coach_share_pct == 55
    assert share.pick_rule(rules, "x", None, jun).coach_share_pct == 50
    assert share.pick_rule(rules, "x", None, date(2030, 1, 1)) is None


# --- through the API ---------------------------------------------------------------------------------------------


def _lines(tenant, payee_id) -> list[tuple]:
    return [tuple(r) for r in rows(tenant, select(
        CoachEarning.kind, CoachEarning.gross_minor, CoachEarning.facility_share_minor, CoachEarning.coach_share_minor
    ).where(CoachEarning.staff_payee_id == payee_id).order_by(CoachEarning.created_at, CoachEarning.id))]  # fmt: skip


def rows(tenant, stmt):
    with tenant_session(tenant.id) as session:
        return session.execute(stmt).all()


@pytest.fixture
def coached(client, tenant, owner):
    """An independent coach at 70% with a ten-lesson package ($100: $10 a lesson) and an attended lesson."""
    f = facility(client, owner)
    payee = ok(client.post(f"{API}/staff-payees", headers=owner, json={
        "kind": "trainer", "display_name": "Coach Ines", "location_id": f.location, "resource_id": f.coach}))  # fmt: skip
    ok(client.post(f"{API}/staff-payees/{payee['id']}/engagements", headers=owner,
                   json={"engagement": "independent", "effective_from_on": "2031-01-01"}))  # fmt: skip
    ok(client.put(f"{API}/coach-share-rules", headers=owner, json={
        "staff_payee_id": payee["id"], "effective_from_on": "2031-01-01", "coach_share_pct": "70"}), 200)  # fmt: skip
    plan = package_plan(client, owner, tenant, reservation_type_id=f.type)
    person = new_client(client, owner, f.location, first_name="Ana", last_name="Ruiz", birth_on="1990-02-03")
    pack = ok(client.post(f"{API}/client-packages", headers=owner,
                          json={"client_id": person["id"], "location_id": f.location, "package_plan_id": plan["id"]}))  # fmt: skip
    seat = ok(book(client, owner, f, [f.coach], at(15), at(16), kind="session",
                   session={"capacity": 2, "allows_free_booking": False}))["booking"]["session"]["id"]  # fmt: skip
    place = ok(client.post(f"{API}/enrollments", headers=owner,
                           json={"session_id": seat, "client_id": person["id"], "client_package_id": pack["id"]}))  # fmt: skip
    return SimpleNamespace(f=f, payee=payee, pack=pack, seat=seat, place=place, person=person)


def _mark(client, tenant, c, status: str):
    _attend(client, tenant, c.seat, c.place["id"], status)


def _attend(client, tenant, seat: str, place_id: str, status: str):
    with clock.freeze(DAY + timedelta(days=1)):
        owner = login(client, tenant)
        ok(client.put(f"{API}/sessions/{seat}/attendance", headers=owner,
                      json={"marks": [{"enrollment_id": place_id, "status": status}]}), 200)  # fmt: skip
    deliver_events()


def _lessons(client, owner, c, pack_id: str, hours) -> list[tuple[str, str]]:
    """More one-hour lessons on the coach's column, each paid from `pack_id`: (session id, enrolment id)."""
    made = []
    for hour in hours:
        seat = ok(book(client, owner, c.f, [c.f.coach], at(hour), at(hour + 1), kind="session",
                       session={"capacity": 2, "allows_free_booking": False}))["booking"]["session"]["id"]  # fmt: skip
        place = ok(client.post(f"{API}/enrollments", headers=owner,
                               json={"session_id": seat, "client_id": c.person["id"], "client_package_id": pack_id}))  # fmt: skip
        made.append((seat, place["id"]))
    return made


def test_a_voided_package_charge_reverses_every_lesson_it_paid_for(client, tenant, owner, coached):
    """$500 for ten lessons on an uninvoiced charge, three taught at 70%: $105 owed until the charge is voided."""
    c = coached
    plan = package_plan(client, owner, tenant, reservation_type_id=c.f.type, fee_minor=50000)
    pack = ok(client.post(f"{API}/client-packages", headers=owner, json={
        "client_id": c.person["id"], "location_id": c.f.location, "package_plan_id": plan["id"],
        "invoice_mode": "deferred"}))  # fmt: skip
    for seat, place in _lessons(client, owner, c, pack["id"], (17, 19, 21)):
        _attend(client, tenant, seat, place, "attended")
    assert sum(x[3] for x in _lines(tenant, c.payee["id"])) == 10500
    ok(client.post(f"{API}/charges/{pack['charge_id']}/void", headers=owner | {"Idempotency-Key": "void-charge-1"},
                   json={"reason": "Sold in error"}), 200)  # fmt: skip
    deliver_events()
    assert sum(x[3] for x in _lines(tenant, c.payee["id"])) == 0


def test_the_ledger_follows_the_lesson_money_and_replays_change_nothing(client, tenant, owner, coached):
    c = coached
    _mark(client, tenant, c, "attended")
    assert _lines(tenant, c.payee["id"]) == [("lesson", 1000, 300, 700)]
    earning = ok(client.get(f"{API}/coach-earnings", headers=owner), 200)["data"][0]
    assert earning["description"] == "Lesson with Ana R." and earning["earned_on"] == "2031-05-05"
    deliver_events()  # nothing new to deliver; the ledger stays put
    _mark(client, tenant, c, "excused")  # the credit comes back: the earning is reversed
    assert _lines(tenant, c.payee["id"])[-1] == ("reversal", -1000, -300, -700)
    _mark(client, tenant, c, "attended")
    assert _lines(tenant, c.payee["id"])[-1] == ("lesson", 1000, 300, 700)
    # A refund starts with reversing the package charge: the lesson is worth nothing now and is reversed.
    charge = c.pack["charge_id"]
    refund = {"Idempotency-Key": "refund-1"}
    ok(client.post(f"{API}/charges/{charge}/reverse", headers=owner | refund, json={"reason": "Refund"}))
    deliver_events()
    lines = _lines(tenant, c.payee["id"])
    assert lines[-1] == ("reversal", -1000, -300, -700) and sum(x[3] for x in lines) == 0


def test_credits_added_by_hand_do_not_lower_the_value_of_a_lesson(client, tenant, owner, coached):
    """$100 for ten lessons: a lesson is $10. Adding ten credits later must not re-recognise it at $5."""
    c = coached
    _mark(client, tenant, c, "attended")
    ok(client.post(f"{API}/client-packages/{c.pack['id']}/credit-adjustments", headers=owner,
                   json={"delta": 10, "note": "Goodwill"}), 200)  # fmt: skip
    _mark(client, tenant, c, "excused")
    _mark(client, tenant, c, "attended")
    assert _lines(tenant, c.payee["id"])[-1] == ("lesson", 1000, 300, 700)


def test_an_independent_coach_is_never_on_payroll_and_an_employee_earns_no_share(client, tenant, owner, coached):
    c = coached
    ok(client.put(f"{API}/staff-payees/{c.payee['id']}/pay-rates/default", headers=owner,
                  json={"pay_basis": "per_session", "rate_60_minor": 3000, "session_commission_pct": "70"}), 200)  # fmt: skip
    _mark(client, tenant, c, "attended")
    with clock.freeze(DAY + timedelta(days=1)):
        owner = login(client, tenant)
        run = ok(client.post(f"{API}/payroll-runs", headers=owner, json={
            "location_id": c.f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-10"}))  # fmt: skip
    statements = ok(client.get(f"{API}/payroll-runs/{run['id']}/statements", headers=owner), 200)["data"]
    assert [s for s in statements if s["staff_payee_id"] == c.payee["id"]] == []
    # Back to staff coach from 6 May: the 5 May lesson stays shared, and a later run would pay sessions again.
    ok(client.post(f"{API}/staff-payees/{c.payee['id']}/engagements", headers=owner,
                   json={"engagement": "employee", "effective_from_on": "2031-05-06"}))  # fmt: skip
    history = ok(client.get(f"{API}/staff-payees/{c.payee['id']}/engagements", headers=owner), 200)
    assert [h["engagement"] for h in history] == ["independent", "employee"]
    assert _lines(tenant, c.payee["id"]) == [("lesson", 1000, 300, 700)]


def test_payout_statement_flow_adjustment_step_up_and_paid_is_final(client, tenant, owner, coached):
    c = coached
    _mark(client, tenant, c, "attended")
    body = {"location_id": c.f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-31"}
    [payout] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    assert (payout["status"], payout["gross_minor"], payout["coach_share_minor"]) == ("draft", 1000, 700)
    assert "does not move money" in payout["notice"]
    assert ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"] == []  # nothing left unpaid
    url = f"{API}/coach-payouts/{payout['id']}"
    adjusted = ok(
        client.post(f"{url}/adjustments", headers=owner, json={"amount_minor": 250, "reason": "Extra clinic"})
    )
    assert (adjusted["coach_share_minor"], adjusted["facility_share_minor"], adjusted["gross_minor"]) == (950, 50, 1000)
    lazy = login(client, tenant, elevated=False)
    refused = client.post(f"{url}/approve", headers=lazy)
    assert (refused.status_code, refused.json()["code"]) == (403, "step-up-required")
    assert ok(client.post(f"{url}/approve", headers=owner), 200)["status"] == "approved"
    paid = ok(client.post(f"{url}/paid", headers=owner, json={
        "paid_on": "2031-06-01", "payment_method": "bank_transfer", "payment_reference": "TX-2031-06-01"}), 200)  # fmt: skip
    assert (paid["status"], paid["payment_reference"]) == ("paid", "TX-2031-06-01")
    for attempt in (client.post(f"{url}/adjustments", headers=owner, json={"amount_minor": 1, "reason": "Late"}),
                    client.post(f"{url}/paid", headers=owner, json={"paid_on": "2031-06-02", "payment_method": "cheque"}),
                    client.delete(url, headers=owner)):  # fmt: skip
        assert (attempt.status_code, attempt.json()["code"]) == (409, "invalid-state-transition")
    card = client.post(f"{url}/paid", headers=owner, json={"paid_on": "2031-06-02", "payment_method": "other",
                                                           "payment_reference": "4111 1111 1111 1111"})  # fmt: skip
    assert card.status_code == 422
    csv_file = client.get(f"{url}/document?format=csv", headers=owner)
    assert csv_file.status_code == 200 and "Lesson with Ana R.,0.00" not in csv_file.text and "9.50" in csv_file.text
    assert client.get(f"{url}/document", headers=owner).content.startswith(b"%PDF")
    actions = rows(tenant, select(AuditEvent.action, func.count()).where(AuditEvent.entity_id == payout["id"])
                          .group_by(AuditEvent.action))  # fmt: skip
    assert dict(actions) == {"staff.coach_payout.create": 1, "staff.coach_payout.adjust": 1,
                             "staff.coach_payout.approve": 1, "staff.coach_payout.pay": 1,
                             "staff.coach_payout.read": 2}  # fmt: skip


def test_the_coach_sees_only_their_own_and_never_a_share_rule(client, tenant, owner, coached):
    c = coached
    _mark(client, tenant, c, "attended")
    ines_email, ines = add_staff(tenant, "coach", location_ids=[c.f.location])
    other_email, _ = add_staff(tenant, "coach", location_ids=[c.f.location])
    ok(client.patch(f"{API}/staff-payees/{c.payee['id']}", headers=owner, json={"staff_user_id": str(ines)}), 200)
    body = {"location_id": c.f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-31"}
    [payout] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    headers = login(client, tenant, ines_email)
    assert [e["coach_share_minor"] for e in ok(client.get(f"{API}/coach-earnings", headers=headers), 200)["data"]] == [
        700
    ]
    assert ok(client.get(f"{API}/coach-payouts/{payout['id']}", headers=headers), 200)["coach_share_minor"] == 700
    mine = ok(client.get(f"{API}/coach-earnings", headers=headers), 200)["data"][0]
    assert (mine["coach_share_pct"], mine["court_fee_minor"]) == (None, None)  # would reveal the rule
    assert client.get(f"{API}/coach-share-rules", headers=headers).status_code == 403
    assert client.get(f"{API}/staff-payees/{c.payee['id']}/engagements", headers=headers).status_code == 403
    assert client.post(f"{API}/coach-payouts/{payout['id']}/approve", headers=headers).status_code == 403
    stranger = login(client, tenant, other_email)
    assert ok(client.get(f"{API}/coach-earnings", headers=stranger), 200)["data"] == []
    assert client.get(f"{API}/coach-payouts/{payout['id']}", headers=stranger).status_code == 404
    desk_email, _ = add_staff(tenant, "front_desk", location_ids=[c.f.location])
    assert client.get(f"{API}/coach-earnings", headers=login(client, tenant, desk_email)).status_code == 403


def test_share_rules_validate_and_keep_their_history(client, tenant, owner, coached):
    c = coached
    url = f"{API}/coach-share-rules"
    later = ok(client.put(url, headers=owner, json={"staff_payee_id": c.payee["id"], "effective_from_on": "2031-07-01",
                                                    "coach_share_pct": "60", "court_fee_minor": 500,
                                                    "court_fee_basis": "hour", "court_fee_applies": "after_split"}), 200)  # fmt: skip
    rules = ok(client.get(f"{url}?staff_payee_id={c.payee['id']}", headers=owner), 200)["data"]
    assert [r["coach_share_pct"] for r in rules] == ["70.00", "60.00"]
    assert (
        client.put(url, headers=owner, json={"effective_from_on": "2031-07-01", "coach_share_pct": "101"}).status_code
        == 422
    )
    unknown = client.put(url, headers=owner, json={"reservation_type_id": c.payee["id"], "effective_from_on": "2031-07-01",
                                                   "coach_share_pct": "50"})  # fmt: skip
    assert unknown.status_code == 422
    ok(client.delete(f"{url}/{later['id']}", headers=owner), 204)
    assert len(ok(client.get(url, headers=owner), 200)["data"]) == 1
    taxed = ok(client.put(f"{API}/staff-payees/{c.payee['id']}/tax-form", headers=owner,
                          json={"tax_form_on_file_on": "2031-01-15"}), 200)  # fmt: skip
    assert taxed["tax_form_on_file_on"] == "2031-01-15"
    assert scalar(tenant, select(func.count()).select_from(CoachEarning)) == 0  # rules alone earn nothing
