# Public API guide

How a partner system talks to Courtmastr Facility: authenticate with an API key, page through lists, read
errors, retry safely, and receive webhooks. The machine-readable contract is the generated OpenAPI document
at `/api/v1/openapi.json` (interactive docs at `/api/v1/docs`); this guide covers what the schema cannot say.

## Authentication

An Owner or Admin creates a key under **Integrations → API keys**. The key is shown once, at creation and on
rotation; the server stores only its SHA-256 hash, so a lost key cannot be recovered, only rotated.

Send it as a bearer token on every request:

```
GET /api/v1/clients HTTP/1.1
Host: app.example.com
Authorization: Bearer fhk_<tenant>_<secret>
```

The tenant is encoded in the key, so no tenant header is needed. Keys never go in a URL or query string.

What a key may do is the intersection of:

- the **scopes** picked when it was created (permission keys such as `clients.client.read`);
- the **creator's own permissions**, re-checked on every request, so a key loses access the moment its
  creator does (role change, deactivation, expired access);
- the **locations** the key was limited to, intersected with the creator's locations.

Keys cannot carry administrative, identity, impersonation or permission-granting scopes. Scopes that move
money or change prices need an explicit confirmation at creation. Endpoints that act as a person (`/me`,
sign-in, password changes, creating other keys) refuse keys with `403 api-key-not-allowed`.

| Situation | Answer |
|---|---|
| Missing, unknown, revoked or expired key; creator deactivated | `401 unauthenticated` |
| Tenant suspended | `403 tenant-suspended` |
| Scope not on the key | `403 permission-denied` |
| Record outside the key's tenant or locations | `404 not-found` (never 403, so ids cannot be probed) |
| Over the per-key rate limit | `429 rate-limited` with `Retry-After` |

**Rotation.** Rotating returns a new secret and keeps the old one working for a grace period (24 hours by
default, `grace_minutes` 0 to 10080), so the partner can deploy the new key without downtime. When someone other than the key's owner rotates it,
the key becomes theirs and the old secret stops at once. **Revocation**
takes effect at once. `last_used_at` shows when a key was last seen (updated at most once a minute).

## Lists and pagination

Every list returns one page and an opaque cursor:

```json
{ "data": [ ... ], "page": { "next_cursor": "eyJ2Ijo...", "has_more": true } }
```

Ask for the next page with `?cursor=<next_cursor>`; stop when `has_more` is false. `limit` is 1 to 200
(default 50). Cursors are keyset positions, so pages stay stable while rows are added. Filters are flat query
parameters on allow-listed fields, with operators such as `status[in]=failed,abandoned`; `sort=-created_at`
sorts descending. Unknown filter or sort fields are a `422`, never silently ignored.

## Errors

Errors use `application/problem+json`:

```json
{
  "type": "about:blank", "title": "Validation failed", "status": 422, "code": "validation-failed",
  "detail": "...", "trace_id": "...",
  "errors": [ { "pointer": "/scopes/0", "code": "scope-not-grantable", "detail": "..." } ]
}
```

Branch on `status` and `code`, not on the English text. `errors[].pointer` is a JSON Pointer into the request
body. Quote `trace_id` when asking for support.

## Idempotency

Send `Idempotency-Key: <a fresh UUID>` on every `POST` that creates or moves something. A retry with the same
key and the same body within 24 hours returns the first response instead of acting twice; the same key with a
different body is `422 idempotency-key-reused`. Payment and refund endpoints require the header. Generate the
key once per logical operation and reuse it for that operation's retries.

## Webhooks

**Integrations → Webhooks** registers an HTTPS endpoint and the events it wants. The event picker offers only
events the creator may read for every location the event can come from; `["*"]` is expanded to the concrete
list at save time, so new event types are never delivered without someone opting in. If the creator later
loses the permission or is deactivated, the endpoint is disabled.

The URL must be HTTPS and must resolve only to public addresses. Private, loopback, link-local, metadata and
other reserved ranges are refused when the endpoint is saved, and again when each delivery is sent (the
connection is pinned to the address that was checked, which defeats DNS rebinding). Redirects are not followed.

### Delivery

Each delivery is one `POST` with a JSON body:

```json
{ "id": "<event id>", "type": "clients.client.created", "created_at": "2026-11-10T21:04:05+00:00",
  "data": { "client_id": "...", "location_id": "..." } }
```

| Header | Meaning |
|---|---|
| `FH-Event-Id` | The event id. Use it to drop duplicates: delivery is at least once. |
| `FH-Event-Type` | The event type, as in the body. |
| `FH-Delivery-Id` | This delivery. A replay re-sends the same delivery with the same event id. |
| `FH-Signature` | `t=<unix seconds>,v1=<hex HMAC-SHA256>`; two `v1` values during a secret rotation. |

Answer any `2xx` within 10 seconds; do the work afterwards. Anything else (or a timeout) is retried after
roughly 1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours, 12 hours and 24 hours (eight attempts in all, each
delay jittered by up to 10%). Then the delivery is marked failed. `410 Gone` disables the endpoint at once.
An endpoint is disabled automatically after 20 failed deliveries in a row or 5 days without a success; the
creator is emailed, and re-enabling it in the screen resets the count. Failed deliveries can be replayed from
the delivery log, which shows the status, attempts, last response and a preview with free text redacted.
**Test** sends a signed `integrations.webhook.tested` event synchronously and shows the result.

Payloads carry ids, amounts in minor units, dates and status codes, not names or free text: fetch the record
through the API with a key when you need more.

### Verifying the signature

Compute HMAC-SHA256 over `<t>.<raw body>` with the endpoint's signing secret, compare in constant time with
each `v1` value, and reject timestamps more than 5 minutes from now. Use the raw bytes as received; re-encoding
the JSON changes them.

```python
import hashlib, hmac, time

def verify(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = [p.split("=", 1) for p in header.split(",") if "=" in p]
    stamps = [v for k, v in parts if k == "t"]
    if len(stamps) != 1 or not stamps[0].isdigit() or abs(time.time() - int(stamps[0])) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{stamps[0]}.".encode() + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, v) for k, v in parts if k == "v1")

# Flask example
@app.post("/hooks/courtmastr")
def hook():
    if not verify(SIGNING_SECRET, request.headers.get("FH-Signature", ""), request.get_data()):
        abort(400)
    event = request.get_json()
    if seen_before(event["id"]):
        return "", 200
    queue_for_processing(event)
    return "", 200
```

**Rotating the signing secret** returns a new secret; for the next 24 hours every delivery is signed with both
the new and the previous one, so the consumer can switch without dropping events.
