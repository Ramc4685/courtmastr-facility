"""Typed settings: config/app.yaml (+ optional app.<env>.yaml overlay); secrets from the environment only."""

import os
from functools import cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import yaml
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[3]


class AppInfo(BaseModel):
    display_name: str
    code_name: str
    web_base_url: str
    base_domain: str


class Api(BaseModel):
    host: str
    port: int
    max_body_bytes: int = 1_048_576
    trusted_proxies: list[str] = []  # peers whose X-Forwarded-For names the client
    # True only when browsers reach the API with no proxy in front: then the socket peer is the client. Outside dev
    # and test, an empty trusted_proxies without this is refused at startup (every client would look like the proxy).
    exposed_directly: bool = False


class Db(BaseModel):
    host: str
    port: int
    name: str
    pool_size: int = 10
    # libpq sslmode; FH_DB_SSLMODE overrides. Outside dev and test it must be require, verify-ca or verify-full
    # (security-baseline V9 wants verify-full; the CA file comes from libpq's own PGSSLROOTCERT).
    sslmode: str | None = None


class Redis(BaseModel):
    url: str  # FH_REDIS_URL overrides (it may carry a password); outside dev and test it must be rediss://


class Email(BaseModel):
    adapter: str
    smtp_host: str
    smtp_port: int
    from_address: str
    log_links: bool = False


class Jobs(BaseModel):
    broker: str


class Argon2(BaseModel):
    memory_kib: int
    time_cost: int
    parallelism: int


class SessionLifetime(BaseModel):
    idle_min: int
    absolute_hours: int


class Stripe(BaseModel):
    """Stripe Connect adapter, used when payments.provider is stripe. Keys come from the environment only
    (STRIPE_KEY_VARS), never from a file."""

    api_base: str = "https://api.stripe.com"
    api_version: str = "2026-05-27.dahlia"  # pinned so the account default cannot change the request shapes
    timeout_seconds: float = 20.0
    # hosted: Stripe's onboarding pages, the tenant gets a full dashboard (production). api: dev and test only, the
    # platform fills Stripe's test values on create so a test account goes active with no Stripe login.
    test_onboarding: str = "hosted"


STRIPE_KEY_VARS = ("FH_STRIPE_SECRET_KEY", "FH_STRIPE_PUBLISHABLE_KEY", "FH_STRIPE_WEBHOOK_SECRET")
_LIVE_KEY_PREFIXES = ("sk_live_", "pk_live_", "rk_live_")
PRODUCTION_ENVS = ("prod", "production")  # the only FH_ENV values that may hold a live Stripe key


class Payments(BaseModel):
    provider: str = "fake"  # fake | stripe | none. fake: the in-process test processor (dev and test only)
    default_country: str = "US"  # country of a newly connected processor account
    stripe: Stripe = Stripe()


class Notifications(BaseModel):
    adapter: str = "email"  # email | noop


class Auth(BaseModel):
    access_ttl_min: int
    refresh_grace_sec: int
    magic_link_ttl_min: int
    password_reset_ttl_min: int
    invite_ttl_days: int
    lockout_threshold: int
    lockout_window_min: int
    lockout_min: int
    lockout_max_min: int
    pre_session_ttl_min: int
    password_min_length: int
    cookie_secure: bool
    argon2: Argon2
    sessions: dict[str, SessionLifetime]
    step_up_min: int = 10  # how long a re-authentication satisfies `+` keys (owner decision 4)
    mfa_challenge_ttl_min: int = 5  # the pending sign-in between password (or link) and the second factor


class Bucket(BaseModel):
    limit: int
    window_sec: int
    closed: bool = False  # refuse rather than allow while Redis is unreachable


class RateLimit(BaseModel):
    enabled: bool
    buckets: dict[str, Bucket]
    api_per_minute: int = 120  # per API key (ADR 0012 section 2)


