"""Kernel hardening and the ports that ship ahead of their modules: redirect guard, emailed-link tokens in
the URL fragment, security headers, the body-size cap, lane overrides, notifications, the fake provider."""

import pytest

from app.adapters.fake_payments import FakeProvider
from app.adapters.notifications import NoopNotifier
from app.core.db.session import tenant_session
from app.core.settings import REPO_ROOT, get_settings
from app.modules.platform.auth import safe_redirect_path
from app.ports import notifications
from conftest import link_token

API = "/api/v1"


@pytest.mark.parametrize(
    "path",
    [
        "//evil.example", "//evil.example/x", "/\\evil.example", "/\\/evil.example", "\\\\evil.example",
        "https://evil.example", "http://evil.example/", "javascript:alert(1)", "evil.example", "", None,
        "/ok\\..\\evil", "/a\tb", "/a\nb", "/\x00", " /calendar", "data:text/html,x",
    ],
)  # fmt: skip
def test_redirect_guard_refuses_anything_but_a_local_path(path):
    assert safe_redirect_path(path) is None


@pytest.mark.parametrize("path", ["/", "/calendar", "/staff/123?tab=roles", "/a/b#section", "/search?q=a//b"])
def test_redirect_guard_keeps_local_paths(path):
    assert safe_redirect_path(path) == path


def test_emailed_links_carry_the_token_in_the_fragment_only(client, tenant, mailbox):
    """security-baseline 17.2: a fragment never reaches a server log or a Referer header."""
    headers = {"X-Tenant-Slug": tenant.slug}
    for redirect in ("/calendar", "//evil.example", "/\\evil.example", "https://evil.example"):
        body = {"email": tenant.owner_email, "redirect_path": redirect}
        assert client.post(f"{API}/auth/magic-links", headers=headers, json=body).status_code == 202
        link = next(word for word in mailbox[-1].body.split() if word.startswith("http"))
        base, _, fragment = link.partition("#")
        assert base == f"{get_settings().app.web_base_url}/auth/magic-link" and "?" not in link
        assert fragment.startswith("token=fhl_")
        assert ("&redirect=/calendar" in fragment) == (redirect == "/calendar") and "evil" not in link
    assert client.post(f"{API}/auth/password-resets", headers=headers, json={"email": tenant.owner_email})
    assert "/auth/reset-password#token=" in mailbox[-1].body
    consumed = client.post(f"{API}/auth/magic-links/consume", json={"token": link_token(mailbox[-2])})
    assert consumed.status_code == 200


def test_security_headers_on_every_kind_of_response(client, tenant, owner):
    for response in (
        client.get(f"{API}/health/live"),
        client.get(f"{API}/me", headers=owner),
        client.get(f"{API}/me"),  # 401
        client.get(f"{API}/no-such-route"),  # 404
        client.post(f"{API}/auth/sign-in", content=b"{", headers={"content-type": "application/json"}),  # 422
    ):
        headers = response.headers
        assert headers["x-content-type-options"] == "nosniff", response.url
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cross-origin-opener-policy"] == "same-origin"
        assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        assert headers["cache-control"] == "no-store"
        assert "geolocation=()" in headers["permissions-policy"]
        assert "strict-transport-security" not in headers  # only when cookies are Secure, i.e. behind TLS
        assert headers["x-request-id"]
    docs = client.get(f"{API}/docs")
    assert docs.status_code == 200 and "content-security-policy" not in docs.headers  # the page loads its UI
    assert docs.headers["x-content-type-options"] == "nosniff"


def test_hsts_is_sent_when_cookies_are_secure(monkeypatch):
    from app.core.api import SecurityHeadersMiddleware

    monkeypatch.setattr(get_settings().auth, "cookie_secure", True)
    assert SecurityHeadersMiddleware(None).headers[b"strict-transport-security"].startswith(b"max-age=31536000")


