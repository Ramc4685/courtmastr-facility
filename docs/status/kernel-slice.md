# Kernel slice: status

Date: 2026-11-10. Scope: the shared pieces three parallel lanes (space, people, money) build on, so that no
lane has to invent them: lane isolation, the `clients` skeleton, the `billing` kernel, the notification port,
the seeds convention, and the hardening carried over from the module 1 review.

## Plan that was followed, with the check for each step

| # | Step | Check | Result |
|---|---|---|---|
| 1 | Baseline is green before any change | `make test` on `86d791e` | passed |
| 2 | Lane overrides in settings, CLI, Makefile, Vite, Playwright | `test_lane_overrides`; three lanes migrated and tested (below) | passed |
| 3 | Hardening: redirect guard tests, fragment tokens, security headers, body cap | `tests/test_hardening.py`, `features/auth/auth.test.tsx` | passed |
| 4 | Shared primitives: `core/schemas.py`, `camel_id`, `tenant_counter`, `location_today` | counter concurrency and DST tests | passed |
| 5 | `clients` skeleton with RLS, permissions, endpoints, picker | isolation tests cover both tables; `clients/tests`; Vitest; axe | passed |
| 6 | `billing` kernel with RLS, append-only ledger, fake provider | `billing/tests` incl. the randomised books-agree property test | passed |
| 7 | Notification port (no-op and email) | commit / rollback / missing-placeholder tests | passed |
| 8 | Seeds per context, run twice | `make seed` twice, same output | passed |
| 9 | Everything green, OpenAPI and web types regenerated | numbers below | passed |
| 10 | Three lane worktrees, each proven green | per-lane `make test` | see "Lane environments" |

## What was built

**Lane isolation.** `FH_DB_NAME`, `FH_TEST_DB_NAME`, `FH_API_PORT`, `FH_WEB_PORT` override `config/app.yaml`
(`core/settings.py::_lane_overrides`; `FH_WEB_PORT` also rewrites `app.web_base_url`, which emailed links and
the cross-site check use). `web/lane.ts` gives Vite and Playwright the same two ports from the environment or
the repo's `.env`. `make lane-db` creates the two databases if missing (owner `fh_owner`, as the init script
does) and migrates both. Defaults are unchanged.

**Platform additions.** `tenant_counter` with `platform.service.next_number(session, key)` (gapless: the row
lock is held to commit, a rollback returns the number); `platform.service.location_today(session, id)`.
Both are needed by all three lanes (booking, invoice, receipt and member numbers; local dates).

**clients skeleton** (`backend/app/modules/clients/`). Tables `client` (first and last name, mobile phone,
home location, primary email, member number and source, status, disabled_at; names, checks and indexes as in
data-model-people 1.1) and `client_portal_access` (1.11 in full: the link from a client-kind `identity` to the
client records it signs in as). Endpoints `listClients`, `createClient`, `getClient`. All 16 permission keys
of rbac-matrix 6.5. Event `clients.client.created`. Web: `ClientPicker`, a WAI-ARIA combobox.

**billing kernel** (`backend/app/modules/billing/`). Fourteen tables as in data-model-money section 1:
`revenue_category`, `tax`, `tax_rate`, `revenue_category_tax`, `tender_type`, `provider_account`, `charge`,
`charge_tax`, `invoice`, `payment`, `payment_allocation`, `refund`, `ledger_transaction`, `ledger_entry`. The
two ledger tables are `SELECT, INSERT` only for `fh_app`, and a deferred constraint trigger
(`ct_ledger_transaction_balanced`) rejects at commit any transaction whose debits and credits differ or that
has fewer than two lines. The postings are those of ADR 0003 section 2. All 39 permission keys of
rbac-matrix 6.10. `PaymentProvider` port and `FakeProvider` (card success, two declines, unknown outcome,
pending bank debit that settles or is returned, refunds, idempotency keys). Fourteen endpoints, listed in the
module README.

**Notification port** (`app/ports/notifications.py`): `register_template(key, subject=, body=)` and
`send(session, template_key, to, data)`; adapters `NoopNotifier` and `EmailNotifier` (through the existing
email port, after commit), chosen by `notifications.adapter`.

**Seeds.** `backend/seeds/<ctx>.py` with `seed(session)`, called in layer order from `seeds/demo.py`.
`seeds/clients.py`: six clients over both locations, and the demo member identity linked to Morgan Member.
`seeds/billing.py`: tenders, an 8.25% sales tax, four revenue categories, one paid invoice with change on
account.

**Hardening.**

- Redirect guard: backend `safe_redirect_path` (extracted from the link builder; now also refuses control
  characters) with 22 cases; web `safeNext` with 19 cases (`//host`, `/\host`, absolute URLs, schemes).
- Emailed sign-in, invite and reset tokens moved from `?token=` to `#token=` end to end: link builder, the
  landing page (reads the fragment once, then removes it from the address bar), the `link_token` test helper
  and tests on both sides. `<meta name="referrer" content="no-referrer">` on the web shell.
- `SecurityHeadersMiddleware`: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Cross-Origin-Opener-Policy`, `Permissions-Policy`, a deny-all `Content-Security-Policy` (the API serves
  data, not pages; the interactive docs page is exempt), `Cache-Control: no-store` unless the handler set
  one, and HSTS when cookies are Secure.
- `BodyLimitMiddleware`: `413 payload-too-large` problem document over `api.max_body_bytes` (1 MiB), by
  `Content-Length` and by counting a chunked body.

## Service APIs the lanes call

All take the request session and no principal (internal functions, ADR 0009 section 9). Full rules:
`backend/app/modules/billing/README.md`, `backend/app/modules/clients/README.md`.

```python
# app.modules.billing.service
post_charge(session, *, client_id, location_id, description, unit_price_minor, source_context, source_type,
            source_id, source_line_no=0, quantity=1, discount_minor=0, revenue_category_id=None,
            revenue_on=None, exclude_tax_ids=(), additional_description=None, internal_remarks=None,
            service_starts_on=None, service_ends_on=None) -> Charge
