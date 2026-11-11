"""Static permission catalogue and the service-layer gate (overview 3.16, rbac-matrix.md).

Each context's permissions.py registers its keys with the default grant per system role. System-role
grants resolve from this code, never from rows, so a release reaches every tenant at deploy (ADR 0009).
"""

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Select

from app.core.auth.principal import Principal
from app.core.errors import NotFound, PermissionDenied


class Scope(StrEnum):
    TENANT = "tenant"
    LOCATION = "location"
    CLIENT = "client"


# system_key -> (column in rbac-matrix.md section 6, seeded display name). Owner holds every key.
SYSTEM_ROLES = {
    "owner": ("-", "Owner"),
    "admin": ("Ad", "Admin"),
    "manager": ("Mg", "Manager"),
    "front_desk": ("FD", "Front Desk"),
    "coach": ("CT", "Coach/Trainer"),
    "league_admin": ("LM", "League Manager"),
    "scorekeeper": ("SK", "Scorekeeper"),
    "view_only": ("VO", "View Only"),
}


@dataclass(frozen=True)
class Permission:
    key: str  # <context>.<aggregate>.<verb>; also the audit action and the API-key scope
    scope: Scope
    label: str
    flags: tuple[str, ...] = ()  # rbac-matrix.md section 4 codes
    roles: dict[str, str] = field(default_factory=dict)  # system_key -> reach, Owner implied
    accepts_own_reach: bool = False
    subject_type: str | None = None
    entitlement: str | None = None

    @property
    def context(self) -> str:
        return self.key.split(".", 1)[0]

    @property
    def is_owner_only(self) -> bool:
        return "OO" in self.flags  # never grantable, not in the role editor


CATALOGUE: dict[str, Permission] = {}


def register(*permissions: Permission) -> None:
    for permission in permissions:
        unknown = set(permission.roles) - set(SYSTEM_ROLES)
        if unknown or permission.key in CATALOGUE:
            raise ValueError(f"bad catalogue entry {permission.key}: {unknown or 'duplicate'}")
        CATALOGUE[permission.key] = permission


def system_role_grants(system_key: str) -> dict[str, str]:
    if system_key == "owner":
        return dict.fromkeys(CATALOGUE, "all")
    return {p.key: p.roles[system_key] for p in CATALOGUE.values() if system_key in p.roles}


def authorize(principal: Principal, key: str, *, location_id: UUID | None = None) -> None:
    """The real gate: services call this on the loaded aggregate, whoever the caller is.

    403 when the principal lacks the key; 404 when the record is outside its location set (never
    reveal existence).
    """
    if principal.kind == "system":
        return
    if principal.kind != "staff" or key not in principal.permissions:
        raise PermissionDenied(f"Requires {key}", required=key)
    if location_id is not None and principal.location_ids is not None and location_id not in principal.location_ids:
        raise NotFound()


def authorize_tenant_wide(principal: Principal, key: str) -> None:
    """Writes to a tenant-wide row (location_id IS NULL) under a location-scoped key: the caller must reach
    every location, since the row governs all of them."""
    authorize(principal, key)
    if principal.kind != "system" and principal.location_ids is not None:
        raise PermissionDenied(f"Requires {key} at every location", required=key)


def scope_query(stmt: Select, principal: Principal, location_column) -> Select:
    """Restrict a list query to the caller's permitted locations."""
    if principal.kind == "system" or principal.location_ids is None:
        return stmt
    return stmt.where(location_column.in_(principal.location_ids))
