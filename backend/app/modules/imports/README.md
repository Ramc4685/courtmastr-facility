# imports (Phase 8 I1: IMP-01, IMP-02, MEM-23)

CSV imports of clients and households, memberships, opening balances and POS products. Staff screen: Settings >
Import data (`web/src/features/imports/`).

## Placement and boundaries

`data-model-core` 2.6 puts `import_job` under platform, but platform (L0) may not import clients, memberships,
billing or pos (overview section 2). The importer therefore lives in its own context `imports`, above everything
it writes to, with two import-linter contracts: it may call platform, clients, memberships, billing, pos and
engagement only, and no context may import it. The permission keys stay `platform.import_job.read` (Admin,
Manager) and `platform.import_job.run` (Admin; flags `D +`, so step-up), as in `rbac-matrix.md` 6.1. Both are
tenant-wide keys; a job also belongs to a location, and a job at a location outside the caller's set is 404.

Running a check or a commit also needs **every location** (403 `all-locations-required`, at the router dependency
and again in `start_dry_run` / `start_commit`): rows match and update clients by member number or email wherever
those clients are, and the worker runs as the system principal, so a location-scoped admin could otherwise reach
clients outside their set. A commit also authorizes the keys of the staff commands the type's writes stand for
(`service.KIND_KEYS`: clients `clients.client.create`, `.update`, `clients.consent.update`; memberships
`memberships.contract.sell`; balances `billing.charge.create`, `billing.payment.take`; products
`pos.product.manage`, `pos.inventory.adjust`). Before every chunk the worker checks that the submitter is still an
active staff user with the run key, every location and (for a commit) those keys; otherwise the job stops as
`failed` with a plain-words `stop_reason` (step-up is not re-checked off-request).

Every row goes through the owning context's import function, so its rules, audit rows, events and plan limits
apply. These are internal (ADR 0009 section 9: no principal; the import command carries the gate):

| Context | Function | Notes |
|---|---|---|
| clients | `service.import_client` (existed), `service.find_by_primary_email`, `households.import_link` | import_client now refuses a new record the duplicate rule pairs with an existing client (409 `possible-duplicate`); its `client.created` event carries `source: "import"` and `import_job_id` |
| engagement | `service.import_consent`; handlers `on_client_created`, `on_contract_activated` | marketing consent with source `import`, actor system (GDPR rules below); the two automation handlers skip import-sourced events |
| memberships | `service.import_contract`; `_converge` | an existing contract carried over; billing starts at the next bill date; an imported contract activates with reason `import`, also when an upcoming one starts later |
| billing | `service.post_opening_balance`, `service.tax_ids_by_code` | owed: a charge (source `imports`/`opening_balance`) on an invoice; credit: an external payment (account credit) |
| pos | `catalogue.import_product` | create or update by SKU; a stock count is a `set` movement |

## Flow

1. `POST /import-jobs` {kind, location_id}: status `new`.
2. `PUT /import-jobs/{id}/source`: the raw CSV (UTF-8 with or without a BOM, at most 10 MB and 20,000 rows),
   stored through `platform.files` with purpose `import_source` (scanned). Columns are auto-matched by our key or
   label, without case or punctuation. Status `uploaded`. A new upload replaces the file and clears results.
3. `POST /import-jobs/{id}/dry-runs` {column_mapping, date_format}: checks every row. Each row is applied in a
   savepoint that is always rolled back, and any after-commit hooks it queued are dropped, so nothing reaches the
   database or the outside world. Status `validated`, or `needs_review` when a row has a problem.
4. `POST /import-jobs/{id}/commits`: applies the rows. A row that fails now (a plan limit, a clash) is `failed`
   with its reason; the rest are imported. Status `completed`. Upload, check and commit load the job with a row
   lock, and the check records the file it checked: a commit of any other file is 409 `check-stale`.
5. `GET /import-jobs/{id}/error-report`: `Row, Outcome, Column, Problem` for every row not imported, and for
   imported rows that carry a warning ("Imported with a warning"; in a dry run "Would import with a warning").
   Problems are plain words and never quote a cell. Every cell is neutralised against formula injection.

