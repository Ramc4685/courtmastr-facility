"""QuickBooks Online connection (INT-07): the OAuth round trip, sealed and refreshed credentials, account
mappings, a manual sync over a date range, retry of one failed day, and the inbound webhook.

Everything goes through the AccountingConnect port. The real adapter (`QuickBooksConnect`) is chosen only when
the Intuit app credentials are in the environment; otherwise the simulated `FakeQuickBooks` answers and every
call lands in adapter_command_log. Neither has run against Intuit (docs/status/phase15-api.md).
"""

import hashlib
import json
import os
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import audit, clock, crypto, inbound_webhooks
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.settings import get_settings
from app.modules.integrations.models import (
    AccountingExport,
    ConnectionStatus,
    ExportStatus,
    ExternalConnection,
    Provider,
)
from app.ports.accounting import AccountingConnect, Credentials

PROVIDER = Provider.QUICKBOOKS_ONLINE
STATE_TTL = 600  # seconds the authorise round trip may take
MAX_SYNC_DAYS = 31
STALE_SYNC = timedelta(minutes=10)  # a running sync whose last chunk is older than this was lost
MAPPING_KINDS = ("ledger_account", "tender_account", "tax_account", "revenue_account", "revenue_class")
SETTINGS_KEYS = {"default_income_account", "sync_from", "auto_sync"}
_ENV = ("FH_QUICKBOOKS_CLIENT_ID", "FH_QUICKBOOKS_CLIENT_SECRET", "FH_QUICKBOOKS_WEBHOOK_VERIFIER")


def connector() -> AccountingConnect:
    """shortcut: app credentials are read from the environment here because core settings are frozen this
    phase; move them into `core.settings.Integrations` (secrets from env) with the core handover."""
    from app.adapters.accounting import FakeQuickBooks, QuickBooksConnect

    client_id, client_secret, verifier = (os.environ.get(name, "") for name in _ENV)
    if client_id and client_secret and verifier:
        return QuickBooksConnect(client_id=client_id, client_secret=client_secret, webhook_verifier=verifier)
    return FakeQuickBooks()


def _simulated_outside_dev(adapter: Any) -> bool:
    """The simulated adapter's codes and signing secret are public, so it may never claim a company or verify a
    webhook outside dev and test."""
    return getattr(adapter, "simulated", False) and get_settings().env not in ("dev", "test")


def _port(session: Session, location_id: UUID | None) -> Any:
    from app.modules.integrations import service

    adapter = connector()
    if _simulated_outside_dev(adapter):
        raise ValidationFailed(
            "QuickBooks Online is not configured", pointer="/provider", code="provider-not-configured"
        )
    return service.adapter_for(session, adapter, "accounting", location_id)


def redirect_uri() -> str:
    """The web app's callback page, which POSTs state and code to the API (the OIDC sign-in pattern): a GET
    that changes state would break the no-mutating-GET rule (security-baseline 5.2)."""
    return f"{get_settings().app.web_base_url.rstrip('/')}/integrations/quickbooks/callback"


# --- credentials -------------------------------------------------------------------------------------------


def _seal(row: ExternalConnection, credentials: Credentials, tenant_id: UUID) -> None:
    row.credentials_ciphertext = crypto.encrypt(json.dumps(asdict(credentials)), tenant_id)


def credentials(session: Session, row: ExternalConnection) -> Credentials:
    """The connection's current tokens, refreshed (and resealed) when they expire within five minutes. The row is
    locked first, so two workers never both spend the single-use refresh token."""
    session.flush()
    session.execute(select(ExternalConnection.id).where(ExternalConnection.id == row.id).with_for_update())
    session.refresh(row, attribute_names=["credentials_ciphertext"])
    if not row.credentials_ciphertext:
        raise Conflict("The connection has no credentials", code="invalid-state-transition")
    tenant_id = session.info["tenant_id"]
    current = Credentials(**json.loads(crypto.decrypt(row.credentials_ciphertext, tenant_id)))
    if current.expires_at - clock.now().timestamp() > 300:
        return current
    fresh = _port(session, row.location_id).refresh(current)
    _seal(row, fresh, tenant_id)
    return fresh


def refresh_if_due(session: Session, row: ExternalConnection) -> bool:
    """Internal (sync_chunk): refresh due tokens as a step of their own, so they commit before any posting that
    might roll back. True when the tokens were rotated; a failure is left to the export, which records it."""
    before = row.credentials_ciphertext
    try:
        credentials(session, row)
    except Exception:  # the provider boundary: the day's export attempt reports it
        return False
    return row.credentials_ciphertext != before


