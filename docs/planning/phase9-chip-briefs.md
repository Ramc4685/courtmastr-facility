# Phase 9 chip briefs, batch 1 (start each as its own session, Opus, own worktree cut from claude/phase9-wave1-711cdd)

**Since Phase 8 merged (2026-11-12, `e6975b7`):** the chain is `1081 → 12xx → 1272 → 1301 … 1310` (head 1310); rebuild lane databases from scratch, never upgrade old ones. Two new gates, `make typecheck` (mypy; a new file that only fails on Optional narrowing may join the per-file debt list in `backend/pyproject.toml`, anything else is fixed) and `make boundaries` (import-linter). Any test that builds a staging or production config needs the `deploy_secrets` fixture (`billing/tests/test_stripe.py`). Use `platform.files.load/remove/download_url` and `core.jobs.chunked_actor` as shipped; `+` keys return `403 step-up-required` for un-elevated sessions.

Shared background for both: FacilityHub (display name Courtmastr Facility): clean-room multi-tenant sports-facility SaaS, FastAPI + SQLAlchemy 2 sync + Postgres 16 with forced RLS, Dramatiq, React 18 + TS + Tailwind. Phase 9 = backlog wave 1 "money ready for real customers", coordinated from the Phase 9 coordinator session on branch `claude/phase9-wave1-711cdd`; plan `docs/planning/phase9-plan.md` (owner decisions, file ownership, migration block 13xx, Phase 8 handover). Owner pre-approved everything; do not push. Chips A and B run at the same time and both append to `billing/models.py` and `billing/router.py`: keep additions as new lines next to existing ones, change nothing else there. Phases 8 and 10 run elsewhere; the machine rebooted under load today, so keep test runs focused and run the full suite once at the end in the background. First step for both: make sure the branch contains `claude/phase9-wave1-711cdd` (`git merge --ff-only claude/phase9-wave1-711cdd` if cut from main). Report back to the Phase 9 coordinator session (the one on that branch), not to Phase 0.

---

## Title: P9 chip A: charge catalogue (BIL-14, MEM-04)

You are Phase 9 chip A: the charge catalogue. Rows: BIL-14 (P0, L) pre-defined items, a generic charge catalogue with one-off and recurring items; MEM-04 (P1) catalogue items as membership plan add-ons and per-sale add-on changes.

Read first: `CLAUDE.md`, `docs/BRIEF.md`, `docs/dev/module-playbook.md` (lanes, security rules, kernel APIs), `backend/app/modules/billing/README.md`, `docs/status/08-billing-payments.md` and `08-billing-payments-web.md`, `docs/architecture/data-model-money.md` (catalogue section: `catalog_item`, `catalog_item_sale`; schema of record), `docs/architecture/rbac-matrix.md` billing keys, `docs/api/openapi-*.yaml` for catalogue paths and operationIds, `docs/status/05-memberships-packages.md` (MEM-04 row).

Lane: `.env` = main checkout's `.env` plus `FH_DB_NAME=facilityhub_p9a`, `FH_TEST_DB_NAME=facilityhub_p9a_test`, `FH_API_PORT=8301`, `FH_WEB_PORT=5301`; `make lane-db` then `make seed`. Never `make up/down/reset`, `make worker`, `make relay`. Fake processor only.

Build: models appended to `billing/models.py`; new `billing/catalog.py` (staff commands with both gates; internal functions other contexts call without a principal); migrations 1301 to 1309, first `down_revision` = head you find (`alembic heads`, expect `0953`), `enable_rls`, `tfk`; selling an item goes through `service.post_charge` (idempotent origin) and `create_invoice_for_charges`; recurrence expansion as pure domain logic with tests, plus an idempotent `@tenant_actor` renewal job added as one line to `app/scheduler.py`; audit once per aggregate; events via `events.publish`; keyset lists via `paginate()`; dates local to the location (`platform.service.location_today`). MEM-04: plan add-ons can reference catalogue items (billed with each dues period or once at sale, per the data model), and a sale can add or drop add-ons under the right key. Extend `populate()` in `backend/conftest.py`, `_BODIES` in `tests/test_isolation.py`, keys in `billing/permissions.py` from the RBAC matrix, seed demo items, `make openapi web-api`, staff screens under `web/src/features/billing/` (catalogue list and edit, sell to client from client billing) with Vitest tests and a Playwright spec with axe. Colours from CSS variables only.

Done: `make lint typecheck boundaries test web-check web-test` green in the lane, e2e spec green, `test_isolation`/`test_location_scope`/`test_portal_schemas` green without allow-list edits, billing README (interface plus assumptions), both 08 status docs, 05 status docs and the CLAUDE.md status row updated, Conventional Commits, no push. Report: branch, commit range, migration numbers, scheduler line added, anything partial with its reason.

---

## Title: P9 chip B: PDF engine, statements, location day

