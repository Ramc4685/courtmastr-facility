"""reporting request and response models (openapi-programs.yaml, tag reporting). Report parameters stay a free
object here: each report's own parameter model (registry.py) validates them in the service, and its JSON Schema
is served on the definition."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Key = Annotated[str, StringConstraints(max_length=64)]


class ReportDefinitionOut(Out):
    key: str
    name: str
    description: str
    category: str
    required_permission: str
    required_entitlement: str | None
    date_basis: str
    params_schema: dict[str, Any]
    columns: list[dict[str, Any]]
    total_columns: list[dict[str, Any]]
    detail_columns: list[dict[str, Any]] | None
    supports_detail: bool
    export_formats: list[str]
    is_stub: bool
    features: list[str]


class ReportRunCreate(In):
    report_key: Key
    params: dict[str, Any] | None = None
    saved_report_id: UUID | None = None


class ReportRunOut(Out):
    id: UUID
    report_key: str
    saved_report_id: UUID | None
    params: dict[str, Any]
    status: str
    row_count: int | None
    totals: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class ReportRowsOut(Out):
    columns: list[dict[str, Any]]
    data: list[dict[str, Any]]
    totals: dict[str, Any] | None
    page: dict[str, Any]


class SavedReportCreate(In):
    report_key: Key
    name: Name
    params: dict[str, Any] = {}
    columns: list[Key] | None = None
    is_shared: bool = False


class SavedReportUpdate(In):
    name: Name | None = None
    params: dict[str, Any] | None = None
    columns: list[Key] | None = None
    is_shared: bool | None = None


class SavedReportOut(Out):
    id: UUID
    report_key: str
    name: str
    params: dict[str, Any]
    columns: list[str] | None
    is_shared: bool
    owner_staff_user_id: UUID
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExportJobCreate(In):
    source_kind: Literal["report_run", "list", "document_batch"] = "report_run"
    report_run_id: UUID | None = None
    format: Literal["csv", "xlsx", "pdf"] = "csv"
    includes_details: bool = False
    page_size: Literal["a4", "letter"] | None = None
    orientation: Literal["portrait", "landscape"] | None = None


class ExportJobOut(Out):
    id: UUID
    source_kind: str
    report_run_id: UUID | None
    source_key: str
    params: dict[str, Any]
    format: str
    includes_details: bool
    page_size: str | None
    orientation: str | None
    status: str
    row_count: int | None
    file_name: str | None
    error: str | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
