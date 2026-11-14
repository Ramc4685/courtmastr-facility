"""Package plans, the sale, validity and expiry, renewal, recurring series, sharing, removal, the portal,
permissions, merge and erasure (PKG-01 to PKG-07, PKG-09, PKG-10, PKG-13, PKG-14)."""

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.audit import AuditEvent
from app.core.auth import Principal
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.modules import clients, platform
from app.modules.documents.tests.support import sign, template
from app.modules.memberships.tests.support import (
    API,
    SYSTEM,
    account_credit,
    at,
    charges,
    event_types,
    invoices,
    ok,
    open_balance,
    package_plan,
    refused,
    sale,
    tx,
    world,
)
from app.modules.packages import service
from app.modules.packages.models import ClientPackage, CreditLedgerEntry, PackageSeries, PackageShare
from conftest import add_staff, login, new_client, scalar

D = date


def pack(w, plan: dict, **fields) -> dict:
    return {"client_id": w.person["id"], "location_id": w.location_id, "package_plan_id": plan["id"]} | fields


def sell_at(w, plan: dict, day: date, **fields) -> ClientPackage:
    """Sell through the internal interface on a calendar day."""
    with at(day), tx(w.tenant) as session:
        sold = service.sell(session, client_id=UUID(w.person["id"]), location_id=UUID(w.location_id),
                            package_plan_id=UUID(plan["id"]), **fields)  # fmt: skip
        return sold["package"]


def daily(tenant, day: date) -> dict:
    with at(day), tx(tenant) as session:
        return service.run_daily(session)


def package(tenant, package_id) -> ClientPackage:
    with tx(tenant) as session:
        return session.get(ClientPackage, package_id)


def ledger(tenant, package_id) -> list[CreditLedgerEntry]:
    with tx(tenant) as session:
        stmt = select(CreditLedgerEntry).where(CreditLedgerEntry.client_package_id == package_id)
        return list(session.scalars(stmt.order_by(CreditLedgerEntry.occurred_at, CreditLedgerEntry.id)))


def reserve(tenant, package_id, client_id, source_id=None, day: date | None = None, **extra):
    with tx(tenant) as session:
        return service.reserve_credit(session, client_package_id=package_id, client_id=UUID(str(client_id)),
                                      source_type="booking", source_id=source_id or uuid4(), session_on=day, **extra)  # fmt: skip


def settle(tenant, source_id, outcome: str):
    with tx(tenant) as session:
        return service.settle_credit(session, source_type="booking", source_id=source_id, outcome=outcome)


@pytest.fixture
def w(client, tenant, owner):
    return world(client, owner, tenant)


# --- plans -------------------------------------------------------------------------------------------------------


def test_plan_shapes_and_their_rules(w, client, owner):
    post = lambda **fields: client.post(f"{API}/package-plans", headers=owner, json=fields)  # noqa: E731
    base = ok(client.get(f"{API}/package-plans", headers=owner))["data"]
    assert base == []
    ten = package_plan(client, owner, w.tenant)
    common = {
        "reservation_type_id": ten["reservation_type_id"],
        "revenue_category_id": ten["revenue_category_id"],
        "name": "X",
    }
    paid = common | {"fee_minor": 1000, "fee_basis": "per_session"}
    assert post(**paid, session_mode="single").status_code == 201
    assert post(**paid, session_mode="range", min_session_count=1, max_session_count=5).status_code == 201
    assert post(**paid, session_mode="unlimited", validity_count=1, validity_unit="month").status_code == 201
    free = {
        "reservation_type_id": ten["reservation_type_id"],
        "name": "Trial",
        "session_mode": "single",
        "pricing_category": "free",
    }
    assert post(**free).status_code == 201
    recurring = paid | {"kind": "recurring", "session_mode": "fixed", "session_count": 4, "recurrence_unit": "month",
                        "recurrence_interval_count": 1, "recurrence_occurrences_count": 6}  # fmt: skip
    assert post(**recurring).status_code == 201
    for bad in (
        paid | {"session_mode": "fixed"},  # no count
        paid | {"session_mode": "range", "min_session_count": 5, "max_session_count": 2},
        common | {"session_mode": "single"},  # paid without a fee
        free | {"fee_minor": 100},  # free with a fee
        common | {"session_mode": "single", "fee_minor": 100, "fee_basis": "per_package"},  # single is per session
        recurring | {"session_mode": "range", "session_count": None, "min_session_count": 1, "max_session_count": 2},
        paid | {"session_mode": "single", "kind": "recurring"},  # recurring without a recurrence
        paid | {"session_mode": "single", "start_rule": "fixed_date"},
        paid | {"session_mode": "single", "validity_count": 3},  # count without unit
        paid | {"session_mode": "single", "auto_renew_lead_count": 5, "auto_renew_lead_unit": "day"},  # no length
        paid | {"session_mode": "single", "validity_count": 1, "validity_unit": "week", "auto_renew_lead_count": 8,
                "auto_renew_lead_unit": "day"},  # lead longer than the package
        paid | {"session_mode": "single", "default_invoice_mode": "per_period"},
        paid | {"session_mode": "single", "renewal_target": "plan", "renews_as_plan_id": str(uuid4())},
        paid | {"session_mode": "single", "discount_pct": "5", "discount_minor": 5},
    ):  # fmt: skip
        assert post(**bad).status_code == 422, bad
    listed = ok(client.get(f"{API}/package-plans?session_mode=single&pricing_category=paid", headers=owner))["data"]
    assert len(listed) == 1 and len(ok(client.get(f"{API}/package-plans?kind=recurring", headers=owner))["data"]) == 1
    url = f"{API}/package-plans/{ten['id']}"
    edited = ok(
        client.patch(url, headers=owner, json={"fee_minor": 12000, "validity_count": 6, "validity_unit": "month"})
    )
    assert (edited["fee_minor"], edited["version"]) == (12000, 2) and ok(client.get(url, headers=owner))[
        "validity_count"
    ] == 6
    cleared = ok(client.patch(url, headers=owner, json={"validity_count": None, "validity_unit": None}))
    assert cleared["validity_count"] is None
    settings = ok(client.patch(f"{API}/package-settings", headers=owner, json={"is_no_show_charged": False}))
    assert (settings["is_no_show_charged"], settings["is_late_cancel_charged"]) == (False, True)
    assert ok(client.get(f"{API}/package-settings", headers=owner))["expiry_notice_days"] == 7


# --- sale --------------------------------------------------------------------------------------------------------


