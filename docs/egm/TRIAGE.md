# Drift backlog triage

Triage of `DRIFT_BACKLOG.md` (178 items, written 2026-11-12) against `main` at `321bb84`, done 2026-11-13.
Read-only pass: claims were checked by grep or by reading the cited lines; no tests were run. Line numbers
below are current `main` (several routers moved after the Phase 14 batch 1 merge). Paths are relative to
`backend/app/modules/` unless they start with `docs/`, `web/`, `mobile/`, `config/` or `backend/`.

Verification depth: every CODE-DEFECT, CONTRACT, DEAD, ALREADY-RESOLVED and OWNER-DECISION row was checked
in code. DOCS-ONLY rows were checked that the README still says it (grep on the README) or that the code
fact holds; rows marked `(nc)` rest on the drift report alone, because they are pure additions to a README
where being wrong costs nothing.

## Counts

| Bucket | Items |
|---|---|
| CODE-DEFECT | 6 (1 high, 2 medium, 3 low) |
| CONTRACT | 12 (7 change the yaml, 5 need code, all 5 planned features) |
| DOCS-ONLY | 142 |
| DEAD | 11 (1 delete, 10 keep) |
| ALREADY-RESOLVED | 4 |
| OWNER-DECISION | 3 (2 known, 1 new) plus 2 new questions raised inside other rows |

## Code defects, worst first

| Id | Sev | Where | What is wrong | Smallest fix |
|---|---|---|---|---|
| platform-4a | high | `platform/service.py:60-70`, `platform/schemas.py:175` | `PATCH /tenant` accepts `currency` and writes it with no check. The comment says the guard "arrives with the billing context"; billing shipped. Changing it re-labels every `_minor` amount in the ledger. | Drop `currency` from `TenantUpdate` (set at provisioning only). Platform may not import billing, so a "has charges" check would need a registered hook; removing the field is smaller and safe. One test: PATCH with `currency` is 422. |
| platform-4b | medium | `platform/service.py:265-283` | `archive_location` has no `location-has-future-bookings` guard (comment: "once the scheduling context exists"; it exists). A location with live bookings can be archived. | Platform keeps a `register_location_archive_check` hook (same shape as `register_client_ids_resolver`, `service.py:486`); scheduling registers a "future bookings at this location" read; raise `Conflict(code="location-has-future-bookings")`. One test. |
| documents-1 | medium | `rentals/service.py:1576` (`sell_plan`), `portal_buy_plan`; `documents/schemas.py:23` | Documents accepts a `rental_plan` binding, and staff can bind a waiver to a rental plan, but rentals never calls `requirements_for` / `ensure_pending` / `consume` (no `documents` reference in `rentals/*.py`). The waiver is silently not enforced. | Call the three functions in the plan sale path the way `packages/service.py:573-575,655,699` does. If the owner wants no gate on rentals, remove `rental_plan` from the binding kinds instead (see new question Q2). |
| rentals-9 | medium | `rentals/service.py:1299-1303` | `create_portal_rental` refuses every portal booking of a rental type whose eligibility is not `everyone`, members included, and tells the client "memberships arrive with build module 5". `_is_member` already exists (`:1498-1501`) and plans use it (`:1523`). | `if rtype.eligibility != "everyone" and not _is_member(session, client_id, today)`, message "Online booking of this rental is for members." One test each way. |
| programs-1 | low | `programs/selfservice.py:23,59,80,87`; `programs/router.py:101-107` | Stand-in keys outlived their exit condition. Booking policies are gated by `programs.registration_config.manage` (admin, manager, league_admin) though `engagement.portal_settings.manage` (admin, manager) exists, so league admins can edit portal booking policy. The roster message uses `scheduling.enrollment.create`; `engagement.message.send_direct` exists with the same roles plus league_admin. Suppressions still apply (the port goes through `engagement.install_notifier`, `bootstrap.py:55`). | Swap both constants to the engagement keys; update `rbac-matrix.md` rows and the two README lines (47-48). Programs may not import engagement, but a key is a string. |
| billing-11 | low | `billing/documents.py:694-702` | Bulk invoicing by `location_id` loads every uninvoiced charge at the location in the request; only `charge_ids` is capped (`schemas.py:587`, 1000). Unbounded synchronous work. | Apply the same 1000 cap to the location mode (fetch 1001, refuse with 422 and a hint to narrow), or document it; cap is the smaller safe change. |
| integrations-7 | low | `integrations/service.py:694-704` | `_ledger_rows` reads billing's `ledger_entry` with raw SQL (declared shortcut). It bypasses billing's interface; the README's reason ("until module 8") is stale. | Add an internal `billing.service.ledger_day_totals(session, location_id, on)` and call it. Fits Phase 15 (INT-07); until then fix the README reason only. |

