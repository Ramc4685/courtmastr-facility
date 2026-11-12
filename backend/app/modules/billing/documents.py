"""What billing shows and sends: invoice and receipt documents and their deliveries (BIL-10, PAY-03), the
emailed pay link, statements (BIL-11), the client billing summary (BIL-21), accounts receivable ageing
(BIL-19), billing history (BIL-09) and bulk invoicing from the workbench (BIL-02).

Documents are structured data, a PDF rendered from that data with `app.core.pdf`, and a plain-text email
that links to the PDF in the portal. A sent PDF is stored (`stored_file_id` on the delivery) so it can be shown
as it went out. Statement periods and the ageing "as at" cut end at midnight on the location's wall clock.
"""

import hashlib
import secrets
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core import audit, clock, pdf
from app.core.audit import AuditEvent
from app.core.auth import Principal, authorize, scope_query, system_principal
from app.core.errors import Conflict, DomainError, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import clients, platform
from app.modules.billing import catalogue, service
from app.modules.billing.autopay import money, portal_link
from app.modules.billing.domain.dunning import AGEING_BUCKETS, ageing_bucket
from app.modules.billing.models import (
    BillingDocumentDelivery,
    Charge,
    Invoice,
    InvoicePayLink,
    Payment,
    PaymentAllocation,
    Refund,
)
from app.ports import notifications, payment_provider

PAY_LINK_DAYS = 14
MAX_STATEMENT_DAYS = 366

notifications.register_template(
    "billing.invoice", subject="$subject",
    body="Invoice $invoice_number from $facility\n\n$lines\n\nTotal: $total\nBalance due: $balance (due $due_on)"
    "$pay\n\nView or download the PDF in your account:\n$document_link$footer",
)  # fmt: skip
notifications.register_template(
    "billing.receipt", subject="Receipt $receipt_number from $facility",
    body="Receipt $receipt_number\n\nReceived: $received ($tender) on $received_on\nApplied: $applied\n"
    "Refunded: $refunded\nOn account: $unapplied\n\nYour payments and invoices are in your account:\n$document_link"
    "$footer",
)  # fmt: skip
notifications.register_template(
    "billing.statement", subject="$subject",
    body="$intro\n\nStatement for $period\n\n$lines\n\nInvoiced: $invoiced\nPaid: $paid\nBalance due: $balance\n"
    "Credit on account: $credit\n\nView or download the PDF in your account:\n$document_link$footer",
)  # fmt: skip


def _footer(text: str | None) -> str:
    return f"\n\n{text}" if text else ""


def _currency(session: Session) -> str:
    return platform.service.get_tenant(session).currency


def _recipient(session: Session, client_id: UUID | None, to_email: str | None, channel: str) -> str | None:
    """Where an email goes: the ad-hoc address if given (never written back to the client), else the payer's."""
    if channel != "email":
        return None
    address = to_email or (clients.service.get(session, client_id).primary_email if client_id else None)
    if not address:
        raise ValidationFailed("There is no email address to send to.", pointer="/to_email", code="no-email-address")
    return address


def _deliver(
    session: Session, kind: str, channel: str, to_email: str | None, data: bytes, name: str, **subject
) -> BillingDocumentDelivery:
    # `sent` means handed to the notification port in this transaction; it goes out after commit. Delivery
    # confirmation (bounces) belongs to engagement and is not tracked here.
    row = BillingDocumentDelivery(
        document_kind=kind, channel=channel, to_email=to_email, status="sent",
        requested_by_staff_user_id=service._staff_id(session), stored_file_id=store_pdf(session, data, kind, name).id,
        **subject,
    )  # fmt: skip
    session.add(row)
    session.flush()
    return row


def store_pdf(session: Session, data: bytes, kind: str, name: str):
    """Keep the PDF as it went out. Internal: statement batches store each recipient's copy too."""
    staff_id = service._staff_id(session)
    return platform.files.store(
        session, data, purpose=f"billing.{kind}", content_type=platform.files.PDF, original_name=name,
        uploaded_by=("staff", staff_id) if staff_id else ("system", None),
    )  # fmt: skip


def _zone(session: Session, location_id: UUID) -> str:
    return platform.service.location_time_zone(session, location_id)


def _local_day(zone: str, day: date) -> datetime:
    """The instant a local calendar day starts at a location (overview 3.7)."""
    return datetime.combine(day, time.min, ZoneInfo(zone))


