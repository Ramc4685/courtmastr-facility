# Module 4: clients and households (lane `people`)

Built on `lane/people`. Migration `0201_clients_households` (down revision `0002`). Backend: `clients`
(service, households, activity, merge), an `engagement` slice for consent, and platform data subject requests
(`platform/privacy.py`). Web: `web/src/features/clients/`.

Totals: **P0** 13 done, 1 partial, 3 not built (17). **P1** 5 done, 4 partial, 1 not built (10).

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| CLI-01 Client profile record | P0 | done | `clients/models.py` `Client` (every column in data-model 1.1 except `photo_file_id`), `service.client_view` | `test_profile.py`, `test_clients.py`, isolation | Sensitive fields are masked unless the caller has `read_sensitive`. Optimistic `version`. |
| CLI-02 Manual client creation | P0 | done | `POST /clients`, `service.create_client`; web Add client dialog | `test_profile.py::test_emails_*`, `test_field_policy_*` | Idempotency-Key honoured by the router. Each new address gets a double opt-in link. |
| CLI-03 Client list, search and saved views | P0 | done | `service.list_clients` (`view=` recent, created, birthdays this or next month, disabled, duplicates, no_category); web `ClientsPage` | `test_views_search_and_recent`, `ClientsPage.test.tsx`, `e2e/clients.spec.ts` | Trigram search over name, preferred name, email, member number, phone and address. Named views are server code. A user's own saved filters live in browser localStorage. The axe scan passes in both themes with no exclusions: refetching rows (shared `Table`) are no longer dimmed by opacity, which had dropped muted text to 2.8:1. |
| CLI-04 Per-context field requirement policy | P0 | done | `client_field_policy`, `service.check_capture` for staff, portal and registration | `test_field_policy_applies_per_capture_context` | Names are locked everywhere; email and birth date are locked for registration. Registration calls `check_capture(..., "registration")` once that module exists. |
| CLI-05 Custom client fields | P1 | done | `custom_field`, `Client.custom_values` (jsonb), `/custom-fields` | `test_custom_fields_validate_and_merge` | Types: text, number, date, boolean, choice. Policy keys are `custom.<key>`. |
| CLI-06 Client categories | P0 | done | `/client-categories` with client counts | `test_categories_tags_and_counts` | A category in use cannot be deleted (`in-use`); deactivate it instead. |
| CLI-07 Referral categories and source | P1 | done | `/referral-categories`, `Client.referral_source` | `test_categories_tags_and_counts` | |
| CLI-08 Tags (sports, seasons, custom) | P0 | done | `tag`, `client_tag`, `/tags`; sport and season tags are seeded per tenant | `test_categories_tags_and_counts` | List filter `tag_id`. |
| CLI-09 Activity log with attachments | P1 | partial | `client_note`, `/clients/{id}/notes`, `/client-notes/{id}`; web Notes tab | `test_notes_subjects_and_timeline` | **Attachments not built**: they need platform uploads (`stored_file`) and object storage, which do not exist yet. |
| CLI-10 Activity/task subject list | P1 | done | `note_subject`, `/note-subjects` | `test_notes_subjects_and_timeline` | A free-text subject is allowed in place of a list entry. |
| CLI-11 Client tasks and task/activity report | P1 | partial | `client_task`, `/client-tasks` (filters, `overdue=true`), `/client-tasks/open-count`, `activity.send_task_reminders`, hourly `send_client_task_reminders` actor | `test_tasks_own_reach_counts_and_reminders`, `test_task_reminders` | Reminders go once per task on the client's home-location day. **Not built**: a dedicated task/activity report (the reporting module owns it). Own reach means the assignee. |
| CLI-12 Client photo | P0 | not built | none | none | Needs the platform uploads flow (security-baseline 8), `stored_file` and object storage. None exist, so `photo_file_id` and the photo routes are left out. |
| CLI-13 Duplicate detection and merge | P1 | done | `merge.py`: `list_duplicates`, `precheck`, `merge`, `register_merge_handler`; web `MergePage` | `test_duplicates_precheck_and_merge`, `test_merge_blocker_*`, meta-test `test_every_table_with_a_client_fk_*` | Synchronous in one transaction. Back-fills blank fields. The loser stays as a tombstone with a `client_merge` row (append-only). |
| CLI-14 Disable a client | P0 | done | `/clients/{id}/disable` and `/enable` | `test_disable_revokes_portal_access_and_enable_restores_it` | Disable revokes portal access and disables an identity left with no other access. Enable restores exactly what the disable revoked. |
| CLI-15 Self-service portal access provisioning | P0 | done | `households.invite_to_portal`, `revoke_portal_access`; the platform activation hook flips invited rows to active | `test_portal_invite_profile_and_dependents` | An address that is already someone's login can only attach as manager (`identity-in-use`). `/me` fills `client_ids`. |
| CLI-16 Communication subscriptions | P0 | partial | `engagement` slice: `communication_preference`, `consent_event` (append-only); staff and portal GET and PUT; `engagement.service.is_subscribed` | `test_preferences_*`, `test_portal_preferences_*` | Opting in an email address needs that address confirmed. A staff change needs a note and a basis. **Not built**: the public signed-link preference centre and one-click unsubscribe (engagement module). |
| CLI-17 Default trainer / salesperson ownership | P1 | done | `PUT /clients/{id}/owners`, `service._own_clause` | `test_member_numbers_versions_and_owners` | `own` reach is trainer or salesperson. The booking clause of rbac-matrix 3.2 waits for scheduling. |
| CLI-18 Emergency contacts | P0 | done | `client_emergency_contact`, staff and portal GET and PUT | `test_emergency_contacts_and_import`, households | Reading needs `read_sensitive`. Up to 10 per client. |
| CLI-19 Cross-location shared client record | P0 | done | Lists are tenant-wide; `home_location_id` is an attribute | `test_clients_are_tenant_wide_not_location_scoped` | |
| CLI-20 Staff-facing client alerts and notes | P1 | done | `client_alert`, `/clients/{id}/alerts`, `activity.active_alerts(...)`; derived `GET /clients/{id}/system-alerts` (`memberships.service.client_alerts`) | `test_alerts_show_where_and_when_set`, `memberships/tests/test_client_alerts`, e2e `desk.spec` | Derived alerts live in memberships (clients is layer 1 and cannot read billing or documents): balance due, expiring within 14 days or expired, missing required waiver; each one needs its owner's read key. |
| CLI-21 Client API surface | P1 | partial | Every resource is in `backend/openapi.json` under the staff API | isolation and module tests | **Not built**: public API keys and scopes (integrations module). `createClientExport` (CSV) is also not built. |
| FAM-01 Typed client-to-client relationships | P0 | done | `relationship_type` (system types seeded), `client_relationship` (one row per pair, inverse rendered), staff create, approve and end | `test_types_and_staff_relationships` | `relationship-exists` on a second live link between the same pair. |
| FAM-02 Self-service relationship management | P0 | done | `/portal/dependents`, `/portal/relationships` (request, list, end), `/public/relationship-confirmations` | `test_portal_invite_*`, `test_relationship_request_*`, `test_staff_approve_*` | A dependent has no login and is managed through a non-primary access row. A request always answers 202 (no account enumeration). |
| FAM-03 Act on behalf of a related person | P0 | done | `households.can_act_for(session, identity_id, client_id, capability)`, checked per request | `test_can_act_for_rules` | Authorities are self, manager, guardian and delegate. A delegate cannot edit the profile or consent. |
| FAM-04 Membership sharing | P0 | not built | none | none | Owned by memberships (`membership_share`, data-model-people section 9). |
| FAM-05 Package sharing | P0 | not built | none | none | Owned by packages (`package_share`). |
| FAM-06 Rental plan sharing | P1 | not built | none | none | Owned by rentals. |

Also built, outside the CLI and FAM IDs:

- **Member numbers** (MEM-05): manual, scanned or generated from `tenant_counter('member_number')`, with
  `ensure_member_number` for memberships.
- **GDPR export and erasure**: `/data-subject-requests` with a subject-handler registry. Erasure anonymises
  the client, deletes the rows that only describe the person, keeps the ledger, and hashes opt-outs. The
  sentinel scan test covers it.
- **Activity timeline**: `/clients/{id}/timeline`.
- **Import-ready service**: `service.import_client`.
