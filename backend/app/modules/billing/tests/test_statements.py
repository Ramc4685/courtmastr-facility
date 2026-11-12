"""Phase 9 chip B: invoice, receipt and statement PDFs (BIL-10, PAY-03, BIL-11), statement batches with
per-recipient status, the portal statement, and the location's day in statements and AR ageing (REL-04)."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.errors import NotFound, ValidationFailed
from app.core.events import OutboxEvent
from app.modules import clients, platform
from app.modules.billing import documents, statements
from app.modules.billing import subject as documents_subject
from app.modules.billing.models import BillingDocumentDelivery, Invoice, StatementBatch, StatementRecipient
from app.modules.billing.tests.test_autopay import drain
from app.modules.billing.tests.test_billing import cash, charge, work
from app.modules.billing.tests.test_money import NOON
from app.modules.billing.tests.test_surface import item
from conftest import new_client

# 23:30 on 10 November in America/Chicago (the shop's zone) is already 11 November in UTC.
LATE = datetime(2026, 11, 11, 5, 30, tzinfo=UTC)
AFTER = datetime(2026, 11, 11, 6, 30, tzinfo=UTC)  # 00:30 on 11 November there
NOV10 = date(2026, 11, 10)
MONTH = {"period_from_on": "2026-11-01", "period_to_on": "2026-11-30"}
MONTH_RANGE = {"from_on": "2026-11-01", "to_on": "2026-11-30"}


def _is_pdf(response, name_prefix: str) -> bytes:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith(f'attachment; filename="{name_prefix}')
    assert response.content.startswith(b"%PDF")
    return response.content


def _invoice(api, shop, **over) -> dict:
    return api("POST", "/invoices", {"charge_ids": [api("POST", "/charges", item(shop, **over), 201)["id"]]}, 201)


def test_invoice_and_receipt_pdfs_carry_the_document(client, api, shop, desk, member):
    with clock.freeze(NOON):
        invoice = _invoice(api, shop)
        payment = api("POST", "/payments", {"client_id": str(shop.client_id), "location_id": str(shop.location_id),
                                            "amount_minor": 1500, "tender_kind": "cash", "invoice_id": invoice["id"]},
                      201)  # fmt: skip
    data = _is_pdf(client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=desk.front), "invoice-")
    assert f"Invoice {invoice['number']}".encode() in data and b"Court hire" in data and b"10.83 USD" in data
    assert b"Balance due" in data and b"page 1" in data
    assert client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=desk.front).content == data  # deterministic

    receipt = _is_pdf(client.get(f"/api/v1/payments/{payment['id']}/receipt/pdf", headers=shop.owner), "receipt-")
    assert f"Receipt {payment['receipt_number']}".encode() in receipt
    assert b"15.00 USD" in receipt and b"4.17 USD" in receipt and b"2026-11-10" in receipt  # on account; local day

    assert client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=member.headers).status_code == 403
    assert client.get(f"/api/v1/invoices/{shop.location_id}/pdf", headers=shop.owner).status_code == 404


def test_portal_invoice_pdf_and_statement_are_the_callers_own(client, api, shop, member):
    with clock.freeze(NOON):
        mine, theirs = _invoice(api, shop, client_id=member.id), _invoice(api, shop, client_id=member.stranger)
    data = _is_pdf(client.get(f"/api/v1/portal/invoices/{mine['id']}/pdf", headers=member.headers), "invoice-")
    assert f"Invoice {mine['number']}".encode() in data
    assert client.get(f"/api/v1/portal/invoices/{theirs['id']}/pdf", headers=member.headers).status_code == 404
    assert client.get(f"/api/v1/portal/invoices/{mine['id']}/pdf", headers=shop.owner).status_code == 404

    portal = member.api
    with clock.freeze(NOON):
        own = portal("GET", "/portal/statement")
        assert (own["client_id"], own["to_on"], own["time_zone"]) == (member.id, "2026-11-10", "America/Chicago")
        assert [row["id"] for row in own["invoices"]] == [mine["id"]] and own["invoiced_minor"] == 1083
        pdf = client.get("/api/v1/portal/statement/pdf?from_on=2026-11-01&to_on=2026-11-10", headers=member.headers)
        assert b"Period: 2026-11-01 to 2026-11-10" in _is_pdf(pdf, "statement-2026-11-01-2026-11-10")
    portal("GET", f"/portal/statement?client_id={member.stranger}", None, 404)
    api("GET", "/portal/statement", None, 403)


def test_statement_period_is_the_home_locations_day(client, api, shop):
    """REL-04: a payment at 23:30 local on the last day is inside; 00:30 the next day is not."""
    with work(shop.tenant) as session:
        with clock.freeze(LATE):
            inside = cash(session, shop, 500)
        with clock.freeze(AFTER):
            outside = cash(session, shop, 700)
        document = documents.statement(session, shop.client_id, date(2026, 11, 1), NOV10)
        assert [p.id for p in document["payments"]] == [inside.id] and document["paid_minor"] == 500
        assert document["time_zone"] == "America/Chicago"
        next_day = documents.statement(session, shop.client_id, date(2026, 11, 11), date(2026, 11, 11))
        assert [p.id for p in next_day["payments"]] == [outside.id]
    url = f"/api/v1/clients/{shop.client_id}/statement/pdf?from_on=2026-11-01&to_on=2026-11-10"
    data = _is_pdf(client.get(url, headers=shop.owner), "statement-")
    assert b"5.00 USD" in data and b"2026-11-10" in data and b"7.00 USD" not in data
    staff = api("GET", f"/clients/{shop.client_id}/statement?from_on=2026-11-01&to_on=2026-11-10")
    assert staff["paid_minor"] == 500 and staff["time_zone"] == "America/Chicago"


def test_ageing_as_at_cut_is_the_locations_day(api, shop):
    """REL-04: an allocation applied at 23:30 local on `as_of` counts as paid on that day."""
    with work(shop.tenant) as session:
        with clock.freeze(NOON):
            owed = charge(session, shop, 1000)
            unpaid = charge(session, shop, 400)
        with clock.freeze(LATE):
            cash(session, shop, owed.total_minor, allocations=[(owed.id, owed.total_minor)])
    rows = api("GET", "/receivables-ageing?as_of=2026-11-10")["rows"]
    mine = next(row for row in rows if row["client_id"] == str(shop.client_id))
    assert mine["total_minor"] == unpaid.total_minor  # the late payment counts on the local day
    with clock.freeze(NOON):
        assert api("GET", "/receivables-ageing")["as_of"] == "2026-11-10"


def test_sending_a_document_stores_its_pdf_and_links_to_it(api, shop, mailbox):
    emailed = new_client(api.client, shop.owner, shop.location_id, primary_email=f"doc@{shop.tenant.slug}.example.com")
    invoice = _invoice(api, shop, client_id=emailed["id"])
    sent = api("POST", f"/invoices/{invoice['id']}/deliveries", {"channel": "email"}, 201)
    assert f"/portal/invoices?invoice={invoice['id']}" in mailbox[-1].body
    api("POST", f"/clients/{emailed['id']}/statement/deliveries", {"from_on": "2026-01-01", "to_on": "2026-12-31"}, 201)
    assert "/portal/statement?from_on=2026-01-01&to_on=2026-12-31" in mailbox[-1].body
    with work(shop.tenant) as session:
        row = session.get(BillingDocumentDelivery, sent["id"])
        stored, data = platform.files.read(session, row.stored_file_id)
        assert (stored.content_type, stored.purpose, stored.original_name) == (
            "application/pdf", "billing.invoice", f"invoice-{invoice['number']}.pdf",
        )  # fmt: skip
        assert f"Invoice {invoice['number']}".encode() in data


def test_erasure_purges_every_pdf_sent_to_the_client(api, shop, mailbox):
    """Invoice and receipt deliveries carry only the invoice or payment; all of the client's PDFs go."""
    emailed = new_client(api.client, shop.owner, shop.location_id, primary_email=f"gone@{shop.tenant.slug}.example.com")
    with clock.freeze(NOON):
        invoice = _invoice(api, shop, client_id=emailed["id"])
        payment = api("POST", "/payments", {"client_id": emailed["id"], "location_id": str(shop.location_id),
                                            "amount_minor": 500, "tender_kind": "cash", "invoice_id": invoice["id"]},
                      201)  # fmt: skip
        api("POST", f"/invoices/{invoice['id']}/deliveries", {"channel": "email"}, 201)
        api("POST", f"/payments/{payment['id']}/receipt-deliveries", {"channel": "email"}, 201)
        api("POST", f"/clients/{emailed['id']}/statement/deliveries", MONTH_RANGE, 201)
        api("POST", "/statement-batches", {"location_id": str(shop.location_id), "client_ids": [emailed["id"]]} | MONTH,
            201)  # fmt: skip
    with work(shop.tenant) as session:
        client_id = UUID(emailed["id"])
        mine = BillingDocumentDelivery.invoice_id == UUID(invoice["id"])
        mine |= BillingDocumentDelivery.payment_id == UUID(payment["id"])
        mine |= BillingDocumentDelivery.client_id == client_id
        files = list(session.scalars(select(BillingDocumentDelivery.stored_file_id).where(mine)))
        files += session.scalars(
            select(StatementRecipient.stored_file_id).where(StatementRecipient.client_id == client_id)
        )
        kinds = {platform.files.read(session, f)[0].purpose for f in files}
        assert kinds == {"billing.invoice", "billing.receipt", "billing.statement"} and len(files) == 4
        assert platform.privacy.HANDLERS["billing"].erase(session, client_id)["purged_documents"] == 4
        for stored_file_id in files:
            with pytest.raises(NotFound):
                platform.files.read(session, stored_file_id)
        addresses = set(session.scalars(select(BillingDocumentDelivery.to_email).where(mine)))
        assert addresses == {documents_subject.ERASED_EMAIL}


