"""documents service: templates and versions, bindings and requirements, issued documents, signatures and evidence,
emailed links, the waiver indicator, settings (DOC-01..DOC-09, DOC-14, DOC-15).

Staff functions take a principal and authorize; internal functions other contexts call (`requirements_for`,
`ensure_pending`, `consume`, `status_for`, `has_valid_waiver`) take none: the selling context's staff or portal
command carries the gate (ADR 0009 section 9).
"""

import base64
import binascii
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, system_principal, tokens
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.core.jobs import tenant_actor
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import clients, platform
from app.modules.documents.domain import content, pdf, signing
from app.modules.documents.events import DocumentAccepted, DocumentDeclined, DocumentExpired, DocumentSent
from app.modules.documents.models import (
    ClientDocument,
    ClientDocumentStatus,
    DocumentAcceptance,
    DocumentBinding,
    DocumentDelivery,
    DocumentLocationSettings,
    DocumentSettings,
    DocumentTemplate,
    DocumentTemplateVersion,
)
from app.modules.platform import files
from app.ports import notifications

_READ = "documents.document.read"
_GENERATE = "documents.document.generate"
_COLLECT = "documents.document.collect_signature"
_VOID = "documents.document.void"
_MANAGE = "documents.template.manage"
SIGNATURE_MAX_BYTES = 300_000
LINK_PREFIX = "fhd"

CONSTRAINT_CODES["uq_document_template_active_consent"] = "consent-template-active"

notifications.register_template(
    "documents.signing_link",
    subject="$organization: please review $title",
    body='Hello $name,\n\n$organization asks you to review and sign "$title". Open the link below to read it and '
    "accept or decline.\n\n$url\n\nThe link works once and expires on $expires (UTC). If you were not expecting "
    "this, ignore this message.",
)


def _gone(code: str, detail: str) -> DomainError:
    return DomainError(detail, status=410, code=code)


def _actor_staff_id(principal: Principal) -> UUID | None:
    return principal.staff_user_id if principal.kind == "staff" else None


# --- settings (DOC-04, DOC-06, DOC-09, DOC-15) ----------------------------------------------------------------


def settings_row(session: Session) -> DocumentSettings:
    row = session.scalar(select(DocumentSettings))
    if row is None:
        row = DocumentSettings()
        session.add(row)
        session.flush()
    return row


def get_settings_for(session: Session, principal: Principal) -> DocumentSettings:
    authorize(principal, _READ)
    return settings_row(session)


def update_settings(session: Session, principal: Principal, data: dict) -> DocumentSettings:
    authorize(principal, _MANAGE)
    row = settings_row(session)
    for key, value in data.items():
        setattr(row, key, value)
    audit.record(session, _MANAGE, row, changes=audit.diff(row))
    session.flush()
    return row


def _location(session: Session, location_id: UUID, principal: Principal | None = None, pointer: str = "/location_id"):
    try:
        return platform.service.get_location(session, principal or system_principal("documents"), location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer=pointer) from None


def _location_settings(session: Session, location_id: UUID) -> DocumentLocationSettings:
    row = session.scalar(select(DocumentLocationSettings).where(DocumentLocationSettings.location_id == location_id))
    if row is None:
        row = DocumentLocationSettings(location_id=location_id)
        session.add(row)
        session.flush()
    return row


def get_location_settings(session: Session, principal: Principal, location_id: UUID) -> DocumentLocationSettings:
    platform.service.get_location(session, principal, location_id)
    authorize(principal, _READ)
    return _location_settings(session, location_id)


def update_location_settings(session: Session, principal: Principal, location_id: UUID, data: dict):
    platform.service.get_location(session, principal, location_id)
    authorize(principal, _MANAGE)
    row = _location_settings(session, location_id)
    if data.get("is_consent_required") and _active_consent_template(session) is None:
        raise Conflict("Publish a consent template before requiring consent.", code="consent-template-missing")
    for key, value in data.items():
        setattr(row, key, value)
    audit.record(session, _MANAGE, row, location_id=location_id, changes=audit.diff(row))
    session.flush()
    return row


# --- templates and versions (DOC-01) ---------------------------------------------------------------------------


def version_view(row: DocumentTemplateVersion) -> dict:
    body = row.body_html
    if row.sanitizer_version < content.SANITIZER_VERSION:  # a tightened policy applies without a data migration
        body = content.sanitize(body)
    return {
        "id": row.id, "version_number": row.version_number, "body_html": body, "acceptance_text": row.acceptance_text,
        "body_sha256": row.body_sha256, "signature_blocks": row.signature_blocks, "published_at": row.published_at,
        "change_note": row.change_note,
    }  # fmt: skip


def _draft(session: Session, template_id: UUID) -> DocumentTemplateVersion | None:
    return session.scalar(
        select(DocumentTemplateVersion).where(
            DocumentTemplateVersion.template_id == template_id, DocumentTemplateVersion.published_at.is_(None)
        )
    )


def template_view(session: Session, row: DocumentTemplate) -> dict:
    current = session.get(DocumentTemplateVersion, row.current_version_id) if row.current_version_id else None
    view = {c.key: getattr(row, c.key) for c in DocumentTemplate.__table__.columns if c.key != "tenant_id"}
    return view | {
        "current_version": current and version_view(current),
        "has_draft": _draft(session, row.id) is not None,
    }


def _template(session: Session, template_id: UUID) -> DocumentTemplate:
    row = session.get(DocumentTemplate, template_id)
    if row is None:
        raise NotFound()
    return row


def list_templates(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _GENERATE)
    page = paginate(
        session, select(DocumentTemplate), query, id_column=DocumentTemplate.id,
        sort_fields={"name": DocumentTemplate.name, "created_at": DocumentTemplate.created_at}, default_sort="name",
        filter_fields={"status": DocumentTemplate.status, "kind": DocumentTemplate.kind,
                       "is_waiver": DocumentTemplate.is_waiver},
        search=(DocumentTemplate.name,),
    )  # fmt: skip
    return page | {"data": [template_view(session, row) for row in page["data"]]}


def get_template(session: Session, principal: Principal, template_id: UUID) -> dict:
    authorize(principal, _GENERATE)
    return template_view(session, _template(session, template_id))


def create_template(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, _MANAGE)
    row = DocumentTemplate(**data)
    session.add(row)
    session.flush()
    audit.record(session, _MANAGE, row, changes={"name": row.name, "kind": row.kind, "is_waiver": row.is_waiver})
    return template_view(session, row)


def update_template(session: Session, principal: Principal, template_id: UUID, data: dict) -> dict:
    authorize(principal, _MANAGE)
    row = _template(session, template_id)
    for key, value in data.items():
        setattr(row, key, value)
    audit.record(session, _MANAGE, row, changes=audit.diff(row))
    session.flush()
    return template_view(session, row)


def list_versions(session: Session, principal: Principal, template_id: UUID, query: ListQuery) -> dict:
    authorize(principal, _MANAGE)
    _template(session, template_id)
    page = paginate(
        session, select(DocumentTemplateVersion).where(DocumentTemplateVersion.template_id == template_id), query,
        id_column=DocumentTemplateVersion.id, sort_fields={"version_number": DocumentTemplateVersion.version_number},
        default_sort="-version_number",
    )  # fmt: skip
    return page | {"data": [version_view(row) for row in page["data"]]}


