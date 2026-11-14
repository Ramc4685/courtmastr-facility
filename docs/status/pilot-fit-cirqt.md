# Pilot fit check: CIRQT

CIRQT is an unmanned facility with four convertible courts. Badminton and pickleball can be played on all four. Courts 2 and 3 each also become one volleyball court; the owner settled this as reading (ii). Rentals are the main revenue, the membership fee is small, and there are badminton and volleyball leagues and paid coaching.

This check builds CIRQT in the product and drives it the way the owner would. The first run changed no product code; two gaps have since been closed in the product.

- Seed: `backend/seeds/cirqt.py`. It is idempotent and refused outside dev and test.
- Scenarios: `backend/tests/test_pilot_cirqt.py`. Every gap is a strict `xfail` whose reason states the gap, so a test turns red the day its gap closes.
- Screenshots: `docs/status/pilot-cirqt/`.

**Result: 18 pass, 0 fail, 7 gaps.** Run on 2026-11-13 against Alembic head 2001 (league set scoring and league nights added since the first run).

## Assumptions (owner to confirm)

These are the values the seed uses. Marked items are assumptions.

- **Zone:** America/Chicago.
- **Hours:** open 06:00 to 23:00 every day *(assumed)*.
- **Prime time:** 18:00 to 22:00 every day. At prime, members pay $40 a court-hour for volleyball and $25 for badminton and pickleball.
- **Off-prime:** 20% less than prime *(assumed; the owner said 10 to 30%)*.
- **Morning pickleball:** $12 until noon *(the owner said $10 to $15)*.
- **Guests:** pay 20% more than members *(assumed)*. Guest prices are therefore:
  - badminton: $24 off-prime, $30 prime;
  - volleyball: $38.40 off-prime, $48 prime;
  - morning pickleball: $14.40.
- **Membership:** $10 a month, adult and junior *(assumed)*.
- **Club rate:** a club or coach holding the same weekly slot pays 15% less *(assumed)*.
- **Volleyball changeover:** 10 minutes before and after, on Courts 2 and 3.
- **One-lesson package:** $50 *(assumed)*.
- **Independent coach:** gets 70% of lesson money *(assumed)*.
- **Staff coach:** paid $30 per session *(assumed)*.
- **Help line:** the support number shown to members is synthetic, +1 309 555 0100. When something fails on site, staff open the door remotely.

## Scenarios

| # | Scenario | Result |
|---|---|---|
| a | A member books and pays for Court 1 online. Overlaps are refused, and the database exclusion constraint is the final arbiter. | pass |
| b | Volleyball on Court 2 or 3 blocks badminton and pickleball on that court, including the 10-minute changeover. The neighbouring court stays free. | pass |
| c | A committed league night refuses public rentals on its courts. | pass |
| c | A night blocked first by staff is used by the league scheduler. | pass for scheduling. Staff hold the courts as that league's night (Schedule tab, "Hold a league night"); its games take their slots out of the hold. A plain calendar block still counts as a clash. Known limits below. |
| d | Badminton and volleyball leagues record scores and standings. | pass |
| d | Set-by-set or game scores. | pass. Badminton is best of 3 to 21, win by 2, cap 30; volleyball best of 5 to 25, deciding set to 15. Every set is checked, the score is the sets won, and standings break ties on set ratio, then points ratio. |
| e | A parent buys a junior membership for a child. The child gets no marketing and does not appear on public pages. | pass |
| e | A minor cannot be opted into marketing. | **gap**: no minor rule |
| e | A minor cannot get a buying login. | **gap**: the invitation works like an adult's |
| f | Desk work: check-in, a walk-in rental, cash, cancel, refund. | pass (secondary, because CIRQT is unmanned). The front desk role may not refund, so a manager does it. |
| g | Prime and off-prime pricing in Chicago time, with a booking that straddles 18:00 ($24 + $30), the noon morning edge, Saturday, and the public slot prices. | pass |
| g | Member prices on bookings. | **gap**: everyone pays the guest price |
| h | Cancellation cut-off and late fee. The paid amount becomes account credit; a manager can waive the fee. | pass |
| h | No-show rule for rentals. | **gap** |
| i | Daily and monthly utilisation and revenue reports. | pass, via a workaround: an availability window per court. Changeover minutes count as held time. |
| i | Utilisation measured from opening hours. | **gap** |
| j | A newcomer goes from finding CIRQT to signing up, paying the membership and paying for a court, with no staff involved. | pass. One set-up step is needed first: turn on self sign-up. |
| k | Staff book several courts for several weeks in one go, on one invoice. | pass |
| k | A club holds a weekly prime slot for 8 weeks at 15% off ($25.50 a week). | pass |
| k | A member bulk-books online. | **gap**: one court and one occurrence per checkout |
| l | A member buys a lesson package and enrols in a coached lesson. The lesson holds its court. | pass |
| m | A parent buys a lesson for a child and drops the child off. | pass |
| m | Online, a parent can rent only in their own name, so a child cannot be put on a court alone from the portal. | pass |
| m | A child cannot be booked on a court without a parent on the booking. | **gap**: staff can do it, and a rental has no participant list or age rule |
| n | Staff coach versus independent coach: pay rates and what the coach sees. | pass (see below) |

