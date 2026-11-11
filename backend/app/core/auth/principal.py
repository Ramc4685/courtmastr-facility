"""Who is acting. Built per request from current rows; nothing here is cached in the session token."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    kind: str  # staff | client | api_key | system
    tenant_id: UUID | None = None
    identity_id: UUID | None = None
    email: str = ""
    display_name: str = ""
    staff_user_id: UUID | None = None
    role_id: UUID | None = None
    role_system_key: str | None = None
    permissions: Mapping[str, str] = field(default_factory=dict)  # effective key -> reach (all | own)
    location_ids: frozenset[UUID] | None = None  # None = every location of the tenant
    session_id: UUID | None = None
    api_key_id: UUID | None = None  # kind = api_key: the key; staff_user_id stays None (it is not a person)

    @property
    def is_owner(self) -> bool:
        return self.kind == "system" or self.role_system_key == "owner"

    def has(self, key: str) -> bool:
        return self.kind == "system" or key in self.permissions

    # Audit attribution (ADR 0007 section 4).
    @property
    def actor_type(self) -> str:
        return self.kind

    @property
    def actor_id(self) -> UUID | None:
        return self.api_key_id or self.staff_user_id or self.identity_id

    @property
    def actor_label(self) -> str:
        return self.display_name or self.email


def system_principal(job_name: str) -> Principal:
    """Jobs and seeds: passes every check, still audited as actor_type = system."""
    return Principal(kind="system", display_name=job_name)
