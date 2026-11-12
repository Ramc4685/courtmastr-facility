# clients

People: client profiles, households, notes and tasks, merge, and the GDPR subject handlers for this context.
Build module 4. Feature status: `docs/status/04-clients-households.md`. Migration `0201_clients_households`.

| File | What it holds |
|---|---|
| `models.py` | Every table of data-model-people section 1 except photo storage: `client`, `client_email`, settings, field policy, custom fields, categories, tags, emergency contacts, relationship types and relationships, portal access, notes, subjects, tasks, alerts, `client_merge` (append-only), recent views |
| `service.py` | Profile queries and commands, field policy (`check_capture`), member numbers, owners and `own` reach, and the internal interface |
| `households.py` | Relationships, `can_act_for`, portal invitation and revocation, and every `/portal` function |
| `activity.py` | Notes, subjects, tasks (`send_task_reminders`), alerts (`active_alerts`), timeline |
| `merge.py` | Duplicates, precheck, merge, `register_merge_handler`; registers this context's erase and export handlers |
| `router.py` | Staff, portal and activity routes; a separate `public` router for emailed links |

## Internal interface (no permission check; ADR 0009 section 9)

`get`, `require_active`, `resolve` (follows `merged_into_id`), `display_name`, `is_minor` (age of majority
from `tenant.settings`, default 18), `email_is_verified`, `client_addresses`, `ensure_member_number`,
`import_client`, `link_identity`, `client_ids_for_identity`, `households.can_act_for(session, identity_id,
client_id, capability)`, `households.actable_client_ids`, `activity.active_alerts(session, client_id,
"check_in" | "booking", on)`.

## Integrator notes

- **Every table with a foreign key to `client` needs a merge handler and an erase handler.** The meta-test
  `test_every_table_with_a_client_fk_has_merge_and_erase_handlers` fails otherwise. Billing tables
  (`invoice`, `charge`, `payment`, `refund`, `ledger_entry`) are allow-listed there until the money lane
  registers `clients.merge.register_merge_handler(...)` and `platform.privacy.register_subject_handler(...)`;
  remove them from `MONEY` when it does. A merge precheck can return blockers (for example an open balance).
- Portal routes must check `can_act_for` per request. Delegates may book, buy and view the schedule only.
- `PrincipalOut.client_ids` is filled by the resolver this package registers with platform.
- Opt-in to marketing lives in the `engagement` slice; ask `engagement.service.is_subscribed` before sending.

Imports (Phase 8 I1): `service.import_client` refuses a new record that the duplicate rule pairs with an existing
client (409 `possible-duplicate`; the importer reports the row as skipped, never merged), and matches by member
number without case. `service.find_by_primary_email` and `households.import_link` (member linked to its head,
`created_via` import, idempotent) are internal for the `imports` context, which carries the gate.

## Not built

Client photo (needs platform uploads and `stored_file`), note attachments, CSV export (`createClientExport`),
the portal member card, a scheduler for task reminders, derived system alerts, and the booking clause of the
`own` reach predicate (waits for scheduling).

## Assumptions

- Email verification tokens live on `client_email`. `client.primary_email` is the denormalised, lower-cased
  copy of the primary row; the migration back-fills one row per existing client.
- Portal GET operation ids start with `get`/`list` (kernel naming test), which differs from the YAML ids.
- `is_own_clients_scope_enabled` is stored only; RBAC reach decides visibility.
- A user's saved list filters live in browser localStorage; the named views are server code.
- Merge runs synchronously in one transaction; `client_merge` history is never re-pointed.

## Security hardening (wave 1, P-01 to P-07)

- Every client command loads the client through `service.load`, including task and relationship bodies; a
  body id outside the caller's reach is 422 at its pointer, a path id is 404.
- A portal request for a guardianship over a minor (either side of the type) is stored `pending` with no
  token and no email; only staff `approve_relationship` activates it, and the minor cannot end it in the
  portal (409 `staff-approval-required`). Minor tests use the home location's date.
- The portal may set `birth_on` only while it is blank (422 `field-locked`).
- Merge never carries acting rights: the loser's manager access rows are revoked and its live relationships
  that grant acting rights (from either side) end. `merge-precheck` lists them under `review` so staff
  re-grant on purpose. Rights already held on the survivor's own record are untouched.
  A portal-created record cannot survive a merge with a staff-created one (blocker `survivor-portal-created`):
  the staff record must be the survivor, so a portal manager never inherits the real record's history.
- A portal-created record matches as a duplicate on email only through a verified address.
- `client_merge.backfilled_fields` stores field names only (`{field: true}`): the table is append-only and
  erasure cannot clear values. Rows written before this change exist only in demo tenants.