def _pdf(title: str, session: Session, *, subtitle: str | None, footer: str | None) -> pdf.Document:
    return pdf.Document(title, organization=platform.service.get_tenant(session).name, subtitle=subtitle, footer=footer)


# --- invoices ----------------------------------------------------------------------------------------------


def invoice_document(session: Session, invoice: Invoice) -> dict:
    """The printable content of an invoice. Voided items and internal remarks are left out."""
    charges = session.scalars(
        select(Charge).where(Charge.invoice_id == invoice.id, Charge.status != "voided").order_by(Charge.id)
    ).all()
    payer = clients.service.get(session, invoice.bill_to_client_id) if invoice.bill_to_client_id else None
    cfg = catalogue.settings_for(session, invoice.location_id)
    return {
        "invoice_id": invoice.id, "number": invoice.number, "status": invoice.status, "invoice_on": invoice.invoice_on,
        "due_on": invoice.due_on, "bill_to_client_id": invoice.bill_to_client_id,
        "bill_to_name": clients.service.display_name(payer) if payer else None,
        "organization_name": invoice.organization_name, "comments": invoice.comments, "currency": _currency(session),
        "total_minor": invoice.total_minor, "balance_minor": invoice.balance_minor,
        "paid_minor": invoice.total_minor - invoice.balance_minor, "footer": cfg.invoice_footer,
        "lines": [
            {
                "charge_id": c.id, "description": c.description, "additional_description": c.additional_description,
                "quantity": c.quantity, "unit_price_minor": c.unit_price_minor, "discount_minor": c.discount_minor,
                "net_minor": c.net_minor, "tax_minor": c.tax_minor, "total_minor": c.total_minor,
            }
            for c in charges
        ],
        "instalments": [
            {"due_on": row.due_on, "amount_minor": row.amount_minor, "covered_minor": row.covered_minor}
            for row in service.schedule_of(session, invoice.id)
        ],
    }  # fmt: skip


def get_invoice_document(session: Session, principal: Principal, invoice_id: UUID) -> dict:
    authorize(principal, "billing.invoice.read")
    return invoice_document(session, service._get(session, Invoice, invoice_id))


def invoice_pdf(document: dict, organization_session: Session) -> bytes:
    """The invoice document as a PDF (BIL-10): exactly the lines and totals of `invoice_document`."""
    currency = document["currency"]
    bill_to = document["bill_to_name"] or "-"
    if document["organization_name"]:
        bill_to = f"{bill_to}, {document['organization_name']}"
    doc = _pdf(f"Invoice {document['number']}", organization_session, subtitle=f"Bill to: {bill_to}",
               footer=document["footer"])  # fmt: skip
    doc.fields([
        ("Invoice date", pdf.local_date(document["invoice_on"])), ("Due", pdf.local_date(document["due_on"])),
        ("Status", document["status"].replace("_", " ")),
    ])  # fmt: skip
    doc.table(
        [pdf.Column("Item"), pdf.Column("Qty", 14, "R"), pdf.Column("Price", 26, "R"), pdf.Column("Discount", 24, "R"),
         pdf.Column("Tax", 22, "R"), pdf.Column("Total", 28, "R")],
        [(line["description"] + (f" - {line['additional_description']}" if line["additional_description"] else ""),
          line["quantity"], pdf.money(line["unit_price_minor"], currency), pdf.money(line["discount_minor"], currency),
          pdf.money(line["tax_minor"], currency), pdf.money(line["total_minor"], currency))
         for line in document["lines"]],
        empty="No items.",
    )  # fmt: skip
    doc.fields([
        ("Total", pdf.money(document["total_minor"], currency)), ("Paid", pdf.money(document["paid_minor"], currency)),
        ("Balance due", pdf.money(document["balance_minor"], currency)),
    ])  # fmt: skip
    if document["instalments"]:
        doc.heading("Payment schedule")
        doc.table(
            [pdf.Column("Due"), pdf.Column("Amount", 40, "R"), pdf.Column("Paid", 40, "R")],
            [(pdf.local_date(row["due_on"]), pdf.money(row["amount_minor"], currency),
              pdf.money(row["covered_minor"], currency)) for row in document["instalments"]],
        )  # fmt: skip
    if document["comments"]:
        doc.heading("Comments").text(document["comments"])
    return doc.output()


