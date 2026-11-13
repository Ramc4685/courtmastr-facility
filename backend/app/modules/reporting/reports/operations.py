"""League, branded app and operational reports (phase 12 chip D): games by venue, officials' assignments and
roster demographics (LGE-32), app installs (RPT-38), and resource utilization, peak times and class popularity
(RPT-40; trainer productivity is on `trainer_performance` in `staff.py`)."""

from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.reporting import views as v
from app.modules.reporting.registry import (
    ATTENDANCE,
    LEAGUE,
    MAX_ROWS,
    Col,
    Params,
    RangeParams,
    ReportSpec,
    Scope,
    _between,
    _int,
    _key,
    _loc,
    _pct,
    _sum,
    too_large,
)

MARKETING = "reporting.marketing.run"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _fetch(session: Session, stmt, view, scope: Scope) -> list:
    found = list(session.execute(_loc(stmt, view, scope)).all())
    if len(found) > MAX_ROWS:
        raise too_large()  # rows are regrouped in Python, so the service's count would miss the cap
    return found


def _span(location_id: UUID, p: RangeParams, scope: Scope) -> tuple[date, date]:
    """The location's own range (see `_between`), for figures computed in Python."""
    if scope.day_ranges is not None and location_id in scope.day_ranges:
        return scope.day_ranges[location_id]
    assert p.from_on and p.to_on  # the service resolves both before building
    return p.from_on, p.to_on


# --- LGE-32 games by venue, officials, demographics ----------------------------------------------------------

_GAME_COLS = (Col("game_on", "Date", "date"), Col("game_time", "Time"), Col("competition_name", "Competition"),
              Col("home_name", "Home"), Col("away_name", "Away"), Col("status", "Status"))  # fmt: skip


def _games_by_venue(session: Session, p: RangeParams, scope: Scope) -> dict:
    g = v.league_game.c
    details = [dict(r._mapping) for r in _fetch(session, select(
        g.venue_name, g.game_on, g.game_time, g.competition_name, g.round_label, g.home_name, g.away_name, g.status,
    ).where(_between(g.game_on, p, scope)).order_by(g.venue_name, g.game_on, g.game_time, g.game_id), v.league_game, scope)]  # fmt: skip
    venues: dict[str, dict] = {}
    for d in details:
        venue = d.pop("venue_name") or "(no venue)"
        d["group_key"] = _key(venue)
        row = venues.setdefault(venue, {"group_key": d["group_key"], "venue": venue, "game_count": 0,
                                        "scheduled_count": 0, "played_count": 0, "postponed_count": 0})  # fmt: skip
        row["game_count"] += 1
        row[f"{d['status']}_count"] += 1
    rows = list(venues.values())
    keys = ("game_count", "scheduled_count", "played_count", "postponed_count")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


class OfficialParams(RangeParams):
    official_ids: list[UUID] | None = None


def _officials(session: Session, p: OfficialParams, scope: Scope) -> dict:
    o = v.game_official.c
    where = [_between(o.game_on, p, scope)]
    if p.official_ids:
        where.append(o.official_id.in_(p.official_ids))
    details = [dict(r._mapping) for r in _fetch(session, select(
        o.official_id, o.official_name, o.game_on, o.game_time, o.venue_name, o.competition_name, o.home_name,
        o.away_name, o.role, o.status,
    ).where(*where).order_by(o.official_name, o.official_id, o.game_on, o.game_time, o.game_official_id),
        v.game_official, scope)]  # fmt: skip
    officials: dict[str, dict] = {}
    for d in details:
        d["group_key"] = _key(d.pop("official_id"))
        row = officials.setdefault(d["group_key"], {"group_key": d["group_key"], "official_name": d["official_name"],
                                                    "assignment_count": 0, "venues": set()})  # fmt: skip
        row["assignment_count"] += 1
        row["venues"].add(d["venue_name"])
    rows = list(officials.values())
    for row in rows:
        row["venue_count"] = len(row.pop("venues"))
    return {"rows": rows, "totals": {"official_count": len(rows), "assignment_count": len(details)}, "details": details}


