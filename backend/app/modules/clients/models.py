"""clients tables (docs/architecture/data-model-people.md section 1). Skeleton: the columns every other
context needs to reference a person. Build module 4 adds the remaining columns of 1.1; nothing here is renamed."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk

_E164 = r"^\+[1-9][0-9]{6,14}$"


class ClientStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MemberNumberSource(StrEnum):
    GENERATED = "generated"
    MANUAL = "manual"
    SCANNED = "scanned"


class PortalAccessStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    REVOKED = "revoked"


class Client(TenantOwned, Timestamps, Base):
    """One row per person, never per family (CLI-01); shared across the tenant's locations (CLI-19)."""

    __tablename__ = "client"
    __table_args__ = tenant_args(
        *tfk("home_location_id", "location"),
        CheckConstraint("btrim(first_name) <> ''", name="first_name"),
        CheckConstraint("btrim(last_name) <> ''", name="last_name"),
        CheckConstraint(f"phone_mobile ~ '{_E164}'", name="phone_mobile"),
        CheckConstraint(  # one constraint under the data model's name: the pair rule and the vocabulary
            "(member_number IS NULL AND member_number_source IS NULL) OR (member_number IS NOT NULL AND "
            f"member_number_source IN ({', '.join(repr(m.value) for m in MemberNumberSource)}))",
            name="member_number_source",
        ),
        enum_check("status", ClientStatus),
        CheckConstraint("(status = 'disabled') = (disabled_at IS NOT NULL)", name="disabled"),
        Index(
            "uq_client_tenant_id_member_number", "tenant_id", "member_number", unique=True,
            postgresql_where=text("member_number IS NOT NULL"),
        ),
        Index("ix_client_name", "tenant_id", func.lower(text("last_name")), func.lower(text("first_name")), "id"),
        Index("ix_client_status", "tenant_id", "status", "id"),
    )  # fmt: skip

    first_name: Mapped[str]
    last_name: Mapped[str]
    phone_mobile: Mapped[str | None]
    home_location_id: Mapped[UUID]
    # Module 4 turns this into the denormalised copy of the primary client_email row; same column, same name.
    primary_email: Mapped[str | None] = mapped_column(CITEXT)
    member_number: Mapped[str | None] = mapped_column(CITEXT)
    member_number_source: Mapped[str | None] = enum_column()
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    disabled_at: Mapped[datetime | None]


class ClientPortalAccess(TenantOwned, Timestamps, Base):
    """Which client records a client-kind identity signs in as. Email is not an identity key here (CLI-15)."""

    __tablename__ = "client_portal_access"
    __table_args__ = tenant_args(
        *tfk("identity_id", "identity"),
        *tfk("client_id", "client"),
        *tfk("invited_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "identity_id", "client_id", name="uq_client_portal_access_identity_client"),
        Index(
            "uq_client_portal_access_primary", "tenant_id", "client_id", unique=True,
            postgresql_where=text("is_primary AND status <> 'revoked'"),
        ),
        enum_check("status", PortalAccessStatus),
    )  # fmt: skip

    identity_id: Mapped[UUID]
    client_id: Mapped[UUID]
    is_primary: Mapped[bool] = mapped_column(server_default=text("true"))
    status: Mapped[str] = enum_column(server_default=text("'invited'"))
    invited_at: Mapped[datetime | None]
    invited_by_staff_user_id: Mapped[UUID | None]
    activated_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
