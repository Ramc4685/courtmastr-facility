"""Staff users, roles and permission administration, with the escalation rules of rbac-matrix.md section 13."""

from collections.abc import Iterable
from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.auth import CATALOGUE, Principal, authorize
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules.platform import auth, mfa, rbac
from app.modules.platform.events import StaffUserDeactivated, StaffUserInvited
from app.modules.platform.models import (
    Identity,
    Location,
    Role,
    RolePermission,
    StaffUser,
    TokenPurpose,
    UserLocationAccess,
    UserPermissionOverride,
)
from app.ports.email import EmailMessage, send_after_commit

# --- shared rules ------------------------------------------------------------------------------------------


def _self_escalation(detail: str) -> PermissionDenied:
    return PermissionDenied(detail, code="self-escalation")


def _check_known(keys: Iterable[str]) -> None:
    for key in keys:
        if key not in CATALOGUE or CATALOGUE[key].is_owner_only:  # owner-only keys are not in the role editor
            raise ValidationFailed(f"Unknown permission: {key}", code="unknown-permission", pointer="/grants")


def _check_grantable(principal: Principal, keys: Iterable[str]) -> None:
    """No grant beyond self: an editor can only hand out keys it holds."""
    keys = list(keys)
    _check_known(keys)
    for key in keys:
        if not principal.has(key):
            raise _self_escalation(f"You cannot grant {key} because you do not hold it.")


def _check_owner_protection(principal: Principal, target: StaffUser) -> None:
    """No non-Owner may update, deactivate or reset credentials of an Owner."""
    if target.role.system_key == "owner" and not principal.is_owner:
        raise PermissionDenied("Only an owner can change an owner.")


def _check_not_self(
    principal: Principal, target: StaffUser, detail: str = "You cannot change your own role, permissions or locations."
) -> None:
    if principal.staff_user_id == target.id:
        raise _self_escalation(detail)


def _check_last_owner(session: Session, target: StaffUser) -> None:
    """A tenant always keeps at least one active Owner."""
    if target.role.system_key != "owner" or not target.is_active:
        return
    others = session.scalar(
        select(func.count())
        .select_from(StaffUser)
        .join(Role, Role.id == StaffUser.role_id)
        .where(Role.system_key == "owner", StaffUser.is_active, StaffUser.id != target.id)
    )
    if not others:
        raise Conflict("The account must keep at least one active owner.", code="last-owner")


def _check_assignable_role(session: Session, principal: Principal, role: Role) -> None:
    if role.system_key == "owner":
        if not principal.is_owner:
            raise _self_escalation("Only an owner can assign the Owner role.")
        return
    missing = [key for key in rbac.role_grants(session, role) if not principal.has(key)]
    if missing:
        raise _self_escalation(f"You cannot assign a role that grants {missing[0]}, which you do not hold.")


def _load_role(session: Session, role_id: UUID, *, pointer: str | None = None) -> Role:
    role = session.get(Role, role_id)
    if role is None:
        if pointer:
            raise ValidationFailed("Unknown role.", pointer=pointer)
        raise NotFound()
    return role


def _refresh(session: Session, staff_user: StaffUser) -> StaffUser:
    session.flush()
    session.refresh(staff_user)  # reload the read-only joins after id columns or child rows changed
    return staff_user


# --- staff users -------------------------------------------------------------------------------------------


def list_staff_users(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "platform.staff_user.read")
    filters = dict(query.filters)
    stmt = select(StaffUser).join(Identity, Identity.id == StaffUser.identity_id)
    if location_id := filters.pop("location_id", None):
        try:
            in_location = select(UserLocationAccess.staff_user_id).where(
                UserLocationAccess.location_id == UUID(location_id)
            )
        except ValueError:
            raise ValidationFailed("Invalid location_id", pointer="/location_id") from None
        stmt = stmt.where(StaffUser.has_all_location_access | StaffUser.id.in_(in_location))
    query = ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters)
    return paginate(
        session,
        stmt,
        query,
        id_column=StaffUser.id,
        sort_fields={
            "last_name": StaffUser.last_name,
            "first_name": StaffUser.first_name,
            "email": Identity.email,
            "created_at": StaffUser.created_at,
        },
        default_sort="last_name,first_name",
        filter_fields={
            "role_id": StaffUser.role_id,
            "is_active": StaffUser.is_active,
            "identity_status": Identity.status,
        },
        search=(StaffUser.first_name, StaffUser.last_name, Identity.email),
    )


