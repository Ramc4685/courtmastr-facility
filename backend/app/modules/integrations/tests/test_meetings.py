"""Virtual sessions (INT-09, SSP-18, CLS-08): the VideoMeeting port contract on the simulated adapter and on
ZoomVideo over httpx.MockTransport (never Zoom), the session meeting commands, the Zoom connection, and the
member join with its window, its place check and the attendance mark."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.adapters.video import FakeVideo, ZoomVideo
from app.core import clock
from app.core.db.session import tenant_session
from app.modules.integrations.tests.test_public_api import _member
from app.modules.programs.models import Attendance
from app.modules.scheduling.tests.helpers import API, book, facility, ok
from conftest import login, make_tenant

WHEN = datetime(2031, 5, 3, 15, tzinfo=UTC)


def _zoom(request: httpx.Request) -> httpx.Response:
    """A stand-in for Zoom's OAuth token and meetings endpoints, shaped like their public documentation."""
    if request.url.host == "zoom.us":
        good = request.url.params.get("account_id") == "acct-1" and request.headers["authorization"].startswith(
            "Basic "
        )
        return httpx.Response(200, json={"access_token": "zt", "expires_in": 3600}) if good else httpx.Response(400)
    assert request.headers["authorization"] == "Bearer zt"
    if request.method == "POST" and request.url.path.endswith("/meetings"):
        return httpx.Response(201, json={"id": 85746065432, "join_url": "https://zoom.example/j/85746065432",
                                         "start_url": "https://zoom.example/s/85746065432", "password": "x1"})  # fmt: skip
    if request.method in ("PATCH", "DELETE"):
        return httpx.Response(204)
    return httpx.Response(404)


def _real(account_id: str = "acct-1") -> ZoomVideo:
    http = httpx.Client(transport=httpx.MockTransport(_zoom))
    return ZoomVideo(account_id=account_id, client_id="cid", client_secret="secret", client=http)


@pytest.mark.parametrize("make", [FakeVideo, _real], ids=["fake", "zoom"])
def test_video_meeting_contract(make):
    adapter = make()
    adapter.check_account()
    made = adapter.create_meeting(topic="Kids clinic", starts_at=WHEN, minutes=60, host_user_id="me")
    assert made.external_meeting_id and made.join_url.startswith("https://") and made.host_start_url
    assert adapter.update_meeting(made.external_meeting_id, starts_at=WHEN + timedelta(hours=1), minutes=30) is None
    assert adapter.delete_meeting(made.external_meeting_id) is None


def test_zoom_encodes_the_host_as_one_path_segment():
    paths: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.raw_path.decode())
        return _zoom(request)

    http = httpx.Client(transport=httpx.MockTransport(record))
    zoom = ZoomVideo(account_id="acct-1", client_id="cid", client_secret="secret", client=http)
    zoom.create_meeting(topic="t", starts_at=WHEN, minutes=30, host_user_id="../a/b@x.com")
    assert paths[-1] == "/v2/users/..%2Fa%2Fb@x.com/meetings"


def test_zoom_refuses_credentials_for_another_account():
    with pytest.raises(httpx.HTTPStatusError):
        _real("someone-else").check_account()


# --- the meeting of a session ------------------------------------------------------------------------------


def _session(client, owner, f, starts_at: datetime, minutes: int = 60) -> str:
    end = starts_at + timedelta(minutes=minutes)
    created = ok(book(client, owner, f, [f.court], starts_at.isoformat(), end.isoformat(), kind="session",
                      title="Coach note", public_title="Online clinic"))  # fmt: skip
    return created.get("booking", created)["session"]["id"]


def _meeting(session_id: str) -> str:
    return f"{API}/sessions/{session_id}/video-meeting"


def _connect_zoom(client, headers, account_id: str | None = None):
    app = {"account_id": account_id or f"acct-{uuid4().hex[:10]}", "client_id": "simulated", "client_secret": "s"}
    return client.post(f"{API}/external-connections", headers=headers, json={"provider": "zoom", "zoom": app})


def test_a_pasted_meeting_is_sealed_shown_to_staff_and_removable(client, tenant, owner):
    f = facility(client, owner)
    seat = _session(client, owner, f, WHEN)
    assert client.get(_meeting(seat), headers=owner).status_code == 404
    body = {"provider": "manual", "join_url": "https://meet.example/abc", "passcode": "4242"}
    put = ok(client.put(_meeting(seat), headers=owner, json=body), 200)
    assert (put["provider"], put["join_url"], put["has_passcode"]) == ("manual", "https://meet.example/abc", True)
    with tenant_session(tenant.id) as session:
        from app.modules.integrations.models import VideoMeeting

        row = session.scalar(select(VideoMeeting).where(VideoMeeting.session_id == seat))
        assert "meet.example" not in row.join_url_ciphertext  # sealed at rest
    assert client.put(_meeting(seat), headers=owner, json={"provider": "manual"}).status_code == 422
    insecure = {"provider": "manual", "join_url": "http://meet.example/abc"}
    assert client.put(_meeting(seat), headers=owner, json=insecure).status_code == 422
    assert client.delete(_meeting(seat), headers=owner).status_code == 204
    assert client.get(_meeting(seat), headers=owner).status_code == 404


