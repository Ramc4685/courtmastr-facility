"""resources service: schedule groups, the resource tree, standing links and availability windows.

Staff commands take a principal and authorize it; the functions under "internal" are what scheduling calls.
Hold rows belong to scheduling (L2), which this context may not import, so tree edits and archiving run the
callables scheduling registers in HOOKS, in the caller's transaction (ADR 0004 section 3).
"""

from collections.abc import Callable, Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import platform
from app.modules.resources.events import ResourceArchived, ResourceCreated, ResourceTreeChanged
from app.modules.resources.models import AvailabilityWindow, Resource, ResourceGroup, ResourceLink

MANAGE = "resources.resource.manage"
WINDOWS = "resources.availability.manage"
MAX_DEPTH = 3  # ADR 0004 section 3: bounds hold fan-out
# "tree_changed": fn(session, resource) after a node gains or changes its parent;
# "archiving": fn(session, resource) raises Conflict when the node still has future holds.
HOOKS: dict[str, list[Callable]] = {"tree_changed": [], "archiving": []}


def _location(session: Session, principal: Principal, location_id: UUID, pointer: str = "/location_id"):
    try:
        return platform.service.get_location(session, principal, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer=pointer) from None


def _scoped(session: Session, principal: Principal, model, row_id: UUID):
    """Load a location-owned row; missing or outside the caller's locations is 404."""
    row = session.get(model, row_id)
    in_scope = principal.kind == "system" or principal.location_ids is None
    if row is None or not (in_scope or row.location_id in principal.location_ids):
        raise NotFound()
    return row


# --- schedule groups ---------------------------------------------------------------------------------------


def list_groups(session: Session, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, scope_query(select(ResourceGroup), principal, ResourceGroup.location_id), query,
        id_column=ResourceGroup.id, sort_fields={"sort_order": ResourceGroup.sort_order, "name": ResourceGroup.name},
        default_sort="sort_order,name",
        filter_fields={"location_id": ResourceGroup.location_id, "is_active": ResourceGroup.is_active},
    )  # fmt: skip


def create_group(session: Session, principal: Principal, data: dict) -> ResourceGroup:
    _location(session, principal, data["location_id"])
    authorize(principal, MANAGE, location_id=data["location_id"])
    group = ResourceGroup(**data)
    session.add(group)
    session.flush()
    audit.record(session, MANAGE, group, location_id=group.location_id, changes={"name": True})
    return group


def update_group(session: Session, principal: Principal, group_id: UUID, data: dict) -> ResourceGroup:
    group = _scoped(session, principal, ResourceGroup, group_id)
    authorize(principal, MANAGE, location_id=group.location_id)
    if data.get("is_active") is False and session.scalar(
        select(func.count()).where(Resource.resource_group_id == group.id, Resource.status == "active")
    ):
        raise Conflict("Move or archive the group's resources first.", code="resource-group-in-use")
    for key, value in data.items():
        setattr(group, key, value)
    audit.record(session, MANAGE, group, location_id=group.location_id, changes=audit.diff(group))
    session.flush()
    return group


# --- resources ---------------------------------------------------------------------------------------------


def list_resources(session: Session, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, scope_query(select(Resource), principal, Resource.location_id), query, id_column=Resource.id,
        sort_fields={"sort_order": Resource.sort_order, "name": Resource.name}, default_sort="sort_order,name",
        filter_fields={
            "location_id": Resource.location_id, "resource_group_id": Resource.resource_group_id,
            "kind": Resource.kind, "status": Resource.status, "parent_id": Resource.parent_id,
            "is_online_bookable": Resource.is_online_bookable,
        },
        search=(Resource.name, Resource.public_name),
    )  # fmt: skip


def get_resource(session: Session, principal: Principal, resource_id: UUID) -> dict:
    resource = _scoped(session, principal, Resource, resource_id)
    return _detail(session, resource)


def _detail(session: Session, resource: Resource) -> dict:
    columns = {c.key: getattr(resource, c.key) for c in Resource.__table__.columns}
    return columns | {"linked_resource_ids": linked_ids(session, [resource.id])}


