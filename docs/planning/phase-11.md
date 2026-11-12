# Phase 11: online self-service and the member app (Wave 3)

Date: 2026-11-12. Phase branch: `claude/phase11-wave3-48da13`, cut from `main` at `752a99b` (Phase 9 merged).
Source: `docs/planning/phase-features.md` section "Phase 11" (36 features: 15 P0, 15 P1, 6 P2) and
`docs/planning/remaining-work.md` section 4 "Wave 3". Full autonomy from the owner; nothing goes to `main` from
here: the gated phase-branch head goes back to the Phase 0 session.
Status: **planned.** Chips not started.

## How the phase runs

One coordinating session plans, briefs, reviews and merges; it does not build. Each chip is its own Opus session
in its own worktree, cut from the phase branch, with its own lane databases. **At most three chips at once**
(Phases 12 and 14 run beside this one). A chip commits to its own branch and never pushes. The coordinator
reviews each chip's diff, merges it into the phase branch, re-points the chip's first `down_revision`,
regenerates `backend/openapi.json`, `web/src/api/schema.d.ts` and `mobile/src/api/schema.d.ts`, and runs the
gate. When every chip is merged, a Fable reviewer reads the whole phase diff across lanes and a second Fable
reviewer does the security review the wave plan requires after Phase 11. Blocking findings are fixed before the
hand-back.

**Gate**, per chip in its lane and on the phase branch after every merge:
`make lint typecheck boundaries test web-check web-test`, the Playwright specs for every screen the chip touched
with `--workers=1`, and for any chip that touches `mobile/`: `make mobile-check mobile-test`.

Neighbours: Phase 14 (wave 6, `1400s`) is running now and owns `programs` event forms and group tools, `leagues`,
`resources` lockers, `rentals` locker rentals and plans, `scheduling` direct links and shared bookings, and
`packages` post-billed periods. Phase 12 (reports, `1600s`) owns `reporting`. Phases 13 (member communication,
push provider) and 16 are parked. Phase 8's rules stand: `core/*`, `infra/*`, `ports/storage.py` and
`platform/files.py` are asked about, not edited. Billing is no longer locked (Phase 9 is on `main`), but every
portal sale still ends in `billing.checkout.secure_online_checkout` and billing changes stay small and named in
the chip's merge note.

## State checked before planning

From `docs/status/README.md`, `03-rentals.md`, `05-memberships-packages*.md`, `06-programs.md`, `10-checkin.md`,
`13-assessments.md`, `14-engagement.md`, `17-mobile.md` and `backend/openapi.json` at `752a99b`:

- **Portal (web).** `/portal/*` behind `RequireClient` with Home, Sessions, Programs, Bookings (rentals: search,
  hold, pay by new card, abandon, cancel), Memberships, Packages, Invoices, Statement, Inbox, Profile. Tenant
  comes from the host or `X-Tenant-Slug`; the web app has no slug routing (SSP-01). `GET /public/portal-config`,
  `GET /public/branding` and `GET /public/portal-terms` exist; no theming and no recorded terms acknowledgment
  (SSP-14). Portal access is staff-invited only: no public sign-up (SSP-05). Sessions are a list, not a calendar
  (SSP-12). Packages sell in the portal but not inline at booking (SSP-08).
- **Phase 9 on main.** Card entry (Payment Element, bank, 3-D Secure, `confirmPortalPayment`), coupons at portal
  checkout (`quotePortalCoupon`, SSP-11 done), portal receipts and statements, invoice and receipt PDFs.
- **Rentals.** RNT-06 and SSP-04: backend and portal screen built; `confirmPortalRental` takes a new card token
  only and does not go through `secure_online_checkout`. No per-location portal rental defaults.
- **Memberships and packages.** MEM-09 and PKG-09: portal buy with a new card only, no stored-method option.
- **Programs.** REG-10: deposits stored but not charged separately, no instalment plans. REG-12: multi-participant
  checkout through `secure_online_checkout`, no guest checkout. Coupons now work.
- **Virtual sessions.** CLS-08 and SSP-18 not built; the `virtual_room` resource kind exists;
  `app/ports/video_meeting.py` has `FakeVideo` (a simulated meeting provider).
