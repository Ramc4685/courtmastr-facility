# Phase 15: public API and integrations

Branch `claude/phase15-public-api-integrations`. Plan: `docs/planning/phase-15.md`. Module rules:
`backend/app/modules/integrations/README.md`. Migrations 1701 to 1705.

## Never run live

**QuickBooks Online and Zoom have never been called.** Both sit behind ports (`ports/accounting.py`,
`ports/video_meeting.py`) with a simulated adapter (`FakeQuickBooks`, `FakeVideo`) and a real one
(`QuickBooksOnline`, `ZoomVideo`). The real adapters are tested only on `httpx.MockTransport` stand-ins shaped
from the providers' public documentation, in the same contract tests as the fakes. The simulated adapters are
refused outside `dev` and `test` (`422 provider-not-configured` / `provider-unavailable`). Before a tenant
uses either for real: register a QuickBooks app and set its credentials in the environment, create a Zoom
Server-to-Server app, and run one connection end to end in a sandbox account of each.

## Features

| ID | State | Notes |
|---|---|---|
| INT-01 | partial | Generated reference with `x-api-key-scopes` per operation; tenant-wide ceiling across a tenant's keys; rate-limit tests. Keys hold only an allow-list of the documented resources' contexts (`KEY_CONTEXTS`). Web: API reference tab with a filter. Not built: OAuth 2.0 client-credentials (16-integrations). |
| INT-02, CLI-21, MEM-22, INT-04, PKG-16, INT-03, BIL-23, INT-06, LGE-27 | done | Key reach proven per resource (scope, refusal, location 404); money routes replay on `Idempotency-Key`. |
| INT-05, SSP-19 | done | Client bearer token reaches `/portal/*`; a key does not. |
| INT-08, SCH-19, STF-13, LGE-25 | done | Staff and team calendar feeds; address shown once, stored hashed; web panel. |
| SCH-20 | partial | Public schedule per location under the portal listing rule (hidden, unlisted, out-of-range and hidden-when-full sessions left out), public titles only, busy times of that location only. Web: settings tab with a copyable embed snippet. Not enabled: cross-site embedding at the proxy (the UI says so). |
| INT-07 | partial, simulated | OAuth per tenant or location, callback bound to the staff user and single-use state, realm verified against the token and claimed per tenant, released on disconnect; mappings, range sync as a chunked job (one committed day per chunk, the location's own dates, finished days only, request id per day), retry, signed webhook. Web: connect, disconnect, callback page, mappings dialog and a queued sync. Never run live. |
| INT-09, SSP-18, CLS-08 | partial, simulated | Pasted link or Zoom meeting per session, sealed; member join from 10 minutes before the start, marks attendance; disconnect marks meetings failed; a rescheduled session moves its Zoom meeting and a cancelled one deletes it, after commit. Web: staff meeting panel on the session; portal Join online button and Stop my calendar feed. Not built: `/webhooks/zoom`, `virtual_room` holds; enrolments carry no session times, so the button shows only for sessions seen before their start. |
| INT-13 | partial | Measurement id and linked domains, `GET /public/analytics-config`. The tag is not loaded: see below. |
| BIL-24 | parked | Legacy outsourced collections; billing's collections queue and CSV export cover hand-off. |
| PAY-19 | parked | Legacy magnetic swipe; raw card data never reaches us (ADR 0003). |

## Decisions and deviations from the contract

- The OAuth callback is a staff `POST /external-connections/oauth/callback`, not the contract's anonymous
  redirecting `GET`: the state is bound to the staff user who started it, works once and lasts 10 minutes.
- The member join is `POST /portal/enrollments/{id}/join` answering `{join_url, passcode}`, not a `GET 302`,
  because it writes attendance.
- Video-meeting paths name `{schedule_session_id}`; `VideoMeeting.status` is `scheduled` or `failed` only.
- Zoom uses each tenant's Server-to-Server app, not ADR 0012 section 5's user OAuth; there is no browser step.
- QuickBooks app credentials come from the environment (shortcut, as core settings were frozen this phase).
- **INT-13 needs an owner decision.** ADR 0012 section 6 expects the GA4 tag on public and portal pages after
  consent; security-baseline V10 and section 14 forbid third-party analytics in web and mobile (the portal
  serves minors), and the proxy CSP is `script-src 'self'`. The consent-gated loader was written and then
  removed. To ship it: amend the baseline for public registration pages, exclude minors' sessions, and allow
  the tag hosts in `infra/proxy/Caddyfile`.

## Read functions added to other modules

`platform.service.client_identity_is_active` (member feeds) and `programs.selfservice.own_place` (the join).

## Handover

- **Feed tokens and the 405 log line (core).** The calendar-feed route redacts its token inside the handler, so a
  request the router refuses before any handler runs (a 405 for a method the route does not declare) is logged
  by `core/api.py` with the raw path. The route now declares GET, HEAD, OPTIONS and PROPFIND, which covers what
  calendar apps send; the lasting fix is to redact `/public/calendar-feeds/<token>` in the core access-log
  middleware itself. Core was frozen this phase.
