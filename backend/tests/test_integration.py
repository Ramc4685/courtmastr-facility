"""Seams between the lanes, through the HTTP API on real PostgreSQL: what one context must do when another
acts. Package credits at a session and packages at the till have their own files
(programs/tests/test_package_credits.py, pos/tests/test_package_lines.py)."""

from uuid import uuid4

from app.modules.documents.tests.support import sign, template
from app.modules.memberships.tests.support import deliver_events, sale, world
from app.modules.rentals.tests.test_rentals import f, rent  # noqa: F401  (the rentals facility fixture)
from app.modules.scheduling.tests.helpers import at, book
from conftest import new_client

API = "/api/v1"


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


def test_a_membership_with_a_waiver_is_billed_collected_by_autopay_and_activated_by_the_signature(
    client, tenant, owner
):
    """memberships x documents x billing: the sale bills at once on an autopay invoice, billing's autopay run
    collects it from the stored card, and access starts only when the waiver is signed."""
    w = world(client, owner, tenant)
    waiver = template(client, owner)
    ok(client.put(f"{API}/document-bindings", headers=owner,
                  json={"scope_type": "membership_plan", "scope_id": w.plan["id"], "template_id": waiver["id"],
                        "frequency": "every_purchase"}))  # fmt: skip
    person = w.person["id"]
    ok(client.post(f"{API}/clients/{person}/payment-methods", headers=owner,
                   json={"method_token": "tok_card_ok", "is_autopay": True}), 201)  # fmt: skip

    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w, is_autopay=True)), 201)
    assert sold["status"] == "upcoming"
    invoice = ok(client.get(f"{API}/invoices/{sold['invoice_id']}", headers=owner))
    assert (invoice["is_autopay"], invoice["status"], invoice["bill_to_client_id"]) == (True, "open", person)

    run = ok(client.post(f"{API}/autopay-runs", headers=owner | {"Idempotency-Key": f"run-{uuid4().hex}"},
                         json={"location_id": w.location_id}), 201)["run"]  # fmt: skip
    assert (run["succeeded_count"], run["failed_count"]) == (1, 0)
    paid = ok(client.get(f"{API}/invoices/{sold['invoice_id']}", headers=owner))
    assert (paid["status"], paid["balance_minor"]) == ("paid", 0)

    document = ok(client.get(f"{API}/client-documents/{sold['client_document_id']}", headers=owner))
    assert sign(client, owner, document).status_code == 200
    deliver_events()
    assert ok(client.get(f"{API}/membership-contracts/{sold['id']}", headers=owner))["status"] == "active"


def test_a_rental_is_billed_and_paid_through_the_full_billing_module(client, owner, f):  # noqa: F811
    """rentals x scheduling x billing: the rental's invoice carries billing's payment schedule, a payment at
    the desk settles it, and the rental reads its charge state back from billing."""
    created = ok(rent(client, owner, f, 21, 23), 201)
    rental, invoice_id = created["rental"], created["invoice_ids"][0]
    invoice = ok(client.get(f"{API}/invoices/{invoice_id}", headers=owner))
    schedule = ok(client.get(f"{API}/invoices/{invoice_id}/payment-schedule", headers=owner))
    assert sum(row["amount_minor"] for row in schedule["instalments"]) == invoice["total_minor"] == 9743
    payment = ok(client.post(f"{API}/payments", headers=owner | {"Idempotency-Key": f"pay-{uuid4().hex}"}, json={
        "client_id": f.person, "location_id": f.location, "amount_minor": 9743, "tender_kind": "cash",
        "invoice_id": invoice_id}), 201)  # fmt: skip
    assert payment["status"] == "succeeded"
    assert ok(client.get(f"{API}/invoices/{invoice_id}", headers=owner))["status"] == "paid"
    assert ok(client.get(f"{API}/rentals/{rental['id']}", headers=owner))["charge_state"] == "billed"
    # the court is really held: a second rental of the same hours is refused by the exclusion constraint
    clash = rent(client, owner, f, 21, 23)
    assert (clash.status_code, clash.json()["code"]) == (409, "booking-conflict")


