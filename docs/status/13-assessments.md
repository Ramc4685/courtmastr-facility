# Module 13: fitness assessments (context `assessments`)

Branch `claude/hungry-mcnulty-ecbb83` (lane w2c), migration `0952_assessments_core`. Module README:
`backend/app/modules/assessments/README.md`. Tests: `backend/app/modules/assessments/tests/`
(`test_assessments.py` 6, `test_progress.py` 3), the generated isolation, RLS, portal-schema and security
suites, `web/src/features/assessments/assessments.test.tsx` and `web/e2e/staff-assessments.spec.ts`.

Counts: P0 3 done. P1 1 done, 1 partial.

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| FIT-01 Assessment categories and fields | P0 | done | `/assessment-templates` (list, create, patch), `/assessment-templates/{id}/fields`, `/assessment-fields/{id}`; web `/assessments/setup` | `test_categories_and_fields_are_tenant_wide_definitions`; vitest create category | Numeric fields with decimal places, unit and better direction; archive and restore, never delete. |
| FIT-02 Record values on a client | P0 | done | `/assessment-results` (list, create, get, patch, delete); web client profile Assessments tab | `test_recording_rounds_values_and_keeps_them_out_of_the_audit_trail`, `test_coach_reaches_only_their_own_clients_and_cannot_delete`; vitest record; e2e scan | Half-up rounding to the field; values are flag-only in audit. The scoring hook is the `assessments.result.recorded` event (ids only); no scorer subscribes yet. |
| FIT-03 History and per-client report | P0 | done | `GET /assessment-series` (per field: points, first, latest, change, best); web progress table | `test_history_summarises_each_field_newest_first`, `test_progress.py` | Trend chart on the client tab (`TrendChart.tsx`); report `assessment_history` exports CSV, XLSX and PDF. Report `assessment_history`; trend chart on the client tab. Report: `docs/status/15-reporting.md` (phase 12). |
| FIT-04 Assessment summary report | P1 | partial | none | none | `summary_max_age_days_default` is stored for it. Report `assessment_summary`; no maximum-age option yet. Report: `docs/status/15-reporting.md` (phase 12). |
| FIT-05 Client-facing progress sharing | P1 | done | `/portal/assessment-results`, `/portal/assessment-bests`, `/portal/progress-share-links` (create, list, revoke), `POST /public/progress-shares/lookup`, `PATCH /assessment-settings`; web portal Progress page and public `/progress` page | `test_portal_shows_visible_fields_and_bests_only_when_sharing_is_on`, `test_fit_05_share_link_is_revocable_and_expires`; `booking.test.tsx`, `e2e/portal-booking.spec.ts` | Behind a tenant toggle, client-visible fields only. Share links are fragment tokens (hash stored), 1 to 90 days, revocable. Not wired into the mobile app. Phase 11 B. |
