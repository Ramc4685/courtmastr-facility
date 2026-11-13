# Build module 6: programs and registration

Scope: the `programs` context (parity rows CLS and REG), backend, staff screens and portal screens. Rules and
assumptions are in `backend/app/modules/programs/README.md`. Date: 2026-11-10.

Backend tests are in `backend/app/modules/programs/tests/`:
- `test_sessions.py`, `test_package_credits.py` and `test_hardening.py` (from module 2).
- `test_groups.py`, `test_checkout.py` and `test_selfservice.py` (new in module 6).

The generated isolation, location-scope and security tests in `backend/tests/` cover every new route.
Web: `web/src/features/programs/programs.test.tsx` (Vitest) and `web/e2e/programs.spec.ts` (Playwright with
an axe scan).

## P0 features

| Feature | Status | Where | Tests | Notes |
|---|---|---|---|---|
| CLS-01 Register into a session | done | `POST /enrollments` (free, package), `POST /portal/enrollments` | `test_sessions.py`, `test_package_credits.py`, `test_portal_books_and_cancels_early_or_late` | |
| CLS-02 Multi-enrolment | done | `POST /enrollments/batch` (`all_linked`, `custom`); cancel `scope: batch` | `test_series_batch_rebook_and_roster_message` | Full or ineligible occurrences are skipped with their code. |
| CLS-03 Roster, attendance and participant actions | done | roster, attendance, cancel, `POST /enrollments/{id}/rebook`, `POST /sessions/{id}/roster/messages` | `test_sessions.py`, `test_series_batch_rebook_and_roster_message` | The message is plain text; the module 14 key is a shortcut (README). |
| CLS-04 Capacity and bulk change | done | module 2 `POST /sessions/capacity-changes`; programs: capacity on group nodes | module 2 tests, `test_admin_edits_*` | |
| CLS-05 Free booking | done | `allows_free_booking`, package or `free_book` override | `test_sessions.py`, `test_hardening.py` | |
| CLS-06 Waitlist with auto-promotion | done | auto-promote, manual and open-offer modes; `POST /portal/waitlist-entries/{id}/claim`; offers lapse | `test_open_offer_first_claim_wins`, `test_sessions.py` | |
| CLS-09 Client self-booking and cancellation | done | `/portal/session-listings` (with reasons), `/portal/enrollments`, cancel; booking policies | `test_listings_*`, `test_portal_books_*`, `test_policy_*` | |
| CLS-10 Program registration through groups | done | program groups with linked sessions | `test_tree_capacity_*` | |
| REG-01 Group creation | done | `/program-groups` CRUD | `test_groups.py` | |
| REG-02 Subgroup hierarchy | done | `parent_id`, `child_label`, capacity along the chain, `/tree` | `test_tree_capacity_*` | |
| REG-05 Lifecycle | done | complete, archive, reopen, delete, restore, hourly auto-archive | `test_lifecycle_*`, `test_auto_archive_*` | |
| REG-07 Staff registration | done | `POST /enrollments` with group target, fees, payer, one invoice | `test_fees_are_billed_*` | Payment is taken against the invoice in billing. |
| REG-09 Group waitlist and promotion | done | manual and auto-promote; demote to waitlist; billing on promotion | `test_group_waitlist_*`, `test_admin_edits_*` | |
| REG-12 Registrant online checkout | done | `/portal/registration-checkouts`; guest `POST /public/guest-checkouts` (+ `/confirm`, `/abandon`); web `/f/:slug/programs/:id/guest` | `test_checkout.py`, `test_guest_checkout.py` | Guests: off by default per group (`allows_guest_checkout`), new card only, always new clients, the guest token (hash kept) is the only key; a program with a blocking document refuses guests (409 `guest-documents-required`); no 3-D Secure for guests. No coupons in the portal basket. |
| REG-10 Online registration config | done | `/registration-config` (with `payment_plan`, `balance_due_on`, `instalment_count`, `instalment_unit`), publish, fees with `is_online` and `deposit_minor`, four payment requirements | `test_portal_pays_*`, `test_reg_10_deposit_and_instalment_plans` | Deposit now and the balance on a date or in equal instalments on the invoice schedule, collected by autopay (decision Q5, phase 11 B). Staff checkout still invoices in full. Fix: a plan's invoice is created as an autopay invoice, so the autopay run collects the later instalments (test runs it on the first instalment date). |

