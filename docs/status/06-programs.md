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
| REG-10 Online registration config | partial | `/registration-config`, publish, fees with `is_online`, four payment requirements | `test_portal_pays_*` | Deposits are stored but not charged separately; there are no instalment plans. |
| REG-12 Registrant online checkout | done | `/portal/registration-checkouts`; guest `POST /public/guest-checkouts` (+ `/confirm`, `/abandon`); web `/f/:slug/programs/:id/guest` | `test_checkout.py`, `test_guest_checkout.py` | Guests: off by default per group (`allows_guest_checkout`), new card only, always new clients, the guest token (hash kept) is the only key; a program with a blocking document refuses guests (409 `guest-documents-required`); no 3-D Secure for guests. No coupons in the portal basket. |

**P0 total: 15. Done: 13. Partial: 2.**

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
