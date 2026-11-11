# programs (L3): session slice only

Shipped with build module 2 so capacity sessions work end to end: enrolment of a client into a single
session, roster, attendance marks and the session waitlist. Build module 6 completes the context (groups,
fees, packages, checkout, forms, portal). Tables follow `docs/architecture/data-model-programs.md` 1.9 to
1.11 with the session-target columns only; nothing is renamed later, columns are added.

| File | What |
|---|---|
| `models.py` | `enrollment`, `attendance`, `waitlist_entry` (session target) |
| `service.py` | enrol, cancel, roster, attendance, waitlist, `promote_waitlist` |
| `handlers.py` | `scheduling.session.capacity_changed` (promote), `scheduling.session.cancelled` (close) |
| `router.py` | 10 operations of `openapi-programs.yaml` |

## Rules

- The seat is taken by `scheduling.reserve_seat` under the session row lock, then the roster row is
  inserted, one transaction. Full is `409 capacity-full`; a second enrolment is `409 already-enrolled`.
- Cancelling an enrolment releases the seat and promotes the head of the queue in the same transaction.
  Raising capacity promotes through the event handler. FIFO by `queued_at, id`. Only `auto_promote`
  entries move by themselves, and not within 60 minutes of the start; staff can promote any entry by hand.
- Permission keys are the `scheduling.enrollment.*`, `scheduling.attendance.*` and
  `scheduling.waitlist.manage` rows of rbac-matrix 6.3, with `own` reach judged by scheduling.

## Assumptions and limits

- **Only `pricing = free` exists.** Packages (module 5) and fees (module 6) are not built, so a session that
  does not allow free booking can be enrolled into only by a holder of `scheduling.enrollment.free_book`.
- Reads (roster, enrolment list) are gated by `scheduling.booking.read`, not `programs.registration.read`,
  which is registered with module 6.
- `ck_enrollment_target` and `ck_waitlist_entry_target` allow the session target only; module 6 replaces
  both checks when it adds the group and form columns.
- The promotion email is sent through the notification port with no consent gate (transactional).

## Not built

Multi-enrolment (CLS-02), roster email (CLS-03), open-offer waitlist mode and claims (CLS-06), portal and
mobile self-booking (CLS-09), virtual meeting links (CLS-08), everything about groups (CLS-10, REG).

## Changed at integration

- **A package can pay for a place.** `POST /enrollments` takes `client_package_id`; `pricing` becomes
  `entitlement` and one credit is held through `packages.service.reserve_credit` (source type `enrollment`).
  The package must be of the session's reservation type, in date on the session's day at its location, and
  owned by or shared with the client: otherwise 409 with the packages code.
- **The credit follows the mark.** Attended consumes it; a no-show consumes or returns it per the package
  settings; excused returns it. A corrected mark undoes the previous outcome first, so marks can change.
- **Cancelling returns the credit**, or keeps it on a `late` cancel when the package settings say so.
- **Merge and erasure** are handled in `subject.py`: a duplicate place in the same session is cancelled as
  `client_merged`.
- Not built: choosing a package when promoting from the waitlist (promotion is free), and a `pricing: fee`.
