## backend/app/modules/engagement/README.md

Re-run after Phase 11 (diff `aa20e1b..HEAD`). The Phase 11 sections of the README (portal entry, C1 app config, C2 content,
favourites and usage) match the code on routes, gates, limits and tile types. What still differs:

- [wording] README line 9 says `models.py` has "15 tables" and lists them. It defines 21 (`models.py` `__tablename__`): the list
  lacks `portal_signup` (:573), `app_config` (:624), `app_content` (:657), `location_contact` (:694), `app_inquiry` (:729),
  `client_favorite` (:770) and `app_usage_day` (:791). The Phase 11 sections name them, but the file table does not. Lines 3-5 (scope)
  omit the member app.
- [wording] The file table (README lines 7-16) has no rows for `signup.py`, `content.py`, `member.py`, `domain/app_config.py`,
  `events.py`, `permissions.py` or `schemas.py`. Line 11 says `service.py` holds "portal settings and videos" and nothing else about
  Phase 11. Line 14 says `subject.py` holds merge and data-subject handlers for four tables. It now registers five handler pairs
  (`engagement_favorite`, `engagement_app_inquiry`, `engagement_signup`, `engagement_messaging`; subject.py:110-124), and a fifth,
  `"engagement"` for `communication_preference` and `consent_event`, lives in `service.py:340-342`.
- [wording] Line 16 lists staff screens as "campaigns, templates and segments, automations and reminders, settings". The web feature
  also has `AppConfigPage.tsx` (route `engagement/app`, `web/src/app/App.tsx:206`) and `MemberContentPage.tsx` (route
  `engagement/app-content`, :207). Only the second is described, in the C2 section.
- [contract] `getPortalVideo` (`GET /portal/videos/{video_id}`, `docs/api/openapi-programs.yaml:5446`) has no route. `service.get_portal_video`
  exists (`service.py:1882`), is never called, and `router.py:448` mounts only the list. Not listed under "Not built".
- [contract] `POST /public/portal-signups` and `POST /public/portal-signups/confirm` (`router.py:511,525`) are not in any
  `docs/api/*.yaml`. Every other Phase 11 route is (app-config, app-directory, app-contents, location-contacts, trial-requests,
  feedback, favorites, app-usage, app-inquiries).
- [wording] The "Endpoints the mobile app depends on (keep stable)" section (README lines ~104-114) names `mobile/src/api/api.ts`, which
  does not exist. The adapter is `mobile/src/adapters/api.ts`. Of the listed routes it calls only `GET /portal/inbox` (no
  `client_id`), `POST /portal/inbox/{id}/read` and `POST /portal/devices` (api.ts:253-256). Nothing in `mobile/src` calls
  `/portal/inbox/unread-count`, `DELETE /portal/devices/{id}`, `/portal/videos`, `/public/portal-config` or the preferences route.
  The adapter does call routes the section omits: `/public/app-config` and `/public/app-directory` (api.ts:141,155),
  `/portal/app-contents`, `/public/location-contacts`, `/public/trial-requests`, `/portal/feedback`, `/portal/favorites`,
  `/portal/favorites/schedule`, `/portal/app-usage` (api.ts:259-275), plus `/portal/wallet-passes`, `/portal/package-plans`,
  `/portal/payment-methods/setup-intents`, `/portal/payments/{id}/confirm`, `/portal/session-listings`, `/portal/enrollments`,
  `/portal/app-cards` and `/portal/assessment-bests`.
- [undocumented] Events: the README names only `engagement.app_inquiry.received` (line 192). Five others are unmentioned:
  `engagement.campaign.sent`, `engagement.message.bounced`, `engagement.consent.changed`, `engagement.portal_signup.confirmed` and
  `engagement.app_config.updated` (`events.py:9-40`). The README's portal-entry section mentions `PortalSignupConfirmed`
  in prose only.
- [undocumented] Cross-context hooks from Phase 11: `service.present_schedule` registered with
  `programs.selfservice.register_listing_presenter` (`service.py:1989`); `platform.branding.public_url_for_key` for directory icons
  (`service.py:1984`); and `core.db.platform.search_app_directory`, the only cross-tenant read (`service.py:1985`). C1 says flags apply
  "inside `listPortalSessionListings`" but names none of these hooks or the cross-tenant read.
- [undocumented] Portal inbox items expire 30 days after publishing (`INBOX_DAYS = 30`, `service.py:355`; set at :953 and :1463;
  filtered by `_live_items`, :1252-1253). Deviation 4 says nothing about expiry.
- [undocumented] Permission keys `engagement.sms_campaign.send` and `engagement.inbox.reply` (`permissions.py:19,23`) are registered
  and used nowhere. SMS is under "Not built"; replying is not.
- [undocumented] Built-in segments are read-only (`409 segment-read-only`, `service.py` `ensure_builtin_segments`), the system-template
  catalogue (`SYSTEM_TEMPLATES`) and `POST /segments/preview` (`router.py:126`) are not in the README. Releasing a permanent
  suppression is `409 suppression-permanent`, a second release `409 invalid-state-transition`; line 56 says only "permanently after a release".
- [undocumented] The audit action `engagement.app_inquiry.receive` (`content.py:32,259`) is not a registered permission; it is only an
  audit label for an anonymous write. README does not say so.
- [wording] The C2 section says the staff page needs `engagement.campaign.read` as well as the content keys. True
  (`App.tsx:196`), but it makes `MemberContentPage` and `AppConfigPage` unreachable for a role holding only the Phase 11 keys. This
  is a code issue as well as a doc one.
- [contract] The README says the context's endpoints are the contract (lines 104-110), but `docs/api/openapi-programs.yaml` tags many operations `engagement` that no route serves, and Not built (lines 116-120) lists none of them. Evidence is the router (`router.py:37-479`) against the spec. Operations missing from the code:
  - `POST /webhooks/email/{provider}`. README deviation 6 (lines 80-82) says the webhook is not built, but this is not in Not built.
  - Campaign operations: `POST /campaigns/{id}/resume`, `/unschedule`, `/copy` and `/audience-preview`.
  - Media library: `GET|POST /media-assets` and `DELETE /media-assets/{id}`.
  - App content: `/news-stories` (and `/public/news-stories`), `/home-screens`, `/app-tiles`, `/portal-content*`, `/portal/content`, `/locations/{id}/app-content`, `/app-config`, `/public/app-config` and `/public/app-directory`.
  - Portal and public intake: `/portal-invitations*`, `/public/portal-invitations/*`, `/trial-requests*`, `/portal/favorites*`, `/portal/app-events`, `/portal/menu` and `/app-analytics`.
  - The email-verification routes in this spec file are served by `clients/router.py`, not engagement.
- [contract] The spec and the code disagree on the shape of some routes:
  - The spec has `POST /campaigns/{id}/test-send` (`openapi-programs.yaml:4633`); the code has `POST /campaigns/{id}/test` (`router.py:202`).
  - The spec has `GET|PUT /portal/communication-preferences` (`openapi-programs.yaml:~4196`); the code has `/portal/clients/{client_id}/communication-preferences` (`router.py:51,56`).
  - The spec has `POST /public/unsubscribe/{token}`; the code takes the token in the body at `POST /public/unsubscribe` (`router.py:457`), which matches README lines 27-29.
  - The spec names the device path parameter `device_id`; the code uses `device_registration_id` (`router.py:427`).
