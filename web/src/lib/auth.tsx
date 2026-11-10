import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, setCsrfToken, setUnauthenticatedHandler, type Schemas } from '../api/client'

export type Me = Schemas['Me']
const SESSION_KEY = ['session'] as const
// Drop every cached tenant query except the session itself (qc.clear() would detach the session observer).
const notSession = { predicate: (q: { queryKey: readonly unknown[] }) => q.queryKey[0] !== SESSION_KEY[0] }

/** Session restore: the CSRF token comes from GET /auth/session (refreshing once if the access cookie lapsed). */
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
  signIn: (email: string, password: string) => Promise<void>
  sessionStarted: (csrf: string | null | undefined) => Promise<void>
  signOut: () => Promise<void>
  can: (key: string) => boolean
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const session = useQuery({ queryKey: SESSION_KEY, queryFn: restore, staleTime: Infinity, retry: false })

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      setCsrfToken(null)
      qc.setQueryData(SESSION_KEY, null)
    })
  }, [qc])

  const sessionStarted = useCallback(
    async (csrf: string | null | undefined) => {
      setCsrfToken(csrf)
      qc.removeQueries(notSession)
      qc.setQueryData(SESSION_KEY, await api.get('/api/v1/me'))
    },
    [qc],
  )

  const signIn = useCallback(
    async (email: string, password: string) => {
      const out = await api.post('/api/v1/auth/sign-in', { body: { email, password, audience: 'staff', client_kind: 'web' } })
      await sessionStarted(out.csrf_token)
    },
    [sessionStarted],
  )

  const signOut = useCallback(async () => {
    try {
      await api.post('/api/v1/auth/sign-out')
    } finally {
      setCsrfToken(null)
      qc.setQueryData(SESSION_KEY, null)
      qc.removeQueries(notSession)
    }
  }, [qc])

  const me = session.data
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
