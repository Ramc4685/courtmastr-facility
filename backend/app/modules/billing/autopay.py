"""Autopay collection runs, dunning and billing notices (PAY-09, PAY-08, PAY-07, BIL-22; ADR 0005 section 8).

A run collects, for one location and one business date, every autopay invoice with money due: account credit
first, then the payer's autopay method, off-session. A decline moves the invoice through `dunning_state`
(retry dates come from `domain.dunning.decide`); a failed attempt stays on the autopay-error list until staff
clear it. Every notice is recorded in `billing_notice` before it is sent, so a rerun never notifies twice.
"""

from calendar import monthrange
from datetime import date, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, scope_query, system_principal
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import clients, platform
from app.modules.billing import catalogue, methods, service
from app.modules.billing.domain import dunning
from app.modules.billing.events import PaymentMethodExpiring
from app.modules.billing.models import (
    AutopayAttempt,
    AutopayRun,
    BillingNotice,
    Charge,
    Invoice,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentSchedule,
)
from app.ports import notifications

_SIGN_OFF = "\n\n$facility"
for _key, _subject, _body in (
    ("payment_declined", "Your payment to $facility did not go through",
     "We could not take your payment of $amount.$detail\n\nYou can pay or update your payment method here:\n$link"),
    ("staff_decline_alert", "Declined payment: $client",
     "A payment of $amount from $client was declined ($detail). Receipt $receipt."),
    ("due_reminder", "Invoice $invoice_number is due on $due_on",
     "This is a reminder that $amount is due on $due_on for invoice $invoice_number.\n\nPay here:\n$link"),
    ("past_due_reminder", "Invoice $invoice_number is past due",
     "$amount on invoice $invoice_number was due on $due_on and has not been paid.\n\nPay here:\n$link"),
    ("final_notice", "Final notice for invoice $invoice_number",
     "We were unable to collect $amount for invoice $invoice_number and will not try again automatically."
     "\n\nPlease pay here:\n$link"),
    ("method_expiring", "Your saved card ending $last4 is about to expire",
     "The $brand card ending $last4 that we hold for you expires $expires. Please update it here:\n$link"),
):  # fmt: skip
    notifications.register_template(f"billing.{_key}", subject=_subject, body=_body + _SIGN_OFF)


def money(amount_minor: int, currency: str) -> str:
    # shortcut: assumes a two-decimal currency; use the tenant locale formatter when one exists.
    return f"{amount_minor / 100:,.2f} {currency}"


def portal_link(path: str = "/portal/billing") -> str:
    return f"{get_settings().app.web_base_url}{path}"


def notify(
    session: Session,
    kind: str,
    subject_type: str,
    subject_id: UUID,
    dedupe_key: str,
    *,
    to: str | None,
    data: dict,
    client_id: UUID | None = None,
    location_id: UUID | None = None,
) -> bool:
    """Send a billing notice at most once per (kind, subject, dedupe_key). The log row is inserted first and
    the message goes out only if that insert won, so reruns and catch-up never double-notify. Returns
    whether this call was the first. A missing address still records the notice (nothing to send to)."""
    first = session.execute(
        pg_insert(BillingNotice)
        .values(
            id=new_id(),
            tenant_id=session.info["tenant_id"],
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            dedupe_key=dedupe_key,
            client_id=client_id,
            location_id=location_id,
            sent_at=clock.now(),
        )  # fmt: skip
        .on_conflict_do_nothing()
        .returning(BillingNotice.id)
    ).first()
    if first and to:
        tenant = platform.service.get_tenant(session)
        template = "payment_declined" if kind == "authentication_required" else kind
        notifications.send(session, f"billing.{template}", to, {"facility": tenant.name, **data})
    return bool(first)


def _email_of(session: Session, client_id: UUID | None) -> str | None:
    return clients.service.get(session, client_id).primary_email if client_id else None


# --- declines: notices and dunning -------------------------------------------------------------------------