LEAGUE_AGE_BANDS = ((8, "Under 8"), (11, "8 to 10"), (14, "11 to 13"), (18, "14 to 17"), (30, "18 to 29"),
                    (40, "30 to 39"), (50, "40 to 49"))  # fmt: skip
GENDERS = {"female": "Female", "male": "Male", "non_binary": "Non-binary", "undisclosed": "Undisclosed"}
PLAYING = ("player", "captain")


def _age_band(age: int | None) -> str:
    if age is None:
        return "Unknown"
    return next((label for upper, label in LEAGUE_AGE_BANDS if age < upper), "50 and over")


class DemographicsParams(Params):
    competition_ids: list[UUID] | None = None
    group_by: Literal["team", "gender", "age_band"] = "team"


def _demographics(session: Session, p: DemographicsParams, scope: Scope) -> dict:
    r = v.league_roster.c
    where = [r.role.in_(PLAYING)]
    if p.competition_ids:
        where.append(r.competition_id.in_(p.competition_ids))
    found = _fetch(session, select(r.competition_id, r.competition_name, r.sport_name, r.age_group_name, r.team_name,
                                   r.gender, r.age).where(*where)
                   .order_by(r.competition_name, r.team_name, r.roster_entry_id), v.league_roster, scope)  # fmt: skip
    label = {"team": lambda x: x.team_name, "gender": lambda x: GENDERS.get(x.gender, "Unknown"),
             "age_band": lambda x: _age_band(x.age)}[p.group_by]  # fmt: skip
    groups: dict[tuple, dict] = {}
    per_competition: dict[UUID, int] = {}
    for x in found:
        name = label(x)
        row = groups.setdefault((x.competition_id, name), {
            "group_key": _key(x.competition_id, name), "competition_name": x.competition_name,
            "sport_name": x.sport_name, "age_group_name": x.age_group_name, "label": name, "player_count": 0,
        })  # fmt: skip
        row["player_count"] += 1
        per_competition[x.competition_id] = per_competition.get(x.competition_id, 0) + 1
    rows = []
    for (competition_id, _), row in groups.items():
        rows.append(row | {"share_pct": _pct(row["player_count"], per_competition[competition_id])})
    return {"rows": rows, "totals": {"player_count": len(found), "competition_count": len(per_competition)},
            "details": None}  # fmt: skip


# --- RPT-38 branded app installs -----------------------------------------------------------------------------


def _app_devices(session: Session, p: RangeParams, scope: Scope) -> dict:
    d = v.device.c
    found = _fetch(session, select(d.location_id, d.platform, d.app_version, d.is_push_enabled, d.registered_on,
                                   d.last_active_on, d.revoked_on).where(d.registered_on <= p.to_on)
                   .order_by(d.platform, d.app_version, d.device_registration_id), v.device, scope)  # fmt: skip
    groups: dict[tuple, dict] = {}
    for x in found:
        start, end = _span(x.location_id, p, scope)
        if x.registered_on > end:
            continue
        row = groups.setdefault((x.platform, x.app_version), {
            "group_key": _key(x.platform, x.app_version), "platform": x.platform, "app_version": x.app_version,
            "registered_count": 0, "active_count": 0, "removed_count": 0, "installed_count": 0, "push_enabled_count": 0,
        })  # fmt: skip
        installed = x.revoked_on is None or x.revoked_on > end
        row["registered_count"] += start <= x.registered_on
        row["active_count"] += x.last_active_on is not None and start <= x.last_active_on <= end
        row["removed_count"] += x.revoked_on is not None and start <= x.revoked_on <= end
        row["installed_count"] += installed
        row["push_enabled_count"] += installed and x.is_push_enabled
    rows = list(groups.values())
    keys = ("registered_count", "active_count", "removed_count", "installed_count", "push_enabled_count")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": None}


# --- RPT-40 resource utilization -----------------------------------------------------------------------------


class UtilizationParams(RangeParams):
    resource_kinds: list[Literal["venue", "trainer", "virtual_room"]] | None = None


