# Build module 3: rentals (lane `space`)

Scope: the `rentals` context (prefix RNT), backend and staff web screens. Rules, own-design choices and
assumptions are in `backend/app/modules/rentals/README.md`. Date: 2026-11-10.

Backend tests are in `backend/app/modules/rentals/tests/` (`test_pricing.py`, `test_rentals.py`), plus the
generated tenant-isolation and security tests in `backend/tests/`. Web: `web/src/features/rentals/rentals.test.tsx`
(Vitest) and `web/e2e/rentals.spec.ts` (Playwright with the axe WCAG 2.1 AA scan on every rentals screen).

## Feature table

| Feature | Pri | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| RNT-01 Rental types | P0 | done | `GET/POST /rental-types`, `GET/PATCH /rental-types/{id}`; screen `/rentals/setup` "Types and rates" | `test_types_and_rates`; Vitest setup; e2e setup scan | Per location, revenue category, colour, resource list, plan allow-list. Zero prices allowed. Archive by `is_active=false`, no delete. |
| RNT-02 Rental rates | P0 | done | `GET/POST /rental-types/{id}/rates`, `GET/PATCH /rental-rates/{id}`; `domain/pricing.py`; rate dialog with rules | `test_pricing.py` (12 golden cases), `test_book_and_bill_*`; Vitest "adds a rate with an evening price rule" | Bases per hour, per booking, flat; per-resource or once; four line groupings; time-band, weekday, date-range and membership price rules plus stacking discounts. Rate taxes cannot be picked in the web (no tax list endpoint yet; set through the API). |
| RNT-03 Staff-booked rental, single or recurring, one or many resources | P0 | done | `POST /rentals`, `POST /rentals/preview`, `GET /rentals`, `GET /rentals/{id}`; "New rental" dialog with price preview | `test_book_and_bill_*`, `test_routing_modes`, `test_permissions_and_validation`; e2e books one | Billing through the billing kernel: new invoice, per line, per week/month, existing open invoice, or cart. The web form books one resource; the API takes up to 20. `updateRental` (moving a rental) is not built: cancel and rebook. |
| RNT-04 Extend a rental and bill selected occurrences | P1 | done | `POST /rentals/{id}/extensions`, `POST /rentals/charges` (preview or bill); "Unbilled queue" tab with "Bill selected" | `test_extend_a_recurring_rental`, `test_unbilled_queue_and_bill_selected`; Vitest bill-selected; e2e bills from the queue | Only a series can be extended; extension occurrences arrive unbilled. No extend control on the web yet (API only). |
| RNT-05 Online rental policy per rental type | P0 | done | type columns `access`, `online_rental_rate_id`, `eligibility`, `min_lead_min`, length limits, `slot_granularity_min`, `online_payment_mode`, `deposit_pct`; edited in the type dialog | `test_types_and_rates`, `test_online_checkout_*` | Membership eligibility refuses online booking (`membership-required`) until module 5 exists. |
| RNT-06 Client online rental search and booking | P0 | partial | `GET /public/rental-types`, `GET /public/rental-availability`, `POST /portal/rentals` (hold), `/confirm` (card token, idempotent), `/abandon`, `/cancel`; `billing.invoice.paid` handler | `test_online_checkout_hold_payment_abandon_and_expiry` | Backend complete, including hold expiry and the paid-invoice handler. **No portal screen** (the portal shell belongs to module 4/17); the data it needs is served. Stored payment methods arrive with module 8. |
| RNT-07 Buffer times on rentals | P1 | done | type `buffer_before_min`/`buffer_after_min`, per-request override, held by scheduling's exclusion constraint | `test_buffers_pad_the_held_range`; online slots respect them in `test_online_checkout_*` | |
| RNT-08 Remove a rental or recurring rental | P0 | done | `POST /rentals/{id}/cancel` (this, following, all; credit or keep charge; late fee, waiver); calendar cancel settles through `scheduling.booking.cancelled`; cancel dialog | `test_cancel_settles_shares_of_a_combined_line`, `test_late_fee_keep_charge_and_waiver`, `test_calendar_cancel_settles_through_the_handler`; Vitest cancel | A cash/card refund of a specific payment is module 8; reversed money becomes account credit. |
| RNT-09 Rental plans | P1 | done | `GET/POST /rental-plans`, `GET/PATCH/DELETE /rental-plans/{id}`, `POST/PATCH /rental-plan-purchases`, list, get, `/ledger`; portal `GET /portal/rental-plans`, `GET/POST /portal/rental-plan-purchases`, opt-out; `plan` charge decision; plans and "Plans sold" tabs, portal Rental plans | `test_rental_plans_full_coverage_credit_and_removal`, `test_auto_renew_autopay_and_day_roll`, `test_portal_purchase_members_only_and_opt_out`; e2e | Append-only ledger, full-coverage debit under lock, credit back on cancel; auto-renew and autopay through billing (hourly day-roll), members-only sales and member price (reads `memberships.is_member`), portal purchase through `secure_online_checkout`. |
| RNT-10 Share a rental plan | P1 | done | `PUT /rental-plan-purchases/{id}/shares`; "Plans sold" Manage dialog | `test_share_with_related_clients_only`; e2e | Live, active relatives only; one balance; shares carry over to a renewal. |
| RNT-11 Remove and refund a rental plan | P1 | done | `POST /rental-plan-purchases/{id}/cancel` (reverse or keep billing, reason); "Remove" dialog | `test_rental_plans_full_coverage_credit_and_removal` | Reversal turns paid money into account credit; a card refund is module 8. |
| RNT-12 Rental Plan Sales report | P1 | partial | read models `rpt_rental_booking`, `rpt_rental_plan_sale` (migration `0102_space_rentals.py`); "Plans sold" list | isolation tests cover the views' base tables | No report screen or CSV/PDF/XLSX export (reports, module 15). |
| RNT-13 Publish a rental on the public league site | P2 | done | `PUT /rentals/{id}/public-schedule` (`rentals.public_listing.publish`) | `test_permissions_and_validation` | The flag is stored and returned; the public feed that reads it is leagues (module 11). No web control. |
| RNT-14 Rental equipment catalogue | P0 | done | built as POS-17 (equipment catalogue) | `pos` tests | Point of sale, module 9. |
| RNT-15 Rent equipment through POS | P0 | done | built as POS-18 (equipment line on a sale) | `pos` tests | Point of sale, module 9. |
| RNT-16 Return rented equipment | P0 | done | built as POS-18 (return through the loan) | `pos` tests | Point of sale, module 9. |
| RNT-17 Locker rental to a client | P1 | done | `GET/POST /locker-leases`, `POST /locker-leases/{id}/renew`; `/lockers` board | `test_lease_terms_billing_and_one_lease_per_locker`, `test_fee_override_needs_its_own_key_and_term_must_be_current`; e2e | One open lease per locker (unique index); one charge per term through billing; another fee needs the override key. |
| RNT-18 Clear locker assignments | P1 | done | `POST /locker-leases/{id}/clear`, `POST /locker-leases/clear-expired` | `test_clear_renew_and_clear_expired`; e2e | No automatic release: staff clear expired lockers per location or room. |

