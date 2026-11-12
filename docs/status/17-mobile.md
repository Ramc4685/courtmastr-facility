# Module 17, member mobile app: status

Date: 2026-11-11. Branch `claude/mobile-api-f2c2b5`. Code: `mobile/` (Expo SDK 58, React Native 0.88, strict
TypeScript, Expo Router). How to run it: `mobile/README.md`. Screenshots: `docs/status/mobile-screens/`
(demo adapter, 01 to 16) and `docs/status/mobile-screens/api/` (real API, 01 to 10).

## What is real and what is not available yet

`EXPO_PUBLIC_PORTAL_ADAPTER` now defaults to `api`, and every member screen runs against the real
member-portal API through `src/api/client.ts`. The adapter maps these operations: `listPortalActableClients`
(household; acting-for ids come from the server), `listPortalSessionListings`, `listPortalEnrollments`,
`createPortalEnrollment` (with `client_package_id` when a package covers the session), `cancelPortalEnrollment`,
`listPortalClientPackages`, `listPortalMembershipContracts`, `issuePortalAppCard` and `listPortalAppCards`,
`listPortalAssessmentBests` (new Progress screen), `listPortalInvoices`, `listPortalPaymentMethods`,
`payPortalInvoices`, `listPortalInbox`, `markPortalInboxItemRead` and `registerPortalDevice`. The check-in card
derives the server's `fhq.<credential>.<step>.<mac>` code on the device from the seed returned once by
`issuePortalAppCard` (HMAC-SHA256, 30-second steps, `src/lib/card.ts`).

**Not available yet** (no endpoint; the app says so and does not guess): facility search by name
(`searchAppDirectory`; the facility screen asks for the code) and the live tenant theme (`getPublicAppConfig`;
the bundled theme is used). `EXPO_PUBLIC_PORTAL_ADAPTER=demo` keeps the in-memory demo adapter for UI work,
labelled **DEMO DATA** on every screen.

The tenant is reached through `EXPO_PUBLIC_API_ORIGIN` plus `X-Tenant-Slug` (iOS cannot resolve
`courtside-demo.localhost`); signed-in calls take the tenant from the token. Production uses
`https://<slug>.<platform domain>`.

Status key: **done** means it works against the real API on this branch. **partial** means part of the scope is
missing or waits on the named operation(s). **not built** means there is no
app code.

## Parity table (APP rows of `docs/discovery/parity-matrix.md`)