@pytest.fixture
def payers(api, shop):
    """Two payers with an invoice at the shop this month: one with an email address, one without."""
    with_email = new_client(api.client, shop.owner, shop.location_id,
                            primary_email=f"stmt@{shop.tenant.slug}.example.com")["id"]  # fmt: skip
    without = new_client(api.client, shop.owner, shop.location_id)["id"]
    with clock.freeze(NOON):
        for client_id in (with_email, without):
            _invoice(api, shop, client_id=client_id)
    return with_email, without


def test_a_statement_batch_reports_each_recipient_and_resends(api, shop, desk, payers, mailbox):
    with_email, without = payers
    body = {"location_id": str(shop.location_id)} | MONTH
    api("POST", "/statement-batches", body, 403, headers=desk.front)  # front desk does not send statements
    api("POST", "/statement-batches", body | {"period_to_on": "2026-10-01"}, 422)
    batch = api("POST", "/statement-batches", body, 201)
    counts = (batch["status"], batch["recipient_count"], batch["sent_count"], batch["skipped_count"])
    assert counts == ("completed", 2, 1, 1)
    status = {row["client_id"]: row["status"] for row in batch["recipients"]}
    assert status == {with_email: "sent", without: "skipped_no_email"}
    assert mailbox[-1].to == f"stmt@{shop.tenant.slug}.example.com" and "Statement for 2026-11-01" in mailbox[-1].body

    api("GET", f"/statement-batches/{batch['id']}", None, 404, headers=desk.west_manager)  # another location
    assert len(api("GET", f"/statement-batches/{batch['id']}/recipients")) == 2
    assert [row["id"] for row in api("GET", "/statement-batches")["data"]] == [batch["id"]]
    assert api("GET", "/statement-batches", headers=desk.west_manager)["data"] == []

    with work(shop.tenant) as session:
        clients.service.get(session, without).primary_email = f"late@{shop.tenant.slug}.example.com"
    again = api("POST", f"/statement-batches/{batch['id']}/resend", {})
    assert (again["sent_count"], again["skipped_count"]) == (2, 0) and mailbox[-1].to.startswith("late@")
    with work(shop.tenant) as session:
        recipients = session.scalars(select(StatementRecipient)).all()
        assert all(row.stored_file_id for row in recipients)
        assert b"Statement for" in platform.files.read(session, recipients[0].stored_file_id)[1]
        completed = select(OutboxEvent).where(OutboxEvent.event_type == "billing.statement_batch.completed")
        assert len(session.scalars(completed).all()) == 2
        actions = session.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "statement_batch")).all()
        assert actions == ["billing.statement.send", "billing.statement.send"]


