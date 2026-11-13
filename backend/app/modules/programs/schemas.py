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
    season_classifier_id: UUID | None = None
    sport_classifier_id: UUID | None = None
    age_division_classifier_id: UUID | None = None


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
    season_classifier_id: UUID | None
    sport_classifier_id: UUID | None
    age_division_classifier_id: UUID | None
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
    allows_guest_checkout: bool | None = None  # REG-12: off by default
    # REG-10 (decision Q5): deposit now (each fee's deposit_minor), balance on a date or in equal instalments
    payment_plan: Literal["pay_in_full", "deposit", "instalments"] | None = None
    balance_due_on: date | None = None
    instalment_count: Annotated[int, Field(ge=2, le=24)] | None = None
    instalment_unit: Literal["week", "half_month", "month"] | None = None


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
    allows_guest_checkout: bool
    payment_plan: str
    balance_due_on: date | None
    instalment_count: int | None
    instalment_unit: str | None


# --- public listing (anonymous) -----------------------------------------------------------------------------


class PublicFee(Out):
    id: UUID
    fee_kind: str
    description: str
    amount_minor: int
    deposit_minor: int | None = None  # REG-10: paid at checkout when the group has a payment plan


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
    allows_guest_checkout: bool  # REG-12: a guest may check out without an account
    payment_plan: str = "pay_in_full"
    balance_due_on: date | None = None
    instalment_count: int | None = None
    instalment_unit: str | None = None
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
    terms_version_id: Annotated[str, StringConstraints(max_length=64)] | None = None  # the portal terms shown (SSP-14)
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
    due_now_minor: int = 0  # REG-10: what checkout charges (before tax) when a group has a payment plan
    instalments: list["PortalInstalment"] = []


class PortalInstalment(Out):
    due_on: date
    amount_minor: int


# --- guest checkout (REG-12, phase-11 Q6): anonymous, its own schemas ------------------------------------------

GuestName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
GuestToken = Annotated[str, StringConstraints(min_length=10, max_length=200)]


class GuestPayer(In):
    first_name: GuestName
    last_name: GuestName
    email: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    ]
    phone_mobile: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    birth_on: date  # registration always requires it (clients LOCKED fields)


class GuestParticipant(In):
    first_name: GuestName
    last_name: GuestName
    birth_on: date  # registration always requires it; the email is the payer's


class GuestItem(In):
    program_group_id: UUID
    program_fee_id: UUID | None = None
    participant: Annotated[int, Field(ge=0, le=3)] | None = None  # index into participants; null: the payer


class GuestCheckoutCreate(In):
    location_id: UUID
    payer: GuestPayer
    participants: Annotated[list[GuestParticipant], Field(max_length=4)] = []
    items: Annotated[list[GuestItem], Field(min_length=1, max_length=4)]  # with the per-IP hold cap (checkout)


class GuestCheckoutConfirm(In):
    """A guest pays in full by a new card: no stored methods, no account credit, no instalments."""

    guest_token: GuestToken
    method_token: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    coupon_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | None = None
    terms_version_id: Annotated[str, StringConstraints(max_length=64)] | None = None  # the portal terms shown (SSP-14)


class GuestCheckoutToken(In):
    guest_token: GuestToken


class GuestCheckoutItem(Out):
    id: UUID
    client_name: str
    program_group_id: UUID
    program_group_name: str
    amount_minor: int
    status: str


class GuestCheckoutOut(Out):
    id: UUID
    location_id: UUID
    status: str
    total_minor: int
    expires_at: datetime
    completed_at: datetime | None
    items: list[GuestCheckoutItem]
    guest_token: str | None = None  # only on create: keep it in memory to confirm or abandon
    provider: str | None = None  # only on create: the processor the card is tokenised for, None when none
    publishable_key: str | None = None
    account_ref: str | None = None


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
    reservation_type_id: UUID | None = None  # SSP-08: which online package plans cover it


