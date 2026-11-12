# Module 5 web: memberships and packages screens

Branch `lane/people`. Builds on the backend in `docs/status/05-memberships-packages.md` (service rules, jobs,
backend tests); this file adds the staff web screens and gives the combined status per feature. "done" means
the API and a staff screen exist and are tested; "partial" names what is missing; "not built" means neither.

## Screens

| Screen | Route / place | Permission | What it does |
|---|---|---|---|
| Memberships: Contracts | `/memberships` | `memberships.contract.read` | Contracts by status, with client names and links. |
| Memberships: Upcoming renewals | `/memberships` tab | same | Renewals due within 7 to 90 days. |
| Memberships: Plans | `/memberships` tab | `memberships.plan.manage` | Plan table (active / retired / all), New plan, Duplicate, plan dialog with every plan field, included package add-ons, and the required document. |
| Memberships: Types | `/memberships` tab | `memberships.plan.manage` | Add, retire and reactivate types (revenue category required). |
| Memberships: Preferences | `/memberships` tab | `memberships.plan.manage` | Membership settings. |
| Packages: Expiring packages | `/packages` | `packages.package.read` | Active packages whose last valid day is within N days (default: the expiry notice setting), with Renew. |
| Packages: Plans | `/packages` tab | `packages.plan.manage` | Plan table and plan dialog (shape, price, validity, renewal, sharing, members-only, online, invoice mode, required document). |
| Packages: Preferences | `/packages` tab | `packages.plan.manage` | Package settings (cancel and no-show credit policy, expiry notice, and more). |
| Client profile: Memberships tab | `/clients/:id` | `memberships.contract.read` | Live contracts (or all of them); sell membership; freeze / unfreeze, suspend / unsuspend, cancel (quote, credit, refund, bundled packages), undo cancel, renew (same or another plan), change plan, shares, auto-renew toggle, details (schedule, freezes, suspensions, history). |
| Client profile: Packages tab | `/clients/:id` | `packages.package.read` | Packages owned or shared; sell or grant complimentary; ledger with balance and manual adjustment; shares; edit (expiry, booking after expiry, auto-renew, remarks); renew; remove (quote, reverse or keep billing); recurring series with cancel. |

The sell dialogs show the server quote live: periods with proration, total, amount due now, required documents
and whether they block. Payment is taken in the same request through the billing kernel (cash, card token,
cheque, external terminal, other) with an Idempotency-Key. Each action button is checked against its own
permission key and labelled with the contract or package name.

Tests:
- Vitest `web/src/features/memberships/memberships.test.tsx` (5 tests). It covers the money and date helpers,
  a sale from the quote with its payment body, a cancel with credit and refund, the package ledger and credit
  adjustment, and the document-required refusal.
- Playwright `web/e2e/memberships.spec.ts` (2 tests). It runs an axe WCAG 2.1 AA scan in light and dark themes
  on every memberships and packages tab, the plan dialog, the client tabs, the sell membership dialog and the
  ledger. It also sells a package with cash end to end.
- Backend: two new filters. `expires_on_or_before` on `listClientPackages` is tested by
  `test_packages::test_expiring_packages_filter_uses_the_last_valid_day_and_skips_never_expiring`. `id[in]` on
  `listClients` is tested by `test_clients::test_create_get_list_and_search`.

Totals: whole backend suite 1232 passed, 0 skipped, coverage 95% (domain gate passes). Web: 47 Vitest tests and
7 Playwright tests pass. `make lint` and `make web-check` are clean.

Counts (39 features):

| Priority | done | partial | not built |
|---|---|---|---|
| P0 | 10 | 5 | 0 |
| P1 | 11 | 7 | 3 |
| P2 | 1 | 0 | 2 |

The P1 count moved by 4 from the backend file: MEM-13 and MEM-14 are now partial because their edit commands
have no screen, and PKG-09 is partial because it has no portal page.

## Memberships

