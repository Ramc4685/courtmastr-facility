"""programs groups (build module 6): the registerable tree, its sessions and fees, online registration settings,
staff registration into a node, the group waitlist and the lifecycle (REG-01, REG-02, REG-05, REG-07, REG-09,
REG-10, CLS-10).

Capacity of a node counts its own enrolments and its descendants' (`enrolled_count`). Taking a place locks the
node and every ancestor root-first and increments each, so a league of 120 with teams of 12 enforces both; the
CHECK constraints are the guard and answer `capacity-full`. A participant of a node also takes a seat in every
session linked to it or to an ancestor, so a drop-in booking and a registrant share one session counter.
"""

import re
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, platform, scheduling
from app.modules.programs import events as ev
from app.modules.programs.models import (
    Enrollment,
    ProgramFee,
    ProgramGroup,
    ProgramSession,
    RegistrationConfig,
    WaitlistEntry,
)
from app.ports import notifications

READ, MANAGE, DELETE, CONFIG = (
    "programs.registration.read",
    "programs.program.manage",
    "programs.program.delete",
    "programs.registration_config.manage",
)
ENROLL, CANCEL, WAITLIST = "programs.registration.create", "programs.registration.cancel", "programs.waitlist.manage"
REVERSE = "billing.charge.reverse"
LIVE = ("pending", "enrolled")
MAX_DEPTH = 5
CONSTRAINT_CODES.update({
    "ck_program_group_capacity": "capacity-full",
    "ck_program_group_children": "max-children-reached",
    "uq_enrollment_group_client": "already-enrolled",
    "uq_waitlist_entry_group_client": "already-waitlisted",
    "uq_program_session_session": "session-already-linked",
    "uq_registration_config_public_slug": "slug-taken",
})  # fmt: skip
notifications.register_template(
    "programs.group_waitlist_promoted",
    subject="You are registered: $title",
    body="Good news, $first_name. A place opened up in $title and you are now registered.",
)

_GROUP_FIELDS = (
    "kind", "name", "description", "child_label", "revenue_category_id", "capacity", "max_children", "price_minor",
    "contact_name", "contact_email", "starts_on", "ends_on", "auto_archive_on", "waitlist_mode",
)  # fmt: skip


# --- loading and reach --------------------------------------------------------------------------------------


