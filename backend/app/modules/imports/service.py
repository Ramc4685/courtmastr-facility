"""imports service: CSV import jobs (IMP-01, IMP-02, MEM-23). Tenant-wide keys `platform.import_job.read` and
`platform.import_job.run` (D +), checked here with `authorize` on the loaded job and its location; a job at a
location outside the caller's set is 404.

Flow: create a job for a type and location, upload the CSV (stored through platform.files, purpose
`import_source`), map columns, then a DRY RUN validates every row inside a savepoint that is always rolled back,
and a COMMIT applies them. Both run as the chunked job `run_import` (core.jobs.chunked_actor): each chunk is one
transaction over `chunk_rows` rows (per type), with the cursor on the locked job row. Every source row ends as one
ImportJobRow: valid or invalid (dry run), created, updated, skipped (a duplicate) or failed, with its reasons.

Idempotency: a commit chunk that did not commit left no rows behind, so a retry redoes exactly that chunk. A row
whose natural key (kinds.py) an earlier row of the same job already took is skipped; for the types that never
update (memberships, balances), so is a row an earlier job already created. Opening balances also pass billing
an idempotency key made of the resolved client and the balance itself, so one posts once per tenant.

Scope: an import matches and updates clients by member number or email at any location, so running a dry run or
a commit needs every location (`all-locations-required`) besides the run key, and a commit also needs the keys
the equivalent staff commands need (KIND_KEYS). The worker re-checks before each chunk that the submitter is
still active with the run key and every location; otherwise the job stops with `stop_reason`."""

import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, clock, crypto
from app.core.auth import Principal, authorize
from app.core.auth.permissions import scope_query
from app.core.errors import Conflict, DomainError, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.pan import contains_card_number
from app.core.schemas import CARD_DATA, CARD_DATA_DETAIL, FREE_TEXT_FIELDS
from app.core.settings import get_settings
from app.modules import clients, platform
from app.modules.imports import csvio
from app.modules.imports.kinds import KINDS, SMALL_CHUNK, Context, Kind
from app.modules.imports.models import EntityType, ImportJob, ImportJobRow, JobStatus, RowStatus

