"""assessments HTTP surface (openapi-people.yaml, tag assessments): staff routes and the client-visible portal
view. Path ids are named after their table (`assessment_template_id`, not the spec's `template_id`) so the
generated isolation and location suites can fill them. GET ids start with get/list (kernel rule), so the
portal reads are listPortal* instead of the spec's portalList*."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, current_ctx, public_session, require
from app.core.errors import ValidationFailed
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import rate_limit
from app.modules.assessments import schemas as s
from app.modules.assessments import service

router = APIRouter(
    route_class=TxRoute, tags=["assessments"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]
Read = Annotated[Ctx, Depends(require(service.READ))]
Record = Annotated[Ctx, Depends(require(service.RECORD))]
Delete = Annotated[Ctx, Depends(require(service.DELETE))]
Manage = Annotated[Ctx, Depends(require(service.MANAGE))]
Portal = Annotated[Ctx, Depends(current_ctx)]
ActFor = Annotated[UUID | None, Query(alias="client_id")]
ClientId = Annotated[UUID, Query()]
From = Annotated[datetime | None, Query(alias="recorded_at[gte]")]
To = Annotated[datetime | None, Query(alias="recorded_at[lte]")]


# --- definitions ---------------------------------------------------------------------------------------------


@router.get("/assessment-templates", response_model=s.Page[s.AssessmentTemplateOut])
def list_assessment_templates(query: Lists, ctx: Read):
    return service.list_templates(ctx.session, ctx.principal, query)


@router.post("/assessment-templates", response_model=s.AssessmentTemplateOut, status_code=201)
def create_assessment_template(body: s.AssessmentTemplateCreate, ctx: Manage):
    return service.create_template(ctx.session, ctx.principal, body.model_dump())


@router.patch("/assessment-templates/{assessment_template_id}", response_model=s.AssessmentTemplateOut)
def update_assessment_template(assessment_template_id: UUID, body: s.AssessmentTemplateUpdate, ctx: Manage):
    return service.update_template(
        ctx.session, ctx.principal, assessment_template_id, body.model_dump(exclude_unset=True)
    )


@router.post("/assessment-templates/{assessment_template_id}/fields", response_model=s.AssessmentFieldOut,
             status_code=201)  # fmt: skip
def create_assessment_field(assessment_template_id: UUID, body: s.AssessmentFieldCreate, ctx: Manage):
    return service.create_field(ctx.session, ctx.principal, assessment_template_id, body.model_dump())


@router.patch("/assessment-fields/{assessment_field_id}", response_model=s.AssessmentFieldOut)
def update_assessment_field(assessment_field_id: UUID, body: s.AssessmentFieldUpdate, ctx: Manage):
    return service.update_field(ctx.session, ctx.principal, assessment_field_id, body.model_dump(exclude_unset=True))


@router.get("/assessment-settings", response_model=s.AssessmentSettingsOut)
def get_assessment_settings(ctx: Read):
    return service.get_settings(ctx.session, ctx.principal)


@router.patch("/assessment-settings", response_model=s.AssessmentSettingsOut)
def update_assessment_settings(body: s.AssessmentSettingsUpdate, ctx: Manage):
    return service.update_settings(ctx.session, ctx.principal, body.model_dump(exclude_unset=True))


# --- results -------------------------------------------------------------------------------------------------


@router.get("/assessment-results", response_model=s.Page[s.AssessmentResultOut])
def list_assessment_results(client_id: ClientId, query: Lists, ctx: Read):
    return service.list_results(ctx.session, ctx.principal, client_id, query)


@router.post("/assessment-results", response_model=s.AssessmentResultOut, status_code=201)
def create_assessment_result(body: s.AssessmentResultCreate, ctx: Record):
    return service.create_result(ctx.session, ctx.principal, body.model_dump())


@router.get("/assessment-results/{assessment_result_id}", response_model=s.AssessmentResultOut)
def get_assessment_result(assessment_result_id: UUID, ctx: Read):
    return service.get_result(ctx.session, ctx.principal, assessment_result_id)


@router.patch("/assessment-results/{assessment_result_id}", response_model=s.AssessmentResultOut)
def update_assessment_result(assessment_result_id: UUID, body: s.AssessmentResultUpdate, ctx: Record):
    return service.update_result(ctx.session, ctx.principal, assessment_result_id, body.model_dump(exclude_unset=True))


@router.delete("/assessment-results/{assessment_result_id}", status_code=204)
def delete_assessment_result(assessment_result_id: UUID, ctx: Delete):
    service.delete_result(ctx.session, ctx.principal, assessment_result_id)
    return Response(status_code=204)


@router.get("/assessment-series", response_model=s.AssessmentSeriesList)
def get_assessment_series(
    client_id: ClientId, ctx: Read, starts: From = None, ends: To = None,
    assessment_template_id: Annotated[UUID | None, Query()] = None,
    field_ids: Annotated[str | None, Query(alias="assessment_field_id[in]", description="Comma-separated ids")] = None,
):  # fmt: skip
    try:
        ids = [UUID(i) for i in field_ids.split(",")] if field_ids else None
    except ValueError:
        raise ValidationFailed("Not a list of ids.", pointer="/assessment_field_id[in]") from None
    return service.get_series(ctx.session, ctx.principal, client_id, field_ids=ids,
                              template_id=assessment_template_id, starts=starts, ends=ends)  # fmt: skip


# --- portal --------------------------------------------------------------------------------------------------


@router.get("/portal/assessment-results", response_model=s.Page[s.PortalAssessmentResultOut])
def list_portal_assessment_results(query: Lists, ctx: Portal, client_id: ActFor = None):
    """Client-visible results of the acted-for client (404 while sharing is off)."""
    return service.portal_list_results(ctx.session, ctx.principal, client_id, query)


@router.get("/portal/assessment-bests", response_model=list[s.PortalAssessmentBestOut])
def list_portal_assessment_bests(ctx: Portal, client_id: ActFor = None):
    """Personal best and latest value per client-visible field."""
    return service.portal_bests(ctx.session, ctx.principal, client_id)


@router.get("/portal/progress-share-links", response_model=list[s.PortalShareLinkOut])
def list_portal_progress_share_links(ctx: Portal, client_id: ActFor = None):
    """FIT-05: the acted-for client's share links, live and revoked. 404 while sharing is off."""
    return service.portal_list_share_links(ctx.session, ctx.principal, client_id)