def test_a_merge_carries_every_contexts_rows_and_an_erasure_is_blocked_by_what_is_open(client, owner, f):  # noqa: F811
    """clients x billing x scheduling x programs x rentals: the duplicate's rental, invoice and session place
    follow it into the survivor; the erasure of a client with money owed and a booking ahead is blocked."""
    keep = ok(client.get(f"{API}/clients/{f.person}", headers=owner))
    twin = new_client(client, owner, f.location, first_name=keep["first_name"], last_name=keep["last_name"])["id"]
    created = ok(rent(client, owner, f, 21, 23, client_id=twin), 201)
    invoice_id = created["invoice_ids"][0]
    seat = ok(book(client, owner, f, [f.court2], at(10), at(11), kind="session", session={"capacity": 2}), 201)[
        "booking"
    ]["session"]["id"]
    for person in (f.person, twin):
        ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": seat, "client_id": person}), 201)

    ok(client.post(f"{API}/clients/{f.person}/merge", headers=owner, json={"merged_client_ids": [twin]}))

    assert ok(client.get(f"{API}/invoices/{invoice_id}", headers=owner))["bill_to_client_id"] == f.person
    assert ok(client.get(f"{API}/charges?client_id={twin}", headers=owner))["data"] == []
    rentals = ok(client.get(f"{API}/rentals?client_id={f.person}", headers=owner))["data"]
    assert [row["id"] for row in rentals] == [created["rental"]["id"]]
    roster = ok(client.get(f"{API}/sessions/{seat}/roster", headers=owner))
    assert (roster["booked_count"], [p["client_id"] for p in roster["participants"]]) == (1, [f.person])
    gone = ok(client.get(f"{API}/enrollments?client_id={f.person}&status=cancelled", headers=owner))["data"]
    assert [row["cancel_kind"] for row in gone] == ["client_merged"]  # the duplicate place, now the survivor's

    erase = ok(client.post(f"{API}/data-subject-requests", headers=owner,
                           json={"client_id": f.person, "kind": "erasure", "reason": "Asked"}), 201)  # fmt: skip
    assert erase["status"] == "blocked"
    assert {(b["context"], b["code"]) for b in erase["blockers"]} == {
        ("billing", "open-balance"),
        ("scheduling", "upcoming-booking"),
    }


def test_a_suspended_tenant_keeps_its_retention_jobs_and_nothing_else(tenant, monkeypatch):
    """Suspension must not stop purges, export expiry or file byte deletion; it does stop billing and messaging."""
    from app import scheduler
    from app.core.db.session import tenant_session
    from app.modules.platform.models import Tenant

    with tenant_session(tenant.id) as session:
        session.get(Tenant, tenant.id).status = "suspended"
    sent: dict[str, set[str]] = {}

    def record(names, tenant_ids):
        tenant_ids = list(tenant_ids)
        for tenant_id in tenant_ids:
            sent.setdefault(tenant_id, set()).update(names)
        return len(tenant_ids) * len(tuple(names))

    monkeypatch.setattr(scheduler, "enqueue", record)
    scheduler.tick_hour()
    assert sent[str(tenant.id)] == set(scheduler.RETENTION)
    assert set(scheduler.RETENTION) <= set(scheduler.EVERY_HOUR)  # every retention job is a real hourly actor


def test_the_scheduler_starts_every_periodic_job_for_a_tenant_and_they_all_run(client, tenant, owner):
    """kernel x every context with a dated job: the clock's names resolve to real actors, and one tick for a
    tenant with an unpaid autopay membership runs them all without error (twice: they are idempotent)."""
    from app import scheduler

    w = world(client, owner, tenant)
    # autopay starts at the location's local run time: midnight, so the test passes at any hour
    ok(client.patch(f"{API}/locations/{w.location_id}", headers=owner, json={"autopay_run_time": "00:00"}))
    ok(client.post(f"{API}/clients/{w.person['id']}/payment-methods", headers=owner,
                   json={"method_token": "tok_card_ok", "is_autopay": True}), 201)  # fmt: skip
    sold = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w, is_autopay=True)), 201)
    assert str(tenant.id) in scheduler.active_tenants()
    jobs = scheduler.EVERY_MINUTE + scheduler.EVERY_HOUR
    for _ in range(2):
        assert scheduler.enqueue(jobs, [str(tenant.id)]) == len(jobs)
        deliver_events()
    # billing_daily collected the membership's first invoice from the stored card
    assert ok(client.get(f"{API}/invoices/{sold['invoice_id']}", headers=owner))["status"] == "paid"
