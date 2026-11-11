"""Wave 1 hardening, batch money: online membership checkout secures payment before the contract exists
(M-09, M-10), and a staff sale carries only what the seller may set (M-12)."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.errors import DomainError, ValidationFailed
from app.modules import billing, platform
from app.modules.billing.tests.test_money import provider_payments
from app.modules.memberships import service
from app.modules.memberships.models import MembershipContract
from app.modules.memberships.tests.support import API, charges, membership_plan, ok, tx, world
from app.modules.memberships.tests.test_renewal_jobs import _member
from conftest import add_staff, login, new_client, scalar


@pytest.fixture
def w(client, tenant, owner):
    return world(client, owner, tenant)


@pytest.fixture
def shop(w, client, owner):
    """An online plan with nothing due before its start, a member who may buy it, and the location's today."""
    online = membership_plan(client, owner, w.tenant, is_sold_online=True)
    member = _member(w.tenant, w.person["id"])
    with tx(w.tenant) as session:
        today = platform.service.location_today(session, UUID(w.location_id))
        billing.service.ensure_defaults(session)  # committed tender rows and processor account, as in a live
        billing.service._provider_account(session)  # tenant: the `initiated` row then survives a rollback

    def buy(key=None, **data):
        body = {"membership_plan_id": UUID(online["id"]), "location_id": UUID(w.location_id)} | data
        with tx(w.tenant) as session:
            session.info["actor"] = member
            return service.portal_buy(session, member, body, key or f"k-{uuid4().hex}")

    return type("Shop", (), {"buy": staticmethod(buy), "today": today})


def _contracts(w) -> int:
    return scalar(w.tenant, select(func.count()).select_from(MembershipContract))


def test_future_start_needs_a_payment_method(w, shop):
    later = shop.today + timedelta(days=25)  # nothing falls due at the sale
    with pytest.raises(ValidationFailed) as refused:
        shop.buy(start_on=later)
    assert (refused.value.code, _contracts(w)) == ("payment-method-required", 0)
    sold = shop.buy(start_on=later, method_token="tok_card_ok")
    assert (sold["status"], sold["invoice_id"], sold["payment_id"]) == ("upcoming", None, None)
    with tx(w.tenant) as session:
        method = billing.methods.autopay_method(session, UUID(w.person["id"]))
        assert method is not None and method.status == "active"  # the start date has a card to charge
        assert session.get(MembershipContract, sold["id"]).is_autopay is True


def test_portal_cannot_turn_autopay_off_or_backdate(w, shop):
    for day in (shop.today - timedelta(days=1), shop.today + timedelta(days=service.ONLINE_START_WINDOW_DAYS + 1)):
        with pytest.raises(ValidationFailed) as refused:
            shop.buy(start_on=day, method_token="tok_card_ok")
        assert refused.value.extra["errors"][0]["pointer"] == "/start_on"
    sold = shop.buy(is_autopay=False, method_token="tok_card_ok")
    assert sold["payment_status"] == "succeeded"
    with tx(w.tenant) as session:
        assert session.get(MembershipContract, sold["id"]).is_autopay is True


def test_a_processor_timeout_sells_nothing_and_the_retry_sells_once(w, shop):
    """M-10: `unknown` is not paid. The sale rolls back; the same key, once the processor answers, sells once."""
    key = f"k-{uuid4().hex}"
    with pytest.raises(DomainError) as timeout:
        shop.buy(key, method_token="tok_card_unknown")
    assert (timeout.value.status, timeout.value.code, _contracts(w)) == (503, "provider-unavailable", 0)
    sold = shop.buy(key, method_token="tok_card_unknown")
    assert sold["payment_status"] == "succeeded" and _contracts(w) == 1
    assert len(charges(w.tenant, w.person["id"])) == 1 and provider_payments(w, key) == 1  # charged once


def test_sale_cannot_carry_what_the_seller_may_not_do(w, client, owner):
    """M-12: front desk may sell, but not share the contract or credit the sale to someone else."""
    email, front_id = add_staff(w.tenant, "front_desk", location_ids=[w.location_id])
    _, other_id = add_staff(w.tenant, "coach", location_ids=[w.location_id])
    front = login(client, w.tenant, email)
    body = lambda **extra: {"client_id": new_client(client, owner, w.location_id)["id"],  # noqa: E731
                            "location_id": w.location_id, "membership_plan_id": w.plan["id"]} | extra  # fmt: skip
    post = lambda data, headers=front: client.post(f"{API}/membership-contracts", headers=headers, json=data)  # noqa: E731
    friend = new_client(client, owner, w.location_id)["id"]
    assert post(body(share_client_ids=[friend])).status_code == 403
    assert post(body(sold_by_staff_user_id=str(other_id))).status_code == 403
    ok(post(body()), 201)
    ok(post(body(sold_by_staff_user_id=str(front_id))), 201)  # crediting oneself is the default anyway
    ok(post(body(share_client_ids=[friend], sold_by_staff_user_id=str(other_id)), owner), 201)
