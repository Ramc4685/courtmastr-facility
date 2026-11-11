"""Shared helpers for the memberships and packages tests.

HTTP tests run at the real time. Lifecycle tests travel in time instead: they call the services directly, as the
system principal, inside `at(day)`, which freezes the injected clock (tokens would expire across a frozen jump,
and the service layer is where the dates are decided anyway).
"""

from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import func, select

from app import relay
from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.events import OutboxEvent
from app.modules import billing
from app.modules.billing.models import Charge, Invoice, Payment
from app.modules.memberships.models import BillingSchedulePeriod, MembershipContract
from app.modules.platform.models import Location
from app.modules.scheduling.models import ReservationType
from conftest import new_client

API = "/api/v1"
SYSTEM = system_principal("tests")


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def refused(response, status: int, code: str) -> dict:
    assert (response.status_code, response.json()["code"]) == (status, code), response.text
    return response.json()


@contextmanager
def tx(tenant):
    """One committed unit of work as the system principal: what a request or a job run is."""
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        yield session


def at(day: date, hour: int = 18):
    """Freeze the clock on a calendar day (18:00 UTC is the same date across the Americas)."""
    return clock.freeze(datetime(day.year, day.month, day.day, hour, tzinfo=UTC))


def location(client, headers, time_zone: str = "America/Chicago", name: str | None = None) -> str:
    body = {"name": name or f"Site {uuid4().hex[:6]}", "time_zone": time_zone, "country_code": "US"}
    return ok(client.post(f"{API}/locations", headers=headers, json=body), 201)["id"]


def category(tenant, code: str = "MEMB") -> str:
    with tx(tenant) as session:
        return str(billing.service.create_revenue_category(session, code=code, label=code.title()).id)


def membership_plan(client, headers, tenant, **fields) -> dict:
    """A 12 x monthly plan at 31.00 a month under a fresh membership type."""
    kind = ok(client.post(f"{API}/membership-types", headers=headers,
                          json={"name": f"Type {uuid4().hex[:6]}", "revenue_category_id": category(tenant)}), 201)  # fmt: skip
    body = {"membership_type_id": kind["id"], "name": f"Plan {uuid4().hex[:6]}", "billing_occurrences_count": 12,
            "term_fee_minor": 3100}  # fmt: skip
    return ok(client.post(f"{API}/membership-plans", headers=headers, json=body | fields), 201)


def lesson_type(client, headers, tenant) -> str:
    """The tenant's reservation type for package plans (one is enough: plans only need a real one to point at)."""
    with tx(tenant) as session:
        found = session.scalar(select(ReservationType.id).order_by(ReservationType.id).limit(1))
        site = session.scalar(select(Location.id).order_by(Location.id).limit(1))
    if found:
        return str(found)
    body = {"location_id": str(site) if site else location(client, headers), "name": "Lesson"}
    return ok(client.post(f"{API}/reservation-types", headers=headers, json=body), 201)["id"]


def package_plan(client, headers, tenant, **fields) -> dict:
    """A ten-session pack at 100.00 with no expiry."""
    body = {"reservation_type_id": lesson_type(client, headers, tenant), "name": f"Pack {uuid4().hex[:6]}", "session_mode": "fixed",
            "session_count": 10, "fee_minor": 10000, "fee_basis": "per_package",
            "revenue_category_id": category(tenant, "PACK")}  # fmt: skip
    if fields.get("pricing_category") == "free":
        body = {k: v for k, v in body.items() if k not in ("fee_minor", "fee_basis", "revenue_category_id")}
    return ok(client.post(f"{API}/package-plans", headers=headers, json=body | fields), 201)


def world(client, owner, tenant, time_zone: str = "America/Chicago", **plan_fields) -> SimpleNamespace:
    """A location, a client and a membership plan: the starting point of most tests."""
    location_id = location(client, owner, time_zone)
    return SimpleNamespace(
        tenant=tenant, owner=owner, location_id=location_id, person=new_client(client, owner, location_id),
        plan=membership_plan(client, owner, tenant, **plan_fields),
    )  # fmt: skip


def sale(w, **fields) -> dict:
    return {"client_id": w.person["id"], "location_id": w.location_id, "membership_plan_id": w.plan["id"]} | fields


