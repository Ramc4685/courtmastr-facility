"""documents HTTP surface (openapi-people.yaml, tag documents): staff, portal and public routes.

GET operation ids start with get/list (a kernel rule for SameSite=Lax), so the portal and public reads are named
getPortal*/listPortal*/getPublicPortalTerms instead of the spec's portalGet*/publicGet*. File downloads stream the stored bytes with the caller's session instead of returning a signed URL: the local-disk
storage adapter has no URL signing (see README).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.core.api import TxRoute, camel_id
from app.core.auth import system_principal, tokens
from app.core.auth.deps import Ctx, current_ctx, public_session, request_session, require
from app.core.context import client_ip
from app.core.errors import NotFound, ValidationFailed
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import rate_limit
from app.modules.documents import schemas as s
from app.modules.documents import service

router = APIRouter(
    route_class=TxRoute, tags=["documents"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
# No Idempotency-Key on the token routes: the token is single-use, so a replayed decision gets 410, never twice.
public = APIRouter(route_class=TxRoute, tags=["documents"], generate_unique_id_function=camel_id)
Lists = Annotated[ListQuery, Depends(list_query)]
Read = Annotated[Ctx, Depends(require("documents.document.read"))]
Generate = Annotated[Ctx, Depends(require("documents.document.generate"))]
Collect = Annotated[Ctx, Depends(require("documents.document.collect_signature"))]
Void = Annotated[Ctx, Depends(require("documents.document.void"))]
Manage = Annotated[Ctx, Depends(require("documents.template.manage"))]
Portal = Annotated[Ctx, Depends(current_ctx)]
ActFor = Annotated[UUID | None, Query(alias="client_id")]


def _meta(request: Request) -> dict:
    return {"ip": client_ip.get(), "user_agent": request.headers.get("user-agent")}


def _file(row, data: bytes) -> Response:
    name = (row.original_name or "document").replace('"', "")
    return Response(
        data, media_type=row.content_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "private, no-store"},
    )  # fmt: skip


def _doc(ctx: Ctx, doc) -> dict:
    return service.document_view(ctx.session, doc)


# --- templates -------------------------------------------------------------------------------------------------


@router.get("/document-templates", response_model=s.Page[s.DocumentTemplateOut])
def list_document_templates(query: Lists, ctx: Generate):
    """Filters: status, kind, is_waiver. q searches the name. Sort: name, created_at."""
    return service.list_templates(ctx.session, ctx.principal, query)


@router.post("/document-templates", response_model=s.DocumentTemplateOut, status_code=201)
def create_document_template(body: s.DocumentTemplateCreate, ctx: Manage):
    """Errors: already-exists (name), consent-template-active (on publish of a second consent template)."""
    return service.create_template(ctx.session, ctx.principal, body.model_dump())


@router.get("/document-templates/{template_id}", response_model=s.DocumentTemplateOut)
def get_document_template(template_id: UUID, ctx: Generate):
    return service.get_template(ctx.session, ctx.principal, template_id)


@router.patch("/document-templates/{template_id}", response_model=s.DocumentTemplateOut)
def update_document_template(template_id: UUID, body: s.DocumentTemplateUpdate, ctx: Manage):
    nullable = {"description", "signature_validity_days"}
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k in nullable}
    return service.update_template(ctx.session, ctx.principal, template_id, data)


@router.get("/document-templates/{template_id}/versions", response_model=s.Page[s.DocumentTemplateVersionOut])
def list_document_template_versions(template_id: UUID, query: Lists, ctx: Manage):
    return service.list_versions(ctx.session, ctx.principal, template_id, query)


@router.put("/document-templates/{template_id}/draft", response_model=s.DocumentTemplateVersionOut)
def save_document_template_draft(template_id: UUID, body: s.DocumentTemplateDraft, ctx: Manage):
    """The body is sanitised to the rich-text allow-list on save. Errors: unknown-merge-field, validation-failed."""
    return service.save_draft(ctx.session, ctx.principal, template_id, body.model_dump(mode="json"))


@router.post("/document-templates/{template_id}/publish", response_model=s.DocumentTemplateOut)
def publish_document_template(template_id: UUID, ctx: Manage):
    """Errors: no-draft, consent-template-active."""
    return service.publish_template(ctx.session, ctx.principal, template_id)


@router.post("/document-templates/{template_id}/archive", response_model=s.DocumentTemplateOut)
def archive_document_template(template_id: UUID, ctx: Manage):
    """Errors: in-use (an active binding)."""
    return service.archive_template(ctx.session, ctx.principal, template_id)


@router.post("/document-templates/{template_id}/restore", response_model=s.DocumentTemplateOut)
def restore_document_template(template_id: UUID, ctx: Manage):
    return service.restore_template(ctx.session, ctx.principal, template_id)


# --- bindings and requirements ---------------------------------------------------------------------------------


@router.get("/document-bindings", response_model=s.Page[s.DocumentBindingOut])
def list_document_bindings(query: Lists, ctx: Generate):
    """Filters: scope_type, scope_id, template_id, is_active."""
    return service.list_bindings(ctx.session, ctx.principal, query)


@router.put("/document-bindings", response_model=s.DocumentBindingOut)
def upsert_document_binding(body: s.DocumentBindingUpsert, ctx: Manage):
    """Replaces the active binding of the scope. Errors: validation-failed."""
    data = body.model_dump()
    if (data["template_id"] is None) == (data["custom_text"] is None):
        raise ValidationFailed("Give either a template or custom text.", pointer="/template_id")
    if (data["scope_id"] is None) != (data["scope_type"] in ("program_default", "portal_terms")):
        raise ValidationFailed("scope_id is required for this scope type, and only for it.", pointer="/scope_id")
    return service.upsert_binding(ctx.session, ctx.principal, data)


@router.delete("/document-bindings/{binding_id}", status_code=204)
def deactivate_document_binding(binding_id: UUID, ctx: Manage):
    service.deactivate_binding(ctx.session, ctx.principal, binding_id)
    return Response(status_code=204)


@router.get("/document-requirements", response_model=s.DocumentRequirementList)
def get_document_requirements(
    ctx: Read, client_id: UUID, scope_type: Annotated[s.ScopeType, Query()], scope_id: UUID | None = None
):
    """What the client must accept before a sale in this scope (the selling context calls the same rule)."""
    return service.get_requirements(ctx.session, ctx.principal, scope_type, scope_id, client_id)


# --- client documents ------------------------------------------------------------------------------------------


@router.get("/client-documents", response_model=s.Page[s.ClientDocumentOut])
def list_client_documents(query: Lists, ctx: Read):
    """Filters: client_id, location_id, template_id, status[in], issued_at[gte|lte], is_deleted (soft-deleted
    documents still recoverable), source_type, source_id. q searches the title. Sort: issued_at."""
    return service.list_client_documents(ctx.session, ctx.principal, query)


@router.post("/client-documents", response_model=s.ClientDocumentOut, status_code=201)
def create_client_document(body: s.ClientDocumentCreate, ctx: Generate, request: Request):
    """Errors: email-not-verified, client-inactive, validation-failed."""
    data = body.model_dump()
    return _doc(ctx, service.create_client_document(ctx.session, ctx.principal, data, _meta(request)))


@router.get("/client-documents/{document_id}", response_model=s.ClientDocumentOut)
def get_client_document(document_id: UUID, ctx: Read):
    return service.get_document(ctx.session, ctx.principal, document_id)


@router.delete("/client-documents/{document_id}", status_code=204)
def delete_client_document(document_id: UUID, ctx: Void):
    """Soft delete; restore within document_settings.deleted_recovery_days."""
    service.delete_document(ctx.session, ctx.principal, document_id)
    return Response(status_code=204)


@router.post("/client-documents/{document_id}/restore", response_model=s.ClientDocumentOut)
def restore_client_document(document_id: UUID, ctx: Void):
    """Errors: recovery-window-lapsed."""
    return service.restore_document(ctx.session, ctx.principal, document_id)


@router.post("/client-documents/{document_id}/void", response_model=s.ClientDocumentOut)
def void_client_document(document_id: UUID, ctx: Void):
    return service.void_document(ctx.session, ctx.principal, document_id)


@router.get("/client-documents/{document_id}/file", response_class=Response)
def get_client_document_file(
    document_id: UUID, ctx: Read, variant: Annotated[str, Query(pattern="^(rendered|paper_scan)$")] = "rendered"
):
    """The PDF of the signed record (rendered) or the uploaded paper copy, as an attachment."""
    return _file(*service.get_document_file(ctx.session, ctx.principal, document_id, variant))


@router.post("/client-documents/{document_id}/acceptances", response_model=s.ClientDocumentOut)
def submit_client_document_acceptance(document_id: UUID, body: s.AcceptanceSubmit, ctx: Collect, request: Request):
    """In-person signing witnessed by the signed-in staff user. Errors: content-mismatch, already-exists,
    guardian-required, invalid-state-transition, validation-failed."""
    data = body.model_dump()
    return service.submit_acceptances(ctx.session, ctx.principal, document_id, data, _meta(request))


@router.get("/client-documents/{document_id}/deliveries", response_model=s.Page[s.DocumentDeliveryOut])
def list_client_document_deliveries(document_id: UUID, query: Lists, ctx: Read):
    return service.list_deliveries(ctx.session, ctx.principal, document_id, query)


@router.post("/client-documents/{document_id}/deliveries", response_model=s.DocumentDeliveryOut, status_code=201)
def send_client_document(document_id: UUID, body: s.DocumentDeliveryCreate, ctx: Collect):
    """Emails a single-use signing link to confirmed addresses of the client or a guardian; supersedes earlier
    links. Errors: email-not-verified, invalid-state-transition."""
    recipients = [str(r) for r in body.recipient_emails]
    return service.send_document(ctx.session, ctx.principal, document_id, recipients)


@router.put("/client-documents/{document_id}/paper-scan", response_model=s.ClientDocumentOut)
async def upload_client_document_paper_scan(document_id: UUID, request: Request, ctx: Collect):
    """Raw file bytes (PDF, JPEG or PNG, up to storage.max_upload_bytes) with their Content-Type; marks the
    document paper-signed. Optional X-File-Name. Errors: file-type-mismatch, file-too-large, file-empty."""
    data = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    name = request.headers.get("x-file-name")
    return service.upload_paper_scan(ctx.session, ctx.principal, document_id, data, content_type, name)


@router.delete("/client-documents/{document_id}/paper-scan", response_model=s.ClientDocumentOut)
def clear_client_document_paper_signed(document_id: UUID, ctx: Collect):
    """Clears the paper-signed flag: accepted -> pending (paper method only)."""
    return service.clear_paper_signed(ctx.session, ctx.principal, document_id)


# --- indicator and settings ------------------------------------------------------------------------------------


@router.get("/client-document-statuses", response_model=s.Page[s.ClientDocumentStatusOut])
def list_client_document_statuses(ctx: Read, client_ids: Annotated[str, Query(alias="client_id[in]")]):
    """Waiver and consent indicator for up to 200 clients."""
    return service.list_statuses(ctx.session, ctx.principal, service.parse_client_ids(client_ids))


@router.put("/client-document-statuses/{client_id}/waiver-override", response_model=s.ClientDocumentStatusOut)
def set_waiver_override(client_id: UUID, body: s.WaiverOverrideIn, ctx: Collect):
    return service.set_waiver_override(ctx.session, ctx.principal, client_id, body.model_dump())


@router.delete("/client-document-statuses/{client_id}/waiver-override", status_code=204)
def clear_waiver_override(client_id: UUID, ctx: Collect):
    service.clear_waiver_override(ctx.session, ctx.principal, client_id)
    return Response(status_code=204)


@router.get("/document-settings", response_model=s.DocumentSettingsOut)
def get_document_settings(ctx: Read):
    return service.get_settings_for(ctx.session, ctx.principal)


@router.patch("/document-settings", response_model=s.DocumentSettingsOut)
def update_document_settings(body: s.DocumentSettingsUpdate, ctx: Manage):
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    return service.update_settings(ctx.session, ctx.principal, data)


@router.get("/document-location-settings/{location_id}", response_model=s.DocumentLocationSettingsOut)
def get_document_location_settings(location_id: UUID, ctx: Read):
    return service.get_location_settings(ctx.session, ctx.principal, location_id)


@router.patch("/document-location-settings/{location_id}", response_model=s.DocumentLocationSettingsOut)
def update_document_location_settings(location_id: UUID, body: s.DocumentLocationSettingsUpdate, ctx: Manage):
    """Errors: consent-template-missing."""
    return service.update_location_settings(ctx.session, ctx.principal, location_id, body.model_dump())


# --- portal ----------------------------------------------------------------------------------------------------


@router.get("/portal/client-documents", response_model=s.Page[s.ClientDocumentOut])
def list_portal_client_documents(query: Lists, ctx: Portal, client_id: ActFor = None):
    """Your documents, or a household member's you may act for (client_id). Filter: status."""
    return service.portal_list(ctx.session, ctx.principal, client_id, query)


