# Shared by backup.sh, restore.sh and drill.sh (sourced). Bash 3.2 compatible (macOS) and Linux.
#
# Connection: the standard libpq variables (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE). The role must bypass
# row-level security (a superuser, or a dedicated role with BYPASSRLS and pg_read_all_data): the tables FORCE RLS,
# so any other role dumps no rows. Never the application's fh_app.
# FH_PG_EXEC: a command prefix that runs the PostgreSQL client tools somewhere else, for hosts without them,
#   e.g. FH_PG_EXEC="docker exec -i -e PGPASSWORD -e PGUSER postgres-container". Dumps still stream to this host.
# FH_BACKUP_PASSPHRASE: encrypts backups at rest (from the environment, never an argument).
set -euo pipefail
# shellcheck disable=SC2206
PGX=(${FH_PG_EXEC:-})
CIPHER=(-aes-256-cbc -pbkdf2 -iter 600000 -salt)

die() { echo "error: $*" >&2; exit 1; }
need_passphrase() { [ -n "${FH_BACKUP_PASSPHRASE:-}" ] || die "FH_BACKUP_PASSPHRASE is not set"; }
pg() { "${PGX[@]+"${PGX[@]}"}" "$@"; }
psql_q() { pg psql -X -q -At -v ON_ERROR_STOP=1 "$@"; }
sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
encrypt() { openssl enc "${CIPHER[@]}" -pass env:FH_BACKUP_PASSPHRASE "$@"; }
decrypt() { openssl enc -d "${CIPHER[@]}" -pass env:FH_BACKUP_PASSPHRASE "$@"; }

# One line per fact, run as a BYPASSRLS role: row counts per public table, RLS coverage, migration head.
FACTS_SQL=$(cat <<'SQL'
SELECT 'rows|' || c.relname || '|' || (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM public.%I', c.relname), false, true, '')))[1]::text
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY c.relname;
SELECT 'rls|' || count(*) FILTER (WHERE c.relrowsecurity AND c.relforcerowsecurity) || '|' || (SELECT count(*) FROM pg_policies WHERE schemaname = 'public')
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r';
SELECT 'head|' || version_num FROM alembic_version;
SQL
)
