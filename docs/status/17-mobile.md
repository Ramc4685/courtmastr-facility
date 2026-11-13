# Module 17, member mobile app: status

Date: 2026-11-13. Branch `claude/phase11-portal-member-app-d22713` (Phase 11 chips C1 and C2). Code: `mobile/` (Expo SDK 58,
React Native 0.88, strict TypeScript, Expo Router). How to run it: `mobile/README.md`. Screenshots: `docs/status/mobile-screens/`
(demo adapter, 01 to 16) and `docs/status/mobile-screens/api/` (real API, 01 to 10, taken before C1 and C2).

## What is real and what is not available yet

`EXPO_PUBLIC_PORTAL_ADAPTER` now defaults to `api`, and every member screen runs against the real
member-portal API through `src/api/client.ts`. The adapter maps these operations: `listPortalActableClients`
(household; acting-for ids come from the server), `listPortalSessionListings` (with the `location_id` filter),
`listPortalEnrollments`, `createPortalEnrollment` (with `client_package_id` when a package covers the session),
`cancelPortalEnrollment`, `listPortalClientPackages`, `listPortalMembershipContracts`, `issuePortalAppCard` and
`listPortalAppCards`, `listPortalAssessmentBests`, `listPortalInvoices`, `listPortalPaymentMethods`,
`createPortalSetupIntent` with `confirmPortalPayment` for a new card, `payPortalInvoices`, the package and membership
purchase routes, `listPortalInbox`, `markPortalInboxItemRead`, `registerPortalDevice`, the wallet pass routes
(`/portal/wallet-passes`), and the C2 routes for content, contacts, feedback, favourites, the personal schedule and
usage counts. The public config comes from `GET /public/app-config` (the live theme and home layout) and facility
search from `GET /public/app-directory`. The check-in card derives the server's `fhq.<credential>.<step>.<mac>` code
on the device from the seed returned once by `issuePortalAppCard` (HMAC-SHA256, 30-second steps, `src/lib/card.ts`).

**Not available yet** (the app says so and does not guess): add-to-calendar (`expo-calendar` is not installed);
instructor favourites (listings carry no instructor); images in news, info pages and the gallery (stored through
`platform.files`, not yet shown in the app); signed Apple and Google wallet passes (the wallet adapter is fake until
issuer certificates exist, so CHK-13 stays partial); push delivery (fake adapter only, Phase 13 picks the provider).
`EXPO_PUBLIC_PORTAL_ADAPTER=demo` keeps the in-memory demo adapter for UI work, labelled **DEMO DATA** on every screen.

The tenant is reached through `EXPO_PUBLIC_API_ORIGIN` plus `X-Tenant-Slug` (iOS cannot resolve
`courtside-demo.localhost`); signed-in calls take the tenant from the token. Production uses
`https://<slug>.<platform domain>`.

Status key: **done** means it works against the real API on this branch. **partial** means part of the scope is
missing or waits on the named operation(s). **not built** means there is no
app code.

## Parity table (APP rows of `docs/discovery/parity-matrix.md`)

