"""Freeze, suspension and cancel (MEM-12 to MEM-16; ADR 0005 sections 4 to 6), travelling in time at the service
layer. The standing plan is 12 monthly periods of 31.00 sold on 1 January 2025: the term ends 31 December."""

from datetime import date, timedelta
from uuid import UUID

import pytest

from app.core.errors import Conflict, PermissionDenied, ValidationFailed
from app.modules.memberships import service
from app.modules.memberships.tests.support import (
    account_credit,
    at,
    charges,
    contract,
    daily,
    event_types,
    invoices,
    open_balance,
    pay,
    periods,
    row_dates,
    run,
    scheduled_total,
    sell_at,
    tx,
    world,
)

D = date
JAN1 = D(2025, 1, 1)
TOTAL = 12 * 3100


@pytest.fixture
def w(client, tenant, owner):
    return world(client, owner, tenant, auto_renew_lead_count=30, auto_renew_lead_unit="day")


def _status(w, sold, day: date) -> dict:
    with tx(w.tenant) as session:
        return service.eligibility(session, UUID(w.person["id"]), day)


# --- freeze ------------------------------------------------------------------------------------------------------


def test_freeze_pauses_billing_extends_the_term_and_never_changes_money(w):
    sold = sell_at(w, JAN1)
    pay(w, JAN1, 3100, sold["invoice_id"])
    assert daily(w.tenant, D(2025, 2, 1))["periods_billed"] == 1
    assert daily(w.tenant, D(2025, 3, 1))["periods_billed"] == 1  # March is billed and stays unpaid
    freeze = run(
        w.tenant, D(2025, 3, 10), service.freeze_contract, sold["id"], {"end_on": D(2025, 4, 9), "remarks": "Injury"}
    )

    frozen = contract(w.tenant, sold["id"])
    assert (frozen.status, frozen.end_on, frozen.original_end_on) == (
        "frozen",
        D(2026, 1, 31),
        D(2025, 12, 31),
    )  # 31 days out
    assert (frozen.renew_on, frozen.is_auto_renew, frozen.is_autopay) == (
        D(2026, 1, 1),
        True,
        False,
    )  # flags not flipped
    assert freeze.extended_days_count == 31 and scheduled_total(w.tenant, sold["id"]) == TOTAL
    withheld = periods(w.tenant, sold["id"], "withheld")
    assert len(withheld) == 9 and {p.withheld_by_freeze_id for p in withheld} == {freeze.id}
    # billing restarts on the resume date and steps by cadence from there: no realignment to the 1st
    assert [p.due_on for p in withheld][:3] == [D(2025, 4, 10), D(2025, 5, 10), D(2025, 6, 10)]
    assert (withheld[-1].service_during.lower, withheld[-1].service_during.upper) == (D(2025, 12, 10), D(2026, 1, 10))
    assert (
        open_balance(w.tenant, w.person["id"]) == 6200
    )  # February and March were consumed before the freeze: still owed
    state = _status(w, sold, D(2025, 3, 20))
    assert (state["is_member"], state["status"], state["reason"]) == (False, "frozen", "frozen")

    during = daily(w.tenant, D(2025, 3, 20))
    assert (during["transitions"], during["periods_billed"], during["renewed"]) == (0, 0, 0)
    assert daily(w.tenant, D(2025, 4, 9))["periods_billed"] == 0  # the last frozen day
    resumed = daily(w.tenant, D(2025, 4, 10))
    assert (resumed["transitions"], resumed["periods_billed"]) == (1, 1)
    back = contract(w.tenant, sold["id"])
    assert back.status == "active" and periods(w.tenant, sold["id"], "withheld") == []
    assert event_types(w.tenant, sold["id"]) == [
        "memberships.contract.activated", "memberships.contract.frozen", "memberships.contract.unfrozen",
    ]  # fmt: skip
    assert daily(w.tenant, D(2025, 4, 10)) == {"transitions": 0, "renewed": 0, "periods_billed": 0, "failed": []}
    assert scheduled_total(w.tenant, sold["id"]) == TOTAL and len(charges(w.tenant, w.person["id"])) == 4


