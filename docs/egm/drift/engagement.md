## backend/app/modules/engagement/README.md

Re-run 2026-11-13 on claude/fix-browser-dates. Checked against `backend/app/modules/engagement/`, `docs/api/openapi-programs.yaml`, `mobile/src/adapters/api.ts` and `web/src/app/App.tsx`. Counts: stale-not-built 0, missing 1, contract 5, undocumented 11, wording 8. Dropped since the last run: the API-key claim at README:71 now holds (`integrations/service.py:68-78` `KEY_PERMISSIONS` lists `engagement.campaign.create`).

Since the last report the README now covers inbox expiry, built-in segments and system templates, `POST /segments/preview`, the unused `sms_campaign.send` and `inbox.reply` keys, the three messaging events, `getPortalVideo`, suppression errors and the correct mobile adapter path. Those items are closed and not repeated. What still differs:

### [missing]

- [missing] README:120 lists `locale?` in the `POST /portal/devices` body. `schemas.py:495` accepts it, but `DeviceRegistration` has no `locale` column (`models.py:385-410`) and `register_device` never reads it, so the value is dropped.

### [contract]

- [contract] `POST /public/portal-signups` and `/confirm` (README:140-146; `router.py` public routes) appear in no `docs/api/*.yaml` (grep for `portal-signups` finds nothing). Every other Phase 11 route is in the spec.
- [contract] README:132-136 "Not built" lists none of the spec operations tagged `engagement` that no route serves: `POST /webhooks/email/{provider}` (`openapi-programs.yaml:5629`, also contradicts README:92-94 only by omission), `/campaigns/{id}/resume` (:4704), `/unschedule` (:5661), `/copy`, `/audience-preview`, `/media-assets*` (:5681,5696), `/news-stories*` and `/public/news-stories` (:5744-5779). The router mounts none of them (`router.py:164-233`).
- [contract] Route shapes differ from the spec: `POST /campaigns/{id}/test-send` (`openapi-programs.yaml:4639`) vs `POST /campaigns/{id}/test` (`router.py:217`); `/portal/communication-preferences` (:4202) vs `/portal/clients/{client_id}/communication-preferences` (`router.py:66,71`, README:125).
- [contract] README:34 says suppressions are "`T`, admin only". Only create and release are (`engagement.suppression.manage`, `permissions.py:32`; `router.py:266,271`). `GET /suppressions` needs `engagement.campaign.read` (`router.py:261-263`, `service.py:1107-1108`), so any manager can list them.
- [contract] README:58-59 says the context emits `engagement.consent.changed`. It is published only for an unsubscribe-link change and the public preference centre (`service.py:1187,1228`). Staff edits, portal edits, imports and the GDPR-off opt-outs record consent events but publish nothing.

### [undocumented]

