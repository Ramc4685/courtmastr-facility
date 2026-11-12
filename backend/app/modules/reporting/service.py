"""reporting services (RPT-01 report centre; the P0 reports live in registry.py). Every report is a family key
(rbac-matrix 6.17) checked with `authorize`; requested locations are loaded through platform, so one outside the
caller's set is a 404. A run is computed inline and frozen as a JSON snapshot in a stored file (ADR 0010); rows
are paged from that snapshot, never re-queried. Runs, saved reports and exports belong to a staff user: others
get a 404 (a shared saved report is visible to holders of its family key, but only its owner may change it)."""

import hashlib
import json
from datetime import timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import platform
from app.modules.reporting.catalogue import REGISTRY
from app.modules.reporting.domain import csv_file, periods
from app.modules.reporting.events import ExportCompleted
from app.modules.reporting.models import ExportJob, ReportRun, RunStatus, SavedReport
from app.modules.reporting.registry import MAX_ROWS, ReportSpec, Scope, too_large

RUN_KEYS = tuple(sorted({spec.permission for spec in REGISTRY.values()}))
EXPORT = "reporting.report.export"
RETENTION = timedelta(days=7)
ROWS_LIMIT = 1000

CONSTRAINT_CODES["uq_saved_report_owner_name"] = "already-exists"


def _staff(principal: Principal) -> UUID:
    # Runs, saved reports and exports are a person's history; an API key is not a person (README).
    if principal.staff_user_id is None:
        raise PermissionDenied("Report runs and exports belong to a staff user")
    return principal.staff_user_id


def _holds(principal: Principal, key: str) -> bool:
    return principal.kind == "system" or key in principal.permissions


def _spec(principal: Principal, report_key: str) -> ReportSpec:
    spec = REGISTRY.get(report_key)
    if spec is None:
        raise NotFound("Unknown report")
    authorize(principal, spec.permission)
    return spec


def _permitted_keys(principal: Principal) -> list[str]:
    return [spec.key for spec in REGISTRY.values() if _holds(principal, spec.permission)]


# --- definitions ---------------------------------------------------------------------------------------------


def definition_view(spec: ReportSpec) -> dict:
    return {
        "key": spec.key, "name": spec.name, "description": spec.description, "category": spec.category,
        "required_permission": spec.permission, "required_entitlement": None, "date_basis": spec.date_basis,
        "params_schema": spec.params.model_json_schema(), "columns": [c.out() for c in spec.columns],
        "total_columns": [c.out() for c in spec.totals],
        "detail_columns": [c.out() for c in spec.detail_columns] if spec.detail_columns else None,
        "supports_detail": spec.detail_columns is not None, "export_formats": ["csv"], "is_stub": False,
        "features": list(spec.features),
    }  # fmt: skip


def list_definitions(principal: Principal, *, category: str | None = None, q: str | None = None) -> dict:
    """The catalogue the caller may run: ten reports, so one page (no cursor)."""
    found = [
        definition_view(spec) for spec in REGISTRY.values()
        if _holds(principal, spec.permission) and (category is None or spec.category == category)
        and (not q or q.lower() in spec.name.lower())
    ]  # fmt: skip
    return {"data": found, "page": {"next_cursor": None, "has_more": False}}


def get_definition(principal: Principal, report_key: str) -> dict:
    return definition_view(_spec(principal, report_key))


# --- parameters ----------------------------------------------------------------------------------------------


def _parse(spec: ReportSpec, raw: dict):
    try:
        return spec.params.model_validate(raw or {})
    except ValidationError as error:
        first = error.errors()[0]
        pointer = "/params/" + "/".join(str(part) for part in first["loc"])
        raise ValidationFailed(first["msg"], pointer=pointer) from None


