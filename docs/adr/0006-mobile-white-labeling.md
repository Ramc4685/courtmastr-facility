# ADR 0006: Mobile white-labelling, OTA, offline card, household switching, push

Status: Accepted. Date: 2026-11-10. Conforms to `docs/architecture/overview.md` (sections 1, 2, 3.4, 3.12,
3.15, 3.16, 6, 7 rows 3, 12, 15, 17). Feature IDs refer to `docs/discovery/feature-inventory.md`; `A1`..`A10`
to `docs/discovery/gaps-and-complaints.md`; "U-nnn" to line numbers in `docs/discovery/unknowns.md`.

## Context

- The reference product ships two member apps from different lineages: a shared multi-tenant app with a facility
  directory (APP-01) and a paid per-facility branded app (APP-02) published through a 4-6 week vendor service
  (APP-03), administered from a separate portal with its own users (PLT-13, U-638).
- The member app is the reference's clearest weakness: 15 of 25 sampled store reviews are 1-star, mostly
  load/crash after an update, sometimes blocking gym entry (A1, A2, A3, U-648). Cards cannot live on two phones
  or be shared between parents, and deleted cards reappear (A4). A parent must log out and in as the child to
  book for them, with no change planned (APP-01, U-664).
- Discovery sources conflict on several points (shared vs branded feature split, cards per app, in-app purchase,
  store account ownership, push text). This ADR states the rule we adopt for each.
- Fixed by the lead: one Expo / React Native codebase; mobile talks only to `/api/v1/portal/*` and
  `/api/v1/public/*`; push goes through the `PushProvider` port with an Expo push adapter; `access` issues signed
  card credentials and mobile renders them (overview section 6); store submission is out of v1 (APP-03 is
  v2-adapter); build module 17 (APP: 4 P0, 10 P1).

## Decision

### 1. One codebase, one JS bundle, N native shells

There is exactly one JavaScript bundle. A "variant" is a native shell that differs only in store-mandated
static identity. Everything a tenant can change after install is runtime config. No tenant-specific code
paths, native modules or forks; behaviour differences are entitlement flags evaluated at runtime.

| Concern | Build time (variant) | Runtime (`app-config`) |
|---|---|---|
| App name, icon, splash, bundle id / application id, URL scheme, associated domains | yes | no |
| Pinned tenant (branded) or directory mode (shared) | yes | no |
| Push credentials (APNs key, FCM service account), signing identity | yes (EAS credentials) | no |
| Colours, logo, typography choice (from bundled fonts), home layout, tiles, captions | no | yes (APP-02, APP-04, APP-05) |
| Locations, hours, content, announcements, schedule presentation flags | no | yes (APP-07, APP-08, APP-14, APP-16, APP-18) |
| Feature entitlements, payment publishable key and connected account id, minimum supported runtime | no | yes |

- Variants in v1: `shared` (FacilityHub-branded directory app) and `demo` (one branded variant that proves the
  mechanism at GATE 17). Variant definitions are JSON files `mobile/variants/<slug>.json` read by
  `app.config.ts` via `APP_VARIANT`. The same fields exist as `tenant_app_variant` metadata columns (name,
  bundle ids, store listing text, asset file ids) so the APP-03 pipeline adapter can generate the file later.
  Trade-off: committed files do not scale past tens of tenants; accepted because store publishing is v2.
- **Tenant identity is read from the native shell, never from the JS bundle or `Constants.expoConfig`.** An OTA
  update carries the config of whichever variant published it, so one update serving every shell would
  otherwise re-brand them all. A config plugin writes `FHTenantSlug` / `FHVariant` into `Info.plist` and Android
  string resources; a ten-line native-constants read exposes them. CI test: bundle built as `shared`, run in the
  `demo` shell, must resolve tenant `demo`.
- API base URL is `https://<tenant-slug>.<platform-domain>/api/v1`, so anonymous tenant resolution is the same
  host rule as web (overview 3.4, SSP-01). The shared app first calls a platform-host directory endpoint
  (`GET /api/v1/public/app-directory?q=&near=`), then switches host.
- `GET /api/v1/public/app-config` returns one versioned document (`schema_version`, `config_version`, ETag):
  theme tokens, locations, entitlements, home layout, content pointers, `min_runtime` (soft and hard). The app
  validates it against the schema compiled into the bundle and falls back to last-known-good, then to the
  bundled default theme. It never blocks first paint on the network (A1).
- Theme tokens are validated on save for WCAG 2.1 AA contrast (text on primary, on surface); the server
  derives the on-colour when the tenant's choice fails. Rejected: free-form per-tenant style sheets.