def get_invoice_pdf(session: Session, principal: Principal, invoice_id: UUID) -> tuple[str, bytes]:
    authorize(principal, "billing.invoice.read")
    document = invoice_document(session, service._get(session, Invoice, invoice_id))
    return f"invoice-{document['number']}.pdf", invoice_pdf(document, session)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_pay_link(session: Session, invoice: Invoice) -> str:
    """A link that lets whoever holds it pay this one invoice without signing in. The token is random, only
    its hash is stored, it expires, and the payment it produces uses it up. It rides in the URL fragment so
    it never reaches a server log or a Referer header (security-baseline 17.2)."""
    token = secrets.token_urlsafe(32)
    session.add(
        InvoicePayLink(
            invoice_id=invoice.id, token_hash=_hash(token), expires_at=clock.now() + timedelta(days=PAY_LINK_DAYS)
        )
    )
    session.flush()
    return f"{get_settings().app.web_base_url}/pay#token={token}"


def send_invoice(session: Session, principal: Principal, invoice_id: UUID, data: dict) -> BillingDocumentDelivery:
    """Email an invoice with a pay link (when something is owed), or record that it was printed or
    downloaded."""
    authorize(principal, "billing.invoice.send")
    invoice = service._get(session, Invoice, invoice_id)
    if invoice.status == "voided":
        raise Conflict("This invoice is voided.", code="invoice-voided")
    to_email = _recipient(session, invoice.bill_to_client_id, data.get("to_email"), data["channel"])
    document = invoice_document(session, invoice)
    name = f"invoice-{invoice.number}.pdf"
    row = _deliver(session, "invoice", data["channel"], to_email, invoice_pdf(document, session), name,
                   invoice_id=invoice.id)  # fmt: skip
    if to_email:
        cfg, currency = catalogue.settings_for(session, invoice.location_id), document["currency"]
        pay = f"\n\nPay online:\n{create_pay_link(session, invoice)}" if invoice.balance_minor > 0 else ""
        notifications.send(
            session, "billing.invoice", to_email,
            {
                "subject": cfg.invoice_email_subject.replace("{invoice_number}", str(invoice.number)),
                "facility": platform.service.get_tenant(session).name, "invoice_number": invoice.number,
                "lines": "\n".join(
                    f"{line['description']}: {money(line['total_minor'], currency)}" for line in document["lines"]
                ),
                "total": money(invoice.total_minor, currency), "balance": money(invoice.balance_minor, currency),
                "due_on": invoice.due_on.isoformat(), "pay": pay, "footer": _footer(cfg.invoice_footer),
                "document_link": portal_link(f"/portal/invoices?invoice={invoice.id}"),
            },
        )  # fmt: skip
    audit.record(
        session, "billing.invoice.send", invoice, location_id=invoice.location_id,
        changes={"channel": [None, data["channel"]], "to_email": True},
    )  # fmt: skip
    return row


def list_invoice_deliveries(session: Session, principal: Principal, invoice_id: UUID) -> list:
    authorize(principal, "billing.invoice.read")
    invoice = service._get(session, Invoice, invoice_id)
    return list(
        session.scalars(
            select(BillingDocumentDelivery)
            .where(BillingDocumentDelivery.invoice_id == invoice.id)
            .order_by(BillingDocumentDelivery.created_at.desc())
        )
    )


class LinkInvalid(DomainError):
    """One answer for unknown, expired and used links, so the endpoint is no oracle for guessing tokens."""

    status, code = 404, "link-invalid"


def _link(session: Session, token: str, *, lock: bool = False) -> tuple[InvoicePayLink, Invoice]:
    stmt = select(InvoicePayLink).where(InvoicePayLink.token_hash == _hash(token))
    link = session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    if link is None or link.used_at is not None or link.expires_at <= clock.now():
        raise LinkInvalid("This link is not valid any more.")
    return link, session.get(Invoice, link.invoice_id)


def invoice_by_link(session: Session, token: str) -> dict:
    """What the pay page shows. Reading does not use the link up."""
    _, invoice = _link(session, token)
    document = invoice_document(session, invoice)
    shown = {
        key: document[key]
        for key in ("number", "status", "invoice_on", "due_on", "bill_to_name", "currency", "total_minor",
                    "balance_minor", "lines")
    }  # fmt: skip
    try:
        account = service._provider_account(session)
        shown["provider"] = account.provider
        shown |= payment_provider.browser_keys(account.provider, account.provider_account_ref)
    except Conflict:
        shown["provider"] = None
    return shown