def test_zoom_meetings_need_a_verified_connection(client, owner):
    f = facility(client, owner)
    seat = _session(client, owner, f, WHEN)
    refused = client.put(_meeting(seat), headers=owner, json={"provider": "zoom"})
    assert (refused.status_code, refused.json()["code"]) == (422, "provider-unavailable")
    missing = client.post(f"{API}/external-connections", headers=owner, json={"provider": "zoom"})
    assert missing.status_code == 422
    connected = _connect_zoom(client, owner)
    assert connected.status_code == 201 and connected.json()["status"] == "active", connected.text
    ports = {row["port"]: row for row in client.get(f"{API}/integration-adapters", headers=owner).json()}
    assert (ports["video_meeting"]["status"], ports["video_meeting"]["adapter"]) == ("connected", "zoom")
    made = ok(client.put(_meeting(seat), headers=owner, json={"provider": "zoom"}), 200)
    assert made["provider"] == "zoom" and made["join_url"].startswith("https://video.invalid/j/")
    moved = ok(client.put(_meeting(seat), headers=owner, json={"provider": "zoom"}), 200)
    assert moved["join_url"] == made["join_url"]  # an existing Zoom meeting is moved, not recreated
    pasted = ok(
        client.put(_meeting(seat), headers=owner, json={"provider": "manual", "join_url": "https://m.example/1"}), 200
    )
    assert pasted["external_connection_id"] is None


def test_a_zoom_account_connected_elsewhere_is_refused_and_released_on_disconnect(client, owner):
    account = f"acct-{uuid4().hex[:10]}"
    first = _connect_zoom(client, owner, account).json()
    rival = login(client, make_tenant())
    taken = _connect_zoom(client, rival, account)
    assert (taken.status_code, taken.json()["code"]) == (409, "account-in-use")
    assert client.post(f"{API}/external-connections/{first['id']}/disconnect", headers=owner).status_code == 200
    assert _connect_zoom(client, rival, account).status_code == 201


def test_the_simulated_zoom_app_is_refused_outside_dev_and_test(client, owner, monkeypatch):
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "env", "production")
    # outside dev and test `simulated` reaches the real adapter, whose token request is refused
    monkeypatch.setattr(ZoomVideo, "check_account", lambda self: (_ for _ in ()).throw(RuntimeError("refused")))
    refused = _connect_zoom(client, owner)
    assert (refused.status_code, refused.json()["code"]) == (422, "provider-unavailable")


# --- the member join ---------------------------------------------------------------------------------------


def _join(client, member, enrollment_id: str):
    return client.post(f"{API}/portal/enrollments/{enrollment_id}/join", headers=member)


def test_a_member_joins_their_own_place_inside_the_window_and_is_marked_attended(client, tenant, owner):
    f = facility(client, owner)
    client_id, member = _member(client, tenant, owner)
    soon = clock.now().replace(second=0, microsecond=0) + timedelta(minutes=5)
    later = soon + timedelta(hours=2)
    seat, early_seat = _session(client, owner, f, soon), _session(client, owner, f, later)
    for session_id in (seat, early_seat):
        ok(
            client.put(
                _meeting(session_id), headers=owner, json={"provider": "manual", "join_url": "https://m.example/x"}
            ),
            200,
        )
    place = ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": seat, "client_id": client_id}))
    early = ok(
        client.post(f"{API}/enrollments", headers=owner, json={"session_id": early_seat, "client_id": client_id})
    )

    too_soon = _join(client, member, early["id"])
    assert (too_soon.status_code, too_soon.json()["code"]) == (409, "policy-violation")
    joined = _join(client, member, place["id"])
    assert joined.status_code == 200 and joined.json()["join_url"] == "https://m.example/x", joined.text
    with tenant_session(tenant.id) as session:
        mark = session.scalar(select(Attendance).where(Attendance.enrollment_id == place["id"]))
        assert (mark.status, mark.source) == ("attended", "video_join")
    assert _join(client, member, place["id"]).status_code == 200  # a second click joins again, marks once

    _, stranger = _member(client, tenant, owner)
    assert _join(client, stranger, place["id"]).status_code == 404  # someone else's place
    assert _join(client, owner, place["id"]).status_code in (403, 404)  # staff use the staff screens


