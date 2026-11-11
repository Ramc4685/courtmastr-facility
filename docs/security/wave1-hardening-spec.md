# Wave 1 hardening spec

Security review of the wave 1 modules (platform, clients and households, resources, scheduling, rentals,
documents, memberships, packages, billing, pos, the programs slice) at `6fc504d` on
`security/wave1-hardening`. Input: the 25-item security backlog plus a sweep of every file under
`backend/app/modules/` for patterns A to H. This file is the work order for three fix batches that run in
parallel on disjoint files, after a small shared batch 0.

Paths are relative to `backend/app/`. "Test" names the regression test that must fail before the fix and
pass after it. Every fix keeps the house rules: out of scope is `NotFound` (404), never 403; "today" is
`platform.service.location_today`; one `audit.record` per mutated aggregate.

## 1. What the sweep found

31 findings. Most of the code is disciplined: every `L`-scoped key I traced passes the record's location,
and the scoped loaders (`rentals._scoped`, `scheduling._load`, `packages._load`, `memberships._load`,
`documents.load_document`, `clients.service.load`) are used almost everywhere. The holes cluster in three
places: money that can be pointed at the wrong person, online checkout that hands over the goods before
payment is secured, and sibling paths that skip a gate the main path applies.

| Pattern | Count | Findings |
|---|---|---|
| A. `authorize` without the record's location | 4 | M-02, M-03, M-04, S-07 |
| B. bare `session.get` past the scoped loader | 4 | P-01, P-02, P-03, P-08 |
| C. gate missing on a sibling path or privileged flag | 9 | M-05, M-06, M-12, P-06, S-01, S-02, S-03, S-04, S-05 |
| D. online entitlement without secured payment | 3 | M-08, M-09, M-10 |
| E. portal schema or portal input leaks or over-trusts | 6 | M-13, P-04, P-05, P-10, P-11, S-06 |
| F. evidence or ledger immutability | 2 | P-07, P-09 |
| G. tender ownership and per-tender permission | 2 | M-01, M-11 |
| H. injection into a provider query | 1 | M-07 |

| Batch | Count | Files it owns (nobody else edits them) |
|---|---|---|
| 0 shared | 6 pieces | `core/auth/deps.py`, `core/auth/permissions.py`, `core/auth/__init__.py`, `core/idempotency.py`, new `modules/billing/checkout.py`, new `backend/tests/test_location_scope.py`, `backend/tests/test_portal_schemas.py`, `backend/tests/known_open/*.py` |
| money | 13 | `modules/billing/**` (except `checkout.py`), `modules/pos/**`, `modules/packages/service.py`, `modules/memberships/service.py`, `adapters/stripe_connect.py`, `tests/known_open/money.py` |
| people | 11 | `modules/clients/**`, `modules/documents/**`, `modules/engagement/**`, `modules/packages/{router,schemas}.py`, `modules/memberships/{router,schemas}.py`, `tests/known_open/people.py` (no migration) |
| space | 7 | `modules/scheduling/**`, `modules/resources/**`, `modules/rentals/**`, `modules/programs/**`, `modules/platform/**`, `tests/known_open/space.py` |

`packages/service.py` and `memberships/service.py` hold both checkout and non-checkout code, so the split is
by file, not by topic: the service files go to money, their routers and schemas to people. New tests go in
new files (`<module>/tests/test_hardening.py`, or `test_checkout_hardening.py` and `test_portal_schema.py`
where two batches share a tests directory) so test files never collide either.

Not touched by any batch: `backend/openapi.json`, `web/src/api/schema.d.ts`, `CLAUDE.md`,
`docs/dev/module-playbook.md`. The Land phase regenerates the first two once (`make openapi web-api`), runs
`make web-check` (portal screens lose fields in M-13, P-11, S-06) and adds section 7 to the last two.

### Backlog status

