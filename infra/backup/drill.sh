#!/usr/bin/env bash
# Restore drill: restore the newest backup (or the given one) into a scratch database, check it, drop it, print
# PASS or FAIL. Exit status 0 only on PASS. Run it on a schedule: a backup nobody restored is a hope, not a backup.
#
#   infra/backup/drill.sh [archive.tar.enc]
#
# Checks: (1) the migration head equals the manifest's, and FH_EXPECTED_HEAD when set (the code's head);
# (2) every public table's row count equals the count recorded at backup time, from the same snapshot;
# (3) RLS is intact: every table has RLS enabled and forced, the policy count matches, and the application role
# (fh_app) with no tenant selected sees no rows in any RLS table. FH_DRILL_KEEP=1 keeps the scratch database.
. "$(dirname "$0")/lib.sh"
need_passphrase
DB=${PGDATABASE:-facilityhub}; DIR=${FH_BACKUP_DIR:-backups}
archive=${1:-$(ls -1t "$DIR"/fh-"$DB"-*.tar.enc 2>/dev/null | head -1)}
[ -n "$archive" ] && [ -f "$archive" ] || die "no backup found in $DIR"
scratch="fh_drill_$(date -u +%Y%m%d%H%M%S)"; work=$(mktemp -d); fail=0
cleanup() { [ -n "${FH_DRILL_KEEP:-}" ] || psql_q -d postgres -c "DROP DATABASE IF EXISTS \"$scratch\" WITH (FORCE)" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
check() { if [ "$1" = ok ]; then echo "PASS  $2"; else echo "FAIL  $2"; fail=1; fi; }

echo "drill: $(basename "$archive") -> $scratch"
FH_RESTORE_MANIFEST_OUT="$work/MANIFEST" "$(dirname "$0")/restore.sh" "$archive" "$scratch" || { echo "FAIL  restore"; echo "DRILL FAIL"; exit 1; }
check ok "restore completed"
psql_q -d "$scratch" -c "$FACTS_SQL" > "$work/after" || { echo "FAIL  cannot query the restored database"; echo "DRILL FAIL"; exit 1; }

head_then=$(sed -n 's/^head|//p' "$work/MANIFEST"); head_now=$(sed -n 's/^head|//p' "$work/after")
[ "$head_then" = "$head_now" ] && check ok "migration head $head_now matches the backup manifest" || check bad "migration head $head_now, manifest says $head_then"
if [ -n "${FH_EXPECTED_HEAD:-}" ]; then
  [ "$head_now" = "$FH_EXPECTED_HEAD" ] && check ok "migration head equals the code's head ($FH_EXPECTED_HEAD)" || check bad "migration head $head_now, code expects $FH_EXPECTED_HEAD"
fi

grep '^rows|' "$work/MANIFEST" | sort > "$work/rows.then"; grep '^rows|' "$work/after" | sort > "$work/rows.now"
tables=$(wc -l < "$work/rows.now" | tr -d ' '); total=$(awk -F'|' '{s+=$3} END {print s+0}' "$work/rows.now")
if [ "$tables" -gt 0 ] && diff -q "$work/rows.then" "$work/rows.now" >/dev/null; then check ok "row counts equal on all $tables tables ($total rows)"
else check bad "row counts differ: $(diff "$work/rows.then" "$work/rows.now" | head -5 | tr '\n' ' ')"; fi

rls_then=$(sed -n 's/^rls|//p' "$work/MANIFEST"); rls_now=$(sed -n 's/^rls|//p' "$work/after")
forced=${rls_now%%|*}; policies=${rls_now##*|}
if [ "$rls_then" = "$rls_now" ] && [ "$forced" -gt 0 ] && [ "$policies" -gt 0 ]; then check ok "RLS intact: $forced tables forced, $policies policies, same as the backup"
else check bad "RLS facts differ or empty: now $rls_now, backup $rls_then"; fi

leak=$(pg psql -X -q -v ON_ERROR_STOP=1 -d "$scratch" 2>&1 <<'SQL' || true
DO $$ DECLARE r record; n bigint; seen int := 0; leaks text := '';
BEGIN
  SET LOCAL ROLE fh_app;
  FOR r IN SELECT c.relname FROM pg_class c JOIN pg_namespace ns ON ns.oid = c.relnamespace
           WHERE ns.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity LOOP
    BEGIN EXECUTE format('SELECT count(*) FROM public.%I', r.relname) INTO n;
    EXCEPTION WHEN insufficient_privilege THEN n := 0; END;
    seen := seen + 1; IF n > 0 THEN leaks := leaks || r.relname || ' '; END IF;
  END LOOP;
  IF leaks <> '' THEN RAISE EXCEPTION 'RLS leak: fh_app without a tenant reads %', leaks; END IF;
  RAISE NOTICE 'rls-checked %', seen;
END $$;
SQL
)
case "$leak" in *rls-checked*) check ok "fh_app with no tenant selected reads no rows from any of the $(echo "$leak" | sed -n 's/.*rls-checked \([0-9]*\).*/\1/p') RLS tables" ;; *) check bad "RLS isolation check: $(echo "$leak" | head -2 | tr '\n' ' ')" ;; esac

[ "$fail" = 0 ] && echo "DRILL PASS (scratch database $scratch dropped)" || echo "DRILL FAIL"
exit "$fail"