def _on_payment_state(session: Session, payment: Payment, was: str) -> None:
    """Runs in the transaction that changed a payment's status (service.PAYMENT_HOOKS)."""
    attempt = session.execute(
        select(AutopayAttempt).where(AutopayAttempt.payment_id == payment.id)
    ).scalar_one_or_none()
    if attempt is not None and attempt.status == "processing":  # a bank debit answered after the run
        today = platform.service.location_today(session, payment.location_id)
        _settle_attempt(session, attempt, payment, today)
        _tally(session, session.get(AutopayRun, attempt.autopay_run_id))
    if payment.status == "failed" and was != "failed":
        _notify_decline(session, payment)


def _notify_decline(session: Session, payment: Payment) -> None:
    """PAY-08: tell the payer and alert staff. Only a real decline gets here: an `unknown` outcome never
    notifies (the processor may still have taken the money)."""
    cfg = catalogue.settings_for(session, payment.location_id)
    amount = money(payment.amount_minor, payment.currency)
    needs_payer = payment.failure_category == "authentication_required"
    if cfg.decline_notice_scope == "all_payments" or (
        cfg.decline_notice_scope == "autopay_payments" and payment.origin == "autopay"
    ):
        detail = " Your bank asked for you to confirm it yourself." if needs_payer else ""
        notify(
            session, "authentication_required" if needs_payer else "payment_declined", "payment", payment.id,
            "status:failed", to=_email_of(session, payment.client_id), client_id=payment.client_id,
            location_id=payment.location_id, data={"amount": amount, "detail": detail, "link": portal_link()},
        )  # fmt: skip
    if cfg.decline_alert_email and cfg.decline_alert_mode == "per_event":
        payer = (
            clients.service.display_name(clients.service.get(session, payment.client_id)) if payment.client_id else ""
        )
        notify(
            session, "staff_decline_alert", "payment", payment.id, "status:failed", to=cfg.decline_alert_email,
            location_id=payment.location_id,
            data={"amount": amount, "client": payer or "a walk-in customer", "receipt": payment.receipt_number,
                  "detail": payment.failure_category or "declined"},
        )  # fmt: skip


def _dun(session: Session, invoice: Invoice, attempt: AutopayAttempt, payment: Payment, on: date) -> None:
    """Decide what a decline means for the invoice: retry on a date, wait for a new method, or stop."""
    last_success = session.scalar(
        select(func.max(AutopayAttempt.attempt_no)).where(
            AutopayAttempt.invoice_id == invoice.id, AutopayAttempt.status == "succeeded"
        )
    )
    failed = session.execute(
        select(func.count(), func.min(AutopayRun.business_on))
        .select_from(AutopayAttempt)
        .join(AutopayRun, AutopayRun.id == AutopayAttempt.autopay_run_id)
        .where(
            AutopayAttempt.invoice_id == invoice.id,
            AutopayAttempt.status == "failed",
            AutopayAttempt.attempt_no > (last_success or 0),
        )  # fmt: skip
    ).one()
    cfg = catalogue.settings_for(session, invoice.location_id)
    decision = dunning.decide(
        payment.failure_category, payment.tender_kind, failed[0], failed[1] or on, list(cfg.autopay_retry_offset_days)
    )
    invoice.dunning_state, invoice.next_attempt_on = decision.state, decision.next_attempt_on
    if payment.failure_category in dunning.SUSPENDS and attempt.payment_method_id:
        methods.suspend_method(session, attempt.payment_method_id)
    if decision.state == "exhausted":
        notify(
            session, "final_notice", "invoice", invoice.id, f"attempt:{attempt.attempt_no}",
            to=_email_of(session, invoice.bill_to_client_id), client_id=invoice.bill_to_client_id,
            location_id=invoice.location_id,
            data={"amount": money(invoice.balance_minor, payment.currency), "invoice_number": invoice.number,
                  "link": portal_link()},
        )  # fmt: skip
    session.flush()


def _settle_attempt(session: Session, attempt: AutopayAttempt, payment: Payment, on: date) -> None:
    if payment.status == "succeeded":
        attempt.status = "succeeded"
    elif payment.status in ("failed", "cancelled"):
        attempt.status = "failed"
        attempt.failure_category, attempt.failure_message = payment.failure_category, payment.failure_message
        session.flush()
        _dun(session, service._lock(session, Invoice, attempt.invoice_id), attempt, payment, on)
    else:  # processing, or unknown: never a decline, never retried under another key
        attempt.status = "processing"
    session.flush()