| ID | Feature | Priority | Status | Location | Tests | Notes |
|---|---|---|---|---|---|---|
| APP-01 | Member app core (shared multi-tenant app) | P0 | partial | `src/app/*`, `src/lib/{app-state,session,auth,household,booking}.ts*`, `src/adapters/*` | `auth.test.ts`, `household.test.tsx`, `adapters.test.ts` | Real API: facility entry by code and deep link (`/t/<slug>`), password and magic-link sign-in, refresh, sign-out, biometric unlock, household switch (`listPortalActableClients`), schedule (`listPortalSessionListings`; the verdict comes from the server reason), booking with or without a package, cancel and my bookings (`listPortalEnrollments`). Not available yet: facility search by name (`searchAppDirectory`). Limits: the listing carries no resource or trainer name; my bookings shows enrolments inside the 60-day listing window only. |
| APP-02 | White-label branded app (per-tenant theme) | P0 | partial | `src/lib/theme.ts`, `src/lib/tenant.ts`, `app.config.ts`, `variants/*.json` | `adapters.test.ts` (AA contrast on any brand colour), `card.test.tsx` (dark scheme) | Runtime theme with light/dark, contrast-derived on-colours, last-known-good cache and a bundled fallback; build-time variants via `APP_VARIANT`. Not available yet: the live tenant theme (`getPublicAppConfig` has no endpoint), so the api adapter uses the bundled theme. Gap: a pinned tenant is read from JS `extra`, not natively from Info.plist as ADR 0006 describes. |
| APP-03 | App-store publishing and launch service | v2-adapter | partial | `eas.json`, `app.config.ts`, `variants/`, `mobile/README.md` (Builds) | none | EAS profiles (development, preview/staging, production) and the per-tenant variant approach are in place and documented. No store submission, by scope. Tenant store-metadata fields are a backend item and are not built. |
| APP-04 | Home-screen designer | P1 | not built | n/a | n/a | Home is a fixed layout. Needs the layout JSON in `getAppConfig`/`putAppConfig` and a staff editor. |
| APP-05 | Home-screen tile catalogue | P1 | partial | `src/app/(tabs)/home.tsx` | none | The matrix's MVP shape: one fixed default layout with six tiles (book, card, memberships, invoices, notifications, facility). No tile-type registry, and nothing is driven by `getPublicAppConfig`. |
| APP-06 | Digital membership card | P0 | done | `src/lib/card.ts`, `src/ui/{MemberCard,CardPager,Barcode}.tsx`, `src/app/(tabs)/card.tsx` | `card.test.tsx` (rolling-code vector, states, offline load, Code 128) | `issuePortalAppCard` returns a seed once; it stays in SecureStore and the device derives `fhq.<credential>.<step>.<mac>` (HMAC-SHA256, 30 s steps, re-derived every 5 s), so the card works offline. Verified: the code shown in the simulator was decoded and `POST /check-ins/evaluate` returned `would_grant: true`; a tampered code was refused. Wallet passes not built. |
| APP-07 | In-app News & Info CMS | P1 | not built | n/a | n/a | No API planned on this branch. |
| APP-08 | Contact & hours page | P1 | partial | `src/app/facility.tsx` | none | Real: every location with city, IANA zone and weekly hours from `GET /public/locations`. Department phone list not built (no field in the public location schema yet). |
| APP-09 | Services contact list | P2 | not built | n/a | n/a | |
| APP-10 | In-app feedback | P2 | not built | n/a | n/a | |
| APP-11 | Tell a friend | P2 | not built | n/a | n/a | |
| APP-12 | Trial pass request ("Try us") | P1 | not built | n/a | n/a | |
| APP-13 | Favorites and personalised schedule | P1 | not built | n/a | n/a | `putRegisterFavorites` exists in the specs; the app has no favorites UI. |
| APP-14 | Announcements, promotions, gallery | P1 | not built | n/a | n/a | The inbox (below) is not this feature. |
| APP-15 | Social and device integrations | P2 | not built | n/a | n/a | No share sheet or add-to-calendar yet. |
| APP-16 | Multi-location apps | P1 | partial | `src/app/facility.tsx`, `src/lib/hooks.ts` (`useZone`) | none | All locations are listed and schedule times use the home location's zone, so a West-location session shows in the home zone. No location switcher filtering the schedule yet. |
| APP-17 | App engagement analytics | P1 | not built | n/a | n/a | No product-event capture. |
| APP-18 | App schedule presentation controls | P1 | not built | n/a | n/a | These are server-side policy flags applied inside `listPortalSessionListings`. The app shows whatever that returns (full/eligible badges) and has no policy logic of its own. |
| APP-19 | In-app purchase and payment | P0 | partial | `src/app/invoices.tsx`, `src/app/memberships.tsx` | `adapters.test.ts` (payment-method mapping; body carries only a payment-method id, plus the Idempotency-Key) | Real API: open invoices (`listPortalInvoices`) paid with a saved card (`listPortalPaymentMethods`, `payPortalInvoices`); verified paying invoice #3 in the simulator. A returned `next_action` is shown but `confirmPortalPayment` is not wired. Not built: new-card entry (`createPortalSetupIntent`) and buying memberships or packages. Invoice lines are not in the list response, so none are shown. |

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
| Push plumbing (permission after first booking, Expo token, device registration, tap opens inbox) | `src/lib/push.ts`, `src/lib/booking.ts` | `adapters.test.ts` (device mapping) | partial: `registerPortalDevice` is mapped; needs a physical device and an EAS `projectId` (not verifiable in the simulator or Expo Go) |
| Progress (assessment results: latest and best per field) | `src/app/progress.tsx` | `adapters.test.ts` | done: `listPortalAssessmentBests` |
| Biometric unlock | `src/lib/biometric.ts`, `src/app/unlock.tsx` | none | done in code; the simulator has no enrolled biometrics, so it was not exercised end to end |

## Verification

- `make mobile-check`: `tsc --noEmit` and ESLint, clean.
- `make mobile-test`: 5 suites, 42 tests, all passing (auth, card including the rolling-code vector, household
  switching, adapters against URL-routed fetch mocks, theme contrast).
- iOS Simulator (iPhone 18 Pro, Expo Go) against the lane API on :8230 (migrated and seeded), adapter `api`.
  Signed in as `member@courtside-demo.example.com`, then walked home, household (Morgan, Mia, Riley), schedule,
  booking a private lesson with the ten-lesson package, my bookings, the card (decoded and evaluated by the
  front desk endpoint), memberships, progress, invoices, paying invoice #3 and the inbox with mark-read.
  Screenshots `mobile-screens/api/01-home.png` to `10-inbox.png`.

## Known gaps later work must not assume away

- Not available yet: `searchAppDirectory` and `getPublicAppConfig` (no endpoints).
- The fake payment provider keeps stored methods in process memory, so a method attached by `make seed` is
  unknown to a separately started API and paying with it fails `processor_error`. Attach a fresh `tok_card_ok`
  method through `POST /portal/payment-methods` against the running API before testing payments.
- The demo inbox shows the seeded announcement twice after a reseed (data, not the app).
- The pinned tenant comes from JS config, not native Info.plist (APP-02 note).
- Push and biometrics need a development build on a device.
- No in-app buying and no new-card entry (APP-19).