- **Assessments.** FIT-05 partial: portal results and bests with tenant sharing settings; no per-client share
  link and no web portal progress page beyond home.
- **Mobile.** On the real portal API: shared multi-tenant app, facility by code and deep link, password and magic
  link, biometric unlock, household switch, rolling-code card (APP-06 done), invoices paid with a saved method,
  inbox, progress, push plumbing (no provider). Missing: `getPublicAppConfig` and `searchAppDirectory` (specified
  in `docs/api/openapi-programs.yaml` with `getAppConfig` and `putAppConfig`, never built), a session listing
  location filter, new-card entry and in-app buying, wallet pass, every P1/P2 content feature.
- **Check-in.** CHK-13: rotating signed QR accepted at kiosk and window; no wallet pass.
- The status note that `putRegisterFavorites` serves APP-13 is wrong: it is the POS register favorites route.

## Chips

| Chip | Features | Owns | Migrations | Lane DB / ports | Starts |
|---|---|---|---|---|---|
| **A. Portal entry and accounts** | SSP-01, SSP-05, SSP-14, SSP-13, REG-12, SSP-07, SSP-15 | portal shell, slug routing, theming, menu, public sign-up and guest checkout, terms acknowledgment; `engagement` portal settings, `auth` portal sign-up, `documents` terms acceptance, `programs/checkout.py` guest path | 1501 to 1519 | `p11a`, 8501 / 5501 | batch 1 |
| **B. Portal booking and buying** | SSP-04, RNT-06, SSP-08, SSP-12, CLS-08, SSP-18, MEM-09, PKG-09, REG-10, FIT-05 | portal pages for sessions, calendar, rentals, memberships, packages, progress; stored-method sales; virtual sessions in `scheduling`; deposits and instalments in `programs` registration config and `billing` | 1521 to 1539 | `p11b`, 8502 / 5502 | batch 1 |
| **C1. Member app core** | APP-01, APP-02, APP-06, APP-19, CHK-13, APP-04, APP-05, APP-16, APP-18 | `mobile/` core; backend app config (`getAppConfig`, `putAppConfig`, `getPublicAppConfig`, `searchAppDirectory`) and its staff screen; wallet pass port; session listing location filter | 1541 to 1559 | `p11c1`, 8503 / 5503 | batch 1 |
| **C2. Member app content** | APP-07, APP-08, APP-12, APP-13, APP-14, APP-17, APP-09, APP-10, APP-11, APP-15 | `mobile/` content screens; backend news, announcements, gallery, trial requests, feedback, favourites, contact lists, product events | 1561 to 1579 | `p11c2`, 8504 / 5504 | after C1 merges |

7 + 10 + 9 + 10 = 36 features. P0: A has SSP-01, SSP-05, SSP-14, REG-12; B has SSP-04, RNT-06, SSP-08, SSP-12,
SSP-18, REG-10; C1 has APP-01, APP-02, APP-06, APP-19, CHK-13.

C2 waits for C1: both live in `mobile/` and C2's tiles register in C1's tile catalogue. A and B both add to the
web portal shell (`PortalApp.tsx`, `shared.tsx`): additive lines only, nothing else changed; A owns the shell's
structure (routing, theme, menu), B owns the pages.

### A. Portal entry and accounts

- SSP-01: slug routing in the web app. `/f/:slug` is the tenant's public landing page (welcome text, locations,
  links into programs, rentals, plans and sign-in); `/f/:slug/*` serves the public and sign-in pages with
  `X-Tenant-Slug` set by `src/api/client.ts`. Host-based tenants keep working unchanged. Portal visibility
  (enabled, public listing on or off) comes from the existing portal settings. A signed-in request whose
  `X-Tenant-Slug` names a tenant other than the session's is a 404 (server side, in the existing tenant
  resolution; ask the coordinator before touching `core/db`).
- SSP-05: public self-registration (decision below): `POST /public/portal-signups` creates a pending sign-up and
  emails a verification link (token in the URL fragment, hashed at rest, single use, 24 hours);
  `POST /public/portal-signups/confirm` creates the client and the portal login and signs in. Same response
  whether or not the email is known; rate limited per IP and per email through the existing limiter.