def test_frozen_member_is_refused_and_readmitted_by_date_even_when_the_job_is_late(w):
    sold = sell_at(w, JAN1)
    run(
        w.tenant,
        D(2025, 3, 5),
        service.freeze_contract,
        sold["id"],
        {"start_on": D(2025, 3, 10), "end_on": D(2025, 3, 19)},
    )
    assert contract(w.tenant, sold["id"]).status == "active"  # the freeze has not begun; no job has run since
    assert _status(w, sold, D(2025, 3, 9))["is_member"] is True
    for day in (D(2025, 3, 10), D(2025, 3, 19)):
        assert (_status(w, sold, day)["is_member"], _status(w, sold, day)["reason"]) == (False, "frozen")
    assert _status(w, sold, D(2025, 3, 20))["is_member"] is True  # day after the freeze end


def test_freeze_unbills_unpaid_periods_inside_it_and_leaves_paid_ones_alone(w):
    run(w.tenant, JAN1, service.update_settings, {"billing_lead_days": 7})
    sold = sell_at(w, JAN1)
    assert daily(w.tenant, D(2025, 1, 25))["periods_billed"] == 1  # February, a week ahead
    february = invoices(w.tenant, w.person["id"])[-1]
    pay(w, D(2025, 1, 26), 3100, february.id)
    assert daily(w.tenant, D(2025, 2, 22))["periods_billed"] == 1  # March, invoiced and unpaid
    freeze = run(
        w.tenant,
        D(2025, 2, 25),
        service.freeze_contract,
        sold["id"],
        {"start_on": D(2025, 2, 26), "end_on": D(2025, 3, 27)},
    )

    rows = {p.service_during.lower: p for p in periods(w.tenant, sold["id"])}
    assert (
        rows[D(2025, 2, 1)].status == "billed" and rows[D(2025, 1, 1)].status == "billed"
    )  # started before the freeze
    march = next(p for p in rows.values() if p.charge_sequence == 1)
    assert (march.status, march.charge_id, march.due_on, march.withheld_by_freeze_id) == (
        "withheld",
        None,
        D(2025, 3, 28),
        freeze.id,
    )
    kinds = sorted((c.kind, c.status) for c in charges(w.tenant, w.person["id"]))
    assert kinds == [("reversal", "active"), ("standard", "active"), ("standard", "active"), ("standard", "reversed")]
    assert (
        open_balance(w.tenant, w.person["id"]) == 3100 and account_credit(w.tenant, w.person["id"]) == 0
    )  # only January is owed
    assert contract(w.tenant, sold["id"]).end_on == D(2026, 1, 30) and scheduled_total(w.tenant, sold["id"]) == TOTAL

    assert daily(w.tenant, D(2025, 2, 26))["transitions"] == 1
    assert daily(w.tenant, D(2025, 3, 21))["periods_billed"] == 0  # inside the lead window, but frozen
    resumed = daily(w.tenant, D(2025, 3, 28))
    assert (resumed["transitions"], resumed["periods_billed"]) == (1, 1)
    again = [c for c in charges(w.tenant, w.person["id"]) if c.source_id == march.id and c.kind == "standard"]
    assert sorted((c.source_line_no, c.status) for c in again) == [
        (0, "reversed"),
        (1, "active"),
    ]  # billed afresh, once
    assert daily(w.tenant, D(2025, 3, 28))["periods_billed"] == 0