def get_staff_user(
    session: Session, principal: Principal, staff_user_id: UUID, *, permission: str = "platform.staff_user.read"
) -> StaffUser:
    authorize(principal, permission)
    staff_user = session.get(StaffUser, staff_user_id)
    if staff_user is None:
        raise NotFound()
    return staff_user


def _send_invite(session: Session, identity: Identity) -> None:
    ttl = timedelta(days=get_settings().auth.invite_ttl_days)
    auth.issue_link(session, identity, TokenPurpose.INVITE, ttl)


def _set_locations(
    session: Session,
    principal: Principal,
    staff_user: StaffUser,
    *,
    has_all: bool,
    location_ids: list[UUID],
    primary_location_id: UUID | None,
) -> None:
    """Location containment: an editor limited to a location set can only assign locations inside it, and
    leaves the target's other locations as they are (S-07): it has no say over them."""
    wanted = set(location_ids)
    if primary_location_id:
        wanted.add(primary_location_id)
    foreign: dict[UUID, bool] = {}  # location -> is_primary, outside the editor's set
    if principal.location_ids is not None:
        if has_all or not wanted <= principal.location_ids:
            raise _self_escalation("You can only assign locations you have access to yourself.")
        if staff_user.has_all_location_access:
            raise _self_escalation("Only someone with access to every location can change this user's locations.")
        foreign = {
            a.location_id: a.is_primary and primary_location_id is None
            for a in staff_user.location_access
            if a.location_id not in principal.location_ids
        }
    known = set(session.scalars(select(Location.id).where(Location.id.in_(wanted)))) if wanted else set()
    if wanted - known:
        raise ValidationFailed("Unknown location.", pointer="/location_ids")
    staff_user.has_all_location_access = has_all
    session.execute(delete(UserLocationAccess).where(UserLocationAccess.staff_user_id == staff_user.id))
    rows = {location_id: location_id == primary_location_id for location_id in wanted} | foreign
    for location_id in sorted(rows):
        session.add(
            UserLocationAccess(staff_user_id=staff_user.id, location_id=location_id, is_primary=rows[location_id])
        )


def invite_staff_user(session: Session, principal: Principal, data: dict) -> StaffUser:
    """Create the identity (invited) and staff user, and email a 7-day invite link. No admin-typed password."""
    authorize(principal, "platform.staff_user.invite")
    # hook: staff-seat metering, off by owner decision (platform README "Deferred"); enforce_limit "staff_users"
    role = _load_role(session, data["role_id"], pointer="/role_id")
    _check_assignable_role(session, principal, role)
    identity = Identity(kind="staff", email=data["email"], status="invited")
    session.add(identity)
    session.flush()  # a duplicate email surfaces here as uq_identity_kind_email -> 409 already-exists
    staff_user = StaffUser(
        identity_id=identity.id,
        role_id=role.id,
        first_name=data["first_name"],
        last_name=data["last_name"],
        mobile_phone=data.get("mobile_phone"),
        linked_resource_id=data.get("linked_resource_id"),
        access_expires_on=data.get("access_expires_on"),
        ip_policy=role.default_ip_policy,
    )
    session.add(staff_user)
    session.flush()
    _set_locations(
        session, principal, staff_user,
        has_all=data.get("has_all_location_access", False),
        location_ids=data.get("location_ids") or [],
        primary_location_id=data.get("primary_location_id"),
    )  # fmt: skip
    _send_invite(session, identity)
    audit.record(session, "platform.staff_user.invite", staff_user, changes={"role_id": [None, str(role.id)]})
    events.publish(session, StaffUserInvited(staff_user_id=staff_user.id, role_id=role.id), staff_user.id)
    return _refresh(session, staff_user)


