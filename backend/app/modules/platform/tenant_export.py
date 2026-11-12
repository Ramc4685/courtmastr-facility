"""The tenant export bundle (IMP-04): the whole account as a zip of one CSV per table plus a manifest, for an Owner
leaving or keeping their own copy. Built off the request by the chunked `run_tenant_export` job (ADR 0008 section
3: one bounded chunk per message, the cursor and the zip so far on the locked row), stored through `platform.files`,
downloaded by a signed URL, and purged by `purge_expired_exports` once it expires. Every step is audited.

What is in it: every tenant-owned table the app role can read, all its rows (RLS keeps them to this tenant), minus
the plumbing and secrets below. File bytes (scans, photos, logos) are not inside; their `stored_file` rows are.
Per-client exports for a data-subject request stay in `platform.privacy` (one person, built on read).
"""

import csv
import io
import json
import re
import zipfile
from datetime import timedelta
from uuid import UUID

from sqlalchemy import LargeBinary, Table, literal, select, text, true, tuple_, update
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize
from app.core.db import Base
from app.core.errors import Conflict, NotFound
from app.core.jobs import chunked_actor, on_dead_letter, tenant_actor
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules.platform import files
from app.modules.platform.models import TenantExport, TenantExportStatus

KEY = "platform.tenant.export"
CHUNK_ROWS = 5_000  # rows written per job message
# Never exported: sign-in secrets and sessions, job and idempotency plumbing, and the bundles themselves.
SKIP_TABLES = frozenset({
    "auth_session", "auth_token", "mfa_factor", "mfa_recovery_code", "idempotency_key", "outbox_event",
    "processed_event", "failed_job", "tenant_export",
})  # fmt: skip
_SECRET = re.compile(r"hash|secret|token|password|credential|cipher|encrypted|partial|key_prefix")
# Values that open a door even though their names look harmless: badge and card numbers that check a client in.
_SECRET_COLUMNS = frozenset({"credential.value"})
STALE_AFTER = timedelta(minutes=30)  # a queued or running export untouched this long has died: it counts as failed
_FORMULA = ("=", "+", "-", "@", "\t", "\r")  # a spreadsheet would run these as formulas


_READABLE = text(
    "SELECT relname FROM pg_class WHERE relkind = 'r' AND relforcerowsecurity"
    " AND relnamespace = 'public'::regnamespace AND has_table_privilege(oid, 'SELECT')"
)


def tables(session: Session) -> list[Table]:
    """Tenant tables under forced row-level security that the app role may read: platform-held tables with a
    tenant_id (inbound provider webhooks, ...) are neither, so they never enter a bundle."""
    readable = set(session.scalars(_READABLE))
    return sorted(
        (t for t in Base.metadata.tables.values() if t.name in readable and t.name not in SKIP_TABLES),
        key=lambda t: t.name,
    )


def columns(table: Table) -> list:
    return [
        c for c in table.c
        if not _SECRET.search(c.name) and f"{table.name}.{c.name}" not in _SECRET_COLUMNS
        and c.info.get("audit") != "never" and not isinstance(c.type, LargeBinary)
    ]  # fmt: skip


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, default=str)
    text = str(value)
    return "'" + text if isinstance(value, str) and text.startswith(_FORMULA) else text


def view(session: Session, row: TenantExport) -> dict:
    out = {c: getattr(row, c) for c in (
        "id", "status", "requested_by_staff_user_id", "row_count", "error", "started_at", "finished_at",
        "expires_at", "created_at")}  # fmt: skip
    out["progress"] = {"tables_done": row.progress.get("table", 0), "tables_total": len(tables(session))}
    return out


def _load(session: Session, export_id: UUID, *, lock: bool = False) -> TenantExport:
    stmt = select(TenantExport).where(TenantExport.id == export_id)
    row = session.scalars(stmt.with_for_update() if lock else stmt).one_or_none()
    if row is None:
        raise NotFound()
    return row