def pay_by_link(session: Session, token: str, *, method_token: str, idempotency_key: str) -> Payment:
    """Pay the invoice's whole balance by card through its emailed link. The link is single-use: a payment
    that succeeds (or is pending) consumes it; a decline leaves it usable for another try."""
    link, invoice = _link(session, token, lock=True)
    invoice = service._lock(session, Invoice, invoice.id)
    if invoice.status not in ("open", "partially_paid") or invoice.balance_minor <= 0:
        raise Conflict("Nothing is owed on this invoice.", code="invoice-not-payable")
    if session.info.get("actor") is None:  # anonymous surface: the audit trail names the link, not a person
        session.info["actor"] = system_principal("pay link")
    payment = service.take_payment(
        session, client_id=invoice.bill_to_client_id, location_id=invoice.location_id,
        amount_minor=invoice.balance_minor, tender_kind="card", method_token=method_token, origin="portal",
        invoice_id=invoice.id, idempotency_key=f"paylink:{link.id}:{idempotency_key}",
    )  # fmt: skip
    if payment.status in ("succeeded", "processing"):
        link.used_at, link.payment_id = clock.now(), payment.id
        session.flush()
    return payment


# --- receipts ----------------------------------------------------------------------------------------------


def receipt(session: Session, payment: Payment) -> dict:
    """Received, applied, refunded and what is left on account (PAY-03)."""
    applied = session.execute(
        select(PaymentAllocation.amount_minor, Charge.description, Charge.invoice_id)
        .join(Charge, Charge.id == PaymentAllocation.charge_id)
        .where(PaymentAllocation.payment_id == payment.id, PaymentAllocation.status == "applied")
        .order_by(PaymentAllocation.id)
    ).all()
    refunded = service._int(
        session,
        select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
            Refund.payment_id == payment.id, Refund.status == "succeeded"
        ),
    )
    return {
        "payment_id": payment.id, "receipt_number": payment.receipt_number, "status": payment.status,
        "client_id": payment.client_id, "tender_kind": payment.tender_kind, "currency": payment.currency,
        "received_at": payment.received_at, "received_minor": payment.amount_minor,
        "applied_minor": sum(row.amount_minor for row in applied), "refunded_minor": refunded,
        "unapplied_minor": payment.unapplied_minor, "card_brand": payment.card_brand, "card_last4": payment.card_last4,
        "footer": catalogue.settings_for(session, payment.location_id).receipt_footer,
        "lines": [
            {"description": row.description, "invoice_id": row.invoice_id, "amount_minor": row.amount_minor}
            for row in applied
        ],
    }  # fmt: skip


def get_receipt(session: Session, principal: Principal, payment_id: UUID) -> dict:
    authorize(principal, "billing.payment.read")
    return receipt(session, service._get(session, Payment, payment_id))


def receipt_pdf(session: Session, payment: Payment) -> bytes:
    """The receipt as a PDF (PAY-03): received, what it paid, refunds and what is left on account. The
    received date is the location's day."""
    document, currency = receipt(session, payment), payment.currency
    payer = clients.service.get(session, payment.client_id) if payment.client_id else None
    tender = payment.tender_kind.replace("_", " ")
    if payment.card_last4:
        tender = f"{tender} ({payment.card_brand or 'card'} ending {payment.card_last4})"
    doc = _pdf(f"Receipt {payment.receipt_number}", session,
               subtitle=f"Received from: {clients.service.display_name(payer) if payer else '-'}",
               footer=document["footer"])  # fmt: skip
    doc.fields([
        ("Received on", pdf.local_date(payment.received_at, _zone(session, payment.location_id))),
        ("Amount", pdf.money(payment.amount_minor, currency)), ("Paid by", tender),
        ("Status", payment.status.replace("_", " ")),
    ])  # fmt: skip
    doc.heading("Applied to")
    doc.table(
        [pdf.Column("Item"), pdf.Column("Amount", 40, "R")],
        [(line["description"], pdf.money(line["amount_minor"], currency)) for line in document["lines"]],
        empty="Nothing yet: the payment is on account.",
    )  # fmt: skip
    doc.fields([
        ("Applied", pdf.money(document["applied_minor"], currency)),
        ("Refunded", pdf.money(document["refunded_minor"], currency)),
        ("On account", pdf.money(document["unapplied_minor"], currency)),
    ])  # fmt: skip
    return doc.output()


def get_receipt_pdf(session: Session, principal: Principal, payment_id: UUID) -> tuple[str, bytes]:
    authorize(principal, "billing.payment.read")
    payment = service._get(session, Payment, payment_id)
    return f"receipt-{payment.receipt_number}.pdf", receipt_pdf(session, payment)