Both runs are the chunked job `run_import` (`core.jobs.chunked_actor`): each chunk in its own transaction, cursor
on the locked job row. Chunk size is per type (`Kind.chunk_rows`, `service.chunk_rows`): 200 rows for products and
clients, but 20 for memberships and balances, and for clients when member numbers are generated on creation. Those
rows take a per-tenant counter (invoice, receipt, member number) through `platform.next_number`, a row lock held to
the end of the transaction; at 200 rows a chunk held it for seconds, back to back, so front-desk payments waited
and card payments hit the 500 ms `lock_timeout` in billing's `_initiate`. At 20 rows the lock is held well under a
second per chunk (`test_chunk_size_per_kind_keeps_counter_locks_short`). A row that raises anything other than a
refusal (a bug) is rolled back to its savepoint and `failed` with code `unexpected`; only the exception's class
name is logged, never values, and the job carries on. `python -m app.cli run-import --tenant ID --job ID` runs the same chunks
in-process when no worker is running (lanes, operators). A chunk that exhausts its retries dead-letters, and the
`on_dead_letter` hook ends the job as `failed` (shown as "Stopped"); committed chunks keep their rows, and a new
import of the same file recognises them.

## Row outcomes and idempotency

Every non-blank source row becomes one `import_job_row`: `valid` or `invalid` (dry run), `created`, `updated`,
`skipped` (a duplicate) or `failed`. Row numbers are spreadsheet rows (the header is row 1), not the 1-based data
rows of the data model, so they match what a person sees in the spreadsheet.

- `row_key` is a keyed MAC (`core.crypto.mac`, not a plain hash, so member numbers and emails cannot be guessed
  back from it) of the type and the row's natural key: clients use the member number, else email and names,
  else names, birth date and mobile; memberships use the client reference, plan and start; balances use the client
  reference, date, direction and amount; products use the SKU.