_SECURITY_FIELDS = frozenset({"ip_policy", "access_expires_on"})  # extending access or lifting an IP restriction
_UPDATABLE_FIELDS = _SECURITY_FIELDS | {
    "first_name", "last_name", "mobile_phone", "linked_resource_id", "is_attendance_notified"
}  # fmt: skip


def update_staff_user(session: Session, principal: Principal, staff_user_id: UUID, data: dict) -> StaffUser:
    staff_user = get_staff_user(session, principal, staff_user_id, permission="platform.staff_user.update")
    _check_owner_protection(principal, staff_user)
    if unknown := sorted(data.keys() - _UPDATABLE_FIELDS):
        raise ValidationFailed(f"{unknown[0]} cannot be changed here.", code="unknown-field", pointer=f"/{unknown[0]}")
    changed = {field for field, value in data.items() if getattr(staff_user, field) != value}
    if changed & _SECURITY_FIELDS:
        _check_not_self(principal, staff_user, "You cannot change your own access expiry or IP policy.")
    if "ip_policy" in changed:
        authorize(principal, "platform.security.manage")
    for field in changed:
        setattr(staff_user, field, data[field])
    audit.record(session, "platform.staff_user.update", staff_user, changes=audit.diff(staff_user))
    return _refresh(session, staff_user)


def deactivate_staff_user(session: Session, principal: Principal, staff_user_id: UUID) -> StaffUser:
    staff_user = get_staff_user(session, principal, staff_user_id, permission="platform.staff_user.deactivate")
    _check_owner_protection(principal, staff_user)
    _check_last_owner(session, staff_user)
    if staff_user.is_active:
        staff_user.is_active = False
        auth.revoke_sessions(session, staff_user.identity_id, "disabled")  # immediate, not at token expiry
        audit.record(session, "platform.staff_user.deactivate", staff_user, changes={"is_active": [True, False]})
        events.publish(session, StaffUserDeactivated(staff_user_id=staff_user.id), staff_user.id)
    return _refresh(session, staff_user)


def reactivate_staff_user(session: Session, principal: Principal, staff_user_id: UUID) -> StaffUser:
    staff_user = get_staff_user(session, principal, staff_user_id, permission="platform.staff_user.deactivate")
    _check_owner_protection(principal, staff_user)
    if not staff_user.is_active:
        # hook: staff-seat metering, off by owner decision (platform README "Deferred"); enforce_limit "staff_users"
        staff_user.is_active = True
        audit.record(session, "platform.staff_user.reactivate", staff_user, changes={"is_active": [False, True]})
    return _refresh(session, staff_user)


def resend_invitation(session: Session, principal: Principal, staff_user_id: UUID) -> None:
    staff_user = get_staff_user(session, principal, staff_user_id, permission="platform.staff_user.invite")
    if staff_user.identity.status != "invited":
        raise Conflict("This user has already accepted the invitation.")
    _send_invite(session, staff_user.identity)
    audit.record(session, "platform.staff_user.invite", staff_user, reason="resend")


def reset_credentials(session: Session, principal: Principal, staff_user_id: UUID) -> None:
    """Admin reset sends the same reset link as self-service and signs the user out everywhere (PLT-03)."""
    staff_user = get_staff_user(session, principal, staff_user_id, permission="platform.staff_user.reset_credentials")
    _check_owner_protection(principal, staff_user)
    identity = staff_user.identity
    if identity.status == "invited":
        _send_invite(session, identity)
    else:
        ttl = timedelta(minutes=get_settings().auth.password_reset_ttl_min)
        auth.issue_link(session, identity, TokenPurpose.PASSWORD_RESET, ttl)
        auth.revoke_sessions(session, identity.id, "admin")
    audit.record(session, "platform.staff_user.reset_credentials", staff_user)