def test_request_body_size_cap(client, tenant):
    limit = get_settings().api.max_body_bytes
    headers = {"X-Tenant-Slug": tenant.slug, "content-type": "application/json"}
    url = f"{API}/auth/sign-in"
    padded = lambda size: b'{"email": "a@example.com", "password": "' + b"x" * size + b'"}'  # noqa: E731

    declared = client.post(url, content=padded(limit), headers=headers)
    assert declared.status_code == 413 and declared.headers["content-type"] == "application/problem+json"
    assert declared.json()["code"] == "payload-too-large" and declared.json()["trace_id"]
    assert declared.headers["x-content-type-options"] == "nosniff"

    def chunks():  # no Content-Length: the cap counts what actually arrives
        for _ in range(limit // 65536 + 2):
            yield b"x" * 65536

    streamed = client.post(url, content=chunks(), headers=headers)
    assert streamed.status_code == 413 and streamed.json()["code"] == "payload-too-large"
    # Under the cap the request reaches validation as usual (the password is too long for the schema).
    assert client.post(url, content=padded(2000), headers=headers).status_code == 422


def test_only_the_file_routes_take_large_bodies():
    """The Caddy @upload matcher (infra/proxy/Caddyfile) must list the same routes."""
    from app.core.api import BodyLimitMiddleware

    match = BodyLimitMiddleware.UPLOAD_PATHS.match
    for path in ("client-documents/x/paper-scan", "clients/x/photo", "client-notes/x/attachments"):
        assert match(f"/api/v1/{path}")
    for path in ("clients/x", "clients/x/photo/extra", "client-notes/x/attachments/y", "auth/sign-in"):
        assert not match(f"/api/v1/{path}")
    caddy = (REPO_ROOT / "infra/proxy/Caddyfile").read_text()
    assert "clients/[^/]+/photo" in caddy and "client-notes/[^/]+/attachments" in caddy


# --- lane isolation ------------------------------------------------------------------------------------------


def test_lane_overrides(monkeypatch):
    load = get_settings.__wrapped__
    assert (load().db.name, load().api.port, load().app.web_base_url) == (
        get_settings().db.name, get_settings().api.port, get_settings().app.web_base_url,
    )  # fmt: skip
    for name, value in (("FH_DB_NAME", "facilityhub_space"), ("FH_TEST_DB_NAME", "facilityhub_test_space"),
                        ("FH_API_PORT", "8110"), ("FH_WEB_PORT", "5193")):  # fmt: skip
        monkeypatch.setenv(name, value)
    lane = load()  # FH_ENV=test: the test database name applies
    assert (lane.db.name, lane.api.port, lane.app.web_base_url) == (
        "facilityhub_test_space", 8110, "http://localhost:5193",
    )  # fmt: skip
    assert lane.db_url("app").endswith("/facilityhub_test_space")
    monkeypatch.setenv("FH_ENV", "dev")
    assert load().db.name == "facilityhub_space"


def test_fake_payments_are_refused_outside_dev_and_test(monkeypatch, tmp_path, deploy_secrets):
    config = (REPO_ROOT / "config" / "app.yaml").read_text()
    (tmp_path / "app.yaml").write_text(config.replace("cookie_secure: false", "cookie_secure: true"))
    (tmp_path / "app.prod.yaml").write_text("email:\n  log_links: false\napi:\n  exposed_directly: true\n")
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", "prod")
    monkeypatch.setenv("FH_PAYMENTS_PROVIDER", "")  # a local .env trying Stripe must not mask the config under test
    with pytest.raises(RuntimeError, match="payments.provider"):
        get_settings.__wrapped__()
    (tmp_path / "app.prod.yaml").write_text(
        "email:\n  log_links: false\npayments:\n  provider: none\nstorage:\n  scanner: clamd\napi:\n  exposed_directly: true\n"
    )
    assert get_settings.__wrapped__().payments.provider == "none"


def test_production_refuses_to_guess_whether_a_proxy_stands_in_front(monkeypatch, tmp_path, deploy_secrets):
    """Behind an unlisted proxy every client is the proxy (one sign-in bucket, a useless allow-list): outside dev
    and test, an empty api.trusted_proxies needs api.exposed_directly said out loud."""
    config = (REPO_ROOT / "config" / "app.yaml").read_text().replace("cookie_secure: false", "cookie_secure: true")
    (tmp_path / "app.yaml").write_text(config)
    base = "email: {log_links: false}\npayments: {provider: none}\nstorage: {scanner: clamd}\n"
    (tmp_path / "app.prod.yaml").write_text(base)
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", "prod")
    monkeypatch.setenv("FH_PAYMENTS_PROVIDER", "")
    with pytest.raises(RuntimeError, match="api.trusted_proxies"):
        get_settings.__wrapped__()
    (tmp_path / "app.prod.yaml").write_text(base + "api: {trusted_proxies: [fdaa::/16]}\n")
    assert get_settings.__wrapped__().api.trusted_proxies == ["fdaa::/16"]
    (tmp_path / "app.prod.yaml").write_text(base + "api: {exposed_directly: true}\n")
    assert get_settings.__wrapped__().api.exposed_directly


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("FH_DATA_KEY", "", "FH_DATA_KEY"),
        ("FH_DATA_KEY", "ZmFjaWxpdHlodWItZGV2LW9ubHktZGF0YS1rZXktMzI=", "FH_DATA_KEY"),  # the dev key
        ("FH_DATA_KEY", "VwpXfRnSkcoF5/q6HdE+0q6UoYCTPLxCXfp2XaacPsw=", "FH_DATA_KEY"),  # the old stack example
        ("FH_OPERATOR_TOKEN", "dev-operator-token", "FH_OPERATOR_TOKEN"),
        ("FH_OPERATOR_TOKEN", "stack-operator-token", "FH_OPERATOR_TOKEN"),
        ("FH_OPERATOR_TOKEN", "short-but-random-31-characters!", "FH_OPERATOR_TOKEN"),
    ],
)
def test_production_refuses_dev_and_example_secrets(monkeypatch, tmp_path, deploy_secrets, name, value, message):
    """The data key seals TOTP and OIDC secrets and keys file-URL and recovery-code MACs; a committed value is public."""
    config = (REPO_ROOT / "config" / "app.yaml").read_text().replace("cookie_secure: false", "cookie_secure: true")
    (tmp_path / "app.yaml").write_text(config)
    overlay = "email: {log_links: false}\npayments: {provider: none}\nstorage: {scanner: clamd}\napi: {exposed_directly: true}\n"
    (tmp_path / "app.prod.yaml").write_text(overlay)
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", "prod")
    monkeypatch.setenv("FH_PAYMENTS_PROVIDER", "")
    assert get_settings.__wrapped__().env == "prod"  # the generated values start
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=message):
        get_settings.__wrapped__()
    if name == "FH_OPERATOR_TOKEN":
        monkeypatch.setenv(name, "")  # empty turns the operator endpoints off, which is allowed
        assert get_settings.__wrapped__().env == "prod"