def save_draft(session: Session, principal: Principal, template_id: UUID, data: dict) -> dict:
    """Create or replace the one open draft. The body is sanitised here, on write (security-baseline 9.2)."""
    authorize(principal, _MANAGE)
    template = _template(session, template_id)
    if template.status == "archived":
        raise Conflict("Restore the template before editing it.")
    body = content.sanitize(data["body_html"])
    if not body:
        raise ValidationFailed("The document needs some text.", pointer="/body_html")
    if unknown := content.unknown_fields(body, data["acceptance_text"]):
        raise ValidationFailed(
            f"Unknown merge fields: {', '.join(unknown)}.", pointer="/body_html", code="unknown-merge-field"
        )
    blocks = data.get("signature_blocks") or signing.DEFAULT_BLOCKS
    if problem := signing.check_blocks(blocks):
        raise ValidationFailed(problem, pointer="/signature_blocks")
    draft = _draft(session, template_id)
    if draft is None:
        latest = session.scalar(
            select(func.max(DocumentTemplateVersion.version_number)).where(
                DocumentTemplateVersion.template_id == template_id
            )
        )
        draft = DocumentTemplateVersion(template_id=template_id, version_number=(latest or 0) + 1)
        session.add(draft)
    draft.body_html, draft.acceptance_text, draft.change_note = body, data["acceptance_text"], data.get("change_note")
    draft.signature_blocks, draft.sanitizer_version = blocks, content.SANITIZER_VERSION
    draft.body_sha256 = content.content_hash(body, data["acceptance_text"])
    session.flush()
    audit.record(session, _MANAGE, template, changes={"draft_version": draft.version_number})
    return version_view(draft)


def publish_template(session: Session, principal: Principal, template_id: UUID) -> dict:
    authorize(principal, _MANAGE)
    template = _template(session, template_id)
    if template.status == "archived":
        raise Conflict("Restore the template before publishing it.")
    draft = _draft(session, template_id)
    if draft is None:
        raise Conflict("There is no draft to publish.", code="no-draft")
    draft.published_at, draft.published_by_staff_user_id = clock.now(), _actor_staff_id(principal)
    template.current_version_id, template.status = draft.id, "active"
    audit.record(
        session, _MANAGE, template, changes={**audit.diff(template), "published_version": draft.version_number}
    )
    session.flush()
    return template_view(session, template)


def archive_template(session: Session, principal: Principal, template_id: UUID) -> dict:
    authorize(principal, _MANAGE)
    template = _template(session, template_id)
    if template.status == "archived":
        raise Conflict("The template is already archived.")
    bound = session.scalar(
        select(func.count()).where(DocumentBinding.template_id == template_id, DocumentBinding.is_active)
    )
    if bound:
        raise Conflict("A plan or program still requires this template; remove the binding first.", code="in-use")
    template.status = "archived"
    audit.record(session, _MANAGE, template, changes=audit.diff(template))
    session.flush()
    return template_view(session, template)


def restore_template(session: Session, principal: Principal, template_id: UUID) -> dict:
    authorize(principal, _MANAGE)
    template = _template(session, template_id)
    if template.status != "archived":
        raise Conflict("Only an archived template can be restored.")
    template.status = "active" if template.current_version_id else "draft"
    audit.record(session, _MANAGE, template, changes=audit.diff(template))
    session.flush()
    return template_view(session, template)


def _active_consent_template(session: Session) -> DocumentTemplate | None:
    return session.scalar(
        select(DocumentTemplate).where(DocumentTemplate.kind == "consent", DocumentTemplate.status == "active")
    )


# --- bindings and requirements (DOC-08, DOC-14) ----------------------------------------------------------------


def binding_view(row: DocumentBinding) -> dict:
    return {c.key: getattr(row, c.key) for c in DocumentBinding.__table__.columns if c.key != "tenant_id"}


def list_bindings(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _GENERATE)
    page = paginate(
        session, select(DocumentBinding), query, id_column=DocumentBinding.id,
        sort_fields={"created_at": DocumentBinding.created_at}, default_sort="-created_at",
        filter_fields={"scope_type": DocumentBinding.scope_type, "scope_id": DocumentBinding.scope_id,
                       "template_id": DocumentBinding.template_id, "is_active": DocumentBinding.is_active},
    )  # fmt: skip
    return page | {"data": [binding_view(row) for row in page["data"]]}


def _active_binding(session: Session, scope_type: str, scope_id: UUID | None) -> DocumentBinding | None:
    return session.scalar(
        select(DocumentBinding).where(
            DocumentBinding.scope_type == scope_type,
            DocumentBinding.scope_id.is_(None) if scope_id is None else DocumentBinding.scope_id == scope_id,
            DocumentBinding.is_active,
        )
    )


def upsert_binding(session: Session, principal: Principal, data: dict) -> dict:
    """One active binding per scope: replaced in place. scope_id is opaque here; the owning context validates it."""
    authorize(principal, _MANAGE)
    if data.get("template_id"):
        template = session.get(DocumentTemplate, data["template_id"])
        if template is None or template.status != "active":
            raise ValidationFailed("Choose an active template.", pointer="/template_id")
    row = _active_binding(session, data["scope_type"], data.get("scope_id"))
    if row is None:
        row = DocumentBinding()
        session.add(row)
    for key, value in data.items():
        setattr(row, key, value)
    if "template_id" in data or "custom_text" in data:  # exactly one of the two, the other cleared
        row.template_id, row.custom_text = data.get("template_id"), data.get("custom_text")
    session.flush()
    audit.record(session, _MANAGE, row, changes=audit.diff(row) or {"scope_type": row.scope_type})
    return binding_view(row)


def deactivate_binding(session: Session, principal: Principal, binding_id: UUID) -> None:
    authorize(principal, _MANAGE)
    row = session.get(DocumentBinding, binding_id)
    if row is None:
        raise NotFound()
    row.is_active = False
    audit.record(session, _MANAGE, row, changes=audit.diff(row))
    session.flush()


def _binding_for(session: Session, scope_type: str, scope_id: UUID | None) -> DocumentBinding | None:
    """A program without its own binding falls back to the program default (data-model 2.3)."""
    found = _active_binding(session, scope_type, scope_id)
    if found is None and scope_type == "program_group":
        found = _active_binding(session, "program_default", None)
    return found


def _today(session: Session, location_id: UUID | None = None) -> date:
    if location_id is not None:
        return platform.service.location_today(session, location_id)
    zone = ZoneInfo(platform.service.get_tenant(session).default_time_zone)
    return clock.now().astimezone(zone).date()


def _is_valid(doc: ClientDocument, today: date) -> bool:
    return doc.status == "accepted" and doc.deleted_at is None and (doc.expires_on is None or doc.expires_on >= today)


def requirements_for(
    session: Session, scope_type: str, scope_id: UUID | None, client_id: UUID, *, online: bool = False,
    source: tuple[str, str, UUID] | None = None,
) -> list[dict]:  # fmt: skip
    """What `client_id` must accept before a sale or sign-up in this scope completes. Internal.

    first_purchase: satisfied by any valid acceptance of the template (or of this binding's custom text).
    every_purchase: satisfied by a valid acceptance issued for this binding that no sale has consumed yet, or one
    already consumed by `source` (a retried sale). The selling context calls `consume` when the sale completes.
    """
    binding = _binding_for(session, scope_type, scope_id)
    if binding is None:
        return []
    stmt = select(ClientDocument).where(ClientDocument.client_id == client_id, ClientDocument.deleted_at.is_(None))
    if binding.frequency == "first_purchase" and binding.template_id:
        stmt = stmt.where(ClientDocument.template_id == binding.template_id)
    else:
        stmt = stmt.where(ClientDocument.binding_id == binding.id)
        if binding.frequency == "every_purchase":
            unused = ClientDocument.source_id.is_(None)
            stmt = stmt.where(unused if source is None else unused | (ClientDocument.source_id == source[2]))
    today = _today(session)
    docs = list(session.scalars(stmt.order_by(ClientDocument.issued_at.desc())))
    satisfied = next((d for d in docs if _is_valid(d, today)), None)
    pending = next((d for d in docs if d.status == "pending"), None)
    template = session.get(DocumentTemplate, binding.template_id) if binding.template_id else None
    client = clients.service.get(session, client_id)
    return [{
        "binding_id": binding.id, "template_id": binding.template_id,
        "title": template.name if template else "Terms and conditions",
        "is_satisfied": satisfied is not None, "satisfied_by_document_id": satisfied and satisfied.id,
        "pending_document_id": pending and pending.id,
        "requires_guardian": bool(template and _requires_guardian(session, template, client, today)),
        "is_blocking": binding.is_enforced_online if online else binding.is_enforced_at_desk,
    }]  # fmt: skip


