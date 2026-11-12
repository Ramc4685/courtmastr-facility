"""Phase 9 chip D in memberships: suspension for non-payment (MEM-14, owner decision Q13), the freeze resume
modes, payment-method capture and the online card-save mode (MEM-05), and the autopay default (BIL-17)."""

from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.modules import billing
from app.modules.billing.models import PaymentMethod
from app.modules.memberships import service
from app.modules.memberships.models import MembershipSuspension
from app.modules.memberships.tests.support import (
    at,
    contract,
    daily,
    invoices,
    membership_plan,
    pay,
    periods,
    run,
    sell_at,
    tx,
    world,
)
from app.modules.memberships.tests.test_renewal_jobs import _member
from conftest import new_client

D = date
JAN1 = D(2025, 1, 1)


@pytest.fixture
def w(client, tenant, owner):
    return world(client, owner, tenant)


def _billing_settings(tenant, **values) -> None:
    with tx(tenant) as session:
        row = billing.catalogue.settings_for(session)
        for key, value in values.items():
            setattr(row, key, value)


def _sweep(tenant, day: date) -> dict:
    """Billing's daily pass marks invoices past due, then the memberships rule runs: the job order of a day."""
    with at(day), tx(tenant) as session:
        billing.autopay.daily(session)
    with at(day), tx(tenant) as session:
        return service.sweep_past_due(session)


def _suspensions(tenant, contract_id) -> list[MembershipSuspension]:
    with tx(tenant) as session:
        stmt = select(MembershipSuspension).where(MembershipSuspension.membership_contract_id == contract_id)
        return list(session.scalars(stmt.order_by(MembershipSuspension.created_at)))


# --- MEM-14 -------------------------------------------------------------------------------------------------------


def test_the_non_payment_rule_is_off_by_default(w):
    sold = sell_at(w, JAN1)
    assert _sweep(w.tenant, D(2025, 3, 1)) == {"suspended": 0, "lifted": 0, "failed": []}
    assert contract(w.tenant, sold["id"]).status == "active" and _suspensions(w.tenant, sold["id"]) == []


def test_an_overdue_membership_is_suspended_and_lifted_once_paid(w):
    _billing_settings(w.tenant, membership_suspend_after_days=5)
    sold = sell_at(w, JAN1)  # January's dues are invoiced at the sale, due today, and stay unpaid
    assert _sweep(w.tenant, D(2025, 1, 4))["suspended"] == 0  # not yet five days past due
    assert _sweep(w.tenant, D(2025, 1, 10))["suspended"] == 1
    assert _sweep(w.tenant, D(2025, 1, 11))["suspended"] == 0  # one suspension at a time
    (auto,) = _suspensions(w.tenant, sold["id"])
    assert (auto.past_due_invoice_id, auto.during.lower, auto.during.upper) == (
        UUID(str(sold["invoice_id"])), D(2025, 1, 10), None
    )  # fmt: skip
    assert contract(w.tenant, sold["id"]).status == "suspended"

    pay(w, D(2025, 1, 15), 3100, sold["invoice_id"])
    assert _sweep(w.tenant, D(2025, 1, 15))["lifted"] == 1  # the sweep lifts what the payment settled
    (lifted,) = _suspensions(w.tenant, sold["id"])
    assert lifted.removal_remarks == "Lifted automatically: the invoice was settled"
    assert lifted.during.upper == D(2025, 1, 15)  # ended yesterday (exclusive upper bound)
    assert contract(w.tenant, sold["id"]).status == "active"
    assert _sweep(w.tenant, D(2025, 1, 20)) == {"suspended": 0, "lifted": 0, "failed": []}

    # February's invoice is another debt: it can suspend again; paying it lifts at once (the paid event's handler).
    assert daily(w.tenant, D(2025, 2, 1))["periods_billed"] == 1
    february = invoices(w.tenant, w.person["id"])[-1]
    assert _sweep(w.tenant, D(2025, 2, 2))["suspended"] == 0  # marked past due today
    assert _sweep(w.tenant, D(2025, 2, 8))["suspended"] == 1
    pay(w, D(2025, 2, 9), 3100, february.id)
    with at(D(2025, 2, 9)), tx(w.tenant) as session:
        assert service.invoice_settled(session, february.id) == 1
    assert contract(w.tenant, sold["id"]).status == "active"


