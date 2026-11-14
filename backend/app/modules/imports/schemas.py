"""imports request and response models (our API: tag imports)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401

KindValue = Literal["clients", "memberships", "balances", "products"]
Header = Annotated[str, StringConstraints(max_length=200)]


class ImportFieldOut(Out):
    key: str
    label: str
    required: bool
    help: str
    example: str


class ImportTemplateOut(Out):
    kind: str
    label: str
    guide: list[str]
    fields: list[ImportFieldOut]


class ImportJobCreate(In):
    kind: KindValue
    location_id: UUID


class ImportDryRunCreate(In):
    column_mapping: (
        Annotated[dict[Annotated[str, StringConstraints(max_length=64)], Header], Field(max_length=40)] | None
    ) = None
    date_format: Literal["iso", "mdy", "dmy"] | None = None


class ImportJobOut(Out):
    id: UUID
    kind: str
    location_id: UUID
    status: str
    source_file_name: str | None
    source_headers: list[str]
    column_mapping: dict[str, str]
    date_format: str
    total_row_count: int
    processed_row_count: int
    valid_row_count: int
    created_count: int
    updated_count: int
    skipped_count: int
    error_count: int
    has_error_report: bool
    stop_reason: str | None  # plain words, for a failed (stopped) job
    submitted_by_staff_user_id: UUID
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime
    files_purged_at: datetime | None
    created_at: datetime
    updated_at: datetime