| # | Status | Where |
|---|---|---|
| 1 | open | M-01 (wrong payer), M-02 (target location) |
| 2 | open for the payer check; the recording location is already checked by `_location_in_scope` | M-01 |
| 3 | **done**: merged as `6fc504d`. Left over: dropping `facilityhub_fixauthz` and `facilityhub_test_fixauthz` needs the owner's approval; `session.established_by` not started, see section 6 | - |
| 4 | open | M-07 |
| 5, 6 | open | M-04 |
| 7 | open for the permission; the location half is by design, see 18 | M-05 |
| 8 | open | P-06 |
| 9 | open | P-07 |
| 10 | open | P-04 |
| 11 | open | P-02 |
| 12 | open | S-01 |
| 13 | open | S-02 |
| 14 | open | S-03 |
| 15 | open | S-04 |
| 16 | open, low: neither key accepts `own` reach today, so the fix is consistency | P-01 |
| 17 | open | P-03 |
| 18 | **not a defect**: `billing.invoice.read`, `billing.invoice.send` and `billing.payment.read` are `C` (client-following) keys; rbac-matrix 3.1 says the key at any permitted location suffices. Batch 0 locks that in a test instead of changing it | section 6 |
| 19 | open | P-08 |
| 20 | open | P-09 |
| 21 | open | S-05 |
| 22 | open. **Partly closed already**: `PortalPackageBuy` has no `invoice_mode` field, so the client cannot send one. The plan default still opens the hole | M-08 |
| 23 | **Partly closed already**: a stored method of another client is refused by `billing.service.take_payment` (`method.client_id == client_id`), and the sale's client cannot change while a leg is captured. Per-tender permission and the scoped client load are open | M-11 |
| 24 | open | M-09 |
| 25 | open | P-11 |

## 2. Batch 0: shared pieces, built first

One commit, `feat(security): shared guards for wave 1 hardening`. It must leave `make test` green: tests
that the three batches will turn green are listed in `tests/known_open/<batch>.py` and run as
`xfail(strict=True)`, so a batch that fixes one must delete its entry and a batch that forgets fails.

**0.1 `core/auth/deps.py` `require`.** Add `dependency.keys = keys` before `return dependency`. The
generated tests read a route's router key from it. One line, no behaviour change.

**0.2 `core/auth/permissions.py` `authorize_tenant_wide(principal, key)`.** `authorize(principal, key)`, then
`PermissionDenied(required=key)` unless `principal.kind == "system"` or `principal.location_ids is None`.
For writes to a tenant-wide row (`location_id IS NULL`) under a location-scoped key. Export it from
`core/auth/__init__.py`. `pos.service.put_settings` already does this inline; S-04 is the first caller, money
may switch POS over.

**0.3 `core/idempotency.py`.** `KEY_PATTERN = r"^[A-Za-z0-9_.:\-]{1,255}$"` and `pattern=KEY_PATTERN` on the
`Idempotency-Key` header of the `idempotency` dependency. All twelve module routers mount it on their staff
and portal routes, which then answer 422 to any other character. Anonymous routers (the pay link) do not
mount it: M-07 covers that one.

**0.4 `modules/billing/checkout.py` (new) `secure_online_checkout`.** The one rule for every portal
checkout: *an entitlement with a non-zero total exists only once payment is secured.*

```python
SECURED = ("succeeded", "processing")

def secure_online_checkout(
    session, *, client_id, location_id, total_minor, invoice, idempotency_key,
    method_token=None, payment_method_id=None, tender_kind="card",
    must_pay_now=True, on_account_ok=False,
) -> Payment | None:
```

Called inside the sale's transaction, after the sale wrote its rows; every refusal raises without
`persist`, so the entitlement rolls back with it.

| Case | Result |
|---|---|
| `total_minor <= 0` | `None` |
| `on_account_ok` and no method given | `None` (the plan explicitly sells on account) |
| invoice with a balance | `take_payment(amount=invoice.balance_minor, invoice_id=..., origin="portal")`; returns it when `status in SECURED` |
| ... status `failed`, `cancelled`, `requires_action` | cancel a `requires_action` payment, then `Conflict(code="payment-failed")` |
| ... status `unknown` or `initiated` | `DomainError(503, code="provider-unavailable")`, as `pos.sales._settle_leg` does. The `initiated` payment row survives the rollback (it was committed by `_initiate`); a retry with the same key replays it, and money that did go through lands as account credit |
| nothing due now, `must_pay_now` | `Conflict(code="payment-failed")`: a paid-in-full sale produced no invoice |
| nothing due now, not `must_pay_now` | a chargeable method must be on file: `methods.attach_method(..., is_autopay=True)` with `method_token`, else an existing `methods.autopay_method`, else `ValidationFailed(code="payment-method-required", pointer="/method_token")` |

Also export `is_secured(payment) -> bool`. Test: `billing/tests/test_checkout.py` (one case per row, with
`FakeProvider` outcomes).

