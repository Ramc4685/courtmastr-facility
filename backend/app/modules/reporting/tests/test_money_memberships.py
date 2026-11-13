"""Phase 12 chip B: money, membership and package reports through the API, each over two locations in different
zones (Main in Chicago, North in New York), with the own reach of the package pipeline (ADR 0010 section 6)."""
# ruff: noqa: F811  (pytest fixtures imported from test_reporting are redefined as parameters)

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from app.core import clock
from app.core.db.session import tenant_session
from app.modules.billing.models import Invoice
from app.modules.memberships.tests.support import membership_plan, package_plan
from app.modules.packages.tests.test_packages import reserve, settle
from app.modules.platform.models import StaffUser
from app.modules.reporting.reports import money
from app.modules.reporting.tests.test_reporting import (  # noqa: F401  (same_day_everywhere is an autouse fixture)
    API,
    _location,
    _pay,
    _sale,
    code,
    ok,
    ran,
    rows,
    run,
    same_day_everywhere,
    world,
)
from conftest import add_staff, login, new_client


def today() -> date:
    return clock.now().date()  # noon in Chicago (same_day_everywhere): one date in both zones


def day(n: int) -> str:
    return str(today() + timedelta(days=n))


# --- receivables (RPT-06, BIL-19) ----------------------------------------------------------------------------


def test_receivables_by_due_date_count_instalments_as_they_fall_due(client, tenant, owner, world):
    main_person = new_client(client, owner, world.main)["id"]
    north_person = new_client(client, owner, world.north)["id"]
    charge, invoice = _sale(client, owner, main_person, world.main, world.category, 3000, pay=False)  # 3300 taxed
    instalments = [{"due_on": day(n), "amount_minor": 1100} for n in (10, 40, 70)]
    ok(client.put(f"{API}/invoices/{invoice['id']}/payment-schedule", headers=owner, json={"instalments": instalments}))
    _pay(client, owner, main_person, world.main, invoice["id"], 1000)
    _, north_invoice = _sale(client, owner, north_person, world.north, world.category, 1000, pay=False)  # 1100
    ok(client.put(f"{API}/invoices/{north_invoice['id']}/payment-schedule", headers=owner,
                  json={"instalments": [{"due_on": day(20), "amount_minor": 1100}]}))  # fmt: skip

    nothing_due = ran(client, owner, "receivables", as_of_on=day(5))
    assert nothing_due["row_count"] == 0 and nothing_due["params"]["basis"] == "due"

    main = ran(client, owner, "receivables", as_of_on=day(50), location_ids=[world.main])
    (row,) = rows(client, owner, main["id"])["data"]
    # two instalments due (2200) less 1000 paid; the first is not covered, so 40 days late
    assert (row["balance_minor"], row["days_past_due"], row["days_31_60_minor"]) == (1200, 40, 1200)
    (detail,) = rows(client, owner, main["id"], group_key=row["group_key"])["data"]
    assert (detail["number"], detail["due_on"], detail["total_minor"]) == (invoice["number"], day(10), 3300)

    north = ran(client, owner, "receivables", as_of_on=day(50), location_ids=[world.north])
    assert north["totals"]["balance_minor"] == 1100 and north["totals"]["days_1_30_minor"] == 1100
    both = ran(client, owner, "receivables", as_of_on=day(50))
    assert both["totals"]["balance_minor"] == 2300 and both["row_count"] == 2

    by_invoice = ran(client, owner, "receivables", basis="invoice", as_of_on=day(0), location_ids=[world.main])
    assert by_invoice["totals"]["balance_minor"] == charge["total_minor"] - 1000  # the whole invoice counts

    tag = ok(client.post(f"{API}/collections-tags", headers=owner, json={"name": "Agency"}), 201)
    ok(client.put(f"{API}/clients/{north_person}/collections-profile", headers=owner,
                  json={"collections_tag_id": tag["id"]}))  # fmt: skip
    flagged = rows(client, owner, ran(client, owner, "receivables", as_of_on=day(50))["id"])["data"]
    assert sorted(r["in_collections"] for r in flagged) == [False, True]
    assert ran(client, owner, "receivables", as_of_on=day(50), include_collections=False)["row_count"] == 1
    assert ran(client, owner, "receivables", as_of_on=day(50), invoices="auto_pay_only")["row_count"] == 0
    response, _ = run(client, owner, "receivables", as_of_on=day(0), earliest_on=day(1))
    assert response.status_code == 422 and response.json()["errors"][0]["pointer"] == "/params/earliest_on"


