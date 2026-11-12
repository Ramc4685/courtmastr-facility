"""Request and response models of the programs context (docs/api/openapi-programs.yaml). Where the YAML and the data
model disagree, the data model wins (module README). Portal and public models never reuse a staff model."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import In, Out, Page  # noqa: F401

Reason = Annotated[str, StringConstraints(max_length=500)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]
Text = Annotated[str, StringConstraints(max_length=5000)]
Minor = Annotated[int, Field(ge=0, le=100_000_000)]
Ids = Annotated[list[UUID], Field(max_length=50)]
GroupKind = Literal["program", "camp", "clinic", "class_series", "competition", "team", "other"]
GroupWaitlist = Literal["disabled", "manual", "auto_promote"]
Disposition = Literal["reversed", "kept", "none"]


class _OneTarget(In):
    """Exactly one of session_id / program_group_id."""

    session_id: UUID | None = None
    program_group_id: UUID | None = None

    @model_validator(mode="after")
    def _one_target(self):
        if (self.session_id is None) == (self.program_group_id is None):
            raise ValueError("Give exactly one of session_id and program_group_id.")
        return self


# --- enrolments ---------------------------------------------------------------------------------------------


class EnrollmentCreate(_OneTarget):
    client_id: UUID
    client_package_id: UUID | None = None  # session target: the package that pays for the place
    program_fee_ids: Ids = []  # group target
    payer_client_id: UUID | None = None
    registrant_comment: Reason | None = None


class EnrollmentBatchCreate(In):
    client_id: UUID
    session_id: UUID
    booked_scope: Literal["all_linked", "custom"]
    session_ids: Annotated[list[UUID], Field(max_length=200)] = []
    client_package_id: UUID | None = None


class EnrollmentRebook(In):
    session_id: UUID
    client_package_id: UUID | None = None


class EnrollmentCancel(In):
    cancel_kind: Literal["early", "late", "staff_removed"] = "staff_removed"
    billing_disposition: Disposition | None = None
    reason: Reason | None = None
    add_to_waitlist: bool = False
    scope: Literal["single", "batch"] = "single"


class EnrollmentOut(Out):
    id: UUID
    location_id: UUID
    client_id: UUID
    target_kind: str
    session_id: UUID | None
    program_group_id: UUID | None
    status: Literal["pending", "enrolled", "cancelled"]
    pricing: str
    program_fee_id: UUID | None
    charge_id: UUID | None
    payer_client_id: UUID | None
    checkout_id: UUID | None
    batch_id: UUID | None
    booked_scope: str | None
    channel: str
    hold_expires_at: datetime | None
    enrolled_at: datetime | None
    cancelled_at: datetime | None
    cancel_kind: str | None
    billing_disposition: str | None


class Skipped(Out):
    session_id: UUID
    code: str | None


class EnrollmentBatchResult(Out):
    batch_id: UUID
    enrolled: list[EnrollmentOut]
    skipped: list[Skipped]


class Participant(Out):
    enrollment_id: UUID
    client_id: UUID
    client_name: str
    enrolled_at: datetime | None
    channel: str
    attendance: Literal["scheduled", "attended", "no_show", "excused"]


class Roster(Out):
    session_id: UUID
    capacity: int
    booked_count: int
    waiting_count: int
    participants: list[Participant]


class Mark(In):
    enrollment_id: UUID
    status: Literal["attended", "no_show", "excused"]


class AttendancePut(In):
    marks: Annotated[list[Mark], Field(min_length=1, max_length=500)]


class RosterMessage(In):
    subject: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    body_html: Annotated[str, StringConstraints(min_length=1, max_length=20000)]
    statuses: list[Literal["enrolled", "pending", "cancelled"]] = ["enrolled"]


class Accepted(Out):
    job_id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    resource_url: str | None


# --- waitlist -----------------------------------------------------------------------------------------------


class WaitlistCreate(_OneTarget):
    client_id: UUID
    mode: Literal["manual", "auto_promote"] = "auto_promote"  # session target; a group uses its own mode
    program_fee_id: UUID | None = None
    payer_client_id: UUID | None = None


class WaitlistOut(Out):
    id: UUID
    location_id: UUID
    client_id: UUID
    target_kind: str
    session_id: UUID | None
    program_group_id: UUID | None
    status: Literal["waiting", "offered", "promoted", "expired", "removed"]
    mode: str
    queued_at: datetime
    offer_expires_at: datetime | None
    position: int | None
    promoted_enrollment_id: UUID | None


# --- program groups -----------------------------------------------------------------------------------------


class _GroupFields(In):
    kind: GroupKind | None = None
    description: Text | None = None
    child_label: Annotated[str, StringConstraints(min_length=1, max_length=40)] | None = None
    revenue_category_id: UUID | None = None
    capacity: Annotated[int, Field(ge=0, le=100_000)] | None = None
    max_children: Annotated[int, Field(ge=0, le=10_000)] | None = None
    price_minor: Minor | None = None
    contact_name: Name | None = None
    contact_email: Annotated[str, StringConstraints(max_length=320)] | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    auto_archive_on: date | None = None
    waitlist_mode: GroupWaitlist | None = None


class ProgramGroupCreate(_GroupFields):
    name: Name
    parent_id: UUID | None = None
    location_id: UUID | None = None  # required for a root; a subgroup lives at its parent's location


class ProgramGroupUpdate(_GroupFields):
    name: Name | None = None


class ProgramGroupOut(Out):
    id: UUID
    location_id: UUID
    parent_id: UUID | None
    depth: int
    kind: str
    name: str
    description: str | None
    child_label: str
    revenue_category_id: UUID | None
    capacity: int | None
    max_children: int | None
    enrolled_count: int
    child_count: int
    price_minor: int | None
    contact_name: str | None
    contact_email: str | None
    starts_on: date | None
    ends_on: date | None
    status: str
    auto_archive_on: date | None
    completed_at: datetime | None
    waitlist_mode: str | None
    deleted_at: datetime | None
    spots_left: int | None
    waiting_count: int
    created_at: datetime
    updated_at: datetime


class ProgramGroupNode(ProgramGroupOut):
    children: list["ProgramGroupNode"]


class ProgramSessionsAdd(In):
    session_ids: Annotated[list[UUID], Field(min_length=1, max_length=200)]


class ProgramSessionOut(Out):
    id: UUID
    sequence_no: int
    starts_at: datetime
    ends_at: datetime
    title: str | None
    status: str
    capacity: int
    booked_count: int


class GroupParticipant(Out):
    enrollment_id: UUID
    client_id: UUID
    client_name: str
    program_group_id: UUID
    program_group_name: str
    enrolled_at: datetime | None
    channel: str
    payer_client_id: UUID | None
    charge_id: UUID | None
    invoice_id: UUID | None


class GroupRoster(Out):
    program_group_id: UUID
    capacity: int | None
    enrolled_count: int
    waiting_count: int
    participants: list[GroupParticipant]


# --- fees ---------------------------------------------------------------------------------------------------


class _FeeFields(In):
    fee_kind: Literal["individual", "join_subgroup", "new_subgroup"] | None = None
    deposit_minor: Minor | None = None
    revenue_category_id: UUID | None = None
    is_online: bool | None = None
    is_active: bool | None = None
    sort_order: Annotated[int, Field(ge=0, le=10_000)] | None = None


class ProgramFeeCreate(_FeeFields):
    description: Name
    amount_minor: Minor
    location_id: UUID | None = None  # catalogue fee only


class ProgramFeeUpdate(_FeeFields):
    description: Name | None = None
    amount_minor: Minor | None = None


class ProgramFeeOut(Out):
    id: UUID
    location_id: UUID
    program_group_id: UUID | None
    fee_kind: str
    description: str
    amount_minor: int
    deposit_minor: int | None
    revenue_category_id: UUID | None
    is_online: bool
    is_active: bool
    sort_order: int


# --- online registration config (REG-10) --------------------------------------------------------------------

PaymentRequirement = Literal[
    "pay_later_allowed", "immediate_card_payment", "card_required_charge_optional", "card_required_no_charge"
]


class RegistrationConfigPut(In):
    is_enabled: bool | None = None
    opens_on: date | None = None
    closes_on: date | None = None
    payment_requirement: PaymentRequirement | None = None
    displays_openings: bool | None = None
    online_description: Text | None = None
    closed_message: Text | None = None
    confirmation_message: Text | None = None
    public_slug: Annotated[str, StringConstraints(max_length=80)] | None = None
    portal_publish_name: Name | None = None


class RegistrationConfigOut(Out):
    program_group_id: UUID
    is_enabled: bool
    opens_on: date | None
    closes_on: date | None
    payment_requirement: str
    displays_openings: bool
    online_description: str | None
    closed_message: str | None
    confirmation_message: str | None
    public_slug: str | None
    is_portal_visible: bool
    portal_publish_name: str | None
    portal_published_at: datetime | None


# --- public listing (anonymous) -----------------------------------------------------------------------------


class PublicFee(Out):
    id: UUID
    fee_kind: str
    description: str
    amount_minor: int


class PublicProgramGroup(Out):
    id: UUID
    location_id: UUID
    name: str
    description: str | None
    starts_on: date | None
    ends_on: date | None
    spots_left: int | None
    registration_state: Literal["open", "not_yet_open", "closed", "full_waitlist", "full"]
    payment_requirement: str
    confirmation_message: str | None
    closed_message: str | None
    fees: list[PublicFee]
    children: list["PublicProgramGroup"]


# --- registration checkout (REG-12) -------------------------------------------------------------------------


class MissingDocument(Out):
    client_id: UUID
    program_group_id: UUID
    binding_id: UUID
    document_id: UUID | None


class CheckoutCreate(In):
    location_id: UUID
    payer_client_id: UUID | None = None
    comment: Reason | None = None


class CheckoutItemAdd(In):
    program_group_id: UUID
    client_id: UUID
    program_fee_id: UUID | None = None  # one fee per place in a basket
    comment: Reason | None = None


class CheckoutConfirm(In):
    method_token: Annotated[str, StringConstraints(max_length=200)] | None = None
    payment_method_id: UUID | None = None
    pay_later: bool = False


class CheckoutItem(Out):
    id: UUID
    client_id: UUID
    client_name: str
    program_group_id: UUID
    program_group_name: str
    program_fee_id: UUID | None
    amount_minor: int
    status: str
    hold_expires_at: datetime | None


class CheckoutOut(Out):
    id: UUID
    location_id: UUID
    channel: str
    payer_client_id: UUID | None
    status: str
    invoice_id: UUID | None
    total_minor: int
    expires_at: datetime
    completed_at: datetime | None
    missing_documents: list[MissingDocument]
    items: list[CheckoutItem]


class PortalCheckoutCreate(In):
    location_id: UUID
    comment: Reason | None = None


class PortalCheckoutItemAdd(In):
    program_group_id: UUID
    client_id: UUID
    program_fee_id: UUID | None = None  # one fee per place in a basket
    comment: Reason | None = None


class PortalCheckoutConfirm(In):
    method_token: Annotated[str, StringConstraints(max_length=200)] | None = None
    payment_method_id: UUID | None = None
    pay_later: bool = False
    coupon_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = (
        None  # SSP-11
    )


class PortalMissingDocument(Out):
    client_id: UUID
    program_group_id: UUID
    document_id: UUID | None


class PortalCheckoutItem(Out):
    id: UUID
    client_id: UUID
    client_name: str
    program_group_id: UUID
    program_group_name: str
    amount_minor: int
    status: str
    hold_expires_at: datetime | None


class PortalCheckoutOut(Out):
    id: UUID
    location_id: UUID
    status: str
    invoice_id: UUID | None
    total_minor: int
    expires_at: datetime
    completed_at: datetime | None
    missing_documents: list[PortalMissingDocument]
    items: list[PortalCheckoutItem]


# --- session booking policy and self-service (CLS-09) -------------------------------------------------------

ListingMode = Literal["bookable", "list_only", "unlisted", "hidden"]
PolicyWaitlist = Literal["disabled", "auto_promote", "open_offer"]
Days = Annotated[int, Field(ge=1, le=730)]
Minutes = Annotated[int, Field(ge=0, le=100_000)]


class BookingPolicyDefault(In):
    listing_mode: ListingMode
    requires_active_membership: bool
    visible_range_days: Days
    hides_full_sessions: bool
    booking_cutoff_minutes: Minutes
    allows_self_cancel: bool
    cancel_notice_minutes: Minutes
    waitlist_mode: PolicyWaitlist


class BookingPolicyOverride(In):
    """Per reservation type, at the type's location; a null field inherits the location default."""

    listing_mode: ListingMode | None = None
    requires_active_membership: bool | None = None
    visible_range_days: Days | None = None
    hides_full_sessions: bool | None = None
    booking_cutoff_minutes: Minutes | None = None
    allows_self_cancel: bool | None = None
    cancel_notice_minutes: Minutes | None = None
    waitlist_mode: PolicyWaitlist | None = None


