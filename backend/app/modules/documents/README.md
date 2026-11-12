# documents

Waivers, agreements and consent: versioned templates, issued documents with signatures and evidence, emailed
single-use links, bindings to plans and programs, the waiver indicator, paper uploads and the signed PDF.
Build module 7. Feature status: `docs/status/07-waivers-documents.md`. Migration `0202_documents_core`.

| File | What it holds |
|---|---|
| `models.py` | data-model-people section 2: templates and versions, bindings, `client_document`, `document_acceptance` (append-only evidence), deliveries, the `client_document_status` projection, tenant and location settings |
| `domain/content.py` | The rich-text allow-list (nh3), merge fields, the evidence hash |
| `domain/signing.py` | Signer roles per version, who must sign (guardian for minors), how decisions add up |
| `domain/pdf.py` | The PDF of the signed record (fpdf2), from the stored snapshot only |
| `service.py` | Every command and query, the internal interface, sweeps, merge and erase handlers |
| `router.py` | Staff and portal routes; a `public` router for the emailed link and portal terms |

Files go through `app/ports/storage.py` (local-disk adapter `app/adapters/local_storage.py`, root
`storage.local_dir`) and the `stored_file` table in `platform/files.py`, which sniffs the type, re-encodes images
and refuses mismatches (security-baseline 8).

## Internal interface (no permission check; ADR 0009 section 9)

`requirements_for(session, scope_type, scope_id, client_id, online=, source=)`, `ensure_pending(session,
binding_id, client_id, location_id)`, `consume(session, document_ids, (context, type, id))`, `status_for(session,
client_ids)`, `has_valid_waiver(session, client_id)`, `refresh_status`, `issue(...)`, `run_sweeps(session)` and the
queued `sweep_documents` actor. Selling contexts (memberships, packages, programs, rentals) call
`requirements_for` before checkout, `ensure_pending` to present the document, and `consume` when the sale completes
so an `every_purchase` binding asks again next time. `scope_id` is opaque here: the owning context validates it.

## Decisions and assumptions

- **Sanitised on write, sanitised on render.** Bodies are cleaned with nh3 when a draft is saved (no images, links
  https/mailto/tel only, `rel` forced) and again with DOMPurify in the browser (`components/SanitizedHtml.tsx`, the
  only component allowed to use `dangerouslySetInnerHTML`; ESLint enforces it). `sanitizer_version` lets a tighter
  policy apply to old versions on read.
- **The evidence is the snapshot.** Issuing merges the current version into `client_document.body_html` and
  `acceptance_text` (values HTML-escaped) and hashes them; every signer must send that `content_sha256` back
  (`content-mismatch` otherwise). Each acceptance row stores signer, role, method, typed name or drawn image,
  server time, IP, user agent, the hash and the witnessing staff user. The template version hash is in the PDF.
- **Guardians.** A version lists signature blocks (client, guardian, co_signer). For a minor (age from the
  template, default under 18) the guardian's signature is required instead of the client's. A guardian on file
  (an active guardianship relationship) must sign as that client; staff may record a named guardian only when none
  is on file. Through the emailed link the guardian is the one whose confirmed address received it.
- **Drawn signatures are inline**, base64 PNG of at most about 300 KB in the acceptance body, re-encoded and stored,
  instead of the spec's separate `signature_file_id` upload.
- **Downloads stream** from `GET .../file` with the caller's session (`Content-Disposition: attachment`, nosniff,
  no-store) instead of returning a signed URL: the local-disk adapter cannot sign URLs.
- **Emailed links**: token in the URL fragment, posted in the body, stored as a hash, single use (any decision
  consumes it), superseded by a resend (410 `token-superseded`), expiry from `document_settings` (default 48 h),
  sent only to confirmed addresses of the client or a guardian. The public routes are rate limited and carry no
  Idempotency-Key: a replayed decision gets 410.
- **Uploads to a profile**: create a document without a template (a title, `acceptance_method: paper`), then
  `PUT /client-documents/{id}/paper-scan` with the raw bytes (PDF, JPEG or PNG up to `storage.max_upload_bytes`,
  20 MiB; the body-limit middleware exempts only this route). A paper copy marks the document accepted with a
  `paper` evidence row witnessed by the uploader; clearing the flag returns it to pending.
- **Deleted** means soft-deleted for `deleted_recovery_days` (default 30), restorable, then voided by the sweep.
- **Expiry** is the signing date in the location's zone plus `signature_validity_days`. The indicator applies the
  date test on every read, so it is exact even before the sweep marks the document `expired`. Renewal is a fresh
  issue of the template's current version (the web "Renew" action); the old record stays as history.
- **Operation ids**: GET operations must start with get/list (kernel rule), so the spec's `portalGet*`,
  `portalListClientDocuments` and `publicGetPortalTerms` are `getPortal*`, `listPortalClientDocuments` and
  `getPublicPortalTerms`. Schema names carry a Document prefix.

## Known gaps

- Bulk send and the missing-document audit (DOC-07, P1) are not built; `document_bulk_send` does not exist.
- `app/scheduler.py` enqueues `sweep_documents` hourly per tenant; between runs indicator reads stay correct,
  while stored statuses and stale links lag.
- `is_staff_notified_on_decision` is stored but no staff notification is sent yet (engagement owns that channel).
- Signed documents of an erased client are retained (legal hold, security-baseline 4.3) without a restricted view.
- The PDF uses built-in Latin-1 fonts: other scripts print as "?" (see the shortcut note in `domain/pdf.py`).
- The template editor is a markup textarea with formatting buttons and a live sanitised preview, not WYSIWYG.
- The IP is only recorded when the request carries a real address (the test client's does not).

## Security hardening (wave 1, P-08 to P-11)

- `listClientDocumentStatuses` skips client ids outside the caller's reach.
- Decided evidence is immutable: a paper scan on an accepted document needs `documents.document.void` (at the
  document's location), replaces the file only and never rewrites `content_sha256`; returning a paper-signed
  document to pending also needs the void key.
- The signer role is derived. Portal: `client` only for the caller's own record, otherwise `guardian`. Link:
  `guardian` when the document requires one, `client` only when a recipient is a verified address of the
  client (422 at `/signer_role` otherwise). A link sent to a guardian of an adult client therefore cannot be
  signed; send it to the client.
- Portal routes return `PortalClientDocumentOut` and `PortalDocumentAcceptanceOut` (no witness, signer client,
  source, binding, deletion or stored-file ids).
