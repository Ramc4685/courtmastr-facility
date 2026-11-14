# clients

People: client profiles, households, notes and tasks, merge, and the GDPR subject handlers for this context.
Build module 4. Feature status: `docs/status/04-clients-households.md`. Migrations `0002_kernel_clients_billing`,
`0201_clients_households` and `1091_clients_photo_and_note_attachments`.

| File | What it holds |
|---|---|
| `models.py` | Every table of data-model-people section 1 except the photo bytes (kept in `platform.files`): `client`, `client_email`, settings, `client_location_settings`, field policy, custom fields, categories, referral categories, tags, emergency contacts, relationship types and relationships, portal access, notes, `client_note_attachment`, subjects, tasks, alerts, `client_merge` (append-only), recent views |
| `service.py` | Profile queries and commands, field policy (`check_capture`), member numbers, owners and `own` reach, and the internal interface |
| `households.py` | Relationships, `can_act_for`, portal invitation and revocation, and every `/portal` function |
| `activity.py` | Notes, subjects, tasks (`send_task_reminders`), alerts (`active_alerts`), timeline |
| `merge.py` | Duplicates, precheck, merge, `register_merge_handler`; registers this context's erase and export handlers |
| `files.py` | Client photo (CLI-12, `client.photo_file_id`) and note attachments (CLI-09, `client_note_attachment`) on `platform.files` |
| `router.py` | Staff, portal and activity routes; a separate `public` router for emailed links |

## Internal interface (no permission check; ADR 0009 section 9)

