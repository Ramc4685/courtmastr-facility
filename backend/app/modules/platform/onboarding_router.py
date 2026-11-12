"""Setup checklist (ONB-01) and support request (ONB-03) routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import StringConstraints

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.core.schemas import In, Out, Page
from app.modules.platform import onboarding

router = APIRouter(
    route_class=TxRoute, tags=["platform"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Setup = Annotated[Ctx, Depends(require(onboarding.CHECKLIST_KEY))]
Support = Annotated[Ctx, Depends(require(onboarding.SUPPORT_KEY))]


class ChecklistStepOut(Out):
    key: str
    label: str
    path: str
    is_done: bool


class ChecklistOut(Out):
    steps: list[ChecklistStepOut]
    done_count: int
    is_complete: bool
    is_dismissed: bool


class ChecklistDismissal(In):
    is_dismissed: bool


class SupportScreenshotOut(Out):
    id: UUID
    content_type: str
    size_bytes: int


class SupportRequestCreate(In):
    category: Literal["question", "problem", "billing", "import", "feedback"]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    screenshot_file_id: UUID | None = None


class SupportRequestOut(Out):
    id: UUID
    category: str
    message: str
    status: str
    screenshot_file_id: UUID | None
    closed_at: datetime | None
    created_at: datetime


@router.get("/onboarding/checklist", response_model=ChecklistOut)
def get_onboarding_checklist(ctx: Setup):
    """Setup steps, each worked out from the account's data now."""
    return onboarding.checklist(ctx.session, ctx.principal)


@router.put("/onboarding/checklist/dismissal", response_model=ChecklistOut)
def put_onboarding_checklist_dismissal(body: ChecklistDismissal, ctx: Setup):
    """Hide or show the checklist for the signed-in staff user only."""
    return onboarding.set_dismissed(ctx.session, ctx.principal, body.model_dump())


@router.put("/support-requests/screenshot", response_model=SupportScreenshotOut, status_code=201)
async def upload_support_screenshot(request: Request, ctx: Support):
    """Raw JPEG or PNG bytes (under 900 KiB); send the returned id as screenshot_file_id.
    Errors: file-type-mismatch, file-too-large, file-empty."""
    content_type = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    data, name = await request.body(), request.headers.get("x-file-name")
    return onboarding.upload_screenshot(ctx.session, ctx.principal, data, content_type, name)


@router.post("/support-requests", response_model=SupportRequestOut, status_code=201)
def create_support_request(body: SupportRequestCreate, ctx: Support):
    """Records the request and emails it to the operator's support address."""
    return onboarding.create_request(ctx.session, ctx.principal, body.model_dump())


@router.get("/support-requests", response_model=Page[SupportRequestOut])
def list_support_requests(query: Annotated[ListQuery, Depends(list_query)], ctx: Support):
    """The caller's own requests. Filter: status."""
    return onboarding.list_requests(ctx.session, ctx.principal, query)


@router.get("/support-requests/{support_request_id}", response_model=SupportRequestOut)
def get_support_request(support_request_id: UUID, ctx: Support):
    return onboarding.get_request(ctx.session, ctx.principal, support_request_id)


@router.post("/support-requests/{support_request_id}/close", response_model=SupportRequestOut)
def close_support_request(support_request_id: UUID, ctx: Support):
    """Errors: invalid-state-transition."""
    return onboarding.close_request(ctx.session, ctx.principal, support_request_id)
