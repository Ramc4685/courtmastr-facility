"""Reports known only by name in the discovery docs (RPT-41) that existing views already answer: check-in details
(also the insurer visit export: flag the participating clients with a client category and filter on it) and new
memberships. The full name-to-key map is in docs/status/15-reporting.md."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.reporting import views as v
from app.modules.reporting.registry import ATTENDANCE, MEMBERSHIP, Col, RangeParams, ReportSpec, Scope, _between, _loc


class CheckInDetailParams(RangeParams):
    client_category_ids: list[UUID] | None = None
    check_in_station_ids: list[UUID] | None = None
    include_denied: bool = False


def _check_in_details(session: Session, p: CheckInDetailParams, scope: Scope) -> dict:
    k, c = v.check_in.c, v.client.c
    where = [_between(k.check_in_on, p, scope)]
    if not p.include_denied:
        where.append(k.result != "denied")
    if p.client_category_ids:
        where.append(c.client_category_id.in_(p.client_category_ids))
    if p.check_in_station_ids:
        where.append(k.check_in_station_id.in_(p.check_in_station_ids))
    query = (
        select(k.check_in_on, k.check_in_hour, c.client_name, c.member_number, c.client_category_name,
               k.membership_type_name, k.station_name, k.channel, k.result)
        .select_from(v.check_in).join(v.client, c.client_id == k.client_id)
        .where(*where).order_by(k.check_in_on, k.check_in_hour, c.client_name, k.check_in_id)
    )  # fmt: skip
    rows = [dict(r._mapping) for r in session.execute(_loc(query, v.check_in, scope))]
    return {"rows": rows, "totals": {"check_in_count": len(rows)}, "details": None}


class NewMembershipParams(RangeParams):
    membership_type_ids: list[UUID] | None = None


def _new_memberships(session: Session, p: NewMembershipParams, scope: Scope) -> dict:
    t = v.membership_term.c
    where = [t.status != "cancelled", _between(t.start_on, p, scope)]
    if p.membership_type_ids:
        where.append(t.membership_type_id.in_(p.membership_type_ids))
    query = select(
        t.start_on, t.client_name, t.contract_name, t.membership_type_name, t.status, t.sold_by_name,
        t.contract_value_minor,
    ).where(*where).order_by(t.start_on, t.client_name, t.membership_contract_id)  # fmt: skip
    rows = [dict(r._mapping) for r in session.execute(_loc(query, v.membership_term, scope))]
    value = sum(r["contract_value_minor"] or 0 for r in rows)
    return {"rows": rows, "totals": {"contract_count": len(rows), "value_minor": value}, "details": None}


SPECS = (
    ReportSpec(
        "check_in_details", "Check-in details",
        "Every check-in in the period with the client, category, membership, station and result, in the location's "
        "local time. Filter on a client category to export the visits of one group, such as an insurer's programme.",
        "clients", ATTENDANCE, "check_in_date", CheckInDetailParams,
        (Col("check_in_on", "Date", "date"), Col("check_in_hour", "Hour", "number"), Col("client_name", "Client"),
         Col("member_number", "Member number"), Col("client_category_name", "Category"),
         Col("membership_type_name", "Membership"), Col("station_name", "Station"), Col("channel", "Channel"),
         Col("result", "Result")),
        (Col("check_in_count", "Check-ins", "count"),),
        _check_in_details, None, ("RPT-41", "CHK-19"),
    ),
    ReportSpec(
        "new_memberships", "New memberships",
        "Contracts starting in the period, with who sold them and their value. Cancelled contracts are left out.",
        "membership", MEMBERSHIP, "start_date", NewMembershipParams,
        (Col("start_on", "Starts", "date"), Col("client_name", "Member"), Col("contract_name", "Membership"),
         Col("membership_type_name", "Type"), Col("status", "Status"), Col("sold_by_name", "Sold by"),
         Col("contract_value_minor", "Value", "money")),
        (Col("contract_count", "Contracts", "count"), Col("value_minor", "Value", "money")),
        _new_memberships, None, ("RPT-41", "MEM-21"),
    ),
)  # fmt: skip