| Feature | Priority | Status | Where (screens; API in the backend file) | Tests | Notes |
|---|---|---|---|---|---|
| MEM-01 Membership type catalogue | P0 | done | Memberships > Types | backend `test_sale::test_catalogue...`; e2e scan | Retire and reactivate; no delete. |
| MEM-02 Membership plan templates | P0 | done | Memberships > Plans (dialog, Duplicate) | backend; e2e scan of the dialog | Edits reach later sales only (snapshot). |
| MEM-03 Plan proration rules | P1 | done | plan dialog (mode, tail); sell dialog periods table | backend `test_schedule`; Vitest sale test | With seller's choice, the sell dialog asks whether to prorate. |
| MEM-04 Plan add-ons | P1 | done | plan dialog "Included packages" and "Billed add-ons" (pre-defined items) (PUT addons) | backend `test_credits`, `test_catalog_addons`; e2e `memberships.spec` (axe) | The sale dialog sells the plan's own add-ons; changing them for one sale is API only (`addons` on the sale, behind `memberships.contract.customize_terms`). |
| MEM-05 Membership preferences | P0 | partial | Memberships > Preferences | backend; e2e scan | The payment-method capture settings are stored but have no effect (no stored payment methods). |
| MEM-06 Simple (record-only) membership | P2 | done | a zero-fee plan sold from the client tab | backend `test_sale::test_record_only...` | |
| MEM-07 Staff sale of a membership contract | P0 | done | client Memberships > Sell membership | backend; Vitest sale test; e2e scan | Per-sale customised terms (fee, discount, end date, occurrences, visit cap) are API only. No card saving or coupons. |
| MEM-08 Contract document acceptance at sale | P1 | done | plan dialog "Required document"; sell dialog requirements | backend `test_sale::test_contract_document_gates...`; Vitest asserts the text | The contract waits as upcoming; signing is on the Documents tab. |
| MEM-09 Online membership sales | P1 | partial | API only | backend | No portal web page. |
| MEM-10 Contract list, status views and edit | P0 | done | Memberships > Contracts; client tab; Details dialog | backend; e2e scan | The auto-renew toggle is on screen. Salesperson, referrer, notes and visit-cap edits are API only. |
| MEM-11 Contract renewal | P0 | done | Upcoming renewals tab; Renew dialog (same terms or another plan) | backend `test_renewal_jobs` | Still needs a scheduler for automatic renewals (backend gap). |
| MEM-12 Freeze a contract | P0 | done | Freeze dialog; Unfreeze | backend `test_lifecycle` | Unfreeze removes the live freeze. |
| MEM-13 Edit or remove a freeze and re-bill | P1 | done | Details dialog: freeze end date, Remove freeze, period Edit, Reprice, Invoice deferred periods; Unfreeze | backend, Vitest `desk.test`, e2e `desk.spec` | |
| MEM-14 Suspend and unsuspend a contract | P1 | partial | Suspend dialog; Unsuspend; Details dialog edits and removes a suspension | backend | Automatic suspension for non-payment is not built. |
| MEM-15 Cancel a contract | P0 | done | Cancel dialog; Undo cancel | backend; Vitest cancel test | Reason-coded; bundled packages choice. |
| MEM-16 Cancel with full or partial refund | P1 | done | Cancel dialog (quote, credit, refund checkbox) | backend; Vitest asserts the cancel body | The refund checkbox appears only with `billing.refund.create`. |
| MEM-17 Shared membership | P1 | done | Shares dialog (ClientPicker add, revoke) | backend | |
| MEM-18 Member auto-renew opt-out | P1 | partial | staff toggle on the client tab; portal API | backend | No portal page for the member's own opt-out. |
| MEM-19 Membership number and member card | P0 | partial | the member number is on the client profile | backend | No card, QR code or RFID (check-in module). |
| MEM-20 Visit limits and visit counting | P0 | done | Details dialog lists recent visits and adjusts the count with a reason | backend, Vitest `desk.test` | Check-in records visits (phase 10 chip B). |
| MEM-21 Revenue and lifecycle reports | P1 | not built | none | none | |
| MEM-22 Membership data in the public API | P1 | partial | OpenAPI | `test_kernel` snapshot | No API keys or scopes. |
| MEM-23 Onboarding checklist | P2 | not built | none | none | |

## Packages

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| PKG-01 Package plan definition | P0 | done | Packages > Plans dialog | backend; e2e scan | Reservation type is a raw id input with suggestions (the scheduling table is not merged yet). Kind and reservation type are fixed after creation. |
| PKG-02 Free and complimentary plans | P1 | done | plan pricing "Free"; sell dialog "Complimentary" | backend | Complimentary appears only with `packages.package.grant_complimentary`. |
| PKG-03 Recurring package plans | P1 | done | plan kind "Recurring"; client tab Recurring series section with Cancel series | backend | Needs the daily job. |
| PKG-04 Validity window and expiry | P0 | done | plan validity fields; Edit dialog (extend, booking after expiry); Expiring packages tab | backend; new filter test; e2e scan | |
| PKG-05 Auto-renewal and renewal prompts | P1 | done | plan renewal fields; Edit (auto-renew); Renew button | backend | Renewals are not collected automatically. |
| PKG-06 Package sharing | P1 | done | plan share mode; Shares dialog | backend | |
| PKG-07 Staff sale of a package | P0 | partial | client Packages > Sell package (quote, invoice mode, payment) | backend; Vitest document-required test; e2e cash sale | No ad-hoc package, per-sale pricing, coupons or account-credit pre-apply. |
| PKG-08 Sale through point of sale | P1 | not built | none | none | POS module. |
| PKG-09 Online package sales | P1 | partial | plan online settings; API | backend | No portal web page. |
| PKG-10 Member-only plans | P1 | done | plan dialog members-only checkboxes | backend | |
| PKG-11 Post-billed packages | P2 | not built | none | none | No tables, rate table or batch close. Not built here either. |
| PKG-12 Session registration, roster and attendance | P0 | done | Session panel: Pay with, Speed register, Sell a package inline; Book across sessions pays with a package | backend `test_credits`, `test_session_desk` | |
| PKG-13 Remove a package and reverse or refund | P1 | done | Remove dialog (removal quote, billing mode, override reason when sessions were used) | backend, Vitest `desk.test` | |
| PKG-14 Client ledger and balance views | P0 | done | client Packages tab; Ledger dialog with adjustment | backend; Vitest ledger test; e2e scan | Available = granted − reserved − consumed − forfeited. |
| PKG-15 Sales and usage reports | P1 | not built | none | none | |
| PKG-16 Package data in the public and self-service APIs | P1 | partial | OpenAPI | as PKG-09 | No API keys or cart. |

## Assumptions

- Change plan copies the reference behaviour: there is no single command. The dialog cancels the old contract
  on day D with reason upgrade or downgrade, then sells the new plan from D+1. If that sale fails, it calls
  undo-cancel. These are separate requests, so if the undo also fails the old contract stays cancelled (the
  error shown is the sale's).
- Cards are entered as a provider token typed by staff until billing ships hosted card fields. Card numbers
  never reach us.
- "Due now" is the quote's `due_now_minor`. The payment amount defaults to it.
- The expiring list leaves out packages that never expire.

## Known defects and gaps

- Everything in the backend file's known defects (no scheduler, and the rest).
- No portal or mobile screens for module 5.
- Change plan is not atomic (see Assumptions).
- Per-sale customised membership terms have no screen (MEM-07).
- `pnpm build` was not run; `tsc --noEmit` and eslint are clean.