def get_requirements(session: Session, principal: Principal, scope_type: str, scope_id: UUID | None, client_id: UUID):
    clients.service.load(session, principal, client_id, _READ)
    return {"requirements": requirements_for(session, scope_type, scope_id, client_id)}


def ensure_pending(
    session: Session, binding_id: UUID, client_id: UUID, location_id: UUID, *, method: str = "checkbox",
    origin: str = "sale",
) -> ClientDocument:  # fmt: skip
    """The pending document a checkout presents for this binding, issued on first call. Internal."""
    binding = session.get(DocumentBinding, binding_id)
    if binding is None:
        raise NotFound()
    pending = session.scalar(
        select(ClientDocument).where(
            ClientDocument.binding_id == binding_id, ClientDocument.client_id == client_id,
            ClientDocument.status == "pending", ClientDocument.deleted_at.is_(None),
        )
    )  # fmt: skip
    if pending is not None:
        return pending
    template = session.get(DocumentTemplate, binding.template_id) if binding.template_id else None
    return issue(
        session, client=clients.service.get(session, client_id), location_id=location_id, template=template,
        binding=binding, method=method, origin=origin,
    )  # fmt: skip


def consume(session: Session, document_ids: list[UUID], source: tuple[str, str, UUID]) -> None:
    """Record the sale (context, type, id) that used these acceptances, so an every_purchase binding asks again
    next time. Internal; idempotent for the same source."""
    for doc in session.scalars(select(ClientDocument).where(ClientDocument.id.in_(document_ids))):
        if doc.source_id is None:
            doc.source_context, doc.source_type, doc.source_id = source
            audit.record(session, _GENERATE, doc, changes={"source_type": doc.source_type})
    session.flush()


# --- issuing (DOC-02) -------------------------------------------------------------------------------------------


def _requires_guardian(session: Session, template: DocumentTemplate, client, on: date) -> bool:
    return template.requires_guardian_for_minors and clients.service.is_minor(client, on, template.minor_age_years)


def _merge_values(session: Session, client, location, on: date) -> dict[str, str | None]:
    return {
        "client.first_name": client.first_name, "client.last_name": client.last_name,
        "client.full_name": clients.service.display_name(client), "client.member_number": client.member_number,
        "client.birth_date": client.birth_on.isoformat() if client.birth_on else None,
        "location.name": location.name, "organization.name": platform.service.get_tenant(session).name,
        "document.date": on.isoformat(),
    }  # fmt: skip


def issue(
    session: Session, *, client, location_id: UUID, method: str, origin: str, template: DocumentTemplate | None = None,
    binding: DocumentBinding | None = None, title: str | None = None, issued_by: UUID | None = None,
) -> ClientDocument:  # fmt: skip
    """Render the template's current version (or the binding's plain terms) into a pinned snapshot and its PDF."""
    location = _location(session, location_id)
    on = _today(session, location_id)
    version = session.get(DocumentTemplateVersion, template.current_version_id) if template else None
    if version is not None:
        values = _merge_values(session, client, location, on)
        body = content.merge(version_view(version)["body_html"], values, escape=True)
        acceptance = content.merge(version.acceptance_text, values, escape=False)
        blocks = version.signature_blocks
    elif binding is not None and binding.custom_text:
        body, acceptance = f"<p>{content.sanitize(binding.custom_text)}</p>", "I have read and accept these terms."
        blocks = signing.DEFAULT_BLOCKS
    else:  # an uploaded document: the scan is the content
        body, acceptance, blocks = "", "", []
    doc = ClientDocument(
        client_id=client.id, location_id=location_id, template_id=template and template.id,
        template_version_id=version and version.id, title=title or (template.name if template else "Terms and conditions"),
        description=template and template.description, origin=origin, binding_id=binding and binding.id,
        acceptance_method=method, status="pending", issued_by_staff_user_id=issued_by, issued_at=clock.now(),
        requires_guardian=bool(template and _requires_guardian(session, template, client, on)), body_html=body,
        acceptance_text=acceptance, signature_blocks=blocks, content_sha256=content.content_hash(body, acceptance),
    )  # fmt: skip
    session.add(doc)
    if template is not None:
        template.last_used_at = clock.now()
    session.flush()
    if body:
        _render(session, doc)
    audit.record(session, _GENERATE, doc, location_id=location_id, changes={
        "status": [None, "pending"], "origin": [None, origin], "title": doc.title,
    })  # fmt: skip
    return doc


def create_client_document(session: Session, principal: Principal, data: dict, request_meta: dict) -> ClientDocument:
    """Issue a template to a client, or (no template, a title, paper) open a record for an uploaded document.
    acceptance_method email_link sends the first link to recipient_emails."""
    authorize(principal, _GENERATE)
    client = clients.service.require_active(session, data["client_id"])
    clients.service.load(session, principal, client.id, _GENERATE)
    _location(session, data["location_id"], principal)
    template = None
    if data.get("template_id"):
        template = session.get(DocumentTemplate, data["template_id"])
        if template is None or template.status != "active" or template.current_version_id is None:
            raise ValidationFailed("Choose an active template.", pointer="/template_id")
    elif not data.get("title") or data["acceptance_method"] != "paper":
        raise ValidationFailed("Give a template, or a title for an uploaded paper document.", pointer="/template_id")
    if data["acceptance_method"] == "email_link" and not data.get("recipient_emails"):
        raise ValidationFailed("Choose who receives the link.", pointer="/recipient_emails")
    doc = issue(
        session, client=client, location_id=data["location_id"], template=template, method=data["acceptance_method"],
        origin="consent" if template and template.kind == "consent" else ("import" if template is None else "manual"),
        title=data.get("title"), issued_by=_actor_staff_id(principal),
    )  # fmt: skip
    if data["acceptance_method"] == "email_link":
        _send(session, doc, data["recipient_emails"], _actor_staff_id(principal))
    return doc


# --- reading -------------------------------------------------------------------------------------------------


def acceptance_view(row: DocumentAcceptance) -> dict:
    keys = ("id", "decision", "signer_role", "signer_client_id", "signer_name", "method", "typed_signature",
            "signature_file_id", "decided_at", "witnessed_by_staff_user_id")  # fmt: skip
    return {k: getattr(row, k) for k in keys}


def _acceptances(session: Session, doc_id: UUID) -> list[DocumentAcceptance]:
    return list(
        session.scalars(
            select(DocumentAcceptance)
            .where(DocumentAcceptance.client_document_id == doc_id)
            .order_by(DocumentAcceptance.decided_at)
        )
    )


