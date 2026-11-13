#!/usr/bin/env bash
# Smoke test of a running container stack, through the proxy only (what a browser would reach):
#   shell and SPA fallback, security headers, body cap and the upload exception, onboarding and sign-in,
#   trusted-proxy client IP, a file upload and download round trip, and readiness going red with Redis stopped.
# Needs: `make stack-up` with the mail profile (Mailpit carries the invitation link), curl, python3, openssl.
#   infra/docker/smoke.sh          prints PASS/FAIL per check and the raw header block; exit 1 on any FAIL
set -euo pipefail
cd "$(dirname "$0")/../.."
ENVF=${FH_STACK_ENV:-infra/docker/.env.stack}
set -a; . "$ENVF"; set +a
S="docker compose --env-file $ENVF -f infra/docker/compose.stack.yml --profile mail"
BASE="https://localhost:${FH_STACK_HTTPS_PORT:-18443}"
MAIL="http://127.0.0.1:${FH_STACK_MAIL_UI_PORT:-18025}"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fails=0
ok() { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fails=$((fails + 1)); }
expect() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got '$2', want '$3')"; fi; }
has() { if grep -qi -- "$2" <<<"$3"; then ok "$1"; else bad "$1 (missing: $2)"; fi; }
code() { curl -ks -o /dev/null -w '%{http_code}' --max-time 30 "$@"; }
jget() { python3 -c 'import sys, json
d = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    d = d[int(part)] if part.isdigit() else d[part]
print(d)' "$1"; }
ready() { code "$BASE/api/v1/health/ready"; }
wait_ready() { for _ in $(seq 60); do [ "$(ready)" = 200 ] && return 0; sleep 2; done; return 1; }

echo "== readiness"; wait_ready && ok "ready answers 200" || { bad "stack never became ready"; exit 1; }

echo "== web shell"
root=$(curl -ks "$BASE/")
has "index.html served with the SPA root" 'id="root"' "$root"
has "SPA fallback: /sign-in serves the shell" 'id="root"' "$(curl -ks "$BASE/sign-in")"
asset=$(grep -o '/assets/[^"]*\.js' <<<"$root" | head -1)
has "hashed asset is cached immutably" 'immutable' "$(curl -ksI "$BASE$asset")"

echo "== security headers"
page=$(curl -ksI "$BASE/"); api=$(curl -ks -D - -o /dev/null "$BASE/api/v1/health/live")
echo "--- GET / ---"; echo "$page"; echo "--- GET /api/v1/health/live ---"; echo "$api"
for h in 'x-content-type-options: nosniff' 'x-frame-options: DENY' 'referrer-policy: no-referrer' 'cross-origin-opener-policy: same-origin'; do
  has "page: $h" "$h" "$page"; has "api: $h" "$h" "$api"
done
has "api: strict-transport-security: max-age=31536000" 'strict-transport-security: max-age=31536000' "$api"
if grep -qi '^strict-transport-security' <<<"$page"; then bad "page sends HSTS on localhost"; else ok "page sends no HSTS on localhost (it would pin every local dev server)"; fi
has "page CSP is strict" "script-src 'self' https://js.stripe.com https://*.js.stripe.com;" "$page"
has "page CSP lets the Stripe Payment Element frame in" "frame-src https://js.stripe.com https://*.js.stripe.com https://hooks.stripe.com;" "$page"
has "page CSP lets Stripe.js call its API, nothing else" "connect-src 'self' https://api.stripe.com;" "$page"
has "page CSP forbids framing" "frame-ancestors 'none'" "$page"
has "api keeps its own deny-all CSP" "default-src 'none'; frame-ancestors 'none'" "$api"
has "api responses are no-store" 'cache-control: no-store' "$api"
if grep -qi '^server:' <<<"$page"; then bad "Server header is exposed"; else ok "no Server header"; fi

echo "== docs, OpenAPI and operator routes are not public"
for path in /api/v1/docs /api/v1/docs/oauth2-redirect /api/v1/openapi.json /api/v1/operator/tenants; do
  expect "$path is 404 through the proxy" "$(code "$BASE$path")" 404
done

echo "== body cap"
head -c 2097152 /dev/zero | tr '\0' 'a' > "$tmp/big"
expect "2 MiB JSON body is refused" "$(code -X POST -H 'content-type: application/json' --data-binary @"$tmp/big" "$BASE/api/v1/auth/sign-in")" 413

echo "== onboarding and sign-in"
curl -s -X DELETE "$MAIL/api/v1/messages" >/dev/null
email="owner-$(openssl rand -hex 3)@smoke.example.com"; slug="smoke-$(openssl rand -hex 3)"
$S run --rm -T api cli onboard-tenant --name "Smoke Club" --slug "$slug" --time-zone America/Chicago \
  --owner-email "$email" --owner-first-name Smoke --owner-last-name Owner >/dev/null 2>&1
# Two-step verification (S2) is required for an owner by default and is tested by its own suite. Here the new tenant's
# policy is set to optional (superuser, test setup only) so the checks below can use password sign-in.
docker exec -e PGPASSWORD="$FH_POSTGRES_PASSWORD" fhstack-postgres-1 psql -U postgres -d facilityhub -Atc \
  "UPDATE tenant SET staff_mfa_policy = 'optional' WHERE slug = '$slug'" >/dev/null
token=""
for _ in $(seq 30); do
  id=$(curl -s "$MAIL/api/v1/messages" | jget messages.0.ID 2>/dev/null || true)
  if [ -n "$id" ]; then token=$(curl -s "$MAIL/api/v1/message/$id" | jget Text | grep -o 'token=[A-Za-z0-9_-]*' | head -1 | cut -d= -f2); break; fi; sleep 1
done
[ -n "$token" ] && ok "invitation email arrived through the SMTP sink" || { bad "no invitation email"; exit 1; }
password="Smoke-$(openssl rand -hex 8)-Stack"
# Anonymous routes find the tenant from the host name (slug.base_domain) or, as here, X-Tenant-Slug.
pre() { curl -ks -H "x-tenant-slug: $slug" -c "$tmp/$1" "$BASE/api/v1/auth/pre-session" | jget csrf_token; }
csrf=$(pre jar0)
accepted=$(curl -ks -o "$tmp/accept.json" -w "%{http_code}" -b "$tmp/jar0" -H "x-tenant-slug: $slug" -H "x-csrf-token: $csrf" -H 'content-type: application/json' \
  -d "{\"token\":\"$token\",\"new_password\":\"$password\",\"client_kind\":\"web\"}" "$BASE/api/v1/auth/invitations/accept")
expect "invitation accepted ($(head -c 150 "$tmp/accept.json"))" "$accepted" 200
csrf=$(pre jar1)
signin=$(curl -ks -b "$tmp/jar1" -c "$tmp/jar1" -H "x-tenant-slug: $slug" -H "x-csrf-token: $csrf" -H 'content-type: application/json' \
  -H 'x-forwarded-for: 203.0.113.9' -d "{\"email\":\"$email\",\"password\":\"$password\"}" "$BASE/api/v1/auth/sign-in")
session_csrf=$(jget csrf_token <<<"$signin" 2>/dev/null || true)
[ -n "$session_csrf" ] && ok "sign-in through the proxy returns a session" || { bad "sign-in failed: $signin"; exit 1; }
expect "session cookie works: GET /me" "$(code -b "$tmp/jar1" "$BASE/api/v1/me")" 200

echo "== client IP"
stored=$(docker exec -e PGPASSWORD="$FH_POSTGRES_PASSWORD" fhstack-postgres-1 psql -U postgres -d facilityhub -Atc \
  "SELECT host(ip) FROM auth_session ORDER BY created_at DESC LIMIT 1")
if [ -n "$stored" ] && [ "$stored" != "203.0.113.9" ]; then ok "client-supplied X-Forwarded-For is not believed (session ip $stored)"; else bad "session ip is '$stored'"; fi

echo "== trusted edge (EDGE_CIDRS)"
signin_ip() {  # sign in with a spoofed X-Forwarded-For, return the address the session row recorded
  local c; c=$(pre jarx)
  curl -ks -o /dev/null -b "$tmp/jarx" -c "$tmp/jarx" -H "x-tenant-slug: $slug" -H "x-csrf-token: $c" -H 'content-type: application/json' \
    -H "x-forwarded-for: $1" -d "{\"email\":\"$email\",\"password\":\"$password\"}" "$BASE/api/v1/auth/sign-in"
  docker exec -e PGPASSWORD="$FH_POSTGRES_PASSWORD" fhstack-postgres-1 psql -U postgres -d facilityhub -Atc "SELECT host(ip) FROM auth_session ORDER BY created_at DESC LIMIT 1"
}
FH_STACK_EDGE_CIDRS=172.29.77.1/32 $S up -d --wait web >/dev/null 2>&1; wait_ready || true
expect "a trusted edge's appended client address is used, a spoofed left-most hop is not" "$(signin_ip "6.6.6.6, 203.0.113.9")" 203.0.113.9
$S up -d --wait web >/dev/null 2>&1; wait_ready || true
got=$(signin_ip 198.51.100.7)
if [ -n "$got" ] && [ "$got" != 198.51.100.7 ]; then ok "back to the default, the same header is not believed (session ip $got)"; else bad "default proxy believed a client-supplied address ($got)"; fi

echo "== file round trip"
jid() { local body; body=$(cat); jget id <<<"$body" 2>/dev/null || { echo "FAIL  create call answered: $body" >&2; exit 1; }; }
api_call() { curl -ks -b "$tmp/jar1" -H "x-csrf-token: $session_csrf" -H "idempotency-key: $(uuidgen)" "$@"; }
me=$(curl -ks -b "$tmp/jar1" "$BASE/api/v1/me")
loc=$(jget locations.0.id <<<"$me" 2>/dev/null || true)
if [ -z "$loc" ]; then
  loc=$(api_call -H 'content-type: application/json' -d '{"name":"Smoke Gym","time_zone":"America/Chicago","country_code":"US"}' "$BASE/api/v1/locations" | jid)
fi
client=$(api_call -H 'content-type: application/json' -d "{\"first_name\":\"Pat\",\"last_name\":\"Upload\",\"home_location_id\":\"$loc\"}" "$BASE/api/v1/clients" | jid)
doc=$(api_call -H 'content-type: application/json' -d "{\"client_id\":\"$client\",\"location_id\":\"$loc\",\"acceptance_method\":\"paper\",\"title\":\"Smoke upload\"}" "$BASE/api/v1/client-documents" | jid)
base64 -d > "$tmp/in.png" <<<'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
expect "PNG uploaded through the proxy (scanned by ClamAV)" "$(api_call -o /dev/null -w '%{http_code}' -X PUT -H 'content-type: image/png' -H 'x-file-name: pixel.png' --data-binary @"$tmp/in.png" "$BASE/api/v1/client-documents/$doc/paper-scan")" 200
# The API streams the stored bytes back (read from the bucket); a presigned bucket URL is used for other downloads.
curl -ks -b "$tmp/jar1" -D "$tmp/dl.headers" -o "$tmp/out.png" "$BASE/api/v1/client-documents/$doc/file?variant=paper_scan"
# files.clean re-encodes uploads (metadata stripped), so the stored bytes are the cleaned image, not identical bytes.
expect "download is the stored PNG (signature 89504e47, content-type image/png)" \
  "$(head -c 4 "$tmp/out.png" | od -An -tx1 | tr -d ' \n') $(grep -i '^content-type:' "$tmp/dl.headers" | tr -d '\r ' | cut -d: -f2)" "89504e47 image/png"
echo "--- download response headers ---"; tr -d '\r' < "$tmp/dl.headers"

echo "== upload size exception"
head -c 3145728 /dev/zero > "$tmp/three"; head -c 23068672 /dev/zero > "$tmp/twentytwo"
c3=$(api_call -o /dev/null -w '%{http_code}' -X PUT -H 'content-type: image/png' --data-binary @"$tmp/three" "$BASE/api/v1/client-documents/$doc/paper-scan")
if [ "$c3" != 413 ]; then ok "3 MiB to the upload route passes the proxy cap (app answered $c3)"; else bad "3 MiB upload refused with 413"; fi
expect "22 MiB to the upload route is refused" "$(api_call -o /dev/null -w '%{http_code}' -X PUT -H 'content-type: image/png' --data-binary @"$tmp/twentytwo" "$BASE/api/v1/client-documents/$doc/paper-scan")" 413

echo "== readiness with Redis stopped"
$S stop redis >/dev/null 2>&1
red=""; for _ in $(seq 20); do red=$(ready); [ "$red" = 503 ] && break; sleep 1; done
expect "readiness is 503 while Redis is down" "$red" 503
echo "body: $(curl -ks "$BASE/api/v1/health/ready")"
$S start redis >/dev/null 2>&1
wait_ready && ok "readiness recovers when Redis returns" || bad "readiness did not recover"

echo; [ "$fails" = 0 ] && echo "SMOKE PASS" || echo "SMOKE FAIL ($fails)"
exit $((fails > 0))
