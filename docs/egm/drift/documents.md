## backend/app/modules/documents/README.md (checked against docs/api/openapi-people.yaml)

Refreshed 2026-11-13 against the current worktree (README after ADR 0013, `service.py`, `router.py`, `events.py`, `permissions.py`, `models.py`, `rentals/service.py`, `memberships/service.py`, `backend/app/core/api.py`, `docs/api/openapi-people.yaml`). This replaces the earlier report.

- [undocumented] Terms acceptances are exported with the subject and moved to the survivor on a client merge (`documents_terms` handlers, `backend/app/modules/documents/service.py:1398-1405`; export at `:1394`). The README's terms section (lines 94-104) names only the erasure retention.
- [undocumented] The audit key `documents.terms.accept` (`service.py:1274`) and `portal_terms_version` (`service.py:1230`, the shared builder behind the public terms and `record_terms_acceptance`) are not in the README.
- [undocumented] `terms_acceptance` and `TermsSaleKind` (`models.py:388-414`) are not in the file table or the migration line (line 5 cites only `0202_documents_core`). The table is created by `1501_portal_entry_and_accounts`.
- [undocumented] `is_agreement` (`service.py:584`) and `is_signed` (`:590`) are internal helpers used by `memberships.bind_agreement` (`memberships/service.py:974-975`, `:979`). The internal interface list (README lines 22-28) names neither, and nothing mentions DOC-11 or that memberships calls the permission-checked `load_document` directly (`memberships/service.py:973`).
- [undocumented] `is_agreement` and `is_signed` take a raw document or id and check no scope. `is_signed` is called with `contract.client_document_id` (`memberships/service.py:979`), which is not loaded through a gate. The README does not say callers must have loaded the document.
- [no tests] Neither helper is referenced under `backend/app/modules/documents/tests/`. They are covered only through the memberships agreement tests, and no documents test pins `is_agreement` returning False for a paper upload, a non-`agreement` kind or `is_waiver=true`.
- [wording] The README's terms section (line 97-98) says the recorder is called "before `secure_online_checkout`" for every portal sale. The wording is accurate, but the `PortalTermsOut.terms_version_id` field is only described in the schema comment (`schemas.py:302`), not as a change to the public response shape.
- [contract naming] The spec's `portalGetConsentState` (`docs/api/openapi-people.yaml:3214`) is implemented as `getPortalConsentState` (`router.py:308`). The README names the `portalGet*` rename generically (lines 78-80), so this specific case is a minor gap.
- [contract, known gap] The spec defines `listClientsMissingDocument`, `createDocumentBulkSend`, `listDocumentBulkSends` and `getDocumentBulkSend` (`openapi-people.yaml:3117`, `:3131`, `:3144`, `:3158`). None is in `router.py`. The README's Known gaps cover this (DOC-07), so it is documented drift.
- [link suggestion] The README has no pointer to `docs/api/openapi-people.yaml`, to ADR 0013, or a "Callers" line listing memberships, packages, programs, rentals and `memberships.bind_agreement`. Adding them would make future drift checks cheaper.

Backlog entries:

- documents: README omits terms-acceptance export and merge repoint, the `documents.terms.accept` audit key, `portal_terms_version`, and the `terms_acceptance` table and migration 1501. Docs only.
- documents: README omits `is_agreement` and `is_signed` and the caller-must-load rule. Docs only. Add a documents test for `is_agreement` and `is_signed`.
- documents: README should link the OpenAPI file and ADR 0013. Docs only.

Fixed since the last report and dropped: rentals now calls `requirements_for`, `ensure_pending` and `consume` in `sell_plan` and `portal_buy_plan` (`rentals/service.py:1650,1652,1665`, ADR 0013), matching README lines 25-29. Rentals' portal booking confirm also ends in `secure_online_checkout` (`rentals/service.py:1458`), so the old "rentals take payment directly" wording finding no longer applies. Earlier fixed items stay fixed: the four exempt upload routes (`core/api.py:237-242`), S3 and malware scan, `events.py`, the `bulk_request` key, `settings_row` and the `sweep_documents` docstring.

No other operation-id drift was found: every implemented route matches a spec operation, allowing for the documented renames.
