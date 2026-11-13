# Courtmastr Facility (code name FacilityHub): local developer entry points.
COMPOSE = docker compose --env-file .env -f infra/docker-compose.yml
UV = cd backend && uv run

.PHONY: up down reset migrate lane-db lane-env lane-drop seed test lint fmt typecheck boundaries contract api-diff api worker relay scheduler openapi web-install web web-api web-check web-test web-e2e mobile-install mobile mobile-api mobile-check mobile-test

.env:
	cp .env.example .env

up: .env            ## start Postgres, Redis and Mailpit and wait until healthy
	$(COMPOSE) up -d --wait

down:               ## stop the services (data volume is kept)
	$(COMPOSE) down

reset:              ## stop the services and DELETE the data volume (clean slate)
	$(COMPOSE) down -v

migrate: .env       ## apply Alembic migrations as fh_owner
	$(UV) alembic upgrade head

lane-db: .env       ## create (if missing) and migrate the databases named by FH_DB_NAME / FH_TEST_DB_NAME
	$(UV) python -m app.cli lane-db
	$(UV) alembic upgrade head
	cd backend && FH_ENV=test uv run alembic upgrade head

lane-env:           ## in a worktree: write .env from the main checkout's; LANE=name [API_PORT=n WEB_PORT=n]
	$(UV) python -m app.cli lane-env --lane "$(LANE)" $(if $(API_PORT),--api-port $(API_PORT)) $(if $(WEB_PORT),--web-port $(WEB_PORT))

lane-drop: .env     ## DELETE a lane's two databases after it merges (refuses the main ones); [LANE=name], default this .env's
	$(UV) python -m app.cli lane-drop $(if $(LANE),--lane "$(LANE)")

seed: .env          ## idempotent demo data (docs/dev/demo-accounts.md)
	$(UV) python -m seeds.demo

test: .env          ## full suite against the Compose Postgres, then the 80% gate on domain logic
	$(UV) pytest
	$(UV) coverage report --fail-under=80 --include='app/modules/*/service.py,app/modules/billing/*.py,app/modules/pos/*.py,app/adapters/stripe_connect.py,app/adapters/fake_payments.py,app/ports/payment_provider.py,app/core/inbound_webhooks.py,app/modules/clients/households.py,app/modules/programs/groups.py,app/modules/programs/checkout.py,app/modules/programs/selfservice.py,app/modules/programs/forms.py,app/modules/programs/tools.py,app/modules/clients/activity.py,app/modules/clients/merge.py,app/modules/platform/privacy.py,app/modules/platform/files.py,app/modules/*/auth.py,app/modules/*/staff.py,app/modules/*/rbac.py,app/modules/*/domain/*,app/modules/reporting/registry.py,app/core/ids.py,app/core/pagination.py,app/modules/integrations/feeds.py,app/modules/integrations/quickbooks.py'

lint:               ## ruff lint and format check
	$(UV) ruff check . && uv run ruff format --check .

typecheck:          ## mypy over backend/app (config and per-module overrides in backend/pyproject.toml)
	$(UV) mypy

boundaries:         ## import-linter: the bounded-context contracts of overview section 2
	$(UV) lint-imports

contract: .env      ## long Schemathesis run (every operation, FH_CONTRACT_EXAMPLES each, default 25); `make test` runs a small one
	cd backend && FH_CONTRACT_SAMPLE=1 FH_CONTRACT_EXAMPLES=$${FH_CONTRACT_EXAMPLES:-25} uv run pytest tests/test_contract_schemathesis.py --no-cov

# Breaking changes against the merge base with main (API_DIFF_BASE overrides the ref); needs oasdiff on PATH.
# Allowed exceptions live in docs/api/breaking-allow.txt, each with its reason.
api-diff:           ## oasdiff: fail on breaking changes in backend/openapi.json unless listed in docs/api/breaking-allow.txt
	git show $$(git merge-base $${API_DIFF_BASE:-main} HEAD):backend/openapi.json | oasdiff breaking - backend/openapi.json --fail-on ERR --err-ignore docs/api/breaking-allow.txt

fmt:
	$(UV) ruff check --fix . && uv run ruff format .

api: .env           ## API on http://localhost:8100 (FH_API_PORT overrides)
	$(UV) python -m app.cli serve

worker: .env        ## Dramatiq worker
	$(UV) dramatiq app.worker

relay: .env         ## outbox relay loop
	$(UV) python -m app.relay

scheduler: .env     ## the clock: enqueues the periodic jobs (autopay, renewals, expiries, hold reaper) per tenant
	$(UV) python -m app.scheduler

openapi: .env       ## export the generated OpenAPI document to backend/openapi.json
	$(UV) python -m app.cli openapi > openapi.json

WEB = cd web && pnpm

