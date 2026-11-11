"""Renewal, the daily job, time zones, price changes, sharing, visits, the portal opt-out, merge and erasure
(MEM-10, MEM-11, MEM-17 to MEM-20; ADR 0005 sections 6 to 8)."""

import threading
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.auth import Principal
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules import billing, clients, platform
from app.modules.billing.models import Refund
from app.modules.memberships import service
from app.modules.memberships.models import MembershipContract, MembershipShare, MembershipVisit
from app.modules.memberships.tests.support import (
    API,
    SYSTEM,
    as_ids,
    at,
    charges,
    contract,
    daily,
    event_types,
    membership_plan,
    ok,
    open_balance,
    periods,
    refused,
    run,
    sale,
    scheduled_total,
    sell_at,
    tx,
    world,
)
from conftest import new_client

D = date
JAN1 = D(2025, 1, 1)


@pytest.fixture
def w(client, tenant, owner):
    return world(client, owner, tenant, auto_renew_lead_count=30, auto_renew_lead_unit="day")


def _successor(tenant, contract_id) -> MembershipContract | None:
    with tx(tenant) as session:
        return service._successor(session, contract_id)


# --- renewal -----------------------------------------------------------------------------------------------------


def test_job_renews_once_at_the_lead_and_the_successor_takes_over_at_term_end(w, client, owner):
    kid = new_client(client, owner, w.location_id)
    sold = sell_at(w, JAN1, share_client_ids=[UUID(kid["id"])])
    ok(
        client.patch(
            f"{API}/membership-plans/{w.plan['id']}",
            headers=owner,
            json={"term_fee_minor": 9900, "initiation_fee_minor": 500},
        )
    )
    queue = run(w.tenant, D(2025, 11, 15), service.list_upcoming_renewals, 30, None)
    assert [(r["contract_id"], r["renew_on"], r["successor_contract_id"], r["next_term_fee_minor"]) for r in queue] == [
        (sold["id"], D(2025, 12, 1), None, 3100)]  # fmt: skip
    assert run(w.tenant, D(2025, 10, 1), service.list_upcoming_renewals, 30, None) == []

    assert daily(w.tenant, D(2025, 11, 30))["renewed"] == 0
    assert daily(w.tenant, D(2025, 12, 1))["renewed"] == 1
    assert daily(w.tenant, D(2025, 12, 1))["renewed"] == 0 and daily(w.tenant, D(2025, 12, 2))["renewed"] == 0
    successor = _successor(w.tenant, sold["id"])
    assert (successor.status, successor.start_on, successor.end_on, successor.sales_channel) == (
        "upcoming", D(2026, 1, 1), D(2026, 12, 31), "renewal")  # fmt: skip
    # same terms = the price as sold (a price lock), never prorated, no second enrolment fee
    assert (successor.term_fee_minor, successor.initiation_fee_minor, successor.is_prorated) == (3100, 0, False)
    assert {p.kind for p in periods(w.tenant, successor.id)} == {"dues"} and scheduled_total(
        w.tenant, successor.id
    ) == 12 * 3100
    assert (successor.is_auto_renew, successor.renew_on) == (True, D(2026, 12, 1))
    with tx(w.tenant) as session:
        shares = session.scalars(
            select(MembershipShare).where(MembershipShare.membership_contract_id == successor.id)
        ).all()
    assert [(s.client_id, s.origin) for s in shares] == [(UUID(kid["id"]), "carried_from_previous")]
    assert event_types(w.tenant, sold["id"])[-1] == "memberships.contract.renewed"
    queue = run(w.tenant, D(2025, 12, 5), service.list_upcoming_renewals, 30, None)
    assert queue[0]["successor_contract_id"] == successor.id and queue[0]["next_start_on"] == D(2026, 1, 1)

    assert daily(w.tenant, D(2025, 12, 31))["transitions"] == 0  # the last day belongs to the old term
    turn = daily(w.tenant, D(2026, 1, 1))
    assert (turn["transitions"], turn["periods_billed"], turn["failed"]) == (2, 1, [])
    assert (contract(w.tenant, sold["id"]).status, contract(w.tenant, successor.id).status) == ("expired", "active")
    assert event_types(w.tenant, sold["id"])[-1] == "memberships.contract.expired"
    assert daily(w.tenant, D(2026, 1, 1)) == {"transitions": 0, "renewed": 0, "periods_billed": 0, "failed": []}


