"""Phase 14 C1 in rentals: locker leases (RNT-17, RNT-18, RES-08), plan sharing (RNT-10, FAM-06) and plan
auto-renew, autopay, members-only and the portal purchase (RNT-09)."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.auth import passwords, system_principal
from app.core.db.session import tenant_session
from app.modules import billing, clients, platform
from app.modules.platform.models import Identity
from app.modules.rentals import service
from app.modules.rentals.models import RentalPlanPurchase, RentalPlanShare
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import PASSWORD, add_staff, login, new_client


@pytest.fixture
def f(client, owner, tenant):
    f = facility(client, owner)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        f.category = str(billing.service.create_revenue_category(session, code="RENT", label="Rentals").id)
    f.rtype = ok(client.post(f"{API}/rental-types", headers=owner, json={
        "location_id": f.location, "name": "Court hire", "revenue_category_id": f.category, "resource_ids": [f.court],
    }))["id"]  # fmt: skip
    f.person = new_client(client, owner, f.location)["id"]
    room = ok(client.post(f"{API}/locker-rooms", headers=owner, json={"location_id": f.location, "name": "West"}))
    ok(client.post(f"{API}/locker-rooms/{room['id']}/lockers/bulk", headers=owner, json={"from_number": 1, "to_number": 2}))  # fmt: skip
    board = ok(client.get(f"{API}/lockers", headers=owner, params={"locker_room_id": room["id"]}), 200)["data"]
    f.room, (f.locker, f.locker2) = room["id"], [r["id"] for r in sorted(board, key=lambda r: r["number"])]
    return f


def lease(client, headers, f, locker=None, **body):
    return client.post(f"{API}/locker-leases", headers=headers,
                       json={"locker_id": locker or f.locker, "client_id": f.person} | body)  # fmt: skip


def board_state(client, owner, f, locker) -> dict:
    rows = ok(client.get(f"{API}/lockers", headers=owner, params={"locker_room_id": f.room}), 200)["data"]
    return next(r for r in rows if r["id"] == locker)


def test_lease_terms_billing_and_one_lease_per_locker(client, owner, f, tenant):
    term = ok(client.post(f"{API}/locker-terms", headers=owner, json={
        "location_id": f.location, "name": "Year", "starts_on": "2026-01-01", "ends_on": "2040-12-31", "price_minor": 6000,
    }))  # fmt: skip
    rented = ok(lease(client, owner, f, term_kind="term", locker_term_id=term["id"]))
    assert (rented["fee_minor"], rented["ends_on"], rented["state"]) == (6000, "2040-12-31", "rented")
    assert rented["charge_state"] == "billed" and rented["charge_id"]
    taken = lease(client, owner, f, term_kind="day")
    assert taken.status_code == 409 and taken.json()["code"] == "locker-already-rented"
    row = board_state(client, owner, f, f.locker)
    assert row["state"] == "rented" and row["client_id"] == f.person and row["locker_lease_id"] == rented["id"]
    retire = client.patch(f"{API}/lockers/{f.locker}", headers=owner, json={"status": "retired"})
    assert retire.status_code == 409 and retire.json()["code"] == "locker-leased"
    month = ok(lease(client, owner, f, f.locker2, term_kind="month", starts_on="2031-01-31"))
    assert (month["starts_on"], month["ends_on"], month["fee_minor"], month["charge_state"]) == (
        "2031-01-31", "2031-02-27", 0, "no_charge",
    )  # fmt: skip
    with tenant_session(tenant.id) as session:
        charge = session.get(billing.models.Charge, UUID(rented["charge_id"]))
        assert (charge.source_type, charge.total_minor) == ("locker_lease", 6000)
    ok(client.post(f"{API}/locker-leases/{month['id']}/clear", headers=owner), 200)
    assert lease(client, owner, f, f.locker2, term_kind="custom").status_code == 422  # custom needs an end


def test_fee_override_needs_its_own_key_and_term_must_be_current(client, owner, f, tenant):
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    assert lease(client, desk, f, term_kind="week", fee_minor=1500).status_code == 403
    keyed = ok(lease(client, owner, f, term_kind="week", fee_minor=1500, invoice_routing="cart"))
    assert keyed["fee_minor"] == 1500 and keyed["charge_state"] == "billed"
    ended = ok(client.post(f"{API}/locker-terms", headers=owner, json={
        "location_id": f.location, "name": "Old", "starts_on": "2020-01-01", "ends_on": "2020-06-30",
    }))  # fmt: skip
    late = lease(client, desk, f, f.locker2, term_kind="term", locker_term_id=ended["id"])
    assert late.status_code == 409 and late.json()["code"] == "term-ended"
    mixed = lease(client, desk, f, f.locker2, term_kind="day", locker_term_id=ended["id"])
    assert mixed.status_code == 422
    ok(client.patch(f"{API}/lockers/{f.locker2}", headers=owner, json={"status": "out_of_service"}), 200)
    out = lease(client, desk, f, f.locker2, term_kind="day")
    assert out.status_code == 409 and out.json()["code"] == "locker-unavailable"


def test_clear_renew_and_clear_expired(client, owner, f):
    lapsed = ok(lease(client, owner, f, term_kind="custom", starts_on="2020-01-01", ends_on="2020-01-31"))
    assert lapsed["state"] == "expired" and board_state(client, owner, f, f.locker)["state"] == "expired"
    renewed = ok(client.post(f"{API}/locker-leases/{lapsed['id']}/renew", headers=owner, json={"term_kind": "month"}))
    assert renewed["starts_on"] == "2020-02-01" and renewed["renewed_from_lease_id"] == lapsed["id"]
    again = client.post(f"{API}/locker-leases/{lapsed['id']}/renew", headers=owner, json={"term_kind": "month"})
    assert again.status_code == 409 and again.json()["code"] == "lease-cleared"
    ok(lease(client, owner, f, f.locker2, term_kind="custom", starts_on="2020-03-01", ends_on="2020-03-02"))
    swept = ok(client.post(f"{API}/locker-leases/clear-expired", headers=owner, json={"location_id": f.location, "locker_room_id": f.room}), 200)  # fmt: skip
    assert swept == {"cleared_count": 2}
    assert ok(client.post(f"{API}/locker-leases/clear-expired", headers=owner, json={"location_id": f.location}), 200) == {"cleared_count": 0}  # fmt: skip
    assert board_state(client, owner, f, f.locker)["state"] == "available"
    fresh = ok(lease(client, owner, f, term_kind="day"))
    cleared = ok(client.post(f"{API}/locker-leases/{fresh['id']}/clear", headers=owner), 200)
    assert cleared["state"] == "cleared" and cleared["clear_source"] == "staff"
    assert (
        ok(client.post(f"{API}/locker-leases/{fresh['id']}/clear", headers=owner), 200)["cleared_at"]
        == cleared["cleared_at"]
    )
    history = ok(
        client.get(f"{API}/locker-leases", headers=owner, params={"locker_id": f.locker, "is_open": "false"}), 200
    )
    assert {r["clear_source"] for r in history["data"]} == {"renewed", "bulk_expired", "staff"}
    assert ok(client.get(f"{API}/locker-leases", headers=owner, params={"is_open": "true"}), 200)["data"] == []


# --- plans -------------------------------------------------------------------------------------------------


def plan(client, owner, f, **extra) -> dict:
    return ok(client.post(f"{API}/rental-plans", headers=owner, json={
        "location_id": f.location, "name": f"Plan {uuid4().hex[:5]}", "rental_type_id": f.rtype, "model": "per_hour",
        "quantity": "5", "price_minor": 1000, "is_flat_rate": True, "revenue_category_id": f.category,
    } | extra))  # fmt: skip


def sell(client, owner, plan_id, client_id, **extra):
    return client.post(f"{API}/rental-plan-purchases", headers=owner | {"Idempotency-Key": f"sell-{uuid4().hex}"},
                       json={"rental_plan_id": plan_id, "client_id": client_id} | extra)  # fmt: skip


def relate(client, owner, f) -> str:
    kid = new_client(client, owner, f.location, first_name="Kit")["id"]
    parent_of = next(
        t for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200) if t["code"] == "parent_of"
    )
    ok(client.post(f"{API}/clients/{f.person}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": parent_of["id"]}))  # fmt: skip
    return kid


def test_share_with_related_clients_only(client, owner, f, tenant):
    kid = relate(client, owner, f)
    stranger = new_client(client, owner, f.location)["id"]
    closed = ok(sell(client, owner, plan(client, owner, f)["id"], f.person))
    refused = client.put(
        f"{API}/rental-plan-purchases/{closed['id']}/shares", headers=owner, json={"client_ids": [kid]}
    )
    assert refused.status_code == 409 and refused.json()["code"] == "plan-not-shareable"
    sellable = plan(client, owner, f, is_shareable=True)
    ok(client.patch(f"{API}/rental-types/{f.rtype}", headers=owner, json={"rental_plan_ids": [sellable["id"]]}), 200)
    bought = ok(sell(client, owner, sellable["id"], f.person))
    shares = f"{API}/rental-plan-purchases/{bought['id']}/shares"
    odd = client.put(shares, headers=owner, json={"client_ids": [stranger]})
    assert odd.status_code == 422 and odd.json()["code"] == "client-not-related"
    assert ok(client.put(shares, headers=owner, json={"client_ids": [kid]}), 200)["shared_with_client_ids"] == [kid]
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    assert client.put(shares, headers=desk, json={"client_ids": []}).status_code == 403
    covered = client.post(f"{API}/rentals", headers=owner | {"Idempotency-Key": f"r-{uuid4().hex}"}, json={
        "location_id": f.location, "rental_type_id": f.rtype, "client_id": kid, "resources": [{"resource_id": f.court}],
        "starts_at": "2031-05-05T15:00:00Z", "ends_at": "2031-05-05T16:00:00Z",
        "charge": {"decision": "plan", "rental_plan_purchase_id": bought["id"]},
    })  # fmt: skip
    assert covered.status_code == 201, covered.text
    assert ok(client.put(shares, headers=owner, json={"client_ids": []}), 200)["shared_with_client_ids"] == []
    with tenant_session(tenant.id) as session:
        revoked = session.scalars(select(RentalPlanShare).where(RentalPlanShare.client_id == UUID(kid))).one()
        assert revoked.revoked_at is not None


def test_auto_renew_autopay_and_day_roll(client, owner, f, tenant):
    kid = relate(client, owner, f)
    no_validity = ok(sell(client, owner, plan(client, owner, f)["id"], f.person))
    bad = client.patch(f"{API}/rental-plan-purchases/{no_validity['id']}", headers=owner, json={"is_auto_renew": True})
    assert bad.status_code == 422
    monthly = plan(client, owner, f, validity_days=30, is_auto_renew=True, is_autopay_default=True, is_shareable=True)
    assert (monthly["is_auto_renew"], monthly["is_autopay_default"]) == (True, True)
    bought = ok(sell(client, owner, monthly["id"], f.person))
    assert (bought["is_auto_renew"], bought["is_autopay"]) == (True, True)
    ok(client.put(f"{API}/rental-plan-purchases/{bought['id']}/shares", headers=owner, json={"client_ids": [kid]}), 200)
    on = ok(
        client.patch(f"{API}/rental-plan-purchases/{no_validity['id']}", headers=owner, json={"is_autopay": True}), 200
    )
    assert on["is_autopay"] is True
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        today = platform.service.location_today(session, UUID(f.location))
        assert service.run_plan_day(session)["renewed"] == 0  # nothing has lapsed yet
    with (
        clock.freeze(clock.now() + timedelta(days=31)),
        tenant_session(tenant.id, actor=system_principal("tests")) as session,
    ):
        assert service.run_plan_day(session) == {"activated": 0, "expired": 1, "renewed": 1}
        assert service.run_plan_day(session) == {"activated": 0, "expired": 0, "renewed": 0}  # idempotent
        successor = session.scalars(
            select(RentalPlanPurchase).where(RentalPlanPurchase.renewed_from_purchase_id == UUID(bought["id"]))
        ).one()
        assert successor.starts_on == today + timedelta(days=31) and successor.is_autopay  # lapsed: starts today
        assert service._shared_with(session, successor.id) == [UUID(kid)]


def portal_client(client, owner, tenant, f) -> tuple[str, dict]:
    person = new_client(client, owner, f.location, primary_email=f"pat-{uuid4().hex[:6]}@example.com")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(
            kind="client", email=person["primary_email"], status="active", email_verified_at=clock.now(),
            password_hash=passwords.hash_password(PASSWORD),
        )  # fmt: skip
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, person["id"], identity.id)
    return person["id"], login(client, tenant, person["primary_email"], audience="client")


def test_portal_purchase_members_only_and_opt_out(client, owner, f, tenant, monkeypatch):
    person, portal = portal_client(client, owner, tenant, f)
    open_plan = plan(
        client, owner, f, is_sold_online=True, validity_days=30, is_auto_renew=True, member_price_minor=600
    )
    members = plan(client, owner, f, is_sold_online=True, is_members_only=True)
    listed = {p["id"]: p for p in ok(client.get(f"{API}/portal/rental-plans", headers=portal), 200)["data"]}
    assert listed[open_plan["id"]]["price_minor"] == 1000 and listed[members["id"]]["is_purchasable"] is False

    def buy(body, key):
        return client.post(f"{API}/portal/rental-plan-purchases", headers=portal | {"Idempotency-Key": key}, json=body)

    refused = buy({"rental_plan_id": members["id"], "method_token": "tok_card_ok"}, f"k-{uuid4().hex}")
    assert refused.status_code == 422 and refused.json()["code"] == "membership-required"
    declined = buy({"rental_plan_id": open_plan["id"], "method_token": "tok_card_declined"}, f"k-{uuid4().hex}")
    assert declined.status_code >= 400, declined.text
    with tenant_session(tenant.id) as session:  # a failed payment sells nothing
        assert (
            session.scalars(select(RentalPlanPurchase).where(RentalPlanPurchase.client_id == UUID(person))).all() == []
        )
    key = f"k-{uuid4().hex}"
    bought = ok(buy({"rental_plan_id": open_plan["id"], "method_token": "tok_card_ok"}, key))
    assert bought["is_owner"] and bought["payment_status"]
    assert ok(client.get(f"{API}/rental-plan-purchases/{bought['id']}", headers=owner), 200)["price_minor"] == 1000
    assert ok(buy({"rental_plan_id": open_plan["id"], "method_token": "tok_card_ok"}, key))["id"] == bought["id"]
    mine = ok(client.get(f"{API}/portal/rental-plan-purchases", headers=portal), 200)["data"]
    assert [p["id"] for p in mine] == [bought["id"]] and mine[0]["is_auto_renew"]
    opted = ok(
        client.post(f"{API}/portal/rental-plan-purchases/{bought['id']}/auto-renew-opt-out", headers=portal), 200
    )
    assert opted["is_auto_renew"] is False
    staff_side = client.post(f"{API}/portal/rental-plan-purchases/{bought['id']}/auto-renew-opt-out", headers=owner)
    assert staff_side.status_code == 404
    monkeypatch.setattr(service, "_is_member", lambda *a: True)
    assert ok(buy({"rental_plan_id": members["id"], "method_token": "tok_card_ok"}, f"k-{uuid4().hex}"))["is_owner"]
    discounted = ok(sell(client, owner, open_plan["id"], f.person))
    assert discounted["price_minor"] == 600 and Decimal(discounted["balance"]) == 5  # members pay the member price
