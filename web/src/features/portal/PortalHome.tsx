import { Button } from '../../components/Button'
import { useAuth } from '../../lib/auth'
import { PortalProgress } from '../assessments/PortalProgress'
import { AuthLayout } from '../auth/AuthLayout'

/** Signed-in clients land here. Bookings, memberships and payments arrive with the portal slice; the member's
 * own assessment progress shows when the club shares it (module 13). */
export function PortalHome() {
  const { signOut } = useAuth()
  return (
    <AuthLayout title="Member portal">
      <div className="space-y-6">
        <PortalProgress />
        <p className="text-sm text-muted">Bookings, memberships and payments will appear here.</p>
        <Button variant="secondary" onClick={() => void signOut()}>Sign out</Button>
      </div>
    </AuthLayout>
  )
}
