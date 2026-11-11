"""assessments services (FIT-01 to FIT-03, and the FIT-05 portal view). Results hang off a client, so reads and
recording go through `clients.service.load` (C keys, own reach for coaches); deleting an entry is an `L` key on
the entry's location. Values are health data: audit rows say that values changed, never what they are."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize
from app.core.auth.permissions import authorize_tenant_wide
from app.core.errors import NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import clients, platform
from app.modules.assessments.domain import progress
from app.modules.assessments.events import ResultRecorded
from app.modules.assessments.models import (
    AssessmentField,
    AssessmentResult,
    AssessmentResultValue,
    AssessmentSettings,
    AssessmentTemplate,
)

READ = "assessments.assessment.read"
RECORD = "assessments.assessment.record"
DELETE = "assessments.assessment.delete"
MANAGE = "assessments.definition.manage"

CONSTRAINT_CODES["uq_assessment_template_name"] = "already-exists"
CONSTRAINT_CODES["uq_assessment_field_name"] = "already-exists"


# --- definitions (FIT-01) ------------------------------------------------------------------------------------


def _fields(session: Session, template_ids: list[UUID]) -> dict[UUID, list[AssessmentField]]:
    found: dict[UUID, list[AssessmentField]] = {t: [] for t in template_ids}
    rows = session.scalars(
        select(AssessmentField).where(AssessmentField.assessment_template_id.in_(template_ids))
        .order_by(AssessmentField.sort_order, AssessmentField.name)
    )  # fmt: skip
    for row in rows:
        found[row.assessment_template_id].append(row)
    return found


def template_view(template: AssessmentTemplate, fields: list[AssessmentField]) -> dict:
    return {c.key: getattr(template, c.key) for c in AssessmentTemplate.__table__.columns} | {"fields": fields}


def list_templates(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, READ)
    page = paginate(
        session, select(AssessmentTemplate), query, id_column=AssessmentTemplate.id,
        sort_fields={"sort_order": AssessmentTemplate.sort_order, "name": AssessmentTemplate.name},
        default_sort="sort_order", filter_fields={"is_active": AssessmentTemplate.is_active},
    )  # fmt: skip
    fields = _fields(session, [t.id for t in page["data"]])
    return page | {"data": [template_view(t, fields[t.id]) for t in page["data"]]}


def _template(session: Session, template_id: UUID) -> AssessmentTemplate:
    if (template := session.get(AssessmentTemplate, template_id)) is None:
        raise NotFound()
    return template


def create_template(session: Session, principal: Principal, data: dict) -> dict:
    authorize_tenant_wide(principal, MANAGE)
    template = AssessmentTemplate(**data)
    session.add(template)
    session.flush()
    audit.record(session, MANAGE, template, changes=audit.diff(template))
    return template_view(template, [])


def update_template(session: Session, principal: Principal, template_id: UUID, data: dict) -> dict:
    authorize_tenant_wide(principal, MANAGE)
    template = _template(session, template_id)
    for key, value in data.items():
        setattr(template, key, value)
    audit.record(session, MANAGE, template, changes=audit.diff(template))
    session.flush()
    return template_view(template, _fields(session, [template.id])[template.id])


def create_field(session: Session, principal: Principal, template_id: UUID, data: dict) -> AssessmentField:
    authorize_tenant_wide(principal, MANAGE)
    template = _template(session, template_id)
    field = AssessmentField(assessment_template_id=template.id, **data)
    session.add(field)
    session.flush()
    audit.record(session, MANAGE, field, changes=audit.diff(field))
    return field


def update_field(session: Session, principal: Principal, field_id: UUID, data: dict) -> AssessmentField:
    """Changing decimal places applies to values recorded from now on; stored values keep their rounding."""
    authorize_tenant_wide(principal, MANAGE)
    if (field := session.get(AssessmentField, field_id)) is None:
        raise NotFound()
    for key, value in data.items():
        setattr(field, key, value)
    audit.record(session, MANAGE, field, changes=audit.diff(field))
    session.flush()
    return field


def _settings(session: Session) -> AssessmentSettings:
    row = session.scalar(select(AssessmentSettings))
    if row is None:
        row = AssessmentSettings(is_portal_sharing_enabled=False, summary_max_age_days_default=90)
        session.add(row)
        session.flush()
    return row


def get_settings(session: Session, principal: Principal) -> AssessmentSettings:
    authorize(principal, READ)
    return _settings(session)


def update_settings(session: Session, principal: Principal, data: dict) -> AssessmentSettings:
    authorize_tenant_wide(principal, MANAGE)
    row = _settings(session)
    for key, value in data.items():
        setattr(row, key, value)
    audit.record(session, MANAGE, row, changes=audit.diff(row))
    session.flush()
    return row


# --- results (FIT-02) ----------------------------------------------------------------------------------------


def _values(session: Session, result: AssessmentResult) -> list[AssessmentResultValue]:
    return list(session.scalars(
        select(AssessmentResultValue).where(AssessmentResultValue.assessment_result_id == result.id)
        .order_by(AssessmentResultValue.assessment_field_id)
    ))  # fmt: skip


def result_view(session: Session, result: AssessmentResult) -> dict:
    return {c.key: getattr(result, c.key) for c in AssessmentResult.__table__.columns} | {
        "values": _values(session, result)}  # fmt: skip


def _result(session: Session, principal: Principal, result_id: UUID, key: str) -> AssessmentResult:
    """The entry, if the caller reaches its client with `key`; otherwise 404."""
    if (result := session.get(AssessmentResult, result_id)) is None:
        raise NotFound()
    clients.service.load(session, principal, result.client_id, key)
    return result


def _checked_values(session: Session, values: list[dict]) -> list[tuple[AssessmentField, object]]:
    """Each value names an active field of an active category, once; rounded to the field."""
    ids = [v["assessment_field_id"] for v in values]
    if len(set(ids)) != len(ids):
        raise ValidationFailed("A field appears twice.", pointer="/values")
    fields = {f.id: f for f in session.scalars(
        select(AssessmentField).join(AssessmentTemplate, AssessmentTemplate.id == AssessmentField.assessment_template_id)
        .where(AssessmentField.id.in_(ids), AssessmentField.is_active, AssessmentTemplate.is_active)
    )}  # fmt: skip
    checked = []
    for index, value in enumerate(values):
        if (field := fields.get(value["assessment_field_id"])) is None:
            raise ValidationFailed("Unknown or archived field.", pointer=f"/values/{index}/assessment_field_id")
        checked.append((field, progress.rounded(value["value"], field.decimal_places)))
    return checked


def _write_values(session: Session, result: AssessmentResult, values: list[dict]) -> None:
    session.execute(delete(AssessmentResultValue).where(AssessmentResultValue.assessment_result_id == result.id))
    for field, value in _checked_values(session, values):
        session.add(AssessmentResultValue(
            assessment_result_id=result.id, assessment_field_id=field.id, client_id=result.client_id,
            recorded_at=result.recorded_at, value=value,
        ))  # fmt: skip


def list_results(session: Session, principal: Principal, client_id: UUID, query: ListQuery) -> dict:
    clients.service.load(session, principal, client_id, READ)
    page = paginate(
        session, select(AssessmentResult).where(AssessmentResult.client_id == client_id), query,
        id_column=AssessmentResult.id, sort_fields={"recorded_at": AssessmentResult.recorded_at},
        default_sort="-recorded_at",
        filter_fields={"client_id": AssessmentResult.client_id, "recorded_at": AssessmentResult.recorded_at},
    )  # fmt: skip
    return page | {"data": [result_view(session, r) for r in page["data"]]}


def get_result(session: Session, principal: Principal, result_id: UUID) -> dict:
    return result_view(session, _result(session, principal, result_id, READ))


def create_result(session: Session, principal: Principal, data: dict) -> dict:
    client = clients.service.require_active(session, data["client_id"])
    clients.service.load(session, principal, client.id, RECORD)
    try:
        platform.service.get_location(session, principal, data["location_id"])
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    result = AssessmentResult(
        client_id=client.id, location_id=data["location_id"], recorded_at=data["recorded_at"], note=data.get("note"),
        recorded_by_staff_user_id=principal.staff_user_id if principal.kind == "staff" else None,
    )  # fmt: skip
    session.add(result)
    session.flush()
    _write_values(session, result, data["values"])
    audit.record(session, RECORD, result, location_id=result.location_id,
                 changes=audit.diff(result) | {"values": len(data["values"])})  # fmt: skip
    events.publish(session, ResultRecorded(assessment_result_id=result.id, client_id=client.id), result.id)
    session.flush()
    return result_view(session, result)


def update_result(session: Session, principal: Principal, result_id: UUID, data: dict) -> dict:
    """Edit the date, note or values; the denormalised time on value rows moves with the result."""
    result = _result(session, principal, result_id, RECORD)
    for key in ("recorded_at", "note"):
        if key in data:
            setattr(result, key, data[key])
    changes = audit.diff(result)
    if data.get("values") is not None:
        _write_values(session, result, data["values"])
        changes["values"] = True
    elif "recorded_at" in data:  # keep the stored values (even on a since-archived field); move their time
        session.execute(update(AssessmentResultValue).where(AssessmentResultValue.assessment_result_id == result.id)
                        .values(recorded_at=result.recorded_at))  # fmt: skip
    audit.record(session, RECORD, result, location_id=result.location_id, changes=changes)
    session.flush()
    return result_view(session, result)


def delete_result(session: Session, principal: Principal, result_id: UUID) -> None:
    """Hard delete (data-model 5.3); the audit row keeps the trail, without the values."""
    result = _result(session, principal, result_id, READ)
    if result.location_id is None:
        authorize_tenant_wide(principal, DELETE)
    else:
        authorize(principal, DELETE, location_id=result.location_id)
    audit.record(session, DELETE, result, location_id=result.location_id, changes={"deleted": True})
    session.delete(result)
    session.flush()


# --- history (FIT-03) ----------------------------------------------------------------------------------------


def _series(session: Session, client_id: UUID, field_ids: list[UUID] | None, template_id: UUID | None,
            starts: datetime | None, ends: datetime | None, visible_only: bool = False) -> list[dict]:  # fmt: skip
    v, f = AssessmentResultValue, AssessmentField
    stmt = select(v, f).join(f, f.id == v.assessment_field_id).where(v.client_id == client_id)
    if field_ids:
        stmt = stmt.where(v.assessment_field_id.in_(field_ids))
    if template_id is not None:
        stmt = stmt.where(f.assessment_template_id == template_id)
    if starts is not None:
        stmt = stmt.where(v.recorded_at >= starts)
    if ends is not None:
        stmt = stmt.where(v.recorded_at <= ends)
    if visible_only:
        stmt = stmt.where(f.is_client_visible)
    grouped: dict[UUID, tuple[AssessmentField, list]] = {}
    for value, field in session.execute(stmt.order_by(f.sort_order, f.name, v.recorded_at.desc(), v.id)):
        grouped.setdefault(field.id, (field, []))[1].append(value)
    return [
        {"field": field, "assessment_field_id": field.id,
         "points": [{"result_id": p.assessment_result_id, "recorded_at": p.recorded_at, "value": p.value} for p in rows]}
        | progress.summary([(p.recorded_at, p.value) for p in rows], field.better_direction)
        for field, rows in grouped.values()
    ]  # fmt: skip


def get_series(session: Session, principal: Principal, client_id: UUID, *, field_ids: list[UUID] | None = None,
               template_id: UUID | None = None, starts: datetime | None = None, ends: datetime | None = None) -> dict:  # fmt: skip
    clients.service.load(session, principal, client_id, READ)
    return {"series": _series(session, client_id, field_ids, template_id, starts, ends)}


# --- portal (FIT-05) -----------------------------------------------------------------------------------------


def _portal_client(session: Session, principal: Principal, client_id: UUID | None) -> UUID:
    """The client the identity acts for (default: its own record), with sharing switched on; otherwise 404."""
    if principal.kind != "client" or principal.identity_id is None or not _settings(session).is_portal_sharing_enabled:
        raise NotFound()
    if client_id is None:
        if not (own := clients.service.client_ids_for_identity(session, principal.identity_id)):
            raise NotFound()
        client_id = own[0]
    if clients.households.can_act_for(session, principal.identity_id, client_id, "assessments") is None:
        raise NotFound()
    return client_id


def _names(session: Session, field_ids: set[UUID]) -> dict[UUID, tuple[AssessmentField, str]]:
    rows = session.execute(
        select(AssessmentField, AssessmentTemplate.name)
        .join(AssessmentTemplate, AssessmentTemplate.id == AssessmentField.assessment_template_id)
        .where(AssessmentField.id.in_(field_ids))
    )  # fmt: skip
    return {field.id: (field, name) for field, name in rows}


def portal_list_results(session: Session, principal: Principal, client_id: UUID | None, query: ListQuery) -> dict:
    """Entries of the acted-for client, client-visible fields only; an entry with none of them is left out."""
    subject = _portal_client(session, principal, client_id)
    visible = select(AssessmentResultValue.assessment_result_id).join(
        AssessmentField, AssessmentField.id == AssessmentResultValue.assessment_field_id
    ).where(AssessmentField.is_client_visible)  # fmt: skip
    stmt = select(AssessmentResult).where(AssessmentResult.client_id == subject, AssessmentResult.id.in_(visible))
    filters = {k: v for k, v in query.filters.items() if k != "client_id"}
    page = paginate(
        session, stmt, ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters),
        id_column=AssessmentResult.id, sort_fields={"recorded_at": AssessmentResult.recorded_at},
        default_sort="-recorded_at",
    )  # fmt: skip
    values = {r.id: _values(session, r) for r in page["data"]}
    names = _names(session, {v.assessment_field_id for rows in values.values() for v in rows})
    data = []
    for result in page["data"]:
        shown = [
            {"assessment_field_id": v.assessment_field_id, "field_name": names[v.assessment_field_id][0].name,
             "template_name": names[v.assessment_field_id][1], "unit_label": names[v.assessment_field_id][0].unit_label,
             "value": v.value}
            for v in values[result.id] if names[v.assessment_field_id][0].is_client_visible
        ]  # fmt: skip
        data.append({"id": result.id, "recorded_at": result.recorded_at, "values": shown})
    return page | {"data": data}


def portal_bests(session: Session, principal: Principal, client_id: UUID | None) -> list[dict]:
    """Personal best and latest value per client-visible field the client has a value for."""
    subject = _portal_client(session, principal, client_id)
    rows = _series(session, subject, None, None, None, None, visible_only=True)
    names = _names(session, {r["assessment_field_id"] for r in rows})
    found = []
    for row in rows:
        field, template_name = names[row["assessment_field_id"]]
        best_at = next((p["recorded_at"] for p in row["points"] if p["value"] == row["best_value"]), None)
        found.append({
            "assessment_field_id": field.id, "field_name": field.name, "template_name": template_name,
            "unit_label": field.unit_label, "better_direction": field.better_direction, "best_value": row["best_value"],
            "best_recorded_at": best_at if row["best_value"] is not None else None,
            "latest_value": row["latest_value"], "latest_recorded_at": row["points"][0]["recorded_at"],
        })  # fmt: skip
    return found
