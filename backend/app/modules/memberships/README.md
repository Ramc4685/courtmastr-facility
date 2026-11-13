# memberships

Membership types and plans, sold contracts and their lifecycle, the billing schedule, freezes, suspensions,
renewals, cancellations, sharing and visit counting (build module 5; ADR 0005; data-model-people section 3).
Staff and portal screens live in `web/src/features/` (`docs/status/README.md` module 5). Feature status:
`docs/status/05-memberships-packages.md`.

| File | What it holds |
|---|---|
| `domain/schedule.py` | Pure arithmetic: the schedule with proration and tail rules, due dates, discounts, re-dating after a freeze, `effective_status`, the cancel credit. No database, no clock |
| `models.py` | The eleven tables of section 3 (deviations listed in its docstring) |
| `service.py` | Staff commands (authorize, audit, events), the daily job `run_daily`, and the internal interface |
| `handlers.py` | `documents.document.accepted`: a contract waiting for its document may start |
| `router.py` | Staff, portal and public routes |

**How it fits together.** A sale snapshots the plan onto the contract and generates the whole schedule
(`billing_schedule_period`) in one transaction. A period becomes a charge only through `billing.service`, with
origin `(memberships, billing_schedule_period, period id, charge_sequence)`, so billing twice is impossible.
The stored status changes in one function, `_converge`, which moves it to the date-derived
`domain.effective_status`; every command converges first, and entitlement reads use the function directly, so
a late job never admits or refuses anyone wrongly. One live contract per owner is the exclusion constraint
`ex_membership_contract_term_overlap` (409 `membership-overlap`); one successor per contract is
`uq_membership_contract_previous`.

**Internal interface (no permission check, ADR 0009 section 9).** `eligibility(session, client_id, on=None)`,
`is_member(...)`, `record_visit(session, client_id=, check_in_id=, location_id=)` for `access`;
`status_of(session, contract_id)` and `addon_grants(session, contract_id)` for `packages`.

**The daily job.** `run_daily(session)` / the actor `run_membership_day`: per live contract, in its own
savepoint, converge the status, create the successor when `renew_on` has come, bill periods whose `bill_on`
has come. Idempotent; a missed day is caught up by the next run. `app/scheduler.py` enqueues it hourly per
tenant (`EVERY_HOUR`).

## Imported contracts (Phase 8 I1, MEM-23)

`service.import_contract` (internal, for `imports`) carries over an existing contract: plan by active name, the
plan's terms snapshotted as at a sale, an optional price per period, dues scheduled only from the next bill date
(none: record-only), no enrolment fee, add-ons, shares or document gate, and an expired contract does not renew.
The same owner, plan and start is returned as existing. A given status must match the dates (422
`status-mismatch`). Refused rather than adjusted: a start other than the plan's
fixed start (`plan-fixed-start`) and a first bill (due date less the billing lead) before the next bill date
(`bills-before-next-bill-date`). Activation converges with reason `import`, and so does the later start of an imported
upcoming contract (`sales_channel` import), so engagement sends no "membership started" automation for either.

## Not built (by name)

- Account credit auto-applied at sale. Since integration an invoice billed for an autopay contract is an
  autopay invoice, and billing's autopay run collects it from the client's stored method.