def test_open_ended_freeze_holds_the_contract_until_an_end_date_is_saved(w):
    sold = sell_at(w, JAN1)
    before = row_dates(w.tenant, sold["id"])
    freeze = run(w.tenant, D(2025, 3, 10), service.freeze_contract, sold["id"], {})
    held = contract(w.tenant, sold["id"])
    assert (held.status, held.end_on, freeze.extended_days_count) == ("frozen", D(2025, 12, 31), 0)
    assert [r[2] for r in row_dates(w.tenant, sold["id"])] == [r[2] for r in before]  # dates wait for the end date
    late = daily(w.tenant, D(2026, 2, 1))  # past the original end: a frozen contract neither expires nor renews
    assert (late["transitions"], late["renewed"], late["periods_billed"]) == (0, 0, 0)
    assert contract(w.tenant, sold["id"]).status == "frozen"

    saved = run(w.tenant, D(2026, 2, 5), service.update_freeze, freeze.id, {"end_on": D(2026, 2, 10)})
    assert saved.extended_days_count == 338 and contract(w.tenant, sold["id"]).end_on == D(2025, 12, 31) + timedelta(
        days=338
    )
    assert periods(w.tenant, sold["id"], "withheld")[0].due_on == D(2026, 2, 11)
    longer = run(w.tenant, D(2026, 2, 6), service.update_freeze, freeze.id, {"end_on": D(2026, 2, 20)})
    assert longer.extended_days_count == 348  # recomputed from the pre-freeze dates, never accumulated
    assert contract(w.tenant, sold["id"]).end_on == D(2025, 12, 31) + timedelta(days=348)
    assert periods(w.tenant, sold["id"], "withheld")[0].due_on == D(2026, 2, 21)
    reopened = run(w.tenant, D(2026, 2, 7), service.update_freeze, freeze.id, {"end_on": None})
    assert reopened.extended_days_count == 0 and contract(w.tenant, sold["id"]).end_on == D(2025, 12, 31)
    assert scheduled_total(w.tenant, sold["id"]) == TOTAL


def test_removing_a_freeze_before_it_begins_restores_the_schedule_exactly(w):
    sold = sell_at(w, JAN1)
    before = row_dates(w.tenant, sold["id"])
    freeze = run(
        w.tenant,
        D(2025, 3, 5),
        service.freeze_contract,
        sold["id"],
        {"start_on": D(2025, 3, 10), "end_on": D(2025, 4, 9)},
    )
    assert row_dates(w.tenant, sold["id"]) != before and contract(w.tenant, sold["id"]).status == "active"
    removed = run(w.tenant, D(2025, 3, 6), service.remove_freeze, freeze.id, {"removal_remarks": "Changed their mind"})
    assert removed.removed_at is not None and removed.extended_days_count == 0
    assert row_dates(w.tenant, sold["id"]) == before
    back = contract(w.tenant, sold["id"])
    assert (back.end_on, back.renew_on, back.status) == (D(2025, 12, 31), D(2025, 12, 1), "active")
    with tx(w.tenant) as session:
        assert len(service.list_freezes(session, session.info["actor"], sold["id"])) == 1  # kept for history
    with pytest.raises(Conflict, match="already ended"):
        run(w.tenant, D(2025, 3, 6), service.remove_freeze, freeze.id, {})


def test_unfreezing_a_running_freeze_ends_it_yesterday_and_resumes_today(w):
    sold = sell_at(w, JAN1)
    freeze = run(w.tenant, D(2025, 3, 10), service.freeze_contract, sold["id"], {"end_on": D(2025, 4, 9)})
    ended = run(w.tenant, D(2025, 3, 15), service.remove_freeze, freeze.id, {})
    assert (ended.during.lower, ended.during.upper, ended.extended_days_count) == (D(2025, 3, 10), D(2025, 3, 15), 5)
    back = contract(w.tenant, sold["id"])
    assert (back.status, back.end_on) == ("active", D(2026, 1, 5))  # the five days actually frozen
    due = [p.due_on for p in periods(w.tenant, sold["id"], "scheduled")]
    assert due[:4] == [D(2025, 2, 1), D(2025, 3, 1), D(2025, 3, 15), D(2025, 4, 15)]  # billing resumes today
    assert daily(w.tenant, D(2025, 3, 15))["periods_billed"] == 3 and scheduled_total(w.tenant, sold["id"]) == TOTAL