def reset_mfa(session: Session, principal: Principal, staff_user_id: UUID) -> None:
    """Lost authenticator (ADR 0002 section 6): an Owner or Admin removes another user's factor and recovery
    codes and signs them out everywhere. Only an Owner resets an Owner; nobody resets their own here (their
    security page needs a code). If MFA is required for them, the next sign-in walks them through enrolment,
    which needs an emailed link (S2)."""
    staff_user = get_staff_user(session, principal, staff_user_id, permission="platform.staff_user.reset_mfa")
    _check_not_self(principal, staff_user, "Change your own two-step verification from your security page.")
    _check_owner_protection(principal, staff_user)
    identity = staff_user.identity
    if mfa.factor(session, identity.id) is None:
        raise Conflict("This user has no two-step verification to reset.")
    mfa.remove(session, identity.id)
    auth.revoke_sessions(session, identity.id, "mfa_change")
    audit.record(session, "platform.staff_user.reset_mfa", staff_user)  # actor and target only; no secrets
    name = get_settings().app.display_name
    body = (
        "An administrator removed the two-step verification from your account, and you were signed out everywhere. "
        "At your next sign-in you can set up a new authenticator app. If you did not ask for this, contact your "
        "administrator now."
    )
    send_after_commit(session, EmailMessage(identity.email, f"{name}: two-step verification was reset", body))


def assign_role(
    session: Session, principal: Principal, staff_user_id: UUID, role_id: UUID, *, reset_overrides: bool = True
) -> StaffUser:
    staff_user = get_staff_user(session, principal, staff_user_id, permission="platform.staff_user.assign_role")
    _check_not_self(principal, staff_user)
    _check_owner_protection(principal, staff_user)
    role = _load_role(session, role_id, pointer="/role_id")
    _check_assignable_role(session, principal, role)
    if role.id != staff_user.role_id:
        _check_last_owner(session, staff_user)
        changes = {"role_id": [str(staff_user.role_id), str(role.id)]}
        staff_user.role_id = role.id
        if reset_overrides and staff_user.overrides:
            # Deltas were written against the old role; carrying them to a narrower one would surprise (ADR 0009).
            changes["dropped_overrides"] = sorted(o.permission_key for o in staff_user.overrides)
            session.execute(delete(UserPermissionOverride).where(UserPermissionOverride.staff_user_id == staff_user.id))
        audit.record(session, "platform.staff_user.assign_role", staff_user, changes=changes)
    return _refresh(session, staff_user)


def assign_locations(session: Session, principal: Principal, staff_user_id: UUID, data: dict) -> StaffUser:
    staff_user = get_staff_user(session, principal, staff_user_id, permission="platform.staff_user.assign_locations")
    _check_not_self(principal, staff_user)
    _check_owner_protection(principal, staff_user)
    before = sorted(str(a.location_id) for a in staff_user.location_access)
    had_all = staff_user.has_all_location_access
    _set_locations(
        session, principal, staff_user,
        has_all=data["has_all_location_access"],
        location_ids=data.get("location_ids") or [],
        primary_location_id=data.get("primary_location_id"),
    )  # fmt: skip
    _refresh(session, staff_user)
    after = sorted(str(a.location_id) for a in staff_user.location_access)
    audit.record(
        session, "platform.staff_user.assign_locations", staff_user,
        changes={"location_ids": [before, after], "has_all_location_access": [had_all, staff_user.has_all_location_access]},
    )  # fmt: skip
    return staff_user


def get_permissions(session: Session, principal: Principal, staff_user_id: UUID) -> dict:
    return _permissions_view(session, get_staff_user(session, principal, staff_user_id))


