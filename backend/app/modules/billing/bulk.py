"""Bulk actions from the billing-items workbench (BIL-02), stored and worked through by a chunked job.

A request authorizes the action's key at the action's location, picks the subjects there (charges, invoices or
clients, at most `MAX_ITEMS`), stores one item per subject and either runs them at once (a dry run, or at most
`IN_REQUEST_LIMIT` items) or enqueues `run_bulk_action`. Each item, or each client's group of charges when
invoicing, is its own savepoint, so one failure is reported on its row and the rest go through. The job runs as
the person or API key that started it: the principal is re-loaded and re-authorized at each chunk, so a job
outlives neither the account, its permission, nor the key.
"""

import hashlib
import json
import logging
from datetime import date
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize, deps
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.core.jobs import chunked_actor
from app.core.pagination import ListQuery, paginate
from app.modules import clients, platform
from app.modules.billing import catalog, documents, service
from app.modules.billing.models import BillingBulkAction, BillingBulkActionItem, CatalogItem, Charge, Invoice

log = logging.getLogger(__name__)
MAX_ITEMS = 1000  # the workbench's cap per action
IN_REQUEST_LIMIT = 25  # more than this runs as a job
CHUNK_ITEMS = 50  # items (or invoicing clients) per job message

KEYS = {
    "create_invoices": "billing.invoice.bulk_create",
    "reverse_charges": "billing.charge.reverse",
    "email_invoices": "billing.invoice.send",
    "render_invoices": "billing.invoice.send",
    "add_catalog_item": "billing.charge.create",
}


def _by_key(session: Session, key: str) -> BillingBulkAction | None:
    return session.scalar(select(BillingBulkAction).where(BillingBulkAction.idempotency_key == key))


def create_bulk_action(session: Session, principal: Principal, data: dict, idempotency_key: str) -> BillingBulkAction:
    action, location_id = data["action"], data["location_id"]
    authorize(principal, KEYS[action], location_id=location_id)
    service._location_in_scope(session, principal, location_id)
    request_hash = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    key = service._staff_key(principal, idempotency_key)
    if key:
        existing = _by_key(session, key)
        if existing is not None:
            if existing.request_hash != request_hash:  # a key is bound to the request that first used it
                raise Conflict("This Idempotency-Key was used for another bulk action.", code="idempotency-key-reused")
            return action_view(existing)
    params = _params(session, action, location_id, data.get("params") or {})
    subjects = _subjects(session, principal, action, location_id, data, params)
    if data.get("preview_id"):
        _check_preview(session, principal, data, subjects)
    row = BillingBulkAction(
        location_id=location_id, action=action, is_dry_run=bool(data.get("is_dry_run")), params=params,
        item_count=len(subjects), requested_by_staff_user_id=service._staff_id(session),
        requested_by_api_key_id=principal.api_key_id, idempotency_key=key,
        request_hash=request_hash,
    )  # fmt: skip
    session.add(row)
    session.flush()
    session.add_all(
        BillingBulkActionItem(
            billing_bulk_action_id=row.id, subject_type=subject_type, subject_id=subject_id, group_client_id=client_id,
            status="skipped" if error else "pending", error_code=error, amount_minor=amount,
        )
        for subject_type, subject_id, client_id, error, amount in subjects
    )  # fmt: skip
    session.flush()
    audit.record(
        session, KEYS[action], row, location_id=location_id,
        changes={"action": [None, action], "item_count": [None, len(subjects)], "is_dry_run": [None, row.is_dry_run]},
    )  # fmt: skip
    if row.is_dry_run or len(subjects) <= IN_REQUEST_LIMIT:
        while run_chunk(session, row.id):
            pass
    else:
        tenant_id, action_id = str(session.info["tenant_id"]), str(row.id)
        session.info.setdefault("after_commit", []).append(lambda: run_bulk_action.send(tenant_id, action_id))
    return action_view(row)