def resolve(session: Session, principal: Principal, spec: ReportSpec, raw: dict):
    """Validated, frozen parameters and the row scope. A relative period resolves at each location in its own
    zone; explicit-date defaults and the as-of default use the one chosen location's today, or the earliest
    today across the tenant when several are in play."""
    params = _parse(spec, raw)
    chosen = list(dict.fromkeys(params.location_ids or []))
    for location_id in chosen:
        platform.service.get_location(session, principal, location_id)  # 404 outside the caller's set
    if chosen:
        locations = tuple(chosen)
    elif principal.kind != "system" and principal.location_ids is not None:
        locations = tuple(sorted(principal.location_ids))
    else:
        locations = None
    if len(chosen) == 1:
        today = platform.service.location_today(session, chosen[0])
    else:
        today = platform.service.earliest_today(session)
    changes: dict = {"location_ids": list(locations) if locations is not None else None}
    day_ranges = None
    if spec.is_ranged:
        if params.period:
            # Each location's own "today": a single range cut at the earliest one dropped the start of the day
            # at locations further east. The frozen from/to span every location's range.
            local = {
                location_id: periods.resolve(params.period, day)
                for location_id, day in platform.service.location_todays(session, locations).items()
            } or {None: periods.resolve(params.period, today)}
            start, end = min(r[0] for r in local.values()), max(r[1] for r in local.values())
            if len(set(local.values())) > 1:
                day_ranges = local
        else:
            start, end = params.from_on or today, params.to_on or today
        if end < start:
            raise ValidationFailed("The end date is before the start date", pointer="/params/to_on")
        if day_ranges is None and (end - start).days >= periods.MAX_DAYS:  # presets fit by construction
            raise ValidationFailed(f"A report covers at most {periods.MAX_DAYS} days", pointer="/params/to_on")
        changes |= {"from_on": start, "to_on": end}
    if hasattr(params, "as_of_on"):
        changes["as_of_on"] = params.as_of_on or today
    reach = "all" if principal.kind == "system" else principal.permissions.get(spec.permission)
    own_only = reach == "own"
    if own_only and not spec.own_reach:
        raise PermissionDenied(f"Requires {spec.permission} for every row", required=spec.permission)
    own = platform.service.linked_resource_id(session, principal.staff_user_id) if own_only else None
    return params.model_copy(update=changes), Scope(locations, own_only, own, day_ranges)


# --- runs ----------------------------------------------------------------------------------------------------


def _expired(expires_at) -> bool:
    return expires_at <= clock.now()


def run_view(run: ReportRun) -> dict:
    view = {c: getattr(run, c) for c in (
        "id", "report_key", "saved_report_id", "params", "status", "row_count", "totals", "error", "started_at",
        "finished_at", "expires_at", "created_at", "updated_at")}  # fmt: skip
    if run.status == RunStatus.SUCCEEDED and _expired(run.expires_at):
        view["status"] = RunStatus.EXPIRED
    return view


def _load_run(session: Session, principal: Principal, run_id: UUID) -> ReportRun:
    run = session.get(ReportRun, run_id)
    if run is None or run.requested_by_staff_user_id != _staff(principal):
        raise NotFound()
    spec = REGISTRY[run.report_key]
    authorize(principal, spec.permission)
    built = run.params.get("scope", {})
    if principal.permissions.get(spec.permission) == "own":
        own = platform.service.linked_resource_id(session, principal.staff_user_id)
        if not built.get("own_only") or built.get("own_resource_id") != (str(own) if own else None):
            raise NotFound()  # built with rows the caller's current reach no longer covers
    frozen = run.params.get("location_ids")
    if principal.location_ids is not None and (
        frozen is None or not {UUID(i) for i in frozen} <= principal.location_ids
    ):
        raise NotFound()  # the caller's location set shrank since the run
    return run


def _snapshot(spec: ReportSpec, result: dict) -> bytes:
    return json.dumps({
        "columns": [c.out() for c in spec.columns], "rows": result["rows"], "totals": result["totals"],
        "detail_columns": [c.out() for c in spec.detail_columns] if spec.detail_columns else None,
        "details": result["details"],
    }, default=str).encode()  # fmt: skip


def create_run(session: Session, principal: Principal, data: dict) -> dict:
    staff_user_id = _staff(principal)
    spec = _spec(principal, data["report_key"])
    raw = data.get("params")
    saved = None
    if data.get("saved_report_id"):
        try:
            saved = _load_saved(session, principal, data["saved_report_id"])
        except NotFound:
            raise ValidationFailed("Unknown saved report", pointer="/saved_report_id") from None
        if saved.report_key != spec.key:
            raise ValidationFailed("The saved report is for another report", pointer="/saved_report_id")
        raw = {**saved.params, **(raw or {})}
    params, scope = resolve(session, principal, spec, raw or {})
    started = clock.now()
    result = spec.build(session, params, scope)
    if len(result["rows"]) + len(result["details"] or []) > MAX_ROWS:
        raise too_large()
    frozen = params.model_dump(mode="json")
    own = str(scope.own_resource_id) if scope.own_resource_id else None
    frozen["scope"] = {"own_only": scope.own_only, "own_resource_id": own}  # re-checked on every read
    stored = platform.files.store(
        session, _snapshot(spec, result), purpose="report_result", content_type="application/json",
        uploaded_by=("staff", staff_user_id), original_name=f"{spec.key}.json", generated=True,
    )  # fmt: skip
    run = ReportRun(
        report_key=spec.key, saved_report_id=saved.id if saved else None, requested_by_staff_user_id=staff_user_id,
        params=frozen, params_hash=hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest(),
        status=RunStatus.SUCCEEDED, started_at=started, finished_at=clock.now(), row_count=len(result["rows"]),
        totals=json.loads(json.dumps(result["totals"], default=str)), result_file_id=stored.id,
        expires_at=started + RETENTION,
    )  # fmt: skip
    session.add(run)
    if saved:
        saved.last_run_at = started
    session.flush()
    audit.record(session, "reporting.report_run.create", run, changes=audit.diff(run))
    return run_view(run)