def _row(session: Db, group_id: UUID, *, deleted: bool = False, lock: bool = False) -> ProgramGroup:
    stmt = select(ProgramGroup).where(ProgramGroup.id == group_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(stmt)
    if row is None or (row.deleted_at is not None) != deleted:
        raise NotFound()
    return row


def _own_sessions(session: Db, principal: Principal):
    """The session ids on the coach's own calendar (a SELECT), or None when the caller is not `own`-limited."""
    mine = platform.service.linked_resource_id(session, principal.staff_user_id)
    return scheduling.service.sessions_with_resource(mine, select(ProgramSession.session_id)) if mine else None


def _own_reach(principal: Principal, key: str) -> bool:
    return principal.kind == "staff" and principal.permissions.get(key) == "own"


def _reaches(session: Db, principal: Principal, group: ProgramGroup, key: str) -> bool:
    """`own` reach (coach): the node, an ancestor or a descendant has a session on the coach's calendar."""
    if not _own_reach(principal, key):
        return True
    sessions = _own_sessions(session, principal)
    if sessions is None:
        return False
    ids = [g.id for g in _chain(session, group)] + _subtree_ids(session, group.id)
    stmt = select(func.count()).where(ProgramSession.program_group_id.in_(ids), ProgramSession.session_id.in_(sessions))
    return bool(session.scalar(stmt))


def reached_groups(session: Db, principal: Principal):
    """A SELECT of the group ids with a session on the coach's own calendar (empty without one)."""
    sessions = _own_sessions(session, principal)
    reached = select(ProgramSession.program_group_id)
    return reached.where(ProgramSession.session_id.in_(sessions)) if sessions is not None else reached.where(False)


def load(session: Db, principal: Principal, group_id: UUID, key: str, *, deleted: bool = False, lock: bool = False):
    """The group the caller may act on with `key`: missing, deleted or out of location scope is 404."""
    group = _row(session, group_id, deleted=deleted, lock=lock)
    authorize(principal, key, location_id=group.location_id)
    if not _reaches(session, principal, group, key):
        raise NotFound()
    return group


def _chain(session: Db, group: ProgramGroup, *, lock: bool = False) -> list[ProgramGroup]:
    """The node and its ancestors, root first; locked FOR UPDATE in that order when asked (one lock order)."""
    ids, current = [], group
    while current is not None:
        ids.append(current.id)
        current = session.get(ProgramGroup, current.parent_id) if current.parent_id else None
    stmt = select(ProgramGroup).where(ProgramGroup.id.in_(ids)).order_by(ProgramGroup.depth)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return list(session.scalars(stmt))


def _subtree_ids(session: Db, root_id: UUID, *, include_deleted: bool = False) -> list[UUID]:
    """Every descendant of a node (not the node itself); the tree is at most five levels deep."""
    found, frontier = [], [root_id]
    while frontier:
        stmt = select(ProgramGroup.id).where(ProgramGroup.parent_id.in_(frontier))
        if not include_deleted:
            stmt = stmt.where(ProgramGroup.deleted_at.is_(None))
        frontier = list(session.scalars(stmt))
        found += frontier
    return found


def _linked_sessions(session: Db, group_ids: list[UUID]) -> list[UUID]:
    return list(
        session.scalars(
            select(ProgramSession.session_id)
            .where(ProgramSession.program_group_id.in_(group_ids))
            .order_by(ProgramSession.session_id)
        )
    )


def _live_count(session: Db, group_ids: list[UUID]) -> int:
    return session.scalar(
        select(func.count()).where(Enrollment.program_group_id.in_(group_ids), Enrollment.status.in_(LIVE))
    )


# --- places -------------------------------------------------------------------------------------------------


def _take_place(session: Db, group: ProgramGroup) -> None:
    """One place in the node, its ancestors and every session linked along the chain, or 409 capacity-full."""
    chain = _chain(session, group, lock=True)
    for node in chain:
        if node.status != "active" or node.deleted_at is not None:
            raise Conflict("This program is not open for registration.", code="program-not-active")
        if node.capacity is not None and node.enrolled_count >= node.capacity:
            raise Conflict(f"{node.name} is full.", code="capacity-full", program_group_id=str(node.id))
    for node in chain:
        node.enrolled_count += 1
    for session_id in _linked_sessions(session, [node.id for node in chain]):
        scheduling.service.reserve_seat(session, session_id)
    session.flush()


def _release_place(session: Db, group: ProgramGroup) -> None:
    chain = _chain(session, group, lock=True)
    for node in chain:
        node.enrolled_count = max(node.enrolled_count - 1, 0)
    for session_id in _linked_sessions(session, [node.id for node in chain]):
        scheduling.service.release_seat(session, session_id)
    session.flush()


def has_space(session: Db, group: ProgramGroup) -> bool:
    return all(n.capacity is None or n.enrolled_count < n.capacity for n in _chain(session, group))


def spots_left(session: Db, group: ProgramGroup) -> int | None:
    left = [n.capacity - n.enrolled_count for n in _chain(session, group) if n.capacity is not None]
    return max(min(left), 0) if left else None


# --- groups -------------------------------------------------------------------------------------------------


def _check_span(data: dict) -> None:
    if data.get("starts_on") and data.get("ends_on") and data["ends_on"] < data["starts_on"]:
        raise ValidationFailed("The end date is before the start date.", pointer="/ends_on")


def create_group(session: Db, principal: Principal, data: dict) -> ProgramGroup:
    """A program, or a subgroup under `parent_id` (REG-01, REG-02). A subgroup lives at its parent's location
    and copies the parent's revenue category when it names none."""
    _check_span(data)
    values = {k: data.get(k) for k in _GROUP_FIELDS if data.get(k) is not None}
    if data.get("parent_id"):
        parent = load(session, principal, data["parent_id"], MANAGE, lock=True)
        if parent.status != "active":
            raise Conflict("Subgroups can be added to active programs only.", code="program-not-active")
        if parent.depth + 1 > MAX_DEPTH:
            raise ValidationFailed("Programs nest at most six levels deep.", pointer="/parent_id")
        values |= {"location_id": parent.location_id, "parent_id": parent.id, "depth": parent.depth + 1}
        values.setdefault("revenue_category_id", parent.revenue_category_id)
        parent.child_count += 1
    else:
        if data.get("location_id") is None:
            raise ValidationFailed("Choose a location.", pointer="/location_id")
        authorize(principal, MANAGE, location_id=data["location_id"])
        values |= {"location_id": data["location_id"], "depth": 0}
    row = ProgramGroup(**values)
    session.add(row)
    session.flush()  # ck_program_group_children on the parent, uq_program_group_sibling_name
    audit.record(session, MANAGE, row, location_id=row.location_id, changes=audit.diff(row))
    return row


def update_group(session: Db, principal: Principal, group_id: UUID, data: dict) -> ProgramGroup:
    row = load(session, principal, group_id, MANAGE, lock=True)
    _check_span({"starts_on": row.starts_on, "ends_on": row.ends_on} | data)
    if data.get("capacity") is not None and data["capacity"] < row.enrolled_count:
        raise Conflict("Capacity cannot go below the number registered.", code="capacity-below-enrolled")
    if data.get("max_children") is not None and data["max_children"] < row.child_count:
        raise Conflict("The subgroup limit is below the subgroups that exist.", code="max-children-below-count")
    for key in _GROUP_FIELDS:
        if key in data:
            if key in ("name", "kind", "child_label") and data[key] is None:
                raise ValidationFailed("This field cannot be empty.", pointer=f"/{key}")
            setattr(row, key, data[key])
    changes = audit.diff(row)
    session.flush()
    if changes:
        audit.record(session, MANAGE, row, location_id=row.location_id, changes=changes)
    return row


def group_view(session: Db, row: ProgramGroup) -> dict:
    return {c.key: getattr(row, c.key) for c in ProgramGroup.__table__.columns if c.key != "tenant_id"} | {
        "spots_left": spots_left(session, row),
        "waiting_count": session.scalar(
            select(func.count()).where(WaitlistEntry.program_group_id == row.id, WaitlistEntry.status == "waiting")
        ),
    }


def get_group(session: Db, principal: Principal, group_id: UUID) -> dict:
    return group_view(session, load(session, principal, group_id, READ))


def list_groups(session: Db, principal: Principal, query: ListQuery) -> dict:
    """Roots by default; `parent_id` lists one node's children; `deleted=true` lists the deleted."""
    authorize(principal, READ)
    g = ProgramGroup
    filters = dict(query.filters)
    deleted = str(filters.pop("deleted", "")).lower() == "true"
    stmt = select(g).where(g.deleted_at.is_not(None) if deleted else g.deleted_at.is_(None))
    if "parent_id" not in filters and not deleted:
        stmt = stmt.where(g.parent_id.is_(None))
    if _own_reach(principal, READ):
        stmt = stmt.where(g.id.in_(reached_groups(session, principal)))
    query = ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters)
    page = paginate(
        session, scope_query(stmt, principal, g.location_id), query, id_column=g.id,
        sort_fields={"name": g.name, "starts_on": g.starts_on, "created_at": g.created_at}, default_sort="name",
        filter_fields={"location_id": g.location_id, "status": g.status, "kind": g.kind, "parent_id": g.parent_id},
        search=(g.name,),
    )  # fmt: skip
    return page | {"data": [group_view(session, row) for row in page["data"]]}


