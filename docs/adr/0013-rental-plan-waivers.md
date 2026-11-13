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
checkout) are gated. Renewals are not: the client accepted at the first sale and no one is present at renewal.

## Consequences

- The binding means what staff expect; a plan with no binding sells as before.
- One more allowed cross-context import. Documents stays below rentals (it imports nothing from rentals), so no
  cycle is created.
- A rental type (as opposed to a plan) still has no document binding; adding one would be a new decision.