- Home layout (APP-04, APP-05): draft and live layout JSON on the tenant; "publish" copies draft to live and
  bumps `config_version` (U-639 leaves promotion undocumented; this is our rule). MVP renders a fixed default
  layout through the same tile registry; the designer is P1.

### 2. EAS build profiles

- One EAS project. Profiles in `eas.json` are by purpose, not by tenant: `development` (dev client, internal),
  `preview` (internal distribution, `staging` channel), `production` (store, `production` channel). Variant is an
  orthogonal environment variable, so the build matrix is `profile x variant` driven by CI, and adding a tenant
  adds no profile. Rejected: one profile or one EAS project per tenant (N copies of release configuration).
- `runtimeVersion` is an explicit integer in `mobile/runtime-version.json`, bumped by hand whenever native code,
  the Expo SDK or a config plugin changes. Rejected: the `fingerprint` policy, because variant identity (icon,
  bundle id) is part of the fingerprint and would give every shell its own runtime, fragmenting OTA. Guard: CI
  computes the fingerprint of the `shared` variant and fails if it changed without a runtime bump.
- A native release is therefore `N` binaries from one commit; an OTA release is one bundle for all of them.
- **Store account rule (resolves U-654, U-647).** Branded shells are published under the tenant's own Apple
  and Google developer accounts (newest reference statements; also what current store policy on templated apps
  requires). The shared shell is published under ours. v1 builds the `demo` shell to internal tracks only; the
  submission pipeline is the APP-03 port with a no-op adapter. Setup fees and lead times are commercial, not
  modelled.

### 3. OTA updates and rollback

Driven by A2 ("broke immediately after an app update") and A3 ("the app is the way into the gym").

- Launch never waits for an update: the app starts on the cached bundle (`fallbackToCacheTimeout: 0`),
  downloads in the background and applies on the next cold start. Trade-off: a fix lands one launch late;
  accepted because a spinner at the door is the failure we are designing out.
- Promotion path for every update: `staging` channel (internal shells) -> `production` at 5% rollout ->
  25% -> 100%, each step gated on crash-free sessions (SLO 99.5% per release, tracked first-party) and on a
  config-contract check: every live tenant's `app-config` must validate against the new bundle's schema. That
  check replaces per-tenant device smoke tests, which do not scale; device end-to-end runs on `shared` and
  `demo` only.
- Rollback is two-layered: (1) the update client's own launch-failure recovery reverts to the previous bundle
  on device; (2) operators republish the previous update or roll back to the embedded bundle on the channel.
  Both are rehearsed in the release runbook before GATE 17.
- Channels are global, not per tenant. A tenant can be held back only by `min_runtime`/feature flags in its
  config, never by a private channel. Rejected: per-tenant channels (drift, N rollouts; the reference's
  per-app update service is where its regressions came from).
- Backward compatibility: the API is additive within `/api/v1` (overview 3.15) and `app-config` carries
  `schema_version`; the server keeps serving the previous config schema for as long as a supported runtime
  needs it. `min_runtime.hard` forces an update screen, **except** the membership card, cached bookings and
  facility contact screens, which stay reachable.
- OTA never changes native capability, payment flows mandated by store policy, or the app's stated purpose.

### 4. Offline-first membership card (APP-06, CHK-13, overview divergence 17)

Offline-first applies to the member's phone: the card always renders. The scanner side stays online and the
server stays authoritative for eligibility.

- **Issuance.** `access` owns a `credential` of kind `mobile_pass` per client. For each (credential, app
  installation) the server issues a compact signed token:
  `FH1.<base64url(payload)>.<base64url(sig)>`, payload = `kid`, `cred` (credential id), `inst` (installation
  id), `iat`, `exp`; Ed25519 with a per-tenant key pair (private key encrypted at rest, `kid` rotation with
  overlap). About 170 characters, a comfortably scannable QR.
- **Time box.** Default validity 72 hours, tenant-configurable 12 hours to 7 days. The app refreshes whenever
  it is foregrounded online and opportunistically in a background task once half the lifetime has passed.
  Trade-off: longer validity tolerates longer offline stretches but lengthens the window in which a
  screenshot scans; mitigated by the check-in screen showing the member photo (reference behaviour, APP-06)
  and by server-side state. Rejected: a device-held secret generating TOTP-style codes (true rotation, but
  needs time-synced offline verifiers and secure-enclave handling we do not otherwise need); rejected: opaque
  random tokens (no tamper-proof expiry, no future offline verification at door adapters).