def send_receipt(session: Session, principal: Principal, payment_id: UUID, data: dict) -> BillingDocumentDelivery:
    authorize(principal, "billing.invoice.send")
    payment = service._get(session, Payment, payment_id)
    if payment.status not in ("succeeded", "voided", "disputed", "charged_back"):
        raise Conflict("A receipt exists once the payment has settled.", code="payment-not-settled")
    to_email = _recipient(session, payment.client_id, data.get("to_email"), data["channel"])
    name = f"receipt-{payment.receipt_number}.pdf"
    row = _deliver(session, "receipt", data["channel"], to_email, receipt_pdf(session, payment), name,
                   payment_id=payment.id)  # fmt: skip
    if to_email:
        document, currency = receipt(session, payment), payment.currency
        notifications.send(
            session, "billing.receipt", to_email,
            {
                "facility": platform.service.get_tenant(session).name, "receipt_number": payment.receipt_number,
                "received": money(payment.amount_minor, currency), "tender": payment.tender_kind.replace("_", " "),
                "received_on": pdf.local_date(payment.received_at, _zone(session, payment.location_id)),
                "applied": money(document["applied_minor"], currency),
                "refunded": money(document["refunded_minor"], currency),
                "unapplied": money(payment.unapplied_minor, currency), "footer": _footer(document["footer"]),
                "document_link": portal_link("/portal/invoices"),
            },
        )  # fmt: skip
    return row


# --- client summary and statements -------------------------------------------------------------------------


def billing_summary(session: Session, client_id: UUID) -> dict:
    """A payer's standing, computed from the rows (ADR 0003 section 2): credit on account, open invoice
    balance, the part of it that is past due, and what is billed but not yet invoiced."""
    owed = session.execute(
        select(
            func.coalesce(func.sum(Invoice.balance_minor), 0),
            func.coalesce(func.sum(Invoice.balance_minor).filter(Invoice.past_due_since_on.is_not(None)), 0),
            func.min(Invoice.past_due_since_on),
        ).where(
            Invoice.bill_to_client_id == client_id, Invoice.status.in_(("open", "partially_paid", "payment_pending"))
        )
    ).one()
    uninvoiced = service._int(
        session,
        select(func.coalesce(func.sum(Charge.total_minor - Charge.applied_minor), 0)).where(
            Charge.client_id == client_id, Charge.invoice_id.is_(None), Charge.status == "active"
        ),
    )
    return {
        "client_id": client_id, "currency": _currency(session), "credit_minor": service.credit_balance(session, client_id),
        "open_balance_minor": int(owed[0]), "past_due_minor": int(owed[1]), "oldest_past_due_on": owed[2],
        "uninvoiced_minor": uninvoiced,
    }  # fmt: skip


def get_billing_summary(session: Session, principal: Principal, client_id: UUID) -> dict:
    authorize(principal, "billing.invoice.read")
    clients.service.get(session, client_id)
    return billing_summary(session, client_id)


def get_account_credit(session: Session, principal: Principal, client_id: UUID) -> dict:
    """The pooled credit and the payments it sits on (the reference's "Unused" column per payment)."""
    authorize(principal, "billing.payment.read")
    clients.service.get(session, client_id)
    payments = session.scalars(
        select(Payment)
        .where(Payment.client_id == client_id, Payment.status == "succeeded", Payment.unapplied_minor > 0)
        .order_by(Payment.received_at, Payment.id)
    ).all()
    return {
        "client_id": client_id, "currency": _currency(session),
        "credit_minor": sum(payment.unapplied_minor for payment in payments), "payments": payments,
    }  # fmt: skip