def document_view(session: Session, doc: ClientDocument) -> dict:
    view = {c.key: getattr(doc, c.key) for c in ClientDocument.__table__.columns if c.key != "tenant_id"}
    view["client_name"] = clients.service.display_name(clients.service.get(session, doc.client_id))
    view["required_roles"] = sorted(signing.required_roles(doc.signature_blocks, doc.requires_guardian))
    return view | {"acceptances": [acceptance_view(a) for a in _acceptances(session, doc.id)]}


def _doc(session: Session, doc_id: UUID) -> ClientDocument:
    doc = session.get(ClientDocument, doc_id)
    if doc is None:
        raise NotFound()
    return doc


def load_document(session: Session, principal: Principal, doc_id: UUID, key: str) -> ClientDocument:
    """The document, if the caller reaches its client with `key` (own reach for coaches); else 404."""
    doc = _doc(session, doc_id)
    clients.service.load(session, principal, doc.client_id, key)
    if key in (_VOID,):
        authorize(principal, key, location_id=doc.location_id)
    return doc


def list_client_documents(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Document history (DOC-06). Visible across locations (CLI-19); location_id is a filter, not a scope.
    is_deleted=true lists soft-deleted documents inside the recovery window instead of live ones."""
    stmt = select(ClientDocument)
    if (reach := clients.service.reach_filter(principal, _READ, ClientDocument.client_id)) is not None:
        stmt = stmt.where(reach)
    filters = dict(query.filters)
    if filters.pop("is_deleted", "false").lower() == "true":
        stmt = stmt.where(ClientDocument.deleted_at.is_not(None), ClientDocument.status != "voided")
    else:
        stmt = stmt.where(ClientDocument.deleted_at.is_(None))
    page = paginate(
        session, stmt, ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters),
        id_column=ClientDocument.id, sort_fields={"issued_at": ClientDocument.issued_at}, default_sort="-issued_at",
        filter_fields={
            "client_id": ClientDocument.client_id, "location_id": ClientDocument.location_id,
            "template_id": ClientDocument.template_id, "status": ClientDocument.status,
            "issued_at": ClientDocument.issued_at, "source_type": ClientDocument.source_type,
            "source_id": ClientDocument.source_id,
        },
        search=(ClientDocument.title,),
    )  # fmt: skip
    return page | {"data": [document_view(session, d) for d in page["data"]]}


def get_document(session: Session, principal: Principal, doc_id: UUID) -> dict:
    return document_view(session, load_document(session, principal, doc_id, _READ))


def document_file(session: Session, doc: ClientDocument, variant: str) -> tuple[Any, bytes]:
    file_id = doc.paper_scan_file_id if variant == "paper_scan" else doc.rendered_file_id
    if file_id is None:
        raise NotFound("No file of this kind for the document.")
    return files.read(session, file_id)


def get_document_file(session: Session, principal: Principal, doc_id: UUID, variant: str):
    return document_file(session, load_document(session, principal, doc_id, _READ), variant)


# --- the PDF snapshot ------------------------------------------------------------------------------------------


def _render(session: Session, doc: ClientDocument) -> None:
    """PDF of exactly what was presented plus every decision so far; re-rendered after each decision."""
    version = session.get(DocumentTemplateVersion, doc.template_version_id) if doc.template_version_id else None
    signers = []
    for a in _acceptances(session, doc.id):
        png = files.read(session, a.signature_file_id)[1] if a.signature_file_id else None
        witness = None
        if a.witnessed_by_staff_user_id:
            staff = session.get(platform.models.StaffUser, a.witnessed_by_staff_user_id)
            witness = f"{staff.first_name} {staff.last_name}"
        signers.append(pdf.Signer(
            role=a.signer_role, decision=a.decision, name=a.signer_name, method=a.method,
            decided_at=a.decided_at.strftime("%Y-%m-%d %H:%M:%S UTC"), typed_signature=a.typed_signature,
            signature_png=png, ip=str(a.ip) if a.ip else None, user_agent=a.user_agent, witnessed_by=witness,
        ))  # fmt: skip
    snapshot = pdf.Snapshot(
        title=doc.title, organization=platform.service.get_tenant(session).name,
        client_name=clients.service.display_name(clients.service.get(session, doc.client_id)),
        body_html=doc.body_html, acceptance_text=doc.acceptance_text, blocks=doc.signature_blocks,
        document_id=str(doc.id), issued_at=doc.issued_at.strftime("%Y-%m-%d %H:%M UTC"), status=doc.status,
        content_sha256=doc.content_sha256, version_label=version and f"version {version.version_number}",
        version_sha256=version and version.body_sha256,
    )  # fmt: skip
    stored = files.store(
        session, pdf.render(snapshot, signers), purpose="documents.rendered", content_type=files.PDF,
        uploaded_by=("system", None), original_name=f"{doc.title}.pdf", generated=True,
    )  # fmt: skip
    doc.rendered_file_id = stored.id


# --- signing (DOC-03, DOC-04) ------------------------------------------------------------------------------------


def _signature_png(session: Session, raw: str, uploaded_by: tuple[str, UUID | None]) -> UUID:
    """A drawn signature arrives as base64 PNG (optionally a data: URL); it is decoded, re-encoded and stored."""
    try:
        data = base64.b64decode(raw.split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise ValidationFailed("The signature image is not valid.", pointer="/signers") from None
    cleaned, kind = files.clean(data, files.PNG, allowed=(files.PNG,), max_bytes=SIGNATURE_MAX_BYTES)
    return files.store(session, cleaned, purpose="documents.signature", content_type=kind, uploaded_by=uploaded_by).id


def _check_signer(session: Session, doc: ClientDocument, signer: dict, *, staff: bool) -> None:
    role, signer_client = signer["signer_role"], signer.get("signer_client_id")
    allowed = signing.required_roles(doc.signature_blocks, doc.requires_guardian) | {"client"}
    if role not in allowed:
        raise ValidationFailed(f"This document has no {role.replace('_', ' ')} signature.", pointer="/signers")
    if role == "client" and signer_client not in (None, doc.client_id):
        raise ValidationFailed("The client signature belongs to the document's client.", pointer="/signers")
    if role == "guardian":
        guardians = clients.households.guardian_ids(session, doc.client_id)
        # Staff may witness a guardian who is not on file (free text); a guardian on file must sign as themself.
        if (signer_client or guardians or not staff) and signer_client not in guardians:
            raise ValidationFailed(
                "The guardian must be a client with a guardianship link to this client.", pointer="/signers",
                code="guardian-required",
            )  # fmt: skip
    method = signer["method"]
    if method == "typed_name" and not (signer.get("typed_signature") or "").strip():
        raise ValidationFailed("Type the signer's name to sign.", pointer="/signers")
    if method == "drawn_signature" and not signer.get("signature_png"):
        raise ValidationFailed("Draw the signature to sign.", pointer="/signers")


def record_decisions(
    session: Session, doc: ClientDocument, content_sha256: str, signers: list[dict], *, meta: dict,
    uploaded_by: tuple[str, UUID | None], staff: bool, witnessed_by: UUID | None = None,
    delivery: DocumentDelivery | None = None,
) -> ClientDocument:  # fmt: skip
    """Validate and append one evidence row per signer, then apply the transition (state machine 7.6)."""
    if doc.status != "pending" or doc.deleted_at is not None:
        raise Conflict("Only a pending document can be signed or declined.")
    if content_sha256 != doc.content_sha256:
        raise Conflict("The document changed since it was shown; reload it.", code="content-mismatch")
    existing = {a.signer_role: a.decision for a in _acceptances(session, doc.id)}
    roles = [s["signer_role"] for s in signers]
    if len(set(roles)) != len(roles) or set(roles) & set(existing):
        raise Conflict("This signer has already decided.", code="already-exists")
    for signer in signers:
        _check_signer(session, doc, signer, staff=staff)
    now = clock.now()
    for signer in signers:
        file_id = _signature_png(session, signer["signature_png"], uploaded_by) if signer.get("signature_png") else None
        if signer["method"] == "drawn_signature" and file_id is None:  # pragma: no cover - _check_signer guards
            raise ValidationFailed("Draw the signature to sign.", pointer="/signers")
        session.add(DocumentAcceptance(
            client_document_id=doc.id, decision=signer["decision"], signer_role=signer["signer_role"],
            signer_client_id=signer.get("signer_client_id"), signer_name=signer["signer_name"].strip(),
            method="drawn_signature" if file_id else signer["method"], typed_signature=signer.get("typed_signature"),
            signature_file_id=file_id, delivery_id=delivery and delivery.id, witnessed_by_staff_user_id=witnessed_by,
            ip=meta.get("ip"), user_agent=(meta.get("user_agent") or "")[:500] or None, content_sha256=doc.content_sha256,
            decided_at=now,
        ))  # fmt: skip
        existing[signer["signer_role"]] = signer["decision"]
    session.flush()
    status = signing.outcome(signing.required_roles(doc.signature_blocks, doc.requires_guardian), existing)
    _transition(session, doc, status)
    return doc


def _transition(session: Session, doc: ClientDocument, status: str) -> None:
    """Apply a decided status (or stay pending), re-render, update the indicator, audit once, emit the event."""
    before = doc.status
    if status != "pending":
        doc.status, doc.decided_at = status, clock.now()
        doc.version += 1
        template = session.get(DocumentTemplate, doc.template_id) if doc.template_id else None
        if status == "accepted" and template and template.signature_validity_days:
            doc.expires_on = _today(session, doc.location_id) + timedelta(days=template.signature_validity_days)
        session.execute(
            update(DocumentDelivery)
            .where(DocumentDelivery.client_document_id == doc.id, DocumentDelivery.outcome == "pending")
            .values(outcome="superseded")
        )
    if doc.body_html:
        _render(session, doc)
    refresh_status(session, doc.client_id)
    audit.record(session, _COLLECT, doc, location_id=doc.location_id, changes={
        "status": [before, doc.status], "signatures": True,
    })  # fmt: skip
    event = {"accepted": DocumentAccepted, "declined": DocumentDeclined}.get(status)
    if event is not None:
        events.publish(session, event(client_document_id=doc.id, client_id=doc.client_id), doc.id)
    session.flush()


def submit_acceptances(session: Session, principal: Principal, doc_id: UUID, data: dict, meta: dict) -> dict:
    """In-person signing at the desk, witnessed by the signed-in staff user (DOC-03)."""
    doc = load_document(session, principal, doc_id, _COLLECT)
    record_decisions(
        session, doc, data["content_sha256"], data["signers"], meta=meta, staff=True,
        uploaded_by=("staff", principal.staff_user_id), witnessed_by=_actor_staff_id(principal),
    )  # fmt: skip
    return document_view(session, doc)


# --- emailed links (DOC-04) ------------------------------------------------------------------------------------


def _check_recipients(session: Session, doc: ClientDocument, recipients: list[str]) -> None:
    owners = [doc.client_id, *clients.households.guardian_ids(session, doc.client_id)]
    for address in recipients:
        if not any(clients.service.email_is_verified(session, owner, address) for owner in owners):
            raise ValidationFailed(
                "Links go only to confirmed addresses of the client or a guardian.", pointer="/recipient_emails",
                code="email-not-verified",
            )  # fmt: skip


def _send(session: Session, doc: ClientDocument, recipients: list[str], sent_by: UUID | None) -> DocumentDelivery:
    recipients = sorted({r.strip().lower() for r in recipients})
    _check_recipients(session, doc, recipients)
    session.execute(
        update(DocumentDelivery)
        .where(DocumentDelivery.client_document_id == doc.id, DocumentDelivery.outcome == "pending")
        .values(outcome="superseded")
    )
    raw, digest = tokens.mint(LINK_PREFIX, session.info["tenant_id"])
    now = clock.now()
    delivery = DocumentDelivery(
        client_document_id=doc.id, recipient_emails=recipients, token_hash=digest, sent_by_staff_user_id=sent_by,
        sent_at=now, expires_at=now + timedelta(hours=settings_row(session).email_link_ttl_hours),
    )  # fmt: skip
    session.add(delivery)
    session.flush()
    client = clients.service.get(session, doc.client_id)
    url = f"{get_settings().app.web_base_url}/sign#token={raw}"  # fragment: never sent to a server (17.2)
    for address in recipients:
        notifications.send(session, "documents.signing_link", address, {
            "organization": platform.service.get_tenant(session).name, "title": doc.title,
            "name": client.first_name, "url": url, "expires": delivery.expires_at.strftime("%Y-%m-%d %H:%M"),
        })  # fmt: skip
    events.publish(session, DocumentSent(client_document_id=doc.id, client_id=doc.client_id), doc.id)
    audit.record(session, _COLLECT, delivery, location_id=doc.location_id, changes={"recipients": len(recipients)})
    return delivery


def delivery_view(row: DocumentDelivery) -> dict:
    keys = ("id", "recipient_emails", "sent_at", "expires_at", "opened_at", "outcome")
    return {k: getattr(row, k) for k in keys}


def list_deliveries(session: Session, principal: Principal, doc_id: UUID, query: ListQuery) -> dict:
    load_document(session, principal, doc_id, _READ)
    page = paginate(
        session, select(DocumentDelivery).where(DocumentDelivery.client_document_id == doc_id), query,
        id_column=DocumentDelivery.id, sort_fields={"sent_at": DocumentDelivery.sent_at}, default_sort="-sent_at",
    )  # fmt: skip
    return page | {"data": [delivery_view(r) for r in page["data"]]}


def send_document(session: Session, principal: Principal, doc_id: UUID, recipients: list[str]) -> dict:
    doc = load_document(session, principal, doc_id, _COLLECT)
    if doc.status != "pending" or doc.deleted_at is not None or not doc.body_html:
        raise Conflict("Only a pending document can be sent for signing.")
    return delivery_view(_send(session, doc, recipients, _actor_staff_id(principal)))


def _delivery(session: Session, raw: str) -> tuple[DocumentDelivery, ClientDocument]:
    delivery = session.scalar(select(DocumentDelivery).where(DocumentDelivery.token_hash == tokens.digest(raw)))
    if delivery is None:
        raise NotFound("This link is not valid.", code="token-invalid")
    if delivery.outcome == "superseded":
        raise _gone("token-superseded", "A newer link was sent; use the latest email.")
    if delivery.outcome != "pending" or delivery.expires_at <= clock.now():
        raise _gone("token-expired", "This link has expired or was already used.")
    doc = _doc(session, delivery.client_document_id)
    if doc.status != "pending" or doc.deleted_at is not None:
        raise _gone("token-expired", "This document no longer needs a decision.")
    return delivery, doc


def _public_view(session: Session, doc: ClientDocument, delivery: DocumentDelivery) -> dict:
    return {
        "title": doc.title, "body_html": doc.body_html, "acceptance_text": doc.acceptance_text,
        "content_sha256": doc.content_sha256, "requires_guardian": doc.requires_guardian,
        "client_display_name": clients.service.display_name(clients.service.get(session, doc.client_id)),
        "expires_at": delivery.expires_at, "tenant_name": platform.service.get_tenant(session).name,
        "status": doc.status, "signature_blocks": doc.signature_blocks,
    }  # fmt: skip


def public_open(session: Session, raw: str) -> dict:
    """View through the emailed link: records the first opening, does not consume the token."""
    delivery, doc = _delivery(session, raw)
    if delivery.opened_at is None:
        delivery.opened_at = clock.now()
    return _public_view(session, doc, delivery)


def public_decide(session: Session, data: dict, meta: dict) -> dict:
    """Accept or decline through the link (method typed_name, or drawn when a signature is supplied). The token is
    single-use: any decision consumes it. A guardian signs as the guardian whose confirmed address got the link."""
    delivery, doc = _delivery(session, data["token"])
    # The role is derived: a link counts as the client's only when it went to the client's confirmed address.
    to_client = any(clients.service.email_is_verified(session, doc.client_id, a) for a in delivery.recipient_emails)
    role = "guardian" if doc.requires_guardian else data.get("signer_role") or ("client" if to_client else "guardian")
    if role == "client" and not to_client:
        raise ValidationFailed("This link was sent to a guardian; sign as the guardian.", pointer="/signer_role")
    signer = {
        "decision": data["decision"], "signer_role": role,
        "signer_name": data["signer_name"], "typed_signature": data["typed_signature"],
        "method": "drawn_signature" if data.get("signature_png") else "typed_name",
        "signature_png": data.get("signature_png"), "signer_client_id": None,
    }  # fmt: skip
    if signer["signer_role"] == "guardian":
        signer["signer_client_id"] = next(
            (g for g in clients.households.guardian_ids(session, doc.client_id)
             if any(clients.service.email_is_verified(session, g, a) for a in delivery.recipient_emails)),
            None,
        )  # fmt: skip
    record_decisions(
        session, doc, data["content_sha256"], [signer], meta=meta, staff=False, uploaded_by=("client", None),
        delivery=delivery,
    )  # fmt: skip
    delivery.outcome = data["decision"]
    return _public_view(session, doc, delivery)


# --- paper and uploads (DOC-05) --------------------------------------------------------------------------------


def upload_paper_scan(
    session: Session, principal: Principal, doc_id: UUID, data: bytes, content_type: str, filename: str | None
) -> dict:
    """Attach a scanned signed copy (PDF, JPEG or PNG) and mark the document paper-signed, witnessed by the
    uploader. Also how a document is uploaded to a client profile: issue it without a template, then upload.
    Replacing the scan of an accepted document needs the void key and never rewrites its hash (evidence)."""
    doc = load_document(session, principal, doc_id, _COLLECT)
    if doc.status not in ("pending", "accepted") or doc.deleted_at is not None:
        raise Conflict("Only a pending or accepted document takes a paper copy.")
    if doc.status == "accepted":
        load_document(session, principal, doc_id, _VOID)
    cleaned, kind = files.clean(
        data,
        content_type,
        allowed=(files.PDF, files.JPEG, files.PNG),
        max_bytes=get_settings().storage.max_upload_bytes,
    )
    stored = files.store(
        session, cleaned, purpose="documents.paper_scan", content_type=kind,
        uploaded_by=("staff", principal.staff_user_id), original_name=filename,
    )  # fmt: skip
    if doc.status == "accepted":
        old = doc.paper_scan_file_id
        doc.paper_scan_file_id = stored.id
        audit.record(session, _VOID, doc, location_id=doc.location_id,
                     changes={"paper_scan_file_id": [old and str(old), str(stored.id)]})  # fmt: skip
        session.flush()
        return document_view(session, doc)
    doc.paper_scan_file_id, doc.is_paper_signed = stored.id, True
    if not doc.body_html:  # nothing was presented on screen: the scan itself is the evidence
        doc.content_sha256 = stored.sha256
    role = "guardian" if doc.requires_guardian else "client"
    decided = {a.signer_role for a in _acceptances(session, doc.id)}
    if role not in decided:
        client = clients.service.get(session, doc.client_id)
        session.add(DocumentAcceptance(
            client_document_id=doc.id, decision="accepted", signer_role=role, signer_name=clients.service.display_name(client),
            method="paper", witnessed_by_staff_user_id=_actor_staff_id(principal), ip=None, user_agent=None,
            content_sha256=doc.content_sha256, decided_at=clock.now(),
        ))  # fmt: skip
        session.flush()
    _transition(session, doc, "accepted")
    session.flush()
    return document_view(session, doc)


def clear_paper_signed(session: Session, principal: Principal, doc_id: UUID) -> dict:
    """accepted -> pending when the paper flag is cleared (paper method only, state machine 7.6). The paper evidence
    row stays (append-only); a new paper copy marks it signed again. Undoing a decision needs the void key."""
    doc = load_document(session, principal, doc_id, _VOID)
    if doc.acceptance_method != "paper" or not doc.is_paper_signed or doc.status != "accepted":
        raise Conflict("Only a paper-signed document can be returned to pending.")
    doc.is_paper_signed, doc.status, doc.decided_at, doc.expires_on = False, "pending", None, None
    doc.version += 1
    refresh_status(session, doc.client_id)
    audit.record(session, _COLLECT, doc, location_id=doc.location_id, changes=audit.diff(doc))
    session.flush()
    return document_view(session, doc)


# --- void, delete, restore (DOC-06) ----------------------------------------------------------------------------


def void_document(session: Session, principal: Principal, doc_id: UUID) -> dict:
    doc = load_document(session, principal, doc_id, _VOID)
    if doc.status in ("voided", "expired"):
        raise Conflict("This document is already closed.")
    before, doc.status = doc.status, "voided"
    doc.version += 1
    _close_deliveries(session, doc)
    refresh_status(session, doc.client_id)
    audit.record(session, _VOID, doc, location_id=doc.location_id, changes={"status": [before, "voided"]})
    session.flush()
    return document_view(session, doc)


def _close_deliveries(session: Session, doc: ClientDocument) -> None:
    session.execute(
        update(DocumentDelivery)
        .where(DocumentDelivery.client_document_id == doc.id, DocumentDelivery.outcome == "pending")
        .values(outcome="superseded")
    )


def delete_document(session: Session, principal: Principal, doc_id: UUID) -> None:
    """Soft delete, recoverable for document_settings.deleted_recovery_days (amendment A1)."""
    doc = load_document(session, principal, doc_id, _VOID)
    if doc.deleted_at is not None or doc.status == "voided":
        raise NotFound()
    doc.deleted_at, doc.deleted_by_staff_user_id = clock.now(), _actor_staff_id(principal)
    doc.version += 1
    _close_deliveries(session, doc)
    refresh_status(session, doc.client_id)
    audit.record(session, _VOID, doc, location_id=doc.location_id, changes={"deleted": True})
    session.flush()


def restore_document(session: Session, principal: Principal, doc_id: UUID) -> dict:
    doc = load_document(session, principal, doc_id, _VOID)
    if doc.deleted_at is None:
        raise Conflict("The document is not deleted.")
    if doc.status == "voided" or doc.deleted_at < clock.now() - timedelta(
        days=settings_row(session).deleted_recovery_days
    ):
        raise Conflict("The recovery window has passed.", code="recovery-window-lapsed")
    doc.deleted_at, doc.deleted_by_staff_user_id = None, None
    doc.version += 1
    session.flush()  # the source-uniqueness index applies to live rows again: a duplicate fails here
    refresh_status(session, doc.client_id)
    audit.record(session, _VOID, doc, location_id=doc.location_id, changes={"deleted": False})
    session.flush()
    return document_view(session, doc)


# --- waiver and consent indicator (DOC-15, DOC-09) ---------------------------------------------------------------


def refresh_status(session: Session, client_id: UUID) -> None:
    """Recompute the stored projection for one client, in the caller's transaction (data-model 2.8)."""
    waivers = list(
        session.scalars(
            select(ClientDocument)
            .join(DocumentTemplate, DocumentTemplate.id == ClientDocument.template_id)
            .where(
                ClientDocument.client_id == client_id, ClientDocument.status == "accepted",
                ClientDocument.deleted_at.is_(None), DocumentTemplate.is_waiver,
            )
        )
    )  # fmt: skip
    consent = session.scalar(
        select(ClientDocument)
        .join(DocumentTemplate, DocumentTemplate.id == ClientDocument.template_id)
        .where(
            ClientDocument.client_id == client_id, ClientDocument.status == "accepted",
            ClientDocument.deleted_at.is_(None), DocumentTemplate.kind == "consent",
        )
        .order_by(ClientDocument.decided_at.desc())
        .limit(1)
    )  # fmt: skip
    row = session.scalar(select(ClientDocumentStatus).where(ClientDocumentStatus.client_id == client_id))
    if row is None:
        if not waivers and consent is None:
            return
        row = ClientDocumentStatus(client_id=client_id)
        session.add(row)
    row.has_waiver = bool(waivers)
    expiries = [d.expires_on for d in waivers]
    row.waiver_valid_until_on = None if not expiries or None in expiries else max(expiries)
    row.consent_document_id = consent and consent.id
    row.consent_accepted_at = consent and consent.decided_at
    session.flush()


def _effective(row: ClientDocumentStatus | None, today: date) -> bool:
    if row is None:
        return False
    if row.waiver_override is not None:
        return row.waiver_override == "on_file"
    return row.has_waiver and (row.waiver_valid_until_on is None or row.waiver_valid_until_on >= today)


def status_for(session: Session, client_ids: list[UUID]) -> dict[UUID, dict]:
    """Waiver and consent indicator per client, override and date test applied. Internal (check-in, rosters)."""
    rows = {r.client_id: r for r in session.scalars(
        select(ClientDocumentStatus).where(ClientDocumentStatus.client_id.in_(client_ids)))}  # fmt: skip
    required = set(session.scalars(
        select(DocumentLocationSettings.location_id).where(DocumentLocationSettings.is_consent_required)))  # fmt: skip
    today = _today(session)
    out = {}
    for client_id in client_ids:
        row = rows.get(client_id)
        home = clients.service.get(session, client_id).home_location_id if required else None
        out[client_id] = {
            "client_id": client_id, "is_waiver_on_file": _effective(row, today),
            "waiver_valid_until_on": row and row.waiver_valid_until_on, "waiver_override": row and row.waiver_override,
            "waiver_override_note": row and row.waiver_override_note,
            "consent_accepted_at": row and row.consent_accepted_at,
            "is_consent_missing": home in required and not (row and row.consent_accepted_at),
        }  # fmt: skip
    return out


def has_valid_waiver(session: Session, client_id: UUID) -> bool:
    return status_for(session, [client_id])[client_id]["is_waiver_on_file"]


def list_statuses(session: Session, principal: Principal, client_ids: list[UUID]) -> dict:
    authorize(principal, _READ)
    visible = []
    for cid in client_ids:  # ids outside the caller's reach are skipped, as memberships.list_standings does
        try:
            clients.service.load(session, principal, cid, _READ)
        except NotFound:
            continue
        visible.append(cid)
    statuses = status_for(session, visible)
    return {"data": list(statuses.values()), "page": {"next_cursor": None, "has_more": False}}


def set_waiver_override(session: Session, principal: Principal, client_id: UUID, data: dict) -> dict:
    clients.service.load(session, principal, client_id, _COLLECT)
    row = session.scalar(select(ClientDocumentStatus).where(ClientDocumentStatus.client_id == client_id))
    if row is None:
        row = ClientDocumentStatus(client_id=client_id)
        session.add(row)
    row.waiver_override, row.waiver_override_note = data["waiver_override"], data.get("note")
    row.waiver_override_by_staff_user_id, row.waiver_override_at = _actor_staff_id(principal), clock.now()
    session.flush()
    audit.record(session, _COLLECT, row, changes=audit.diff(row) or {"waiver_override": data["waiver_override"]})
    return status_for(session, [client_id])[client_id]


def clear_waiver_override(session: Session, principal: Principal, client_id: UUID) -> None:
    clients.service.load(session, principal, client_id, _COLLECT)
    row = session.scalar(select(ClientDocumentStatus).where(ClientDocumentStatus.client_id == client_id))
    if row is None or row.waiver_override is None:
        return
    row.waiver_override = row.waiver_override_note = row.waiver_override_by_staff_user_id = None
    row.waiver_override_at = None
    audit.record(session, _COLLECT, row, changes=audit.diff(row))
    session.flush()


# --- portal (SSP-20, DOC-03, DOC-08) ----------------------------------------------------------------------------


def _portal_client(session: Session, principal: Principal, client_id: UUID | None) -> UUID:
    """The client the identity acts for (default: its own record), checked with can_act_for(documents)."""
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    if client_id is None:
        own = clients.service.client_ids_for_identity(session, principal.identity_id)
        if not own:
            raise NotFound()
        client_id = own[0]
    if clients.households.can_act_for(session, principal.identity_id, client_id, "documents") is None:
        raise NotFound()
    return client_id


def portal_list(session: Session, principal: Principal, client_id: UUID | None, query: ListQuery) -> dict:
    subject = _portal_client(session, principal, client_id)
    filters = {k: v for k, v in query.filters.items() if k != "client_id"}
    stmt = select(ClientDocument).where(ClientDocument.client_id == subject, ClientDocument.deleted_at.is_(None))
    page = paginate(
        session, stmt, ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters),
        id_column=ClientDocument.id, sort_fields={"issued_at": ClientDocument.issued_at}, default_sort="-issued_at",
        filter_fields={"status": ClientDocument.status},
    )  # fmt: skip
    return page | {"data": [document_view(session, d) for d in page["data"]]}


