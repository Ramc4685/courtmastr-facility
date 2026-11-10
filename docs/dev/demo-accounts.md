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
| Client (Morgan Member) | member@courtside-demo.example.com | sign in with `"audience": "client"` |

Locations: **Courtside Downtown** (`America/Chicago`) and **Courtside West** (`America/Los_Angeles`).

Six demo clients (four at Downtown, two at West). Billing: a `SALES` tax of 8.25%, revenue categories
`RENTALS` and `RETAIL` (taxed), `MEMBERSHIPS` and `PROGRAMS` (untaxed), and one paid invoice for Morgan Member
with change left on account. Payments use the fake processor; card and bank tokens that script each outcome
(`tok_card_ok`, `tok_card_declined`, `tok_ach_ok`, ...) are listed in `backend/app/adapters/fake_payments.py`.

Memberships and packages: plans `Adult monthly` (prorated to the 1st, bundles the `Member lesson pair`
package, sold online), `Adult annual` and the free `Guest of a member`; Morgan Member holds an active monthly
contract shared with Mia, Riley Reyes an annual one with a freeze two weeks out. Package plans `Ten private
lessons` (sold online, shared with relatives), `Free trial lesson`, `Unlimited month` and the recurring `Four
lessons a month`; Morgan has a ten-pack with two lessons used and one booked. No scheduler runs the daily jobs
yet; run them by hand from `backend/`:

```
uv run python -c "from app.bootstrap import bootstrap; bootstrap(); from app.modules import memberships, packages; from app.core.db.platform import resolve_tenant; t = str(resolve_tenant(slug='courtside-demo').id); print(memberships.service.run_membership_day.fn(t), packages.service.run_package_day.fn(t))"
```

Tenant resolution in development: send `X-Tenant-Slug: courtside-demo`, or call the API as
`http://courtside-demo.localhost:8100`. Emailed links (magic link, reset, invite) land in Mailpit at
http://localhost:58025 and are also written to the API log.

Operator token for `POST /api/v1/operator/tenants` (tenant onboarding): the `FH_OPERATOR_TOKEN` value in `.env`.
