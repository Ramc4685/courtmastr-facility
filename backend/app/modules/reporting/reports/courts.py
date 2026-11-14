"""Court use (pilot fit CIRQT, scenario i): utilisation measured against the time a court could be booked, with
changeover, staff blocks and league or program use told apart from rented play, split by the peak window the
owner configured, and revenue per court-hour. Rules are in the module README ("Court use").

The work is one SQL statement per run over the `rpt_court*` views (migration 2011). Per court and local day it
builds multiranges: available time (facility hours of that weekday in the location's zone, narrowed by the
court's own windows when it has any, minus whole-location closures), the peak bands of the rental types the court
offers, and the court's holds including those of its halves. Multirange union counts a physical minute once and
the zone conversion makes a 23 or 25 hour day come out right. Python only adds the court-days up to the grain."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.reporting.registry import (
    ATTENDANCE,
    FINANCIAL,
    MAX_ROWS,
    Col,
    RangeParams,
    ReportSpec,
    Scope,
    _key,
    too_large,
)

PROGRAM = "program"  # the key of league, class and program use (bookings that are not rentals or blocks)
PROGRAM_LABEL = "League and programs"
SOURCES = {True: "Court windows", False: "Opening hours"}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class CourtParams(RangeParams):
    resource_ids: list[UUID] | None = Field(None, description="Courts to include; empty means every court")
    resource_group_ids: list[UUID] | None = Field(None, description="Court groups to include")


class CourtUseParams(CourtParams):
    grain: Literal["day", "week", "month"] = Field("day", description="One row per court (or group) and period")
    group_by: Literal["court", "court_group", "sport"] = Field("court", description="Rows per court, group or sport")


# --- SQL -----------------------------------------------------------------------------------------------------


def _min(mr: str) -> str:
    """Whole minutes in a multirange (bookings, hours and bands are minute-aligned)."""
    return f"(SELECT coalesce(sum(extract(epoch FROM upper(x) - lower(x))), 0)::bigint / 60 FROM unnest({mr}) x)"


def _wall(day: str, clock: str, zone: str = "c.time_zone") -> str:
    """A local date and wall time (24:00 is the next midnight) as an instant in the court's zone."""
    return f"((({day})::date + {clock}) AT TIME ZONE {zone})"


def _fires(band: str, day: str) -> str:
    """A peak band applies on a local day: its weekdays (none means every day) and its date limits."""
    return (f"(coalesce(cardinality({band}.weekdays), 0) = 0 OR extract(isodow FROM {day})::int = ANY({band}.weekdays))"
            f" AND ({band}.starts_on IS NULL OR {day} >= {band}.starts_on)"
            f" AND ({band}.ends_on IS NULL OR {day} <= {band}.ends_on)")  # fmt: skip


def _days(rng: str, zone: str) -> str:
    """The local dates a range touches (its upper bound is exclusive), for an equality join on the day."""
    return (f"generate_series((lower({rng}) AT TIME ZONE {zone})::date::timestamp, "
            f"((upper({rng}) - interval '1 microsecond') AT TIME ZONE {zone})::date::timestamp, interval '1 day')")  # fmt: skip


def _split(src: str, group: str, total: str, weight: str, order: str) -> str:
    """Largest remainder in SQL: `total` (the same on every row of a `group`) shared over the group's rows in
    proportion to `weight`, in whole minor units that always sum to the total; the leftover units go to the largest
    fractions, ties by `order`. A negative total (a reversal) is split as its size, so it mirrors its charge."""
    return f"""SELECT q.*, (sign(q.{total}) * (q.lo + CASE WHEN row_number() OVER (PARTITION BY {group}
                   ORDER BY q.raw - q.lo DESC, {order}) <= abs(q.{total}) - sum(q.lo) OVER (PARTITION BY {group})
                   THEN 1 ELSE 0 END))::bigint AS part
        FROM (SELECT p.*, floor(p.raw) AS lo FROM (
            SELECT s.*, CASE WHEN sum({weight}) OVER (PARTITION BY {group}) = 0 THEN 0
                             ELSE abs(s.{total})::numeric * {weight} / sum({weight}) OVER (PARTITION BY {group}) END AS raw
            FROM {src} s) p) q"""


EMPTY = "tstzmultirange()"


