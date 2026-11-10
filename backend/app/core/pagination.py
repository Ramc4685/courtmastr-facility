"""Keyset pagination, flat filters and sort allow-lists for list endpoints (overview 3.14)."""

import base64
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import Query, Request
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, ValidationFailed

_RESERVED = {"limit", "cursor", "sort", "include", "q"}
_FILTER = re.compile(r"(\w+)(?:\[(gte|gt|lte|lt|in|ne)\])?")
_OPS = {
    None: lambda c, v: c == v,
    "ne": lambda c, v: c != v,
    "gte": lambda c, v: c >= v,
    "gt": lambda c, v: c > v,
    "lte": lambda c, v: c <= v,
    "lt": lambda c, v: c < v,
}


@dataclass
class ListQuery:
    limit: int = 50
    cursor: str | None = None
    sort: str | None = None
    include_total: bool = False
    q: str | None = None
    filters: dict[str, str] = field(default_factory=dict)


def list_query(
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    cursor: str | None = Query(None, description="Opaque keyset cursor from page.next_cursor"),
    sort: str | None = Query(None, description="Comma-separated allow-listed fields; - prefix for descending"),
    include: str | None = Query(None, description="`total` adds page.total"),
    q: str | None = Query(None, description="Free-text search"),
) -> ListQuery:
    """Standard list parameters; everything else in the query string is a filter (`field` or `field[op]`)."""
    filters = {k: v for k, v in request.query_params.items() if k not in _RESERVED}
    return ListQuery(limit, cursor, sort, "total" in (include or "").split(","), q, filters)


def _coerce(column, raw: Any, name: str) -> Any:
    if not isinstance(raw, str):
        return raw
    kind = column.type.python_type
    try:
        if kind is bool:
            if raw.lower() not in ("true", "false"):
                raise ValueError(raw)
            return raw.lower() == "true"
        if kind is UUID:
            return UUID(raw)
        if kind is datetime:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if kind is date:
            return date.fromisoformat(raw)
        if kind is int:
            return int(raw)
    except ValueError:
        raise ValidationFailed(f"Invalid value for {name}", pointer=f"/{name}") from None
    return raw


def _bad_request(detail: str) -> DomainError:
    return DomainError(detail, status=400, code="bad-request")


def apply_filters(stmt: Select, filters: Mapping[str, str], allowed: Mapping[str, Any]) -> Select:
    for name, raw in filters.items():
        match = _FILTER.fullmatch(name)
        if not match or match[1] not in allowed:
            raise _bad_request(f"Unknown query parameter: {name}")
        column, op = allowed[match[1]], match[2]
        if op == "in":
            stmt = stmt.where(column.in_([_coerce(column, part, name) for part in raw.split(",")]))
        else:
            stmt = stmt.where(_OPS[op](column, _coerce(column, raw, name)))
    return stmt


def _order(sort: str, allowed: Mapping[str, Any], id_column) -> list[tuple[Any, bool]]:
    order: list[tuple[Any, bool]] = []
    for part in filter(None, sort.split(",")):
        name, descending = part.lstrip("-"), part.startswith("-")
        if name not in allowed:
            raise _bad_request(f"Cannot sort by {name}")
        order.append((allowed[name], descending))
    return [*order, (id_column, False)]  # id (UUIDv7) is always the tiebreaker


def _after(order: list[tuple[Any, bool]], values: list[Any]):
    """Keyset predicate for mixed directions: (a, b) after (va, vb) is a > va OR (a = va AND b > vb)."""
    clauses = []
    for i, (column, descending) in enumerate(order):
        equal = [c == v for (c, _), v in zip(order[:i], values[:i], strict=True)]
        clauses.append(and_(*equal, column < values[i] if descending else column > values[i]))
    return or_(*clauses)


def paginate(
    session: Session,
    stmt: Select,
    query: ListQuery,
    *,
    id_column,
    sort_fields: Mapping[str, Any],
    default_sort: str = "",
    filter_fields: Mapping[str, Any] | None = None,
    search: Sequence[Any] = (),
) -> dict[str, Any]:
    """Run `stmt` (whose first selected entity is the row to return) as one keyset page.

    Sort columns must be NOT NULL. Returns {"data": [...], "page": {"next_cursor", "has_more"[, "total"]}}.
    """
    stmt = apply_filters(stmt, query.filters, filter_fields or {})
    if query.q and search:
        stmt = stmt.where(or_(*(column.icontains(query.q, autoescape=True) for column in search)))
    page: dict[str, Any] = {}
    if query.include_total:
        page["total"] = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))

    order = _order(query.sort or default_sort, sort_fields, id_column)
    if query.cursor:
        try:
            raw = json.loads(base64.urlsafe_b64decode(query.cursor.encode()))
            values = [_coerce(c, v, "cursor") for (c, _), v in zip(order, raw, strict=True)]
        except (ValueError, TypeError, DomainError):
            raise _bad_request("Invalid cursor for this sort") from None
        stmt = stmt.where(_after(order, values))
    stmt = stmt.add_columns(*(column for column, _ in order))
    stmt = stmt.order_by(*(c.desc() if descending else c.asc() for c, descending in order))
    rows = session.execute(stmt.limit(query.limit + 1)).all()

    has_more = len(rows) > query.limit
    rows = rows[: query.limit]
    next_cursor = None
    if has_more:
        last = list(rows[-1][-len(order) :])
        next_cursor = base64.urlsafe_b64encode(json.dumps(last, default=str).encode()).decode()
    return {"data": [row[0] for row in rows], "page": {"next_cursor": next_cursor, "has_more": has_more, **page}}
