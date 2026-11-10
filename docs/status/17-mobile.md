# Module 17, member mobile app: status

Date: 2026-11-10. Branch `claude/mobile-app-0775de`. Code: `mobile/` (Expo SDK 58, React Native 0.88, strict
TypeScript, Expo Router). How to run it: `mobile/README.md`. Screenshots: `docs/status/mobile-screens/`.

## What is real and what is demo

On this branch the platform core is the only backend. The app therefore calls the **real API** for facility
lookup (`GET /public/locations` with the tenant header), password sign-in, magic-link request and consume,
session refresh and rotation, sign-out, `GET /me`, signed-in devices (`GET`/`DELETE /auth/sessions`) and
facility hours. Everything else goes through one typed adapter (`mobile/src/adapters/`). `api.ts` targets the
planned operations in `docs/api/openapi-*.yaml`. `demo.ts` is an in-memory stand-in. The switch is
`EXPO_PUBLIC_PORTAL_ADAPTER` (default `demo`). Each screen fed by the demo adapter carries a **DEMO DATA**
banner that names the API it waits on, and demo card tokens are signed `DEMO`. **Every row below marked
"partial" works end to end against the demo adapter only.** None of them has run against a real portal
endpoint, because those endpoints do not exist yet.

Status key: **done** means it works against the real API on this branch. **partial** means the app side is
built but waits on the named operation(s), or part of the scope is missing. **not built** means there is no
app code.

## Parity table (APP rows of `docs/discovery/parity-matrix.md`)

| ID | Feature | Priority | Status | Location | Tests | Notes |
|---|---|---|---|---|---|---|
| APP-01 | Member app core (shared multi-tenant app) | P0 | partial | `src/app/*`, `src/lib/{app-state,session,auth,household,booking}.ts*`, `src/adapters/*` | `auth.test.ts` (11), `household.test.tsx` (3), `adapters.test.ts` | Real: shared app, facility entry by code and deep link (`/t/<slug>`, checked against `GET /public/locations`), sign-in with password and magic link, refresh, sign-out, biometric unlock, household switch without sign-out. Waits on `searchAppDirectory` (name/city search), `portalListActableClients` (household), `listPortalSessionListings`, `createPortalEnrollment`, `cancelPortalEnrollment`, `listPortalEnrollments` (schedule, booking, my bookings). The eligibility verdict is rendered from `listPortalSessionListings`; the app computes none. |
| APP-02 | White-label branded app (per-tenant theme) | P0 | partial | `src/lib/theme.ts`, `src/lib/tenant.ts`, `app.config.ts`, `variants/*.json` | `adapters.test.ts` (AA contrast on any brand colour), `card.test.tsx` (dark scheme) | Runtime theme with light/dark, contrast-derived on-colours, last-known-good cache (`fh.brand.<slug>`) and a bundled fallback; build-time variants via `APP_VARIANT`. Waits on `getPublicAppConfig` for the live tenant theme: today Courtside and Riverside use demo colours (labelled as such on Facility info) and other tenants the bundled theme. Gap: a pinned tenant is read from JS `extra`, not natively from Info.plist as ADR 0006 describes. |
| APP-03 | App-store publishing and launch service | v2-adapter | partial | `eas.json`, `app.config.ts`, `variants/`, `mobile/README.md` (Builds) | none | EAS profiles (development, preview/staging, production) and the per-tenant variant approach are in place and documented. No store submission, by scope. Tenant store-metadata fields are a backend item and are not built. |
| APP-04 | Home-screen designer | P1 | not built | n/a | n/a | Home is a fixed layout. Needs the layout JSON in `getAppConfig`/`putAppConfig` and a staff editor. |
| APP-05 | Home-screen tile catalogue | P1 | partial | `src/app/(tabs)/home.tsx` | none | The matrix's MVP shape: one fixed default layout with six tiles (book, card, memberships, invoices, notifications, facility). No tile-type registry, and nothing is driven by `getPublicAppConfig`. |
| APP-06 | Digital membership card | P0 | partial | `src/lib/card.ts`, `src/ui/{MemberCard,CardPager,Barcode}.tsx`, `src/app/(tabs)/card.tsx` | `card.test.tsx` (token decode, status, sync, offline load, expired/offline/demo states, Code 128) | `FH1.<payload>.<sig>` QR with a 72 h lifetime, refreshed at half-life. Cards for every household member are kept on the device in SecureStore and work offline. Clear states: ready, refresh soon / refresh when online, refresh needed (barcode of the member number instead), offline. Reachable while the app is locked. Waits on `issueAppCard` and `listAppCards` (real signed tokens; demo tokens say they will not check you in). Wallet passes not built. |
| APP-07 | In-app News & Info CMS | P1 | not built | n/a | n/a | No API planned on this branch. |
| APP-08 | Contact & hours page | P1 | partial | `src/app/facility.tsx` | none | Real: every location with city, IANA zone and weekly hours from `GET /public/locations`. Department phone list not built (no field in the public location schema yet). |
| APP-09 | Services contact list | P2 | not built | n/a | n/a | |
| APP-10 | In-app feedback | P2 | not built | n/a | n/a | |
| APP-11 | Tell a friend | P2 | not built | n/a | n/a | |
| APP-12 | Trial pass request ("Try us") | P1 | not built | n/a | n/a | |
| APP-13 | Favorites and personalised schedule | P1 | not built | n/a | n/a | `putRegisterFavorites` exists in the specs; the app has no favorites UI. |
| APP-14 | Announcements, promotions, gallery | P1 | not built | n/a | n/a | The inbox (below) is not this feature. |
| APP-15 | Social and device integrations | P2 | not built | n/a | n/a | No share sheet or add-to-calendar yet. |
| APP-16 | Multi-location apps | P1 | partial | `src/app/facility.tsx`, `src/lib/hooks.ts` (`useZone`) | none | All locations are listed, and schedule times are shown in the home location's zone. There is no location switcher filtering the schedule. That waits on `listPortalSessionListings` taking a location filter. |
| APP-17 | App engagement analytics | P1 | not built | n/a | n/a | No product-event capture. |
| APP-18 | App schedule presentation controls | P1 | not built | n/a | n/a | These are server-side policy flags applied inside `listPortalSessionListings`. The app shows whatever that returns (full/eligible badges) and has no policy logic of its own. |
| APP-19 | In-app purchase and payment | P0 | partial | `src/app/invoices.tsx`, `src/app/memberships.tsx` | `adapters.test.ts` (body carries only a payment-method id, plus the Idempotency-Key) | Pay open invoices with the saved method: one Idempotency-Key per intent; a returned `next_action` is shown but completing it (`confirmPortalPayment`) is not built. Waits on `listPortalInvoices`, `listPortalPaymentMethods`, `payPortalInvoices`. Not built: the Stripe PaymentSheet (`createPortalSetupIntent`) for new cards, and buying memberships/packages (`portalBuyMembershipContract`, `portalBuyClientPackage`). |