def test_staff_sale_grants_credits_bills_and_takes_payment(w, client, owner):
    plan = package_plan(
        client, owner, w.tenant, validity_count=6, validity_unit="month", invoice_description="Ten lessons"
    )
    quote = ok(client.post(f"{API}/client-packages/quote", headers=owner, json=pack(w, plan)))
    assert (quote["sessions_granted_count"], quote["price_minor"], quote["unit_price_minor"]) == (10, 10000, 1000)
    assert scalar(w.tenant, select(func.count()).select_from(ClientPackage)) == 0

    sold = ok(client.post(f"{API}/client-packages", headers=owner,
                          json=pack(w, plan, payment={"amount_minor": 10000, "tender_kind": "bank_transfer"})), 201)  # fmt: skip
    assert (sold["status"], sold["sessions_granted_count"], sold["sessions_available_count"]) == ("active", 10, 10)
    assert (sold["price_minor"], sold["invoice_mode"], sold["payment_status"]) == (10000, "single", "succeeded")
    start = date.fromisoformat(sold["valid_from_on"])
    assert sold["valid_until_on"] == quote["valid_until_on"] and date.fromisoformat(
        sold["valid_until_on"]
    ) >= start + timedelta(days=180)
    (charge,) = charges(w.tenant, w.person["id"])
    assert (charge.source_context, charge.source_type, str(charge.source_id), charge.total_minor) == (
        "packages", "client_package", sold["id"], 10000)  # fmt: skip
    assert invoices(w.tenant, w.person["id"])[0].status == "paid" and str(charge.id) == sold["charge_id"]
    entries = ledger(w.tenant, sold["id"])
    assert [(e.entry_type, e.reason, e.granted_delta, e.actor_type) for e in entries] == [
        ("grant", "purchase", 10, "staff")
    ]
    assert event_types(w.tenant, UUID(sold["id"])) == ["packages.package.sold"]
    assert (
        scalar(
            w.tenant, select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "packages.package.sell")
        )
        == 1
    )

    ok(client.patch(f"{API}/package-plans/{plan['id']}", headers=owner, json={"fee_minor": 99, "name": "Changed"}))
    again = ok(client.get(f"{API}/client-packages/{sold['id']}", headers=owner))
    assert (again["price_minor"], again["name"]) == (10000, plan["name"])  # the sold package is a snapshot
    listed = ok(client.get(f"{API}/client-packages?client_id={w.person['id']}&status=active", headers=owner))["data"]
    assert [p["id"] for p in listed] == [sold["id"]]
    page = ok(client.get(f"{API}/client-packages/{sold['id']}/ledger", headers=owner))["data"]
    assert [e["entry_type"] for e in page] == ["grant"]


def test_price_and_credits_by_session_mode(w, client, owner):
    kinds = {
        "per_session": package_plan(client, owner, w.tenant, session_count=5, fee_minor=1500, fee_basis="per_session", discount_pct="10"),
        "range": package_plan(client, owner, w.tenant, session_mode="range", session_count=None, min_session_count=2,
                              max_session_count=6, fee_minor=1000, fee_basis="per_session", discount_minor=500),
        "unlimited": package_plan(client, owner, w.tenant, session_mode="unlimited", session_count=None, fee_minor=9000,
                                  validity_count=1, validity_unit="month"),
        "single": package_plan(client, owner, w.tenant, session_mode="single", session_count=None, fee_minor=2500, fee_basis="per_session"),
        "free": package_plan(client, owner, w.tenant, session_mode="single", session_count=None, pricing_category="free"),
        "later": package_plan(client, owner, w.tenant, default_invoice_mode="deferred", start_rule="fixed_date",
                              fixed_start_on="2030-01-01", validity_count=10, validity_unit="day"),
    }  # fmt: skip

    def sell(key, **fields):
        return client.post(f"{API}/client-packages", headers=owner, json=pack(w, kinds[key], **fields))

    per_session = ok(sell("per_session"), 201)
    assert (per_session["price_minor"], per_session["unit_price_minor"], per_session["sessions_granted_count"]) == (
        6750,
        1350,
        5,
    )
    assert sell("range").status_code == 422 and sell("range", quantity=7).status_code == 422
    ranged = ok(sell("range", quantity=3), 201)
    assert (ranged["sessions_granted_count"], ranged["price_minor"], ranged["unit_price_minor"]) == (3, 2500, 833)
    unlimited = ok(sell("unlimited"), 201)
    assert (unlimited["is_unlimited"], unlimited["sessions_available_count"], unlimited["price_minor"]) == (
        True,
        None,
        9000,
    )
    assert ledger(w.tenant, unlimited["id"]) == []  # nothing to grant
    assert ok(sell("single"), 201)["sessions_granted_count"] == 1
    free = ok(sell("free"), 201)
    assert (free["price_minor"], free["invoice_mode"], free["charge_id"], free["invoice_id"]) == (0, "none", None, None)
    assert sell("free", payment={"amount_minor": 1, "tender_kind": "cash"}).status_code == 422
    later = ok(sell("later"), 201)
    assert (later["invoice_mode"], later["invoice_id"], later["valid_from_on"], later["valid_until_on"]) == (
        "deferred", None, "2030-01-01", "2030-01-10")  # fmt: skip
    assert later["charge_id"] and len(invoices(w.tenant, w.person["id"])) == 4  # the deferred charge waits uninvoiced
    assert (
        sell("single", payment={"amount_minor": 2500, "tender_kind": "card", "method_token": "tok_card_ok"}).status_code
        == 422
    )
    retired = ok(client.patch(f"{API}/package-plans/{kinds['single']['id']}", headers=owner, json={"is_active": False}))
    assert retired["is_active"] is False and sell("single").status_code == 422


def test_complimentary_grant_needs_its_own_permission(w, client, owner):
    plan = package_plan(client, owner, w.tenant)
    desk_email, _ = add_staff(w.tenant, "front_desk", location_ids=[w.location_id])
    desk = login(client, w.tenant, desk_email)
    refused(
        client.post(f"{API}/client-packages/complimentary", headers=desk, json=pack(w, plan)), 403, "permission-denied"
    )
    gift = ok(
        client.post(
            f"{API}/client-packages/complimentary", headers=owner, json=pack(w, plan, internal_remarks="Apology")
        ),
        201,
    )
    assert (gift["is_complimentary"], gift["price_minor"], gift["invoice_mode"], gift["sessions_granted_count"]) == (
        True,
        0,
        "none",
        10,
    )
    assert charges(w.tenant, w.person["id"]) == []
    assert (
        scalar(w.tenant, select(AuditEvent.action).where(AuditEvent.entity_id == UUID(gift["id"])))
        == "packages.package.grant_complimentary"
    )
    assert ok(client.post(f"{API}/client-packages", headers=desk, json=pack(w, plan)), 201)["is_complimentary"] is False


