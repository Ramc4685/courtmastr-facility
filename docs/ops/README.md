# Operations

How the platform is packaged, run, watched and recovered. Provider-neutral: nothing here needs a particular cloud.
Hosting is the owner's call (Fly.io or AWS, chosen on cost, possibly switched later); no deployment exists yet.

| Document | What it covers |
|---|---|
| [runbook.md](runbook.md) | start, stop, migrate, roll back, restore, rotate secrets, requeue dead letters |
| [monitoring.md](monitoring.md) | what to alert on and the thresholds, the 99.9% monthly target and its error budget |
| [performance-budget.md](performance-budget.md) | the load test, p95 budgets per request class, measured latencies, hot spots |
| [deploy-fly.md](deploy-fly.md), [deploy-aws.md](deploy-aws.md) | one-page outlines: what maps to what, cost drivers, what is still open |
| [production-options.md](production-options.md) | hosting comparison with prices (AWS, Fly, DigitalOcean, Render, VPS) and the go-live checklist; decision pending |

## What is in the box

- **Images.** `infra/docker/backend.Dockerfile` (one image; the command picks `api`, `worker`, `relay`, `scheduler`,
  `migrate`, `s3-init`, `cli`) and `infra/docker/web.Dockerfile` (the Vite build served by Caddy, which is also the
  reverse proxy). Pinned base images by digest, non-root user, no secrets baked in, healthchecks.
- **Stack.** `infra/docker/compose.stack.yml` runs everything on one machine under its own project name (`fhstack`),
  network, volumes and ports, so it cannot collide with the dev Compose. `make stack-up`, `make stack-smoke`,
  `make stack-down`. The first `make stack-up` writes `infra/docker/.env.stack` from `stack.env.example`, generating
  `FH_DATA_KEY` and `FH_OPERATOR_TOKEN` (the stack runs as `FH_ENV=stack`, which refuses dev or example values like
  production does);
  delete an older `.env.stack` that still holds the committed example key. It also writes a throwaway self-signed
  certificate to `infra/docker/.stack-tls/` (git-ignored) for the stack's Redis, which serves TLS only; the stack's
  Postgres serves TLS with the image's snakeoil pair. Outside dev and test the app refuses a database
  without `sslmode=verify-full` and a Redis URL that is not `rediss://` or that turns off certificate or host-name
  checks (`ssl_cert_reqs=none|optional`, `ssl_check_hostname=false`) (security-baseline V9). Only `FH_ENV=stack`,
  the local stack and explicitly not production, accepts encryption without verification, for its self-signed
  certificates (`config/app.stack.yaml`: `sslmode=require`, `ssl_cert_reqs=none&ssl_check_hostname=false`).
  A deployment (`config/app.production.yaml`) sets:
  - `FH_DB_SSLMODE=verify-full` and `PGSSLROOTCERT=<path to the provider's CA bundle>` (read by libpq, so the
    variable goes to every backend process: api, worker, relay, scheduler, migrate);
  - `FH_REDIS_URL=rediss://...` with a certificate the system trust store accepts, or
    `?ssl_ca_certs=<path to the CA bundle>` for a private CA (it may carry the Redis password, so it is a secret).
- **Proxy.** `infra/proxy/Caddyfile`. Caddy rather than nginx: automatic TLS with renewal and one small file.
  Sets HSTS, a strict CSP for the SPA (the API sends its own deny-all CSP), `nosniff`, referrer, frame and
  permissions headers; caps API bodies at 1 MiB with the one upload route allowed 21 MiB (mirrors
  `core/api.py` `BodyLimitMiddleware.UPLOAD_PATHS`); slow-client timeouts; compression; SPA fallback; `/api` to the
  API. It sets `X-Forwarded-For` to the socket peer, and the app trusts only the proxy's address
  (`api.trusted_proxies`, see `core/api.py::_ip`). In a cloud deployment put the proxy's network CIDR there; outside dev and test the API refuses to start with the list
  empty unless `api.exposed_directly: true` (no proxy at all in front).
- **Backups.** `infra/backup/` (see [runbook.md](runbook.md#restore-from-backup)).
- **Release notes.** `CHANGELOG.md`; the staff app's account menu links to "What's new", built from the same file.

## Object storage

Files live in an S3-compatible bucket (`storage.adapter: s3`), private, served by short-lived presigned URLs that carry
the stored content type and a `Content-Disposition`. Two operational rules:

- **`nosniff` on downloads.** If a CDN or proxy sits in front of the bucket, it must add
  `X-Content-Type-Options: nosniff` to file responses (security-baseline 8.3); the presigned URL fixes the content
  type but cannot force the header. Without a CDN, check that the provider already sends it.
- **Backup is a provider feature, not a script.** Turn on bucket versioning (AWS S3, Fly Tigris, MinIO all have
  it) and, for disaster recovery, replication to a second bucket in another region or account. Set a lifecycle rule
  that expires old versions after the retention you choose. The stack's `s3-init` command enables versioning on the
  local stand-in when it supports it. Restoring a file is restoring a version in the provider console.

## Known limits (see `docs/status/phase8-o1-ops.md` for the full list)

- Settings read non-secret values only from `config/app.<env>.yaml`; there are no environment overrides for the
  database host or Redis URL. A cloud deployment therefore supplies its own overlay file (see
  `infra/docker/config/app.production.yaml`). A small env-override layer in `core/settings.py` would simplify that.
- There is no `/metrics` endpoint and no scheduler heartbeat; monitoring uses logs, probes and SQL (monitoring.md).
- Tenants resolve from `slug.<base_domain>` (or the `X-Tenant-Slug` header). The Caddyfile serves one site name, so
  subdomain tenants need a wildcard DNS record and a wildcard certificate (a DNS-01 ACME challenge); decide before go-live.
- The stack's TLS certificate comes from Caddy's local CA, which browsers do not trust by default; trust the root from
  the web container's `/data/caddy/pki` for browser testing, or use curl `-k`.
