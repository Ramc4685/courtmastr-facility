"""Permission enforcement, the role matrix, overrides and the escalation rules (rbac-matrix.md section 13)."""

import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.auth import CATALOGUE, Principal, system_role_grants
from app.core.auth.permissions import SYSTEM_ROLES
from app.core.db.session import tenant_session
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery
from app.modules.platform import rbac, service, staff
from app.modules.platform.models import AuthSession, StaffUser, UserPermissionOverride
from conftest import add_staff, link_token, login, role_id, scalar

API = "/api/v1"
MATRIX = Path(__file__).resolve().parents[5] / "docs" / "architecture" / "rbac-matrix.md"


def _matrix_rows(context: str = "platform") -> dict[str, dict]:
    """Parse one context's table in section 6 of rbac-matrix.md: key -> {scope, flags, own, roles}."""
    section = re.split(r"### 6\.\d+ ", MATRIX.read_text().split(f" {context}\n")[1])[0]
    columns = [key for key, (column, _) in SYSTEM_ROLES.items() if column != "-"]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if match := re.fullmatch(rf"`({context}\.[\w.]+)`", cells[0]):
            grants = {
                role: "all" if cell == "Y" else cell
                for role, cell in zip(columns, cells[4:11], strict=True)
                if cell != "-"
            }
            rows[match[1]] = {
                "scope": cells[1],
                "flags": tuple(cells[2].split()),
                "own": cells[3] == "own",
                "roles": grants,
            }
    return rows


# A context joins this list when it registers its catalogue: (package name, rows in its rbac-matrix table).
@pytest.mark.parametrize(
    ("context", "count"),
    [
        ("platform", 28), ("clients", 16), ("billing", 39), ("pos", 15), ("documents", 6), ("memberships", 13),
        ("packages", 9), ("resources", 5), ("scheduling", 20), ("rentals", 11),
        ("access", 12),
    ],
)  # fmt: skip
def test_catalogue_matches_the_rbac_matrix_document(context, count):
    """Matrix conformance: the document cannot drift from permissions.py."""
    rows = _matrix_rows(context)
    in_code = {key: p for key, p in CATALOGUE.items() if p.context == context}
    assert set(rows) == set(in_code) and len(rows) == count
    for key, row in rows.items():
        permission = in_code[key]
        assert permission.scope.value[0].upper() == row["scope"], key
        assert permission.flags == row["flags"], key
        assert permission.roles == row["roles"], key
        assert permission.accepts_own_reach == row["own"], key


def test_every_registered_context_is_checked_against_the_matrix():
    assert {p.context for p in CATALOGUE.values()} == {
        "platform", "clients", "billing", "pos", "documents", "memberships", "packages", "resources", "scheduling",
        "rentals",
        "access",
    }  # fmt: skip


def test_system_role_grants_resolve_from_code():
    assert set(system_role_grants("owner")) == set(CATALOGUE)
    assert "platform.tenant.manage_subscription" not in system_role_grants("admin")  # owner-only
    assert "platform.support_access.grant" not in system_role_grants("admin")  # owner-default
    platform_grants = lambda role: {k for k in system_role_grants(role) if k.startswith("platform.")}  # noqa: E731
    assert platform_grants("manager") == {
        "platform.location.update", "platform.staff_user.read", "platform.role.read", "platform.audit.read",
        "platform.import_job.read",
    }  # fmt: skip
    for role in ("front_desk", "coach", "league_admin", "scorekeeper", "view_only"):
        assert platform_grants(role) == set()
    assert system_role_grants("coach")["clients.client.read"] == "own"
    assert system_role_grants("scorekeeper") == {}
    assert system_role_grants("view_only") == {"scheduling.booking.read": "all"}  # reads the schedule only


