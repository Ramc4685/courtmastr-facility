"""Effective-permission resolution for staff (ADR 0009 section 3, data-model-core 2.4).

Evaluated per request from current rows, so a role edit or a revocation applies on the next request.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import CATALOGUE, Principal, system_role_grants
from app.modules.platform.models import Role, RolePermission, StaffUser


def role_grants(session: Session, role: Role) -> dict[str, str]:
    """key -> reach. System roles resolve from code; custom roles from their null-subject rows."""
    if role.system_key:
        return system_role_grants(role.system_key)
    keys = session.scalars(
        select(RolePermission.permission_key).where(
            RolePermission.role_id == role.id, RolePermission.subject_id.is_(None), RolePermission.is_allowed
        )
    )
    return {key: "all" for key in keys if key in CATALOGUE}  # rows naming a retired key are ignored


def effective_permissions(session: Session, staff_user: StaffUser) -> dict[str, str]:
    """Role grants, then per-user overrides win. No override applies to an Owner."""
    grants = role_grants(session, staff_user.role)
    if staff_user.role.system_key == "owner":
        return grants
    for override in staff_user.overrides:
        if override.subject_id is not None or override.permission_key not in CATALOGUE:
            continue  # subject-scoped overrides are stored but have no subjects to apply to until scheduling
        if override.is_allowed:
            grants[override.permission_key] = "all"
        else:
            grants.pop(override.permission_key, None)
    return grants


def staff_principal(session: Session, staff_user: StaffUser, session_id=None) -> Principal:
    all_locations = staff_user.has_all_location_access or staff_user.role.system_key == "owner"
    return Principal(
        kind="staff",
        tenant_id=staff_user.tenant_id,
        identity_id=staff_user.identity_id,
        email=staff_user.identity.email,
        display_name=staff_user.display_name,
        staff_user_id=staff_user.id,
        role_id=staff_user.role_id,
        role_system_key=staff_user.role.system_key,
        permissions=effective_permissions(session, staff_user),
        location_ids=None if all_locations else frozenset(a.location_id for a in staff_user.location_access),
        session_id=session_id,
    )