def create_export(session: Session, principal: Principal) -> dict:
    """Owner only, with a fresh step-up (`OO X +`). One export at a time per tenant."""
    authorize(principal, KEY)
    fail_stale(session)
    busy = session.scalar(select(TenantExport.id).where(TenantExport.status.in_(("queued", "running"))).limit(1))
    if busy:
        raise Conflict("An export is already being built.", code="export-in-progress")
    row = TenantExport(requested_by_staff_user_id=principal.staff_user_id, status=TenantExportStatus.QUEUED)
    session.add(row)
    session.flush()
    audit.record(session, KEY, row, changes={"status": [None, row.status]})
    tenant_id, export_id = str(session.info["tenant_id"]), str(row.id)
    session.info.setdefault("after_commit", []).append(lambda: run_tenant_export.send(tenant_id, export_id))
    return view(session, row)


def list_exports(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, KEY)
    page = paginate(
        session, select(TenantExport), query, id_column=TenantExport.id,
        sort_fields={"created_at": TenantExport.created_at}, default_sort="-created_at",
        filter_fields={"status": TenantExport.status},
    )  # fmt: skip
    page["data"] = [view(session, row) for row in page["data"]]
    return page


def get_export(session: Session, principal: Principal, export_id: UUID) -> dict:
    authorize(principal, KEY)
    return view(session, _load(session, export_id))


def download_url(session: Session, principal: Principal, export_id: UUID) -> dict:
    """A signed URL valid 5 minutes; each issue is audited (who took the whole account, and when)."""
    authorize(principal, KEY)
    row = _load(session, export_id)
    if row.status == TenantExportStatus.EXPIRED or (row.expires_at and row.expires_at <= clock.now()):
        raise NotFound("The export has expired.")
    if row.status != TenantExportStatus.SUCCEEDED or row.file_id is None:
        raise Conflict("The export is not ready.", code="export-not-ready")
    audit.record(session, KEY, row, changes={"download_url_issued": True})
    return {"url": files.download_url(session, row.file_id), "expires_in": files.URL_TTL_SECONDS}


def _after(pk: list, last: list[str] | None):
    """The keyset condition past the last primary key written (stored as text in the row's progress)."""
    if not last:
        return true()
    return tuple_(*pk) > tuple_(*(literal(c.type.python_type(v), c.type) for c, v in zip(pk, last, strict=True)))


def export_chunk(session: Session, export_id: UUID) -> bool:
    """Internal, for the job: write the next CHUNK_ROWS rows of the current table into the zip on the row, or,
    after the last table, store the zip. True while work remains. A table larger than one chunk is split into
    `<table>.csv`, `<table>.2.csv`, ... each with its header. Rows are paged by primary key (keyset), so writes
    between chunks neither skip nor repeat a row; each chunk is its own snapshot, so the bundle is consistent per
    chunk, not across the account. shortcut: the zip so far is held on the row; move to multipart upload past ~1 GB."""
    row = session.scalars(select(TenantExport).where(TenantExport.id == export_id).with_for_update()).one_or_none()
    if row is None or row.status not in (TenantExportStatus.QUEUED, TenantExportStatus.RUNNING):
        return False
    if row.status == TenantExportStatus.QUEUED:
        row.status, row.started_at, row.partial, row.progress = TenantExportStatus.RUNNING, clock.now(), b"", {}
    progress = dict(row.progress)
    index, last, part = progress.get("table", 0), progress.get("after"), progress.get("part", 1)
    counts = progress.get("counts", {})
    every = tables(session)
    finishing = index >= len(every)
    buffer = io.BytesIO(row.partial or b"")
    with zipfile.ZipFile(buffer, "a", zipfile.ZIP_DEFLATED) as archive:
        if not finishing:
            table = every[index]
            cols, pk = columns(table), list(table.primary_key.columns)
            got = session.execute(select(*cols, *pk).where(_after(pk, last)).order_by(*pk).limit(CHUNK_ROWS)).all()
            text = io.StringIO()
            writer = csv.writer(text)
            writer.writerow([c.name for c in cols])
            writer.writerows([_cell(v) for v in line[: len(cols)]] for line in got)
            archive.writestr(f"{table.name}.csv" if part == 1 else f"{table.name}.{part}.csv", text.getvalue())
            counts[table.name] = counts.get(table.name, 0) + len(got)
            if len(got) == CHUNK_ROWS:
                last, part = [str(v) for v in got[-1][len(cols) :]], part + 1
            else:
                index, last, part = index + 1, None, 1
        else:
            archive.writestr("manifest.json", json.dumps({
                "tenant_id": str(session.info["tenant_id"]), "generated_at": clock.now().isoformat(),
                "row_counts": counts, "omitted_tables": sorted(SKIP_TABLES),
                "note": "Secret columns (hashes, tokens, credentials, key prefixes, badge numbers) and file bytes "
                "are not included.",
            }, indent=2))  # fmt: skip
    row.partial = buffer.getvalue()
    row.progress = {"table": index, "after": last, "part": part, "counts": counts}
    if not finishing:
        return True
    now = clock.now()
    stored = files.store(
        session, row.partial, purpose="tenant_export", content_type="application/zip", uploaded_by=("system", None),
        original_name=f"account-export-{now.date().isoformat()}.zip",
    )  # fmt: skip
    row.file_id, row.status, row.partial = stored.id, TenantExportStatus.SUCCEEDED, None
    row.row_count, row.finished_at = sum(counts.values()), now
    row.expires_at = now + timedelta(days=get_settings().retention.tenant_export_days)
    session.flush()
    audit.record(session, "platform.tenant.export.complete", row, changes={"row_count": row.row_count})
    return False