**0.5 `backend/tests/test_location_scope.py` (new, generated).** Reuses `_ID_ROUTES` and `_BODIES` from
`tests/test_isolation.py`. Fixture: `populate(client, tenant)` (rows at location Main), a second location,
and `add_staff(tenant, "admin", location_ids=[other])`, so a refusal is about scope, never about a missing
key. For every staff route with an id parameter:

- resolve each `{x}_id` to a table (default: the table named `x`; a small `_TABLES` override map for
  `contract`, `package`, `document`, `rental` and the like; an unresolved name fails the test, so a new
  route cannot slip through);
- the route is **location-bound** when the first id's table is `location` or has a `location_id` column,
  and either its router key (from 0.1) has `Scope.LOCATION` or it has no key (configuration reads); or when
  its operationId is in `LOCATION_BOUND_WRITES = {"markInvoicePaid", "cancelPayment"}` (M-04);
- assert the other-location admin gets `404 not-found`, and the owner gets anything but 404 for the same
  call (so the 404 is scope, not a bad fixture);
- routes under a `C` or `T` key are collected into one extra test that asserts the set equals a reviewed
  snapshot, so a key that changes scope, or a new client-following route, is a visible diff. This is where
  backlog 18 is recorded as intended behaviour.

**0.6 `backend/tests/test_portal_schemas.py` (new, generated).** Walks `ROUTES` from `tests/test_security.py`.
A route is *portal* when its path starts with `/portal/` or `/public/`, *staff* when it depends on
`require`. Two assertions per portal route, over its `response_model` and every model nested in it:

1. no model is also reachable from a staff route's `response_model`, except the names in
   `PORTAL_SAFE_SHARED`, each with a one-line reason: `PageInfo`, `FacilityHoursDay`, `InvoiceDocument`,
   `DocumentLine`, `DocumentInstalment` (the printed invoice the client receives anyway), `BillingSummary`,
   `PaymentMethodOut`, `SetupIntentOut`, `EmergencyContactOut`, `EmergencyContactsOut`,
   `RelationshipTypeOut`, `RelationshipOut`, `PreferenceOut`, `Preferences`, `StandingOut`,
   `ContractQuoteOut`, `QuotePeriodOut`, `DocumentRequirementOut`, `DocumentRequirementList`, `Quote`,
   `QuoteLine`;
2. no field name matches `(_staff_user_id$|^internal_|^actor_|^memo$|^note$|^void_reason$)`. This one also
   catches a leak in a schema that is portal-only.

Known open at batch 0: money `/portal/invoices`, `/portal/payments` (GET and POST); people
`/portal/client-packages/{package_id}/ledger`, `/portal/package-series/{series_id}/auto-renew-opt-out`, the
four `/portal/client-documents` routes; space the four `/portal/rentals` routes.

## 3. Batch money

Commit per finding group is fine; subject `fix(billing): ...`, `fix(pos): ...` and so on.

**M-01 (G, high). `billing/service.py` `_plan`, reached from `allocate`, `take_payment` and `spend_credit`.**
Exploit: `POST /payments/{B's payment}/allocations {"invoice_id": A's}` or
`POST /clients/{B}/account-credit/apply {"allocations": [A's charge]}` settles client A's debt with client
B's money; nothing compares the payer with the target. Fix, once, in `_plan` after the targets are loaded:
each target charge must satisfy `charge.client_id == client_id`, or its invoice's
`bill_to_client_id == client_id`, or the two clients have a live relationship
(`clients.households.relationships_of(session, client_id, live_only=True)`); otherwise
`ValidationFailed(code="payer-mismatch", pointer="/allocations")` (or `/invoice_id`). A payment with no
client (walk-in) may only target charges with no client. Put the "payer or live relative" set in one private
function and make `desk.reassign_invoice_payer` use it too. Test: `billing/tests/test_hardening.py`
`test_money_never_pays_a_strangers_item`: allocate, take-with-allocations, take-with-invoice and credit
apply against another client are 422; a parent paying a linked child's charge still works; POS and portal
pay suites stay green.

**M-02 (A). `billing/service.py` `allocate_payment`.** Exploit: a manager scoped to location A applies a
location A payment to charges at location B, which `billing.payment.reallocate` (`L`) should forbid. Fix:
before `allocate`, load the explicit charges (or the invoice) with `_get(..., pointer=...)` and
`authorize(principal, "billing.payment.reallocate", location_id=target.location_id)` for each; a
location-limited principal must name targets (422 on the automatic "oldest first" mode). Test: same file,
`test_reallocate_checks_each_target_location` (404).

