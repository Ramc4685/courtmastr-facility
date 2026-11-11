"""Recurrence: the pure generator, DST-correct local time in three zones, materialised series, series
edits (this, following, all, selected, date range), scoped cancel and worker generation of long series."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.scheduling import jobs, service
from app.modules.scheduling.domain import recurrence as rec
from app.modules.scheduling.domain import slots
from app.modules.scheduling.models import Booking, BookingSeriesRun, ResourceHold
from app.modules.scheduling.tests.helpers import API, at, book, booking_body, drain, facility, local, ok

CHICAGO, KOLKATA, AUCKLAND = "America/Chicago", "Asia/Kolkata", "Pacific/Auckland"


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def rule(pattern: str, **extra) -> dict:
    return {"pattern": pattern, "range_type": "count", "occurrence_limit": 4} | extra


# --- pure functions ----------------------------------------------------------------------------------------

EXPANSIONS = [
    (rec.Rule("single", date(2031, 1, 6)), ["2031-01-06"]),
    (rec.Rule("daily", date(2031, 1, 30), occurrence_limit=3), ["2031-01-30", "2031-01-31", "2031-02-01"]),
    (rec.Rule("daily", date(2031, 1, 1), 3, occurrence_limit=3), ["2031-01-01", "2031-01-04", "2031-01-07"]),
    (rec.Rule("daily", date(2031, 1, 3), weekdays=(1, 5), occurrence_limit=3), ["2031-01-03", "2031-01-06", "2031-01-10"]),
    (rec.Rule("weekly", date(2031, 1, 8), weekdays=(1, 3), occurrence_limit=4), ["2031-01-08", "2031-01-13", "2031-01-15", "2031-01-20"]),
    (rec.Rule("weekly", date(2031, 1, 6), 2, (1,), occurrence_limit=3), ["2031-01-06", "2031-01-20", "2031-02-03"]),
    (rec.Rule("weekly", date(2031, 1, 6), range_type="until", until_on=date(2031, 1, 20)), ["2031-01-06", "2031-01-13", "2031-01-20"]),
    # A month without the 31st is skipped, not moved (RFC 5545 behaviour).
    (rec.Rule("monthly_by_date", date(2031, 1, 31), occurrence_limit=3), ["2031-01-31", "2031-03-31", "2031-05-31"]),
    (rec.Rule("monthly_by_weekday", date(2031, 1, 14), weekdays=(2,), month_week=2, occurrence_limit=3), ["2031-01-14", "2031-02-11", "2031-03-11"]),
    (rec.Rule("monthly_by_weekday", date(2031, 1, 31), weekdays=(5,), month_week=-1, occurrence_limit=3), ["2031-01-31", "2031-02-28", "2031-03-28"]),
    (rec.Rule("monthly_by_weekday", date(2031, 1, 29), month_week=5, occurrence_limit=2), ["2031-01-29", "2031-04-30"]),
    (rec.Rule("yearly", date(2031, 7, 4), occurrence_limit=3), ["2031-07-04", "2032-07-04", "2033-07-04"]),
    (rec.Rule("yearly", date(2028, 2, 29), range_type="until", until_on=date(2030, 12, 31)), ["2028-02-29"]),
]  # fmt: skip


@pytest.mark.parametrize(
    ("given", "expected"), EXPANSIONS, ids=[f"{r.pattern}-{i}" for i, (r, _) in enumerate(EXPANSIONS)]
)
def test_rule_expansion(given, expected):
    assert [d.isoformat() for d in rec.expand(given, 2000)] == expected


@pytest.mark.parametrize(
    ("given", "code"),
    [
        (rec.Rule("daily", date(2031, 1, 1), occurrence_limit=2001), "series-too-long"),
        (rec.Rule("yearly", date(2031, 1, 1), occurrence_limit=10), "series-too-long"),  # past the three-year horizon
        (rec.Rule("daily", date(2031, 1, 1), range_type="until", until_on=date(2034, 6, 1)), "series-too-long"),
        (rec.Rule("daily", date(2031, 1, 1)), "validation-failed"),
        (rec.Rule("daily", date(2031, 1, 1), 0, occurrence_limit=2), "validation-failed"),
        (rec.Rule("daily", date(2031, 1, 2), range_type="until", until_on=date(2031, 1, 1)), "validation-failed"),
        (rec.Rule("hourly", date(2031, 1, 1), occurrence_limit=2), "validation-failed"),
    ],
)
def test_rule_limits(given, code):
    with pytest.raises(rec.RuleError) as error:
        rec.expand(given, 2000)
    assert error.value.code == code


def test_until_range_is_inclusive():
    assert (
        len(rec.expand(rec.Rule("weekly", date(2031, 1, 6), range_type="until", until_on=date(2031, 12, 29)), 2000))
        == 52
    )


LOCAL_TIMES = [
    # zone, local date, wall time, expected UTC instant
    (CHICAGO, date(2031, 3, 8), time(18, 0), "2031-03-09T00:00"),  # CST, the day before spring forward
    (CHICAGO, date(2031, 3, 9), time(18, 0), "2031-03-09T23:00"),  # CDT
    (CHICAGO, date(2031, 3, 9), time(2, 30), "2031-03-09T08:00"),  # does not exist: next valid instant (03:00 CDT)
    (CHICAGO, date(2031, 11, 2), time(1, 30), "2031-11-02T06:30"),  # happens twice: the first (CDT)
    (CHICAGO, date(2031, 11, 2), time(18, 0), "2031-11-03T00:00"),
    (KOLKATA, date(2031, 3, 9), time(18, 0), "2031-03-09T12:30"),  # no DST, half-hour offset
    (AUCKLAND, date(2031, 4, 6), time(2, 30), "2031-04-05T13:30"),  # ambiguous in autumn: first (NZDT)
    (AUCKLAND, date(2031, 9, 28), time(2, 30), "2031-09-27T14:00"),  # gap in spring: 03:00 NZDT
    (AUCKLAND, date(2031, 9, 28), time(18, 0), "2031-09-28T05:00"),
]


@pytest.mark.parametrize(("zone", "day", "wall", "expected"), LOCAL_TIMES)
def test_localize_across_dst(zone, day, wall, expected):
    instant = rec.localize(day, wall, ZoneInfo(zone))
    assert instant == datetime.fromisoformat(expected).replace(tzinfo=UTC)
    if expected[11:] not in ("08:00", "14:00"):  # valid wall times round-trip
        assert rec.local_parts(instant, ZoneInfo(zone)) == (day, wall)


def test_span_wall_times_and_helpers():
    zone = ZoneInfo(CHICAGO)
    # 01:30 for 60 minutes on the spring-forward night: the end wall time 02:30 does not exist, so 03:00.
    start, end = rec.span(date(2031, 3, 9), time(1, 30), 60, zone)
    assert (end - start) == timedelta(minutes=30)
    # Both ends in the gap collapse; the end becomes start plus the nominal duration.
    start, end = rec.span(date(2031, 3, 9), time(2, 10), 30, zone)
    assert end - start == timedelta(minutes=30)
    # A class through the autumn night is an hour longer on the clock, the same on the wall.
    start, end = rec.span(date(2031, 11, 1), time(23, 0), 240, zone)
    assert end - start == timedelta(hours=5) and rec.local_parts(end, zone) == (date(2031, 11, 2), time(3, 0))
    assert rec.parse_wall("24:00") == (time(0, 0), 1) and rec.parse_wall("09:30") == (time(9, 30), 0)
    assert rec.parse_wall(time(7, 0)) == (time(7, 0), 0)
    assert rec.nominal_minutes(time(22, 0), time(0, 0), 1) == 120


def test_free_time_arithmetic():
    t = lambda h: datetime(2031, 1, 1, tzinfo=UTC) + timedelta(hours=h)  # noqa: E731
    assert slots.subtract([(t(8), t(12)), (t(11), t(20))], [(t(9), t(10)), (t(9.5), t(11)), (t(19), t(22))]) == [
        (t(8), t(9)),
        (t(11), t(19)),
    ]
    assert slots.subtract([(t(8), t(10))], [(t(8), t(9.75))], 30) == []
    assert slots.subtract([(t(8), t(10))], [(t(6), t(7)), (t(10), t(11))]) == [(t(8), t(10))]
    monday = date(2031, 1, 6)
    assert slots.window_fires_on(monday, monday, None, [1], 2) and not slots.window_fires_on(
        monday + timedelta(7), monday, None, [1], 2
    )
    assert slots.window_fires_on(monday + timedelta(14), monday, None, [1], 2)
    assert not slots.window_fires_on(monday, monday + timedelta(1), None, [1], 1)
    assert not slots.window_fires_on(monday + timedelta(7), monday, monday, [1], 1)
    assert not slots.window_fires_on(monday, monday, None, [2], 1)


# --- materialised series through the API -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("zone", "first", "count", "utc_hours"),
    [
        (CHICAGO, (2031, 3, 3), 3, [0, 23, 23]),  # weekly 18:00 across spring forward: 00:00Z then 23:00Z
        (CHICAGO, (2031, 10, 27), 2, [23, 0]),  # across fall back
        (KOLKATA, (2031, 3, 3), 3, [12, 12, 12]),
        (AUCKLAND, (2031, 3, 31), 2, [5, 6]),  # NZDT to NZST
        (AUCKLAND, (2031, 9, 22), 2, [6, 5]),
    ],
)
def test_weekly_series_keeps_its_wall_time_across_dst(client, owner, zone, first, count, utc_hours):
    f = facility(client, owner, zone)
    body = booking_body(
        f,
        [f.court],
        local(zone, *first, 18),
        local(zone, *first, 19, 30),
        kind="session",
        recurrence=rule("weekly", occurrence_limit=count),
    )
    created = ok(client.post(f"{API}/bookings", headers=owner, json=body))
    assert created["created_count"] == count and created["conflict_count"] == 0
    rows = ok(
        client.get(f"{API}/bookings?booking_series_id={created['booking_series_id']}&sort=starts_at", headers=owner),
        200,
    )["data"]
    assert [datetime.fromisoformat(r["starts_at"]).hour for r in rows] == utc_hours
    for row in rows:
        starts = datetime.fromisoformat(row["starts_at"]).astimezone(ZoneInfo(zone))
        ends = datetime.fromisoformat(row["ends_at"]).astimezone(ZoneInfo(zone))
        assert (starts.hour, ends.hour, ends.minute) == (18, 19, 30)
        assert (row["local_start_time"], row["duration_min"], row["occurrence_on"]) == (
            "18:00",
            90,
            starts.date().isoformat(),
        )
        assert row["session"]["capacity"] == 4  # every occurrence has its own seat counter


def test_daily_series_through_both_dst_nights(client, owner, f):
    gap = booking_body(
        f,
        [f.court],
        local(CHICAGO, 2031, 3, 8, 2, 30),
        local(CHICAGO, 2031, 3, 8, 3, 30),
        recurrence=rule("daily", occurrence_limit=3),
    )
    series = ok(client.post(f"{API}/bookings", headers=owner, json=gap))["booking_series_id"]
    rows = ok(client.get(f"{API}/bookings?booking_series_id={series}&sort=starts_at", headers=owner), 200)["data"]
    # 8 March 02:30 CST; 9 March 02:30 does not exist and becomes 03:00 CDT; 10 March 02:30 CDT.
    assert [r["starts_at"] for r in rows] == ["2031-03-08T08:30:00Z", "2031-03-09T08:00:00Z", "2031-03-10T07:30:00Z"]
    assert {r["local_start_time"] for r in rows} == {"02:30"} and {r["duration_min"] for r in rows} == {60}
    fold = booking_body(
        f,
        [f.court2],
        local(CHICAGO, 2031, 11, 1, 1, 30),
        local(CHICAGO, 2031, 11, 1, 2, 15),
        recurrence=rule("daily", occurrence_limit=2),
    )
    series = ok(client.post(f"{API}/bookings", headers=owner, json=fold))["booking_series_id"]
    rows = ok(client.get(f"{API}/bookings?booking_series_id={series}&sort=starts_at", headers=owner), 200)["data"]
    assert [r["starts_at"] for r in rows] == ["2031-11-01T06:30:00Z", "2031-11-02T06:30:00Z"]  # the first 01:30
    assert rows[1]["ends_at"] == "2031-11-02T08:15:00Z"  # 02:15 CST: the ambiguous hour passes twice


def test_an_end_at_midnight_stays_on_its_day(client, owner, f):
    body = booking_body(
        f,
        [f.court],
        local(CHICAGO, 2031, 6, 2, 22),
        local(CHICAGO, 2031, 6, 3, 0),
        recurrence=rule("daily", occurrence_limit=2),
    )
    series = ok(client.post(f"{API}/bookings", headers=owner, json=body))["booking_series_id"]
    detail = ok(client.get(f"{API}/booking-series/{series}", headers=owner), 200)
    assert (detail["rules"][0]["end_time"], detail["rules"][0]["end_day_offset"], detail["occurrence_count"]) == (
        "00:00",
        1,
        2,
    )
    rows = ok(client.get(f"{API}/bookings?booking_series_id={series}", headers=owner), 200)["data"]
    assert [r["occurrence_on"] for r in rows] == ["2031-06-02", "2031-06-03"]  # back to back, no clash


def series_of(client, owner, f, count: int = 5, resources=None, **extra) -> tuple[str, list[dict]]:
    body = booking_body(
        f,
        resources or [f.court],
        at(15),
        at(16),
        kind="session",
        recurrence=rule("daily", occurrence_limit=count),
        **extra,
    )
    created = ok(client.post(f"{API}/bookings", headers=owner, json=body))
    rows = ok(
        client.get(f"{API}/bookings?booking_series_id={created['booking_series_id']}&sort=starts_at", headers=owner),
        200,
    )["data"]
    return created["booking_series_id"], rows


def live(client, owner, series: str) -> list[dict]:
    url = f"{API}/bookings?booking_series_id={series}&sort=starts_at&status[ne]=cancelled"
    return ok(client.get(url, headers=owner), 200)["data"]


def test_conflicts_abort_by_default_and_skip_on_request(client, owner, f, tenant):
    blocker = ok(book(client, owner, f, [f.half_a], at(15 + 48), at(16 + 48)))["booking"]  # day 3 of the series
    body = booking_body(f, [f.court], at(15), at(16), kind="session", recurrence=rule("daily", occurrence_limit=5))
    preview = ok(client.post(f"{API}/bookings/preview", headers=owner, json=body), 200)
    assert (preview["requested_count"], preview["ok_count"], preview["conflict_count"]) == (5, 4, 1)
    assert [o["status"] for o in preview["occurrences"]] == ["ok", "ok", "conflict", "ok", "ok"]
    assert preview["occurrences"][2]["conflicts"][0]["booking_id"] == blocker["id"]
    aborted = client.post(f"{API}/bookings", headers=owner, json=body)
    assert aborted.status_code == 409 and aborted.json()["code"] == "booking-conflict"
    assert aborted.json()["results"][0]["index"] == 2 and aborted.json()["conflicts"][0]["booking_id"] == blocker["id"]
    with tenant_session(tenant.id) as session:  # all or nothing
        assert session.scalar(select(func.count()).select_from(Booking)) == 1
    skipped = ok(client.post(f"{API}/bookings", headers=owner, json=body | {"on_conflict": "skip"}))
    assert (skipped["created_count"], skipped["conflict_count"]) == (4, 1)
    assert skipped["results"][0]["status"] == "conflict" and skipped["results"][0]["local_start"] == "2031-05-07"
    detail = ok(client.get(f"{API}/booking-series/{skipped['booking_series_id']}", headers=owner), 200)
    one = detail["rules"][0]
    assert (detail["occurrence_count"], one["status"], one["created_count"], one["conflict_count"]) == (
        4,
        "completed",
        4,
        1,
    )
    assert (
        ok(client.get(f"{API}/booking-series/{detail['id']}/rules/{one['id']}", headers=owner), 200)["rule"]["pattern"]
        == "daily"
    )
    # A pass whose occurrences overlap each other is flagged by the preview and refused by the engine.
    overlapping = booking_body(f, [f.court2], at(15), at(15 + 30), recurrence=rule("daily", occurrence_limit=3))
    statuses = [
        o["status"]
        for o in ok(client.post(f"{API}/bookings/preview", headers=owner, json=overlapping), 200)["occurrences"]
    ]
    assert statuses == ["ok", "conflict", "ok"]
    assert client.post(f"{API}/bookings", headers=owner, json=overlapping).status_code == 409
    single = ok(
        client.post(f"{API}/bookings/preview", headers=owner, json=booking_body(f, [f.court], at(15), at(16))), 200
    )
    assert single["conflict_count"] == 1  # the series now holds that hour


def test_series_skips_closure_days(client, owner, f):
    ok(
        client.post(
            f"{API}/blackouts",
            headers=owner,
            json={"location_id": f.location, "name": "Holiday", "starts_at": at(24), "ends_at": at(48)},
        )
    )
    body = booking_body(f, [f.court], at(15), at(16), kind="session", recurrence=rule("daily", occurrence_limit=3))
    statuses = [
        o["status"] for o in ok(client.post(f"{API}/bookings/preview", headers=owner, json=body), 200)["occurrences"]
    ]
    assert statuses == ["ok", "blackout", "ok"]
    created = ok(client.post(f"{API}/bookings", headers=owner, json=body))  # a closure is a skip, never an abort
    assert (created["created_count"], created["results"][0]["status"]) == (2, "blackout")


def test_series_validation(client, owner, f):
    def post(**extra):
        return client.post(f"{API}/bookings", headers=owner, json=booking_body(f, [f.court], at(15), at(16), **extra))  # noqa: E731

    assert post(recurrence=rule("daily", occurrence_limit=None)).json()["errors"][0]["pointer"] == "/recurrence"
    assert post(recurrence=rule("yearly", occurrence_limit=9)).json()["errors"][0]["code"] == "series-too-long"
    ok(
        client.patch(
            f"{API}/scheduling-settings?location_id={f.location}", headers=owner, json={"max_series_occurrences": 3}
        ),
        200,
    )
    assert post(recurrence=rule("daily", occurrence_limit=4)).json()["errors"][0]["code"] == "series-too-long"
    assert post(kind="session", block_kind="unpaid").status_code == 422
    assert (
        client.post(
            f"{API}/bookings", headers=owner, json=booking_body(f, [f.court], at(15), at(16)) | {"block_kind": None}
        ).status_code
        == 422
    )
    assert post(starts_at=at(16)).json()["errors"][0]["pointer"] == "/ends_at"
    assert post(starts_at="2031-05-05T15:00:30Z").json()["errors"][0]["pointer"] == "/starts_at"
    two_primaries = booking_body(f, [f.court], at(15), at(16)) | {
        "resources": [{"resource_id": f.court, "role": "primary"}, {"resource_id": f.court2, "role": "primary"}]
    }
    assert client.post(f"{API}/bookings", headers=owner, json=two_primaries).status_code == 422


# --- series edits ------------------------------------------------------------------------------------------


def edit(client, owner, series: str, scope: dict, patch: dict, status: int = 200, **extra) -> dict:
    return ok(
        client.post(
            f"{API}/booking-series/{series}/edits", headers=owner, json={"scope": scope, "patch": patch} | extra
        ),
        status,
    )


def test_edit_scopes_this_following_all_selected_and_date_range(client, owner, f):
    series, rows = series_of(client, owner, f)
    ids = [r["id"] for r in rows]
    titles = lambda: [r["title"] for r in live(client, owner, series)]  # noqa: E731
    assert (
        edit(client, owner, series, {"mode": "this", "anchor_booking_id": ids[1]}, {"title": "One"})["affected_count"]
        == 1
    )
    assert titles() == ["Clinic", "One", "Clinic", "Clinic", "Clinic"]
    assert (
        edit(client, owner, series, {"mode": "following", "anchor_booking_id": ids[3]}, {"title": "Late"})[
            "affected_count"
        ]
        == 2
    )
    assert titles() == ["Clinic", "One", "Clinic", "Late", "Late"]
    assert (
        edit(
            client,
            owner,
            series,
            {"mode": "selected", "booking_ids": [ids[0], ids[2]]},
            {"notes": "Bring water", "title": "Picked"},
        )["affected_count"]
        == 2
    )
    assert titles() == ["Picked", "One", "Picked", "Late", "Late"]
    assert (
        edit(
            client,
            owner,
            series,
            {"mode": "date_range", "from_on": "2031-05-06", "to_on": "2031-05-07"},
            {"public_title": "Open"},
        )["affected_count"]
        == 2
    )
    assert [r["public_title"] for r in live(client, owner, series)] == [None, "Open", "Open", None, None]
    assert (
        edit(client, owner, series, {"mode": "all"}, {"title": "Everyone"})["affected_count"] == 5
    )  # rename is series-wide
    assert (
        set(titles()) == {"Everyone"} and live(client, owner, series)[0]["notes"] == "Bring water"
    )  # blank fields untouched
    other, other_rows = series_of(client, owner, f, 2, [f.court2])
    foreign = client.post(
        f"{API}/booking-series/{series}/edits",
        headers=owner,
        json={"scope": {"mode": "this", "anchor_booking_id": other_rows[0]["id"]}, "patch": {"title": "X"}},
    )
    assert foreign.status_code == 422 and foreign.json()["errors"][0]["pointer"] == "/scope/anchor_booking_id"
    assert (
        edit(client, owner, series, {"mode": "selected", "booking_ids": [other_rows[0]["id"]]}, {"title": "X"})[
            "affected_count"
        ]
        == 0
    )


def test_time_edit_on_following_keeps_earlier_occurrences_and_survives_dst(client, owner):
    f = facility(client, owner, CHICAGO)
    body = booking_body(
        f,
        [f.court],
        local(CHICAGO, 2031, 2, 24, 18),
        local(CHICAGO, 2031, 2, 24, 19),
        kind="session",
        recurrence=rule("weekly", occurrence_limit=4),
    )
    series = ok(client.post(f"{API}/bookings", headers=owner, json=body))["booking_series_id"]
    rows = live(client, owner, series)
    scope = {"mode": "following", "anchor_booking_id": rows[1]["id"]}
    preview = edit(client, owner, series, scope, {"start_time": "07:30", "duration_min": 45}, preview=True)
    assert preview["affected_count"] == 3 and len(preview["results"]) == 3
    assert [r["starts_at"] for r in live(client, owner, series)] == [
        r["starts_at"] for r in rows
    ]  # a preview writes nothing
    assert edit(client, owner, series, scope, {"start_time": "07:30", "duration_min": 45})["affected_count"] == 3
    after = live(client, owner, series)
    assert after[0]["starts_at"] == rows[0]["starts_at"] and after[0]["version"] == 1
    # 3 March is CST (13:30Z); 10 and 17 March are CDT (12:30Z): 07:30 on the wall every week.
    assert [r["starts_at"][11:16] for r in after[1:]] == ["13:30", "12:30", "12:30"]
    assert {(r["local_start_time"], r["duration_min"], r["version"]) for r in after[1:]} == {("07:30", 45, 2)}


def test_shifting_a_whole_series_never_collides_with_its_own_old_times(client, owner, f, tenant):
    series, rows = series_of(client, owner, f, 5)
    # Every occurrence moves onto the next one's old slot: holds are released first, so nothing clashes.
    assert edit(client, owner, series, {"mode": "all"}, {"shift_days": 1})["conflict_count"] == 0
    after = live(client, owner, series)
    assert [r["occurrence_on"] for r in after] == ["2031-05-06", "2031-05-07", "2031-05-08", "2031-05-09", "2031-05-10"]
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(ResourceHold)) == 5 * 4  # court, two halves, a quarter
    assert book(client, owner, f, [f.court], at(15), at(16)).status_code == 201  # the first day is free again
    resourced = edit(
        client, owner, series, {"mode": "all"}, {"resources": [{"resource_id": f.court2}], "buffer_after_min": 15}
    )
    assert resourced["affected_count"] == 5
    assert {r["resources"][0]["resource_id"] for r in live(client, owner, series)} == {f.court2}
    assert {r["buffer_after_min"] for r in live(client, owner, series)} == {15}
    assert book(client, owner, f, [f.court2], at(16 + 24), at(17 + 24)).status_code == 409  # inside the new buffer


def test_edit_conflicts_abort_or_skip_with_attribution(client, owner, f):
    series, rows = series_of(client, owner, f, 4)
    blocker = ok(book(client, owner, f, [f.quarter], at(18 + 24), at(19 + 24)))["booking"]  # day 2 at 18:00
    request = {"scope": {"mode": "all"}, "patch": {"start_time": "13:00"}}  # 18:00Z
    aborted = client.post(f"{API}/booking-series/{series}/edits", headers=owner, json=request)
    assert aborted.status_code == 409 and aborted.json()["conflicts"][0]["booking_id"] == blocker["id"]
    assert [r["starts_at"] for r in live(client, owner, series)] == [r["starts_at"] for r in rows]  # rolled back whole
    preview = edit(client, owner, series, {"mode": "all"}, {"start_time": "13:00"}, on_conflict="skip", preview=True)
    assert [r["status"] for r in preview["results"]] == ["ok", "conflict", "ok", "ok"]
    done = edit(client, owner, series, {"mode": "all"}, {"start_time": "13:00"}, on_conflict="skip")
    assert (done["affected_count"], done["conflict_count"]) == (3, 1) and done["results"][0]["booking_id"] == rows[1][
        "id"
    ]
    after = live(client, owner, series)
    assert [r["starts_at"][11:16] for r in after] == ["18:00", "15:00", "18:00", "18:00"]  # the clashing one stayed put
    assert book(client, owner, f, [f.court], at(15 + 24), at(16 + 24)).status_code == 409  # and still holds its time


def test_bulk_capacity_through_the_series_editor_reports_overfull_sessions(client, owner, f, tenant):
    series, rows = series_of(client, owner, f, 3)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        service.reserve_seat(session, UUID(rows[1]["session"]["id"]), 3)
    result = edit(client, owner, series, {"mode": "all"}, {"session": {"capacity": 2, "is_self_bookable": False}})
    assert (result["affected_count"], result["results"][0]["status"]) == (2, "capacity-below-booked")
    assert [r["session"]["capacity"] for r in live(client, owner, series)] == [2, 4, 2]
    assert [r["session"]["is_self_bookable"] for r in live(client, owner, series)] == [False, False, False]


def test_scoped_cancel_and_stacking_another_pass(client, owner, f, tenant):
    series, rows = series_of(client, owner, f, 4)
    url = f"{API}/booking-series/{series}"
    scope = {"scope": {"mode": "following", "anchor_booking_id": rows[2]["id"]}}
    assert (
        ok(client.post(f"{url}/cancellations", headers=owner, json=scope | {"preview": True}), 200)["affected_count"]
        == 2
    )
    assert len(live(client, owner, series)) == 4
    assert (
        ok(
            client.post(f"{url}/cancellations", headers=owner, json=scope | {"reason": "client", "note": "Coach away"}),
            200,
        )["affected_count"]
        == 2
    )
    assert len(live(client, owner, series)) == 2 and ok(client.get(url, headers=owner), 200)["occurrence_count"] == 2
    gone = ok(client.get(f"{API}/bookings/{rows[3]['id']}", headers=owner), 200)
    assert (gone["status"], gone["cancel_reason"], gone["session"]["capacity"]) == (
        "cancelled",
        "client",
        4,
    )  # the row stays
    assert book(client, owner, f, [f.court], at(15 + 72), at(16 + 72)).status_code == 201
    add = {
        "start_on": "2031-06-02",
        "start_time": "09:00",
        "end_time": "10:30",
        "rule": rule("weekly", weekdays=[1, 4], occurrence_limit=3),
    }
    assert ok(client.post(f"{url}/rules", headers=owner, json=add | {"preview": True}))["preview"]["ok_count"] == 3
    added = ok(client.post(f"{url}/rules", headers=owner, json=add | {"resources": [{"resource_id": f.court2}]}))
    assert added["created_count"] == 3 and added["booking"]["resources"][0]["resource_id"] == f.court2
    detail = ok(client.get(url, headers=owner), 200)
    assert detail["occurrence_count"] == 5 and [r["sequence"] for r in detail["rules"]] == [1, 2]
    assert (
        live(client, owner, series)[-1]["occurrence_on"] == "2031-06-09"
        and live(client, owner, series)[-1]["duration_min"] == 90
    )


# --- long series: the worker -------------------------------------------------------------------------------


def long_series(client, owner, f, count: int, on=None, **extra) -> str:
    body = booking_body(
        f,
        on or [f.court, f.coach],
        at(15),
        at(16),
        kind="session",
        recurrence=rule("daily", occurrence_limit=count),
        **extra,
    )
    response = client.post(f"{API}/bookings", headers=owner, json=body)
    accepted = ok(response, 202)
    assert accepted["booking"] is None and accepted["created_count"] == 0
    return accepted["status_url"]


def test_long_series_is_generated_by_the_worker_in_chunks(client, owner, f, tenant):
    status_url = long_series(client, owner, f, 120)
    assert ok(client.get(status_url, headers=owner), 200)["status"] == "pending"
    drain()
    run = ok(client.get(status_url, headers=owner), 200)
    assert (run["status"], run["kind"], run["requested_count"], run["ok_count"], run["conflict_count"]) == (
        "completed",
        "generate",
        120,
        120,
        0,
    )
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 120
        assert (
            session.scalar(select(func.count()).select_from(ResourceHold)) == 120 * 5
        )  # court, halves, quarter, coach
        assert session.scalar(select(func.count(Booking.occurrence_index.distinct()))) == 120
    # At-least-once delivery: the same message again changes nothing.
    jobs.generate_series.send(str(tenant.id), run["id"])
    drain()
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 120
    detail = ok(client.get(f"{API}/booking-series/{run['booking_series_id']}", headers=owner), 200)
    assert (detail["occurrence_count"], detail["rules"][0]["status"]) == (120, "completed")


def test_long_series_abort_writes_nothing_and_skip_reports_each_clash(client, owner, f, tenant):
    blocker = ok(book(client, owner, f, [f.coach], at(15 + 24 * 70), at(16 + 24 * 70)))["booking"]
    status_url = long_series(client, owner, f, 90)
    drain()
    run = ok(client.get(status_url, headers=owner), 200)
    assert (run["status"], run["ok_count"], run["conflict_count"]) == ("failed", 0, 1)
    assert run["results"][0]["index"] == 70 and run["results"][0]["conflicts"][0]["booking_id"] == blocker["id"]
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 1
    status_url = long_series(client, owner, f, 90, on_conflict="skip")
    drain()
    run = ok(client.get(status_url, headers=owner), 200)
    assert (run["status"], run["ok_count"], run["conflict_count"], run["results"][0]["status"]) == (
        "completed",
        89,
        1,
        "conflict",
    )


def test_generation_resumes_after_a_killed_worker_and_undoes_a_lost_race(client, owner, f, tenant):
    system = system_principal("tests")
    run_id = UUID(long_series(client, owner, f, 70).rsplit("/", 1)[1])
    with tenant_session(tenant.id, actor=system) as session:
        assert service.run_generation_chunk(session, run_id) is True  # first chunk, then the worker "dies"
    with tenant_session(tenant.id) as session:
        run = session.get(BookingSeriesRun, run_id)
        assert (run.status, run.ok_count, run.command["next_index"]) == ("running", 50, 50)
    with tenant_session(tenant.id, actor=system) as session:
        assert service.run_generation_chunk(session, run_id) is False
        assert service.run_generation_chunk(session, run_id) is False  # finished: a late message is a no-op
        assert session.get(BookingSeriesRun, run_id).ok_count == 70
    # Abort mode, and a rival takes a slot after the pre-check passed: the whole pass is removed.
    run_id = UUID(long_series(client, owner, f, 60, on=[f.court2]).rsplit("/", 1)[1])
    with tenant_session(tenant.id, actor=system) as session:
        assert service.run_generation_chunk(session, run_id) is True
    ok(book(client, owner, f, [f.court2], at(15 + 24 * 55), at(16 + 24 * 55)))
    with tenant_session(tenant.id, actor=system) as session:
        assert service.run_generation_chunk(session, run_id) is False
        run = session.get(BookingSeriesRun, run_id)
        assert (run.status, run.ok_count, run.results[0]["index"]) == ("failed", 0, 55)
        assert (
            session.scalar(select(func.count()).where(Booking.booking_series_rule_id == run.booking_series_rule_id))
            == 0
        )
