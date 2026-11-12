"""Request and response models for the documents API (docs/api/openapi-people.yaml, tag documents).

Portal and public bodies have their own schemas with only the fields the caller may set (security-baseline 17.1).
Drawn signatures travel inline as base64 PNG (`signature_png`, at most about 300 KB) instead of a separate upload.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import EmailStr, Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Text = Annotated[str, StringConstraints(max_length=4000)]
Body = Annotated[str, StringConstraints(max_length=200_000)]
Png = Annotated[str, StringConstraints(max_length=420_000)]  # base64 of a <=300 KB image
Role = Literal["client", "guardian", "co_signer"]
Decision = Literal["accepted", "declined"]
ScopeType = Literal[
    "membership_plan", "package_plan", "program_group", "program_default", "rental_plan", "portal_terms"
]


class SignatureBlock(In):
    role: Role
    label: Short | None = None


# --- templates -------------------------------------------------------------------------------------------------


class DocumentTemplateCreate(In):
    name: Name
    kind: Literal["agreement", "consent"] = "agreement"
    is_waiver: bool = False
    description: Text | None = None
    signature_validity_days: int | None = Field(None, ge=1, le=3650)
    requires_guardian_for_minors: bool = True
    minor_age_years: int = Field(18, ge=1, le=25)


class DocumentTemplateUpdate(In):
    name: Name | None = None
    is_waiver: bool | None = None
    description: Text | None = None
    signature_validity_days: int | None = Field(None, ge=1, le=3650)
    requires_guardian_for_minors: bool | None = None
    minor_age_years: int | None = Field(None, ge=1, le=25)


class DocumentTemplateDraft(In):
    body_html: Body
    acceptance_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    change_note: Short | None = None
    signature_blocks: list[SignatureBlock] | None = Field(None, max_length=3)


class DocumentTemplateVersionOut(Out):
    id: UUID
    version_number: int
    body_html: str
    acceptance_text: str
    body_sha256: str
    signature_blocks: list[dict]
    published_at: datetime | None
    change_note: str | None


class DocumentTemplateOut(Out):
    id: UUID
    name: str
    kind: str
    is_waiver: bool
    description: str | None
    signature_validity_days: int | None
    requires_guardian_for_minors: bool
    minor_age_years: int
    status: str
    current_version: DocumentTemplateVersionOut | None
    has_draft: bool
    last_used_at: datetime | None
    created_at: datetime


# --- bindings --------------------------------------------------------------------------------------------------


class DocumentBindingUpsert(In):
    """One active binding per scope. Exactly one of template_id and custom_text (plain text, DOC-14)."""

    scope_type: ScopeType
    scope_id: UUID | None = None
    template_id: UUID | None = None
    custom_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)] | None = None
    frequency: Literal["first_purchase", "every_purchase"] = "first_purchase"
    is_enforced_online: bool = True
    is_enforced_at_desk: bool = True


class DocumentBindingOut(Out):
    id: UUID
    scope_type: str
    scope_id: UUID | None
    template_id: UUID | None
    custom_text: str | None
    frequency: str
    is_enforced_online: bool
    is_enforced_at_desk: bool
    is_active: bool


class DocumentRequirementOut(Out):
    binding_id: UUID
    template_id: UUID | None
    title: str
    is_satisfied: bool
    satisfied_by_document_id: UUID | None
    pending_document_id: UUID | None
    requires_guardian: bool
    is_blocking: bool


class DocumentRequirementList(Out):
    requirements: list[DocumentRequirementOut]


# --- client documents ------------------------------------------------------------------------------------------


class ClientDocumentCreate(In):
    """Issue a template, or (no template_id, a title, acceptance_method paper) open a record for an uploaded
    document and then PUT its file to /paper-scan."""

    client_id: UUID
    location_id: UUID
    template_id: UUID | None = None
    title: Name | None = None
    acceptance_method: Literal["paper", "checkbox", "drawn_signature", "email_link"]
    recipient_emails: list[EmailStr] | None = Field(None, max_length=5)


class DocumentAcceptanceOut(Out):
    id: UUID
    decision: str
    signer_role: str
    signer_client_id: UUID | None
    signer_name: str
    method: str
    typed_signature: str | None
    signature_file_id: UUID | None
    decided_at: datetime
    witnessed_by_staff_user_id: UUID | None


class PortalDocumentAcceptanceOut(Out):
    """No witness, signer client id or signature file (P-11)."""

    id: UUID
    decision: str
    signer_role: str
    signer_name: str
    method: str
    decided_at: datetime


class PortalClientDocumentOut(Out):
    """The portal view: no source, binding, deletion or stored-file references (P-11)."""

    id: UUID
    version: int
    client_id: UUID
    client_name: str
    location_id: UUID
    title: str
    description: str | None
    acceptance_method: str
    status: str
    requires_guardian: bool
    required_roles: list[str]
    issued_at: datetime
    decided_at: datetime | None
    expires_on: date | None
    is_paper_signed: bool
    body_html: str
    acceptance_text: str
    signature_blocks: list[dict]
    content_sha256: str
    acceptances: list[PortalDocumentAcceptanceOut]


class ClientDocumentOut(Out):
    id: UUID
    version: int
    client_id: UUID
    client_name: str
    location_id: UUID
    template_id: UUID | None
    template_version_id: UUID | None
    title: str
    description: str | None
    origin: str
    binding_id: UUID | None
    acceptance_method: str
    status: str
    requires_guardian: bool
    required_roles: list[str]
    issued_at: datetime
    decided_at: datetime | None
    expires_on: date | None
    is_paper_signed: bool
    body_html: str
    acceptance_text: str
    signature_blocks: list[dict]
    content_sha256: str
    rendered_file_id: UUID | None
    paper_scan_file_id: UUID | None
    source_type: str | None
    source_id: UUID | None
    deleted_at: datetime | None
    acceptances: list[DocumentAcceptanceOut]


class StaffSigner(In):
    decision: Decision
    signer_role: Role
    signer_client_id: UUID | None = None
    signer_name: Name
    method: Literal["paper", "checkbox", "drawn_signature", "typed_name"]
    typed_signature: Short | None = None
    signature_png: Png | None = None


class AcceptanceSubmit(In):
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    signers: list[StaffSigner] = Field(min_length=1, max_length=3)


class PortalSigner(In):
    decision: Decision
    signer_role: Literal["client", "guardian"]
    signer_client_id: UUID | None = None
    signer_name: Name
    method: Literal["checkbox", "drawn_signature", "typed_name"]
    typed_signature: Short | None = None
    signature_png: Png | None = None


class PortalAcceptanceSubmit(In):
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    signers: list[PortalSigner] = Field(min_length=1, max_length=2)


class DocumentDeliveryCreate(In):
    recipient_emails: list[EmailStr] = Field(min_length=1, max_length=5)


class DocumentDeliveryOut(Out):
    id: UUID
    recipient_emails: list[str]
    sent_at: datetime
    expires_at: datetime
    opened_at: datetime | None
    outcome: str


# --- public link -----------------------------------------------------------------------------------------------


class DocumentTokenIn(In):
    token: Annotated[str, StringConstraints(min_length=10, max_length=200)]


class PublicDocumentDecision(In):
    token: Annotated[str, StringConstraints(min_length=10, max_length=200)]
    decision: Decision
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    signer_name: Name
    signer_role: Literal["client", "guardian"] | None = None
    typed_signature: Name
    signature_png: Png | None = None


class PublicDocumentView(Out):
    title: str
    body_html: str
    acceptance_text: str
    content_sha256: str
    client_display_name: str
    requires_guardian: bool
    expires_at: datetime
    tenant_name: str
    status: str
    signature_blocks: list[dict]


class PortalTermsOut(Out):
    title: str
    body_html: str
    terms_version_id: str  # send back on every portal sale (SSP-14)


# --- indicator and settings ------------------------------------------------------------------------------------


class ClientDocumentStatusOut(Out):
    client_id: UUID
    is_waiver_on_file: bool
    waiver_valid_until_on: date | None
    waiver_override: str | None
    waiver_override_note: str | None
    consent_accepted_at: datetime | None
    is_consent_missing: bool


class WaiverOverrideIn(In):
    waiver_override: Literal["on_file", "not_on_file"]
    note: Short | None = None


class DocumentSettingsOut(Out):
    email_link_ttl_hours: int
    deleted_recovery_days: int
    is_staff_notified_on_decision: bool
    is_waiver_required_for_check_in: bool
    is_waiver_required_for_booking: bool


class DocumentSettingsUpdate(In):
    email_link_ttl_hours: int | None = Field(None, ge=1, le=720)
    deleted_recovery_days: int | None = Field(None, ge=1, le=365)
    is_staff_notified_on_decision: bool | None = None
    is_waiver_required_for_check_in: bool | None = None
    is_waiver_required_for_booking: bool | None = None


class DocumentLocationSettingsOut(Out):
    location_id: UUID
    is_consent_required: bool


class DocumentLocationSettingsUpdate(In):
    is_consent_required: bool


class PortalConsentStateOut(Out):
    is_consent_required: bool
    is_consent_missing: bool
    pending_document_id: UUID | None