**M-03 (A). `billing/desk.py` `refund_account_credit`.** Exploit: `billing.refund.create` (`L`, `$`) is
checked with no location, so a manager at A refunds credit that sits on payments taken at B. Fix: pass
`location_ids=principal.location_ids` to `service.refund_credit`, which filters the payments it draws on
when the set is not None; an amount above the in-scope credit is the existing `refund-exceeds-unapplied`.
Test: `test_credit_refund_stays_inside_the_callers_locations`.

**M-04 (A). `billing/desk.py` `mark_invoice_paid`, `cancel_payment`; `billing/service.py`
`confirm_payment_at_desk`.** Exploit: front desk at A marks an invoice of B as paid elsewhere (a record-only
payment for the whole balance, no money) or cancels B's pending payment. `billing.payment.take` is `C`, but
these write to another location's books rather than collect from a client, which rbac-matrix 3.1 reserves
for `L`. Fix: `authorize(principal, "billing.payment.take", location_id=invoice.location_id)` in
`mark_invoice_paid`; the existing `desk._payment(session, principal, payment_id, "billing.payment.take")`
loader in `cancel_payment`; the same `authorize(..., location_id=payment.location_id)` on the loaded row in
`confirm_payment_at_desk`. Test: the two `LOCATION_BOUND_WRITES` cases of 0.5 leave `known_open/money.py`.

**M-05 (C). `billing/documents.py` `send_receipt` and its route in `billing/router.py`.** Exploit: anyone
with the read key `billing.payment.read` emails a receipt to any address. Fix: gate both with
`billing.invoice.send` (the same key `send_invoice` uses). No location: `C` key. Test:
`test_sending_a_receipt_needs_the_send_key` (a role with read but not send gets 403).

**M-06 (C, high). `billing/service.py` `create_invoice` (staff command).** Exploit: front desk invoices
client A's items with `bill_to_client_id` = an unrelated client B and `is_autopay: true`; the next autopay
run charges B's stored card (`autopay._collect` charges the payer's autopay method).
`reassign_invoice_payer` enforces "someone on the invoice or a relative", the create path does not. Fix:
apply the M-01 payer set in `create_invoice` when `bill_to_client_id` is given (422 `payer-not-related`);
internal callers of `create_invoice_for_charges` are unchanged. Test:
`test_an_invoice_cannot_be_billed_to_a_stranger`.