def _base(p: CourtParams, scope: Scope) -> tuple[str, dict]:
    """The shared CTEs: per court and local day its available, peak and used multiranges, and revenue rows."""
    where, args = ["true"], dict[str, object]({"from_on": p.from_on, "to_on": p.to_on})
    if scope.location_ids is not None:
        where.append("location_id = ANY(CAST(:locations AS uuid[]))")
        args["locations"] = list(scope.location_ids)
    courts = list(where)
    if p.resource_ids:
        courts.append("court_id = ANY(CAST(:courts AS uuid[]))")
        args["courts"] = p.resource_ids
    if p.resource_group_ids:
        courts.append("court_group_id = ANY(CAST(:groups AS uuid[]))")
        args["groups"] = p.resource_group_ids
    ranges = scope.day_ranges or {}
    args |= {"o_loc": list(ranges), "o_from": [r[0] for r in ranges.values()], "o_to": [r[1] for r in ranges.values()]}
    revenue = "(SELECT * FROM rpt_court_revenue WHERE charge_id IN (SELECT charge_id FROM rv_charge))"
    items = _split(revenue, "charge_id", "net_minor", "s.item_weight", "q.rental_booking_charge_item_id")
    band = f"tstzrange({_wall('z.day', 'b.start_time', 'z.time_zone')}, {_wall('z.day', 'b.end_time', 'z.time_zone')})"
    opening = f"tstzrange({_wall('d.day', 'fh.opens_time')}, {_wall('d.day', 'fh.closes_time')})"
    near = "tstzrange(CAST(s.from_on - 1 AS timestamp) AT TIME ZONE 'UTC', CAST(s.to_on + 2 AS timestamp) AT TIME ZONE 'UTC')"
    sql = f"""
    WITH span AS (
        SELECT l.location_id, l.time_zone, coalesce(o.from_on, CAST(:from_on AS date)) AS from_on,
               coalesce(o.to_on, CAST(:to_on AS date)) AS to_on
        FROM (SELECT DISTINCT location_id, time_zone FROM rpt_court WHERE {" AND ".join(where)}) l
        LEFT JOIN unnest(CAST(:o_loc AS uuid[]), CAST(:o_from AS date[]), CAST(:o_to AS date[]))
             AS o(location_id, from_on, to_on) ON o.location_id = l.location_id
    ),
    court AS (SELECT * FROM rpt_court WHERE {" AND ".join(courts)}),
    rv_charge AS (  -- the charges paying for play on a chosen court near the span
        SELECT DISTINCT v.charge_id FROM rpt_court_revenue v JOIN court c ON c.court_id = v.court_id
        JOIN span s ON s.location_id = c.location_id WHERE v.played && {near}
    ),
    rv_item AS (  -- each charge's net over all its items (any court, any date), so a part never depends on the ask
        SELECT x.court_id, x.rental_type_id, x.played, x.charge_id, x.rental_booking_charge_item_id AS item_id,
               x.part AS item_minor
        FROM ({items}) x
    ),
    zday AS (  -- every local day needed: the span's, and the days of the occurrences it is paid for
        SELECT location_id, time_zone, day, bool_or(in_span) AS in_span,
               tstzrange(day::timestamp AT TIME ZONE time_zone, (day + 1)::timestamp AT TIME ZONE time_zone) AS whole
        FROM (SELECT s.location_id, s.time_zone, g::date AS day, true AS in_span FROM span s
              CROSS JOIN generate_series(s.from_on::timestamp, s.to_on::timestamp, interval '1 day') g
              UNION ALL
              SELECT c.location_id, c.time_zone, g::date, false FROM rv_item i JOIN court c ON c.court_id = i.court_id
              CROSS JOIN {_days("i.played", "c.time_zone")} g) d
        GROUP BY location_id, time_zone, day
    ),
    court_peak AS (  -- the union of the peak bands of the rental types a court offers, once per court and day
        SELECT t.court_id, z.day,
               range_agg({band}) AS mr
        FROM court c JOIN zday z ON z.location_id = c.location_id
        JOIN rpt_court_rental_type t ON t.court_id = c.court_id
        JOIN rpt_peak_band b ON b.rental_type_id = t.rental_type_id AND {_fires("b", "z.day")}
        GROUP BY t.court_id, z.day
    ),
    day AS (
        SELECT c.court_id, c.location_id, c.time_zone, c.has_windows, z.day, z.whole
        FROM court c JOIN zday z ON z.location_id = c.location_id AND z.in_span
    ),
    hold AS (
        SELECT h.* FROM rpt_court_hold h JOIN span s ON s.location_id = h.location_id
        WHERE h.court_id IN (SELECT court_id FROM court) AND h.during && {near}
    ),
    avail AS (
        SELECT d.court_id, d.location_id, d.day, d.whole, d.time_zone,
               ((CASE WHEN fh.weekday IS NULL THEN tstzmultirange(d.whole)
                      WHEN fh.is_closed OR fh.opens_time IS NULL OR fh.closes_time IS NULL THEN {EMPTY}
                      ELSE tstzmultirange({opening})
                 END) * (CASE WHEN d.has_windows THEN coalesce(win.mr, {EMPTY}) ELSE tstzmultirange(d.whole) END)
               ) - coalesce(shut.mr, {EMPTY}) AS open_mr,
               coalesce(pk.mr, {EMPTY}) AS peak_mr
        FROM day d
        JOIN court c ON c.court_id = d.court_id
        LEFT JOIN rpt_facility_hours fh ON fh.location_id = d.location_id AND fh.weekday = extract(isodow FROM d.day)
        LEFT JOIN LATERAL (
            SELECT range_agg(tstzrange({_wall("d.day", "w.start_time")}, {_wall("d.day", "w.end_time")})) AS mr
            FROM rpt_court_window w
            WHERE w.court_id = d.court_id AND d.day >= w.starts_on AND (w.ends_on IS NULL OR d.day <= w.ends_on)
              AND extract(isodow FROM d.day)::int = ANY(w.weekdays) AND ((d.day - w.starts_on) / 7) % w.interval_weeks = 0
        ) win ON true
        LEFT JOIN LATERAL (
            SELECT range_agg(x.during) AS mr FROM rpt_closure x WHERE x.location_id = d.location_id AND x.during && d.whole
        ) shut ON true
        LEFT JOIN court_peak pk ON pk.court_id = d.court_id AND pk.day = d.day
    ),
    held AS (  -- each hold cut at the local days it touches (an equality join, not days times holds)
        SELECT h.court_id, z.day,
               coalesce(range_agg(h.played * z.whole) FILTER (WHERE h.use_kind = 'rental'), {EMPTY}) AS rental,
               coalesce(range_agg(h.played * z.whole) FILTER (WHERE h.use_kind = 'program'), {EMPTY}) AS program,
               coalesce(range_agg(h.during * z.whole) FILTER (WHERE h.use_kind = 'block'), {EMPTY}) AS block,
               coalesce(range_agg(h.during * z.whole) FILTER (WHERE h.use_kind <> 'block'), {EMPTY}) AS booked
        FROM hold h JOIN court c ON c.court_id = h.court_id
        CROSS JOIN {_days("h.during", "c.time_zone")} g
        JOIN zday z ON z.location_id = c.location_id AND z.day = g::date AND z.in_span
        GROUP BY h.court_id, z.day
    ),
    base AS (  -- each minute in one category: rental, then league or program, then a staff block, then changeover
        SELECT a.court_id, a.day, a.whole, a.open_mr, a.peak_mr, coalesce(u.rental, {EMPTY}) AS r,
               coalesce(u.program, {EMPTY}) - coalesce(u.rental, {EMPTY}) AS g,
               coalesce(u.block, {EMPTY}) - coalesce(u.rental, {EMPTY}) - coalesce(u.program, {EMPTY}) AS b,
               coalesce(u.booked, {EMPTY}) - coalesce(u.rental, {EMPTY}) - coalesce(u.program, {EMPTY})
                   - coalesce(u.block, {EMPTY}) AS f
        FROM avail a LEFT JOIN held u ON u.court_id = a.court_id AND u.day = a.day
    ),
    rv_seg AS (  -- an item's occurrence cut at local days and at the court's peak bands
        SELECT i.charge_id, i.item_id, i.court_id, coalesce(i.rental_type_id::text, '{PROGRAM}') AS sport,
               i.item_minor, z.day, z.in_span, k.peak, {_min("k.mr")} AS minutes
        FROM rv_item i JOIN court c ON c.court_id = i.court_id
        CROSS JOIN {_days("i.played", "c.time_zone")} g
        JOIN zday z ON z.location_id = c.location_id AND z.day = g::date
        LEFT JOIN court_peak pk ON pk.court_id = i.court_id AND pk.day = z.day
        CROSS JOIN LATERAL (VALUES (true, tstzmultirange(i.played * z.whole) * coalesce(pk.mr, {EMPTY})),
                                   (false, tstzmultirange(i.played * z.whole) - coalesce(pk.mr, {EMPTY}))) k(peak, mr)
    ),
    rev AS (  -- each item's part over its segments by rented minutes, dated by the local day it is played
        SELECT x.court_id, x.day, x.sport, sum(x.part) AS net_minor, coalesce(sum(x.part) FILTER (WHERE x.peak), 0) AS peak_minor
        FROM ({_split("rv_seg", "item_id, charge_id", "item_minor", "s.minutes", "q.day, q.peak")}) x
        WHERE x.in_span GROUP BY x.court_id, x.day, x.sport
    )"""
    return sql, args


