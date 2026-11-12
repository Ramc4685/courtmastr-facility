#!/usr/bin/env bash
# Logical backup of one database: schema with RLS policies and grants, data, and the role definitions (no password
# hashes), in a single AES-256 encrypted archive. Rows and RLS facts are read from the same snapshot as the dump, so
# restore.sh and drill.sh can prove the restore is exact. Retention is by count.
#
#   FH_BACKUP_PASSPHRASE=... PGPASSWORD=... PGUSER=postgres PGHOST=... infra/backup/backup.sh
#
# Settings: PGDATABASE (default facilityhub), FH_BACKUP_DIR (default ./backups), FH_BACKUP_KEEP (default 14),
# FH_BACKUP_SKIP_GLOBALS=1 on managed Postgres where pg_dumpall --globals-only is not permitted.
# Limit: the archive is encrypted, not authenticated. A wrong passphrase fails to decrypt, and restore verifies the
# manifest's checksums, but nothing proves who wrote it. Keep backups in storage only the platform can write to.
. "$(dirname "$0")/lib.sh"
need_passphrase
DB=${PGDATABASE:-facilityhub}; DIR=${FH_BACKUP_DIR:-backups}; KEEP=${FH_BACKUP_KEEP:-14}
case "$KEEP" in ''|*[!0-9]*|0) die "FH_BACKUP_KEEP must be a whole number of at least 1" ;; esac
umask 077; mkdir -p "$DIR"
work=$(mktemp -d); session=""
# On any exit (failure, Ctrl-C, kill): release the snapshot holder first, wait until its psql has really ended, and only
# then delete the work directory. Otherwise the open REPEATABLE READ transaction would pin xmin and block vacuum forever.
cleanup() { touch "$work/done"; [ -z "$session" ] || wait "$session" 2>/dev/null || true; rm -rf "$work"; }
trap cleanup EXIT
trap 'exit 130' INT TERM
stamp=$(date -u +%Y%m%dT%H%M%SZ)

# A held-open REPEATABLE READ session exports a snapshot and reads the facts; pg_dump joins that snapshot.
# The loop also ends if the work directory vanishes, so it can never outlive this script.
( printf '%s\n' "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;" "SELECT 'snap|' || pg_export_snapshot();" "$FACTS_SQL"
  while [ -d "$work" ] && [ ! -e "$work/done" ]; do sleep 0.2; done; echo "COMMIT;" ) \
  | psql_q -d "$DB" > "$work/facts" &
session=$!
snapshot=""
for _ in $(seq 150); do
  snapshot=$(sed -n 's/^snap|//p' "$work/facts" 2>/dev/null | head -1); [ -n "$snapshot" ] && break; sleep 0.2
done
[ -n "$snapshot" ] || { touch "$work/done"; die "could not open a snapshot on $DB"; }

pg pg_dump --format=custom --dbname="$DB" --snapshot="$snapshot" > "$work/db.dump" || { touch "$work/done"; die "pg_dump failed"; }
touch "$work/done"; wait "$session" || die "snapshot session failed"
if [ -z "${FH_BACKUP_SKIP_GLOBALS:-}" ]; then
  pg pg_dumpall --globals-only --no-role-passwords > "$work/globals.sql" || die "pg_dumpall failed (managed Postgres? set FH_BACKUP_SKIP_GLOBALS=1)"
else : > "$work/globals.sql"; fi

{ echo "format|1"; echo "db|$DB"; echo "created|$stamp"
  echo "owner|$(psql_q -d "$DB" -c "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()")"
  echo "pg|$(psql_q -d "$DB" -c "SHOW server_version")"
  grep -v '^snap|' "$work/facts"
  echo "sha|db.dump|$(sha "$work/db.dump")"; echo "sha|globals.sql|$(sha "$work/globals.sql")"; } > "$work/MANIFEST"

out="$DIR/fh-$DB-$stamp.tar.enc"
tar -C "$work" -cf - MANIFEST globals.sql db.dump | encrypt -out "$out.partial"
mv "$out.partial" "$out"
# Retention by count: keep the newest $KEEP archives of this database.
ls -1t "$DIR"/fh-"$DB"-*.tar.enc 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f "$old"; done
echo "backup ok: $out ($(wc -c < "$out" | tr -d ' ') bytes, head $(sed -n 's/^head|//p' "$work/MANIFEST"), kept newest $KEEP)"
