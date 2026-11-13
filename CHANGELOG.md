# Changelog

User-visible changes to Courtmastr Facility, newest first. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The staff app's "What's new" page shows this file. Internal refactors, tests and docs are left out. Add a line
under `Unreleased` in the same change that makes the behaviour visible.

## [Unreleased]

### Added
- Calendar feeds: subscribe to your bookings and shifts, or a team's games, from any calendar app; the address is shown once.
- An embeddable public schedule per location showing published sessions and free seats, never names.
- QuickBooks Online connection with account mappings and a sync over a date range (simulated until a QuickBooks app is registered).
- Online sessions: attach a meeting link or a Zoom meeting through your own Zoom app; members join from 10 minutes before the start and are marked attended.
- The Integrations screen gains Connections and Calendar feeds tabs.
- The API reference lists the key scopes each operation needs.
- Connections: edit an accounting connection's account and class mappings, and queue a QuickBooks sync.
- Staff can add, replace or remove a session's online meeting (a pasted link or a Zoom meeting) from the session panel.
- Portal: a Join online button on bookings from 10 minutes before the start, and a calendar card to get or stop your calendar feed.
- A Public schedule tab to publish a location's schedule and copy an embed snippet (other sites cannot load it until the proxy allows it).

### Security
- The public schedule leaves out hidden, unlisted and out-of-range sessions, and busy times show only that location's.
- Members can revoke their calendar feed, and making a new one stops the old address; feeds of a suspended account stop.
- QuickBooks sync posts each finished day of the location once, even when a run is retried.
- API keys can hold only the documented API resources' permissions.
- Online sessions: moving a session moves its Zoom meeting, and cancelling it deletes the meeting.
- Secrets shown once (padlock combinations, API keys, webhook signing secrets, kiosk pairing codes, payment onboarding links) are no longer kept with retried requests; repeating such a request returns an error instead of the secret.
- A payer locked out of the portal for a past-due balance can no longer buy a rental plan or pay for an event form registration there.

### Added
- Leagues: a public league site with your branding, facility info, news, photos, sponsors, links and a class listing; competition filters with a shareable link and embed code; public teams and brackets, with player names shown only where you turn them on.
- Leagues: a TV board per location showing today's games and scores, refreshing on its own.
- Leagues: members post classifieds and pickup games from the portal; staff approve them first, they expire after 30 days, and replies go through the club without showing anyone's address.
- Leagues: the schedule generator runs in the background over several weekly windows, with all four bye modes and live progress.
- Leagues: double elimination with a reset game, three games guaranteed, and pool-to-bracket crossover.
- Leagues: league venues, per-team scheduling preferences, ladders, player stat tables with formula stats, and game card PDFs.
- Leagues: per-competition league staff and a scorekeeper screen that shows only the scorekeeper's games.
- Leagues: publish a program as a league or tournament; captains manage their roster in the portal ("My teams"); split a team fee across players.
- Lockers: set up locker rooms (create lockers in bulk), priced locker terms and padlocks, then rent, renew and clear lockers from the Lockers board. Padlock combinations are stored encrypted and shown only to staff allowed to reveal them; every reveal is logged.
- Rental plans can renew automatically and charge the saved card, be sold to members only, and be shared with related clients; members can buy a rental plan and stop its renewal in the portal.
- Reports: export to Excel or PDF as well as CSV, print the results, filter by category, type, trainer or staff, chart revenue against the goal, and email saved reports on a schedule; the home page shows at-a-glance tiles.
- Reports: receivables by instalment due date, unapplied payments, income and balances, underpaid items, accrued and unused session value, package pipeline and sales, and membership revenue, deferred revenue, actions, attrition, expiry and referrals.
- Reports: low-usage check-ins, check-in summary, client activity items, contacts and demographics with export, referral sources, trial conversions, retention, non-training clients, group rosters and waitlists, campaign history, POS returns, inventory and re-order, equipment, rental plan sales, and POS sales by coupon with buying price and margin.
- Reports: time entries, payroll and commission statements, trainer performance, assessment history (with a trend chart on the client's assessments) and summary, league venues, officials and demographics, app installs, resource utilization, peak times, class popularity, check-in details and new memberships.
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
- Event forms: build a sign-up page for an event with its own questions, prices, stock limits, sign-up window, capacity and wait list; anyone can sign up for a free event without an account, and priced events take payment in the member portal.
- Event form registrations: look up, edit, cancel (with refunds of live charges), promote from the wait list, export to CSV and see summaries by registration, revenue, demographics and answers.
- Programs can be filed under seasons, sports and age divisions, filtered by them, and saved as personal views with your own choice of columns.
- Program tools: copy a program, create a repeating series from it, export its members to CSV, and move registrations to another program in one step.
- Event forms accept one live sign-up per email address without an account, limit how often anyone can sign up, and remove the contact details of anonymous sign-ups a year after the event.
- Registration defaults per location that new programs start with.

### Changed
- Sign-in is harder to abuse: per-address and per-account rate limits, escalating lockouts, a common-password check, and a sign-in token that expires with the page.
- Staff can only sign in from the networks the owner lists, when a list is set; this now applies to owners and admins too.
- Staff are signed out after 30 minutes without activity (the owner can set 15 to 60) and after 12 hours in any case.
- Sending a campaign to every client needs its own permission.

### Fixed
- Reports: receivables and open invoices no longer fail as "too large" on a tenant with many settled invoices; expiring memberships at one location are no longer hidden by a renewal at another; package session value no longer loses a cent to rounding (100.00 over three sessions reports 100.00).
- Reports: a dashboard tile with too much data shows as unavailable instead of disappearing; a failing report schedule no longer stops the others, a schedule whose owner lost access is switched off, and an admin can see and delete anyone's schedule.
- Erasing a client's data also clears stored report results and export files.
- Reports with a relative period over locations in different time zones use each location's own days; a late-evening run no longer drops the start of the day at an eastern location.
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
