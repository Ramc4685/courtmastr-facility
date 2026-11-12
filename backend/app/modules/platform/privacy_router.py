"""Data subject request routes (openapi-core.yaml): GDPR export and erasure of a client."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import StringConstraints

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.core.schemas import In, Out, Page
from app.modules.platform import privacy, tenant_export

router = APIRouter(
    route_class=TxRoute, tags=["platform"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)


class DsrCreate(In):
    client_id: UUID
    kind: Literal["export", "erasure"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None


class DsrConfirm(In):
    confirmation: Annotated[str, StringConstraints(max_length=10)]  # must be ERASE
    is_blocker_override: bool = False


class DsrOut(Out):
    id: UUID
    client_id: UUID
    kind: str
    status: str
    requested_by_staff_user_id: UUID
    reason: str | None
    blockers: list[dict[str, Any]]
    is_blocker_override: bool
    handler_results: dict[str, Any]
    confirmed_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    due_at: datetime  # the GDPR response deadline: 30 days after the request (PLT-16)
    is_overdue: bool
    bundle: dict[str, Any] | None = None  # a completed export, built when read (7 days)


@router.post("/data-subject-requests", response_model=DsrOut, status_code=201)
def create_data_subject_request(body: DsrCreate, ctx: Annotated[Ctx, Depends(require())]):
    """Export completes at once; erasure is `requested` (or `blocked`) until confirmed. Errors: already-erased."""
    return privacy.view(privacy.create_request(ctx.session, ctx.principal, body.model_dump()))


@router.get("/data-subject-requests", response_model=Page[DsrOut])
def list_data_subject_requests(
    query: Annotated[ListQuery, Depends(list_query)],
    ctx: Annotated[Ctx, Depends(require("platform.data_subject_request.read"))],
):
    """Filters: client_id, kind, status."""
    return privacy.list_requests(ctx.session, ctx.principal, query)


@router.get("/data-subject-requests/{request_id}", response_model=DsrOut)
def get_data_subject_request(
    request_id: UUID, ctx: Annotated[Ctx, Depends(require("platform.data_subject_request.read"))]
):
    return privacy.get_request(ctx.session, ctx.principal, request_id)


@router.post("/data-subject-requests/{request_id}/confirm", response_model=DsrOut)
def confirm_data_subject_request(
    request_id: UUID, body: DsrConfirm, ctx: Annotated[Ctx, Depends(require("platform.data_subject_request.erase"))]
):
    """Type ERASE. Errors: erasure-blocked (send is_blocker_override to proceed)."""
    return privacy.view(privacy.confirm_request(ctx.session, ctx.principal, request_id, body.model_dump()))


# --- GDPR mode (PLT-16) and the tenant export bundle (IMP-04) --------------------------------------------------


class PrivacySettings(In):
    is_gdpr_mode: bool


class PrivacySettingsOut(Out):
    is_gdpr_mode: bool


class TenantExportProgress(Out):
    tables_done: int
    tables_total: int


class TenantExportOut(Out):
    id: UUID
    status: str
    requested_by_staff_user_id: UUID
    row_count: int | None
    error: str | None
    progress: TenantExportProgress
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class TenantExportDownload(Out):
    url: str
    expires_in: int


Security = Annotated[Ctx, Depends(require("platform.security.manage"))]
Export = Annotated[Ctx, Depends(require(tenant_export.KEY))]


@router.get("/privacy-settings", response_model=PrivacySettingsOut)
def get_privacy_settings(ctx: Security):
    return privacy.get_privacy_settings(ctx.session, ctx.principal)


@router.put("/privacy-settings", response_model=PrivacySettingsOut)
def put_privacy_settings(body: PrivacySettings, ctx: Security):
    """GDPR mode: express marketing consent only, shorter retention of sessions and sign-in links."""
    return privacy.put_privacy_settings(ctx.session, ctx.principal, body.model_dump())


@router.post("/tenant-exports", response_model=TenantExportOut, status_code=202)
def create_tenant_export(ctx: Export):
    """Owner only, after a fresh step-up. Builds a zip of every table in the background.
    Errors: export-in-progress, step-up-required."""
    return tenant_export.create_export(ctx.session, ctx.principal)


@router.get("/tenant-exports", response_model=Page[TenantExportOut])
def list_tenant_exports(query: Annotated[ListQuery, Depends(list_query)], ctx: Export):
    """Filter: status."""
    return tenant_export.list_exports(ctx.session, ctx.principal, query)


@router.get("/tenant-exports/{tenant_export_id}", response_model=TenantExportOut)
def get_tenant_export(tenant_export_id: UUID, ctx: Export):
    return tenant_export.get_export(ctx.session, ctx.principal, tenant_export_id)


@router.post("/tenant-exports/{tenant_export_id}/download-url", response_model=TenantExportDownload)
def create_tenant_export_download_url(tenant_export_id: UUID, ctx: Export):
    """A signed link valid 5 minutes. Errors: export-not-ready; 404 once expired."""
    return tenant_export.download_url(ctx.session, ctx.principal, tenant_export_id)