def _depth(session: Session, resource_id: UUID | None) -> int:
    """Number of nodes from the root down to this one (0 for None)."""
    depth = 0
    while resource_id is not None:
        depth, resource_id = depth + 1, session.scalar(select(Resource.parent_id).where(Resource.id == resource_id))
    return depth


def _height(session: Session, resource_id: UUID) -> int:
    children = descendants(session, [resource_id])[resource_id]
    return (
        1
        + max((_depth(session, child) for child in children), default=_depth(session, resource_id))
        - _depth(session, resource_id)
    )


def _check_parent(session: Session, resource: Resource, parent_id: UUID | None, height: int = 1) -> None:
    if parent_id is None:
        return
    parent = session.get(Resource, parent_id)
    if parent is None or parent.location_id != resource.location_id or parent.status != "active":
        raise ValidationFailed("Unknown parent resource at this location.", pointer="/parent_id")
    if resource.kind != "venue" or parent.kind != "venue":
        raise ValidationFailed("Only venues form a tree.", pointer="/parent_id")
    if resource.id is not None and (
        parent_id == resource.id or parent_id in descendants(session, [resource.id])[resource.id]
    ):
        raise ValidationFailed("A resource cannot sit under itself.", pointer="/parent_id", code="resource-cycle")
    if _depth(session, parent_id) + height > MAX_DEPTH:
        raise ValidationFailed(
            f"The tree is at most {MAX_DEPTH} levels deep.", pointer="/parent_id", code="tree-too-deep"
        )


def _check_group(session: Session, resource: Resource, group_id: UUID) -> None:
    group = session.get(ResourceGroup, group_id)
    if group is None or group.location_id != resource.location_id or not group.is_active:
        raise ValidationFailed("Unknown schedule group at this location.", pointer="/resource_group_id")


def create_resource(session: Session, principal: Principal, data: dict) -> dict:
    _location(session, principal, data["location_id"])
    authorize(principal, MANAGE, location_id=data["location_id"])
    staff_user_id = data.pop("staff_user_id", None)
    if data.get("counts_toward_plan") is None:  # a court split into halves is one metered resource
        data["counts_toward_plan"] = data.get("parent_id") is None and data["kind"] != "virtual_room"
    if (data["kind"] == "virtual_room") != (data.get("external_ref") is not None):
        raise ValidationFailed("external_ref is required for, and only for, a virtual room.", pointer="/external_ref")
    if staff_user_id and data["kind"] != "trainer":
        raise ValidationFailed("Only a trainer resource is linked to a staff user.", pointer="/staff_user_id")
    resource = Resource(**data)
    _check_group(session, resource, data["resource_group_id"])
    _check_parent(session, resource, data.get("parent_id"))
    session.add(resource)
    session.flush()
    if staff_user_id:
        platform.service.set_linked_resource(session, staff_user_id, resource.id)
    audit.record(
        session, MANAGE, resource, location_id=resource.location_id,
        changes={"kind": [None, resource.kind], "parent_id": [None, str(resource.parent_id or "") or None]},
    )  # fmt: skip
    events.publish(session, ResourceCreated(resource_id=resource.id, location_id=resource.location_id), resource.id)
    if resource.parent_id:
        _tree_changed(session, resource)
    return _detail(session, resource)


def _tree_changed(session: Session, resource: Resource) -> None:
    for hook in HOOKS["tree_changed"]:
        hook(session, resource)
    events.publish(
        session,
        ResourceTreeChanged(resource_id=resource.id, location_id=resource.location_id, parent_id=resource.parent_id),
        resource.id,
    )


def update_resource(session: Session, principal: Principal, resource_id: UUID, data: dict) -> dict:
    resource = _scoped(session, principal, Resource, resource_id)
    authorize(principal, MANAGE, location_id=resource.location_id)
    if resource.status != "active":
        raise Conflict("Restore the resource before editing it.")
    reparented = "parent_id" in data and data["parent_id"] != resource.parent_id
    if reparented:
        _check_parent(session, resource, data["parent_id"], _height(session, resource.id))
    if data.get("resource_group_id"):
        _check_group(session, resource, data["resource_group_id"])
    for key, value in data.items():
        setattr(resource, key, value)
    audit.record(session, MANAGE, resource, location_id=resource.location_id, changes=audit.diff(resource))
    session.flush()
    if reparented:
        _tree_changed(session, resource)
    return _detail(session, resource)