def test_freeze_guards(w, client, owner):
    sold = sell_at(w, JAN1)
    freeze = lambda day, data: run(w.tenant, day, service.freeze_contract, sold["id"], data)  # noqa: E731
    with pytest.raises(ValidationFailed):
        freeze(D(2025, 3, 10), {"start_on": D(2025, 3, 9)})  # backdated
    with pytest.raises(ValidationFailed):
        freeze(D(2025, 3, 10), {"start_on": D(2026, 1, 1)})  # after the term
    with pytest.raises(ValidationFailed):
        freeze(D(2025, 3, 10), {"start_on": D(2025, 3, 20), "end_on": D(2025, 3, 19)})
    first = freeze(D(2025, 3, 1), {"start_on": D(2025, 3, 10), "end_on": D(2025, 3, 19)})
    with pytest.raises(Conflict) as overlap:
        freeze(D(2025, 3, 1), {"start_on": D(2025, 3, 19), "end_on": D(2025, 3, 25)})
    assert overlap.value.code == "freeze-overlap"
    freeze(D(2025, 3, 1), {"start_on": D(2025, 3, 20), "end_on": D(2025, 3, 25)})  # back to back is fine
    run(
        w.tenant,
        D(2025, 3, 1),
        service.suspend_contract,
        sold["id"],
        {"start_on": D(2025, 5, 1), "end_on": D(2025, 5, 10)},
    )
    with pytest.raises(Conflict) as clash:
        freeze(D(2025, 3, 1), {"start_on": D(2025, 5, 10), "end_on": D(2025, 5, 20)})
    assert clash.value.code == "freeze-suspension-overlap"
    with pytest.raises(Conflict) as extend:
        run(w.tenant, D(2025, 3, 2), service.update_freeze, first.id, {"end_on": D(2025, 3, 22)})
    assert extend.value.code == "freeze-overlap"
    with pytest.raises(ValidationFailed):
        run(w.tenant, D(2025, 3, 2), service.update_freeze, first.id, {"end_on": D(2025, 3, 1)})
    assert daily(w.tenant, D(2025, 3, 10))["transitions"] == 1
    with pytest.raises(Conflict, match="Only an active"):
        freeze(D(2025, 3, 10), {"start_on": D(2025, 4, 1)})  # already frozen
    with pytest.raises(Conflict) as ended:
        run(w.tenant, D(2025, 3, 20), service.update_freeze, first.id, {"end_on": D(2025, 3, 30)})
    assert ended.value.code == "freeze-ended"

    run(w.tenant, JAN1, service.update_settings, {"is_remark_required_on_freeze": True, "is_remark_required_on_suspend": True,
                                                   "is_remark_required_on_cancel": True})  # fmt: skip
    other = world(client, owner, w.tenant)
    second = sell_at(other, JAN1)
    for command, data in ((service.freeze_contract, {}), (service.suspend_contract, {"remarks": "  "}),
                          (service.cancel_contract, {"reason": "voluntary"})):  # fmt: skip
        with pytest.raises(ValidationFailed) as missing:
            run(other.tenant, D(2025, 2, 1), command, second["id"], data)
        assert missing.value.code == "remark-required"
    assert (
        run(other.tenant, D(2025, 2, 1), service.freeze_contract, second["id"], {"remarks": "Travelling"}).remarks
        == "Travelling"
    )


def test_a_freeze_moves_the_upcoming_successor_with_the_term(w):
    sold = sell_at(w, JAN1)
    assert daily(w.tenant, D(2025, 12, 1))["renewed"] == 1
    with tx(w.tenant) as session:
        successor_id = service._successor(session, sold["id"]).id
    run(
        w.tenant,
        D(2025, 12, 5),
        service.freeze_contract,
        sold["id"],
        {"start_on": D(2025, 12, 10), "end_on": D(2025, 12, 19)},
    )
    current, successor = contract(w.tenant, sold["id"]), contract(w.tenant, successor_id)
    assert (current.end_on, successor.start_on, successor.end_on) == (D(2026, 1, 10), D(2026, 1, 11), D(2027, 1, 10))
    first = periods(w.tenant, successor_id)[0]
    assert (first.due_on, first.service_during.lower, first.service_during.upper) == (
        D(2026, 1, 11),
        D(2026, 1, 11),
        D(2026, 2, 11),
    )
    assert scheduled_total(w.tenant, successor_id) == TOTAL


# --- suspension --------------------------------------------------------------------------------------------------