def test_receivables_leave_paid_invoices_to_sql_so_the_row_cap_counts_only_open_ones(client, owner, world, monkeypatch):
    third = _location(client, owner, "Third")
    person = new_client(client, owner, third)["id"]
    for _ in range(2):
        _sale(client, owner, person, third, world.category, 1000)  # paid in full
    _, open_invoice = _sale(client, owner, person, third, world.category, 1000, pay=False)
    ok(client.put(f"{API}/invoices/{open_invoice['id']}/payment-schedule", headers=owner,
                  json={"instalments": [{"due_on": day(0), "amount_minor": 1100}]}))  # fmt: skip
    monkeypatch.setattr(money, "MAX_ROWS", 1)  # stands in for 50,000 paid invoices
    for basis in ("due", "invoice"):
        assert ran(client, owner, "receivables", basis=basis, location_ids=[third])["totals"]["balance_minor"] == 1100


# --- unapplied payments (RPT-07), income and balances (RPT-08), underpaid items (RPT-09) -----------------------


def test_unapplied_payments_weigh_money_on_account_against_unpaid_invoices(client, tenant, owner, world):
    holder = new_client(client, owner, world.north)["id"]
    body = {"client_id": holder, "location_id": world.north, "amount_minor": 5000, "tender_kind": "card",
            "method_token": "tok_card_ok"}  # fmt: skip
    ok(client.post(f"{API}/payments", headers=owner | {"Idempotency-Key": uuid4().hex}, json=body), 201)
    _sale(client, owner, holder, world.north, world.category, 1000, pay=False)  # 1100 still owed at North

    north = ran(client, owner, "unapplied_payments", location_ids=[world.north])
    (row,) = rows(client, owner, north["id"])["data"]
    assert (row["unapplied_minor"], row["unpaid_minor"], row["liability_minor"]) == (5000, 1100, 3900)
    assert ran(client, owner, "unapplied_payments", location_ids=[world.main])["row_count"] == 0


def test_income_balances_and_underpaid_items_follow_their_location(client, tenant, owner, world):
    _sale(client, owner, world.person, world.main, world.category, 500, pay=False)  # 550 owed at Main
    item = {"client_id": world.person, "location_id": world.north, "description": "Lesson", "unit_price_minor": 300,
            "revenue_category_id": world.category}  # fmt: skip
    ok(client.post(f"{API}/charges", headers=owner, json=item), 201)  # 330 at North, on no invoice

    main = ran(client, owner, "income_balances", from_on=day(0), to_on=day(0), location_ids=[world.main])
    assert main["totals"] == {"invoice_count": 2, "total_minor": 2750, "paid_minor": 2200, "balance_minor": 550}
    north = ran(client, owner, "income_balances", from_on=day(0), to_on=day(0), location_ids=[world.north])
    assert (north["totals"]["total_minor"], north["totals"]["balance_minor"]) == (7700, 0)

    under_main = ran(client, owner, "underpaid_items", location_ids=[world.main])
    assert (under_main["totals"]["item_count"], under_main["totals"]["balance_minor"]) == (1, 550)
    under_north = ran(client, owner, "underpaid_items", location_ids=[world.north])
    assert under_north["totals"]["balance_minor"] == 330
    assert ran(client, owner, "underpaid_items", location_ids=[world.north], include_uninvoiced=False)["row_count"] == 0
    assert ran(client, owner, "underpaid_items", as_of_on=day(-1))["row_count"] == 0  # nothing earned before today


# --- packages (RPT-10, RPT-22, RPT-23, PKG-15) ---------------------------------------------------------------


def _sell(client, owner, plan, person, location_id) -> dict:
    body = {"client_id": person, "location_id": location_id, "package_plan_id": plan["id"]}
    return ok(client.post(f"{API}/client-packages", headers=owner, json=body), 201)


def _use(tenant, package, person, count):
    for _ in range(count):
        booking = uuid4()
        reserve(tenant, UUID(package["id"]), person, booking)
        settle(tenant, booking, "attended")


@pytest.fixture
def packs(client, tenant, owner, world):
    ten = package_plan(client, owner, tenant)  # ten sessions at 100.00, no expiry
    short = package_plan(client, owner, tenant, session_count=3, validity_count=1, validity_unit="month")
    north_person = new_client(client, owner, world.north)["id"]
    main = _sell(client, owner, ten, world.person, world.main)
    north = _sell(client, owner, short, north_person, world.north)
    _use(tenant, main, world.person, 2)
    _use(tenant, north, north_person, 1)
    return SimpleNamespace(main=main, north=north, north_person=north_person)


