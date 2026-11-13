"""programs group tools (Phase 14 chip A): classifiers (REG-03), saved group searches (REG-04), per-user page
settings and member-grid columns (REG-06), moving members between nodes (REG-08), location registration
defaults (REG-11), and copy, generate and export of a group tree (REG-13).

A move re-prices nothing: the enrolment keeps its fee and charge, only its place moves (released on the old chain,
taken on the new one, so capacity and linked session seats stay right). A copy never carries schedules, members
or league games; registration is copied switched off and unpublished.
"""

import csv
import io
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as Db

from app.core import audit, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, authorize_tenant_wide
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.modules import platform
from app.modules.programs import events as ev
from app.modules.programs import groups
from app.modules.programs.models import (
    Enrollment,
    ProgramClassifier,
    ProgramFee,
    ProgramGroup,
    ProgramPageSetting,
    ProgramSavedView,
    RegistrationConfig,
    RegistrationDefault,
)

UPDATE, EXPORT = "programs.registration.update", "programs.registration.export"
MAX_COPY_NODES = 50  # shortcut: a bigger tree is refused, not queued; move to a chunked job if a customer needs it
MAX_SERIES = 52
COLUMNS = {
    "program_list": ("name", "kind", "status", "starts_on", "ends_on", "capacity", "enrolled_count", "spots_left",
                     "waiting_count", "season", "sport", "age_division", "contact_name"),
    "member_grid": ("client_name", "program_group_name", "enrolled_at", "channel", "payer", "invoice"),
}  # fmt: skip
DEFAULT_COLUMNS = {
    "program_list": ["name", "kind", "status", "starts_on", "enrolled_count", "spots_left"],
    "member_grid": ["client_name", "program_group_name", "enrolled_at", "channel"],
}
CONSTRAINT_CODES.update({
    "uq_program_classifier_kind_title": "already-exists",
    "uq_program_saved_view_name": "already-exists",
})  # fmt: skip


def _staff(principal: Principal) -> UUID:
    if principal.kind != "staff" or principal.staff_user_id is None:
        raise NotFound()
    return principal.staff_user_id


# --- classifiers (REG-03) -----------------------------------------------------------------------------------


def _usage(session: Db, classifier_id: UUID) -> int:
    g = ProgramGroup
    return session.execute(
        select(func.count()).where(
            or_(
                g.season_classifier_id == classifier_id,
                g.sport_classifier_id == classifier_id,
                g.age_division_classifier_id == classifier_id,
            )
        )
    ).scalar_one()


def _classifier_view(session: Db, row: ProgramClassifier) -> dict:
    return {
        "id": row.id, "kind": row.kind, "title": row.title, "sort_order": row.sort_order,
        "is_active": row.is_active, "group_count": _usage(session, row.id),
    }  # fmt: skip


def list_classifiers(session: Db, principal: Principal, kind: str | None = None) -> list[dict]:
    """Every classifier, by kind then sort order (a short tenant list: no paging)."""
    authorize(principal, groups.READ)
    stmt = select(ProgramClassifier).order_by(
        ProgramClassifier.kind, ProgramClassifier.sort_order, ProgramClassifier.title
    )
    if kind is not None:
        stmt = stmt.where(ProgramClassifier.kind == kind)
    return [_classifier_view(session, row) for row in session.scalars(stmt.limit(500))]


def _classifier(session: Db, principal: Principal, classifier_id: UUID) -> ProgramClassifier:
    authorize_tenant_wide(principal, groups.MANAGE)
    row = session.get(ProgramClassifier, classifier_id)
    if row is None:
        raise NotFound()
    return row


def create_classifier(session: Db, principal: Principal, data: dict) -> dict:
    authorize_tenant_wide(principal, groups.MANAGE)
    row = ProgramClassifier(kind=data["kind"], title=data["title"], sort_order=data.get("sort_order") or 0)
    session.add(row)
    session.flush()  # uq_program_classifier_kind_title
    audit.record(session, groups.MANAGE, row, changes=audit.diff(row))
    return _classifier_view(session, row)


