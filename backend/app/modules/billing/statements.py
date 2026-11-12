"""Statement batches (BIL-11): statements for many payers at once, each recipient with its own outcome.

A batch picks the payers with a non-voided invoice at its location in the period (by invoice or due date;
`is_open_only` keeps only invoices that still owe), optionally narrowed to `client_filter.client_ids`. Each
recipient gets the statement PDF stored and, when they have an email address, the statement email; without
one the row is `skipped_no_email`. A small batch runs in the request; a larger one is a background job.
A failure is kept on its recipient row and the others still go out; `resend` retries.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, scope_query, system_principal
from app.core.db import tenant_session
from app.core.errors import Conflict, DomainError, ValidationFailed
from app.core.jobs import tenant_actor
from app.core.pagination import ListQuery, paginate
from app.modules import clients, platform
from app.modules.billing import documents, service
from app.modules.billing.events import StatementBatchCompleted
from app.modules.billing.models import Invoice, StatementBatch, StatementRecipient

KEY = "billing.statement.send"
IN_REQUEST_LIMIT = 25  # more recipients than this run as a job
_OPEN = ("open", "partially_paid", "payment_pending")
_RETRY = ("failed", "skipped_no_email")


def _payers(session: Session, batch: StatementBatch) -> list[UUID]:
    column = Invoice.due_on if batch.date_basis == "due_date" else Invoice.invoice_on
    stmt = (
        select(Invoice.bill_to_client_id)
        .distinct()
        .where(
            Invoice.location_id == batch.location_id,
            Invoice.bill_to_client_id.is_not(None),
            Invoice.status != "voided",
            column.between(batch.period_from_on, batch.period_to_on),
        )  # fmt: skip
    )
    if batch.is_open_only:
        stmt = stmt.where(Invoice.status.in_(_OPEN), Invoice.balance_minor > 0)
    if ids := batch.client_filter.get("client_ids"):
        stmt = stmt.where(Invoice.bill_to_client_id.in_([UUID(str(i)) for i in ids]))
    return list(session.scalars(stmt.order_by(Invoice.bill_to_client_id)))


def create_batch(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, KEY, location_id=data["location_id"])
    from_on, to_on = data["period_from_on"], data["period_to_on"]
    if to_on < from_on or (to_on - from_on).days > documents.MAX_STATEMENT_DAYS:
        raise ValidationFailed("A statement covers at most 366 days.", pointer="/period_to_on")
    if not platform.service.location_exists(session, data["location_id"]):
        raise ValidationFailed("Unknown location.", pointer="/location_id")
    client_ids = [str(i) for i in data.get("client_ids") or []]
    batch = StatementBatch(
        location_id=data["location_id"], period_from_on=from_on, period_to_on=to_on, date_basis=data["date_basis"],
        is_open_only=data["is_open_only"], client_filter={"client_ids": client_ids} if client_ids else {},
        requested_by_staff_user_id=service._staff_id(session),
    )  # fmt: skip
    session.add(batch)
    session.flush()
    payers = _payers(session, batch)
    session.add_all(StatementRecipient(statement_batch_id=batch.id, client_id=client_id) for client_id in payers)
    session.flush()
    audit.record(
        session, KEY, batch, location_id=batch.location_id,
        changes={"period_from_on": [None, str(from_on)], "period_to_on": [None, str(to_on)],
                 "recipients": [None, len(payers)]},
    )  # fmt: skip
    _run_or_enqueue(session, batch, len(payers))
    return batch_view(session, batch)


def _run_or_enqueue(session: Session, batch: StatementBatch, count: int) -> None:
    if count <= IN_REQUEST_LIMIT:
        run_batch(session, batch.id)
        return
    tenant_id, batch_id = str(session.info["tenant_id"]), str(batch.id)
    session.info.setdefault("after_commit", []).append(lambda: run_statement_batch.send(tenant_id, batch_id))


def run_batch(session: Session, batch_id: UUID) -> None:
    """Send every queued recipient. Idempotent: a rerun only touches rows still queued, and a redelivered job
    that finds none leaves the finished batch (and its event) alone."""
    batch = service._get(session, StatementBatch, batch_id, lock=True)
    queued = session.scalars(
        select(StatementRecipient)
        .where(StatementRecipient.statement_batch_id == batch.id, StatementRecipient.status == "queued")
        .order_by(StatementRecipient.id)
    ).all()
    if not queued and batch.status == "completed":
        return
    batch.status = "running"
    for recipient in queued:
        try:
            with session.begin_nested():
                _send(session, batch, recipient)
        except DomainError as error:
            recipient.status, recipient.failure_message = "failed", error.detail or error.code
        except Exception as error:  # noqa: BLE001 (one recipient's fault must not stop the others)
            recipient.status, recipient.failure_message = "failed", f"Could not send: {type(error).__name__}"
    counts = dict(
        session.execute(
            select(StatementRecipient.status, func.count())
            .where(StatementRecipient.statement_batch_id == batch.id)
            .group_by(StatementRecipient.status)
        ).all()
    )
    batch.status, batch.finished_at = "completed", clock.now()
    session.flush()
    events.publish(
        session,
        StatementBatchCompleted(
            statement_batch_id=batch.id, location_id=batch.location_id, sent_count=counts.get("sent", 0),
            failed_count=counts.get("failed", 0), skipped_count=counts.get("skipped_no_email", 0),
        ),
        batch.id,
    )  # fmt: skip


def _send(session: Session, batch: StatementBatch, recipient: StatementRecipient) -> None:
    client = clients.service.get(session, recipient.client_id)
    document = documents.statement(session, client.id, batch.period_from_on, batch.period_to_on, batch.date_basis)
    stored = documents.store_pdf(
        session, documents.statement_pdf(session, document), "statement", documents.statement_name(document)
    )
    recipient.stored_file_id, recipient.to_email, recipient.failure_message = stored.id, client.primary_email, None
    if not client.primary_email:
        recipient.status = "skipped_no_email"
    else:
        documents.email_statement(session, client, document, client.primary_email)
        recipient.status, recipient.sent_at = "sent", clock.now()
    session.flush()


@tenant_actor(max_retries=3)
def run_statement_batch(session: Session, statement_batch_id: str) -> None:
    try:
        run_batch(session, UUID(statement_batch_id))
    except Exception:
        # The job's own transaction rolls back; record the failure apart so the batch never sits queued.
        # A retry sets it running again and finishes the rows still queued.
        with tenant_session(session.info["tenant_id"], actor=system_principal("run_statement_batch")) as other:
            other.get(StatementBatch, UUID(statement_batch_id)).status = "failed"
        raise


def _load(session: Session, principal: Principal, batch_id: UUID) -> StatementBatch:
    batch = service._get(session, StatementBatch, batch_id)
    authorize(principal, KEY, location_id=batch.location_id)
    return batch


def resend(session: Session, principal: Principal, batch_id: UUID, data: dict) -> dict:
    """Send again to the given recipients, or to every failed and skipped one (an address may have been
    added since)."""
    batch = _load(session, principal, batch_id)
    if batch.status not in ("completed", "failed"):
        raise Conflict("The batch is still sending; resend once it has finished.")
    stmt = select(StatementRecipient).where(StatementRecipient.statement_batch_id == batch.id)
    ids = data.get("statement_recipient_ids")
    stmt = stmt.where(StatementRecipient.id.in_(ids)) if ids else stmt.where(StatementRecipient.status.in_(_RETRY))
    rows = session.scalars(stmt).all()
    for row in rows:
        row.status = "queued"
    batch.status, batch.finished_at = "queued", None
    session.flush()
    audit.record(session, KEY, batch, location_id=batch.location_id, changes={"resent": [None, len(rows)]})
    _run_or_enqueue(session, batch, len(rows))
    return batch_view(session, batch)


def batch_view(session: Session, batch: StatementBatch) -> dict:
    rows = session.scalars(
        select(StatementRecipient)
        .where(StatementRecipient.statement_batch_id == batch.id)
        .order_by(StatementRecipient.id)
    ).all()
    names = {row.client_id: clients.service.display_name(clients.service.get(session, row.client_id)) for row in rows}
    counts = {status: sum(1 for row in rows if row.status == status) for status in ("queued", "sent", "failed",
                                                                                    "skipped_no_email")}  # fmt: skip
    return {
        "id": batch.id, "location_id": batch.location_id, "period_from_on": batch.period_from_on,
        "period_to_on": batch.period_to_on, "date_basis": batch.date_basis, "is_open_only": batch.is_open_only,
        "status": batch.status, "created_at": batch.created_at, "finished_at": batch.finished_at,
        "recipient_count": len(rows), "sent_count": counts["sent"], "failed_count": counts["failed"],
        "skipped_count": counts["skipped_no_email"], "queued_count": counts["queued"],
        "recipients": [
            {"id": row.id, "client_id": row.client_id, "client_name": names[row.client_id], "to_email": row.to_email,
             "status": row.status, "failure_message": row.failure_message, "sent_at": row.sent_at}
            for row in rows
        ],
    }  # fmt: skip


def get_batch(session: Session, principal: Principal, batch_id: UUID) -> dict:
    return batch_view(session, _load(session, principal, batch_id))


def list_batches(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, KEY)
    stmt = scope_query(select(StatementBatch), principal, StatementBatch.location_id)
    page = paginate(
        session, stmt, query, id_column=StatementBatch.id,
        sort_fields={"created_at": StatementBatch.created_at}, default_sort="-created_at",
        filter_fields={"location_id": StatementBatch.location_id, "status": StatementBatch.status},
    )  # fmt: skip
    page["data"] = [batch_view(session, batch) | {"recipients": []} for batch in page["data"]]
    return page