def get_run(session: Session, principal: Principal, run_id: UUID) -> dict:
    return run_view(_load_run(session, principal, run_id))


def list_runs(session: Session, principal: Principal, query: ListQuery) -> dict:
    stmt = select(ReportRun).where(
        ReportRun.requested_by_staff_user_id == _staff(principal), ReportRun.report_key.in_(_permitted_keys(principal))
    )
    page = paginate(
        session, stmt, query, id_column=ReportRun.id, sort_fields={"created_at": ReportRun.created_at},
        default_sort="-created_at", filter_fields={"report_key": ReportRun.report_key, "status": ReportRun.status},
    )  # fmt: skip
    page["data"] = [run_view(run) for run in page["data"]]
    return page


def _read_snapshot(session: Session, run: ReportRun) -> dict:
    if run.status != RunStatus.SUCCEEDED:
        raise Conflict("The run has no result yet")
    if _expired(run.expires_at):
        raise NotFound("The result has expired; run the report again")
    _, data = platform.files.read(session, run.result_file_id)
    return json.loads(data)


def _sort_key(name: str):
    def key(row: dict):
        value = row.get(name)
        return (value is None, value.lower() if isinstance(value, str) else (value if value is not None else 0))

    return key


def list_rows(session: Session, principal: Principal, run_id: UUID, *, limit: int = 100, cursor: str | None = None,
              sort: str | None = None, group_key: str | None = None) -> dict:  # fmt: skip
    """One page of a snapshot. `group_key` drills into the detail rows of one summary row. The cursor is an
    offset into the frozen snapshot, which never changes, so offsets are stable."""
    snapshot = _read_snapshot(session, _load_run(session, principal, run_id))
    if group_key is not None:
        if snapshot["details"] is None:
            raise ValidationFailed("This report has no detail rows", pointer="/group_key")
        columns, rows = snapshot["detail_columns"], [r for r in snapshot["details"] if r.get("group_key") == group_key]
    else:
        columns, rows = snapshot["columns"], snapshot["rows"]
    if sort:
        name = sort.lstrip("-")
        if name not in {c["key"] for c in columns}:
            raise ValidationFailed(f"Cannot sort by {name}", pointer="/sort")
        rows = sorted(rows, key=_sort_key(name), reverse=sort.startswith("-"))
    try:
        start = max(int(cursor or 0), 0)
    except ValueError:
        raise ValidationFailed("Invalid cursor", pointer="/cursor") from None
    limit = max(1, min(limit, ROWS_LIMIT))
    chunk = rows[start : start + limit]
    more = start + limit < len(rows)
    page = {"next_cursor": str(start + limit) if more else None, "has_more": more, "total": len(rows)}
    return {"columns": columns, "data": chunk, "totals": snapshot["totals"], "page": page}


# --- saved reports -------------------------------------------------------------------------------------------


def _load_saved(session: Session, principal: Principal, saved_id: UUID, *, owner: bool = False) -> SavedReport:
    saved = session.get(SavedReport, saved_id)
    me = _staff(principal)
    if saved is None or (saved.owner_staff_user_id != me and not saved.is_shared):
        raise NotFound()
    spec = REGISTRY.get(saved.report_key)
    if spec is None or not _holds(principal, spec.permission):
        raise NotFound()
    if owner and saved.owner_staff_user_id != me:
        raise PermissionDenied("Only the owner can change a saved report")
    return saved


def create_saved(session: Session, principal: Principal, data: dict) -> SavedReport:
    owner = _staff(principal)
    spec = _spec(principal, data["report_key"])
    params = _parse(spec, data.get("params") or {}).model_dump(mode="json", exclude_none=True)
    saved = SavedReport(
        report_key=spec.key, name=data["name"], params=params, columns=data.get("columns"),
        is_shared=data.get("is_shared", False), owner_staff_user_id=owner,
    )  # fmt: skip
    session.add(saved)
    session.flush()
    audit.record(session, "reporting.saved_report.create", saved, changes=audit.diff(saved))
    return saved