def test_suspension_denies_access_keeps_dues_billing_and_bills_a_fee_per_period(w):
    sold = sell_at(w, JAN1)
    suspension = run(w.tenant, D(2025, 1, 20), service.suspend_contract, sold["id"],
                     {"end_on": D(2025, 3, 10), "fee_minor": 500, "remarks": "Unpaid locker damage"})  # fmt: skip
    suspended = contract(w.tenant, sold["id"])
    assert (suspended.status, suspended.end_on, suspended.renew_on) == (
        "suspended",
        D(2025, 12, 31),
        D(2025, 12, 1),
    )  # no dates move
    fees = [p for p in periods(w.tenant, sold["id"]) if p.kind == "suspension_fee"]
    # one at the start (no dues fall due that day) and one beside each dues period that falls due inside
    assert [(p.due_on, p.amount_minor, p.suspension_id) for p in fees] == [
        (D(2025, 1, 20), 500, suspension.id), (D(2025, 2, 1), 500, suspension.id), (D(2025, 3, 1), 500, suspension.id)]  # fmt: skip
    state = _status(w, sold, D(2025, 2, 1))
    assert (state["is_member"], state["status"], state["reason"]) == (False, "suspended", "suspended")

    billed = daily(w.tenant, D(2025, 2, 1))  # dues continue: February plus the two fees now due
    assert (billed["periods_billed"], billed["transitions"]) == (3, 0)
    assert invoices(w.tenant, w.person["id"])[-1].total_minor == 3100 + 500 + 500

    ended = run(w.tenant, D(2025, 2, 10), service.remove_suspension, suspension.id, {"removal_remarks": "Settled"})
    assert (ended.during.lower, ended.during.upper, ended.removed_at) == (D(2025, 1, 20), D(2025, 2, 10), None)
    assert contract(w.tenant, sold["id"]).status == "active"
    fees = {
        p.due_on: (p.status, p.cancelled_reason) for p in periods(w.tenant, sold["id"]) if p.kind == "suspension_fee"
    }
    assert fees[D(2025, 3, 1)] == ("cancelled", "suspension_ended") and fees[D(2025, 2, 1)] == ("billed", None)
    assert event_types(w.tenant, sold["id"]) == [
        "memberships.contract.activated", "memberships.contract.suspended", "memberships.contract.activated"]  # fmt: skip
    assert _status(w, sold, D(2025, 2, 10))["is_member"] is True
    assert daily(w.tenant, D(2025, 3, 1))["periods_billed"] == 1  # only March dues: the fee row was cancelled


def test_suspension_edits_and_guards(w):
    sold = sell_at(w, JAN1)
    plain = run(
        w.tenant,
        D(2025, 1, 20),
        service.suspend_contract,
        sold["id"],
        {"start_on": D(2025, 2, 10), "end_on": D(2025, 2, 20)},
    )
    assert plain.fee_minor is None and not [p for p in periods(w.tenant, sold["id"]) if p.kind == "suspension_fee"]
    assert contract(w.tenant, sold["id"]).status == "active"  # future-dated
    with pytest.raises(Conflict) as overlap:
        run(w.tenant, D(2025, 1, 20), service.suspend_contract, sold["id"], {"start_on": D(2025, 2, 15)})
    assert overlap.value.code == "suspension-overlap"
    run(
        w.tenant,
        D(2025, 1, 20),
        service.freeze_contract,
        sold["id"],
        {"start_on": D(2025, 4, 1), "end_on": D(2025, 4, 10)},
    )
    with pytest.raises(Conflict) as clash:
        run(
            w.tenant,
            D(2025, 1, 20),
            service.suspend_contract,
            sold["id"],
            {"start_on": D(2025, 4, 5), "end_on": D(2025, 4, 6)},
        )
    assert clash.value.code == "freeze-suspension-overlap"
    with pytest.raises(Conflict):
        run(w.tenant, D(2025, 1, 21), service.update_suspension, plain.id, {"end_on": D(2025, 4, 2)})  # into the freeze
    with pytest.raises(ValidationFailed):
        run(w.tenant, D(2025, 1, 21), service.suspend_contract, sold["id"], {"start_on": D(2025, 1, 1)})

    withdrawn = run(w.tenant, D(2025, 1, 22), service.remove_suspension, plain.id, {})
    assert withdrawn.removed_at is not None  # never began: withdrawn outright
    paid = run(w.tenant, D(2025, 1, 22), service.suspend_contract, sold["id"],
               {"start_on": D(2025, 2, 10), "end_on": D(2025, 2, 20), "fee_minor": 700})  # fmt: skip

    def fee_dates():
        return sorted(p.due_on for p in periods(w.tenant, sold["id"], "scheduled") if p.kind == "suspension_fee")

    assert fee_dates() == [D(2025, 2, 10)]
    run(w.tenant, D(2025, 1, 23), service.update_suspension, paid.id, {"end_on": D(2025, 3, 15), "remarks": "Longer"})
    assert fee_dates() == [D(2025, 2, 10), D(2025, 3, 1)]
    run(w.tenant, D(2025, 1, 24), service.update_suspension, paid.id, {"end_on": D(2025, 2, 12)})
    assert fee_dates() == [D(2025, 2, 10)]
    assert daily(w.tenant, D(2025, 2, 21))["transitions"] == 0  # began and ended between runs: the dates decide
    with pytest.raises(Conflict) as ended:
        run(w.tenant, D(2025, 2, 21), service.update_suspension, paid.id, {"end_on": D(2025, 3, 1)})
    assert ended.value.code == "suspension-ended"
    with tx(w.tenant) as session:
        assert len(service.list_suspensions(session, session.info["actor"], sold["id"])) == 2


