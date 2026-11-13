"""Review fixes after phase 12: a failing schedule no longer starves the tenant's others, a schedule whose owner
lost access stops (and an admin can see and delete any schedule in their locations), and erasing a client purges
the report snapshots and export files that may name them."""

from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import platform
from app.modules.platform.models import StaffUser, StoredFile, UserLocationAccess
from app.modules.reporting import schedules, service
from app.modules.reporting.models import ExportJob, ReportRun, ReportSchedule
from app.modules.reporting.tests import test_exports_schedules as sched
from app.modules.reporting.tests.test_reporting import API, code, drain, ok, ran
from conftest import add_staff, login

world, same_day_everywhere, team = sched.world, sched.same_day_everywhere, sched.team  # shared fixtures
_saved, _schedule_body, _tick = sched._saved, sched._schedule_body, sched._tick


def _ticks(tenant) -> None:
    for _ in range(10):  # the hourly job re-sends while a schedule may be due
        if not _tick(tenant):
            return
    raise AssertionError("schedules kept falling due")


# --- 1. one failing schedule does not starve the others ------------------------------------------------------


def test_a_schedule_that_crashes_does_not_stop_the_next_one(client, tenant, owner, world, monkeypatch):
    broken = _saved(client, owner, "revenue_summary")
    healthy = _saved(client, owner, "deposits")
    first = ok(client.post(f"{API}/report-schedules", headers=owner,
                           json=_schedule_body(broken, world, [tenant.owner_id])), 201)  # fmt: skip
    second = ok(client.post(f"{API}/report-schedules", headers=owner,
                            json=_schedule_body(healthy, world, [tenant.owner_id])), 201)  # fmt: skip
    assert first["id"] < second["id"]  # ids are ordered: the broken one is picked first
    real = schedules.service.create_run

    def create_run(session, principal, data):
        if data["report_key"] == "revenue_summary":
            raise RuntimeError("renderer bug")
        return real(session, principal, data)

    monkeypatch.setattr(schedules.service, "create_run", create_run)
    _ticks(tenant)
    drain()  # leaves no queued export (and its email) for the next test
    with tenant_session(tenant.id) as session:
        assert session.get(ReportSchedule, first["id"]).last_run_on is not None  # claim advanced anyway
        assert session.get(ReportSchedule, second["id"]).last_run_on is not None
        keys = session.scalars(select(ExportJob.source_key).where(ExportJob.notify_on_complete)).all()
    assert keys == ["deposits"]


# --- 2. orphaned schedules -----------------------------------------------------------------------------------


def test_a_deactivated_owners_schedule_stops_and_says_why(client, tenant, owner, world, team, mailbox):
    saved = _saved(client, team.manager)
    made = ok(client.post(f"{API}/report-schedules", headers=team.manager,
                          json=_schedule_body(saved, world, [tenant.owner_id, team.manager_id])), 201)  # fmt: skip
    with tenant_session(tenant.id) as session:
        session.get_one(StaffUser, team.manager_id).is_active = False
    _ticks(tenant)
    drain()
    with tenant_session(tenant.id) as session:
        schedule = session.get_one(ReportSchedule, made["id"])
        assert schedule.is_active is False
        assert session.scalars(select(ExportJob).where(ExportJob.notify_on_complete)).all() == []
        actions = session.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == UUID(made["id"]))).all()
    assert "reporting.report_schedule.deactivate" in actions
    assert mailbox == []  # the owner (a recipient) gets nothing from a schedule its author may no longer run


@pytest.mark.parametrize("lost", ["keys", "location"])
def test_an_owner_who_lost_the_keys_or_the_location_stops_the_schedule(client, tenant, owner, world, team, lost):
    saved = _saved(client, team.manager)
    made = ok(client.post(f"{API}/report-schedules", headers=team.manager,
                          json=_schedule_body(saved, world, [tenant.owner_id])), 201)  # fmt: skip
    with tenant_session(tenant.id) as session:
        if lost == "keys":  # front desk runs no financial reports
            session.get_one(StaffUser, team.manager_id).role_id = platform.staff.ensure_system_roles(session)[
                "front_desk"
            ].id
        else:  # still a manager, now at North only: the schedule's location is Main
            session.execute(update(UserLocationAccess).where(UserLocationAccess.staff_user_id == team.manager_id)
                            .values(location_id=world.north))  # fmt: skip
    _ticks(tenant)
    drain()
    with tenant_session(tenant.id) as session:
        assert session.get_one(ReportSchedule, made["id"]).is_active is False
        assert session.scalars(select(ExportJob).where(ExportJob.notify_on_complete)).all() == []


