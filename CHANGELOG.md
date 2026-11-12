# Changelog

User-visible changes to Courtmastr Facility, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The staff app's "What's new" page shows this file. Internal refactors, tests and docs are left out. Add a line
under `Unreleased` in the same change that makes the behaviour visible.

## [Unreleased]

### Added
- Phase 8 (platform, security and operations) is in progress; the entries below have landed.
- File storage in a cloud bucket with malware scanning and expiring download links.
- Background jobs retry automatically, and failed jobs land in a dead-letter list an operator can requeue.
- Old records (expired sessions, sign-in links, processed events) are purged on a schedule.
- A "What's new" link in the account menu shows this changelog.
- Container images, a reverse proxy with security headers, and backup and restore scripts for self-hosting.
- Settings > Import data: bring clients and households, memberships, opening balances and products over from a CSV file, with a check that imports nothing, a problem report and progress.

### Changed
- Sign-in is harder to abuse: per-address and per-account rate limits, escalating lockouts, a common-password check, and a sign-in token that expires with the page.
- Staff can only sign in from the networks the owner lists, when a list is set.

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
