"""CLI-20: derived client alerts, computed on read from billing, memberships and documents, through the real route.
Each alert shows only to a caller with its owning context's read key; outside reach is 404."""

from datetime import timedelta
from uuid import UUID, uuid4

from app.core import clock
from app.core.auth import system_principal
from app.core.auth.principal import Principal
from app.core.db.session import tenant_session
from app.modules.memberships import service
from app.modules.memberships.tests.support import API, ok, sale, world
from conftest import add_staff, login, new_client


def _codes(client, headers, client_id) -> list[str]:
    return [a["code"] for a in ok(client.get(f"{API}/clients/{client_id}/system-alerts", headers=headers))]


def test_alerts_follow_the_owning_contexts_and_the_callers_keys(client, tenant, owner):
    w = world(client, owner, tenant, billing_occurrences_count=1)
    person = w.person["id"]
    assert _codes(client, owner, person) == []

    start = (clock.now() - timedelta(days=20)).date().isoformat()  # a one-month term that ends in about ten days
    sold = client.post(f"{API}/membership-contracts", headers=owner, json=sale(w, start_on=start))
    assert sold.status_code == 201, sold.text
    alerts = ok(client.get(f"{API}/clients/{person}/system-alerts", headers=owner))
    by_code = {a["code"]: a for a in alerts}
    assert set(by_code) == {"balance_due", "membership_expiring"}
    assert (
        by_code["balance_due"]["amount_minor"] == 3100 and by_code["membership_expiring"]["on"] == sold.json()["end_on"]
    )

    ok(client.patch(f"{API}/document-settings", headers=owner, json={"is_waiver_required_for_check_in": True}))
    assert "waiver_missing" in _codes(client, owner, person)

    league_email, _ = add_staff(tenant, "league_admin", location_ids=[w.location_id])
    league = login(client, tenant, league_email)  # billing and documents, but no memberships key
    assert sorted(_codes(client, league, person)) == ["balance_due", "waiver_missing"]
    viewer_email, _ = add_staff(tenant, "view_only", location_ids=[w.location_id])
    viewer = login(client, tenant, viewer_email)
    assert client.get(f"{API}/clients/{person}/system-alerts", headers=viewer).status_code == 403
    coach_email, _ = add_staff(tenant, "coach", location_ids=[w.location_id])
    coach = login(client, tenant, coach_email)  # own reach: not this client's trainer
    assert client.get(f"{API}/clients/{person}/system-alerts", headers=coach).status_code == 404
    other = new_client(client, owner, w.location_id)["id"]
    assert _codes(client, owner, other) == ["waiver_missing"]


def test_own_reach_on_a_section_key_hides_that_section(client, tenant, owner):
    """A caller who reaches every client but only their own memberships and documents must not learn another
    trainer's client's plan, end date or missing waiver. No system role mixes reach like this today, so the
    principal is built by hand; a section shows only when loading the client with that section's key works."""
    w = world(client, owner, tenant, billing_occurrences_count=1)
    person = w.person["id"]
    start = (clock.now() - timedelta(days=20)).date().isoformat()
    assert client.post(f"{API}/membership-contracts", headers=owner, json=sale(w, start_on=start)).status_code == 201
    ok(client.patch(f"{API}/document-settings", headers=owner, json={"is_waiver_required_for_check_in": True}))
    reach = {"clients.client.read": "all", "memberships.contract.read": "own", "documents.document.read": "own"}
    mixed = Principal(kind="staff", tenant_id=tenant.id, staff_user_id=uuid4(), permissions=reach)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert [a["code"] for a in service.client_alerts(session, mixed, UUID(person))] == []
        full = Principal(
            kind="staff", tenant_id=tenant.id, staff_user_id=uuid4(), permissions=dict.fromkeys(reach, "all")
        )
        assert {a["code"] for a in service.client_alerts(session, full, UUID(person))} == {
            "membership_expiring",
            "waiver_missing",
        }