| ID | Feature | Priority | Status | Location | Tests | Notes |
|---|---|---|---|---|---|---|
| APP-01 | Member app core (shared multi-tenant app) | P0 | done | `src/app/*`, `src/lib/{app-state,session,auth,household,booking}.ts*`, `src/adapters/*` | `auth.test.ts`, `household.test.tsx`, `adapters.test.ts` | Real API: facility entry by code, deep link (`/t/<slug>`) or search by name (`searchAppDirectory`, public, rate limited, listed portals only); password and magic-link sign-in, refresh, sign-out, biometric unlock, household switch (`listPortalActableClients`), schedule (`listPortalSessionListings`; the verdict comes from the server reason), booking with or without a package, cancel and my bookings (`listPortalEnrollments`). Limits: the listing carries no resource or trainer name; my bookings shows enrolments inside the 60-day listing window only. |
| APP-02 | White-label branded app (per-tenant theme) | P0 | done | `src/lib/theme.ts`, `src/lib/tenant.ts`, `app.config.ts`, `variants/*.json` | `adapters.test.ts` (AA contrast on any brand colour), `card.test.tsx` (dark scheme), `backend/app/modules/engagement/tests/test_app_config.py` | The live theme comes from `GET /public/app-config`, with light and dark schemes, contrast-derived on-colours, a last-known-good cache and the bundled theme as fallback; build-time variants via `APP_VARIANT`. Gap: a pinned tenant is read from JS `extra`, not natively from Info.plist as ADR 0006 describes. |
| APP-03 | App-store publishing and launch service | v2-adapter | partial | `eas.json`, `app.config.ts`, `variants/`, `mobile/README.md` (Builds) | none | EAS profiles (development, preview/staging, production) and the per-tenant variant approach are in place and documented. No store submission, by scope. Tenant store-metadata fields are a backend item and are not built. |
| APP-04 | Home-screen designer | P1 | done | staff `web/src/features/engagement/AppConfigPage.tsx`; `backend/app/modules/engagement/domain/app_config.py`; `GET/PUT /app-config` | `test_app_config.py`, `web/e2e/app-config.spec.ts` | Staff editor for the home layout (tiles, order, captions, styling, global design) with a live preview, WCAG AA. Stored as JSON in the tenant's app config and read by the app through `getPublicAppConfig`. |
| APP-05 | Home-screen tile catalogue | P1 | done | `src/lib/tiles.tsx`, `src/app/(tabs)/home.tsx` | `test_app_config.py` | A tile-type registry of eleven types: book, card, memberships, invoices, notifications, facility, news, contacts, favorites, feedback, try_us. The layout comes from the config, with the fixed six-tile layout as fallback. The type list lives in two places (`domain/app_config.py` and `tiles.tsx`); a new type goes in both. |
| APP-06 | Digital membership card | P0 | done | `src/lib/card.ts`, `src/ui/{MemberCard,CardPager,Barcode}.tsx`, `src/app/(tabs)/card.tsx`, `src/app/wallet.tsx` | `card.test.tsx` (rolling-code vector, states, offline load, Code 128) | `issuePortalAppCard` returns a seed once; it stays in SecureStore and the device derives `fhq.<credential>.<step>.<mac>` (HMAC-SHA256, 30 s steps, re-derived every 5 s), so the card works offline. Verified: the code shown in the simulator was decoded and `POST /check-ins/evaluate` returned `would_grant: true`; a tampered code was refused. The wallet pass screen shows a separate long-lived pass (CHK-13, fake adapter, see that row). |
| APP-07 | In-app News & Info CMS | P1 | done | `src/app/news.tsx`; staff `web/src/features/engagement/MemberContentPage.tsx`; `engagement/content.py` | `test_member_content.py`, `memberContent.test.tsx`, `e2e/engagement-member-content.spec.ts` | News and info pages with a publish window, for one location or all. Plain text and https links only, no HTML. Images are stored through `platform.files` but the app does not show them yet. |
| APP-08 | Contact & hours page | P1 | done | `src/app/facility.tsx`, `src/app/contacts.tsx` | `test_member_content.py` | Every location with city, IANA zone and weekly hours from `GET /public/locations`, and department phone lines from `GET /public/location-contacts` (shown while the location's portal is open). |
| APP-09 | Services contact list | P2 | done | `src/app/contacts.tsx` | `test_member_content.py` | Services contacts (name, role, phone, email) per location, from the same contact records as APP-08. |
| APP-10 | In-app feedback | P2 | done | `src/app/feedback.tsx` | `test_member_content.py` | Feedback with an optional 1 to 5 rating goes to the staff inbox (`POST /portal/feedback`); staff read it at `/app-inquiries`. |
| APP-11 | Tell a friend | P2 | partial | share sheet in the app | none | Shares the tenant's landing URL from the portal settings. The action is hidden when no web origin is configured, so the app never shares a dead link. |
| APP-12 | Trial pass request ("Try us") | P1 | done | `src/app/try-us.tsx` | `try-us.test.tsx` | `POST /public/trial-requests`, rate limited per IP and per address. Creates an inquiry for staff follow-up, never a client; answers 202 whether or not anything was stored. |
| APP-13 | Favorites and personalised schedule | P1 | partial | `src/app/favorites.tsx` | `test_member_favorites_usage.py` | Favourites for reservation types and program groups (`/portal/favorites`) and a personal schedule of the sessions they cover (`/portal/favorites/schedule`). Missing: instructor favourites (listings carry no instructor); no favourite toggle in the app yet, because no listing shows groups or types; the schedule has no slot offers. |
| APP-14 | Announcements, promotions, gallery | P1 | done | `src/app/news.tsx`; staff `MemberContentPage.tsx` | `test_member_content.py`, `memberContent.test.tsx` | Announcements, promotions and gallery entries that staff publish with dates; the app lists them. The staff screen is `MemberContentPage.tsx`. No images in the app yet. The inbox (below) is not this feature. |
| APP-15 | Social and device integrations | P2 | partial | booking screens (share) | none | Sharing a booking is built. Add-to-calendar is not (`expo-calendar` is not installed). |
| APP-16 | Multi-location apps | P1 | done | `src/app/facility.tsx`, `src/app/(tabs)/schedule.tsx`, `src/lib/hooks.ts` (`useZone`) | none | A location switcher on the schedule filters the listing (`location_id`), and each session shows in its own location's zone. |
| APP-17 | App engagement analytics | P1 | partial | `src/lib/usage.ts` | `usage.test.ts`, `test_member_favorites_usage.py` | Anonymous daily counts of screen views and actions (`POST /portal/app-usage`), read by staff at `/app-usage` on `MemberContentPage.tsx`. No install, open or push-open tracking; no third-party SDK. |
| APP-18 | App schedule presentation controls | P1 | done | `src/app/(tabs)/schedule.tsx` | `test_app_config.py` | Server-side flags (spots left, full sessions, days ahead) set in the app config and applied inside `listPortalSessionListings`. The app shows what the server returns and has no policy logic of its own. |
| APP-19 | In-app purchase and payment | P0 | done | `src/app/buy.tsx`, `src/app/invoices.tsx`, `src/app/memberships.tsx` | `adapters.test.ts` (payment-method mapping; body carries only a payment-method id, plus the Idempotency-Key) | Pays open invoices and buys packages and memberships with a saved card or a new one. New-card entry (`createPortalSetupIntent`) keeps card data in the processor's own element (Stripe React Native in Stripe test mode; the fake processor's token flow otherwise). A returned `next_action` is completed through `confirmPortalPayment`. One Idempotency-Key per intent. |