def get_saved(session: Session, principal: Principal, saved_id: UUID) -> SavedReport:
    return _load_saved(session, principal, saved_id)


def list_saved(session: Session, principal: Principal, query: ListQuery) -> dict:
    stmt = select(SavedReport).where(
        or_(SavedReport.owner_staff_user_id == _staff(principal), SavedReport.is_shared),
        SavedReport.report_key.in_(_permitted_keys(principal)),
    )
    return paginate(
        session, stmt, query, id_column=SavedReport.id,
        sort_fields={"name": SavedReport.name, "created_at": SavedReport.created_at}, default_sort="name",
        filter_fields={"report_key": SavedReport.report_key, "is_shared": SavedReport.is_shared},
        search=(SavedReport.name,),
    )  # fmt: skip


def update_saved(session: Session, principal: Principal, saved_id: UUID, data: dict) -> SavedReport:
    saved = _load_saved(session, principal, saved_id, owner=True)
    if data.get("params") is not None:
        spec = _spec(principal, saved.report_key)
        data["params"] = _parse(spec, data["params"]).model_dump(mode="json", exclude_none=True)
    for field in ("name", "params", "is_shared"):
        if data.get(field) is not None:
            setattr(saved, field, data[field])
    if "columns" in data:
        saved.columns = data["columns"]
    session.flush()
    audit.record(session, "reporting.saved_report.update", saved, changes=audit.diff(saved))
    return saved


def delete_saved(session: Session, principal: Principal, saved_id: UUID) -> None:
    saved = _load_saved(session, principal, saved_id, owner=True)
    session.execute(update(ReportRun).where(ReportRun.saved_report_id == saved.id).values(saved_report_id=None))
    audit.record(session, "reporting.saved_report.delete", saved)
    session.delete(saved)
    session.flush()


# --- export jobs ---------------------------------------------------------------------------------------------


def export_view(session: Session, job: ExportJob) -> dict:
    view = {c: getattr(job, c) for c in (
        "id", "source_kind", "report_run_id", "source_key", "params", "format", "includes_details", "page_size",
        "orientation", "status", "row_count", "error", "expires_at", "created_at", "updated_at")}  # fmt: skip
    view["file_name"] = None
    if job.file_id:
        view["file_name"] = session.scalar(
            select(platform.models.StoredFile.original_name).where(platform.models.StoredFile.id == job.file_id)
        )
    if job.status == RunStatus.SUCCEEDED and _expired(job.expires_at):
        view["status"] = RunStatus.EXPIRED
    return view


def _load_export(session: Session, principal: Principal, job_id: UUID) -> ExportJob:
    authorize(principal, EXPORT)
    job = session.get(ExportJob, job_id)
    if job is None or job.requested_by_staff_user_id != _staff(principal):
        raise NotFound()
    if job.report_run_id:
        _load_run(session, principal, job.report_run_id)  # family key and location set still hold
    return job


def create_export(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, EXPORT)
    staff_user_id = _staff(principal)
    if data.get("source_kind", "report_run") != "report_run":
        raise ValidationFailed("Only report runs can be exported yet", pointer="/source_kind", code="not-supported")
    if data.get("format", "csv") != "csv":
        raise ValidationFailed("Only CSV exports are available yet", pointer="/format", code="not-supported")
    if not data.get("report_run_id"):
        raise ValidationFailed("A report run is required", pointer="/report_run_id")
    try:
        run = _load_run(session, principal, data["report_run_id"])
    except NotFound:
        raise ValidationFailed("Unknown report run", pointer="/report_run_id") from None
    if run.status != RunStatus.SUCCEEDED or _expired(run.expires_at):
        raise Conflict("The run has no result to export; run the report again")
    job = ExportJob(
        source_kind="report_run", report_run_id=run.id, source_key=run.report_key, params=run.params, format="csv",
        includes_details=data.get("includes_details", False), page_size=data.get("page_size"),
        orientation=data.get("orientation"), status=RunStatus.QUEUED, requested_by_staff_user_id=staff_user_id,
        expires_at=run.expires_at,
    )  # fmt: skip
    session.add(job)
    session.flush()
    audit.record(session, "reporting.export_job.create", job, changes=audit.diff(job))
    tenant_id, job_id = str(session.info["tenant_id"]), str(job.id)

    def enqueue() -> None:
        from app.modules.reporting.jobs import run_export

        run_export.send(tenant_id, job_id)

    session.info.setdefault("after_commit", []).append(enqueue)
    return export_view(session, job)