def _measures(played: str, buffer: str) -> str:
    """Minutes columns of one court-day (`b0`): play and changeover inside the available time, play outside it."""
    return ", ".join((
        f"{_min('b0.open_mr')} AS available", f"{_min('b0.open_mr * b0.peak_mr')} AS peak_available",
        f"{_min(f'({played}) * b0.open_mr')} AS played", f"{_min(f'({played}) * b0.open_mr * b0.peak_mr')} AS peak_played",
        f"{_min(f'({played}) - b0.open_mr')} AS outside", f"{_min(f'({buffer}) * b0.open_mr')} AS buffer",
    ))  # fmt: skip


def _run(session: Session, sql: str, args: dict) -> list:
    found = session.execute(text(sql + f" LIMIT {MAX_ROWS + 1}"), args).all()
    if len(found) > MAX_ROWS:
        raise too_large()
    return list(found)


def _court_days(session: Session, p: CourtParams, scope: Scope) -> list:
    base, args = _base(p, scope)
    sql = f"""{base}
    SELECT b0.court_id, c.court_name, c.court_group_id, c.court_group_name, c.sort_order, c.has_windows, b0.day,
           {_measures("b0.r + b0.g", "b0.f")},
           {_min("b0.r * b0.open_mr")} AS rental, {_min("b0.g * b0.open_mr")} AS program,
           {_min("b0.b * b0.open_mr")} AS blocked,
           coalesce(rv.net_minor, 0) AS revenue_minor, coalesce(rv.peak_minor, 0) AS peak_revenue_minor
    FROM base b0 JOIN court c ON c.court_id = b0.court_id
    LEFT JOIN (SELECT court_id, day, sum(net_minor) AS net_minor, sum(peak_minor) AS peak_minor FROM rev
               GROUP BY court_id, day) rv ON rv.court_id = b0.court_id AND rv.day = b0.day
    ORDER BY b0.day, c.sort_order, c.court_name, b0.court_id"""
    return _run(session, sql, args)


