# Member app (`mobile/`)

Expo (SDK 58) + React Native + strict TypeScript + Expo Router. One shared app that finds a facility at
runtime and themes itself per tenant (ADR 0006). Status per parity feature: `docs/status/17-mobile.md`.

## Run it in the iOS Simulator

```
make mobile-install          # once; Node 22 + pnpm
make up lane-db seed api     # backend on FH_API_PORT (this lane uses 8150)
cp mobile/.env.example mobile/.env.local   # EXPO_PUBLIC_API_ORIGIN must match FH_API_PORT
make mobile                  # then press i (installs Expo Go in the booted simulator)
```

If `i` times out opening the simulator: `xcrun simctl launch booted host.exp.Exponent`, then
`xcrun simctl openurl booted exp://localhost:8081` (use the Metro port it prints). On a physical phone with
Expo Go, scan the QR code and set `EXPO_PUBLIC_API_ORIGIN` to your machine's LAN address.

Sign in with a seeded member (`docs/dev/demo-accounts.md`), for example `member@courtside-demo.example.com`.
Biometric unlock and push need a development build (`eas build --profile development`); Expo Go limits push.

## Configuration (`.env.local`, never secrets)

| Variable | Meaning |
|---|---|
| `EXPO_PUBLIC_API_ORIGIN` | API origin in development; the tenant travels in `X-Tenant-Slug`. |
| `EXPO_PUBLIC_PLATFORM_DOMAIN` | When set, requests go to `https://<slug>.<domain>` instead (production shape). |
| `EXPO_PUBLIC_PORTAL_ADAPTER` | `demo` (default) or `api`. See below. |

## Real API vs demo adapter

Facility lookup, sign-in (password and magic link), refresh, sign-out, `/me`, signed-in devices and facility
hours call the real API on this branch. Household, card, schedule, booking, memberships, packages, invoices,
payments, inbox and push registration go through `src/adapters/` because those endpoints are not merged yet.
`api.ts` targets the planned operations in `docs/api/openapi-*.yaml`; `demo.ts` is an in-memory stand-in.
Every screen fed by the demo adapter shows a **DEMO DATA** banner naming the API it waits on, and demo card
tokens end in `.DEMO`. Flip `EXPO_PUBLIC_PORTAL_ADAPTER=api` once those endpoints land.

## Security notes

Tokens live only in `expo-secure-store` (`fh.session.<slug>`); TanStack Query's persisted cache in AsyncStorage
holds no tokens. Emailed sign-in links carry the token in the URL fragment; the app reads it from the fragment,
consumes it once and replaces the route so it never stays in navigation state. Links with `?token=` are refused.
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