def statement(session: Session, client_id: UUID, from_on: date, to_on: date, basis: str = "invoice_date") -> dict:
    """A payer's invoices, payments and refunds in a period (BIL-11). Voided invoices and voided payments are
    left out. `basis` picks whether invoices are selected by invoice date or due date. The period's days are
    the payer's home location's days, so a payment at 23:30 there on `to_on` is inside."""
    if to_on < from_on or (to_on - from_on).days > MAX_STATEMENT_DAYS:
        raise ValidationFailed("A statement covers at most 366 days.", pointer="/to_on")
    column = Invoice.due_on if basis == "due_date" else Invoice.invoice_on
    invoices = session.scalars(
        select(Invoice)
        .where(Invoice.bill_to_client_id == client_id, Invoice.status != "voided", column.between(from_on, to_on))
        .order_by(column, Invoice.number)
    ).all()
    zone = _zone(session, clients.service.get(session, client_id).home_location_id)
    start, end = _local_day(zone, from_on), _local_day(zone, to_on + timedelta(days=1))
    payments = session.scalars(
        select(Payment)
        .where(
            Payment.client_id == client_id,
            Payment.status.in_(("succeeded", "processing")),
            Payment.received_at >= start,
            Payment.received_at < end,
        )  # fmt: skip
        .order_by(Payment.received_at)
    ).all()
    refunds = session.scalars(
        select(Refund)
        .where(Refund.client_id == client_id, Refund.status == "succeeded", Refund.refund_on.between(from_on, to_on))
        .order_by(Refund.refund_on)
    ).all()
    summary = billing_summary(session, client_id)
    return {
        "client_id": client_id, "from_on": from_on, "to_on": to_on, "date_basis": basis, "time_zone": zone,
        "currency": summary["currency"], "invoices": invoices, "payments": payments, "refunds": refunds,
        "invoiced_minor": sum(invoice.total_minor for invoice in invoices),
        "paid_minor": sum(payment.amount_minor for payment in payments),
        "refunded_minor": sum(row.amount_minor for row in refunds),
        "balance_due_minor": summary["open_balance_minor"], "credit_minor": summary["credit_minor"],
    }  # fmt: skip


def get_statement(
    session: Session, principal: Principal, client_id: UUID, from_on: date | None, to_on: date | None, basis: str
):
    """Default period: the 30 days up to today at the client's home location."""
    authorize(principal, "billing.invoice.read")
    home = clients.service.get(session, client_id).home_location_id
    to_on = to_on or (
        platform.service.location_today(session, home) if home else platform.service.earliest_today(session)
    )
    return statement(session, client_id, from_on or to_on - timedelta(days=30), to_on, basis)


def statement_pdf(session: Session, document: dict) -> bytes:
    """The statement as a PDF (BIL-11); dates are the payer's home location's days."""
    client = clients.service.get(session, document["client_id"])
    currency, zone = document["currency"], document["time_zone"]
    period = f"{pdf.local_date(document['from_on'])} to {pdf.local_date(document['to_on'])}"
    cfg = catalogue.settings_for(session, client.home_location_id)
    doc = _pdf(f"Statement for {clients.service.display_name(client)}", session, subtitle=f"Period: {period}",
               footer=cfg.statement_footer)  # fmt: skip
    doc.heading("Invoices")
    doc.table(
        [pdf.Column("Invoice", 24), pdf.Column("Date", 28), pdf.Column("Due", 28), pdf.Column("Status"),
         pdf.Column("Total", 32, "R"), pdf.Column("Balance", 32, "R")],
        [(row.number, pdf.local_date(row.invoice_on), pdf.local_date(row.due_on), row.status.replace("_", " "),
          pdf.money(row.total_minor, currency), pdf.money(row.balance_minor, currency))
         for row in document["invoices"]],
        empty="No invoices in this period.",
    )  # fmt: skip
    doc.heading("Payments")
    doc.table(
        [pdf.Column("Receipt", 24), pdf.Column("Date", 28), pdf.Column("Paid by"), pdf.Column("Amount", 32, "R")],
        [(row.receipt_number, pdf.local_date(row.received_at, zone), row.tender_kind.replace("_", " "),
          pdf.money(row.amount_minor, currency)) for row in document["payments"]],
        empty="No payments in this period.",
    )  # fmt: skip
    if document["refunds"]:
        doc.heading("Refunds")
        doc.table(
            [pdf.Column("Date"), pdf.Column("Amount", 32, "R")],
            [(pdf.local_date(row.refund_on), pdf.money(row.amount_minor, currency)) for row in document["refunds"]],
        )  # fmt: skip
    doc.fields([
        ("Invoiced", pdf.money(document["invoiced_minor"], currency)),
        ("Paid", pdf.money(document["paid_minor"], currency)),
        ("Refunded", pdf.money(document["refunded_minor"], currency)),
        ("Balance due", pdf.money(document["balance_due_minor"], currency)),
        ("Credit on account", pdf.money(document["credit_minor"], currency)),
    ])  # fmt: skip
    return doc.output()


def statement_name(document: dict) -> str:
    return f"statement-{document['from_on'].isoformat()}-{document['to_on'].isoformat()}.pdf"


