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

Backend: `scheduling/tests/test_sharing.py`, `packages/tests/test_post_billed.py`,
`memberships/tests/test_agreement.py` (25 in all after the round 2 review), plus the security, isolation, location-scope, portal-schema,
RLS-meta and RBAC suites. Web: `sharing.test.tsx` (2); Playwright `e2e/shared-post-billed.spec.ts` (2, axe;
run in CI only).

## Assumptions

- One direct link per session, shown once: only its digest is stored. Asking again while it is on returns its
  status only; an explicit regenerate or turning it off replaces it. The link waives hidden, list-only, the
  visible range and self-booking, nothing else. Booking from the link is the portal's ordinary enrolment, so the visitor
  signs in first.
- Shared booking participants must be active relatives of the organiser, and only a client's own booking
  (with an organiser) can be shared; class sessions take seats through enrolments only. Package credit is
  spent by the packages calls, not by scheduling.
- A direct link's token travels in the portal enrolment body and waives only the listing and self-booking
  checks.
- Rate tiers are whole-count: every session of the period bills at the highest tier the count reaches; tier 1
  always exists.
- A post-billed package ends at a close only once nothing is held or used after the closing date; a renewal
  stays post-billed; a credit restored after billing is credited at the next close against the line's live charge,
  following staff edits to their replacement (counted as handled only when staff reversed it and nothing live is
  left); one failing package does not stop a close, its failure is kept on the close and can be retried alone, and
  a later close that bills the package clears it. Its reservation type must belong to its location.
- Decision taken for the owner: a credit-back keeps a staff discount flat (not pro rata), capped at the line's
  new gross, and does not credit again sessions staff already took off the charge by hand.
- One bound agreement per contract, signed and of the agreement kind; a signed binding is not replaced.

## Not built

Direct links for slot offers; extra billed items on a post-billed rate; refunding money already paid for a
credited session; an automatic (scheduled) close; a portal view of shared bookings; picking a package on the direct-link page (it books free sessions only).

## Handovers

No edits to `billing/*`, `core/*` or `infra/*`. After review, `programs` (portal enrolment) takes the
`direct_link_token` and calls `scheduling.service.has_live_link`, as the lead asked.