def _portal_doc(session: Session, principal: Principal, doc_id: UUID, client_id: UUID | None) -> ClientDocument:
    doc = _doc(session, doc_id)
    subject = _portal_client(session, principal, client_id or doc.client_id)
    if doc.client_id != subject or doc.deleted_at is not None:
        raise NotFound()
    return doc


def portal_get(session: Session, principal: Principal, doc_id: UUID, client_id: UUID | None) -> dict:
    return document_view(session, _portal_doc(session, principal, doc_id, client_id))


def portal_file(session: Session, principal: Principal, doc_id: UUID, client_id: UUID | None):
    return document_file(session, _portal_doc(session, principal, doc_id, client_id), "rendered")


def portal_requirements(session: Session, principal: Principal, scope_type: str, scope_id: UUID | None,
                        client_id: UUID | None) -> dict:  # fmt: skip
    """Requirements before an online checkout; issues the pending document of each unmet blocking binding."""
    subject = _portal_client(session, principal, client_id)
    found = requirements_for(session, scope_type, scope_id, subject, online=True)
    for item in found:
        if not item["is_satisfied"] and item["is_blocking"] and item["pending_document_id"] is None:
            home = clients.service.get(session, subject).home_location_id
            if home is None:
                raise Conflict("Set a home location before signing documents online.", code="location-required")
            item["pending_document_id"] = ensure_pending(session, item["binding_id"], subject, home, origin="sale").id
    return {"requirements": found}