def test_accrued_and_unused_session_value_split_by_location(client, tenant, owner, world, packs):
    accrued = ran(client, owner, "accrued_session_revenue", from_on=day(0), to_on=day(0), location_ids=[world.main])
    assert accrued["totals"] == {"sessions": 2, "value_minor": 2000}  # 10000 / 10 a session
    (row,) = rows(client, owner, accrued["id"])["data"]
    assert len(rows(client, owner, accrued["id"], group_key=row["group_key"])["data"]) == 2
    north = ran(client, owner, "accrued_session_revenue", from_on=day(0), to_on=day(0), location_ids=[world.north])
    assert north["totals"]["sessions"] == 1
    assert ran(client, owner, "accrued_session_revenue", from_on=day(-3), to_on=day(-1))["row_count"] == 0

    unused = ran(client, owner, "unused_session_value", location_ids=[world.main])
    assert unused["totals"] == {"package_count": 1, "unused": 8, "value_minor": 8000}
    assert ran(client, owner, "unused_session_value", as_of_on=day(-1))["row_count"] == 0  # granted today
    later = ran(client, owner, "unused_session_value", as_of_on=day(60), location_ids=[world.north])
    assert later["row_count"] == 0  # the one-month pack has expired by then


def test_package_pipeline_and_sales(client, tenant, owner, world, packs):
    summary = ran(client, owner, "package_summary", location_ids=[world.main])
    (row,) = rows(client, owner, summary["id"])["data"]
    assert (row["sessions_granted_count"], row["sessions_consumed_count"], row["sessions_remaining"]) == (10, 2, 8)

    expiring = ran(client, owner, "expiring_packages", from_on=day(0), to_on=day(45))
    assert [r["sessions_remaining"] for r in rows(client, owner, expiring["id"])["data"]] == [2]  # the North pack
    assert ran(client, owner, "expiring_packages", from_on=day(0), to_on=day(45),
               location_ids=[world.main])["row_count"] == 0  # fmt: skip

    candidates = ran(client, owner, "renewal_candidates")
    assert [r["sessions_remaining"] for r in rows(client, owner, candidates["id"])["data"]] == [2]
    assert ran(client, owner, "renewal_candidates", min_remaining=3, max_remaining=10)["totals"]["package_count"] == 1
    assert run(client, owner, "renewal_candidates", min_remaining=3, max_remaining=2)[0].status_code == 422

    sales = ran(client, owner, "package_sales", from_on=day(0), to_on=day(0), location_ids=[world.main])
    assert sales["totals"] == {"package_count": 1, "sessions": 10, "cost_minor": 10000, "paid_minor": 0,
                               "balance_minor": 10000}  # fmt: skip


def test_trainers_see_the_packages_of_their_own_clients_only(client, tenant, owner, world, packs):
    group = ok(
        client.post(f"{API}/resource-groups", headers=owner, json={"location_id": world.main, "name": "Staff"}), 201
    )
    email, staff_id = add_staff(tenant, "coach", all_locations=True)
    trainer = ok(client.post(f"{API}/resources", headers=owner, json={
        "location_id": world.main, "resource_group_id": group["id"], "kind": "trainer", "name": "Coach Tester",
        "staff_user_id": str(staff_id)}), 201)  # fmt: skip
    with tenant_session(tenant.id) as session:
        session.execute(update(StaffUser).where(StaffUser.id == staff_id).values(linked_resource_id=trainer["id"]))
    coach = login(client, tenant, email)
    assert ran(client, coach, "package_summary")["row_count"] == 0  # nobody names them yet
    ok(client.put(f"{API}/clients/{world.person}/owners", headers=owner,
                    json={"default_trainer_staff_user_id": str(staff_id)}))  # fmt: skip
    mine = ran(client, coach, "package_summary")
    assert mine["row_count"] == 1 and rows(client, coach, mine["id"])["data"][0]["sessions_remaining"] == 8
    assert ran(client, coach, "renewal_candidates")["row_count"] == 0  # the North client is not theirs
    assert code(run(client, coach, "receivables")[0], 403) == "permission-denied"


def test_renewal_candidates_take_the_last_session_of_the_same_service(client, tenant, owner, world):
    pt = package_plan(client, owner, tenant, session_count=2)  # the tenant's first reservation type
    other_type = ok(client.post(f"{API}/reservation-types", headers=owner,
                                json={"location_id": world.main, "name": "Pilates"}), 201)["id"]  # fmt: skip
    pilates = package_plan(client, owner, tenant, session_count=3, reservation_type_id=other_type)
    person = new_client(client, owner, world.main)["id"]
    _sell(client, owner, pt, person, world.main)  # 2 left, never booked
    _use(tenant, _sell(client, owner, pilates, person, world.main), person, 1)  # 2 left, booked today
    active = ran(client, owner, "renewal_candidates", last_session_before_on=day(0), location_ids=[world.main])
    # a Pilates session today does not make the untouched PT pack look active
    assert [r["reservation_type_name"] for r in rows(client, owner, active["id"])["data"]] == ["Pilates"]