def journal_poster(session: Session, row: ExternalConnection) -> Any:
    """Internal (service._accounting_adapter): the AccountingSync adapter for a QuickBooks connection. The
    simulated adapter is refused outside dev and test: it would mark days posted with nothing sent."""
    adapter = connector()
    if _simulated_outside_dev(adapter):
        raise ValidationFailed("QuickBooks Online is not configured", code="provider-not-configured")
    return adapter.journal_poster(credentials(session, row))


# --- the OAuth round trip ----------------------------------------------------------------------------------


def start(session: Session, row: ExternalConnection, principal: Principal, return_url: str | None) -> str:
    """Leave the new connection pending and return the provider's authorise URL. The state is sealed with the
    tenant's data key and binds tenant, connection, staff user and expiry, so it cannot be forged or replayed
    into another tenant."""
    web = get_settings().app.web_base_url.rstrip("/")
    if return_url and not (return_url == web or return_url.startswith(web + "/")):
        raise ValidationFailed("The return address must be on this app", pointer="/return_url")
    tenant_id = session.info["tenant_id"]
    row.status = ConnectionStatus.PENDING
    row.settings = {**(row.settings or {}), "return_url": return_url or f"{web}/integrations"}
    payload = {"c": str(row.id), "u": str(principal.staff_user_id), "x": clock.now().timestamp() + STATE_TTL}
    state = f"{tenant_id.hex}.{crypto.encrypt(json.dumps(payload), tenant_id)}"
    return _port(session, row.location_id).authorize_url(state=state, redirect_uri=redirect_uri())


def complete(
    session: Session, principal: Principal, state: str, code: str | None, company_id: str | None, error: str | None
) -> dict:
    """Exchange the code and activate the connection, for the staff user who started it only (the state seals
    their id, so a link planted on someone else does nothing: OAuth CSRF). Any failure after the state checks
    out marks the connection `error`, which also uses the state up, and is reported in the result."""
    row, outcome = _complete(session, principal, state, code, company_id, error)
    back = row.settings.get("return_url", get_settings().app.web_base_url)
    return {"external_connection_id": row.id, "status": outcome, "return_url": back}


def _fail(session: Session, row: ExternalConnection, reason: str) -> tuple[ExternalConnection, str]:
    row.status, row.last_error, row.last_error_at = ConnectionStatus.ERROR, reason[:200], clock.now()
    audit.record(session, "integrations.connection.authorize", row, location_id=row.location_id,
                 changes=audit.diff(row))  # fmt: skip
    return row, "error"


def _complete(
    session: Session, principal: Principal, state: str, code: str | None, company_id: str | None, error: str | None
) -> tuple[ExternalConnection, str]:
    tenant_id = session.info["tenant_id"]
    head, _, sealed = state.partition(".")
    try:
        if head != tenant_id.hex:
            raise ValueError("other tenant")
        payload = json.loads(crypto.decrypt(sealed, tenant_id))
    except Exception:  # any malformed, forged or other-tenant state (AES-GCM raises InvalidTag)
        raise PermissionDenied("This connection link is not valid", code="state-invalid") from None
    if payload["u"] != str(principal.staff_user_id):
        raise PermissionDenied("This connection link was started by someone else", code="state-invalid")
    row = session.get(ExternalConnection, UUID(payload["c"]), with_for_update=True)
    # a retried attempt takes over the row (create_external_connection): an earlier starter's link dies with it
    stale = row is not None and str(row.connected_by_staff_user_id) != payload["u"]
    if row is None or stale or row.status != ConnectionStatus.PENDING or payload["x"] < clock.now().timestamp():
        raise PermissionDenied("This connection link has expired", code="state-invalid")
    if error or not code or not company_id:
        return _fail(session, row, error or "no code")
    if not company_id.isdigit():
        return _fail(session, row, "realm-invalid")
    port = _port(session, row.location_id)
    try:
        creds = port.exchange_code(code=code, company_id=company_id, redirect_uri=redirect_uri())
        verified = port.token_company_id(creds)
    except Exception as exc:  # the provider boundary: record it, never leak it
        return _fail(session, row, type(exc).__name__)
    if verified != company_id:  # the browser named a company the token does not open
        return _fail(session, row, "realm-mismatch")
    claimed = session.scalar(text("SELECT app.claim_provider_account(:p, :r)"), {"p": PROVIDER.value, "r": company_id})
    if not claimed:
        raise Conflict("This QuickBooks company is connected to another account", code="account-in-use")
    _seal(row, creds, tenant_id)
    row.status, row.external_account_id, row.connected_at = ConnectionStatus.ACTIVE, company_id, clock.now()
    row.connected_by_staff_user_id, row.last_error = principal.staff_user_id, None
    audit.record(
        session, "integrations.connection.authorize", row, location_id=row.location_id, changes=audit.diff(row)
    )
    return row, "connected"


