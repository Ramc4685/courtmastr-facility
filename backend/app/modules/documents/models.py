"""documents tables (docs/architecture/data-model-people.md section 2, the schema of record).

Additions to the data model, recorded in the module README: `document_template_version.signature_blocks` and
`.sanitizer_version`; `client_document.body_html`, `.acceptance_text` and `.signature_blocks` (the presented
snapshot after merge fields, which the hash covers). Not created: `document_bulk_send` and
`document_delivery.bulk_send_id` (DOC-07 is not built), `client_document.external_provider/external_ref` (DOC-13
is a v2 adapter).
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, CheckConstraint, ForeignKeyConstraint, Index, SmallInteger, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JsonDict, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk

_FLAG = {"audit": "flag"}
_NIL = "'00000000-0000-0000-0000-000000000000'::uuid"


class TemplateKind(StrEnum):
    AGREEMENT = "agreement"
    CONSENT = "consent"


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ScopeType(StrEnum):
    MEMBERSHIP_PLAN = "membership_plan"
    PACKAGE_PLAN = "package_plan"
    PROGRAM_GROUP = "program_group"
    PROGRAM_DEFAULT = "program_default"
    RENTAL_PLAN = "rental_plan"
    PORTAL_TERMS = "portal_terms"


class Frequency(StrEnum):
    FIRST_PURCHASE = "first_purchase"
    EVERY_PURCHASE = "every_purchase"


class Origin(StrEnum):
    MANUAL = "manual"
    SALE = "sale"
    REGISTRATION = "registration"
    BULK_SEND = "bulk_send"
    CONSENT = "consent"
    EXTERNAL_PROVIDER = "external_provider"
    IMPORT = "import"


class AcceptanceMethod(StrEnum):
    PAPER = "paper"
    CHECKBOX = "checkbox"
    DRAWN_SIGNATURE = "drawn_signature"
    EMAIL_LINK = "email_link"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    VOIDED = "voided"


class Decision(StrEnum):
    ACCEPTED = "accepted"
    DECLINED = "declined"


class SignerRole(StrEnum):
    CLIENT = "client"
    GUARDIAN = "guardian"
    CO_SIGNER = "co_signer"


class SignMethod(StrEnum):
    PAPER = "paper"
    CHECKBOX = "checkbox"
    DRAWN_SIGNATURE = "drawn_signature"
    TYPED_NAME = "typed_name"


class DeliveryOutcome(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class WaiverOverride(StrEnum):
    ON_FILE = "on_file"
    NOT_ON_FILE = "not_on_file"


class DocumentTemplate(TenantOwned, Timestamps, Base):
    __tablename__ = "document_template"
    __table_args__ = tenant_args(
        enum_check("kind", TemplateKind),
        enum_check("status", TemplateStatus),
        CheckConstraint("signature_validity_days > 0", name="signature_validity_days"),
        CheckConstraint("minor_age_years BETWEEN 1 AND 25", name="minor_age_years"),
        # circular with document_template_version: checked at commit
        ForeignKeyConstraint(
            ["tenant_id", "current_version_id"],
            ["document_template_version.tenant_id", "document_template_version.id"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            name="fk_document_template_current_version",
        ),  # fmt: skip
        Index("ix_document_template_current_version_id", "tenant_id", "current_version_id"),
        Index(
            "uq_document_template_name",
            "tenant_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("status <> 'archived'"),
        ),  # fmt: skip
        Index(
            "uq_document_template_active_consent",
            "tenant_id",
            unique=True,
            postgresql_where=text("kind = 'consent' AND status = 'active'"),
        ),  # fmt: skip
    )

    name: Mapped[str] = mapped_column(info={"audit": "value"})
    kind: Mapped[str] = enum_column(server_default=text("'agreement'"))
    is_waiver: Mapped[bool] = mapped_column(server_default=text("false"))
    description: Mapped[str | None]
    signature_validity_days: Mapped[int | None]
    requires_guardian_for_minors: Mapped[bool] = mapped_column(server_default=text("true"))
    minor_age_years: Mapped[int] = mapped_column(SmallInteger, server_default=text("18"))
    current_version_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'draft'"))
    last_used_at: Mapped[datetime | None]


class DocumentTemplateVersion(TenantOwned, Timestamps, Base):
    """Immutable once published (service-enforced); one open draft per template."""

    __tablename__ = "document_template_version"
    __table_args__ = tenant_args(
        *tfk("template_id", "document_template", ondelete="CASCADE"),
        *tfk("published_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "template_id", "version_number"),
        CheckConstraint("char_length(acceptance_text) BETWEEN 1 AND 1000", name="acceptance_text"),
        CheckConstraint("jsonb_typeof(signature_blocks) = 'array'", name="signature_blocks"),
        Index(
            "uq_document_template_version_draft",
            "tenant_id",
            "template_id",
            unique=True,
            postgresql_where=text("published_at IS NULL"),
        ),  # fmt: skip
    )

    template_id: Mapped[UUID]
    version_number: Mapped[int]
    body_html: Mapped[str]
    acceptance_text: Mapped[str]
    body_sha256: Mapped[str] = mapped_column(info={"audit": "value"})
    signature_blocks: Mapped[list] = mapped_column(JsonDict, server_default=text("'[]'"))
    sanitizer_version: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    published_at: Mapped[datetime | None]
    published_by_staff_user_id: Mapped[UUID | None]
    change_note: Mapped[str | None]


class DocumentBinding(TenantOwned, Timestamps, Base):
    __tablename__ = "document_binding"
    __table_args__ = tenant_args(
        *tfk("template_id", "document_template"),
        enum_check("scope_type", ScopeType),
        enum_check("frequency", Frequency),
        CheckConstraint("(scope_type IN ('program_default', 'portal_terms')) = (scope_id IS NULL)", name="scope"),
        CheckConstraint("num_nonnulls(template_id, custom_text) = 1", name="content"),
        Index(
            "uq_document_binding_scope",
            "tenant_id",
            "scope_type",
            text(f"coalesce(scope_id, {_NIL})"),
            unique=True,
            postgresql_where=text("is_active"),
        ),  # fmt: skip
    )

    scope_type: Mapped[str] = enum_column()
    scope_id: Mapped[UUID | None]
    template_id: Mapped[UUID | None]
    custom_text: Mapped[str | None]
    frequency: Mapped[str] = enum_column(server_default=text("'every_purchase'"))
    is_enforced_online: Mapped[bool] = mapped_column(server_default=text("true"))
    is_enforced_at_desk: Mapped[bool] = mapped_column(server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ClientDocument(TenantOwned, Timestamps, Base):
    __tablename__ = "client_document"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("location_id", "location", index=False),
        *tfk("template_id", "document_template", index=False),
        *tfk("template_version_id", "document_template_version"),
        *tfk("binding_id", "document_binding"),
        *tfk("issued_by_staff_user_id", "staff_user"),
        *tfk("rendered_file_id", "stored_file"),
        *tfk("paper_scan_file_id", "stored_file"),
        *tfk("deleted_by_staff_user_id", "staff_user"),
        enum_check("origin", Origin),
        enum_check("acceptance_method", AcceptanceMethod),
        enum_check("status", DocumentStatus),
        CheckConstraint("num_nonnulls(source_context, source_type, source_id) IN (0, 3)", name="source"),
        CheckConstraint("(status IN ('accepted', 'declined')) <= (decided_at IS NOT NULL)", name="decided_at"),
        CheckConstraint("jsonb_typeof(signature_blocks) = 'array'", name="signature_blocks"),
        Index("ix_client_document_client", "tenant_id", "client_id", "id"),
        Index("ix_client_document_history", "tenant_id", "location_id", text("issued_at DESC")),
        Index(
            "ix_client_document_pending",
            "tenant_id",
            "issued_at",
            postgresql_where=text("status = 'pending' AND deleted_at IS NULL"),
        ),  # fmt: skip
        Index("ix_client_document_template_client", "tenant_id", "template_id", "client_id"),
        Index(
            "ix_client_document_expiry",
            "tenant_id",
            "expires_on",
            postgresql_where=text("status = 'accepted' AND expires_on IS NOT NULL"),
        ),  # fmt: skip
        Index("ix_client_document_deleted", "tenant_id", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
        Index(
            "uq_client_document_source",
            "tenant_id",
            "source_context",
            "source_type",
            "source_id",
            text(f"coalesce(template_id, {_NIL})"),
            unique=True,
            postgresql_where=text("source_id IS NOT NULL AND status <> 'voided' AND deleted_at IS NULL"),
        ),  # fmt: skip
    )

    client_id: Mapped[UUID]
    location_id: Mapped[UUID]
    template_id: Mapped[UUID | None]
    template_version_id: Mapped[UUID | None]
    title: Mapped[str] = mapped_column(info={"audit": "value"})
    description: Mapped[str | None]
    origin: Mapped[str] = enum_column(server_default=text("'manual'"))
    binding_id: Mapped[UUID | None]
    source_context: Mapped[str | None] = enum_column()
    source_type: Mapped[str | None] = enum_column()
    source_id: Mapped[UUID | None]
    acceptance_method: Mapped[str] = enum_column()
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    issued_by_staff_user_id: Mapped[UUID | None]
    issued_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    decided_at: Mapped[datetime | None]
    expires_on: Mapped[date | None]
    requires_guardian: Mapped[bool] = mapped_column(server_default=text("false"))
    body_html: Mapped[str]
    acceptance_text: Mapped[str]
    signature_blocks: Mapped[list] = mapped_column(JsonDict, server_default=text("'[]'"))
    rendered_file_id: Mapped[UUID | None]
    content_sha256: Mapped[str] = mapped_column(info={"audit": "value"})
    paper_scan_file_id: Mapped[UUID | None]
    is_paper_signed: Mapped[bool] = mapped_column(server_default=text("false"))
    deleted_at: Mapped[datetime | None]
    deleted_by_staff_user_id: Mapped[UUID | None]
    version: Mapped[int] = mapped_column(server_default=text("1"))


class DocumentAcceptance(TenantOwned, Base):
    """Append-only evidence: one row per signer per document (OV 3.4)."""

    __tablename__ = "document_acceptance"
    __table_args__ = tenant_args(
        *tfk("client_document_id", "client_document", index=False),
        *tfk("signer_client_id", "client"),
        *tfk("signature_file_id", "stored_file"),
        *tfk("delivery_id", "document_delivery"),
        *tfk("witnessed_by_staff_user_id", "staff_user"),
        enum_check("decision", Decision),
        enum_check("signer_role", SignerRole),
        enum_check("method", SignMethod),
        CheckConstraint("method <> 'drawn_signature' OR signature_file_id IS NOT NULL", name="drawn"),
        UniqueConstraint("tenant_id", "client_document_id", "signer_role"),
    )

    client_document_id: Mapped[UUID]
    decision: Mapped[str] = enum_column()
    signer_role: Mapped[str] = enum_column()
    signer_client_id: Mapped[UUID | None]
    signer_name: Mapped[str] = mapped_column(info=_FLAG)
    method: Mapped[str] = enum_column()
    typed_signature: Mapped[str | None] = mapped_column(info=_FLAG)
    signature_file_id: Mapped[UUID | None]
    delivery_id: Mapped[UUID | None]
    witnessed_by_staff_user_id: Mapped[UUID | None]
    ip: Mapped[Any | None] = mapped_column(INET, info=_FLAG)
    user_agent: Mapped[str | None]
    content_sha256: Mapped[str] = mapped_column(info={"audit": "value"})
    decided_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class DocumentDelivery(TenantOwned, Timestamps, Base):
    __tablename__ = "document_delivery"
    __table_args__ = tenant_args(
        *tfk("client_document_id", "client_document", ondelete="CASCADE"),
        *tfk("sent_by_staff_user_id", "staff_user"),
        enum_check("outcome", DeliveryOutcome),
        CheckConstraint("cardinality(recipient_emails) >= 1", name="recipient_emails"),
        Index("uq_document_delivery_token", "tenant_id", "token_hash", unique=True),
        Index("ix_document_delivery_expiry", "tenant_id", "expires_at", postgresql_where=text("outcome = 'pending'")),
    )

    client_document_id: Mapped[UUID]
    recipient_emails: Mapped[list[str]] = mapped_column(ARRAY(Text), info=_FLAG)  # lower-cased on write
    token_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    sent_by_staff_user_id: Mapped[UUID | None]
    sent_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    expires_at: Mapped[datetime]
    opened_at: Mapped[datetime | None]
    outcome: Mapped[str] = enum_column(server_default=text("'pending'"))


class ClientDocumentStatus(TenantOwned, Timestamps, Base):
    """Stored projection read in batches (data-model 2.8). Readers apply the date test."""

    __tablename__ = "client_document_status"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("waiver_override_by_staff_user_id", "staff_user"),
        *tfk("consent_document_id", "client_document"),
        enum_check("waiver_override", WaiverOverride),
        UniqueConstraint("tenant_id", "client_id", name="uq_client_document_status_client"),
    )

    client_id: Mapped[UUID]
    has_waiver: Mapped[bool] = mapped_column(server_default=text("false"))
    waiver_valid_until_on: Mapped[date | None]
    waiver_override: Mapped[str | None] = enum_column()
    waiver_override_by_staff_user_id: Mapped[UUID | None]
    waiver_override_at: Mapped[datetime | None]
    waiver_override_note: Mapped[str | None]
    consent_document_id: Mapped[UUID | None]
    consent_accepted_at: Mapped[datetime | None]


class DocumentSettings(TenantOwned, Timestamps, Base):
    __tablename__ = "document_settings"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", name="uq_document_settings_tenant"),
        CheckConstraint("email_link_ttl_hours BETWEEN 1 AND 720", name="email_link_ttl_hours"),
        CheckConstraint("deleted_recovery_days BETWEEN 1 AND 365", name="deleted_recovery_days"),
    )

    email_link_ttl_hours: Mapped[int] = mapped_column(server_default=text("48"), info={"audit": "value"})
    deleted_recovery_days: Mapped[int] = mapped_column(server_default=text("30"), info={"audit": "value"})
    is_staff_notified_on_decision: Mapped[bool] = mapped_column(server_default=text("true"))
    is_waiver_required_for_check_in: Mapped[bool] = mapped_column(server_default=text("false"))
    is_waiver_required_for_booking: Mapped[bool] = mapped_column(server_default=text("false"))


class DocumentLocationSettings(TenantOwned, Timestamps, Base):
    __tablename__ = "document_location_settings"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False), UniqueConstraint("tenant_id", "location_id")
    )

    location_id: Mapped[UUID]
    is_consent_required: Mapped[bool] = mapped_column(server_default=text("false"))


class TermsSaleKind(StrEnum):
    MEMBERSHIP = "membership"
    PACKAGE = "package"
    PROGRAM = "program"
    RENTAL = "rental"


class TermsAcceptance(TenantOwned, Timestamps, Base):
    """One recorded acknowledgment of the bound portal terms at one version, taken at the start of a portal sale
    (SSP-14). `terms_version_id` is the version the buyer was shown (see service.portal_terms_version);
    `subject_id` is what was being bought (plan, program group or rental), since the sale has no id yet."""

    __tablename__ = "terms_acceptance"
    __table_args__ = tenant_args(
        *tfk("client_id", "client"),
        *tfk("binding_id", "document_binding"),
        enum_check("sale_kind", TermsSaleKind),
    )

    client_id: Mapped[UUID]
    binding_id: Mapped[UUID]
    terms_version_id: Mapped[str] = mapped_column(info={"audit": "value"})
    sale_kind: Mapped[str] = enum_column()
    subject_id: Mapped[UUID]
    identity_id: Mapped[UUID | None]
    accepted_at: Mapped[datetime]
    ip: Mapped[Any | None] = mapped_column(INET, info=_FLAG)