Counts: P0 9 features: 8 done (RNT-14 to RNT-16 through POS), 1 partial (RNT-06, no portal screen).
P1 8 features: 7 done, 1 partial (RNT-12). P2 1 feature: done.

## Definition of done

| Item | State |
|---|---|
| Migrations with RLS forced | `0102_space_rentals.py`: 13 tables, `enable_rls` on each, composite tenant FKs |
| Seed data | `backend/seeds/rentals.py` (run twice, same output); described in `docs/dev/demo-accounts.md` |
| Tests on real Postgres, isolation | `make test`: 885 passed; `populate()` fills every rentals table, so the generated isolation tests cover all 32 operations |
| Domain coverage at least 80% | gate 95% total; `rentals/service.py` 86%, `rentals/domain/pricing.py` 99% |
| Idempotent money handlers | `Idempotency-Key` required on create, charges, plan sale and portal confirm; charges idempotent by source; handlers idempotent |
| UTC storage, per-location zones | `timestamptz` everywhere; bands, midnight cuts, week/month routing and the web all use the location's IANA zone; DST case in `test_pricing.py` |
| OpenAPI current | `make openapi web-api` run; `backend/openapi.json`, `web/src/api/schema.d.ts` |
| WCAG 2.1 AA | `web/e2e/rentals.spec.ts` scans list, new-rental dialog, unbilled queue, setup, plans, plans sold |
| Module README | `backend/app/modules/rentals/README.md` |

## Shared files touched (additive)

`backend/app/bootstrap.py`, `backend/app/main.py`, `backend/conftest.py` (`_populate_rentals`),
`backend/tests/test_isolation.py` (`_BODIES`), `backend/tests/test_kernel.py` ("search" GET prefix),
`backend/app/modules/scheduling/service.py` and `backend/app/modules/billing/service.py` (internal functions
listed in the README), `backend/seeds/demo.py`, `web/src/app/App.tsx`, `web/src/app/nav.ts` (Rentals moved out
of "coming soon"), `web/src/app/auth.test.tsx` (coming-soon count 15 to 14), `docs/dev/demo-accounts.md`.
