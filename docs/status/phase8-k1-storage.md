# Phase 8 chip K1: files and object storage

Branch `claude/p8-k1-storage-f89eb6`, cut from `claude/phase8-wave7-5be825`. Unblocks CLI-12, CLI-09, PLT-08,
MKT-06 and CHK-12 (security-baseline 8, overview 3.17). Details and limits: `backend/app/modules/platform/README.md`
section "Files and object storage".

## Built

- **Port** (`ports/storage.py`): `delete`, `keys` (tenant prefix listing) and `url` (time-limited direct URL, or
  None when the adapter has no origin) next to the unchanged `put`, `get`, `object_key`, `check_key`.
  `object_key(..., public=True)` gives the `t/<tenant>/public/` prefix.
- **Adapters:** `LocalStorage` gained `delete`, `keys`, `url`; new `S3Storage` (boto3; AWS S3, Fly Tigris,
  MinIO-compatible) chosen by `storage.adapter` in `config/app.yaml`, keys from `FH_S3_*` env vars only.
  boto3 health check: 1.44.0 released 2026-11-10, AWS-maintained.
- **Scanner port** (`ports/scanner.py`) with `NoopScanner` and `ClamdScanner` (INSTREAM over TCP, fails
  closed). `files.store` scans first; a hit is 422 `file-infected`. `core/settings.py` refuses `noop` outside
  dev and test (stricter than "production only", matching the other guards there).
- **`files`:** `load(session, id, purpose=)`, `remove(session, id)`, `download_url(session, id)`, `store(...,
  public=False)`, and the hourly `@tenant_actor purge_files` (one line in `app/scheduler.py`). `clean`,
  `store`, `read` keep their signatures and behaviour (store additionally scans).
- **Signed local route** `GET /api/v1/files/{tenant_id}/{file_id}?exp=&sig=` (`platform/files_router.py`),
  listed in `tests/test_security.py` `ANONYMOUS` (the signature is the credential). `make openapi web-api` run.
- **Compose:** optional profiles `storage` (service `s3`, RustFS) and `scan` (service `clamav`,
  `clamav/clamav-debian` for arm64). MinIO no longer publishes container images (`minio/minio` and
  `quay.io/minio/minio` both refuse pulls), so the S3 stand-in is RustFS, a MinIO-compatible server.
- **Web:** `components/FileUpload.tsx` (purpose, accepted types, max size, route; uses `Input` and
  `uploadFile` from `api/client.ts`; errors tied by `aria-describedby`, progress in a `role=status` region)
  with `FileUpload.test.tsx`. No screen uses it yet.
- **No migration:** the public flag is the object-key prefix and `purpose` stays free text, so `1201-1209`
  are unused. `populate()` needs no change (no new table or column).

## Deferred

- The presigned direct-to-bucket upload of 8.1 (quarantine prefix, `POST /uploads`, scan job, `rejected`
  status, 24-hour quarantine purge): uploads stay in-request under the 20 MiB body cap. `shortcut:` comment in
  `files.py`, README note. Upgrade when a surface needs larger files or API workers must stop buffering bytes.
- A public URL for `public` files and the bucket policy on `t/*/public/*` (PLT-08, chip T2).
- `nosniff` on the bucket origin: S3 presigned URLs cannot set it; the CDN or proxy in front of the bucket
  must (chip O1).
- Fixed image renditions (resize); orphan objects are reported, never deleted automatically.

## Test evidence

`backend/app/modules/platform/tests/test_files.py`, 17 tests. Baseline 8.3 `test_upload_rules` cases: type
confusion (HTML as JPEG, PNG as JPEG), oversize, decompression bomb (100-megapixel 1-bit PNG), EICAR with the
scanner on (fake scanner in the suite, real clamd when running), traversal filename, cross-tenant file id
(read, load, download_url, remove and the port), expired and forged signatures on the signed route, wrong
purpose and a `pending` file. Also: remove after commit and on rollback, purge deletes purged bytes and
reports orphans idempotently, purge on the hourly clock, production refuses the no-op scanner, image
renditions served inline. The S3 adapter test (put, get, list, presigned GET with disposition, forged and
unsigned requests refused, delete) and the clamd test (EICAR found, multi-chunk clean file) ran against the
Compose `s3` and `clamav` services in this lane; both skip when those services are not running.

Gate in the lane (2026-11-11, load average about 30 from parallel lanes): `make lint` and `make web-check`
green. Full `make test`: 3818 passed; the coverage gate passed at 92% (`files.py` 96%, the new adapters and
ports 97%). One real failure, fixed: the generated isolation test could not fill `{tenant_id}` and `{file_id}`,
so `populate()` now stores a file (`_populate_files`) and a missing `exp`/`sig` is 404, not 422. The 22 POS and
programs errors came from the shared Postgres briefly refusing connections in mid-run ("recovery state has
not been yet reached"); those 42 tests pass on rerun. After the fix, `test_isolation`, `test_security`,
`test_hardening` and `test_files` pass (2172). Still red under this load: scheduling's
`test_fifteen_hundred_linked_occurrences_commit_through_the_worker`, a 120-second budget that took 201 seconds.
K1 does not touch scheduling. `make web-test`: 134 passed; the first run had 4 failures that went away on a
rerun with no change. The whole suite was not rerun end to end after the fix (about 1.5 hours at this load).
