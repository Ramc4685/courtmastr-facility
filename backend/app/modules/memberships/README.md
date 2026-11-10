# memberships

Membership types and plans, sold contracts and their lifecycle, the billing schedule, freezes, suspensions,
renewals, cancellations, sharing and visit counting (build module 5; ADR 0005; data-model-people section 3).
Backend only: the web screens are a separate piece of work. Feature status: `docs/status/05-memberships-packages.md`.

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
has come. Idempotent; a missed day is caught up by the next run. **Nothing schedules it yet** (the kernel has
no scheduler): enqueue it daily per tenant after each location's `membership_renewal_run_time`.

## Not built (by name)

- Autopay and dunning, stored payment methods, `payment_schedule` for single-invoice contracts, account credit
  auto-applied at sale, non-payment suspension: all wait for billing (build module 8). `is_autopay` is stored
  and carried, nothing collects on it.
- Pre-defined billing items as add-ons (`catalog_item`), coupons on a contract.
- `POST /plan-changes` (deferred by ADR 0005's reconciliation): upgrade and downgrade are "renew into another
  plan" (`renews_as_plan_id` on the contract or on a manual renew) or cancel with a reason and sell anew.
- Backdated freezes and suspensions (they start today or later); freeze limits and freeze fees (not in the
  reference). `freeze_resume_invoice_mode` is stored, the schedule always resumes per period.
- MEM-21 reports and `rpt_*` views, MEM-22 API keys, MEM-23 checklist, member card rendering (MEM-19: the
  number lives on `client`; `ensure_member_number` is called at sale).
- Web screens.

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
- **Renewal** never copies add-ons to the successor (the bundled package renews itself, MEM-04). A successor
  that would overlap another membership of the owner is not created; the job reports it in `failed`.
- **Visits.** The daily rule is per client per contract per local day. `depleted` is reported, not enforced
  (`access` decides).
- **API.** Path ids `membership_plan_id`, `membership_share_id`; GET operation ids start with get/list; small
  sub-resources return arrays; added `listUpcomingMembershipRenewals`, `repriceMembershipContract`.
- A zero-priced sale has `invoice_mode = none` and no schedule rows (MEM-06 record-only membership).
