# Monitoring and alerting

No vendor is assumed. Everything below is read from three sources every host already has: the **structured JSON
logs** the API and workers write to stderr, **HTTP probes** of the health endpoints, and **two small SQL/Redis
queries**. Ship the logs to whatever collector the hosting provider offers (Fly logs, CloudWatch, Loki, a file) and
express the alerts in that tool.

## Why no `/metrics` endpoint

A Prometheus endpoint would need a new dependency, per-process aggregation across uvicorn and Dramatiq workers, and a
decision about who may scrape it. The request log already carries everything an API dashboard needs
(`status`, `duration_ms`, `path`, `tenant_id`), and the rest is a probe or a query. If a metrics stack is adopted
later, add the endpoint then, bound to an internal port.

## The service level objective

**Target: 99.9% of each calendar month.** A goal, not a contract.

- Availability SLI: the share of one-minute external probes of `GET /api/v1/health/ready` that return 200
  (`ok` or `degraded`). Probe from outside the platform, from at least two locations, every 30 seconds.
- Error budget: 0.1% of a 30-day month is **43 minutes 12 seconds** of failed minutes (about 43.8 minutes in an
  average month). A 31-day month gives 44.6 minutes.
- Spending policy: more than half the budget gone before mid-month freezes risky releases; a spent budget means only
  fixes ship until the month rolls over.
- Burn-rate alerts (page when the budget would run out too soon): 14x the allowed error rate for 1 hour, or 6x for
  6 hours. Ticket at 1x over 3 days.
- Planned maintenance counts against the budget unless the proxy serves a maintenance page; there is no multi-region
  failover in this design, so a single-region provider outage is also budget spent.

## Signals

| Signal | Source | Warn | Page |
|---|---|---|---|
| Readiness | probe `GET /api/v1/health/ready`; 503 means Postgres, Redis or the migration head is wrong | `degraded` for 10 min (outbox relay behind its 300 s lag SLO) | 503 on 2 consecutive probes (60 s) |
| Liveness | probe `GET /api/v1/health/live`, and the container healthchecks | a container restarts | no answer for 2 min |
| 5xx rate | request log: `status >= 500` over all requests, 5-minute window | above 1% | above 5% |
| p95 latency | request log `duration_ms`, 5-minute p95, excluding `/api/v1/docs` | above 800 ms | above 2,000 ms |
| 4xx anomalies | request log: `401`/`403`/`429` per minute | `429` above 50/min (someone is hammering sign-in) | none; investigate on warn |
| Queue depth | Redis `LLEN dramatiq:default` (and `dramatiq:<queue>` for any other queue) | above 500 for 10 min | above 5,000 or rising for 30 min |
| Dead letters | open rows in `failed_job`: `SELECT count(*) FROM failed_job WHERE resolved_at IS NULL` (run per tenant, or as `fh_platform`) | any row older than 1 h | above 25, or a burst of 10 in 5 min |
| Scheduler heartbeat | the scheduler enqueues `expire_checkout_holds` every minute for every active tenant; alert when the worker log shows none for 5 min. There is no explicit heartbeat yet (see Gaps) | none logged for 5 min | none logged for 15 min |
| Outbox lag | readiness `outbox_relay` check, or `SELECT now() - min(occurred_at) FROM outbox_event WHERE published_at IS NULL` | above 60 s | above 300 s (readiness turns `degraded`) |
| Backup age | newest object in the backup location | older than 26 h | older than 50 h, or a failed restore drill |
| Restore drill | `infra/backup/drill.sh` exit status, run weekly | any FAIL | two weekly FAILs in a row |
| Disk | database volume, backup volume and host root | above 75% | above 90%, or fewer than 7 days to full at the current growth |
| Certificate expiry | `openssl s_client -connect host:443 -servername host \| openssl x509 -noout -enddate` from outside | under 21 days (Caddy renews at 30 days left, so this means renewal is failing) | under 7 days |
| Database connections | `SELECT count(*) FROM pg_stat_activity` against `max_connections` | above 70% | above 90% |

Request-log lines look like `{"ts": ..., "level": "INFO", "logger": "app.request", "msg": "request", "trace_id": ...,
"method": "GET", "path": "/api/v1/me", "status": 200, "duration_ms": 12.4, "tenant_id": ..., "principal_id": ...}`.
They carry ids only, never email addresses, names or payloads (overview 3.17). Job failures arrive as `ERROR` lines
from the worker and as rows in `failed_job`.

## Gaps worth closing later

- **Scheduler heartbeat.** The scheduler logs only `scheduler started`. A log line per tick (or a Redis key with a
  60-second TTL that the tick refreshes) would make the signal exact. Small change in `app/scheduler.py`; outside this
  chip's brief.
- **Metrics endpoint**, if a metrics stack is adopted (see above).
- **Alert routing**: choose the destination (email, SMS, a chat webhook) when the host is chosen.
