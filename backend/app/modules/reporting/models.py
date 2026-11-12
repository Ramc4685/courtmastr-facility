"""reporting tables (docs/architecture/data-model-programs.md section 4, ADR 0010). The context stores what users
save and what runs and exports produce, never business facts: those are read through the `rpt_*` views in
`views.py`. The report catalogue is code (`registry.py`), not a table."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, LargeBinary, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, WallTime, enum_check, enum_column, tenant_args, tfk


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class SourceKind(StrEnum):
    REPORT_RUN = "report_run"
    LIST = "list"
    DOCUMENT_BATCH = "document_batch"


class ExportFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class SavedReport(TenantOwned, Timestamps, Base):
    """A user's saved parameter set (4.2). It grants nothing: running it applies the runner's gates."""

    __tablename__ = "saved_report"
    __table_args__ = tenant_args(
        *tfk("owner_staff_user_id", "staff_user", index=False),
        Index("uq_saved_report_owner_name", "tenant_id", "owner_staff_user_id", func.lower(text("name")), unique=True),
    )

    report_key: Mapped[str] = mapped_column(info={"audit": "value"})
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    params: Mapped[dict] = mapped_column(server_default=text("'{}'"))
    columns: Mapped[dict | None]
    owner_staff_user_id: Mapped[UUID]
    is_shared: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    last_run_at: Mapped[datetime | None]


class ReportRun(TenantOwned, Timestamps, Base):
    """One execution with frozen, resolved parameters: a static snapshot kept in `result_file_id` (4.3)."""

    __tablename__ = "report_run"
    __table_args__ = tenant_args(
        *tfk("saved_report_id", "saved_report"),
        *tfk("requested_by_staff_user_id", "staff_user", index=False),
        *tfk("result_file_id", "stored_file"),
        enum_check("status", RunStatus),
        Index("ix_report_run_recent", "tenant_id", "requested_by_staff_user_id", "id"),
    )

    report_key: Mapped[str] = mapped_column(info={"audit": "value"})
    saved_report_id: Mapped[UUID | None]
    requested_by_staff_user_id: Mapped[UUID]
    params: Mapped[dict]
    params_hash: Mapped[str] = mapped_column(info={"audit": "value"})
    status: Mapped[str] = enum_column(server_default=text("'queued'"))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    row_count: Mapped[int | None] = mapped_column(info={"audit": "value"})
    # Deviation from 4.3 (README): the report totals sit on the row too, so lists show them without the file.
    totals: Mapped[dict | None]
    result_file_id: Mapped[UUID | None]
    error: Mapped[str | None]
    expires_at: Mapped[datetime]


class ExportJob(TenantOwned, Timestamps, Base):
    """A file rendered by the `run_export` job from a report run snapshot (4.4)."""

    __tablename__ = "export_job"
    __table_args__ = tenant_args(
        *tfk("report_run_id", "report_run"),
        *tfk("file_id", "stored_file"),
        *tfk("requested_by_staff_user_id", "staff_user", index=False),
        enum_check("source_kind", SourceKind),
        enum_check("format", ExportFormat),
        enum_check("status", RunStatus),
        CheckConstraint("(source_kind = 'report_run') = (report_run_id IS NOT NULL)", name="source"),
        CheckConstraint("page_size IS NULL OR page_size IN ('a4', 'letter')", name="page_size"),
        CheckConstraint("orientation IS NULL OR orientation IN ('portrait', 'landscape')", name="orientation"),
        Index("ix_export_job_history", "tenant_id", "requested_by_staff_user_id", "id"),
        Index("ix_export_job_source", "tenant_id", "source_key", "id"),
    )

    source_kind: Mapped[str] = enum_column()
    report_run_id: Mapped[UUID | None]
    source_key: Mapped[str] = mapped_column(info={"audit": "value"})
    params: Mapped[dict] = mapped_column(server_default=text("'{}'"))
    format: Mapped[str] = enum_column(server_default=text("'csv'"))
    includes_details: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    page_size: Mapped[str | None] = enum_column()
    orientation: Mapped[str | None] = enum_column()
    status: Mapped[str] = enum_column(server_default=text("'queued'"))
    row_count: Mapped[int | None] = mapped_column(info={"audit": "value"})
    file_id: Mapped[UUID | None]
    error: Mapped[str | None]
    requested_by_staff_user_id: Mapped[UUID]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    expires_at: Mapped[datetime]
    # Chunked rendering (core.jobs.chunked_actor): the cursor and counts, and the CSV rendered so far, cleared
    # when the file is stored. Deviation from data-model-programs 4.4 (README).
    progress: Mapped[dict] = mapped_column(server_default=text("'{}'"))
    partial: Mapped[bytes | None] = mapped_column(LargeBinary, info={"audit": "never"})
    # A scheduled delivery: when the file is stored, the requester gets an email with a sign-in link to it.
    notify_on_complete: Mapped[bool] = mapped_column(server_default=text("false"))


class ReportSchedule(TenantOwned, Timestamps, Base):
    """Scheduled delivery of a saved report (RPT-01; ADR 0010 section 7 as amended). At `send_time` in the
    location's zone on each due day, every recipient gets their own run and export, built with their own
    permissions and locations, and an email linking to it (never the file)."""

    __tablename__ = "report_schedule"
    __table_args__ = tenant_args(
        *tfk("saved_report_id", "saved_report"),
        *tfk("location_id", "location", index=False),
        *tfk("owner_staff_user_id", "staff_user", index=False),
        enum_check("frequency", Frequency),
        enum_check("format", ExportFormat),
        CheckConstraint("(frequency = 'weekly') = (weekday IS NOT NULL)", name="weekday"),
        CheckConstraint("(frequency = 'monthly') = (month_day IS NOT NULL)", name="month_day"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("month_day BETWEEN 1 AND 28", name="month_day_range"),
        CheckConstraint("cardinality(recipient_staff_user_ids) BETWEEN 1 AND 20", name="recipients"),
    )

    saved_report_id: Mapped[UUID]
    location_id: Mapped[UUID]  # whose time zone sets the send time and the day
    owner_staff_user_id: Mapped[UUID]
    frequency: Mapped[str] = enum_column()
    weekday: Mapped[int | None] = mapped_column(info={"audit": "value"})  # 0 Monday to 6 Sunday
    month_day: Mapped[int | None] = mapped_column(info={"audit": "value"})
    send_time: Mapped[str] = mapped_column(WallTime, info={"audit": "value"})
    format: Mapped[str] = enum_column(server_default=text("'csv'"))
    includes_details: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    recipient_staff_user_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PgUUID(as_uuid=True)))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    last_run_on: Mapped[date | None]  # the location-local day of the last delivery; at most one a day