def test_a_contract_suspended_at_renewal_hands_the_suspension_to_its_successor(w):
    sold = sell_at(w, JAN1)
    run(w.tenant, D(2025, 11, 20), service.suspend_contract, sold["id"], {"fee_minor": 500})  # open-ended
    assert daily(w.tenant, D(2025, 12, 1))["renewed"] == 1
    with tx(w.tenant) as session:
        successor_id = service._successor(session, sold["id"]).id
    rows = periods(w.tenant, successor_id)
    assert sum(p.amount_minor for p in rows if p.kind == "dues") == TOTAL
    assert [p.amount_minor for p in rows if p.kind == "suspension_fee"] == [500] * 12  # dues plus fee, every period
    turn = daily(w.tenant, D(2026, 1, 1))
    assert turn["transitions"] == 2 and turn["failed"] == []
    assert (contract(w.tenant, sold["id"]).status, contract(w.tenant, successor_id).status) == ("expired", "suspended")
    assert sorted(event_types(w.tenant, successor_id)) == [
        "memberships.contract.activated",
        "memberships.contract.suspended",
    ]


# --- cancel ------------------------------------------------------------------------------------------------------


def test_cancel_on_the_start_date_reverses_everything_and_can_refund(w):
    sold = sell_at(w, JAN1, payment={"amount_minor": 3100, "tender_kind": "cash"})
    quote = run(w.tenant, D(2025, 1, 5), service.quote_cancellation, sold["id"], JAN1)
    assert (quote["is_full_reversal"], quote["reversed_minor"], quote["paid_on_reversed_minor"]) == (True, 3100, 3100)
    assert len(quote["periods_voided"]) == 11 and quote["proposed_credit_minor"] == 0
    done = run(w.tenant, D(2025, 1, 5), service.cancel_contract, sold["id"],
               {"reason": "administrative_error", "effective_on": JAN1, "is_refunded": True, "remarks": "Wrong client"})  # fmt: skip
    assert (done["status"], done["cancelled_on"], done["end_on"], done["cancel_reason"]) == (
        "cancelled", JAN1, JAN1, "administrative_error")  # fmt: skip
    assert done["released_minor"] == 3100 and [(r["amount_minor"], r["status"]) for r in done["refunds"]] == [
        (3100, "succeeded")
    ]
    assert {p.status for p in periods(w.tenant, sold["id"])} == {"cancelled"}
    assert open_balance(w.tenant, w.person["id"]) == 0 and account_credit(w.tenant, w.person["id"]) == 0
    assert event_types(w.tenant, sold["id"])[-1] == "memberships.contract.cancelled"
    assert _status(w, sold, D(2025, 1, 6))["is_member"] is False
    with pytest.raises(Conflict):
        run(w.tenant, D(2025, 1, 6), service.cancel_contract, sold["id"], {"reason": "voluntary"})
    again = sell_at(w, D(2025, 1, 6))  # a cancelled contract no longer blocks a new sale
    assert again["status"] == "active"