- [undocumented] `engagement.app_config.updated` (`events.py:36-40`; `service.py:1942`) is not in the events paragraph (README:58-59). `engagement.portal_signup.confirmed` appears only as the class name `PortalSignupConfirmed` (README:144).
- [undocumented] Cross-context hooks from Phase 11: `service.present_schedule` registered with `programs.selfservice.register_listing_presenter` (`service.py:1967,1989`), `platform.branding.public_url_for_key` for directory icons (`service.py:1984`) and `core.db.platform.search_app_directory`, the one cross-tenant read (`service.py:1985`). README:186-187 says flags apply "inside `listPortalSessionListings`" without naming the hook.
- [undocumented] The audit action `engagement.app_inquiry.receive` (`content.py:32,259`) is a label only, not a registered permission. README:228-231 does not say so.
- [undocumented] `POST /campaigns/{id}/test` and its `campaign.edit` gate (`router.py:217`), and the campaign lifecycle routes cancel, recall, stats, recipients and delete (`router.py:187-232`), are not described. README:31-34 and 70 cover only send, schedule and edit.
- [undocumented] Campaign validation and skips: https-only links, 180-character push limit (`push-too-long`, `service.py:536-537`), and a `duplicate` skip row (`service.py:936,968`).
- [undocumented] An announcement writes inbox items with no `is_subscribed` check (`service.py:943-953`); only the push automation checks (`service.py:1457`, README:53-54). README does not state the announcement behaviour.
- [undocumented] Staff routes `GET|PUT /clients/{client_id}/communication-preferences` (`router.py:52,58`), with required `basis` and `note` (`schemas.py:39-42`). README:125 names only the portal route.
- [undocumented] `handlers.py` also consumes `clients.client.created`, `memberships.contract.activated`, `memberships.contract.renewed`, `scheduling.booking.rescheduled` and `billing.payment.failed` (`handlers.py:29,75,83,90,95`). README:12 lists bookings, enrollments, waitlist and declined payments, and the import skip appears only at README:113-114. The `TRIGGERS` catalogue (`service.py:1491`) is cited but not listed.
- [undocumented] Portal settings: slug and `portal-slug-taken`, tenant-wide `PUT /locations/{id}/portal-settings` fields, `GET /public/portal-config` payload (`service.py:1707-1760,1813`). README:150-168 covers menu, redirects and terms but not the slug rule.
- [undocumented] Templates have a `preset` origin that is read-only (`template-read-only`), a template in use is retired instead of deleted, and a segment in use cannot be deleted (`segment-in-use`) (`router.py:101,107,148`). README:60-62 covers built-in segments and system templates only.
- [undocumented] `automation_rule.is_system` guards (`automation-system`, built-in rules change only `is_enabled`, `delay_minutes`, `message_template_id`) exist at `service.py:1552,1565`, but no code creates a system rule. README:99-101 says there is no built-in rule and does not mention the guard.

### [wording]

- [wording] README:9 says `models.py` has "15 tables". It defines 22 (`models.py` `__tablename__`): the list lacks `portal_signup` (:573), `app_config` (:624), `app_content` (:657), `location_contact` (:694), `app_inquiry` (:729), `client_favorite` (:770), `app_usage_day` (:791). README:3-5 (scope) omits the member app.
- [wording] The file table (README:7-16) has no rows for `signup.py`, `content.py`, `member.py`, `domain/app_config.py`, `events.py`, `permissions.py`, `schemas.py`. README:14 says `subject.py` handles four tables; it registers merge and erasure handlers for favourites, inquiries, sign-ups and messaging (`subject.py:153-170`) plus retention purges for usage, sign-ups, trial inquiries and bodies.
- [wording] README:16 lists staff screens as campaigns, templates and segments, automations and reminders, settings. The web feature also has `AppConfigPage.tsx`, `MemberContentPage.tsx`, `MessagesPages.tsx`, `PortalPage.tsx` and `UnsubscribePage.tsx` (`App.tsx:17-26`).
- [wording] README:235-237 says the parent `/engagement` route "still requires `engagement.campaign.read`". `App.tsx:229` now accepts `campaign.read`, `portal_settings.manage` or any member content key, and the content pages sit under the `portal` route gated by `portal_settings.manage` or `app_content.manage` (`App.tsx:238`). Only the index and campaign pages need `campaign.read`.
- [wording] README:43-45 names `express_written` or `express_verbal` as the express bases. Plain `express` is also accepted and is the default (`schemas.py:42`), and it is what the portal and the public pages record (`service.py:1183,1227`).
- [wording] README:20-23 "Every email goes through `service._deliver`". Campaign duplicate-skip rows are written directly (`service.py:968`) and inbox items bypass it (`service.py:953,1463`); both are still logged, but not through `_deliver`.
- [wording] `router.py:343` docstring says automation rules include "the built-in waitlist promotion notice"; README:99-101 says there is no built-in rule, and nothing sets `is_system` (see above).
- [wording] `router.py:439` docstring says re-registering a token "moves it to this login"; README:96-98 and the code revoke the other login's row and add a new one (`service.py:1296-1303`).