def revoke(session: Session, row: ExternalConnection) -> None:
    """Internal (disconnect): revoke at the provider, best effort; the local credentials are wiped regardless."""
    if row.provider != PROVIDER or not row.credentials_ciphertext:
        return
    try:
        _port(session, row.location_id).revoke(credentials(session, row))
    except Exception as exc:  # the provider boundary: disconnecting locally must still succeed
        row.last_error, row.last_error_at = f"revoke failed: {type(exc).__name__}", clock.now()


# --- settings and mappings ---------------------------------------------------------------------------------


def _load(session: Session, principal: Principal, connection_id: UUID, key: str) -> ExternalConnection:
    from app.modules.integrations import service

    row = service._load_connection(session, principal, connection_id)
    authorize(principal, key, location_id=row.location_id)
    return row


def get_connection(session: Session, principal: Principal, connection_id: UUID) -> ExternalConnection:
    return _load(session, principal, connection_id, "integrations.connection.manage")


def update_settings(session: Session, principal: Principal, connection_id: UUID, settings: dict) -> ExternalConnection:
    """Merge-patch of the provider settings we use; null removes a key. Unknown keys are refused."""
    row = _load(session, principal, connection_id, "integrations.connection.manage")
    session.refresh(row, with_for_update=True)  # merge over the stored settings, never a stale sync status
    if row.provider == Provider.GOOGLE_ANALYTICS:
        from app.modules.integrations import analytics

        if row.status != ConnectionStatus.ACTIVE:
            raise Conflict("The connection is disconnected", code="invalid-state-transition")
        merged = {k: v for k, v in (row.settings | settings).items() if v is not None}
        row.settings = analytics.clean(merged)
        row.external_account_id = row.settings["measurement_id"]
        audit.record(
            session, "integrations.connection.update", row, location_id=row.location_id, changes=audit.diff(row)
        )
        session.flush()
        return row
    unknown = set(settings) - SETTINGS_KEYS
    if unknown:
        raise ValidationFailed(f"Unknown setting {sorted(unknown)[0]}", pointer=f"/settings/{sorted(unknown)[0]}")
    merged = dict(row.settings or {})
    for key, value in settings.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    row.settings = merged
    audit.record(session, "integrations.connection.update", row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def _posting_keys(session: Session, row: ExternalConnection) -> set[str]:
    """Posting keys the connection's recent exports carried, so unmapped ones can be listed."""
    keys: set[str] = set()
    totals = session.scalars(
        select(AccountingExport.totals)
        .where(AccountingExport.external_connection_id == row.id)
        .order_by(AccountingExport.business_on.desc())
        .limit(60)
    )
    for total in totals:
        keys |= {line["posting_key"] for line in (total or {}).get("lines", [])}
        keys |= set((total or {}).get("unmapped", []))
    return keys


def get_mappings(session: Session, principal: Principal, connection_id: UUID) -> dict:
    row = _load(session, principal, connection_id, "integrations.connection.manage")
    mappings = (row.settings or {}).get("mappings", [])
    options: dict[str, list] = {"accounts": [], "classes": []}
    unavailable = False
    if row.provider == PROVIDER and row.status == ConnectionStatus.ACTIVE:
        try:
            for option in _port(session, row.location_id).list_options(credentials(session, row)):
                options["accounts" if option.kind == "account" else "classes"].append(
                    {"id": option.id, "name": option.name}
                )
        except Conflict:
            raise
        except Exception:  # the provider boundary: answer anyway, so tokens refreshed above still commit
            options, unavailable = {"accounts": [], "classes": []}, True
    mapped = {m["local_key"] for m in mappings}
    unmapped = [{"local_key": key} for key in sorted(_posting_keys(session, row) - mapped)]
    return {"mappings": mappings, "unmapped": unmapped, "external_options": options, "options_unavailable": unavailable}


def put_mappings(session: Session, principal: Principal, connection_id: UUID, mappings: list[dict]) -> dict:
    """Replace the mapping set. `account_map` (posting key -> account id) and `class_map` are derived from it
    and are what the daily export reads."""
    row = _load(session, principal, connection_id, "integrations.connection.manage")
    session.refresh(row, with_for_update=True)  # merge over the stored settings, never a stale sync status
    seen = set()
    for index, mapping in enumerate(mappings):
        # accounts of every kind share one account_map, so a posting key is unique across them
        slot = ("class" if mapping["kind"] == "revenue_class" else "account", mapping["local_key"])
        if slot in seen:
            raise ValidationFailed("Each key is mapped once", pointer=f"/mappings/{index}/local_key")
        seen.add(slot)
    clean = [{k: m.get(k) for k in ("kind", "local_key", "external_id", "external_name")} for m in mappings]
    account_map = {m["local_key"]: m["external_id"] for m in clean if m["kind"] != "revenue_class"}
    class_map = {m["local_key"]: m["external_id"] for m in clean if m["kind"] == "revenue_class"}
    row.settings = {**(row.settings or {}), "mappings": clean, "account_map": account_map, "class_map": class_map}
    audit.record(
        session, "integrations.sync_mapping.replace", row, location_id=row.location_id, changes=audit.diff(row)
    )
    session.flush()
    return get_mappings(session, principal, connection_id)


# --- sync and retry ----------------------------------------------------------------------------------------


def run_sync(session: Session, principal: Principal, connection_id: UUID, data: dict) -> dict:
    """Queue the export of each day in [from, to] for the connection's location (or the one named). Dates are the
    location's own; the default is its yesterday. The chunked job `sync_accounting_job` posts one day per
    committed chunk, so a failure on a later day never rolls back days already posted, and the connection row
    (`settings.sync`) is its status. Idempotent per day; `retries_failed` re-attempts failed days."""
    from app.modules import platform

    row = _load(session, principal, connection_id, "integrations.sync.run")
    session.refresh(row, with_for_update=True)
    if row.status != ConnectionStatus.ACTIVE:
        raise Conflict("The connection is not active")
    if _live(row):  # a stale one was lost (its message or worker died) and is taken over
        raise Conflict("A sync is already running for this connection", code="sync-in-progress")
    location_id = row.location_id or data.get("location_id")
    if location_id is None:
        raise ValidationFailed("Name the location to sync", pointer="/location_id")
    authorize(principal, "integrations.sync.run", location_id=location_id)
    try:
        today = platform.service.location_today(session, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location", pointer="/location_id") from None
    first, last = data.get("from") or today - timedelta(days=1), data.get("to") or today - timedelta(days=1)
    if last < first or (last - first).days >= MAX_SYNC_DAYS or last >= today:
        raise ValidationFailed(f"Pick up to {MAX_SYNC_DAYS} past days", pointer="/to")
    job: dict[str, Any] = {
        "status": "running", "location_id": str(location_id), "next_on": first.isoformat(),
        "last_on": last.isoformat(), "retries_failed": bool(data.get("retries_failed")), "counts": {},
        "beat_at": clock.now().isoformat(),
    }  # fmt: skip
    row.settings = {**(row.settings or {}), "sync": job}
    audit.record(session, "integrations.sync.start", row, location_id=location_id, changes=audit.diff(row))
    session.flush()
    tenant_id, ident = str(session.info["tenant_id"]), str(row.id)

    def enqueue() -> None:
        from app.modules.integrations.jobs import sync_accounting_job

        sync_accounting_job.send(tenant_id, ident)

    session.info.setdefault("after_commit", []).append(enqueue)
    return _sync_view(row)


def _sync_view(row: ExternalConnection) -> dict:
    job = row.settings["sync"]
    return {
        "status": job["status"], "counts": job["counts"],
        "status_url": f"/api/v1/external-connections/{row.id}/sync",
    }  # fmt: skip


def _is_stale(job: dict) -> bool:
    beat = job.get("beat_at")
    return job.get("status") == "running" and (beat is None or clock.now() - datetime.fromisoformat(beat) > STALE_SYNC)


def _live(row: ExternalConnection) -> bool:
    job = (row.settings or {}).get("sync") or {}
    return job.get("status") == "running" and not _is_stale(job)


def _status(row: ExternalConnection) -> dict:
    job = (row.settings or {}).get("sync") or {}
    keys = ("location_id", "next_on", "last_on", "beat_at")
    return {"status": job.get("status", "idle"), "counts": job.get("counts", {}),
            "retries_failed": bool(job.get("retries_failed")), "is_stale": _is_stale(job),
            **{k: job.get(k) for k in keys}}  # fmt: skip


def get_sync_status(session: Session, principal: Principal, connection_id: UUID) -> dict:
    return _status(_load(session, principal, connection_id, "integrations.sync.run"))


def reset_sync(session: Session, principal: Principal, connection_id: UUID) -> dict:
    """Stop a sync that stopped answering (no chunk for STALE_SYNC), so the connection is usable again."""
    row = _load(session, principal, connection_id, "integrations.sync.run")
    session.refresh(row, with_for_update=True)
    job = (row.settings or {}).get("sync") or {}
    if _live(row):
        raise Conflict("The sync is still working", code="sync-in-progress")
    if job.get("status") != "running":
        raise Conflict("No sync is running", code="invalid-state-transition")
    row.settings = {**row.settings, "sync": {**job, "status": "failed"}}
    audit.record(session, "integrations.sync.reset", row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return _status(row)


def sync_chunk(session: Session, connection_id: UUID) -> bool:
    """One day of a queued sync (internal, the chunked job). Returns True while days remain."""
    from app.core.auth import system_principal
    from app.modules.integrations import service

    row = session.get(ExternalConnection, connection_id, with_for_update=True)
    job = dict((row.settings or {}).get("sync") or {}) if row is not None else {}
    if row is None or job.get("status") != "running":
        return False
    counts = dict(job["counts"])
    job["beat_at"] = clock.now().isoformat()
    rotates = row.provider == PROVIDER and get_settings().integrations.quickbooks_enabled
    if row.status == ConnectionStatus.ACTIVE and rotates and refresh_if_due(session, row):
        row.settings = {**row.settings, "sync": job}
        return True  # the rotated tokens commit on their own before the next chunk posts anything
    if row.status != ConnectionStatus.ACTIVE:
        job["status"] = "failed"
    else:
        day, location_id = date.fromisoformat(job["next_on"]), UUID(job["location_id"])
        existing = session.scalar(
            select(AccountingExport.status).where(
                AccountingExport.external_connection_id == row.id, AccountingExport.location_id == location_id,
                AccountingExport.business_on == day,
            )
        )  # fmt: skip
        if existing == ExportStatus.FAILED and not job["retries_failed"]:
            outcome = ExportStatus.FAILED.value
        else:
            principal = system_principal("integrations.sync")
            outcome = service.export_accounting_day(session, principal, row.id, location_id, day).status
        counts[outcome] = counts.get(outcome, 0) + 1
        job["next_on"] = (day + timedelta(days=1)).isoformat()
        if day >= date.fromisoformat(job["last_on"]):
            job["status"] = "completed"
    job["counts"] = counts
    row.settings = {**row.settings, "sync": job}
    session.flush()
    return job["status"] == "running"


def fail_sync(session: Session, connection_id: UUID) -> None:
    """Dead letter: a chunk kept failing, so the sync stops and a new one may start."""
    row = session.get(ExternalConnection, connection_id, with_for_update=True)
    if row is not None and (row.settings or {}).get("sync", {}).get("status") == "running":
        row.settings = {**row.settings, "sync": {**row.settings["sync"], "status": "failed"}}
        session.flush()


def retry_export(session: Session, principal: Principal, export_id: UUID) -> AccountingExport:
    from app.modules.integrations import service

    authorize(principal, "integrations.sync.run")
    stmt = select(AccountingExport).where(AccountingExport.id == export_id)
    if principal.location_ids is not None:
        stmt = stmt.where(AccountingExport.location_id.in_(principal.location_ids))
    export = session.scalar(stmt)
    if export is None:
        raise NotFound()
    if export.status != ExportStatus.FAILED:
        raise Conflict("Only a failed day can be retried")
    return service.export_accounting_day(
        session, principal, export.external_connection_id, export.location_id, export.business_on
    )


# --- inbound webhook ---------------------------------------------------------------------------------------


def receive_webhook(body: bytes, signature: str) -> int:
    """Verify `intuit-signature`, then store each realm's notification once in the inbound log (routed to its
    tenant by provider_account_lookup). The sync is one-way, so a stored change needs no further processing;
    an unknown realm is kept as `ignored`. Returns the number of new notifications."""
    adapter = connector()
    if not get_settings().integrations.quickbooks_enabled or _simulated_outside_dev(adapter):
        raise PermissionDenied("Invalid signature", code="invalid-signature", status=401)
    if not adapter.verify_webhook(body, signature):
        raise PermissionDenied("Invalid signature", code="invalid-signature", status=401)
    try:
        payload = json.loads(body)
        notifications = payload["eventNotifications"]
    except (ValueError, KeyError, TypeError):
        raise ValidationFailed("Not a QuickBooks notification") from None
    digest, stored = hashlib.sha256(body).hexdigest()[:32], 0
    for index, notification in enumerate(notifications if isinstance(notifications, list) else []):
        realm = str(notification.get("realmId", ""))
        recorded = inbound_webhooks.record(PROVIDER.value, f"{digest}:{index}", realm, "data_change", notification)
        if recorded is not None:
            stored += 1
            inbound_webhooks.finish(recorded[0])
    return stored
