"""Group tools: classifiers (REG-03), list filters and saved views (REG-04), page settings (REG-06), moving
members (REG-08), location registration defaults (REG-11), and copy, series and export (REG-13)."""

import pytest

from app.modules.programs.tests.test_checkout import keyed
from app.modules.programs.tests.test_groups import fee_of, group_of, program, register
from app.modules.programs.tests.test_sessions import people
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import add_staff, login


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def code(response) -> tuple[int, str]:
    return response.status_code, response.json().get("code")


def test_classifiers_tag_and_filter_programs(client, owner, f):
    summer = ok(client.post(f"{API}/program-classifiers", headers=owner, json={"kind": "season", "title": "Summer"}))
    soccer = ok(client.post(f"{API}/program-classifiers", headers=owner, json={"kind": "sport", "title": "Soccer"}))
    dup = client.post(f"{API}/program-classifiers", headers=owner, json={"kind": "season", "title": "summer"})
    assert dup.status_code == 409
    wrong = client.post(f"{API}/program-groups", headers=owner,
                        json={"location_id": f.location, "name": "X", "season_classifier_id": soccer["id"]})  # fmt: skip
    assert wrong.status_code == 422
    camp = program(client, owner, f, season_classifier_id=summer["id"], description="Beach games")
    program(client, owner, f, name="Clinic")
    listed = ok(client.get(f"{API}/program-groups?season_classifier_id={summer['id']}", headers=owner), 200)["data"]
    assert [g["id"] for g in listed] == [camp["id"]]
    assert [g["id"] for g in ok(client.get(f"{API}/program-groups?q=beach", headers=owner), 200)["data"]] == [
        camp["id"]
    ]
    seasons = ok(client.get(f"{API}/program-classifiers?kind=season", headers=owner), 200)
    assert seasons[0]["group_count"] == 1
    assert code(client.delete(f"{API}/program-classifiers/{summer['id']}", headers=owner)) == (409, "in-use")
    off = ok(client.patch(f"{API}/program-classifiers/{summer['id']}", headers=owner, json={"is_active": False}), 200)
    assert off["is_active"] is False
    assert client.delete(f"{API}/program-classifiers/{soccer['id']}", headers=owner).status_code == 204


def test_saved_views_and_page_settings_are_per_staff_user(client, owner, tenant, f):
    other = login(client, tenant, add_staff(tenant, "admin", location_ids=[f.location])[0])
    view = ok(client.post(f"{API}/program-saved-views", headers=owner,
                          json={"name": "Camps", "filters": {"kind": "camp"}, "sort": "-starts_on"}))  # fmt: skip
    bad = client.post(f"{API}/program-saved-views", headers=owner, json={"name": "X", "filters": {"secret": "1"}})
    assert code(bad)[0] == 422
    assert code(client.post(f"{API}/program-saved-views", headers=owner, json={"name": "Y", "sort": "price"}))[0] == 422
    renamed = ok(
        client.patch(f"{API}/program-saved-views/{view['id']}", headers=owner, json={"name": "All camps"}), 200
    )
    assert renamed["name"] == "All camps"
    assert ok(client.get(f"{API}/program-saved-views", headers=other), 200) == []
    assert client.patch(f"{API}/program-saved-views/{view['id']}", headers=other, json={"name": "Z"}).status_code == 404

    url = f"{API}/program-page-settings/program_list"
    default = ok(client.get(url, headers=owner), 200)
    assert default["columns"] and "name" in default["available_columns"]
    saved = ok(client.put(url, headers=owner, json={"title": "Camps", "columns": ["name", "status"], "page_size": 25,
                                                   "default_view_id": view["id"]}), 200)  # fmt: skip
    assert saved["columns"] == ["name", "status"] and saved["default_view_id"] == view["id"]
    assert code(client.put(url, headers=owner, json={"columns": ["nope"]}))[0] == 422
    assert client.get(f"{API}/program-page-settings/unknown", headers=owner).status_code == 404
    assert client.delete(f"{API}/program-saved-views/{view['id']}", headers=owner).status_code == 204