You are Phase 9 chip B: documents and PDF. Rows: BIL-10 (P0) invoice PDF; PAY-03 (P0) receipt PDF; BIL-11 (P1) statement batches with per-recipient status, statement PDF, portal statement; REL-04 statements and the AR ageing "as at" cut on the location's day instead of UTC (the two `shortcut:` comments in `billing/documents.py`, near `statement()` and the ageing cut); the shared PDF engine Phase 12 reports will reuse.

Read first: `CLAUDE.md`, `docs/BRIEF.md`, `docs/dev/module-playbook.md`, `backend/app/modules/billing/README.md`, `docs/status/08-billing-payments.md` and `08-billing-payments-web.md`, `docs/architecture/data-model-money.md` (documents, deliveries, statements), `docs/architecture/rbac-matrix.md` billing keys, `docs/api/openapi-*.yaml` for document and statement paths, `backend/app/modules/documents/domain/pdf.py` (fpdf2 is already a dependency).

Lane: `.env` = main `.env` plus `FH_DB_NAME=facilityhub_p9b`, `FH_TEST_DB_NAME=facilityhub_p9b_test`, `FH_API_PORT=8302`, `FH_WEB_PORT=5302`; `make lane-db` then `make seed`. Same lane prohibitions; fake processor only.

Build: a small engine in new `app/core/pdf.py` (page, header with tenant name and footer, table, money and local-date formatting; deterministic output so tests can assert text); do not change the `documents` module. Invoice, receipt and statement PDFs rendered from the existing JSON documents, served from download routes with the same gates as the JSON routes, attached to or linked from the email deliveries, stored through `platform.files` if the data model asks for a stored copy (Phase 8's branch adds `files.load/remove/download_url`; code against what is here and name the swap in the report). Statement batches: stored batch with per-recipient rows and status (migrations 1310 to 1319, first `down_revision` = head you find, `enable_rls`, `tfk`), run in the request up to a limit or as a `@tenant_actor` job; staff screen to create, follow and resend. Portal statement: portal route with a portal schema (no staff fields) and a screen. Day boundaries: the location's IANA zone for statement periods and the ageing cut, with a test that a payment at 23:30 local on the last day lands inside. Both gates, audit, events, `populate()`, `_BODIES`, `make openapi web-api`, Vitest and a Playwright spec with axe. Colours from CSS variables only.

Done: same gate as chip A; billing README (engine interface, assumptions; remove the UTC assumption), both 08 status docs and the CLAUDE.md row updated, Conventional Commits, no push. Report: branch, commit range, migration numbers, the `app/core/pdf.py` interface in three lines, anything partial with its reason.

---

# Batch 2 (same shared background as above; C and D both append to `billing/models.py` and `billing/router.py` under the same additive-only rule)

Batch 2 is cut before chips A and B merge. Code against the branch as you find it; the coordinator re-points your first
migration's `down_revision` and regenerates `openapi.json` / `schema.d.ts` at merge time. Chip B's `app/core/pdf.py` and
receipt PDF are not here yet: C names the portal receipt PDF hook in its report rather than building another renderer.

---

## Title: P9 chip C: card entry and portal pay

You are Phase 9 chip C: card entry and portal payment. Rows: PAY-06 and PAY-10 (P0) saving a bank account through Stripe
Financial Connections next to the existing card field; PAY-11 (P0) 3-D Secure, i.e. `handleNextAction` wherever the API returns a
client secret that needs action (staff take-payment, pay link, portal checkout, saved-method setup), plus the webhook retry for
events stored but never enqueued; PAY-18 (P0) portal pay: partial amounts, confirm on return from the processor, a portal
receipt (JSON now; the PDF hooks onto chip B's renderer at merge), paying for a household member the payer may pay for;
PAY-15 (P1) wallets (Apple Pay / Google Pay) through the Payment Element where the processor offers them (tap-to-pay stays
partial: hardware); SSP-11 (P1) coupons at portal checkout through the one coupon engine (`billing.catalogue` quote, redeem,
release; owner decision Q8).

Read first: `CLAUDE.md`, `docs/BRIEF.md`, `docs/dev/module-playbook.md` (security rules: portal sales end in
`secure_online_checkout`, portal routes never reuse staff schemas, money only to its owner), `docs/planning/phase9-plan.md`,
`backend/app/modules/billing/README.md`, `docs/status/08-billing-payments.md` and `08-billing-payments-web.md`,
`docs/architecture/data-model-money.md` (payment methods, intents, webhooks), `docs/adr/` on payments and idempotency,
`backend/app/adapters/stripe_connect.py` and `fake_payments.py`, `web/src/features/billing/StripeCardField.tsx`.

Owns: `billing/portal.py`, `billing/checkout.py`, `billing/methods.py`, `billing/webhooks.py` (retry only),
`adapters/stripe_connect.py`, `adapters/fake_payments.py`, `web/src/features/billing/{StripeCardField,PaymentMethodField,TakePaymentDialog,PayLinkPage}`,
portal billing screens. Do not edit `billing/service.py`, `desk.py`, `documents.py`, `autopay.py` or `catalog.py`.

Lane: `.env` = main `.env` plus `FH_DB_NAME=facilityhub_p9c`, `FH_TEST_DB_NAME=facilityhub_p9c_test`, `FH_API_PORT=8303`,
`FH_WEB_PORT=5303`; no `FH_STRIPE_*` lines; `make lane-db` then `make seed`. Never `make up/down/reset`, `make worker`,
`make relay`. Fake processor everywhere; Stripe only through mocked HTTP in tests; no live keys, ever. Card and bank numbers only
ever inside Stripe's own Elements; nothing of them reaches our API, logs or storage.

Build: migrations 1320 to 1329 if needed (`enable_rls`, `tfk`). The fake adapter gains a "requires action" mode so 3DS paths
are testable end to end. One shared web `PaymentMethodField` (card, bank, wallet) used by staff take-payment, pay link and portal
checkout; Phase 10 reuses it at the check-in window, so keep its props small and documented. Webhook retry is an idempotent
`@tenant_actor` sweep added as one line in `app/scheduler.py`. Every payment and confirm route takes `Idempotency-Key`. Portal
partial pay never pays more than is owed and never another household's invoice. Both gates, audit, events, `populate()`,
`_BODIES`, `make openapi web-api`, Vitest, and Playwright specs with axe for portal pay and the 3DS path (fake adapter).

Done: `make lint typecheck boundaries test web-check web-test` green in the lane, e2e specs green, the three generated guards green without
allow-list edits, billing README and both 08 status docs and the CLAUDE.md row updated, Conventional Commits, no push. Report to
the Phase 9 coordinator: branch, commit range, migration numbers, the scheduler line, `PaymentMethodField` props, anything
partial with its reason.

---

## Title: P9 chip D: collections and dunning

You are Phase 9 chip D: collections and dunning. Rows: BIL-17 (P0) autopay default resolution (plan, then tenant setting,
then channel), written down and tested; BIL-20 (P1) collections tags, a collections profile on the client and a collections
report; BIL-22 (P0) portal lockout for past-due accounts actually enforced, plus the staff notices screen; PAY-07 (P1)
expiring-cards screen; PAY-08 (P0) daily digest of failed and upcoming autopays to staff; MEM-14 (P1) automatic suspension for
non-payment (owner decision Q13: a billing setting, off by default, suspends a membership when an invoice for it is past due by
N days and lifts it when paid; staff can still suspend by hand); MEM-05 (P0) capture, online card-save and freeze-resume
settings actually take effect where they are read.

Read first: `CLAUDE.md`, `docs/BRIEF.md`, `docs/dev/module-playbook.md`, `docs/planning/phase9-plan.md`,
`backend/app/modules/billing/README.md`, `docs/status/08-billing-payments.md`, `08-billing-payments-web.md` and
`05-memberships-packages.md`, `docs/architecture/data-model-money.md` (autopay, notices, settings), `docs/architecture/rbac-matrix.md`
billing and membership keys, `backend/app/modules/billing/autopay.py`, the memberships suspension code.

Owns: `billing/autopay.py`, billing notices code, the settings parts of `billing/catalogue.py`, `memberships` settings and
suspension code, web autopay, notices, collections and expiring-cards screens. Do not edit `billing/service.py`, `desk.py`,
`documents.py`, `portal.py`, `checkout.py`, `methods.py` or `catalog.py`. Memberships reacts to billing through events
(upward flow is an event): suspension on past-due is an idempotent `@handles` + `@tenant_actor` subscriber or a daily job, never
a billing import of memberships.

Lane: `.env` = main `.env` plus `FH_DB_NAME=facilityhub_p9d`, `FH_TEST_DB_NAME=facilityhub_p9d_test`, `FH_API_PORT=8304`,
`FH_WEB_PORT=5304`; no `FH_STRIPE_*` lines; `make lane-db` then `make seed`. Same lane prohibitions; fake processor only.

Build: migrations 1330 to 1339 (`enable_rls`, `tfk`). Daily jobs (digest, auto-suspend sweep) are idempotent `@tenant_actor`
lines in `app/scheduler.py`, run on the location's day (`platform.service.location_today`). Digest goes through the notification
port. Lockout is checked server-side on portal routes, not only hidden in the screen. Collections tags and profile carry their
own keys; the report uses keyset `paginate()`. Both gates, audit, events, `populate()`, `_BODIES`, `make openapi web-api`, Vitest
and Playwright specs with axe for the screens touched.

Done: same gate as chip C; billing README (assumptions include Q13 and the BIL-17 resolution order), the 08 and 05 status docs
and the CLAUDE.md rows updated, Conventional Commits, no push. Report to the Phase 9 coordinator: branch, commit range,
migration numbers, scheduler lines, anything partial with its reason.