# --- the run -----------------------------------------------------------------------------------------------


def _due_amount(session: Session, invoice: Invoice, business_on: date) -> int:
    """What autopay should collect now: instalments due by the business date that are not yet covered, less
    money a pending bank debit is already holding against the invoice."""
    due = service._int(
        session,
        select(func.coalesce(func.sum(PaymentSchedule.amount_minor - PaymentSchedule.covered_minor), 0)).where(
            PaymentSchedule.invoice_id == invoice.id, PaymentSchedule.due_on <= business_on
        ),
    )
    pending = service._int(
        session,
        select(func.coalesce(func.sum(PaymentAllocation.amount_minor), 0))
        .join(Charge, Charge.id == PaymentAllocation.charge_id)
        .where(Charge.invoice_id == invoice.id, PaymentAllocation.status == "provisional"),
    )
    return max(due - pending, 0)


def _selection(location_id: UUID, business_on: date):
    return (
        select(Invoice)
        .where(
            Invoice.location_id == location_id,
            Invoice.is_autopay,
            Invoice.balance_minor > 0,
            Invoice.status.in_(("open", "partially_paid")),
            Invoice.dunning_state.in_(("none", "retrying")),
            Invoice.due_on <= business_on,
            or_(Invoice.next_attempt_on.is_(None), Invoice.next_attempt_on <= business_on),
        )  # fmt: skip
        .order_by(Invoice.due_on, Invoice.id)
    )


def preview(session: Session, location_id: UUID, business_on: date) -> list[dict]:
    """What a run would try to collect, without side effects."""
    rows = []
    for invoice in session.scalars(_selection(location_id, business_on)):
        due = _due_amount(session, invoice, business_on)
        if due > 0:
            credit = min(service.credit_balance(session, invoice.bill_to_client_id), due)
            rows.append(
                {
                    "invoice_id": invoice.id,
                    "number": invoice.number,
                    "bill_to_client_id": invoice.bill_to_client_id,
                    "due_minor": due,
                    "credit_minor": credit,
                    "has_payment_method": methods.autopay_method(session, invoice.bill_to_client_id) is not None,
                }  # fmt: skip
            )
    return rows


def _run_for(session: Session, location_id: UUID, business_on: date) -> AutopayRun:
    session.execute(
        pg_insert(AutopayRun)
        .values(id=new_id(), tenant_id=session.info["tenant_id"], location_id=location_id, business_on=business_on,
                started_at=clock.now())
        .on_conflict_do_nothing()
    )  # fmt: skip
    return session.execute(
        select(AutopayRun)
        .where(AutopayRun.location_id == location_id, AutopayRun.business_on == business_on)
        .with_for_update()
    ).scalar_one()


def _collect(session: Session, run: AutopayRun, invoice: Invoice) -> AutopayAttempt | None:
    """One attempt on one invoice. The provider key is derived from (invoice, attempt number), so a run that
    dies and is started again charges the same provider payment, never a second one."""
    due = _due_amount(session, invoice, run.business_on)
    if due <= 0:
        return None
    payer = invoice.bill_to_client_id
    attempt = AutopayAttempt(
        autopay_run_id=run.id, invoice_id=invoice.id, attempt_no=invoice.attempt_count + 1, amount_minor=due
    )
    session.add(attempt)
    invoice.attempt_count = attempt.attempt_no
    session.flush()
    attempt.credit_applied_minor = service.spend_credit(session, payer, invoice_id=invoice.id, limit=due)
    remaining = due - attempt.credit_applied_minor
    method = methods.autopay_method(session, payer)
    if remaining == 0:
        attempt.status = "succeeded"  # settled from account credit alone: no provider call
    elif method is None:
        attempt.status, attempt.failure_category = "skipped", "no_payment_method"
        attempt.failure_message = "No payment method on file."
        invoice.dunning_state, invoice.next_attempt_on = "awaiting_method", None
        notify(
            session, "payment_declined", "invoice", invoice.id, f"attempt:{attempt.attempt_no}",
            to=_email_of(session, payer), client_id=payer, location_id=invoice.location_id,
            data={"amount": money(remaining, platform.service.get_tenant(session).currency),
                  "detail": " We have no payment method on file for you.", "link": portal_link()},
        )  # fmt: skip
    else:
        attempt.payment_method_id = method.id
        payment = service.take_payment(
            session, client_id=payer, location_id=invoice.location_id, amount_minor=remaining,
            tender_kind="card" if method.kind == "card" else "bank_debit", payment_method_id=method.id,
            off_session=True, origin="autopay", invoice_id=invoice.id,
            idempotency_key=f"autopay:{invoice.id}:{attempt.attempt_no}",
        )  # fmt: skip
        attempt.payment_id = payment.id
        _settle_attempt(session, attempt, payment, run.business_on)
    session.flush()
    return attempt


