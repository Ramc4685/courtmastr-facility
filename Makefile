# Courtmastr Facility (code name FacilityHub): local developer entry points.
COMPOSE = docker compose --env-file .env -f infra/docker-compose.yml
UV = cd backend && uv run

.PHONY: up down reset migrate lane-db seed test lint fmt api worker relay scheduler openapi web-install web web-api web-check web-test web-e2e mobile-install mobile mobile-api mobile-check mobile-test

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

seed: .env          ## idempotent demo data (docs/dev/demo-accounts.md)
	$(UV) python -m seeds.demo

test: .env          ## full suite against the Compose Postgres, then the 80% gate on domain logic
	$(UV) pytest
	$(UV) coverage report --fail-under=80 --include='app/modules/*/service.py,app/modules/billing/*.py,app/modules/pos/*.py,app/adapters/stripe_connect.py,app/adapters/fake_payments.py,app/ports/payment_provider.py,app/core/inbound_webhooks.py,app/modules/clients/households.py,app/modules/clients/activity.py,app/modules/clients/merge.py,app/modules/platform/privacy.py,app/modules/platform/files.py,app/modules/*/auth.py,app/modules/*/staff.py,app/modules/*/rbac.py,app/modules/*/domain/*,app/core/ids.py,app/core/pagination.py'

lint:               ## ruff lint and format check
	$(UV) ruff check . && uv run ruff format --check .

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