def test_location_defaults_seed_new_programs(client, owner, f):
    url = f"{API}/locations/{f.location}/registration-defaults"
    assert ok(client.get(url, headers=owner), 200)["waitlist_mode"] == "manual"
    ok(client.put(url, headers=owner, json={"waitlist_mode": "auto_promote", "displays_openings": True,
                                            "confirmation_message": "See you there"}), 200)  # fmt: skip
    camp = program(client, owner, f)
    assert camp["waitlist_mode"] == "auto_promote"
    config = ok(client.put(f"{API}/program-groups/{camp['id']}/registration-config", headers=owner,
                           json={"is_enabled": True}), 200)  # fmt: skip
    assert config["displays_openings"] is True and config["confirmation_message"] == "See you there"


def test_move_members_between_groups(client, owner, f):
    a, b = program(client, owner, f, name="A"), program(client, owner, f, name="B", capacity=1)
    x, y = people(client, owner, f, 2)
    ex = ok(register(client, owner, a["id"], x))
    ey = ok(register(client, owner, a["id"], y))
    result = ok(client.post(f"{API}/enrollments/move", headers=owner,
                            json={"enrollment_ids": [ex["id"], ey["id"]], "to_program_group_id": b["id"]}), 200)  # fmt: skip
    assert [(o["moved"], o["code"]) for o in result["outcomes"]] == [(True, None), (False, "capacity-full")]
    assert group_of(client, owner, b["id"])["enrolled_count"] == 1
    assert group_of(client, owner, a["id"])["enrolled_count"] == 1
    same = ok(client.post(f"{API}/enrollments/move", headers=owner,
                          json={"enrollment_ids": [ex["id"]], "to_program_group_id": b["id"]}), 200)  # fmt: skip
    assert same["outcomes"][0]["code"] == "same-group"


def test_copy_series_and_export(client, owner, f):
    camp = program(client, owner, f, starts_on="2031-06-02", ends_on="2031-06-06")
    ok(client.post(f"{API}/program-groups", headers=owner, json={"parent_id": camp["id"], "name": "Week 1"}))
    fee = fee_of(client, owner, camp["id"], 5000)
    (person,) = people(client, owner, f, 1)
    ok(register(client, owner, camp["id"], person, program_fee_ids=[fee["id"]]))
    copy = ok(client.post(f"{API}/program-groups/{camp['id']}/copy", headers=owner,
                          json={"name": "Camp 2032", "starts_on": "2032-06-07"}))  # fmt: skip
    assert (copy["starts_on"], copy["ends_on"]) == ("2032-06-07", "2032-06-11") and copy["enrolled_count"] == 0
    children = ok(client.get(f"{API}/program-groups?parent_id={copy['id']}", headers=owner), 200)["data"]
    assert [c["name"] for c in children] == ["Week 1"]

    series = ok(client.post(f"{API}/program-groups/{camp['id']}/children/generate", headers=owner, json={
        "first_starts_on": "2031-07-07", "last_starts_on": "2031-07-21", "interval_weeks": 1, "include_children": False,
    }))  # fmt: skip
    assert [g["starts_on"] for g in series["created"]] == ["2031-07-07", "2031-07-14", "2031-07-21"]
    backwards = client.post(f"{API}/program-groups/{camp['id']}/children/generate", headers=owner,
                            json={"first_starts_on": "2031-07-21", "last_starts_on": "2031-07-07"})  # fmt: skip
    assert code(backwards)[0] == 422
    undated = program(client, owner, f, name="Undated")
    no_dates = client.post(f"{API}/program-groups/{undated['id']}/children/generate", headers=owner,
                           json={"first_starts_on": "2031-07-07", "last_starts_on": "2031-07-07"})  # fmt: skip
    assert code(no_dates) == (422, "template-needs-dates")

    csv = client.post(f"{API}/program-groups/{camp['id']}/exports", headers=keyed(owner))
    assert csv.status_code == 200 and csv.headers["content-disposition"].startswith("attachment")
    assert len(csv.text.splitlines()) == 2