def update_classifier(session: Db, principal: Principal, classifier_id: UUID, data: dict) -> dict:
    row = _classifier(session, principal, classifier_id)
    for key in ("title", "sort_order", "is_active"):
        if data.get(key) is not None:
            setattr(row, key, data[key])
    changes = audit.diff(row)
    session.flush()
    if changes:
        audit.record(session, groups.MANAGE, row, changes=changes)
    return _classifier_view(session, row)


def delete_classifier(session: Db, principal: Principal, classifier_id: UUID) -> None:
    """A real delete, blocked while a group uses it (deactivate it instead)."""
    row = _classifier(session, principal, classifier_id)
    if _usage(session, row.id):
        raise Conflict("Groups use this classifier; deactivate it instead.", code="in-use")
    audit.record(session, groups.MANAGE, row, changes={"title": [row.title, None]})
    session.delete(row)
    session.flush()


# --- saved views (REG-04) -----------------------------------------------------------------------------------


def _check_filters(filters: dict | None, sort: str | None) -> None:
    for name in filters or {}:
        if name.split("[", 1)[0] not in groups.LIST_FILTERS:
            raise ValidationFailed(f"Cannot filter groups by {name}.", pointer="/filters")
    for part in filter(None, (sort or "").split(",")):
        if part.lstrip("-") not in ("name", "starts_on", "created_at"):
            raise ValidationFailed(f"Cannot sort groups by {part}.", pointer="/sort")


def _view(session: Db, principal: Principal, view_id: UUID) -> ProgramSavedView:
    row = session.get(ProgramSavedView, view_id)
    if row is None or row.staff_user_id != _staff(principal):
        raise NotFound()
    return row


def list_saved_views(session: Db, principal: Principal) -> list[ProgramSavedView]:
    authorize(principal, groups.READ)
    stmt = select(ProgramSavedView).where(ProgramSavedView.staff_user_id == _staff(principal))
    return list(session.scalars(stmt.order_by(ProgramSavedView.name).limit(100)))


def create_saved_view(session: Db, principal: Principal, data: dict) -> ProgramSavedView:
    authorize(principal, groups.READ)
    _check_filters(data.get("filters"), data.get("sort"))
    row = ProgramSavedView(
        staff_user_id=_staff(principal), name=data["name"], filters=data.get("filters") or {}, sort=data.get("sort")
    )
    session.add(row)
    session.flush()  # uq_program_saved_view_name
    audit.record(session, groups.READ, row, changes={"name": [None, row.name]})
    return row


def update_saved_view(session: Db, principal: Principal, view_id: UUID, data: dict) -> ProgramSavedView:
    authorize(principal, groups.READ)
    row = _view(session, principal, view_id)
    _check_filters(data.get("filters"), data.get("sort"))
    for key in ("name", "filters"):
        if data.get(key) is not None:
            setattr(row, key, data[key])
    if "sort" in data:
        row.sort = data["sort"]
    changes = audit.diff(row)
    session.flush()
    if changes:
        audit.record(session, groups.READ, row, changes=changes)
    return row


def delete_saved_view(session: Db, principal: Principal, view_id: UUID) -> None:
    authorize(principal, groups.READ)
    row = _view(session, principal, view_id)
    audit.record(session, groups.READ, row, changes={"name": [row.name, None]})
    session.delete(row)
    session.flush()


# --- page settings (REG-06) ---------------------------------------------------------------------------------


def _setting_view(page_key: str, row: ProgramPageSetting | None) -> dict:
    stored = row.settings if row is not None else {}
    return {
        "page_key": page_key, "title": stored.get("title"),
        "columns": stored.get("columns") or DEFAULT_COLUMNS[page_key], "available_columns": list(COLUMNS[page_key]),
        "page_size": stored.get("page_size", 50), "default_view_id": stored.get("default_view_id"),
    }  # fmt: skip


