"""`member_on`: was the client actually a member on a date (rentals price and gate by it). A contract counts from
its start to its effective end (cancellation, expiry), never inside a freeze or suspension, and never when it was
un-sold (cancelled before or on its start, everything reversed). The standing plan: 12 monthly periods sold on
1 January 2025, so the term ends 31 December."""

from datetime import date
from uuid import UUID

import pytest

from app.modules.memberships import service
from app.modules.memberships.tests.support import daily, run, sell_at, tx, world

D = date
JAN1 = D(2025, 1, 1)


def _live(w):
    sell_at(w, JAN1, is_auto_renew=False)


def _auto_renewing(w):
    sell_at(w, JAN1, is_auto_renew=True)


def _renewed(w):
    sell_at(w, JAN1, is_auto_renew=True)
    assert daily(w.tenant, D(2025, 12, 1))["renewed"] == 1
    daily(w.tenant, D(2026, 1, 1))


def _expired(w):
    sell_at(w, JAN1, is_auto_renew=False)
    daily(w.tenant, D(2026, 1, 1))


def _cancelled_before_start(w):
    sold = sell_at(w, D(2024, 12, 1), start_on=JAN1)
    run(w.tenant, D(2024, 12, 10), service.cancel_contract, sold["id"], {"reason": "voluntary"})


def _unsold_on_its_start(w):
    sold = sell_at(w, JAN1)
    run(w.tenant, D(2025, 1, 5), service.cancel_contract, sold["id"],
        {"reason": "administrative_error", "effective_on": JAN1})  # fmt: skip


def _cancelled_mid_term(w):
    sold = sell_at(w, JAN1)
    run(w.tenant, D(2025, 3, 10), service.cancel_contract, sold["id"], {"reason": "voluntary"})


def _frozen(w):
    sold = sell_at(w, JAN1)
    run(w.tenant, D(2025, 3, 1), service.freeze_contract, sold["id"],
        {"start_on": D(2025, 3, 10), "end_on": D(2025, 3, 20)})  # fmt: skip


def _suspended(w):
    sold = sell_at(w, JAN1)
    run(w.tenant, D(2025, 3, 1), service.suspend_contract, sold["id"],
        {"start_on": D(2025, 5, 1), "end_on": D(2025, 5, 10)})  # fmt: skip


CASES = {
    "live": (_live, {D(2024, 12, 31): False, JAN1: True, D(2025, 12, 31): True, D(2026, 1, 1): False}),
    "auto_renewing": (_auto_renewing, {JAN1: True, D(2026, 3, 1): True}),  # covers past its end until it stops
    "renewed": (_renewed, {D(2025, 6, 1): True, D(2026, 6, 1): True}),
    "expired": (_expired, {D(2025, 6, 1): True, D(2025, 12, 31): True, D(2026, 1, 1): False}),
    "cancelled_before_start": (_cancelled_before_start, {JAN1: False, D(2025, 6, 1): False}),
    "unsold_on_its_start": (_unsold_on_its_start, {JAN1: False, D(2025, 1, 5): False}),
    "cancelled_mid_term": (_cancelled_mid_term, {D(2025, 2, 1): True, D(2025, 3, 10): True, D(2025, 3, 11): False}),
    "frozen": (_frozen, {D(2025, 3, 9): True, D(2025, 3, 15): False, D(2025, 3, 21): True}),
    "suspended": (_suspended, {D(2025, 4, 30): True, D(2025, 5, 5): False, D(2025, 5, 11): True}),
}


@pytest.mark.parametrize("case", CASES)
def test_member_on_counts_only_dates_the_client_was_a_member(client, owner, tenant, case):
    w = world(client, owner, tenant, auto_renew_lead_count=30, auto_renew_lead_unit="day")
    setup, expected = CASES[case]
    setup(w)
    with tx(tenant) as session:
        got = {day: service.member_on(session, UUID(w.person["id"]), day) is not None for day in expected}
    assert got == expected