# --- notification port ---------------------------------------------------------------------------------------


def test_notification_goes_out_by_email_only_when_the_transaction_commits(tenant, mailbox):
    notifications.TEMPLATES.pop("tests.booking_confirmed", None)
    notifications.register_template(
        "tests.booking_confirmed", subject="Booked: $what", body="Hi $name, see you at $when.\n"
    )
    with pytest.raises(ValueError, match="already registered"):
        notifications.register_template("tests.booking_confirmed", subject="x", body="y")
    data = {"what": "Court 1", "name": "Casey", "when": "5 pm"}
    with tenant_session(tenant.id) as session:
        notifications.send(session, "tests.booking_confirmed", "casey@example.com", data)
        assert mailbox == []  # nothing leaves before the commit
    assert [(m.to, m.subject, m.body) for m in mailbox] == [
        ("casey@example.com", "Booked: Court 1", "Hi Casey, see you at 5 pm.\n")
    ]
    with pytest.raises(RuntimeError), tenant_session(tenant.id) as session:
        notifications.send(session, "tests.booking_confirmed", "casey@example.com", data)
        raise RuntimeError("roll back")
    assert len(mailbox) == 1
    with tenant_session(tenant.id) as session:
        with pytest.raises(KeyError):  # programming errors surface in the request, not in delivery
            notifications.send(session, "tests.booking_confirmed", "casey@example.com", {"what": "x"})
        with pytest.raises(KeyError):
            notifications.send(session, "tests.unknown", "casey@example.com", {})


def test_noop_notifier_delivers_nothing(tenant, mailbox):
    notifications.TEMPLATES.setdefault("tests.noop", notifications.NotificationTemplate("s", "b"))
    before = notifications._notifier  # restore what was installed, or later tests run without engagement's log
    notifications.configure(NoopNotifier())
    try:
        with tenant_session(tenant.id) as session:
            notifications.send(session, "tests.noop", "casey@example.com", {})
    finally:
        notifications.configure(before)
    assert mailbox == []


# --- fake payment provider -----------------------------------------------------------------------------------


