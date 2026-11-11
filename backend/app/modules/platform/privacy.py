"""Data subject requests: GDPR export and erasure of a client (security-baseline 4.2, data-model-core).

Every context holding personal data about a client registers a subject handler: `export` returns its part of
the bundle, `erase` anonymises or deletes, `precheck` may block an erasure (open balance, live contract). A
meta-test fails when a table with a foreign key to `client` is covered by no handler. Runs synchronously in
the request transaction: one tenant's handful of rows per subject does not need a job.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules.platform.events import DataSubjectRequestCompleted
from app.modules.platform.models import DataSubjectRequest

EXPORT_WINDOW = timedelta(days=7)
_ACTION = {"export": "platform.data_subject_request.export", "erasure": "platform.data_subject_request.erase"}


@dataclass(frozen=True)
class SubjectHandler:
    context: str
    tables: tuple[str, ...]
    export: Callable[[Session, UUID], dict]
    erase: Callable[[Session, UUID], dict]
    precheck: Callable[[Session, UUID], list[dict]] | None = None  # -> blockers {code, detail}


HANDLERS: dict[str, SubjectHandler] = {}


def register_subject_handler(context: str, *, tables, export, erase, precheck=None) -> None:
    HANDLERS[context] = SubjectHandler(context, tuple(tables), export, erase, precheck)


def _client(session: Session, client_id: UUID):
    from app.modules.clients import service as clients  # noqa: PLC0415 - platform must not import clients at load

    try:
        return clients.get(session, client_id)
    except NotFound:
        raise ValidationFailed("Unknown client.", pointer="/client_id") from None


def view(row: DataSubjectRequest) -> dict:
    return {c.key: getattr(row, c.key) for c in DataSubjectRequest.__table__.columns}


def create_request(session: Session, principal: Principal, data: dict) -> DataSubjectRequest:
    """Export completes at once (the bundle is built when read). Erasure needs a reason and runs the
    prechecks: `requested` when clear, `blocked` with the blockers otherwise; confirm_request then erases."""
    kind = data["kind"]
    action = _ACTION[kind]
    authorize(principal, action)
    if principal.staff_user_id is None:
        raise ValidationFailed("Only a staff user can file a data subject request.")
    client = _client(session, data["client_id"])
    if client.erased_at is not None:
        raise Conflict("This client was already erased.", code="already-erased")
    if kind == "erasure" and not data.get("reason"):
        raise ValidationFailed("Say why the data is being erased.", pointer="/reason")
    row = DataSubjectRequest(
        client_id=client.id, kind=kind, requested_by_staff_user_id=principal.staff_user_id, reason=data.get("reason")
    )
    if kind == "export":
        row.status, row.completed_at = "completed", clock.now()
    else:
        row.blockers = [
            {"context": h.context, **b} for h in HANDLERS.values() if h.precheck for b in h.precheck(session, client.id)
        ]
        row.status = "blocked" if row.blockers else "requested"
    session.add(row)
    session.flush()
    audit.record(session, action, row, changes={"status": [None, row.status]})
    if kind == "export":
        events.publish(session, DataSubjectRequestCompleted(request_id=row.id, client_id=client.id, kind=kind), row.id)
    return row


def list_requests(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "platform.data_subject_request.read")
    return paginate(
        session, select(DataSubjectRequest), query, id_column=DataSubjectRequest.id,
        sort_fields={"created_at": DataSubjectRequest.created_at}, default_sort="-created_at",
        filter_fields={"client_id": DataSubjectRequest.client_id, "kind": DataSubjectRequest.kind,
                       "status": DataSubjectRequest.status},
    )  # fmt: skip


def get_request(session: Session, principal: Principal, request_id: UUID) -> dict:
    """The request; a completed export within its window also carries the bundle, built now from live data."""
    authorize(principal, "platform.data_subject_request.read")
    row = session.get(DataSubjectRequest, request_id)
    if row is None:
        raise NotFound()
    out = view(row)
    if row.kind == "export" and row.status == "completed":
        client = _client(session, row.client_id)
        if client.erased_at is None and clock.now() - row.completed_at <= EXPORT_WINDOW:
            authorize(principal, "platform.data_subject_request.export")
            out["bundle"] = {h.context: h.export(session, row.client_id) for h in HANDLERS.values()}
            audit.record(session, "platform.data_subject_request.export", row, changes={"bundle_read": True})
    return out


def confirm_request(session: Session, principal: Principal, request_id: UUID, data: dict) -> DataSubjectRequest:
    """Run the erasure. Typed confirmation `ERASE`; blockers stop it unless explicitly overridden."""
    authorize(principal, "platform.data_subject_request.erase")
    row = session.get(DataSubjectRequest, request_id)
    if row is None:
        raise NotFound()
    if row.kind != "erasure" or row.status not in ("requested", "blocked"):
        raise Conflict("Only an open erasure request can be confirmed.")
    if data.get("confirmation") != "ERASE":
        raise ValidationFailed("Type ERASE to confirm.", pointer="/confirmation")
    if row.status == "blocked" and not data.get("is_blocker_override"):
        raise Conflict("This erasure is blocked; resolve the blockers or override them.", code="erasure-blocked")
    row.is_blocker_override = row.status == "blocked"
    row.handler_results = {h.context: h.erase(session, row.client_id) for h in HANDLERS.values()}
    row.status, row.confirmed_at, row.completed_at = "completed", clock.now(), clock.now()
    session.flush()
    audit.record(
        session, "platform.data_subject_request.erase", row, reason=row.reason,
        changes={"status": ["requested", "completed"], "is_blocker_override": row.is_blocker_override},
    )  # fmt: skip
    events.publish(
        session, DataSubjectRequestCompleted(request_id=row.id, client_id=row.client_id, kind="erasure"), row.id
    )
    return row
