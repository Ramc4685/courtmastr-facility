# Web

One React 18 + TypeScript app for the staff admin and (later) the member portal, routed by principal kind:
staff land in the admin shell, clients in `/portal`. Vite, Tailwind, TanStack Query, React Router.

## Run

```sh
make up migrate seed api   # backend on :8100 (see backend/README.md)
make web-install           # once: pnpm install + Playwright chromium
make web                   # http://localhost:5183, /api proxied to :8100
```

Sign in with a demo account from `docs/dev/demo-accounts.md`. Emailed links (magic link, invite, reset) land
in Mailpit at http://localhost:58025 and point at `/auth/*` pages here.

| Command | Does |
|---|---|
| `make web-check` | `tsc --noEmit` (strict) and ESLint (incl. jsx-a11y) |
| `make web-test` | Vitest + Testing Library |
| `make web-e2e` | Playwright smoke test against the live API (starts Vite if it is not running) |
| `make web-api` | Regenerate `src/api/schema.d.ts` after `make openapi` |

## Layout

```
src/api/        schema.d.ts (generated, do not edit), client.ts (typed fetch wrapper)
src/app/        routes, guards, app frame, navigation model
src/components/ design system: Button, Field (Input/Select/Checkbox), Table (keyset), Dialog, Toast, Tabs, Badge, states
src/features/   screens per backend context (platform = build module 1), auth, portal placeholder
src/lib/        auth/session context, formatting and time zones, theme
e2e/            Playwright specs (axe WCAG 2.1 AA check in each)
```

Rules that are easy to break:

- Never store tokens in browser storage. The session is the HttpOnly cookie; the CSRF token lives in memory
  (`client.ts`) and is re-read from `GET /auth/session` on load. All requests go through `api.*`, which adds
  `X-CSRF-Token`, an `Idempotency-Key` on mutations, the refresh-and-retry on 401, and problem+json errors.
- Hide what the role cannot do with `can(key)` (keys from `GET /me`), and still handle 403: pages behind a
  permission use `RequirePermission`, and `ErrorState` explains a 403 from the API.
- Colours come from the CSS variables in `src/index.css` (light and dark); use the Tailwind token names
  (`bg-surface`, `text-muted`, `bg-primary`), not raw colours.
- The display name comes from `config/app.yaml` (`app.display_name`) at build time; do not hard-code it.
- In development the tenant slug for anonymous calls is `courtside-demo` (override with `VITE_TENANT_SLUG`);
  in production the tenant comes from the host.
