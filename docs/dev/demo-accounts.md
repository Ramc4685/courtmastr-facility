# Demo accounts (development only)

Created by `make seed` in the tenant **Courtside Demo Club** (slug `courtside-demo`). The seed refuses to
run outside the `dev` and `test` environments. Never use these values anywhere else.

Password for every account: `courtside-demo-2026`

| Role | Email | Locations |
|---|---|---|
| Owner | owner@courtside-demo.example.com | all |
| Admin | admin@courtside-demo.example.com | all |
| Manager | manager@courtside-demo.example.com | Courtside Downtown |
| Front Desk | front-desk@courtside-demo.example.com | Courtside Downtown |
| Coach/Trainer | coach@courtside-demo.example.com | Courtside Downtown |
| League Manager | league-admin@courtside-demo.example.com | Courtside Downtown |
| Scorekeeper | scorekeeper@courtside-demo.example.com | Courtside Downtown |
| View Only | view-only@courtside-demo.example.com | Courtside Downtown |
| Client (no profile yet) | member@courtside-demo.example.com | sign in with `"audience": "client"` |

Locations: **Courtside Downtown** (`America/Chicago`) and **Courtside West** (`America/Los_Angeles`).

Tenant resolution in development: send `X-Tenant-Slug: courtside-demo`, or call the API as
`http://courtside-demo.localhost:8100`. Emailed links (magic link, reset, invite) land in Mailpit at
http://localhost:58025 and are also written to the API log.

Operator token for `POST /api/v1/operator/tenants` (tenant onboarding): the `FH_OPERATOR_TOKEN` value in `.env`.