def portal_submit(session: Session, principal: Principal, doc_id: UUID, client_id: UUID | None, data: dict,
                  meta: dict) -> dict:  # fmt: skip
    """Accept or decline as the client or as guardian. Every signer is the identity's own client."""
    doc = _portal_doc(session, principal, doc_id, client_id)
    own = clients.service.client_ids_for_identity(session, principal.identity_id)
    if not own:
        raise NotFound()
    me = own[0]
    signers = []
    for signer in data["signers"]:
        if signer.get("signer_client_id") not in (None, me):
            raise ValidationFailed("You can only sign as yourself.", pointer="/signers")
        if me != doc.client_id and signer["signer_role"] != "guardian":
            raise ValidationFailed("You can only sign someone else's document as their guardian.", pointer="/signers")
        signers.append(
            signer | {"signer_client_id": me if signer["signer_role"] == "guardian" or me == doc.client_id else None}
        )
    record_decisions(
        session, doc, data["content_sha256"], signers, meta=meta, staff=False, uploaded_by=("client", principal.identity_id),
    )  # fmt: skip
    return document_view(session, doc)


def portal_consent(session: Session, principal: Principal) -> dict:
    """Whether the signed-in client's home location requires privacy consent they have not given (DOC-09); when it
    is missing, the pending consent document to accept is issued once and returned."""
    subject = _portal_client(session, principal, None)
    state = status_for(session, [subject])[subject]
    home = clients.service.get(session, subject).home_location_id
    required = bool(home and _location_settings(session, home).is_consent_required)
    pending = None
    if state["is_consent_missing"] and (template := _active_consent_template(session)) is not None:
        pending = session.scalar(
            select(ClientDocument.id).where(
                ClientDocument.client_id == subject, ClientDocument.template_id == template.id,
                ClientDocument.status == "pending", ClientDocument.deleted_at.is_(None),
            )
        )  # fmt: skip
        if pending is None:
            client = clients.service.get(session, subject)
            pending = issue(session, client=client, location_id=home, template=template, method="checkbox",
                            origin="consent").id  # fmt: skip
    return {"is_consent_required": required, "is_consent_missing": state["is_consent_missing"],
            "pending_document_id": pending}  # fmt: skip