def test_members_only_and_document_bound_plans(w, client, owner):
    members = package_plan(client, owner, w.tenant, is_members_only_at_desk=True)
    refused(client.post(f"{API}/client-packages", headers=owner, json=pack(w, members)), 409, "members-only")
    assert ok(client.post(f"{API}/client-packages/quote", headers=owner, json=pack(w, members)))["is_member"] is False
    ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    assert client.post(f"{API}/client-packages", headers=owner, json=pack(w, members)).status_code == 201

    bound = package_plan(client, owner, w.tenant)
    waiver = template(client, owner)
    ok(client.put(f"{API}/document-bindings", headers=owner,
                  json={"scope_type": "package_plan", "scope_id": bound["id"], "template_id": waiver["id"],
                        "frequency": "every_purchase"}))  # fmt: skip
    stopped = refused(
        client.post(f"{API}/client-packages", headers=owner, json=pack(w, bound)), 409, "document-required"
    )
    document = ok(client.get(f"{API}/client-documents/{stopped['document_id']}", headers=owner))  # issued and kept
    assert document["status"] == "pending"
    again = refused(client.post(f"{API}/client-packages", headers=owner, json=pack(w, bound)), 409, "document-required")
    assert again["document_id"] == stopped["document_id"]  # the same pending document, not a second one
    assert sign(client, owner, document).status_code == 200
    sold = ok(client.post(f"{API}/client-packages", headers=owner, json=pack(w, bound)), 201)
    assert sold["client_document_id"] == document["id"]
    used = ok(client.get(f"{API}/client-documents/{document['id']}", headers=owner))
    assert used["source_id"] == sold["id"]
    refused(
        client.post(f"{API}/client-packages", headers=owner, json=pack(w, bound)), 409, "document-required"
    )  # every purchase


# --- validity, expiry and renewal --------------------------------------------------------------------------------


def test_expiry_forfeits_what_is_left_unless_booking_after_expiry_is_allowed(w, client, owner):
    strict = package_plan(client, owner, w.tenant, validity_count=1, validity_unit="month")
    lenient = package_plan(
        client, owner, w.tenant, validity_count=1, validity_unit="month", allows_booking_after_expiry=True
    )
    a, b = sell_at(w, strict, D(2025, 1, 10)), sell_at(w, lenient, D(2025, 1, 10))
    assert (a.valid_during.lower, a.valid_during.upper) == (D(2025, 1, 10), D(2025, 2, 10))
    person = w.person["id"]
    with at(D(2025, 1, 20)):
        booked, attended = uuid4(), uuid4()
        reserve(w.tenant, a.id, person, booked, D(2025, 2, 5))
        reserve(w.tenant, a.id, person, attended)
        settle(w.tenant, attended, "attended")
        for outside in (D(2025, 1, 9), D(2025, 2, 10)):
            with pytest.raises(Conflict) as out:
                reserve(w.tenant, a.id, person, day=outside)
            assert out.value.code == "package-out-of-range"
        assert reserve(w.tenant, b.id, person, day=D(2025, 3, 1)) is not None  # leftover sessions may be booked later
    assert daily(w.tenant, D(2025, 2, 9))["expired"] == 0  # the last valid day
    assert daily(w.tenant, D(2025, 2, 10))["expired"] == 2
    assert daily(w.tenant, D(2025, 2, 10)) == {"renewed": 0, "expired": 0, "periods_generated": 0, "failed": []}
    gone, kept = package(w.tenant, a.id), package(w.tenant, b.id)
    assert (gone.status, gone.sessions_forfeited_count, gone.sessions_reserved_count, gone.sessions_consumed_count) == (
        "expired",
        8,
        1,
        1,
    )
    assert (kept.status, kept.sessions_forfeited_count, service.available(kept)) == ("expired", 0, 9)
    assert (
        ledger(w.tenant, a.id)[-1].reason == "expiry" and event_types(w.tenant, a.id)[-1] == "packages.package.expired"
    )
    with at(D(2025, 2, 11)):
        with pytest.raises(Conflict) as dead:
            reserve(w.tenant, a.id, person)
        assert dead.value.code == "package-not-usable"
        assert reserve(w.tenant, b.id, person) is not None
        assert settle(w.tenant, booked, "attended").entry_type == "consume"  # booked while valid: still honoured
        with tx(w.tenant) as session:
            assert [p.id for p in service.spendable_packages(session, UUID(person))] == [b.id]

    extended = ok(client.patch(f"{API}/client-packages/{a.id}", headers=owner, json={"valid_until_on": "2099-01-01"}))
    assert (extended["status"], extended["valid_until_on"], extended["sessions_available_count"]) == (
        "exhausted",
        "2099-01-01",
        0,
    )
    forever = ok(client.patch(f"{API}/client-packages/{b.id}", headers=owner, json={"valid_until_on": None}))
    assert (forever["status"], forever["valid_until_on"]) == ("active", None)
    assert (
        client.patch(f"{API}/client-packages/{b.id}", headers=owner, json={"valid_until_on": "2020-01-01"}).status_code
        == 422
    )