def _permissions_view(session: Session, staff_user: StaffUser) -> dict:
    from_role = rbac.role_grants(session, staff_user.role)
    effective = rbac.effective_permissions(session, staff_user)
    return {
        "staff_user_id": staff_user.id,
        "role": staff_user.role,
        "effective": [
            {"key": key, "reach": reach, "source": "role" if from_role.get(key) == reach else "override"}
            for key, reach in sorted(effective.items())
        ],
        "overrides": staff_user.overrides,
        # Computed, not "rows exist": an override made redundant by a later role edit stops showing.
        "is_diverged_from_role": effective != from_role,
    }


def replace_permission_overrides(
    session: Session, principal: Principal, staff_user_id: UUID, grants: list[dict]
) -> dict:
    """Replace the user's whole override set (PLT-05). Overrides equal to the role's grant are not stored."""
    staff_user = get_staff_user(
        session, principal, staff_user_id, permission="platform.staff_user.override_permissions"
    )
    _check_not_self(principal, staff_user)
    if staff_user.role.system_key == "owner":
        raise Conflict("No override applies to an owner.")
    _check_known(g["permission_key"] for g in grants)
    _check_grantable(principal, (g["permission_key"] for g in grants if g["is_allowed"]))
    from_role = rbac.role_grants(session, staff_user.role)
    before = {o.permission_key: o.is_allowed for o in staff_user.overrides}
    session.execute(delete(UserPermissionOverride).where(UserPermissionOverride.staff_user_id == staff_user.id))
    after: dict[str, bool] = {}
    for grant in grants:
        redundant = grant.get("subject_id") is None and (grant["permission_key"] in from_role) == grant["is_allowed"]
        if not redundant:
            session.add(UserPermissionOverride(staff_user_id=staff_user.id, **grant))
            after[grant["permission_key"]] = grant["is_allowed"]
    audit.record(
        session, "platform.staff_user.override_permissions", staff_user, changes={"overrides": [before, after]}
    )
    return _permissions_view(session, _refresh(session, staff_user))


def reset_permissions(session: Session, principal: Principal, staff_user_id: UUID) -> dict:
    """Reset to role: delete every override."""
    staff_user = get_staff_user(
        session, principal, staff_user_id, permission="platform.staff_user.override_permissions"
    )
    _check_not_self(principal, staff_user)
    if staff_user.overrides:
        before = {o.permission_key: o.is_allowed for o in staff_user.overrides}
        session.execute(delete(UserPermissionOverride).where(UserPermissionOverride.staff_user_id == staff_user.id))
        audit.record(
            session,
            "platform.staff_user.override_permissions",
            staff_user,
            changes={"overrides": [before, {}]},
            reason="reset",
        )
    return _permissions_view(session, _refresh(session, staff_user))


# --- roles -------------------------------------------------------------------------------------------------


def ensure_system_roles(session: Session) -> dict[str, Role]:
    """Idempotent: one locked row per system role, for the foreign key. Their grants live in code."""
    from app.core.auth.permissions import SYSTEM_ROLES

    existing = {r.system_key: r for r in session.scalars(select(Role).where(Role.is_system))}
    for key, (_column, name) in SYSTEM_ROLES.items():
        if key not in existing:
            existing[key] = Role(name=name, is_system=True, system_key=key)
            session.add(existing[key])
    session.flush()
    return existing


def list_roles(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "platform.role.read")
    page = paginate(
        session, select(Role), query, id_column=Role.id,
        sort_fields={"name": Role.name, "created_at": Role.created_at}, default_sort="name",
        filter_fields={"is_system": Role.is_system},
    )  # fmt: skip
    counts = dict(session.execute(select(StaffUser.role_id, func.count()).group_by(StaffUser.role_id)).all())
    page["data"] = [_role_view(session, role, counts.get(role.id, 0), with_permissions=False) for role in page["data"]]
    return page


