# Security wave 1 hardening: status

Branch `security/wave1-hardening`. Work order: `docs/security/wave1-hardening-spec.md`. Rules for new
modules: `docs/dev/module-playbook.md` section "Security rules for new modules".

## Findings fixed, per pattern

| Pattern | Findings | Fix |
|---|---|---|
| A. `authorize` without the record's location | M-02, M-03, M-04, S-07 | location passed from the loaded record; out of scope is 404 |
| B. bare `session.get` past the scoped loader | P-01, P-02, P-03, P-08 | scoped loaders (`clients.service.load` and siblings) |
| C. gate missing on a sibling path or privileged flag | M-05, M-06, M-12, P-06, S-01 to S-05 | gates moved into the shared inner function; own keys for privileged flags; P-06 merge also blocks a portal-created survivor (`survivor-portal-created`) |
| D. online entitlement without secured payment | M-08, M-09, M-10 | `billing/checkout.py` `secure_online_checkout`; a reused Idempotency-Key is a replay that must belong to the same client and fully cover this invoice, else `idempotency-key-reused` |
| E. portal schema or input leaks | M-13, P-04, P-05, P-10, P-11, S-06 | portal-only schemas and server-derived inputs |
| F. evidence and ledger immutability | P-07, P-09 | hashes immutable once decided; merge log stores field names |
| G. tender ownership and per-tender permission | M-01, M-11 | payer must be the client or an active relative (pending no longer counts) |
| H. injection into a provider query | M-07 | key pattern at the edge, escape and exact `fh_key` match at the sink |

Backlog items 26 (every Idempotency-Key header carries `KEY_PATTERN`) and 27 (relationship parties loaded
with the manage key) were also fixed in the review pass.

## Tests added

Every fix has a regression test that fails against the pre-fix source. Generated guards:
`backend/tests/test_location_scope.py` (location), `test_portal_schemas.py` (portal),
`test_hardening.py` (every Idempotency-Key header has the pattern). Per-module `tests/test_hardening.py` in
billing, pos, packages, memberships, clients, documents, platform, programs, rentals and scheduling, plus
`billing/tests/test_checkout.py` and `memberships/tests/test_checkout_hardening.py`. The three
`backend/tests/known_open/{money,people,space}.py` xfail lists are empty. Final gate numbers are in the merge
commit report: lint clean, 2462 tests passing on the branch, `web-check` clean, `web-test` 88 passing.

## Deferred

- Backlog 3: dropping `facilityhub_fixauthz` and `facilityhub_test_fixauthz` needs the owner's approval; a
  `session.established_by` column was not started.
- `make web-e2e` was not run.

## Follow-ups closed on main after landing

- Backlog 28: setting a reservation type's `default_allows_free_booking` (create or update) now needs
  `scheduling.enrollment.free_book` at the type's location, because every seat of that type inherits it.
  Booking a seat of a free-by-default type stays allowed: whoever made the type free already held the
  permission. Test: `scheduling/tests/test_hardening.py::test_free_default_of_a_type_needs_free_book`.
- Backlog 29: merge is blocked (`survivor-has-other-managers`) when the loser has its own managers or
  guardians and the survivor has ones the loser lacks, so two portal-created records under different
  guardians cannot be merged into one guardian's reach. A loser nobody acts for (a desk duplicate) still
  merges. Test: `test_merge_of_two_portal_records_keeps_guardians_apart`.
- Backlog 26: every `Idempotency-Key` header already carried `KEY_PATTERN`; a test now enforces it
  (`tests/test_idempotency_headers.py`). Backlog 27 was closed in `4969dfc`.
- Staff relationships left `pending` no longer count as a payer or bill-to (behaviour change).
