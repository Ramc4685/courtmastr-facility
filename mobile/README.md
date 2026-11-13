# Member app (`mobile/`)

Expo (SDK 58) + React Native + strict TypeScript + Expo Router. One shared app that finds a facility at
runtime and themes itself per tenant (ADR 0006). Status per parity feature: `docs/status/17-mobile.md`.

## Run it in the iOS Simulator

```
make mobile-install          # once; Node 22 + pnpm
make up lane-db seed api     # backend on FH_API_PORT (repo .env; default 8100)
cp mobile/.env.example mobile/.env.local   # set EXPO_PUBLIC_API_ORIGIN to http://localhost:<FH_API_PORT>
make mobile                  # then press i (installs Expo Go in the booted simulator)
```

If `i` times out opening the simulator: `xcrun simctl launch booted host.exp.Exponent`, then
`xcrun simctl openurl booted exp://localhost:8081` (use the Metro port it prints). The simulator reaches the
host's `localhost` directly. On a physical phone with Expo Go, scan the QR code and set
`EXPO_PUBLIC_API_ORIGIN` to your machine's LAN address.

Enter the facility code `courtside-demo`, then sign in with a seeded member (`docs/dev/demo-accounts.md`),
for example `member@courtside-demo.example.com`. Biometric unlock and push need a development build
(`eas build --profile development`); Expo Go limits push.

## How the app reaches a tenant

The browser portal finds the tenant from the Host (`courtside-demo.localhost`). iOS does not resolve
`*.localhost`, so in development the app calls `EXPO_PUBLIC_API_ORIGIN` and sends `X-Tenant-Slug: <slug>`,
which `public_session` accepts for the public routes (facility lookup, sign-in, magic link). After sign-in the
tenant comes from the access token. With `EXPO_PUBLIC_PLATFORM_DOMAIN` set, requests go to
`https://<slug>.<domain>/api/v1` instead, the production shape (`src/lib/config.ts`, `tenantBase`).

## Configuration (`.env.local`, never secrets)

| Variable | Meaning |
|---|---|
| `EXPO_PUBLIC_API_ORIGIN` | API origin in development; the tenant travels in `X-Tenant-Slug`. |
| `EXPO_PUBLIC_PLATFORM_DOMAIN` | When set, requests go to `https://<slug>.<domain>` instead (production shape). |
| `EXPO_PUBLIC_WEB_ORIGIN` | Member web portal origin (https) for tell-a-friend links (`<origin>/f/<slug>`); defaults to `https://<platform domain>`. Unset: no tell-a-friend row. |
| `EXPO_PUBLIC_PORTAL_ADAPTER` | `api` (default) or `demo`. See below. |

## Real API vs demo adapter

With the default `api` adapter every member screen calls the real member-portal API through
`src/api/client.ts`: household (`/portal/clients`, server-checked acting-for ids), schedule and booking
(session listings, enrollments, package-backed booking), my bookings, the check-in card (`fhq.` rolling QR
derived on the device from the seed `/portal/app-cards` issues), memberships, packages, progress
(`/portal/assessment-bests`), invoices, paying with a saved card, the inbox and push-device registration.

Phase 11 C2 adds news and info (`/portal/app-contents`, grouped by kind; pictures are not shown yet, the app has
no authenticated image loader), location contacts and "Try us" (public, also reachable from sign-in; the trial
form always shows the same thank-you), feedback, favourites with the next 14 days of matching sessions (removing
only: no app list shows programs or booking types to favourite), sharing a booking and tell-a-friend through the
system share sheet, and anonymous screen counts (`src/lib/usage.ts`: route names only, batches of 50, every 60 s
and on background, only while signed in). Add-to-calendar is not built (no calendar module is bundled).

Facility search by name (`searchAppDirectory`) and the live tenant theme, home layout and currency
(`getPublicAppConfig`) come from the real public API; when the theme cannot be loaded the app uses the saved or
bundled one. The buy screen asks the server which card processor applies with a read
(`GET /portal/payment-methods/processor`), never by creating a setup intent, and shows prices in the
facility's currency. "Try us" shows the same thank-you for every server answer, but says the request was not
sent when there was no answer (offline) or a server error.

`EXPO_PUBLIC_PORTAL_ADAPTER=demo` switches to `src/adapters/demo.ts`, an in-memory stand-in for UI work with
no backend. Every screen it feeds shows a **DEMO DATA** banner, and demo card tokens end in `.DEMO`.

## Security notes

Tokens live only in `expo-secure-store` (`fh.session.<slug>`); TanStack Query's persisted cache in AsyncStorage
holds no tokens. Emailed sign-in links carry the token in the URL fragment; the app reads it from the fragment,
consumes it once and replaces the route so it never stays in navigation state. Links with `?token=` are refused, and a link this device did not ask for in the last 20 minutes is used only after
the person confirms (login CSRF). Every tenant activation re-applies the biometric lock, deep links included.
The paste-a-link field covers links opened on another device. Payments send only a saved payment-method id.

## Commands

```
make mobile-check   # tsc --noEmit + eslint
make mobile-test    # Jest + React Native Testing Library
make mobile-api     # regenerate src/api/schema.d.ts after make openapi
```

## Builds (EAS; store submission is out of scope)

`app.config.ts` reads `variants/${APP_VARIANT}.json` (default `shared`): scheme, bundle id, display name and an
optional pinned tenant. A tenant-branded build is a variant file plus a profile, for example
`APP_VARIANT=demo eas build --profile preview`. Profiles in `eas.json`: `development` (dev client),
`preview` (internal, `staging` channel), `production` (store, auto-increment). OTA updates share
`runtime-version.json` across variants, so one JS update reaches every tenant build on that runtime.
