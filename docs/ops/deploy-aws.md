# Deploying on AWS (outline)

Status: **not deployed, nothing created in any AWS account.** This page says what maps to what so the owner can price it
and decide. Pipeline: `.github/workflows/deploy.yml` (manual, skeleton). The images are plain containers; nothing in
them is AWS-specific.

## What maps to what

| Piece | On AWS |
|---|---|
| Backend image, four processes | four ECS services on Fargate (`api` behind the load balancer; `worker`, `relay`, `scheduler` without), one task definition each, the process chosen by the container command (`api`, `worker`, `relay`, `scheduler`) |
| Migrations | a one-shot ECS task with the `migrate` command, run by the gated workflow step before the services roll |
| Proxy + web build | the web image (Caddy) as an ECS service behind an Application Load Balancer with an ACM certificate; run it with `SITE_ADDRESS=:8080` so the load balancer terminates TLS. Alternative: serve the static build from S3 behind CloudFront and route `/api` to the load balancer, which also gives a place to add `nosniff` through a response headers policy |
| Postgres 16 with RLS | RDS for PostgreSQL 16, Multi-AZ for the 99.9% target. The migrations need `btree_gist`, `citext`, `pg_trgm` (all supported on RDS); the backup role needs `BYPASSRLS` (`rds_superuser` can create it; set `FH_BACKUP_SKIP_GLOBALS=1`) |
| Redis | ElastiCache for Redis (or Valkey), same VPC, not public |
| Object storage | S3 bucket: private, versioning on, replication to a second region or account for disaster recovery, a lifecycle rule for old versions. `storage.adapter: s3` with `endpoint_url: null`; credentials from the task role (leave `FH_S3_*` unset: the adapter then uses boto3's default chain) |
| ClamAV | an ECS service from the `clamav/clamav-debian` image, reached over service discovery on port 3310; give it memory for the signature database |
| Registry | ECR |
| Secrets | Secrets Manager or SSM Parameter Store, injected as environment variables by the task definition |
| Config overlay | bake a thin image layer on top of the backend image containing `app.production.yaml`, or mount it from EFS/S3 at start |
| Logs and alarms | CloudWatch Logs (the JSON logs parse natively) and CloudWatch alarms on the signals in monitoring.md; Route 53 health checks for the external probe |
| DNS and certificates | Route 53 and ACM |

## Things that must be true before a go-live

1. Client IP: behind an Application Load Balancer the proxy's socket peer is the balancer, so by default every client would
   share one address and S1's per-address sign-in limits would become one shared bucket. Set the proxy's `EDGE_CIDRS` to the
   load balancer's subnets (it forwards the client in `X-Forwarded-For`, the default `EDGE_IP_HEADER`), then confirm that
   `core/api.py::_ip` returns the real client. The mechanism is tested locally with a stand-in edge (`infra/docker/smoke.sh`);
   on AWS it is **untested**. Separately, the API's own overlay lists the proxy tasks' subnet in `api.trusted_proxies`
   (not the balancer's: the API only ever talks to the proxy). Production refuses to start with it empty unless
   `api.exposed_directly: true`.
2. The migrate and deploy steps in the workflow are placeholders: fill them for ECS (OIDC role, `register-task-definition`,
   `update-service`, `run-task`).
3. Overlay values: `app.web_base_url`, `db.host`, `redis.url`, `email` relay (SES is the natural one), bucket name.
4. Backups: a scheduled task runs `infra/backup/backup.sh` and copies the archive to a separate bucket; RDS automated
   backups and point-in-time recovery are the provider-level safety net on top of the logical dumps; run `drill.sh`
   weekly.

## Cost drivers (look prices up, do not trust any number here)

Fargate vCPU and memory hours for every always-on task, the load balancer (hourly plus capacity units), RDS instance, Multi-AZ
and storage, the ElastiCache node, **NAT gateway hours and data processed** (a frequent surprise for tasks in private
subnets; VPC endpoints for S3, ECR and logs reduce it), data transfer out, CloudWatch log ingestion and retention, S3 storage
and requests, and replication traffic. Current prices: <https://aws.amazon.com/pricing/> and the AWS Pricing Calculator
at <https://calculator.aws/>.

## Availability notes

99.9% a month needs at least two API tasks in different zones, Multi-AZ RDS, and health checks on
`/api/v1/health/ready` at the load balancer target group. The cheapest single-zone layout cannot meet it.