def get_tree(session: Db, principal: Principal, group_id: UUID) -> dict:
    """The node with every live descendant nested under `children` (REG-02)."""
    root = load(session, principal, group_id, READ)
    ids = _subtree_ids(session, root.id)
    rows = list(session.scalars(select(ProgramGroup).where(ProgramGroup.id.in_(ids)).order_by(ProgramGroup.name)))
    views = {row.id: group_view(session, row) | {"children": []} for row in [root, *rows]}
    for row in rows:
        views[row.parent_id]["children"].append(views[row.id])
    return views[root.id]


def _set_status(session: Db, principal: Principal, group_id: UUID, to: str, allowed: tuple[str, ...]) -> ProgramGroup:
    row = load(session, principal, group_id, MANAGE, lock=True)
    if row.status == to:
        return row
    if row.status not in allowed:
        raise Conflict(f"A {row.status} program cannot become {to}.", code="invalid-transition")
    was, row.status = row.status, to
    row.completed_at = None if to == "active" else row.completed_at or clock.now()
    audit.record(session, MANAGE, row, location_id=row.location_id, changes={"status": [was, to]})
    if to == "completed":
        events.publish(session, ev.GroupCompleted(program_group_id=row.id, location_id=row.location_id), row.id)
    session.flush()
    return row


def complete_group(session: Db, principal: Principal, group_id: UUID) -> ProgramGroup:
    """REG-05: no new registrations; the roster stays."""
    return _set_status(session, principal, group_id, "completed", ("active",))


def archive_group(session: Db, principal: Principal, group_id: UUID) -> ProgramGroup:
    return _set_status(session, principal, group_id, "archived", ("active", "completed"))


def reopen_group(session: Db, principal: Principal, group_id: UUID) -> ProgramGroup:
    return _set_status(session, principal, group_id, "active", ("completed", "archived"))


def delete_group(session: Db, principal: Principal, group_id: UUID) -> None:
    """Soft delete of a node and its subtree (REG-05). Refused while anyone is registered in it."""
    row = load(session, principal, group_id, DELETE, lock=True)
    ids = [row.id, *_subtree_ids(session, row.id)]
    if _live_count(session, ids):
        raise Conflict("Cancel or move the registrations first.", code="has-registrations")
    now = clock.now()
    for node in session.scalars(select(ProgramGroup).where(ProgramGroup.id.in_(ids))):
        node.deleted_at, node.deleted_by_staff_user_id = now, principal.staff_user_id
    for entry in session.scalars(
        select(WaitlistEntry).where(
            WaitlistEntry.program_group_id.in_(ids), WaitlistEntry.status.in_(("waiting", "offered"))
        )
    ):
        entry.status, entry.removed_reason = "expired", "program_deleted"
    if row.parent_id:
        _row(session, row.parent_id, lock=True).child_count -= 1
    audit.record(session, DELETE, row, location_id=row.location_id, changes={"deleted": [False, True]})
    session.flush()


def restore_group(session: Db, principal: Principal, group_id: UUID) -> ProgramGroup:
    """Undo a delete: the node and the descendants deleted with it come back."""
    row = load(session, principal, group_id, DELETE, deleted=True, lock=True)
    if row.parent_id:
        parent = session.get(ProgramGroup, row.parent_id)
        if parent.deleted_at is not None:
            raise Conflict("Restore the parent program first.", code="parent-deleted")
        parent.child_count += 1
    stamp = row.deleted_at
    for node in session.scalars(
        select(ProgramGroup).where(
            ProgramGroup.id.in_([row.id, *_subtree_ids(session, row.id, include_deleted=True)]),
            ProgramGroup.deleted_at == stamp,
        )
    ):
        node.deleted_at = node.deleted_by_staff_user_id = None
    session.flush()  # uq_program_group_sibling_name: a new sibling may have taken the name meanwhile
    audit.record(session, DELETE, row, location_id=row.location_id, changes={"deleted": [True, False]})
    return row


def auto_archive_due(session: Db) -> int:
    """Internal (hourly job, REG-05): archive active groups whose auto-archive date has come at their location."""
    done = 0
    g = ProgramGroup
    for row in session.scalars(
        select(g)
        .where(g.status == "active", g.auto_archive_on.is_not(None), g.deleted_at.is_(None))
        .with_for_update(skip_locked=True)
    ).all():
        if row.auto_archive_on <= platform.service.location_today(session, row.location_id):
            row.status, row.completed_at = "archived", row.completed_at or clock.now()
            audit.record(session, MANAGE, row, location_id=row.location_id, changes={"status": ["active", "archived"]})
            events.publish(session, ev.GroupCompleted(program_group_id=row.id, location_id=row.location_id), row.id)
            done += 1
    session.flush()
    return done


# --- sessions (CLS-10) --------------------------------------------------------------------------------------


def list_sessions(session: Db, principal: Principal, group_id: UUID) -> list[dict]:
    group = load(session, principal, group_id, READ)
    links = session.scalars(
        select(ProgramSession).where(ProgramSession.program_group_id == group.id).order_by(ProgramSession.sequence_no)
    ).all()
    return [{"sequence_no": ln.sequence_no} | scheduling.service.get_session(session, ln.session_id) for ln in links]


