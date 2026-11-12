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

If pay per use matters most, Option C on AWS (Lambda plus Aurora Serverless v2) halves the pilot bill for about two
weeks of rework, and can return to Fargate later without a rewrite.

If minimum cost and setup time matter more than long-term headroom, Fly.io at ~$120–150 is the runner-up. The images
are portable, so moving later is possible. The database move is the one painful step.

## 5a. Option C: serverless, pay per use (owner asked 2026-11-12)

The aim is to pay only when the app is used. The database sets the floor on every provider, because Postgres must
be awake whenever a facility is open. Only the compute can truly drop to zero.

### On AWS

| Piece today | Serverless replacement | Change to the code |
|---|---|---|
| `api` and `web` containers | Lambda running the **same container image** through the AWS Lambda Web Adapter, with CloudFront in front | small: config and the client-IP header |
| Dramatiq worker on Redis | Lambda triggered by SQS (swap Dramatiq's broker for SQS; `@tenant_actor` and `chunked_actor` keep their shape) | medium: `core/jobs`, deploy wiring |
| `relay` (outbox) | a Lambda run every minute by EventBridge Scheduler, or after each commit | small |
| `scheduler` | EventBridge Scheduler rules invoking the job Lambda | small |
| ClamAV (3 GB, always on) | GuardDuty Malware Protection for S3, behind a new adapter for the existing scanner port | small to medium |
| Redis (queue, rate limits) | none: the queue moves to SQS, and rate limits move to Postgres or DynamoDB on-demand | medium: `core/ratelimit` |
| RDS PostgreSQL | **Aurora Serverless v2 (PostgreSQL 16)** with minimum 0 ACU: it pauses when nothing is connected and wakes on the first connection. About $0.12 per ACU-hour, plus storage. | none: same extensions and RLS |

Rough cost for a one-facility pilot (~300k API requests a month):

| Item | ~ per month |
|---|---|
| Lambda and CloudFront | $0–5 (the permanent free tier is 1M requests and 400k GB-seconds a month) |
| Aurora at 0.5–1 ACU while the facility is open, paused overnight | $30–50 |
| Outbound internet for Lambdas inside the private network | ~$4 with a NAT instance on a tiny server, or $33 with a managed NAT gateway |
| SQS, EventBridge, malware scanning, S3, logs, SES | $5–10 |
| **Total** | **~$40–100** |

That is roughly half the container pilot (~$120–150). After startup credits, the first year is close to free.

Trade-offs:

- **Rework:** about 1.5–2 weeks of build and test before deploying: the jobs broker, rate limits, the scanner adapter
  and the pipeline.
- **Cold starts:** the first request after idle waits about 1–3 s for Lambda. If the database was paused, add about
  15 s while it wakes. Fix this by keeping a 0.5 ACU minimum during opening hours, set on a schedule.
- **Connections:** each Lambda copy opens its own database connections. Cap Lambda concurrency rather than buying RDS
  Proxy, which has a high minimum charge.
- **Limits:**
  - Lambda runs at most 15 minutes per call. The Phase 8 chunked jobs already fit that.
  - Lambda request bodies are limited to 6 MB. Large uploads must go straight to S3.
- **Scale:** once ~20+ facilities use it every day, the database never sleeps and serverless costs about the same as
  containers or a little more. Because the Lambda uses the same container image, moving back to Fargate is a
  configuration change, not a rewrite.

### Serverless containers elsewhere (less rework)

These run the existing containers almost unchanged and still scale to zero.

| Provider | Compute | Database | ~ pilot | Notes |
|---|---|---|---|---|
| **Azure Container Apps** | API and web scale to zero. The worker scales 0→N on the Redis queue length (KEDA), so Dramatiq stays. Monthly free grant of 180k vCPU-seconds and 2M requests. | Azure Database for PostgreSQL Flexible Server, Burstable B1ms (~$13–20 plus storage). It does not pause by itself. High availability needs a General Purpose tier (~$130+). | **$40–80** | the least rework of all; Postgres HA is expensive; ClamAV could become Defender for Storage malware scanning |
| **Google Cloud Run** | API and web scale to zero. The worker needs at least one instance running (always on). Cloud Scheduler for the clock. | Cloud SQL for PostgreSQL (~$25 small; HA doubles it). It does not pause. Memorystore Redis has a ~$35 floor (or Upstash, pay per request). | **$60–110** | little rework; no managed malware scanner, so ClamAV stays as a service |

## 5b. Startup credits

Each cloud gives credits only for its own services. Applying to more than one is allowed, but the app runs on one.
Amounts are for a **self-funded** company. Larger programmes need an accelerator or investor referral. Terms change
often, so check each official page before applying.

| Program | Self-funded amount | Bigger tier | Notes |
|---|---|---|---|
| **AWS Activate Founders** | **$1,000**, select startups up to $5,000 over time; credits usually last up to two years | Portfolio: $100k+ through an accelerator or VC | needs a paid AWS account (not free tier only); new accounts also get up to $200 in free-tier credits |
| **Microsoft for Startups** (Founders Hub) | about **$1,000**, rising to about $5,000 after verification | up to $150,000 with an Investor Network referral | for privately held, for-profit companies below Series C |
| **Google for Startups Cloud Program, Start tier** | **$2,000** for one year (covers Cloud and Firebase) | Scale: up to $200k ($350k for AI-first) when funded | pre-funded, recently founded (sources say within 2–5 years), working MVP |

For a self-funded start, the credits are about the same everywhere ($1–5k). That covers 1–2 years of a serverless
pilot on any of them, so credits shouldn't decide the cloud. The cheapest *ongoing* bill and the least rework should.

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
[Render pricing](https://render.com/pricing), [Amazon SES pricing](https://aws.amazon.com/ses/pricing/),
[Aurora Serverless v2 auto-pause](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html),
[AWS Activate credits](https://aws.amazon.com/aws-startups/learn/everything-you-need-to-know-about-aws-activate-credits/),
[Microsoft for Startups Azure benefits](https://learn.microsoft.com/en-gb/microsoft-for-startups/benefits/azure),
[Google for Startups Cloud Program FAQ](https://cloud.google.com/startup/faq).
