#!/usr/bin/env bash
# Restore an archive from backup.sh into a database that does not exist yet.
#
#   infra/backup/restore.sh <archive.tar.enc> <target-database> [--drop-existing]
#
# Creates any missing roles (without passwords: set them from your secret store), creates the database owned as in the
# source, runs pg_restore, and prints the manifest's migration head. Refuses to touch an existing database unless
# --drop-existing is given. Needs a superuser connection (extensions, ownership), like backup.sh.
# FH_RESTORE_MANIFEST_OUT=<path> keeps a copy of the verified manifest (drill.sh uses it).
. "$(dirname "$0")/lib.sh"
need_passphrase
archive=${1:-}; target=${2:-}; mode=${3:-}
[ -f "$archive" ] && [ -n "$target" ] || die "usage: restore.sh <archive.tar.enc> <target-database> [--drop-existing]"
case "$target" in *[!A-Za-z0-9_]*) die "target database name may only use letters, digits and underscores" ;; esac
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
decrypt -in "$archive" | tar -C "$work" -xf - 2>/dev/null || die "cannot decrypt $archive (wrong passphrase or damaged file)"
for f in db.dump globals.sql; do
  want=$(sed -n "s/^sha|$f|//p" "$work/MANIFEST"); [ "$(sha "$work/$f")" = "$want" ] || die "checksum mismatch on $f"
done
exists=$(psql_q -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$target'")
if [ -n "$exists" ]; then
  [ "$mode" = "--drop-existing" ] || die "database $target exists; pass --drop-existing to replace it"
  psql_q -d postgres -c "DROP DATABASE \"$target\" WITH (FORCE)" >/dev/null
fi
# Roles: already-exists errors are expected and harmless; anything else shows in the output.
pg psql -X -q -d postgres < "$work/globals.sql" 2>&1 | grep -v 'already exists' || true
owner=$(sed -n 's/^owner|//p' "$work/MANIFEST")
psql_q -d postgres -c "CREATE DATABASE \"$target\" OWNER \"$owner\"" >/dev/null
pg pg_restore --exit-on-error --dbname="$target" < "$work/db.dump" || die "pg_restore failed"
[ -z "${FH_RESTORE_MANIFEST_OUT:-}" ] || cp "$work/MANIFEST" "$FH_RESTORE_MANIFEST_OUT"
echo "restored $(basename "$archive") into $target (migration head $(sed -n 's/^head|//p' "$work/MANIFEST"))"
