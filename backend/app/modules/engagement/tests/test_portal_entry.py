"""Phase 11 chip A: public sign-up (SSP-05), menu (SSP-13), redirects (SSP-07), social links (SSP-15), the public
config the landing page reads (SSP-01), and the tenant colours in public branding (SSP-14)."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.db.session import tenant_session
from app.modules.engagement.models import PortalSignup
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import link_token

SIGNUPS = f"{API}/public/portal-signups"


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def settings(client, owner, f, **body):
    url = f"{API}/locations/{f.location}/portal-settings"
    return client.put(url, headers=owner, json={"is_enabled": True, "is_public": True} | body)


def public(tenant) -> dict:
    return {"X-Tenant-Slug": tenant.slug}


def signup(client, tenant, f, email=None, **extra):
    body = {"location_id": f.location, "email": email or f"n-{uuid4().hex[:8]}@example.com",
            "first_name": "Nia", "last_name": "Newcomer"} | extra  # fmt: skip
    return client.post(SIGNUPS, headers=public(tenant), json=body)


def test_signup_is_off_by_default(client, owner, tenant, f):
    ok(settings(client, owner, f), 200)
    refused = signup(client, tenant, f)
    assert (refused.status_code, refused.json()["code"]) == (409, "signup-disabled")


def test_signup_verifies_the_email_then_creates_the_client_and_signs_in(client, owner, tenant, f, mailbox):
    ok(settings(client, owner, f, allows_self_signup=True), 200)
    email = f"n-{uuid4().hex[:8]}@example.com"
    assert signup(client, tenant, f, email).status_code == 202
    message = mailbox[-1]
    assert f"/f/{tenant.slug}/signup/confirm#token=" in message.body
    assert "?" not in message.body.split("/signup/confirm")[1].split("#")[0]  # never in the query string
    token = link_token(message)

    done = client.post(f"{SIGNUPS}/confirm", headers=public(tenant), json={"token": token})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "signed_in" and done.json()["csrf_token"]
    assert not done.json().get("access_token")  # the web gets the session cookie, not a token
    assert "fh_session" in done.headers.get("set-cookie", "")
    found = ok(client.get(f"{API}/clients", headers=owner, params={"q": email}), 200)["data"]
    assert len(found) == 1

    again = client.post(f"{SIGNUPS}/confirm", headers=public(tenant), json={"token": token})
    assert (again.status_code, again.json()["code"]) == (401, "token-invalid")


def test_known_and_unknown_addresses_answer_alike(client, owner, tenant, f, mailbox):
    ok(settings(client, owner, f, allows_self_signup=True), 200)
    email = f"n-{uuid4().hex[:8]}@example.com"
    first = signup(client, tenant, f, email)
    token = link_token(mailbox[-1])
    assert client.post(f"{SIGNUPS}/confirm", headers=public(tenant), json={"token": token}).status_code == 200
    second = signup(client, tenant, f, email)  # now has a login: a sign-in link, same answer
    assert (first.status_code, first.content) == (second.status_code, second.content)
    assert "/signup/confirm" not in mailbox[-1].body


def test_expired_signup_link(client, owner, tenant, f, mailbox):
    ok(settings(client, owner, f, allows_self_signup=True), 200)
    email = f"n-{uuid4().hex[:8]}@example.com"
    signup(client, tenant, f, email)
    token = link_token(mailbox[-1])
    with tenant_session(tenant.id) as session:
        row = session.scalar(select(PortalSignup).where(PortalSignup.email == email))
        row.expires_at = clock.now() - timedelta(minutes=1)
    late = client.post(f"{SIGNUPS}/confirm", headers=public(tenant), json={"token": token})
    assert (late.status_code, late.json()["code"]) == (401, "token-expired")


def test_redirects_need_https_on_an_allowed_domain(client, owner, f):
    assert settings(client, owner, f, redirect_url="http://example.com/thanks").status_code == 422
    foreign = settings(client, owner, f, redirect_url="https://evil.example.net/x")
    assert (foreign.status_code, foreign.json()["code"]) == (422, "redirect-not-allowed")
    sneaky = settings(client, owner, f, redirect_url="https://club.example.org@evil.example.net/",
                      redirect_domains=["club.example.org"])  # fmt: skip
    assert sneaky.status_code == 422
    body = ok(settings(client, owner, f, redirect_url="https://www.club.example.org/thanks",
                       redirect_domains=["club.example.org"]), 200)  # fmt: skip
    assert body["redirect_url"] == "https://www.club.example.org/thanks"


def test_menu_and_social_links_reach_the_public_config(client, owner, tenant, f):
    twice = [{"key": "programs", "label": "A"}, {"key": "programs", "label": "B"}]
    assert settings(client, owner, f, menu=twice).status_code == 422
    assert settings(client, owner, f, social_links={"instagram": "javascript:alert(1)"}).status_code == 422
    menu = [{"key": "programs", "label": "Camps", "is_visible": True},
            {"key": "rentals", "label": "Courts", "is_visible": False}]  # fmt: skip
    social = {"instagram": "https://instagram.com/club"}
    ok(settings(client, owner, f, menu=menu, social_links=social), 200)

    config = ok(client.get(f"{API}/public/portal-config", headers=public(tenant)), 200)
    assert config["tenant_slug"] == tenant.slug
    (location,) = [loc for loc in config["locations"] if loc["location_id"] == f.location]
    assert [item["key"] for item in location["menu"]] == ["programs", "rentals"]
    assert location["social_links"] == social and location["allows_self_signup"] is False


def test_public_branding_carries_the_tenant_colours(client, owner, tenant):
    colours = {"brand_primary_color": "#1A4D8F", "brand_accent_color": "#f2a900"}
    assert client.patch(f"{API}/tenant", headers=owner, json=colours).status_code == 200
    assert client.patch(f"{API}/tenant", headers=owner, json={"brand_primary_color": "blue"}).status_code == 422
    brand = ok(client.get(f"{API}/public/branding", headers=public(tenant)), 200)
    assert (brand["primary_color"], brand["accent_color"]) == ("#1a4d8f", "#f2a900")