def _setting(session: Db, staff_user_id: UUID, page_key: str) -> ProgramPageSetting | None:
    p = ProgramPageSetting
    return session.scalar(select(p).where(p.staff_user_id == staff_user_id, p.page_key == page_key))


def _page(page_key: str) -> str:
    if page_key not in COLUMNS:
        raise NotFound()
    return page_key


def get_page_setting(session: Db, principal: Principal, page_key: str) -> dict:
    authorize(principal, groups.READ)
    _page(page_key)
    return _setting_view(page_key, _setting(session, _staff(principal), page_key))


def put_page_setting(session: Db, principal: Principal, page_key: str, data: dict) -> dict:
    authorize(principal, groups.READ)
    _page(page_key)
    staff_user_id = _staff(principal)
    unknown = [c for c in data.get("columns") or [] if c not in COLUMNS[page_key]]
    if unknown:
        raise ValidationFailed(f"Unknown column: {unknown[0]}.", pointer="/columns")
    if data.get("default_view_id") is not None:
        _view(session, principal, data["default_view_id"])
    row = _setting(session, staff_user_id, page_key)
    if row is None:
        row = ProgramPageSetting(staff_user_id=staff_user_id, page_key=page_key)
        session.add(row)
    row.settings = {
        "title": data.get("title"), "columns": list(dict.fromkeys(data.get("columns") or [])),
        "page_size": data.get("page_size", 50),
        "default_view_id": str(data["default_view_id"]) if data.get("default_view_id") else None,
    }  # fmt: skip
    session.flush()
    audit.record(session, groups.READ, row, changes={"page_key": [None, page_key]})
    return _setting_view(page_key, row)


# --- move members (REG-08) ----------------------------------------------------------------------------------


def _move_one(session: Db, principal: Principal, enrollment_id: UUID, target: ProgramGroup) -> None:
    row = session.get(Enrollment, enrollment_id)
    if row is None or row.target_kind != "group" or row.program_group_id is None:
        raise NotFound()
    source = groups.load(session, principal, row.program_group_id, UPDATE)
    if row.status != "enrolled":
        raise Conflict("Only a confirmed registration can be moved.", code="not-movable")
    if source.id == target.id:
        raise Conflict("The member is already in this group.", code="same-group")
    if source.location_id != target.location_id:
        raise Conflict("Members move between groups of one location.", code="different-location")
    groups._release_place(session, source)
    groups._take_place(session, target)
    row.program_group_id = target.id
    session.flush()  # uq_enrollment_group_client
    audit.record(
        session,
        UPDATE,
        row,
        location_id=row.location_id,
        changes={"program_group_id": [str(source.id), str(target.id)]},
    )
    events.publish(
        session,
        ev.EnrollmentMoved(
            enrollment_id=row.id, from_program_group_id=source.id, program_group_id=target.id,
            client_id=row.client_id, location_id=row.location_id,
        ),
        row.id,
    )  # fmt: skip


def move_enrollments(session: Db, principal: Principal, data: dict) -> dict:
    """One command, one savepoint per member: a full target or a duplicate comes back with its code and the rest
    still move. Nothing is re-priced: the enrolment keeps its fee and charge."""
    target = groups.load(session, principal, data["to_program_group_id"], UPDATE)
    outcomes = []
    for enrollment_id in dict.fromkeys(data["enrollment_ids"]):
        try:
            with session.begin_nested():
                _move_one(session, principal, enrollment_id, target)
            outcomes.append({"enrollment_id": enrollment_id, "moved": True, "code": None})
        except DomainError as exc:
            outcomes.append({"enrollment_id": enrollment_id, "moved": False, "code": exc.code})
        except IntegrityError as exc:
            name = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
            outcomes.append(
                {"enrollment_id": enrollment_id, "moved": False, "code": CONSTRAINT_CODES.get(name, "conflict")}
            )
    return {"to_program_group_id": target.id, "outcomes": outcomes}


