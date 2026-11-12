#!/bin/sh
# Container entrypoint: the first argument picks the process. Anything else is exec'd as given.
set -eu
cd /srv/fh/backend
case "${1:-api}" in
  api)       exec uvicorn app.main:app --host 0.0.0.0 --port 8100 --workers "${FH_API_WORKERS:-2}" --no-access-log ;;
  worker)    exec dramatiq app.worker --processes "${FH_WORKER_PROCESSES:-1}" --threads "${FH_WORKER_THREADS:-8}" ;;
  relay)     exec python -m app.relay ;;
  scheduler) exec python -m app.scheduler ;;
  migrate)   exec alembic upgrade head ;;
  s3-init)   exec python /usr/local/bin/s3-init.py ;;
  cli)       shift; exec python -m app.cli "$@" ;;
  *)         exec "$@" ;;
esac