def test_renewal_candidates_count_clients_not_names(client, tenant, owner, world):
    plan = package_plan(client, owner, tenant, session_count=2)
    for _ in range(2):
        twin = new_client(client, owner, world.main, first_name="Sam", last_name="Same")["id"]
        _sell(client, owner, plan, twin, world.main)
    candidates = ran(client, owner, "renewal_candidates", location_ids=[world.main])
    assert candidates["totals"] == {"client_count": 2, "package_count": 2}


# --- memberships (RPT-11, MEM-21, RPT-13 to RPT-16) ----------------------------------------------------------


@pytest.fixture
def members(client, tenant, owner, world):
    plan = membership_plan(client, owner, tenant)  # 12 x 31.00 a month
    north_person = new_client(client, owner, world.north)["id"]

    def sell(person, location_id, **extra):
        body = {"client_id": person, "location_id": location_id, "membership_plan_id": plan["id"]} | extra
        return ok(client.post(f"{API}/membership-contracts", headers=owner, json=body), 201)

    main = sell(world.person, world.main)
    north = sell(north_person, world.north, referred_by_client_id=world.person)
    return SimpleNamespace(main=main, north=north, north_person=north_person)


def test_membership_revenue_by_month_and_deferred_revenue(client, tenant, owner, world, members):
    year = {"from_on": day(0), "to_on": day(364)}
    main = ran(client, owner, "membership_revenue_by_month", **year, location_ids=[world.main])
    assert main["totals"]["total_minor"] == 12 * 3100
    assert main["totals"]["posted_minor"] >= 3100  # the first period is billed at the sale
    first = rows(client, owner, main["id"])["data"][0]
    assert rows(client, owner, main["id"], group_key=first["group_key"])["data"]
    assert ran(client, owner, "membership_revenue_by_month", **year)["totals"]["total_minor"] == 2 * 12 * 3100

    with tenant_session(tenant.id) as session:
        invoice = session.scalars(select(Invoice).where(Invoice.bill_to_client_id == world.person,
                                                        Invoice.total_minor == 3100)).first()  # fmt: skip
    _pay(client, owner, world.person, world.main, str(invoice.id), 3100)
    deferred = ran(client, owner, "deferred_membership_revenue", location_ids=[world.main])
    (row,) = rows(client, owner, deferred["id"])["data"]
    assert (row["billed_minor"], row["paid_minor"], row["recognized_minor"], row["remaining_minor"]) == (
        3100, 3100, 3100, 0)  # fmt: skip
    assert ran(client, owner, "deferred_membership_revenue", liable_only=True,
               location_ids=[world.main])["row_count"] == 0  # fmt: skip
    north = ran(client, owner, "deferred_membership_revenue", location_ids=[world.north])
    assert north["totals"]["paid_minor"] == 0 and north["row_count"] == 1


def test_membership_actions_attrition_expiry_and_referrals(client, tenant, owner, world, members):
    ok(client.post(f"{API}/membership-contracts/{members.main['id']}/cancel",
                   headers=owner | {"Idempotency-Key": uuid4().hex}, json={"reason": "voluntary"}))  # fmt: skip
    ok(client.post(f"{API}/membership-contracts/{members.north['id']}/freezes", headers=owner,
                   json={"start_on": day(40), "end_on": day(50)}), 201)  # fmt: skip

    window = {"from_on": day(0), "to_on": day(60)}
    main = ran(client, owner, "membership_actions", **window, location_ids=[world.main])
    assert [(r["action"], r["action_count"]) for r in rows(client, owner, main["id"])["data"]] == [("cancelled", 1)]
    north = ran(client, owner, "membership_actions", **window, location_ids=[world.north])
    assert [r["action"] for r in rows(client, owner, north["id"])["data"]] == ["frozen"]
    started = ran(client, owner, "membership_actions", from_on=day(40), to_on=day(50), date_by="start")
    assert started["totals"]["action_count"] == 1
    assert ran(client, owner, "membership_actions", **window, actions=["suspended"])["row_count"] == 0

    lost = ran(client, owner, "membership_attrition", months=1, location_ids=[world.main])
    assert lost["totals"]["lost"] == 1 and lost["params"]["as_of_on"] == day(0)
    assert ran(client, owner, "membership_attrition", months=1, location_ids=[world.north])["totals"]["lost"] == 0

    year_end = {"from_on": day(300), "to_on": day(400)}
    expiring = ran(client, owner, "expiring_memberships", **year_end)
    assert expiring["row_count"] == 1  # the cancelled Main contract is no renewal prospect
    assert ran(client, owner, "expiring_memberships", **year_end, location_ids=[world.main])["row_count"] == 0

    referrals = ran(client, owner, "membership_referrals", from_on=day(0), to_on=day(0))
    (row,) = rows(client, owner, referrals["id"])["data"]
    assert (row["contract_count"], row["value_minor"]) == (1, 12 * 3100)
    assert ran(client, owner, "membership_referrals", from_on=day(0), to_on=day(0),
               location_ids=[world.main])["row_count"] == 0  # fmt: skip


