import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, ApiError, setCsrfToken, setUnauthenticatedHandler, type Schemas } from '../api/client'
import { clearHeldAttempts, heldOwner } from './heldAttempts'

export type Me = Schemas['Me']
type Challenge = Schemas['MfaChallengeOut']
const SESSION_KEY = ['session'] as const
// Drop every cached tenant query except the session itself (qc.clear() would detach the session observer).
const notSession = { predicate: (q: { queryKey: readonly unknown[] }) => q.queryKey[0] !== SESSION_KEY[0] }

/** Session restore: the CSRF token comes from GET /auth/session; a 401 there means no session. */
async function restore(): Promise<Me | null> {
  try {
    const session = await api.get('/api/v1/auth/session')
    setCsrfToken(session.csrf_token)
    return await api.get('/api/v1/me')
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null
    throw e
  }
}

type AuthValue = {
  me: Me | null | undefined
  isLoading: boolean
  error: unknown
  /** Resolves null once signed in, or with the pending MFA challenge when a second step is due. */
  signIn: (email: string, password: string, audience?: 'staff' | 'client') => Promise<Challenge | null>
  sessionStarted: (csrf: string | null | undefined) => Promise<void>
  signOut: () => Promise<void>
  can: (key: string) => boolean
}

const AuthContext = createContext<AuthValue | null>(null)
const SESSION_COMMIT_TIMEOUT_MS = 2000

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const session = useQuery({ queryKey: SESSION_KEY, queryFn: restore, staleTime: Infinity, retry: false })

  // React Query tells observers about setQueryData on a later tick. Callers navigate as soon as sessionStarted
  // resolves, so it waits for this provider to commit the new session; otherwise the route guard still sees no
  // session and bounces the user through /sign-in.
  const rendered = useRef<Me | null | undefined>(undefined)
  const waiters = useRef<(() => void)[]>([])
  const release = useCallback(() => {
    for (const resolve of waiters.current.splice(0)) resolve()
  }, [])
  useEffect(() => {
    rendered.current = session.data
    release()
  }, [session.data, release])
  useEffect(() => release, [release]) // unmount: nothing will render again

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      setCsrfToken(null) // held attempts stay with their owner: the same person signing back in may still need them
      qc.setQueryData(SESSION_KEY, null)
      // Back to the value already rendered (null) in the same tick: no re-render comes, so release by hand.
      release()
    })
  }, [qc, release])

  const sessionStarted = useCallback(
    async (csrf: string | null | undefined) => {
      setCsrfToken(csrf)
      qc.removeQueries(notSession)
      const next = await api.get('/api/v1/me')
      // a different person never resumes someone else's held payment form; the same person keeps theirs
      if (heldOwner() !== next.principal.identity_id) clearHeldAttempts(next.principal.identity_id)
      await new Promise<void>((resolve) => {
        qc.setQueryData(SESSION_KEY, next)
        // Structural sharing keeps the old object when nothing changed, and then no re-render is coming.
        if (qc.getQueryData(SESSION_KEY) === rendered.current) return resolve()
        waiters.current.push(resolve)
        // Safety net: never leave the caller (a disabled sign-in button) waiting on a render that is not coming.
        setTimeout(resolve, SESSION_COMMIT_TIMEOUT_MS)
      })
    },
    [qc],
  )

  const signIn = useCallback(
    async (email: string, password: string, audience: 'staff' | 'client' = 'staff') => {
      const out = await api.post('/api/v1/auth/sign-in', { body: { email, password, audience, client_kind: 'web' } })
      if ('mfa_token' in out) return out
      await sessionStarted(out.csrf_token)
      return null
    },
    [sessionStarted],
  )

  const signOut = useCallback(async () => {
    try {
      await api.post('/api/v1/auth/sign-out')
    } finally {
      setCsrfToken(null)
      clearHeldAttempts()
      qc.setQueryData(SESSION_KEY, null)
      qc.removeQueries(notSession)
      release()
    }
  }, [qc, release])

  const me = session.data
  // A restored or changed session (another tab signed someone else in): held attempts belong to their identity. No
  // session (a lapsed one, or still loading) leaves them bound to their owner.
  const identity = me?.principal.identity_id ?? null
  if (identity !== null && heldOwner() !== identity) clearHeldAttempts(identity)
  const keys = useMemo(() => new Set((me?.permissions ?? []).map((p) => p.key)), [me])
  const can = useCallback((key: string) => keys.has(key), [keys])

  const value: AuthValue = { me, isLoading: session.isPending, error: session.error, signIn, sessionStarted, signOut, can }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}

/** The signed-in staff principal; only call below the staff route guard. */
export function useMe(): Me {
  const { me } = useAuth()
  if (!me) throw new Error('useMe without a session')
  return me
}

const LOCATION_STORE = 'fh.location'
type LocationValue = { locationId: string | null; setLocationId: (id: string | null) => void }
const LocationContext = createContext<LocationValue>({ locationId: null, setLocationId: () => {} })

/** The location the staff member is working at. Remembered per browser (a convenience, not state). */
export function LocationProvider({ children }: { children: ReactNode }) {
  const me = useMe()
  const allowed = me.locations ?? []
  const [stored, setStored] = useState<string | null>(() => {
    try {
      return localStorage.getItem(LOCATION_STORE)
    } catch {
      return null
    }
  })
  const valid = stored && allowed.some((l) => l.id === stored) ? stored : null
  const locationId = valid ?? (me.has_all_location_access ? null : (me.primary_location_id ?? allowed[0]?.id ?? null))
  const setLocationId = useCallback((id: string | null) => {
    setStored(id)
    try {
      if (id) localStorage.setItem(LOCATION_STORE, id)
      else localStorage.removeItem(LOCATION_STORE)
    } catch {
      /* storage blocked: the choice lasts for this page only */
    }
  }, [])
  return <LocationContext.Provider value={{ locationId, setLocationId }}>{children}</LocationContext.Provider>
}

export const useCurrentLocation = () => useContext(LocationContext)