def get_statement_pdf(
    session: Session, principal: Principal, client_id: UUID, from_on: date | None, to_on: date | None, basis: str
) -> tuple[str, bytes]:
    document = get_statement(session, principal, client_id, from_on, to_on, basis)
    return statement_name(document), statement_pdf(session, document)


def email_statement(session: Session, client, document: dict, to_email: str) -> None:
    """Internal: the statement email, also sent by statement batches."""
    cfg, currency = catalogue.settings_for(session, client.home_location_id), document["currency"]
    facility = platform.service.get_tenant(session).name
    notifications.send(
        session, "billing.statement", to_email,
        {
            "subject": cfg.statement_email_subject or f"Your statement from {facility}",
            "intro": cfg.statement_email_body or f"Here is your statement from {facility}.",
            "period": f"{document['from_on'].isoformat()} to {document['to_on'].isoformat()}",
            "lines": "\n".join(
                f"Invoice {invoice.number} ({invoice.invoice_on.isoformat()}): "
                f"{money(invoice.total_minor, currency)}, balance {money(invoice.balance_minor, currency)}"
                for invoice in document["invoices"]
            ) or "No invoices in this period.",
            "invoiced": money(document["invoiced_minor"], currency), "paid": money(document["paid_minor"], currency),
            "balance": money(document["balance_due_minor"], currency),
            "credit": money(document["credit_minor"], currency), "footer": _footer(cfg.statement_footer),
            "document_link": portal_link(
                f"/portal/statement?from_on={document['from_on'].isoformat()}&to_on={document['to_on'].isoformat()}"
            ),
        },
    )  # fmt: skip


def send_statement(session: Session, principal: Principal, client_id: UUID, data: dict) -> BillingDocumentDelivery:
    """Email one client their statement. Many at once: `statements.create_batch`."""
    authorize(principal, "billing.statement.send")
    client = clients.service.get(session, client_id)
    document = statement(session, client_id, data["from_on"], data["to_on"], data.get("date_basis", "invoice_date"))
    to_email = _recipient(session, client_id, data.get("to_email"), "email")
    row = _deliver(session, "statement", "email", to_email, statement_pdf(session, document),
                   statement_name(document), client_id=client_id)  # fmt: skip
    email_statement(session, client, document, to_email)
    audit.record(session, "billing.statement.send", row, changes={"to_email": True})
    return row


# --- accounts receivable ageing (BIL-19) -------------------------------------------------------------------


def receivables_ageing(
    session: Session, principal: Principal, *, as_of: date | None = None, location_id: UUID | None = None
) -> dict:
    """Who owes what, by how long it has been due, as at a date.

    A charge counts if it was billed on or before `as_of` (default: the earliest location's today) and had not
    been reversed or voided by the end of that day at its location; what
    it owed then is its total minus the allocations that were applied by then and not yet released (the
    "payments up to" cut). It is aged from its invoice's due date, or from its bill date while uninvoiced.
    """
    authorize(principal, "billing.invoice.read")
    if as_of is None:
        as_of = (platform.service.location_today(session, location_id) if location_id
                 else platform.service.earliest_today(session))  # fmt: skip
    # The day ends at midnight on each charge's location's wall clock.
    locations = session.scalars(select(Charge.location_id).distinct()).all()
    cut = case(
        {loc: _local_day(_zone(session, loc), as_of + timedelta(days=1)) for loc in locations},
        value=Charge.location_id,
    ) if locations else _local_day("UTC", as_of + timedelta(days=1))  # fmt: skip
    paid = (
        select(func.coalesce(func.sum(PaymentAllocation.amount_minor), 0))
        .where(
            PaymentAllocation.charge_id == Charge.id,
            PaymentAllocation.applied_at < cut,
            or_(PaymentAllocation.released_at.is_(None), PaymentAllocation.released_at >= cut),
        )  # fmt: skip
        .correlate(Charge)
        .scalar_subquery()
    )
    undone = func.coalesce(Charge.reversed_at, Charge.voided_at)
    stmt = (
        select(Charge.client_id, func.coalesce(Invoice.due_on, Charge.bill_on), Charge.total_minor - paid)
        .outerjoin(Invoice, and_(Invoice.id == Charge.invoice_id, Invoice.status != "voided"))
        .where(Charge.kind != "reversal", Charge.bill_on <= as_of, or_(undone.is_(None), undone >= cut))
    )
    stmt = scope_query(stmt, principal, Charge.location_id)
    if location_id is not None:
        stmt = stmt.where(Charge.location_id == location_id)
    by_client: dict = defaultdict(lambda: dict.fromkeys(AGEING_BUCKETS, 0))
    for client_id, due_on, owed in session.execute(stmt):
        if owed:
            by_client[client_id][ageing_bucket(due_on, as_of)] += int(owed)
    rows = [
        {"client_id": client_id, **buckets, "total_minor": sum(buckets.values())}
        for client_id, buckets in by_client.items()
    ]
    rows.sort(key=lambda row: -row["total_minor"])
    totals = {bucket: sum(row[bucket] for row in rows) for bucket in AGEING_BUCKETS}
    return {
        "as_of": as_of, "currency": _currency(session), "rows": rows,
        "totals": {**totals, "total_minor": sum(totals.values())},
    }  # fmt: skip