`platform-4a` and `platform-4b` are one backlog item (platform 4), counted once.

## Fix log (branch `claude/egm-drift-fixes-8810b9`)

| Item | Commit | Note |
|---|---|---|
| platform-4a, platform-4b (backlog platform 4) | bbec55d | `currency` dropped from `TenantUpdate`; `register_location_archive_check` + scheduling's `location-has-future-bookings` |
| rentals-9 | c3a42e9 | members pass `_is_member`; assumption `active_members` = `paid_up_members` in the rentals README |
| programs-1, engagement-4 | 7168997 | engagement keys swapped in; `getPortalVideo` served |
| billing-11, integrations-7 | 5664dd3 | location mode capped at 1000; `billing.service.ledger_day_totals` |
| imports-1, imports-2, integrations-2, scheduling-2, packages-9, access-3, access-4 | 96dbe58 | yaml synced; `access.checkin.delete` and `deleteCheckIn` deleted. integrations-2 and access-4 keep their README halves for the docs batch |
| documents-1 | not fixed, handed back | the import contract forbids `rentals` -> `documents` (`backend/pyproject.toml`); needs an `ignore_imports` line or dropping `rental_plan` from the binding kinds (Q2) |
| Docs batch (package 6) | one `docs(<module>)` commit per module on `claude/egm-drift-docs-8810b9` | DOCS rows and README halves of CONTRACT and DEAD rows, plus the stale comments in `documents/service.py`, `integrations/jobs.py`, `memberships/models.py`, `rentals/schemas.py` and `rentals/__init__.py`; backlog lines end in "Docs batch." |

## New owner questions

- **Q1 (pos-3).** `/pos-reports/*` is gated by `pos.sale.read` (`pos/router.py:502-525`) while the report centre's
  `pos_sales` report needs `reporting.pos.run` (admin, manager). Front desk can read POS sales totals by one
  road and not the other. Pick the key for `/pos-reports`.
- **Q2 (documents-1).** Should a waiver bound to a rental plan block the sale? Yes means the fix above; no means
  drop the binding kind.
- **Q3 (access-4).** Kiosk session attendance, eligible sessions and kiosk package purchase are in the contract
  but in no README "not built" list and no phase. Build (Phase 11) or drop from the contract?
- **Q4 (dead keys with no phase).** `platform.client_session.impersonate`, `platform.tenant.transfer_ownership`,
  `platform.tenant.close`, `leagues.discipline.manage`, `billing.dispute.manage`: in `rbac-matrix.md`, in no
  phase list. Kept for now; schedule or strike from the matrix.

Already known and unchanged: catalog-item read permission (billing-1), "only platform reads platform models"
(platform-1), location scoping in billing collections (not a backlog item).

## Per-item table

Buckets: CODE, CONTRACT, DOCS, DEAD, RESOLVED, OWNER.

### access (14)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | `access/desk.py:360` sets `photo_url`; README:142-144 still says always null | Rewrite the photo-slot bullet |
| 2 | DOCS | `access/models.py:32-35`; README:11 says `admitted / denied / see_staff` | README: `granted / denied / granted_override` |
| 3 | DEAD | `access/permissions.py:20` (`checkin.delete`, no other reference); `docs/api/openapi-money.yaml:4052` `deleteCheckIn`; README:112 records "never deleted" | Delete the key, its matrix row and the contract operation |
| 4 | CONTRACT | `access/router.py:204` `GET /membership-type-access` not in yaml; yaml `:4383`, `:4521`, `:4715`, `:4731` not served | Yaml: add `listMembershipTypeAccess`. Keep wallet pass (CHK-13, Phase 11). Kiosk attendance, eligible sessions, kiosk package purchase: Q3; until answered list them under "not built" in the README |
| 5 | DOCS | `access/models.py:38-44`; README:13 | List the six credential kinds |
| 6 | DOCS | `access/service.py:244-246,727`; README:58 | Say "from 5 h before to 3 h after the start" style, per path |
| 7 | DOCS | `access/events.py:35-50` | Fix the "only the access-mode change publishes" sentence |
| 8 | DOCS | `access/events.py:16-30` | Add the four check-in events |
| 9 | DEAD | `access/permissions.py:28-29`, no route | Keep (CHK-16 door hardware, Phase 15); name them in the deferred note |
| 10 | DOCS | `access/models.py:17-29` (nc) | Add channels `pos`, `door`, `api` and `client_record` |
| 11 | DOCS | `access/subject.py:4,65` (nc) | Add "erasure drops the access mode" |
| 12 | DOCS | `access/service.py:359-362` (nc) | Add the `check_in_station_id` filter to README and the router docstring |
| 13 | DOCS | README:27 (nc) | Add `exit_pin_failure_count` to migration 1022 |
| 14 | DOCS | `access/subject.py:39-50` (nc) | Add the export handler |