def test_attrition_counts_a_contract_starting_on_the_first_as_active_that_month(client, owner, world, members):
    first = (today().replace(day=1) + timedelta(days=32)).replace(day=1)
    person = new_client(client, owner, world.north)["id"]
    plan = members.north["membership_plan_id"]
    body = {"client_id": person, "location_id": world.north, "membership_plan_id": plan, "start_on": str(first)}
    ok(client.post(f"{API}/membership-contracts", headers=owner, json=body), 201)
    attrition = ran(client, owner, "membership_attrition", months=1, as_of_on=str(first), location_ids=[world.north])
    assert attrition["totals"]["at_start"] == 2  # today's contract and the one starting on the first


def test_membership_revenue_is_before_tax_for_billed_and_scheduled_periods(client, tenant, owner, world):
    vat = ok(client.post(f"{API}/taxes", headers=owner, json={"code": f"V{uuid4().hex[:5]}", "label": "VAT",
                                                              "rate": "0.2", "effective_from_on": "2020-01-01"}), 201)  # fmt: skip
    taxed = ok(client.post(f"{API}/revenue-categories", headers=owner,
                           json={"code": f"T{uuid4().hex[:5]}", "label": "Taxed", "tax_ids": [vat["id"]]}), 201)  # fmt: skip
    kind = ok(client.post(f"{API}/membership-types", headers=owner,
                          json={"name": f"Taxed {uuid4().hex[:6]}", "revenue_category_id": taxed["id"]}), 201)  # fmt: skip
    plan = ok(client.post(f"{API}/membership-plans", headers=owner, json={
        "membership_type_id": kind["id"], "name": "Taxed plan", "billing_occurrences_count": 12, "term_fee_minor": 3100,
    }), 201)  # fmt: skip
    person = new_client(client, owner, world.north)["id"]
    body = {"client_id": person, "location_id": world.north, "membership_plan_id": plan["id"]}
    ok(client.post(f"{API}/membership-contracts", headers=owner, json=body), 201)
    year = ran(client, owner, "membership_revenue_by_month", from_on=day(0), to_on=day(364), location_ids=[world.north])
    # the billed first month (charge net) and the eleven scheduled ones are on the same pre-tax basis
    assert year["totals"]["total_minor"] == 12 * 3100 and year["totals"]["posted_minor"] == 3100
    deferred = ran(client, owner, "deferred_membership_revenue", location_ids=[world.north])
    assert deferred["totals"]["billed_minor"] == 3720  # the charge itself was taxed: 3100 + 20 %


def test_expiring_memberships_judge_superseded_only_within_the_callers_locations(client, owner, world, members):
    body = {"client_id": world.person, "location_id": world.north, "membership_plan_id": members.main["membership_plan_id"],
            "start_on": day(401)}  # fmt: skip
    ok(client.post(f"{API}/membership-contracts", headers=owner, json=body), 201)  # the renewal, at North
    year_end = {"from_on": day(300), "to_on": day(400)}
    main = ran(client, owner, "expiring_memberships", **year_end, location_ids=[world.main])
    assert main["row_count"] == 1  # a North contract the caller cannot see neither hides nor reveals anything
    everywhere = ran(client, owner, "expiring_memberships", **year_end)
    assert everywhere["row_count"] == 1  # Main is superseded; North's referral contract still expires


def test_unused_session_value_rounds_once_so_an_untouched_pack_is_worth_its_price(client, tenant, owner, world):
    third = _location(client, owner, "Third")
    three = package_plan(client, owner, tenant, session_count=3)  # 100.00 over three sessions: 33.333... each
    _sell(client, owner, three, new_client(client, owner, third)["id"], third)
    unused = ran(client, owner, "unused_session_value", location_ids=[third])
    assert unused["totals"]["value_minor"] == 10000  # not 3 x 3333