def archive_resource(session: Session, principal: Principal, resource_id: UUID) -> dict:
    resource = _scoped(session, principal, Resource, resource_id)
    authorize(principal, MANAGE, location_id=resource.location_id)
    if resource.status == "archived":
        return _detail(session, resource)
    if session.scalar(select(func.count()).where(Resource.parent_id == resource.id, Resource.status == "active")):
        raise Conflict("Archive the sub-resources first.", code="resource-has-children")
    for hook in HOOKS["archiving"]:
        hook(session, resource)
    resource.status = "archived"
    audit.record(session, MANAGE, resource, location_id=resource.location_id, changes=audit.diff(resource))
    events.publish(session, ResourceArchived(resource_id=resource.id, location_id=resource.location_id), resource.id)
    session.flush()
    return _detail(session, resource)


def restore_resource(session: Session, principal: Principal, resource_id: UUID) -> dict:
    resource = _scoped(session, principal, Resource, resource_id)
    authorize(principal, MANAGE, location_id=resource.location_id)
    if resource.status == "archived":
        if resource.parent_id and session.get(Resource, resource.parent_id).status != "active":
            raise Conflict("Restore the parent resource first.")
        resource.status = "active"
        audit.record(session, MANAGE, resource, location_id=resource.location_id, changes=audit.diff(resource))
        session.flush()  # uq_resource_name answers a name taken meanwhile with already-exists
        if resource.parent_id:
            _tree_changed(session, resource)
    return _detail(session, resource)


def replace_links(session: Session, principal: Principal, resource_id: UUID, to_ids: list[UUID]) -> dict:
    resource = _scoped(session, principal, Resource, resource_id)
    authorize(principal, MANAGE, location_id=resource.location_id)
    targets = {r.id: r for r in get_many(session, to_ids)}
    for index, to_id in enumerate(to_ids):
        target = targets.get(to_id)
        if (
            target is None
            or target.location_id != resource.location_id
            or target.status != "active"
            or to_id == resource.id
        ):
            raise ValidationFailed("Unknown resource at this location.", pointer=f"/to_resource_ids/{index}")
    current = set(linked_ids(session, [resource.id]))
    for link in session.scalars(select(ResourceLink).where(ResourceLink.from_resource_id == resource.id)):
        if link.to_resource_id not in to_ids:
            session.delete(link)
    for to_id in dict.fromkeys(to_ids):
        if to_id not in current:
            session.add(ResourceLink(from_resource_id=resource.id, to_resource_id=to_id))
    audit.record(session, MANAGE, resource, location_id=resource.location_id, changes={"links": True})
    session.flush()
    return _detail(session, resource)


# --- availability windows ----------------------------------------------------------------------------------


def _authorize_windows(session: Session, principal: Principal, resource: Resource) -> None:
    authorize(principal, WINDOWS, location_id=resource.location_id)
    own = principal.kind == "staff" and principal.permissions.get(WINDOWS) == "own"
    if own and platform.service.linked_resource_id(session, principal.staff_user_id) != resource.id:
        raise PermissionDenied("You can manage your own availability only.", required=WINDOWS)


def list_windows(session: Session, principal: Principal, resource_id: UUID) -> list[AvailabilityWindow]:
    resource = _scoped(session, principal, Resource, resource_id)
    return list(
        session.scalars(
            select(AvailabilityWindow)
            .where(AvailabilityWindow.resource_id == resource.id)
            .order_by(AvailabilityWindow.starts_on, AvailabilityWindow.start_time, AvailabilityWindow.id)
        )
    )


def create_window(session: Session, principal: Principal, resource_id: UUID, data: dict) -> AvailabilityWindow:
    resource = _scoped(session, principal, Resource, resource_id)
    _authorize_windows(session, principal, resource)
    window = AvailabilityWindow(**data, resource_id=resource.id, location_id=resource.location_id)
    session.add(window)
    session.flush()
    audit.record(
        session, WINDOWS, window, location_id=window.location_id, changes={"resource_id": [None, str(resource.id)]}
    )
    return window