## What is missing, ranked for CIRQT

1. **Building control: door codes and court lights.** There is no adapter, no booking-bound code, no booking start or end trigger and no remote unlock route. For an unmanned site this is the blocker. Details are below.
2. **Member prices on rentals.** Rentals price every payer as a guest; screenshot 05 shows a member billed $54 (guest $24 + $30) for 17:00-19:00, and the portal (screenshot 15) tells a member "members pay less" while quoting the guest $24. The member price and membership-type rules are stored but never used on bookings. Rentals are the main revenue, so this matters more than anything except the door.
3. **Recurring and bulk booking online, and a contract object for clubs.** Staff can book a recurring weekly slot on a discounted rate, but:
   - a member or club cannot do it themselves;
   - there is no agreement with a term or renewal, only a series of bookings on one invoice.
4. **Kids rules.** The product cannot express "a child who plays must have a parent on the booking":
   - a rental has one client and no age setting;
   - sessions have no age limits either.

   It also has no minor guard on marketing opt-in or on portal invitations.
5. **No-shows and overstays for rentals.** There is no mark, no fee and no rule.
6. **Paying independent coaches.** Payroll computes the commission line, but nothing pays out and there is no revenue split at checkout.
7. **Utilisation from opening hours.** The report needs per-court availability windows.
8. ~~**League details.**~~ Closed: league nights the scheduler fills, and set-by-set scoring with set and points ratio in the standings. League nights work for scheduling, with three known limits until a follow-up redesign (leagues README, "League nights: known limits"):
   - a game that is rescheduled, postponed or cancelled does not give its slot back to the night, so a public booking can take it; staff re-block the old slot;
   - with a night on a parent court and a game on one half, the sibling half opens for that hour;
   - two games carved at the same moment can report a false clash; the loser is left unschedulable with the reason, never double-booked.

## Setting CIRQT up: screens versus API

The seed does all of this through service functions. A real owner can do most of it on screens:

- courts and groups (Resources);
- opening hours (location);
- rental types with buffers, rates and price rules (Rental setup);
- memberships;
- leagues, teams and venues.

Steps that are API-only or easy to miss:

- **Self sign-up** is off by default (`PUT /locations/{id}/portal-settings` with `allows_self_signup`). Without it a newcomer is refused with `signup-disabled`.
- **The coach's calendar column**, `linked_resource_id` on the staff user. The seed sets it directly.
- **Utilisation** needs per-court availability windows that copy the opening hours.
- **The portal shows sessions only 30 days ahead** by default (`visible_range_days`).

## Building control (door code and court lights)

Nothing in the product drives a door or a light today. The access module reserves a `door` check-in channel, but nothing writes to it. The permissions `access.door.unlock` and `access.device.manage` are registered with no route behind them (CHK-15 and CHK-16 are deferred).

**What an adapter could hook into today:**

| Need | Existing hook | Limit |
|---|---|---|
| Know about a booking | Events `scheduling.booking.created`, `.rescheduled` and `.cancelled`; `rentals.rental.booked` and `.cancelled`, published through the outbox with the booking id | These fire when the booking changes, not when it starts or ends |
| Act at start and end | The scheduler runs hourly, plus a per-minute hold reaper. Automation rules can trigger on an event after a delay. Engagement reminders run 15 minutes to 14 days before a session. | There is no booking-start or booking-end job, and per-court timing needs minute precision |
| Who may enter | Check-in evaluation (`access/domain/evaluate.py`): membership, booking and waiver rules, plus `client_bookings_starting` arrival marking; the kiosk | It evaluates a scan; it never issues or opens anything |
| What a person carries | Credentials of kind barcode, rfid, app_card and wallet_pass (the wallet pass uses a fake adapter) | These are long-lived per person, not per booking |
| Sending the code | The notification port (`ports/notifications.py`, `Notifier.deliver`) and email | There is no SMS or push provider |
| Per-court mapping | Resources: Court 1 to 4, and each booking's resource holds, including buffers | There is no device or zone record linking a court to a light circuit or a door |

**What a booking-bound one-time code needs:**

