"""assessments (build module 13): categories and fields, recording results per client, per-field history, the
portal progress view, and the merge and erasure handlers, each through the API with both permission gates."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.audit import AuditEvent
from app.core.auth import passwords, system_principal
from app.core.db.session import tenant_session
from app.core.events import OutboxEvent
from app.modules import clients
from app.modules.assessments import subject
from app.modules.platform.models import Identity
from conftest import PASSWORD, add_staff, login, new_client, scalar

API = "/api/v1"


@pytest.fixture
def location_id(client, owner):
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    response = client.post(f"{API}/locations", headers=owner, json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def _code(response, status):
    assert response.status_code == status, response.text
    return response.json()["code"]


def _setup(client, owner):
    template = ok(client.post(f"{API}/assessment-templates", headers=owner, json={"name": "Fitness"}), 201)
    url = f"{API}/assessment-templates/{template['id']}/fields"
    weight = ok(client.post(url, headers=owner, json={
        "name": "Weight", "decimal_places": 1, "unit_label": "kg", "better_direction": "lower"}), 201)  # fmt: skip
    plank = ok(client.post(url, headers=owner, json={
        "name": "Plank", "unit_label": "s", "better_direction": "higher", "is_client_visible": False}), 201)  # fmt: skip
    return template, weight, plank


def _record(client, headers, person, location_id, when, values, status=201):
    body = {"client_id": person, "location_id": location_id, "recorded_at": when,
            "values": [{"assessment_field_id": f, "value": v} for f, v in values]}  # fmt: skip
    return ok(client.post(f"{API}/assessment-results", headers=headers, json=body), status)


def test_categories_and_fields_are_tenant_wide_definitions(client, tenant, owner, location_id):
    template, weight, plank = _setup(client, owner)
    assert _code(client.post(f"{API}/assessment-templates", headers=owner, json={"name": "fitness"}), 409) == (
        "already-exists"
    )
    url = f"{API}/assessment-templates/{template['id']}/fields"
    assert _code(client.post(url, headers=owner, json={"name": "WEIGHT"}), 409) == "already-exists"
    assert client.post(url, headers=owner, json={"name": "Grip", "decimal_places": 7}).status_code == 422
    listed = ok(client.get(f"{API}/assessment-templates", headers=owner))["data"]
    assert [f["name"] for f in listed[0]["fields"]] == ["Plank", "Weight"]
    archived = ok(client.patch(f"{API}/assessment-fields/{plank['id']}", headers=owner, json={"is_active": False}))
    assert archived["is_active"] is False
    ok(client.post(url, headers=owner, json={"name": "Plank"}), 201)  # an archived name is free again
    renamed = ok(client.patch(f"{API}/assessment-templates/{template['id']}", headers=owner, json={"name": "Fit"}))
    assert renamed["name"] == "Fit" and len(renamed["fields"]) == 3
    assert ok(client.get(f"{API}/assessment-templates?is_active=false", headers=owner))["data"] == []
    manager_email, _ = add_staff(tenant, "manager", all_locations=True)
    manager = login(client, tenant, manager_email)
    ok(client.post(f"{API}/assessment-templates", headers=manager, json={"name": "Mobility"}), 201)
    local_email, _ = add_staff(tenant, "manager", location_ids=[location_id])
    local = login(client, tenant, local_email)
    assert client.post(f"{API}/assessment-templates", headers=local, json={"name": "Speed"}).status_code == 403
    desk_email, _ = add_staff(tenant, "front_desk", all_locations=True)
    desk = login(client, tenant, desk_email)
    assert client.get(f"{API}/assessment-templates", headers=desk).status_code == 403
    assert client.post(url, headers=desk, json={"name": "Grip"}).status_code == 403


def test_recording_rounds_values_and_keeps_them_out_of_the_audit_trail(client, tenant, owner, location_id):
    _, weight, plank = _setup(client, owner)
    person = new_client(client, owner, location_id)["id"]
    result = _record(
        client, owner, person, location_id, "2031-01-06T15:00:00Z", [(weight["id"], "80.25"), (plank["id"], "61.5")]
    )
    values = {v["assessment_field_id"]: float(v["value"]) for v in result["values"]}
    assert values == {weight["id"]: 80.3, plank["id"]: 62}  # half-up to each field's decimal places
    assert result["recorded_by_staff_user_id"] == str(tenant.owner_id) and result["location_id"] == location_id
    assert scalar(tenant, select(func.count()).select_from(OutboxEvent)
                  .where(OutboxEvent.event_type == "assessments.result.recorded")) == 1  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        trail = [
            str(c) for c in session.scalars(select(AuditEvent.changes).where(AuditEvent.action.like("assessments.%")))
        ]
    assert trail and not any("80.3" in c or "62" in c for c in trail)  # values are health data: flag only
    twice = _record(
        client, owner, person, location_id, "2031-01-06T15:00:00Z", [(weight["id"], 1), (weight["id"], 2)], 422
    )
    assert twice["errors"][0]["pointer"] == "/values"
    unknown = _record(client, owner, person, location_id, "2031-01-06T15:00:00Z", [(str(uuid4()), 1)], 422)
    assert unknown["errors"][0]["pointer"] == "/values/0/assessment_field_id"
    ok(client.patch(f"{API}/assessment-fields/{plank['id']}", headers=owner, json={"is_active": False}))
    archived = _record(client, owner, person, location_id, "2031-01-06T15:00:00Z", [(plank["id"], 1)], 422)
    assert archived["errors"][0]["pointer"] == "/values/0/assessment_field_id"
    elsewhere = _record(client, owner, person, str(uuid4()), "2031-01-06T15:00:00Z", [(weight["id"], 1)], 422)
    assert elsewhere["errors"][0]["pointer"] == "/location_id"
    moved = ok(client.patch(f"{API}/assessment-results/{result['id']}", headers=owner,
                            json={"recorded_at": "2031-01-07T15:00:00Z", "note": "Re-weighed"}))  # fmt: skip
    assert moved["note"] == "Re-weighed" and len(moved["values"]) == 2  # values kept, their time moved
    series = ok(
        client.get(f"{API}/assessment-series?client_id={person}&assessment_field_id[in]={weight['id']}", headers=owner)
    )
    assert series["series"][0]["points"][0]["recorded_at"].startswith("2031-01-07")
    edited = ok(client.patch(f"{API}/assessment-results/{result['id']}", headers=owner,
                             json={"values": [{"assessment_field_id": weight["id"], "value": "79.94"}]}))  # fmt: skip
    assert [float(v["value"]) for v in edited["values"]] == [79.9]
    assert (
        client.get(
            f"{API}/assessment-series?client_id={person}&assessment_field_id[in]=nope", headers=owner
        ).status_code
        == 422
    )


def test_history_summarises_each_field_newest_first(client, owner, location_id):
    _, weight, plank = _setup(client, owner)
    person = new_client(client, owner, location_id)["id"]
    for day, kg, secs in (("01", "82", 40), ("15", "80.5", 75), ("29", "81", 60)):
        _record(
            client, owner, person, location_id, f"2031-01-{day}T15:00:00Z", [(weight["id"], kg), (plank["id"], secs)]
        )
    series = {
        s["assessment_field_id"]: s
        for s in ok(client.get(f"{API}/assessment-series?client_id={person}", headers=owner))["series"]
    }
    w, p = series[weight["id"]], series[plank["id"]]
    assert [float(x["value"]) for x in w["points"]] == [81, 80.5, 82]
    assert (float(w["latest_value"]), float(w["first_value"]), float(w["change"]), float(w["best_value"])) == (
        81,
        82,
        -1,
        80.5,
    )
    assert float(p["best_value"]) == 75
    window = ok(client.get(f"{API}/assessment-series?client_id={person}&recorded_at[gte]=2031-01-10T00:00:00Z"
                           f"&recorded_at[lte]=2031-01-20T00:00:00Z", headers=owner))["series"]  # fmt: skip
    assert {len(s["points"]) for s in window} == {1}
    page = ok(client.get(f"{API}/assessment-results?client_id={person}&limit=2", headers=owner))
    assert [r["recorded_at"][:10] for r in page["data"]] == ["2031-01-29", "2031-01-15"] and page["page"]["has_more"]


def test_coach_reaches_only_their_own_clients_and_cannot_delete(client, tenant, owner, location_id):
    _, weight, _ = _setup(client, owner)
    coach_email, coach_id = add_staff(tenant, "coach", location_ids=[location_id])
    coach = login(client, tenant, coach_email)
    mine = new_client(client, owner, location_id)["id"]
    owners = client.put(
        f"{API}/clients/{mine}/owners", headers=owner, json={"default_trainer_staff_user_id": str(coach_id)}
    )
    assert owners.status_code < 300, owners.text
    theirs = new_client(client, owner, location_id)["id"]
    recorded = _record(client, coach, mine, location_id, "2031-01-06T15:00:00Z", [(weight["id"], 70)])
    assert recorded["recorded_by_staff_user_id"] == str(coach_id)
    assert (
        _record(client, coach, theirs, location_id, "2031-01-06T15:00:00Z", [(weight["id"], 70)], 404)["code"]
        == "not-found"
    )
    other = _record(client, owner, theirs, location_id, "2031-01-06T15:00:00Z", [(weight["id"], 90)])
    assert client.get(f"{API}/assessment-results/{other['id']}", headers=coach).status_code == 404
    assert client.get(f"{API}/assessment-results?client_id={theirs}", headers=coach).status_code == 404
    assert client.get(f"{API}/assessment-series?client_id={theirs}", headers=coach).status_code == 404
    assert client.delete(f"{API}/assessment-results/{recorded['id']}", headers=coach).status_code == 403
    ok(client.delete(f"{API}/assessment-results/{recorded['id']}", headers=owner), 204)
    assert client.get(f"{API}/assessment-results/{recorded['id']}", headers=owner).status_code == 404
    deleted = scalar(
        tenant, select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "assessments.assessment.delete")
    )
    assert deleted == 1


def _portal(client, owner, tenant, location_id):
    person = new_client(client, owner, location_id, primary_email=f"pat-{uuid4().hex[:6]}@example.com")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = Identity(
            kind="client", email=person["primary_email"], status="active", email_verified_at=clock.now(),
            password_hash=passwords.hash_password(PASSWORD),
        )  # fmt: skip
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, person["id"], identity.id)
    return person["id"], login(client, tenant, person["primary_email"], audience="client")


def test_portal_shows_visible_fields_and_bests_only_when_sharing_is_on(client, tenant, owner, location_id):
    _, weight, plank = _setup(client, owner)
    me, portal = _portal(client, owner, tenant, location_id)
    for day, kg in (("01", "82"), ("15", "80"), ("29", "81")):
        _record(client, owner, me, location_id, f"2031-01-{day}T15:00:00Z", [(weight["id"], kg), (plank["id"], 50)])
    _record(client, owner, me, location_id, "2031-02-01T15:00:00Z", [(plank["id"], 90)])  # hidden field only
    assert client.get(f"{API}/portal/assessment-results", headers=portal).status_code == 404  # sharing off
    ok(client.patch(f"{API}/assessment-settings", headers=owner, json={"is_portal_sharing_enabled": True}))
    assert ok(client.get(f"{API}/assessment-settings", headers=owner))["is_portal_sharing_enabled"] is True
    results = ok(client.get(f"{API}/portal/assessment-results", headers=portal))["data"]
    assert len(results) == 3 and all(len(r["values"]) == 1 for r in results)
    assert results[0]["values"][0]["field_name"] == "Weight" and "note" not in results[0]
    [best] = ok(client.get(f"{API}/portal/assessment-bests", headers=portal))
    assert (float(best["best_value"]), best["best_recorded_at"][:10], float(best["latest_value"])) == (
        80,
        "2031-01-15",
        81,
    )
    stranger = new_client(client, owner, location_id)["id"]
    assert client.get(f"{API}/portal/assessment-results?client_id={stranger}", headers=portal).status_code == 404
    assert client.get(f"{API}/portal/assessment-bests", headers=owner).status_code in (403, 404)


def test_merge_moves_results_and_erasure_deletes_them(client, tenant, owner, location_id):
    _, weight, _ = _setup(client, owner)
    keep = new_client(client, owner, location_id, first_name="Jo", last_name="Same")["id"]
    dup = new_client(client, owner, location_id, first_name="Jo", last_name="Same")["id"]
    moved = _record(client, owner, dup, location_id, "2031-01-06T15:00:00Z", [(weight["id"], 70)])
    ok(client.post(f"{API}/clients/{keep}/merge", headers=owner, json={"merged_client_ids": [dup]}))
    assert ok(client.get(f"{API}/assessment-results/{moved['id']}", headers=owner))["client_id"] == keep
    assert len(ok(client.get(f"{API}/assessment-series?client_id={keep}", headers=owner))["series"][0]["points"]) == 1
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        exported = subject._export(session, keep)
        assert exported["assessment_results"][0]["values"][0]["value"].startswith("70")
        assert subject._erase(session, keep) == {"deleted_assessment_results": 1}
    assert client.get(f"{API}/assessment-results/{moved['id']}", headers=owner).status_code == 404


def test_w2_09_an_out_of_reach_client_is_404_before_any_422(client, tenant, owner, location_id):
    """A disabled or unknown client outside the coach's reach must not answer 422: that would confirm it exists."""
    _, weight, _ = _setup(client, owner)
    coach_email, _ = add_staff(tenant, "coach", location_ids=[location_id])
    coach = login(client, tenant, coach_email)
    theirs = new_client(client, owner, location_id)["id"]
    ok(client.post(f"{API}/clients/{theirs}/disable", headers=owner, json={}))
    for person in (theirs, str(uuid4())):
        when, values = "2031-01-06T15:00:00Z", [(weight["id"], 70)]
        assert _record(client, coach, person, location_id, when, values, 404)["code"] == "not-found"
    assert _record(client, owner, theirs, location_id, "2031-01-06T15:00:00Z", [(weight["id"], 70)], 422)