def test_time_based_renewal_runs_once_and_copies_the_package_as_sold(w, client, owner):
    plan = package_plan(client, owner, w.tenant, validity_count=1, validity_unit="month", auto_renew_lead_count=5,
                        auto_renew_lead_unit="day")  # fmt: skip
    kid = new_client(client, owner, w.location_id)
    first = sell_at(w, plan, D(2025, 1, 10))
    assert (first.is_auto_renew, first.renew_on) == (True, D(2025, 2, 4))  # five days before the last valid day
    with tx(w.tenant) as session:
        service.add_share(session, SYSTEM, first.id, UUID(kid["id"]))
    ok(client.patch(f"{API}/package-plans/{plan['id']}", headers=owner, json={"fee_minor": 20000}))
    assert daily(w.tenant, D(2025, 2, 3))["renewed"] == 0
    assert daily(w.tenant, D(2025, 2, 4))["renewed"] == 1
    assert daily(w.tenant, D(2025, 2, 4))["renewed"] == 0 and daily(w.tenant, D(2025, 2, 5))["renewed"] == 0
    with tx(w.tenant) as session:
        second = service._successor(session, first.id)
        shares = session.scalars(select(PackageShare).where(PackageShare.client_package_id == second.id)).all()
    assert (second.valid_during.lower, second.valid_during.upper, second.sales_channel) == (
        D(2025, 2, 10),
        D(2025, 3, 10),
        "renewal",
    )
    assert (second.price_minor, second.sessions_granted_count, second.renew_on) == (
        10000,
        10,
        D(2025, 3, 4),
    )  # same terms
    assert [(s.client_id, s.origin) for s in shares] == [(UUID(kid["id"]), "carried_from_previous")]
    assert len(charges(w.tenant, w.person["id"])) == 2 and len(invoices(w.tenant, w.person["id"])) == 2
    assert event_types(w.tenant, first.id)[-1] == "packages.package.renewed"
    with pytest.raises(Conflict) as twice:
        with at(D(2025, 2, 5)), tx(w.tenant) as session:
            service.renew_package(session, SYSTEM, first.id)
    assert twice.value.code == "already-renewed"

    other = package_plan(client, owner, w.tenant, fee_minor=7000, session_count=6)
    with at(D(2025, 2, 6)), tx(w.tenant) as session:  # renew into another plan: read from that plan now
        edited = service.update_package(session, SYSTEM, second.id, {"renews_as_plan_id": UUID(other["id"])})
        third = service.renew_package(session, SYSTEM, second.id)
    assert edited["renewal_target"] == "plan"
    assert (third["name"], third["price_minor"], third["sessions_granted_count"], third["valid_from_on"]) == (
        other["name"],
        7000,
        6,
        D(2025, 3, 10),
    )
    assert third["valid_until_on"] is None and third["previous_package_id"] == second.id


def test_renewal_threshold_flags_or_renews_when_credits_run_low(w, client, owner):
    flagging = package_plan(client, owner, w.tenant, session_count=3, renewal_threshold_count=1)
    renewing = package_plan(
        client, owner, w.tenant, session_count=3, renewal_threshold_count=1, is_auto_renew_on_threshold=True
    )
    a, b = sell_at(w, flagging, D(2025, 1, 10)), sell_at(w, renewing, D(2025, 1, 10))
    assert (a.renewal_flagged_at, b.renewal_flagged_at, b.is_auto_renew) == (None, None, True)
    person = w.person["id"]
    with at(D(2025, 1, 12)):
        for pkg in (a, b):
            reserve(w.tenant, pkg.id, person)
            assert package(w.tenant, pkg.id).renewal_flagged_at is None  # two left: above the threshold
            last = uuid4()
            reserve(w.tenant, pkg.id, person, last)
        assert package(w.tenant, a.id).renewal_flagged_at is not None
        with tx(w.tenant) as session:
            assert service._successor(session, a.id) is None  # flagged for staff, nothing sold
            renewed = service._successor(session, b.id)
        assert (
            renewed is not None and renewed.valid_during.lower == D(2025, 1, 12) and renewed.sessions_granted_count == 3
        )
        settle(w.tenant, last, "early_cancel")  # back above the threshold: the flag clears, no second successor
        assert package(w.tenant, b.id).renewal_flagged_at is None
        reserve(w.tenant, b.id, person)
    with tx(w.tenant) as session:
        chained = session.scalars(select(ClientPackage).where(ClientPackage.previous_package_id == b.id)).all()
    assert len(chained) == 1 and len(charges(w.tenant, person)) == 3
    view = ok(client.get(f"{API}/client-packages/{a.id}", headers=owner))
    assert view["is_renewal_due"] is True and view["renewal_threshold_count"] == 1
    off = ok(
        client.patch(
            f"{API}/client-packages/{a.id}",
            headers=owner,
            json={"renewal_threshold_count": None, "is_auto_renew": False},
        )
    )
    assert off["renewal_threshold_count"] is None


def test_recurring_plan_materialises_one_period_at_a_time(w, client, owner):
    monthly = package_plan(client, owner, w.tenant, kind="recurring", session_count=4, fee_minor=4000, recurrence_unit="month",
                           recurrence_interval_count=1, recurrence_occurrences_count=3)  # fmt: skip
    first = sell_at(w, monthly, D(2025, 1, 15))
    with tx(w.tenant) as session:
        series = session.get(PackageSeries, first.package_series_id)
    assert (series.occurrences_total_count, series.occurrences_generated_count, series.next_period_start_on, series.invoice_mode) == (
        3, 1, D(2025, 2, 15), "per_period")  # fmt: skip
    assert (first.series_sequence_number, first.valid_during.upper, first.is_auto_renew) == (1, D(2025, 2, 15), False)
    assert [c.total_minor for c in charges(w.tenant, w.person["id"])] == [4000]
    assert daily(w.tenant, D(2025, 2, 14))["periods_generated"] == 0
    assert daily(w.tenant, D(2025, 2, 15))["periods_generated"] == 1
    assert daily(w.tenant, D(2025, 2, 15))["periods_generated"] == 0
    caught_up = daily(w.tenant, D(2025, 5, 1))  # the job was down for weeks: the last period, then the series closes
    assert (caught_up["periods_generated"], caught_up["expired"], caught_up["failed"]) == (1, 2, [])
    with tx(w.tenant) as session:
        done = session.get(PackageSeries, series.id)
        periods = session.scalars(select(ClientPackage).where(ClientPackage.package_series_id == series.id)
                                  .order_by(ClientPackage.series_sequence_number)).all()  # fmt: skip
    assert (done.status, done.occurrences_generated_count, done.next_period_start_on) == ("completed", 3, None)
    assert [(p.series_sequence_number, p.valid_during.lower, p.sessions_granted_count) for p in periods] == [
        (1, D(2025, 1, 15), 4), (2, D(2025, 2, 15), 4), (3, D(2025, 3, 15), 4)]  # fmt: skip
    assert [c.total_minor for c in charges(w.tenant, w.person["id"])] == [4000] * 3 and len(
        invoices(w.tenant, w.person["id"])
    ) == 3
    listed = ok(client.get(f"{API}/package-series?client_id={w.person['id']}", headers=owner))["data"]
    assert [s["status"] for s in listed] == ["completed"]
    refused(client.post(f"{API}/package-series/{series.id}/cancel", headers=owner), 409, "invalid-state-transition")