**CHK-13** (app member cards, module 10) is partial: the rotating card works in the app (APP-06); the wallet pass
route, the app screen and the revoke path exist on a fake adapter that builds an unsigned pass.

## Also built (supports the rows above, no APP ID of its own)

| Item | Location | Tests | Status / waits on |
|---|---|---|---|
| Typed API client from `backend/openapi.json` (`pnpm gen:api`, `make mobile-api`), problem+json errors, 401 refresh-and-retry | `src/api/*` | `auth.test.ts`, `adapters.test.ts` | done |
| Secure token storage (SecureStore only; the persisted query cache holds no tokens) | `src/lib/session.ts` | `auth.test.ts` | done |
| Magic-link token from the URL fragment only, used once, route replaced; `?token=` refused; paste field. A link this device did not request in the last 20 minutes needs explicit confirmation (login CSRF) | `src/lib/auth.ts`, `src/app/auth/magic-link.tsx`, `src/lib/app-state.tsx` | `auth.test.ts`, `app-state.test.tsx` | done (security-baseline 17.2) |
| Biometric lock is re-applied on every tenant activation, so a `t/<slug>` deep link cannot skip unlock | `src/lib/app-state.tsx` | `app-state.test.tsx` | done |
| Offline-aware data: TanStack Query persisted to AsyncStorage, NetInfo and AppState managers, offline banner | `src/lib/query.ts`, `src/ui/kit.tsx` | indirectly | done |
| Notifications inbox with server-synced read state | `src/app/inbox.tsx` | `adapters.test.ts` | done: `listPortalInbox`, `markPortalInboxItemRead`, verified in the simulator |
| Memberships and packages view | `src/app/memberships.tsx` | `adapters.test.ts` | done: `listPortalMembershipContracts`, `listPortalClientPackages` |
| Push plumbing (permission after first booking, Expo token, device registration, tap opens inbox) | `src/lib/push.ts`, `src/lib/booking.ts` | `adapters.test.ts` (device mapping) | partial: `registerPortalDevice` is mapped; needs a physical device and an EAS `projectId` (not verifiable in the simulator or Expo Go); the server side is the fake push adapter (Phase 13) |
| Progress (assessment results: latest and best per field) | `src/app/progress.tsx` | `adapters.test.ts` | done: `listPortalAssessmentBests` |
| Biometric unlock | `src/lib/biometric.ts`, `src/app/unlock.tsx` | none | done in code; the simulator has no enrolled biometrics, so it was not exercised end to end |

## Verification

- Last recorded run, before C1 and C2 landed: `make mobile-check` (`tsc --noEmit` and ESLint) clean, and
  `make mobile-test` with 5 suites and 42 tests passing (auth, card including the rolling-code vector, household
  switching, adapters against URL-routed fetch mocks, theme contrast).
- The C1 and C2 additions (`try-us`, `usage` and the new adapter mappings) were not re-run in this docs pass; their gate
  result belongs in the chip hand-over note.
- iOS Simulator (iPhone 18 Pro, Expo Go) against the lane API on :8230 (migrated and seeded), adapter `api`, before C1
  and C2. Signed in as `member@courtside-demo.example.com`, then walked home, household (Morgan, Mia, Riley), schedule,
  booking a private lesson with the ten-lesson package, my bookings, the card (decoded and evaluated by the
  front desk endpoint), memberships, progress, invoices, paying invoice #3 and the inbox with mark-read.
  Screenshots `mobile-screens/api/01-home.png` to `10-inbox.png`.

## Known gaps later work must not assume away

- Not available yet: add-to-calendar, instructor favourites, images in news, info pages and the gallery, signed wallet
  passes (issuer certificates), and push delivery (Phase 13 provider).
- The fake payment provider keeps stored methods in process memory, so a method attached by `make seed` is
  unknown to a separately started API and paying with it fails `processor_error`. Attach a fresh `tok_card_ok`
  method through `POST /portal/payment-methods` against the running API before testing payments.
- The demo inbox shows the seeded announcement twice after a reseed (data, not the app).
- The pinned tenant comes from JS config, not native Info.plist (APP-02 note).
- Push and biometrics need a development build on a device.
- Card entry uses the fake processor's token flow unless Stripe test mode is configured (APP-19).
- Portal plan lists are not filtered by location (plans have no location link): the app offers every package and
  membership plan the client may buy, whichever location is picked (APP-19).
