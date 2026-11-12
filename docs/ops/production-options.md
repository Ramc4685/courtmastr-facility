# Getting to production: hosting options and everything else go-live needs

Status: **decision pending, nothing created in any account.** Written 2026-11-12 to let the owner choose a host. It
builds on `deploy-aws.md` and `deploy-fly.md` (Phase 8), which map each piece onto those providers. All prices are
approximate US on-demand list prices checked in November 2026. Confirm them in each provider's calculator before
committing.

## 1. What has to run

The app is plain containers (built in Phase 8, `infra/docker/`), so any container host works. Production needs:

| Piece | What it is | Always on? | Size to start |
|---|---|---|---|
| `web` | Caddy proxy plus the built React app | yes, 2 copies for 99.9% | 0.25 vCPU, 0.5 GB |
| `api` | FastAPI | yes, 2 copies in different zones | 0.5 vCPU, 1 GB each |
| `worker` | Dramatiq jobs (emails, billing runs, PDFs, imports) | yes | 0.5 vCPU, 1 GB |
| `relay` | outbox to queue | yes | 0.25 vCPU, 0.5 GB |
| `scheduler` | clock (nightly billing, reminders, retention) | yes, exactly 1 | 0.25 vCPU, 0.5 GB |
| `clamav` | malware scanner for uploads (production refuses to start without one) | yes | 0.5 vCPU, **3 GB** (signature database) |
| `migrate` | one-shot Alembic run before each deploy | no | 0.5 vCPU, 1 GB |
| PostgreSQL 16 | needs `btree_gist`, `citext`, `pg_trgm`, a role with BYPASSRLS for backups | managed, with a standby for 99.9% | 2 vCPU, 2 GB |
| Redis / Valkey | queue and rate limits | managed | smallest node |
| Object storage | photos, documents, PDFs, backups | S3-compatible, versioned | pay per GB |

## 2. Option A: AWS (recommended)

This is the layout in `deploy-aws.md`: ECS on Fargate (ARM/Graviton) behind an Application Load Balancer, RDS for
PostgreSQL Multi-AZ, ElastiCache, S3, ECR, Secrets Manager, CloudWatch, Route 53 and ACM. Email is SES (decided
separately), so everything sits on one bill and one account.

### Launch (first 1 to 10 facilities, meets the 99.9% target)

| Item | Sizing | ~ per month |
|---|---|---|
| Fargate tasks (ARM) | api ×2, worker, relay, scheduler, web ×2, clamav (see section 1) | $92 |
| Application Load Balancer | 1, light traffic | $22 |
| NAT gateway | 1, so private tasks can reach Stripe, SES and Expo | $35–45 |
| RDS PostgreSQL | db.t4g.small Multi-AZ, 20 GB gp3 | $52 |
| ElastiCache Valkey | cache.t4g.micro | $12 |
| Public IPv4 addresses | load balancer ×2 | $7 |
| CloudWatch logs and alarms | a few GB a month | $5–15 |
| S3 (files, backups), ECR, Secrets Manager, Route 53 | | $10 |
| SES email | ~20k emails per facility | $2–20 |
| **Total** | | **~$240–280** |

### Cheaper pilot (one facility, no 99.9% promise)

Single-AZ RDS (~$25), one api task, no NAT (tasks in public subnets with security groups), static web from S3 and
CloudFront: **~$120–150 a month.** It moves up to the Launch layout without changes to the code.

### Growth (~50 facilities)

api ×3 at 1 vCPU / 2 GB, worker ×2, RDS db.m7g.large Multi-AZ with 100 GB, two Valkey nodes: **~$650–800 a month**
on-demand. A one-year Compute Savings Plan and an RDS reserved instance take about 20–35% off once the size is stable.

### Staging

A second, smaller copy (single-AZ, one of each task) for testing releases before production: **~$100–130 a month.**
It can be shut down outside working hours.

### AWS cost traps to avoid

- NAT gateway data charges: add free S3 gateway endpoints and keep image pulls on ECR.
- CloudWatch log retention left at "never expire".
- Forgotten idle resources such as old snapshots, unattached IPs and staging left running.
- Mitigation: set an AWS Budget alarm (for example $350) on day one.

### Strengths and weaknesses

- Strengths:
  - the best long-term scalability and reliability: Multi-AZ database, point-in-time recovery, managed patching
  - Stripe, SES and S3 are in the same region
  - no migration ever needed
- Weaknesses:
  - the most setup: VPC, IAM, task definitions and the deploy workflow; about 2–4 days to wire and test, which I can do
  - a more complicated bill
  - you hold the root account, which must be locked down with hardware MFA

## 3. Option B: simpler platforms

These run the same containers with less setup and often less cost at small scale, but fewer controls as you grow.

