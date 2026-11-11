"""assessments tables (docs/architecture/data-model-people.md section 5). Values are health data (rbac flag
`H`): measured values are declared `audit: flag`, so the trail records that a value changed, never what to."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Numeric, SmallInteger, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk


class BetterDirection(StrEnum):
    HIGHER = "higher"
    LOWER = "lower"
    NONE = "none"


class AssessmentTemplate(TenantOwned, Timestamps, Base):
    __tablename__ = "assessment_template"
    __table_args__ = tenant_args(
        Index(
            "uq_assessment_template_name",
            "tenant_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("is_active"),
        ),  # fmt: skip
    )

    name: Mapped[str] = mapped_column(Text, info={"audit": "value"})
    sort_order: Mapped[int] = mapped_column(server_default=text("0"), info={"audit": "value"})
    is_active: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})


class AssessmentField(TenantOwned, Timestamps, Base):
    __tablename__ = "assessment_field"
    __table_args__ = tenant_args(
        *tfk("assessment_template_id", "assessment_template", index=False),
        enum_check("better_direction", BetterDirection),
        CheckConstraint("decimal_places BETWEEN 0 AND 6", name="decimal_places"),
        Index(
            "uq_assessment_field_name",
            "tenant_id",
            "assessment_template_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("is_active"),
        ),  # fmt: skip
    )

    assessment_template_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(Text, info={"audit": "value"})
    decimal_places: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), info={"audit": "value"})
    unit_label: Mapped[str | None] = mapped_column(Text, info={"audit": "value"})
    better_direction: Mapped[str] = enum_column(server_default=text("'none'"))
    is_client_visible: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    sort_order: Mapped[int] = mapped_column(server_default=text("0"), info={"audit": "value"})
    is_active: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})


class AssessmentResult(TenantOwned, Timestamps, Base):
    __tablename__ = "assessment_result"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("recorded_by_staff_user_id", "staff_user"),
        *tfk("location_id", "location"),
        Index("ix_assessment_result_client", "tenant_id", "client_id", text("recorded_at DESC")),
    )

    client_id: Mapped[UUID]
    recorded_at: Mapped[datetime]
    recorded_by_staff_user_id: Mapped[UUID | None]
    location_id: Mapped[UUID | None]
    note: Mapped[str | None] = mapped_column(Text)


class AssessmentResultValue(TenantOwned, Timestamps, Base):
    __tablename__ = "assessment_result_value"
    __table_args__ = tenant_args(
        *tfk("assessment_result_id", "assessment_result", ondelete="CASCADE", index=False),
        *tfk("assessment_field_id", "assessment_field", index=False),
        *tfk("client_id", "client", index=False),
        UniqueConstraint("tenant_id", "assessment_result_id", "assessment_field_id"),
        Index(
            "ix_assessment_result_value_series",
            "tenant_id",
            "client_id",
            "assessment_field_id",
            text("recorded_at DESC"),
            postgresql_include=["value"],
        ),  # fmt: skip
        Index(
            "ix_assessment_result_value_cohort",
            "tenant_id",
            "assessment_field_id",
            text("recorded_at DESC"),
            "client_id",
            postgresql_include=["value"],
        ),  # fmt: skip
    )

    assessment_result_id: Mapped[UUID]
    assessment_field_id: Mapped[UUID]
    client_id: Mapped[UUID]
    recorded_at: Mapped[datetime]
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), info={"audit": "flag"})  # health data (H)


class AssessmentSettings(TenantOwned, Timestamps, Base):
    __tablename__ = "assessment_settings"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", name="uq_assessment_settings_tenant"),
        CheckConstraint("summary_max_age_days_default BETWEEN 1 AND 3650", name="summary_max_age_days_default"),
    )

    is_portal_sharing_enabled: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    summary_max_age_days_default: Mapped[int] = mapped_column(server_default=text("90"), info={"audit": "value"})