- **Verification.** Kiosk and front desk post the scanned string to the check-in endpoint; `access` verifies
  signature and `exp` (5 minutes leeway), loads the credential, then runs the normal check-in decision
  (membership state, holds, waivers, access rules). The token proves identity of the card, never entitlement,
  so freezing, cancelling or revoking takes effect at the next scan regardless of what the phone has cached.
- **Storage.** Token and session in the platform secure store (Keychain / Keystore); card display data (name,
  photo thumbnail, membership label, number) in the local cache. The card screen needs no network and no
  live session; it is the first screen reachable from a cold start and from the hard-update screen.
- **Expired while offline.** The card still renders, marked "refresh needed", with the membership number in
  text and as a static barcode so front-desk lookup works (overview divergence 17 fallback). It never renders
  blank.
- **Static barcode mode.** Tenants whose scanners read only 1D key-tag codes may enable a static Code 128 of
  the credential number as the primary code. This is parity behaviour ("scans like a key tag", APP-06) and is
  screenshot-shareable; it is off by default and labelled as weaker in settings.
- **Resolved conflicts.**
  - U-464, U-641 (self-registered vs auto-generated number): cards are server-issued for the authenticated
    identity. No free-text card registration; an existing key-tag number on the client is reused as the
    credential number.
  - U-470, U-652, A4 (several cards, several devices, cap of ten): a device shows a card for every client the
    signed-in identity can act for (section 5). No cap. The same client's card may live on any number of
    devices, each with its own installation-bound token. Members list and revoke their installations; staff
    revoke per client. The card set is derived from relationships, so there is nothing to add or delete and a
    removed card cannot reappear; the reference's chain-wide "delete all cards" tool is not reproduced.
  - U-465 (mobile or GPS check-in): no phone-only attendance check-in. Entry is recorded only by a scan at a
    desk or kiosk. The reference's "social check-in" tile is a share action (APP-15, P2).
  - The phone card does not open doors by itself; door access remains the `DoorController` port (CHK-13).
- Wallet passes (CHK-13 P1) sit behind a `WalletPassProvider` port with a no-op adapter; a pass carries the
  static credential number because an issued pass cannot refresh a short-lived token offline.
- v1 offline scope is read-only: card, cached schedule, my bookings, facility info. No offline write queue;
  bookings and purchases need capacity and payment checks and require `Idempotency-Key` (overview 3.12).

### 5. Household account switching (FAM-02, FAM-03, overview divergence 3)

- One identity signs in once. The app loads the set of clients it may act for (`client_portal_access` plus
  active guardian-type relationships) and shows a persistent profile switcher. Switching is instant and local;
  no logout. This replaces the reference's log-out-and-in-as-the-child flow (APP-01, U-664).
- "Acting for" is client-side state. Every portal request names the target client explicitly and the server
  checks `can_act_for(identity, client_id)` on each call (overview 3.16). Rejected: a server-side "current
  profile" on the session, because the web portal and two phones sharing an identity would race each other.
- Payment always uses the signed-in identity's payment methods and billing address (FAM-03). Entitlement use
  for the selected client reads share rows, not the family graph (FAM-04, FAM-05).
- The card screen shows every dependent's card regardless of the selected profile (swipe between cards);
  both guardians' phones hold them (A4).
- A dependent with their own identity (a teenager) signs in to their own device and sees only themselves.
- Identities are tenant-scoped (overview 3.4). In the shared app a person who belongs to two facilities holds
  two sessions; the "home club" switcher (APP-01) changes tenant, the profile switcher changes client. A
  branded shell is pinned to one tenant and offers only the location switcher (APP-16).
- When a relationship or portal access ends, the next sync removes the profile and its card; until then the
  server refuses calls and the scan-time decision uses current state.

### 6. Push notifications (MKT-16, MKT-17, MKT-13, overview divergence 12)

- `engagement` records an app installation per device: tenant, variant, platform, Expo push token, optional
  identity, selected home location(s), per-topic opt-ins, `last_seen_at`. Anonymous installations are valid:
  the reference lets users without an account receive push and promotions (APP-01).
- Delivery uses the `PushProvider` port with the Expo push adapter. Tokens are registered against the variant
  that produced them; each branded shell has its own APNs key and FCM service account held as EAS credentials.
  Sends are jobs on the `notifications` queue; a receipt-polling job deactivates tokens reported as
  unregistered. Rejected for v1: direct APNs/FCM adapters per tenant (credential custody for N tenants); the
  port keeps that door open.
- Three classes, each a topic the member can mute separately: transactional (booking, waitlist promotion B8,
  reminders MKT-13, payment failed), broadcast (MKT-16, P0), targeted (MKT-17, P1, reusing the campaign
  segment engine). Routing for a dependent's events goes to every identity that can act for that client.