class PortalEnrollmentCreate(In):
    client_id: UUID
    session_id: UUID
    client_package_id: UUID | None = None
    direct_link_token: Annotated[str, Field(max_length=200)] | None = None  # SCH-16: books an unlisted session


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
    starts_at: datetime | None = Field(None, description="The session's start; none for a program registration")
    ends_at: datetime | None = None


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
    location_id: UUID
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


# --- group tools (Phase 14 chip A: REG-03, REG-04, REG-06, REG-08, REG-11, REG-13) ------------------------------

ClassifierKindName = Literal["season", "sport", "age_division"]
Short = Annotated[str, StringConstraints(min_length=1, max_length=120, strip_whitespace=True)]
PaymentRequirementName = Literal[
    "pay_later_allowed", "immediate_card_payment", "card_required_charge_optional", "card_required_no_charge"
]


class ProgramClassifierCreate(In):
    kind: ClassifierKindName
    title: Short
    sort_order: Annotated[int, Field(ge=0, le=10_000)] = 0


class ProgramClassifierUpdate(In):
    title: Short | None = None
    sort_order: Annotated[int, Field(ge=0, le=10_000)] | None = None
    is_active: bool | None = None


class ProgramClassifierOut(Out):
    id: UUID
    kind: str
    title: str
    sort_order: int
    is_active: bool
    group_count: int


FilterValue = Annotated[str, StringConstraints(max_length=500)]


class ProgramSavedViewCreate(In):
    name: Short
    filters: Annotated[dict[Annotated[str, StringConstraints(max_length=60)], FilterValue], Field(max_length=20)] = {}
    sort: Annotated[str, StringConstraints(max_length=120)] | None = None


class ProgramSavedViewUpdate(In):
    name: Short | None = None
    filters: (
        Annotated[dict[Annotated[str, StringConstraints(max_length=60)], FilterValue], Field(max_length=20)] | None
    ) = None
    sort: Annotated[str, StringConstraints(max_length=120)] | None = None


class ProgramSavedViewOut(Out):
    id: UUID
    name: str
    filters: dict[str, str]
    sort: str | None
    created_at: datetime


ColumnKey = Annotated[str, StringConstraints(min_length=1, max_length=40)]


class ProgramPageSettingPut(In):
    title: Annotated[str, StringConstraints(max_length=80)] | None = None
    columns: Annotated[list[ColumnKey], Field(max_length=30)] = []
    page_size: Annotated[int, Field(ge=10, le=200)] = 50
    default_view_id: UUID | None = None


class ProgramPageSettingOut(Out):
    page_key: str
    title: str | None
    columns: list[str]
    available_columns: list[str]
    page_size: int
    default_view_id: UUID | None


class EnrollmentMove(In):
    enrollment_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    to_program_group_id: UUID


class EnrollmentMoveOutcome(Out):
    enrollment_id: UUID
    moved: bool
    code: str | None


class EnrollmentMoveResult(Out):
    to_program_group_id: UUID
    outcomes: list[EnrollmentMoveOutcome]


class RegistrationDefaultsPut(In):
    payment_requirement: PaymentRequirementName = "immediate_card_payment"
    displays_openings: bool = False
    waitlist_mode: GroupWaitlist = "manual"
    online_description: Text | None = None
    confirmation_message: Text | None = None
    closed_message: Text | None = None


class RegistrationDefaultsOut(Out):
    location_id: UUID
    payment_requirement: str
    displays_openings: bool
    waitlist_mode: str
    online_description: str | None
    confirmation_message: str | None
    closed_message: str | None


class ProgramGroupCopy(In):
    name: Name
    starts_on: date | None = None
    ends_on: date | None = None
    include_children: bool = True
    include_fees: bool = True
    include_registration: bool = True


class ProgramGroupGenerate(In):
    """A series of programs from this one as the template: one copy per interval whose start falls in the range,
    each keeping the template's length (REG-13)."""

    first_starts_on: date
    last_starts_on: date
    interval_weeks: Annotated[int, Field(ge=1, le=52)] = 1
    include_children: bool = True
    include_fees: bool = True
    include_registration: bool = True


class ProgramGroupGenerated(Out):
    created: list[ProgramGroupOut]


# --- event forms (REG-15 to REG-24) -----------------------------------------------------------------------------

ItemKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
QuestionType = Literal["text_box", "drop_down", "radio", "checkbox", "purchase_quantity"]
HexColour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Email = Annotated[str, StringConstraints(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class FormChoice(In):
    key: ItemKey
    text: Short
    price_minor: Minor = 0


class FormDependsOn(In):
    question_key: ItemKey
    choice_key: ItemKey


class FormQuestion(In):
    """A typed question (REG-16): its attributes are required, hint, staff-only visibility, an expiry date, a
    length limit, priced choices and a dependency on an earlier question's choice."""

    type: Literal["question"] = "question"
    key: ItemKey
    question_type: QuestionType
    text: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    hint: Annotated[str, StringConstraints(max_length=500)] | None = None
    required: bool = False
    visibility: Literal["shown", "staff_only"] = "shown"
    expires_on: date | None = None
    max_length: Annotated[int, Field(ge=1, le=5000)] | None = None
    choices: Annotated[list[FormChoice], Field(max_length=100)] = []
    unit_price_minor: Minor | None = None
    max_quantity: Annotated[int, Field(ge=1, le=1000)] | None = None
    depends_on: FormDependsOn | None = None


class FormTopic(In):
    """An information topic (REG-18): a heading and plain text shown between questions."""

    type: Literal["topic"] = "topic"
    key: ItemKey
    title: Short
    body: Annotated[str, StringConstraints(max_length=10_000)] = ""


FormItem = Annotated[FormQuestion | FormTopic, Field(discriminator="type")]


class FormSchemaDoc(In):
    items: Annotated[list[FormItem], Field(max_length=200)] = []


class FormTheme(In):
    accent_color: HexColour | None = None
    header_alignment: Literal["left", "center", "right"] = "left"


class _FormFields(In):
    event_name: Short | None = None
    event_text: Annotated[str, StringConstraints(max_length=500)] | None = None
    event_starts_on: date | None = None
    event_ends_on: date | None = None
    opens_local: datetime | None = None  # wall time at the form's location; stored in UTC
    closes_local: datetime | None = None
    closed_message: Text | None = None
    confirmation_message: Text | None = None
    is_template: bool | None = None
    revenue_category_id: UUID | None = None
    allows_coupons: bool | None = None
    has_waitlist: bool | None = None
    capacity: Annotated[int, Field(ge=1, le=1_000_000)] | None = None
    theme: FormTheme | None = None


class EventFormCreate(_FormFields):
    """Blank, or a copy of another form or template (`copy_from_form_id`): settings, the latest questions and the
    inventory caps, never registrations or the header image."""

    name: Name
    location_id: UUID | None = None
    copy_from_form_id: UUID | None = None


class EventFormUpdate(_FormFields):
    name: Name | None = None


class EventFormVersionOut(Out):
    id: UUID
    version_no: int
    state: str
    schema_doc: FormSchemaDoc
    published_at: datetime | None


class EventFormOut(Out):
    id: UUID
    location_id: UUID
    time_zone: str
    name: str
    event_name: str | None
    event_text: str | None
    event_starts_on: date | None
    event_ends_on: date | None
    status: str
    effective_state: str
    opens_at: datetime | None
    auto_close_at: datetime | None
    opens_local: datetime | None
    closes_local: datetime | None
    closed_message: str | None
    confirmation_message: str | None
    is_template: bool
    copied_from_form_id: UUID | None
    revenue_category_id: UUID | None
    allows_coupons: bool
    has_waitlist: bool
    capacity: int | None
    submitted_count: int
    has_header_image: bool
    theme: dict
    is_free: bool
    created_at: datetime
    updated_at: datetime


class EventFormDetail(EventFormOut):
    draft: EventFormVersionOut | None
    published: EventFormVersionOut | None


class FormInventoryItemPut(In):
    item_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}(\.[A-Za-z0-9_-]{1,64})?$")]
    limit_count: Annotated[int, Field(ge=0, le=1_000_000)]
    is_enabled: bool = True
    sold_out_memo: Annotated[str, StringConstraints(max_length=200)] | None = None
    shows_count_publicly: bool = False


class FormInventoryPut(In):
    items: Annotated[list[FormInventoryItemPut], Field(max_length=200)]


class FormInventoryOut(Out):
    item_key: str
    label: str
    is_enabled: bool
    limit_count: int
    sold_count: int
    remaining: int
    sold_out_memo: str | None
    shows_count_publicly: bool


class FormAnswerIn(In):
    item_key: ItemKey
    text_value: Annotated[str, StringConstraints(max_length=5000)] | None = None
    choice_keys: Annotated[list[ItemKey], Field(max_length=100)] = []
    quantity: Annotated[int, Field(ge=0, le=1000)] | None = None


class _Contact(In):
    contact_name: Name
    contact_email: Email
    contact_phone: Annotated[str, StringConstraints(max_length=40)] | None = None
    answers: Annotated[list[FormAnswerIn], Field(max_length=200)] = []


class PublicFormSubmissionCreate(_Contact):
    """Anonymous: free forms only. No client is created; staff can link one later."""


class PortalFormSubmissionCreate(_Contact):
    """contact_name and contact_email are ignored when signed in: the registrant's name and the identity's email."""

    contact_name: Name | None = None  # type: ignore[assignment]
    contact_email: Email | None = None  # type: ignore[assignment]
    form_id: UUID
    registrant_client_id: UUID
    method_token: Annotated[str, StringConstraints(max_length=255)] | None = None
    payment_method_id: UUID | None = None
    coupon_code: Annotated[str, StringConstraints(max_length=60)] | None = None


class FormAnswerOut(Out):
    item_key: str
    choice_key: str | None
    label: str
    question_type: str
    text_value: str | None
    quantity: int | None
    amount_minor: int


class FormSubmissionOut(Out):
    id: UUID
    form_id: UUID
    location_id: UUID
    confirmation_no: int
    status: str
    channel: str
    contact_name: str
    contact_email: str
    contact_phone: str | None
    account_client_id: UUID | None
    registrant_client_id: UUID | None
    total_minor: int
    invoice_id: UUID | None
    submitted_at: datetime
    cancelled_at: datetime | None
    last_edited_at: datetime | None


class FormSubmissionDetail(FormSubmissionOut):
    answers: list[FormAnswerOut]


class FormSubmissionUpdate(In):
    """Staff edit (REG-21): contact fields, the client link and text answers. Priced answers are not re-priced."""

    contact_name: Name | None = None
    contact_email: Email | None = None
    contact_phone: Annotated[str, StringConstraints(max_length=40)] | None = None
    registrant_client_id: UUID | None = None
    text_answers: Annotated[
        dict[ItemKey, Annotated[str, StringConstraints(max_length=5000)]], Field(max_length=200)
    ] = {}


class FormSubmissionCancel(In):
    reverse_charges: bool = False
    reason: Reason | None = None


class FormSummaryRow(Out):
    group: str
    label: str
    count: int
    amount_minor: int | None


class FormSummaryOut(Out):
    summary_key: str
    rows: list[FormSummaryRow]


class PublicFormChoice(Out):
    key: str
    text: str
    price_minor: int
    sold_out: bool
    remaining: int | None


class PublicFormDependsOn(Out):
    question_key: str
    choice_key: str


class PublicFormItem(Out):
    type: str
    key: str
    question_type: str | None = None
    text: str | None = None
    hint: str | None = None
    required: bool = False
    max_length: int | None = None
    unit_price_minor: int | None = None
    max_quantity: int | None = None
    sold_out: bool = False
    remaining: int | None = None
    choices: list[PublicFormChoice] = []
    depends_on: PublicFormDependsOn | None = None
    title: str | None = None
    body: str | None = None


class PublicForm(Out):
    id: UUID
    event_name: str
    event_text: str | None
    event_starts_on: date | None
    event_ends_on: date | None
    state: str
    is_free: bool
    allows_coupons: bool
    closed_message: str | None
    has_header_image: bool
    theme: dict
    items: list[PublicFormItem]


class PublicFormReceipt(Out):
    confirmation_no: int
    status: str
    total_minor: int
    confirmation_message: str | None