def test_mid_term_cancel_applies_the_credit_staff_confirm_and_undo_brings_the_term_back(w):
    sold = sell_at(w, JAN1, payment={"amount_minor": 3100, "tender_kind": "cash"})
    quote = run(w.tenant, D(2025, 1, 10), service.quote_cancellation, sold["id"], None)
    assert (quote["effective_on"], quote["proposed_credit_minor"], quote["max_credit_minor"]) == (
        D(2025, 1, 10),
        2100,
        3100,
    )
    assert quote["is_full_reversal"] is False and quote["periods_reversed"] == [] and len(quote["periods_voided"]) == 11
    with pytest.raises(ValidationFailed):
        run(
            w.tenant, D(2025, 1, 10), service.cancel_contract, sold["id"], {"reason": "voluntary", "credit_minor": 3101}
        )
    with pytest.raises(ValidationFailed):
        run(
            w.tenant,
            D(2025, 1, 10),
            service.cancel_contract,
            sold["id"],
            {"reason": "voluntary", "effective_on": D(2024, 12, 31)},
        )

    done = run(
        w.tenant, D(2025, 1, 10), service.cancel_contract, sold["id"], {"reason": "voluntary", "credit_minor": 2100}
    )
    assert (done["status"], done["end_on"], done["credit_minor"], done["released_minor"], done["refunds"]) == (
        "cancelled", D(2025, 1, 10), 2100, 2100, [])  # fmt: skip
    january = next(p for p in periods(w.tenant, sold["id"]) if p.status == "billed")
    assert (january.amount_minor, january.charge_sequence) == (1000, 1)
    standard = sorted(
        (c.total_minor, c.status, c.applied_minor) for c in charges(w.tenant, w.person["id"]) if c.kind == "standard"
    )
    assert standard == [(1000, "active", 1000), (3100, "reversed", 0)]  # the used ten days stay paid
    assert open_balance(w.tenant, w.person["id"]) == 0 and account_credit(w.tenant, w.person["id"]) == 2100

    undone = run(w.tenant, D(2025, 1, 12), service.undo_cancel, sold["id"])
    assert (undone["status"], undone["end_on"], undone["cancel_reason"], undone["cancelled_on"]) == (
        "active",
        D(2025, 12, 31),
        None,
        None,
    )
    assert len(periods(w.tenant, sold["id"], "scheduled")) == 11 and account_credit(w.tenant, w.person["id"]) == 2100
    assert event_types(w.tenant, sold["id"])[-2:] == [
        "memberships.contract.cancelled",
        "memberships.contract.activated",
    ]
    with pytest.raises(Conflict):
        run(w.tenant, D(2025, 1, 12), service.undo_cancel, sold["id"])
    assert daily(w.tenant, D(2025, 2, 1))["periods_billed"] == 1


def test_a_future_cancel_is_scheduled_and_the_daily_job_closes_the_contract(w):
    sold = sell_at(w, JAN1)
    with pytest.raises(ValidationFailed):
        run(w.tenant, D(2025, 1, 10), service.cancel_contract, sold["id"],
            {"reason": "voluntary", "effective_on": D(2025, 3, 31), "credit_minor": 100})  # fmt: skip
    planned = run(
        w.tenant,
        D(2025, 1, 10),
        service.cancel_contract,
        sold["id"],
        {"reason": "voluntary", "effective_on": D(2025, 3, 31)},
    )
    assert (planned["status"], planned["is_cancel_scheduled"], planned["end_on"], planned["cancelled_on"]) == (
        "active", True, D(2025, 3, 31), None)  # fmt: skip
    assert (planned["is_auto_renew"], planned["auto_renew_disabled_by"]) == (False, "staff")
    assert len(periods(w.tenant, sold["id"], "cancelled")) == 9 and len(periods(w.tenant, sold["id"], "scheduled")) == 2
    for command in (service.freeze_contract, service.suspend_contract):
        with pytest.raises(Conflict):
            run(w.tenant, D(2025, 1, 11), command, sold["id"], {})
    with pytest.raises(Conflict):
        run(w.tenant, D(2025, 1, 11), service.renew_contract, sold["id"], {})
    assert daily(w.tenant, D(2025, 3, 31))["transitions"] == 0 and _status(w, sold, D(2025, 3, 31))["is_member"] is True
    assert daily(w.tenant, D(2025, 4, 1))["transitions"] == 1
    closed = contract(w.tenant, sold["id"])
    assert (closed.status, closed.cancelled_on, closed.cancel_reason) == ("cancelled", D(2025, 3, 31), "voluntary")
    assert event_types(w.tenant, sold["id"])[-1] == "memberships.contract.cancelled"
    assert open_balance(w.tenant, w.person["id"]) == 3 * 3100  # the consumed months stay owed