web-install:        ## web dependencies and the Playwright chromium build
	$(WEB) install && pnpm exec playwright install chromium

web:                ## Vite dev server on http://localhost:5183 (FH_WEB_PORT overrides; proxies /api to the API port)
	$(WEB) dev

web-api:            ## regenerate web/src/api/schema.d.ts from backend/openapi.json
	$(WEB) gen:api

web-check:          ## typecheck and lint the web app
	$(WEB) typecheck && pnpm lint

web-test:           ## Vitest unit and component tests
	$(WEB) test

web-e2e:            ## Playwright smoke test; needs make api running and seeded data
	$(WEB) e2e

MOBILE = cd mobile && pnpm

mobile-install:     ## member app dependencies (Expo; Node 22 + pnpm)
	$(MOBILE) install

mobile:             ## Expo dev server; press i for the iOS Simulator (talks to EXPO_PUBLIC_API_ORIGIN, see mobile/README.md)
	$(MOBILE) start

mobile-api:         ## regenerate mobile/src/api/schema.d.ts from backend/openapi.json
	$(MOBILE) gen:api

mobile-check:       ## typecheck and lint the member app
	$(MOBILE) typecheck && pnpm lint

mobile-test:        ## Jest + React Native Testing Library
	$(MOBILE) test

# --- Operations (chip O1): the container stack and the backup drill. See docs/ops/. ---
STACK = docker compose --env-file infra/docker/.env.stack -f infra/docker/compose.stack.yml --profile mail

.PHONY: stack-up stack-smoke stack-down backup-drill backup-drill-fresh

# The app's own secrets are generated, never copied: production refuses the dev and example values.
infra/docker/.env.stack:
	sed -e "s|^FH_DATA_KEY=.*|FH_DATA_KEY=$$(openssl rand -base64 32)|" \
	    -e "s|^FH_OPERATOR_TOKEN=.*|FH_OPERATOR_TOKEN=$$(openssl rand -hex 32)|" infra/docker/stack.env.example > $@

stack-up: infra/docker/.env.stack   ## build and start the whole stack on its own project (fhstack) and ports; https://localhost:18443
	$(STACK) up -d --build --wait --wait-timeout 900

stack-smoke:        ## header, sign-in, upload/download and readiness checks through the proxy
	infra/docker/smoke.sh

stack-down:         ## stop the stack and delete its volumes
	$(STACK) down -v

backup-drill: .env  ## back up this lane's database via the dev Postgres container, restore to a scratch database, check it
	set -a; . ./.env; set +a; export PGPASSWORD="$$FH_POSTGRES_PASSWORD" PGUSER=postgres PGDATABASE="$${FH_DB_NAME:-facilityhub}" \
	  FH_BACKUP_PASSPHRASE=lane-drill-passphrase FH_BACKUP_DIR=var/backups FH_BACKUP_KEEP=2 \
	  FH_PG_EXEC="docker exec -i -e PGPASSWORD -e PGUSER facilityhub-postgres-1" \
	  FH_EXPECTED_HEAD="$$(cd backend && uv run alembic heads | cut -d' ' -f1)"; \
	infra/backup/backup.sh && infra/backup/drill.sh

backup-drill-fresh: backup-drill  ## the same drill against a throwaway Postgres with no fh_* roles (the lost-host case)
	set -a; . ./.env; set +a; export FH_BACKUP_PASSPHRASE=lane-drill-passphrase FH_EXPECTED_HEAD="$$(cd backend && uv run alembic heads | cut -d' ' -f1)"; \
	infra/backup/drill-fresh.sh "$$(ls -t var/backups/*.enc | head -1)"

# --- Performance (chip O2): load test and budget. See docs/ops/performance-budget.md. Not part of test or CI. ---
.PHONY: perf-seed perf perf-profile perf-check

perf-seed: .env     ## grow the demo tenant to the load-test data set (5,000 clients, a month of bookings, ...); after make seed
	cd backend && FH_CONFIG_DIR="$$PWD/../perf/config" uv run python -m seeds.perf

perf: .env          ## start the lane API (prod shape, perf/config overlay), run the front-desk load test, stop it; ARGS="--users 20"
	perf/run.sh $(ARGS)

perf-profile: .env  ## query count, slowest SQL and its EXPLAIN ANALYZE per request, in process; LABELS="calendar.week report.run"
	cd backend && FH_CONFIG_DIR="$$PWD/../perf/config" PYTHONPATH=. uv run python ../perf/profile.py $(LABELS)

perf-check:         ## fail when a p95 in the newest perf/results run exceeds perf/budget.json by the margin (MARGIN=0.25)
	$(UV) python ../perf/loadtest.py --check "$$(ls -t ../perf/results/run-*.json | head -1)" --margin $${MARGIN:-0.25}
