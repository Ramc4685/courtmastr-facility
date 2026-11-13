"""Recorded portal terms acknowledgment (SSP-14): a sale needs the version the buyer was shown, a changed text is a
409 terms-changed carrying the current version, and an accepted sale leaves one terms_acceptance row."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.db.session import tenant_session
from app.modules.documents.models import TermsAcceptance
from app.modules.programs.tests.test_checkout import PORTAL, add, basket, keyed, member, online
from app.modules.programs.tests.test_guest_checkout import allow_guests, start
from app.modules.scheduling.tests.helpers import API, facility, ok


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def bind_terms(client, owner, text: str) -> dict:
    body = {"scope_type": "portal_terms", "custom_text": text}
    response = client.put(f"{API}/document-bindings", headers=owner, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


def shown(client, tenant) -> str:
    return ok(client.get(f"{API}/public/portal-terms", headers={"X-Tenant-Slug": tenant.slug}), 200)["terms_version_id"]


def accepted(tenant, sale_kind: str) -> int:
    with tenant_session(tenant.id) as session:
        return session.scalar(
            select(func.count()).select_from(TermsAcceptance).where(TermsAcceptance.sale_kind == sale_kind)
        )


def test_portal_program_sale_records_the_terms_shown(client, owner, tenant, f, mailbox):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    person, portal = member(client, tenant, owner, f, mailbox)
    bind_terms(client, owner, "Play fair.")
    old = shown(client, tenant)
    bind_terms(client, owner, "Play fair and tidy up.")  # the text changed after the buyer read it
    cart = basket(client, portal, f, PORTAL)
    ok(add(client, portal, cart["id"], camp["id"], person["id"], PORTAL, program_fee_id=fee["id"]), 200)
    confirm = f"{API}/{PORTAL}/{cart['id']}/confirm"

    missing = client.post(confirm, headers=keyed(portal), json={"method_token": "tok_card_ok"})
    assert (missing.status_code, missing.json()["code"]) == (409, "terms-changed")
    stale = client.post(confirm, headers=keyed(portal), json={"method_token": "tok_card_ok", "terms_version_id": old})
    assert stale.status_code == 409 and stale.json()["terms_version_id"] == shown(client, tenant)
    paid = client.post(confirm, headers=keyed(portal),
                       json={"method_token": "tok_card_ok", "terms_version_id": shown(client, tenant)})  # fmt: skip
    assert paid.status_code == 200, paid.text
    assert accepted(tenant, "program") == 1


def test_guest_sale_needs_the_terms_too(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    bind_terms(client, owner, f"Terms {uuid4().hex}")
    cart = ok(start(client, tenant, f, camp, fee))
    confirm, headers = f"{API}/public/guest-checkouts/{cart['id']}/confirm", {"X-Tenant-Slug": tenant.slug}
    body = {"guest_token": cart["guest_token"], "method_token": "tok_card_ok"}
    refused = client.post(confirm, headers=keyed(headers), json=body)
    assert (refused.status_code, refused.json()["code"]) == (409, "terms-changed")
    paid = client.post(confirm, headers=keyed(headers), json=body | {"terms_version_id": shown(client, tenant)})
    assert paid.status_code == 200, paid.text
    assert accepted(tenant, "program") == 1