### assessments (7)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:52 "mobile screens"; `mobile/src/app/progress.tsx` exists | Drop "mobile screens" from Not built |
| 2 | DOCS | `assessments/service.py:243-244`; README:37 | Say the rule is API-only and null rows need the tenant-wide key |
| 3 | DEAD | `assessments/permissions.py:17`, no user | Keep (FIT-05 `shareAssessmentResult`, in the matrix); add to the README key list as unused |
| 4 | DOCS | `assessments/service.py:242-246` | Mention the read gate before the `L` delete key |
| 5 | DOCS | `assessments/subject.py:19-39` (nc) | Add the export handler |
| 6 | DOCS | `assessments/service.py:192,255-266`; README:16 | Split the filter list per operation |
| 7 | DOCS | `web/src/features/assessments/` | Add a screens pointer |

### billing (16)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | OWNER | `billing/router.py:167,325,336` (`Staff = require()`), create/update gated | Known decision: catalog-item list and get permission |
| 2 | DOCS | README:262; `platform/files.py:178` exists | Reword: the signed link exists; billing still sends portal links by choice |
| 3 | DOCS | `billing/events.py` (nc) | Add `statement_batch.completed`, `catalog_item_sale.renewed/.ended/.sold` |
| 4 | DOCS | README:51 signature lacks `tax_ids` | Add the parameter |
| 5 | DOCS | README:65-70 (nc) | Add `location_ids` to `refund_credit` |
| 6 | DOCS | (nc) | Add `audit_changes`, `internal_tender` to `take_payment` |
| 7 | DOCS | README:7-20 | Add `catalog.py`, `checkout.py`, `collections.py`, `events.py`, `subject.py`, `permissions.py`, `schemas.py` rows |
| 8 | DOCS | `billing/domain/recurrence.py` (nc) | Add to the pure-logic list |
| 9 | DOCS | README:9 | Add dispute, statement batch, catalog item, provider customer tables |
| 10 | DOCS | `billing/router.py:1003-1011`: 404 unless the fake processor is registered, which settings refuse in production | Document the portal receipts routes and the dev-only fake-processor route. Not a defect |
| 11 | CODE | `billing/documents.py:694-702`; `billing/schemas.py:587` | Low. Cap the `location_id` mode; see defects table |
| 12 | DOCS | README:166 fragment still present | Repair the sentence |
| 13 | DOCS | no drift shown (`billing/service.py` only prefixes `import:`) | No change; optionally point at imports for the key recipe |
| 14 | DOCS | README:169 | Move `tax_ids_by_code` to the POS import paragraph |
| 15 | DOCS | `billing/statements.py:33-47` (nc) | Add `is_open_only`, `client_filter`, `date_basis` |
| 16 | DEAD | `billing/permissions.py:54`, no user | Keep (in the matrix; disputes arrive by webhook, staff route unbuilt); Q4 |

### clients (10)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:45 vs `backend/app/scheduler.py:25` | Drop "a scheduler for task reminders" from not built |
| 2 | DOCS | README:30 `MONEY`; `clients/tests/test_activity_merge.py:20` has only `MERGE_ALLOWED` | Rewrite: billing registers its handlers |
| 3 | DOCS | README:45; `access/router.py:285` | "Portal member card: API and mobile built (access), no web portal page" |
| 4 | DOCS | README:45 | "Derived system alerts live in memberships" |
| 5 | DOCS | README:18; `clients/service.py:1033` (nc) | `is_minor` takes the age explicitly; the default lives in households |
| 6 | DOCS | README:22 | Add `"profile"` |
| 7 | DOCS | (nc) | Add the seven internal functions other contexts call |
| 8 | DOCS | README:4 | Add migrations 0002 and 1091 |
| 9 | DOCS | `clients/models.py:312,392,618` (nc) | Add the three tables; fix the photo-storage sentence |
| 10 | DOCS | `clients/events.py:23-38` (nc) | Add `ClientDisabled`, `ClientMerged`, `RelationshipChanged` |