def _open_minutes(window, start: date, end: date) -> int:
    """Minutes a weekly availability window is open between two dates (inclusive). Windows repeating every n
    weeks count the weeks since their first day."""
    first, last = max(start, window.starts_on), min(end, window.ends_on or end)
    minutes, day = 0, first
    while day <= last:
        if day.isoweekday() in window.weekdays and ((day - window.starts_on).days // 7) % window.interval_weeks == 0:
            minutes += window.window_minutes
        day += timedelta(days=1)
    return minutes


def _utilization(session: Session, p: UtilizationParams, scope: Scope) -> dict:
    h, w = v.resource_hold.c, v.availability.c
    resources: dict = {}

    def row(resource_id, name, kind) -> dict:
        return resources.setdefault(resource_id, {"group_key": _key(resource_id), "resource_name": name,
                                                  "resource_kind": kind, "booking_count": 0, "held_minutes": 0,
                                                  "open_minutes": 0})  # fmt: skip

    kinds = [h.resource_kind.in_(p.resource_kinds)] if p.resource_kinds else []
    for r in session.execute(_loc(
        select(h.resource_id, func.max(h.resource_name).label("name"), func.max(h.resource_kind).label("kind"),
               func.count(h.booking_id.distinct()).label("n"), _sum(h.held_minutes, "minutes"))
        .where(_between(h.held_on, p, scope), *kinds).group_by(h.resource_id), v.resource_hold, scope,
    )):  # fmt: skip
        row(r.resource_id, r.name, r.kind).update(booking_count=int(r.n), held_minutes=int(r.minutes))
    kinds = [w.resource_kind.in_(p.resource_kinds)] if p.resource_kinds else []
    for x in _fetch(session, select(w.location_id, w.resource_id, w.resource_name, w.resource_kind, w.starts_on, w.ends_on,
                                    w.weekdays, w.interval_weeks, w.window_minutes)
                    .where(w.starts_on <= p.to_on, *kinds), v.availability, scope):  # fmt: skip
        row(x.resource_id, x.resource_name, x.resource_kind)["open_minutes"] += _open_minutes(
            x, *_span(x.location_id, p, scope)
        )
    rows = sorted(resources.values(), key=lambda r: (r["resource_kind"], r["resource_name"]))
    for r in rows:
        r["held_hours"] = round(r.pop("held_minutes") / 60, 2)
        r["open_hours"] = round(r.pop("open_minutes") / 60, 2) or None  # no availability set: no utilization
        r["utilization_pct"] = round(r["held_hours"] * 100 / r["open_hours"], 1) if r["open_hours"] else None
    held = round(sum(r["held_hours"] for r in rows), 2)
    opened = round(sum(r["open_hours"] or 0 for r in rows if r["open_hours"]), 2)
    measured = round(sum(r["held_hours"] for r in rows if r["open_hours"]), 2)
    totals = {"booking_count": sum(r["booking_count"] for r in rows), "held_hours": held, "open_hours": opened,
              "utilization_pct": round(measured * 100 / opened, 1) if opened else None}  # fmt: skip
    return {"rows": rows, "totals": totals, "details": None}


# --- RPT-40 peak times ---------------------------------------------------------------------------------------


def _peak_times(session: Session, p: RangeParams, scope: Scope) -> dict:
    b, c = v.booking_start.c, v.check_in.c
    slots: dict[tuple[int, int], dict] = {}

    def row(weekday: int, hour: int) -> dict:
        return slots.setdefault((weekday, hour), {"group_key": _key(weekday, hour), "weekday": WEEKDAYS[weekday - 1],
                                                  "hour": f"{hour:02d}:00", "booking_count": 0, "check_in_count": 0})  # fmt: skip

    for r in session.execute(_loc(
        select(b.weekday, b.start_hour, func.count().label("n")).where(_between(b.starts_on, p, scope))
        .group_by(b.weekday, b.start_hour), v.booking_start, scope,
    )):  # fmt: skip
        row(r.weekday, r.start_hour)["booking_count"] = int(r.n)
    for r in session.execute(_loc(
        select(c.weekday, c.check_in_hour, func.count().label("n"))
        .where(_between(c.check_in_on, p, scope), c.result != "denied").group_by(c.weekday, c.check_in_hour),
        v.check_in, scope,
    )):  # fmt: skip
        row(r.weekday, r.check_in_hour)["check_in_count"] = int(r.n)
    rows = [slots[k] for k in sorted(slots)]
    for slot in rows:
        slot["activity_count"] = slot["booking_count"] + slot["check_in_count"]
    keys = ("booking_count", "check_in_count", "activity_count")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": None}


# --- RPT-40 class popularity ---------------------------------------------------------------------------------


class ClassParams(RangeParams):
    reservation_type_ids: list[UUID] | None = None


def _class_popularity(session: Session, p: ClassParams, scope: Scope) -> dict:
    s, a = v.class_session.c, v.attendance.c
    where = [_between(s.session_on, p, scope)]
    if p.reservation_type_ids:
        where.append(s.reservation_type_id.in_(p.reservation_type_ids))
    sessions = _fetch(session, select(s.session_id, s.reservation_type_id, s.reservation_type_name, s.session_on,
                                      s.start_time, s.trainer_name, s.capacity, s.booked_count)
                      .where(*where).order_by(s.session_on, s.start_time, s.session_id), v.class_session, scope)  # fmt: skip
    attended = {r.session_id: int(r.n) for r in _fetch(session, select(a.session_id, func.count().label("n")).where(
        a.status == "attended", a.session_id.in_([x.session_id for x in sessions])).group_by(a.session_id),
        v.attendance, scope)}  # fmt: skip
    classes: dict = {}
    details = []
    for x in sessions:
        group = _key(x.reservation_type_id)
        came = attended.get(x.session_id, 0)
        details.append({"group_key": group, "session_on": x.session_on, "start_time": x.start_time,
                        "trainer_name": x.trainer_name, **_int(x, "capacity", "booked_count"), "attended": came,
                        "fill_pct": _pct(x.booked_count, x.capacity)})  # fmt: skip
        row = classes.setdefault(group, {"group_key": group, "class_name": x.reservation_type_name or "(no type)",
                                         "session_count": 0, "capacity": 0, "booked_count": 0, "attended": 0})  # fmt: skip
        row["session_count"] += 1
        row["capacity"] += x.capacity
        row["booked_count"] += x.booked_count
        row["attended"] += came
    rows = list(classes.values())
    for r in rows:
        r["fill_pct"] = _pct(r["booked_count"], r["capacity"])
        r["average_booked"] = round(r["booked_count"] / r["session_count"], 1)
    rows.sort(key=lambda r: (-(r["fill_pct"] or 0), r["class_name"]))
    totals = {k: sum(r[k] for r in rows) for k in ("session_count", "capacity", "booked_count", "attended")}
    return {"rows": rows, "totals": totals | {"fill_pct": _pct(totals["booked_count"], totals["capacity"])},
            "details": details}  # fmt: skip


# --- the specs -----------------------------------------------------------------------------------------------

_VENUE_COUNTS = (Col("game_count", "Games", "count"), Col("scheduled_count", "Scheduled", "count"),
                 Col("played_count", "Played", "count"), Col("postponed_count", "Postponed", "count"))  # fmt: skip
_APP_COUNTS = (Col("registered_count", "New installs", "count"), Col("active_count", "Active in period", "count"),
               Col("removed_count", "Removed", "count"), Col("installed_count", "Installed at end", "count"),
               Col("push_enabled_count", "Push enabled", "count"))  # fmt: skip
_UTILIZATION = (Col("booking_count", "Bookings", "count"), Col("held_hours", "Booked hours", "number"),
                Col("open_hours", "Available hours", "number"), Col("utilization_pct", "Utilization", "pct"))  # fmt: skip
_PEAK = (Col("booking_count", "Bookings starting", "count"), Col("check_in_count", "Check-ins", "count"),
         Col("activity_count", "Total", "count"))  # fmt: skip
_CLASS = (Col("session_count", "Sessions", "count"), Col("capacity", "Places", "count"),
          Col("booked_count", "Booked", "count"), Col("attended", "Attended", "count"), Col("fill_pct", "Fill rate", "pct"))  # fmt: skip

SPECS = (
    ReportSpec(
        "league_games_by_venue", "Games by venue",
        "Scheduled, played and postponed league games in the period per venue, in start order.",
        "leagues", LEAGUE, "game_date", RangeParams,
        (Col("venue", "Venue"), *_VENUE_COUNTS), _VENUE_COUNTS, _games_by_venue,
        (*_GAME_COLS[:3], Col("round_label", "Round"), *_GAME_COLS[3:]),
        ("LGE-32",),
    ),
    ReportSpec(
        "league_officials", "Officials' assignments",
        "Every game each official is assigned to in the period: when, where and in which role, to hand out.",
        "leagues", LEAGUE, "game_date", OfficialParams,
        (Col("official_name", "Official"), Col("assignment_count", "Games", "count"),
         Col("venue_count", "Venues", "count")),
        (Col("official_count", "Officials", "count"), Col("assignment_count", "Assignments", "count")),
        _officials,
        (*_GAME_COLS[:2], Col("venue_name", "Venue"), *_GAME_COLS[2:5], Col("role", "Role"), Col("status", "Status")),
        ("LGE-32",),
    ),
    ReportSpec(
        "league_demographics", "League participants",
        "Players and captains on active teams per competition, by team, gender or age band (age at the "
        "competition's start).",
        "leagues", LEAGUE, "none", DemographicsParams,
        (Col("competition_name", "Competition"), Col("sport_name", "Sport"), Col("age_group_name", "Age group"),
         Col("label", "Group"), Col("player_count", "Players", "count"), Col("share_pct", "Share", "pct")),
        (Col("player_count", "Players", "count"), Col("competition_count", "Competitions", "count")),
        _demographics, None, ("LGE-32",),
    ),
    ReportSpec(
        "app_devices", "App installs",
        "Installs of the client app registered for notifications, by platform and app version: new, active and "
        "removed in the period, and installed at its end. Screen views and session times are not recorded.",
        "marketing", MARKETING, "registered_date", RangeParams,
        (Col("platform", "Platform"), Col("app_version", "App version"), *_APP_COUNTS), _APP_COUNTS, _app_devices,
        None, ("RPT-38",),
    ),
    ReportSpec(
        "resource_utilization", "Resource utilization",
        "Per resource: confirmed bookings and booked hours in the period against the hours its availability "
        "windows are open. Resources without availability windows show no utilization.",
        "operations", ATTENDANCE, "booking_date", UtilizationParams,
        (Col("resource_name", "Resource"), Col("resource_kind", "Kind"), *_UTILIZATION), _UTILIZATION, _utilization,
        None, ("RPT-40",),
    ),
    ReportSpec(
        "peak_times", "Peak times",
        "Bookings starting and check-ins admitted per weekday and hour of the day, in each location's local time.",
        "operations", ATTENDANCE, "activity_date", RangeParams,
        (Col("weekday", "Weekday"), Col("hour", "Hour"), *_PEAK), _PEAK, _peak_times, None, ("RPT-40",),
    ),
    ReportSpec(
        "class_popularity", "Class popularity",
        "Classes and services with a capacity, best filled first: sessions, places, bookings, attendance and fill "
        "rate in the period.",
        "operations", ATTENDANCE, "session_date", ClassParams,
        (Col("class_name", "Class or service"), *_CLASS, Col("average_booked", "Booked per session", "number")),
        _CLASS, _class_popularity,
        (Col("session_on", "Date", "date"), Col("start_time", "Start"), Col("trainer_name", "Instructor"),
         Col("capacity", "Places", "count"), Col("booked_count", "Booked", "count"),
         Col("attended", "Attended", "count"), Col("fill_pct", "Fill rate", "pct")),
        ("RPT-40",),
    ),
)  # fmt: skip