def test_fake_provider_scripts_and_idempotency():
    fake = FakeProvider()
    pay = lambda token, key, amount=1000: fake.create_payment(  # noqa: E731
        account_ref="a", amount_minor=amount, currency="USD", method_token=token, idempotency_key=key
    )
    ok = pay("tok_card_ok", "k1")
    assert (ok.outcome, ok.card_last4) == ("succeeded", "4242")
    assert pay("tok_card_declined", "k1") == ok  # the key wins: same payment, whatever is sent again
    assert (pay("tok_card_declined", "k2").outcome, pay("tok_card_declined", "k2").failure_category) == (
        "declined", "card_declined",
    )  # fmt: skip
    assert pay("tok_card_insufficient", "k3").failure_category == "insufficient_funds"
    assert pay("tok_from_nowhere", "k4").failure_category == "processor_error"

    lost = pay("tok_card_unknown", "k5")
    assert lost.outcome == "unknown" and lost.failure_category is None
    assert fake.get_payment(account_ref="a", provider_payment_ref=lost.provider_payment_ref).outcome == "succeeded"

    for token, final in (("tok_ach_ok", "succeeded"), ("tok_ach_fail", "declined")):
        pending = pay(token, f"ach-{token}")
        ref = pending.provider_payment_ref
        assert pending.outcome == "processing" and pending.card_last4 is None
        assert fake.get_payment(account_ref="a", provider_payment_ref=ref).outcome == "processing"
        fake.settle(ref)
        fake.settle(ref)  # settling twice changes nothing
        assert fake.get_payment(account_ref="a", provider_payment_ref=ref).outcome == final

    refund = lambda key, amount, ref=ok.provider_payment_ref: fake.refund(  # noqa: E731
        account_ref="a", provider_payment_ref=ref, amount_minor=amount, idempotency_key=key
    )
    assert fake.find_refund(account_ref="a", idempotency_key="r1") is None
    first = refund("r1", 600)
    assert first.outcome == "succeeded" and refund("r1", 600) == first
    assert fake.find_refund(account_ref="a", idempotency_key="r1") == first
    assert refund("r2", 401).outcome == "failed"  # more than is left of the payment
    assert refund("r3", 400).outcome == "succeeded"
    assert refund("r4", 1, ref=pay("tok_card_declined", "k2").provider_payment_ref).outcome == "failed"


def test_every_idempotency_key_header_has_the_key_pattern():
    """Backlog 26: no route takes an Idempotency-Key that the shared pattern would refuse."""
    from app.core.idempotency import KEY_PATTERN
    from app.main import app

    loose = [
        (path, method)
        for path, ops in app.openapi()["paths"].items()
        for method, op in ops.items()
        for param in op.get("parameters", [])
        if param["name"].lower() == "idempotency-key"
        and KEY_PATTERN not in {s.get("pattern") for s in [param["schema"], *param["schema"].get("anyOf", [])]}
    ]
    assert loose == []


@pytest.mark.parametrize(
    ("sslmode", "redis_url", "message"),
    [
        ("", "rediss://cache.internal:6380/0", "sslmode"),
        ("disable", "rediss://cache.internal:6380/0", "sslmode"),
        ("prefer", "rediss://cache.internal:6380/0", "sslmode"),
        ("verify-full", "redis://cache.internal:6379/0", "rediss://"),
        ("require", "rediss://cache.internal:6380/0", "verify-full"),  # encrypted but unverified
        ("verify-ca", "rediss://cache.internal:6380/0", "verify-full"),
        ("verify-full", "rediss://cache.internal:6380/0?ssl_cert_reqs=none", "verif"),
        ("verify-full", "rediss://cache.internal:6380/0?SSL_CERT_REQS=optional", "verif"),
        ("verify-full", "rediss://cache.internal:6380/0?ssl_check_hostname=false", "verif"),
        # encoded, fragment-trailed and short spellings that redis-py still honours
        ("verify-full", "rediss://cache.internal:6380/0?ssl_cert_reqs=%6eone", "verif"),
        ("verify-full", "rediss://cache.internal:6380/0?ssl_cert_reqs=none#x", "verif"),
        ("verify-full", "rediss://cache.internal:6380/0?ssl_check_hostname=n", "verif"),
        ("verify-full", "rediss://cache.internal:6380/0?ssl_cert_reqs=CERT_NONE", "verif"),
        ("verify-full", "REDIS://cache.internal:6379/0", "rediss://"),
        # Postgres: only the exact mode reaches the URL
        ("verify-full&sslmode=disable", "rediss://cache.internal:6380/0", "verify-full"),
        ("Verify-Full", "rediss://cache.internal:6380/0", "verify-full"),
    ],
)
def test_production_refuses_plaintext_postgres_and_redis(
    monkeypatch, tmp_path, deploy_secrets, sslmode, redis_url, message
):
    """security-baseline V9: TLS from the app to Postgres and Redis outside dev and test."""
    config = (REPO_ROOT / "config" / "app.yaml").read_text().replace("cookie_secure: false", "cookie_secure: true")
    (tmp_path / "app.yaml").write_text(config)
    overlay = "email: {log_links: false}\npayments: {provider: none}\nstorage: {scanner: clamd}\n"
    (tmp_path / "app.prod.yaml").write_text(overlay + "api: {exposed_directly: true}\n")
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", "prod")
    monkeypatch.setenv("FH_PAYMENTS_PROVIDER", "")
    monkeypatch.setenv("FH_DB_APP_PASSWORD", "x")
    settings = get_settings.__wrapped__()  # deploy_secrets sets verify-full and a rediss:// URL
    assert settings.db_url("app").endswith("?sslmode=verify-full") and settings.redis.url.startswith("rediss://")
    monkeypatch.setenv("FH_DB_SSLMODE", sslmode)
    monkeypatch.setenv("FH_REDIS_URL", redis_url)
    with pytest.raises(RuntimeError, match=message):
        get_settings.__wrapped__()


