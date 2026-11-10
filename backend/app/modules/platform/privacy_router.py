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
from app.modules.platform import privacy

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
    bundle: dict[str, Any] | None = None  # a completed export, built when read (7 days)


@router.post("/data-subject-requests", response_model=DsrOut, status_code=201)
def create_data_subject_request(body: DsrCreate, ctx: Annotated[Ctx, Depends(require())]):
    """Export completes at once; erasure is `requested` (or `blocked`) until confirmed. Errors: already-erased."""
    return privacy.create_request(ctx.session, ctx.principal, body.model_dump())


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
    return privacy.confirm_request(ctx.session, ctx.principal, request_id, body.model_dump())