@router.get("/portal/client-documents/{document_id}", response_model=s.ClientDocumentOut)
def get_portal_client_document(document_id: UUID, ctx: Portal, client_id: ActFor = None):
    return service.portal_get(ctx.session, ctx.principal, document_id, client_id)


@router.get("/portal/client-documents/{document_id}/file", response_class=Response)
def get_portal_client_document_file(document_id: UUID, ctx: Portal, client_id: ActFor = None):
    return _file(*service.portal_file(ctx.session, ctx.principal, document_id, client_id))


@router.get("/portal/document-requirements", response_model=s.DocumentRequirementList)
def get_portal_document_requirements(
    ctx: Portal, scope_type: Annotated[s.ScopeType, Query()], scope_id: UUID | None = None, client_id: ActFor = None
):
    """Requirements before an online checkout; the pending document of each unmet blocking requirement is issued."""
    return service.portal_requirements(ctx.session, ctx.principal, scope_type, scope_id, client_id)


@router.post("/portal/client-documents/{document_id}/acceptances", response_model=s.ClientDocumentOut)
def portal_submit_acceptance(
    document_id: UUID, body: s.PortalAcceptanceSubmit, ctx: Portal, request: Request, client_id: ActFor = None
):
    """Accept or decline as yourself, or as guardian of a dependent. Errors: content-mismatch, already-exists,
    guardian-required."""
    return service.portal_submit(ctx.session, ctx.principal, document_id, client_id, body.model_dump(), _meta(request))


