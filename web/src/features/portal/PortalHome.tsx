import { Button } from '../../components/Button'
import { EmptyState } from '../../components/States'
import { useAuth } from '../../lib/auth'
import { AuthLayout } from '../auth/AuthLayout'

/** The member portal arrives with module 13; signed-in clients land here until then. */
export function PortalHome() {
  const { signOut } = useAuth()
  return (
    <AuthLayout title="Member portal">
      <EmptyState title="The member portal is coming soon" action={<Button variant="secondary" onClick={() => void signOut()}>Sign out</Button>}>
        Bookings, memberships and payments will appear here.
      </EmptyState>
    </AuthLayout>
  )
}
