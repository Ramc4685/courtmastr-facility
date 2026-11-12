"""Request and response models for the clients API (docs/api/openapi-people.yaml, tag clients).

Portal and public request bodies have their own schemas with only the fields the caller may set
(security-baseline 17.1); never reuse a staff schema there.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import EmailStr, Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Order = Annotated[int, Field(ge=0, le=10_000)]  # sort_order: bounded so it never overflows the INTEGER column
Phone = Annotated[str, StringConstraints(pattern=r"^\+[1-9][0-9]{6,14}$")]  # E.164
MemberNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Country = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
GenderValue = Literal["female", "male", "non_binary", "undisclosed"]
CustomValues = dict[str, Any]


class EmailIn(In):
    email: EmailStr
    label: Short | None = None
    is_primary: bool = False


class EmailOut(Out):
    id: UUID
    email: str
    label: str | None
    is_primary: bool
    verification_sent_at: datetime | None
    verified_at: datetime | None


class _Profile(In):
    """Fields staff may set on create and update. Sensitive fields need clients.client.read_sensitive to read."""

    preferred_name: Short | None = None
    gender: GenderValue | None = None
    birth_on: date | None = None
    organization_name: Short | None = None
    phone_mobile: Phone | None = None
    phone_home: Phone | None = None
    phone_work: Phone | None = None
    address_line1: Short | None = None
    address_line2: Short | None = None
    city: Short | None = None
    region: Short | None = None
    postal_code: Short | None = None
    country_code: Country | None = None
    client_category_id: UUID | None = None
    referral_category_id: UUID | None = None
    referral_source: Short | None = None
    custom_values: CustomValues | None = None
    discount_pct: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None = None
    comments: Text | None = None
    medical_notes: Text | None = None
    tag_ids: list[UUID] | None = None
    emails: Annotated[list[EmailIn], Field(max_length=10)] | None = None


class ClientCreate(_Profile):
    first_name: Name
    last_name: Name
    home_location_id: UUID
    primary_email: EmailStr | None = None  # shorthand for emails=[{email, is_primary: true}]
    member_number: MemberNumber | None = None


class ClientUpdate(_Profile):
    first_name: Name | None = None
    last_name: Name | None = None
    home_location_id: UUID | None = None
    version: int | None = None  # optimistic concurrency: a stale version is 409 version-conflict


class ClientListItem(Out):
    id: UUID
    first_name: str
    last_name: str
    preferred_name: str | None
    primary_email: str | None
    phone_mobile: str | None
    home_location_id: UUID
    client_category_id: UUID | None
    member_number: str | None
    status: Literal["active", "disabled"]
    merged_into_id: UUID | None
    erased_at: datetime | None
    created_at: datetime


class ClientOut(ClientListItem):
    """The profile. Sensitive fields are null and `is_sensitive_masked` is true without read_sensitive."""

    gender: str | None
    birth_on: date | None
    organization_name: str | None
    phone_home: str | None
    phone_work: str | None
    address_line1: str | None
    address_line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country_code: str | None
    referral_category_id: UUID | None
    referral_source: str | None
    default_trainer_staff_user_id: UUID | None
    default_salesperson_staff_user_id: UUID | None
    custom_values: CustomValues
    discount_pct: Decimal
    member_number_source: str | None
    comments: str | None
    medical_notes: str | None
    disabled_at: datetime | None
    merged_at: datetime | None
    created_via: str
    updated_at: datetime
    version: int
    emails: list[EmailOut] = []
    tag_ids: list[UUID] = []
    is_sensitive_masked: bool = False


class MemberNumberAssign(In):
    member_number: MemberNumber | None = None  # omit to generate from the tenant counter
    source: Literal["manual", "scanned"] = "manual"


class OwnersAssign(In):
    default_trainer_staff_user_id: UUID | None = None
    default_salesperson_staff_user_id: UUID | None = None


class EmergencyContactIn(In):
    name: Name
    relationship_label: Short | None = None
    phone: Phone | None = None
    phone_alt: Phone | None = None
    email: EmailStr | None = None
    notes: Text | None = None


class EmergencyContactOut(Out):
    id: UUID
    position: int
    name: str
    relationship_label: str | None
    phone: str | None
    phone_alt: str | None
    email: str | None
    notes: str | None


class EmergencyContacts(In):
    contacts: Annotated[list[EmergencyContactIn], Field(max_length=10)]


class EmergencyContactsOut(Out):
    contacts: list[EmergencyContactOut]


class TokenIn(In):
    token: Annotated[str, StringConstraints(min_length=10, max_length=300)]


# --- configuration -------------------------------------------------------------------------------------------


class LookupIn(In):
    name: Name
    sort_order: Order = 0
    is_active: bool = True


class LookupUpdate(In):
    name: Name | None = None
    sort_order: Order | None = None
    is_active: bool | None = None


class LookupOut(Out):
    id: UUID
    name: str
    sort_order: int
    is_active: bool
    client_count: int = 0


class TagIn(In):
    kind: Literal["sport", "season", "custom"] = "custom"
    label: Name
    is_active: bool = True


class TagUpdate(In):
    label: Name | None = None
    is_active: bool | None = None


class TagOut(Out):
    id: UUID
    kind: str
    label: str
    is_active: bool


class CustomFieldIn(In):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
    label: Name
    data_type: Literal["text", "number", "date", "boolean", "choice"] = "text"
    choices: list[Name] | None = None
    sort_order: Order = 0
    is_active: bool = True


class CustomFieldUpdate(In):
    label: Name | None = None
    choices: list[Name] | None = None
    sort_order: Order | None = None
    is_active: bool | None = None


class CustomFieldOut(Out):
    id: UUID
    key: str
    label: str
    data_type: str
    choices: list[str] | None
    sort_order: int
    is_active: bool


Context = Literal["staff", "registration", "portal"]
RequirementValue = Literal["hidden", "optional", "required"]


class FieldPolicyCell(Out):
    field_key: str
    capture_context: Context
    requirement: RequirementValue
    is_locked: bool


class FieldPolicyIn(In):
    field_key: Short
    capture_context: Context
    requirement: RequirementValue


class FieldPolicies(In):
    policies: Annotated[list[FieldPolicyIn], Field(max_length=500)]


class FieldPoliciesOut(Out):
    policies: list[FieldPolicyCell]


class ClientSettingsOut(Out):
    default_gender: str | None
    is_member_number_auto_generated: bool
    member_number_trigger: str
    member_number_prefix: str
    is_verification_email_enabled: bool
    is_own_clients_scope_enabled: bool


class ClientSettingsUpdate(In):
    default_gender: GenderValue | None = None
    is_member_number_auto_generated: bool | None = None
    member_number_trigger: Literal["client_created", "membership_sold"] | None = None
    member_number_prefix: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10)] | None = None
    is_verification_email_enabled: bool | None = None
    is_own_clients_scope_enabled: bool | None = None


class LocationSettingsOut(Out):
    location_id: UUID
    is_portal_photo_edit_enabled: bool


class LocationSettingsUpdate(In):
    is_portal_photo_edit_enabled: bool


# --- households ----------------------------------------------------------------------------------------------


class RelationshipTypeIn(In):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
    label: Name
    inverse_type_id: UUID | None = None  # null: symmetric
    grants_acting_rights: bool = False
    is_guardianship: bool = False
    is_portal_selectable: bool = True


class RelationshipTypeUpdate(In):
    label: Name | None = None
    grants_acting_rights: bool | None = None
    is_guardianship: bool | None = None
    is_portal_selectable: bool | None = None
    is_active: bool | None = None


class RelationshipTypeOut(Out):
    id: UUID
    code: str
    label: str
    inverse_type_id: UUID | None
    inverse_label: str
    grants_acting_rights: bool
    is_guardianship: bool
    is_portal_selectable: bool
    is_system: bool
    is_active: bool


class RelationshipCreate(In):
    """ "This client is <type> of the other client" (from = this client)."""

    other_client_id: UUID
    relationship_type_id: UUID


class RelationshipOut(Out):
    """One relationship seen from one client: `label` is read from that client's side."""

    id: UUID
    client_id: UUID
    other_client_id: UUID
    other_client_name: str
    relationship_type_id: UUID
    label: str
    direction: Literal["outgoing", "incoming"]
    status: str
    created_via: str
    acting_rights: Literal["this_for_other", "other_for_this", "both", "none"]
    confirmed_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class PortalAccessOut(Out):
    id: UUID
    identity_id: UUID
    email: str
    is_primary: bool
    status: str
    identity_status: str
    invited_at: datetime | None
    activated_at: datetime | None
    revoked_at: datetime | None