**M-07 (H, high). `adapters/stripe_connect.py` `find_payment`; `Idempotency-Key` headers in
`billing/router.py` and `pos/router.py`.** Exploit: the Stripe Search query is
`f"metadata['fh_key']:'{idempotency_key}'"` and the key carries the caller's header, including on the
anonymous pay-link route. A key such as `x' OR status:'succeeded` makes the reconciliation of an `unknown`
payment adopt someone else's succeeded intent. Fix, three layers: (1) in `find_payment`, escape `\` and `'`
in the key, and return `None` unless `found[0]["metadata"]["fh_key"] == idempotency_key` exactly; (2)
`pattern=KEY_PATTERN` (0.3) on `RequiredKey` in both routers, which covers `pay_invoice_by_link`; (3) the
core header from 0.3. Test: `billing/tests/test_stripe.py` `test_find_payment_cannot_be_steered`: the
recorded request carries the escaped key, a hit with other metadata is ignored; the pay-link route answers
422 to a key with a quote.

**M-08 (D, high). `packages/service.py` `portal_buy`, `sell`, `_check_plan`.** Exploit: a plan with
`online_sale_mode = "paid_in_full"` and `default_invoice_mode = "deferred"` raises no invoice, the gate
tests only `invoice is not None`, and the client gets the package without paying or sending a card. Fix:
`portal_buy` passes `invoice_mode="single"` to `sell` for a priced plan and replaces its payment block with
`secure_online_checkout(total_minor=package.price_minor, invoice=invoice, must_pay_now=True,
on_account_ok=plan.online_sale_mode == "balance_allowed", ...)`; `_check_plan` refuses `paid_in_full`
together with `default_invoice_mode == "deferred"`. Test: `packages/tests/test_checkout_hardening.py`
`test_paid_in_full_plan_is_never_sold_unpaid`: 409 `payment-failed` and no `client_package` row, with and
without a token; `balance_allowed` still sells on account.

**M-09 (D, high). `memberships/service.py` `portal_buy`, `_portal_sale`.** Exploit: a future `start_on` (or
a `deferred` plan default) bills nothing at the sale, so a member signs up with no card; on the start date
the contract goes active and the first invoice has nothing to charge. The client also chooses `is_autopay`
and an unbounded `start_on`, past or future. Fix: `_portal_sale` drops the client's `is_autopay` (the
contract is autopay whenever its schedule total is above zero) and clamps `start_on` to today through
today + `ONLINE_START_WINDOW_DAYS = 30` at the location (422 outside; a constant with a `shortcut:` comment,
no migration); `portal_buy` calls `secure_online_checkout(total_minor=sum of the schedule,
invoice=invoice, must_pay_now=False, ...)`, so whatever is due now is paid and a sale with nothing due now
stores the payment method as the owner's autopay method. Test:
`memberships/tests/test_checkout_hardening.py` `test_future_start_needs_a_payment_method`,
`test_portal_cannot_turn_autopay_off_or_backdate`.

**M-10 (D). `packages/service.py` `portal_buy` and `memberships/service.py` `portal_buy`: status
`unknown` counts as paid.** Exploit: a processor timeout leaves the payment `unknown`; the sale stands, and
if the payment later resolves to failed nothing takes the entitlement back. Fix: both use the helper, whose
`unknown` row is a 503 that rolls the sale back. Test: one case in each checkout test file with the fake
provider timing out: 503, no package or contract, and the same key retried after the provider recovers
sells exactly once.

**M-11 (G). `pos/sales.py` `add_tender`, `create_sale`, `update_sale`.** Exploit: a role granted
`pos.sale.create` but not the billing keys still takes payments, spends a client's account credit and
leaves a pay-later invoice; the attached client is not loaded through the reach-aware loader. Fix: in
`add_tender`, `authorize(principal, key, location_id=sale.location_id)` with `billing.payment.take` for a
payment leg, `billing.credit.apply` for `account_credit`, `billing.invoice.create` for `pay_later`; attach
the client with `clients.service.load(session, principal, client_id, "clients.client.read")` before
`require_active`. Test: `pos/tests/test_hardening.py` `test_each_tender_needs_its_billing_key`, plus the
regression the backlog asked for, `test_another_clients_stored_card_is_refused` (already 422
`payment-method-not-usable`, now pinned).

**M-12 (C). `memberships/service.py` `_sell`.** Exploit: `share_client_ids` on a staff sale covers other
clients without `memberships.contract.share` (manager and above), and `sold_by_staff_user_id` credits the
sale to anyone without `memberships.contract.edit_sold_by` (the commission flag `W`). Fix: on the staff
channel, `authorize(principal, _SHARE, location_id=location_id)` when the list is not empty and
`authorize(principal, _SOLD_BY, location_id=location_id)` when `sold_by_staff_user_id` is given and is not
the caller. Test: `memberships/tests/test_checkout_hardening.py`
`test_sale_cannot_carry_what_the_seller_may_not_do` (front desk: 403 on both, plain sale still 201).

**M-13 (E). `billing/router.py` portal routes, `billing/schemas.py`.** Exploit: `/portal/payments` returns
the staff `PaymentOut` and `PaymentDetail` (`memo`, `external_reference`, `failure_message`, refund
`reason`), `/portal/invoices` the staff `InvoiceOut` (`void_reason`, `dunning_state`, `attempt_count`,
`next_attempt_on`). Fix: `PortalInvoiceOut`, `PortalPaymentOut`, `PortalPaymentDetail` (with
`PortalAllocationOut`, `PortalRefundOut`) without those fields. Test: the money rows leave
`known_open/money.py` for 0.6.

## 4. Batch people

**P-01 (B, low). `clients/service.py` `disable_client`, `enable_client`, `assign_owners`.** Exploit: none
with today's catalogue (the keys do not accept `own`), but the three commands are the only client writes
that skip the loader, so a later `own` grant would silently reach every client. Fix: replace
`authorize` + `session.get` with `load(session, principal, client_id, "<key>")`. Test:
`clients/tests/test_hardening.py` `test_every_client_command_goes_through_the_loader` (a principal with the
key at reach `own` gets 404 for a client it does not own).

**P-02 (B). `clients/activity.py` `create_task`, `update_task`.** Exploit: a coach (`clients.task.manage`
at reach `own`) creates a task on any client id, which confirms the client exists and attaches text to a
record outside the coach's reach; `update_task` also lets an `own` caller hand the task to another staff
user, which `create_task` forbids. Fix: `service.load(session, principal, data["client_id"],
"clients.activity.write")` with `NotFound` mapped to the existing 422 at `/client_id`; in `update_task`
apply the create rule (an `own` caller may only keep itself as assignee). Test:
`test_tasks_respect_client_reach`.

**P-03 (B). `clients/households.py` `create_relationship`, `approve_relationship`, `end_relationship`.**
Exploit: the second party of a staff link is read with `session.get`, and approve and end load neither
party, so reach is never checked on the people being linked. Fix: load `other_client_id` with
`service.load(..., "clients.client.read")` (422 at `/other_client_id` on `NotFound`); approve and end load
both `from_client_id` and `to_client_id` the same way (404). Test:
`test_relationship_commands_check_both_parties`.

**P-04 (E, high). `clients/households.py` `portal_request_relationship`, `decide_relationship`,
`portal_end_relationship`, `authority`.** Exploit: every system type is portal-selectable, including
`parent_of` and `guardian_of`. A stranger requests guardianship of a minor who has a login; the minor
clicks the emailed link; `authority()` now returns `guardian`, so the stranger can edit the child's profile
and sign the child's waivers. The minor can equally end a real guardian's link. Fix: when the requested
type (either side) `is_guardianship` and the ward is a minor, create the row `pending` with no token and no
email, so only staff `approve_relationship` activates it; `decide_relationship` refuses to accept such a
row; `portal_end_relationship` answers 409 when the caller is the minor ward of a guardianship link. In
`authority`, take the minor test's date from `platform.service.location_today(target.home_location_id)`,
not `clock.now().date()`. Test: `clients/tests/test_hardening.py`
`test_guardianship_of_a_minor_needs_staff`.

**P-05 (E). `clients/households.py` `portal_update_client` (`PortalClientUpdate.birth_on`).** Exploit: a
minor edits their own birth date in the portal and becomes an adult: new documents stop requiring a
guardian signature and guardians drop to delegates. Fix: the portal may set `birth_on` only while it is
empty; a change is 422 `field-locked` at `/birth_on` (staff edit it). Test:
`test_portal_cannot_change_a_recorded_birth_date`.

**P-06 (C, high). `clients/merge.py` `_repoint_access`, `_repoint_relationships`, `precheck`, `_reasons`.**
Exploit: a portal user creates a dependent that shows up as a duplicate of a real client (same last name
and birth date, or a shared email); staff merge the pair; the manager access row and the acting-rights
relationship move
to the real client and the portal user now controls that person's account. Fix: non-primary access rows of
the loser are revoked, not moved; live relationships of the loser whose type grants acting rights end
instead of re-pointing; `precheck` returns both lists as `review` items so staff re-grant on purpose; a
client with `created_via == "portal"` matches as a duplicate on email only through a verified address.
Test: `test_merge_never_carries_acting_rights`.

**P-07 (F). `clients/merge.py` `merge`.** Exploit: `client_merge.backfilled_fields` stores the loser's
values (birth date, phones, address, member number) and the table is append-only, so erasure cannot clear
them: an erased person's data survives. Fix: store field names only (`{field: True}`). No migration and no
change to `_erase_clients`: the app role cannot update the table, and only demo tenants hold rows written
before this fix (`make lane-db` and `make seed` recreate them). Test:
`test_merge_log_holds_no_personal_values` (merge, erase, then no value of the erased client appears in
`client_merge`).

**P-08 (B). `documents/service.py` `list_statuses`.** Exploit: a coach with `own` reach posts any client
ids and reads their waiver and consent status. Fix: skip ids the caller cannot load, exactly as
`memberships.service.list_standings` does (`clients.service.load` in a try, `NotFound` skipped). Test:
`documents/tests/test_hardening.py` `test_bulk_status_respects_reach`.

**P-09 (F, high). `documents/service.py` `upload_paper_scan`, `clear_paper_signed`.** Exploit: front desk
uploads a new "paper scan" onto an already accepted document; the scan is replaced and, for a document with
no on-screen body, `content_sha256` is rewritten: the signed evidence now describes a different file. Fix:
`upload_paper_scan` takes only `pending` documents under `_COLLECT`. Replacing the scan of a decided
document is a separate branch that needs `load_document(..., _VOID)` (location-checked), keeps
`content_sha256`, and audits old and new file ids. `content_sha256` is written by `issue()` and by the
pending paper branch only. `clear_paper_signed` (accepted back to pending) also needs `_VOID`. Test:
`test_decided_evidence_is_immutable` (front desk: 409 or 403, hash and acceptance rows unchanged).

**P-10 (E). `documents/service.py` `portal_submit`, `public_decide`.** Exploit: the caller picks
`signer_role`. A manager or guardian identity signs role `client` on someone else's document, and whoever
holds an emailed link signs as the client even when it went to a guardian's address. The evidence row then
says the client signed. Fix: in `portal_submit`, role `client` only when the caller's own client is
`doc.client_id`, otherwise the role must be `guardian`; in `public_decide`, force `guardian` when
`doc.requires_guardian`, and allow `client` only when a recipient address is a verified address of the
document's client. Test: `test_signer_role_is_derived_not_chosen`.

**P-11 (E). `packages/router.py`, `packages/schemas.py`, `documents/router.py`, `documents/schemas.py`.**
Exploit: the portal package ledger returns the staff `CreditLedgerEntryOut` (staff `note`, `actor_type`,
`actor_id`, and other clients' `client_id` to anyone the package is shared with); portal documents return
`ClientDocumentOut` and `DocumentAcceptanceOut` (`witnessed_by_staff_user_id`, `source_type`, `source_id`,
`deleted_at`, other signers' `signer_client_id`); the series opt-out returns the staff `PackageSeriesOut`.
Fix: `PortalCreditLedgerEntryOut` (no `note`, `actor_*`, `client_id`, `source_*`),
`PortalClientDocumentOut`, `PortalDocumentAcceptanceOut`, `PortalPackageSeriesOut`. Test: the people rows
leave `known_open/people.py` for 0.6.

## 5. Batch space

**S-01 (C). `programs/service.py` `_enroll`, `create_enrollment`, `promote_waitlist_entry`,
`promote_waitlist`.** Exploit: a session that needs a package refuses a free registration without
`scheduling.enrollment.free_book`, but a waitlist entry promoted by staff, or by the automatic promotion,
is enrolled with `pricing = "free"`: waitlist then promote is a free seat. Fix: move the check into
`_enroll(..., may_free)`: no package and `not seat["allows_free_booking"]` needs `may_free`. Staff paths
compute it with `authorize(principal, FREE, location_id=seat["location_id"])` (replacing the location-blind
`principal.has(FREE)`); the automatic promotion passes `False` and leaves the entry waiting. Test:
`programs/tests/test_hardening.py` `test_waitlist_is_not_a_free_seat`.

**S-02 (C). `scheduling/service.py` `_template`, `update_session`, `_apply_patch`.** Exploit: anyone who
can create or edit a session (front desk, a coach on their own calendar) sets `allows_free_booking: true`
and then registers people free, which is exactly what `free_book` exists to restrict. Fix: one private
check, `authorize(principal, "scheduling.enrollment.free_book", location_id=...)` when the request sets the
flag to true and it was not already true, called from the three staff paths. Test:
`scheduling/tests/test_hardening.py` `test_free_booking_flag_needs_free_book`.

**S-03 (C). `scheduling/service.py` `add_rule`.** Exploit: a new pass on a series copies the first rule's
template, so occurrences added by front desk inherit `override_policy: true` (blackouts ignored) and are
attributed to the original creator. Fix: `template["override_policy"]` is true only when
`data.get("override_policy")` and `authorize(principal, OVERRIDE, location_id=series.location_id)` pass,
else false; `template["created_by_staff_user_id"] = str(staff_user_id)`. Test:
`test_added_pass_does_not_inherit_override`.

**S-04 (C). `scheduling/service.py` `update_settings`.** Exploit: with `location_id` None,
`authorize(..., location_id=None)` checks nothing, so a manager limited to one location rewrites the
tenant-wide scheduling defaults for all of them. Fix: `authorize_tenant_wide(principal, LOCATION)` (0.2)
when `location_id is None`. Test: `test_tenant_wide_settings_need_every_location`.

**S-05 (C). `rentals/service.py` `extend_rental`.** Exploit: `data["resources"]` is not checked against the
rental type's resources and `scheduling.service.add_rule` is called without the principal, so a rental is
extended onto any resource of the location with no resource or `own` check. Fix: pull the loop in
`_rental_template` into `_check_type_resources(session, rental_type_id, resources)` and call it here; pass
`principal=principal` to `add_rule`. S-03 closes the inherited override. Test:
`rentals/tests/test_hardening.py` `test_extend_stays_on_the_types_resources`.

**S-06 (E). `rentals/router.py`, `rentals/schemas.py`.** Exploit: portal rental routes return the staff
`RentalOut` (`parties` with other clients' ids, `charge_ids`, `invoice_ids`) and `RentalCancelResult`. Fix:
`PortalRentalOut` without them, `PortalRentalCheckout`, `PortalRentalCancelResult`. Also import
`billing.checkout.is_secured` in `confirm_portal_rental` instead of the inline status tuple: rentals already
holds the slot as `tentative` until payment is secured, so this is one rule in one place, no behaviour
change. Test: the space rows leave `known_open/space.py` for 0.6.

**S-07 (A, low). `platform/staff.py` `_set_locations`, `assign_locations`.** Exploit: an admin limited to
location A replaces a colleague's whole location set, which silently removes that colleague's access to B
and C, locations the admin has no say over. Fix: for a limited editor, locations of the target outside
`principal.location_ids` are kept as they are, and a target with `has_all_location_access` is refused
(`self-escalation`, as today for granting it). Test: `platform/tests/test_hardening.py`
`test_limited_editor_cannot_remove_foreign_locations`.

## 6. Decisions and things left alone

- **Client-following keys stay client-following (backlog 18, half of 7).** Passing a location to the `C`
  read and send keys would break the documented case of staff at site B serving a client whose invoice was
  raised at site A. Only the two writes in M-04 are treated as location-bound. If the owner wants invoices
  private per location, that is a catalogue change (make the keys `L`), not a code patch.
- **`find_payment` amount check (backlog 4).** The exact `fh_key` match in M-07 already ties the intent to
  one payment row. Comparing amounts needs the amount on the provider port; not needed to close the hole.
- **`session.established_by` (backlog 3).** The merged fix reads the sign-in audit event, which is
  append-only. A column would be faster, not safer. Not in this pass.
- **The two stale databases** from the merged branch are still on the shared Postgres; dropping them is an
  irreversible action waiting for the owner.
- **Seen, by design, unchanged:** `T`-keyed catalogue writes that touch location-owned rows (POS equipment
  items, reservation types); coupon and tender lists readable by any signed-in staff; `set_waiver_override`
  under the collect-signature key; rental cancellation reversing charges into account credit under
  `rentals.booking.cancel`.
- **House-rule drift, not security:** `clock.now().date()` is still used in `billing/documents.py:434`,
  `billing/router.py:538`, `billing/methods.py:263`, `clients/activity.py:171,230`,
  `memberships/service.py:715`. Fixes in this pass must not add more; the batch that owns a file may clean
  its own lines.

## 7. Security rules for new modules

For `docs/dev/module-playbook.md` and `CLAUDE.md` (wave 2 builders).

- **Scope comes from the key.** An `L` key is always `authorize(principal, key,
  location_id=record.location_id)` on the loaded record; a `C` key needs no location but does need the
  client loaded through `clients.service.load`; a write to a tenant-wide row uses `authorize_tenant_wide`.
- **Every id from a request goes through the context's scoped loader**, including ids in the body and
  bulk-by-ids lists, which get the same reach filter as the list endpoint. No bare `session.get` in a
  command.
- **Gates live in the shared inner function.** If two paths reach the same effect (create and promote,
  create and "add more", single and series), the check sits where they meet, not in one caller.
- **A privileged flag is a permission, wherever it is set.** `override_*`, `allows_free_*`,
  complimentary, price and commission fields need their own key on create, on generic update and on bulk
  edit; a copied template never carries one over.
- **Money goes only where its owner points it.** A payment, stored method or account credit is used for
  the client it belongs to (or a live relative); each tender type checks its own billing key.
- **Online checkout secures payment first.** Every portal sale with a non-zero total ends in
  `billing.checkout.secure_online_checkout` inside the sale's transaction; never decide "paid" from
  `invoice is not None` or from a client-supplied mode, date or autopay flag.
- **Portal routes have portal schemas and derived inputs.** No response model shared with a staff route, no
  staff notes or actor ids, no other client's id; the payer, signer role, verification state and anything
  age-related are derived on the server, never taken from the client.
- **Evidence is append-only.** Signed-document hashes, ledger rows and decided records are never rewritten;
  a correction is a new row under a void-level key. Logs of a change store field names, not personal values.
- **Nothing a caller sends is formatted into a provider query.** Validate at the edge, escape at the sink,
  and check that what came back is what was asked for.
- **Three generated guards must stay green without edits to their allow-lists:** `test_isolation.py`
  (tenant), `test_location_scope.py` (location), `test_portal_schemas.py` (portal). Adding a route to an
  allow-list is a reviewed decision with a one-line reason.