class Integrations(BaseModel):
    # Dev only: webhook endpoints may use http:// and loopback hosts, so a local receiver works (ADR 0007 s.7).
    webhook_allow_localhost: bool = False
    # The real QuickBooks Online adapter stays off until credentials and an Intuit app exist (ADR 0012 s.4).
    quickbooks_enabled: bool = False
    accounting_file_dir: str = "var/accounting-exports"  # where the accounting_file adapter writes journals


class Audit(BaseModel):
    retention_days: int
    retention_days_long: int


class Retention(BaseModel):
    """Purge periods in days (ADR 0007 section 9, security-baseline 2.3). Audit rows carry their own
    retain_until_on from `audit`; idempotency keys and report results carry their own expiry."""

    auth_session_days: int = 90  # after the session expired or was revoked
    auth_token_days: int = 30  # after the link expired or was used (assumption: no spec value)
    outbox_days: int = 30  # published events only; unpublished rows are never purged
    processed_event_days: int = 45  # must exceed outbox retention plus the retry window
    batch_rows: int = 10_000  # per table per run; the hourly clock drains any backlog
    gdpr_auth_session_days: int = 30  # a tenant in GDPR mode (PLT-16) keeps ended sessions and links shorter
    gdpr_auth_token_days: int = 7
    tenant_export_days: int = 7  # a tenant export bundle stays downloadable this long (IMP-04)
    support_screenshot_days: int = 1  # a screenshot never attached to a support request (ONB-03)
    message_body_days: int = 90  # message.body_text is nulled after this; the row and its counts stay (2.3)
    # A processed or ignored inbound provider event keeps its row (deduplication) but its payload, which may hold
    # provider PII, is emptied after this (ADR 0007 section 9: 90 days; the baseline names no period).
    inbound_payload_days: int = 90


class S3(BaseModel):
    """S3-compatible bucket (AWS S3, Fly Tigris, MinIO). Keys come from the environment only (.env.example)."""

    bucket: str = "facilityhub"
    endpoint_url: str | None = None  # None means AWS; MinIO and Tigris give one
    region: str = "us-east-1"
    path_style: bool = False  # MinIO needs path-style addressing


class Storage(BaseModel):
    adapter: Literal["local", "s3"] = "local"
    local_dir: str = "var/storage"  # relative to the repository root
    max_upload_bytes: int = 20_971_520  # scanned documents and attachments (security-baseline 8.2)
    s3: S3 = S3()
    scanner: Literal["noop", "clamd"] = "noop"  # noop is refused outside dev and test
    clamd_host: str = "127.0.0.1"
    clamd_port: int = 53310
    # Origin serving the public prefix t/*/public/* (logos) straight from the bucket or a CDN; None means the
    # app's /public/objects route serves them (platform.branding).
    public_base_url: str | None = None


class Support(BaseModel):
    operator_email: str = "support@facilityhub.localhost"  # ONB-03 support requests go here


class Imports(BaseModel):
    """CSV imports (Phase 8 I1)."""

    max_opening_balance_minor: int = 10_000_000  # one opening balance, owed or credit: 100,000.00 in the currency
    stalled_minutes: int = 60  # a running import with no progress this long is marked failed (its files can expire)


class Entitlements(BaseModel):
    default_plan: str = "complete"  # subscription_plan.code for new tenants and tenants without a plan (PLT-14)


class Settings(BaseModel):
    env: str
    app: AppInfo
    api: Api
    db: Db
    redis: Redis
    email: Email
    jobs: Jobs
    payments: Payments = Payments()
    notifications: Notifications = Notifications()
    auth: Auth
    rate_limit: RateLimit
    audit: Audit
    integrations: Integrations = Integrations()
    storage: Storage = Storage()
    retention: Retention = Retention()
    entitlements: Entitlements = Entitlements()
    support: Support = Support()
    imports: Imports = Imports()

    def db_url(self, role: str) -> str:
        """role is owner, app or platform; the password comes from FH_DB_<ROLE>_PASSWORD."""
        password = os.environ[f"FH_DB_{role.upper()}_PASSWORD"]
        query = f"?sslmode={self.db.sslmode}" if self.db.sslmode else ""
        return f"postgresql+psycopg://fh_{role}:{password}@{self.db.host}:{self.db.port}/{self.db.name}{query}"

    @property
    def operator_token(self) -> str:
        return os.environ.get("FH_OPERATOR_TOKEN", "")


