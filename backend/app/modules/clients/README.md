# clients (kernel skeleton)

People. This is the thin slice that ships ahead of build module 4 (overview section 6 item 2) so bookings,
charges and payments have a real client to point at. Module 4 (the People lane) completes it.

| File | What it holds |
|---|---|
| `models.py` | `client` (skeleton columns of data-model-people 1.1) and `client_portal_access` (1.11, complete) |
| `service.py` | Staff queries and commands (`list_clients`, `get_client`, `create_client`) and the internal interface |
| `router.py` | `GET /clients`, `POST /clients`, `GET /clients/{client_id}` |
| `permissions.py` | All 16 keys of rbac-matrix 6.5, so seeded roles are already right |
| `events.py` | `clients.client.created` |

Internal interface for other contexts (no permission check; ADR 0009 section 9):
`get(session, client_id)`, `require_active(session, client_id, pointer=)`, `display_name(client)`,
`link_identity(session, client_id, identity_id)`, `client_ids_for_identity(session, identity_id)`.

Web: `web/src/features/clients/ClientPicker.tsx` (combobox; needs `clients.client.read`).

## Deferred to build module 4, by name

- The remaining `client` columns (preferred name, birth date, address, category, custom values, photo, the
  generated `search_text` and `phone_digits` with their trigram indexes, merge and erasure columns) and every
  other table of section 1 (`client_email`, relationships, notes, tasks, settings...). Add columns; rename none.
- `updateClient`, `disableClient`, `enableClient`, merge, export, member-number generation from
  `tenant_counter('member_number')` (the counter exists: `platform.service.next_number`).
- The `own` reach predicate (rbac-matrix 3.2). Until it exists a principal whose reach on
  `clients.client.read` is `own` (the Coach role) sees **no** clients: lists are empty and reads are 404.
- Portal invitation flow; `PrincipalOut.client_ids` is still empty (portal routers call
  `client_ids_for_identity`).
- `clients.client.updated`, `.disabled`, `.merged` events and the merge handlers in every referencing context.

## Assumptions

- `primary_email` is written directly by `create_client` for now. Module 4 introduces `client_email` and
  turns this column into the denormalised copy the data model describes, back-filling one row per client.
- A staff user limited to some locations may create clients only with a home location in their set, although
  reading clients is tenant-wide (CLI-19).
- One check constraint, `ck_client_member_number_source`, carries both the pair rule and the vocabulary: the
  data model gives both that name, and a table cannot hold two constraints with one name.
- Search is `ILIKE` over name, email, phone and member number: correct, but unindexed until the trigram
  indexes land with module 4.