def _tally(session: Session, run: AutopayRun) -> None:
    attempts = session.scalars(select(AutopayAttempt).where(AutopayAttempt.autopay_run_id == run.id)).all()
    run.selected_count = len(attempts)
    run.succeeded_count = sum(a.status == "succeeded" for a in attempts)
    run.failed_count = sum(a.status in ("failed", "skipped") for a in attempts)
    paid = service._int(
        session,
        select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(
            Payment.status == "succeeded",
            Payment.id.in_(select(AutopayAttempt.payment_id).where(AutopayAttempt.autopay_run_id == run.id)),
        ),
    )
    run.collected_minor = paid + sum(a.credit_applied_minor for a in attempts)
    if run.finished_at is not None:
        run.status = "completed_with_errors" if run.failed_count else "completed"
    session.flush()


def run_location(session: Session, location_id: UUID, business_on: date | None = None) -> AutopayRun:
    """Collect everything due at a location for a business date (default: today on the wall there). There is
    one run row per location and date: calling again resumes it, and an invoice already handled is no longer
    selected (paid, pending, waiting for its retry date or for a new method). Because selection is "due on or
    before", one run also catches up any date that was missed."""
    business_on = business_on or platform.service.location_today(session, location_id)
    run = _run_for(session, location_id, business_on)
    run.status, run.finished_at = "running", None
    for invoice in session.scalars(_selection(location_id, business_on).with_for_update(skip_locked=True)).all():
        _collect(session, run, invoice)
    run.finished_at = clock.now()
    _tally(session, run)
    audit.record(
        session, "billing.autopay.run", run, location_id=location_id,
        changes={"selected": [None, run.selected_count], "collected_minor": [None, run.collected_minor]},
    )  # fmt: skip
    return run


def _retry_waiting(session: Session, client_id: UUID) -> None:
    """A payer saved a new autopay method: collect, now, every invoice that was waiting for one or for its
    next retry date (ADR 0005 section 8)."""
    waiting = session.scalars(
        select(Invoice)
        .where(
            Invoice.bill_to_client_id == client_id,
            Invoice.is_autopay,
            Invoice.balance_minor > 0,
            Invoice.status.in_(("open", "partially_paid")),
            Invoice.dunning_state.in_(("retrying", "awaiting_method", "exhausted")),
        )  # fmt: skip
        .order_by(Invoice.due_on, Invoice.id)
        .with_for_update()
    ).all()
    for invoice in waiting:
        invoice.dunning_state, invoice.next_attempt_on = "none", None
        run = _run_for(session, invoice.location_id, platform.service.location_today(session, invoice.location_id))
        _collect(session, run, invoice)
        _tally(session, run)


service.PAYMENT_HOOKS.append(_on_payment_state)
methods.AUTOPAY_METHOD_HOOKS.append(_retry_waiting)


# --- staff commands ----------------------------------------------------------------------------------------


