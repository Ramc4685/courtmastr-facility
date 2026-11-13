## backend/app/modules/documents/README.md

Checked against `git diff aa20e1b..HEAD -- backend/app/modules/documents` (Phase 11, SSP-14) and the current tree.

Phase 11 drift (new):

- [undocumented] Terms acceptances are kept on erasure, exported with the subject, and moved to the survivor on a client merge (`documents_terms` handlers, `backend/app/modules/documents/service.py:1367-1387`). The README's new section (lines 87-96) names none of these behaviours.
- [undocumented] The audit key `documents.terms.accept` (`service.py:1255`) and the new `portal_terms_version` function (`service.py:1211`, the shared builder behind `public_portal_terms` and `record_terms_acceptance`) are not in the README.
- [undocumented] `terms_acceptance` and `TermsSaleKind` (`models.py:388-414`) are still not in the file table (README line 9) or the migration line (line 5, which cites only `0202_documents_core`). The table is created by `1501_portal_entry_and_accounts`.
- [wording] README line 91-92 says every portal sale calls the recorder "before `secure_online_checkout`", rentals included. Rentals never use `secure_online_checkout`. `rentals/service.py:1449` calls `clients.terms.acknowledge` and then takes payment directly. The other three (`memberships/service.py:2018`, `packages/service.py:1234`, `programs/checkout.py:182`) do precede `secure_online_checkout`.
- [wording] `PortalTermsOut.terms_version_id` is only in the schema comment (`schemas.py:302`). The README doesn't say the public terms response shape changed.

Older drift, still present:

- [missing] README lines 25-26 say selling contexts (memberships, packages, programs, rentals) call `requirements_for` / `ensure_pending` / `consume`. Rentals calls none of them (no matches in `rentals/service.py`). A rental type has no document gate. Only the terms hook reaches rentals.
- [wording] Lines 52-53 say the paper-scan route is the only one the body-limit middleware exempts. `BodyLimitMiddleware.UPLOAD_PATHS` also exempts `/clients/{id}/photo`, `/client-notes/{id}/attachments` and `/import-jobs/{id}/source` (`backend/app/core/api.py:237-242`).
- [wording] Lines 16 and 45-46 describe local-disk storage only, and say downloads stream "because the local-disk adapter cannot sign URLs". An S3 adapter with presigned GETs now exists (`backend/app/adapters/s3_storage.py`). Streaming is still what documents does, but the stated reason only applies to local disk.
- [undocumented] `platform/files.py` also runs the malware scanner and refuses with `file-infected` (`backend/app/modules/platform/files.py:102`). Line 17 doesn't mention scanning.
- [undocumented] `settings_row` is used outside the module (`memberships/service.py:137,148`, defined at `documents/service.py:75`) and is not in the internal interface list (lines 22-24).
- [undocumented] `events.py` is not in the file table (lines 7-14). It emits `documents.document.sent`, `.accepted`, `.declined` and `.expired` (`events.py:15-28`). The README names no events.
- [undocumented] `permissions.py:19` registers `documents.document.bulk_request` for the unbuilt DOC-07. The README doesn't note that the key exists unused.
- [wording] The `sweep_documents` docstring says "Nothing schedules it yet (no scheduler in the kernel)" (`service.py:1300`), but `app/scheduler.py:22` enqueues it hourly and the README (line 66) says so. The code comment is the stale side.

## Backlog entries

- documents: README omits terms-acceptance retention, merge repoint, export, the `documents.terms.accept` audit key, `portal_terms_version` and the `terms_acceptance` table/migration 1501 (`service.py:1211,1255,1367-1387`; `models.py:388-414`). Docs only.
- documents: README says rentals call `secure_online_checkout` after the terms hook. They call `take_payment` (`rentals/service.py:1449`). Docs only.
- documents: README says rentals use the document gate (`README.md:25-26`). They don't. Either wire it or fix the text.
- documents: stale `sweep_documents` docstring (`service.py:1300`). One-line code fix.
- documents: README gaps on S3 storage, malware scan, upload path list, `settings_row`, events and the `bulk_request` key. Docs only.