# --- registration defaults (REG-11) -------------------------------------------------------------------------

_DEFAULT_FIELDS = (
    "payment_requirement", "displays_openings", "waitlist_mode", "online_description", "confirmation_message",
    "closed_message",
)  # fmt: skip


def _defaults_view(location_id: UUID, row: RegistrationDefault | None) -> dict:
    if row is None:
        return {
            "location_id": location_id, "payment_requirement": "immediate_card_payment", "displays_openings": False,
            "waitlist_mode": "manual", "online_description": None, "confirmation_message": None, "closed_message": None,
        }  # fmt: skip
    return {"location_id": location_id} | {key: getattr(row, key) for key in _DEFAULT_FIELDS}


def get_defaults(session: Db, principal: Principal, location_id: UUID) -> dict:
    platform.service.get_location(session, principal, location_id)
    authorize(principal, groups.CONFIG, location_id=location_id)
    return _defaults_view(location_id, groups.registration_default(session, location_id))


def put_defaults(session: Db, principal: Principal, location_id: UUID, data: dict) -> dict:
    """Replace the defaults. They apply to groups and registration settings created from now on; existing ones
    keep what they have (a group without its own waitlist mode follows the location default)."""
    platform.service.get_location(session, principal, location_id)
    authorize(principal, groups.CONFIG, location_id=location_id)
    row = groups.registration_default(session, location_id)
    if row is None:
        row = RegistrationDefault(location_id=location_id)
        session.add(row)
    for key in _DEFAULT_FIELDS:
        setattr(row, key, data.get(key))
    changes = audit.diff(row)
    session.flush()
    audit.record(session, groups.CONFIG, row, location_id=location_id, changes=changes)
    return _defaults_view(location_id, row)


# --- copy, generate, export (REG-13) ------------------------------------------------------------------------

_NODE_FIELDS = (*groups._GROUP_FIELDS, "location_id", "depth")
_FEE_FIELDS = ("location_id", "fee_kind", "description", "amount_minor", "deposit_minor", "revenue_category_id",
               "is_online", "is_active", "sort_order")  # fmt: skip
_REG_FIELDS = ("payment_requirement", "displays_openings", "online_description", "closed_message",
               "confirmation_message", "portal_publish_name")  # fmt: skip


def _shift(value, days: int | None):
    return value + timedelta(days=days) if value is not None and days else value


def _tree_size(session: Db, group: ProgramGroup, include_children: bool) -> int:
    return 1 + (len(groups._subtree_ids(session, group.id)) if include_children else 0)


def _copy_node(
    session: Db, src: ProgramGroup, parent_id: UUID | None, values: dict, days: int | None, opts: dict
) -> ProgramGroup:
    row = ProgramGroup(**({k: getattr(src, k) for k in _NODE_FIELDS} | {"parent_id": parent_id} | values))
    for key in ("starts_on", "ends_on", "auto_archive_on"):
        if key not in values:
            setattr(row, key, _shift(getattr(src, key), days))
    session.add(row)
    session.flush()  # uq_program_group_sibling_name
    audit.record(session, groups.MANAGE, row, location_id=row.location_id, changes=audit.diff(row))
    if opts["include_fees"]:
        for fee in session.scalars(select(ProgramFee).where(ProgramFee.program_group_id == src.id)):
            session.add(ProgramFee(program_group_id=row.id, **{k: getattr(fee, k) for k in _FEE_FIELDS}))
    config = groups.config_for(session, src.id)
    if opts["include_registration"] and config is not None:
        session.add(
            RegistrationConfig(
                program_group_id=row.id, is_enabled=False, is_portal_visible=False,
                public_slug=groups._default_slug(row), opens_on=_shift(config.opens_on, days),
                closes_on=_shift(config.closes_on, days), **{k: getattr(config, k) for k in _REG_FIELDS},
            )
        )  # fmt: skip
    if opts["include_children"]:
        children = session.scalars(
            select(ProgramGroup)
            .where(ProgramGroup.parent_id == src.id, ProgramGroup.deleted_at.is_(None))
            .order_by(ProgramGroup.name)
        ).all()
        for child in children:
            _copy_node(session, child, row.id, {}, days, opts)
        row.child_count = len(children)
    session.flush()
    return row


