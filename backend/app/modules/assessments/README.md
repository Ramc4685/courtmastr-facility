# assessments

Build module 13 (parity rows FIT). Assessment categories (`assessment_template`) hold numeric fields; staff
record a result for a client with one value per field; history is a per-field series; clients see their own
client-visible fields and personal bests on the portal when sharing is on.

## Flow

1. An admin creates a category and its fields (`createAssessmentTemplate`, `createAssessmentField`): decimal
   places (0 to 6), unit, better direction (higher, lower, none), client-visible. Archive with `is_active:
   false`; archived names are free again, and history keeps the archived field.
2. Staff record a result (`createAssessmentResult`): client, location, time, note, values. Each value names
   an active field of an active category, once, and is rounded half-up to the field's decimal places on write.
   `assessments.result.recorded` is published with ids only.
3. History: `listAssessmentResults` (entries, newest first, keyset pages) and `getAssessmentSeries` (per field:
   points newest first, latest, first, change, best by direction). Filters: field ids, category, time window.
4. Portal: `listPortalAssessmentResults` and `listPortalAssessmentBests` answer for the acted-for client
   (`client_id`, default the identity's own record) with portal-only schemas: client-visible fields only,
   never the staff note or who recorded the entry.

## Interfaces

- Staff routes under `/assessment-*`; portal routes `/portal/assessment-results`, `/portal/assessment-bests`.
- Permissions (rbac-matrix 6.16): `assessment.read` and `assessment.record` are `C` keys with own reach for
  coaches (their own clients: default trainer or salesperson); `assessment.delete` is `L` on the entry's
  location; `definition.manage` is `T` (needs every location, as all tenant-wide writes do).
- Recording a result loads the client through `clients.service.load` before checking it is active, so a client
  outside the caller's reach (or unknown) is 404, never a 422 that confirms it exists (W2-09).
- Merge moves every entry to the survivor; erasure deletes the client's entries (`subject.py`).
- `clients.households.CAPABILITIES["assessments"]`: who may view a household member's results on the portal
  (the same edit authorities as documents and invoices).

## Assumptions (written down, not guessed)

- Values are health data (rbac flag `H`): the value column is `audit: flag`, so audit rows record that values
  changed and how many, never the numbers. Events carry ids only.
- A result needs a location (the spec allows null). It anchors the `L` delete key, so a location-scoped admin
  deletes only entries taken at their sites.
- Editing a result's time moves its stored values with it, even values on a since-archived field. Replacing
  values re-checks every field.
- Changing a field's decimal places applies to new values; stored values keep their rounding.
- Portal sharing is off until an admin turns it on (`assessment_settings.is_portal_sharing_enabled`); while
  off the portal routes answer 404. A result with no client-visible value is left out of the portal list.
- Personal best of a field with direction `none` is null. The best's date is the newest point with that value.
- Erasure deletes entries rather than anonymising them: there is no retention duty for fitness measurements.
- Path ids are named after their table (`assessment_template_id`) instead of the spec's `template_id`, and
  portal reads are `listPortal*` (kernel naming rule for GET).

## Not built

- The cohort summary report (FIT-04, P1) and its `summary_max_age_days_default` input (the column exists).
- Emailing a result to the client (`shareAssessmentResult`, FIT-05 P1); mobile screens.
- PDF or CSV export of a client's history (FIT-03 names it; the series is in the API and on screen).
- A scoring hook for later automated scoring (FIT-02 mentions one; nothing calls it yet).