def public_portal_terms(session: Session) -> dict:
    """The text bound as portal terms (DOC-14), for the sign-up page."""
    binding = _active_binding(session, "portal_terms", None)
    if binding is None:
        raise NotFound("No portal terms are set.")
    if binding.custom_text:
        return {"title": "Terms and conditions", "body_html": f"<p>{content.sanitize(binding.custom_text)}</p>"}
    template = session.get(DocumentTemplate, binding.template_id)
    version = session.get(DocumentTemplateVersion, template.current_version_id)
    return {"title": template.name, "body_html": version_view(version)["body_html"]}


# --- sweeps (expiry, recovery window, links) ---------------------------------------------------------------------


def run_sweeps(session: Session) -> dict:
    """Idempotent housekeeping, safe to run any time: accepted documents past expires_on become expired (in each
    location's zone), deleted documents past the recovery window become voided, stale links expire."""
    expired = 0
    for doc in session.scalars(
        select(ClientDocument).where(ClientDocument.status == "accepted", ClientDocument.expires_on.is_not(None))
    ):
        if doc.expires_on < _today(session, doc.location_id):
            doc.status = "expired"
            doc.version += 1
            refresh_status(session, doc.client_id)
            audit.record(session, "documents.document.expire", doc, location_id=doc.location_id,
                         changes={"status": ["accepted", "expired"]})  # fmt: skip
            events.publish(session, DocumentExpired(client_document_id=doc.id, client_id=doc.client_id), doc.id)
            expired += 1
    cutoff = clock.now() - timedelta(days=settings_row(session).deleted_recovery_days)
    purged = 0
    for doc in session.scalars(
        select(ClientDocument).where(ClientDocument.deleted_at < cutoff, ClientDocument.status != "voided")
    ):
        before, doc.status = doc.status, "voided"
        audit.record(session, "documents.document.purge", doc, location_id=doc.location_id,
                     changes={"status": [before, "voided"]})  # fmt: skip
        purged += 1
    links = session.execute(
        update(DocumentDelivery)
        .where(DocumentDelivery.outcome == "pending", DocumentDelivery.expires_at <= clock.now())
        .values(outcome="expired")
    ).rowcount
    session.flush()
    return {"expired": expired, "voided": purged, "links_expired": links}


