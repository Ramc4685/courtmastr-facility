"""imports HTTP surface (tag imports). Reads need platform.import_job.read; every write needs
platform.import_job.run, which carries step-up (+). The service checks both again on the loaded job."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.imports import schemas as s
from app.modules.imports import service

router = APIRouter(
    route_class=TxRoute, tags=["imports"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]
Read = Annotated[Ctx, Depends(require(service.READ))]
Run = Annotated[Ctx, Depends(require(service.RUN))]


def _every_location(ctx: Run) -> Ctx:
    """Running a check or an import also needs every location (rows match clients anywhere)."""
    service.require_all_locations(ctx.principal)
    return ctx


RunEverywhere = Annotated[Ctx, Depends(_every_location)]


def _csv(data: bytes, name: str) -> Response:
    return Response(
        data, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "private, no-store"},
    )  # fmt: skip


@router.get("/import-templates", response_model=s.Page[s.ImportTemplateOut])
def list_import_templates(ctx: Read):
    return service.list_templates(ctx.principal)


@router.get("/import-templates/{kind}", response_class=Response)
def get_import_template(kind: str, ctx: Read):
    """The template CSV: our columns and one example row."""
    return _csv(service.template_csv(ctx.principal, kind), f"{kind}-import-template.csv")


@router.get("/import-jobs", response_model=s.Page[s.ImportJobOut])
def list_import_jobs(query: Lists, ctx: Read):
    return service.list_jobs(ctx.session, ctx.principal, query)


@router.post("/import-jobs", response_model=s.ImportJobOut, status_code=201)
def create_import_job(body: s.ImportJobCreate, ctx: Run):
    return service.create_job(ctx.session, ctx.principal, body.model_dump())


@router.get("/import-jobs/{import_job_id}", response_model=s.ImportJobOut)
def get_import_job(import_job_id: UUID, ctx: Read):
    return service.get_job(ctx.session, ctx.principal, import_job_id)


@router.put("/import-jobs/{import_job_id}/source", response_model=s.ImportJobOut)
async def upload_import_job_source(import_job_id: UUID, request: Request, ctx: Run):
    """Raw CSV bytes (UTF-8, with or without a BOM; up to 10 MB) with Content-Type text/csv. Optional X-File-Name.
    Errors: file-empty, file-too-large, file-type-mismatch, file-not-utf8, file-not-csv, file-no-header,
    file-duplicate-header, file-too-many-rows, file-infected."""
    data = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip().lower()
    name = request.headers.get("x-file-name")
    return service.upload_source(ctx.session, ctx.principal, import_job_id, data, content_type, name)


@router.post("/import-jobs/{import_job_id}/dry-runs", response_model=s.ImportJobOut, status_code=202)
def create_import_job_dry_run(import_job_id: UUID, body: s.ImportDryRunCreate, ctx: RunEverywhere):
    """Check every row without importing anything; the job moves to validated or needs_review. Needs every
    location (403 all-locations-required)."""
    return service.start_dry_run(ctx.session, ctx.principal, import_job_id, body.model_dump())


@router.post("/import-jobs/{import_job_id}/commits", response_model=s.ImportJobOut, status_code=202)
def create_import_job_commit(import_job_id: UUID, ctx: RunEverywhere):
    """Import the checked rows; the job moves to completed with a report of rows that failed. Needs every
    location (403 all-locations-required) and the keys of the staff commands the type's writes stand for;
    409 check-stale when the file changed after the check."""
    return service.start_commit(ctx.session, ctx.principal, import_job_id)


@router.get("/import-jobs/{import_job_id}/error-report", response_class=Response)
def get_import_job_error_report(import_job_id: UUID, ctx: Read):
    row, data = service.error_report(ctx.session, ctx.principal, import_job_id)
    return _csv(data, (row.original_name or "import-report.csv").replace('"', ""))