def test_renewing_into_another_plan_reads_that_plan_now_and_applies_the_renewal_discount(w, client, owner):
    sold = sell_at(w, JAN1)
    gold = membership_plan(client, owner, w.tenant, term_fee_minor=5000, billing_occurrences_count=6, max_visits_count=40,
                           auto_renew_lead_count=14, auto_renew_lead_unit="day")  # fmt: skip
    edited = run(w.tenant, D(2025, 6, 1), service.update_contract, sold["id"],
                 {"renews_as_plan_id": UUID(gold["id"]), "renewal_discount_pct": 10, "renewal_description": "Loyalty price",
                  "renewal_remark": "Promised by Sam"})  # fmt: skip
    assert (edited["renewal_target"], edited["renews_as_plan_id"]) == ("plan", UUID(gold["id"]))
    ok(
        client.patch(f"{API}/membership-plans/{gold['id']}", headers=owner, json={"term_fee_minor": 6000})
    )  # before renewal
    queue = run(w.tenant, D(2025, 11, 15), service.list_upcoming_renewals, 30, None)
    assert (queue[0]["next_name"], queue[0]["next_term_fee_minor"], queue[0]["next_discount_pct"]) == (
        gold["name"],
        6000,
        10,
    )

    assert daily(w.tenant, D(2025, 12, 1))["renewed"] == 1
    successor = _successor(w.tenant, sold["id"])
    assert (successor.name, successor.membership_plan_id, successor.term_fee_minor) == (
        gold["name"],
        UUID(gold["id"]),
        6000,
    )
    assert (successor.end_on, successor.max_visits_count, successor.auto_renew_lead_count) == (D(2026, 6, 30), 40, 14)
    assert (successor.invoice_description, successor.internal_notes, successor.renewal_target) == (
        "Loyalty price",
        "Promised by Sam",
        "same_terms",
    )
    assert {p.amount_minor for p in periods(w.tenant, successor.id)} == {5400}
    renewed = next(e for e in _events(w.tenant, sold["id"]) if e["type"] == "memberships.contract.renewed")
    assert (renewed["term_fee_minor"], renewed["start_on"], renewed["successor_contract_id"]) == (
        6000,
        "2026-01-01",
        str(successor.id),
    )

    back = run(w.tenant, D(2025, 6, 2), service.update_contract, successor.id, {"renewal_target": "same_terms"})
    assert back["renews_as_plan_id"] is None
    with pytest.raises(ValidationFailed):
        run(w.tenant, D(2025, 6, 2), service.update_contract, successor.id, {"renews_as_plan_id": uuid4()})


def _events(tenant, aggregate_id) -> list[dict]:
    from app.core.events import OutboxEvent

    with tx(tenant) as session:
        return list(session.scalars(select(OutboxEvent.payload).where(OutboxEvent.aggregate_id == aggregate_id)))


def test_manual_renew_upgrade_and_its_guards(w, client, owner):
    plain = world(client, owner, w.tenant)  # a plan with no renewal lead never renews by itself
    once = sell_at(plain, JAN1)
    assert (once["is_auto_renew"], once["renew_on"]) == (False, None)
    assert daily(w.tenant, D(2025, 12, 31))["renewed"] == 0
    with pytest.raises(ValidationFailed):
        run(
            w.tenant, D(2025, 6, 1), service.update_contract, once["id"], {"is_auto_renew": True}
        )  # no lead to renew on
    armed = run(w.tenant, D(2025, 6, 1), service.update_contract, once["id"],
                {"is_auto_renew": True, "auto_renew_lead_count": 1, "auto_renew_lead_unit": "month"})  # fmt: skip
    assert armed["renew_on"] == D(2025, 11, 30)

    sold = sell_at(w, JAN1)
    gold = membership_plan(client, owner, w.tenant, term_fee_minor=5000)
    upgraded = run(w.tenant, D(2025, 6, 1), service.renew_contract, sold["id"], {"renews_as_plan_id": UUID(gold["id"])})
    assert (upgraded["status"], upgraded["name"], upgraded["term_fee_minor"], upgraded["previous_contract_id"]) == (
        "upcoming", gold["name"], 5000, sold["id"])  # fmt: skip
    with pytest.raises(Conflict) as twice:
        run(w.tenant, D(2025, 6, 1), service.renew_contract, sold["id"], {})
    assert twice.value.code == "already-renewed"
    assert daily(w.tenant, D(2025, 12, 1))["renewed"] == 1  # only the other contract; this one has its successor
    with pytest.raises(Conflict):
        run(w.tenant, D(2025, 6, 1), service.renew_contract, upgraded["id"], {})  # not started yet
    run(w.tenant, D(2025, 6, 2), service.freeze_contract, sold["id"], {})
    other = world(client, owner, w.tenant, auto_renew_lead_count=30, auto_renew_lead_unit="day")
    frozen = sell_at(other, JAN1)
    run(w.tenant, D(2025, 6, 2), service.freeze_contract, frozen["id"], {})
    with pytest.raises(Conflict):
        run(w.tenant, D(2025, 6, 3), service.renew_contract, frozen["id"], {})  # a frozen contract does not renew
    assert daily(w.tenant, D(2025, 12, 5))["renewed"] == 0


