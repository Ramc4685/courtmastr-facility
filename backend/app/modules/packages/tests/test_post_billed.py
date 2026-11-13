"""Post-billed packages (PKG-11) and the period close that bills them (BIL-18): tiered rates, usage up to the
closing date, one charge and invoice per package, idempotency per period, skipped lines and the gate."""

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

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


def use(w, package: dict, day: date, *, settle: bool = True) -> None:
    """One session paid by the package: a credit reserved for a booking, then consumed by attending."""
    source = {"source_type": "booking", "source_id": uuid4()}
    with at(day), tx(w.tenant) as session:
        service.reserve_credit(session, client_package_id=UUID(package["id"]), client_id=UUID(w.person["id"]),
                               session_on=day, reservation_type_id=UUID(w.type_id), **source)  # fmt: skip
        if settle:
            service.settle_credit(session, outcome="attended", **source)


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