def _sport_days(session: Session, p: CourtParams, scope: Scope) -> list:
    """Per sport (rental type, or league and programs) and day: the play of that sport against the available time
    of the courts that offer it (league and programs: every court). Sports may overlap one another on a court."""
    base, args = _base(p, scope)
    sql = f"""{base},
    offer AS (
        SELECT t.court_id, t.rental_type_id::text AS sport, t.rental_type_name AS sport_name
        FROM rpt_court_rental_type t WHERE t.court_id IN (SELECT court_id FROM court)
        UNION ALL SELECT court_id, '{PROGRAM}', NULL FROM court
    ),
    sport_held AS (
        SELECT d.court_id, d.day, coalesce(h.rental_type_id::text, '{PROGRAM}') AS sport,
               range_agg(h.played * d.whole) AS played, range_agg(h.during * d.whole) AS booked
        FROM day d JOIN hold h ON h.court_id = d.court_id AND h.during && d.whole
        WHERE h.use_kind <> 'block' GROUP BY 1, 2, 3
    )
    SELECT o.sport, max(o.sport_name) AS sport_name, b0.day,
           sum(x.available) AS available, sum(x.peak_available) AS peak_available, sum(x.played) AS played,
           sum(x.peak_played) AS peak_played, sum(x.outside) AS outside, sum(x.buffer) AS buffer,
           coalesce(sum(rv.net_minor), 0) AS revenue_minor, coalesce(sum(rv.peak_minor), 0) AS peak_revenue_minor
    FROM offer o JOIN base b0 ON b0.court_id = o.court_id
    LEFT JOIN sport_held sh ON sh.court_id = o.court_id AND sh.day = b0.day AND sh.sport = o.sport
    CROSS JOIN LATERAL (SELECT {_measures(f"coalesce(sh.played, {EMPTY})", f"coalesce(sh.booked, {EMPTY}) - coalesce(sh.played, {EMPTY})")}) x
    LEFT JOIN (SELECT court_id, day, sport, sum(net_minor) AS net_minor, sum(peak_minor) AS peak_minor FROM rev
               GROUP BY 1, 2, 3) rv ON rv.court_id = o.court_id AND rv.day = b0.day AND rv.sport = o.sport
    GROUP BY o.sport, b0.day ORDER BY b0.day, max(o.sport_name) NULLS LAST, o.sport"""  # fmt: skip
    return _run(session, sql, args)