def add_sessions(session: Db, principal: Principal, group_id: UUID, session_ids: list[UUID]) -> list[dict]:
    """Link scheduling sessions to the node. Everyone registered in the node or below takes a seat in each new
    session at once: a session without room for them is 409 capacity-full and nothing is linked."""
    group = load(session, principal, group_id, MANAGE, lock=True)
    seated = _live_count(session, [group.id, *_subtree_ids(session, group.id)])
    last = session.scalar(
        select(func.coalesce(func.max(ProgramSession.sequence_no), 0)).where(
            ProgramSession.program_group_id == group.id
        )
    )
    for index, session_id in enumerate(dict.fromkeys(session_ids)):
        try:
            seat = scheduling.service.get_session(session, session_id)
        except NotFound:
            raise ValidationFailed("Unknown session.", pointer=f"/session_ids/{index}") from None
        if seat["location_id"] != group.location_id:
            raise ValidationFailed("The session is at another location.", pointer=f"/session_ids/{index}")
        last += 1
        session.add(ProgramSession(program_group_id=group.id, session_id=session_id, sequence_no=last))
        session.flush()  # uq_program_session_session
        if seated:
            scheduling.service.reserve_seat(session, session_id, seated)
    audit.record(session, MANAGE, group, location_id=group.location_id, changes={"session_count": [None, last]})
    return list_sessions(session, principal, group_id)


def remove_session(session: Db, principal: Principal, group_id: UUID, session_id: UUID) -> None:
    group = load(session, principal, group_id, MANAGE, lock=True)
    link = session.scalar(
        select(ProgramSession).where(
            ProgramSession.program_group_id == group.id, ProgramSession.session_id == session_id
        )
    )
    if link is None:
        raise NotFound()
    seated = _live_count(session, [group.id, *_subtree_ids(session, group.id)])
    if seated:
        scheduling.service.release_seat(session, session_id, seated)
    session.delete(link)
    audit.record(session, MANAGE, group, location_id=group.location_id, changes={"session_removed": [None, True]})
    session.flush()


# --- fees (REG-07, REG-10) ----------------------------------------------------------------------------------

_FEE_FIELDS = (
    "fee_kind", "description", "amount_minor", "deposit_minor", "revenue_category_id", "is_online", "is_active",
    "sort_order",
)  # fmt: skip


def _fee(session: Db, principal: Principal, fee_id: UUID, key: str) -> ProgramFee:
    fee = session.get(ProgramFee, fee_id)
    if fee is None:
        raise NotFound()
    if fee.program_group_id is not None:
        load(session, principal, fee.program_group_id, key)
    else:
        authorize(principal, key, location_id=fee.location_id)
    return fee


def _check_deposit(amount: int, deposit: int | None) -> None:
    if deposit is not None and deposit > amount:
        raise ValidationFailed("The deposit cannot exceed the fee.", pointer="/deposit_minor")


def create_fee(session: Db, principal: Principal, data: dict, group_id: UUID | None = None) -> ProgramFee:
    """A group's own fee, or (no group) a staff-only catalogue fee at a location."""
    values = {k: data[k] for k in _FEE_FIELDS if data.get(k) is not None}
    _check_deposit(values["amount_minor"], values.get("deposit_minor"))
    if group_id is not None:
        group = load(session, principal, group_id, MANAGE)
        values |= {"location_id": group.location_id, "program_group_id": group.id}
    else:
        if data.get("location_id") is None:
            raise ValidationFailed("Choose a location.", pointer="/location_id")
        authorize(principal, MANAGE, location_id=data["location_id"])
        values |= {"location_id": data["location_id"], "is_online": False}
    fee = ProgramFee(**values)
    session.add(fee)
    session.flush()
    audit.record(session, MANAGE, fee, location_id=fee.location_id, changes=audit.diff(fee))
    return fee


def list_group_fees(session: Db, principal: Principal, group_id: UUID) -> list[ProgramFee]:
    group = load(session, principal, group_id, READ)
    stmt = select(ProgramFee).where(ProgramFee.program_group_id == group.id)
    return list(session.scalars(stmt.order_by(ProgramFee.sort_order, ProgramFee.id)))


def list_catalogue_fees(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, READ)
    f = ProgramFee
    return paginate(
        session, scope_query(select(f).where(f.program_group_id.is_(None)), principal, f.location_id), query,
        id_column=f.id, sort_fields={"sort_order": f.sort_order, "description": f.description},
        default_sort="sort_order", filter_fields={"location_id": f.location_id, "is_active": f.is_active},
        search=(f.description,),
    )  # fmt: skip


def update_fee(session: Db, principal: Principal, fee_id: UUID, data: dict) -> ProgramFee:
    fee = _fee(session, principal, fee_id, MANAGE)
    for key in _FEE_FIELDS:
        if key in data:
            if data[key] is None and key not in ("deposit_minor", "revenue_category_id"):
                raise ValidationFailed("This field cannot be empty.", pointer=f"/{key}")
            setattr(fee, key, data[key])
    if fee.program_group_id is None:
        fee.is_online = False  # catalogue fees are staff-side only
    _check_deposit(fee.amount_minor, fee.deposit_minor)
    changes = audit.diff(fee)
    session.flush()
    if changes:
        audit.record(session, MANAGE, fee, location_id=fee.location_id, changes=changes)
    return fee


def delete_fee(session: Db, principal: Principal, fee_id: UUID) -> None:
    """A fee someone registered or queued under is retired (inactive) so their records keep it."""
    fee = _fee(session, principal, fee_id, MANAGE)
    used = session.scalar(select(func.count()).where(Enrollment.program_fee_id == fee.id)) or session.scalar(
        select(func.count()).where(WaitlistEntry.program_fee_id == fee.id)
    )
    audit.record(session, MANAGE, fee, location_id=fee.location_id, changes={"is_active": [fee.is_active, False]})
    if used:
        fee.is_active = False
    else:
        session.delete(fee)
    session.flush()


def active_fees(session: Db, group: ProgramGroup, *, online: bool = False) -> list[ProgramFee]:
    stmt = select(ProgramFee).where(ProgramFee.program_group_id == group.id, ProgramFee.is_active)
    if online:
        stmt = stmt.where(ProgramFee.is_online)
    return list(session.scalars(stmt.order_by(ProgramFee.sort_order, ProgramFee.id)))