def test_a_database_name_cannot_smuggle_url_parameters_past_the_tls_guard(monkeypatch, tmp_path, deploy_secrets):
    from sqlalchemy.engine import make_url

    config = (REPO_ROOT / "config" / "app.yaml").read_text().replace("cookie_secure: false", "cookie_secure: true")
    (tmp_path / "app.yaml").write_text(config)
    overlay = "email: {log_links: false}\npayments: {provider: none}\nstorage: {scanner: clamd}\n"
    (tmp_path / "app.prod.yaml").write_text(overlay + "api: {exposed_directly: true}\n")
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", "prod")
    monkeypatch.setenv("FH_PAYMENTS_PROVIDER", "")
    monkeypatch.setenv("FH_DB_APP_PASSWORD", "p@ss/word?x")
    monkeypatch.setenv("FH_DB_NAME", "fh?sslmode=disable&application_name=")
    url = make_url(get_settings.__wrapped__().db_url("app"))
    assert dict(url.query) == {"sslmode": "verify-full"}
    assert (url.database, url.password) == ("fh?sslmode=disable&application_name=", "p@ss/word?x")


def test_dev_and_test_keep_plain_local_postgres_and_redis():
    settings = get_settings()
    assert settings.db.sslmode is None and "sslmode" not in settings.db_url("app")


def test_the_local_container_stack_may_use_its_self_signed_certificates(monkeypatch, tmp_path, deploy_secrets):
    """FH_ENV=stack is the local container stack, explicitly not production: every production guard applies
    except certificate verification, since its Postgres and Redis certificates are self-signed."""
    config = (REPO_ROOT / "config" / "app.yaml").read_text().replace("cookie_secure: false", "cookie_secure: true")
    (tmp_path / "app.yaml").write_text(config)
    overlay = "email: {log_links: false}\npayments: {provider: none}\nstorage: {scanner: clamd}\n"
    (tmp_path / "app.stack.yaml").write_text(overlay + "api: {exposed_directly: true}\n")
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", "stack")
    monkeypatch.setenv("FH_PAYMENTS_PROVIDER", "")
    monkeypatch.setenv("FH_DB_SSLMODE", "require")
    monkeypatch.setenv("FH_REDIS_URL", "rediss://redis:6379/0?ssl_cert_reqs=none&ssl_check_hostname=false")
    assert get_settings.__wrapped__().env == "stack"
    monkeypatch.setenv("FH_REDIS_URL", "redis://redis:6379/0")
    with pytest.raises(RuntimeError, match="rediss://"):  # still TLS
        get_settings.__wrapped__()


def test_the_shipped_production_overlay_verifies_certificates():
    import yaml

    prod = yaml.safe_load((REPO_ROOT / "infra" / "docker" / "config" / "app.production.yaml").read_text())
    assert prod["db"]["sslmode"] == "verify-full"
    assert prod["redis"]["url"].startswith("rediss://") and "ssl_cert_reqs" not in prod["redis"]["url"]


def test_signed_in_slug_naming_another_tenant_is_not_found(client, tenant, owner):
    """SSP-01: /f/:slug sends X-Tenant-Slug; a slug that is not the session's tenant reads as unknown, the same
    body whether that tenant exists or not."""
    from conftest import make_tenant

    assert client.get(f"{API}/me", headers=owner | {"X-Tenant-Slug": tenant.slug}).status_code == 200
    foreign = client.get(f"{API}/me", headers=owner | {"X-Tenant-Slug": make_tenant().slug})
    unknown = client.get(f"{API}/me", headers=owner | {"X-Tenant-Slug": "no-such-tenant-x"})
    assert foreign.status_code == unknown.status_code == 404
    strip = lambda r: {k: v for k, v in r.json().items() if k != "trace_id"}  # noqa: E731
    assert strip(foreign) == strip(unknown) and foreign.json()["code"] == "tenant-not-found"
