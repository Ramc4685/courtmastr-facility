# Build Brief: FacilityHub — Sports & Fitness Facility Management Platform

## Role
You are the lead engineer on a greenfield, multi-tenant SaaS.
Target: feature parity with EZFacility (https://www.ezfacility.com).
I am a solution architect (20 yrs). Skip basics. Flag trade-offs.

## Clean-room rules (non-negotiable)
- Research ONLY public pages: marketing site, feature pages, industry pages,
  public help center (https://support.ezfacility.com/hc/en-us), public API page.
- Do NOT log in, sign up for demos, scrape behind auth, or bypass robots/ToS.
- Do NOT copy their code, text, UI layouts, icons, images, or brand.
- Extract WHAT features do. Design HOW ourselves.
- Respect 1–2 second delays between page fetches.

## Reverse-engineering scope
Allowed: black-box functional analysis of public material.
Infer features, workflows, entities, and rules from observed behavior.
Not allowed: decompiling their apps, probing their APIs or servers,
inspecting authenticated traffic, or extracting their source/assets.

## Coding discipline
Follow the Karpathy guidelines in CLAUDE.md (installed plugin):
think before coding, simplicity first, surgical changes, goal-driven.
They apply to every module. This brief wins on any conflict.

## Working rules
- Use plan mode before each phase. Stop at every GATE for my approval.
- One module per branch. Commit per module. Conventional commits.
- Config in YAML. Secrets via env only. Never commit secrets.
- Every module ships: migrations, seed data, tests, OpenAPI 3 docs.
- Keep CLAUDE.md lean (<120 lines). Update it as decisions land.
- If a requirement is ambiguous, list assumptions. Don't silently guess.

## Proposed stack (confirm at GATE 1)
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2
- DB: PostgreSQL 16 (row-level multi-tenancy via tenant_id + RLS)
- Jobs: Celery or Dramatiq + Redis (billing runs, reminders, reports)
- Web: React 18 + TypeScript + Tailwind (admin + member portal)
- Mobile: Expo / React Native (white-label config per tenant)
- Payments: Stripe Connect (tenants = connected accounts). No raw card data.
- Infra: Docker Compose locally. AWS (ECS Fargate, RDS, S3, EventBridge) later.
- Booking conflicts: enforce in DB with Postgres exclusion constraints
  on (resource_id, tstzrange). Not app-level checks only.

---

## PHASE 0 — Exhaustive Discovery (black-box, public sources only)
Goal: zero missed features. Completeness beats speed here.

### 0.1 Source map — crawl ALL of these
- Marketing site: every /features/*, /industries/*, /plans-pricing,
  /ez-api-services, /partners, /benefits pages. Use sitemap.xml first.
- Help center: https://support.ezfacility.com/hc/en-us — enumerate EVERY
  category, section, and article via sitemap. This is the richest source.
  Admin how-tos reveal screens, fields, settings, and edge cases.
- Release notes / product updates / blog posts announcing features.
- EZFacility YouTube channel: video titles + descriptions (+ transcripts
  if publicly available).
- Public review sites (Capterra, G2, Software Advice, GetApp): extract
  features mentioned AND complaints. Complaints = our differentiators.
- Public mobile app store listings (iOS + Android): feature bullets,
  screenshots descriptions, release notes.

### 0.2 Extraction rules
- Per source, record: URL, feature, sub-feature, settings/options,
  actors, workflows, fields mentioned, limits, integrations.
- Infer data entities from help articles (e.g., "membership freeze" →
  freeze entity with start/end/fee).
- Tag every item with evidence URL. No evidence = no claim.

### 0.3 Outputs
1. `docs/discovery/source-coverage.md` — every URL crawled, status,
   features found per URL. Report totals (pages, help articles).
2. `docs/discovery/feature-inventory.md` — module → feature →
   sub-feature → settings → user story → actor → priority.
3. `docs/discovery/workflows.md` — end-to-end flows (book court, sell
   membership, run league season, month-end billing, check-in).
4. `docs/discovery/entity-catalog.md` — inferred entities + fields.
5. `docs/discovery/parity-matrix.md` — feature | evidence URL |
   our approach | MVP? | complexity (S/M/L).
6. `docs/discovery/gaps-and-complaints.md` — review-site pain points.
7. `docs/discovery/unknowns.md` — anything unconfirmable publicly.

### 0.4 Completeness verification
- Launch a separate verifier subagent. It re-reads the help-center
  sitemap and checks every article maps to ≥1 inventory item.
- Unmapped articles → add or justify exclusion. Repeat until zero.
- Hardware/partner items (RFID, turnstiles, underwriting, app-store
  publishing): keep in inventory, mark "v2 / adapter only".

**GATE 0: stop. Show coverage stats. I review inventory before design.**

## PHASE 1 — Architecture
1. ADRs in `docs/adr/`: tenancy model, auth, payments, scheduling engine,
   recurring billing, mobile white-labeling, audit logging.
2. Domain model + ERD (Mermaid) in `docs/architecture/data-model.md`.
3. Bounded contexts and module boundaries (modular monolith first).
4. RBAC matrix: Owner, Admin, Front Desk, Coach/Trainer, Member, Parent/Guardian.
5. OpenAPI 3 skeleton for all P0 endpoints.
6. Security baseline: OWASP ASVS L2 targets, PII handling, minors' data,
   audit trail, rate limiting, tenant-isolation tests.
**GATE 1: stop. I approve stack, ADRs, and data model.**

## PHASE 2 — Build (in this order, one module at a time)
Each module: plan → schema → API → tests → web UI → seed → docs.

| # | Module | Key capabilities |
|---|--------|------------------|
| 1 | Platform core | Tenants, locations, users, RBAC, auth (OIDC + magic link), audit log |
| 2 | Resources & scheduling | Courts/fields/rooms, availability rules, drag-drop calendar, recurring bookings, blackout dates, conflict prevention |
| 3 | Rentals & events | Online rental booking, deposits, capacity, holds, cancellation policies |
| 4 | Members & households | Profiles, family/guardian links, photo ID, player passes, notes, tags |
| 5 | Memberships & packages | Plans, recurring dues, freezes, punch-cards, session credits, attendance tracking |
| 6 | Programs & registration | Classes, camps, clinics, multi-enrollment, waitlists, guest checkout, discount codes |
| 7 | Waivers | Digital waivers, versioning, e-signature, minor/guardian signing |
| 8 | Billing & payments | Invoices, Stripe card/ACH, autopay, dunning, refunds, credits, tax |
| 9 | POS & inventory | Products, SKUs, stock levels, equipment rental, receipts, cash drawer |
| 10 | Check-in & access | Front-desk check-in, QR member cards, kiosk mode. Hardware adapters = interface only |
| 11 | Leagues & tournaments | Seasons, divisions, teams, rosters, round-robin + bracket generation, standings, ref/court assignment |
| 12 | Staff | Shifts, time clock, payroll export, commissions, trainer availability |
| 13 | Engagement | Self-service portal, email + push campaigns, segments, reminders, video library, Zoom links |
| 14 | Fitness assessments | Configurable assessment templates, scores over time (AI scoring hook later) |
| 15 | Reporting | Financial, membership, attendance, payroll, POS. Export CSV/PDF/XLSX |
| 16 | Integrations | QuickBooks Online sync, webhooks, public REST API with API keys |
| 17 | Mobile app | Book, pay, digital membership card, push, schedules, per-tenant branding |

**GATE after modules 2, 8, 11, 17: stop for demo and review.**

## Definition of done (every module)
- Tenant-isolation test proves no cross-tenant reads/writes.
- ≥80% coverage on domain logic. Contract tests on API.
- Idempotent payment and webhook handlers.
- Time zones handled per location. Store UTC.
- Accessibility: WCAG 2.1 AA on all web screens.
- Docs updated: OpenAPI, CLAUDE.md, module README (short).

## Out of scope for v1
RFID/turnstile hardware, merchant underwriting, app-store submission,
native Smartwaiver clone (build own waivers), multi-currency.

## Start now
Begin PHASE 0. Show your crawl plan first, then execute.