# --- figures -------------------------------------------------------------------------------------------------

_MINUTES = ("available", "peak_available", "played", "peak_played", "rental", "program", "buffer", "blocked", "outside")
_MONEY = ("revenue_minor", "peak_revenue_minor")


def _half_up(value: Decimal, places: str = "1") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _pct(part: int, whole: int) -> float | None:
    return float(_half_up(Decimal(part * 100) / whole, "0.1")) if whole else None


def _per_hour(minor: int, minutes: int) -> int | None:
    return int(_half_up(Decimal(minor * 60) / minutes)) if minutes else None


def _figures(m: dict) -> dict:
    """Hours, rates and money from summed minutes (rates are worked out once, from the sums, never averaged)."""
    hours = lambda k: float(_half_up(Decimal(m[k]) / 60, "0.01"))  # noqa: E731
    out = {f"{k}_hours": hours(k) for k in _MINUTES if k in m}
    off_available, off_played = m["available"] - m["peak_available"], m["played"] - m["peak_played"]
    return out | {
        "utilization_pct": _pct(m["played"], m["available"]),
        "peak_utilization_pct": _pct(m["peak_played"], m["peak_available"]),
        "offpeak_utilization_pct": _pct(off_played, off_available),
        "revenue_minor": m["revenue_minor"], "peak_revenue_minor": m["peak_revenue_minor"],
        "offpeak_revenue_minor": m["revenue_minor"] - m["peak_revenue_minor"],
        "revenue_per_available_hour_minor": _per_hour(m["revenue_minor"], m["available"]),
        "revenue_per_sold_hour_minor": _per_hour(m["revenue_minor"], m.get("rental", m["played"])),
    }  # fmt: skip


def _period(day: date, grain: str) -> date:
    if grain == "week":
        return day - timedelta(days=day.weekday())  # ISO weeks start on Monday
    return day.replace(day=1) if grain == "month" else day


def _add(into: dict, row, keys) -> None:
    for k in keys:
        into[k] = into.get(k, 0) + int(getattr(row, k))


def _court_use(session: Session, p: CourtUseParams, scope: Scope) -> dict:
    total: dict = {}
    groups: dict[tuple, dict] = {}
    if p.group_by == "sport":
        found = _sport_days(session, p, scope)
        for x in found:
            kind = "program" if x.sport == PROGRAM else "rental"
            row = groups.setdefault((_period(x.day, p.grain), x.sport), {
                "label": x.sport_name or PROGRAM_LABEL, "m": {"rental": 0, "program": 0, "blocked": 0}})  # fmt: skip
            _add(row["m"], x, ("available", "peak_available", "played", "peak_played", "outside", "buffer", *_MONEY))
            row["m"][kind] += int(x.played)
        for x in _court_days(session, p, scope):  # totals stay physical: one minute counts once per court
            _add(total, x, (*_MINUTES, *_MONEY))
    else:
        for x in _court_days(session, p, scope):
            key = (x.court_id, x.court_name) if p.group_by == "court" else (x.court_group_id, x.court_group_name)
            row = groups.setdefault((_period(x.day, p.grain), key[0]), {"label": key[1], "sources": set(), "m": {}})
            row["sources"].add(SOURCES[x.has_windows])
            _add(row["m"], x, (*_MINUTES, *_MONEY))
            _add(total, x, (*_MINUTES, *_MONEY))
    rows = []
    for (period, key), g in groups.items():
        sources = g.get("sources")
        source = (sources.pop() if len(sources) == 1 else "Mixed") if sources else None
        rows.append({"group_key": _key(period, key), "period_on": period, "label": g["label"], "hours_source": source}
                    | _figures(g["m"]))  # fmt: skip
    totals = _figures(total) if total else _figures(dict.fromkeys((*_MINUTES, *_MONEY), 0))
    return {"rows": rows, "totals": totals, "details": None}


