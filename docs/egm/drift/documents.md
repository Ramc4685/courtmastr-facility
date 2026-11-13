## backend/app/modules/documents/README.md (checked against docs/api/openapi-people.yaml)

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
- [missing] Lines 25-26 say selling contexts "(memberships, packages, programs, rentals)" call `requirements_for` / `ensure_pending` / `consume`. Rentals calls none of them; the only callers are `backend/app/modules/memberships/service.py:467,594,600,602,729,768`, `backend/app/modules/packages/service.py:573,575,655,699` and `backend/app/modules/programs/checkout.py:54,135,139,164`. A rental type has no document gate.

Refreshed 2026-11-13 against the merged working tree (README after main's EGM fixes, `service.py`, `router.py`, `events.py`, `permissions.py`, `memberships/service.py`, `docs/api/openapi-people.yaml`). This replaces the earlier report.

- [undocumented] `service.is_agreement(session, doc)` (`backend/app/modules/documents/service.py:575`) and `service.is_signed(session, doc_id)` (`:581`) are internal helpers for memberships (DOC-11), called from `memberships.bind_agreement` (`backend/app/modules/memberships/service.py:974-975`, `:979`). The README's internal interface list (lines 22-31) names neither. The README also never mentions DOC-11, binding an agreement to a contract, or the fact that memberships calls `load_document` directly (`memberships/service.py:973`), which is a permission-checked function used as if it were internal.
- [logic duplicated] `bind_agreement` computes "signed" through `is_signed` for the new document (`memberships/service.py:974`) and again for the existing one (`:979`), and `is_agreement` is called separately (`:975`). Whether a document counts as an agreement or as signed is decided in `documents` only, which is the fix for the earlier inline duplicate; but `is_signed` is reached only through memberships and has no documents-side caller.
- [no tests] Neither helper is referenced by any test under `backend/app/modules/documents/tests/`. `is_agreement` and `is_signed` are covered only indirectly, through the memberships agreement tests. `is_agreement` returns False for a document with no `template_id` (paper upload), for a template whose `kind` is not `agreement`, and for `is_waiver=true`; no documents test pins that.
- [undocumented] The ADR 0009 section 9 internal convention ("no principal, no authorize") is stated in the README, but `is_agreement` and `is_signed` take a raw `ClientDocument` or id and do not check tenant, client or location scope. That is fine only because `bind_agreement` loads the document through `load_document` first, but `is_signed` is also called with `contract.client_document_id` (`memberships/service.py:979`), which is not loaded through a gate. The README does not say callers must have loaded the document.
- [contract naming, partly undocumented] The README explains the renamed portal operation ids (lines 64-66: `getPortal*`, `listPortalClientDocuments`, `getPublicPortalTerms`). The spec's `portalGetConsentState` (`docs/api/openapi-people.yaml:3214`) is also renamed, to `getPortalConsentState` (`backend/app/modules/documents/router.py:308`). The README names `portalGet*` generically, so this is a minor gap.
- [contract, known gap] The spec defines `listClientsMissingDocument`, `createDocumentBulkSend`, `listDocumentBulkSends` and `getDocumentBulkSend` (`docs/api/openapi-people.yaml:3117`, `:3131`, `:3144`, `:3158`). None is implemented in `router.py`. The README's Known gaps (line 68) cover DOC-07 and the missing-document audit and now names the unused `documents.document.bulk_request` key, so this is documented drift.
- [link suggestion] The README has no pointer to the OpenAPI file. Adding `docs/api/openapi-people.yaml` and a short "Callers" line, including `memberships.bind_agreement`, would make future drift checks cheaper.

Fixed since the last report and dropped: the README now lists `settings_row` among the internal functions and says memberships reads waiver rules from it (`memberships/service.py:1962`, `:1964`); rentals is removed from the selling contexts and the README says it does not call the gate yet; the body-limit sentence lists all four exempt upload routes; the S3 adapter and why streaming is kept are described; the malware scan is named; `events.py` is in the file table with its four events; the `bulk_request` key is mentioned; and the `sweep_documents` docstring no longer says nothing schedules it (`service.py:1271-1272`).

No operation-id drift was found beyond the items above: every implemented route matches a spec operation (allowing for the documented renames), and the Python signatures of the two helpers are not part of the HTTP contract.