def _params(session: Session, action: str, location_id: UUID, params: dict) -> dict:
    if action == "reverse_charges":
        reason = str(params.get("reason") or "").strip()
        if not reason:
            raise ValidationFailed("A reversal needs a reason.", pointer="/params/reason")
        revenue_on = params.get("revenue_on")
        if revenue_on:
            try:
                date.fromisoformat(str(revenue_on))
            except ValueError:
                raise ValidationFailed("Give the revenue date as YYYY-MM-DD.", pointer="/params/revenue_on") from None
        return {"reason": reason, "revenue_on": revenue_on or None}
    if action == "add_catalog_item":
        try:
            item = service._get(session, CatalogItem, UUID(str(params.get("catalog_item_id"))))
        except (ValueError, NotFound):
            raise ValidationFailed("Choose an item to add.", pointer="/params/catalog_item_id") from None
        if item.location_id != location_id or not catalog.item_is_active(session, item.id):
            raise ValidationFailed("Choose an active item of this location.", pointer="/params/catalog_item_id")
        return {"catalog_item_id": str(item.id)}
    if action == "create_invoices":
        due_on = params.get("due_on")
        return {"due_on": due_on and str(date.fromisoformat(str(due_on))), "is_autopay": bool(params.get("is_autopay"))}
    return {}


def _check_preview(session: Session, principal: Principal, data: dict, subjects: list[tuple]) -> None:
    """A run that names its dry run must act on the same subjects at the same amounts, else 409: the person
    approved what the preview showed, not what the books say now."""
    preview = _load(session, principal, data["preview_id"])
    if not preview.is_dry_run or (preview.action, preview.location_id) != (data["action"], data["location_id"]):
        raise ValidationFailed("Name a dry run of this action at this location.", pointer="/preview_id")
    shown = dict(
        session.execute(
            select(BillingBulkActionItem.subject_id, BillingBulkActionItem.amount_minor).where(
                BillingBulkActionItem.billing_bulk_action_id == preview.id, BillingBulkActionItem.status != "skipped"
            )
        ).all()
    )
    if shown != {subject_id: amount for _, subject_id, _, error, amount in subjects if error is None}:
        raise Conflict("Items or prices changed since the preview. Preview again.", code="bulk-preview-stale")


def _subjects(
    session: Session, principal: Principal, action: str, location_id: UUID, data: dict, params: dict
) -> list[tuple]:
    """(subject_type, subject_id, group_client_id, skip error code, amount) for every subject, at the action's
    location. The amount is what a preview showed: the charge or invoice total, or the item's net fee."""
    if action in ("create_invoices", "reverse_charges"):
        wanted = data.get("charge_ids") or []
        stmt = select(Charge).where(
            Charge.location_id == location_id, Charge.status == "active", Charge.kind != "reversal"
        )
        if action == "create_invoices":
            stmt = stmt.where(Charge.invoice_id.is_(None))
        if wanted:
            stmt = stmt.where(Charge.id.in_(wanted))
        elif action == "reverse_charges":
            raise ValidationFailed("Select the items to reverse.", pointer="/charge_ids")
        elif data.get("only_mine"):
            stmt = stmt.where(Charge.created_by_staff_user_id == principal.staff_user_id)
        rows = _capped(session, stmt.order_by(Charge.client_id, Charge.id), "/charge_ids")
        found = {row.id for row in rows}
        missing = "charge-not-invoiceable" if action == "create_invoices" else "charge-not-reversible"
        return [  # a clientless (POS) charge has no payer to invoice; reversing one is fine
            (
                "charge",
                row.id,
                row.client_id,
                "charge-has-no-client" if action == "create_invoices" and row.client_id is None else None,
                row.total_minor,
            )
            for row in rows
        ] + [
            ("charge", charge_id, None, missing, None) for charge_id in dict.fromkeys(wanted) if charge_id not in found
        ]
    if action in ("email_invoices", "render_invoices"):
        wanted = data.get("invoice_ids") or []
        if not wanted:
            raise ValidationFailed("Select the invoices.", pointer="/invoice_ids")
        found_invoices = select(Invoice).where(
            Invoice.location_id == location_id, Invoice.id.in_(wanted), Invoice.status != "voided"
        )
        rows = _capped(session, found_invoices.order_by(Invoice.id), "/invoice_ids")
        found = {row.id for row in rows}
        return [("invoice", row.id, row.bill_to_client_id, None, row.total_minor) for row in rows] + [
            ("invoice", invoice_id, None, "invoice-not-found", None)
            for invoice_id in dict.fromkeys(wanted)
            if invoice_id not in found
        ]
    wanted = list(dict.fromkeys(data.get("client_ids") or []))
    if not wanted or len(wanted) > MAX_ITEMS:
        raise ValidationFailed(f"Select between 1 and {MAX_ITEMS} clients.", pointer="/client_ids")
    item = session.get(CatalogItem, UUID(params["catalog_item_id"]))
    if item is None:
        raise ValidationFailed("Choose an item of this location.", pointer="/params/catalog_item_id")
    fee = item.fee_minor - service._pct_discount(item.fee_minor, item.discount_pct, item.discount_minor or 0)
    reach = principal.location_ids  # None: every location; a key is held to its creator's (and its own)

    def reachable(client_id: UUID) -> bool:  # unknown and out-of-reach clients look the same (404 rule)
        try:
            client = clients.service.get(session, client_id)
        except NotFound:
            return False
        return reach is None or client.home_location_id in reach

    return [
        ("client", client_id, client_id, None if reachable(client_id) else "client-not-found", fee)
        for client_id in wanted
    ]


