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
| `files.py` | Client photo (CLI-12, `client.photo_file_id`) and note attachments (CLI-09, `client_note_attachment`) on `platform.files` |
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

## Not built

Webcam capture and portal photo edit for CLI-12, CSV export (`createClientExport`),
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

## Client files (phase 10 chip F: CLI-12 photo, CLI-09 note attachments)

- Uploads are raw request bytes with their Content-Type (as `documents` paper scans), checked by
  `platform.files.clean`: the type is sniffed from the magic bytes and must match the declared one; photos are
  JPEG or PNG and re-encoded (EXIF and GPS dropped); attachments are PDF, JPEG or PNG. No SVG or HTML. The stored
  key is generated; the user's filename is kept only as sanitised metadata for `Content-Disposition`.
- Size caps: photo 5 MiB, attachment `storage.max_upload_bytes`, at most 5 attachments per note
  (`too-many-attachments`). **Effective cap today is 1 MiB**: `core/api.py` `BodyLimitMiddleware` lists only the
  paper-scan route in `UPLOAD_PATHS`, so larger bodies get 413 before the route. Phase 8 owns `core/*`: handover
  to add `/clients/{id}/photo` and `/client-notes/{id}/attachments` there.
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
  Attachments ride on their notes, which merge re-points. Erasure first marks the photo's and the attachments'
  `stored_file` rows `purged` with `original_name` null (`files.purge_rows`), then nulls `photo_file_id` and
  deletes the notes (which cascades `client_note_attachment`). Removing a photo or attachment leaves its row
  `ready` and unreferenced. The bytes stay until Phase 8 chip K1 adds `files.remove`; a purge must check for
  other references first, since a merged survivor and its tombstone can share one photo file.
- Subject-access export lists each note's attachments (`file_name`, `content_type`, `size_bytes`), not bytes.
- Uploads to a note lock the note row first, so concurrent uploads cannot exceed the per-note cap.
- The check-in status card loads the photo route directly (`ClientPhotoById`) and hides the image on 404 or 403;
  it never reads the profile, which would log a recent view. The kiosk never shows photos.