@pytest.fixture
def people(client, tenant):
    """One signed-in user per interesting role, plus a location."""
    owner = login(client, tenant)
    location = client.post(
        f"{API}/locations", headers=owner, json={"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    ).json()
    out = {"owner": owner, "location_id": location["id"], "ids": {"owner": str(tenant.owner_id)}}
    for key in ("admin", "manager", "front_desk"):
        email, staff_user_id = add_staff(tenant, key, location_ids=[location["id"]], all_locations=key == "admin")
        out[key], out["ids"][key] = login(client, tenant, email), str(staff_user_id)
    return out


@pytest.mark.parametrize(
    ("role", "method", "path", "status"),
    [
        ("front_desk", "GET", "/tenant", 200),  # configuration reads need no key
        ("front_desk", "GET", "/locations", 200),
        ("front_desk", "GET", "/staff-users", 403),
        ("front_desk", "GET", "/roles", 403),
        ("front_desk", "GET", "/audit-events", 403),
        ("front_desk", "PATCH", "/tenant", 403),
        ("manager", "GET", "/staff-users", 200),
        ("manager", "GET", "/roles", 200),
        ("manager", "GET", "/permissions", 200),
        ("manager", "GET", "/audit-events", 200),
        ("manager", "PATCH", "/tenant", 403),
        ("manager", "POST", "/locations", 403),
        ("manager", "POST", "/roles", 403),
        ("manager", "POST", "/staff-users", 403),
        ("admin", "PATCH", "/tenant", 200),
        ("admin", "GET", "/staff-users", 200),
    ],
)
def test_router_gate_follows_the_matrix(client, people, role, method, path, status):
    response = client.request(method, f"{API}{path}", headers=people[role], json={} if method != "GET" else None)
    assert response.status_code == status, response.text
    if status == 403:
        body = response.json()
        assert body["code"] == "permission-denied" and body["required"].startswith("platform.")


def test_service_gate_denies_without_the_router(tenant):
    """Two-gate rule: mutating service functions deny an unprivileged principal even when called directly."""
    nobody = Principal(
        kind="staff", tenant_id=tenant.id, staff_user_id=uuid4(), permissions={}, location_ids=frozenset()
    )
    client_principal = Principal(kind="client", tenant_id=tenant.id, identity_id=uuid4())
    some_id = uuid4()
    calls = [
        lambda s, p: service.update_tenant(s, p, {"name": "x"}),
        lambda s, p: service.create_location(s, p, {"name": "x", "time_zone": "UTC"}),
        lambda s, p: service.list_audit_events(s, p, ListQuery()),
        lambda s, p: staff.list_staff_users(s, p, ListQuery()),
        lambda s, p: staff.invite_staff_user(s, p, {}),
        lambda s, p: staff.update_staff_user(s, p, some_id, {}),
        lambda s, p: staff.deactivate_staff_user(s, p, some_id),
        lambda s, p: staff.reactivate_staff_user(s, p, some_id),
        lambda s, p: staff.resend_invitation(s, p, some_id),
        lambda s, p: staff.reset_credentials(s, p, some_id),
        lambda s, p: staff.assign_role(s, p, some_id, some_id),
        lambda s, p: staff.assign_locations(s, p, some_id, {}),
        lambda s, p: staff.replace_permission_overrides(s, p, some_id, []),
        lambda s, p: staff.reset_permissions(s, p, some_id),
        lambda s, p: staff.list_roles(s, p, ListQuery()),
        lambda s, p: staff.create_role(s, p, {"name": "x"}),
        lambda s, p: staff.update_role(s, p, some_id, {}),
        lambda s, p: staff.replace_role_permissions(s, p, some_id, []),
        lambda s, p: staff.delete_role(s, p, some_id),
    ]
    with tenant_session(tenant.id) as session:
        for principal in (nobody, client_principal):
            for call in calls:
                with pytest.raises(PermissionDenied):
                    call(session, principal)
        with pytest.raises(NotFound):  # location reads are scope-checked rather than key-checked
            service.get_location(session, nobody, some_id)


def test_custom_role_lifecycle(client, tenant, people):
    owner = people["owner"]
    manager_role = str(role_id(tenant, "manager"))
    blank = client.post(f"{API}/roles", headers=owner, json={"name": "Accountant", "description": "Read-only finance"})
    assert blank.status_code == 201 and blank.json()["permissions"] == [] and blank.json()["is_system"] is False
    clone = client.post(
        f"{API}/roles", headers=owner, json={"name": "Site Lead", "clone_from_role_id": manager_role}
    ).json()
    assert {g["permission_key"] for g in clone["permissions"]} == set(system_role_grants("manager"))
    assert clone["cloned_from_role_id"] == manager_role
    assert (
        client.post(f"{API}/roles", headers=owner, json={"name": "site lead"}).json()["code"] == "already-exists"
    )  # citext

    role_url = f"{API}/roles/{blank.json()['id']}"
    grants = {
        "grants": [
            {"permission_key": "platform.audit.read", "is_allowed": True},
            {"permission_key": "platform.role.read", "is_allowed": False},
        ]
    }
    replaced = client.put(f"{role_url}/permissions", headers=owner, json=grants).json()
    assert [g["permission_key"] for g in replaced["permissions"]] == ["platform.audit.read"]  # roles hold no deny rows
    assert client.patch(role_url, headers=owner, json={"name": "Bookkeeper"}).json()["name"] == "Bookkeeper"
    unknown = client.put(
        f"{role_url}/permissions", headers=owner, json={"grants": [{"permission_key": "nope.x.y", "is_allowed": True}]}
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown-permission"
    owner_only = {"grants": [{"permission_key": "platform.tenant.close", "is_allowed": True}]}
    assert client.put(f"{role_url}/permissions", headers=owner, json=owner_only).json()["code"] == "unknown-permission"

    listed = client.get(f"{API}/roles?include=total", headers=owner).json()
    assert listed["page"]["total"] == len(SYSTEM_ROLES) + 2
    assert next(r for r in listed["data"] if r["system_key"] == "owner")["staff_user_count"] == 1
    assert client.get(f"{API}/roles?is_system=false", headers=owner).json()["data"][0]["name"] in (
        "Bookkeeper",
        "Site Lead",
    )
    manager_grants = client.get(f"{API}/roles/{manager_role}", headers=owner).json()["permissions"]
    assert len([g for g in manager_grants if g["permission_key"].startswith("platform.")]) == 5

    # System roles are locked; a role in use cannot be deleted.
    for response in (
        client.patch(f"{API}/roles/{manager_role}", headers=owner, json={"name": "Boss"}),
        client.put(f"{API}/roles/{manager_role}/permissions", headers=owner, json={"grants": []}),
        client.delete(f"{API}/roles/{manager_role}", headers=owner),
    ):
        assert response.status_code == 409 and response.json()["code"] == "system-role-immutable"
    assert (
        client.put(
            f"{API}/staff-users/{people['ids']['front_desk']}/role", headers=owner, json={"role_id": clone["id"]}
        ).status_code
        == 200
    )
    in_use = client.delete(f"{API}/roles/{clone['id']}", headers=owner)
    assert in_use.status_code == 409 and in_use.json()["code"] == "role-in-use"
    assert client.delete(role_url, headers=owner).status_code == 204
    assert client.get(role_url, headers=owner).status_code == 404
    # The front-desk user now holds the cloned role's grants, resolved on the next request.
    assert client.get(f"{API}/staff-users", headers=people["front_desk"]).status_code == 200
    catalogue = client.get(f"{API}/permissions?context=platform", headers=owner).json()
    assert catalogue["page"]["total"] == 28 and catalogue["data"][0]["scope"] in ("tenant", "location")


def test_overrides_are_sparse_deltas(client, tenant, people):
    owner, desk_id, manager_id = people["owner"], people["ids"]["front_desk"], people["ids"]["manager"]
    url = f"{API}/staff-users/{desk_id}"
    grants = {"grants": [
        {"permission_key": "platform.staff_user.read", "is_allowed": True},
        {"permission_key": "platform.role.read", "is_allowed": False},  # the role does not grant it: redundant
    ]}  # fmt: skip
    view = client.put(f"{url}/permission-overrides", headers=owner, json=grants).json()
    assert view["is_diverged_from_role"] is True
    assert [o["permission_key"] for o in view["overrides"]] == ["platform.staff_user.read"]
    assert [e for e in view["effective"] if e["key"].startswith("platform.")] == [
        {
            "key": "platform.staff_user.read",
            "reach": "all",
            "subject_type": None,
            "subject_ids": None,
            "source": "override",
        }
    ]
    assert client.get(f"{API}/staff-users", headers=people["front_desk"]).status_code == 200
    assert client.get(url, headers=owner).json()["has_permission_overrides"] is True

    # A deny override takes a key away from a manager.
    deny = {"grants": [{"permission_key": "platform.role.read", "is_allowed": False}]}
    assert (
        client.put(f"{API}/staff-users/{manager_id}/permission-overrides", headers=owner, json=deny).status_code == 200
    )
    assert client.get(f"{API}/roles", headers=people["manager"]).status_code == 403
    assert (
        client.get(f"{API}/staff-users/{manager_id}/permissions", headers=owner).json()["is_diverged_from_role"] is True
    )

    # Reset to role, and role assignment drops overrides unless told otherwise.
    reset = client.post(f"{API}/staff-users/{manager_id}/permissions/reset", headers=owner).json()
    assert reset["overrides"] == [] and reset["is_diverged_from_role"] is False
    assert client.get(f"{API}/roles", headers=people["manager"]).status_code == 200
    kept = client.put(
        f"{url}/role", headers=owner, json={"role_id": str(role_id(tenant, "view_only")), "reset_overrides": False}
    )
    assert kept.json()["has_permission_overrides"] is True and kept.json()["role"]["system_key"] == "view_only"
    dropped = client.put(f"{url}/role", headers=owner, json={"role_id": str(role_id(tenant, "coach"))})
    assert dropped.json()["has_permission_overrides"] is False
    assert scalar(tenant, select(func.count()).select_from(UserPermissionOverride)) == 0
    assert (
        client.put(
            f"{url}/permission-overrides",
            headers=owner,
            json={"grants": [{"permission_key": "x.y.z", "is_allowed": False}]},
        ).json()["code"]
        == "unknown-permission"
    )
    assert (
        client.put(
            f"{API}/staff-users/{tenant.owner_id}/permission-overrides", headers=people["admin"], json={"grants": []}
        ).status_code
        == 409
    )


def test_staff_update_guards_security_fields(client, tenant, people):
    owner, admin, ids = people["owner"], people["admin"], people["ids"]

    def patch(headers, staff_user_id, body):
        response = client.patch(f"{API}/staff-users/{staff_user_id}", headers=headers, json=body)
        return response.status_code, response.json().get("code")

    # No self-service on security fields, even as owner; ordinary profile fields stay editable.
    for body in ({"access_expires_on": "2099-12-31"}, {"ip_policy": "facility_networks"}):
        assert patch(admin, ids["admin"], body) == (403, "self-escalation")
    assert patch(owner, ids["owner"], {"ip_policy": "facility_networks"}) == (403, "self-escalation")
    assert patch(admin, ids["admin"], {"first_name": "Ada", "ip_policy": "any"})[0] == 200  # unchanged value is fine

    # ip_policy on someone else needs platform.security.manage.
    deny = {"grants": [{"permission_key": "platform.security.manage", "is_allowed": False}]}
    assert (
        client.put(f"{API}/staff-users/{ids['admin']}/permission-overrides", headers=owner, json=deny).status_code
        == 200
    )
    assert patch(admin, ids["manager"], {"ip_policy": "facility_networks"})[0] == 403
    assert patch(admin, ids["manager"], {"access_expires_on": "2099-12-31"})[0] == 200
    allow = {"grants": []}
    assert (
        client.put(f"{API}/staff-users/{ids['admin']}/permission-overrides", headers=owner, json=allow).status_code
        == 200
    )
    assert patch(admin, ids["manager"], {"ip_policy": "facility_networks"})[0] == 200

    # Only listed fields: the API rejects extras, and so does the service if a caller passes them through.
    assert patch(admin, ids["manager"], {"is_active": False})[0] == 422
    with tenant_session(tenant.id) as session:
        principal = rbac.staff_principal(session, session.get(StaffUser, UUID(ids["admin"])))
        session.info["actor"] = principal
        with pytest.raises(ValidationFailed) as refused:
            staff.update_staff_user(session, principal, UUID(ids["manager"]), {"role_id": role_id(tenant, "owner")})
    assert refused.value.code == "unknown-field"


def test_escalation_rules(client, tenant, people):
    owner, admin, ids = people["owner"], people["admin"], people["ids"]
    owner_role, admin_role = str(role_id(tenant, "owner")), str(role_id(tenant, "admin"))

    def code(response):
        return response.status_code, response.json()["code"]

    # 1. No grant beyond self: an admin cannot hand out an owner-default key it does not hold.
    od = {"grants": [{"permission_key": "platform.support_access.grant", "is_allowed": True}]}
    assert code(client.put(f"{API}/staff-users/{ids['manager']}/permission-overrides", headers=admin, json=od)) == (
        403,
        "self-escalation",
    )
    custom = client.post(f"{API}/roles", headers=admin, json={"name": "Helper"}).json()
    assert code(client.put(f"{API}/roles/{custom['id']}/permissions", headers=admin, json=od)) == (
        403,
        "self-escalation",
    )
    assert code(
        client.post(f"{API}/roles", headers=admin, json={"name": "Owner Clone", "clone_from_role_id": owner_role})
    ) == (403, "self-escalation")
    assert client.put(f"{API}/roles/{custom['id']}/permissions", headers=owner, json=od).status_code == 200
    # ...nor assign a role that carries one.
    assert code(
        client.put(f"{API}/staff-users/{ids['manager']}/role", headers=admin, json={"role_id": custom["id"]})
    ) == (403, "self-escalation")

    # 2. No self-service, even as owner.
    for path, body in (
        ("role", {"role_id": admin_role}),
        ("locations", {"has_all_location_access": True}),
        ("permission-overrides", {"grants": []}),
    ):
        assert code(client.put(f"{API}/staff-users/{ids['admin']}/{path}", headers=admin, json=body)) == (
            403,
            "self-escalation",
        )
    assert code(client.post(f"{API}/staff-users/{ids['admin']}/permissions/reset", headers=admin)) == (
        403,
        "self-escalation",
    )

    # 3. Owner protection.
    assert code(
        client.put(f"{API}/staff-users/{ids['manager']}/role", headers=admin, json={"role_id": owner_role})
    ) == (403, "self-escalation")
    invite = {"email": "second-owner@example.com", "first_name": "A", "last_name": "B", "role_id": owner_role}
    assert code(client.post(f"{API}/staff-users", headers=admin, json=invite)) == (403, "self-escalation")
    for response in (
        client.patch(f"{API}/staff-users/{ids['owner']}", headers=admin, json={"first_name": "Pwned"}),
        client.post(f"{API}/staff-users/{ids['owner']}/deactivate", headers=admin),
        client.post(f"{API}/staff-users/{ids['owner']}/credential-reset", headers=admin),
        client.put(f"{API}/staff-users/{ids['owner']}/role", headers=admin, json={"role_id": admin_role}),
        client.put(
            f"{API}/staff-users/{ids['owner']}/locations", headers=admin, json={"has_all_location_access": False}
        ),
    ):
        assert code(response) == (403, "permission-denied")
    assert code(client.post(f"{API}/staff-users/{ids['owner']}/deactivate", headers=owner)) == (409, "last-owner")
    # With a second owner, the first can be demoted by them; then the survivor is the last owner again.
    assert (
        client.put(f"{API}/staff-users/{ids['admin']}/role", headers=owner, json={"role_id": owner_role}).status_code
        == 200
    )
    assert (
        client.put(f"{API}/staff-users/{ids['owner']}/role", headers=admin, json={"role_id": admin_role}).status_code
        == 200
    )
    assert code(client.post(f"{API}/staff-users/{ids['admin']}/deactivate", headers=admin)) == (409, "last-owner")
    # The demoted ex-owner is now an admin and can no longer touch an owner.
    assert code(client.put(f"{API}/staff-users/{ids['admin']}/role", headers=owner, json={"role_id": admin_role})) == (
        403,
        "permission-denied",
    )


def test_location_containment(client, tenant, people):
    owner = people["owner"]
    second = client.post(
        f"{API}/locations", headers=owner, json={"name": "Annex", "time_zone": "America/Denver", "country_code": "US"}
    ).json()
    email, _ = add_staff(tenant, "admin", location_ids=[people["location_id"]])  # an admin limited to Main
    limited = login(client, tenant, email)

    # Sees and edits only its own location; the other one does not exist as far as it can tell.
    assert [loc["name"] for loc in client.get(f"{API}/locations", headers=limited).json()["data"]] == ["Main"]
    assert client.get(f"{API}/locations/{second['id']}", headers=limited).status_code == 404
    assert (
        client.patch(f"{API}/locations/{second['id']}", headers=limited, json={"phone": "+15550100"}).status_code == 404
    )
    assert client.get(f"{API}/locations/{second['id']}/facility-hours", headers=limited).status_code == 404
    assert (
        client.patch(
            f"{API}/locations/{people['location_id']}", headers=limited, json={"phone": "+15550100"}
        ).status_code
        == 200
    )
    me = client.get(f"{API}/me", headers=limited).json()
    assert me["has_all_location_access"] is False and me["primary_location_id"] == people["location_id"]
    assert [loc["id"] for loc in me["locations"]] == [people["location_id"]]

    # 4. It can only assign locations inside its own set.
    target = f"{API}/staff-users/{people['ids']['front_desk']}/locations"
    for body in ({"has_all_location_access": True}, {"has_all_location_access": False, "location_ids": [second["id"]]}):
        response = client.put(target, headers=limited, json=body)
        assert (response.status_code, response.json()["code"]) == (403, "self-escalation")
    inside = client.put(
        target,
        headers=limited,
        json={
            "has_all_location_access": False,
            "location_ids": [people["location_id"]],
            "primary_location_id": people["location_id"],
        },
    )
    assert inside.status_code == 200 and inside.json()["primary_location_id"] == people["location_id"]
    both = client.put(
        target,
        headers=owner,
        json={"has_all_location_access": False, "location_ids": [people["location_id"], second["id"]]},
    )
    assert sorted(both.json()["location_ids"]) == sorted([people["location_id"], second["id"]])
    assert (
        len(client.get(f"{API}/staff-users?location_id={second['id']}", headers=owner).json()["data"]) >= 2
    )  # desk + all-access users
    assert client.get(f"{API}/staff-users?location_id=nope", headers=owner).status_code == 422
    # A location it creates becomes visible to it.
    created = client.post(
        f"{API}/locations", headers=limited, json={"name": "Pop-up", "time_zone": "UTC", "country_code": "US"}
    )
    assert created.status_code == 201
    assert client.get(f"{API}/locations/{created.json()['id']}", headers=limited).status_code == 200


def test_staff_user_administration(client, tenant, people, mailbox):
    owner, ids = people["owner"], people["ids"]
    invite = {"email": f"kim@{tenant.slug}.example.com", "first_name": "Kim", "last_name": "Zed", "role_id": str(role_id(tenant, "front_desk")),
              "location_ids": [people["location_id"]], "primary_location_id": people["location_id"], "mobile_phone": "+15550101"}  # fmt: skip
    created = client.post(f"{API}/staff-users", headers=owner, json=invite)
    assert created.status_code == 201
    kim = created.json()
    assert (
        kim["email"] == invite["email"]
        and kim["role"]["system_key"] == "front_desk"
        and kim["location_ids"] == [people["location_id"]]
    )
    duplicate = client.post(f"{API}/staff-users", headers=owner, json={**invite, "email": invite["email"].upper()})
    assert (
        duplicate.status_code == 409
        and duplicate.json()["code"] == "already-exists"
        and duplicate.json()["field"] == "email"
    )
    assert (
        client.post(
            f"{API}/staff-users", headers=owner, json={**invite, "email": "x@example.com", "role_id": str(uuid4())}
        ).status_code
        == 422
    )
    assert client.post(f"{API}/staff-users", headers=owner, json={**invite, "email": "not-an-email"}).status_code == 422
    assert client.post(f"{API}/staff-users", headers=owner, json={**invite, "surprise": 1}).status_code == 422

    assert client.post(f"{API}/staff-users/{kim['id']}/invitation/resend", headers=owner).status_code == 202
    assert (
        client.post(f"{API}/staff-users/{kim['id']}/credential-reset", headers=owner).status_code == 202
    )  # still invited: invite again
    assert [m.subject.split(": ")[1] for m in mailbox] == ["you have been invited"] * 3
    first, _, last = (link_token(m) for m in mailbox)
    assert (
        client.post(f"{API}/auth/invitations/accept", json={"token": first}).json()["code"] == "token-invalid"
    )  # superseded
    assert client.post(f"{API}/auth/invitations/accept", json={"token": last}).status_code == 200

    # Credential reset for an active user: a link, and every session revoked.
    manager_session = scalar(
        tenant, select(func.count()).select_from(AuthSession).where(AuthSession.revoked_at.is_(None))
    )
    assert client.post(f"{API}/staff-users/{ids['manager']}/credential-reset", headers=owner).status_code == 202
    assert (
        "reset-password" in mailbox[-1].body and client.get(f"{API}/me", headers=people["manager"]).status_code == 401
    )
    assert (
        scalar(tenant, select(func.count()).select_from(AuthSession).where(AuthSession.revoked_at.is_(None)))
        == manager_session - 1
    )

    updated = client.patch(
        f"{API}/staff-users/{kim['id']}", headers=owner, json={"last_name": "Abel", "ip_policy": "facility_networks"}
    ).json()
    assert updated["last_name"] == "Abel" and updated["ip_policy"] == "facility_networks"
    assert client.patch(f"{API}/staff-users/{kim['id']}", headers=owner, json={"first_name": None}).status_code == 422
    assert client.get(f"{API}/staff-users/{uuid4()}", headers=owner).status_code == 404

    listing = client.get(f"{API}/staff-users?sort=last_name&include=total", headers=owner).json()
    assert listing["page"]["total"] == 5 and listing["data"][0]["last_name"] == "Abel"
    assert [u["id"] for u in client.get(f"{API}/staff-users?q=kim", headers=owner).json()["data"]] == [kim["id"]]
    assert [
        u["id"]
        for u in client.get(f"{API}/staff-users?role_id={role_id(tenant, 'owner')}", headers=owner).json()["data"]
    ] == [ids["owner"]]
    client.post(f"{API}/staff-users/{kim['id']}/deactivate", headers=owner)
    client.post(f"{API}/staff-users/{kim['id']}/deactivate", headers=owner)  # idempotent
    assert [u["id"] for u in client.get(f"{API}/staff-users?is_active=false", headers=owner).json()["data"]] == [
        kim["id"]
    ]
    assert client.get(f"{API}/staff-users?identity_status[in]=invited,disabled", headers=owner).json()["data"] == []
    assert client.get(f"{API}/staff-users?sort=-email&limit=1", headers=owner).json()["page"]["has_more"] is True