- SSP-14: the portal reads `GET /public/branding` and applies the tenant's colours as CSS variables (contrast
  checked, falling back to the defaults when a colour fails AA); content and legal text from portal settings
  and `portal_terms`. Recorded acknowledgment: every portal sale request carries the `terms_version_id` it
  showed; `documents` records one acceptance row (client, version, sale kind, sale id, time) through an internal
  function, called once at the start of each portal sale path (memberships, packages, programs, rentals) before
  `secure_online_checkout`. A stale or missing version when terms are bound is a 409 `terms-changed`. A owns the
  function and its four one-line call sites; B does not move them.
- SSP-13: portal menu configuration per location (show, hide, order, rename the portal sections), stored in
  portal settings, applied by the shell; staff screen in the existing portal settings page.
- REG-12: guest checkout for program groups (decision below), through the same `programs/checkout.py` path as
  portal checkout and ending in `secure_online_checkout` with a new card only. Guest routes get their own
  schemas (never the staff or portal ones).
- SSP-07: a per-location (and optional per-group) post-registration redirect URL, `https` only, validated
  against an allow-list of the tenant's own domains plus any the tenant adds, applied after a successful
  checkout or sign-up. SSP-15: social links (fixed set of networks, `https` URLs) in portal settings, shown on
  the landing page and portal footer.

### B. Portal booking and buying

- SSP-04 and RNT-06: per-location portal rental defaults (which rental types are bookable online, lead time,
  maximum length, booking horizon); `confirmPortalRental` accepts a stored `payment_method_id` as well as a new
  token and is moved onto `secure_online_checkout` (today it pays outside it, against the security rule).