create_invoice_for_charges(session, charge_ids, *, bill_to_client_id=None, due_on=None, origin="staff") -> Invoice
take_payment(session, *, client_id, location_id, amount_minor, tender_kind, idempotency_key=None,
             method_token=None, origin="staff", invoice_id=None, allocations=None,
             external_reference=None, memo=None) -> Payment
confirm_payment(session, payment_id) -> Payment
allocate(session, payment_id, *, invoice_id=None, allocations=None) -> Payment
refund(session, payment_id, *, amount_minor, reason, idempotency_key=None, method=None, comments=None) -> Refund
reverse(session, charge_id, *, reason, revenue_on=None) -> Charge
default_revenue_category(session) -> RevenueCategory
create_revenue_category(session, *, code, label, tax_ids=(), parent_id=None) -> RevenueCategory
create_tax(session, *, code, label, rate, effective_from_on) -> Tax
ensure_defaults(session) -> None

# app.modules.clients.service
get(session, client_id) -> Client                       # NotFound
require_active(session, client_id, *, pointer="/client_id") -> Client   # 422 on the body pointer
display_name(client) -> str
link_identity(session, client_id, identity_id, *, is_primary=True) -> None
client_ids_for_identity(session, identity_id) -> list[UUID]

# app.modules.platform.service
next_number(session, counter_key) -> int
location_today(session, location_id) -> date

# app.ports.notifications
register_template(key, *, subject, body) -> None
send(session, template_key, to, data) -> None
```

Events on the outbox: `clients.client.created`; `billing.charge.created`, `billing.charge.reversed`,
`billing.invoice.issued`, `billing.invoice.paid`, `billing.payment.processing`, `billing.payment.succeeded`,
`billing.payment.failed`, `billing.payment.refunded`.

## Observed check results (main checkout)

| Check | Result |
|---|---|
| `make lint` | ruff check and format: clean |
| `make test` | 451 passed; domain-logic coverage gate 98% (floor 80%); whole app 96% |
| Generated isolation tests | all 17 new tables enrolled through `populate()`: no cross-tenant read, write or forged insert; RLS forced; 7 new id routes return 404 for the other tenant's id; 12 foreign-reference bodies return 422 |
| Migration | `0002`: upgrade, downgrade, upgrade; `alembic check` reports no drift from the models |
| `make openapi web-api` | regenerated and committed (51 paths) |
| `make web-check` | `tsc` and eslint (jsx-a11y): clean |
| `make web-test` | 37 passed |
| `make web-e2e` | 3 passed, axe WCAG 2.1 AA with zero violations, including the client picker in both themes in four states |
| `pnpm build` | passes; the development-only picker preview route is not in the bundle |

## Deviations from the specifications, with reasons

1. **Payment initiation is one transaction, not two** (ADR 0003 section 8 asks for an `initiated` row
   committed before the provider call). Replays are safe through the provider idempotency key and are
   tested, including a retry after a rollback. The gap is a process that dies after the provider answered
   and is never retried; harmless with the in-process fake, and the Money lane must close it before a real
   processor is connected.
2. **`billing.payment.processing` is emitted** although overview section 2 does not list it yet (ADR 0003
   requests that amendment).
3. **Ledger tables have no `created_at` / `updated_at`** (playbook rule for append-only tables); `posted_at`
   is the timestamp.
4. **Default rows are created on first use**, not at tenant creation (tender types, system revenue
   categories, the fake provider account): `platform` may not call up into `billing`.
5. **`ck_client_member_number_source`** is one constraint holding both the pair rule and the vocabulary,
   because the data model gives two constraints the same name.
6. **`core/schemas.py` and `core.api.camel_id`** were extracted from the platform module so other contexts do
   not import platform's schemas. Platform re-exports them; its API is unchanged.
7. **Whole permission sections registered early** (clients 6.5, billing 6.10). Three platform tests that
   asserted "this role holds exactly these keys" now filter by the `platform.` prefix.
8. **A development-only route `/dev/client-picker`** exists so the Playwright axe sweep can scan the picker
   on a real page; it is compiled out of production builds.
9. **CLAUDE.md build-status rows 9 to 17 were folded into one row** to stay under the 120-line CI limit.

## Not built (deferred, by owner)

- **Money lane (module 8):** everything under "Deferred" in `billing/README.md`: Stripe Connect, webhooks and
  the sweep, the pre-provider transaction, voids, adjustments, schedules, autopay, dunning, coupons, stored
  methods, settings, statements, management endpoints for categories, taxes and tenders, portal surfaces.
- **People lane (module 4):** everything under "Deferred" in `clients/README.md`: the remaining columns and
  tables, update, disable, merge, the `own` reach predicate (Coach sees no clients until then), member-number
  generation, the portal invitation flow, `PrincipalOut.client_ids`.
- **Engagement (module 13):** consent gate, preferences, delivery log, channels other than email.
- **Not attempted here:** a Playwright test that follows a real emailed link out of Mailpit (CI has no
  Mailpit in the e2e job; both halves are covered by backend and Vitest tests); per-lane Redis isolation
  (lanes must not run the worker or relay); an import-linter contract for the context layers.

## Lane environments

Filled in after the worktrees were created; see the table at the end of this file.
