"""Typed settings: config/app.yaml (+ optional app.<env>.yaml overlay); secrets from the environment only."""

import os
from functools import cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

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


class Db(BaseModel):
    host: str
    port: int
    name: str
    pool_size: int = 10


class Redis(BaseModel):
    url: str


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
    """Stripe Connect adapter. Off by default; keys come from the environment only (FH_STRIPE_SECRET_KEY,
    FH_STRIPE_WEBHOOK_SECRET), never from a file."""

    enabled: bool = False
    api_base: str = "https://api.stripe.com"
    timeout_seconds: float = 20.0


class Payments(BaseModel):
    provider: str = "fake"  # fake | none: the in-process test processor; real ones are connected per tenant
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

    def db_url(self, role: str) -> str:
        """role is owner, app or platform; the password comes from FH_DB_<ROLE>_PASSWORD."""
        password = os.environ[f"FH_DB_{role.upper()}_PASSWORD"]
        return f"postgresql+psycopg://fh_{role}:{password}@{self.db.host}:{self.db.port}/{self.db.name}"

    @property
    def operator_token(self) -> str:
        return os.environ.get("FH_OPERATOR_TOKEN", "")


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
    through FH_DB_NAME, FH_TEST_DB_NAME, FH_API_PORT and FH_WEB_PORT. Unset means the config file value."""
    if name := os.environ.get("FH_TEST_DB_NAME" if env == "test" else "FH_DB_NAME"):
        data["db"]["name"] = name
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
    settings = Settings(env=env, **data)
    if env not in ("dev", "test") and (not settings.auth.cookie_secure or settings.email.log_links):
        # Dev conveniences that are unsafe anywhere else: cookies over plain HTTP, sign-in links in the log.
        raise RuntimeError("outside dev and test, auth.cookie_secure must be true and email.log_links false")
    if env not in ("dev", "test") and settings.integrations.webhook_allow_localhost:
        raise RuntimeError("outside dev and test, integrations.webhook_allow_localhost must be false (SSRF guard)")
    if env not in ("dev", "test") and settings.payments.provider == "fake":
        raise RuntimeError("outside dev and test, payments.provider must not be fake: it takes no real money")
    if env not in ("dev", "test") and settings.storage.scanner == "noop":
        raise RuntimeError("outside dev and test, storage.scanner must not be noop: uploads must be malware-scanned")
    return settings
