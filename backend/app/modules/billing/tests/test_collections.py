"""Phase 9 chip D: collections tags, profiles and report (BIL-20), the portal lockout for past-due payers
(BIL-22), expiring cards (PAY-07), the staff daily digest (PAY-08) and the membership autopay default (BIL-17)."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.audit import AuditEvent
from app.modules.billing import autopay, catalogue, collections, methods
from app.modules.billing.models import Invoice
from app.modules.billing.tests.test_billing import charge, svc, work
from app.modules.billing.tests.test_money import NOON, TODAY
from conftest import new_client
from tests.test_security import ROUTES

# Portal POST routes that stay open while a payer is locked out for a past-due balance.
OPEN_PORTAL_POSTS = {
    "/portal/app-cards", "/portal/client-documents/{document_id}/acceptances",
    "/portal/client-packages/{package_id}/auto-renew-opt-out",
    "/portal/dependents", "/portal/devices", "/portal/enrollments/{enrollment_id}/cancel",
    "/portal/inbox/{inbox_item_id}/read", "/portal/league-teams/{competition_team_id}/roster",
    "/portal/membership-contracts/{contract_id}/auto-renew-opt-out",
    "/portal/package-series/{series_id}/auto-renew-opt-out", "/portal/payment-methods",
    "/portal/payment-methods/setup-intents", "/portal/payments", "/portal/payments/{payment_id}/confirm",
    "/portal/registration-checkouts/{checkout_id}/abandon", "/portal/relationships",
    "/portal/relationships/{relationship_id}/end", "/portal/rental-plan-purchases/{purchase_id}/auto-renew-opt-out",
    "/portal/rentals/{rental_id}/abandon",
    "/portal/rentals/{rental_id}/cancel",
    "/portal/wallet-passes", "/portal/progress-share-links",  # phase 11: a credential like app-cards; own data
    "/portal/progress-share-links/{progress_share_link_id}/revoke",
    "/portal/feedback",  # phase 11 C2: in-app feedback to the staff inbox; no money
    "/portal/favorites", "/portal/app-usage",  # phase 11 C2: favourites and anonymous usage counts; no money
}  # fmt: skip


def _settings(tenant, **values) -> None:
    with work(tenant) as session:
        row = catalogue.settings_for(session)
        for key, value in values.items():
            setattr(row, key, value)


def _past_due_invoice(shop, client_id, days: int = 10) -> UUID:
    """An invoice for the client that fell due `days` ago and was marked past due by the daily pass."""
    with clock.freeze(NOON - timedelta(days=days)), work(shop.tenant) as session:
        invoice = svc.create_invoice_for_charges(session, [charge(session, shop, 1000, client_id=client_id).id])
    with clock.freeze(NOON), work(shop.tenant) as session:
        svc.refresh_invoice(session, invoice.id)
        assert session.get(Invoice, invoice.id).past_due_since_on is not None
        return invoice.id


def test_portal_post_routes_are_each_locked_or_deliberately_open():
    posts = {
        path.removeprefix("/api/v1") for path, route, _ in ROUTES if "POST" in route.methods and "/portal/" in path
    }
    assert posts == collections.PORTAL_PURCHASE_ROUTES | OPEN_PORTAL_POSTS
    assert not collections.PORTAL_PURCHASE_ROUTES & OPEN_PORTAL_POSTS


def test_tags_profiles_and_the_collections_report(api, shop, desk):
    tag = api("POST", "/collections-tags", {"name": "Payment plan"}, 201)
    api("POST", "/collections-tags", {"name": "payment PLAN"}, 409, "already-exists")
    agency = api("POST", "/collections-tags", {"name": "Agency", "description": "Sent to the agency"}, 201)
    api("POST", "/collections-tags", {"name": "Nope"}, 403, headers=desk.front)
    api("GET", "/collections-report", None, 403, headers=desk.front)  # a manager key
    who = str(shop.client_id)
    api("GET", f"/clients/{who}/collections-profile", None, 404, "not-in-collections")

    with work(shop.tenant) as session:
        owed = svc.create_invoice_for_charges(session, [charge(session, shop, 1000).id]).balance_minor
    profile = api(
        "PUT", f"/clients/{who}/collections-profile", {"collections_tag_id": tag["id"], "notes": "Calls back"}
    )
    assert (profile["collections_tag_id"], profile["notes"]) == (tag["id"], "Calls back") and profile["placed_on"]
    assert api("GET", f"/clients/{who}/collections-profile")["collections_tag_id"] == tag["id"]
    with work(shop.tenant) as session:
        audited = session.scalars(
            select(AuditEvent.changes).where(AuditEvent.action.like("billing.collections%"))
        ).all()
    assert len(audited) == 3 and all(audited)  # two tags and a profile; the diff is taken before the flush
    # A manager limited to another location cannot place a client whose home is here (location gate).
    api(
        "PUT",
        f"/clients/{who}/collections-profile",
        {"collections_tag_id": agency["id"]},
        404,
        headers=desk.west_manager,
    )

    api("PATCH", f"/collections-tags/{agency['id']}", {"is_active": False})
    api("PUT", f"/clients/{who}/collections-profile", {"collections_tag_id": agency["id"]}, 422)  # no longer used
    api("PATCH", f"/collections-tags/{tag['id']}", {"is_active": False})
    kept = api(
        "PUT", f"/clients/{who}/collections-profile", {"collections_tag_id": tag["id"], "placed_on": "2026-01-02"}
    )
    assert kept["placed_on"] == "2026-01-02" and kept["notes"] is None  # a retired tag stays where it is

    rows = api("GET", f"/collections-report?collections_tag_id={tag['id']}")["data"]
    assert [(r["client_id"], r["collections_tag_name"], r["balance_minor"], r["past_due_minor"]) for r in rows] == [
        (who, "Payment plan", owed, 0)
    ]
    assert api("GET", f"/collections-report?collections_tag_id={agency['id']}")["data"] == []
    assert [t["name"] for t in api("GET", "/collections-tags?is_active=false")["data"]] == ["Agency", "Payment plan"]
    api("DELETE", f"/clients/{who}/collections-profile", None, 204)
    api("DELETE", f"/clients/{who}/collections-profile", None, 404, "not-in-collections")
    assert api("GET", "/collections-report")["data"] == []


def test_a_past_due_payer_cannot_buy_or_book_online_but_can_pay(shop, member):
    _past_due_invoice(shop, UUID(member.id))
    quote = "/portal/membership-contracts/quote"
    member.api("POST", quote, {}, 422)  # the setting is off: not locked (the empty body is refused instead)
    _settings(shop.tenant, is_portal_blocked_when_past_due=True)
    member.api("POST", quote, {}, 403, "portal-past-due")
    member.api("POST", "/portal/rentals", {}, 403, "portal-past-due")
    with work(shop.tenant) as session:
        assert not collections.is_portal_locked(session, [UUID(member.stranger)])
        assert not collections.is_portal_locked(session, [])
    owed = [row["id"] for row in member.api("GET", "/portal/invoices?is_payable=true")["data"]]  # reading is open
    member.api("POST", "/portal/payments", {"invoice_ids": owed, "method_token": "tok_card_ok"}, 201)
    member.api("POST", quote, {}, 422)  # settled: open again


def test_a_guardian_is_locked_out_by_a_dependent_reached_only_through_a_relationship(api, shop, member, client):
    kid = new_client(client, shop.owner, shop.location_id)["id"]  # no portal access row: only the relationship
    types = {t["code"]: t["id"] for t in api("GET", "/relationship-types")}
    api("POST", f"/clients/{member.id}/relationships",
        {"other_client_id": kid, "relationship_type_id": types["parent_of"]}, 201)  # fmt: skip
    _past_due_invoice(shop, UUID(kid))
    _settings(shop.tenant, is_portal_blocked_when_past_due=True)
    member.api("POST", "/portal/membership-contracts/quote", {"client_id": kid}, 403, "portal-past-due")


def test_expiring_cards_lists_cards_through_a_month_with_their_holder(api, shop):
    with work(shop.tenant) as session:
        soon = methods.attach_method(session, shop.client_id, "tok_card_ok")
        soon.exp_month, soon.exp_year = 1, 2020  # already expired
        later = methods.attach_method(session, shop.client_id, "tok_card_ok", is_autopay=False)
        later.exp_month, later.exp_year = 3, 2040
        methods.attach_method(session, shop.client_id, "tok_ach_ok")  # not a card
        ids = (str(soon.id), str(later.id))
    rows = api("GET", "/expiring-cards?through=2040-03")["data"]
    assert [(r["id"], r["is_expired"], r["exp_year"]) for r in rows] == [(ids[0], True, 2020), (ids[1], False, 2040)]
    assert rows[0]["client_name"] and [r["id"] for r in api("GET", "/expiring-cards")["data"]] == [ids[0]]
    assert [r["id"] for r in api("GET", "/expiring-cards?through=2040-03&is_autopay=false")["data"]] == [ids[1]]
    api("GET", "/expiring-cards?through=2040-13", None, 422)


def test_the_daily_digest_reports_failures_and_due_autopay_once_a_day(shop, mailbox):
    _settings(shop.tenant, decline_alert_email="desk@example.com", decline_alert_mode="daily_digest")
    with clock.freeze(NOON), work(shop.tenant) as session:
        methods.attach_method(session, shop.client_id, "tok_card_ok")
        svc.create_invoice_for_charges(
            session, [charge(session, shop).id], is_autopay=True, due_on=TODAY + timedelta(days=1)
        )
        declined = svc.take_payment(
            session, client_id=shop.client_id, location_id=shop.location_id, amount_minor=500, tender_kind="card",
            method_token="tok_card_declined", idempotency_key="digest-decline",
        )  # fmt: skip
        assert declined.status == "failed"
    assert not [m for m in mailbox if m.to == "desk@example.com"]  # no alert per decline in digest mode
    with clock.freeze(NOON + timedelta(days=1)), work(shop.tenant) as session:
        assert autopay.digest(session) == 1
        assert autopay.digest(session) == 0  # once a local day
    (message,) = [m for m in mailbox if m.to == "desk@example.com"]
    assert "1 failed on 2026-11-10, 1 autopay due" in message.subject
    assert "receipt" in message.body and "on invoice" in message.body
    with clock.freeze(NOON + timedelta(days=2)), work(shop.tenant) as session:
        assert autopay.digest(session) == 1  # the next day: nothing failed, the autopay is still to collect
    _settings(shop.tenant, decline_alert_mode="per_event")
    with clock.freeze(NOON + timedelta(days=3)), work(shop.tenant) as session:
        assert autopay.digest(session) == 0


@pytest.mark.parametrize(
    ("plan", "channel", "staff", "portal", "expected"),
    [
        (True, "staff", False, False, True), (False, "portal", True, True, False),
        (None, "staff", True, False, True), (None, "staff", False, True, False),
        (None, "portal", False, True, True), (None, "portal", True, False, False),
    ],
)  # fmt: skip
def test_the_membership_autopay_default_is_plan_then_setting_for_the_channel(
    shop, plan, channel, staff, portal, expected
):
    _settings(shop.tenant, is_membership_autopay_default_staff=staff, is_membership_autopay_default_portal=portal)
    with work(shop.tenant) as session:
        resolved = catalogue.membership_autopay_default(session, shop.location_id, channel=channel, plan_default=plan)
        assert resolved is expected
