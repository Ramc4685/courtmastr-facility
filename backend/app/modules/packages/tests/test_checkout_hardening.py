"""Wave 1 hardening, batch money: an online package exists only once its payment is secured (M-08, M-10)."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from app.core.errors import Conflict, DomainError
from app.modules import billing
from app.modules.billing.tests.test_money import provider_payments
from app.modules.memberships.tests.support import API, invoices, package_plan, tx, world
from app.modules.packages import service
from app.modules.packages.models import ClientPackage, PackagePlan
from app.modules.packages.tests.test_packages import _as, _member
from conftest import new_client, scalar


@pytest.fixture
def w(client, tenant, owner):
    w = world(client, owner, tenant)
    with tx(tenant) as session:  # committed tender rows and processor account, as in a tenant that has sold before
        billing.service.ensure_defaults(session)
        billing.service._provider_account(session)
    w.member = _member(tenant, w.person["id"])
    return w


def _packages(w) -> int:
    return scalar(w.tenant, select(func.count()).select_from(ClientPackage))


def _buy(w, plan, key=None, **data):
    body = {"package_plan_id": UUID(plan["id"]), "location_id": UUID(w.location_id)} | data
    return _as(w.tenant, w.member, service.portal_buy, body, key or f"k-{uuid4().hex}")


def test_paid_in_full_plan_is_never_sold_unpaid(w, client, owner):
    plan = package_plan(client, owner, w.tenant, online_sale_mode="paid_in_full")
    deferred = {**plan, "default_invoice_mode": "deferred"}
    refused = client.post(f"{API}/package-plans", headers=owner, json={
        k: deferred[k] for k in ("reservation_type_id", "name", "session_mode", "session_count", "fee_minor",
                                 "fee_basis", "revenue_category_id", "online_sale_mode", "default_invoice_mode")
    } | {"name": "Deferred"})  # fmt: skip
    assert refused.status_code == 422, refused.text  # the plan cannot be set up that way any more
    assert refused.json()["errors"][0]["pointer"] == "/default_invoice_mode"
    with tx(w.tenant) as session:  # ...but a plan saved before the rule still exists
        session.execute(
            update(PackagePlan).where(PackagePlan.id == UUID(plan["id"])).values(default_invoice_mode="deferred")
        )

    for token in (None, "tok_card_declined"):
        with pytest.raises(Conflict) as failed:
            _buy(w, plan, **({"method_token": token} if token else {}))
        assert (failed.value.code, _packages(w)) == ("payment-failed", 0)
    bought = _buy(w, plan, method_token="tok_card_ok")
    assert (bought["payment_status"], bought["invoice_id"] is not None) == ("succeeded", True)
    assert invoices(w.tenant, w.person["id"])[0].status == "paid"

    on_account = package_plan(client, owner, w.tenant, online_sale_mode="balance_allowed")
    sold = _buy(w, on_account)  # a plan that allows a balance still sells on account
    assert (sold["payment_status"], sold["invoice_id"] is not None, _packages(w)) == (None, True, 2)


def test_a_processor_timeout_sells_nothing_and_the_retry_sells_once(w, client, owner):
    """M-10: `unknown` is not paid. The sale rolls back; the same key, once the processor answers, sells once."""
    plan = package_plan(client, owner, w.tenant, online_sale_mode="paid_in_full")
    key = f"k-{uuid4().hex}"
    with pytest.raises(DomainError) as timeout:
        _buy(w, plan, key, method_token="tok_card_unknown")
    assert (timeout.value.status, timeout.value.code, _packages(w)) == (503, "provider-unavailable", 0)
    sold = _buy(w, plan, key, method_token="tok_card_unknown")
    paid = provider_payments(w, f"portal:{w.member.identity_id}:{key}")  # a client's key is bound to its identity
    assert (sold["payment_status"], _packages(w), paid) == ("succeeded", 1, 1)


def test_pkg_09_buy_with_a_stored_method(w, client, owner):
    """PKG-09 (phase 11 B): the portal buyer pays with a card already on file; someone else's card is refused."""
    plan = package_plan(client, owner, w.tenant, online_sale_mode="paid_in_full")
    other = new_client(client, owner, w.location_id)["id"]
    with tx(w.tenant) as session:
        mine = billing.methods.attach_method(session, UUID(w.person["id"]), "tok_card_ok").id
        theirs = billing.methods.attach_method(session, UUID(other), "tok_card_ok").id
    with pytest.raises(DomainError) as refused:
        _buy(w, plan, payment_method_id=theirs)
    assert (refused.value.code, _packages(w)) == ("payment-method-not-usable", 0)
    bought = _buy(w, plan, payment_method_id=mine)
    assert bought["payment_status"] == "succeeded" and invoices(w.tenant, w.person["id"])[0].status == "paid"