def test_recurring_single_invoice_cancel_and_series_auto_renew(w, client, owner):
    prepaid = package_plan(client, owner, w.tenant, kind="recurring", session_count=2, fee_minor=3000, recurrence_unit="week",
                           recurrence_interval_count=1, recurrence_occurrences_count=4, is_series_auto_renew=True)  # fmt: skip
    first = sell_at(w, prepaid, D(2025, 1, 6), invoice_mode="single")
    assert [c.total_minor for c in charges(w.tenant, w.person["id"])] == [12000]  # the whole series on one invoice
    assert daily(w.tenant, D(2025, 1, 13))["periods_generated"] == 1
    assert [c.total_minor for c in charges(w.tenant, w.person["id"])] == [12000]  # later periods carry no charge
    rolled = daily(w.tenant, D(2025, 2, 3))  # the fourth week ended: the series restarts on the plan's terms
    assert rolled["periods_generated"] == 2 and rolled["failed"] == []
    with tx(w.tenant) as session:
        all_series = session.scalars(select(PackageSeries).order_by(PackageSeries.id)).all()
    assert [(s.status, s.occurrences_generated_count) for s in all_series] == [("completed", 4), ("active", 1)]
    assert [c.total_minor for c in charges(w.tenant, w.person["id"])] == [12000, 12000]

    cancelled = ok(client.post(f"{API}/package-series/{all_series[1].id}/cancel", headers=owner))
    assert (cancelled["status"], cancelled["next_period_start_on"]) == ("cancelled", None)
    assert daily(w.tenant, D(2025, 3, 1))["periods_generated"] == 0
    assert ok(client.get(f"{API}/package-series/{first.package_series_id}", headers=owner))["status"] == "completed"


# --- sharing and removal -----------------------------------------------------------------------------------------


def test_sharing_by_plan_preset_and_by_hand(w, client, owner):
    kid, friend = new_client(client, owner, w.location_id), new_client(client, owner, w.location_id)
    parent_of = next(t for t in ok(client.get(f"{API}/relationship-types", headers=owner)) if t["code"] == "parent_of")
    ok(client.post(f"{API}/clients/{w.person['id']}/relationships", headers=owner,
                   json={"other_client_id": kid["id"], "relationship_type_id": parent_of["id"]}), 201)  # fmt: skip
    family = package_plan(client, owner, w.tenant, share_mode="all_related", session_count=2)
    sold = ok(client.post(f"{API}/client-packages", headers=owner, json=pack(w, family)), 201)
    url = f"{API}/client-packages/{sold['id']}/shares"
    assert [(s["client_id"], s["origin"]) for s in ok(client.get(url, headers=owner))] == [(kid["id"], "plan_preset")]
    assert sold["share_count"] == 1 and sold["share_mode"] == "all_related"

    with pytest.raises(Conflict) as not_shared:
        reserve(w.tenant, UUID(sold["id"]), friend["id"])
    assert not_shared.value.code == "package-not-shared"
    share = ok(client.post(url, headers=owner, json={"client_id": friend["id"]}), 201)
    assert ok(client.post(url, headers=owner, json={"client_id": friend["id"]}), 201)["id"] == share["id"]
    assert client.post(url, headers=owner, json={"client_id": w.person["id"]}).status_code == 422
    reserve(w.tenant, UUID(sold["id"]), kid["id"])
    entry = reserve(w.tenant, UUID(sold["id"]), friend["id"])
    assert str(entry.client_id) == friend["id"]  # the ledger says who used the owner's credit
    with pytest.raises(Conflict) as empty:
        reserve(w.tenant, UUID(sold["id"]), w.person["id"])  # every sharer draws on the one balance
    assert empty.value.code == "package-exhausted"
    usable = ok(client.get(f"{API}/client-packages?usable_by_client_id={friend['id']}", headers=owner))["data"]
    assert [p["id"] for p in usable] == [sold["id"]] and usable[0]["owner_client_id"] == w.person["id"]
    assert client.get(f"{API}/client-packages?usable_by_client_id=nope", headers=owner).status_code == 422

    assert client.delete(f"{url}/{share['id']}", headers=owner).status_code == 204
    assert client.delete(f"{url}/{uuid4()}", headers=owner).status_code == 404
    with tx(w.tenant) as session:
        assert service.spendable_packages(session, UUID(friend["id"])) == []


def test_remove_reverses_or_keeps_billing_and_releases_open_reservations(w, client, owner):
    plan = package_plan(client, owner, w.tenant, session_count=4, fee_minor=8000)
    paid = {"payment": {"amount_minor": 8000, "tender_kind": "cash"}}
    unused = ok(client.post(f"{API}/client-packages", headers=owner, json=pack(w, plan, **paid)), 201)
    used = ok(client.post(f"{API}/client-packages", headers=owner, json=pack(w, plan, **paid)), 201)
    person = w.person["id"]
    booked, attended = uuid4(), uuid4()
    reserve(w.tenant, UUID(used["id"]), person, booked)
    reserve(w.tenant, UUID(used["id"]), person, attended)
    settle(w.tenant, attended, "attended")

    quote = ok(client.post(f"{API}/client-packages/{unused['id']}/removal-quote", headers=owner))
    assert (quote["can_reverse_billing"], quote["charge_total_minor"], quote["paid_minor"]) == (True, 8000, 8000)
    removed = ok(
        client.post(
            f"{API}/client-packages/{unused['id']}/remove", headers=owner, json={"removal_mode": "billing_reversed"}
        )
    )
    assert (removed["status"], removed["removal_mode"], removed["sessions_forfeited_count"], removed["is_auto_renew"]) == (
        "removed", "billing_reversed", 4, False)  # fmt: skip
    assert account_credit(w.tenant, person) == 8000 and open_balance(w.tenant, person) == 0  # the money is now credit
    refused(client.post(f"{API}/client-packages/{unused['id']}/remove", headers=owner, json={"removal_mode": "billing_kept"}),
            409, "invalid-state-transition")  # fmt: skip

    quote = ok(client.post(f"{API}/client-packages/{used['id']}/removal-quote", headers=owner))
    assert (quote["needs_override_reason"], quote["sessions_consumed_count"], quote["open_reservations_count"]) == (
        True,
        1,
        1,
    )  # the owner holds the override (question 16), so can_reverse_billing is true; without a reason it is refused
    refused(client.post(f"{API}/client-packages/{used['id']}/remove", headers=owner, json={"removal_mode": "billing_reversed"}),
            409, "package-in-use")  # fmt: skip
    kept = ok(
        client.post(f"{API}/client-packages/{used['id']}/remove", headers=owner, json={"removal_mode": "billing_kept"})
    )
    assert (kept["status"], kept["sessions_reserved_count"], kept["sessions_consumed_count"], kept["sessions_forfeited_count"]) == (
        "removed", 0, 1, 3)  # fmt: skip
    assert [(e.entry_type, e.reason) for e in ledger(w.tenant, used["id"])][-2:] == [
        ("release", "removal"),
        ("forfeit", "removal"),
    ]
    assert settle(w.tenant, booked, "attended") is None  # its credit was released with the package
    with pytest.raises(Conflict):
        reserve(w.tenant, UUID(used["id"]), person)
    for path, body in (
        ("", {"internal_remarks": "x"}),
        ("/credit-adjustments", {"delta": 1, "note": "x"}),
        ("/shares", {"client_id": str(uuid4())}),
    ):
        method = "PATCH" if not path else "POST"
        assert (
            client.request(method, f"{API}/client-packages/{used['id']}{path}", headers=owner, json=body).status_code
            == 409
        )