# Dev and test only: a fixed data key so a fresh checkout works (core.crypto). Refused anywhere else, as are the
# values that were ever committed as examples (they are public) and an operator token short enough to guess.
DEV_DATA_KEY = "ZmFjaWxpdHlodWItZGV2LW9ubHktZGF0YS1rZXktMzI="  # base64 of b"facilityhub-dev-only-data-key-32"
_EXAMPLE_DATA_KEYS = {DEV_DATA_KEY, "VwpXfRnSkcoF5/q6HdE+0q6UoYCTPLxCXfp2XaacPsw="}
_EXAMPLE_OPERATOR_TOKENS = {"dev-operator-token", "stack-operator-token"}
MIN_OPERATOR_TOKEN_LENGTH = 32


def _refuse_example_secrets() -> None:
    data_key = os.environ.get("FH_DATA_KEY", "").strip()
    if not data_key or data_key in _EXAMPLE_DATA_KEYS:
        # It seals TOTP secrets, OIDC client secrets and webhook and integration credentials, and keys the file
        # URL and recovery-code MACs: a known key gives all of them away.
        raise RuntimeError("outside dev and test, FH_DATA_KEY must be set to a generated key, not a dev or example one")
    token = os.environ.get("FH_OPERATOR_TOKEN", "")
    if token and (token in _EXAMPLE_OPERATOR_TOKENS or len(token) < MIN_OPERATOR_TOKEN_LENGTH):
        raise RuntimeError(
            f"outside dev and test, FH_OPERATOR_TOKEN must be empty (endpoint off) or a generated value of at least "
            f"{MIN_OPERATOR_TOKEN_LENGTH} characters, never an example one"
        )


_TLS_SSLMODES = ("require", "verify-ca", "verify-full")
# The local container stack (infra/docker/compose.stack.yml): every production guard, but its Postgres and Redis
# certificates are self-signed, so encryption without verification is accepted there and nowhere else.
STACK_ENV = "stack"


def _redis_unverified(url: str) -> bool:
    """True when the URL's query weakens verification, read the way redis-py reads it (decoded, fragment dropped)
    and case-folded: ssl_cert_reqs may only say required, ssl_check_hostname only a true value (both default safe)."""
    for key, values in parse_qs(urlsplit(url).query, keep_blank_values=True).items():
        key = key.casefold()
        if key == "ssl_cert_reqs" and any(v.casefold() != "required" for v in values):
            return True
        if key == "ssl_check_hostname" and any(v.casefold() not in ("true", "t", "yes", "y", "1") for v in values):
            return True
    return False


def _refuse_plaintext_backends(settings: "Settings") -> None:
    """security-baseline V9: names, emails and session data cross the network to Postgres and Redis, encrypted
    and to a verified server (Postgres verify-full with PGSSLROOTCERT; Redis with its CA in ssl_ca_certs)."""
    if settings.env == STACK_ENV:
        if settings.db.sslmode not in _TLS_SSLMODES:
            raise RuntimeError("in the stack, db.sslmode (or FH_DB_SSLMODE) must be require or stricter")
    elif settings.db.sslmode != "verify-full":
        raise RuntimeError("outside dev and test, db.sslmode (or FH_DB_SSLMODE) must be verify-full (PGSSLROOTCERT)")
    if urlsplit(settings.redis.url).scheme.casefold() != "rediss":
        raise RuntimeError("outside dev and test, the Redis URL (FH_REDIS_URL) must use TLS: rediss://")
    if settings.env != STACK_ENV and _redis_unverified(settings.redis.url):
        raise RuntimeError("outside dev and test, the Redis URL must verify the server's certificate and host name")