- Coupons on a contract.
- `POST /plan-changes` (deferred by ADR 0005's reconciliation): upgrade and downgrade are "renew into another
  plan" (`renews_as_plan_id` on the contract or on a manual renew) or cancel with a reason and sell anew.
- Backdated freezes and suspensions (they start today or later); freeze limits and freeze fees (not in the
  reference).
- MEM-21 reports and `rpt_*` views, MEM-22 API keys, MEM-23 checklist, member card rendering (MEM-19: the
  number lives on `client`; `ensure_member_number` is called at sale).

## Billing settings that take effect (Phase 9 chip D)

- **Non-payment suspension (MEM-14, Q13).** `suspend_past_due_memberships` (hourly in `app/scheduler.py`,
  idempotent `@tenant_actor`) runs `sweep_past_due`: when billing's `membership_suspend_after_days` is set,
  an active contract whose invoice has been past due that many days gets a suspension with reason
  `non_payment`; it is lifted when the invoice is paid or voided (the `billing.invoice.paid` / `voided`
  handlers, and the sweep as a backstop). One automatic suspension per contract and invoice; a suspension
  staff remove by hand stays removed. Manual suspension is unchanged.
- **Payment capture (MEM-05).** `payment_method_capture = required` refuses a staff autopay sale without a
  stored method (`payment-method-required`); `hidden` and `optional` change only the screen.
- **Online card save (MEM-05).** `online_card_save_mode`: `always` keeps the card that pays now, `ask` keeps
  it only when the member ticks "Save this card", `when_nothing_due` keeps it only when nothing is due now.
  An autopay contract always keeps it (its later dues need a method). The processor saves it with the charge
  (billing's "save during payment"), so a timeout stays recoverable. The quote returns `card_save_mode` and
  `is_autopay` so the portal knows whether to ask.
- **Freeze resume (MEM-05).** `freeze_resume_invoice_mode`: `per_period` (default) bills each period as
  before; `single` bills every period left on the resume day as one invoice; `deferred` holds those periods
  until billing's `invoice_deferred` releases them.
- **Autopay default (BIL-17).** `membership_plan.is_autopay_default` is nullable: null follows billing's
  setting for the sales channel. The quote returns the resolved `is_autopay`.

## Assumptions and deviations

- **Schema.** `coupon_id`, `payment_method_id`, `catalog_item_id` are not created (their tables do not exist);
  `membership_visit.check_in_id` has no FK (the `access` context owns `check_in`). Added:
  `membership_contract.end_on_before_cancel`; `billing_schedule_period.charge_sequence`, `.pre_freeze`,
  `.cancelled_reason`. Events: suspension end emits `memberships.contract.activated` with
  `reason = "unsuspended"` (data model), not a separate `.unsuspended`.
- **Proration** is offered for monthly and yearly cadences only. A stub divides by the days of the full period
  that ends (first stub) or starts (last stub) at the 1st. A discount applies after proration; a flat discount
  is capped at the period amount.
- **Due date** with `payment_due_day`: the first such day on or after the period start. The enrolment fee is
  due at the sale even when the membership starts later.
- **Freeze** follows ADR 0005 section 4 (the first withheld period is due on the resume date, the rest step
  by cadence) rather than the data model's "shift by the frozen days". Withheld rows stay `withheld` until the
  freeze ends. Removing a freeze that has begun ends it as of yesterday. A freeze does not move a suspension
  scheduled after it.
- **Cancel.** Billed periods that start after the cancel date are reversed whether paid or not (paid money
  becomes account credit); ADR 0005 names only the unpaid ones. The partial credit is "reverse the period,
  bill the used part again, move the payment across". A future-dated cancel is stored as `cancel_reason` on a
  live contract (the table check ties `cancelled_on` to status `cancelled`); the job closes it on the day.
  Undo uses `memberships.contract.cancel` (the matrix has no separate key). A cancelled upcoming successor is
  detached (`previous_contract_id = NULL`) so the term can be renewed again.
- **Refund on cancel** returns the released money per payment: record-only tenders as an external refund,
  processed ones to the original method (needs an Idempotency-Key). The portal opt-out refunds only processed
  payments of the cancelled successor; other money stays account credit.
- **Renewal** never copies package add-ons to the successor (the bundled package renews itself, MEM-04); it
  carries pre-defined item add-ons that recur, billed with the successor's dues, and drops one-off ones. A successor
  that would overlap another membership of the owner is not created; the job reports it in `failed`.
- **Visits.** The daily rule is per client per contract per local day. `depleted` is reported, not enforced
  (`access` decides).
- **API.** Path ids `membership_plan_id`, `membership_share_id`; GET operation ids start with get/list; small
  sub-resources return arrays; added `listUpcomingMembershipRenewals`, `repriceMembershipContract`.
- A zero-priced sale has `invoice_mode = none` and no schedule rows (MEM-06 record-only membership).

## Derived client alerts (CLI-20, phase 10 chip E)

`GET /clients/{client_id}/system-alerts` (`client_alerts`) is staff only and gated on `clients.client.read`. Memberships is the lowest layer allowed to read billing and documents, so it owns these alerts. Each alert also needs its owner's read key:
- `balance_due` (`billing.invoice.read`): the open balance plus uninvoiced charges; shown as danger when past due.
- `membership_expiring` within 14 days, or `membership_expired` (`memberships.contract.read`).
- `waiver_missing` (`documents.document.read`): only when the documents settings require a waiver for check-in or booking.

"Today" is the client's home-location day. Assumption: 14 days counts as "expiring soon" (`EXPIRING_SOON_DAYS`).

## Agreement binding (DOC-11, Phase 14 C2)

`PUT /membership-contracts/{id}/agreement {client_document_id}` binds an issued agreement to the contract
(`memberships.contract.update`, plus read reach on the document). The document must be a live document of the
contract's owner (not voided or deleted); a contract still waiting on its gating document keeps that one.
Erasure keeps both: contracts are financial records and signed documents are retained as evidence.
Assumption: one bound document per contract (rebinding replaces it, audited).