def update_window(session: Session, principal: Principal, window_id: UUID, data: dict) -> AvailabilityWindow:
    window = _scoped(session, principal, AvailabilityWindow, window_id)
    _authorize_windows(session, principal, session.get(Resource, window.resource_id))
    for key, value in data.items():
        setattr(window, key, value)
    audit.record(session, WINDOWS, window, location_id=window.location_id, changes=audit.diff(window))
    session.flush()
    return window


def delete_window(session: Session, principal: Principal, window_id: UUID) -> None:
    window = _scoped(session, principal, AvailabilityWindow, window_id)
    _authorize_windows(session, principal, session.get(Resource, window.resource_id))
    audit.record(session, WINDOWS, window, location_id=window.location_id, changes={"deleted": True})
    session.delete(window)
    session.flush()


# --- internal: the cross-context interface -----------------------------------------------------------------


def get_many(session: Session, ids: Iterable[UUID]) -> list[Resource]:
    ids = list(ids)
    return list(session.scalars(select(Resource).where(Resource.id.in_(ids)))) if ids else []


def in_location(session: Session, location_id: UUID, *, group_id: UUID | None = None, ids=None) -> list[Resource]:
    """Active resources of a location in calendar-column order."""
    stmt = select(Resource).where(Resource.location_id == location_id, Resource.status == "active")
    if group_id:
        stmt = stmt.where(Resource.resource_group_id == group_id)
    if ids is not None:
        stmt = stmt.where(Resource.id.in_(list(ids)))
    return list(session.scalars(stmt.order_by(Resource.sort_order, Resource.name, Resource.id)))


def descendants(session: Session, ids: Iterable[UUID]) -> dict[UUID, list[UUID]]:
    """root id -> every active node below it. Trees are a handful of rows, at most MAX_DEPTH levels."""
    result: dict[UUID, list[UUID]] = {root: [] for root in ids}
    frontier = {root: root for root in result}  # node -> its root
    while frontier:
        rows = session.execute(
            select(Resource.id, Resource.parent_id).where(
                Resource.parent_id.in_(list(frontier)), Resource.status == "active"
            )
        ).all()
        frontier = {child: frontier[parent] for child, parent in rows}
        for child, root in frontier.items():
            result[root].append(child)
    return result


def ancestors(session: Session, resource_id: UUID) -> list[UUID]:
    found, parent = [], session.scalar(select(Resource.parent_id).where(Resource.id == resource_id))
    while parent is not None:
        found.append(parent)
        parent = session.scalar(select(Resource.parent_id).where(Resource.id == parent))
    return found


def linked_ids(session: Session, from_ids: Iterable[UUID]) -> list[UUID]:
    """Standing links (RES-05): the resources a booking of any of `from_ids` also holds by default."""
    return list(
        session.scalars(
            select(ResourceLink.to_resource_id)
            .where(ResourceLink.from_resource_id.in_(list(from_ids)))
            .order_by(ResourceLink.to_resource_id)
        )
    )


def windows_for(session: Session, resource_ids: Iterable[UUID]) -> dict[UUID, list[AvailabilityWindow]]:
    grouped: dict[UUID, list[AvailabilityWindow]] = {}
    rows = session.scalars(
        select(AvailabilityWindow).where(
            AvailabilityWindow.resource_id.in_(list(resource_ids)), AvailabilityWindow.is_active
        )
    )
    for row in rows:
        grouped.setdefault(row.resource_id, []).append(row)
    return grouped


def trainer_group(session: Session, location_id: UUID) -> UUID:
    """The schedule group a new trainer column joins when none is named: the first active group at the
    location, else a new "Trainers" group (staff creates trainer payees through this). Internal."""
    found = session.scalar(
        select(ResourceGroup.id)
        .where(ResourceGroup.location_id == location_id, ResourceGroup.is_active)
        .order_by(ResourceGroup.sort_order, ResourceGroup.name, ResourceGroup.id)
        .limit(1)
    )
    if found is None:
        group = ResourceGroup(location_id=location_id, name="Trainers")
        session.add(group)
        session.flush()
        audit.record(session, MANAGE, group, location_id=location_id, changes={"name": True})
        found = group.id
    return found