`get`, `require_active`, `resolve` (follows `merged_into_id`), `display_name`, `is_minor` (takes the age of
majority as an argument; households reads the tenant setting, default 18), `email_is_verified`, `client_addresses`,
`ensure_member_number`, `import_client`, `link_identity`, `client_ids_for_identity`, `audience`,
`client_ids_for_address`, `find_by_member_number`, `find_by_last_name_prefix`, `display_names`, `reach_filter`,
`households.can_act_for(session, identity_id, client_id, capability)`, `households.actable_client_ids`,
`households.guardian_ids`, `households.household_ids` (a client and the clients one acting relationship away; the
kiosk's past-due lockout), `activity.active_alerts(session, client_id, "check_in" | "booking" | "profile", on)`.

## Age confirmation (owner decision "Staff confirm once", claude/rentals-pilot)

- **Only the confirm action confirms.** `POST /clients/{id}/age-confirmation` (key `clients.client.confirm_age`,
  front desk and up, location scoped; never on an API key) clears `is_birth_on_unverified`, records
  `age_confirmed_at` and `age_confirmed_by_staff_user_id`, may correct the date, and audits flag-only. A client
  update confirms only when it sends `confirm_age: true` and the caller holds the key. Every other write of
  `birth_on` (sign-up, guest checkout, a dependant, a desk edit, the till, an import, a merge backfill, an API key)
  leaves the date unconfirmed; changing a confirmed date resets it and the response says `age_confirmation_reset`.
- **A merge never confirms.** The survivor stays confirmed only if it and every merged record were confirmed for
  the same date and no merged record brings a login the survivor did not have; otherwise it becomes unconfirmed
  (merge audit `age_confirmation_reset`, flag-only), keeps the earliest booking and joins the queue. No event fires.
- **One source of truth.** A client is confirmed when it has a birth date and `age_confirmed_at`; only the confirm
  action (single or bulk; never an import) sets it, so a raw write of `birth_on` (a seed, a script) is
  unconfirmed. `is_birth_on_unverified` in the API is derived from it (migration 1985 drops the stored flag).
- **Where staff confirm.** At the client's home location, or at the booking location the one staff notice went to
  (`age_review_location_id`): that location's staff see the person in the queue and confirm without moving them.
  Moving an unconfirmed client's home is refused (`403 age-check-pending`) for a holder of the confirm key who cannot
  confirm at the current home, so a move is never a way to gain the right (chosen over audit-and-block as smaller).
  A merge follows the same rule in both directions: every unconfirmed record in it, survivor or merged, must be one
  the caller could confirm at its current home, else `403 age-check-pending`.
- **Never a child, never without a date.** The single confirm and the confirm flag on an edit refuse a date that
  makes the person a minor (`422 minor-not-confirmed`) and a missing date (`birth-date-required`). Both actions take a
  row lock on the client, so concurrent replays fire `age_confirmed` once.
- **One wording.** `ENTRY_CODE_NOTICE` and `with_phone` ("Questions? Call us on X.") are shared with building
  control's held-code message.
- **Self-service needs a declared date.** Sign-up, guest checkout and portal dependants require `birth_on` and
  `birth_on_declared: true`; a person may not change a recorded date (`field-locked`).
- **Seam for building-control.** Event `clients.client.age_confirmed` (fired once, on the transition) and
  `service.is_age_confirmed(session, client_id)` (internal). Building-control issues a held entry code on the event
  and treats an unverified or missing date as "hold". No reverse event fires when a changed date unconfirms a client;
  building-control re-reads `is_age_confirmed` when it issues a code.
- **Queue and notice.** `GET /client-age-reviews` lists unconfirmed adults (children never get entry codes, so they
  are never listed), people with an online booking first
  (`earliest_booking_at`, kept by `note_unconfirmed_booking`, which the portal rental checkout and portal session
  enrolment call once the booking is written; a declared minor's bookings are ignored); `include=total` is the dashboard count. A newcomer's
  first booking emails the location's alert address (else its email) once, without the birth date. The portal
  identity carries `age_confirmed` and `entry_code_notice` (the notice plus the location phone from
  `platform.service.location_contact`). A declared minor is told instead that a parent or guardian must book and come
  with them (codes are never sent to minors).

- **Go-live for existing members.** Migration 1983 left every existing date unconfirmed, and an import never
  confirms an age (owner decision): imported adults wait in the queue, and their rows say "Imported, age not
  confirmed". The way out is `POST /client-age-reviews/confirmations`: up to 200 ids and a required note, kept
  flag-only; key `clients.client.confirm_ages`, `+` step-up, admin and manager, plus `clients.client.confirm_age` at
  each person's HOME location (not the location a booking told). Anyone outside that reach (`not-found`), a child
  (`minor`) or anyone with no birth date (`no-birth-date`) is skipped, never confirmed and never failing the batch:
  listed in `skipped_client_ids`, with the reason in `skipped`. Each confirmed person is audited once and fires `age_confirmed` once. To
  pick a freshly imported batch, filter the queue with `created_via=import` and `created_at[gte]=<when the import
  ran>`; the web queue has "Imported only" and "Joined on or after" for this, with checkboxes and "Confirm selected".
  Assumption: the front desk confirms one at a time, so the bulk key starts at manager.

## Integrator notes

- **Every table with a foreign key to `client` needs a merge handler and an erase handler.** The meta-test
  `test_every_table_with_a_client_fk_has_merge_and_erase_handlers` fails otherwise. Billing tables
  (`invoice`, `charge`, `payment`, `refund`, `ledger_entry`) are covered: billing registers its merge and subject
  handlers in `billing/subject.py`, so none is exempted in the meta-test. A merge precheck can return blockers (for
  example an open balance).
- Portal routes must check `can_act_for` per request. Delegates may book, buy and view the schedule only.
- `PrincipalOut.client_ids` is filled by the resolver this package registers with platform.
- Opt-in to marketing lives in the `engagement` slice; ask `engagement.service.is_subscribed` before sending.
- Events (`events.py`): `clients.client.created`, `clients.client.updated`, `clients.client.disabled`,
  `clients.client.merged` and `clients.relationship.changed`. The note-attachment event is in `files.py`.

Imports (Phase 8 I1): `service.import_client` refuses a new record that the duplicate rule pairs with an existing
client (409 `possible-duplicate`; the importer reports the row as skipped, never merged), and matches by member
number without case. An update never changes the primary email: a new address is
added as a secondary one. `service.find_by_primary_email` and `households.import_link` (member linked to its head,
`created_via` import, idempotent) are internal for the `imports` context, which carries the gate. An imported
client's `clients.client.created` event carries `source: "import"` and `import_job_id`.

## Not built

Webcam capture and portal photo edit for CLI-12, CSV export (`createClientExport`),
a web portal page for the member card (the API and the mobile app have one, in `access`), and the booking clause
of the `own` reach predicate (waits for scheduling).

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

## Client files (phase 10 chip F: CLI-12 photo, CLI-09 note attachments)

- Uploads are raw request bytes with their Content-Type (as `documents` paper scans), checked by
  `platform.files.clean`: the type is sniffed from the magic bytes and must match the declared one; photos are
  JPEG or PNG and re-encoded (EXIF and GPS dropped); attachments are PDF, JPEG or PNG. No SVG or HTML. The stored
  key is generated; the user's filename is kept only as sanitised metadata for `Content-Disposition`.
- Size caps: photo 5 MiB, attachment `storage.max_upload_bytes`, at most 5 attachments per note
  (`too-many-attachments`). Both routes are in `core/api.py` `BodyLimitMiddleware.UPLOAD_PATHS` and the Caddy
  `@upload` matcher, so the 1 MiB body cap does not apply to them.
- Bytes are served by permission-checked routes (`getClientPhoto` inline, `getClientNoteAttachment` always as a
  download) with `nosniff`, `no-store` and a sandboxing CSP. `files.read` is followed by a `purpose` check, so a
  file of another purpose is 404.
- Keys: photo upload/remove `clients.client.update`, photo read `clients.client.read` (with `own` reach);
  attachments read `clients.activity.read`, add and remove `clients.activity.write` (removing an attachment is an
  edit of the note, not a note deletion). Attachments follow their note's reach; notes carry no restricted flag
  today, so a note's attachment is exactly as visible as the note. Nothing reaches the portal.
- Audit is flag-only: `photo_file_id: true` on the client, `attachments: true` on the note; never names or ids of
  files. Events: `ClientUpdated` for the photo, `NoteAttachmentChanged` (in `files.py`) for attachments.
- Merge: `photo_file_id` is a backfill field (a survivor without a photo takes the loser's; its own wins).
  Attachments ride on their notes, which merge re-points. Erasure first purges the photo's and the attachments'
  `stored_file` rows and bytes (`platform.files.remove`) with `original_name` null (`files.purge_rows`), then
  nulls `photo_file_id` and deletes the notes (which cascades `client_note_attachment`). Replacing or removing a
  photo or attachment purges its file the same way; a photo only once no client points at it, since a merged
  survivor and its tombstone can share one photo file.
- Subject-access export lists each note's attachments (`file_name`, `content_type`, `size_bytes`), not bytes.
- Uploads to a note lock the note row first, so concurrent uploads cannot exceed the per-note cap.
- The check-in status card loads the photo route directly (`ClientPhotoById`) and hides the image on 404 or 403;
  it never reads the profile, which would log a recent view. The kiosk never shows photos.

## Phase 10 chip E (front desk)

- `send_client_task_reminders` runs hourly (`scheduler.EVERY_HOUR`). Each due task is reminded once (`reminder_sent_at`, rows locked with `SKIP LOCKED` so overlapping runs never double-send), when its due date is reached on the client's home-location day.
- `possible_duplicates(session, principal, data)` backs the register's quick-create. It matches on the same last name plus any of: first name, birth date (only for a caller holding `clients.client.read_sensitive`, within its reach), email (a portal record only through a verified address), or mobile number with a similar first name. It stays inside the caller's reach and skips merged and erased records.
- Derived alerts (balance, membership expiry, waiver) are not here: this context is layer 1 and cannot read billing or documents. They live in memberships; see its README.

## Self-service clients and terms (Phase 11 chip A)

- `create_self_service(session, data, created_via=portal|registration, verified_email=False)` creates a client for
  public sign-up and guest checkout. It never matches an existing client by email; duplicates go through merge.
- `clients.terms` holds the recorder documents registers (`register`) and the sale paths call (`acknowledge`):
  a registry, because packages and rentals may not import documents.
