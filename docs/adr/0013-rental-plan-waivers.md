# ADR 0013: Rentals may call documents for rental plan waivers

- Status: Accepted
- Date: 2026-11-13
- Scope: `rentals` (rental plan sales) and its import contract in `backend/pyproject.toml`.
- Conforms to: `docs/architecture/overview.md` section 2 (boundaries), ADR 0009 section 9 (internal functions).

## Context

Documents accepts a binding of a template to a rental plan (`scope_type = rental_plan`) and staff can create one,
but rentals never checked it, so a waiver bound to a rental plan was silently not enforced (EGM triage
documents-1, question Q2). The import contract forbade `rentals -> documents`. The owner decided on 2026-11-13
(question 8) that a bound waiver must block the sale, as it does for packages, memberships and programs.

## Decision

`rentals.service` may import the top-level `app.modules.documents` package, through one `ignore_imports` line in
the rentals contract, and nothing deeper. It calls the same three internal functions packages uses:
`requirements_for` before the sale, `ensure_pending` to issue the document (the refusal is 409
`document-required` carrying `document_id`, kept after rollback), and `consume` once the purchase row exists. Both
the desk sale (`sell_plan`, `online=False`) and the portal purchase (`portal_buy_plan`, `online=True`, before
checkout) are gated. The client-active and members-only checks run before the document is issued, so an
ineligible client is never handed one.

### Amendment (review 2026-11-13): the cases left open

- **Shared plans.** A share-holder may not book on a plan shared with them until they have accepted its waiver
  themselves; the owner's acceptance does not cover them. The check runs before the booking is written (so the
  refusal keeps the pending document it issues), and the acceptance is consumed against the share row (`rental_plan_share`):
  one signature per share, not per booking.
- **Renewals** are gated too, replacing "renewals are not": a renewal needs a currently valid acceptance when the
  binding is `every_purchase` (an unused one) or the earlier signature has expired. No one is present at renewal, so
  instead of refusing, the purchase expires as usual, the renewal waits on an issued pending document
  (`rental_plan_purchase.renewal_waits_since`), the client is notified once, and the day-roll (hourly) retries until
  the document is signed (the successor then starts that day), auto-renew is turned off, or the purchase can no
  longer renew (plan archived, client no longer eligible).
- **Purchases that predate the binding** are asked at their next renewal by the same rule; nothing is asked of them
  mid-term.

## Consequences

- The binding means what staff expect; a plan with no binding sells as before.
- One more allowed cross-context import. Documents stays below rentals (it imports nothing from rentals), so no
  cycle is created.
- A rental type (as opposed to a plan) still has no document binding; adding one would be a new decision.
- A renewal can lapse for days while the client has not signed; the client is told by email, and the pending
  document shows on their record. The purchase API does not expose the wait yet.