def test_a_large_batch_runs_as_a_job_and_a_failure_stays_on_its_row(api, shop, payers, monkeypatch):
    monkeypatch.setattr(statements, "IN_REQUEST_LIMIT", 0)
    body = {"location_id": str(shop.location_id), "client_ids": [payers[0]]} | MONTH
    queued = api("POST", "/statement-batches", body, 201)
    assert (queued["status"], queued["recipient_count"], queued["queued_count"]) == ("queued", 1, 1)
    drain()
    done = api("GET", f"/statement-batches/{queued['id']}")
    assert (done["status"], done["sent_count"]) == ("completed", 1)

    def broken(*args, **kwargs):
        raise ValidationFailed("No statement today.")

    monkeypatch.setattr(statements, "IN_REQUEST_LIMIT", 25)
    monkeypatch.setattr(documents, "email_statement", broken)
    failed = api("POST", "/statement-batches", body | {"client_ids": list(payers)}, 201)
    assert (failed["failed_count"], failed["skipped_count"]) == (1, 1)
    row = next(row for row in failed["recipients"] if row["status"] == "failed")
    assert (row["failure_message"], row["client_id"]) == ("No statement today.", payers[0])


def test_statement_batch_open_only_and_unknown_location(api, shop, payers):
    with work(shop.tenant) as session:
        owed = session.scalars(select(Invoice).where(Invoice.bill_to_client_id == payers[1])).one()
        cash(session, shop, owed.balance_minor, client_id=owed.bill_to_client_id, invoice_id=owed.id)
    body = {"location_id": str(shop.location_id), "is_open_only": True, "date_basis": "due_date"} | MONTH
    batch = api("POST", "/statement-batches", body, 201)
    assert [row["client_id"] for row in batch["recipients"]] == [payers[0]]
    api("POST", "/statement-batches", body | {"location_id": str(shop.client_id)}, 422)