def test_undoing_a_scheduled_cancel_and_cancelling_before_the_start(w, client, owner):
    sold = sell_at(w, JAN1)
    run(
        w.tenant,
        D(2025, 1, 10),
        service.cancel_contract,
        sold["id"],
        {"reason": "voluntary", "effective_on": D(2025, 3, 31)},
    )
    undone = run(w.tenant, D(2025, 2, 1), service.undo_cancel, sold["id"])
    assert (undone["status"], undone["end_on"], undone["is_cancel_scheduled"]) == ("active", D(2025, 12, 31), False)
    assert len(periods(w.tenant, sold["id"], "scheduled")) == 11 and scheduled_total(w.tenant, sold["id"]) == TOTAL

    other = world(client, owner, w.tenant, initiation_fee_minor=5000)
    future = sell_at(other, JAN1, start_on=D(2025, 6, 1))
    assert (future["status"], future["invoice_id"] is not None) == (
        "upcoming",
        True,
    )  # the enrolment fee is due at sale
    gone = run(other.tenant, D(2025, 1, 2), service.cancel_contract, future["id"], {"reason": "other"})
    assert (gone["status"], gone["cancelled_on"], gone["end_on"]) == ("cancelled", D(2025, 6, 1), D(2025, 6, 1))
    assert open_balance(other.tenant, other.person["id"]) == 0 and {
        p.status for p in periods(other.tenant, future["id"])
    } == {"cancelled"}
    # the client holds another membership in the old dates now: the undo is refused
    sell_at(other, D(2025, 1, 3), start_on=D(2025, 7, 1))
    with pytest.raises(Conflict) as overlap:
        run(other.tenant, D(2025, 1, 4), service.undo_cancel, future["id"])
    assert overlap.value.code == "membership-overlap"


def test_cancel_takes_the_upcoming_successor_with_it_and_prepaid_periods_become_credit(w, client, owner):
    sold = sell_at(w, JAN1)
    assert daily(w.tenant, D(2025, 12, 1))["renewed"] == 1
    with tx(w.tenant) as session:
        successor_id = service._successor(session, sold["id"]).id
    run(w.tenant, D(2025, 12, 5), service.cancel_contract, sold["id"], {"reason": "voluntary"})
    successor = contract(w.tenant, successor_id)
    assert (successor.status, successor.previous_contract_id, successor.cancelled_on) == (
        "cancelled",
        None,
        successor.start_on,
    )
    run(w.tenant, D(2025, 12, 6), service.undo_cancel, sold["id"])  # detached, so the term can be renewed again
    run(w.tenant, D(2025, 12, 6), service.update_contract, sold["id"], {"is_auto_renew": True})
    assert daily(w.tenant, D(2025, 12, 6))["renewed"] == 1

    prepaid = world(client, owner, w.tenant, billing_occurrences_count=3)
    whole = sell_at(prepaid, JAN1, invoice_mode="single", payment={"amount_minor": 9300, "tender_kind": "cash"})
    done = run(prepaid.tenant, D(2025, 1, 31), service.cancel_contract, whole["id"], {"reason": "voluntary"})
    assert done["released_minor"] == 6200 and account_credit(prepaid.tenant, prepaid.person["id"]) == 6200
    assert [p.status for p in periods(prepaid.tenant, whole["id"])] == ["billed", "cancelled", "cancelled"]


def test_refund_on_cancel_needs_the_refund_permission(w, tenant):
    from app.core.auth import Principal

    sold = sell_at(w, JAN1, payment={"amount_minor": 3100, "tender_kind": "cash"})
    canceller = Principal(kind="staff", tenant_id=tenant.id, staff_user_id=tenant.owner_id, location_ids=None,
                          permissions={"memberships.contract.cancel": "all"})  # fmt: skip
    with at(D(2025, 1, 5)), pytest.raises(PermissionDenied), tx(tenant) as session:
        service.cancel_contract(
            session, canceller, sold["id"], {"reason": "voluntary", "effective_on": JAN1, "is_refunded": True}
        )
    assert contract(tenant, sold["id"]).status == "active"