def _capped(session: Session, stmt, pointer: str) -> list:
    rows = list(session.scalars(stmt.limit(MAX_ITEMS + 1)).all())
    if len(rows) > MAX_ITEMS:
        raise ValidationFailed(f"More than {MAX_ITEMS} items. Select them a batch at a time.", pointer=pointer)
    return rows


def run_chunk(session: Session, action_id: UUID) -> bool:
    """Work through the next chunk of pending items; True while more remain. Idempotent: done items are never
    touched again, and a redelivered message serialises on the action's row lock."""
    row = service._get(session, BillingBulkAction, action_id, lock=True)
    if row.status in ("completed", "completed_with_errors"):
        return False
    row.status = "running"
    pending = select(BillingBulkActionItem).where(
        BillingBulkActionItem.billing_bulk_action_id == row.id, BillingBulkActionItem.status == "pending"
    )
    if row.action == "create_invoices":  # whole clients per chunk, so a client never gets two invoices
        payers = session.scalars(
            pending.with_only_columns(BillingBulkActionItem.group_client_id).distinct()
            .order_by(BillingBulkActionItem.group_client_id).limit(CHUNK_ITEMS)
        ).all()  # fmt: skip
        items = session.scalars(pending.where(BillingBulkActionItem.group_client_id.in_(payers))).all()
        groups: dict[UUID | None, list] = {}
        for item in items:
            groups.setdefault(item.group_client_id, []).append(item)
        for group in groups.values():
            _attempt(session, row, group)
    else:
        items = session.scalars(pending.order_by(BillingBulkActionItem.id).limit(CHUNK_ITEMS)).all()
        for item in items:
            _attempt(session, row, [item])
    if not items:  # pending items no chunk can select would loop for ever: fail them instead
        _fail_pending(session, row, "not-processed")
    counts = dict(
        session.execute(
            select(BillingBulkActionItem.status, func.count())
            .where(BillingBulkActionItem.billing_bulk_action_id == row.id)
            .group_by(BillingBulkActionItem.status)
        ).all()
    )
    row.done_count, row.failed_count = counts.get("done", 0), counts.get("failed", 0)
    if counts.get("pending"):
        session.flush()
        return True
    row.status = "completed_with_errors" if row.failed_count else "completed"
    row.finished_at = clock.now()
    session.flush()
    return False


def _attempt(session: Session, row: BillingBulkAction, items: list[BillingBulkActionItem]) -> None:
    try:
        with session.begin_nested() as nested:
            result_type, result_id = _apply(session, row, items)
            if row.is_dry_run:  # the same work, then undone: what would happen, nothing kept
                nested.rollback()
                result_id = None
    except DomainError as error:
        for item in items:
            item.status, item.error_code = "failed", error.code
        return
    except Exception:  # noqa: BLE001 (one subject's fault must not stop the others)
        log.exception("bulk action %s item failed", row.id)
        for item in items:
            item.status, item.error_code = "failed", "internal-error"
        return
    for item in items:
        item.status, item.result_type, item.result_id = "done", result_type, result_id


