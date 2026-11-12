# Changelog

User-visible changes to Courtmastr Facility, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The staff app's "What's new" page shows this file. Internal refactors, tests and docs are left out. Add a line
under `Unreleased` in the same change that makes the behaviour visible.

## [Unreleased]

### Added
- Collections: tag clients in collections, keep notes on their billing page, and see a collections report with what each owes.
- The portal refuses online buying and booking while an account is past due, when the billing setting is on; paying unlocks it.
- Billing notices and expiring-cards screens, and a staff daily digest of failed and upcoming autopay.
- Memberships can suspend automatically when an invoice stays past due (a billing setting, off by default) and resume when it is paid.
- Membership preferences for payment-method capture, online card saving and freeze resume billing now take effect; the portal can ask to save the card.
- Autopay at sale follows the plan, then the billing setting for the sales channel.
- An autopay membership bought online keeps the card it was paid with, saved with the payment so a processor timeout is still recovered safely.
- A pending bank debit pauses an invoice's past-due clock instead of restarting it.
- Phase 8 (platform, security and operations) is in progress; the entries below have landed.
- File storage in a cloud bucket with malware scanning and expiring download links.
- Background jobs retry automatically, and failed jobs land in a dead-letter list an operator can requeue.
- Old records (expired sessions, sign-in links, processed events) are purged on a schedule.
- A "What's new" link in the account menu shows this changelog.
- Two-step verification with an authenticator app and recovery codes, set up on your account's security page; owners choose who must use it, and an owner or admin can reset a lost authenticator.
- Sensitive actions ask you to confirm it is you (a code or your password) when you last did so more than 10 minutes ago.
- Staff can sign in with Google Workspace or Microsoft Entra ID once the owner adds the provider under Settings > Security; the first sign-in is confirmed by an emailed link.
- Settings > Plan and usage shows the account's plan, its limits and what is in use.
- Upload your logo for the account and for each location; it shows in the staff sidebar and the member portal.
- GDPR mode under Settings > Privacy & data: marketing needs express consent, old sign-in records are kept for less time, and privacy requests show their 30-day deadline.
- The owner can export all of the account's data as a zip of spreadsheets.
- A setup checklist on the dashboard ticks off each step as you complete it.
- Help & support: send a request, with a screenshot, to the support team and follow your requests.
- Container images, a reverse proxy with security headers, and backup and restore scripts for self-hosting.
- Settings > Import data: bring clients and households, memberships, opening balances and products over from a CSV file, with a check that imports nothing, a problem report and progress. Imports send no welcome messages, and in GDPR mode marketing consent is kept only with the date and source of consent.

### Changed
- Sign-in is harder to abuse: per-address and per-account rate limits, escalating lockouts, a common-password check, and a sign-in token that expires with the page.
- Staff can only sign in from the networks the owner lists, when a list is set; this now applies to owners and admins too.
- Staff are signed out after 30 minutes without activity (the owner can set 15 to 60) and after 12 hours in any case.
- Sending a campaign to every client needs its own permission.

### Fixed
- Signing in no longer flashes the sign-in page again before opening the page you asked for.
- Accessibility: form errors are announced to screen readers, date and time fields show a focus ring on every Tab stop, the member portal's skip link moves focus, checkboxes have larger targets, and the calendar and portal no longer scroll sideways on narrow screens.
- POS sales and payments make fewer database round trips.

## [MVP] - 2026-11-11

### Added
- **Platform:** tenants, locations, staff users, roles and permissions, magic-link and password sign-in, and an activity log.
- **Resources and scheduling:** courts, rooms and trainers with opening hours; a calendar with booking, recurring series, conflicts and holds.
- **Rentals and events:** rental types and rates, staff bookings, online checkout and shareable plans.
- **Clients and households:** client profiles, households, activity timeline, duplicate merge, consents and privacy requests.
- **Memberships and packages:** contracts with a billing schedule, renewals, credit packs and expiry reminders.
- **Programs and registration:** classes, camps and clinics with groups, registration, waitlists and self-service changes.
- **Waivers and documents:** templates, e-signing with evidence, emailed signing links and PDF copies.
- **Billing and payments:** invoices, payments, refunds, autopay, stored payment methods, a public pay page and Stripe Connect.
- **Point of sale:** register with barcode scan, returns, receipts, stock, cash drawers and equipment rental.
- **Check-in:** front-desk check-in and a kiosk mode.
- **Leagues and tournaments:** teams, schedules, brackets, standings and public league pages.
- **Staff time and pay:** time clock, shifts, pay rates and pay statements.
- **Assessments:** fitness assessments with trend history for each client.
- **Engagement:** email and push campaigns, segments, templates, reminders, automations and a preference centre.
- **Reporting:** a report centre with financial, membership, attendance, point-of-sale and time-clock reports.
- **Integrations:** API keys, signed webhooks and accounting exports.
- **Member app and portal:** a member web portal and an Expo mobile app with a digital membership card.
