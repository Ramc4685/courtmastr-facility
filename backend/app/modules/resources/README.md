# resources (L1)

Bookable things: schedule groups, the resource tree (venue, sub-venue, trainer, virtual room), standing
links between resources, and availability windows. Schema of record: `docs/architecture/data-model-core.md`
section 3. Calls `platform` only.

| File | What |
|---|---|
| `models.py` | `resource_group`, `resource`, `resource_link`, `availability_window`; lockers: `locker_room`, `locker`, `locker_term`, `padlock` (Phase 14 C1) |
| `service.py` | staff commands (both gates, audit, events) and the internal interface that scheduling and staff use: `get_many`, `in_location`, `descendants`, `ancestors`, `linked_ids`, `windows_for`, `get_window`, `trainer_group`, `HOOKS`. `trainer_group` creates the "Trainers" group when a location has none; staff calls it when it creates a trainer payee |
| `router.py` | 14 operations of `openapi-core.yaml` tag `resources`, plus 14 locker and padlock operations |
| `web/src/features/resources/` | staff screen `ResourcesPage.tsx`, with `queries.ts` and a test |

## Rules worth knowing

- The tree is at most 3 levels deep (`MAX_DEPTH`), venues only, one location. Cycles are refused.
- Hold rows belong to scheduling, which this layer may not import. A tree edit or an archive therefore runs
  the callables in `service.HOOKS` in the same transaction: scheduling registers the hold back-fill
  (`tree_changed`) and the future-bookings guard (`archiving`). `resources.resource.tree_changed` is still
  published for other consumers.
- A sub-venue and a virtual room default to `counts_toward_plan = false` (a split court is one metered resource).
- **Lockers (RES-07, RES-08).** Rooms hold numbered lockers created in bulk (`from_number..to_number`, at most
  500 at a time; numbers already in the room are skipped and counted). Leases live in rentals, an upper layer,
  so `listLockers` merges the lease state through `HOOKS["locker_states"]` and taking a rented locker out of
  service runs `HOOKS["locker_retiring"]` (rentals refuses with `locker-leased`). Terms are named, priced date
  ranges at a location.
- **Padlocks (RES-09).** The combination is encrypted with `core.crypto.encrypt` (per-tenant key), never
  returned by a list or a read, and revealed only by `POST /padlocks/{id}/reveal` under
  `resources.padlock.reveal_combination` (front desk has it). Every reveal and every change writes an audit
  event that records that it happened, never the value. A padlock must sit at its locker's location. Delete is
  soft: the padlock leaves its locker, and the number becomes free again.

## Assumptions and deviations

- The data model asks for three-column same-location foreign keys (`tenant_id, location_id, parent_id`). The
  RLS meta-test requires every tenant FK to be exactly `(tenant_id, id)`, so same-location is a service rule.
- Trainer rows are created two ways. `POST /resources` (`kind: trainer`, optional `staff_user_id`, which sets
  `staff_user.linked_resource_id`) makes one directly. Staff's `create_payee` creates the column through
  `create_resource` and publishes `staff.trainer.created` afterwards, so both roads exist.
- Names sort by `sort_order, name` with the database default collation, not ICU numeric ("Court 10" sorts
  before "Court 9" unless `sort_order` is set).
- A coach holds `resources.availability.manage` with `own` reach: only the windows of their linked resource.
- A window can be offered as bookable slots (scheduling `slot_offer`, SCH-07). Deleting the window drops its
  offer, unless a slot was already taken; then the delete is refused and the offer should be paused instead
  (scheduling's rule).

## Not built

Plan-limit metering of `counts_toward_plan` (PLT-14); a league venue list separate from these resources (RES-06;
leagues already books games onto them). Lockers:
no `lockers` plan-entitlement gate (the feature key is not in `platform.entitlements.FEATURES`; Phase 8 owns
it), no hard purge of deleted padlocks, no locker map view (the board is a table).