def test_staff_can_lift_an_automatic_suspension_and_it_stays_lifted(w):
    _billing_settings(w.tenant, membership_suspend_after_days=3)
    sold = sell_at(w, JAN1)
    assert _sweep(w.tenant, D(2025, 1, 2))["suspended"] == 0
    assert _sweep(w.tenant, D(2025, 1, 10))["suspended"] == 1
    (auto,) = _suspensions(w.tenant, sold["id"])
    run(w.tenant, D(2025, 1, 11), service.remove_suspension, auto.id, {"remarks": "Promised to pay Friday"})
    assert contract(w.tenant, sold["id"]).status == "active"
    assert _sweep(w.tenant, D(2025, 1, 12))["suspended"] == 0  # the same invoice does not suspend again
    planned = {"start_on": D(2025, 1, 20), "end_on": D(2025, 1, 25)}  # staff still suspend by hand
    run(w.tenant, D(2025, 1, 12), service.suspend_contract, sold["id"], planned)
    assert len(_suspensions(w.tenant, sold["id"])) == 2


# --- MEM-05: freeze resume modes ----------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["single", "deferred"])
def test_a_freeze_resumes_with_one_invoice_or_holds_the_rest_for_staff(w, mode):
    run(w.tenant, JAN1, service.update_settings, {"freeze_resume_invoice_mode": mode})
    sold = sell_at(w, JAN1)
    pay(w, JAN1, 3100, sold["invoice_id"])
    dates = {"start_on": D(2025, 1, 15), "end_on": D(2025, 2, 14)}
    run(w.tenant, D(2025, 1, 10), service.freeze_contract, sold["id"], dates)
    assert len(periods(w.tenant, sold["id"], "withheld")) == 11
    before = len(invoices(w.tenant, w.person["id"]))
    billed = daily(w.tenant, D(2025, 2, 15))["periods_billed"]
    if mode == "single":
        assert billed == 11 and len(invoices(w.tenant, w.person["id"])) == before + 1  # everything left, together
        assert periods(w.tenant, sold["id"], "withheld") == []
        return
    assert billed == 0 and len(periods(w.tenant, sold["id"], "withheld")) == 11  # held after the resume
    assert daily(w.tenant, D(2025, 3, 20))["periods_billed"] == 0
    done = run(w.tenant, D(2025, 3, 20), service.invoice_deferred, sold["id"], None)
    assert len(done["period_ids"]) == 11 and done["invoice_id"] and periods(w.tenant, sold["id"], "withheld") == []


# --- MEM-05: capture and card saving; BIL-17 at the sale ----------------------------------------------------------


def test_required_capture_needs_a_stored_method_for_an_autopay_sale(w):
    run(w.tenant, JAN1, service.update_settings, {"payment_method_capture": "required"})
    with pytest.raises(ValidationFailed) as refused:
        sell_at(w, JAN1, is_autopay=True)
    assert refused.value.code == "payment-method-required"
    with tx(w.tenant) as session:
        billing.methods.attach_method(session, UUID(w.person["id"]), "tok_card_ok")
    assert sell_at(w, JAN1, is_autopay=True)["is_autopay"] is True


def _stored(tenant, client_id: str) -> list[PaymentMethod]:
    with tx(tenant) as session:
        return list(session.scalars(select(PaymentMethod).where(PaymentMethod.client_id == UUID(client_id))))


@pytest.mark.parametrize(
    ("mode", "save", "kept"),
    [("always", None, True), ("ask", None, False), ("ask", True, True), ("when_nothing_due", True, False)],
)
def test_the_card_that_pays_online_is_kept_by_the_save_mode(w, client, owner, mode, save, kept):
    run(w.tenant, JAN1, service.update_settings, {"online_card_save_mode": mode})
    online = membership_plan(client, owner, w.tenant, is_sold_online=True)
    person = new_client(client, owner, w.location_id)
    member = _member(w.tenant, person["id"])
    buy = {"membership_plan_id": UUID(online["id"]), "location_id": UUID(w.location_id), "method_token": "tok_card_ok"}
    with tx(w.tenant) as session:
        session.info["actor"] = member
        bought = service.portal_buy(session, member, buy | {"save_method": save}, f"k-{uuid4().hex}")
    assert bought["payment_status"] == "succeeded" and bought["is_autopay"] is True  # BIL-17: the portal default
    cards = [(c.kind, c.is_autopay) for c in _stored(w.tenant, person["id"])]
    assert cards == ([("card", True)] if kept else [])


def test_an_open_plan_default_follows_the_channel_setting(w, client, owner):
    assert w.plan["is_autopay_default"] is None
    assert sell_at(w, JAN1)["is_autopay"] is False  # the staff setting's default
    _billing_settings(w.tenant, is_membership_autopay_default_staff=True)
    other = world(client, owner, w.tenant)
    assert sell_at(other, JAN1)["is_autopay"] is True
    fixed = world(client, owner, w.tenant, is_autopay_default=False)
    assert sell_at(fixed, JAN1)["is_autopay"] is False  # the plan's own default wins