**P0 total: 15. Done: 15. Partial: 0.** (REG-10 and REG-12 closed in phase 11 B and chip A; the stale partial rows were removed.)

## Screens

- **Staff:**
  - `/programs`: list and create.
  - `/programs/:id`: overview and lifecycle, subgroups, linked sessions, fees, online registration and publish, roster with register and cancel, waitlist.
  - `/programs/register`: the registration basket.
  - `/programs/booking-policies`: location default and per-type overrides.
  - Session panel: book across a series, move (rebook), message participants, and cancel with scope.
- **Portal:** `/portal/programs` (published programs, basket and confirm), `/portal/sessions` (listings with reasons, book, cancel, waitlist join, leave and claim).

Web limits:
- **Portal confirm payment:** it offers pay later or a saved card only, with no new-card entry. A pay-now program therefore needs a card on file.
- **Documents:** the missing-documents notice does not link to signing.
- **No screens:** the fee catalogue and the `/tree` view have none.
- **Not browser-tested:** basket confirm, the portal booking actions and the session tools. Vitest covers them; the Playwright spec scans the screens with axe.

## Phase 14 chip A: event forms and group tools (P1, P2)

Backend: `tools.py` and `forms.py`, migration `1401_programs_forms_tools`. Tests: `tests/test_tools.py` and
`tests/test_forms.py`, plus the generated isolation, location-scope, security and portal-schema tests. Web:
`forms.test.tsx` (Vitest) and `web/e2e/forms.spec.ts` (Playwright with an axe scan on every screen, including
an anonymous sign-up in a fresh browser context and the priced form in the portal).

| Feature | Status | Where | Notes |
|---|---|---|---|
| REG-03 Group classifiers | done | `/program-classifiers`; `/programs/setup`; program Tools tab | Tenant-wide; in-use ones deactivate only. |
| REG-04 Search, views and filters | done | classifier filters on `/program-groups`; `/program-saved-views` | Views are per staff user. |
| REG-06 Page personalisation | partial | `/program-page-settings/{page_key}`; column chooser on `/programs` | `member_grid` settings are stored but the roster has no chooser. |
| REG-08 Move members | done | `POST /enrollments/move`; program Tools tab | Same location only; per-row outcome codes. |
| REG-11 Registration defaults | done | `/locations/{id}/registration-defaults`; `/programs/setup` | Copied when a group first gets online settings. |
| REG-13 Copy, export, generate | done | `/program-groups/{id}/copy`, `/children/generate`, `/exports`; Tools tab | Generate makes sibling programs; 52 per series, 50 nodes per copy. |
| REG-15 Form builder | done | `/forms` CRUD, copy, templates, publish; `/programs/forms` | Versioned drafts. |
| REG-16 Question types | done | text, drop-down, pick one, pick any, quantity; required, staff-only, show-when | |
| REG-17 Stock caps | done | `/forms/{id}/inventory`; Stock tab | Row-locked; sold-out and count-left shown publicly when asked. |
| REG-18 Information topics | done | topic items in the question list | Plain text. |
| REG-19 Branding | partial | header image (`platform.files`), accent colour | No width or font settings. |
| REG-20 Open, close, auto-close | done | window in location time; close and reopen; capacity | |
| REG-21 Lookup, edit, export | done | `/form-submissions`, edit, cancel, promote; CSV | Edit covers contact, client link and text answers. |
| REG-22 Summaries | done | `/forms/{id}/summaries/{key}`; Summaries tab | Registrant, revenue, demographic, answer. |
| REG-23 Registrant flow | done | `/forms/:id` (anonymous, free) and `/portal/forms/:id` (priced, `secure_online_checkout`) | Members reach a form by its link; no portal list. |
| REG-24 Wait list and promo codes | done | `waitlisted` status and promote; coupons through billing | New card only at checkout. |

**Chip A total: 16. Done: 14. Partial: 2.**