- A second row with the same key in one job is skipped ("Same as row N").
- Memberships and balances never update, so a key an earlier job created is skipped ("An earlier import added this
  row"). A membership whose owner, plan and start already exist is also skipped. A balance's billing idempotency
  key is the resolved client, as-of date, direction and amount, never the job id or how the file names the client,
  so the same opening balance posts once per tenant however it arrives (a second job, or a file naming the client
  by email instead of member number); a repeat is skipped with "Skipped: this opening balance was already posted"
  (`already-posted`).
- Clients and products update: a client matched by member number, or by a single client with the same email and
  names, is updated; its primary email, member number and home location are kept, and a file email the client
  does not have is added as a secondary address (primary only when the client had none). A product is matched by
  SKU.
- A retried chunk redoes exactly the rows its rolled-back transaction lost; a duplicate message only waits on
  the row lock and continues from the cursor. A crash mid-chunk rolls back that chunk's rows, their outcomes and
  the cursor together, so a resumed commit neither duplicates nor skips a row (`test_chunk_retry_never_duplicates`).

## What a dry run cannot leak

Each row runs in a savepoint that is always rolled back, so everything transactional goes with it: the outbox rows
`events.publish` wrote (subscribers never see them), consent and audit rows, and per-tenant counters such as
member and invoice numbers (`platform.next_number` is a locked row, so the number returns; numbering stays
gapless). Emails and queued jobs are `after_commit` hooks; the engine drops any the row added. No import path
writes to file storage, takes a rate-limit token (Redis) or uses a database sequence. The only files a run writes
are the job's own problem report, after the rows. Checked by `test_a_dry_run_leaks_nothing_outside_its_transaction`
(member-number counter, outbox, consent rows, mailbox) and the per-type dry-run tests (record counts).

## Messages imports do and do not send

- Not sent: "new client" automations (`clients.client.created` carries `source: "import"`, which engagement's
  handler skips); "membership started" automations (`memberships.contract.activated` with reason `import`, also
  when an imported upcoming contract reaches its start date); verification emails (imports skip double opt-in);
  household confirmation requests (links are made directly); notices for periods before the next bill date (those
  periods are not created).
- Still sent, as for any member: billing from the next bill date on (invoices, receipts, failed-payment notices),
  auto-renewal notices and renewals, and campaigns or automations on later events (bookings, renewals). Other
  subscribers to `client.created` (webhooks, reporting) still receive the event, marked as an import.

## Plan limits

The commit hits `entitlements.enforce_limit` inside `clients._create`, reported per row as `plan-limit-reached`.
A dry run rolls each row back, so it counts instead: rows that would create a client beyond `limit - usage` at the
start of the check are `invalid` with the same code.

## Retention

Source files and error reports are removed `expires_at` (30 days after the upload) by the hourly purge, through
the new `platform.retention.register_purge` hook (`import_job_files`); the row outcomes (row keys, problems) go 30
days after that (`import_job_rows`). The job itself, with its counts, stays as the import's history. A job stuck in
`validating` or `importing` with no progress for `imports.stalled_minutes` (config, default 60) is marked failed
by the same hourly purge (as `platform.tenant_export` does for stalled exports), so its file expires.

Erasure: `imports` registers a data subject handler. Erasing a client deletes the `import_job_row` rows that point
at the client or at their contracts, charges or payments, and removes at once the source files and error reports
of those jobs (they hold the client's cells), instead of waiting for expiry; a running job keeps its file until it
ends and the hourly purge removes it at `expires_at`. Rows that failed or were skipped carry no entity, so a file
that named the client only in such a row is not found this way; it expires within the 30-day window, which we
accept: the job holds no cell values, only the file does, and that file is gone at `expires_at`. The export side
returns nothing: a row holds no personal data.

## Assumptions and limits

- Money: two-decimal currencies only (`csvio.money`), no sign, no thousands separator.
- Dates: one format per file (ISO, MM/DD/YYYY or DD/MM/YYYY), chosen by the person, never guessed. "Today" for
  future-date checks is the job location's date.
- Phones: E.164 after removing spaces, dots, dashes and brackets; a number without its country code is refused.
- Possible duplicates are skipped, never merged. Merge them by hand after the import.
- Marketing consent. Outside GDPR mode an imported opt-in skips double opt-in (the person consented in the old
  system) and is recorded with basis `import`. In GDPR mode (PLT-16) an opt-in counts as express only with its
  evidence, the `consent_date` and `consent_source` columns: the consent event gets basis `express`, that date as
  `occurred_at` (start of day at the job's location) and the source text in its note. Without both, the client is
  imported not subscribed and the row carries the warning `consent-evidence-missing`. Opt-outs are always recorded.
  An import never overrides a choice made here: an opt-in for a topic the client opted out of (any address,
  however recent the file's consent date) is withheld with the warning `consent-withheld` ("Consent withheld: the
  client opted out here"); an address already subscribed is left alone. Email consent applies to the client's
  primary email only, so for an existing client whose file email is new (added as secondary) the opt-in is not
  imported and the row carries `consent-withheld`.
  Because GDPR mode treats `import` like an implied basis, switching GDPR mode on later stops marketing to clients
  imported without evidence, and switching it off writes them an opt-out (T2's rule for unproven opt-ins).
- Imported contracts have no document gate, add-ons, shares or enrolment fee; cancelled contracts are not
  importable. Billing before the next bill date is assumed done by the old system. A row is refused, never
  adjusted, when its first bill (due date less the tenant's billing lead) would fall before the next bill date
  (`bills-before-next-bill-date`) or when the plan has a fixed start date other than the file's
  (`plan-fixed-start`).
- An opening credit is an external payment received now, on the tender "Opening balance" (created disabled, so
  the desk never offers it; the deposits report lists it under that label, apart from money taken on the import
  day); the as-of date goes into its memo, the import job into its external reference, and the submitting staff
  user's id into its audit row. Refunding it is an external hand-back, never to a card. One opening balance, owed
  or credit, is at most `imports.max_opening_balance_minor` (config, default 10,000,000 minor units, 100,000.00
  in the account currency): above it the row fails with `amount-too-large`.
- Reading cells: each is stripped and normalised to Unicode NFC (so names and emails typed with combining accents
  match the composed form), and the apostrophe our own writer puts before a formula character is removed, so the
  downloaded template's example row (`+13095550101`) passes its own check.
- Audit rows carry counts and flags only (no names, emails or cells); the worker's actor is the system principal
  `run_import`, and the job keeps the staff user who submitted it.

- POS products follow the catalogue's bounds: SKU (also the product ID) at most 60 characters, at most 20 tax
  codes, price at most 999,999,999.99, stock at most 1,000,000.

Deferred: cancelling a running job; restarting a stopped (`failed`) job in place; IMP-02 operator-assisted imports (an operator running a file for a tenant);
custom fields, tags and notes on client rows; package balances.