# --- portal ------------------------------------------------------------------------------------------------------


def _member(tenant, person_id: str) -> Principal:
    with tx(tenant) as session:
        identity = platform.service.create_client_identity(session, f"m-{uuid4().hex[:8]}@example.com")
        clients.service.link_identity(session, UUID(person_id), identity.id)
        return Principal(kind="client", tenant_id=tenant.id, identity_id=identity.id, display_name="Member")


def _as(tenant, principal, fn, *args, **kwargs):
    with tx(tenant) as session:
        session.info["actor"] = principal
        return fn(session, principal, *args, **kwargs)


def test_portal_lists_buys_and_opts_out(w, client, owner):
    from app.core.pagination import ListQuery

    friend = new_client(client, owner, w.location_id)
    member, outsider = _member(w.tenant, w.person["id"]), _member(w.tenant, friend["id"])
    online = package_plan(client, owner, w.tenant, online_sale_mode="paid_in_full", validity_count=1, validity_unit="month",
                          auto_renew_lead_count=3, auto_renew_lead_unit="day")  # fmt: skip
    account = package_plan(client, owner, w.tenant, online_sale_mode="balance_allowed", is_members_only_online=True)
    desk_only = package_plan(client, owner, w.tenant)
    plans = _as(w.tenant, member, service.portal_list_plans, None, ListQuery())["data"]
    assert {p["id"]: p["is_purchasable"] for p in plans} == {UUID(online["id"]): True, UUID(account["id"]): False}

    buy = {"package_plan_id": UUID(online["id"]), "location_id": UUID(w.location_id)}
    with pytest.raises(Conflict) as declined:
        _as(w.tenant, member, service.portal_buy, buy | {"method_token": "tok_card_declined"}, f"k-{uuid4().hex}")
    assert declined.value.code == "payment-failed"
    with pytest.raises(Conflict):
        _as(w.tenant, member, service.portal_buy, buy, f"k-{uuid4().hex}")  # pay-in-full with no payment
    assert (
        scalar(w.tenant, select(func.count()).select_from(ClientPackage)) == 0
        and charges(w.tenant, w.person["id"]) == []
    )
    bought = _as(w.tenant, member, service.portal_buy, buy | {"method_token": "tok_card_ok"}, f"k-{uuid4().hex}")
    assert (bought["payment_status"], bought["sales_channel"], bought["sessions_available_count"]) == (
        "succeeded",
        "portal",
        10,
    )
    assert (
        invoices(w.tenant, w.person["id"])[0].status == "paid"
        and ledger(w.tenant, bought["id"])[0].actor_type == "client"
    )
    with pytest.raises(ValidationFailed):
        _as(w.tenant, member, service.portal_buy, buy | {"package_plan_id": UUID(desk_only["id"])}, "k-desk-only")
    with pytest.raises(Conflict) as members:
        _as(w.tenant, member, service.portal_buy, buy | {"package_plan_id": UUID(account["id"])}, "k-members")
    assert members.value.code == "members-only"
    ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    on_account = _as(
        w.tenant, member, service.portal_buy, buy | {"package_plan_id": UUID(account["id"])}, "k-on-account"
    )
    assert (on_account["payment_status"], on_account["invoice_id"] is not None) == (None, True)  # a balance is allowed

    with tx(w.tenant) as session:
        service.add_share(session, SYSTEM, bought["id"], UUID(friend["id"]))
    mine = _as(w.tenant, member, service.portal_list_packages, None, ListQuery())["data"]
    theirs = _as(w.tenant, outsider, service.portal_list_packages, None, ListQuery())["data"]
    assert {p["id"] for p in mine} == {bought["id"], on_account["id"]} and [p["id"] for p in theirs] == [bought["id"]]
    assert (
        len(_as(w.tenant, outsider, service.portal_list_ledger, bought["id"], ListQuery())["data"]) == 1
    )  # a sharer may look
    with pytest.raises(NotFound):
        _as(w.tenant, outsider, service.portal_list_ledger, on_account["id"], ListQuery())
    with pytest.raises(NotFound):
        _as(
            w.tenant, outsider, service.portal_disable_auto_renew, bought["id"]
        )  # only the owner's side decides renewal
    with pytest.raises(NotFound):
        _as(w.tenant, member, service.portal_list_packages, UUID(friend["id"]), ListQuery())  # not theirs to act for
    off = _as(w.tenant, member, service.portal_disable_auto_renew, bought["id"])
    assert (off["is_auto_renew"], off["auto_renew_disabled_by"]) == (False, "client")
    assert _as(w.tenant, member, service.portal_disable_auto_renew, bought["id"])["version"] == off["version"]
    with at(date.fromisoformat(str(off["valid_until_on"]))), tx(w.tenant) as session:
        assert service.run_daily(session)["renewed"] == 0

    weekly = package_plan(client, owner, w.tenant, kind="recurring", recurrence_unit="week", recurrence_interval_count=1,
                          recurrence_occurrences_count=2, is_series_auto_renew=True, online_sale_mode="balance_allowed")  # fmt: skip
    series_id = _as(w.tenant, member, service.portal_buy, buy | {"package_plan_id": UUID(weekly["id"])}, "k-series")[
        "package_series_id"
    ]
    assert _as(w.tenant, member, service.portal_disable_series_auto_renew, series_id).is_auto_renew is False
    with pytest.raises(NotFound):
        _as(w.tenant, outsider, service.portal_disable_series_auto_renew, series_id)
    # over HTTP a staff token never reaches a portal view, and buying needs an Idempotency-Key
    assert client.get(f"{API}/portal/client-packages", headers=owner).status_code == 404
    assert client.get(f"{API}/portal/package-plans", headers=owner).status_code == 404
    public = ok(client.get(f"{API}/public/package-plans", headers={"X-Tenant-Slug": w.tenant.slug}))["data"]
    assert {p["id"]: p["is_purchasable"] for p in public} == {
        online["id"]: True,
        account["id"]: False,
        weekly["id"]: True,
    }
    assert (
        client.post(
            f"{API}/portal/client-packages",
            headers=owner,
            json={"package_plan_id": online["id"], "location_id": w.location_id},
        ).status_code
        == 422
    )