def _fail(session: Session, row: TenantExport, error: str) -> None:
    before = row.status
    row.status, row.error, row.partial, row.finished_at = TenantExportStatus.FAILED, error, None, clock.now()
    session.flush()
    audit.record(session, "platform.tenant.export.fail", row, changes={"status": [before, "failed"]})


def fail_stale(session: Session) -> int:
    """Internal: a queued or running export untouched for STALE_AFTER has died (a worker crash loses even the
    dead letter); mark it failed and drop its partial zip so a new export can start."""
    rows = session.scalars(
        select(TenantExport).where(TenantExport.status.in_(("queued", "running")),
                                   TenantExport.updated_at < clock.now() - STALE_AFTER)
        .with_for_update(skip_locked=True)
    ).all()  # fmt: skip
    for row in rows:
        _fail(session, row, "The export stopped and was abandoned. Start a new one.")
    return len(rows)


@chunked_actor(max_retries=3)
def run_tenant_export(session, export_id: str) -> bool:
    return export_chunk(session, UUID(export_id))


@on_dead_letter("run_tenant_export")
def _export_dead(session: Session, export_id: str) -> None:
    """Retries exhausted: the row says failed (with why) and the partial zip goes."""
    row = session.scalars(select(TenantExport).where(TenantExport.id == UUID(export_id)).with_for_update()).first()
    if row is not None and row.status in (TenantExportStatus.QUEUED, TenantExportStatus.RUNNING):
        _fail(session, row, "The export could not be built. Start a new one; if it fails again, contact support.")


@tenant_actor
def purge_expired_exports(session: Session) -> int:
    """Hourly: an expired bundle's file goes (`files.remove`) and the row says expired; a stalled export is
    failed and any failed row's partial zip is dropped. Idempotent."""
    fail_stale(session)
    session.execute(update(TenantExport).where(TenantExport.status == TenantExportStatus.FAILED,
                                               TenantExport.partial.is_not(None)).values(partial=None))  # fmt: skip
    rows = session.scalars(
        select(TenantExport)
        .where(TenantExport.status == TenantExportStatus.SUCCEEDED, TenantExport.expires_at <= clock.now())
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        if row.file_id:
            files.remove(session, row.file_id)
        row.status, row.file_id = TenantExportStatus.EXPIRED, None
        audit.record(session, "platform.tenant.export.expire", row, changes={"status": ["succeeded", "expired"]})
    session.flush()
    return len(rows)
