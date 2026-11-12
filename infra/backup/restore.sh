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
db_exists() { psql_q -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$1'"; }
if [ -n "$(db_exists "$target")" ] && [ "$mode" != "--drop-existing" ]; then
  die "database $target exists; pass --drop-existing to replace it"
fi
# Roles: only fh_* role statements from the archive are run, one per line, never anything else (no psql meta-commands,
# no other SQL). pg_dumpall writes `CREATE ROLE fh_app;` and `ALTER ROLE fh_app WITH ...`. A role line that grants
# SUPERUSER, CREATEROLE, CREATEDB or REPLICATION is refused, and BYPASSRLS is allowed only for the roles the init script
# itself creates with it. Already-exists errors are expected; any other error stops the restore.
init="$(dirname "$0")/../postgres/init/01-roles.sh"
bypass_ok=""; [ ! -f "$init" ] || bypass_ok=$(sed -n -E 's/^CREATE ROLE +(fh_[a-z_]+) .* BYPASSRLS.*/\1/p' "$init" | tr '\n' ' ')
grep -E '^(CREATE|ALTER) ROLE fh_[a-z_]+[ ;]|^GRANT fh_[a-z_]+ TO fh_[a-z_]+' "$work/globals.sql" > "$work/roles.sql" || true
while IFS= read -r line; do
  role=$(sed -n -E 's/^(CREATE|ALTER) ROLE (fh_[a-z_]+).*/\2/p' <<<"$line")
  if grep -qE ' (SUPERUSER|CREATEROLE|CREATEDB|REPLICATION)( |;|$)' <<<"$line"; then die "archive grants a privileged attribute: $line"; fi
  if grep -qE ' BYPASSRLS( |;|$)' <<<"$line"; then
    case " $bypass_ok" in *" $role "*) ;; *) die "archive grants BYPASSRLS to $role, which the init script does not: $line" ;; esac
  fi
done < "$work/roles.sql"
errors=$(pg psql -X -q -d postgres < "$work/roles.sql" 2>&1 | grep -v 'already exists' || true)
[ -z "$errors" ] || die "role setup failed: $errors"
owner=$(sed -n 's/^owner|//p' "$work/MANIFEST")
case "$owner" in ''|[!A-Za-z_]*|*[!A-Za-z0-9_]*) die "manifest names an invalid database owner" ;; esac
# Restore into a temporary database and swap it in only on success, so a failed restore never costs an existing database.
tmp="${target}_restoring"
drop_tmp() { psql_q -d postgres -c "DROP DATABASE IF EXISTS \"$tmp\" WITH (FORCE)" >/dev/null 2>&1 || true; }
drop_tmp; trap 'drop_tmp; rm -rf "$work"' EXIT
psql_q -d postgres -c "CREATE DATABASE \"$tmp\" OWNER \"$owner\"" >/dev/null
pg pg_restore --exit-on-error --dbname="$tmp" < "$work/db.dump" || die "pg_restore failed (an existing $target is untouched)"
if [ -n "$(db_exists "$target")" ]; then psql_q -d postgres -c "DROP DATABASE \"$target\" WITH (FORCE)" >/dev/null; fi
psql_q -d postgres -c "ALTER DATABASE \"$tmp\" RENAME TO \"$target\"" >/dev/null
[ -z "${FH_RESTORE_MANIFEST_OUT:-}" ] || cp "$work/MANIFEST" "$FH_RESTORE_MANIFEST_OUT"
echo "restored $(basename "$archive") into $target (migration head $(sed -n 's/^head|//p' "$work/MANIFEST"))"
