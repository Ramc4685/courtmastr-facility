/** Money attempts whose outcome is unknown, held in memory (never browser storage) so a reopened form resumes the
 * same Idempotency-Key and request (features/billing/attempt.tsx). Bound to the signed-in identity: the auth
 * provider calls clearHeldAttempts on sign-in, sign-out and any change of who is signed in, so on a shared desk
 * browser the next person never inherits another's held form. */
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

const slot = (scope: string) => `${owner ?? 'nobody'}:${scope}`
export const getHeld = (scope: string) => held.get(slot(scope))
export const setHeld = (scope: string, value: Held) => void held.set(slot(scope), value)
export const dropHeld = (scope: string) => void held.delete(slot(scope))
