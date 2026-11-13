# Module 14: engagement (context `engagement`)

Branch `claude/happy-chebyshev-1b3896` (lane w2d), migration `0801_engagement_messaging`. Module README:
`backend/app/modules/engagement/README.md` (rules, written assumptions, the endpoints the mobile app depends on).
Tests: `backend/app/modules/engagement/tests/` (`test_messaging.py`, `test_rules.py`, preference tests from module
4), the generated isolation, RLS, location-scope and security suites, `web/src/features/engagement/engagement.test.tsx`
and `web/e2e/engagement.spec.ts` (axe).

Counts: P0 15 owned here (11 MKT, 4 SSP): 8 done, 7 partial. P1: MKT-20 done; MKT-04, 06, 11, 12, 17, 18 not built.
The other SSP rows belong to the selling modules and the portal screens (see `README.md` in this directory).

| Feature | Priority | Status | Where | Notes |
|---|---|---|---|---|
| MKT-01 Email verification | P0 | done | module 4 (`/public/email-verifications/confirm`); `_deliver` skips marketing to unverified addresses | Transactional mail goes to any unsuppressed address (README assumption 2). |
| MKT-02 Subscriptions per address | P0 | partial | communication preferences (module 4); `/public/communication-preferences` (open, put), `/public/unsubscribe`; web `/unsubscribe` | Fragment token `fhu`, hashed, 90 days, body only. No RFC 8058 `List-Unsubscribe` header: the email port has no headers. |
| MKT-03 Email campaigns | P0 | partial | `/campaigns` CRUD, `send`, `schedule`, `cancel`, `test`; built-in segments; web `/engagement` | Plain text with merge fields, no rich text. Fan-out runs in the sending transaction (`shortcut:` comment), scheduled sends by `send_due_messages` every minute. SMTP/Mailpit adapter only. |
| MKT-05 Template library | P0 | partial | `/message-templates` CRUD, copy-on-edit via `copied_from_id` | One system template (session reminder); no preset library seeds. |
| MKT-07 Campaign history and analytics | P0 | partial | `/campaigns/{id}/stats`, `/campaigns/{id}/recipients`, `/messages`; `record_delivery_event` | Counters move forward once per step. No provider webhook (SMTP emits none) and no CSV export. |
| MKT-08 Suppression list | P0 | partial | `/suppressions` (list, create, release); checked in `_deliver` | A second bounce after release is permanent. Fed only by `record_delivery_event`, which no provider calls yet. |
| MKT-09 Anti-spam guardrails | P0 | done | server-side unsubscribe footer on every marketing email; consent events (module 4); per-client `/messages?client_id=` | Footer is added after rendering and cannot be removed by the template. |
| MKT-10 Direct email from the profile | P0 | done | `POST /messages` (`message.send_direct`, coach `own`) | Body kept for direct messages only. |
| MKT-13 Session and booking reminders | P0 | done | `/reminder-rules`; handlers on booking and enrollment create, reschedule, cancel | `scheduled_notification` rows, two offsets at most, re-checked at send time. |
| MKT-14 Staff alert routing | P0 | partial | `/notification-routes`; alerts on waitlist promotion and declined payments | No daily summary job. |
| MKT-16 Push broadcast | P0 | partial | `channel=push` campaigns, 180-character check, `/portal/devices`, portal inbox with read state and recall; the inbox and badge show the acting-for member's items only (`?client_id=`), never a household merge | No push provider: device sends are logged `channel_unavailable`; the inbox carries the announcement. |
| MKT-20 Triggered sequences | P1 | done | `/automation-rules` (trigger, delay, template, exit event) | Fixed trigger catalogue (`service.TRIGGERS`); delay 0 sends in the handler's transaction. |
| SSP-01 Portal enablement and landing | P0 | done | `/locations/{id}/portal-settings`, `GET /public/portal-config` (`tenant_slug`); web `/f/:slug` landing (locations, welcome, programs, sign-in, sign-up) | Tenant from host or `X-Tenant-Slug`; a signed-in call whose slug names another tenant is 404 `tenant-not-found` (`current_ctx`). |
| SSP-05 Public self-registration | P0 | done | `POST /public/portal-signups`, `POST /public/portal-signups/confirm`; `portal_signup`; web `/f/:slug/signup` and `/signup/confirm` | Off by default per location (`allows_self_signup`). Same 202 for known and unknown addresses; token in the URL fragment, hash kept, single use, 24 h. Always a new client (staff merge duplicates). The form collects name, email, mobile only: a portal field policy that requires more refuses the sign-up. |
| SSP-07 Post-registration redirects | P2 | done | portal settings `redirect_url`, `group_redirect_urls`, `redirect_domains` | https only, no userinfo or port, host must be the tenant's own domain or an allow-listed one; re-checked on every public read. Group redirects have no staff screen yet (API only). |
| SSP-13 Portal menu configuration | P1 | done | portal settings `menu` [{key, label, is_visible}]; portal nav applies it | Home and Profile cannot be hidden; order editing is API only (the staff screen keeps the built-in order). |
| SSP-15 Social links | P2 | done | portal settings `social_links` (facebook, instagram, x, youtube, tiktok, linkedin; https) | Shown in the landing and portal footers. |
| SSP-14 Portal design and legal text | P0 | done | tenant `brand_primary_color` / `brand_accent_color` in `GET /public/branding`; `terms_acceptance`; `terms_version_id` on every portal sale | Colours apply only where they pass WCAG AA (primary 4.5:1 with white, accent 3:1), never in dark mode. Each portal sale (memberships, packages, programs, rentals, guest) records the terms version shown or answers 409 `terms-changed`. The documents `portal_terms` binding is the only terms source: a `portal_settings.terms_text` saved before Phase 11 is no longer served and is not migrated into a binding (nothing is deployed, so no data migration). |
| SSP-16 Video library | P0 | done | `/videos` CRUD, `GET /portal/videos` | Allow-listed providers (YouTube, Vimeo) only. |

Gap B8 (waitlist promotion notice): programs sends it through the notification port, which now routes through
`_deliver`, so it is logged, suppressed addresses are skipped, and staff are alerted by route.
