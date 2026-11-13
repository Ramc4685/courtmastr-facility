# Phase 14 chip C2: direct links, shared bookings, series merge, post-billed packages, agreement binding

Branch `claude/phase14-c2-shared-bookings-af70cf`. Migration `1481_scheduling_packages_shared_post_billed`.

## Done

| Id | What | Where |
|---|---|---|
| SCH-16 | Direct registration link per session; token in the URL fragment, resolved by an anonymous rate-limited POST | `scheduling/sharing.py`, `web/src/features/scheduling/sharing.tsx` (`/direct-link`) |
| SCH-17, SSP-09 | Shared bookings: related clients on one booking, each with their own attendance | `booking_participant`, `ParticipantsCard` |
| SCH-21 | Merge two reservations into one series (holds untouched, only `scheduling.service`) | `service.merge_series`, `MergeSeriesForm` |
| PKG-11 | Post-billed packages with tiered per-session rates | `packages/postbilled.py`, `PostBilled.tsx` |
| BIL-18 | Period close per location and date: `post_charge` + `create_invoice_for_charges`, gate `packages.period.close`, idempotent | `postbilled.close_period` |
| DOC-11 | Membership agreement bound to its contract, shown, kept on erasure | `memberships.service.bind_agreement`, `ClientMembershipsTab` |

New tables (all with `tenant_id`, `UNIQUE (tenant_id, id)`, `enable_rls`, `tfk`, a `populate()` row):
`booking_participant`, `post_billed_rate`, `post_billed_close`, `post_billed_line`, `post_billed_usage`.

## Tests

Backend: `scheduling/tests/test_sharing.py` (7), `packages/tests/test_post_billed.py` (5),
`memberships/tests/test_agreement.py` (2), plus the security, isolation, location-scope, portal-schema,
RLS-meta and RBAC suites. Web: `sharing.test.tsx` (2); Playwright `e2e/shared-post-billed.spec.ts` (2, axe;
run in CI only).

## Assumptions

- One direct link per session, reusable; turning it off rotates the token. Booking from the link is the
  portal's ordinary enrolment, so the visitor signs in first.
- Shared booking participants must be active relatives of the organiser; package credit is spent by the
  packages calls, not by scheduling.
- Rate tiers are whole-count: every session of the period bills at the highest tier the count reaches.
- One bound agreement per contract; rebinding replaces it (audited).

## Not built

Direct links for slot offers; extra billed items on a post-billed rate; refunds when a billed credit is later
restored; an automatic (scheduled) close; a portal view of shared bookings.

## Handovers

None: no edits to `billing/*`, `core/*`, `infra/*` or other contexts' modules.