### documents (8)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | CODE | no `documents` reference in `rentals/*.py`; `documents/schemas.py:23` accepts `rental_plan`; README:25 claims rentals calls it | Medium. Wire the gate in rentals' plan sale (or drop the binding kind, Q2) |
| 2 | DOCS | `backend/app/core/api.py:237-242`; README:53 | List the four exempt upload paths |
| 3 | DOCS | README:46 | "Streams by choice; the S3 adapter can sign" |
| 4 | DOCS | `platform/files.py` scanner (nc) | Add malware scanning |
| 5 | DOCS | `memberships/service.py` uses `settings_row` (nc) | Add to the internal interface |
| 6 | DOCS | `documents/events.py:15-28` (nc) | Add the four events and the file row |
| 7 | DEAD | `documents/permissions.py:19`, no user | Keep (DOC-07, Phase 13); note it in the README |
| 8 | DOCS | `documents/service.py:1259` docstring "Nothing schedules it yet"; `backend/app/scheduler.py:22` does | Fix the code docstring |

### engagement (10)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:112 `mobile/src/api/api.ts`; real file `mobile/src/adapters/api.ts` | Fix the path |
| 2 | DOCS | README:104 | Split "used by the app today" from "reserved for the app" |
| 3 | DOCS | README:112-114 (nc) | Complete the list of adapter routes |
| 4 | CONTRACT | yaml `docs/api/openapi-programs.yaml:5446` `getPortalVideo`; `engagement/service.py:1819` exists; `engagement/router.py:433` serves the list only | Code: add `GET /portal/videos/{video_id}` (three lines; the service function is otherwise dead) |
| 5 | DOCS | `engagement/events.py:9-28` (nc) | Add the three events |
| 6 | DOCS | `engagement/service.py:351` (nc) | Add the 30-day inbox expiry |
| 7 | DEAD | `engagement/permissions.py:19,22`, no user | Keep (SMS MKT-15/MKT-23, Phase 15); add "reply to client messages" to Not built |
| 8 | DOCS | `engagement/service.py:286-340` (nc) | Say where the second handler pair lives |
| 9 | DOCS | (nc) | Add built-in segments, system templates, `POST /segments/preview` |
| 10 | DOCS | `engagement/service.py:1118-1128` (nc) | Add the two 409 codes |

### imports (7)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | CONTRACT | served `imports/router.py:67,78,85,93`; yaml `docs/api/openapi-core.yaml:1544,1559` | Yaml: replace `/commit` and `/rows` with `/source`, `/dry-runs`, `/commits`, `/error-report`, and add `GET /import-templates`. The code is the tested Phase 8 behaviour |
| 2 | CONTRACT | yaml `:1574` `cancelImportJob`; README:172 defers it; no route | Yaml: remove the operation (re-add when cancel is built) |
| 3 | DOCS | `imports/router.py:41,46,52` | Add the three routes to the flow |
| 4 | DOCS | (nc) | Add `nothing-to-import` |
| 5 | DOCS | (nc) | Add upload types and error codes |
| 6 | DOCS | (nc) | Add `already-exists` |
| 7 | DOCS | README:113 | `clients.service._create` |

### integrations (7)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:17 vs README:65; `integrations/jobs.py:21` docstring also stale | Fix both: the sweep runs every minute |
| 2 | CONTRACT | served, not in yaml: `runAccountingExport`, `listIntegrationAdapters`, `listAdapterCommands` (`backend/openapi.json`) | Yaml: add the three operations; README: "22 of 38" |
| 3 | CONTRACT | in yaml, not served: `getExternalConnection`, `updateExternalConnection`, `runSync`, `retryAccountingExport`, `receiveQuickBooksEvents`, `receiveZoomEvents` | Code, later: Phase 15 (INT-07, INT-09). Now: add them to the README Not built list |
| 4 | DOCS | `backend/app/core/settings.py` (nc) | "dev and test" |
| 5 | DEAD | `integrations/permissions.py:19`, no user | Keep (calendar feeds, Phase 15); list the module's keys in the README |
| 6 | DOCS | `integrations/events.py:9-15` (nc) | Add the file row and the `webhook = false` note |
| 7 | CODE | `integrations/service.py:694-704` | Low. Billing internal read; see defects table. README reason is stale either way |