- SSP-08: book a session and buy a covering package in one flow: the portal offers the online-sellable package
  plans that cover the session (the existing online sale flags), buys through `portalBuyClientPackage` and
  books with the new `client_package_id`; if the booking fails after the sale, the package stays (it is the
  client's) and the screen says so. Session-level online sale flags as the reference describes them.
- SSP-12: a portal calendar view (week and month) over `listPortalSessionListings`, times in the location's zone,
  keyboard navigable, with the list view kept.
- CLS-08 and SSP-18: a virtual session has a meeting (created through `ports/video_meeting.py`, the fake adapter
  only; the real Zoom adapter is Phase 16's). The join link is never in public or listing responses; an
  enrolled client (or a guardian acting for one) gets it from a portal route from 15 minutes before the start to
  the end; staff see it on the session. Meeting fields are additive columns on the session row in a chip
  migration; holds stay with `scheduling.service`.
- MEM-09 and PKG-09: the portal buy flows accept a stored payment method as well as a new card.
- REG-10: deposits and instalment plans (decision below), configured per group in registration config, charged
  through `billing.service` and the existing autopay; `secure_online_checkout` with `must_pay_now=False` proves a
  chargeable method for the later instalments.
- FIT-05: a web portal Progress page (results and bests, as the app shows) and a revocable read-only share link
  for one client's progress (token in the URL fragment, hashed, expires, client or guardian creates and
  revokes), gated by the tenant's existing sharing setting.

### C1. Member app core

- Backend: build `getAppConfig`, `putAppConfig`, `getPublicAppConfig` and `searchAppDirectory` as specified in
  `docs/api/openapi-programs.yaml` (read the module that spec assigns them to; if none, `engagement`). The config
  holds the tenant theme (colours, logo through `platform.files`), the home layout JSON (APP-04: tiles, order,
  captions, styling, global design) and schedule presentation flags (APP-18, applied server side inside
  `listPortalSessionListings`). `searchAppDirectory` lists only tenants whose portal is enabled and publicly
  listed, by name prefix, rate limited, and returns slug, name, logo and city, nothing else.
- Staff screen for the app config with a live preview of the home layout (APP-04), WCAG AA.
- APP-05: a tile-type registry in the app (book, card, memberships, invoices, notifications, facility, plus the
  types C2 adds), driven by the config, with the current fixed layout as the fallback.
- APP-01 and APP-02: the app uses `getPublicAppConfig` for the live theme (keeping the last-known-good cache and
  bundled fallback) and `searchAppDirectory` for facility search.
- APP-16: `listPortalSessionListings` gains a `location_id` filter; the app gets a location switcher and shows
  times in each session's own location zone.
- APP-19: in-app buying of packages and memberships and new-card entry. Card data only in the processor's own
  component (Stripe's React Native element in Stripe test mode; the fake processor's token flow otherwise);
  `next_action` completed through `confirmPortalPayment`; one Idempotency-Key per intent.
- CHK-13 and APP-06: a wallet pass (decision below) behind a new `ports/wallet_pass.py` with a fake adapter that
  builds an unsigned pass; issue, list and revoke from the portal; check-in accepts the pass credential.
- Push stays on the existing notification port with the fake adapter (Phase 13 picks the provider).

### C2. Member app content (after C1)

- APP-07 News and info pages and APP-14 announcements, promotions and a gallery: staff-authored content with
  publish and expiry dates, per location or tenant-wide, images through `platform.files`; portal read routes;
  app screens and tiles. Plain text with links, no raw HTML.
- APP-08: department phone list on locations (an additive field on the location's public schema; ask the
  coordinator, it is a `platform` change). APP-09: services contact list (name, role, phone, email) per location.
- APP-12: trial pass request ("Try us"), public, rate limited, creates a lead for staff follow-up (an
  `engagement` task or inbox item; no client is created until staff convert it).
- APP-13: favourites (sessions, programs, staff) per client and a personalised schedule filtered by them. Not
  `putRegisterFavorites` (that is the POS register).
- APP-17: first-party product events (screen views and tile taps; no PII, client id only as a hashed per-tenant
  key, 90-day retention through the existing retention job pattern), aggregated counts on a staff screen. No
  third-party analytics SDK.
- APP-10 in-app feedback (to a staff inbox), APP-11 tell a friend (share sheet with the tenant's landing URL from
  chip A), APP-15 share sheet and add-to-calendar for a booking.

## Decisions taken for the owner (open questions in `remaining-work.md` section 5)

Written here so chips do not guess; each chip copies its own into the module README's assumptions.

- **Q5 deposits and instalments (B):** yes to both, per group. A deposit is charged at checkout as its own line;
  the balance falls due on a group date. An instalment plan splits the balance into N charges at a fixed
  interval, each posted through `billing.service` and collected by the existing autopay on the stored method;
  a plan needs a chargeable method on file. Staff can still invoice by hand.
- **Q6 guest checkout (A):** yes, per group, **off by default**. A guest gives name, email and participant details
  and pays in full by new card only (no stored methods, no account credit, no instalments). A new client is
  always created (never matched by email: matching would let anyone attach purchases to another person's
  record); staff merge duplicates with the existing merge. Documents and receipts go to the email with a
  fragment-token link.
- **Q7 public sign-up (A):** per location, **off by default**. When on, anyone can create a portal account after
  verifying their email; the same response whether or not the address is known. A new client is created;
  staff merge duplicates. Staff invites keep working.
- **Wallet pass (C1):** signed Apple Wallet and Google Wallet passes need the tenant's or platform's issuer
  accounts, so CHK-13 ships behind a port with a fake adapter and stays **partial** until those exist. A wallet
  pass cannot rotate, so it carries its own long-lived, revocable credential kind, revoked with the card or when
  the client loses access; the rotating app QR stays the primary mobile check-in.
- **Virtual sessions (B):** fake meeting adapter only; join links only to enrolled clients in the window above.
- **Push (C1, C2):** fake adapter only; Phase 13 picks the provider.
- **Analytics (C2):** first-party, aggregated, no PII, no third-party SDK.

## Lanes: setup for every chip

From the chip's worktree root, with `X` its lane (`a`, `b`, `c1`, `c2`) and `N` its port digit (1 to 4):

```bash
cp "/Users/ramc/Documents/Creative Projects/Facility Software/.env" .env
sed -i '' -e '/^FH_PAYMENTS_PROVIDER/d' -e '/^FH_STRIPE_/d' -e '/^FH_DB_NAME=/d' -e '/^FH_TEST_DB_NAME=/d' -e '/^FH_API_PORT=/d' -e '/^FH_WEB_PORT=/d' .env
printf 'FH_DB_NAME=facilityhub_p11X\nFH_TEST_DB_NAME=facilityhub_p11X_test\nFH_API_PORT=850N\nFH_WEB_PORT=550N\n' >> .env
```

Then this guard, before `make lane-db` and before every `make test`, `make seed` or Playwright run. It refuses
when either database still names the main databases or is missing, or when a payment-provider line survived:

```bash
grep -q '^FH_DB_NAME=facilityhub_p11' .env && grep -q '^FH_TEST_DB_NAME=facilityhub_p11.*_test$' .env \
  && ! grep -Eq '^FH_(TEST_)?DB_NAME=facilityhub(_test)?$|^FH_PAYMENTS_PROVIDER|^FH_STRIPE_' .env \
  || { echo 'refusing: lane .env names the main databases or a payment provider'; exit 1; }
```

Then `make lane-db` and `make seed`. Never `make up`, `down` or `reset`; never `make worker` or `relay` (Redis is
shared). The fake processor everywhere; no Stripe keys in a lane. Mobile chips point `EXPO_PUBLIC_API_ORIGIN` at
their lane API.

**Migrations.** The phase branch head is `1331` (`uv run alembic heads`). A chip's first revision has
`down_revision = "1331"`, numbered from its own block; later revisions chain inside the block. At merge the
coordinator re-points each chip's first revision onto the phase branch's head, and once more onto `main`'s head
at hand-back (Phase 14's `14xx` or Phase 12's `16xx` may land first).

## Shared files

| File | Who edits |
|---|---|
| `backend/conftest.py` `populate()`, `migrations/env.py`, `bootstrap.py`, `main.py`, `seeds/demo.py`, `test_isolation.py` `_BODIES`, `test_rbac.py` list, `web/src/app/App.tsx`, `nav.ts`, `web/src/features/portal/{PortalApp,shared}.tsx` | each chip adds its own lines next to the existing ones and changes nothing else (A owns the portal shell's structure) |
| `backend/openapi.json`, `web/src/api/schema.d.ts`, `mobile/src/api/schema.d.ts` | chips regenerate for their own work; the coordinator regenerates after each merge |
| Module `README.md`s, the chip's rows in `docs/status/*.md` and `docs/status/README.md` | the chip |
| `CHANGELOG.md` | each chip adds its own lines under `Unreleased` |
| `CLAUDE.md` build-status table, this file | coordinator only |
| `core/*`, `infra/*`, `ports/storage.py`, `platform/files.py` | Phase 8 rules: ask the coordinator |
| `programs` outside `checkout.py` and registration config; `rentals` locker and plan code; `scheduling` direct links and shared bookings | Phase 14 is changing these now: additive edits only, named in the merge note |

## Done, per chip

- Tests on the real PostgreSQL as `fh_app`; every new table in `populate()`; isolation, location-scope,
  portal-schema and security suites green without allow-list edits; 80% domain coverage holds.
- Both permission gates, audit and events on every new command; new keys in `permissions.py` and the RBAC matrix.
  Portal and public routes have their own schemas; every portal sale ends in `secure_online_checkout`.
- A Playwright spec with an axe scan for every new web screen, signing in through the shared helper; colours
  from the CSS variables. Mobile: tests for every new screen and adapter mapping, `make mobile-check mobile-test`,
  and a simulator walk-through against the lane API with screenshots in `docs/status/mobile-screens/`.
- The gate above green in the chip's lane; Conventional Commits, no attribution trailers, nothing pushed.
- Module README, status rows and `CHANGELOG.md` updated; assumptions written down, not guessed. A hand-over note
  `p11-chip-<x>.md` in the shared notes folder with the head commit, migrations, gate results and known gaps.

## Progress

| Date | Chip | Event | Commit |
|---|---|---|---|
| 2026-11-12 | plan | written | aa41743 |
| 2026-11-12 | A, B, C1 | proposed as session cards (batch 1); C2 waits for C1 | |
