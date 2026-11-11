# Phase 8, chip O1: operations baseline

Branch `claude/p8-o1-ops-dd611f`, cut from `claude/phase8-wave7-5be825`. Nothing pushed, nothing deployed, no cloud
account touched. Covers the cloud-neutral part of PLT-15, REL-01 and ONB-04. Docs: `docs/ops/`.

## Built

| Piece | Where |
|---|---|
| Backend image (one image; commands `api`, `worker`, `relay`, `scheduler`, `migrate`, `s3-init`, `cli`), multi-stage, python:3.12-slim pinned by digest, uid 10001, no secrets, healthcheck | `infra/docker/backend.Dockerfile`, `entrypoint.sh`, `healthcheck.py`, `s3-init.py` |
| Web image: Vite build served by Caddy (also the reverse proxy), pinned by digest, uid 10001, healthcheck | `infra/docker/web.Dockerfile`, `infra/proxy/Caddyfile` |
| Whole-stack Compose (proxy, api, worker, relay, scheduler, migrate, Postgres, Redis, RustFS S3 stand-in, ClamAV, optional Mailpit) on its own project `fhstack`, network `172.29.77.0/24`, volumes and ports (18443, 18080, 19000, 18025); read-only root filesystems, all capabilities dropped; the DB owner password reaches only `migrate` | `infra/docker/compose.stack.yml`, `config/app.production.yaml`, `stack.env.example` |
| Proxy: automatic TLS, HSTS, strict SPA CSP, nosniff, referrer, frame, COOP and permissions headers, 1 MiB API body cap with the 21 MiB upload exception, slow-client timeouts, compression, SPA fallback, `/api` upstream with active health checks, `X-Forwarded-For` set from the socket peer; `api.trusted_proxies` is the proxy's pinned `/32` | `infra/proxy/Caddyfile` |
| Health: `/api/v1/health/live` and `/ready` already existed and were already in `test_security.py`'s anonymous list. Added the missing readiness test (red with Redis down, nothing leaked) | `backend/tests/test_health.py` |
| Backup, restore and restore drill (encrypted logical dump with RLS policies, grants and fh_* roles, snapshot-consistent row and RLS facts, retention by count) | `infra/backup/` |
| Monitoring signals with thresholds, 99.9% monthly SLO and error budget, log-based (no `/metrics`, reasons given) | `docs/ops/monitoring.md` |
| Runbook: start, stop, migrate, roll back, restore, rotate secrets, requeue dead letters | `docs/ops/runbook.md` |
| Changelog, and a "What's new" page linked from the account menu (static build-time import, Vitest, tokens, labelled lists) | `CHANGELOG.md`, `web/src/lib/changelog.ts`, `web/src/features/platform/WhatsNewPage.tsx` |
| Deploy workflow skeleton (manual; build, Trivy scan, gated migrate, gated deploy placeholders that do nothing without `DEPLOY_ENABLED`), Fly example, Fly and AWS outlines | `.github/workflows/deploy.yml`, `infra/fly/fly.toml`, `docs/ops/deploy-fly.md`, `deploy-aws.md` |
| Makefile (appended): `stack-up`, `stack-smoke`, `stack-down`, `backup-drill` | `Makefile` |

Why Caddy rather than nginx: TLS issuance and renewal are built in (ACME, or an internal CA for localhost), one short file,
no certbot or cron.

## Evidence

**Stack through the proxy** (`infra/docker/smoke.sh`, 31 checks, `SMOKE PASS`). All services reported healthy first.
The web shell loads, `/sign-in` serves the shell (SPA fallback), the hashed asset is `immutable`; a 2 MiB JSON body is
refused with 413; an invitation was emailed through Mailpit, accepted and signed in through the proxy, and `/me` works
with the cookie; a client-supplied `X-Forwarded-For: 203.0.113.9` was not believed (the session row holds the proxy's
view of the peer, `172.29.77.1`); a PNG uploaded through `PUT /client-documents/{id}/paper-scan` (ClamAV scan, S3
write) came back from the download route as the cleaned PNG (`files.clean` re-encodes, so bytes are not identical by
design); a 3 MiB body to the upload route passes the proxy cap and a 22 MiB body is refused; with Redis stopped
readiness is 503 with `{"status":"unavailable","checks":{"postgres":"ok","migrations":"ok","redis":"failed","outbox_relay":"ok"}}`
and recovers when Redis starts.

Header check, `GET /` (page) and `GET /api/v1/health/live` (API), through the proxy:

```
GET /                                       GET /api/v1/health/live
strict-transport-security: max-age=31536000; includeSubDomains   (both)
x-content-type-options: nosniff                                   (both)
x-frame-options: DENY                                             (both)
referrer-policy: no-referrer                                      (both)
cross-origin-opener-policy: same-origin                           (both)
permissions-policy: camera=(self), microphone=(), geolocation=(), payment=(self)   (both)
content-security-policy: default-src 'none'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline';
  img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; manifest-src 'self'; worker-src 'self';
  form-action 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'          (page)
content-security-policy: default-src 'none'; frame-ancestors 'none'                        (API, its own)
cache-control: no-cache  (page)             cache-control: no-store  (API)
no Server header
```

The stack was then torn down: containers, the `fhstack_*` volumes and network, both built images, the three base images I
pulled and the build cache are removed; the pre-existing images were left alone. Free disk stayed above 65 GB throughout.

**Restore drill** (`make backup-drill`, the lane database `facilityhub_o1` with the demo seed, through the dev Postgres
container; scratch database dropped afterwards):

```
PASS  restore completed
PASS  migration head 1220 matches the backup manifest
PASS  migration head equals the code's head (1220)
PASS  row counts equal on all 217 tables (1158 rows)
PASS  RLS intact: 213 tables forced, 213 policies, same as the backup
PASS  fh_app with no tenant selected reads no rows from any of the 213 RLS tables
DRILL PASS (scratch database fh_drill_... dropped)
```
A wrong passphrase makes the drill fail cleanly (`FAIL restore`, `DRILL FAIL`).

**Image scan** (Trivy, HIGH and CRITICAL with a fix): backend image clean. Web image: one HIGH in the pinned Caddy binary
(CVE-2026-78661, `golang.org/x/net/html`, fixed in 0.62.0); no patched `caddy:2-alpine` existed on 2026-11-11 and Caddy does
not parse untrusted HTML, so it is a dated, reviewed exception in `.trivyignore` (revisit by 2026-12-11).

**Gates in the lane**: `make lint` clean. `make test`: 4,189 passed, 2 failed, 2 skipped. The Stripe test failed only because the `.env` copied from the main checkout carried Stripe test keys; with those lines removed from the lane `.env` it passes. The other failure is `test_fifteen_hundred_linked_occurrences_commit_through_the_worker` (K3's known timing flake: 124 s in the full run, 190 s on its own, on a machine shared with a dozen lanes); O1 changes nothing in scheduling. `make web-check` clean; `make web-test` 140 passed (32 files).

## Review findings fixed

The automated security review of the first commit found three issues; all addressed. `restore.sh` runs only `fh_*` role
statements from the archive (no psql meta-commands or other SQL), stops on any role error, and validates the owner name;
the compose file gives the DB owner password only to `migrate`, and S3 keys only to `s3-init` and the app services.
Accepted limit: the archive is encrypted (AES-256-CBC, PBKDF2) with checksums inside the encrypted manifest but is not
signed, so anyone holding the passphrase can forge one; the passphrase is as sensitive as the database.

## Deferred or not verified

- **Browser check of the strict CSP.** The built-in browser rejected Caddy's local CA, and I did not bypass that. Verified by
  inspection instead: the built `index.html` has one module script and one stylesheet, no inline script, no external URL.
  Someone should load the stack in a browser that trusts the Caddy local CA (`docker cp` the root certificate out of the web
  container's `/data/caddy/pki`) and confirm no CSP violations in the console.
- **Tenant host routing.** Tenants resolve from `slug.<base_domain>`. The proxy's site address is a single name, so
  subdomains need a wildcard DNS record and wildcard certificate (DNS-01 ACME) in a real deployment, or the web client's
  `X-Tenant-Slug` header. The smoke test uses the header. Decide before go-live.
- **No environment overrides in `core/settings.py`** for the DB host, Redis URL and so on; a cloud deployment supplies an
  overlay file. A small override layer would remove that step (backend change outside this chip).
- **No `/metrics` and no scheduler heartbeat**; signals come from logs, probes and SQL (monitoring.md lists the gap).
- **`FH_DATA_KEY` rotation** has no re-encryption path.
- **Client IP behind a platform edge (Fly, an AWS load balancer)** is untested; the proxy-to-API chain is verified only
  with Caddy as the first hop.
- **The deploy workflow was not run**, and its migrate and deploy steps are placeholders. Bucket versioning on the S3
  stand-in is attempted by `s3-init`; whether RustFS honours it was not checked.
- Backups are scripts, not scheduled; scheduling depends on the host (cron, a scheduled task).

## What the owner must decide or provide to go live

1. The host: Fly.io or AWS (cost), and a region.
2. A domain name, and whether tenants get subdomains (wildcard certificate) or the header approach.
3. A real mail relay (SMTP host and credentials) and a from-address on a verified domain.
4. Stripe live keys when payments go live (production refuses the fake processor).
5. Where backups are written, who holds `FH_BACKUP_PASSPHRASE` and `FH_DATA_KEY`, and the alert destination (email, SMS or chat).
6. Whether to accept the Caddy scan exception until a patched release ships.