def test_disconnecting_zoom_stops_its_meetings_and_finished_sessions_take_none(client, tenant, owner):
    f = facility(client, owner)
    client_id, member = _member(client, tenant, owner)
    connection = _connect_zoom(client, owner).json()
    seat = _session(client, owner, f, clock.now().replace(second=0, microsecond=0) + timedelta(minutes=5))
    ok(client.put(_meeting(seat), headers=owner, json={"provider": "zoom"}), 200)
    place = ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": seat, "client_id": client_id}))
    ok(client.post(f"{API}/external-connections/{connection['id']}/disconnect", headers=owner), 200)
    meeting = ok(client.get(_meeting(seat), headers=owner), 200)
    assert (meeting["status"], meeting["last_error"]) == ("failed", "connection-disconnected")
    refused = _join(client, member, place["id"])
    assert (refused.status_code, refused.json()["code"]) == (409, "invalid-state-transition")

    past = _session(client, owner, f, clock.now().replace(second=0, microsecond=0) - timedelta(hours=3))
    late = client.put(_meeting(past), headers=owner, json={"provider": "manual", "join_url": "https://m.example/z"})
    assert (late.status_code, late.json()["code"]) == (409, "invalid-state-transition")


def test_a_zoom_meeting_follows_its_session_after_commit(client, tenant, owner, monkeypatch):
    from app.core.auth import system_principal
    from app.core.events import SUBSCRIBERS
    from app.modules.integrations import handlers, meetings

    assert handlers.move_virtual_meeting in SUBSCRIBERS["scheduling.booking.rescheduled"]  # runs after commit
    assert handlers.drop_virtual_meeting in SUBSCRIBERS["scheduling.session.cancelled"]
    calls: list = []
    monkeypatch.setattr(FakeVideo, "update_meeting", lambda self, mid, **kw: calls.append(("update", mid, kw)))
    monkeypatch.setattr(FakeVideo, "delete_meeting", lambda self, mid: calls.append(("delete", mid)))
    f = facility(client, owner)
    _connect_zoom(client, owner)
    created = ok(book(client, owner, f, [f.court], WHEN.isoformat(), (WHEN + timedelta(hours=1)).isoformat(),
                      kind="session", public_title="Online clinic"))  # fmt: skip
    booking = created.get("booking", created)
    seat = booking["session"]["id"]
    ok(client.put(_meeting(seat), headers=owner, json={"provider": "zoom"}), 200)
    later = WHEN + timedelta(days=1)
    moved = {"starts_at": later.isoformat(), "ends_at": (later + timedelta(minutes=90)).isoformat(),
             "version": booking["version"]}  # fmt: skip
    booking = ok(client.post(f"{API}/bookings/{booking['id']}/reschedule", headers=owner, json=moved), 200)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:  # the subscriber, after commit
        meetings.on_session_moved(session, UUID(booking["id"]))
    assert calls[0][0] == "update" and calls[0][2] == {"starts_at": later, "minutes": 90}

    cancel = {"version": booking["version"]}
    ok(client.post(f"{API}/bookings/{booking['id']}/cancel", headers=owner, json=cancel), 200)
    for _ in range(2):  # idempotent: a redelivered event finds nothing left to delete
        with tenant_session(tenant.id, actor=system_principal("tests")) as session:
            meetings.on_session_cancelled(session, UUID(seat))
    assert [c[0] for c in calls] == ["update", "delete"]
    assert client.get(_meeting(seat), headers=owner).status_code == 404


def test_a_zoom_host_id_cannot_walk_the_api_path(client, owner):
    f = facility(client, owner)
    seat = _session(client, owner, f, WHEN)
    for bad in ("..", ".", "../users", "a/b", "me?x=1", "%2e%2e", "%2e%2e%2f@x.com", "a%2fb@example.com"):
        body = {"provider": "zoom", "host_external_user_id": bad}
        assert client.put(_meeting(seat), headers=owner, json=body).status_code == 422, bad


def test_a_cancelled_place_cannot_join(client, tenant, owner):
    f = facility(client, owner)
    client_id, member = _member(client, tenant, owner)
    seat = _session(client, owner, f, clock.now().replace(second=0, microsecond=0) + timedelta(minutes=5))
    ok(client.put(_meeting(seat), headers=owner, json={"provider": "manual", "join_url": "https://m.example/y"}), 200)
    place = ok(client.post(f"{API}/enrollments", headers=owner, json={"session_id": seat, "client_id": client_id}))
    ok(client.post(f"{API}/enrollments/{place['id']}/cancel", headers=owner, json={}), 200)
    refused = _join(client, member, place["id"])
    assert (refused.status_code, refused.json()["code"]) == (409, "invalid-state-transition")