- **Text rule (resolves U-604).** Body is capped at 180 characters for parity; the link is a separate field
  (deep link or https URL) and does not consume the cap. Emoji allowed.
- **Recall and edit (resolves U-600 gap).** A scheduled message is editable and cancellable until dispatch.
  After dispatch it can be removed from the in-app inbox but an OS notification already shown cannot be
  recalled; the UI says so.
- Every push also writes an `inbox_item`, kept 30 days and readable with push permission off (MKT-16, APP-05
  Notifications tile).
- Payloads carry the visible text plus ids; the app fetches detail after open. Transactional templates avoid
  a minor's full name on the lock screen by default.
- The OS permission prompt is shown after a soft in-app prompt at a relevant moment (first booking, first
  waitlist join), not at first launch.
- In the shared shell the OS shows our app name and icon, so the facility name is prefixed to the title. In a
  branded shell the tenant's identity is native.
- **Admin model (resolves U-601, U-638, PLT-13).** No separate app-admin portal or user store. Sending is the
  location-scoped permission `engagement.push.send`; app content and layout is
  `engagement.app_content.manage`. The reference's "notification-only" tier is a role holding only the first.

### 7. Shared app vs branded app

The reference splits features by app flavour (U-640): both get card, schedule, announcements and broadcast
push; branded alone gets waitlist, targeted and location-specific push, custom home and splash, unlimited
tiles, own listing, reporting, multi-location. **Our rule: flavour never gates function.** The same bundle
runs in both; differences are native identity plus commercial entitlements stored in `tenant_entitlement`
(PLT-14, overview divergence 15).

| Capability | Shared shell | Branded shell | Gate |
|---|---|---|---|
| Name, icon, splash, store listing, own deep-link domain | ours | tenant's | build variant |
| Facility directory, multi-tenant sessions, home club (APP-01) | yes | no (pinned) | build variant |
| Schedule, booking, waitlist, my bookings, card, purchase (APP-01, APP-06, APP-19) | yes | yes | none |
| Runtime theme (colours, logo) inside the app (APP-02) | yes | yes | none |
| Location switcher, location-addressed broadcast push (APP-16, MKT-16) | yes | yes | none |
| Home-screen designer and tile palette (APP-04, APP-05) | default layout | yes | entitlement `app.home_designer` |
| Targeted push (MKT-17) | entitlement | entitlement | `push.targeted` |
| App analytics dashboard (APP-17) | entitlement | entitlement | `app.analytics` |

Rules adopted for the logged conflicts:

- **Waitlist (U-650, U-129):** a core booking feature in both shells and the web portal; never flavour-gated.
- **In-app purchase (U-651, U-289, APP-19):** native checkout with the Stripe PaymentSheet against the tenant's
  connected account in both shells, using the same checkout orchestration as the portal. This is our design
  choice, not parity (members of the reference get a web view). It covers real-world services (memberships,
  packages, classes, rentals). Digital-only content is not sold inside the app in v1 (store in-app-purchase
  rules); such items open the portal in the system browser.
- **Directory exposure (APP-01):** listing in the shared directory is opt-in per tenant
  (`is_listed_in_app_directory`); a tenant can also be reached by deep link or QR without being listed. This
  avoids the reference's "similarly named business" confusion.
- **Shared to branded migration (APP-02, APP-03):** a separate install; sessions do not transfer (different
  signing teams), credentials are the same, both shells work side by side. When a tenant has a published
  branded shell, the shared shell shows a store-link banner and the tenant can announce it by push.
- **Universal links:** the tenant domain's association files list the branded shell when one exists, otherwise
  the shared shell; all emails and pushes link to https URLs on the tenant domain.
- **Analytics (U-694, U-646):** first-party event ingest only; no third-party analytics SDK, because the user
  base includes minors. Metric definitions are ours (APP-17, P1).
- **Plan packaging (U-60):** not modelled beyond the three entitlement keys above.

## Consequences

- Adding a tenant to the shared app is zero mobile work. Adding a branded tenant is a variant file, credentials
  and store listings; no code and no separate OTA stream.
- One bundle for all shells means one regression reaches everyone. The staged rollout, crash-free gate,
  launch-on-cache rule and two-layer rollback are therefore mandatory release machinery, not optional polish.
- The manual `runtimeVersion` is a discipline cost; the CI fingerprint guard is what makes it safe.
- The tenant-identity-from-native-shell rule adds a small config plugin and a test that must never be removed.
- The card is useful with no network and no session, at the price of a bounded replay window (the token
  lifetime) that only photo verification and server state mitigate.
