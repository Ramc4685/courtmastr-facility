"""The clock (kernel): the one process that starts the periodic jobs, one message per tenant per job.

Every job here is an idempotent @tenant_actor that works out "today" per location and catches up missed
days, so a repeated tick, or a scheduler that was down for a while, changes nothing. That is why the cadence
is coarse: checkout holds are reaped every minute, everything dated runs once an hour (a location's day starts
at its own midnight, not UTC's). Runs as fh_platform because it lists every tenant; the work runs as each tenant.
"""

import logging
import time
from collections.abc import Iterable

from sqlalchemy import text

from app.bootstrap import bootstrap
from app.core import inbound_webhooks
from app.core.db.platform import platform_engine
from app.core.jobs import broker

log = logging.getLogger(__name__)
EVERY_MINUTE = ("expire_checkout_holds", "expire_registration_holds", "send_due_messages", "sweep_webhook_deliveries")
EVERY_HOUR = (
    "billing_daily", "run_membership_day", "run_package_day", "sweep_documents", "auto_archive_programs",
    "abandon_stale_drafts", "purge_expired", "purge_files",
    "purge_expired_results", "purge_expired_exports",
    "send_client_task_reminders",
    "send_low_stock_digest",
    "renew_catalog_item_sales",  # billing pre-defined items (BIL-14)
    "run_rental_plan_day",  # rentals: plan activation, expiry and auto-renew (RNT-09)
    "retry_provider_events",  # billing: webhooks stored but never processed (PAY-11)
    "send_billing_digest",  # billing: staff daily digest of failed and due autopay (PAY-08)
    "run_report_schedules",  # reporting: scheduled delivery of saved reports (RPT-01)
    "suspend_past_due_memberships",  # memberships: non-payment suspension and lift (MEM-14)
)  # fmt: skip
# Retention keeps running for a suspended tenant (purges, export expiry, file byte deletion): suspension stops
# the business, not the data-protection clock. Billing and messaging stay with active tenants only.
RETENTION = ("purge_expired", "purge_files", "purge_expired_results", "purge_expired_exports")


def tenants(status: str = "active") -> list[str]:
    with platform_engine().connect() as conn:
        rows = conn.execute(text("SELECT id FROM tenant WHERE status = :status"), {"status": status})
        return [str(row[0]) for row in rows]


def active_tenants() -> list[str]:
    return tenants("active")


def tick_hour() -> int:
    """The hourly round: every dated job for active tenants, the retention jobs for suspended ones, and the
    retention of the global inbound-webhook table, which belongs to no tenant."""
    inbound_webhooks.purge_payloads()
    return enqueue(EVERY_HOUR, tenants("active")) + enqueue(RETENTION, tenants("suspended"))


def enqueue(actor_names: Iterable[str], tenant_ids: Iterable[str]) -> int:
    """Send each named actor once per tenant; returns how many messages went out."""
    tenant_ids = list(tenant_ids)
    for name in actor_names:
        actor = broker.get_actor(name)
        for tenant_id in tenant_ids:
            actor.send(tenant_id)
    return len(tenant_ids) * len(tuple(actor_names))


def main() -> None:  # pragma: no cover - a loop around enqueue
    from app.core import logging as app_logging

    app_logging.configure()
    bootstrap()
    log.info("scheduler started")
    last_hour = None
    while True:
        enqueue(EVERY_MINUTE, active_tenants())
        hour = time.gmtime().tm_hour
        if hour != last_hour:
            tick_hour()
            last_hour = hour
        time.sleep(60)


if __name__ == "__main__":  # pragma: no cover
    main()