class BookingPolicyOut(Out):
    id: UUID
    location_id: UUID
    reservation_type_id: UUID | None
    listing_mode: str | None
    requires_active_membership: bool | None
    visible_range_days: int | None
    hides_full_sessions: bool | None
    booking_cutoff_minutes: int | None
    allows_self_cancel: bool | None
    cancel_notice_minutes: int | None
    waitlist_mode: str | None


class PortalSessionListing(Out):
    session_id: UUID
    location_id: UUID
    time_zone: str  # the session's location IANA zone: show its wall time there (APP-16)
    title: str | None
    starts_at: datetime
    ends_at: datetime
    spots_left: int | None
    is_bookable: bool
    can_join_waitlist: bool
    reason: str | None


class PortalEnrollmentCreate(In):
    client_id: UUID
    session_id: UUID
    client_package_id: UUID | None = None


class PortalEnrollmentOut(Out):
    id: UUID
    client_id: UUID
    target_kind: str
    session_id: UUID | None
    program_group_id: UUID | None
    status: str
    enrolled_at: datetime | None
    cancelled_at: datetime | None
    cancel_kind: str | None


class PortalWaitlistJoin(In):
    client_id: UUID
    session_id: UUID | None = None
    program_group_id: UUID | None = None
    program_fee_id: UUID | None = None  # group target: the online fee to register under when promoted

    @model_validator(mode="after")
    def _one_target(self):
        if (self.session_id is None) == (self.program_group_id is None):
            raise ValueError("Give exactly one of session_id and program_group_id.")
        return self


class PortalWaitlistOut(Out):
    id: UUID
    client_id: UUID
    target_kind: str
    session_id: UUID | None
    program_group_id: UUID | None
    status: str
    queued_at: datetime
    offer_expires_at: datetime | None
    position: int | None = None


class PortalClaim(In):
    client_package_id: UUID | None = None