### leagues (5)

README was rewritten in Phase 14; it still has no events, data-subject or discipline section.

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | `leagues/service.py:1385` | Add discipline caps to the standings paragraph |
| 2 | DEAD | `leagues/permissions.py:24`, no user even after league depth | Keep (in the matrix); Q4; list under not built |
| 3 | DOCS | `leagues/events.py` (nc) | Add the published events |
| 4 | DOCS | `leagues/subject.py` (nc) | Add merge and erasure handlers |
| 5 | DOCS | README:51,59 still cite `tests/test_location_scope.py`, `tests/test_portal_schemas.py` | Write `backend/tests/...` |

### memberships (11)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:80; `memberships/models.py:3-5` docstring also stale | Fix both: `catalog_item_id` exists on three tables |
| 2 | DOCS | README:80 | "Tables exist; columns deliberately not added" |
| 3 | DOCS | README:54; `access/models.py` `IdCardTemplate` | Member card: built in access |
| 4 | DOCS | README:54; `reporting/views.py` | MEM-21: `rpt_membership_contract` exists |
| 5 | DOCS | README:54 | MEM-22: point at integrations' API keys, scope unverified |
| 6 | DOCS | README:49 | "Coupons: portal sale only, not stored on the contract" |
| 7 | RESOLVED | `memberships/service.py:478,2019` read `online_card_save_mode`; README:67 documents it | None |
| 8 | DOCS | `access/service.py:111`, `staff/service.py:1443` | Add `get_contract`, `seller_periods`, `run_daily`, `import_contract` |
| 9 | DOCS | (nc) | Add merge and erasure handlers and the overlap precheck |
| 10 | DOCS | `memberships/events.py:16-51` (nc) | Add the six events |
| 11 | DOCS | `memberships/service.py:74` (nc) | Add `already-renewed` |

### packages (9)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:4 "Backend only" | Remove |
| 2 | DOCS | README:55 | Remove the stale assumption |
| 3 | DOCS | README:35 | Add the six other events |
| 4 | DOCS | (nc) | Add `session_credit_facts`, `sales_by_seller` |
| 5 | DOCS | `packages/handlers.py:38-46` (nc) | Name the two events and the `cancel_packages` condition |
| 6 | DOCS | (nc) | Add file rows and the key list |
| 7 | DOCS | (nc) | Add the two portal auto-renew opt-outs |
| 8 | CONTRACT | yaml `docs/api/openapi-people.yaml` `portalQuoteClientPackage`; not in `backend/openapi.json`; only staff quote at `packages/router.py:95` | Code, later: Phase 11 self-service. Now: add to Not built |
| 9 | CONTRACT | served ids `listPortalClientPackages` etc. vs yaml `portalList...` | Yaml: rename the four operationIds to the served names (`camel_id` generates them) |

### platform (16)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | OWNER | `clients/files.py:29`, `clients/activity.py:269-270`, `clients/households.py:369,435`, `reporting/service.py:360`, `imports/service.py:98`, `documents/service.py:626` | Known decision |
| 2 | DOCS | README:43; `backend/migrations/versions/0101_space_resources_scheduling.py:546` | Drop the FK from the waiting list |
| 3 | DOCS | README:56; `reporting/jobs.py:16` | Report bytes are purged |
| 4 | CODE | `platform/service.py:60-70` (currency), `:265-283` (archive); `platform/schemas.py:175` | High and medium; see defects table |
| 5 | DOCS | README:231; `config/app.yaml:50` | `auth.sessions` |
| 6 | DOCS | README:51 (nc) | Audit periods are under `audit.retention_days*` |
| 7 | DOCS | no `tenant_export_router.py` in `platform/` | Routes live in `privacy_router.py` |
| 8 | DOCS | `backend/app/core/settings.py:29` default false; absent from `config/*.yaml` | Say the default is implicit |
| 9 | DOCS | `platform/events.py` (nc) | Add the file row and events; note `platform.identity_locked` is the notification name |
| 10 | DOCS | README:7-19 | Add `router.py`, `models.py`, `schemas.py` rows |
| 11 | DOCS | (nc) | Move the allow-list write path and the cross-context helpers to the `service.py` row |
| 12 | DEAD | `platform/permissions.py:20-21,41` and `audit.export`, `support_access.grant`: registration only | Keep all five (in the matrix; audit export fits Phase 12); Q4 for impersonate, transfer, close |
| 13 | DOCS | (nc) | Add the undocumented routes |
| 14 | DOCS | (nc) | Add `open_failed_jobs`, the imports dead-letter and purge callers |
| 15 | DOCS | no drift shown | No change |
| 16 | DOCS | no drift shown, not traced here either | No change; a reviewer pass on S-07 is still owed |

