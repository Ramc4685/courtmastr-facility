"""Post-billed packages (PKG-11) and the period close that bills them (BIL-18): tiered rates, usage up to the
closing date, one charge and invoice per package, idempotency per period, skipped lines and the gate."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.modules import billing
from app.modules.memberships.tests.support import API, at, category, charges, invoices, location, ok, refused, tx
from app.modules.packages import service
from app.modules.packages.models import ClientPackage
from conftest import add_staff, login, new_client

DAY = date(2025, 3, 3)  # in the past: a frozen clock past the sign-in would expire the session


@pytest.fixture
def w(client, owner, tenant):
    site = location(client, owner)
    rtype = ok(
        client.post(f"{API}/reservation-types", headers=owner, json={"location_id": site, "name": "Lesson"}), 201
    )
    return SimpleNamespace(
        tenant=tenant, owner=owner, location_id=site, type_id=rtype["id"], person=new_client(client, owner, site),
        category_id=category(tenant, "LESS"),
    )  # fmt: skip


def rate(client, w, min_sessions: int, minor: int) -> dict:
    body = {"reservation_type_id": w.type_id, "min_sessions": min_sessions, "per_session_minor": minor,
            "revenue_category_id": w.category_id}  # fmt: skip
    return ok(client.post(f"{API}/post-billed-rates", headers=w.owner, json=body), 201)


def open_package(client, w, **fields) -> dict:
    body = {"client_id": w.person["id"], "location_id": w.location_id, "reservation_type_id": w.type_id} | fields
    with at(DAY):
        return ok(client.post(f"{API}/client-packages/post-billed", headers=w.owner, json=body), 201)


def use(w, package: dict, day: date, *, settle: bool = True) -> dict:
    """One session paid by the package: a credit reserved for a booking, then consumed by attending."""
    source = {"source_type": "booking", "source_id": uuid4()}
    with at(day), tx(w.tenant) as session:
        service.reserve_credit(session, client_package_id=UUID(package["id"]), client_id=UUID(w.person["id"]),
                               session_on=day, reservation_type_id=UUID(w.type_id), **source)  # fmt: skip
        if settle:
            service.settle_credit(session, outcome="attended", **source)
    return source


def close(client, w, day: date, path: str = "", headers=None):
    with at(day):
        return client.post(f"{API}/post-billed-closes{path}", headers=headers or w.owner,
                           json={"location_id": w.location_id, "closing_on": day.isoformat()})  # fmt: skip


def test_close_bills_used_sessions_at_the_tier_reached_once_per_period(client, w):
    rate(client, w, 1, 2000)
    rate(client, w, 3, 1500)
    package = open_package(client, w)
    assert package["billing_mode"] == "post_billed" and package["price_minor"] == 0 and package["is_unlimited"]
    assert charges(w.tenant, w.person["id"]) == []  # nothing is charged at the sale
    for _ in range(3):
        use(w, package, DAY)
    use(w, package, DAY, settle=False)  # still reserved: billed once it is consumed

    [line] = ok(close(client, w, DAY, "/preview"), 200)["lines"]
    assert (line["session_count"], line["per_session_minor"], line["total_minor"], line["unsettled_count"]) == (
        3, 1500, 4500, 1)  # fmt: skip
    done = ok(close(client, w, DAY), 201)
    assert (done["package_count"], done["session_count"], done["total_minor"]) == (1, 3, 4500)
    [billed] = done["lines"]
    [charge] = charges(w.tenant, w.person["id"])
    assert (charge.id, charge.quantity, charge.unit_price_minor) == (UUID(billed["charge_id"]), 3, 1500)
    assert [i.id for i in invoices(w.tenant, w.person["id"])] == [UUID(billed["invoice_id"])]

    assert ok(close(client, w, DAY), 201)["id"] == done["id"]  # idempotent per location and date
    assert len(charges(w.tenant, w.person["id"])) == 1
    assert ok(close(client, w, DAY, "/preview"), 200)["post_billed_close_id"] == done["id"]
    listed = ok(client.get(f"{API}/post-billed-closes?location_id={w.location_id}", headers=w.owner), 200)["data"]
    assert [c["id"] for c in listed] == [done["id"]]


def test_already_billed_usage_is_not_billed_again_and_lone_sessions_use_the_base_tier(client, w):
    rate(client, w, 1, 2000)
    rate(client, w, 3, 1500)
    package = open_package(client, w)
    use(w, package, DAY)
    ok(close(client, w, DAY), 201)
    later = DAY + timedelta(days=7)
    [skipped] = ok(close(client, w, later, "/preview"), 200)["lines"]
    assert skipped["skipped_reason"] == "no-usage" and skipped["total_minor"] == 0
    use(w, package, later)
    second = ok(close(client, w, later), 201)
    assert (second["session_count"], second["total_minor"]) == (1, 2000)


def test_a_package_without_auto_renew_ends_at_its_close(client, w):
    rate(client, w, 1, 1000)
    package = open_package(client, w, is_auto_renew=False)
    use(w, package, DAY)
    ok(close(client, w, DAY), 201)
    with tx(w.tenant) as session:
        assert session.get(ClientPackage, UUID(package["id"])).status == "expired"


def test_late_usage_after_a_package_ended_is_billed_exactly_once(client, w):
    rate(client, w, 1, 1000)
    package = open_package(client, w, is_auto_renew=False)
    use(w, package, DAY)
    held = use(w, package, DAY, settle=False)  # booked before the close, attended after it
    first = ok(close(client, w, DAY), 201)
    assert (first["session_count"], first["total_minor"]) == (1, 1000)
    with tx(w.tenant) as session:
        assert session.get(ClientPackage, UUID(package["id"])).status == "active"  # a credit is still held
    later = DAY + timedelta(days=2)
    with at(later), tx(w.tenant) as session:
        service.settle_credit(session, outcome="attended", **held)
    second = ok(close(client, w, later), 201)
    assert (second["session_count"], second["total_minor"]) == (1, 1000)
    with tx(w.tenant) as session:
        assert session.get(ClientPackage, UUID(package["id"])).status == "expired"
    third = ok(close(client, w, later + timedelta(days=1)), 201)
    assert third["package_count"] == 0  # billed once: nothing left for a later close
    assert sorted(c.total_minor for c in charges(w.tenant, w.person["id"])) == [1000, 1000]


def test_a_close_covers_every_package_of_its_period(client, w):
    rate(client, w, 1, 1000)
    with at(DAY):  # no partial closes: a package filter would let one close block the rest of the period
        partial = client.post(f"{API}/post-billed-closes", headers=w.owner, json={
            "location_id": w.location_id, "closing_on": DAY.isoformat(), "client_package_ids": [str(uuid4())]})  # fmt: skip
    refused(partial, 422, "validation-failed")


def billed_sessions(w) -> int:
    return sum(c.quantity for c in charges(w.tenant, w.person["id"]) if c.status != "reversed" and c.total_minor > 0)


def test_renewal_keeps_a_package_post_billed_by_route_and_by_job(client, w):
    rate(client, w, 1, 1000)
    package = open_package(client, w)
    with at(DAY):
        renewed = ok(client.post(f"{API}/client-packages/{package['id']}/renew", headers=w.owner), 201)
    assert (renewed["billing_mode"], renewed["price_minor"]) == ("post_billed", 0)
    use(w, renewed, DAY)
    assert ok(close(client, w, DAY), 201)["session_count"] == 1

    other = open_package(client, w)
    with at(DAY), tx(w.tenant) as session:
        session.get(ClientPackage, UUID(other["id"])).renew_on = DAY
        session.get(ClientPackage, UUID(other["id"])).is_auto_renew = True
        session.flush()
        assert service.run_daily(session)["renewed"] == 1
        successor = session.scalar(select(ClientPackage).where(ClientPackage.previous_package_id == UUID(other["id"])))
        assert successor.billing_mode == "post_billed" and successor.price_minor == 0


def test_a_package_ends_only_once_nothing_is_held_or_dated_after_the_close(client, w):
    rate(client, w, 1, 1000)
    package = open_package(client, w, is_auto_renew=False)
    ends = DAY + timedelta(days=28)
    use(w, package, ends - timedelta(days=1))
    use(w, package, ends + timedelta(days=1))  # used after the closing date, before the close runs
    use(w, package, ends + timedelta(days=2))
    with at(ends + timedelta(days=3)):
        first = ok(client.post(f"{API}/post-billed-closes", headers=w.owner,
                               json={"location_id": w.location_id, "closing_on": ends.isoformat()}), 201)  # fmt: skip
    assert first["session_count"] == 1
    with tx(w.tenant) as session:
        assert session.get(ClientPackage, UUID(package["id"])).status == "active"  # later usage still to bill
    assert ok(close(client, w, ends + timedelta(days=3)), 201)["session_count"] == 2
    with tx(w.tenant) as session:
        assert session.get(ClientPackage, UUID(package["id"])).status == "expired"
    assert billed_sessions(w) == 3


def test_usage_of_a_package_removed_between_closes_is_still_billed(client, w):
    rate(client, w, 1, 1000)
    package = open_package(client, w)
    use(w, package, DAY)
    with tx(w.tenant) as session:
        removed = session.get(ClientPackage, UUID(package["id"]))
        removed.status, removed.removed_at = "removed", datetime.now(UTC)
    assert ok(close(client, w, DAY), 201)["session_count"] == 1
    assert ok(close(client, w, DAY + timedelta(days=1)), 201)["package_count"] == 0


def test_a_credit_restored_after_billing_is_credited_at_the_next_close(client, w):
    rate(client, w, 1, 1000)
    package = open_package(client, w)
    use(w, package, DAY)
    restored = use(w, package, DAY)
    ok(close(client, w, DAY), 201)
    assert billed_sessions(w) == 2
    with at(DAY), tx(w.tenant) as session:  # staff reverse the attendance: the credit goes back
        service.restore_credit(session, **restored)
    later = DAY + timedelta(days=1)
    ok(close(client, w, later), 201)
    assert billed_sessions(w) == 1
    ok(close(client, w, later + timedelta(days=1)), 201)
    assert billed_sessions(w) == 1  # credited once


def test_the_rate_table_always_starts_at_one_session(client, w):
    body = {"reservation_type_id": w.type_id, "min_sessions": 3, "per_session_minor": 900}
    refused(client.post(f"{API}/post-billed-rates", headers=w.owner, json=body), 422, "validation-failed")
    base = rate(client, w, 1, 1000)
    ok(client.post(f"{API}/post-billed-rates", headers=w.owner, json=body), 201)
    refused(client.patch(f"{API}/post-billed-rates/{base['id']}", headers=w.owner, json={"is_active": False}),
            422, "validation-failed")  # fmt: skip
    refused(client.patch(f"{API}/post-billed-rates/{base['id']}", headers=w.owner, json={"min_sessions": 2}),
            422, "validation-failed")  # fmt: skip


def test_one_failing_package_does_not_stop_the_close(client, w, monkeypatch):
    rate(client, w, 1, 1000)
    good, bad = open_package(client, w), open_package(client, w, name="Second")
    use(w, good, DAY)
    use(w, bad, DAY)
    real = billing.service.post_charge

    def flaky(session, **kwargs):
        if kwargs["description"].startswith("Second"):
            raise ValidationFailed("No.", pointer="/x")
        return real(session, **kwargs)

    monkeypatch.setattr(billing.service, "post_charge", flaky)
    done = ok(close(client, w, DAY), 201)
    assert done["package_count"] == 1 and [f["client_package_id"] for f in done["failed"]] == [bad["id"]]
    monkeypatch.setattr(billing.service, "post_charge", real)
    assert ok(close(client, w, DAY + timedelta(days=1)), 201)["package_count"] == 1  # billed at the next close


def test_rates_are_required_and_closes_cannot_run_ahead(client, w):
    body = {"client_id": w.person["id"], "location_id": w.location_id, "reservation_type_id": w.type_id}
    refused(client.post(f"{API}/client-packages/post-billed", headers=w.owner, json=body), 422, "validation-failed")
    tier = rate(client, w, 1, 1000)
    refused(client.post(f"{API}/post-billed-rates", headers=w.owner,
                        json={"reservation_type_id": w.type_id, "per_session_minor": 5}), 409, "rate-tier-exists")  # fmt: skip
    package = open_package(client, w)
    use(w, package, DAY)
    ok(client.patch(f"{API}/post-billed-rates/{tier['id']}", headers=w.owner, json={"is_active": False}), 200)
    [line] = ok(close(client, w, DAY, "/preview"), 200)["lines"]
    assert line["skipped_reason"] == "no-rate"
    with at(DAY):
        ahead = client.post(f"{API}/post-billed-closes", headers=w.owner,
                            json={"location_id": w.location_id, "closing_on": (DAY + timedelta(days=1)).isoformat()})  # fmt: skip
    refused(ahead, 422, "validation-failed")


def test_front_desk_cannot_close_a_period(client, w):
    email, _ = add_staff(w.tenant, "front_desk", all_locations=True)
    refused(close(client, w, DAY, headers=login(client, w.tenant, email)), 403, "permission-denied")


def test_a_hand_reversed_line_does_not_stop_later_usage_being_billed(client, w):
    rate(client, w, 1, 1000)
    package = open_package(client, w)
    use(w, package, DAY)
    restored = use(w, package, DAY)
    [line] = ok(close(client, w, DAY), 201)["lines"]
    with at(DAY), tx(w.tenant) as session:  # staff correct the attendance and also reverse the invoice line
        service.restore_credit(session, **restored)
        billing.service.reverse(session, UUID(line["charge_id"]), reason="Corrected by hand")
    later = DAY + timedelta(days=1)
    use(w, package, later)
    done = ok(close(client, w, later), 201)
    assert (done["session_count"], done["failed"]) == (1, [])  # the credit counts as handled; new usage bills
    assert billed_sessions(w) == 1
    assert ok(close(client, w, later + timedelta(days=1)), 201)["failed"] == []


def test_failures_are_stored_returned_again_and_retried_alone(client, w, monkeypatch):
    rate(client, w, 1, 1000)
    good, bad = open_package(client, w), open_package(client, w, name="Second")
    use(w, good, DAY)
    use(w, bad, DAY)
    real = billing.service.post_charge

    def flaky(session, **kwargs):
        if kwargs["description"].startswith("Second"):
            raise ValidationFailed("No.", pointer="/x")
        return real(session, **kwargs)

    monkeypatch.setattr(billing.service, "post_charge", flaky)
    first = ok(close(client, w, DAY), 201)
    assert [f["client_package_id"] for f in first["failed"]] == [bad["id"]]
    assert ok(close(client, w, DAY), 201)["failed"] == first["failed"]  # a repeat close still shows it
    path = f"{API}/post-billed-closes/{first['id']}"
    assert ok(client.get(path, headers=w.owner), 200)["failed"] == first["failed"]
    monkeypatch.setattr(billing.service, "post_charge", real)
    with at(DAY):
        retried = ok(client.post(f"{path}/retry", headers=w.owner), 200)
    assert (retried["failed"], retried["package_count"], retried["session_count"]) == ([], 2, 2)
    assert sorted(c.quantity for c in charges(w.tenant, w.person["id"])) == [1, 1]  # the good package not again
    with at(DAY):
        assert ok(client.post(f"{path}/retry", headers=w.owner), 200)["package_count"] == 2  # nothing left


def test_a_post_billed_package_needs_a_reservation_type_of_its_location(client, w):
    rate(client, w, 1, 1000)
    elsewhere = location(client, w.owner)
    body = {"client_id": w.person["id"], "location_id": elsewhere, "reservation_type_id": w.type_id}
    with at(DAY):
        refused(client.post(f"{API}/client-packages/post-billed", headers=w.owner, json=body), 422, "validation-failed")