def chosen_fees(
    session: Db, group: ProgramGroup, fee_ids: list[UUID], *, online: bool, pointer: str
) -> list[ProgramFee]:
    """The fees a registration charges: each the node's own (or, staff side, a catalogue fee of its location),
    active, and offered online when the registrant is online. A node with active fees needs at least one."""
    fees = []
    for index, fee_id in enumerate(dict.fromkeys(fee_ids)):
        fee = session.get(ProgramFee, fee_id)
        own = fee is not None and fee.program_group_id == group.id
        catalogue = fee is not None and fee.program_group_id is None and fee.location_id == group.location_id
        if (
            fee is None
            or not fee.is_active
            or not (own or (catalogue and not online))
            or (online and not fee.is_online)
        ):
            raise ValidationFailed("This fee does not apply to the program.", pointer=f"{pointer}/{index}")
        fees.append(fee)
    if not fees and active_fees(session, group, online=online):
        raise ValidationFailed("Choose the fee to register under.", pointer=pointer, code="fee-required")
    return fees


# --- registration config and publication (REG-10, SSP-17) ---------------------------------------------------

_CONFIG_FIELDS = (
    "is_enabled", "opens_on", "closes_on", "payment_requirement", "displays_openings", "online_description",
    "closed_message", "confirmation_message", "public_slug", "portal_publish_name",
)  # fmt: skip
_CONFIG_HIDDEN = ("id", "tenant_id", "created_at", "updated_at")
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")


def config_for(session: Db, group_id: UUID | None) -> RegistrationConfig | None:
    if group_id is None:
        return None
    return session.scalar(select(RegistrationConfig).where(RegistrationConfig.program_group_id == group_id))


def _config_view(group: ProgramGroup, config: RegistrationConfig | None) -> dict:
    if config is None:
        return {
            "program_group_id": group.id, "is_enabled": False, "opens_on": None, "closes_on": None,
            "payment_requirement": "immediate_card_payment", "displays_openings": False, "online_description": None,
            "closed_message": None, "confirmation_message": None, "public_slug": None, "is_portal_visible": False,
            "portal_publish_name": None, "portal_published_at": None,
        }  # fmt: skip
    return {c.key: getattr(config, c.key) for c in RegistrationConfig.__table__.columns if c.key not in _CONFIG_HIDDEN}


def get_config(session: Db, principal: Principal, group_id: UUID) -> dict:
    group = load(session, principal, group_id, READ)
    return _config_view(group, config_for(session, group.id))


def _default_slug(group: ProgramGroup) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", group.name.lower()).strip("-")[:60] or "program"
    return f"{base}-{str(group.id)[-6:]}"


def put_config(session: Db, principal: Principal, group_id: UUID, data: dict) -> dict:
    group = load(session, principal, group_id, CONFIG)
    if data.get("opens_on") and data.get("closes_on") and data["closes_on"] < data["opens_on"]:
        raise ValidationFailed("Registration closes before it opens.", pointer="/closes_on")
    if data.get("public_slug") is not None and not _SLUG.fullmatch(data["public_slug"]):
        raise ValidationFailed("Use lower-case letters, digits and dashes.", pointer="/public_slug")
    config = config_for(session, group.id)
    if config is None:
        config = RegistrationConfig(
            program_group_id=group.id, public_slug=data.get("public_slug") or _default_slug(group)
        )
        session.add(config)
    for key in _CONFIG_FIELDS:
        if key in data and not (
            key in ("public_slug", "payment_requirement", "is_enabled", "displays_openings") and data[key] is None
        ):
            setattr(config, key, data[key])
    changes = audit.diff(config)
    session.flush()  # uq_registration_config_public_slug
    audit.record(session, CONFIG, config, location_id=group.location_id, changes=changes)
    return _config_view(group, config)


def set_published(session: Db, principal: Principal, group_id: UUID, visible: bool) -> dict:
    group = load(session, principal, group_id, CONFIG)
    config = config_for(session, group.id)
    if visible and (config is None or not config.is_enabled):
        raise Conflict("Turn on online registration before publishing.", code="registration-disabled")
    if config is not None and config.is_portal_visible != visible:
        config.is_portal_visible = visible
        config.portal_published_at = clock.now() if visible else None
        audit.record(
            session,
            CONFIG,
            config,
            location_id=group.location_id,
            changes={"is_portal_visible": [not visible, visible]},
        )
        session.flush()
    return _config_view(group, config)


def waitlist_mode(session: Db, group: ProgramGroup) -> str:
    """The node's own setting, else the nearest ancestor's, else manual (REG-11 location defaults not built)."""
    for node in reversed(_chain(session, group)):
        if node.waitlist_mode:
            return node.waitlist_mode
    return "manual"


def registration_state(session: Db, group: ProgramGroup, config: RegistrationConfig | None) -> str:
    """open, not_yet_open, closed, full_waitlist or full: what an online registrant meets today (REG-10)."""
    if group.status != "active" or group.deleted_at is not None or config is None or not config.is_enabled:
        return "closed"
    if not active_fees(session, group, online=True):
        return "closed"
    today = platform.service.location_today(session, group.location_id)
    if config.opens_on and today < config.opens_on:
        return "not_yet_open"
    if config.closes_on and today > config.closes_on:
        return "closed"
    if not has_space(session, group):
        return "full" if waitlist_mode(session, group) == "disabled" else "full_waitlist"
    return "open"


def _public_view(session: Db, group: ProgramGroup, config: RegistrationConfig, *, children: bool) -> dict:
    view = {
        "id": group.id, "location_id": group.location_id, "name": config.portal_publish_name or group.name,
        "description": config.online_description, "starts_on": group.starts_on, "ends_on": group.ends_on,
        "spots_left": spots_left(session, group) if config.displays_openings else None,
        "registration_state": registration_state(session, group, config),
        "payment_requirement": config.payment_requirement, "confirmation_message": config.confirmation_message,
        "closed_message": config.closed_message,
        "fees": [
            {"id": f.id, "fee_kind": f.fee_kind, "description": f.description, "amount_minor": f.amount_minor}
            for f in active_fees(session, group, online=True)
        ],
        "children": [],
    }  # fmt: skip
    if children:
        for child in session.scalars(
            select(ProgramGroup)
            .where(ProgramGroup.parent_id == group.id, ProgramGroup.deleted_at.is_(None))
            .order_by(ProgramGroup.name)
        ):
            child_config = config_for(session, child.id)
            if child_config is not None and child_config.is_enabled:
                view["children"].append(_public_view(session, child, child_config, children=False))
    return view