## Also built (supports the rows above, no APP ID of its own)

| Item | Location | Tests | Status / waits on |
|---|---|---|---|
| Typed API client from `backend/openapi.json` (`pnpm gen:api`, `make mobile-api`), problem+json errors, 401 refresh-and-retry | `src/api/*` | `auth.test.ts`, `adapters.test.ts` | done |
| Secure token storage (SecureStore only; the persisted query cache holds no tokens) | `src/lib/session.ts` | `auth.test.ts` | done |
| Magic-link token from the URL fragment only, used once, route replaced; `?token=` refused; paste field. A link this device did not request in the last 20 minutes needs explicit confirmation (login CSRF) | `src/lib/auth.ts`, `src/app/auth/magic-link.tsx`, `src/lib/app-state.tsx` | `auth.test.ts`, `app-state.test.tsx` | done (security-baseline 17.2) |
| Biometric lock is re-applied on every tenant activation, so a `t/<slug>` deep link cannot skip unlock | `src/lib/app-state.tsx` | `app-state.test.tsx` | done |
| Offline-aware data: TanStack Query persisted to AsyncStorage, NetInfo and AppState managers, offline banner | `src/lib/query.ts`, `src/ui/kit.tsx` | indirectly | done |
| Notifications inbox with server-synced read state | `src/app/inbox.tsx` | `adapters.test.ts` | partial: waits on `listPortalInbox`, `markPortalInboxItemRead` |
| Memberships and packages view | `src/app/memberships.tsx` | none | partial: waits on `portalListMembershipContracts`, `portalListClientPackages` |
| Push plumbing (permission after first booking, Expo token, device registration, tap opens inbox) | `src/lib/push.ts`, `src/lib/booking.ts` | none | partial: waits on `registerPortalDevice`; needs a physical device and an EAS `projectId` (not verifiable in the simulator or Expo Go) |
| Biometric unlock | `src/lib/biometric.ts`, `src/app/unlock.tsx` | none | done in code; the simulator has no enrolled biometrics, so it was not exercised end to end |

## Verification

- `make mobile-check`: `tsc --noEmit` and ESLint, clean.
- `make mobile-test`: 5 suites, 36 tests, all passing (auth, offline card, household switching, adapters and theme contrast).
- iOS Simulator (iPhone 18 Pro, Expo Go) against the lane API on :8150. Signed in as
  `member@courtside-demo.example.com`, then walked facility search, both tenant themes, home, household
  switch, schedule, booking (with the push soft prompt), card (self and dependent), my bookings, more,
  memberships, invoices, inbox, facility info and profile. Screenshots 01 to 16 are in `mobile-screens/`.

## Known gaps later work must not assume away

- `principal.client_ids` is empty for the seeded member (clients-skeleton gap). The household therefore comes
  only from the adapter until `portalListActableClients` exists.
- The pinned tenant comes from JS config, not native Info.plist (APP-02 note).
- Push and biometrics need a development build on a device.
- No in-app buying and no new-card entry (APP-19).
