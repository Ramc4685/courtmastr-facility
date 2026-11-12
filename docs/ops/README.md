# Operations

How the platform is packaged, run, watched and recovered. Provider-neutral: nothing here needs a particular cloud.
Hosting is the owner's call (Fly.io or AWS, chosen on cost, possibly switched later); no deployment exists yet.

| Document | What it covers |
|---|---|
| [runbook.md](runbook.md) | start, stop, migrate, roll back, restore, rotate secrets, requeue dead letters |
| [monitoring.md](monitoring.md) | what to alert on and the thresholds, the 99.9% monthly target and its error budget |
| [performance-budget.md](performance-budget.md) | the load test, p95 budgets per request class, measured latencies, hot spots |
| [deploy-fly.md](deploy-fly.md), [deploy-aws.md](deploy-aws.md) | one-page outlines: what maps to what, cost drivers, what is still open |

## What is in the box

- **Images.** `infra/docker/backend.Dockerfile` (one image; the command picks `api`, `worker`, `relay`, `scheduler`,
  `migrate`, `s3-init`, `cli`) and `infra/docker/web.Dockerfile` (the Vite build served by Caddy, which is also the
  reverse proxy). Pinned base images by digest, non-root user, no secrets baked in, healthchecks.
- **Stack.** `infra/docker/compose.stack.yml` runs everything on one machine under its own project name (`fhstack`),
  network, volumes and ports, so it cannot collide with the dev Compose. `make stack-up`, `make stack-smoke`,
  `make stack-down`.
- **Proxy.** `infra/proxy/Caddyfile`. Caddy rather than nginx: automatic TLS with renewal and one small file.
  Sets HSTS, a strict CSP for the SPA (the API sends its own deny-all CSP), `nosniff`, referrer, frame and
  permissions headers; caps API bodies at 1 MiB with the one upload route allowed 21 MiB (mirrors
  `core/api.py` `BodyLimitMiddleware.UPLOAD_PATHS`); slow-client timeouts; compression; SPA fallback; `/api` to the
  API. It sets `X-Forwarded-For` to the socket peer, and the app trusts only the proxy's address
  (`api.trusted_proxies`, see `core/api.py::_ip`). In a cloud deployment put the proxy's network CIDR there.
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
