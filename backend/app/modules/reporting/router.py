"""reporting HTTP surface (openapi-programs.yaml, tag reporting). Every route needs at least one report family
key at the router; the service checks the report's own family key, the caller's locations and ownership.
Download streams the file instead of the spec's 302 to a signed URL: the storage port has no signed URLs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.reporting import dashboard, schedules, service
from app.modules.reporting import schemas as s

router = APIRouter(
    route_class=TxRoute, tags=["reporting"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]
Run = Annotated[Ctx, Depends(require(*service.RUN_KEYS))]
Export = Annotated[Ctx, Depends(require(service.EXPORT))]
Dashboard = Annotated[Ctx, Depends(require(dashboard.KEY))]


@router.get("/report-definitions", response_model=s.Page[s.ReportDefinitionOut])
def list_report_definitions(ctx: Run, category: str | None = None, q: str | None = None):
    return service.list_definitions(ctx.principal, category=category, q=q)


@router.get("/report-definitions/{report_key}", response_model=s.ReportDefinitionOut)
def get_report_definition(report_key: str, ctx: Run):
    return service.get_definition(ctx.principal, report_key)


@router.get("/report-runs", response_model=s.Page[s.ReportRunOut])
def list_report_runs(query: Lists, ctx: Run):
    return service.list_runs(ctx.session, ctx.principal, query)


@router.post("/report-runs", response_model=s.ReportRunOut)
def create_report_run(body: s.ReportRunCreate, ctx: Run):
    return service.create_run(ctx.session, ctx.principal, body.model_dump())


@router.get("/report-runs/{report_run_id}", response_model=s.ReportRunOut)
def get_report_run(report_run_id: UUID, ctx: Run):
    return service.get_run(ctx.session, ctx.principal, report_run_id)


@router.get("/report-runs/{report_run_id}/rows", response_model=s.ReportRowsOut)
def list_report_run_rows(
    report_run_id: UUID, ctx: Run, limit: Annotated[int, Query(ge=1, le=service.ROWS_LIMIT)] = 100,
    cursor: str | None = None, sort: str | None = None, group_key: str | None = None,
):  # fmt: skip
    return service.list_rows(
        ctx.session, ctx.principal, report_run_id, limit=limit, cursor=cursor, sort=sort, group_key=group_key
    )


@router.get("/saved-reports", response_model=s.Page[s.SavedReportOut])
def list_saved_reports(query: Lists, ctx: Run):
    return service.list_saved(ctx.session, ctx.principal, query)


@router.post("/saved-reports", response_model=s.SavedReportOut, status_code=201)
def create_saved_report(body: s.SavedReportCreate, ctx: Run):
    return service.create_saved(ctx.session, ctx.principal, body.model_dump())


@router.get("/saved-reports/{saved_report_id}", response_model=s.SavedReportOut)
def get_saved_report(saved_report_id: UUID, ctx: Run):
    return service.get_saved(ctx.session, ctx.principal, saved_report_id)


@router.patch("/saved-reports/{saved_report_id}", response_model=s.SavedReportOut)
def update_saved_report(saved_report_id: UUID, body: s.SavedReportUpdate, ctx: Run):
    return service.update_saved(ctx.session, ctx.principal, saved_report_id, body.model_dump(exclude_unset=True))


@router.delete("/saved-reports/{saved_report_id}", status_code=204)
def delete_saved_report(saved_report_id: UUID, ctx: Run):
    service.delete_saved(ctx.session, ctx.principal, saved_report_id)
    return Response(status_code=204)


@router.get("/export-jobs", response_model=s.Page[s.ExportJobOut])
def list_export_jobs(query: Lists, ctx: Export):
    return service.list_exports(ctx.session, ctx.principal, query)


@router.post("/export-jobs", response_model=s.ExportJobOut, status_code=202)
def create_export_job(body: s.ExportJobCreate, ctx: Export):
    return service.create_export(ctx.session, ctx.principal, body.model_dump())


@router.get("/export-jobs/{export_job_id}", response_model=s.ExportJobOut)
def get_export_job(export_job_id: UUID, ctx: Export):
    return service.get_export(ctx.session, ctx.principal, export_job_id)


@router.get("/export-jobs/{export_job_id}/download", response_class=Response)
def get_export_job_file(export_job_id: UUID, ctx: Export):
    row, data = service.download_export(ctx.session, ctx.principal, export_job_id)
    name = (row.original_name or "export.csv").replace('"', "")
    return Response(
        data, media_type=row.content_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "private, no-store"},
    )  # fmt: skip


@router.get("/report-definitions/{report_key}/recipients", response_model=s.Page[s.ReportRecipientOut])
def list_report_recipients(report_key: str, ctx: Export):
    return schedules.recipients(ctx.session, ctx.principal, report_key)


@router.get("/report-schedules", response_model=s.Page[s.ReportScheduleOut])
def list_report_schedules(query: Lists, ctx: Export):
    return schedules.list_mine(ctx.session, ctx.principal, query)


@router.post("/report-schedules", response_model=s.ReportScheduleOut, status_code=201)
def create_report_schedule(body: s.ReportScheduleCreate, ctx: Export):
    return schedules.create(ctx.session, ctx.principal, body.model_dump())


@router.get("/report-schedules/{report_schedule_id}", response_model=s.ReportScheduleOut)
def get_report_schedule(report_schedule_id: UUID, ctx: Export):
    return schedules.get(ctx.session, ctx.principal, report_schedule_id)


@router.patch("/report-schedules/{report_schedule_id}", response_model=s.ReportScheduleOut)
def update_report_schedule(report_schedule_id: UUID, body: s.ReportScheduleUpdate, ctx: Export):
    return schedules.update(ctx.session, ctx.principal, report_schedule_id, body.model_dump(exclude_unset=True))


@router.delete("/report-schedules/{report_schedule_id}", status_code=204)
def delete_report_schedule(report_schedule_id: UUID, ctx: Export):
    schedules.delete(ctx.session, ctx.principal, report_schedule_id)
    return Response(status_code=204)


@router.get("/dashboard", response_model=s.DashboardOut)
def get_dashboard(ctx: Dashboard, location_id: UUID | None = None):
    return dashboard.get_dashboard(ctx.session, ctx.principal, location_id)