@router.post("/portal/progress-share-links", response_model=s.PortalShareLinkCreated, status_code=201)
def create_portal_progress_share_link(body: s.PortalShareLinkCreate, ctx: Portal):
    """A revocable read-only link; the token is in the URL fragment and shown once."""
    return service.portal_create_share_link(ctx.session, ctx.principal, body.model_dump())


@router.post("/portal/progress-share-links/{progress_share_link_id}/revoke", status_code=204)
def revoke_portal_progress_share_link(progress_share_link_id: UUID, ctx: Portal):
    service.portal_revoke_share_link(ctx.session, ctx.principal, progress_share_link_id)
    return Response(status_code=204)


# --- anonymous: the shared progress page ---------------------------------------------------------------------

staff_and_portal = router
public = APIRouter(route_class=TxRoute, tags=["assessments"], generate_unique_id_function=camel_id)


@public.post("/public/progress-shares/lookup", response_model=s.SharedProgressOut,
             dependencies=[Depends(rate_limit("consume"))])  # fmt: skip
def get_shared_progress(body: s.SharedProgressLookup, session: Annotated[Session, Depends(public_session)]):
    """FIT-05: what a live share link shows. The token travels in the body, never the URL. Errors: 404."""
    return service.shared_progress(session, body.token)


router = APIRouter()
router.include_router(staff_and_portal)
router.include_router(public)
