"""Owner or Admin resets another user's lost authenticator (ADR 0002 section 6, phase 8 S4)."""

from sqlalchemy import func, select

from app.core.audit import AuditEvent
from app.core.db.session import tenant_session
from app.modules.platform.models import MfaFactor, MfaRecoveryCode, Tenant
from app.modules.platform.tests.test_mfa_step_up import _enrol, _sign_in
from conftest import add_staff, login, make_tenant, scalar

API = "/api/v1"


def _reset(client, headers, staff_user_id):
    return client.post(f"{API}/staff-users/{staff_user_id}/mfa-reset", headers=headers)


def test_admin_resets_a_lost_factor(client, tenant, mailbox):
    desk_email, desk_id = add_staff(tenant, "front_desk")
    desk = login(client, tenant, desk_email)
    _enrol(client, desk)
    admin_email, _ = add_staff(tenant, "admin")
    admin = login(client, tenant, admin_email)

    assert _reset(client, admin, desk_id).status_code == 204
    assert client.get(f"{API}/me", headers=desk).status_code == 401  # every session revoked
    for model in (MfaFactor, MfaRecoveryCode):
        assert scalar(tenant, select(func.count()).select_from(model)) == 0
    event = scalar(tenant, select(AuditEvent).where(AuditEvent.action == "platform.staff_user.reset_mfa"))
    assert event.entity_id == desk_id and event.actor_label and event.changes == {}
    assert mailbox[-1].to == desk_email and "reset" in mailbox[-1].subject
    assert _reset(client, admin, desk_id).json()["code"] == "invalid-state-transition"  # nothing left to reset

    # Required for them now: the next sign-in walks them through enrolment again.
    with tenant_session(tenant.id) as session:
        session.get(Tenant, tenant.id).staff_mfa_policy = "all"
    challenge = _sign_in(client, tenant, desk_email)
    assert challenge.status_code == 202 and challenge.json()["enrolment_required"]


def test_owner_protection_self_and_tenant_scope(client, tenant):
    target_email, target_id = add_staff(tenant, "admin")
    _enrol(client, login(client, tenant, target_email))
    admin_email, admin_id = add_staff(tenant, "admin")
    admin = login(client, tenant, admin_email)

    assert _reset(client, admin, tenant.owner_id).status_code == 403  # only an Owner resets an Owner
    own = _reset(client, admin, admin_id)
    assert own.status_code == 403 and own.json()["code"] == "self-escalation"  # own factor: security page
    own = _reset(client, login(client, tenant), tenant.owner_id)
    assert own.status_code == 403 and own.json()["code"] == "self-escalation"
    _, foreign_id = add_staff(make_tenant(), "front_desk")
    assert _reset(client, admin, foreign_id).status_code == 404  # outside the tenant
    assert _reset(client, login(client, tenant), target_id).status_code == 204  # the Owner resets an Admin