### pos (9)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | `backend/app/scheduler.py:26` | Drop the low-stock digest from not built |
| 2 | DOCS | README:91; `pos/router.py:370` | Drop quick-create from not built |
| 3 | OWNER | `pos/router.py:502-525` use `pos.sale.read`; `reporting/registry.py:596` uses `reporting.pos.run` | New, Q1 |
| 4 | DOCS | README:74; no `client.discount_pct` use in `pos/` | "Field exists; the register does not apply it" |
| 5 | DOCS | README:45; `imports/kinds.py:363` | Remove "nothing outside pos calls it" |
| 6 | DOCS | (nc) | Add file rows |
| 7 | DOCS | (nc) | Add the five events |
| 8 | DOCS | (nc) | Add merge and erasure handlers |
| 9 | DOCS | README:24 (nc) | Add `draft-sale-exists` |

### programs (8)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | CODE | `programs/selfservice.py:23`; `programs/router.py:101-107`; `engagement/permissions.py:21,25` | Low; see defects table |
| 2 | CONTRACT | `exportProgramGroup` and `generateProgramGroupChildren` are now served (`programs/router.py:543,552`); `publishProgramGroupAsCompetition` (yaml `:1794`) is not | Two of three resolved. Keep the third in the yaml and add it to README Not built (code when league publishing is scheduled) |
| 3 | DOCS | `programs/service.py` package credit calls (nc) | Add the PKG-12 paragraph |
| 4 | DOCS | `programs/handlers.py:9,15` | Add the two subscriptions |
| 5 | DOCS | `programs/events.py` (nc) | Add events and file rows |
| 6 | DOCS | `programs/service.py:35,443` | Add the 60-minute cut-off |
| 7 | DEAD | `form.manage`, `form_response.read` now used; `programs/permissions.py:27` `roster_link.send` still has no user | Keep (REG-26 captain rosters, README Not built) |
| 8 | DEAD | `programs/models.py:146` `video_join`, no producer | Keep (CLS-08 / INT-09 Zoom, Phases 11 and 15) |

### rentals (9)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:13 "32 operations"; router has 44 routes | Recount, or drop the number |
| 2 | DOCS | README:119; `web/src/features/portal/BookingsPage.tsx`, `RentalPlansPage.tsx` | Portal booking and plan screens exist |
| 3 | DOCS | README:120; `billing/router.py:200` | Reason is stale; the picker is still missing |
| 4 | DOCS | README:117 | Same: billing has payment refunds |
| 5 | DOCS | README:69; `rentals/schemas.py:434` docstring | Fix both |
| 6 | DOCS | `rentals/events.py` (nc) | Add events |
| 7 | DOCS | `rentals/subject.py` (nc) | Add the file row |
| 8 | RESOLVED | `rental_plan.share`, `.remove`, `locker_rental.manage`, `public_listing.publish` all have users now | None |
| 9 | CODE | `rentals/service.py:1299-1303` | Medium; see defects table. The README line about module 5 is gone |

### reporting (5)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | CONTRACT | yaml `getManagementDashboard`; not served; `reporting/permissions.py:15` unused | Code, later: RPT-02 is Phase 12. Now: add to README Not built; keep the key |
| 2 | DOCS | `reporting/service.py:27`; registry now also has client and league specs (`reporting/registry.py:595-598`) | "Any family key that has a registered report"; program, payroll, marketing have none yet |
| 3 | DOCS | `reporting/events.py` (nc) | Add the event |
| 4 | DOCS | (nc) | List the registered reports (now more than ten) |
| 5 | DOCS | README:13 | Say other contexts' migrations add `rpt_*` views |

