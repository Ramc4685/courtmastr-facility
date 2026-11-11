import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { ApiError } from '../api/client'
import { ErrorState, LoadingState } from '../components/States'
import { LocationProvider, useAuth } from '../lib/auth'

/** Staff shell: signed out goes to sign-in (remembering where), clients go to the portal. */
export function RequireStaff({ children }: { children: ReactNode }) {
  const { me, isLoading, error } = useAuth()
  const location = useLocation()
  if (isLoading) return <LoadingState label="Restoring your session" />
  if (error) return <ErrorState error={error} onRetry={() => window.location.reload()} />
  if (!me) return <Navigate to={`/sign-in?next=${encodeURIComponent(location.pathname + location.search)}`} replace />
  if (me.principal.kind !== 'staff') return <Navigate to="/portal" replace />
  return <LocationProvider>{children}</LocationProvider>
}

export function RequireClient({ children }: { children: ReactNode }) {
  const { me, isLoading } = useAuth()
  if (isLoading) return <LoadingState label="Restoring your session" />
  if (!me) return <Navigate to="/sign-in?as=member" replace />
  if (me.principal.kind === 'staff') return <Navigate to="/" replace />
  return <>{children}</>
}

/** Pages the role cannot open render the same 403 explanation the API would produce. */
export function RequirePermission({ permission, children }: { permission: string | string[]; children: ReactNode }) {
  const { can } = useAuth()
  if (![permission].flat().some(can)) return <ErrorState error={new ApiError({ status: 403, code: 'permission-denied' })} />
  return <>{children}</>
}
