from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.engagement.domain import rules


def test_unknown_fields_and_render():
    assert rules.unknown_fields("Hi $first_name", "at ${location_name} $oops", None) == ["oops"]
    assert rules.render("Hi $first_name, $title", {"first_name": "Kim"}) == "Hi Kim, "
    assert rules.render(None, {}) == ""
    assert rules.render("Cost $5", {}) == "Cost $5"


@pytest.mark.parametrize(
    ("status", "event", "expected"),
    [
        ("queued", "delivered", "delivered"), ("opened", "delivered", "opened"), ("sent", "click", "clicked"),
        ("clicked", "open", "clicked"), ("delivered", "bounce", "bounced"), ("bounced", "open", "bounced"),
        ("sent", "unsubscribe", "sent"), ("skipped", "delivered", "skipped"), ("opened", "complaint", "complained"),
    ],
)  # fmt: skip
def test_advance_is_forward_only(status, event, expected):
    assert rules.advance(status, event) == expected


def test_check_definition():
    assert rules.check_definition({}) == [("/sources", "Choose at least one source.")]
    assert rules.check_definition({"sources": [{"kind": "all_clients"}]}) == []
    bad = rules.check_definition({
        "sources": [{"kind": "nope"}, {"kind": "tag", "ids": []}],
        "filters": [
            {"kind": "birth_month", "months": [13]}, {"kind": "gender", "values": ["x"]},
            {"kind": "age_range", "min": 30, "max": 20}, {"kind": "home_location", "ids": []}, {"kind": "z"},
            {"kind": "member", "is_member": True}, {"kind": "age_range", "min": 18},
        ],
    })  # fmt: skip
    assert [p for p, _ in bad] == [
        "/sources/0/kind", "/sources/1/ids", "/filters/0/months", "/filters/1/values", "/filters/2",
        "/filters/3/ids", "/filters/4/kind",
    ]  # fmt: skip


def test_age_on():
    assert rules.age_on(date(2000, 6, 15), date(2026, 6, 14)) == 25
    assert rules.age_on(date(2000, 6, 15), date(2026, 6, 15)) == 26


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://www.youtube.com/watch?v=abc", True), ("https://vimeo.com/1", True),
        ("http://youtube.com/x", False), ("https://evil.example.com/x", False),
        ("https://user@youtube.com/x", False), ("javascript:alert(1)", False),
    ],
)  # fmt: skip
def test_video_urls(url, ok):
    assert rules.is_allowed_video_url(url) is ok


def test_https_url():
    assert rules.is_https_url("https://club.example.com/x")
    assert not rules.is_https_url("http://club.example.com")
    assert not rules.is_https_url("https://a@b.example.com")


def test_reminder_times_skip_past_offsets():
    now = datetime(2026, 3, 1, 12, tzinfo=UTC)
    start = now + timedelta(hours=3)
    assert rules.reminder_times(start, [24 * 60, 60, None], now) == [(2, start - timedelta(hours=1))]
