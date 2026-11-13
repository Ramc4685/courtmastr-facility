"""BIL-01 item-level edits: the revenue date and category move by adjustment (history is never rewritten) and a
percentage discount is kept on the item and recomputed half-up on the line."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.modules.billing.models import Charge, LedgerEntry
from app.modules.billing.tests.test_billing import API, assert_books_agree, cash, charge, svc, work
from app.modules.billing.tests.test_money import refused


def _revenue(session, category_id) -> dict:
    rows = session.execute(
        select(LedgerEntry.effective_on, func.sum(LedgerEntry.credit_minor - LedgerEntry.debit_minor))
        .where(LedgerEntry.account == "revenue", LedgerEntry.revenue_category_id == category_id)
        .group_by(LedgerEntry.effective_on)
    ).all()
    return {on: int(total) for on, total in rows if total}


def test_revenue_date_and_category_move_by_adjustment(client, shop, owner):
    with work(shop.tenant) as session:
        other = svc.create_revenue_category(session, code="LESSON", label="Lessons", tax_ids=[shop.tax_id]).id
        item = charge(session, shop, 2000, revenue_on=date(2026, 11, 1))
        cash(session, shop, 2165, allocations=[(item.id, 2165)])
    body = {"revenue_on": "2026-12-01", "revenue_category_id": str(other)}
    refused_edit = client.patch(f"{API}/charges/{item.id}", headers=owner, json=body)
    assert refused_edit.status_code == 422 and refused_edit.json()["errors"][0]["pointer"] == "/reason"
    edited = client.patch(f"{API}/charges/{item.id}", headers=owner, json=body | {"reason": "Booked the wrong month"})
    assert edited.status_code == 200, edited.text
    new = edited.json()
    assert (new["kind"], new["revenue_on"], new["revenue_category_id"], new["total_minor"]) == (
        "adjustment", "2026-12-01", str(other), 2165,
    )  # fmt: skip
    assert new["applied_minor"] == 2165  # the money followed the item
    with work(shop.tenant) as session:
        assert session.get(Charge, item.id).status == "reversed"
        # the original month keeps its posting and its negation: net zero there, all of it on the new date
        assert _revenue(session, shop.category_id) == {}
        assert _revenue(session, other) == {date(2026, 12, 1): 2000}
        assert (
            session.scalar(
                select(func.count()).select_from(LedgerEntry).where(LedgerEntry.effective_on == date(2026, 11, 1))
            )
            > 0
        )
        assert_books_agree(session)


def test_a_revenue_date_in_a_closed_period_and_an_inactive_category_are_refused(shop):
    from app.modules.platform.models import Tenant

    with work(shop.tenant) as session:
        item = charge(session, shop, revenue_on=date(2026, 11, 1))
        gone = svc.create_revenue_category(session, code="OLD", label="Old")
        gone.is_active, gone.deactivated_on = False, date(2026, 1, 1)
        session.get(Tenant, shop.tenant.id).billing_locked_through_on = date(2026, 10, 31)
    with refused("period-locked"), work(shop.tenant) as session:
        svc.adjust_charge(session, item.id, reason="Back-date", revenue_on=date(2026, 10, 1))
    with refused("validation-failed", kind=svc.ValidationFailed), work(shop.tenant) as session:
        svc.adjust_charge(session, item.id, reason="Move", revenue_category_id=gone.id)


def test_a_percentage_discount_is_kept_and_recomputed_on_the_line(client, shop, owner):
    body = {
        "client_id": str(shop.client_id), "location_id": str(shop.location_id), "description": "Lesson",
        "unit_price_minor": 1999, "revenue_category_id": str(shop.category_id), "discount_pct": "15",
    }  # fmt: skip
    made = client.post(f"{API}/charges", headers=owner, json=body)
    assert made.status_code == 201, made.text
    assert (made.json()["discount_minor"], Decimal(made.json()["discount_pct"])) == (300, 15)  # 299.85 half-up
    both = client.post(f"{API}/charges", headers=owner, json=body | {"discount_minor": 10})
    assert both.status_code == 422
    edited = client.patch(
        f"{API}/charges/{made.json()['id']}", headers=owner, json={"unit_price_minor": 1000, "reason": "New price"}
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["discount_minor"], edited.json()["net_minor"]) == (150, 850)
    # what the edit dialog sends: price and percentage together, never an amount beside it
    dialog = client.patch(
        f"{API}/charges/{edited.json()['id']}", headers=owner,
        json={"quantity": "1", "unit_price_minor": 1010, "discount_pct": "15", "reason": "Dialog edit"},
    )  # fmt: skip
    assert dialog.status_code == 200, dialog.text
    assert (dialog.json()["discount_minor"], dialog.json()["net_minor"]) == (152, 858)  # 151.5 half-up, once
    preview = client.post(
        f"{API}/charges/preview", headers=owner,
        json={"location_id": str(shop.location_id), "unit_price_minor": 1010, "discount_pct": "15"},
    )  # fmt: skip
    assert preview.status_code == 200 and preview.json()["net_minor"] == 858
    cleared = client.patch(
        f"{API}/charges/{dialog.json()['id']}", headers=owner, json={"discount_minor": 0, "reason": "No discount"}
    )
    assert (cleared.json()["discount_minor"], cleared.json()["discount_pct"]) == (0, None)