def _apply(
    session: Session, row: BillingBulkAction, items: list[BillingBulkActionItem]
) -> tuple[str | None, UUID | None]:
    params, subject = row.params, items[0].subject_id
    if row.action == "create_invoices":
        invoice = service.create_invoice_for_charges(
            session, [item.subject_id for item in items], is_autopay=params.get("is_autopay", False),
            due_on=params.get("due_on") and date.fromisoformat(params["due_on"]),
        )  # fmt: skip
        return "invoice", invoice.id
    if row.action == "reverse_charges":
        revenue_on = params.get("revenue_on") and date.fromisoformat(params["revenue_on"])
        return "charge", service.reverse(session, subject, reason=params["reason"], revenue_on=revenue_on).id
    if row.action in ("email_invoices", "render_invoices"):
        channel = "email" if row.action == "email_invoices" else "download"
        if row.is_dry_run:  # an email or a stored file cannot be undone by a rollback: run every check instead
            documents.check_invoice_send(session, subject, channel)
            return "billing_document_delivery", None
        return "billing_document_delivery", documents.send_invoice(
            session, session.info["actor"], subject, {"channel": channel}
        ).id
    sale = catalog.sell(session, UUID(params["catalog_item_id"]), client_id=subject)
    return "catalog_item_sale", sale.id


@chunked_actor(max_retries=3)
def run_bulk_action(session: Session, billing_bulk_action_id: str) -> bool:
    return run_job_chunk(session, billing_bulk_action_id)


def run_job_chunk(session: Session, billing_bulk_action_id: str) -> bool:
    """The job runs as the person or API key that started the action: re-loaded at each chunk, so a deactivated
    account, a permission taken away or a revoked key stops the rest (`requester-not-allowed`). Only an action
    neither started (a system job) runs as the system."""
    row = service._get(session, BillingBulkAction, UUID(billing_bulk_action_id))
    if row.requested_by_staff_user_id is not None or row.requested_by_api_key_id is not None:
        requester = (
            platform.staff.principal_for(session, row.requested_by_staff_user_id)
            if row.requested_by_staff_user_id is not None
            else deps.key_principal(session, row.requested_by_api_key_id)
        )
        if requester is None or not _allowed(requester, KEYS[row.action], row.location_id):
            _fail_pending(session, row, "requester-not-allowed")
            return run_chunk(session, row.id)
        session.info["actor"] = requester
    return run_chunk(session, row.id)


def _allowed(principal: Principal, key: str, location_id: UUID) -> bool:
    try:
        authorize(principal, key, location_id=location_id)
    except DomainError:
        return False
    return True


def _fail_pending(session: Session, row: BillingBulkAction, code: str) -> None:
    session.execute(
        update(BillingBulkActionItem)
        .where(BillingBulkActionItem.billing_bulk_action_id == row.id, BillingBulkActionItem.status == "pending")
        .values(status="failed", error_code=code)
    )


def action_view(row: BillingBulkAction) -> BillingBulkAction:
    return row


def _load(session: Session, principal: Principal, action_id: UUID) -> BillingBulkAction:
    row = service._get(session, BillingBulkAction, action_id)
    authorize(principal, "billing.charge.read", location_id=row.location_id)
    service._location_in_scope(session, principal, row.location_id)
    return row


def get_bulk_action(session: Session, principal: Principal, action_id: UUID) -> BillingBulkAction:
    return _load(session, principal, action_id)


def list_bulk_action_items(session: Session, principal: Principal, action_id: UUID, query: ListQuery) -> dict:
    row = _load(session, principal, action_id)
    stmt = select(BillingBulkActionItem).where(BillingBulkActionItem.billing_bulk_action_id == row.id)
    return paginate(
        session, stmt, query, id_column=BillingBulkActionItem.id, sort_fields={},
        filter_fields={"status": BillingBulkActionItem.status},
    )  # fmt: skip