# --- permissions, merge, erasure ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "method", "path", "status"),
    [
        ("front_desk", "GET", "/client-packages", 200),
        ("front_desk", "POST", "/client-packages/quote", 422),
        ("front_desk", "POST", "/package-plans", 403),
        ("front_desk", "PATCH", "/client-packages/{id}", 403),
        ("front_desk", "POST", "/client-packages/{id}/credit-adjustments", 403),
        ("front_desk", "POST", "/client-packages/{id}/shares", 403),
        ("front_desk", "POST", "/client-packages/{id}/remove", 403),
        ("front_desk", "POST", "/client-packages/{id}/renew", 201),
        ("coach", "POST", "/client-packages/{id}/renew", 404),  # may sell, but at their own location only
        ("coach", "GET", "/client-packages/{id}", 404),  # own reach
        ("view_only", "GET", "/client-packages", 403),
        ("manager", "POST", "/client-packages/{id}/remove", 422),
        ("manager", "PATCH", "/package-settings", 200),
    ],
)
def test_router_gate_follows_the_matrix(client, tenant, owner, role, method, path, status):
    w = world(client, owner, tenant)
    plan = package_plan(client, owner, tenant)
    sold = ok(client.post(f"{API}/client-packages", headers=owner, json=pack(w, plan)), 201)
    elsewhere = world(client, owner, tenant).location_id
    email, _ = add_staff(tenant, role, location_ids=[elsewhere if role == "coach" else w.location_id])
    body = None if method == "GET" or path.endswith("renew") else {}
    response = client.request(
        method, f"{API}{path.format(id=sold['id'])}", headers=login(client, tenant, email), json=body
    )
    assert response.status_code == status, response.text


def test_service_gate_and_location_containment(w, client, owner):
    plan = package_plan(client, owner, w.tenant)
    sold = ok(client.post(f"{API}/client-packages", headers=owner, json=pack(w, plan)), 201)
    nobody = Principal(kind="staff", tenant_id=w.tenant.id, staff_user_id=uuid4(), permissions={}, location_ids=None)
    ids = {"client_id": UUID(w.person["id"]), "location_id": UUID(w.location_id), "package_plan_id": UUID(plan["id"])}
    calls = [
        lambda s: service.sell_package(s, nobody, ids),
        lambda s: service.grant_complimentary(s, nobody, ids),
        lambda s: service.quote_package(s, nobody, ids),
        lambda s: service.update_package(s, nobody, sold["id"], {}),
        lambda s: service.adjust_credits(s, nobody, sold["id"], {"delta": 1, "note": "x"}),
        lambda s: service.add_share(s, nobody, sold["id"], uuid4()),
        lambda s: service.remove_package(s, nobody, sold["id"], {"removal_mode": "billing_kept"}),
        lambda s: service.renew_package(s, nobody, sold["id"]),
        lambda s: service.create_plan(s, nobody, {}),
        lambda s: service.update_settings(s, nobody, {}),
        lambda s: service.get_package(s, nobody, sold["id"]),
        lambda s: service.list_plans(s, nobody, None),
    ]
    for call in calls:
        with pytest.raises(PermissionDenied), tx(w.tenant) as session:
            call(session)
    there = world(client, owner, w.tenant)
    manager_email, _ = add_staff(w.tenant, "manager", location_ids=[there.location_id])
    manager = login(client, w.tenant, manager_email)
    assert len(ok(client.get(f"{API}/client-packages", headers=manager))["data"]) == 1  # reads follow the client
    refused(
        client.patch(f"{API}/client-packages/{sold['id']}", headers=manager, json={"internal_remarks": "x"}),
        404,
        "not-found",
    )
    refused(client.post(f"{API}/client-packages", headers=manager, json=pack(w, plan)), 404, "not-found")
    assert client.post(f"{API}/client-packages", headers=manager, json=pack(there, plan)).status_code == 201


def test_merge_moves_packages_and_their_ledger_and_erasure_strips_free_text(w, client, owner):
    twin = new_client(client, owner, w.location_id, first_name=w.person["first_name"], last_name=w.person["last_name"])
    plan = package_plan(client, owner, w.tenant, session_count=3)
    theirs = ok(client.post(f"{API}/client-packages", headers=owner,
                            json=pack(w, plan, client_id=twin["id"], internal_remarks="Prefers mornings")), 201)  # fmt: skip
    ok(
        client.post(f"{API}/client-packages/{theirs['id']}/shares", headers=owner, json={"client_id": w.person["id"]}),
        201,
    )
    booking = uuid4()
    reserve(w.tenant, UUID(theirs["id"]), twin["id"], booking)
    ok(client.post(f"{API}/clients/{w.person['id']}/merge", headers=owner, json={"merged_client_ids": [twin["id"]]}))
    moved = package(w.tenant, theirs["id"])
    assert moved.owner_client_id == UUID(w.person["id"])
    assert {e.client_id for e in ledger(w.tenant, theirs["id"])} == {UUID(w.person["id"])}  # the append-only ledger too
    shares = ok(client.get(f"{API}/client-packages/{theirs['id']}/shares", headers=owner))
    assert [s["revoked_at"] is None for s in shares] == [False]  # a share with oneself ended
    assert settle(w.tenant, booking, "attended").client_id == UUID(w.person["id"])

    request = ok(client.post(f"{API}/data-subject-requests", headers=owner,
                             json={"client_id": w.person["id"], "kind": "erasure", "reason": "Asked by email"}), 201)  # fmt: skip
    done = ok(client.post(f"{API}/data-subject-requests/{request['id']}/confirm", headers=owner,
                          json={"confirmation": "ERASE", "is_blocker_override": True}))  # fmt: skip
    assert done["status"] == "completed"
    kept = package(w.tenant, theirs["id"])
    assert (kept.internal_remarks, kept.is_auto_renew, kept.sessions_consumed_count) == (
        None,
        False,
        1,
    )  # the record stays
    with tx(w.tenant) as session:
        assert service._export(session, UUID(w.person["id"]))["packages"][0]["sessions_consumed_count"] == 1