- A validity window around the booking, for example 15 minutes before the start until the end. It must be in the location's zone and must account for the changeover buffers.
- A choice between one code per booking (shared with the group) and one per participant. For rentals only the booker is known, because rentals have no participant list.
- Revocation when the booking is cancelled, plus reissue when it is rescheduled.
- Issuing at or shortly before arrival, through the notification port.
- An audit record of each issue and use.

**Missing:**

- a device or zone model;
- the code itself;
- start and end triggers at minute precision;
- the door adapter port;
- the remote-unlock route behind `access.door.unlock`;
- light on and off per court.

## Unmanned operation

| Situation | What the product has | Missing |
|---|---|---|
| No-show | Cancellation cut-off and late fee; paid money becomes account credit | A rentals no-show mark, fee or rule. Only shared-booking participants carry a `no_show` attendance, with no money attached. |
| Overstay | Nothing beyond holds ending at the booked time; the buffer protects the next group on volleyball courts | Detection (lights or door), a warning, overtime billing |
| Minor alone | The portal rents only in the parent's own name; there are guardianship roles | Age rules on rentals and sessions; a "parent on the booking" requirement; a minor guard on portal invites and marketing |
| Payment failure | Online checkout must succeed before a rental is confirmed; tentative holds expire through the reaper; collections and portal lockout exist for debts | A link between payment state and door access |
| Door or lights not responding | The location record carries a phone number to show members | A remote unlock route, a device health check, alerts to staff |
| Tailgating | Check-in records each scan | Anything that counts people at the door; that is hardware |

## Staff coach versus independent coach

The seed sets up two coaches:

- **Rowan, staff coach.** A staff sign-in with the coach role, linked to his own trainer column, paid $30 per session through payroll pay rates.
- **Ines, independent coach.** A client record so she can rent courts, plus a payee and trainer column with no sign-in, and a 70% commission rate.

| Question | Answer in the product |
|---|---|
| Who creates the lesson | Staff. They create a session booking with the coach's column and a court. A coach with a sign-in can see the calendar, but an independent coach without one cannot create anything. |
| Who sets the price | The facility, through a package plan (here "One lesson", $50). The coach cannot set their own price. |
| Where the student's money goes | To CIRQT. The portal sells the package, and the money is facility revenue in the RENTALS category. |
| How the coach is paid | Payroll runs compute a per-session amount or a percentage commission line. Nothing pays out. The alternative is that the coach rents the court like anyone and collects from students themselves, outside the product. |
| What a signed-in coach sees | The whole facility schedule (all courts and both coaches, with a New booking button; screenshot 18), their own sessions, their shifts, the payee names and the client list. They do not see pay rates (their own included) or payroll runs. |
| What it cannot do | Payouts to coaches, revenue share at checkout, coach-set prices, or coach self-service for an independent coach without a staff seat. |

## Recurring and bulk pricing

There is no rental contract or plan for court time. A club's weekly slot is a staff-booked recurring rental with these parts:

- a pattern (weekly, a count or an end date);
- one or several courts;
- one invoice for the series;
- a separate rate ("Weekly club") that carries a 15% discount rule.

Rental plans exist (prepaid hours, with a portal purchase), but they are a different thing from a held slot.

Online, a member books one court and one occurrence per checkout.

## Kids

Parents can do the following:

- buy junior memberships and lesson packages for a child;
- enrol the child in a coached session and drop them off.

Online rentals refuse a child's name; this is an accident of portal scoping, not a rule.

There are no age or guardian rules on rentals or sessions. Programs have only an age-division label.

## Volleyball note

Reading (ii) is the real setup and fits: each volleyball court is the same resource as its badminton or pickleball court, so a hold on one blocks the others.

If one volleyball court ever spanned Courts 2 and 3, the product could model it in either of two ways:

- a parent resource over both courts, because holds cover descendants;
- a league venue with both courts.

This was not built.

## Open questions for the owner

1. Should members pay the member price on rentals and guests pay more, or should everyone pay one price? This decides how urgent gap 2 is.
2. Who issues door codes, and how early before a booking? One code per booking or per person? Which door or lighting hardware is installed?
3. Do independent coaches sell lessons through CIRQT (you collect and pay them), or do they rent courts and collect from students themselves?
4. Is a club's weekly slot a fixed-term agreement (for example a season with a renewal), or open-ended?
5. From what age may a child play without a parent present?
6. Confirm the assumed figures listed at the top.

## Dev sign-ins

After `uv run python -m seeds.cirqt` (slug `cirqt`), the password is `cirqt-pilot-2026` and every email is `@cirqt.example.com`.

| Role | Sign-ins |
|---|---|
| Staff | `owner`, `manager`, `front-desk`, `league-admin`, `coach` |
| Portal | `member`, `parent` |