class PortalAccessList(Out):
    data: list[PortalAccessOut]


class PortalInvite(In):
    email: EmailStr | None = None  # one of the client's addresses; default: the primary
    attach_as_manager: bool = False  # when the address is already another person's login


# --- portal surface (own schemas, security-baseline 17.1) ----------------------------------------------------


class PortalClientUpdate(In):
    preferred_name: Short | None = None
    gender: GenderValue | None = None
    birth_on: date | None = None
    phone_mobile: Phone | None = None
    phone_home: Phone | None = None
    phone_work: Phone | None = None
    address_line1: Short | None = None
    address_line2: Short | None = None
    city: Short | None = None
    region: Short | None = None
    postal_code: Short | None = None
    country_code: Country | None = None
    custom_values: CustomValues | None = None


class PortalClientOut(Out):
    id: UUID
    first_name: str
    last_name: str
    preferred_name: str | None
    authority: Literal["self", "manager", "guardian", "delegate"]
    can_edit: bool
    member_number: str | None
    gender: str | None = None
    birth_on: date | None = None
    primary_email: str | None = None
    phone_mobile: str | None = None
    phone_home: str | None = None
    phone_work: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    custom_values: CustomValues = {}


class PortalClientList(Out):
    data: list[PortalClientOut]


class PortalRelationshipRequest(In):
    """Ask an existing account holder to confirm a link. The answer never says whether they exist."""

    relationship_type_id: UUID
    first_name: Name
    last_name: Name
    email: EmailStr


