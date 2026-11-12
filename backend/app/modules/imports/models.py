"""imports tables (data-model-core 2.6 `import_job`, `import_job_row`; deviations in the README).

A job holds no cell values: the source rows are re-read from the stored file, and a row keeps only its number,
the hash of its natural key, its outcome and error codes with plain-words details that never quote a cell."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JsonDict, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk


class ImportKind(StrEnum):
    CLIENTS = "clients"
    MEMBERSHIPS = "memberships"
    BALANCES = "balances"
    PRODUCTS = "products"


class DateFormat(StrEnum):
    ISO = "iso"  # 2026-01-31
    MDY = "mdy"  # 01/31/2026
    DMY = "dmy"  # 31/01/2026


class JobStatus(StrEnum):
    NEW = "new"  # created, no file yet
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    VALIDATED = "validated"  # dry run found no row errors
    NEEDS_REVIEW = "needs_review"  # dry run found row errors: commit imports the rest and fails those rows
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"  # a chunk exhausted its retries (dead letter); rows already done keep their outcomes


class RowStatus(StrEnum):
    VALID = "valid"  # dry run: would import
    INVALID = "invalid"  # dry run: would fail
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"  # duplicate (in the file or already imported)
    FAILED = "failed"


class EntityType(StrEnum):
    CLIENT = "client"
    MEMBERSHIP_CONTRACT = "membership_contract"
    CHARGE = "charge"  # an opening balance owed
    PAYMENT = "payment"  # an opening account credit
    PRODUCT = "product"


class ImportJob(TenantOwned, Timestamps, Base):
    __tablename__ = "import_job"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("source_file_id", "stored_file"),
        *tfk("report_file_id", "stored_file", index=False),
        *tfk("submitted_by_staff_user_id", "staff_user"),
        enum_check("kind", ImportKind),
        enum_check("date_format", DateFormat),
        enum_check("status", JobStatus),
        Index("ix_import_job_status", "tenant_id", "status", "id"),
        Index("ix_import_job_expiry", "tenant_id", "expires_at", postgresql_where=text("files_purged_at IS NULL")),
    )

    location_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    source_file_id: Mapped[UUID | None]
    source_headers: Mapped[list] = mapped_column(JsonDict, server_default=text("'[]'"))  # the file's header row
    date_format: Mapped[str] = enum_column(server_default=text("'iso'"))
    column_mapping: Mapped[dict] = mapped_column(server_default=text("'{}'"))  # our field -> source header
    status: Mapped[str] = enum_column(server_default=text("'new'"))
    submitted_by_staff_user_id: Mapped[UUID]
    total_row_count: Mapped[int] = mapped_column(server_default=text("0"))
    valid_row_count: Mapped[int] = mapped_column(server_default=text("0"))
    created_count: Mapped[int] = mapped_column(server_default=text("0"))
    updated_count: Mapped[int] = mapped_column(server_default=text("0"))
    skipped_count: Mapped[int] = mapped_column(server_default=text("0"))
    error_count: Mapped[int] = mapped_column(server_default=text("0"))
    # The chunk cursor (core.jobs.chunked_actor): {"next": row index, "creates": rows a dry run would create}.
    progress: Mapped[dict] = mapped_column(server_default=text("'{}'"))
    report_file_id: Mapped[UUID | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    expires_at: Mapped[datetime]  # source file and error report are removed after this (retention)
    files_purged_at: Mapped[datetime | None]


class ImportJobRow(TenantOwned, Timestamps, Base):
    __tablename__ = "import_job_row"
    __table_args__ = tenant_args(
        *tfk("import_job_id", "import_job", ondelete="CASCADE", index=False),
        enum_check("status", RowStatus),
        enum_check("entity_type", EntityType),
        Index("uq_import_job_row", "tenant_id", "import_job_id", "row_number", unique=True),
        Index("ix_import_job_row_key", "tenant_id", "row_key"),  # duplicate checks, in this job and earlier ones
    )

    import_job_id: Mapped[UUID]
    row_number: Mapped[int]  # the spreadsheet row: the header is row 1, the first data row is 2
    row_key: Mapped[str]  # SHA-256 of the kind and the row's natural key: the idempotency key
    status: Mapped[str] = enum_column()
    entity_type: Mapped[str | None] = enum_column()
    entity_id: Mapped[UUID | None]  # polymorphic, no FK
    errors: Mapped[list] = mapped_column(JsonDict, server_default=text("'[]'"))  # [{"column", "code", "detail"}]
