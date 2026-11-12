# Runbook

Commands assume the container stack (`infra/docker/compose.stack.yml`, project `fhstack`) and are written so the same
steps work on any container host: replace `docker compose` with the platform's equivalent (`fly machine`, an ECS task
definition, ...). The backend image takes the command as its argument, so every procedure is "run this image with
that command and the production environment variables".

```bash
STACK="docker compose --env-file infra/docker/.env.stack -f infra/docker/compose.stack.yml"
```

## Start

```bash
make stack-up        # builds the images, starts Postgres, Redis, S3, ClamAV, then migrate, then the app
```

Order is enforced by health: Postgres and Redis healthy, then `migrate` and `s3-init` finish, then `api`, `worker`,
`relay`, `scheduler`, then the proxy. ClamAV needs a few minutes on first start to download signatures; the API waits
for it (production refuses to run without a scanner). Check readiness:

```bash
curl -ks https://localhost:18443/api/v1/health/ready
```

## Stop

```bash
make stack-down      # stops the stack AND deletes its volumes (database, queue, bucket). Local only.
$STACK stop          # stops the containers and keeps the data
```

Stop `scheduler` and `relay` first when you need a quiet database (`$STACK stop scheduler relay`), then the API.
Messages already on the Redis queue persist (append-only file) and are processed after the next start.

## Migrate

Migrations run as the `fh_owner` role, in a one-shot container, before any new code serves traffic:

```bash
$STACK run --rm migrate          # alembic upgrade head
```

They are written to be applied while the previous release still runs (additive first, destructive in a later release).
The deploy workflow runs the same command as its own gated step.

## Roll back a release

1. Redeploy the previous image tag. Images are tagged with the commit SHA; keep the last few.
2. Database: do **not** run `alembic downgrade` on production data unless the release notes say the migration is
   reversible and nothing wrote to the new columns. Because migrations are additive first, the previous image normally
   runs fine against the newer schema.
3. If a migration itself damaged data, restore from backup (below) into a new database and switch the app to it.

## Restore from backup

Backups are encrypted logical dumps (`infra/backup/backup.sh`), one archive per run, newest 14 kept by default.

```bash
export FH_BACKUP_PASSPHRASE=...   PGHOST=... PGUSER=postgres PGPASSWORD=...   # a superuser; the passphrase from the secret store
infra/backup/restore.sh backups/fh-facilityhub-<timestamp>.tar.enc facilityhub_restored
```

The script verifies the manifest checksums, creates missing roles (without passwords: set them from the secret store),
creates the database owned as in the source, and restores. It refuses an existing database unless `--drop-existing`.
Then point the app at the restored database (`db.name` in the config overlay), run `migrate` to be safe, and check
`/api/v1/health/ready`. On hosts without client tools set `FH_PG_EXEC` (see `infra/backup/lib.sh`).

**Drill.** `infra/backup/drill.sh` restores the newest backup into a scratch database, checks the migration head, every
table's row count and RLS, prints PASS or FAIL and drops the scratch database. Run it weekly (`make backup-drill` on a
lane). A backup that was never restored is not a backup.

**Roles.** The backup role must bypass RLS (superuser, or a dedicated login role with `BYPASSRLS` and
`pg_read_all_data`): the tables force RLS, so any other role dumps no rows. On managed Postgres where superuser is not
available, create that role and set `FH_BACKUP_SKIP_GLOBALS=1` (roles are then created by your provisioning).

**Files.** Object storage is restored from bucket versioning or replication, not from these archives (README).

## Rotate secrets

All secrets are environment variables; none are in the image or the repository.

| Secret | How to rotate |
|---|---|
| `FH_DB_APP_PASSWORD`, `FH_DB_PLATFORM_PASSWORD`, `FH_DB_OWNER_PASSWORD` | `ALTER ROLE fh_app PASSWORD '...'` as superuser, update the secret, restart `api`, `worker`, `relay`, `scheduler` (owner: used only by `migrate`) |
| `FH_S3_ACCESS_KEY_ID` / `FH_S3_SECRET_ACCESS_KEY` | create a second key pair with the provider, deploy it, then delete the old pair |
| `FH_OPERATOR_TOKEN` | set a new value and restart `api`; leave it empty to disable the onboarding endpoint |
| `FH_BACKUP_PASSPHRASE` | new backups use the new value; keep the old one until the last archive encrypted with it has aged out |
| `FH_DATA_KEY` | **not a drop-in rotation**: it encrypts stored tenant secrets (webhook signing keys). Rotating needs a re-encryption step that does not exist yet; treat the key as long-lived and back it up with the secrets |
| Stripe keys | per the Stripe adapter docs, in the Stripe dashboard first, then the environment |

After any rotation: restart the affected services and confirm `/api/v1/health/ready`.

## Requeue dead letters

A background job that exhausts its retries lands in `failed_job` (ADR 0008). List a tenant's open ones, then requeue or
discard one:

```bash
$STACK run --rm api cli failed-jobs --tenant <tenant-id>
$STACK run --rm api cli failed-jobs --tenant <tenant-id> --requeue <failed-job-id>
$STACK run --rm api cli failed-jobs --tenant <tenant-id> --discard <failed-job-id>
```

(`cli` runs `python -m app.cli`, so on a plain host it is `python -m app.cli failed-jobs ...`.) Look at the error class
first: requeue after the cause is fixed, discard what can never succeed.

## Smoke test

`make stack-smoke` signs in through the proxy, checks the security headers, round-trips a file and checks that
readiness goes red when Redis stops. Run it against any fresh stack.