def _merge(base: dict, over: dict) -> dict:
    for key, value in over.items():
        base[key] = _merge(base[key], value) if isinstance(value, dict) and key in base else value
    return base


def _load_dotenv(path: Path) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def _lane_overrides(data: dict, env: str) -> None:
    """Parallel checkouts (lanes) share one Postgres and one machine: each gets its own databases and ports
    through FH_DB_NAME, FH_TEST_DB_NAME, FH_API_PORT and FH_WEB_PORT. FH_DB_SSLMODE and FH_REDIS_URL (backend TLS,
    the URL may carry a password) ride the same path. Unset means the config file value."""
    if name := os.environ.get("FH_TEST_DB_NAME" if env == "test" else "FH_DB_NAME"):
        data["db"]["name"] = name
    if sslmode := os.environ.get("FH_DB_SSLMODE"):
        data["db"]["sslmode"] = sslmode
    if redis_url := os.environ.get("FH_REDIS_URL"):
        data["redis"]["url"] = redis_url
    if port := os.environ.get("FH_API_PORT"):
        data["api"]["port"] = int(port)
    if port := os.environ.get("FH_WEB_PORT"):
        url = urlsplit(data["app"]["web_base_url"])
        data["app"]["web_base_url"] = url._replace(netloc=f"{url.hostname}:{int(port)}").geturl()


@cache
def get_settings() -> Settings:
    _load_dotenv(REPO_ROOT / ".env")
    env = os.environ.get("FH_ENV", "dev")
    config_dir = Path(os.environ.get("FH_CONFIG_DIR", REPO_ROOT / "config"))
    data = yaml.safe_load((config_dir / "app.yaml").read_text())
    overlay = config_dir / f"app.{env}.yaml"
    if overlay.exists():
        _merge(data, yaml.safe_load(overlay.read_text()) or {})
    _lane_overrides(data, env)
    if env != "test" and (provider := os.environ.get("FH_PAYMENTS_PROVIDER")):
        data["payments"]["provider"] = provider  # try Stripe test mode locally without editing a config file
    settings = Settings(env=env, **data)
    if env not in ("dev", "test") and (not settings.auth.cookie_secure or settings.email.log_links):
        # Dev conveniences that are unsafe anywhere else: cookies over plain HTTP, sign-in links in the log.
        raise RuntimeError("outside dev and test, auth.cookie_secure must be true and email.log_links false")
    if env not in ("dev", "test") and settings.integrations.webhook_allow_localhost:
        raise RuntimeError("outside dev and test, integrations.webhook_allow_localhost must be false (SSRF guard)")
    if env not in ("dev", "test") and settings.payments.stripe.test_onboarding != "hosted":
        raise RuntimeError("outside dev and test, payments.stripe.test_onboarding must be hosted")
    if env not in ("dev", "test") and settings.payments.provider == "fake":
        raise RuntimeError("outside dev and test, payments.provider must not be fake: it takes no real money")
    if env not in PRODUCTION_ENVS and any(
        os.environ.get(name, "").startswith(_LIVE_KEY_PREFIXES) for name in STRIPE_KEY_VARS
    ):
        # A live Stripe key moves real money: only a production deployment may hold one.
        raise RuntimeError(f"a live Stripe key is set but FH_ENV is {env!r}: use test-mode keys outside production")
    if env not in ("dev", "test") and not settings.api.trusted_proxies and not settings.api.exposed_directly:
        # Behind an unlisted proxy every client is seen as the proxy: one global sign-in bucket, and an allow-list
        # error that tells the admin to add the proxy's address (which admits everyone).
        raise RuntimeError("outside dev and test, set api.trusted_proxies to the proxy's address range, or set "
                           "api.exposed_directly: true if no proxy stands in front of the API")  # fmt: skip
    if env not in ("dev", "test"):
        _refuse_example_secrets()
        _refuse_plaintext_backends(settings)
    if env not in ("dev", "test") and settings.storage.scanner == "noop":
        raise RuntimeError("outside dev and test, storage.scanner must not be noop: uploads must be malware-scanned")
    return settings
