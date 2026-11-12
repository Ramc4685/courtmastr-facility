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

Every row goes through the owning context's import function, so its rules, audit rows, events and plan limits
apply. These are internal (ADR 0009 section 9: no principal; the import command carries the gate):

| Context | Function | Notes |
|---|---|---|
| clients | `service.import_client` (existed), `service.find_by_primary_email`, `households.import_link` | import_client now refuses a new record the duplicate rule pairs with an existing client (409 `possible-duplicate`) |
| engagement | `service.import_consent` | marketing consent with source `import`, actor system, basis express |
| memberships | `service.import_contract` | an existing contract carried over; billing starts at the next bill date |
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
   with its reason; the rest are imported. Status `completed`.
5. `GET /import-jobs/{id}/error-report`: `Row, Outcome, Column, Problem` for every row not imported. Problems are
   plain words and never quote a cell. Every cell is neutralised against formula injection.

Both runs are the chunked job `run_import` (`core.jobs.chunked_actor`): 200 rows per message, each chunk in its own
transaction, cursor on the locked job row. `python -m app.cli run-import --tenant ID --job ID` runs the same chunks
in-process when no worker is running (lanes, operators).

## Row outcomes and idempotency

Every non-blank source row becomes one `import_job_row`: `valid` or `invalid` (dry run), `created`, `updated`,
`skipped` (a duplicate) or `failed`. Row numbers are spreadsheet rows (the header is row 1), not the 1-based data
rows of the data model, so they match what a person sees in the spreadsheet.

- `row_key` is SHA-256 of the type and the row's natural key: clients use the member number, else email and names,
  else names, birth date and mobile; memberships use the client reference, plan and start; balances use the client
  reference, date, direction and amount; products use the SKU.
- A second row with the same key in one job is skipped ("Same as row N").
- Memberships and balances never update, so a key an earlier job created is skipped ("An earlier import added this
  row"). A membership whose owner, plan and start already exist is also skipped. A balance's billing idempotency
  key is the job id plus the natural key.
- Clients and products update: a client matched by member number, or by a single client with the same email and
  names, is updated (email, member number and home location are kept); a product is matched by SKU.
- A retried chunk redoes exactly the rows its rolled-back transaction lost; a duplicate message only waits on
  the row lock and continues from the cursor.

## Plan limits

The commit hits `entitlements.enforce_limit` inside `clients._create`, reported per row as `plan-limit-reached`.
A dry run rolls each row back, so it counts instead: rows that would create a client beyond `limit - usage` at the
start of the check are `invalid` with the same code.

## Retention

Source files and error reports are removed `expires_at` (30 days after the upload) by the hourly purge, through
the new `platform.retention.register_purge` hook. The job and its row outcomes stay as the import's history.

## Assumptions and limits

- Money: two-decimal currencies only (`csvio.money`), no sign, no thousands separator.
- Dates: one format per file (ISO, MM/DD/YYYY or DD/MM/YYYY), chosen by the person, never guessed. "Today" for
  future-date checks is the job location's date.
- Phones: E.164 after removing spaces, dots, dashes and brackets; a number without its country code is refused.
- Possible duplicates are skipped, never merged. Merge them by hand after the import.
- Imported email consent skips double opt-in (the person consented in the old system); the import note names the
  job.
- Imported clients raise `clients.client.created` like any new client, so engagement automations on that trigger
  run for them. Imported memberships converge with reason `import`.
- Imported contracts have no document gate, add-ons, shares or enrolment fee; cancelled contracts are not
  importable. Billing before the next bill date is assumed done by the old system.
- An opening credit is an external payment received now; the as-of date goes into its memo.
- Audit rows carry counts and flags only (no names, emails or cells); the worker's actor is the system principal
  `run_import`, and the job keeps the staff user who submitted it.

Deferred: cancelling a running job; IMP-02 operator-assisted imports (an operator running a file for a tenant);
custom fields, tags and notes on client rows; package balances.