def test_renewal_raced_against_itself_creates_one_successor(w):
    sold = sell_at(w, JAN1)
    barrier, outcomes = threading.Barrier(4), []

    def renew() -> None:
        barrier.wait()
        try:
            with tx(w.tenant) as session:
                outcomes.append(service.renew_contract(session, SYSTEM, sold["id"], {})["id"])
        except Conflict as exc:
            outcomes.append(exc.code)

    with at(D(2025, 12, 1)):
        threads = [threading.Thread(target=renew) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert sorted(map(str, outcomes))[-3:] == ["already-renewed"] * 3 and len(set(map(str, outcomes))) == 2
    with tx(w.tenant) as session:
        chained = session.scalars(
            select(MembershipContract).where(MembershipContract.previous_contract_id == sold["id"])
        ).all()
    assert len(chained) == 1


def test_a_successor_that_would_overlap_another_membership_is_reported_not_created(w, client, owner):
    sold = sell_at(w, JAN1)
    sell_at(w, D(2025, 6, 1), start_on=D(2026, 1, 1))  # staff already sold next year's contract by hand
    result = daily(w.tenant, D(2025, 12, 1))
    assert result["renewed"] == 0 and result["failed"] == [
        {"contract_id": str(sold["id"]), "error": "membership-overlap"}
    ]
    assert _successor(w.tenant, sold["id"]) is None


# --- the daily job -----------------------------------------------------------------------------------------------


def test_daily_job_catches_up_missed_days_and_is_idempotent(w):
    run(w.tenant, JAN1, service.update_settings, {"billing_lead_days": 7})
    sold = sell_at(w, JAN1)
    assert daily(w.tenant, D(2025, 1, 24))["periods_billed"] == 0
    assert daily(w.tenant, D(2025, 1, 25))["periods_billed"] == 1  # 7 days before 1 February
    caught_up = daily(w.tenant, D(2025, 5, 1))  # the job did not run for three months
    assert caught_up["periods_billed"] == 3 and caught_up["failed"] == []
    assert daily(w.tenant, D(2025, 5, 1))["periods_billed"] == 0
    assert len(charges(w.tenant, w.person["id"])) == 5 and open_balance(w.tenant, w.person["id"]) == 5 * 3100
    # the queued actor is the same function, one message per tenant
    with at(D(2025, 5, 2)):
        assert service.run_membership_day.fn(str(w.tenant.id))["periods_billed"] == 0
    with at(D(2025, 5, 25)):
        assert service.run_membership_day.fn(str(w.tenant.id))["periods_billed"] == 1
    assert {p.status for p in periods(w.tenant, sold["id"])} == {"billed", "scheduled"}


def test_one_failing_contract_does_not_block_the_rest(w, client, owner):
    good = sell_at(w, JAN1)
    other = world(client, owner, w.tenant)
    bad = sell_at(other, JAN1)
    ok(client.post(f"{API}/clients/{other.person['id']}/disable", headers=owner))  # billing refuses a disabled client
    result = daily(w.tenant, D(2025, 2, 1))
    assert result["periods_billed"] == 1 and [f["contract_id"] for f in result["failed"]] == [str(bad["id"])]
    assert [p.status for p in periods(w.tenant, good["id"])][:2] == ["billed", "billed"]
    assert [p.status for p in periods(w.tenant, bad["id"])][:2] == ["billed", "scheduled"]


def test_stored_status_always_converges_to_the_date_function(w):
    """ADR 0005 section 2: whatever day the job runs, it lands on effective_status; reads never needed it."""
    sold = sell_at(w, JAN1, start_on=D(2025, 1, 10))
    run(w.tenant, JAN1, service.update_contract, sold["id"], {"is_auto_renew": False})
    run(
        w.tenant,
        D(2025, 1, 12),
        service.freeze_contract,
        sold["id"],
        {"start_on": D(2025, 2, 1), "end_on": D(2025, 2, 10)},
    )
    run(
        w.tenant,
        D(2025, 1, 12),
        service.suspend_contract,
        sold["id"],
        {"start_on": D(2025, 3, 1), "end_on": D(2025, 3, 5)},
    )
    end = contract(w.tenant, sold["id"]).end_on
    expected = {
        D(2025, 1, 9): "upcoming", D(2025, 1, 10): "active", D(2025, 2, 1): "frozen", D(2025, 2, 10): "frozen",
        D(2025, 2, 11): "active", D(2025, 3, 1): "suspended", D(2025, 3, 6): "active", end: "active",
        end + timedelta(days=1): "expired",
    }  # fmt: skip
    for day, status in expected.items():
        with at(day), tx(w.tenant) as session:
            assert service.status_of(session, sold["id"]) == status, day
    assert end == D(2026, 1, 19)  # 12 months from the 10th, plus the ten frozen days
    sparse = {
        D(2025, 2, 5): "frozen",
        D(2025, 3, 2): "suspended",
        D(2025, 9, 1): "active",
        end + timedelta(days=1): "expired",
    }
    for day, status in sparse.items():  # the job runs only now and then, in order
        daily(w.tenant, day)
        with at(day), tx(w.tenant) as session:
            assert contract(w.tenant, sold["id"]).status == service.status_of(session, sold["id"]) == status


@pytest.mark.parametrize(
    ("zone", "start_on", "last_instant_before", "first_instant_of"),
    [
        # local midnight, as UTC instants, on the days around both DST changes
        (
            "America/Chicago",
            D(2025, 3, 9),
            datetime(2025, 3, 9, 5, 59, tzinfo=UTC),
            datetime(2025, 3, 9, 6, 0, tzinfo=UTC),
        ),
        (
            "America/Chicago",
            D(2025, 3, 10),
            datetime(2025, 3, 10, 4, 59, tzinfo=UTC),
            datetime(2025, 3, 10, 5, 0, tzinfo=UTC),
        ),
        (
            "America/Chicago",
            D(2025, 11, 2),
            datetime(2025, 11, 2, 4, 59, tzinfo=UTC),
            datetime(2025, 11, 2, 5, 0, tzinfo=UTC),
        ),
        (
            "America/Chicago",
            D(2025, 11, 3),
            datetime(2025, 11, 3, 5, 59, tzinfo=UTC),
            datetime(2025, 11, 3, 6, 0, tzinfo=UTC),
        ),
        (
            "Pacific/Auckland",
            D(2025, 4, 6),
            datetime(2025, 4, 5, 10, 59, tzinfo=UTC),
            datetime(2025, 4, 5, 11, 0, tzinfo=UTC),
        ),
        (
            "Pacific/Auckland",
            D(2025, 4, 7),
            datetime(2025, 4, 6, 11, 59, tzinfo=UTC),
            datetime(2025, 4, 6, 12, 0, tzinfo=UTC),
        ),
        (
            "Pacific/Auckland",
            D(2025, 9, 28),
            datetime(2025, 9, 27, 11, 59, tzinfo=UTC),
            datetime(2025, 9, 27, 12, 0, tzinfo=UTC),
        ),
        (
            "Pacific/Auckland",
            D(2025, 9, 29),
            datetime(2025, 9, 28, 10, 59, tzinfo=UTC),
            datetime(2025, 9, 28, 11, 0, tzinfo=UTC),
        ),
        (
            "Asia/Kolkata",
            D(2025, 3, 9),
            datetime(2025, 3, 8, 18, 29, tzinfo=UTC),
            datetime(2025, 3, 8, 18, 30, tzinfo=UTC),
        ),
    ],
)
def test_a_contract_starts_at_local_midnight_in_its_location_zone(
    client, tenant, owner, zone, start_on, last_instant_before, first_instant_of
):
    w = world(client, owner, tenant, time_zone=zone)
    with clock.freeze(last_instant_before - timedelta(days=3)), tx(tenant) as session:
        sold = service.sell_contract(session, SYSTEM, as_ids(w, start_on=start_on))
    assert sold["status"] == "upcoming"
    with clock.freeze(last_instant_before), tx(tenant) as session:
        assert service.eligibility(session, UUID(w.person["id"]))["is_member"] is False
        assert service.run_daily(session)["transitions"] == 0
    with clock.freeze(first_instant_of), tx(tenant) as session:
        assert service.eligibility(session, UUID(w.person["id"]))["is_member"] is True  # before any job has run
        result = service.run_daily(session)
    assert (result["transitions"], result["periods_billed"]) == (1, 1)
    assert contract(tenant, sold["id"]).status == "active" and periods(tenant, sold["id"])[0].due_on == start_on


def test_each_location_keeps_its_own_day(client, tenant, owner):
    """One instant, two wall dates: only the location where the day has come activates and bills."""
    chicago, auckland = world(client, owner, tenant), world(client, owner, tenant, time_zone="Pacific/Auckland")
    with at(D(2025, 6, 1)), tx(tenant) as session:
        early = service.sell_contract(session, SYSTEM, as_ids(auckland, start_on=D(2025, 6, 10)))
        late = service.sell_contract(session, SYSTEM, as_ids(chicago, start_on=D(2025, 6, 10)))
    with clock.freeze(datetime(2025, 6, 9, 13, 0, tzinfo=UTC)), tx(tenant) as session:  # 10 June 01:00 in Auckland
        assert service.run_daily(session)["transitions"] == 1
    assert (contract(tenant, early["id"]).status, contract(tenant, late["id"]).status) == ("active", "upcoming")
    with clock.freeze(datetime(2025, 6, 10, 5, 0, tzinfo=UTC)), tx(tenant) as session:  # 10 June 00:00 in Chicago
        assert service.run_daily(session)["transitions"] == 1


# --- price changes on a sold contract ----------------------------------------------------------------------------


def test_reprice_and_single_period_edits_touch_only_what_is_not_billed(w, client, owner):
    sold = sell_at(w, JAN1, customize={"discount_pct": 10})
    assert {p.amount_minor for p in periods(w.tenant, sold["id"])} == {2790}
    repriced = run(w.tenant, D(2025, 3, 15), service.reprice_contract, sold["id"],
                   {"term_fee_minor": 4000, "effective_on": D(2025, 4, 1), "remarks": "Annual increase"})  # fmt: skip
    assert repriced["term_fee_minor"] == 4000
    by_month = {p.service_during.lower.month: p for p in periods(w.tenant, sold["id"])}
    assert (by_month[1].amount_minor, by_month[1].status) == (2790, "billed")  # billed: reversal only
    assert (by_month[3].amount_minor, by_month[3].list_amount_minor) == (2790, 3100)  # before the effective date
    assert (by_month[4].amount_minor, by_month[4].list_amount_minor) == (3600, 4000)  # the discount ratio is kept
    assert scheduled_total(w.tenant, sold["id"]) == 3 * 2790 + 9 * 3600

    april = by_month[4]
    edited = run(
        w.tenant,
        D(2025, 3, 15),
        service.update_period,
        april.id,
        {"amount_minor": 1000, "due_on": D(2025, 4, 5), "description": "April, goodwill"},
    )
    assert (edited.amount_minor, edited.due_on, edited.bill_on, edited.description) == (
        1000,
        D(2025, 4, 5),
        D(2025, 4, 5),
        "April, goodwill",
    )
    with pytest.raises(Conflict) as billed:
        run(w.tenant, D(2025, 3, 15), service.update_period, by_month[1].id, {"amount_minor": 1})
    assert billed.value.code == "period-not-editable"
    assert (
        daily(w.tenant, D(2025, 4, 1))["periods_billed"] == 2 and daily(w.tenant, D(2025, 4, 5))["periods_billed"] == 1
    )
    assert sorted(c.total_minor for c in charges(w.tenant, w.person["id"])) == [1000, 2790, 2790, 2790]
    run(w.tenant, D(2025, 4, 6), service.cancel_contract, sold["id"], {"reason": "voluntary"})
    with pytest.raises(Conflict):
        run(w.tenant, D(2025, 4, 7), service.reprice_contract, sold["id"], {"term_fee_minor": 1})
    with pytest.raises(Conflict):
        run(w.tenant, D(2025, 4, 7), service.update_contract, sold["id"], {"internal_notes": "x"})


def test_contract_edits_over_http(w, client, owner):
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    url = f"{API}/membership-contracts/{sold['id']}"
    edited = ok(
        client.patch(url, headers=owner, json={"max_visits_count": 12, "is_autopay": True, "internal_notes": "VIP"})
    )
    assert (edited["max_visits_count"], edited["is_autopay"], edited["version"]) == (12, True, sold["version"] + 1)
    off = ok(client.patch(url, headers=owner, json={"is_auto_renew": False}))
    assert (off["is_auto_renew"], off["auto_renew_disabled_by"]) == (False, "staff")
    on = ok(client.patch(url, headers=owner, json={"is_auto_renew": True, "max_visits_count": None}))
    assert (on["is_auto_renew"], on["auto_renew_disabled_by"], on["max_visits_count"]) == (True, None, None)
    assert client.patch(url, headers=owner, json={"revenue_on": "2025-01-01"}).status_code == 422  # twelve periods
    assert (
        client.patch(url, headers=owner, json={"term_fee_minor": 1}).status_code == 422
    )  # sold terms are not editable
    seller = ok(client.put(f"{url}/sold-by", headers=owner, json={"sold_by_staff_user_id": None}))
    assert seller["sold_by_staff_user_id"] is None
    assert client.put(f"{url}/sold-by", headers=owner, json={"sold_by_staff_user_id": str(uuid4())}).status_code == 422
    repriced = ok(client.post(f"{url}/reprice", headers=owner, json={"term_fee_minor": 3300}))
    assert repriced["term_fee_minor"] == 3300
    renewals = ok(client.get(f"{API}/membership-contracts/upcoming-renewals?days=366", headers=owner))
    assert [r["contract_id"] for r in renewals] == [sold["id"]] and renewals[0]["next_term_fee_minor"] == 3300
    assert (
        ok(
            client.get(
                f"{API}/membership-contracts/upcoming-renewals?days=1&location_id={w.location_id}", headers=owner
            )
        )
        == []
    )
    quote = ok(client.post(f"{url}/cancellation-quote", headers=owner))
    assert quote["is_full_reversal"] is True and quote["proposed_credit_minor"] == 0  # cancelled on the day it began
    cancelled = ok(
        client.post(
            f"{url}/cancel", headers=owner, json={"reason": "downgrade", "remarks": "Moving to the off-peak plan"}
        )
    )
    assert (cancelled["status"], cancelled["cancel_reason"], cancelled["refunds"]) == ("cancelled", "downgrade", [])
    assert ok(client.post(f"{url}/undo-cancel", headers=owner))["status"] == "active"


# --- sharing, entitlement, visits --------------------------------------------------------------------------------


def test_shared_membership_covers_other_clients_and_billing_stays_with_the_owner(w, client, owner):
    kid, friend = new_client(client, owner, w.location_id), new_client(client, owner, w.location_id)
    sold = ok(
        client.post(f"{API}/membership-contracts", headers=owner, json=sale(w, share_client_ids=[kid["id"]])), 201
    )
    url = f"{API}/membership-contracts/{sold['id']}/shares"
    assert sold["covered_client_count"] == 2
    share = ok(client.post(url, headers=owner, json={"client_id": friend["id"]}), 201)  # unrelated clients too
    assert ok(client.post(url, headers=owner, json={"client_id": friend["id"]}), 201)["id"] == share["id"]  # idempotent
    assert client.post(url, headers=owner, json={"client_id": w.person["id"]}).status_code == 422  # the owner
    assert client.post(url, headers=owner, json={"client_id": str(uuid4())}).status_code == 422
    assert len(ok(client.get(url, headers=owner))) == 2

    ids = ",".join([w.person["id"], kid["id"], friend["id"]])
    stranger = new_client(client, owner, w.location_id)
    standings = ok(client.get(f"{API}/membership-standings", headers=owner,
                              params=[("client_ids", i) for i in (*ids.split(","), stranger["id"], str(uuid4()))]))  # fmt: skip
    assert [(s["is_member"], s.get("via")) for s in standings] == [
        (True, "owner"),
        (True, "share"),
        (True, "share"),
        (False, None),
    ]
    assert {s["contract_id"] for s in standings[:3]} == {sold["id"]} and charges(w.tenant, kid["id"]) == []

    assert client.delete(f"{url}/{share['id']}", headers=owner).status_code == 204
    assert client.delete(f"{url}/{share['id']}", headers=owner).status_code == 204
    assert client.delete(f"{url}/{uuid4()}", headers=owner).status_code == 404
    with tx(w.tenant) as session:
        assert (
            service.is_member(session, UUID(friend["id"])) is False
            and service.is_member(session, UUID(kid["id"])) is True
        )
    ok(client.post(f"{API}/membership-contracts/{sold['id']}/cancel", headers=owner, json={"reason": "voluntary"}))
    refused(client.post(url, headers=owner, json={"client_id": friend["id"]}), 409, "invalid-state-transition")
    with tx(w.tenant) as session:
        assert service.is_member(session, UUID(kid["id"])) is False  # a share ends with the contract


def test_visits_are_counted_once_per_check_in_with_cap_and_daily_rule(w, client, owner):
    kid = new_client(client, owner, w.location_id)
    sold = sell_at(w, JAN1, customize={"max_visits_count": 3}, share_client_ids=[UUID(kid["id"])])
    person, location_id, check_in = UUID(w.person["id"]), UUID(w.location_id), uuid4()

    def visit(day, client_id=person, check_in_id=None):
        with at(day), tx(w.tenant) as session:
            return service.record_visit(
                session, client_id=client_id, check_in_id=check_in_id or uuid4(), location_id=location_id
            )

    assert visit(D(2025, 1, 5), check_in_id=check_in) == {"contract_id": sold["id"], "is_counted": True}
    assert visit(D(2025, 1, 5), check_in_id=check_in) == {
        "contract_id": sold["id"],
        "is_counted": True,
    }  # the same check-in
    assert contract(w.tenant, sold["id"]).visits_used_count == 1
    run(w.tenant, D(2025, 1, 5), service.update_settings, {"is_daily_visit_limit_enabled": True})
    with tx(w.tenant) as session:
        assert service.eligibility(session, person, D(2025, 1, 5))["reason"] == "daily_limit_reached"
        assert service.eligibility(session, UUID(kid["id"]), D(2025, 1, 5))["reason"] is None  # per person
    assert visit(D(2025, 1, 5))["is_counted"] is False  # second entry the same local day: recorded, not counted
    assert visit(D(2025, 1, 5), client_id=UUID(kid["id"]))["is_counted"] is True  # the sharer draws on the same cap
    assert visit(D(2025, 1, 6))["is_counted"] is True
    used = contract(w.tenant, sold["id"])
    assert (used.visits_used_count, used.max_visits_count) == (3, 3)
    with tx(w.tenant) as session:
        state = service.eligibility(session, person, D(2025, 1, 7))
    assert (state["is_member"], state["reason"], state["visits_remaining_count"]) == (
        True,
        "depleted",
        0,
    )  # access decides
    assert visit(D(2025, 1, 7), client_id=uuid4()) == {"contract_id": None, "is_counted": False}  # not a member

    url = f"{API}/membership-contracts/{sold['id']}"
    listed = ok(client.get(f"{url}/visits", headers=owner))["data"]
    assert len(listed) == 4 and [v["is_counted"] for v in listed].count(False) == 1
    assert len(ok(client.get(f"{url}/visits?client_id={kid['id']}", headers=owner))["data"]) == 1
    adjusted = ok(
        client.post(f"{url}/visit-adjustments", headers=owner, json={"delta": -2, "reason": "Scanner double read"})
    )
    assert (adjusted["visits_used_count"], adjusted["visits_remaining_count"]) == (1, 2)
    assert client.post(f"{url}/visit-adjustments", headers=owner, json={"delta": -5, "reason": "x"}).status_code == 422
    with tx(w.tenant) as session:
        assert session.scalar(select(MembershipVisit.local_on).where(MembershipVisit.check_in_id == check_in)) == D(
            2025, 1, 5
        )


# --- portal: click-to-cancel (MEM-18) ----------------------------------------------------------------------------


def _member(tenant, person_id: str) -> Principal:
    with tx(tenant) as session:
        identity = platform.service.create_client_identity(session, f"m-{uuid4().hex[:8]}@example.com")
        clients.service.link_identity(session, UUID(person_id), identity.id)
        return Principal(kind="client", tenant_id=tenant.id, identity_id=identity.id, display_name="Member")


def test_member_switches_auto_renew_off_and_keeps_the_term(w, client, owner, mailbox):
    person = new_client(client, owner, w.location_id, primary_email=f"pat-{uuid4().hex[:6]}@example.com")
    w.person = person
    sold = sell_at(w, JAN1)
    assert daily(w.tenant, D(2025, 12, 1))["renewed"] == 1
    successor = _successor(w.tenant, sold["id"])
    with at(D(2025, 12, 2)), tx(w.tenant) as session:  # the renewal is invoiced and paid by card ahead of time
        january = service.invoice_deferred(session, SYSTEM, successor.id, [periods(w.tenant, successor.id)[0].id])
        billing.service.take_payment(session, client_id=UUID(person["id"]), location_id=UUID(w.location_id), amount_minor=3100,
                                     tender_kind="card", method_token="tok_card_ok", idempotency_key=f"k-{uuid4().hex}",
                                     invoice_id=january["invoice_id"])  # fmt: skip
    member, stranger = (
        _member(w.tenant, person["id"]),
        _member(w.tenant, new_client(client, owner, w.location_id)["id"]),
    )
    mailbox.clear()
    with at(D(2025, 12, 3)):
        for outsider in (stranger, SYSTEM):
            with pytest.raises(NotFound), tx(w.tenant) as session:
                service.portal_disable_auto_renew(session, outsider, sold["id"])
        with tx(w.tenant) as session:
            session.info["actor"] = member
            done = service.portal_disable_auto_renew(session, member, sold["id"])
            assert [c["id"] for c in service.portal_list_contracts(session, member, None)] == [successor.id, sold["id"]]
            assert service.portal_standing(session, member, None)["is_member"] is True
    assert (done["is_auto_renew"], done["auto_renew_disabled_by"], done["status"], done["end_on"]) == (
        False,
        "client",
        "active",
        D(2025, 12, 31),
    )
    gone = contract(w.tenant, successor.id)
    assert (gone.status, gone.previous_contract_id) == ("cancelled", None)  # the waiting renewal never starts
    with tx(w.tenant) as session:
        refunds = session.scalars(select(Refund).where(Refund.client_id == UUID(person["id"]))).all()
    assert [(r.amount_minor, r.method, r.status) for r in refunds] == [
        (3100, "original", "succeeded")
    ]  # back to the card
    assert len(mailbox) == 1 and "switched off" in mailbox[0].body and "2025-12-31" in mailbox[0].body
    assert daily(w.tenant, D(2025, 12, 4))["renewed"] == 0
    with at(D(2025, 12, 5)), tx(w.tenant) as session:  # one way from the portal: a repeat changes nothing
        session.info["actor"] = member
        assert service.portal_disable_auto_renew(session, member, sold["id"])["version"] == done["version"]
    assert len(mailbox) == 1


# --- merge and erasure -------------------------------------------------------------------------------------------


def test_merge_is_blocked_by_overlapping_memberships_and_otherwise_moves_everything(w, client, owner):
    twin = new_client(client, owner, w.location_id, first_name=w.person["first_name"], last_name=w.person["last_name"])
    kid = new_client(client, owner, w.location_id)
    mine = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    theirs = ok(client.post(f"{API}/membership-contracts", headers=owner,
                            json=sale(w, client_id=twin["id"], share_client_ids=[kid["id"], w.person["id"]])), 201)  # fmt: skip
    merge = {"merged_client_ids": [twin["id"]]}
    check = ok(client.post(f"{API}/clients/{w.person['id']}/merge-precheck", headers=owner, json=merge))
    assert [(b["context"], b["code"]) for b in check["blockers"]] == [("memberships", "membership-overlap")]
    assert client.post(f"{API}/clients/{w.person['id']}/merge", headers=owner, json=merge).status_code == 409

    ok(
        client.post(
            f"{API}/membership-contracts/{mine['id']}/cancel", headers=owner, json={"reason": "administrative_error"}
        )
    )
    ok(client.post(f"{API}/clients/{w.person['id']}/merge", headers=owner, json=merge))
    moved = contract(w.tenant, theirs["id"])
    assert moved.owner_client_id == UUID(w.person["id"])
    shares = ok(client.get(f"{API}/membership-contracts/{theirs['id']}/shares", headers=owner))
    live = [s["client_id"] for s in shares if s["revoked_at"] is None]
    assert live == [kid["id"]]  # the share with oneself ended
    with tx(w.tenant) as session:
        assert service.is_member(session, UUID(w.person["id"])) is True


def test_erasure_waits_for_a_live_membership_and_then_strips_free_text(w, client, owner):
    kid = new_client(client, owner, w.location_id)
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner,
                          json=sale(w, internal_notes="Recovering from knee surgery", share_client_ids=[kid["id"]])), 201)  # fmt: skip
    request = ok(
        client.post(
            f"{API}/data-subject-requests",
            headers=owner,
            json={"client_id": w.person["id"], "kind": "erasure", "reason": "Asked by email"},
        ),
        201,
    )
    assert request["status"] == "blocked" and any(b["code"] == "live-membership" for b in request["blockers"])
    ok(
        client.post(
            f"{API}/membership-contracts/{sold['id']}/cancel",
            headers=owner,
            json={"reason": "voluntary", "remarks": "Moved away"},
        )
    )
    shared = ok(client.post(f"{API}/membership-contracts", headers=owner,
                            json=sale(w, client_id=kid["id"], share_client_ids=[w.person["id"]])), 201)  # fmt: skip
    again = ok(client.post(f"{API}/data-subject-requests", headers=owner,
                           json={"client_id": w.person["id"], "kind": "erasure", "reason": "Asked by email"}), 201)  # fmt: skip
    assert not any(b.get("code") == "live-membership" for b in again.get("blockers") or [])
    body = {"confirmation": "ERASE", "is_blocker_override": True}
    done = ok(client.post(f"{API}/data-subject-requests/{again['id']}/confirm", headers=owner, json=body))
    assert done["handler_results"]["memberships"] == {"retained_contracts": 1, "revoked_shares": 1}
    kept = contract(w.tenant, sold["id"])
    assert (kept.internal_notes, kept.cancel_remarks, kept.term_fee_minor) == (None, None, 3100)  # the record stays
    assert [
        s["revoked_at"] is None
        for s in ok(client.get(f"{API}/membership-contracts/{shared['id']}/shares", headers=owner))
    ] == [False]