def _copy(session: Db, src: ProgramGroup, name: str, days: int | None, opts: dict, dates: dict) -> ProgramGroup:
    """A copy beside the source (same parent and location), its own counters starting at zero."""
    if src.parent_id is not None:
        parent = groups._row(session, src.parent_id, lock=True)
        parent.child_count += 1  # ck_program_group_children
    return _copy_node(session, src, src.parent_id, {"name": name, **dates}, days, opts)


def copy_group(session: Db, principal: Principal, group_id: UUID, data: dict) -> ProgramGroup:
    """Copy a group (REG-13) with its subgroups, fees and registration settings as asked; never sessions,
    members or games. Dates move with `starts_on` when it is given."""
    src = groups.load(session, principal, group_id, groups.MANAGE)
    groups._check_span(data)
    if _tree_size(session, src, data["include_children"]) > MAX_COPY_NODES:
        raise ValidationFailed(f"Copy at most {MAX_COPY_NODES} groups at once.", code="tree-too-large")
    days = (data["starts_on"] - src.starts_on).days if data.get("starts_on") and src.starts_on else None
    dates = {k: data[k] for k in ("starts_on", "ends_on") if data.get(k) is not None}
    return _copy(session, src, data["name"], days, data, dates)


def generate_series(session: Db, principal: Principal, group_id: UUID, data: dict) -> list[ProgramGroup]:
    """A series of programs from a template and a date range (REG-13): one copy per `interval_weeks` from
    `first_starts_on` to `last_starts_on`, each named after its start and keeping the template's length."""
    src = groups.load(session, principal, group_id, groups.MANAGE)
    if src.starts_on is None:
        raise ValidationFailed("Give the template a start date first.", pointer="/first_starts_on",
                               code="template-needs-dates")  # fmt: skip
    if data["last_starts_on"] < data["first_starts_on"]:
        raise ValidationFailed("The last start is before the first.", pointer="/last_starts_on")
    starts, current = [], data["first_starts_on"]
    while current <= data["last_starts_on"]:
        starts.append(current)
        current += timedelta(weeks=data["interval_weeks"])
    if len(starts) > MAX_SERIES:
        raise ValidationFailed(f"Generate at most {MAX_SERIES} programs at once.", code="series-too-long")
    if len(starts) * _tree_size(session, src, data["include_children"]) > MAX_COPY_NODES * 4:
        raise ValidationFailed("The series is too large to create at once.", code="tree-too-large")
    return [
        _copy(session, src, f"{src.name} {start.isoformat()}", (start - src.starts_on).days, data, {})
        for start in starts
    ]


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text  # spreadsheet formula injection


def export_group(session: Db, principal: Principal, group_id: UUID) -> tuple[bytes, str]:
    """The group and its subgroups' members as CSV (REG-13): one row per confirmed registration."""
    group = groups.load(session, principal, group_id, EXPORT)
    roster = groups.roster(session, principal, group.id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["group", "participant", "enrolled_at", "channel", "invoice_id"])
    for row in roster["participants"]:
        writer.writerow([_cell(row["program_group_name"]), _cell(row["client_name"]),
                         row["enrolled_at"].isoformat() if row["enrolled_at"] else "", row["channel"],
                         row["invoice_id"] or ""])  # fmt: skip
    audit.record(
        session,
        EXPORT,
        group,
        location_id=group.location_id,
        changes={"exported_rows": [None, len(roster["participants"])]},
    )
    name = "".join(c if c.isalnum() else "-" for c in group.name.lower()).strip("-")[:60] or "program"
    return out.getvalue().encode(), f"{name}-members.csv"