- `access` gains per-tenant signing keys and an installation-scoped credential token; `engagement` gains the
  installation table and topic preferences; `platform` gains `tenant_app_variant` metadata and three
  entitlement keys. These need rows in `data-model.md` and `rbac.md`.
- Vocabulary differs from the reference (no "branches", no separate app-admin users, cards are not "added").
- Tenants on 1D-only scanners get a weaker static barcode by explicit choice.
- Publishing under tenants' own developer accounts keeps us inside store policy but makes onboarding depend on
  the tenant's account paperwork (the reference quotes about 30 days for the business identifier alone).

## Alternatives considered

1. **Per-tenant fork or per-tenant EAS project.** Maximum isolation; rejected: N release trains, guaranteed
   drift, and it reproduces the reference's update-regression pattern (A2).
2. **Runtime-only theming in a single shared app, no branded shells.** Cheapest; rejected: fails "own name
   and icon in the stores" (APP-02, P0 for owners).
3. **Web view or PWA wrapper around the member portal.** One UI codebase; rejected: weak offline card, weak
   push on iOS, and store review risk for thin wrappers. The reference's web-view checkout is the part members
   dislike.
4. **Per-tenant OTA channels.** Per-tenant hold-back; rejected in favour of config flags (section 3).
5. **`fingerprint` runtime policy.** Automatic native-change detection; rejected because variant assets
   fragment the runtime (section 2). Kept as a CI guard only.
6. **TOTP-style rotating card or opaque server tokens.** See section 4.
7. **Static barcode only (parity).** Simplest and matches the reference; rejected as the default because it is
   freely shareable. Kept as an opt-in mode.
8. **Server-side "current profile" for household switching.** Rejected (section 5).
9. **Direct APNs/FCM.** Rejected for v1; reachable later through `PushProvider`.
10. **Third-party mobile analytics SDK (what the reference used).** Rejected for minors' data and consent scope.

## Open questions

1. **Push across signing teams.** The design assumes one EAS project can hold APNs/FCM credentials for several
   bundle ids owned by different Apple teams and that the Expo push service routes by the app that registered
   the token. Needs a one-day spike before module 17; if false, branded shells use a direct APNs/FCM adapter
   behind the same port.
2. **Card token lifetime default.** 72 hours is a judgement call between offline tolerance and screenshot
   replay. Confirm, or pick 24 hours with wallet pass as the long-offline path.
3. **Kiosk offline verification.** The token format allows it; v1 keeps scanners online (no discovery
   evidence of offline check-in). Confirm it stays out of v1.
4. **Staff use of the app (A10).** The overview restricts mobile to portal and public surfaces. Coaches marking
   attendance on a phone would need the staff surface; proposed as a post-v1 role-routed shell in the same
   bundle, not decided here.
5. **Digital content sales.** If the video library (engagement) is ever sold on its own, in-app purchase rules
   apply and need a store-billing adapter. Confirm it is bundled with memberships only in v1.
6. **Where `tenant_app_variant` and the installation table live.** Proposed `platform` and `engagement`
   respectively; the overview's aggregate lists do not name them yet and should be amended there first.
7. **Second branded variant for GATE 17.** One `demo` shell proves the mechanism; a second would prove
   isolation between shells (push credentials, universal links). Cost is roughly a day.

## Reconciliation with the data model (Phase 1 review)

`docs/architecture/data-model-programs.md` section 3 (engagement) and `data-model-money.md` section 3 (access)
are the schema of record.

| This ADR says | Schema of record |
|---|---|
| `tenant_app_variant` metadata in `platform` | `engagement.app_config` (one row per tenant: `mode` `shared \| branded`, `app_name`, `icon_file_id`, `theme`, `store_metadata` for the APP-03 pipeline). Only the shared-app directory listing is on the global `tenant` row (`is_listed_in_app_directory`, `app_directory_name`), because that query runs before a tenant is chosen |
| installation table in `engagement` | `device_registration` (push token per install; `platform` `ios \| android`) |
| per-tenant signing keys and an installation-scoped credential token in `access` | `credential` rows of `kind = 'app_card'` with a per-card `secret_ciphertext` and `device_label`; revoking one device is revoking one row, so no tenant-wide key rotation is ever needed |
| entitlement keys | `tenant_entitlement` rows, as written |
| `data-model.md`, `rbac.md` | `data-model-*.md`, `rbac-matrix.md` |

Open question 6 (where the variant metadata and installation table live) is closed by the table above.