### resources (8)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:37-38 still says staff does not exist; `staff/service.py:153-162` creates or adopts | Describe both roads as intended: `POST /resources` then adopt, or `create_payee`. Not a defect: the staff road passes the caller's principal through `create_resource`, so the resources gate holds |
| 2 | DOCS | `resources/service.py` `trainer_group` | Add to the interface; say staff calls it |
| 3 | DOCS | `resources/service.py:173`; README:20 | Add `virtual_room` |
| 4 | DOCS | README:47 still lists RES-06 as not built; `leagues/README.md:102` says venues are built | Reword |
| 5 | RESOLVED | locker and padlock keys have users (refs 2 each); tables and routes exist | None |
| 6 | RESOLVED | README:11 now says "14 ... plus 14 locker and padlock operations" | None |
| 7 | DOCS | README:43 | "Pause the offer", matching scheduling |
| 8 | DOCS | `web/src/features/resources/` | Add a screens pointer |

### scheduling (9)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:15; router has 40 routes | Recount, or drop the numbers |
| 2 | CONTRACT | `scheduling/router.py:244,315,321`; yaml `docs/api/openapi-core.yaml:2736` has `get` only, no `/slots` path | Yaml: add `updateBookingSeriesRule`, `listSlotOfferSlots`, `bookSlotOfferSlot`. All three are gated (`UPDATE_SERIES`, `Read`, `CREATE`) |
| 3 | CONTRACT | eight yaml operations unserved (direct links, public schedule and its settings, merge series) | Code, later: SCH-16, SCH-20 (Phase 15), SCH-21. Now: map operationIds in Not built, add the two settings ops; keep `scheduling.public_schedule.manage` |
| 4 | DOCS | `scheduling/events.py:20-81` (nc) | List the events |
| 5 | DOCS | (nc) | Complete the interface block |
| 6 | DOCS | README:7-16 | Add `subject.py`, `events.py`, `permissions.py` rows |
| 7 | DOCS | `scheduling/permissions.py:41` | Name `reservation_type.grant` |
| 8 | DOCS | `scheduling/schemas.py:17` (nc) | "Step enforced by the API schema" |
| 9 | DOCS | README:47-100 numbering 1-11, 15-18, 12-14 | Renumber |

### staff (10)

| # | Bucket | Evidence | Fix |
|---|---|---|---|
| 1 | DOCS | README:9 | "The twelve tables of section 4" |
| 2 | DOCS | README:36 | Three sections; bonuses ride on sessions |
| 3 | DOCS | `staff/events.py` | Add three events |
| 4 | DOCS | README:35 (nc) | Say a finalized run can be voided |
| 5 | DOCS | `staff/router.py:22,249-251`; `staff/service.py:746-752` filters by the caller's own `staff_user_id` | Document both routes. The key-less gate is the matrix's implicit self rule, not a defect |
| 6 | DOCS | (nc) | Add the clock-in preconditions and codes |
| 7 | DOCS | `staff/service.py:1313-1314,1375-1377` | Add the condition. Not a defect: both bonus kinds are computed from trained minutes, which need a rate or rule to exist |
| 8 | DOCS | (nc) | Add `session-needs-resource` |
| 9 | DOCS | README:68 | Move the two lines under the payee bullet |
| 10 | DOCS | README:98 (nc) | Complete the cross-context list |

## Proposed work packages

Modules are disjoint for code; the docs batch runs last so it does not collide with README lines the code
packages touch.

1. **Platform guards** (`platform`, one hook registration in `scheduling/__init__.py`): platform-4a, 4b. Risk reviewer.
2. **Rentals gates** (`rentals`): documents-1 after Q2, rentals-9.
3. **Programs and engagement keys and route** (`programs`, `engagement`, `rbac-matrix.md`): programs-1, engagement-4.
4. **Billing reads and caps** (`billing`, `integrations`): billing-11, integrations-7.
5. **Contract yaml sync** (`docs/api/*.yaml`, `access/permissions.py`): imports-1, imports-2, integrations-2,
   scheduling-2, packages-9, access-4 (add op), access-3 (delete key and op). No route code changes.
6. **Docs batch** (19 READMEs, one commit per module, mechanical agent): the 142 DOCS rows, the "add to Not
   built" halves of the CONTRACT and DEAD rows, and four stale code comments (`documents/service.py:1259`,
   `integrations/jobs.py:21`, `memberships/models.py:3-5`, `rentals/schemas.py:434`).