def _published():
    return (
        select(ProgramGroup, RegistrationConfig)
        .join(RegistrationConfig, RegistrationConfig.program_group_id == ProgramGroup.id)
        .where(
            RegistrationConfig.is_portal_visible, RegistrationConfig.is_enabled, ProgramGroup.deleted_at.is_(None),
            ProgramGroup.status == "active",
        )
    )  # fmt: skip


def public_list(session: Db, location_id: UUID | None = None) -> list[dict]:
    """Published programs for registrants (SSP-17): anonymous, no staff fields. Capped at 200."""
    stmt = _published().order_by(ProgramGroup.starts_on.nulls_last(), ProgramGroup.name).limit(200)
    if location_id is not None:
        stmt = stmt.where(ProgramGroup.location_id == location_id)
    return [_public_view(session, group, config, children=False) for group, config in session.execute(stmt)]


def public_get(session: Db, group_id: UUID) -> dict:
    found = session.execute(_published().where(ProgramGroup.id == group_id)).first()
    if found is None:
        raise NotFound()
    return _public_view(session, found[0], found[1], children=True)


def published_group(session: Db, group_id: UUID) -> tuple[ProgramGroup, RegistrationConfig]:
    """A node registrants may reach online: published itself, or an enabled child of a published node; else 404."""
    group = session.get(ProgramGroup, group_id)
    if group is None or group.deleted_at is not None:
        raise NotFound()
    config, parent = config_for(session, group_id), config_for(session, group.parent_id)
    if config is None or not config.is_enabled:
        raise NotFound()
    if not (config.is_portal_visible or (parent is not None and parent.is_enabled and parent.is_portal_visible)):
        raise NotFound()
    return group, config


# --- registration into a node (REG-07, CLS-10) --------------------------------------------------------------


def enroll(
    session: Db, group: ProgramGroup, client_id: UUID, *, channel: str, fees: list[ProgramFee],
    payer_client_id: UUID | None = None, status: str = "enrolled", checkout_id: UUID | None = None,
    hold_minutes: int = 15, comment: str | None = None,
) -> Enrollment:  # fmt: skip
    """Internal: take the place (409 capacity-full, program-not-active), then the roster row (409
    already-enrolled). A `pending` row is a checkout hold; charges are raised by `bill`."""
    _take_place(session, group)
    fee, now = (fees[0] if fees else None), clock.now()
    row = Enrollment(
        location_id=group.location_id, client_id=client_id, target_kind="group", program_group_id=group.id,
        status=status, pricing="fee" if any(f.amount_minor for f in fees) else "free",
        program_fee_id=fee.id if fee else None,
        revenue_category_id=(fee.revenue_category_id if fee else None) or group.revenue_category_id,
        payer_client_id=payer_client_id if payer_client_id != client_id else None, channel=channel,
        checkout_id=checkout_id, registrant_comment=comment, enrolled_at=now if status == "enrolled" else None,
        hold_expires_at=now + timedelta(minutes=hold_minutes) if status == "pending" else None,
    )  # fmt: skip
    session.add(row)
    session.flush()  # uq_enrollment_group_client
    if status == "enrolled":
        _created(session, row)
    return row


def _created(session: Db, row: Enrollment) -> None:
    event = ev.GroupEnrollmentCreated(
        enrollment_id=row.id, program_group_id=row.program_group_id, client_id=row.client_id,
        location_id=row.location_id,
    )  # fmt: skip
    events.publish(session, event, row.id)


def confirm_pending(session: Db, row: Enrollment) -> None:
    """Internal (checkout confirm): a held place becomes a registration."""
    row.status, row.enrolled_at, row.hold_expires_at = "enrolled", clock.now(), None
    session.flush()
    _created(session, row)


def bill(session: Db, row: Enrollment, fees: list[ProgramFee]) -> list[UUID]:
    """Internal: one charge per non-zero fee for the participant, sourced to the enrolment. Returns charge ids."""
    ids = []
    for line, fee in enumerate(f for f in fees if f.amount_minor > 0):
        charge = billing.service.post_charge(
            session, client_id=row.client_id, location_id=row.location_id, description=fee.description,
            unit_price_minor=fee.amount_minor, source_context="programs", source_type="enrollment", source_id=row.id,
            source_line_no=line, revenue_category_id=fee.revenue_category_id or row.revenue_category_id,
        )  # fmt: skip
        ids.append(charge.id)
    if ids:
        row.charge_id = ids[0]
        session.flush()
    return ids


def invoice(session: Db, charge_ids: list[UUID], payer_client_id: UUID | None, origin: str = "staff"):
    if not charge_ids:
        return None
    return billing.service.create_invoice_for_charges(
        session, charge_ids, bill_to_client_id=payer_client_id, origin=origin
    )


def check_payer(
    session: Db, participants: list[UUID], payer_client_id: UUID | None, pointer: str = "/payer_client_id"
) -> None:
    """Money goes where its owner points it: the payer is a participant or a relative of one."""
    if payer_client_id is None or payer_client_id in participants:
        return
    clients.service.require_active(session, payer_client_id, pointer=pointer)
    if payer_client_id not in billing.service.related_clients(session, participants):
        raise ValidationFailed(
            "The payer must be the participant or a relative.", pointer=pointer, code="payer-not-related"
        )