READ, RUN = "platform.import_job.read", "platform.import_job.run"
# The keys the staff commands equivalent to each type's writes need; a commit checks them for the submitter.
KIND_KEYS = {
    "clients": ("clients.client.create", "clients.client.update", "clients.consent.update"),
    "memberships": ("memberships.contract.sell",),
    "balances": ("billing.charge.create", "billing.payment.take"),
    "products": ("pos.product.manage", "pos.inventory.adjust"),
}
log = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
RETENTION = timedelta(days=30)  # source file and error report are removed after this
CONTENT_TYPES = {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"}
_UPLOADABLE = (JobStatus.NEW, JobStatus.UPLOADED, JobStatus.VALIDATED, JobStatus.NEEDS_REVIEW)
_CHECKABLE = (JobStatus.UPLOADED, JobStatus.VALIDATED, JobStatus.NEEDS_REVIEW)
_SKIP_CODES = {"possible-duplicate"}  # a service refusal that means "this is a duplicate", not a failure
_TAKEN = (RowStatus.VALID, RowStatus.CREATED, RowStatus.UPDATED)


# --- templates -----------------------------------------------------------------------------------------------------


def _kind(key: str) -> Kind:
    if key not in KINDS:
        raise NotFound()
    return KINDS[key]


def template_view(kind: Kind) -> dict:
    return {
        "kind": kind.key, "label": kind.label, "guide": kind.guide,
        "fields": [{"key": f.key, "label": f.label, "required": f.required, "help": f.help, "example": f.example}
                   for f in kind.fields],
    }  # fmt: skip


def list_templates(principal: Principal) -> dict:
    authorize(principal, READ)
    return {"data": [template_view(kind) for kind in KINDS.values()], "page": {"next_cursor": None, "has_more": False}}


def template_csv(principal: Principal, kind_key: str) -> bytes:
    """Our columns, one example row: the guide is in the template listing (a guide row would import as data)."""
    authorize(principal, READ)
    kind = _kind(kind_key)
    return csvio.write([[f.key for f in kind.fields], [f.example for f in kind.fields]])


# --- jobs ----------------------------------------------------------------------------------------------------------


def job_view(session: Session, job: ImportJob) -> dict:
    view = {c.key: getattr(job, c.key) for c in ImportJob.__table__.columns if c.key not in ("tenant_id", "progress")}
    view["processed_row_count"] = job.progress.get("next", 0) if job.status in (
        JobStatus.VALIDATING, JobStatus.IMPORTING, JobStatus.FAILED) else (
        job.total_row_count if job.finished_at else 0)  # fmt: skip
    view["source_file_name"] = None
    if job.source_file_id and job.files_purged_at is None:
        view["source_file_name"] = session.scalar(
            select(platform.models.StoredFile.original_name).where(platform.models.StoredFile.id == job.source_file_id)
        )
    view["has_error_report"] = job.report_file_id is not None and job.files_purged_at is None
    view["stop_reason"] = job.progress.get("stop_reason") if job.status == JobStatus.FAILED else None
    return view


def require_all_locations(principal: Principal) -> None:
    """Running an import needs every location: rows match clients by member number or email wherever they are."""
    if principal.kind != "system" and principal.location_ids is not None:
        raise PermissionDenied("An import can match clients at any location, so running one needs access to "
                               "every location.", code="all-locations-required")  # fmt: skip


def _load(session: Session, principal: Principal, job_id: UUID, key: str) -> ImportJob:
    """The job, row-locked for a run-key change so an upload and a commit never interleave."""
    authorize(principal, key)
    stmt = select(ImportJob).where(ImportJob.id == job_id)
    job = session.scalars(stmt.with_for_update() if key == RUN else stmt).one_or_none()
    if job is None:
        raise NotFound()
    authorize(principal, key, location_id=job.location_id)  # outside the caller's locations: 404
    return job


def _reset(session: Session, job: ImportJob) -> None:
    session.execute(delete(ImportJobRow).where(ImportJobRow.import_job_id == job.id))
    job.valid_row_count = job.created_count = job.updated_count = job.skipped_count = job.error_count = 0
    job.progress, job.started_at, job.finished_at = {}, None, None
    if job.report_file_id:
        platform.files.remove(session, job.report_file_id)
        job.report_file_id = None


def _enqueue(session: Session, job: ImportJob) -> None:
    tenant_id, job_id = str(session.info["tenant_id"]), str(job.id)

    def enqueue() -> None:
        from app.modules.imports.jobs import run_import

        run_import.send(tenant_id, job_id)

    session.info.setdefault("after_commit", []).append(enqueue)


def create_job(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, RUN)
    if principal.staff_user_id is None:
        raise PermissionDenied("An import belongs to a staff user")
    _kind(data["kind"])
    try:
        platform.service.get_location(session, principal, data["location_id"])
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    job = ImportJob(
        kind=data["kind"], location_id=data["location_id"], submitted_by_staff_user_id=principal.staff_user_id,
        status=JobStatus.NEW, expires_at=clock.now() + RETENTION,
    )  # fmt: skip
    session.add(job)
    session.flush()
    audit.record(session, "imports.import_job.create", job, location_id=job.location_id,
                 changes={"kind": job.kind, "location_id": str(job.location_id)})  # fmt: skip
    return job_view(session, job)


def upload_source(
    session: Session, principal: Principal, job_id: UUID, data: bytes, content_type: str, name: str | None
) -> dict:
    """The CSV itself (UTF-8, with or without a BOM). Replaces an earlier file and clears earlier results."""
    job = _load(session, principal, job_id, RUN)
    if job.status not in _UPLOADABLE:
        raise Conflict("This import has started; start a new import for another file.")
    if not data:
        raise ValidationFailed("The file is empty.", code="file-empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationFailed("A file may be at most 10 MB. Split it and import each part.", code="file-too-large")
    if content_type not in CONTENT_TYPES:
        raise ValidationFailed("Upload a CSV file.", code="file-type-mismatch")
    headers, records = csvio.read(csvio.decode(data))
    stored = platform.files.store(
        session, data, purpose="import_source", content_type="text/csv",
        uploaded_by=("staff", principal.staff_user_id), original_name=name or "import.csv",
    )  # fmt: skip
    if job.source_file_id:
        platform.files.remove(session, job.source_file_id)
    _reset(session, job)
    kind = _kind(job.kind)
    job.source_file_id, job.source_headers = stored.id, headers
    job.column_mapping = csvio.auto_map(headers, kind.fields)
    job.total_row_count = sum(1 for record in records if record)
    job.status, job.expires_at = JobStatus.UPLOADED, clock.now() + RETENTION
    session.flush()
    audit.record(session, "imports.import_job.upload", job, location_id=job.location_id,
                 changes={"source_file_id": str(stored.id), "total_row_count": job.total_row_count})  # fmt: skip
    return job_view(session, job)


def start_dry_run(session: Session, principal: Principal, job_id: UUID, data: dict) -> dict:
    """Check every row against the mapping and the rules, writing nothing outside the job's own rows."""
    job = _load(session, principal, job_id, RUN)
    require_all_locations(principal)
    if job.status not in _CHECKABLE:
        raise Conflict("Upload a file first." if job.status == JobStatus.NEW else "This import is already running.")
    kind = _kind(job.kind)
    mapping = data.get("column_mapping")
    mapping = job.column_mapping if mapping is None else {k: v for k, v in mapping.items() if v}
    csvio.check_mapping(mapping, job.source_headers, kind.fields)
    _reset(session, job)
    job.column_mapping, job.date_format = mapping, data.get("date_format") or job.date_format
    job.status, job.started_at = JobStatus.VALIDATING, clock.now()
    if kind.limit_key and (cap := platform.entitlements.limit(session, kind.limit_key)) is not None:
        job.progress = {"next": 0, "remaining": max(cap - platform.entitlements.usage(session, kind.limit_key), 0)}
    session.flush()
    audit.record(session, "imports.import_job.validate", job, location_id=job.location_id,
                 changes={"column_mapping": True, "date_format": job.date_format})  # fmt: skip
    _enqueue(session, job)
    return job_view(session, job)


def start_commit(session: Session, principal: Principal, job_id: UUID) -> dict:
    """Import the rows a dry run passed; rows that fail now are reported, never silently dropped."""
    job = _load(session, principal, job_id, RUN)
    require_all_locations(principal)
    for key in KIND_KEYS[job.kind]:
        authorize(principal, key, location_id=job.location_id)
    if job.status not in (JobStatus.VALIDATED, JobStatus.NEEDS_REVIEW):
        raise Conflict("Run the check first." if job.status in _CHECKABLE else "This import is already running.")
    if job.progress.get("checked_file_id") != str(job.source_file_id):
        raise Conflict("The file changed after it was checked; run the check again.", code="check-stale")
    if job.valid_row_count == 0:
        raise Conflict("No row can be imported; fix the file and upload it again.", code="nothing-to-import")
    _reset(session, job)
    job.status, job.started_at = JobStatus.IMPORTING, clock.now()
    session.flush()
    audit.record(session, "imports.import_job.commit", job, location_id=job.location_id,
                 changes={"status": job.status})  # fmt: skip
    _enqueue(session, job)
    return job_view(session, job)


def get_job(session: Session, principal: Principal, job_id: UUID) -> dict:
    return job_view(session, _load(session, principal, job_id, READ))


def list_jobs(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, READ)
    page = paginate(
        session, scope_query(select(ImportJob), principal, ImportJob.location_id), query, id_column=ImportJob.id,
        sort_fields={"created_at": ImportJob.created_at}, default_sort="-created_at",
        filter_fields={"kind": ImportJob.kind, "status": ImportJob.status},
    )  # fmt: skip
    page["data"] = [job_view(session, job) for job in page["data"]]
    return page


def error_report(session: Session, principal: Principal, job_id: UUID):
    job = _load(session, principal, job_id, READ)
    if job.report_file_id is None or job.files_purged_at is not None:
        raise NotFound("This import has no error report.")
    return platform.files.read(session, job.report_file_id)


# --- the chunked engine (internal, for jobs.run_import) ------------------------------------------------------------


def _row_key(kind: Kind, data: dict) -> str:
    """A keyed MAC (not a plain hash) of the natural key: member numbers and emails cannot be guessed back."""
    return crypto.mac(f"import-row\x1f{kind.key}\x1f{kind.natural_key(data)}")


def chunk_rows(session: Session, kind: Kind) -> int:
    """Rows per chunk transaction: small while a row takes a per-tenant counter lock (see Kind.chunk_rows)."""
    if kind.key == "clients":
        settings = clients.service.settings_row(session)
        if settings.is_member_number_auto_generated and settings.member_number_trigger == "client_created":
            return SMALL_CHUNK
    return kind.chunk_rows


def _problem(kind: Kind, error: DomainError) -> dict:
    pointers = [e.get("pointer") for e in error.extra.get("errors", [])]
    field = next((kind.pointers[p] for p in pointers if p in kind.pointers), "")
    return {"field": field, "code": error.code, "detail": error.detail or "This row could not be imported."}


def _order(kind: Kind, parsed: list) -> list[int]:
    """Indexes of the non-blank records: household heads first, so a member's head exists when it is linked."""
    rows = [i for i, item in enumerate(parsed) if item is not None]
    if kind.key != "clients":
        return rows
    return sorted(rows, key=lambda i: not parsed[i][0].get("household_head"))


def _household(kind: Kind, parsed: list, idx: int, data: dict, heads: dict) -> tuple[str, str, int | None]:
    """(field, problem, head index) for a clients row in a household; problem '' when fine."""
    ref = (data.get("household_ref") or "").lower()
    found = heads.get(ref, [])
    if data.get("household_head"):
        return (
            ("household_head", "Two rows are marked head of this household.", None)
            if len(found) > 1
            else ("", "", None)
        )
    if len(found) != 1:
        problem = "No row is marked head of this household." if not found else "This household has two heads."
        return "household_ref", problem, None
    return "", "", found[0]


def _apply(session: Session, kind: Kind, data: dict, ctx: Context, dry: bool) -> tuple:
    """Run the context's import function in a savepoint: (status, entity_type, entity_id, created, problems); on
    success the problems are the row's warnings."""
    hooks = session.info.setdefault("after_commit", [])
    pending = len(hooks)
    nested = session.begin_nested()
    try:
        entity_type, entity_id, created, warned = kind.apply(session, data, ctx)
        session.flush()
    except DomainError as error:
        nested.rollback()
        del hooks[pending:]
        problem = _problem(kind, error)
        return (RowStatus.SKIPPED if error.code in _SKIP_CODES else None), None, None, False, [problem]
    except IntegrityError:
        nested.rollback()
        del hooks[pending:]
        return None, None, None, False, [{"field": "", "code": "already-exists",
                                          "detail": "This row clashes with a record that already exists."}]  # fmt: skip
    except Exception as error:  # one poison row must not stop the job; the class name only (no values) is logged
        nested.rollback()
        del hooks[pending:]
        log.warning("import row failed unexpectedly: %s", type(error).__name__)
        return None, None, None, False, [{"field": "", "code": "unexpected",
                                          "detail": "This row could not be imported because of an error on our side."}]  # fmt: skip
    if dry:
        nested.rollback()
        del hooks[pending:]  # nothing a dry run did may reach the outside world (emails, file deletes)
    else:
        nested.commit()
    if kind.once and not created:
        f, c, d = warned[0] if warned else ("", "already-exists", "This record already exists; skipped.")
        return RowStatus.SKIPPED, entity_type, entity_id, False, [{"field": f, "code": c, "detail": d}]
    warnings = [{"field": f, "code": c, "detail": d, "warning": True} for f, c, d in warned]
    if dry:
        return RowStatus.VALID, None, None, created, warnings
    return (RowStatus.CREATED if created else RowStatus.UPDATED), entity_type, entity_id, created, warnings


def _process(session: Session, job: ImportJob, kind: Kind, ctx: Context, parsed: list, idx: int, heads: dict) -> None:
    dry = job.status == JobStatus.VALIDATING
    fail = RowStatus.INVALID if dry else RowStatus.FAILED
    data, errors = parsed[idx]
    problems = [{"field": f, "code": c, "detail": d} for f, c, d in errors]
    problems += [  # rows skip the request schemas, so free text is checked here (security-baseline 3)
        {"field": f, "code": CARD_DATA, "detail": CARD_DATA_DETAIL}
        for f, v in (data or {}).items()
        if f in FREE_TEXT_FIELDS and isinstance(v, str) and contains_card_number(v)
    ]
    status, entity_type, entity_id, key = fail, None, None, ""
    if not problems:
        key = data["_row_key"] = _row_key(kind, data)
        earlier = session.scalar(select(ImportJobRow.row_number).where(
            ImportJobRow.import_job_id == job.id, ImportJobRow.row_key == key, ImportJobRow.status.in_(_TAKEN),
        ).limit(1))  # fmt: skip
        if earlier is not None:
            status = RowStatus.SKIPPED
            problems = [{"field": "", "code": "duplicate-row", "detail": f"Same as row {earlier}; skipped."}]
        elif kind.once and session.scalar(select(ImportJobRow.id).where(
            ImportJobRow.row_key == key, ImportJobRow.status == RowStatus.CREATED, ImportJobRow.import_job_id != job.id,
        ).limit(1)):  # fmt: skip
            status = RowStatus.SKIPPED
            problems = [{"field": "", "code": "already-imported", "detail": "An earlier import added this row."}]
    if not problems and data.get("household_ref") is not None and kind.key == "clients":
        field, problem, head = _household(kind, parsed, idx, data, heads)
        if problem:
            problems = [{"field": field, "code": "household", "detail": problem}]
        elif head is not None:
            head_row = session.scalar(select(ImportJobRow).where(
                ImportJobRow.import_job_id == job.id, ImportJobRow.row_number == head + 2))  # fmt: skip
            if head_row is None or head_row.status not in _TAKEN or (not dry and head_row.entity_id is None):
                detail = f"The household head (row {head + 2}) was not imported."
                problems = [{"field": "household_ref", "code": "household", "detail": detail}]
            elif not dry:
                data["head_client_id"] = head_row.entity_id
    if not problems:
        result, entity_type, entity_id, created, problems = _apply(session, kind, data, ctx, dry)
        status = result or fail
        if dry and status == RowStatus.VALID and created and "remaining" in job.progress:
            if job.progress.get("creates", 0) >= job.progress["remaining"]:
                status = fail
                problems = [{"field": "", "code": "plan-limit-reached",
                             "detail": "The account's plan has no room for another client."}]  # fmt: skip
            else:
                job.progress = job.progress | {"creates": job.progress.get("creates", 0) + 1}
        if status == RowStatus.VALID:
            job.created_count += created  # a dry run's counts are what a commit would do
            job.updated_count += not created
    job.valid_row_count += status in (RowStatus.VALID, RowStatus.CREATED, RowStatus.UPDATED)
    job.created_count += status == RowStatus.CREATED
    job.updated_count += status == RowStatus.UPDATED
    job.skipped_count += status == RowStatus.SKIPPED
    job.error_count += status == fail
    session.add(ImportJobRow(
        import_job_id=job.id, row_number=idx + 2, row_key=key, status=status, entity_type=entity_type,
        entity_id=entity_id, errors=problems,
    ))  # fmt: skip
    session.flush()


def _write_report(session: Session, job: ImportJob, kind: Kind, phase: str) -> None:
    rows = session.scalars(select(ImportJobRow).where(
        ImportJobRow.import_job_id == job.id, func.jsonb_array_length(ImportJobRow.errors) > 0
    ).order_by(ImportJobRow.row_number))  # every row not imported, and imported rows that carry a warning  # fmt: skip
    labels = {f.key: f.label for f in kind.fields}
    lines: list[list] = [["Row", "Outcome", "Column", "Problem"]]
    words: dict[str, str] = {RowStatus.SKIPPED: "Skipped", RowStatus.INVALID: "Would fail", RowStatus.FAILED: "Failed",
                             RowStatus.VALID: "Would import with a warning"}  # fmt: skip
    for row in rows:
        outcome = words.get(row.status, "Imported with a warning")
        for problem in row.errors:
            column = job.column_mapping.get(problem["field"]) or labels.get(problem["field"], "")
            lines.append([row.row_number, outcome, column, problem["detail"]])
    if len(lines) == 1:
        return
    stored = platform.files.store(
        session, csvio.write(lines), purpose="import_report", content_type="text/csv; charset=utf-8",
        uploaded_by=("system", None), original_name=f"import-{job.kind}-{phase}-report.csv",
        generated=True,  # built by us from an already-scanned source: a scanner outage must not fail the job
    )  # fmt: skip
    job.report_file_id = stored.id


def run_chunk(session: Session, job_id: UUID) -> bool:
    """Internal, for the chunked `run_import` job (system session): process the next `chunk_rows` rows of a job in
    its dry-run or commit phase; True while rows remain. A job in any other state is left alone."""
    job = session.scalars(select(ImportJob).where(ImportJob.id == job_id).with_for_update()).one_or_none()
    if job is None or job.status not in (JobStatus.VALIDATING, JobStatus.IMPORTING) or job.source_file_id is None:
        return False
    if (reason := _submitter_cannot_run(session, job)) is not None:
        _stop(session, job, reason, "submitter-lost-access")
        return False
    kind = KINDS[job.kind]
    size = chunk_rows(session, kind)
    _, raw = platform.files.read(session, job.source_file_id)
    headers, records = csvio.read(csvio.decode(raw))
    ctx = Context(job.location_id, job.date_format, platform.service.location_today(session, job.location_id), job.id,
                  job.submitted_by_staff_user_id, is_dry_run=job.status == JobStatus.VALIDATING)  # fmt: skip
    parsed = [kind.parse(csvio.values(r, headers, job.column_mapping), ctx) if r else None for r in records]
    heads: dict[str, list[int]] = {}
    for i, item in enumerate(parsed):
        if item is not None and item[0].get("household_head") and item[0].get("household_ref"):
            heads.setdefault(item[0]["household_ref"].lower(), []).append(i)
    order = _order(kind, parsed)
    start = job.progress.get("next", 0)
    for idx in order[start : start + size]:
        _process(session, job, kind, ctx, parsed, idx, heads)
    job.progress = job.progress | {"next": min(start + size, len(order))}
    if start + size < len(order):
        return True
    dry = job.status == JobStatus.VALIDATING
    if dry:
        job.status = JobStatus.NEEDS_REVIEW if job.error_count else JobStatus.VALIDATED
        job.progress = job.progress | {"checked_file_id": str(job.source_file_id)}  # start_commit compares it
    else:
        job.status = JobStatus.COMPLETED
    job.finished_at = clock.now()
    _write_report(session, job, kind, "check" if dry else "import")
    session.flush()
    audit.record(session, "imports.import_job.complete" if not dry else "imports.import_job.check", job,
                 location_id=job.location_id, changes={
                     "status": job.status, "valid_row_count": job.valid_row_count, "created_count": job.created_count,
                     "updated_count": job.updated_count, "skipped_count": job.skipped_count,
                     "error_count": job.error_count})  # fmt: skip
    return False


def _submitter_cannot_run(session: Session, job: ImportJob) -> str | None:
    """Plain words when the staff user who started the job may no longer run it (queued jobs must not outlive
    their rights): deactivated, the run key or a location taken away. Step-up is not re-checked off-request."""
    submitter = platform.staff.principal_for(session, job.submitted_by_staff_user_id)
    if submitter is None:
        return "The person who started this import can no longer sign in."
    if RUN not in submitter.permissions or submitter.location_ids is not None:
        return "The person who started this import is no longer allowed to run imports at every location."
    if job.status == JobStatus.IMPORTING and any(k not in submitter.permissions for k in KIND_KEYS[job.kind]):
        return "The person who started this import is no longer allowed to make these changes."
    return None


def _stop(session: Session, job: ImportJob, reason: str, code: str) -> None:
    job.status, job.finished_at = JobStatus.FAILED, clock.now()
    job.progress = job.progress | {"stop_reason": reason}
    session.flush()
    audit.record(session, "imports.import_job.fail", job, location_id=job.location_id,
                 changes={"status": job.status, "reason": code, "processed_row_count": job.progress.get("next", 0)})  # fmt: skip


def fail_job(session: Session, job_id: UUID) -> None:
    """Internal (dead-letter hook of `run_import`): a chunk exhausted its retries, so the running job ends as
    failed instead of showing progress forever. Committed chunks keep their rows; a new import of the same file
    recognises them (clients and products update, memberships and balances are skipped as already imported)."""
    job = session.scalars(select(ImportJob).where(ImportJob.id == job_id).with_for_update()).one_or_none()
    if job is None or job.status not in (JobStatus.VALIDATING, JobStatus.IMPORTING):
        return
    _stop(session, job, "The import stopped because of an error on our side.", "dead-letter")


def fail_stalled(session: Session) -> int:
    """A validating or importing job with no progress for `imports.stalled_minutes` has died (a worker crash can
    lose even the dead letter): mark it failed so its files expire and a new import can start."""
    cutoff = clock.now() - timedelta(minutes=get_settings().imports.stalled_minutes)
    jobs = session.scalars(select(ImportJob).where(
        ImportJob.status.in_((JobStatus.VALIDATING, JobStatus.IMPORTING)), ImportJob.updated_at < cutoff,
    ).with_for_update(skip_locked=True)).all()  # fmt: skip
    for job in jobs:
        _stop(session, job, "The import stopped making progress and was abandoned.", "stalled")
    return len(jobs)


# --- retention ---------------------------------------------------------------------------------------------------


def purge_expired_files(session: Session) -> int:
    """Retention hook (platform.retention.register_purge): remove the source file and error report of jobs past
    `expires_at`, one batch per run, after failing stalled jobs. The job stays as the import's history; its row
    outcomes go RETENTION later (`purge_expired_rows`)."""
    fail_stalled(session)
    jobs = session.scalars(select(ImportJob).where(
        ImportJob.expires_at <= clock.now(), ImportJob.files_purged_at.is_(None),
        ImportJob.status.not_in((JobStatus.VALIDATING, JobStatus.IMPORTING)),
    ).limit(200).with_for_update(skip_locked=True))  # fmt: skip
    count = 0
    for job in jobs:
        for file_id in (job.source_file_id, job.report_file_id):
            if file_id:
                platform.files.remove(session, file_id)
        job.files_purged_at = clock.now()
        count += 1
    session.flush()
    return count


# Read-only: the records an import row can point at that belong to a client (imports sits above these contexts,
# which keep no import knowledge; RLS scopes it to the tenant).
_OWNED = text(
    "SELECT 'membership_contract', id FROM membership_contract WHERE owner_client_id = :c "
    "UNION ALL SELECT 'charge', id FROM charge WHERE client_id = :c "
    "UNION ALL SELECT 'payment', id FROM payment WHERE client_id = :c"
)


def purge_expired_rows(session: Session) -> int:
    """Retention hook: the row outcomes (row keys, problems) of jobs whose files went more than RETENTION ago.
    The job itself, with its counts, stays as the import's history. One batch per run, like the other purges."""
    old = select(ImportJob.id).where(ImportJob.files_purged_at < clock.now() - RETENTION)
    batch = (
        select(ImportJobRow.id).where(ImportJobRow.import_job_id.in_(old)).limit(get_settings().retention.batch_rows)
    )
    return len(session.scalars(delete(ImportJobRow).where(ImportJobRow.id.in_(batch)).returning(ImportJobRow.id)).all())


def erase_client_rows(session: Session, client_id: UUID) -> dict:
    """Erasure (data subject handler): the rows that link this client to an import (their client, contract,
    charge or payment), and the source files and reports of those jobs, which hold the client's cells, now rather
    than at expiry. A running job keeps its file until it ends; the hourly purge removes it at `expires_at`."""
    owned = [(EntityType.CLIENT, client_id), *((kind, entity_id) for kind, entity_id in session.execute(
        _OWNED, {"c": client_id}))]  # fmt: skip
    rows = session.scalars(select(ImportJobRow).where(
        or_(*[and_(ImportJobRow.entity_type == kind, ImportJobRow.entity_id == entity_id) for kind, entity_id in owned])
    )).all()  # fmt: skip
    job_ids = {row.import_job_id for row in rows}
    for job in session.scalars(select(ImportJob).where(
        ImportJob.id.in_(job_ids), ImportJob.files_purged_at.is_(None),
        ImportJob.status.not_in((JobStatus.VALIDATING, JobStatus.IMPORTING)),
    )):  # fmt: skip
        for file_id in (job.source_file_id, job.report_file_id):
            if file_id:
                platform.files.remove(session, file_id)
        job.files_purged_at = clock.now()
    for row in rows:
        session.delete(row)
    session.flush()
    return {"deleted_import_job_rows": len(rows), "purged_import_jobs": len(job_ids)}