@router.get("/portal/consent", response_model=s.PortalConsentStateOut)
def get_portal_consent_state(ctx: Portal):
    return service.portal_consent(ctx.session, ctx.principal)


# --- public ------------------------------------------------------------------------------------------------------


def _link_session(request: Request, token: str):
    tenant_id = tokens.tenant_of(token, service.LINK_PREFIX)
    if tenant_id is None:
        raise NotFound("This link is not valid.", code="token-invalid")
    session = request_session(request, tenant_id)
    session.info["actor"] = system_principal("emailed link")
    return session


@public.post("/public/document-deliveries/open", response_model=s.PublicDocumentView,
             dependencies=[Depends(rate_limit("document-link"))])  # fmt: skip
def public_get_document_delivery(body: s.DocumentTokenIn, request: Request):
    """The token travels in the body, never the URL (security-baseline 17.2). Viewing does not consume it.
    Errors: token-invalid (404), token-expired, token-superseded (410)."""
    return service.public_open(_link_session(request, body.token), body.token)


@public.post("/public/document-deliveries/decision", response_model=s.PublicDocumentView,
             dependencies=[Depends(rate_limit("document-link"))])  # fmt: skip
def public_decide_document(body: s.PublicDocumentDecision, request: Request):
    """Accept or decline; any decision consumes the token. Errors: as open, plus content-mismatch."""
    return service.public_decide(_link_session(request, body.token), body.model_dump(), _meta(request))


@public.get("/public/portal-terms", response_model=s.PortalTermsOut)
def get_public_portal_terms(request: Request):
    """The terms a new portal account accepts (DOC-14). Tenant from the host or X-Tenant-Slug."""
    session = public_session(request)
    session.info["actor"] = system_principal("public")
    return service.public_portal_terms(session)