def start_run(session: Session, principal: Principal, data: dict) -> AutopayRun | list[dict]:
    """Run autopay now for one location (PAY-09), or preview it with `is_dry_run`."""
    location_id = data["location_id"]
    authorize(principal, "billing.autopay.run", location_id=location_id)
    try:
        today = platform.service.location_today(session, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    business_on = data.get("business_on") or today
    if business_on > today:
        raise ValidationFailed("Autopay cannot run for a future date.", pointer="/business_on")
    if data.get("is_dry_run"):
        return preview(session, location_id, business_on)
    return run_location(session, location_id, business_on)


def list_runs(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "billing.payment.read")
    return paginate(
        session, scope_query(select(AutopayRun), principal, AutopayRun.location_id), query, id_column=AutopayRun.id,
        sort_fields={"business_on": AutopayRun.business_on}, default_sort="-business_on",
        filter_fields={"location_id": AutopayRun.location_id, "status": AutopayRun.status},
    )  # fmt: skip


def get_run(session: Session, principal: Principal, run_id: UUID) -> AutopayRun:
    run = service._get(session, AutopayRun, run_id)
    authorize(principal, "billing.payment.read", location_id=run.location_id)
    return run


def list_attempts(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Filter `status=failed&is_error_open=true` is the autopay-error queue staff work through (PAY-06)."""
    authorize(principal, "billing.payment.read")
    stmt = select(AutopayAttempt).join(AutopayRun, AutopayRun.id == AutopayAttempt.autopay_run_id)
    stmt = scope_query(stmt, principal, AutopayRun.location_id)
    open_only = query.filters.pop("is_error_open", None)
    if open_only is not None:
        cleared = AutopayAttempt.error_cleared_at
        stmt = stmt.where(cleared.is_(None) if str(open_only).lower() == "true" else cleared.is_not(None))
    return paginate(
        session, stmt, query, id_column=AutopayAttempt.id,
        sort_fields={"created_at": AutopayAttempt.created_at}, default_sort="-created_at",
        filter_fields={
            "status": AutopayAttempt.status, "invoice_id": AutopayAttempt.invoice_id,
            "autopay_run_id": AutopayAttempt.autopay_run_id,
        },
    )  # fmt: skip


def _attempt(session: Session, principal: Principal, attempt_id: UUID) -> tuple[AutopayAttempt, AutopayRun]:
    attempt = service._lock(session, AutopayAttempt, attempt_id)
    run = session.get(AutopayRun, attempt.autopay_run_id)
    authorize(principal, "billing.autopay.run", location_id=run.location_id)
    return attempt, run


def clear_error(session: Session, principal: Principal, attempt_id: UUID) -> AutopayAttempt:
    """Dismiss a failed attempt from the error queue. It changes nothing about what the invoice owes."""
    attempt, run = _attempt(session, principal, attempt_id)
    if attempt.status not in ("failed", "skipped") or attempt.error_cleared_at is not None:
        raise Conflict("There is no open error on this attempt.", code="autopay-error-not-open")
    attempt.error_cleared_at, attempt.error_cleared_by_staff_user_id = clock.now(), principal.staff_user_id
    audit.record(session, "billing.autopay.run", attempt, location_id=run.location_id, changes={"error_cleared": True})
    session.flush()
    return attempt


def retry_attempt(session: Session, principal: Principal, attempt_id: UUID) -> AutopayAttempt:
    """Try a failed invoice again now, whatever its retry date or dunning state (staff decided to)."""
    attempt, _ = _attempt(session, principal, attempt_id)
    if attempt.status not in ("failed", "skipped"):
        raise Conflict("Only a failed attempt can be retried.", code="autopay-attempt-not-failed")
    invoice = service._lock(session, Invoice, attempt.invoice_id)
    if invoice.status not in ("open", "partially_paid") or invoice.balance_minor <= 0:
        raise Conflict("Nothing is owed on this invoice any more.", code="invoice-not-payable")
    invoice.dunning_state, invoice.next_attempt_on = "none", None
    run = _run_for(session, invoice.location_id, platform.service.location_today(session, invoice.location_id))
    again = _collect(session, run, invoice)
    if again is None:
        raise Conflict("Nothing is due on this invoice yet.", code="invoice-not-payable")
    _tally(session, run)
    audit.record(
        session, "billing.autopay.run", again, location_id=invoice.location_id, changes={"status": [None, again.status]}
    )
    return again


# --- the daily job -----------------------------------------------------------------------------------------


def _remind(session: Session, location_id: UUID, today: date, offsets: list[int]) -> int:
    """BIL-22: reminders before (negative offset) and after (positive) an invoice's due date."""
    currency, sent = platform.service.get_tenant(session).currency, 0
    for offset in offsets:
        due_on = today - timedelta(days=offset)
        for invoice in session.scalars(
            select(Invoice).where(
                Invoice.location_id == location_id,
                Invoice.due_on == due_on,
                Invoice.balance_minor > 0,
                Invoice.status.in_(("open", "partially_paid")),
            )  # fmt: skip
        ):
            sent += notify(
                session, "due_reminder" if offset <= 0 else "past_due_reminder", "invoice", invoice.id,
                f"offset:{offset}:{due_on.isoformat()}", to=_email_of(session, invoice.bill_to_client_id),
                client_id=invoice.bill_to_client_id, location_id=location_id,
                data={"amount": money(invoice.balance_minor, currency), "invoice_number": invoice.number,
                      "due_on": due_on.isoformat(), "link": portal_link()},
            )  # fmt: skip
    return sent


def _warn_expiring(session: Session, today: date) -> int:
    """PAY-07: warn before a stored card expires (a card is good through the last day of its month)."""
    cfg, sent = catalogue.settings_for(session), 0
    cards = select(PaymentMethod).where(PaymentMethod.kind == "card", PaymentMethod.status == "active")
    if cfg.card_expiry_notice_scope == "autopay_methods":
        cards = cards.where(PaymentMethod.is_autopay)
    for card in session.scalars(cards):
        expires = date(card.exp_year, card.exp_month, monthrange(card.exp_year, card.exp_month)[1])
        if (expires - today).days in cfg.card_expiry_notice_days:
            first = notify(
                session, "method_expiring", "payment_method", card.id,
                f"lead:{(expires - today).days}:{expires.isoformat()}", to=_email_of(session, card.client_id),
                client_id=card.client_id,
                data={"brand": card.brand or "", "last4": card.last4, "expires": f"{card.exp_month:02d}/{card.exp_year}",
                      "link": portal_link()},
            )  # fmt: skip
            if first:
                events.publish(
                    session, PaymentMethodExpiring(payment_method_id=card.id, client_id=card.client_id), card.id
                )
            sent += first
    return sent


def daily(session: Session) -> dict:
    """The per-tenant daily pass, safe to run any number of times a day: mark invoices past due as the
    calendar moves, send reminders and expiry warnings, and start each location's autopay run once its local
    run time has passed. A location is visited when it has an open invoice."""
    now, system = clock.now(), system_principal("billing.daily")
    summary = {"past_due": 0, "reminders": 0, "expiry_notices": _warn_expiring(session, now.date()), "runs": 0}
    location_ids = session.scalars(
        select(Invoice.location_id).where(Invoice.status.in_(("open", "partially_paid", "payment_pending"))).distinct()
    ).all()
    for location_id in location_ids:
        location = platform.service.get_location(session, system, location_id)
        local = now.astimezone(ZoneInfo(location.time_zone))
        today = local.date()
        overdue = session.scalars(
            select(Invoice.id).where(
                Invoice.location_id == location_id,
                Invoice.due_on < today,
                Invoice.past_due_since_on.is_(None),
                Invoice.balance_minor > 0,
                Invoice.status.in_(("open", "partially_paid")),
            )  # fmt: skip
        ).all()
        for invoice_id in overdue:
            service.refresh_invoice(session, invoice_id)
        summary["past_due"] += len(overdue)
        cfg = catalogue.settings_for(session, location_id)
        summary["reminders"] += _remind(session, location_id, today, list(cfg.due_reminder_offset_days))
        if local.strftime("%H:%M") >= location.autopay_run_time and session.scalar(
            _selection(location_id, today).with_only_columns(func.count()).order_by(None)
        ):
            run_location(session, location_id, today)
            summary["runs"] += 1
    return summary