def create_enrollment(session: Db, principal: Principal, data: dict) -> dict:
    """Staff registration into a group or subgroup (REG-07): the place, a charge per chosen fee and one invoice
    to the payer, in this transaction. Payment is taken against the invoice now (billing) or later."""
    group = load(session, principal, data["program_group_id"], ENROLL)
    clients.service.load(session, principal, data["client_id"], ENROLL)
    clients.service.require_active(session, data["client_id"])
    check_payer(session, [data["client_id"]], data.get("payer_client_id"))
    fees = chosen_fees(session, group, data.get("program_fee_ids") or [], online=False, pointer="/program_fee_ids")
    row = enroll(
        session, group, data["client_id"], channel="staff", fees=fees, payer_client_id=data.get("payer_client_id"),
        comment=data.get("registrant_comment"),
    )  # fmt: skip
    found = invoice(session, bill(session, row, fees), data.get("payer_client_id"))
    audit.record(session, ENROLL, row, location_id=row.location_id, changes={"program_group_id": [None, str(group.id)]})
    return {"enrollment": row, "invoice_id": found.id if found else None}


def _undo_charges(session: Db, row: Enrollment, reason: str) -> None:
    """Void each uninvoiced, unpaid line the enrolment raised; reverse the rest (money applied goes back to the
    payer as account credit; a refund is billing's own step)."""
    for charge_id in billing.service.charge_ids_for_source(session, "programs", "enrollment", row.id):
        if billing.service.charge_states(session, [charge_id])[charge_id]["status"] != "active":
            continue
        try:
            with session.begin_nested():
                billing.service.void_charge(session, charge_id, reason=reason)
        except Conflict:
            billing.service.reverse(session, charge_id, reason=reason)


def cancel(
    session: Db, principal: Principal | None, row: Enrollment, *, kind: str, disposition: str, reason: str | None,
    actor: str,
) -> None:  # fmt: skip
    """Internal: release the place and settle the billing as chosen. `reversed` needs billing.charge.reverse."""
    if disposition == "reversed" and principal is not None:
        authorize(principal, REVERSE, location_id=row.location_id)
    _release_place(session, session.get(ProgramGroup, row.program_group_id))
    row.status, row.cancelled_at, row.cancel_kind, row.cancel_reason = "cancelled", clock.now(), kind, reason
    row.billing_disposition, row.cancelled_by_actor_type, row.hold_expires_at = disposition, actor, None
    if disposition == "reversed":
        _undo_charges(session, row, reason or "Registration cancelled")
    event = ev.GroupEnrollmentCancelled(
        enrollment_id=row.id, program_group_id=row.program_group_id, client_id=row.client_id,
        location_id=row.location_id, cancel_kind=kind,
    )  # fmt: skip
    events.publish(session, event, row.id)
    session.flush()


def cancel_enrollment(session: Db, principal: Principal, row: Enrollment, data: dict) -> Enrollment:
    """Remove a participant: place back, billing reversed, kept or untouched, and optionally demoted to the tail
    of the waitlist (REG-09 "set as waitlisted"). A freed place goes to an auto-promote queue."""
    group = load(session, principal, row.program_group_id, CANCEL)
    if row.status == "cancelled":
        return row
    demote = bool(data.get("add_to_waitlist"))
    kind = "demoted_to_waitlist" if demote else data.get("cancel_kind") or "staff_removed"
    disposition = data.get("billing_disposition") or "none"
    cancel(session, principal, row, kind=kind, disposition=disposition, reason=data.get("reason"), actor="staff")
    audit.record(
        session, CANCEL, row, location_id=row.location_id,
        changes={"status": ["enrolled", "cancelled"], "cancel_kind": [None, kind], "billing_disposition": [None, disposition]},
    )  # fmt: skip
    if demote:
        _queue(
            session,
            group,
            row.client_id,
            channel="staff",
            fee_id=row.program_fee_id,
            payer_client_id=row.payer_client_id,
        )
    else:
        promote_queue(session, group.id)
    return row


# --- group waitlist (REG-09) --------------------------------------------------------------------------------


def _queue(
    session: Db, group: ProgramGroup, client_id: UUID, *, channel: str, fee_id: UUID | None,
    payer_client_id: UUID | None,
) -> WaitlistEntry:  # fmt: skip
    mode = waitlist_mode(session, group)
    if mode == "disabled":
        raise Conflict("This program has no waitlist.", code="waitlist-disabled")
    entry = WaitlistEntry(
        location_id=group.location_id, client_id=client_id, target_kind="group", program_group_id=group.id,
        mode=mode, channel=channel, queued_at=clock.now(), program_fee_id=fee_id, payer_client_id=payer_client_id,
    )  # fmt: skip
    session.add(entry)
    session.flush()  # uq_waitlist_entry_group_client
    return entry


def join_waitlist(
    session: Db, group: ProgramGroup, client_id: UUID, *, channel: str, fees: list[ProgramFee],
    payer_client_id: UUID | None,
) -> WaitlistEntry:  # fmt: skip
    """Internal: queue for a full node (409 session-has-space while there is room, already-enrolled)."""
    if has_space(session, group):
        raise Conflict("The program still has space: register instead.", code="session-has-space")
    if session.scalar(
        select(Enrollment.id).where(
            Enrollment.program_group_id == group.id, Enrollment.client_id == client_id, Enrollment.status.in_(LIVE)
        )
    ):
        raise Conflict("Already registered.", code="already-enrolled")
    fee_id = fees[0].id if fees else None
    return _queue(session, group, client_id, channel=channel, fee_id=fee_id, payer_client_id=payer_client_id)


