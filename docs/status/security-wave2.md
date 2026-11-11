# Security wave 2: status

A read-only review of wave 2 (programs, check-in, leagues, engagement, integrations, staff, assessments,
mobile) on main at `1c8e888` found no critical or high issue and no cross-tenant path. It confirmed nine
medium and low findings. Wave 1's patterns and rules: `docs/status/security-wave1.md` and
`docs/dev/module-playbook.md` section "Security rules for new modules".

## Wave 2 hardening

Every fix has a regression test that fails against the pre-fix source (checked by restoring the pre-fix
service file and running the test).

| Finding | Where | Fix | Test |
|---|---|---|---|
| W2-01 (medium) team-fee payer unscoped | `leagues/service.py` `_bill`, `_client` | the payer is loaded through `clients.service.load(..., leagues.team.manage)` (404 out of reach), must be active, and must be the captain, an active rostered client or an active relative of one (`billing.service.related_clients`), else 422. No billing key is added: the amount comes from the competition and the payer is limited to the team's people (leagues README) | `leagues/tests/test_leagues.py::test_w2_01_team_fee_payer_must_belong_to_the_team` |
| W2-02 (medium) API keys on keyless routes | `core/auth/deps.py` `require` | `require()` with no keys no longer accepts API keys (`accepts_api_key = bool(keys)`). No keyless route is deliberately public to keys | `tests/test_security.py::test_api_keys_cannot_call_keyless_routes` (generated: every keyless route, about 120, with an API key gets `403 api-key-not-allowed`); `integrations/tests/test_integrations.py::test_key_calls_staff_routes_within_its_scopes` now expects 403 on `/locations` |
| W2-03 payee login link | `staff/service.py` `create_payee`, `platform/service.py` `set_linked_resource` | create needs `staff.pay_rate.manage` whenever it sets `staff_user_id`, as update does; an existing link to another resource is `409 already-linked`, never overwritten | `staff/tests/test_staff.py::test_w2_03_linking_a_login_to_a_payee_needs_the_pay_key_and_never_overwrites` |
| W2-04 (low) SSRF via IPv4-embedding IPv6 | `integrations/domain/webhooks.py` `blocked_reason` | NAT64 `64:ff9b::/96`, IPv4-compatible `::/96`, 6to4 and Teredo are refused as `embedded-ipv4`. On Python 3.12.8 `64:ff9b::a00:1` and `::7f00:1` report `is_global=True`, so they used to pass; 6to4 and Teredo were already caught as private | `integrations/tests/test_integrations.py::test_blocked_address_classes` (nine new cases) |
| W2-05 own pay statement | `staff/service.py` `update_pay_statement` | `_not_self` on the statement's staff user, or the linked login of its payee | `staff/tests/test_staff.py::test_w2_05_a_payroll_runner_never_adds_income_to_their_own_statement` |
| W2-06 roster and captain clients unscoped | `leagues/service.py` `_person`, `_new_team`, `update_team` | `client_id` loads under `leagues.roster.manage`, `captain_client_id` under `leagues.team.manage` | `leagues/tests/test_leagues.py::test_w2_06_roster_and_captain_clients_go_through_the_scoped_loader` |
| W2-07 bracket booking and copied rosters | `leagues/service.py` `update_bracket_slot`, `copy_competition_teams` | booking a slot's court also needs `leagues.game.manage`; `includes_rosters` also needs `leagues.roster.manage`, and each copied client loads under it | `leagues/tests/test_leagues.py::test_w2_07_bracket_booking_needs_the_games_key_and_copied_rosters_the_roster_key` |
| W2-08 push token reassigned | `engagement/service.py` `register_portal_device` | a live row held by another identity is revoked (audited) and a new row is added. Migration `0802` turns `uq_device_registration_push_token` into a unique index on live rows | `engagement/tests/test_messaging.py::test_w2_08_a_push_token_on_another_login_is_revoked_never_reassigned` |
| W2-09 422 before 404 | `assessments/service.py` `create_result` | `clients.service.load` runs before `require_active` | `assessments/tests/test_assessments.py::test_w2_09_an_out_of_reach_client_is_404_before_any_422` |

## Scoped differently from the review

- **W2-06 captain key.** The review suggested `leagues.roster.manage` for `captain_client_id`. The captain is set
  on team create and update, which are `leagues.team.manage` commands, and the front desk holds the roster key
  without the team key, so the captain loads under `team.manage`.
- **W2-06 `_roster_views` display names.** Not changed. Every client id on a roster row now passed the scoped
  loader when it was written, so the names the view shows are of clients the writer could reach.
- **W2-01 relatives.** The relative path reuses `billing.service.related_clients` (active relationships only),
  which the billing tests already cover; the leagues test covers the stranger, captain, rostered and
  out-of-reach cases.
- **W2-08 migration number.** `0802` sits in the engagement block but revises `0952`, the current head, so the
  history stays linear.

## Notes for later

- Leagues keys have no own reach in the catalogue, so the scoped client loads in leagues only bite for a
  custom role or a future own-reach grant; the membership rule in W2-01 is what stops a League Manager today.
- A keyless route that should serve API keys needs a permission key on its `require()`; there is no opt-in flag.
