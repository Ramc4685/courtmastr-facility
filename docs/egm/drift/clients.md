## backend/app/modules/clients/README.md

Checked against `backend/app/modules/clients/*.py`, `backend/openapi.json` and `docs/api/openapi-people.yaml`. Only divergences are listed.

### [contract]

- README:87-88 (`getClientNoteAttachment` "always as a download") vs YAML. YAML defines `GET /client-notes/{note_id}/attachment` as "Signed URL for a note attachment" (`docs/api/openapi-people.yaml:1761-1763`). Code serves the bytes at `GET /client-notes/{note_id}/attachments/{attachment_id}` (`backend/app/modules/clients/router.py:549`). The path and the response kind both differ.
- README:11 (`service.py` holds member numbers) vs YAML. YAML declares `PUT /clients/{client_id}/member-number` (`openapi-people.yaml:429-430`). Code registers `POST` (`router.py:101`).
- `PATCH /client-location-settings/{location_id}` in YAML (`openapi-people.yaml:928-930`, `updateClientLocationSettings`) is `PUT` in code (`router.py:226`). The README does not mention the route.
- README:87 names `getClientPhoto` and the attachment operations, but `openapi-people.yaml` has no `getClientPhoto` (only `PUT` and `DELETE` on `/clients/{client_id}/photo`, lines 292-326), no `listClientNoteAttachments`, `uploadClientNoteAttachment` or `deleteClientNoteAttachment`, and no `getClientTimeline`. Code: `router.py:530,535,540,554,468`.
- README:56 says portal GET ids differ from the YAML ids and gives the reason, but it does not list them. Five differ: `portalListActableClients`, `portalGetClient`, `portalGetEmergencyContacts`, `portalListRelationshipTypes` and `portalListRelationships` (YAML lines 1262, 1291, 1383, 1467, 1496) against `listPortalActableClients`, `getPortalClient` and so on in `backend/openapi.json`.

### [missing]

- YAML `portalGetMemberCard` (`GET /portal/clients/{client_id}/member-card`, `openapi-people.yaml:1440`) has no route in the clients router or anywhere else. README:48-50 says the API has a member card "in `access`", but `access/router.py:285-297` serves `/portal/app-cards`, which is a different path. README:49 should name that path and say the YAML route is unbuilt.
- YAML `portalSetClientPhoto` (`PUT /portal/clients/{client_id}/photo`, `openapi-people.yaml:1348`) has no route. README:48 lists portal photo edit as not built, but code ships the setting `is_portal_photo_edit_enabled` (`models.py:402`, `service.py:196`) without saying it has no effect yet.

### [stale-not-built]

No drift detected. The "Not built" list (README:46-50) matches the code: no webcam or portal photo route, no `createClientExport` route, no web portal member-card page (`web/src/app/App.tsx:264` has a staff-only card page), and `service.py:78-79` still lacks the booking clause.

### [undocumented]

- Migration `1982_clients_birth_on_unverified.py` is not in the README:4-5 migration list. It adds `client.is_birth_on_unverified` (`models.py:201`, `schemas.py:106`).
- The flag has no README entry. README:66 says only that the portal may set `birth_on` while it is blank. The code also flags that first portal-entered date for staff review (`service.py:781,832`; `households.py:536-537`).
- README:17-24 (internal interface) omits `service.possible_duplicates` (`service.py:1085`; it is described only at README:110), `create_self_service` (`service.py:1182`) and `terms.acknowledge` (`terms.py:21`). Also omitted: `find_by_primary_email` (`service.py:1249`; it appears only in the imports paragraph, line 42) and `matchable_addresses` (`service.py:1115`).
- README:44 states that an imported client's event carries `source: "import"`. The code also sets `source: "guest"` for `created_via=registration` (`service.py:797`), which is not documented.
- The README does not describe the clients routes it never names: `GET /clients/{client_id}/timeline` (`router.py:468`) and `POST /public/email-verifications/confirm` (`router.py:373`). The latter is in `openapi-programs.yaml:4146`, not in the people YAML.
- `permissions.py:24-39` registers `client.export`, `client.merge`, `consent.update` and `config.manage`. The README documents the keys only for photos and attachments (lines 90-93), not the rest of the catalogue.

### [wording]

- README:19-20 says `is_minor` "takes the age of majority as an argument". That is correct (`service.py:1037`). The tenant-setting lookup with default 18 lives in `households._is_minor` (`households.py:259-263`), as the README implies, but the README does not name that function.
- README:115-116 gives `created_via=portal|registration`. `create_self_service` accepts any string and treats every non-`portal` value as the `registration` context (`service.py:1196`). `_create` receives the raw `created_via` value, so nothing validates it.
- README:98-101 says erasure and replace purge file bytes through `platform.files.remove`. The comment at `merge.py:381` says the bytes "wait for K1", which contradicts that. `files.py:134-141` does call `files.remove`, so the comment is the stale part.
- README:26-32 says that for each table with a client foreign key, no table is exempt from the meta-test. The test exempts `data_subject_request` (`tests/test_activity_merge.py:20,42-43`).
