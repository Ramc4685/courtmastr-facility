# engagement (consent slice)

Only the part of the engagement context that module 4 needs: communication preferences and consent history.

- `communication_preference`: one row per client and topic. Marketing topics default to off.
- `consent_event`: append-only history. Two tenant-scoped SECURITY DEFINER functions alter it:
  `app.repoint_consent_event` (merge) and `app.erase_consent_event` (erasure; note becomes `[erased]`).
- Staff and portal `GET`/`PUT` preferences. Opting an email topic in needs a verified address; a staff change
  needs a basis and a note.
- `service.is_subscribed(session, client_id, topic)` for senders. Merge and erase handlers are registered.

Topics follow the data model, not the YAML enum. Not built: campaigns, the public signed-link preference
centre and one-click unsubscribe.