class PortalDependentCreate(In):
    relationship_type_id: UUID  # read from the caller's side: "I am <type> of the new person"
    first_name: Name
    last_name: Name
    birth_on: date | None = None
    gender: GenderValue | None = None
    email: EmailStr | None = None  # may repeat the parent's address (FAM-02)


class PortalRelationshipList(Out):
    data: list[RelationshipOut]


class RelationshipDecision(In):
    token: Annotated[str, StringConstraints(min_length=10, max_length=300)]
    decision: Literal["accept", "decline"]


class RelationshipDecisionOut(Out):
    status: str


class EmailVerificationOut(Out):
    email: str
    verified_at: datetime | None


# --- activity ------------------------------------------------------------------------------------------------


class NoteSubjectIn(In):
    label: Name
    is_active: bool = True


class NoteSubjectUpdate(In):
    label: Name | None = None
    is_active: bool | None = None


class NoteSubjectOut(Out):
    id: UUID
    label: str
    is_active: bool


class NoteIn(In):
    kind: Literal["call", "email", "task", "other"]
    note_subject_id: UUID | None = None
    subject_text: Short | None = None  # free subject; also creates no list entry
    body: Text | None = None
    occurred_at: datetime | None = None
    staff_user_id: UUID | None = None  # who performed it; default: the caller
    location_id: UUID | None = None


class NoteUpdate(In):
    kind: Literal["call", "email", "task", "other"] | None = None
    note_subject_id: UUID | None = None
    subject_text: Short | None = None
    body: Text | None = None
    occurred_at: datetime | None = None


class NoteOut(Out):
    id: UUID
    client_id: UUID
    kind: str
    note_subject_id: UUID | None
    subject_text: str | None
    body: str | None
    occurred_at: datetime
    staff_user_id: UUID
    location_id: UUID | None
    created_at: datetime


class TaskIn(In):
    client_id: UUID
    note_subject_id: UUID | None = None
    subject_text: Short | None = None
    body: Text | None = None
    assignee_staff_user_id: UUID | None = None  # default: the caller
    due_on: date | None = None
    has_email_reminder: bool = False


class TaskUpdate(In):
    note_subject_id: UUID | None = None
    subject_text: Short | None = None
    body: Text | None = None
    assignee_staff_user_id: UUID | None = None
    status: Literal["open", "in_progress", "done", "cancelled"] | None = None
    due_on: date | None = None
    has_email_reminder: bool | None = None


class TaskOut(Out):
    id: UUID
    client_id: UUID
    note_subject_id: UUID | None
    subject_text: str | None
    body: str | None
    assignee_staff_user_id: UUID
    status: str
    due_on: date | None
    completed_at: datetime | None
    completed_by_staff_user_id: UUID | None
    has_email_reminder: bool
    reminder_sent_at: datetime | None
    created_at: datetime


class OpenTaskCount(Out):
    open_count: int
    overdue_count: int


class AlertIn(In):
    kind: Literal["general", "medical", "injury", "conduct"] = "general"
    severity: Literal["info", "warning", "critical"] = "info"
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    shows_on_profile: bool = True
    shows_on_check_in: bool = True
    shows_on_booking: bool = False
    starts_on: date | None = None
    ends_on: date | None = None


class AlertUpdate(In):
    kind: Literal["general", "medical", "injury", "conduct"] | None = None
    severity: Literal["info", "warning", "critical"] | None = None
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None
    shows_on_profile: bool | None = None
    shows_on_check_in: bool | None = None
    shows_on_booking: bool | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool | None = None


class AlertOut(Out):
    id: UUID
    client_id: UUID
    kind: str
    severity: str
    message: str
    shows_on_profile: bool
    shows_on_check_in: bool
    shows_on_booking: bool
    starts_on: date | None
    ends_on: date | None
    is_active: bool
    created_by_staff_user_id: UUID
    created_at: datetime


class TimelineEntry(Out):
    occurred_at: datetime
    kind: Literal["note", "task", "alert", "audit"]
    id: UUID
    title: str
    detail: str | None = None
    staff_user_id: UUID | None = None


class Timeline(Out):
    data: list[TimelineEntry]
    next_before: datetime | None


# --- merge ---------------------------------------------------------------------------------------------------


class DuplicateCandidate(Out):
    client: ClientListItem
    reasons: list[str]


class DuplicateGroup(Out):
    client: ClientListItem
    candidates: list[DuplicateCandidate]


class MergeRequest(In):
    merged_client_ids: Annotated[list[UUID], Field(min_length=1, max_length=10)]


class MergeBlocker(Out):
    context: str
    code: str
    detail: str
    client_id: UUID


class MergeReviewItem(Out):
    client_id: UUID
    kind: Literal["portal_access", "relationship"]
    id: UUID
    detail: str


class MergePrecheck(Out):
    survivor_client_id: UUID
    merged_client_ids: list[UUID]
    blockers: list[MergeBlocker]
    review: list[MergeReviewItem]
    backfill_fields: list[str]
    can_merge: bool