# --- online sales (MEM-09) ---------------------------------------------------------------------------------------


def test_online_purchase_needs_a_published_plan_and_a_payment_that_goes_through(w, client, owner):
    online = membership_plan(client, owner, w.tenant, is_sold_online=True, initiation_fee_minor=1000)
    member = _member(w.tenant, w.person["id"])
    stranger = new_client(client, owner, w.location_id)
    buy = {"membership_plan_id": UUID(online["id"]), "location_id": UUID(w.location_id)}

    def portal(fn, data, *args):
        with tx(w.tenant) as session:
            session.info["actor"] = member
            return fn(session, member, data, *args)

    quote = portal(service.portal_quote, buy)
    assert (quote["due_now_minor"], quote["total_minor"]) == (4100, 1000 + 12 * 3100)
    with pytest.raises(ValidationFailed):
        portal(service.portal_quote, buy | {"membership_plan_id": UUID(w.plan["id"])})  # not sold online
    with pytest.raises(NotFound):
        portal(service.portal_quote, buy | {"client_id": UUID(stranger["id"])})  # nobody they may buy for
    with pytest.raises(ValidationFailed):
        portal(service.portal_buy, buy, f"k-{uuid4().hex}")  # something is due: a payment method is needed
    with pytest.raises(Conflict) as declined:
        portal(service.portal_buy, buy | {"method_token": "tok_card_declined"}, f"k-{uuid4().hex}")
    assert declined.value.code == "payment-failed"
    assert (
        charges(w.tenant, w.person["id"]) == []
        and run(w.tenant, clock.now().date(), service.list_contracts, _all())["data"] == []
    )

    bought = portal(service.portal_buy, buy | {"method_token": "tok_card_ok"}, f"k-{uuid4().hex}")
    assert (bought["status"], bought["payment_status"], bought["sales_channel"], bought["sold_by_staff_user_id"]) == (
        "active", "succeeded", "portal", None)  # fmt: skip
    assert open_balance(w.tenant, w.person["id"]) == 0 and len(charges(w.tenant, w.person["id"])) == 2
    with pytest.raises(Conflict) as again:
        portal(service.portal_buy, buy | {"method_token": "tok_card_ok"}, f"k-{uuid4().hex}")
    assert again.value.code == "membership-overlap"

    slug = {"X-Tenant-Slug": w.tenant.slug}
    listed = ok(client.get(f"{API}/public/membership-plans", headers=slug))["data"]  # anonymous price list
    assert [(p["id"], p["term_fee_minor"]) for p in listed] == [
        (online["id"], 3100)
    ] and "is_autopay_default" not in listed[0]
    assert (
        client.post(
            f"{API}/portal/membership-contracts",
            headers=owner,
            json={"membership_plan_id": online["id"], "location_id": w.location_id},
        ).status_code
        == 422
    )  # no key
    assert (
        client.post(
            f"{API}/portal/membership-contracts/quote",
            headers=owner,
            json={"membership_plan_id": online["id"], "location_id": w.location_id},
        ).status_code
        == 404
    )  # staff token


def _all():
    from app.core.pagination import ListQuery

    return ListQuery()