def periods(tenant, contract_id, *statuses) -> list[BillingSchedulePeriod]:
    with tx(tenant) as session:
        stmt = select(BillingSchedulePeriod).where(BillingSchedulePeriod.membership_contract_id == contract_id)
        if statuses:
            stmt = stmt.where(BillingSchedulePeriod.status.in_(statuses))
        return list(session.scalars(stmt.order_by(BillingSchedulePeriod.due_on, BillingSchedulePeriod.kind)))


def contract(tenant, contract_id) -> MembershipContract:
    with tx(tenant) as session:
        return session.get(MembershipContract, contract_id)


def scheduled_total(tenant, contract_id) -> int:
    """Sum of every period that is not cancelled: the money a freeze must never change."""
    return sum(p.amount_minor for p in periods(tenant, contract_id) if p.status != "cancelled")


def charges(tenant, client_id) -> list[Charge]:
    with tx(tenant) as session:
        return list(session.scalars(select(Charge).where(Charge.client_id == client_id).order_by(Charge.id)))


def open_balance(tenant, client_id) -> int:
    """What the client still owes: active charges less what is applied to them."""
    with tx(tenant) as session:
        return int(session.scalar(
            select(func.coalesce(func.sum(Charge.total_minor - Charge.applied_minor), 0))
            .where(Charge.client_id == client_id, Charge.status == "active", Charge.kind == "standard")
        ))  # fmt: skip


def account_credit(tenant, client_id) -> int:
    with tx(tenant) as session:
        return int(session.scalar(
            select(func.coalesce(func.sum(Payment.unapplied_minor), 0)).where(Payment.client_id == client_id)
        ))  # fmt: skip


def invoices(tenant, client_id) -> list[Invoice]:
    with tx(tenant) as session:
        return list(
            session.scalars(select(Invoice).where(Invoice.bill_to_client_id == client_id).order_by(Invoice.number))
        )


def event_types(tenant, aggregate_id) -> list[str]:
    with tx(tenant) as session:
        stmt = select(OutboxEvent.event_type).where(OutboxEvent.aggregate_id == aggregate_id)
        return list(session.scalars(stmt.order_by(OutboxEvent.occurred_at, OutboxEvent.id)))


def deliver_events() -> None:
    """Relay every committed outbox event and run the subscribed handlers, as the relay and worker would."""
    from dramatiq import Worker

    from app.core.jobs import broker

    while relay.relay_once():
        pass
    worker = Worker(broker, worker_timeout=100)
    worker.start()
    try:
        broker.join("default", fail_fast=True, timeout=300_000)
        worker.join()
    finally:
        worker.stop()


# --- service-level helpers for the time-travel tests ---------------------------------------------------------


def as_ids(w, **fields) -> dict:
    """sale() with real UUIDs, for calling the service directly."""
    from uuid import UUID

    return {"client_id": UUID(w.person["id"]), "location_id": UUID(w.location_id),
            "membership_plan_id": UUID(w.plan["id"])} | fields  # fmt: skip


def sell_at(w, day: date, **fields) -> dict:
    from app.modules.memberships import service

    with at(day), tx(w.tenant) as session:
        return service.sell_contract(session, SYSTEM, as_ids(w, **fields))


def daily(tenant, day: date) -> dict:
    """The daily job on a calendar day."""
    from app.modules.memberships import service

    with at(day), tx(tenant) as session:
        return service.run_daily(session)


def run(tenant, day: date, fn, *args, **kwargs):
    """Call a service function as the system principal on a calendar day, in its own transaction."""
    with at(day), tx(tenant) as session:
        return fn(session, SYSTEM, *args, **kwargs)


def pay(w, day: date, amount_minor: int, invoice_id=None, tender_kind: str = "cash", **extra):
    from uuid import UUID

    with at(day), tx(w.tenant) as session:
        payment = billing.service.take_payment(
            session, client_id=UUID(w.person["id"]), location_id=UUID(w.location_id), amount_minor=amount_minor,
            tender_kind=tender_kind, invoice_id=invoice_id, **extra,
        )  # fmt: skip
        return payment.id


def row_dates(tenant, contract_id) -> list[tuple]:
    return [(p.kind, p.sequence_number, p.due_on, p.bill_on, p.service_during, p.status, p.amount_minor)
            for p in periods(tenant, contract_id)]  # fmt: skip
