"""Pilot rules for court rentals: member prices that agree between quote and charge (one pricing path for
staff, portal and recurring rentals), and the minors rule (a minor never holds a rental; a guardian books and
names the children who play)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import billing
from app.modules.memberships.tests.support import membership_plan
from app.modules.programs.tests.test_selfservice import SOON, policy
from app.modules.rentals.tests.test_rentals import portal_client
from app.modules.scheduling.tests.helpers import API, DAY, at, book, facility, ok
from conftest import add_staff, login, new_client

CHILD = "2021-03-01"  # ten in 2031
RECURRING = {"pattern": "weekly", "range_type": "count", "occurrence_limit": 3}


@pytest.fixture
def f(client, owner, tenant):
    """Badminton by the hour in Chicago: guest $24, member $20; prime 18:00-22:00 guest $30, member $25."""
    f = facility(client, owner)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        f.category = str(billing.service.create_revenue_category(session, code="CRT", label="Courts").id)
    f.plan = membership_plan(client, owner, tenant)
    f.mtype = f.plan["membership_type_id"]
    f.rtype = ok(client.post(f"{API}/rental-types", headers=owner, json={
        "location_id": f.location, "name": "Badminton", "revenue_category_id": f.category,
        "resource_ids": [f.court, f.court2], "buffer_after_min": 0,
    }))["id"]  # fmt: skip
    f.rate = ok(client.post(f"{API}/rental-types/{f.rtype}/rates", headers=owner, json={
        "name": "Hourly", "amount_minor": 2400, "member_amount_minor": 2000, "basis": "per_hour",
        "rules": [
            {"kind": "rate", "name": "Member prime", "start_time": "18:00", "end_time": "22:00",
             "membership_type_id": f.mtype, "amount_minor": 2500},
            {"kind": "rate", "name": "Prime", "start_time": "18:00", "end_time": "22:00", "amount_minor": 3000},
        ],
    }))["id"]  # fmt: skip
    ok(client.patch(f"{API}/rental-types/{f.rtype}", headers=owner, json={
        "access": "self_service", "online_rental_rate_id": f.rate, "slot_granularity_min": 60,
    }), 200)  # fmt: skip
    f.guest = new_client(client, owner, f.location)["id"]
    f.member = new_client(client, owner, f.location)["id"]
    f.contract = join(client, owner, f, f.member, DAY - timedelta(days=10))
    return f


def join(client, owner, f, client_id: str, start, plan: dict | None = None) -> str:
    body = {"client_id": client_id, "location_id": f.location, "membership_plan_id": (plan or f.plan)["id"],
            "start_on": start.date().isoformat()}  # fmt: skip
    return ok(client.post(f"{API}/membership-contracts", headers=owner, json=body))["id"]


def body(f, who: str, start: float, end: float, **extra) -> dict:
    return {
        "location_id": f.location, "rental_type_id": f.rtype, "client_id": who,
        "resources": [{"resource_id": f.court}], "starts_at": at(start), "ends_at": at(end),
        "charge": {"decision": "bill", "rental_rate_id": f.rate},
    } | extra  # fmt: skip


def rent(client, headers, payload: dict):
    return client.post(f"{API}/rentals", headers=headers | {"Idempotency-Key": f"r-{uuid4().hex}"}, json=payload)


def starting(slots: list[dict], hour: float) -> dict:
    return next(s for s in slots if datetime.fromisoformat(s["starts_at"]) == datetime.fromisoformat(at(hour)))


def units(quote: dict) -> list[int]:
    return [line["unit_amount_minor"] for line in quote["lines"]]


# 15 = 10:00, 22 = 17:00, 23 = 18:00 and 24 = 19:00 in Chicago on DAY (CDT, UTC-5).


def test_member_and_guest_rates_per_band_quote_equals_charge(client, owner, f):
    for who, expected, subtotal in ((f.member, [2000, 2500], 4500), (f.guest, [2400, 3000], 5400)):
        payload = body(f, who, 22, 24)  # straddles 18:00: one line per band, each half-up once
        preview = ok(client.post(f"{API}/rentals/preview", headers=owner, json=payload), 200)["quote"]
        created = ok(rent(client, owner, payload))
        assert sorted(units(preview)) == sorted(units(created["quote"])) == expected
        assert preview["subtotal_minor"] == created["quote"]["subtotal_minor"] == subtotal
        assert created["rental"]["amount_minor"] == subtotal
        assert all(line["is_member_price"] is (who == f.member) for line in created["quote"]["lines"])
        ok(client.post(f"{API}/rentals/{created['rental']['id']}/cancel", headers=owner, json={}), 200)


def test_recurring_rental_prices_each_occurrence_on_its_own_date(client, owner, f, tenant):
    short = membership_plan(client, owner, tenant, billing_occurrences_count=1)  # one month: Apr 15 to May 14
    lapsing = new_client(client, owner, f.location)["id"]
    join(client, owner, f, lapsing, DAY - timedelta(days=20), short)
    created = ok(rent(client, owner, body(f, lapsing, 15, 16, recurrence=RECURRING)))
    assert sorted(units(created["quote"])) == [2000, 2400]  # two member weeks on one line, the lapsed week on another
    assert created["quote"]["subtotal_minor"] == 2000 * 2 + 2400


def test_bill_selected_prices_the_payer_as_a_member(client, owner, f):
    unbilled = ok(rent(client, owner, body(f, f.member, 23, 24, charge={"decision": "unbilled"})))["rental"]
    billed = ok(client.post(f"{API}/rentals/charges", headers=owner | {"Idempotency-Key": uuid4().hex}, json={
        "rental_ids": [unbilled["id"]], "charge": {"decision": "bill", "rental_rate_id": f.rate},
    }), 200)  # fmt: skip
    assert billed["quote"]["subtotal_minor"] == 2500


def test_a_moved_rental_keeps_its_price(client, owner, f):
    rental = ok(rent(client, owner, body(f, f.member, 15, 16)))["rental"]
    booking = ok(client.get(f"{API}/bookings/{rental['booking_id']}", headers=owner), 200)
    moved = {"starts_at": at(24), "ends_at": at(25), "version": booking["version"]}
    ok(client.post(f"{API}/bookings/{rental['booking_id']}/reschedule", headers=owner, json=moved), 200)
    assert ok(client.get(f"{API}/rentals/{rental['id']}", headers=owner), 200)["amount_minor"] == 2000


def online(f, who: str, start: float, end: float) -> dict:
    return {"rental_type_id": f.rtype, "client_id": who, "resource_id": f.court, "starts_at": at(start),
            "ends_at": at(end)}  # fmt: skip


def portal_member(client, owner, tenant, f) -> tuple[str, dict]:
    me, portal = portal_client(client, owner, tenant, f)
    join(client, owner, f, me, DAY - timedelta(days=10))
    return me, portal


def test_portal_quotes_and_charges_the_member_price(client, owner, tenant, f):
    me, portal = portal_member(client, owner, tenant, f)
    query = f"rental_type_id={f.rtype}&on=2031-05-05&length_min=60&resource_id={f.court}"
    public = ok(client.get(f"{API}/public/rental-availability?{query}", headers={"X-Tenant-Slug": tenant.slug}), 200)
    mine = ok(client.get(f"{API}/portal/rental-availability?{query}&client_id={me}", headers=portal), 200)
    price = lambda slots, hour: starting(slots["data"], hour)  # noqa: E731
    assert (price(public, 15)["price_minor"], price(public, 23)["price_minor"]) == (2400, 3000)
    assert (price(mine, 15)["price_minor"], price(mine, 23)["price_minor"]) == (2000, 2500)
    assert price(mine, 23)["is_member_price"] and not price(public, 23)["is_member_price"]
    checkout = ok(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 23, 24)))
    assert checkout["quote"]["subtotal_minor"] == price(mine, 23)["price_minor"]
    stranger = new_client(client, owner, f.location)["id"]
    assert (
        client.get(f"{API}/portal/rental-availability?{query}&client_id={stranger}", headers=portal).status_code == 404
    )


def test_a_membership_that_lapses_after_the_quote_the_charge_wins(client, owner, tenant, f):
    me, portal = portal_client(client, owner, tenant, f)
    contract = join(client, owner, f, me, datetime.now(UTC))  # active today, so it can be suspended
    ten = SOON + timedelta(hours=16)  # 10:00 in Chicago (CST) three days ahead
    query = f"rental_type_id={f.rtype}&on={SOON.date()}&length_min=60&resource_id={f.court}&client_id={me}"
    slots = ok(client.get(f"{API}/portal/rental-availability?{query}", headers=portal), 200)["data"]
    quoted = next(s for s in slots if datetime.fromisoformat(s["starts_at"]) == ten)
    assert quoted["price_minor"] == 2000 and quoted["is_member_price"]
    ok(client.post(f"{API}/membership-contracts/{contract}/suspensions", headers=owner, json={"remarks": "Paused"}))
    request = online(f, me, 0, 1) | {"starts_at": ten.isoformat(), "ends_at": (ten + timedelta(hours=1)).isoformat()}
    checkout = ok(client.post(f"{API}/portal/rentals", headers=portal, json=request))
    assert checkout["quote"]["subtotal_minor"] == 2400  # the guest price, shown on the checkout before paying
    assert not checkout["quote"]["lines"][0]["is_member_price"]


# --- the minors rule ---------------------------------------------------------------------------------------------


def family(client, owner, f) -> tuple[str, str]:
    parent = new_client(client, owner, f.location, first_name="Pat")["id"]
    kid = new_client(client, owner, f.location, first_name="Kit", birth_on=CHILD)["id"]
    parent_of = next(
        t for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200) if t["code"] == "parent_of"
    )
    ok(client.post(f"{API}/clients/{parent}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": parent_of["id"]}))  # fmt: skip
    return parent, kid


def refused(response, status: int, code: str) -> None:
    assert (response.status_code, response.json().get("code")) == (status, code), response.text


def test_a_minor_cannot_hold_a_rental_and_override_needs_the_key_and_a_reason(client, owner, tenant, f):
    _, kid = family(client, owner, f)
    refused(rent(client, owner, body(f, kid, 15, 16)), 422, "minor-cannot-hold-rental")
    refused(client.post(f"{API}/rentals/preview", headers=owner, json=body(f, kid, 15, 16)), 422,
            "minor-cannot-hold-rental")  # fmt: skip
    desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    assert rent(client, desk, body(f, kid, 15, 16, minor_override_reason="Coach's own child")).status_code == 403
    allowed = ok(rent(client, owner, body(f, kid, 15, 16, minor_override_reason="Coach's own child")))
    with tenant_session(tenant.id) as session:
        record = session.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == allowed["rental"]["id"]).order_by(AuditEvent.id.desc())
        ).first()
    assert record.changes["minor_override_reason"] is True  # free text is flag-only


def test_a_guardian_books_and_names_the_children_who_play(client, owner, f):
    parent, kid = family(client, owner, f)
    party = [{"client_id": kid}]
    created = ok(rent(client, owner, body(f, parent, 15, 16, parties=party)))
    assert created["rental"]["parties"] == [{"client_id": kid, "is_charged": False}]
    refused(rent(client, owner, body(f, f.guest, 16, 17, parties=party)), 422, "minor-needs-guardian")
    refused(rent(client, owner, body(f, parent, 17, 18, parties=[{"client_id": kid, "is_charged": True}])), 422,
            "minor-needs-guardian")  # fmt: skip
    unknown = new_client(client, owner, f.location)["id"]  # no birth date: treated as an adult (ADR 0002 section 5)
    ok(rent(client, owner, body(f, unknown, 18, 19)))


def test_the_minor_age_is_the_tenant_setting(client, owner, f):
    _, kid = family(client, owner, f)
    ok(client.patch(f"{API}/tenant", headers=owner, json={"settings": {"minor_age": 8}}), 200)
    ok(rent(client, owner, body(f, kid, 15, 16)))


def test_portal_parent_books_in_own_name_with_the_child_playing(client, owner, tenant, f):
    me, portal = portal_client(client, owner, tenant, f)
    kid = new_client(client, owner, f.location, first_name="Kit", birth_on=CHILD)["id"]
    parent_of = next(
        t for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200) if t["code"] == "parent_of"
    )
    ok(client.post(f"{API}/clients/{me}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": parent_of["id"]}))  # fmt: skip
    checkout = ok(client.post(f"{API}/portal/rentals", headers=portal,
                              json=online(f, me, 15, 16) | {"player_client_ids": [kid]}))  # fmt: skip
    staff_view = ok(client.get(f"{API}/rentals/{checkout['rental']['id']}", headers=owner), 200)
    assert staff_view["parties"] == [{"client_id": kid, "is_charged": False}]
    assert "parties" not in checkout["rental"]  # the portal view carries no co-party ids (S-06)
    stranger = new_client(client, owner, f.location)["id"]
    assert client.post(f"{API}/portal/rentals", headers=portal,
                       json=online(f, me, 16, 17) | {"player_client_ids": [stranger]}).status_code == 404  # fmt: skip


def test_coaching_keeps_its_rules_a_parent_registers_a_child(client, owner, tenant, f):
    """Sessions are not rentals: a parent may still register a child alone (dropped off at coaching)."""
    policy(client, owner, f)
    seat = ok(book(client, owner, f, [f.coach], at(13, SOON), at(14, SOON), kind="session"))["booking"]["session"]
    me, portal = portal_client(client, owner, tenant, f)
    kid = new_client(client, owner, f.location, first_name="Kit", birth_on=CHILD)["id"]
    parent_of = next(
        t for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200) if t["code"] == "parent_of"
    )
    ok(client.post(f"{API}/clients/{me}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": parent_of["id"]}))  # fmt: skip
    enrolled = ok(client.post(f"{API}/portal/enrollments", headers=portal,
                              json={"client_id": kid, "session_id": seat["id"]}))  # fmt: skip
    assert enrolled["client_id"] == kid and enrolled["status"] == "enrolled"
