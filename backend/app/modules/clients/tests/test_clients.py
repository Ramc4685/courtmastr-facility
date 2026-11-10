"""clients skeleton: the record other contexts reference, its permissions and its link to an identity."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import Principal, system_principal
from app.core.db.session import tenant_session
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.core.events import OutboxEvent
from app.core.pagination import ListQuery
from app.modules import clients, platform
from app.modules.platform.models import Identity
from conftest import add_staff, login, new_client, scalar

API = "/api/v1"
SYSTEM = system_principal("tests")


@pytest.fixture
def location_id(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return client.post(f"{API}/locations", headers=owner, json=body).json()["id"]


def test_create_get_list_and_search(client, tenant, owner, location_id):
    body = {
        "first_name": " Ada ", "last_name": "Lovelace", "home_location_id": location_id,
        "primary_email": "Ada@Example.com", "phone_mobile": "+13125550100", "member_number": "M-100",
    }  # fmt: skip
    created = client.post(f"{API}/clients", headers=owner, json=body)
    assert created.status_code == 201, created.text
    ada = created.json()
    assert ada["first_name"] == "Ada" and ada["status"] == "active" and ada["member_number"] == "M-100"
    new_client(client, owner, location_id, first_name="Grace", last_name="Hopper")
    assert client.get(f"{API}/clients/{ada['id']}", headers=owner).json() == ada

    names = lambda query: [c["last_name"] for c in client.get(f"{API}/clients{query}", headers=owner).json()["data"]]  # noqa: E731
    assert names("") == ["Hopper", "Lovelace"]  # by name, case-insensitive
    assert names("?sort=-last_name") == ["Lovelace", "Hopper"]
    for term in ("lovel", "ADA@example", "m-100", "5550100"):  # name, email, member number, phone
        assert names(f"?q={term}") == ["Lovelace"], term
    assert names(f"?home_location_id={location_id}&status=active") == ["Hopper", "Lovelace"]
    assert names("?status=disabled") == []

    audit = scalar(tenant, select(AuditEvent).where(AuditEvent.entity_id == ada["id"]))
    assert audit.action == "clients.client.create" and "first_name" not in audit.changes  # no PII in the trail
    event = scalar(tenant, select(OutboxEvent).where(OutboxEvent.aggregate_id == ada["id"]))
    assert event.event_type == "clients.client.created" and event.payload["client_id"] == ada["id"]


def test_create_validation(client, tenant, owner, location_id):
    base = {"first_name": "A", "last_name": "B", "home_location_id": location_id}
    post = lambda **over: client.post(f"{API}/clients", headers=owner, json=base | over)  # noqa: E731
    assert post(phone_mobile="312-555-0100").status_code == 422  # E.164 only
    assert post(first_name="   ").status_code == 422
    assert post(primary_email="not-an-email").status_code == 422
    assert post(status="disabled").status_code == 422  # unknown fields are refused
    unknown = post(home_location_id="01900000-0000-7000-8000-000000000000")
    assert unknown.status_code == 422 and unknown.json()["errors"][0]["pointer"] == "/home_location_id"
    assert post(member_number="M-1").status_code == 201
    duplicate = post(member_number="m-1")  # citext: case-insensitive
    assert (duplicate.status_code, duplicate.json()["code"], duplicate.json()["field"]) == (
        409, "already-exists", "member_number",
    )  # fmt: skip
    before = scalar(tenant, select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_type == "client"))
    assert before == 1  # failed requests write no audit event


@pytest.mark.parametrize(
    ("role", "can_list", "can_create"),
    [("admin", True, True), ("front_desk", True, True), ("league_admin", True, True), ("coach", True, True),
     ("scorekeeper", False, False), ("view_only", False, False)],
)  # fmt: skip
def test_router_gate_follows_the_matrix(client, tenant, owner, location_id, role, can_list, can_create):
    email, _ = add_staff(tenant, role, location_ids=[location_id])
    headers = login(client, tenant, email)
    assert client.get(f"{API}/clients", headers=headers).status_code == (200 if can_list else 403)
    body = {"first_name": "A", "last_name": "B", "home_location_id": location_id}
    assert client.post(f"{API}/clients", headers=headers, json=body).status_code == (201 if can_create else 403)


def test_own_reach_sees_no_client_until_the_own_predicate_exists(client, tenant, owner, location_id):
    """Coaches hold clients.client.read with reach `own`. The predicate arrives later; meanwhile: nothing."""
    person = new_client(client, owner, location_id)
    email, _ = add_staff(tenant, "coach", location_ids=[location_id])
    coach = login(client, tenant, email)
    assert client.get(f"{API}/clients", headers=coach).json()["data"] == []
    assert client.get(f"{API}/clients/{person['id']}", headers=coach).status_code == 404


def test_clients_are_tenant_wide_not_location_scoped(client, tenant, owner, location_id):
    """CLI-19: a Front Desk user at one site can open a client whose home is another site."""
    other = client.post(
        f"{API}/locations", headers=owner, json={"name": "West", "time_zone": "America/Denver", "country_code": "US"}
    ).json()["id"]
    elsewhere = new_client(client, owner, other)
    email, _ = add_staff(tenant, "front_desk", location_ids=[location_id])
    desk = login(client, tenant, email)
    assert client.get(f"{API}/clients/{elsewhere['id']}", headers=desk).status_code == 200
    # ...but they cannot file a new client under a location they have no access to.
    body = {"first_name": "A", "last_name": "B", "home_location_id": other}
    assert client.post(f"{API}/clients", headers=desk, json=body).status_code == 422


def test_service_gate_without_the_router(tenant, client, owner, location_id):
    member = Principal(kind="client", tenant_id=tenant.id)
    desk = Principal(kind="staff", tenant_id=tenant.id, permissions={})
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        for principal in (member, desk):
            with pytest.raises(PermissionDenied):
                clients.service.list_clients(session, principal, ListQuery())
            with pytest.raises(PermissionDenied):
                clients.service.create_client(session, principal, {})


def test_internal_interface(client, tenant, owner, location_id):
    person = new_client(client, owner, location_id)
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        row = clients.service.require_active(session, person["id"])
        assert clients.service.display_name(row) == f"Casey {person['last_name']}"
        with pytest.raises(ValidationFailed) as unknown:
            clients.service.require_active(session, tenant.id, pointer="/payer_id")
        assert unknown.value.extra["errors"][0]["pointer"] == "/payer_id"
        with pytest.raises(NotFound):
            clients.service.get(session, tenant.id)
        row.status, row.disabled_at = "disabled", clock.now()  # module 4 owns the command; the rule is ours
        session.flush()
        with pytest.raises(ValidationFailed):
            clients.service.require_active(session, person["id"])
        assert clients.service.get(session, person["id"]).status == "disabled"

        identity = Identity(kind="client", email="casey@example.com", status="active")
        session.add(identity)
        session.flush()
        assert clients.service.client_ids_for_identity(session, identity.id) == []
        clients.service.link_identity(session, row.id, identity.id)
        clients.service.link_identity(session, row.id, identity.id)  # idempotent
        assert clients.service.client_ids_for_identity(session, identity.id) == [row.id]


# --- platform slices that ship with the kernel -------------------------------------------------------------


def test_counter_is_gapless_and_per_key(tenant):
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert [platform.service.next_number(session, "invoice") for _ in range(3)] == [1, 2, 3]
        assert platform.service.next_number(session, "receipt") == 1
    with pytest.raises(RuntimeError), tenant_session(tenant.id, actor=SYSTEM) as session:
        assert platform.service.next_number(session, "invoice") == 4
        raise RuntimeError("roll back")
    with tenant_session(tenant.id, actor=SYSTEM) as session:
        assert platform.service.next_number(session, "invoice") == 4  # the rolled-back number is reused


def test_counter_never_hands_out_a_number_twice_under_concurrency(tenant):
    def take(_):
        with tenant_session(tenant.id, actor=SYSTEM) as session:
            return platform.service.next_number(session, "booking_number")

    with ThreadPoolExecutor(8) as pool:
        numbers = list(pool.map(take, range(24)))
    assert sorted(numbers) == list(range(1, 25))


@pytest.mark.parametrize(
    ("zone", "at", "expected"),
    [
        ("America/Chicago", "2026-11-01T03:00:00", date(2026, 10, 31)),
        ("Asia/Kolkata", "2026-11-01T03:00:00", date(2026, 11, 1)),
        ("Pacific/Auckland", "2026-11-01T03:00:00", date(2026, 11, 1)),
        # US spring forward (2026-03-08) and fall back (2026-11-01): the local date flips at local midnight.
        ("America/Chicago", "2026-03-08T05:59:00", date(2026, 3, 7)),
        ("America/Chicago", "2026-03-08T06:00:00", date(2026, 3, 8)),
        ("America/Chicago", "2026-11-01T04:59:00", date(2026, 10, 31)),
        ("America/Chicago", "2026-11-01T05:00:00", date(2026, 11, 1)),
        # New Zealand: daylight time ends 2026-04-05, starts 2026-09-27.
        ("Pacific/Auckland", "2026-04-05T10:59:00", date(2026, 4, 5)),
        ("Pacific/Auckland", "2026-04-05T12:00:00", date(2026, 4, 6)),
        ("Pacific/Auckland", "2026-09-27T10:59:00", date(2026, 9, 27)),
        ("Pacific/Auckland", "2026-09-27T11:00:00", date(2026, 9, 28)),
        ("Asia/Kolkata", "2026-06-30T18:29:00", date(2026, 6, 30)),
        ("Asia/Kolkata", "2026-06-30T18:30:00", date(2026, 7, 1)),
    ],
)
def test_location_today_is_the_date_on_the_wall_there(client, tenant, owner, zone, at, expected):
    body = {"name": f"Site {zone}", "time_zone": zone, "country_code": "US"}
    location = client.post(f"{API}/locations", headers=owner, json=body).json()["id"]
    with clock.freeze(datetime.fromisoformat(at).replace(tzinfo=UTC)), tenant_session(tenant.id) as session:
        assert platform.service.location_today(session, location) == expected
        with pytest.raises(NotFound):
            platform.service.location_today(session, tenant.id)