def test_fit_05_share_link_is_revocable_and_expires(client, tenant, owner, location_id):
    """FIT-05 (phase 11 B): a client shares a read-only progress view through a fragment-token link."""
    _, weight, plank = _setup(client, owner)
    me, portal = _portal(client, owner, tenant, location_id)
    _record(client, owner, me, location_id, "2031-01-01T15:00:00Z", [(weight["id"], "82"), (plank["id"], 50)])
    links = f"{API}/portal/progress-share-links"
    lookup = f"{API}/public/progress-shares/lookup"
    public = {"X-Tenant-Slug": tenant.slug}
    assert client.post(links, headers=portal, json={}).status_code == 404  # sharing off
    ok(client.patch(f"{API}/assessment-settings", headers=owner, json={"is_portal_sharing_enabled": True}))
    made = ok(client.post(links, headers=portal, json={"label": "Coach Sam", "expires_in_days": 7}), 201)
    token = made["token"]
    assert made["url"].endswith(f"/progress#token={token}") and made["is_active"]
    [listed] = ok(client.get(links, headers=portal))
    assert listed["id"] == made["id"] and "token" not in listed
    shared = ok(client.post(lookup, headers=public, json={"token": token}))
    assert shared["first_name"] and len(shared["results"]) == 1 and len(shared["results"][0]["values"]) == 1
    assert "last_name" not in shared and "client_id" not in shared
    assert shared["time_zone"] == ok(client.get(f"{API}/locations/{location_id}", headers=owner))["time_zone"]
    with tenant_session(tenant.id) as session:
        trail = session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "progress_share_link")).all()
        assert trail and all(token not in str(e.changes) for e in trail)
    with clock.freeze(clock.now() + timedelta(days=8)):
        assert client.post(lookup, headers=public, json={"token": token}).status_code == 404  # expired
    assert client.post(lookup, headers=public, json={"token": "x" * 43}).status_code == 404
    stranger = new_client(client, owner, location_id)["id"]
    assert client.post(links, headers=portal, json={"client_id": stranger}).status_code == 404
    revoke = f"{links}/{made['id']}/revoke"
    assert client.post(revoke, headers=portal).status_code == 204
    assert client.post(revoke, headers=portal).status_code == 204  # idempotent
    [gone] = [row for row in ok(client.get(links, headers=portal)) if row["id"] == made["id"]]
    assert gone["is_active"] is False and gone["revoked_at"]
    assert client.post(lookup, headers=public, json={"token": token}).status_code == 404
    again = ok(client.post(links, headers=portal, json={}), 201)
    ok(client.patch(f"{API}/assessment-settings", headers=owner, json={"is_portal_sharing_enabled": False}))
    assert client.post(lookup, headers=public, json={"token": again["token"]}).status_code == 404