def _heatmap(session: Session, p: CourtParams, scope: Scope) -> dict:
    """Average utilisation per local hour of the day and weekday: played minutes over available minutes, both
    summed over the courts and days in the range. Buckets are real hours from local midnight, so a 25 hour day
    has two 01:00 buckets and a 23 hour day none at 02:00."""
    base, args = _base(p, scope)
    sql = f"""{base},
    bucket AS (
        SELECT b0.day, extract(isodow FROM b0.day)::int AS weekday,
               extract(hour FROM t AT TIME ZONE c.time_zone)::int AS hour, b0.open_mr, b0.r + b0.g AS played,
               tstzmultirange(tstzrange(t, t + interval '1 hour')) AS slot
        FROM base b0 JOIN court c ON c.court_id = b0.court_id
        CROSS JOIN generate_series(lower(b0.whole), upper(b0.whole) - interval '1 hour', interval '1 hour') t
    )
    SELECT weekday, hour, sum({_min("open_mr * slot")}) AS available, sum({_min("played * open_mr * slot")}) AS played
    FROM bucket GROUP BY weekday, hour ORDER BY hour, weekday"""
    cells: dict[int, dict] = {}
    for x in _run(session, sql, args):
        cells.setdefault(x.hour, {})[x.weekday] = (int(x.available), int(x.played))
    rows, week = [], [0, 0]
    for hour in sorted(cells):
        row: dict[str, object] = {"group_key": _key(hour), "hour": f"{hour:02d}:00"}
        available = played = 0
        for weekday, name in enumerate(WEEKDAYS, start=1):
            a, u = cells[hour].get(weekday, (0, 0))
            row[f"{name}_pct"] = _pct(u, a)
            available, played = available + a, played + u
        row["all_days_pct"] = _pct(played, available)
        week = [week[0] + available, week[1] + played]
        if available:  # an hour the courts are never open in the range is left out
            rows.append(row)
    return {"rows": rows, "totals": {"utilization_pct": _pct(week[1], week[0])}, "details": None}


# --- the specs -----------------------------------------------------------------------------------------------

_USE = (
    Col("available_hours", "Available hours", "number"), Col("played_hours", "Played hours", "number"),
    Col("utilization_pct", "Utilization", "pct"), Col("rental_hours", "Rented hours", "number"),
    Col("program_hours", "League and program hours", "number"), Col("buffer_hours", "Changeover hours", "number"),
    Col("blocked_hours", "Blocked hours", "number"), Col("outside_hours", "Played outside hours", "number"),
    Col("peak_available_hours", "Peak available hours", "number"), Col("peak_played_hours", "Peak played hours", "number"),
    Col("peak_utilization_pct", "Peak utilization", "pct"), Col("offpeak_utilization_pct", "Off-peak utilization", "pct"),
    Col("revenue_minor", "Revenue", "money"), Col("peak_revenue_minor", "Peak revenue", "money"),
    Col("offpeak_revenue_minor", "Off-peak revenue", "money"),
    Col("revenue_per_available_hour_minor", "Revenue per available hour", "money"),
    Col("revenue_per_sold_hour_minor", "Revenue per rented hour", "money"),
)  # fmt: skip
_HEAT = tuple(Col(f"{d}_pct", d.capitalize(), "pct") for d in WEEKDAYS) + (Col("all_days_pct", "All days", "pct"),)

SPECS = (
    ReportSpec(
        "court_use", "Court use",
        "Per court, court group or sport and day, week or month: played hours against the hours the court could be "
        "booked (opening hours, or the court's own windows inside them, less closures), with changeover, staff "
        "blocks and league or program use shown apart, peak and off-peak, and net rental revenue (after discounts, "
        "before tax) per available and rented hour. A court's halves count as the court.",
        "operations", FINANCIAL, "booking_date", CourtUseParams,
        (Col("period_on", "Period", "date"), Col("label", "Court, group or sport"),
         Col("hours_source", "Hours from"), *_USE), _USE, _court_use, None, ("RPT-40",),
    ),
    ReportSpec(
        "court_use_heatmap", "Court use by hour",
        "Average court utilization per hour of the day and weekday, in the location's local time, over the courts "
        "and dates chosen: for staffing and pricing.",
        "operations", ATTENDANCE, "booking_date", CourtParams,
        (Col("hour", "Hour"), *_HEAT), (Col("utilization_pct", "Utilization", "pct"),), _heatmap, None, ("RPT-40",),
    ),
)  # fmt: skip