| Provider | How the app maps | ~ Launch cost | Notes |
|---|---|---|---|
| **Fly.io** (outline in `deploy-fly.md`) | one app with four process groups, a web app, a clamav app; Fly Managed Postgres (from $38 plus $0.28/GB); Upstash Redis; Tigris storage | **$110–160** | Machines from $6.70 a month (shared CPU, 1 GB). Cheapest managed option. Check that Managed Postgres allows a BYPASSRLS role and gives a standby on the chosen plan. Support plan $29 a month. |
| **DigitalOcean** (App Platform plus Managed Databases) | containers on App Platform; Managed PostgreSQL ($15 a month for the smallest, plus a standby node); Valkey ($15); Spaces storage ($5) | **$130–190** | Simple dashboard and a predictable bill. Fewer regions and less fine-grained networking than AWS. |
| **Render** | web services and background workers; Render Postgres with HA; Key Value; Professional workspace (per user) | **$200–300** | The easiest pushes from GitHub. HA Postgres requires the higher plans. ClamAV needs a larger instance. |
| **A VPS such as Hetzner, using Kamal or Coolify** | two virtual servers, self-run Postgres and Redis | **$50–90** | Cheapest by far. You run database backups, failover, patching and security yourself. **Not recommended** for a product that takes payments. |

Serverless options such as AWS App Runner, Cloud Run or Vercel suit the API but not the always-on worker, relay,
scheduler and ClamAV, so they don't fit this app without rework.

## 4. Everything else go-live needs (any host)

| Area | What | Who | Cost |
|---|---|---|---|
| Domain and TLS | a product domain; wildcard certificate if each facility gets a subdomain (SSP-01 slug routing) | owner buys the domain; I configure | ~$15 a year; certificates free (ACM or Caddy) |
| Payments | Stripe live mode activated, Stripe Connect platform profile approved, business verification, live webhook endpoint, live keys in the secret store, PCI SAQ A self-assessment (card entry never touches our servers) | owner (verification), I wire it | Stripe fees per transaction only |
| Email | SES production access, SPF, DKIM, DMARC on the sending domain, bounce and complaint webhook | owner creates the account; I build the adapter (Phase 13) | see the email cost analysis |
| Push and mobile app | Apple Developer Program, Google Play account, Firebase project, Expo account. Store review, privacy labels. Each white-labelled facility app (ADR 0006) is its own store listing; the brief keeps store submission out of v1 | owner (accounts) | $99 a year Apple; $25 once Google; Expo push free |
| Deploy pipeline | fill in `.github/workflows/deploy.yml` (OIDC role, migrate, roll services), release tags, a rollback step | me | free on GitHub Actions at this volume |
| Monitoring | error tracking (for example Sentry), uptime checks from outside, alerts to your phone, a status page, the alarms in `monitoring.md` | me, with your accounts | $0–50 a month |
| Backups | provider point-in-time recovery plus the logical dumps in `infra/backup/` copied to a separate account or bucket; the weekly restore drill (`drill.sh`) | me | a few dollars a month |
| Security | MFA on every admin account, least-privilege access, secrets only in the secret store, edge rate limiting or WAF; a third-party penetration test before the first paying customer is strongly advised | me; the pen test is a vendor | WAF ~$10–20 a month; pen test ~$3–10k once |
| Legal | Terms of Service, Privacy Policy, a data processing agreement for facilities, cookie notice, accessibility statement; business entity and cyber-liability insurance | owner (with a lawyer); I can draft starting points | varies |
| Support and onboarding | a support email or help desk, help articles, the import tool (Phase 8) for moving a facility's data in | owner, with my help | $0–50 a month |
| Phase 8 checks not yet run | container stack smoke test, strict CSP in a real browser, load test with worker and scheduler, the client-IP check behind the real load balancer | me, once the host exists | none |

## 5. Recommendation

AWS: ECS Fargate (ARM), RDS PostgreSQL Multi-AZ, ElastiCache, S3, SES and CloudWatch, in one region (us-east-2,
Ohio, close to Central Illinois customers).

- Start at the cheaper pilot layout (~$130 a month) for the first facility, with staging switched off when idle.
- Move to the Launch layout (~$260 a month) before promising 99.9% to paying customers.
- Expect roughly $25–50 a month per 10 facilities of extra infrastructure as you grow, well inside a typical
  subscription price.

If minimum cost and setup time matter more than long-term headroom, Fly.io at ~$120–150 is the runner-up. The images
are portable, so moving later is possible. The database move is the one painful step.

## 6. What the owner needs to do to start (I cannot create accounts)

1. Create an AWS account. Turn on MFA for the root user and create an admin user for daily work.
2. Set a billing budget alarm.
3. Buy the product domain.
4. Start Stripe live-mode business verification. It can take days.
5. Later, before the mobile launch: Apple Developer, Google Play, Firebase and Expo accounts.

Then I write the infrastructure as code, fill in the deploy pipeline, stand up staging, run the unrun Phase 8
checks there, and only then production.

Sources: [AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/),
[Amazon RDS for PostgreSQL pricing](https://aws.amazon.com/rds/postgresql/pricing/),
[RDS t4g price summary](https://www.bytebase.com/dbcost/rds/instance/db.t4g.small/),
[Fly.io pricing](https://docs.fly.io/about/pricing),
[DigitalOcean managed database pricing](https://www.digitalocean.com/pricing/managed-databases),
[Render pricing](https://render.com/pricing), [Amazon SES pricing](https://aws.amazon.com/ses/pricing/).
