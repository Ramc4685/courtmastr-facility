"""Fitness assessment reports (phase 12 chip D): each client's results over time per field (FIT-03) and the
summary per category and field across clients (FIT-04). Values are compared on each field's better direction."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.reporting import views as v
from app.modules.reporting.registry import (
    CLIENT,
    MAX_ROWS,
    Col,
    RangeParams,
    ReportSpec,
    Scope,
    _between,
    _key,
    _loc,
    _pct,
    too_large,
)


class AssessmentParams(RangeParams):
    assessment_template_ids: list[UUID] | None = None


class AssessmentHistoryParams(AssessmentParams):
    client_ids: list[UUID] | None = None


def _values(session: Session, p: AssessmentParams, scope: Scope) -> list[dict]:
    """Every value recorded in the period, per client and field in recording order."""
    a = v.assessment_value.c
    where = [_between(a.recorded_on, p, scope)]
    if p.assessment_template_ids:
        where.append(a.assessment_template_id.in_(p.assessment_template_ids))
    client_ids = getattr(p, "client_ids", None)  # history only
    if client_ids:
        where.append(a.client_id.in_(client_ids))
    found = [dict(r._mapping) for r in session.execute(_loc(
        select(a.client_id, a.client_name, a.assessment_field_id, a.template_name, a.field_name, a.unit_label,
               a.better_direction, a.decimal_places, a.recorded_on, a.value)
        .where(*where).order_by(a.template_sort, a.template_name, a.field_sort, a.field_name, a.client_name,
                                a.client_id, a.recorded_at, a.assessment_result_value_id),
        v.assessment_value, scope,
    ))]  # fmt: skip
    if len(found) > MAX_ROWS:
        raise too_large()  # values are regrouped below
    for row in found:
        row["value"] = round(float(row["value"]), row["decimal_places"])
    return found


def _groups(values: Iterable[dict], *keys: str) -> dict[tuple, list[dict]]:
    grouped: dict[tuple, list[dict]] = {}
    for row in values:
        grouped.setdefault(tuple(row[k] for k in keys), []).append(row)
    return grouped


def _gain(first: float, last: float, direction: str) -> float | None:
    """The change from first to last, positive when it moved the better way; none without a direction."""
    return None if direction == "none" else (last - first if direction == "higher" else first - last)


def _best(values: list[float], direction: str) -> float | None:
    return None if direction == "none" else (max(values) if direction == "higher" else min(values))


def _history(session: Session, p: AssessmentHistoryParams, scope: Scope) -> dict:
    values = _values(session, p, scope)
    rows, details = [], []
    for (client_id, field_id), items in _groups(values, "client_id", "assessment_field_id").items():
        first, last, places = items[0], items[-1], items[0]["decimal_places"]
        group = _key(client_id, field_id)
        rows.append({
            "group_key": group, "client_name": first["client_name"], "template_name": first["template_name"],
            "field_name": first["field_name"], "unit_label": first["unit_label"], "value_count": len(items),
            "first_on": first["recorded_on"], "first_value": first["value"], "last_on": last["recorded_on"],
            "last_value": last["value"], "change": round(last["value"] - first["value"], places),
            "best_value": _best([i["value"] for i in items], first["better_direction"]),
        })  # fmt: skip
        details += [{"group_key": group, "recorded_on": i["recorded_on"], "field_name": i["field_name"],
                     "value": i["value"], "unit_label": i["unit_label"]} for i in items]  # fmt: skip
    totals = {"client_count": len({r["client_id"] for r in values}), "value_count": len(values)}
    return {"rows": rows, "totals": totals, "details": details}


def _summary(session: Session, p: AssessmentParams, scope: Scope) -> dict:
    values = _values(session, p, scope)
    rows, details = [], []
    for (field_id,), items in _groups(values, "assessment_field_id").items():
        head, places, direction = items[0], items[0]["decimal_places"], items[0]["better_direction"]
        group = _key(field_id)
        firsts, lasts, changes, gains = [], [], [], []
        for (_client,), mine in _groups(items, "client_id").items():
            first, last = mine[0], mine[-1]
            firsts.append(first["value"])
            lasts.append(last["value"])
            change = round(last["value"] - first["value"], places) if len(mine) > 1 else None
            if change is not None:
                changes.append(change)
                gains.append(_gain(first["value"], last["value"], direction))
            details.append({"group_key": group, "client_name": first["client_name"], "first_on": first["recorded_on"],
                            "first_value": first["value"], "last_on": last["recorded_on"], "last_value": last["value"],
                            "value_count": len(mine), "change": change})  # fmt: skip
        numbers = [i["value"] for i in items]
        improved = sum(1 for g in gains if g is not None and g > 0)
        rows.append({
            "group_key": group, "template_name": head["template_name"], "field_name": head["field_name"],
            "unit_label": head["unit_label"], "better_direction": direction, "client_count": len(firsts),
            "value_count": len(items), "min_value": min(numbers), "max_value": max(numbers),
            "average_value": round(sum(numbers) / len(numbers), places),
            "start_average": round(sum(firsts) / len(firsts), places), "end_average": round(sum(lasts) / len(lasts), places),
            "compared_count": len(changes),
            "average_change": round(sum(changes) / len(changes), places) if changes else None,
            "improved_count": improved if direction != "none" else None,
            "improved_pct": _pct(improved, len(changes)) if direction != "none" else None,
        })  # fmt: skip
    totals = {"client_count": len({r["client_id"] for r in values}), "value_count": len(values)}
    return {"rows": rows, "totals": totals, "details": details}


_TOTALS = (Col("client_count", "Clients", "count"), Col("value_count", "Values", "count"))

SPECS = (
    ReportSpec(
        "assessment_history", "Assessment history",
        "Each client's assessment results in the period per field: first and latest value, the change and the best "
        "value on the field's better direction, with every recorded value as the detail.",
        "fitness", CLIENT, "recorded_date", AssessmentHistoryParams,
        (Col("client_name", "Client"), Col("template_name", "Category"), Col("field_name", "Field"),
         Col("unit_label", "Unit"), Col("value_count", "Values", "count"), Col("first_on", "First", "date"),
         Col("first_value", "First value", "number"), Col("last_on", "Latest", "date"),
         Col("last_value", "Latest value", "number"), Col("change", "Change", "number"),
         Col("best_value", "Best", "number")),
        _TOTALS, _history,
        (Col("recorded_on", "Date", "date"), Col("field_name", "Field"), Col("value", "Value", "number"),
         Col("unit_label", "Unit")),
        ("FIT-03",),
    ),
    ReportSpec(
        "assessment_summary", "Assessment summary",
        "Per category and field across clients: values recorded, lowest, highest and average, the average of each "
        "client's first and latest value in the period, and how many clients with two or more values improved on "
        "the field's better direction.",
        "fitness", CLIENT, "recorded_date", AssessmentParams,
        (Col("template_name", "Category"), Col("field_name", "Field"), Col("unit_label", "Unit"),
         Col("better_direction", "Better"), Col("client_count", "Clients", "count"),
         Col("value_count", "Values", "count"), Col("min_value", "Lowest", "number"),
         Col("max_value", "Highest", "number"), Col("average_value", "Average", "number"),
         Col("start_average", "Average at start", "number"), Col("end_average", "Average at end", "number"),
         Col("compared_count", "Clients compared", "count"), Col("average_change", "Average change", "number"),
         Col("improved_count", "Improved", "count"), Col("improved_pct", "Improved %", "pct")),
        _TOTALS, _summary,
        (Col("client_name", "Client"), Col("first_on", "First", "date"), Col("first_value", "First value", "number"),
         Col("last_on", "Latest", "date"), Col("last_value", "Latest value", "number"),
         Col("value_count", "Values", "count"), Col("change", "Change", "number")),
        ("FIT-04",),
    ),
)  # fmt: skip
