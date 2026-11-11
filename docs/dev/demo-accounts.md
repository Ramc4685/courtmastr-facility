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

POS (Courtside Downtown): a "Pro shop" category with three stocked products (barcodes `0001000500`,
`0001000600`, `0001000700`; the tennis balls sit below their reorder level), a `Front desk` register with those
favourites, a `Staff 10%` discount preset and four `Demo racket` rentals. No drawer is open; sign in as front
desk and open one from the register screen.

Memberships and packages: plans `Adult monthly` (prorated to the 1st, bundles the `Member lesson pair`
package, sold online), `Adult annual` and the free `Guest of a member`; Morgan Member holds an active monthly
contract shared with Mia, Riley Reyes an annual one with a freeze two weeks out. Package plans `Ten private
lessons` (sold online, shared with relatives), `Free trial lesson`, `Unlimited month` and the recurring `Four
lessons a month`; Morgan has a ten-pack with two lessons used and one booked. The lesson packages pay for
Downtown's `Private Lesson` sessions (register Morgan from a lesson on the Schedule and pick "Pay with").
`Court club monthly` is bound to the `Liability waiver`: a sale waits as upcoming until the client signs.
`make scheduler` (with `make worker`) runs the daily jobs; to run them once by hand from `backend/`:

```
uv run python -c "from app.bootstrap import bootstrap; bootstrap(); from app.modules import memberships, packages; from app.core.db.platform import resolve_tenant; t = str(resolve_tenant(slug='courtside-demo').id); print(memberships.service.run_membership_day.fn(t), packages.service.run_package_day.fn(t))"
```

Tenant resolution in development: send `X-Tenant-Slug: courtside-demo`, or call the API as
`http://courtside-demo.localhost:8100`. Emailed links (magic link, reset, invite) land in Mailpit at
http://localhost:58025 and are also written to the API log.

Operator token for `POST /api/v1/operator/tenants` (tenant onboarding): the `FH_OPERATOR_TOKEN` value in `.env`.

## Demo facility (build module 2)

`make seed` gives both locations a calendar for the current and the following week:

- **Downtown:** Courts 1 and 2 (each split into halves A and B) and Court 3, Field 1 (North, South), Studios
  A and B, an online room, trainers Chloe Coach and Dana Park (Dana always holds Studio B). Classes: Yoga
  Flow, Spin, Junior Tennis Clinic, private lessons with Chloe, Open Play; a court resurfacing block and a
  floor shift. Yoga and the clinic have participants; the first private lesson is full with one client
  waiting. The coach sign-in (`coach@...`) is linked to the Chloe Coach resource, so it can change only
  bookings on that column.
- **West:** two courts, a turf field in halves, a studio, trainer Eli Stone, two weekly classes.
- Both locations are closed on the next New Year's Day (a blackout).

## Demo rentals (build module 3)

At Downtown, **Court rental** (Courts 1 to 3) is bookable online: Standard rate $40/hour ($32 member price,
unused until memberships exist), $50 evenings 17:00-22:00, $55 on weekends, plus sales tax; a "Tournament
day" flat rate; 25% deposit online; 24-hour cut-off with a 50% late-cancel fee. Morgan Member has a weekly
Tuesday 19:00 rental on Court 3 (four weeks, billed on one invoice), Riley Reyes has an unbilled Thursday
rental in the queue, and Jordan Okafor bought the **10-hour court pack** and used two hours of it on Friday.

## Demo check-in (build module 10)

At Downtown: barcode `DEMO-CARD-0001` belongs to Morgan Member (scan or type it on Check-in), two earlier
check-ins show under Recent, and a "Front door kiosk" device is registered. To try the kiosk, open Check-in >
Kiosks, create a pairing code, open `/kiosk` in another browser and enter it; "Mem" finds Morgan M.