def test_an_admin_sees_and_deletes_any_schedule_in_their_locations(client, tenant, owner, world, team):
    saved = _saved(client, team.manager)
    made = ok(client.post(f"{API}/report-schedules", headers=team.manager,
                          json=_schedule_body(saved, world, [team.manager_id])), 201)  # fmt: skip
    url = f"{API}/report-schedules"
    north_admin = login(client, tenant, add_staff(tenant, "admin", location_ids=[world.north])[0])
    main_admin = login(client, tenant, add_staff(tenant, "admin", location_ids=[world.main])[0])
    assert ok(client.get(url, headers=north_admin))["data"] == []
    assert code(client.delete(f"{url}/{made['id']}", headers=north_admin), 404) == "not-found"  # outside scope
    assert [s["id"] for s in ok(client.get(url, headers=main_admin))["data"]] == [made["id"]]
    assert code(client.patch(f"{url}/{made['id']}", headers=main_admin, json={"is_active": False}), 404)
    ok(client.delete(f"{url}/{made['id']}", headers=main_admin), 204)
    with tenant_session(tenant.id) as session:
        assert session.get(ReportSchedule, made["id"]) is None


# --- 3. erasure ----------------------------------------------------------------------------------------------


def test_erasing_a_client_purges_report_snapshots_and_export_files(client, tenant, owner, world):
    done = ran(client, owner, "client_export")
    job = ok(client.post(f"{API}/export-jobs", headers=owner, json={"report_run_id": done["id"], "format": "csv"}), 202)
    drain()
    assert client.get(f"{API}/export-jobs/{job['id']}/download", headers=owner).status_code == 200
    pending = ok(client.post(f"{API}/export-jobs", headers=owner, json={"report_run_id": done["id"]}), 202)
    with tenant_session(tenant.id) as session:
        session.get_one(ExportJob, pending["id"]).partial = b"Casey,casey@example.com"
        run_file = session.get_one(ReportRun, done["id"]).result_file_id
        export_file = session.get_one(ExportJob, job["id"]).file_id
    assert "reporting" in platform.privacy.HANDLERS
    with tenant_session(tenant.id, actor=system_principal("test")) as session:
        handler = platform.privacy.HANDLERS["reporting"]
        assert handler.export(session, UUID(world.person)) == {}
        result = handler.erase(session, UUID(world.person))
    assert result["purged_files"] >= 2
    assert code(client.get(f"{API}/report-runs/{done['id']}/rows", headers=owner), 404) == "not-found"
    assert code(client.get(f"{API}/export-jobs/{job['id']}/download", headers=owner), 404) == "not-found"
    with tenant_session(tenant.id) as session:
        assert {session.get_one(StoredFile, f).status for f in (run_file, export_file)} == {"purged"}
        stopped = session.get_one(ExportJob, pending["id"])
        assert stopped.partial is None and stopped.status == "failed"


def test_an_erasure_request_clears_reports_and_lets_todays_schedules_send_again(client, tenant, owner, world):
    done = ran(client, owner, "client_export")
    job = ok(client.post(f"{API}/export-jobs", headers=owner, json={"report_run_id": done["id"], "format": "csv"}), 202)
    drain()
    made = ok(client.post(f"{API}/report-schedules", headers=owner,
                          json=_schedule_body(_saved(client, owner), world, [tenant.owner_id])), 201)  # fmt: skip
    with tenant_session(tenant.id) as session:
        session.get_one(ReportSchedule, made["id"]).last_run_on = clock.now().date()  # sent today: links now dead
    request = ok(client.post(f"{API}/data-subject-requests", headers=owner,
                             json={"client_id": world.person, "kind": "erasure", "reason": "Asked by email"}), 201)  # fmt: skip
    finished = ok(client.post(f"{API}/data-subject-requests/{request['id']}/confirm", headers=owner,
                              json={"confirmation": "ERASE", "is_blocker_override": True}))  # fmt: skip
    assert finished["status"] == "completed"
    assert code(client.get(f"{API}/report-runs/{done['id']}/rows", headers=owner), 404) == "not-found"
    assert code(client.get(f"{API}/export-jobs/{job['id']}/download", headers=owner), 404) == "not-found"
    with tenant_session(tenant.id) as session:
        assert session.get_one(ReportSchedule, made["id"]).last_run_on is None  # re-sent with fresh links


def test_snapshot_writers_take_the_erasure_lock_shared_and_erasure_takes_it_exclusive(
    client, tenant, owner, world, monkeypatch
):
    taken: list[bool] = []
    real = service._snapshot_lock
    monkeypatch.setattr(service, "_snapshot_lock", lambda session, *, exclusive=False: (
        taken.append(exclusive), real(session, exclusive=exclusive))[1])  # fmt: skip
    done = ran(client, owner, "revenue_summary")
    ok(client.post(f"{API}/export-jobs", headers=owner, json={"report_run_id": done["id"]}), 202)
    drain()
    with tenant_session(tenant.id, actor=system_principal("test")) as session:
        service.erase_client(session, UUID(world.person))
    assert taken[0] is False and False in taken[1:-1] and taken[-1] is True  # run, export chunk(s), erase


def test_an_erasure_waits_for_a_snapshot_in_flight(tenant):
    with tenant_session(tenant.id) as writer:
        service._snapshot_lock(writer)  # a run building its snapshot, not yet committed
        with tenant_session(tenant.id) as eraser:
            eraser.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(OperationalError):
                service._snapshot_lock(eraser, exclusive=True)
            eraser.rollback()
