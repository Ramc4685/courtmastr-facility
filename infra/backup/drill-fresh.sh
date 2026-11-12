#!/usr/bin/env bash
# Fresh-cluster restore drill: the same checks as drill.sh, but against a throwaway Postgres container that has no
# fh_* roles and no database (no init script), the situation after losing the database host. Proves the archive's role
# statements and the restore work from nothing. The container is removed afterwards, pass or fail.
#
#   infra/backup/drill-fresh.sh [archive.tar.enc]     (needs docker and the postgres:16 image; same env as drill.sh)
set -euo pipefail
here=$(dirname "$0")
name="fh-drill-pg-$$"
password=$(openssl rand -hex 12)
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker run -d --name "$name" -e POSTGRES_PASSWORD="$password" -e TZ=UTC postgres:16 >/dev/null
for _ in $(seq 60); do docker exec "$name" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
# pg_isready answers during the image's init restart; wait until a real query works.
for _ in $(seq 60); do docker exec "$name" psql -U postgres -Atc 'select 1' >/dev/null 2>&1 && break; sleep 1; done
echo "fresh cluster roles: $(docker exec "$name" psql -U postgres -Atc "select count(*) from pg_roles where rolname like 'fh_%'") fh_* (expected 0)"
export PGUSER=postgres PGPASSWORD="$password" PGDATABASE=${PGDATABASE:-facilityhub}
export FH_PG_EXEC="docker exec -i -e PGPASSWORD -e PGUSER $name"
"$here/drill.sh" "$@"
