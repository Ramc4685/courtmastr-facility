"""assessments request and response models (openapi-people.yaml, tag assessments). Portal responses have their
own models: they show client-visible fields only and never the staff note or who recorded the entry."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Note = Annotated[str, StringConstraints(max_length=2000)]
Direction = Literal["higher", "lower", "none"]
Order = Annotated[int, Field(ge=0, le=10_000)]
Measure = Annotated[Decimal, Field(ge=Decimal("-999999999999"), le=Decimal("999999999999"))]


# --- definitions ---------------------------------------------------------------------------------------------


class AssessmentFieldOut(Out):
    id: UUID
    assessment_template_id: UUID
    name: str
    decimal_places: int
    unit_label: str | None
    better_direction: Direction
    is_client_visible: bool
    sort_order: int
    is_active: bool


class AssessmentFieldCreate(In):
    name: Name
    decimal_places: Annotated[int, Field(ge=0, le=6)] = 0
    unit_label: Unit | None = None
    better_direction: Direction = "none"
    is_client_visible: bool = True
    sort_order: Order = 0


class AssessmentFieldUpdate(In):
    name: Name | None = None
    decimal_places: Annotated[int, Field(ge=0, le=6)] | None = None
    unit_label: Unit | None = None
    better_direction: Direction | None = None
    is_client_visible: bool | None = None
    sort_order: Order | None = None
    is_active: bool | None = None


class AssessmentTemplateOut(Out):
    id: UUID
    name: str
    sort_order: int
    is_active: bool
    fields: list[AssessmentFieldOut]


class AssessmentTemplateCreate(In):
    name: Name
    sort_order: Order = 0


class AssessmentTemplateUpdate(In):
    name: Name | None = None
    sort_order: Order | None = None
    is_active: bool | None = None


class AssessmentSettingsOut(Out):
    is_portal_sharing_enabled: bool
    summary_max_age_days_default: int


class AssessmentSettingsUpdate(In):
    is_portal_sharing_enabled: bool | None = None
    summary_max_age_days_default: Annotated[int, Field(ge=1, le=3650)] | None = None


# --- results -------------------------------------------------------------------------------------------------


class AssessmentValueIn(In):
    assessment_field_id: UUID
    value: Measure


class AssessmentValueOut(Out):
    assessment_field_id: UUID
    value: Decimal


class AssessmentResultOut(Out):
    id: UUID
    client_id: UUID
    recorded_at: datetime
    recorded_by_staff_user_id: UUID | None
    location_id: UUID | None
    note: str | None
    values: list[AssessmentValueOut]


class AssessmentResultCreate(In):
    client_id: UUID
    location_id: UUID
    recorded_at: datetime
    note: Note | None = None
    values: list[AssessmentValueIn] = Field(min_length=1, max_length=200)


class AssessmentResultUpdate(In):
    recorded_at: datetime | None = None
    note: Note | None = None
    values: list[AssessmentValueIn] | None = Field(None, min_length=1, max_length=200)


class AssessmentPoint(Out):
    result_id: UUID
    recorded_at: datetime
    value: Decimal


class AssessmentSeriesOut(Out):
    assessment_field_id: UUID
    points: list[AssessmentPoint]
    latest_value: Decimal | None
    first_value: Decimal | None
    change: Decimal | None
    best_value: Decimal | None


class AssessmentSeriesList(Out):
    series: list[AssessmentSeriesOut]


# --- portal --------------------------------------------------------------------------------------------------


class PortalAssessmentValueOut(Out):
    assessment_field_id: UUID
    field_name: str
    template_name: str
    unit_label: str | None
    value: Decimal


class PortalAssessmentResultOut(Out):
    id: UUID
    recorded_at: datetime
    values: list[PortalAssessmentValueOut]


class PortalAssessmentBestOut(Out):
    assessment_field_id: UUID
    field_name: str
    template_name: str
    unit_label: str | None
    better_direction: Direction
    best_value: Decimal | None
    best_recorded_at: datetime | None
    latest_value: Decimal
    latest_recorded_at: datetime


# --- share links (FIT-05) ------------------------------------------------------------------------------------


class PortalShareLinkCreate(In):
    client_id: UUID | None = None  # whose progress; default: the signed-in client
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    expires_in_days: Annotated[int, Field(ge=1, le=90)] = 30


class PortalShareLinkOut(Out):
    id: UUID
    client_id: UUID
    label: str | None
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    is_active: bool


class PortalShareLinkCreated(PortalShareLinkOut):
    """The token and its link are shown once; only the token's hash is stored."""

    token: str
    url: str


class SharedProgressLookup(In):
    """The token from the link's URL fragment; it travels in the body, never the URL."""

    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]


class SharedProgressOut(Out):
    first_name: str
    expires_at: datetime
    results: list[PortalAssessmentResultOut]
    bests: list[PortalAssessmentBestOut]
