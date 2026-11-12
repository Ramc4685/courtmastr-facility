#!/usr/bin/env bash
# `make perf`: start the lane API in the production process shape (uvicorn, FH_API_WORKERS workers, default 2,
# no reload, no access log) with the perf config overlay, run the load test, stop the API. Extra arguments go to
# perf/loadtest.py (for example --users 20 --duration 300).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
PORT="${FH_API_PORT:-8100}"
if curl -fsS "http://127.0.0.1:${PORT}/api/v1/health/live" >/dev/null 2>&1; then
  echo "Something already answers on port ${PORT}: stop it first (make perf starts its own API)." >&2
  exit 1
fi
LOG="perf/results/api-$(date +%Y%m%d-%H%M%S).log"
mkdir -p perf/results
(cd backend && FH_CONFIG_DIR="$PWD/../perf/config" exec uv run uvicorn app.main:app --host 127.0.0.1 \
  --port "$PORT" --workers "${FH_API_WORKERS:-2}" --no-access-log) >"$LOG" 2>&1 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null; wait "$API_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:${PORT}/api/v1/health/ready" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/api/v1/health/ready" >/dev/null || { echo "API did not become ready; see $LOG" >&2; exit 1; }
(cd backend && uv run python ../perf/loadtest.py --base "http://127.0.0.1:${PORT}/api/v1" "$@")
