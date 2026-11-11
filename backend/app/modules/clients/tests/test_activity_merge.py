"""Notes, tasks, alerts and the timeline; duplicates and merge, with the merge-handler meta-test."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.auth import system_principal
from app.core.db import Base
from app.core.db.session import tenant_session
from app.modules import clients
from app.modules.clients.models import Client, ClientMerge
from app.modules.platform import privacy
from app.modules.platform.models import Identity
from conftest import add_staff, login, new_client

API = "/api/v1"
# Tables whose client foreign keys stay on the losing or erased record on purpose.
MERGE_ALLOWED = {"data_subject_request"}


@pytest.fixture
def location_id(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return client.post(f"{API}/locations", headers=owner, json=body).json()["id"]


def _tables_referencing_client() -> set[str]:
    return {
        table.name
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name == "client"
    }


def test_every_table_with_a_client_fk_has_merge_and_erase_handlers():
    merge_covered = {t for h in clients.merge.HANDLERS.values() for t in h.tables}
    erase_covered = {t for h in privacy.HANDLERS.values() for t in h.tables}
    referencing = _tables_referencing_client()
    assert referencing - merge_covered - MERGE_ALLOWED == set()
    assert referencing - erase_covered - MERGE_ALLOWED == set()


def test_notes_subjects_and_timeline(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    subject = client.post(f"{API}/note-subjects", headers=owner, json={"label": "Renewal"}).json()
    url = f"{API}/clients/{person['id']}/notes"
    both = client.post(url, headers=owner, json={"kind": "call", "note_subject_id": subject["id"], "subject_text": "x"})
    assert both.status_code == 422
    note = client.post(
        url, headers=owner, json={"kind": "call", "note_subject_id": subject["id"], "body": "Asked"}
    ).json()
    client.post(url, headers=owner, json={"kind": "email", "subject_text": "Price list"})
    assert len(client.get(url, headers=owner).json()["data"]) == 2
    assert len(client.get(url, headers=owner, params={"kind": "email"}).json()["data"]) == 1
    in_use = client.delete(f"{API}/note-subjects/{subject['id']}", headers=owner)
    assert in_use.json()["code"] == "in-use"
    switched = client.patch(f"{API}/client-notes/{note['id']}", headers=owner,
                            json={"note_subject_id": None, "subject_text": "Other"})  # fmt: skip
    assert switched.json()["subject_text"] == "Other"
    assert client.delete(f"{API}/note-subjects/{subject['id']}", headers=owner).status_code == 204
    client.post(
        f"{API}/clients/{person['id']}/alerts", headers=owner, json={"message": "Bad knee", "severity": "warning"}
    )
    timeline = client.get(f"{API}/clients/{person['id']}/timeline", headers=owner, params={"limit": 2}).json()
    assert len(timeline["data"]) == 2 and timeline["next_before"]
    rest = client.get(f"{API}/clients/{person['id']}/timeline", headers=owner,
                      params={"before": timeline["next_before"]}).json()  # fmt: skip
    assert {e["kind"] for e in timeline["data"] + rest["data"]} >= {"note", "alert", "audit"}
    assert client.delete(f"{API}/client-notes/{note['id']}", headers=owner).status_code == 204


def test_tasks_own_reach_counts_and_reminders(client, tenant, owner, location_id, mailbox):
    email, coach_id = add_staff(tenant, "coach", location_ids=[location_id])
    person = new_client(client, owner, location_id)
    client.put(
        f"{API}/clients/{person['id']}/owners", headers=owner, json={"default_trainer_staff_user_id": str(coach_id)}
    )
    coach = login(client, tenant, email)
    yesterday = (clock.now().date() - timedelta(days=1)).isoformat()
    mine = client.post(f"{API}/client-tasks", headers=coach, json={
        "client_id": person["id"], "subject_text": "Call", "due_on": yesterday, "has_email_reminder": True})  # fmt: skip
    assert mine.status_code == 201, mine.text
    mine = mine.json()
    other = {"client_id": person["id"], "subject_text": "x", "assignee_staff_user_id": str(tenant.owner_id)}
    assert client.post(f"{API}/client-tasks", headers=coach, json=other).status_code == 422
    owners_task = client.post(f"{API}/client-tasks", headers=owner, json=other).json()
    assert [t["id"] for t in client.get(f"{API}/client-tasks", headers=coach).json()["data"]] == [mine["id"]]
    assert client.patch(f"{API}/client-tasks/{owners_task['id']}", headers=coach, json={"body": "x"}).status_code == 404
    assert client.get(f"{API}/client-tasks/open-count", headers=coach).json() == {"open_count": 1, "overdue_count": 1}
    overdue = client.get(f"{API}/client-tasks", headers=owner, params={"overdue": "true"}).json()["data"]
    assert [t["id"] for t in overdue] == [mine["id"]]
    with tenant_session(tenant.id, actor=system_principal("reminders")) as session:
        assert clients.activity.send_task_reminders(session, clock.now().date()) == 1
        assert clients.activity.send_task_reminders(session, clock.now().date()) == 0
    assert mailbox[-1].to == email
    done = client.patch(f"{API}/client-tasks/{mine['id']}", headers=coach, json={"status": "done"}).json()
    assert done["completed_at"] and done["completed_by_staff_user_id"] == str(coach_id)


def test_alerts_show_where_and_when_set(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    url = f"{API}/clients/{person['id']}/alerts"
    today = clock.now().date()
    later = {"message": "Later", "starts_on": (today + timedelta(days=3)).isoformat()}
    client.post(url, headers=owner, json=later)
    now_alert = client.post(url, headers=owner, json={"message": "Now", "shows_on_booking": True}).json()
    bad = client.post(url, headers=owner, json={"message": "x", "starts_on": "2026-02-02", "ends_on": "2026-02-01"})
    assert bad.status_code == 422
    with tenant_session(tenant.id) as session:
        booking = clients.activity.active_alerts(session, person["id"], "booking", today)
        assert [a.message for a in booking] == ["Now"]
        assert len(clients.activity.active_alerts(session, person["id"], "check_in", today + timedelta(days=5))) == 2
    off = client.patch(f"{API}/client-alerts/{now_alert['id']}", headers=owner, json={"is_active": False}).json()
    assert off["is_active"] is False
    assert [a["message"] for a in client.get(url, headers=owner).json()] == ["Later", "Now"]


def test_duplicates_precheck_and_merge(client, tenant, owner, location_id):
    born = date(1999, 5, 5).isoformat()
    vip = client.post(f"{API}/tags", headers=owner, json={"label": "VIP"}).json()
    keep = new_client(client, owner, location_id, first_name="Lee", last_name="Ray", birth_on=born,
                      primary_email="lee@example.com", tag_ids=[vip["id"]])  # fmt: skip
    lose = new_client(client, owner, location_id, first_name="Lee", last_name="Ray", birth_on=born,
                      primary_email="lee@example.com", phone_mobile="+13125550111", member_number="OLD-1",
                      tag_ids=[vip["id"]])  # fmt: skip
    kid = new_client(client, owner, location_id)
    parent_of = next(
        t for t in client.get(f"{API}/relationship-types", headers=owner).json() if t["code"] == "parent_of"
    )
    client.post(f"{API}/clients/{lose['id']}/relationships", headers=owner,
                json={"other_client_id": kid["id"], "relationship_type_id": parent_of["id"]})  # fmt: skip
    client.post(f"{API}/clients/{lose['id']}/notes", headers=owner, json={"kind": "call", "subject_text": "Hi"})
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        for person in (keep, lose):
            identity = Identity(kind="client", email=f"{person['id']}@example.com", status="active")
            session.add(identity)
            session.flush()
            clients.service.link_identity(session, person["id"], identity.id)
        loser_identity = identity.id
    groups = client.get(f"{API}/client-duplicates", headers=owner).json()
    group = next(g for g in groups if g["client"]["id"] in (keep["id"], lose["id"]))
    assert {"same_birth_date", "shared_email"} <= set(group["candidates"][0]["reasons"])
    body = {"merged_client_ids": [lose["id"]]}
    check = client.post(f"{API}/clients/{keep['id']}/merge-precheck", headers=owner, json=body).json()
    assert check["can_merge"] and {"phone_mobile", "member_number"} <= set(check["backfill_fields"])
    assert [i["kind"] for i in check["review"]] == ["relationship"]  # acting rights never carry over (P-06)
    assert (
        client.post(
            f"{API}/clients/{keep['id']}/merge", headers=owner, json={"merged_client_ids": [keep["id"]]}
        ).status_code
        == 422
    )
    merged = client.post(f"{API}/clients/{keep['id']}/merge", headers=owner, json=body)
    assert merged.status_code == 200, merged.text
    merged = merged.json()
    assert merged["phone_mobile"] == "+13125550111" and merged["member_number"] == "OLD-1"
    assert [e["email"] for e in merged["emails"]] == ["lee@example.com"] and merged["tag_ids"] == [vip["id"]]
    rels = client.get(f"{API}/clients/{keep['id']}/relationships", headers=owner).json()
    assert rels == []
    assert len(client.get(f"{API}/clients/{keep['id']}/notes", headers=owner).json()["data"]) == 1
    tomb = client.get(f"{API}/clients/{lose['id']}", headers=owner).json()
    assert tomb["merged_into_id"] == keep["id"] and tomb["status"] == "disabled"
    assert client.patch(f"{API}/clients/{lose['id']}", headers=owner, json={"city": "x"}).status_code == 409
    again = client.post(f"{API}/clients/{keep['id']}/merge", headers=owner, json=body)
    assert again.status_code == 422
    with tenant_session(tenant.id) as session:
        assert session.get(Identity, loser_identity).status == "merged"  # the survivor kept its own login
        assert session.scalar(select(ClientMerge.backfilled_fields).where(ClientMerge.merged_client_id == lose["id"]))
        assert clients.service.resolve(session, lose["id"]).id == session.get(Client, keep["id"]).id


def test_merge_blocker_from_a_registered_handler(client, tenant, owner, location_id):
    keep, lose = new_client(client, owner, location_id), new_client(client, owner, location_id)
    clients.merge.register_merge_handler(
        "tests", tables=(), repoint=lambda *_: None,
        precheck=lambda session, loser, survivor: [{"code": "open-balance", "detail": "Owes money"}],
    )  # fmt: skip
    try:
        body = {"merged_client_ids": [lose["id"]]}
        check = client.post(f"{API}/clients/{keep['id']}/merge-precheck", headers=owner, json=body).json()
        assert not check["can_merge"] and check["blockers"][0]["code"] == "open-balance"
        blocked = client.post(f"{API}/clients/{keep['id']}/merge", headers=owner, json=body).json()
        assert blocked["code"] == "merge-blocked"
    finally:
        clients.merge.HANDLERS.pop("tests")
