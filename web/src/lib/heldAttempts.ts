/** Money attempts whose outcome is unknown, held in memory (never browser storage) so a reopened form resumes the
 * same Idempotency-Key and request (features/billing/attempt.tsx). Bound to the signed-in identity: the auth
 * provider calls clearHeldAttempts on an explicit sign-out and whenever a different identity signs in, so on a shared
 * desk browser the next person never inherits another's held form. A lapsed session (401) keeps the store bound to
 * its owner: the same person signing back in still has the key of an attempt whose outcome is unknown. */
type Held = { key: string; values?: unknown }

let owner: string | null = null
const held = new Map<string, Held>()

/** Forget every held attempt and bind the store to `identityId` (null: nobody signed in). */
export function clearHeldAttempts(identityId: string | null = null) {
  held.clear()
  owner = identityId
}

/** Who the store is bound to now; the auth provider clears it when that differs from the session's identity. */
export const heldOwner = () => owner

const slot = (scope: string, by: string | null) => `${by ?? 'nobody'}:${scope}`
export const getHeld = (scope: string) => held.get(slot(scope, owner))
/** Writes carry the owner captured when the form mounted: an answer that lands after someone else signed in is
 * dropped, never written into the new person's slot. */
export function setHeld(scope: string, value: Held, by: string | null) {
  if (by === owner) held.set(slot(scope, by), value)
}
export function dropHeld(scope: string, by: string | null) {
  if (by === owner) held.delete(slot(scope, by))
}
