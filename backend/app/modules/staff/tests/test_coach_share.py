"""Coach revenue share (staff README "Coach revenue share"): engagement, share rules, the earnings ledger that
follows the lesson money through events, payout statements, the coach's own view and the payroll split."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from app.core import clock
from app.core.audit import AuditEvent
from app.core.db.session import tenant_session
from app.modules.memberships.tests.support import deliver_events, package_plan
from app.modules.platform.models import StaffUser
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


def test_lesson_value_and_court_fee():
    assert share.lesson_value(22500, 5) == 4500 and share.lesson_value(10000, 3) == 3333
    assert share.lesson_value(0, 5) == 0 and share.lesson_value(5000, 0) == 0  # refunded, or unlimited
    assert share.lesson_value(10000, 10, 11) == 0  # a credit added after the sale is worth nothing to the split
    assert share.court_fee(1200, "session", 90) == 1200 and share.court_fee(1200, "hour", 90) == 1800


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
    # Client-neutral: the immutable ledger has no client id, so erasure could never reach a name written into it.
    assert earning["description"] == "Lesson" and earning["earned_on"] == "2031-05-05"
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


def test_reconcile_locks_are_tenant_scoped_and_taken_in_a_stable_order(client, tenant, owner, coached):
    c = coached
    plan = package_plan(client, owner, tenant, reservation_type_id=c.f.type, fee_minor=50000)
    pack = ok(client.post(f"{API}/client-packages", headers=owner, json={
        "client_id": c.person["id"], "location_id": c.f.location, "package_plan_id": plan["id"],
        "invoice_mode": "deferred"}))  # fmt: skip
    for seat, place in _lessons(client, owner, c, pack["id"], (17, 19, 21)):
        _attend(client, tenant, seat, place, "attended")
    keys: list[str] = []

    def spy(conn, cursor, statement, parameters, *args):
        if "pg_advisory_xact_lock" in statement:
            keys.extend(v for v in (parameters or {}).values() if isinstance(v, str) and "coach-" in v)

    ok(client.post(f"{API}/charges/{pack['charge_id']}/void", headers=owner | {"Idempotency-Key": "void-charge-2"},
                   json={"reason": "Sold in error"}), 200)  # fmt: skip
    event.listen(Engine, "before_cursor_execute", spy)
    try:
        deliver_events()
    finally:
        event.remove(Engine, "before_cursor_execute", spy)
    assert keys and all(k.startswith(f"{tenant.id}:") for k in keys)
    assert keys[0] == f"{tenant.id}:coach-package:{pack['id']}"
    sources = [k for k in keys if ":coach-earning:" in k]
    assert len(sources) == 3 and sources == sorted(sources)


def test_credits_added_by_hand_do_not_lower_the_value_of_a_lesson(client, tenant, owner, coached):
    """$100 for ten lessons: a lesson is $10. Adding ten credits later must not re-recognise it at $5."""
    c = coached
    _mark(client, tenant, c, "attended")
    ok(client.post(f"{API}/client-packages/{c.pack['id']}/credit-adjustments", headers=owner,
                   json={"delta": 10, "note": "Goodwill"}), 200)  # fmt: skip
    _mark(client, tenant, c, "excused")
    _mark(client, tenant, c, "attended")
    assert _lines(tenant, c.payee["id"])[-1] == ("lesson", 1000, 300, 700)


def test_terms_dated_before_today_are_refused_once_the_coach_has_sessions(client, tenant, owner, coached):
    """The lesson on 5 May is already taught by 6 May: new terms from 1 May would pay it twice or not at all."""
    c = coached
    rule = {"staff_payee_id": c.payee["id"], "effective_from_on": "2031-05-01", "coach_share_pct": "90"}
    with clock.freeze(DAY + timedelta(days=1)):
        owner = login(client, tenant)
        for path, method, body in ((f"{API}/coach-share-rules", client.put, rule),
                                   (f"{API}/coach-share-rules", client.put, rule | {"staff_payee_id": None}),
                                   (f"{API}/staff-payees/{c.payee['id']}/engagements", client.post,
                                    {"engagement": "employee", "effective_from_on": "2031-05-01"})):  # fmt: skip
            refused = method(path, headers=owner, json=body)
            assert (refused.status_code, refused.json()["code"]) == (422, "effective-date-has-sessions")
        ok(client.put(f"{API}/coach-share-rules", headers=owner, json=rule | {"effective_from_on": "2031-05-07"}), 200)


def test_deleting_a_rule_dated_before_today_is_refused_like_a_back_dated_change(client, tenant, owner, coached):
    """$500 for ten lessons, three taught at 70% ($105). Deleting the 1 January rule would let a later $500 to $450
    price edit rewrite all three as "no share rule" at $0; refused, the edit leaves $94.50 owed."""
    c = coached
    plan = package_plan(client, owner, tenant, reservation_type_id=c.f.type, fee_minor=50000)
    pack = ok(client.post(f"{API}/client-packages", headers=owner, json={
        "client_id": c.person["id"], "location_id": c.f.location, "package_plan_id": plan["id"],
        "invoice_mode": "deferred"}))  # fmt: skip
    for seat, place in _lessons(client, owner, c, pack["id"], (17, 19, 21)):
        _attend(client, tenant, seat, place, "attended")
    assert sum(x[3] for x in _lines(tenant, c.payee["id"])) == 10500
    [rule] = ok(client.get(f"{API}/coach-share-rules", headers=owner), 200)["data"]
    with clock.freeze(DAY + timedelta(days=1)):
        owner = login(client, tenant)
        refused = client.delete(f"{API}/coach-share-rules/{rule['id']}", headers=owner)
        assert (refused.status_code, refused.json()["code"]) == (422, "effective-date-has-sessions")
        ok(client.patch(f"{API}/charges/{pack['charge_id']}", headers=owner,
                        json={"unit_price_minor": 45000, "reason": "Price corrected"}), 200)  # fmt: skip
    deliver_events()
    lines = _lines(tenant, c.payee["id"])
    assert sum(x[3] for x in lines) == 9450 and [x for x in lines if x[0] == "lesson"][-1] == ("lesson", 4500, 1350, 3150)


def test_a_lesson_with_no_share_rule_is_recorded_wholly_the_facilitys(client, tenant, owner, coached):
    c = coached
    [rule] = ok(client.get(f"{API}/coach-share-rules", headers=owner), 200)["data"]
    ok(client.delete(f"{API}/coach-share-rules/{rule['id']}", headers=owner), 204)
    _mark(client, tenant, c, "attended")
    assert _lines(tenant, c.payee["id"]) == [("lesson", 1000, 1000, 0)]
    earning = ok(client.get(f"{API}/coach-earnings", headers=owner), 200)["data"][0]
    assert earning["description"].endswith("(no share rule)") and earning["coach_share_pct"] is None


def test_approving_a_statement_with_no_rule_lines_needs_an_acknowledgement(client, tenant, owner, coached):
    """A $10 lesson taught with no rule in force pays the coach $0: the statement counts it and approve asks."""
    c = coached
    [rule] = ok(client.get(f"{API}/coach-share-rules", headers=owner), 200)["data"]
    ok(client.delete(f"{API}/coach-share-rules/{rule['id']}", headers=owner), 204)
    _mark(client, tenant, c, "attended")
    body = {"location_id": c.f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-31"}
    [payout] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    assert (payout["no_rule_line_count"], payout["coach_share_minor"]) == (1, 0)
    url = f"{API}/coach-payouts/{payout['id']}/approve"
    for refused in (client.post(url, headers=owner), client.post(url, headers=owner, json={})):
        assert (refused.status_code, refused.json()["code"]) == (422, "no-rule-lines-unacknowledged")
    approved = ok(client.post(url, headers=owner, json={"acknowledge_no_rule_lines": True}), 200)
    assert (approved["status"], approved["no_rule_line_count"]) == ("approved", 1)


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
    huge = client.post(f"{API}/coach-payouts/{payout['id']}/adjustments", headers=owner,
                       json={"amount_minor": 10**10, "reason": "Typo"})  # fmt: skip
    assert huge.status_code == 422  # beyond the int4 money columns: refused, not a database error
    card = client.post(f"{url}/paid", headers=owner, json={"paid_on": "2031-06-02", "payment_method": "other",
                                                           "payment_reference": "4111 1111 1111 1111"})  # fmt: skip
    assert card.status_code == 422
    csv_file = client.get(f"{url}/document?format=csv", headers=owner)
    assert csv_file.status_code == 200 and "Ana" not in csv_file.text and "9.50" in csv_file.text
    assert client.get(f"{url}/document", headers=owner).content.startswith(b"%PDF")
    actions = rows(tenant, select(AuditEvent.action, func.count()).where(AuditEvent.entity_id == payout["id"])
                          .group_by(AuditEvent.action))  # fmt: skip
    assert dict(actions) == {"staff.coach_payout.create": 1, "staff.coach_payout.adjust": 1,
                             "staff.coach_payout.approve": 1, "staff.coach_payout.pay": 1,
                             "staff.coach_payout.read": 2}  # fmt: skip


def test_approve_gathers_a_reversal_that_arrived_after_the_draft_and_refuses_a_negative_total(
    client, tenant, owner, coached
):
    c = coached
    _mark(client, tenant, c, "attended")
    body = {"location_id": c.f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-31"}
    [stale] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    assert stale["coach_share_minor"] == 700
    _mark(client, tenant, c, "excused")  # the lesson is undone after the draft was made
    approved = ok(client.post(f"{API}/coach-payouts/{stale['id']}/approve", headers=owner), 200)
    assert (approved["line_count"], approved["gross_minor"], approved["coach_share_minor"]) == (2, 0, 0)
    # Taught again and paid; then undone once more: the next statement holds only the -$7 reversal.
    _mark(client, tenant, c, "attended")
    [paid] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    ok(client.post(f"{API}/coach-payouts/{paid['id']}/approve", headers=owner), 200)
    ok(client.post(f"{API}/coach-payouts/{paid['id']}/paid", headers=owner,
                   json={"paid_on": "2031-06-01", "payment_method": "cheque"}), 200)  # fmt: skip
    _mark(client, tenant, c, "excused")
    [negative] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    assert negative["coach_share_minor"] == -700
    refused = client.post(f"{API}/coach-payouts/{negative['id']}/approve", headers=owner)
    assert (refused.status_code, refused.json()["code"]) == (409, "payout-negative")
    assert ok(client.get(f"{API}/coach-payouts/{negative['id']}", headers=owner), 200)["status"] == "draft"


def test_a_refused_negative_approve_leaves_the_draft_showing_its_true_total(client, tenant, owner, coached):
    """Lesson A ($7) is paid; the draft holds lesson B (+$7); both are undone: approve finds -$7 and refuses, and the
    draft then says -$7, not a stale +$7."""
    c = coached
    _mark(client, tenant, c, "attended")
    body = {"location_id": c.f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-31"}
    [first] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    ok(client.post(f"{API}/coach-payouts/{first['id']}/approve", headers=owner), 200)
    ok(client.post(f"{API}/coach-payouts/{first['id']}/paid", headers=owner,
                   json={"paid_on": "2031-06-01", "payment_method": "cheque"}), 200)  # fmt: skip
    [(seat, place)] = _lessons(client, owner, c, c.pack["id"], (17,))
    _attend(client, tenant, seat, place, "attended")
    [draft] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    assert draft["coach_share_minor"] == 700
    _mark(client, tenant, c, "excused")
    _attend(client, tenant, seat, place, "excused")
    url = f"{API}/coach-payouts/{draft['id']}"
    refused = client.post(f"{url}/approve", headers=owner)
    assert (refused.status_code, refused.json()["code"]) == (409, "payout-negative")
    assert "later end date" in refused.json()["detail"] and "positive adjustment" in refused.json()["detail"]
    now = ok(client.get(url, headers=owner), 200)
    assert (now["status"], now["line_count"], now["coach_share_minor"]) == ("draft", 3, -700)


def test_a_draft_made_after_a_later_dated_reversal_holds_it_so_approve_agrees(client, tenant, owner, coached):
    """Lesson 5 May +$7, undone 9 June -$7: the May draft is $0, as its approval will be, not $7."""
    c = coached
    _mark(client, tenant, c, "attended")
    with clock.freeze(datetime(2031, 6, 9, 12, tzinfo=UTC)):
        owner = login(client, tenant)
        ok(client.put(f"{API}/sessions/{c.seat}/attendance", headers=owner,
                      json={"marks": [{"enrollment_id": c.place["id"], "status": "excused"}]}), 200)  # fmt: skip
        deliver_events()
        assert _lines(tenant, c.payee["id"])[-1] == ("reversal", -1000, -300, -700)
        body = {"location_id": c.f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-31"}
        [draft] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
        assert (draft["line_count"], draft["coach_share_minor"]) == (2, 0)
        approved = ok(client.post(f"{API}/coach-payouts/{draft['id']}/approve", headers=owner), 200)
        assert (approved["line_count"], approved["coach_share_minor"]) == (2, 0)


def test_an_adjustment_that_would_overflow_the_statement_total_is_refused(client, tenant, owner, coached):
    """$7 owed plus an adjustment of 2,147,483,647 passes the field limit but not the int4 total: 422, not a 500."""
    c = coached
    _mark(client, tenant, c, "attended")
    body = {"location_id": c.f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-31"}
    [payout] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    url = f"{API}/coach-payouts/{payout['id']}"
    refused = client.post(f"{url}/adjustments", headers=owner, json={"amount_minor": 2_147_483_647, "reason": "Typo"})
    assert (refused.status_code, refused.json()["code"]) == (422, "payout-total-out-of-range")
    assert ok(client.get(url, headers=owner), 200)["coach_share_minor"] == 700


def test_adjust_approve_and_mark_paid_lock_the_statement_row(client, tenant, owner, coached):
    """Without the lock an adjustment can land on a statement approved a moment before, and paid can run twice."""
    c = coached
    _mark(client, tenant, c, "attended")
    body = {"location_id": c.f.location, "period_starts_on": "2031-05-01", "period_ends_on": "2031-05-31"}
    [payout] = ok(client.post(f"{API}/coach-payouts", headers=owner, json=body))["data"]
    url = f"{API}/coach-payouts/{payout['id']}"
    seen: list[str] = []

    def spy(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", spy)
    try:
        for path, payload, status in (("/adjustments", {"amount_minor": 100, "reason": "Clinic"}, 201),
                                      ("/approve", None, 200),
                                      ("/paid", {"paid_on": "2031-06-01", "payment_method": "cheque"}, 200)):  # fmt: skip
            seen.clear()
            ok(client.post(f"{url}{path}", headers=owner, json=payload), status)
            assert any("FROM coach_payout" in q and "FOR UPDATE" in q for q in seen), path
    finally:
        event.remove(Engine, "before_cursor_execute", spy)


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


def test_changing_a_share_rule_or_an_engagement_audits_the_old_and_new_values(client, tenant, owner, coached):
    """70% to 90% on the same date: the audit row carries both percents, not a bare flag."""
    c = coached
    rule = {"staff_payee_id": c.payee["id"], "effective_from_on": "2031-01-01", "coach_share_pct": "90",
            "court_fee_minor": 500}  # fmt: skip
    saved = ok(client.put(f"{API}/coach-share-rules", headers=owner, json=rule), 200)
    [changes] = [r[0] for r in rows(tenant, select(AuditEvent.changes).where(AuditEvent.entity_id == saved["id"])
                                    .order_by(AuditEvent.occurred_at.desc()).limit(1))]  # fmt: skip
    assert changes["coach_share_pct"] == ["70.00", "90"] and changes["court_fee_minor"] == [0, 500]
    assert changes["effective_from_on"] == ["2031-01-01", "2031-01-01"]
    term = ok(client.post(f"{API}/staff-payees/{c.payee['id']}/engagements", headers=owner,
                          json={"engagement": "employee", "effective_from_on": "2031-01-01"}))  # fmt: skip
    [changes] = [r[0] for r in rows(tenant, select(AuditEvent.changes).where(AuditEvent.entity_id == term["id"])
                                    .order_by(AuditEvent.occurred_at.desc()).limit(1))]  # fmt: skip
    assert changes["engagement"] == ["independent", "employee"]


def test_a_coachs_report_and_own_view_agree_on_what_is_theirs(client, tenant, owner, coached):
    """One meaning of "own": the payee linked to the coach's sign-in, even when their calendar link is elsewhere."""
    c = coached
    _mark(client, tenant, c, "attended")
    email, ines = add_staff(tenant, "coach", location_ids=[c.f.location])
    ok(client.patch(f"{API}/staff-payees/{c.payee['id']}", headers=owner, json={"staff_user_id": str(ines)}), 200)
    with tenant_session(tenant.id) as session:  # the coach's calendar link moved off this column
        session.get_one(StaffUser, ines).linked_resource_id = None
    headers = login(client, tenant, email)
    mine = sum(e["coach_share_minor"] for e in ok(client.get(f"{API}/coach-earnings", headers=headers), 200)["data"])
    report = ok(client.post(f"{API}/report-runs", headers=headers, json={"report_key": "coach_revenue_split",
                "params": {"from_on": "2031-05-01", "to_on": "2031-05-31"}}), 200)  # fmt: skip
    assert mine == report["totals"]["coach_share_minor"] == 700


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
    huge = {"effective_from_on": "2031-07-01", "coach_share_pct": "50", "court_fee_minor": 10**10}
    assert client.put(url, headers=owner, json=huge).status_code == 422
    unknown = client.put(url, headers=owner, json={"reservation_type_id": c.payee["id"], "effective_from_on": "2031-07-01",
                                                   "coach_share_pct": "50"})  # fmt: skip
    assert unknown.status_code == 422
    ok(client.delete(f"{url}/{later['id']}", headers=owner), 204)
    assert len(ok(client.get(url, headers=owner), 200)["data"]) == 1
    taxed = ok(client.put(f"{API}/staff-payees/{c.payee['id']}/tax-form", headers=owner,
                          json={"tax_form_on_file_on": "2031-01-15"}), 200)  # fmt: skip
    assert taxed["tax_form_on_file_on"] == "2031-01-15"
    assert scalar(tenant, select(func.count()).select_from(CoachEarning)) == 0  # rules alone earn nothing