@tenant_actor
def sweep_documents(session: Session) -> dict:
    """The queued form of run_sweeps, one message per tenant, enqueued hourly by app/scheduler.py. Between runs
    expiry is still exact, because every read applies the date test; only the stored status lags."""
    return run_sweeps(session)


# --- merge and data-subject handlers (CLI-13, security-baseline 4.3) --------------------------------------------


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    session.execute(update(ClientDocument).where(ClientDocument.client_id == loser_id).values(client_id=survivor_id))
    session.execute(text("SELECT app.repoint_document_acceptance(:a, :b)"), {"a": loser_id, "b": survivor_id})
    loser = session.scalar(select(ClientDocumentStatus).where(ClientDocumentStatus.client_id == loser_id))
    survivor = session.scalar(select(ClientDocumentStatus).where(ClientDocumentStatus.client_id == survivor_id))
    if loser is not None:
        if survivor is None:
            loser.client_id = survivor_id
        else:
            if survivor.waiver_override is None and loser.waiver_override is not None:
                survivor.waiver_override, survivor.waiver_override_note = (
                    loser.waiver_override,
                    loser.waiver_override_note,
                )
                survivor.waiver_override_by_staff_user_id = loser.waiver_override_by_staff_user_id
                survivor.waiver_override_at = loser.waiver_override_at
            session.delete(loser)
    session.flush()
    refresh_status(session, survivor_id)


def _export(session: Session, client_id: UUID) -> dict:
    docs = session.scalars(select(ClientDocument).where(ClientDocument.client_id == client_id))
    iso = lambda v: v and v.isoformat()  # noqa: E731 - the bundle is stored as JSON
    return {"documents": [
        {"title": d.title, "status": d.status, "issued_at": iso(d.issued_at), "decided_at": iso(d.decided_at),
         "expires_on": iso(d.expires_on), "content_sha256": d.content_sha256}
        for d in docs
    ]}  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    """Signed documents are retained under restriction as evidence (security-baseline 4.3, retention 7 years);
    unsigned ones are voided and their links closed; the indicator row goes."""
    retained = voided = 0
    for doc in session.scalars(select(ClientDocument).where(ClientDocument.client_id == client_id)):
        if doc.status == "pending":
            doc.status = "voided"
            _close_deliveries(session, doc)
            voided += 1
        else:
            retained += 1
    session.execute(ClientDocumentStatus.__table__.delete().where(ClientDocumentStatus.client_id == client_id))
    session.flush()
    return {"retained_signed_documents": retained, "voided_pending_documents": voided}


clients.merge.register_merge_handler(
    "documents", tables=("client_document", "document_acceptance", "client_document_status"), repoint=_repoint
)
platform.privacy.register_subject_handler(
    "documents",
    tables=("client_document", "document_acceptance", "client_document_status"),
    export=_export,
    erase=_erase,
)


def parse_client_ids(raw: str) -> list[UUID]:
    try:
        ids = [UUID(part) for part in raw.split(",") if part]
    except ValueError:
        raise ValidationFailed("client_id[in] takes comma-separated ids.", pointer="/client_id[in]") from None
    if not 1 <= len(ids) <= 200:
        raise ValidationFailed("Give between 1 and 200 client ids.", pointer="/client_id[in]")
    return ids


def as_utc(value: datetime) -> str:  # pragma: no cover - formatting helper for templates
    return value.strftime("%Y-%m-%d %H:%M UTC")