def test_expiring_packages_filter_uses_the_last_valid_day_and_skips_never_expiring(w, client, owner):
    month = package_plan(client, owner, w.tenant, validity_count=1, validity_unit="month")
    forever = package_plan(client, owner, w.tenant)
    a = sell_at(w, month, D(2025, 1, 10))  # last valid day 2025-02-09
    sell_at(w, forever, D(2025, 1, 10))

    def listed(day):
        page = ok(client.get(f"{API}/client-packages?expires_on_or_before={day}&status=active", headers=owner))
        return [p["id"] for p in page["data"]]

    assert listed("2025-02-08") == [] and listed("2025-02-09") == [str(a.id)]
    refused(client.get(f"{API}/client-packages?expires_on_or_before=soon", headers=owner), 422, "validation-failed")


def test_manager_override_reverses_billing_after_sessions_were_used(w, client, owner):
    """Question 16: reversing the billing of a used package needs packages.package.remove_override at its location
    and a reason, which the audit keeps; without either it stays 409 package-in-use / 403."""
    plan = package_plan(client, owner, w.tenant, session_count=4, fee_minor=8000)
    paid = {"payment": {"amount_minor": 8000, "tender_kind": "cash"}}
    used = ok(client.post(f"{API}/client-packages", headers=owner, json=pack(w, plan, **paid)), 201)
    person, attended = w.person["id"], uuid4()
    reserve(w.tenant, UUID(used["id"]), person, attended)
    settle(w.tenant, attended, "attended")
    url = f"{API}/client-packages/{used['id']}/remove"
    reverse = {"removal_mode": "billing_reversed", "override_reason": "Injured, refund agreed by manager"}

    email, user_id = add_staff(w.tenant, "manager", location_ids=[w.location_id])
    deny = {"grants": [{"permission_key": "packages.package.remove_override", "is_allowed": False}]}
    ok(client.put(f"{API}/staff-users/{user_id}/permission-overrides", headers=owner, json=deny))
    plain = login(client, w.tenant, email)
    quote = ok(client.post(f"{API}/client-packages/{used['id']}/removal-quote", headers=plain))
    assert (quote["can_reverse_billing"], quote["needs_override_reason"]) == (False, True)
    assert client.post(url, headers=plain, json=reverse).status_code == 403
    elsewhere = add_staff(w.tenant, "manager", location_ids=[location_of_other_site(client, owner)])[0]
    assert client.post(url, headers=login(client, w.tenant, elsewhere), json=reverse).status_code == 404
    refused(client.post(url, headers=owner, json={"removal_mode": "billing_reversed"}), 409, "package-in-use")
    assert client.post(url, headers=owner, json={**reverse, "override_reason": "  "}).status_code == 422
    assert package(w.tenant, UUID(used["id"])).status == "active"

    removed = ok(client.post(url, headers=owner, json=reverse))
    assert (removed["status"], removed["removal_mode"]) == ("removed", "billing_reversed")
    assert account_credit(w.tenant, person) == 8000 and open_balance(w.tenant, person) == 0
    reason = scalar(w.tenant, select(AuditEvent.reason).where(
        AuditEvent.entity_id == UUID(used["id"]), AuditEvent.action == "packages.package.remove"))  # fmt: skip
    assert reason == "Injured, refund agreed by manager"


def location_of_other_site(client, owner) -> str:
    body = {"name": f"Other {uuid4().hex[:6]}", "time_zone": "America/Chicago", "country_code": "US"}
    return ok(client.post(f"{API}/locations", headers=owner, json=body), 201)["id"]


def test_portal_quote_previews_an_online_purchase_for_whom_one_may_buy(w, client, owner):
    """portalQuoteClientPackage (SSP-08, PKG-09): the buy body, priced; desk-only plans and strangers refused."""
    stranger = new_client(client, owner, w.location_id)
    member = _member(w.tenant, w.person["id"])
    online = package_plan(client, owner, w.tenant, online_sale_mode="paid_in_full")
    desk_only = package_plan(client, owner, w.tenant)
    body = {"package_plan_id": UUID(online["id"]), "location_id": UUID(w.location_id)}

    quote = _as(w.tenant, member, service.portal_quote, body, None)
    assert (quote["sessions_granted_count"], quote["online_sale_mode"], quote["price_minor"] > 0) == (
        10, "paid_in_full", True,
    )  # fmt: skip
    assert scalar(w.tenant, select(func.count()).select_from(ClientPackage)) == 0  # a preview sells nothing
    with pytest.raises(ValidationFailed):
        _as(w.tenant, member, service.portal_quote, body | {"package_plan_id": UUID(desk_only["id"])}, None)
    with pytest.raises(NotFound):
        _as(w.tenant, member, service.portal_quote, body, UUID(stranger["id"]))


def test_a_staff_sale_that_died_is_finished_by_a_same_key_retry_of_the_same_sale(w, client, owner):
    """Each staff attempt raises a fresh invoice, so the payment key is bound to the sale, not the invoice: the same
    sale retried with the key finishes the first charge; another plan under the key is refused before the processor."""
    from app.modules import billing
    from app.modules.billing.tests.test_money import provider_payments

    plan, other = package_plan(client, owner, w.tenant), package_plan(client, owner, w.tenant)  # the same price
    with tx(w.tenant) as session:  # committed tender rows and processor account: the `initiated` row survives
        billing.service.ensure_defaults(session)
        billing.service._provider_account(session)
    key, card = f"k-{uuid4().hex}", {"amount_minor": 10000, "tender_kind": "card", "method_token": "tok_card_ok"}
    ids = lambda p: {"client_id": UUID(w.person["id"]), "location_id": UUID(w.location_id), "package_plan_id": UUID(p["id"])}  # noqa: E731  # fmt: skip
    sold = lambda: scalar(w.tenant, select(func.count()).select_from(ClientPackage))  # noqa: E731
    with pytest.raises(RuntimeError), tx(w.tenant) as session:
        service.sell(session, **ids(plan), payment=card, idempotency_key=key)
        raise RuntimeError("the request died before commit")
    with tx(w.tenant) as session:
        paid = service.sell(session, **ids(plan), payment=card, idempotency_key=key)["payment"].status
    assert (paid, sold(), provider_payments(w, key)) == ("succeeded", 1, 1)
    with pytest.raises(Conflict) as reused, tx(w.tenant) as session:
        service.sell(session, **ids(other), payment=card, idempotency_key=key)
    assert (reused.value.code, sold(), provider_payments(w, key)) == ("idempotency-key-reused", 1, 1)