def _role_view(
    session: Session, role: Role, staff_user_count: int | None = None, *, with_permissions: bool = True
) -> dict:
    if staff_user_count is None:
        staff_user_count = session.scalar(
            select(func.count()).select_from(StaffUser).where(StaffUser.role_id == role.id)
        )
    view = {c.key: getattr(role, c.key) for c in Role.__table__.columns} | {"staff_user_count": staff_user_count}
    if with_permissions:
        grants = rbac.role_grants(session, role)
        view["permissions"] = [{"permission_key": key, "is_allowed": True} for key in sorted(grants)]
    return view


def get_role(session: Session, principal: Principal, role_id: UUID) -> dict:
    authorize(principal, "platform.role.read")
    return _role_view(session, _load_role(session, role_id))


def _set_role_permissions(session: Session, role: Role, keys: Iterable[str]) -> None:
    session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for key in sorted(set(keys)):
        session.add(RolePermission(role_id=role.id, permission_key=key))


def create_role(session: Session, principal: Principal, data: dict) -> dict:
    """Create a custom role, blank or cloned. A clone copies the source's resolved grants once; no link is kept."""
    authorize(principal, "platform.role.manage")
    role = Role(
        name=data["name"], description=data.get("description"), default_ip_policy=data.get("default_ip_policy", "any")
    )
    keys: list[str] = []
    if source_id := data.get("clone_from_role_id"):
        source = _load_role(session, source_id, pointer="/clone_from_role_id")
        keys = [key for key in rbac.role_grants(session, source) if not CATALOGUE[key].is_owner_only]
        _check_grantable(principal, keys)
        role.cloned_from_role_id = source.id
    session.add(role)
    session.flush()
    _set_role_permissions(session, role, keys)
    audit.record(session, "platform.role.create", role, changes={"permissions": [[], sorted(keys)]})
    session.flush()
    return _role_view(session, role)


def _load_custom_role(session: Session, principal: Principal, role_id: UUID) -> Role:
    authorize(principal, "platform.role.manage")
    role = _load_role(session, role_id)
    if role.is_system:
        raise Conflict("System roles cannot be changed. Clone the role instead.", code="system-role-immutable")
    return role


def update_role(session: Session, principal: Principal, role_id: UUID, data: dict) -> dict:
    role = _load_custom_role(session, principal, role_id)
    for field, value in data.items():
        setattr(role, field, value)
    audit.record(session, "platform.role.update", role, changes=audit.diff(role))
    session.flush()
    return _role_view(session, role)


def replace_role_permissions(session: Session, principal: Principal, role_id: UUID, grants: list[dict]) -> dict:
    """Replace the role's whole grant set (PLT-04). Roles hold no deny rows: absence is denial."""
    role = _load_custom_role(session, principal, role_id)
    keys = [g["permission_key"] for g in grants if g["is_allowed"]]
    _check_grantable(principal, keys)
    before = sorted(rbac.role_grants(session, role))
    _set_role_permissions(session, role, keys)
    audit.record(
        session, "platform.role.update_permissions", role, changes={"permissions": [before, sorted(set(keys))]}
    )
    session.flush()
    return _role_view(session, role)


def delete_role(session: Session, principal: Principal, role_id: UUID) -> None:
    role = _load_custom_role(session, principal, role_id)
    if session.scalar(select(func.count()).select_from(StaffUser).where(StaffUser.role_id == role.id)):
        raise Conflict("Reassign this role's users before deleting it.", code="role-in-use")
    audit.record(session, "platform.role.delete", role, changes={"name": True})
    session.execute(update(Role).where(Role.cloned_from_role_id == role.id).values(cloned_from_role_id=None))
    session.delete(role)
    session.flush()


# --- internal: the cross-context interface =================================================================


def principal_for(session: Session, staff_user_id: UUID) -> Principal | None:
    """A staff user's principal as of now, or None when they may not act (deactivated, expired, identity
    disabled). Integrations bounds API keys and webhook subscriptions by their creator through it (ADR 0012)."""
    staff_user = session.get(StaffUser, staff_user_id)
    if staff_user is None or staff_user.identity.status != "active":
        return None
    return auth._principal_for(session, staff_user.identity)
