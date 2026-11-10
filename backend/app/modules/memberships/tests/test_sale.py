"""Catalogue, the sale and its guards over HTTP (MEM-01 to MEM-08, MEM-10): plans, snapshots, proration at
sale, customised terms, the one-live-contract rule, document gating, permissions and audit."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.modules.documents.tests.support import sign, template
from app.modules.memberships import service
from app.modules.memberships.tests.support import (
    API,
    at,
    charges,
    contract,
    deliver_events,
    event_types,
    invoices,
    ok,
    periods,
    refused,
    sale,
    tx,
    world,
)
from conftest import add_staff, login, new_client, scalar

TODAY = clock.now().date() - timedelta(days=1)  # safely "today or earlier" in every test zone


def test_catalogue_types_plans_duplicate_and_settings(client, tenant, owner):
    w = world(client, owner, tenant, auto_renew_lead_count=30, auto_renew_lead_unit="day", initiation_fee_minor=5000)
    types = ok(client.get(f"{API}/membership-types", headers=owner))["data"]
    assert [t["id"] for t in types] == [w.plan["membership_type_id"]]
    again = client.post(f"{API}/membership-types", headers=owner,
                        json={"name": types[0]["name"].upper(), "revenue_category_id": types[0]["revenue_category_id"]})  # fmt: skip
    refused(again, 409, "already-exists")  # names are unique whatever the case
    ok(client.patch(f"{API}/membership-types/{types[0]['id']}", headers=owner, json={"sort_order": 3}))

    plan_url = f"{API}/membership-plans/{w.plan['id']}"
    assert ok(client.get(plan_url, headers=owner))["addons"] == []
    changed = ok(client.patch(plan_url, headers=owner, json={"term_fee_minor": 3500, "payment_due_day": 5}))
    assert (changed["term_fee_minor"], changed["version"]) == (3500, 2)
    copy = ok(client.post(f"{plan_url}/duplicate", headers=owner), 201)
    assert copy["name"].endswith("(copy)") and copy["term_fee_minor"] == 3500 and copy["id"] != w.plan["id"]
    assert len(ok(client.get(f"{API}/membership-plans?q=Plan", headers=owner))["data"]) == 2

    # rules the checks cannot state, and the ones they can
    weekly = {"billing_interval_unit": "week", "proration_mode": "to_month_start", "proration_tail": "drop_last"}
    assert client.patch(plan_url, headers=owner, json=weekly).status_code == 422
    assert client.patch(plan_url, headers=owner, json={"proration_mode": "to_month_start"}).status_code == 422
    assert (
        client.patch(
            plan_url, headers=owner, json={"renews_as_plan_id": str(uuid4()), "renewal_target": "plan"}
        ).status_code
        == 422
    )
    assert client.patch(plan_url, headers=owner, json={"discount_pct": "10", "discount_minor": 5}).status_code == 422

    settings = ok(client.get(f"{API}/membership-settings", headers=owner))
    assert settings["billing_lead_days"] == 0 and settings["is_remark_required_on_cancel"] is False
    assert (
        ok(client.patch(f"{API}/membership-settings", headers=owner, json={"billing_lead_days": 7}))[
            "billing_lead_days"
        ]
        == 7
    )
    assert client.patch(f"{API}/membership-settings", headers=owner, json={"billing_lead_days": 61}).status_code == 422


def test_sale_snapshots_the_plan_builds_the_schedule_and_bills_what_is_due(client, tenant, owner):
    w = world(client, owner, tenant, initiation_fee_minor=5000, auto_renew_lead_count=30, auto_renew_lead_unit="day",
              max_visits_count=20)  # fmt: skip
    quote = ok(client.post(f"{API}/membership-contracts/quote", headers=owner, json=sale(w)))
    assert (quote["total_minor"], quote["due_now_minor"], len(quote["periods"])) == (5000 + 12 * 3100, 8100, 13)
    assert scalar(tenant, select(func.count()).select_from(service.MembershipContract)) == 0  # a quote writes nothing

    body = sale(w, payment={"amount_minor": 8100, "tender_kind": "cash"}, internal_notes="Paid at the desk")
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=body), 201)
    assert (sold["status"], sold["effective_status"], sold["invoice_mode"]) == ("active", "active", "per_period")
    assert sold["payment_status"] == "succeeded" and sold["invoice_id"] and sold["is_auto_renew"] is True
    assert sold["end_on"] == quote["end_on"] and sold["renew_on"] == quote["renew_on"]
    assert (sold["visits_remaining_count"], sold["covered_client_count"]) == (20, 1)
    assert sold["sold_by_staff_user_id"] == str(tenant.owner_id)

    rows = periods(tenant, sold["id"])
    assert len(rows) == 13 and [r.status for r in rows].count("billed") == 2  # enrolment fee and the first month
    assert {r.kind for r in rows if r.status == "billed"} == {"initiation", "dues"}
    assert all(r.revenue_on == (r.service_during.lower if r.service_during else r.due_on) for r in rows)
    billed = charges(tenant, w.person["id"])
    assert sorted(c.total_minor for c in billed) == [3100, 5000]
    assert {(c.source_context, c.source_type) for c in billed} == {("memberships", "billing_schedule_period")}
    (invoice,) = invoices(tenant, w.person["id"])
    assert (invoice.status, invoice.total_minor, invoice.balance_minor) == ("paid", 8100, 0)
    assert event_types(tenant, sold["id"]) == ["memberships.contract.activated"]

    # the contract is a snapshot: a later plan edit changes nothing already sold
    ok(
        client.patch(
            f"{API}/membership-plans/{w.plan['id']}", headers=owner, json={"term_fee_minor": 9900, "name": "New"}
        )
    )
    again = ok(client.get(f"{API}/membership-contracts/{sold['id']}", headers=owner))
    assert (again["term_fee_minor"], again["name"]) == (3100, w.plan["name"])
    schedule = ok(client.get(f"{API}/membership-contracts/{sold['id']}/billing-schedule", headers=owner))
    assert {p["amount_minor"] for p in schedule if p["kind"] == "dues"} == {3100}
    dues = [p for p in schedule if p["kind"] == "dues"]
    assert dues[0]["start_on"] == sold["start_on"] and dues[-1]["end_on"] == sold["end_on"]

    listed = ok(client.get(f"{API}/membership-contracts?client_id={w.person['id']}&status=active", headers=owner))[
        "data"
    ]
    assert [c["id"] for c in listed] == [sold["id"]]
    history = ok(client.get(f"{API}/membership-contracts/{sold['id']}/history", headers=owner))
    assert {h["action"] for h in history} == {"memberships.contract.sell", "memberships.contract.transition"}
    sell = next(h for h in history if h["action"] == "memberships.contract.sell")
    assert sell["changes"]["term_fee_minor"] == [None, 3100] and "internal_notes" not in sell["changes"]
    assert scalar(tenant, select(func.count()).select_from(AuditEvent).where(
        AuditEvent.action == "memberships.contract.sell")) == 1  # fmt: skip


def test_a_failed_sale_leaves_nothing_behind(client, tenant, owner):
    w = world(client, owner, tenant)
    bad = sale(w, payment={"amount_minor": 3100, "tender_kind": "card", "method_token": "tok_card_ok"})
    assert client.post(f"{API}/membership-contracts", headers=owner, json=bad).status_code == 422  # card needs a key
    assert (
        client.post(
            f"{API}/membership-contracts", headers=owner, json=sale(w, share_client_ids=[w.person["id"]])
        ).status_code
        == 422
    )
    assert scalar(tenant, select(func.count()).select_from(service.MembershipContract)) == 0
    assert (
        scalar(
            tenant, select(func.count()).select_from(AuditEvent).where(AuditEvent.action.like("memberships.contract.%"))
        )
        == 0
    )
    assert charges(tenant, w.person["id"]) == []


def test_card_sale_is_replay_safe(client, tenant, owner):
    w = world(client, owner, tenant)
    body = sale(w, payment={"amount_minor": 3100, "tender_kind": "card", "method_token": "tok_card_ok"})
    key = {"Idempotency-Key": f"sale-{uuid4().hex}"}
    first = ok(client.post(f"{API}/membership-contracts", headers=owner | key, json=body), 201)
    replay = client.post(f"{API}/membership-contracts", headers=owner | key, json=body)
    assert (
        replay.status_code == 201
        and replay.headers["Idempotent-Replayed"] == "true"
        and replay.json()["id"] == first["id"]
    )
    assert len(charges(tenant, w.person["id"])) == 1 and len(invoices(tenant, w.person["id"])) == 1
    declined = sale(w, payment={"amount_minor": 3100, "tender_kind": "card", "method_token": "tok_card_declined"})
    other = new_client(client, owner, w.location_id)
    lost = ok(client.post(f"{API}/membership-contracts", headers=owner | {"Idempotency-Key": f"sale-{uuid4().hex}"},
                          json=declined | {"client_id": other["id"]}), 201)  # fmt: skip
    assert lost["payment_status"] == "failed" and lost["status"] == "active"  # the sale stands; the invoice is open
    assert invoices(tenant, other["id"])[0].status == "open"


def test_one_live_contract_per_owner_and_a_future_one_may_queue(client, tenant, owner, monkeypatch):
    w = world(client, owner, tenant)
    first = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    clash = refused(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 409, "membership-overlap")
    assert clash["contract_id"] == first["id"]
    after = (date.fromisoformat(first["end_on"]) + timedelta(days=1)).isoformat()
    queued = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w, start_on=after)), 201)
    assert (queued["status"], queued["invoice_id"]) == ("upcoming", None)
    assert event_types(tenant, queued["id"]) == []  # not active yet: nothing announced
    # Two sales racing past the readable check are stopped by the exclusion constraint itself, at commit.
    monkeypatch.setattr(service, "_check_overlap", lambda session, row: None)
    refused(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 409, "membership-overlap")
    assert scalar(tenant, select(func.count()).select_from(service.MembershipContract)) == 2


def test_proration_follows_the_plan_or_the_seller(client, tenant, owner):
    w = world(client, owner, tenant, proration_mode="to_month_start", proration_tail="prorate_last")
    with at(date(2025, 1, 15)), tx(tenant) as session:
        sold = service.sell_contract(session, session.info["actor"], sale(w))
    rows = [p for p in periods(tenant, sold["id"]) if p.kind == "dues"]
    assert (sold["start_on"], sold["end_on"], sold["is_prorated"], sold["proration_tail"]) == (
        date(2025, 1, 15), date(2026, 1, 14), True, "prorate_last")  # fmt: skip
    assert [r.amount_minor for r in rows] == [1700, *[3100] * 11, 1400] and rows[0].is_prorated and rows[-1].is_prorated
    assert rows[0].description.endswith("2025-01-15 to 2025-01-31") and rows[0].status == "billed"

    choice = world(client, owner, tenant, proration_mode="seller_choice")
    with at(date(2025, 1, 15)), tx(tenant) as session:
        actor = session.info["actor"]
        plain = service.quote_contract(session, actor, sale(choice))
        dropped = service.quote_contract(session, actor, sale(choice, proration_tail="drop_last"))
        fixed = service.quote_contract(
            session, actor, sale(choice, start_on=date(2025, 2, 1), proration_tail="drop_last")
        )
    assert (plain["is_prorated"], plain["end_on"], plain["total_minor"]) == (False, date(2026, 1, 14), 12 * 3100)
    assert (dropped["is_prorated"], dropped["end_on"], dropped["total_minor"]) == (
        True,
        date(2025, 12, 31),
        1700 + 11 * 3100,
    )
    assert (fixed["is_prorated"], fixed["end_on"]) == (False, date(2026, 1, 31))  # the 1st needs no proration


def test_customised_terms_need_their_own_permission(client, tenant, owner):
    w = world(client, owner, tenant)
    desk_email, _ = add_staff(tenant, "front_desk", location_ids=[w.location_id])
    desk = login(client, tenant, desk_email)
    custom = sale(w, customize={"term_fee_minor": 2000, "discount_pct": "50", "max_visits_count": 8})
    denied = refused(client.post(f"{API}/membership-contracts", headers=desk, json=custom), 403, "permission-denied")
    assert denied["required"] == "memberships.contract.customize_terms"
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=custom), 201)
    assert (sold["term_fee_minor"], float(sold["discount_pct"]), sold["max_visits_count"]) == (2000, 50.0, 8)
    assert {p.amount_minor for p in periods(tenant, sold["id"])} == {1000}
    assert (
        ok(client.get(f"{API}/membership-plans/{w.plan['id']}", headers=owner))["term_fee_minor"] == 3100
    )  # plan untouched

    other = new_client(client, owner, w.location_id)
    start = date.fromisoformat(sold["start_on"])
    ended = sale(w, client_id=other["id"], customize={"end_on": (start + timedelta(days=9)).isoformat()})
    short = ok(client.post(f"{API}/membership-contracts", headers=desk | {}, json=sale(w, client_id=other["id"])), 201)
    assert short["sold_by_staff_user_id"] != str(tenant.owner_id)  # front desk sells the plan as it is
    third = new_client(client, owner, w.location_id)
    ten_days = ok(
        client.post(f"{API}/membership-contracts", headers=owner, json=ended | {"client_id": third["id"]}), 201
    )
    assert (
        ten_days["billing_interval_unit"],
        ten_days["billing_interval_count"],
        ten_days["billing_occurrences_count"],
    ) == ("day", 10, 1)
    assert len(periods(tenant, ten_days["id"])) == 1
    backwards = sale(w, client_id=new_client(client, owner, w.location_id)["id"],
                     customize={"end_on": (start - timedelta(days=1)).isoformat()})  # fmt: skip
    assert client.post(f"{API}/membership-contracts", headers=owner, json=backwards).status_code == 422


def test_record_only_membership_has_no_schedule_and_still_makes_a_member(client, tenant, owner):
    w = world(client, owner, tenant, term_fee_minor=0)
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    assert (sold["invoice_mode"], sold["status"], sold["invoice_id"]) == ("none", "active", None)
    assert periods(tenant, sold["id"]) == [] and charges(tenant, w.person["id"]) == []
    standing = ok(client.get(f"{API}/membership-standings?client_ids={w.person['id']}", headers=owner))
    assert standing[0]["is_member"] is True and standing[0]["contract_id"] == sold["id"]
    assert client.post(f"{API}/membership-contracts", headers=owner,
                       json=sale(w, client_id=new_client(client, owner, w.location_id)["id"],
                                 payment={"amount_minor": 1, "tender_kind": "cash"})).status_code == 422  # fmt: skip


def test_single_and_deferred_invoice_modes(client, tenant, owner):
    w = world(client, owner, tenant, billing_occurrences_count=3)
    single = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w, invoice_mode="single")), 201)
    assert [p.status for p in periods(tenant, single["id"])] == ["billed"] * 3
    assert [i.total_minor for i in invoices(tenant, w.person["id"])] == [9300]  # every period on one invoice

    later = new_client(client, owner, w.location_id)
    deferred = ok(client.post(f"{API}/membership-contracts", headers=owner,
                              json=sale(w, client_id=later["id"], invoice_mode="deferred")), 201)  # fmt: skip
    assert deferred["invoice_id"] is None and charges(tenant, later["id"]) == []
    with tx(tenant) as session:
        assert service.run_daily(session)["periods_billed"] == 0  # "invoice later" stays out of the billing run
    url = f"{API}/membership-contracts/{deferred['id']}/billing-schedule/invoice"
    first = periods(tenant, deferred["id"])[0]
    one = ok(client.post(url, headers=owner, json={"period_ids": [str(first.id)]}))
    assert one["invoice_id"] and one["period_ids"] == [str(first.id)]
    assert client.post(url, headers=owner, json={"period_ids": [str(first.id)]}).status_code == 422  # already billed
    rest = ok(client.post(url, headers=owner))
    assert len(rest["period_ids"]) == 2 and [i.total_minor for i in invoices(tenant, later["id"])] == [3100, 6200]


def test_contract_document_gates_activation_until_it_is_accepted(client, tenant, owner):
    w = world(client, owner, tenant)
    waiver = template(client, owner)
    ok(client.put(f"{API}/document-bindings", headers=owner,
                  json={"scope_type": "membership_plan", "scope_id": w.plan["id"], "template_id": waiver["id"],
                        "frequency": "every_purchase"}))  # fmt: skip
    quote = ok(client.post(f"{API}/membership-contracts/quote", headers=owner, json=sale(w)))
    assert quote["requirements"][0]["is_satisfied"] is False

    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    assert (sold["status"], sold["effective_status"]) == ("upcoming", "upcoming") and sold["client_document_id"]
    assert sold["invoice_id"]  # the sale is billed; only access waits for the signature
    standing = ok(client.get(f"{API}/membership-standings?client_ids={w.person['id']}", headers=owner))[0]
    assert (standing["is_member"], standing["status"]) == (False, "upcoming")
    with tx(tenant) as session:
        assert service.run_daily(session)["transitions"] == 0  # the job does not activate a gated contract

    document = ok(client.get(f"{API}/client-documents/{sold['client_document_id']}", headers=owner))
    assert sign(client, owner, document).status_code == 200
    deliver_events()  # documents.document.accepted reaches the memberships handler
    active = ok(client.get(f"{API}/membership-contracts/{sold['id']}", headers=owner))
    assert (active["status"], active["activated_at"] is not None) == ("active", True)
    assert "memberships.contract.activated" in event_types(tenant, sold["id"])
    consumed = ok(client.get(f"{API}/client-documents/{sold['client_document_id']}", headers=owner))
    assert consumed["source_id"] == sold["id"]  # an every-purchase binding asks again at the next sale


@pytest.mark.parametrize(
    ("role", "method", "path", "status"),
    [
        ("front_desk", "GET", "/membership-contracts", 200),
        ("front_desk", "POST", "/membership-contracts/quote", 422),  # allowed: fails on the empty body
        ("front_desk", "POST", "/membership-plans", 403),
        ("front_desk", "PATCH", "/membership-settings", 403),
        ("front_desk", "POST", "/membership-contracts/{id}/freezes", 403),
        ("front_desk", "POST", "/membership-contracts/{id}/suspensions", 403),
        ("front_desk", "POST", "/membership-contracts/{id}/cancel", 403),
        ("front_desk", "POST", "/membership-contracts/{id}/shares", 403),
        ("front_desk", "POST", "/membership-contracts/{id}/reprice", 403),
        ("front_desk", "POST", "/membership-contracts/{id}/renew", 201),
        ("coach", "POST", "/membership-contracts/{id}/renew", 403),
        ("coach", "GET", "/membership-contracts/{id}", 404),  # own reach: not this coach's client
        ("coach", "GET", "/membership-plans", 200),
        ("view_only", "GET", "/membership-contracts", 403),
        ("scorekeeper", "GET", "/membership-plans", 403),
        ("manager", "POST", "/membership-contracts/{id}/freezes", 201),
        ("manager", "PATCH", "/membership-settings", 200),
    ],
)
def test_router_gate_follows_the_matrix(client, tenant, owner, role, method, path, status):
    w = world(client, owner, tenant, auto_renew_lead_count=1, auto_renew_lead_unit="day")
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    email, _ = add_staff(tenant, role, location_ids=[w.location_id])
    response = client.request(method, f"{API}{path.format(id=sold['id'])}", headers=login(client, tenant, email),
                              json=None if method == "GET" or path.endswith(("freezes", "renew")) else {})  # fmt: skip
    assert response.status_code == status, response.text


def test_own_reach_and_location_containment(client, tenant, owner):
    w = world(client, owner, tenant)
    elsewhere = world(client, owner, tenant)
    here = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    there = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(elsewhere)), 201)
    manager_email, _ = add_staff(tenant, "manager", location_ids=[w.location_id])
    manager = login(client, tenant, manager_email)
    # reads follow the client across locations; commands stop at the location boundary with a 404
    assert len(ok(client.get(f"{API}/membership-contracts", headers=manager))["data"]) == 2
    assert client.post(f"{API}/membership-contracts/{here['id']}/freezes", headers=manager).status_code == 201
    refused(client.post(f"{API}/membership-contracts/{there['id']}/freezes", headers=manager), 404, "not-found")
    refused(client.post(f"{API}/membership-contracts", headers=manager, json=sale(elsewhere)), 404, "not-found")

    coach_email, coach_id = add_staff(tenant, "coach", location_ids=[w.location_id])
    coach = login(client, tenant, coach_email)
    assert ok(client.get(f"{API}/membership-contracts", headers=coach))["data"] == []
    ok(
        client.put(
            f"{API}/clients/{w.person['id']}/owners",
            headers=owner,
            json={"default_trainer_staff_user_id": str(coach_id)},
        )
    )
    assert [c["id"] for c in ok(client.get(f"{API}/membership-contracts", headers=coach))["data"]] == [here["id"]]
    assert client.get(f"{API}/membership-contracts/{here['id']}", headers=coach).status_code == 200
    assert client.get(f"{API}/membership-contracts/{there['id']}/billing-schedule", headers=coach).status_code == 404


def test_service_gate_denies_without_the_router(client, tenant, owner):
    from app.core.auth import Principal
    from app.core.errors import PermissionDenied

    w = world(client, owner, tenant)
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    nobody = Principal(kind="staff", tenant_id=tenant.id, staff_user_id=uuid4(), permissions={}, location_ids=None)
    calls = [
        lambda s: service.sell_contract(s, nobody, sale(w)),
        lambda s: service.freeze_contract(s, nobody, sold["id"], {}),
        lambda s: service.suspend_contract(s, nobody, sold["id"], {}),
        lambda s: service.cancel_contract(s, nobody, sold["id"], {"reason": "voluntary"}),
        lambda s: service.renew_contract(s, nobody, sold["id"], {}),
        lambda s: service.update_contract(s, nobody, sold["id"], {"internal_notes": "x"}),
        lambda s: service.reprice_contract(s, nobody, sold["id"], {"term_fee_minor": 1}),
        lambda s: service.add_share(s, nobody, sold["id"], uuid4()),
        lambda s: service.adjust_visits(s, nobody, sold["id"], {"delta": 1, "reason": "x"}),
        lambda s: service.create_plan(s, nobody, {}),
        lambda s: service.update_settings(s, nobody, {}),
        lambda s: service.get_contract(s, nobody, sold["id"]),
    ]
    for call in calls:
        with pytest.raises(PermissionDenied), tx(tenant) as session:
            call(session)
    assert contract(tenant, sold["id"]).version == 2  # sold and activated; nothing else touched it
