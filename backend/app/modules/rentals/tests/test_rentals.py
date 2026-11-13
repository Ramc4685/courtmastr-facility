"""rentals through the API on real PostgreSQL: setup, booking and billing (routing modes, idempotency),
the unbilled queue, cancellation settlement and late fees, handlers, online checkout with its hold, plans."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.auth import passwords, system_principal
from app.core.db.session import tenant_session
from app.core.events import OutboxEvent
from app.modules import billing, clients, scheduling
from app.modules.platform.models import Identity
from app.modules.rentals import handlers, service
from app.modules.rentals.models import RentalBookingCharge, RentalPlanLedgerEntry
from app.modules.scheduling.tests.helpers import API, DAY, at, drain, facility, ok
from conftest import PASSWORD, add_staff, login, new_client


@pytest.fixture
def f(client, owner, tenant):
    f = facility(client, owner)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        tax = billing.service.create_tax(
            session, code="ST", label="Tax", rate=Decimal("0.0825"), effective_from_on=DAY.date().replace(year=2020)
        )
        category = billing.service.create_revenue_category(session, code="RENT", label="Rentals", tax_ids=[tax.id])
        f.tax, f.category = str(tax.id), str(category.id)
    f.rtype = ok(client.post(f"{API}/rental-types", headers=owner, json={
        "location_id": f.location, "name": "Court hire", "revenue_category_id": f.category,
        "resource_ids": [f.court, f.court2], "buffer_after_min": 0,
    }))["id"]  # fmt: skip
    f.rate = ok(client.post(f"{API}/rental-types/{f.rtype}/rates", headers=owner, json={
        "name": "Standard", "amount_minor": 4000, "basis": "per_hour", "tax_ids": [f.tax],
        "rules": [{"kind": "rate", "name": "Evening", "start_time": "17:00", "end_time": "24:00", "amount_minor": 5000}],
    }))["id"]  # fmt: skip
    f.person = new_client(client, owner, f.location)["id"]
    return f


def rent(client, headers, f, start: float, end: float, charge: dict | None = None, **extra):
    body = {
        "location_id": f.location, "rental_type_id": f.rtype, "client_id": f.person,
        "resources": [{"resource_id": f.court}], "starts_at": at(start), "ends_at": at(end),
        "charge": charge or {"decision": "bill", "rental_rate_id": f.rate},
    } | extra  # fmt: skip
    return client.post(f"{API}/rentals", headers=headers | {"Idempotency-Key": f"rent-{uuid4().hex}"}, json=body)


def weekly(count: int) -> dict:
    return {"pattern": "weekly", "range_type": "count", "occurrence_limit": count}


def invoice(client, owner, invoice_id: str) -> dict:
    return ok(client.get(f"{API}/invoices/{invoice_id}", headers=owner), 200)


def test_types_and_rates(client, owner, f):
    patch = lambda body: client.patch(f"{API}/rental-types/{f.rtype}", headers=owner, json=body)  # noqa: E731
    assert patch({"access": "self_service"}).status_code == 422  # no online rate yet
    other = ok(client.post(f"{API}/rental-types", headers=owner, json={
        "location_id": f.location, "name": "Party room", "revenue_category_id": f.category,
    }))  # fmt: skip
    foreign = ok(client.post(f"{API}/rental-types/{other['id']}/rates", headers=owner, json={"name": "Flat", "amount_minor": 1, "basis": "flat"}))  # fmt: skip
    assert patch({"online_rental_rate_id": foreign["id"]}).status_code == 422
    opened = ok(patch({"access": "self_service", "online_rental_rate_id": f.rate, "deposit_pct": "25"}), 200)
    assert opened["access"] == "self_service" and set(opened["resource_ids"]) == {f.court, f.court2}
    off = client.patch(f"{API}/rental-rates/{f.rate}", headers=owner, json={"is_active": False})
    assert off.status_code == 422
    duplicate = client.post(f"{API}/rental-types", headers=owner, json={
        "location_id": f.location, "name": "Court hire", "revenue_category_id": f.category,
    })  # fmt: skip
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "already-exists"
    rate = ok(client.get(f"{API}/rental-rates/{f.rate}", headers=owner), 200)
    assert rate["tax_ids"] == [f.tax] and rate["rules"][0]["end_time"] == "24:00"
    bad = client.patch(f"{API}/rental-rates/{f.rate}", headers=owner, json={"rules": [{"kind": "discount"}]})
    assert bad.status_code == 422
    listed = ok(client.get(f"{API}/rental-types?location_id={f.location}", headers=owner), 200)["data"]
    assert {t["name"] for t in listed} == {"Court hire", "Party room"}
    assert len(ok(client.get(f"{API}/rental-types/{f.rtype}/rates", headers=owner), 200)["data"]) == 1


def test_book_and_bill_with_tax_band_split_and_replay(client, owner, f, tenant):
    body = {
        "location_id": f.location, "rental_type_id": f.rtype, "client_id": f.person,
        "resources": [{"resource_id": f.court}], "starts_at": at(21), "ends_at": at(23),  # 16:00-18:00 Chicago
        "charge": {"decision": "bill", "rental_rate_id": f.rate},
    }  # fmt: skip
    preview = ok(client.post(f"{API}/rentals/preview", headers=owner, json=body), 200)
    assert preview["conflict_count"] == 0 and preview["quote"]["subtotal_minor"] == 9000
    key = {"Idempotency-Key": f"rent-{uuid4().hex}"}
    created = ok(client.post(f"{API}/rentals", headers=owner | key, json=body))
    quote = created["quote"]
    assert [(line["unit_amount_minor"], line["amount_minor"]) for line in quote["lines"]] == [
        (5000, 5000),
        (4000, 4000),
    ]
    assert (quote["tax_minor"], quote["total_minor"]) == (330 + 413, 9743)
    rental = created["rental"]
    assert rental["charge_state"] == "billed" and rental["amount_minor"] == 9000 and len(rental["charge_ids"]) == 2
    assert created["invoice_ids"] == rental["invoice_ids"] and len(created["invoice_ids"]) == 1
    assert invoice(client, owner, created["invoice_ids"][0])["total_minor"] == 9743
    again = client.post(f"{API}/rentals", headers=owner | key, json=body)  # the same request replayed
    assert again.status_code == 201 and again.json()["rental"]["id"] == rental["id"]
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(RentalBookingCharge)) == 2
        # billing is idempotent by source too: posting a line again returns its charge
        rbc = session.scalars(select(RentalBookingCharge)).first()
        same = billing.service.post_charge(
            session, client_id=rbc.client_id, location_id=rbc.location_id, description="x", unit_price_minor=1,
            source_context="rentals", source_type="rental_booking_charge", source_id=rbc.id,
        )  # fmt: skip
        assert same.id == rbc.charge_id
    clash = rent(client, owner, f, 22, 23)
    assert clash.status_code == 409 and clash.json()["code"] == "booking-conflict"
    assert (
        ok(client.get(f"{API}/rentals/{rental['id']}", headers=owner), 200)["booking_number"]
        == rental["booking_number"]
    )


def test_routing_modes(client, owner, f):
    per_line = ok(rent(client, owner, f, 15, 16, {"decision": "bill", "rental_rate_id": f.rate, "line_grouping": "per_occurrence", "invoice_routing": "new_per_line"}, recurrence=weekly(3)))  # fmt: skip
    assert per_line["created_count"] == 3 and len(per_line["invoice_ids"]) == 3
    monthly = ok(rent(client, owner, f, 13, 14, {"decision": "bill", "rental_rate_id": f.rate, "line_grouping": "per_occurrence", "invoice_routing": "date_based", "routing_period": "month"}, recurrence=weekly(6)))  # fmt: skip
    assert monthly["created_count"] == 6 and len(monthly["invoice_ids"]) == 2  # four in May, two in June
    cart = ok(rent(client, owner, f, 17, 18, {"decision": "bill", "rental_rate_id": f.rate, "invoice_routing": "cart"}))
    assert cart["invoice_ids"] == [] and cart["rental"]["invoice_ids"] == []
    first = ok(rent(client, owner, f, 18, 19))
    onto = ok(rent(client, owner, f, 19, 20, {"decision": "bill", "rental_rate_id": f.rate, "invoice_routing": "existing_open", "existing_invoice_id": first["invoice_ids"][0]}))  # fmt: skip
    assert onto["invoice_ids"] == first["invoice_ids"]
    assert invoice(client, owner, first["invoice_ids"][0])["total_minor"] == 2 * 4330
    missing = rent(
        client, owner, f, 20, 21, {"decision": "bill", "rental_rate_id": f.rate, "invoice_routing": "date_based"}
    )
    assert missing.status_code == 422


def test_buffers_pad_the_held_range(client, owner, f):
    """RNT-07: the type's buffer (or the request's override) is held around the rental."""
    ok(client.patch(f"{API}/rental-types/{f.rtype}", headers=owner, json={"buffer_after_min": 30}), 200)
    ok(rent(client, owner, f, 14, 15, {"decision": "no_charge"}))
    inside = rent(client, owner, f, 15.25, 16, {"decision": "no_charge"})  # starts inside the 30-minute buffer
    assert inside.status_code == 409 and inside.json()["code"] == "booking-conflict"
    ok(rent(client, owner, f, 15.5, 16, {"decision": "no_charge"}, buffer_after_min=0))
    tight = rent(client, owner, f, 16, 17, {"decision": "no_charge"}, buffer_before_min=0)
    assert tight.status_code == 201  # the previous rental was booked with no buffer after


def test_unbilled_queue_and_bill_selected(client, owner, f):
    created = ok(rent(client, owner, f, 15, 16, {"decision": "unbilled"}, recurrence=weekly(3)))
    assert created["quote"] is None and created["rental"]["charge_state"] == "unbilled"
    queue = ok(client.get(f"{API}/rentals?charge_state=unbilled&client_id={f.person}", headers=owner), 200)["data"]
    assert len(queue) == 3
    ids = [r["id"] for r in queue]
    key = lambda: {"Idempotency-Key": f"bill-{uuid4().hex}"}  # noqa: E731
    charge = {"decision": "bill", "rental_rate_id": f.rate, "discount_minor": 1000}
    preview = ok(client.post(f"{API}/rentals/charges", headers=owner | key(), json={"rental_ids": ids, "charge": charge, "preview": True}), 200)  # fmt: skip
    assert preview["quote"]["subtotal_minor"] == 11000 and preview["invoice_ids"] == []
    billed = ok(
        client.post(f"{API}/rentals/charges", headers=owner | key(), json={"rental_ids": ids, "charge": charge}), 200
    )
    assert {r["charge_state"] for r in billed["rentals"]} == {"billed"} and len(billed["invoice_ids"]) == 1
    assert sum(r["amount_minor"] for r in billed["rentals"]) == 11000
    again = client.post(f"{API}/rentals/charges", headers=owner | key(), json={"rental_ids": ids, "charge": charge})
    assert again.status_code == 409 and again.json()["code"] == "rental-not-unbilled"
    assert ok(client.get(f"{API}/rentals?charge_state=unbilled", headers=owner), 200)["data"] == []
    free = ok(rent(client, owner, f, 18, 19, {"decision": "no_charge"}))
    assert free["rental"]["charge_state"] == "no_charge" and free["rental"]["charge_ids"] == []


def test_permissions_and_validation(client, owner, f, tenant):
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    custom = {
        "decision": "bill",
        "custom_rate": {"description": "Friends rate", "unit_amount_minor": 1000, "basis": "per_occurrence"},
    }
    denied = rent(client, desk, f, 15, 16, custom)
    assert denied.status_code == 403 and denied.json()["required"] == "rentals.booking.override_rate"
    assert ok(rent(client, owner, f, 15, 16, custom))["quote"]["subtotal_minor"] == 1000
    assert ok(rent(client, desk, f, 16, 17))["rental"]["charge_state"] == "billed"
    other = ok(client.post(f"{API}/rental-types", headers=owner, json={"location_id": f.location, "name": "Room", "revenue_category_id": f.category}))  # fmt: skip
    foreign = ok(client.post(f"{API}/rental-types/{other['id']}/rates", headers=owner, json={"name": "R", "amount_minor": 1, "basis": "flat"}))  # fmt: skip
    wrong = rent(client, owner, f, 18, 19, {"decision": "bill", "rental_rate_id": foreign["id"]})
    assert wrong.status_code == 422 and wrong.json()["code"] == "rate-not-applicable"
    lane = rent(client, owner, f, 18, 19, resources=[{"resource_id": f.coach}])
    assert lane.status_code == 422 and lane.json()["code"] == "resource-not-allowed"
    elsewhere = facility(client, owner, "America/Denver")
    stranger = login(client, tenant, add_staff(tenant, "manager", location_ids=[elsewhere.location])[0])
    rental = ok(rent(client, owner, f, 19, 20))["rental"]["id"]
    assert client.get(f"{API}/rentals/{rental}", headers=stranger).status_code == 404
    assert client.get(f"{API}/rental-types/{f.rtype}", headers=stranger).status_code == 404
    flag = client.put(f"{API}/rentals/{rental}/public-schedule", headers=desk, json={"is_on_public_schedule": True})
    assert flag.status_code == 403
    assert ok(client.put(f"{API}/rentals/{rental}/public-schedule", headers=owner, json={"is_on_public_schedule": True}), 200)["is_on_public_schedule"]  # fmt: skip


def test_cancel_settles_shares_of_a_combined_line(client, owner, f):
    created = ok(rent(client, owner, f, 15, 16, recurrence=weekly(3)))  # one combined line, 3 x 4000
    [invoice_id] = created["invoice_ids"]
    rentals = ok(client.get(f"{API}/rentals?booking_series_id={created['booking_series_id']}", headers=owner), 200)[
        "data"
    ]
    first, second, third = sorted(rentals, key=lambda r: r["starts_at"])
    result = ok(client.post(f"{API}/rentals/{second['id']}/cancel", headers=owner, json={}), 200)
    assert (result["cancelled_count"], result["reversed_minor"], result["reposted_minor"]) == (1, 12000, 8000)
    assert invoice(client, owner, invoice_id)["total_minor"] == 8660  # the remaining two shares plus their tax
    views = {r["id"]: r for r in ok(client.get(f"{API}/rentals?booking_series_id={created['booking_series_id']}", headers=owner), 200)["data"]}  # fmt: skip
    assert views[second["id"]]["status"] == "cancelled" and views[second["id"]]["amount_minor"] is None
    assert views[first["id"]]["amount_minor"] == views[third["id"]]["amount_minor"] == 4000
    assert ok(client.post(f"{API}/rentals/{second['id']}/cancel", headers=owner, json={}), 200)["cancelled_count"] == 0
    rest = ok(client.post(f"{API}/rentals/{first['id']}/cancel", headers=owner, json={"scope": {"mode": "all"}}), 200)
    assert (rest["cancelled_count"], rest["reversed_minor"], rest["reposted_minor"]) == (2, 12000, 4000)
    assert invoice(client, owner, invoice_id)["total_minor"] == 0


def test_late_fee_keep_charge_and_waiver(client, owner, f, tenant):
    flat = ok(client.post(f"{API}/rental-types/{f.rtype}/rates", headers=owner, json={"name": "Hour", "amount_minor": 4000, "basis": "per_occurrence"}))  # fmt: skip
    ok(client.patch(f"{API}/rental-types/{f.rtype}", headers=owner, json={"cancel_cutoff_hours": 48, "late_cancel_fee_pct": "50"}), 200)  # fmt: skip
    soon = clock.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
    hours = lambda d: (d - DAY).total_seconds() / 3600  # noqa: E731
    charge = {"decision": "bill", "rental_rate_id": flat["id"]}
    late = ok(rent(client, owner, f, hours(soon), hours(soon) + 1, charge))["rental"]["id"]
    result = ok(client.post(f"{API}/rentals/{late}/cancel", headers=owner, json={"reason": "client"}), 200)
    assert (result["reversed_minor"], result["late_fee_minor"]) == (4000, 2000)
    kept = ok(rent(client, owner, f, hours(soon) + 2, hours(soon) + 3, charge))["rental"]["id"]
    result = ok(client.post(f"{API}/rentals/{kept}/cancel", headers=owner, json={"charge_action": "keep_charge"}), 200)
    assert (result["reversed_minor"], result["late_fee_minor"]) == (0, 0)
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    waived = ok(rent(client, owner, f, hours(soon) + 4, hours(soon) + 5, charge))["rental"]["id"]
    assert client.post(f"{API}/rentals/{waived}/cancel", headers=desk, json={"waive_late_fee": True}).status_code == 403
    assert ok(client.post(f"{API}/rentals/{waived}/cancel", headers=owner, json={"waive_late_fee": True}), 200)["late_fee_minor"] == 0  # fmt: skip
    far = ok(rent(client, owner, f, 15, 16, charge))["rental"]["id"]  # 2031: far outside the cut-off
    assert ok(client.post(f"{API}/rentals/{far}/cancel", headers=owner, json={}), 200)["late_fee_minor"] == 0


def test_calendar_cancel_settles_through_the_handler(client, owner, f, tenant):
    rental = ok(rent(client, owner, f, 15, 16))["rental"]
    ok(
        client.post(
            f"{API}/bookings/{rental['booking_id']}/cancel", headers=owner, json={"version": rental["version"]}
        ),
        200,
    )
    with tenant_session(tenant.id) as session:
        event = session.execute(
            select(OutboxEvent).where(OutboxEvent.event_type == "scheduling.booking.cancelled")
        ).scalar_one()
    handlers.settle_cancelled_rental.send(str(tenant.id), str(event.id), event.payload)
    handlers.settle_cancelled_rental.send(str(tenant.id), str(event.id), event.payload)  # redelivered
    drain()
    view = ok(client.get(f"{API}/rentals/{rental['id']}", headers=owner), 200)
    assert view["cancelled_at"] is not None and view["amount_minor"] is None
    assert invoice(client, owner, rental["invoice_ids"][0])["total_minor"] == 0


def test_extend_a_recurring_rental(client, owner, f):
    created = ok(rent(client, owner, f, 15, 16, recurrence=weekly(2)))
    body = {"start_on": "2031-06-02", "start_time": "10:00", "end_time": "11:00", "rule": weekly(2)}
    extended = ok(client.post(f"{API}/rentals/{created['rental']['id']}/extensions", headers=owner, json=body))
    assert extended["created_count"] == 2
    rentals = ok(client.get(f"{API}/rentals?booking_series_id={created['booking_series_id']}", headers=owner), 200)[
        "data"
    ]
    assert sorted(r["charge_state"] for r in rentals) == ["billed", "billed", "unbilled", "unbilled"]
    single = ok(rent(client, owner, f, 18, 19))["rental"]["id"]
    refused = client.post(f"{API}/rentals/{single}/extensions", headers=owner, json=body)
    assert refused.status_code == 422 and refused.json()["code"] == "not-a-series"


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


def test_online_checkout_hold_payment_abandon_and_expiry(client, owner, f, tenant, monkeypatch):
    ok(client.patch(f"{API}/rental-types/{f.rtype}", headers=owner, json={
        "access": "self_service", "online_rental_rate_id": f.rate, "deposit_pct": "25", "slot_granularity_min": 30,
    }), 200)  # fmt: skip
    me, portal = portal_client(client, owner, tenant, f)
    public = {"X-Tenant-Slug": tenant.slug}
    [listed] = ok(client.get(f"{API}/public/rental-types", headers=public), 200)
    assert listed["from_price_minor"] == 4000 and {r["id"] for r in listed["resources"]} == {f.court, f.court2}
    slots = ok(client.get(f"{API}/public/rental-availability?rental_type_id={f.rtype}&on=2031-05-05&length_min=60&resource_id={f.court}", headers=public), 200)["data"]  # fmt: skip
    assert len(slots) == 31 and slots[0]["price_minor"] == 4000  # each half hour from 06:00 that fits an hour by 22:00
    body = {"rental_type_id": f.rtype, "client_id": me, "resource_id": f.court, "starts_at": at(15), "ends_at": at(16)}
    assert client.post(f"{API}/portal/rentals", headers=owner, json=body).status_code == 403
    off = client.post(
        f"{API}/portal/rentals", headers=portal, json=body | {"starts_at": at(15.25), "ends_at": at(16.25)}
    )
    assert off.status_code == 422 and off.json()["code"] == "off-grid"
    checkout = ok(client.post(f"{API}/portal/rentals", headers=portal, json=body))
    assert checkout["payment_required"] and checkout["rental"]["status"] == "tentative" and checkout["expires_at"]
    assert checkout["amount_due_minor"] == 1083  # 25% of 4330
    taken = ok(client.get(f"{API}/public/rental-availability?rental_type_id={f.rtype}&on=2031-05-05&resource_id={f.court}", headers=public), 200)["data"]  # fmt: skip
    assert len(taken) < len(slots)
    rental = checkout["rental"]["id"]

    def pay(token: str):
        key = {"Idempotency-Key": f"pay-{uuid4().hex}"}
        return client.post(
            f"{API}/portal/rentals/{rental}/confirm", headers=portal | key, json={"provider_payment_token": token}
        )

    declined = pay("tok_card_declined")
    assert declined.status_code == 409 and declined.json()["code"] == "payment-declined"
    paid = ok(pay("tok_card_ok"), 200)
    assert paid["rental"]["status"] == "confirmed" and paid["payment_status"] == "succeeded"
    assert invoice(client, owner, paid["invoice_id"])["status"] == "partially_paid"
    assert [r["id"] for r in ok(client.get(f"{API}/portal/rentals", headers=portal), 200)["data"]] == [rental]

    second = ok(
        client.post(f"{API}/portal/rentals", headers=portal, json=body | {"starts_at": at(17), "ends_at": at(18)})
    )
    assert client.post(f"{API}/portal/rentals/{second['rental']['id']}/abandon", headers=portal).status_code == 204
    gone = ok(client.get(f"{API}/rentals/{second['rental']['id']}", headers=owner), 200)
    assert gone["status"] == "cancelled" and gone["amount_minor"] is None

    third = ok(
        client.post(f"{API}/portal/rentals", headers=portal, json=body | {"starts_at": at(19), "ends_at": at(20)})
    )
    with (
        clock.freeze(clock.now() + timedelta(minutes=11)),
        tenant_session(tenant.id, actor=system_principal("tests")) as session,
    ):
        assert scheduling.service.expire_holds(session) == 1
    with tenant_session(tenant.id) as session:
        event = session.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "scheduling.booking.cancelled",
                OutboxEvent.payload["booking_id"].astext == third["rental"]["booking_id"],
            )
        ).scalar_one()
    handlers.settle_cancelled_rental.send(str(tenant.id), str(event.id), event.payload)
    drain()
    expired = ok(client.get(f"{API}/rentals/{third['rental']['id']}", headers=owner), 200)
    assert expired["status"] == "cancelled" and expired["cancelled_at"] and expired["amount_minor"] is None
    late = client.post(f"{API}/portal/rentals/{third['rental']['id']}/confirm", headers=portal | {"Idempotency-Key": f"pay-{uuid4().hex}"}, json={"provider_payment_token": "tok_card_ok"})  # fmt: skip
    assert late.status_code == 409 and late.json()["code"] == "hold-expired"
    cancelled = ok(client.post(f"{API}/portal/rentals/{rental}/cancel", headers=portal), 200)
    assert cancelled["cancelled_count"] == 1
    ok(client.patch(f"{API}/rental-types/{f.rtype}", headers=owner, json={"eligibility": "active_members"}), 200)
    members = client.post(f"{API}/portal/rentals", headers=portal, json=body | {"starts_at": at(21), "ends_at": at(22)})
    assert members.status_code == 422 and members.json()["code"] == "membership-required"
    assert members.json()["detail"] == "Online booking of this rental is for members."
    monkeypatch.setattr(service, "_is_member", lambda *a: True)  # a member books it online
    member = client.post(f"{API}/portal/rentals", headers=portal, json=body | {"starts_at": at(21), "ends_at": at(22)})
    assert member.status_code == 201, member.text


def test_rental_plans_full_coverage_credit_and_removal(client, owner, f, tenant):
    plan = ok(client.post(f"{API}/rental-plans", headers=owner, json={
        "location_id": f.location, "name": "Three hours", "rental_type_id": f.rtype, "model": "per_hour",
        "quantity": "3", "price_minor": 10000, "revenue_category_id": f.category,
    }))  # fmt: skip
    key = lambda: {"Idempotency-Key": f"plan-{uuid4().hex}"}  # noqa: E731
    purchase = ok(client.post(f"{API}/rental-plan-purchases", headers=owner | key(), json={"rental_plan_id": plan["id"], "client_id": f.person}))  # fmt: skip
    assert purchase["status"] == "active" and Decimal(purchase["balance"]) == 3 and purchase["invoice_id"]
    cover = {"decision": "plan", "rental_plan_purchase_id": purchase["id"]}
    covered = ok(rent(client, owner, f, 15, 17, cover))["rental"]
    assert covered["charge_state"] == "plan_covered"
    assert Decimal(ok(client.get(f"{API}/rental-plan-purchases/{purchase['id']}", headers=owner), 200)["balance"]) == 1
    short = rent(client, owner, f, 18, 20, cover)
    assert short.status_code == 409 and short.json()["code"] == "insufficient-plan-balance"
    assert [r["id"] for r in ok(client.get(f"{API}/rentals?client_id={f.person}", headers=owner), 200)["data"]] == [covered["id"]]  # fmt: skip
    back = ok(client.post(f"{API}/rentals/{covered['id']}/cancel", headers=owner, json={}), 200)
    assert Decimal(back["plan_quantity_returned"]) == 2
    ledger = ok(client.get(f"{API}/rental-plan-purchases/{purchase['id']}/ledger", headers=owner), 200)
    assert [(e["entry_type"], Decimal(e["balance_after"])) for e in ledger] == [
        ("grant", 3),
        ("debit", 1),
        ("credit", 3),
    ]
    other = ok(client.post(f"{API}/rental-types", headers=owner, json={"location_id": f.location, "name": "Room", "revenue_category_id": f.category, "resource_ids": [f.court2]}))  # fmt: skip
    wrong = client.post(f"{API}/rentals", headers=owner | key(), json={
        "location_id": f.location, "rental_type_id": other["id"], "client_id": f.person,
        "resources": [{"resource_id": f.court2}], "starts_at": at(15), "ends_at": at(16), "charge": cover,
    })  # fmt: skip
    assert wrong.status_code == 422 and wrong.json()["code"] == "plan-not-applicable"
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    removal = {"cancel_mode": "reverse_billing", "reason": "Changed mind"}
    assert (
        client.post(f"{API}/rental-plan-purchases/{purchase['id']}/cancel", headers=desk, json=removal).status_code
        == 403
    )
    removed = ok(client.post(f"{API}/rental-plan-purchases/{purchase['id']}/cancel", headers=owner, json=removal), 200)
    assert removed["status"] == "cancelled" and Decimal(removed["balance"]) == 0
    assert invoice(client, owner, purchase["invoice_id"])["total_minor"] == 0
    with tenant_session(tenant.id) as session:
        kinds = session.scalars(
            select(RentalPlanLedgerEntry.entry_type).where(
                RentalPlanLedgerEntry.rental_plan_purchase_id == UUID(purchase["id"])
            )
        ).all()
    assert sorted(kinds) == ["credit", "debit", "expire", "grant"]
    unlimited = ok(client.post(f"{API}/rental-plans", headers=owner, json={
        "location_id": f.location, "name": "Unlimited", "rental_type_id": f.rtype, "model": "per_occurrence",
        "is_unlimited": True, "price_minor": 0, "revenue_category_id": f.category,
    }))  # fmt: skip
    assert unlimited["quantity"] is None
    free = ok(client.post(f"{API}/rental-plan-purchases", headers=owner | key(), json={"rental_plan_id": unlimited["id"], "client_id": f.person}))  # fmt: skip
    assert free["balance"] is None and free["charge_id"] is None
    assert ok(rent(client, owner, f, 18, 23, {"decision": "plan", "rental_plan_purchase_id": free["id"]}))["rental"]["charge_state"] == "plan_covered"  # fmt: skip
    assert client.delete(f"{API}/rental-plans/{plan['id']}", headers=owner).status_code == 204
    assert ok(client.get(f"{API}/rental-plans/{plan['id']}", headers=owner), 200)["status"] == "archived"
    assert len(ok(client.get(f"{API}/rental-plan-purchases?client_id={f.person}", headers=owner), 200)["data"]) == 2
