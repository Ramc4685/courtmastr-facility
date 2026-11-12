"""CLI-11: the hourly actor sends task reminders once a task is due on the client's home-location day."""

from datetime import UTC, date, datetime

from app.core import clock
from app.modules.clients import activity
from conftest import new_client

API = "/api/v1"


def test_reminders_follow_each_clients_home_day_and_send_once(client, tenant, owner, mailbox):
    def site(zone: str) -> str:
        body = {"name": zone, "time_zone": zone, "country_code": "US"}
        return client.post(f"{API}/locations", headers=owner, json=body).json()["id"]

    ahead = new_client(client, owner, site("Pacific/Kiritimati"))  # UTC+14
    behind = new_client(client, owner, site("Pacific/Pago_Pago"))  # UTC-11
    due = date(2027, 1, 21)
    for person in (ahead, behind):
        body = {
            "client_id": person["id"],
            "subject_text": "Call back",
            "due_on": due.isoformat(),
            "has_email_reminder": True,
        }
        assert client.post(f"{API}/client-tasks", headers=owner, json=body).status_code == 201

    run = activity.send_client_task_reminders  # the dramatiq actor; calling it runs it here, as a worker would
    with clock.freeze(datetime(2027, 1, 20, 12, tzinfo=UTC)):  # Jan 21 at Kiritimati, Jan 20 at Pago Pago
        assert run(str(tenant.id)) == 1
        assert run(str(tenant.id)) == 0
    assert mailbox[-1].to == tenant.owner_email and ahead["last_name"] in mailbox[-1].body
    with clock.freeze(datetime(2027, 1, 21, 12, tzinfo=UTC)):
        assert run(str(tenant.id)) == 1
    assert behind["last_name"] in mailbox[-1].body


def test_overlapping_runs_send_a_reminder_once(client, tenant, owner):
    """Two runs at once (a slow hour overlapping the next): the second skips the row the first holds."""
    from sqlalchemy import text

    from app.core.auth import system_principal
    from app.core.db.session import tenant_session

    location_id = client.post(f"{API}/locations", headers=owner, json={"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}).json()["id"]  # fmt: skip
    person = new_client(client, owner, location_id)
    body = {"client_id": person["id"], "subject_text": "Call back", "due_on": "2026-01-02", "has_email_reminder": True}
    assert client.post(f"{API}/client-tasks", headers=owner, json=body).status_code == 201
    with tenant_session(tenant.id, actor=system_principal("first")) as first:
        assert activity.send_task_reminders(first) == 1  # flushed, not committed: the row is locked
        with tenant_session(tenant.id, actor=system_principal("second")) as second:
            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            assert activity.send_task_reminders(second) == 0


def test_horizon_covers_zones_two_local_days_apart(client, tenant, owner, mailbox):
    """At 11:00 UTC it is still yesterday at UTC-12 and already tomorrow at UTC+14: a task due tomorrow is due now
    at UTC+14 although the earliest local day is two days behind."""

    def site(zone: str) -> str:
        body = {"name": zone, "time_zone": zone, "country_code": "US"}
        return client.post(f"{API}/locations", headers=owner, json=body).json()["id"]

    site("Etc/GMT+12")  # UTC-12
    ahead = new_client(client, owner, site("Pacific/Kiritimati"))  # UTC+14
    body = {"client_id": ahead["id"], "subject_text": "Call back", "due_on": "2027-01-21", "has_email_reminder": True}
    assert client.post(f"{API}/client-tasks", headers=owner, json=body).status_code == 201
    with clock.freeze(datetime(2027, 1, 20, 11, tzinfo=UTC)):  # Jan 19 23:00 at UTC-12, Jan 21 01:00 at UTC+14
        assert activity.send_client_task_reminders(str(tenant.id)) == 1