def get_export(session: Session, principal: Principal, job_id: UUID) -> dict:
    return export_view(session, _load_export(session, principal, job_id))


def list_exports(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, EXPORT)
    stmt = select(ExportJob).where(
        ExportJob.requested_by_staff_user_id == _staff(principal), ExportJob.source_key.in_(_permitted_keys(principal))
    )
    page = paginate(
        session, stmt, query, id_column=ExportJob.id, sort_fields={"created_at": ExportJob.created_at},
        default_sort="-created_at", filter_fields={"source_key": ExportJob.source_key, "status": ExportJob.status},
    )  # fmt: skip
    page["data"] = [export_view(session, job) for job in page["data"]]
    return page


def download_export(session: Session, principal: Principal, job_id: UUID):
    job = _load_export(session, principal, job_id)
    if job.status == RunStatus.SUCCEEDED and _expired(job.expires_at):
        raise NotFound("The export has expired")
    if job.status != RunStatus.SUCCEEDED or job.file_id is None:
        raise Conflict("The export is not ready")
    return platform.files.read(session, job.file_id)


def purge_expired_results(session: Session) -> int:
    """Internal, for the hourly job: the snapshot of an expired run and the file of an expired export go through
    `files.remove`, and the reference is cleared; the rows stay as history and read `expired`. Idempotent."""
    now, removed = clock.now(), 0
    for model, column in ((ReportRun, "result_file_id"), (ExportJob, "file_id")):
        ref = getattr(model, column)
        stmt = select(model).where(model.expires_at <= now, ref.is_not(None)).with_for_update(skip_locked=True)
        for row in session.scalars(stmt):
            platform.files.remove(session, getattr(row, column))
            setattr(row, column, None)
            removed += 1
    session.flush()
    return removed


EXPORT_CHUNK_ROWS = 1_000  # rows rendered per job message (ADR 0008 section 3)


def render_export_chunk(session: Session, job_id: UUID) -> bool:
    """Internal, for the chunked `run_export` job (system session): render the next EXPORT_CHUNK_ROWS rows of a
    job's CSV from its run snapshot; True while rows remain. The cursor and the bytes so far live on the locked
    job row, so a crash or a redelivery re-renders at most one chunk. A job no longer queued or running is left
    alone."""
    job = session.scalars(select(ExportJob).where(ExportJob.id == job_id).with_for_update()).one_or_none()
    if job is None or job.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        return False
    run = session.get(ReportRun, job.report_run_id)
    try:
        snapshot = _read_snapshot(session, run)
    except (NotFound, Conflict) as error:
        job.status, job.error, job.finished_at = RunStatus.FAILED, error.detail or "Source unavailable", clock.now()
        job.partial = None
        audit.record(session, "reporting.export_job.fail", job, changes={"status": job.status})
        return False
    if job.status == RunStatus.QUEUED:
        job.status, job.started_at, job.partial = RunStatus.RUNNING, clock.now(), b""
    currency = platform.service.get_tenant(session).currency
    # One row sequence over two sections: the rows, then after a blank line the detail rows, each with its header.
    sections = [(snapshot["columns"], snapshot["rows"], csv_file.BOM)]
    if job.includes_details and snapshot["details"]:
        sections.append((snapshot["detail_columns"], snapshot["details"], b"\r\n"))
    start = job.progress.get("next", 0)
    end, offset, piece = start + EXPORT_CHUNK_ROWS, 0, b""
    for columns, rows, lead in sections:
        if start <= offset < end:
            piece += lead + csv_file.header(columns, currency=currency)
        piece += csv_file.body(columns, rows[max(start - offset, 0) : max(end - offset, 0)])
        offset += len(rows)
    job.partial = (job.partial or b"") + piece
    job.progress = {"next": min(end, offset), "total": offset}
    if end < offset:
        return True
    stored = platform.files.store(
        session, job.partial, purpose="report_export", content_type="text/csv; charset=utf-8",
        uploaded_by=("system", None), original_name=f"{run.report_key}-{run.finished_at.date().isoformat()}.csv",
        generated=True,
    )  # fmt: skip
    job.file_id, job.row_count, job.status = stored.id, len(snapshot["rows"]), RunStatus.SUCCEEDED
    job.finished_at, job.partial = clock.now(), None
    job.expires_at = job.finished_at + RETENTION
    session.flush()
    audit.record(session, "reporting.export_job.complete", job, changes=audit.diff(job))
    event = ExportCompleted(export_job_id=job.id, requested_by_staff_user_id=job.requested_by_staff_user_id)
    events.publish(session, event, job.id)
    return False