# --- billing history (BIL-09) ------------------------------------------------------------------------------


def list_history(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Who did what to which invoice, item or payment: the audit events billing wrote, newest first."""
    authorize(principal, "billing.history.read")
    stmt = select(AuditEvent).where(AuditEvent.action.like("billing.%"))
    if principal.kind != "system" and principal.location_ids is not None:
        stmt = stmt.where(AuditEvent.location_id.in_(principal.location_ids))
    return paginate(
        session, stmt, query, id_column=AuditEvent.id,
        sort_fields={"occurred_at": AuditEvent.occurred_at}, default_sort="-occurred_at",
        filter_fields={
            "entity_type": AuditEvent.entity_type, "entity_id": AuditEvent.entity_id, "action": AuditEvent.action,
            "location_id": AuditEvent.location_id,
        },
    )  # fmt: skip


# --- bulk invoicing (BIL-02) -------------------------------------------------------------------------------


def bulk_invoice(session: Session, principal: Principal, data: dict) -> dict:
    """Invoice many uninvoiced items at once: ONE INVOICE PER CLIENT. Items of different clients are never
    put on one payer's invoice (the reference bills a mixed selection to the first client; overview
    divergence 6). Give `charge_ids`, or a `location_id` to take everything uninvoiced there (optionally only
    what you added, `only_mine`: the per-user "cart").

    Each client is its own savepoint: a failure is reported on that client's row and the others still go
    through. With `is_dry_run` nothing is created and the same rows show what would happen.
    """
    stmt = select(Charge).where(Charge.invoice_id.is_(None), Charge.status == "active", Charge.kind != "reversal")
    if data.get("charge_ids"):
        stmt = stmt.where(Charge.id.in_(data["charge_ids"]))
    elif data.get("location_id"):
        stmt = stmt.where(Charge.location_id == data["location_id"])
        if data.get("only_mine"):
            stmt = stmt.where(Charge.created_by_staff_user_id == principal.staff_user_id)
    else:
        raise ValidationFailed("Select items or a location.", pointer="/charge_ids")
    charges = session.scalars(scope_query(stmt, principal, Charge.location_id).order_by(Charge.id)).all()
    groups: dict = defaultdict(list)
    for charge in charges:
        authorize(principal, "billing.invoice.bulk_create", location_id=charge.location_id)
        groups[(charge.client_id, charge.location_id)].append(charge)
    found = {charge.id for charge in charges}
    items = [
        {"client_id": None, "location_id": None, "charge_ids": [charge_id], "total_minor": 0, "invoice_id": None,
         "status": "skipped", "error_code": "charge-not-invoiceable"}
        for charge_id in data.get("charge_ids") or [] if charge_id not in found
    ]  # fmt: skip
    for (client_id, location_id), group in groups.items():
        item = {
            "client_id": client_id, "location_id": location_id, "charge_ids": [charge.id for charge in group],
            "total_minor": sum(charge.total_minor for charge in group), "invoice_id": None, "status": "pending",
            "error_code": None,
        }  # fmt: skip
        if not data.get("is_dry_run"):
            try:
                with session.begin_nested():
                    invoice = service.create_invoice_for_charges(
                        session, item["charge_ids"], due_on=data.get("due_on"),
                        is_autopay=bool(data.get("is_autopay")),
                    )  # fmt: skip
                item["invoice_id"], item["status"] = invoice.id, "done"
            except DomainError as error:
                item["status"], item["error_code"] = "failed", error.code
        items.append(item)
    return {"is_dry_run": bool(data.get("is_dry_run")), "items": items}
