# Deploying on Fly.io (outline)

Status: **not deployed, not tested on Fly.** No account action has been taken. This page says what maps to what so the
owner can price it and decide. Example config: `infra/fly/fly.toml`. Pipeline: `.github/workflows/deploy.yml`
(manual, skeleton).

## What maps to what

| Piece | On Fly |
|---|---|
| Backend image, four processes | one app, process groups `api`, `worker`, `relay`, `scheduler` (`infra/fly/fly.toml`) |
| Proxy + web build (Caddy) | a second app from the web image, the only public one; `SITE_ADDRESS=:8080` and Fly's edge terminates TLS (a site address with only a port makes Caddy serve plain HTTP) |
| Postgres 16 with RLS | Fly's managed Postgres offering, or a self-run Postgres app on a volume. The backup role needs BYPASSRLS; check the offering allows creating roles with it and the `btree_gist`, `citext`, `pg_trgm` extensions (migrations create them) |
| Redis (queue, rate limits) | Upstash Redis through Fly, or a Redis app on a volume with append-only persistence |
| Object storage | Tigris bucket (S3-compatible): `storage.adapter: s3`, endpoint and keys from `fly storage create` output; turn on versioning |
| ClamAV | a third small app from the `clamav/clamav-debian` image, reached at `<app>.internal:3310`; it needs enough memory for the signature database and a volume (or a slow first start every time) |
| Secrets | `fly secrets set` on the backend app |
| Config overlay | `[[files]]` in `fly.toml` puts `app.production.yaml` in place |
| Logs | `fly logs`, or ship to an external collector (monitoring.md) |

## Things that must be true before a go-live

1. The proxy's client-IP handling is verified on Fly. Fly's edge adds its own forwarded headers in front of Caddy:
   confirm what `X-Forwarded-For` the API receives and set `api.trusted_proxies` to the range that makes `core/api.py::_ip`
   return the real client address (rate limits and the staff IP allow-list depend on it). **Untested.**
2. The deploy workflow's migrate and deploy steps are placeholders; fill them in for the commands you choose.
3. `api.trusted_proxies`, `app.web_base_url`, `email.smtp_*` (a real mail relay) and `payments.provider` are set in the
   overlay. Production refuses to start with the fake payment processor, insecure cookies or no malware scanner.
4. Certificate and DNS: the public host name points at the proxy app.
5. Backups: `infra/backup/backup.sh` on a schedule from somewhere with Postgres access, writing to storage that is not
   the database host; a weekly `drill.sh`; bucket versioning on.

## Cost drivers (look prices up, do not trust any number here)

Always-on machines (two API machines, one worker/relay/scheduler machine, one proxy machine, ClamAV: count them and their
memory), the Postgres tier and its storage and replicas, Redis, Tigris storage and requests, volumes and snapshots,
outbound data transfer, and any dedicated IPv4 address. Current prices: <https://fly.io/docs/about/pricing/> and the
pricing pages linked from it for managed Postgres, Upstash and Tigris.

## Availability notes

99.9% a month (monitoring.md) needs at least two API machines in separate failure domains, health checks wired as in
`fly.toml`, and a database with a standby. A single-machine Postgres on one volume cannot meet it.