def create_waitlist_entry(session: Db, principal: Principal, data: dict) -> WaitlistEntry:
    """Queue a client for a full node; the intended fee and payer are kept for promotion."""
    group = load(session, principal, data["program_group_id"], WAITLIST)
    clients.service.load(session, principal, data["client_id"], WAITLIST)
    clients.service.require_active(session, data["client_id"])
    check_payer(session, [data["client_id"]], data.get("payer_client_id"))
    ids = [data["program_fee_id"]] if data.get("program_fee_id") else []
    fees = chosen_fees(session, group, ids, online=False, pointer="/program_fee_id")
    entry = join_waitlist(
        session, group, data["client_id"], channel="staff", fees=fees, payer_client_id=data.get("payer_client_id")
    )
    audit.record(
        session, WAITLIST, entry, location_id=entry.location_id, changes={"program_group_id": [None, str(group.id)]}
    )
    return entry


def queue(session: Db, group_id: UUID) -> list[WaitlistEntry]:
    return list(
        session.scalars(
            select(WaitlistEntry)
            .where(WaitlistEntry.program_group_id == group_id, WaitlistEntry.status == "waiting")
            .order_by(WaitlistEntry.queued_at, WaitlistEntry.id)
        )
    )


def list_waitlist(session: Db, principal: Principal, group_id: UUID) -> list[WaitlistEntry]:
    return queue(session, load(session, principal, group_id, WAITLIST).id)


def promote(session: Db, group: ProgramGroup, entry: WaitlistEntry, *, bill_now: bool = True) -> Enrollment:
    """Internal: enrol the entry (409 capacity-full) and, with `bill_now`, charge its fee on a new invoice."""
    fee = session.get(ProgramFee, entry.program_fee_id) if entry.program_fee_id else None
    fees = [fee] if fee is not None and fee.is_active else []
    row = enroll(session, group, entry.client_id, channel="waitlist", fees=fees, payer_client_id=entry.payer_client_id)
    if bill_now:
        invoice(session, bill(session, row, fees), entry.payer_client_id)
    entry.status, entry.promoted_enrollment_id = "promoted", row.id
    event = ev.GroupWaitlistPromoted(
        enrollment_id=row.id, program_group_id=group.id, client_id=entry.client_id, waitlist_entry_id=entry.id
    )
    events.publish(session, event, entry.id)
    client = clients.service.get(session, entry.client_id)
    if client.primary_email:
        notifications.send(
            session, "programs.group_waitlist_promoted", client.primary_email,
            {"first_name": client.first_name, "title": group.name},
        )  # fmt: skip
    session.flush()
    return row


def promote_entry(session: Db, principal: Principal, entry: WaitlistEntry, *, bill_now: bool = True) -> WaitlistEntry:
    """Staff promotion of a group entry, any mode. Billing on promotion also needs the registration key."""
    group = load(session, principal, entry.program_group_id, WAITLIST)
    if entry.status != "waiting":
        raise Conflict("This entry is no longer waiting.")
    if bill_now and entry.program_fee_id:
        authorize(principal, ENROLL, location_id=group.location_id)
    promote(session, group, entry, bill_now=bill_now)
    audit.record(session, WAITLIST, entry, location_id=entry.location_id, changes={"status": ["waiting", "promoted"]})
    return entry


def promote_queue(session: Db, group_id: UUID) -> int:
    """Internal: after a place frees up, `auto_promote` queues fill it FIFO, billing on enrolment. Walks the
    node and its ancestors, since a place freed in a team is also a place in its league."""
    promoted = 0
    for node in reversed(_chain(session, session.get(ProgramGroup, group_id))):
        if node.status != "active" or node.deleted_at is not None or waitlist_mode(session, node) != "auto_promote":
            continue
        for entry in session.scalars(
            select(WaitlistEntry)
            .where(
                WaitlistEntry.program_group_id == node.id, WaitlistEntry.status == "waiting",
                WaitlistEntry.mode == "auto_promote", WaitlistEntry.channel != "portal",
            )
            .order_by(WaitlistEntry.queued_at, WaitlistEntry.id)
            .with_for_update(skip_locked=True)
        ).all():  # fmt: skip
            try:
                with session.begin_nested():
                    promote(session, node, entry)
            except Conflict as exc:
                if exc.code != "capacity-full":
                    raise
                break
            promoted += 1
    return promoted


def remove_entry(session: Db, principal: Principal, entry: WaitlistEntry) -> None:
    load(session, principal, entry.program_group_id, WAITLIST)
    if entry.status in ("waiting", "offered"):
        was, entry.status, entry.removed_reason = entry.status, "removed", "staff"
        audit.record(session, WAITLIST, entry, location_id=entry.location_id, changes={"status": [was, "removed"]})
        session.flush()


# --- roster -------------------------------------------------------------------------------------------------


def roster(session: Db, principal: Principal, group_id: UUID) -> dict:
    """Everyone registered in the node and its subgroups, with the subgroup each sits in (REG-07)."""
    group = load(session, principal, group_id, READ)
    ids = [group.id, *_subtree_ids(session, group.id)]
    names = dict(session.execute(select(ProgramGroup.id, ProgramGroup.name).where(ProgramGroup.id.in_(ids))).all())
    rows = session.scalars(
        select(Enrollment)
        .where(Enrollment.program_group_id.in_(ids), Enrollment.status == "enrolled")
        .order_by(Enrollment.enrolled_at, Enrollment.id)
    ).all()
    states = billing.service.charge_states(session, [r.charge_id for r in rows if r.charge_id])
    return {
        "program_group_id": group.id, "capacity": group.capacity, "enrolled_count": group.enrolled_count,
        "waiting_count": len(queue(session, group.id)),
        "participants": [
            {
                "enrollment_id": r.id, "client_id": r.client_id, "program_group_id": r.program_group_id,
                "program_group_name": names[r.program_group_id], "enrolled_at": r.enrolled_at, "channel": r.channel,
                "client_name": clients.service.display_name(clients.service.get(session, r.client_id)),
                "payer_client_id": r.payer_client_id, "charge_id": r.charge_id,
                "invoice_id": states.get(r.charge_id, {}).get("invoice_id"),
            }
            for r in rows
        ],
    }  # fmt: skip