def test_staff_defaults_are_the_locations_today(api, shop):
    """23:30 on 10 November in Chicago is 11 November in UTC: the defaults say the 10th."""
    with clock.freeze(LATE):
        staff = api("GET", f"/clients/{shop.client_id}/statement")
        assert (staff["from_on"], staff["to_on"]) == ("2026-10-11", "2026-11-10")
        ageing = api("GET", f"/receivables-ageing?location_id={shop.location_id}")
        assert ageing["as_of"] == "2026-11-10"


def test_a_rerun_or_redelivered_batch_changes_nothing(api, shop, payers):
    batch = api("POST", "/statement-batches", {"location_id": str(shop.location_id)} | MONTH, 201)
    with work(shop.tenant) as session:
        finished = session.get(StatementBatch, UUID(batch["id"])).finished_at
        statements.run_batch(session, UUID(batch["id"]))  # a redelivered job
        assert session.get(StatementBatch, UUID(batch["id"])).finished_at == finished
        completed = select(OutboxEvent).where(OutboxEvent.event_type == "billing.statement_batch.completed")
        assert len(session.scalars(completed).all()) == 1


def test_the_same_idempotency_key_makes_one_batch(api, shop, payers, mailbox):
    body = {"location_id": str(shop.location_id)} | MONTH
    headers = shop.owner | {"Idempotency-Key": "statement-run-november"}
    first = api.client.post("/api/v1/statement-batches", json=body, headers=headers)
    sent = len(mailbox)
    again = api.client.post("/api/v1/statement-batches", json=body, headers=headers)
    assert (first.status_code, again.status_code) == (201, 201) and again.json()["id"] == first.json()["id"]
    assert len(mailbox) == sent and len(api("GET", "/statement-batches")["data"]) == 1


def test_an_unexpected_error_fails_only_its_recipient(api, shop, payers, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr(documents, "email_statement", broken)
    batch = api("POST", "/statement-batches", {"location_id": str(shop.location_id)} | MONTH, 201)
    assert (batch["status"], batch["failed_count"], batch["skipped_count"]) == ("completed", 1, 1)
    row = next(row for row in batch["recipients"] if row["status"] == "failed")
    assert row["failure_message"] == "Could not send: RuntimeError"  # the type, never the error text


def test_resend_waits_for_the_batch_and_a_failed_job_marks_it_failed(api, shop, payers, monkeypatch):
    monkeypatch.setattr(statements, "IN_REQUEST_LIMIT", 0)
    queued = api("POST", "/statement-batches", {"location_id": str(shop.location_id)} | MONTH, 201)
    api("POST", f"/statement-batches/{queued['id']}/resend", {}, 409, code="invalid-state-transition")

    def crash(session, batch_id):
        raise RuntimeError("worker died")

    monkeypatch.setattr(statements, "run_batch", crash)
    with pytest.raises(RuntimeError):  # the job body itself, not through the shared test broker
        statements.run_statement_batch.fn(str(shop.tenant.id), queued["id"])
    assert api("GET", f"/statement-batches/{queued['id']}")["status"] == "failed"
    monkeypatch.undo()
    drain()  # the real job, enqueued when the batch was created, finishes the rows still queued
    assert api("GET", f"/statement-batches/{queued['id']}")["status"] == "completed"
    assert api("POST", f"/statement-batches/{queued['id']}/resend", {}, 200)["status"] == "completed"
